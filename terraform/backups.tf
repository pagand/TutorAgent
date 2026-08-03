# pg_dump target for scripts/backup.sh (BACKUP_S3_URI). force_destroy
# stays at its default false, so a `terraform destroy` refuses to delete
# this bucket while it holds dumps.
resource "aws_s3_bucket" "backups" {
  bucket = "aitutor-backups-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "aitutor-backups"
  }
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    id     = "expire-after-retention"
    status = "Enabled"

    filter {}

    expiration {
      days = var.backup_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.backup_retention_days
    }
  }
}
