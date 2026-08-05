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

  # Retention is deliberately infinite for current objects. This bucket now
  # holds only on-demand snapshots (the nightly cron was deleted 2026-08-04),
  # and a snapshot is the exam's research output: interaction, chat,
  # intervention and mastery data that exists nowhere else once the box is
  # gone. An expiry rule here would silently delete the one artifact the whole
  # system exists to produce.
  #
  # Noncurrent versions are still pruned. Snapshot keys are timestamped and so
  # never overwritten, meaning this only reclaims genuinely superseded writes.
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.backup_retention_days
    }
  }
}
