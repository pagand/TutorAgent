data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "aitutor-instance-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Scoped to exactly the SSM parameters this instance needs: its own
# secrets plus the pre-existing GitHub deploy key. Not a wildcard on
# /aitutor/* or on SSM generally.
data "aws_iam_policy_document" "instance_inline" {
  statement {
    sid     = "ReadOwnSecrets"
    actions = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [
      "arn:aws:ssm:us-west-2:${data.aws_caller_identity.current.account_id}:parameter/aitutor/prod/*",
      "arn:aws:ssm:us-west-2:${data.aws_caller_identity.current.account_id}:parameter/github/deploy-key",
    ]
  }

  statement {
    sid       = "DecryptSsmSecureStrings"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:us-west-2:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }

  # Read-only on artifacts/ (prod/data delivery). Deliberately excludes
  # the ops bucket's terraform/ prefix, which holds state - the instance
  # role never touches it.
  statement {
    sid       = "ReadProdDataArtifacts"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${local.ops_bucket}/artifacts/*"]
  }

  # ListBucket takes a bucket-level resource and an s3:prefix condition,
  # not an object-level resource - it can't share a statement with
  # GetObject above. s3:prefix is only ever present on ListBucket calls,
  # so a shared statement would silently deny every GetObject (the
  # condition key is absent on GetObject requests, so StringLike never
  # matches and the statement grants nothing for it).
  statement {
    sid       = "ListProdDataArtifacts"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${local.ops_bucket}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["artifacts/*"]
    }
  }

  # Stage 5, F3: read-write, not write-only. Backups were previously
  # write-only on this bucket, so nothing on the box could pull a dump
  # back down - no restore path existed at all.
  statement {
    sid       = "ReadWriteBackups"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.backups.arn}/*"]
  }

  statement {
    sid       = "ListBackups"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn]
  }
}

resource "aws_iam_role_policy" "instance_inline" {
  name   = "aitutor-instance-inline"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance_inline.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "aitutor-instance-profile"
  role = aws_iam_role.instance.name
}

# Stage 5, D2: the scheduler role existed only to run the monthly
# start/stop EventBridge schedules for certbot renewal (guardrails.tf),
# both deleted along with certbot.
