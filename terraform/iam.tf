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

  # Read-only on artifacts/ (prod/data delivery), write-only on the
  # backup bucket. Deliberately excludes the ops bucket's terraform/
  # prefix, which holds state - the instance role never touches it.
  statement {
    sid     = "ReadProdDataArtifacts"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${local.ops_bucket}",
      "arn:aws:s3:::${local.ops_bucket}/artifacts/*",
    ]
  }

  statement {
    sid       = "WriteBackups"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.backups.arn}/*"]
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

# EventBridge Scheduler's own execution role, distinct from the instance
# role: it only needs to call ec2:StartInstances/StopInstances.
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "aitutor-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_inline" {
  statement {
    sid       = "StartStopInstance"
    actions   = ["ec2:StartInstances", "ec2:StopInstances"]
    resources = ["arn:aws:ec2:us-west-2:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.app.id}"]
  }
}

resource "aws_iam_role_policy" "scheduler_inline" {
  name   = "aitutor-scheduler-inline"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_inline.json
}
