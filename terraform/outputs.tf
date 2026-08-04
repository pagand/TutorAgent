output "dns_records_to_add" {
  description = "Records to add at the da-tu.ca registrar. api.air.da-tu.ca no longer exists (Stage 5, D1/D4) - the API is served from this same distribution at /api/*."
  value = {
    acm_validation_cname = {
      name  = tolist(aws_acm_certificate.frontend.domain_validation_options)[0].resource_record_name
      type  = tolist(aws_acm_certificate.frontend.domain_validation_options)[0].resource_record_type
      value = tolist(aws_acm_certificate.frontend.domain_validation_options)[0].resource_record_value
    }
    frontend_cname_record = {
      name  = var.domain_frontend
      type  = "CNAME"
      value = aws_cloudfront_distribution.frontend.domain_name
    }
  }
}

output "elastic_ip" {
  value = aws_eip.api.public_ip
}

output "instance_id" {
  value = aws_instance.app.id
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.frontend.id
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.frontend.domain_name
}

output "frontend_bucket_name" {
  value = aws_s3_bucket.frontend.bucket
}

output "backups_bucket_name" {
  value = aws_s3_bucket.backups.bucket
}

output "ops_bucket_name" {
  value = local.ops_bucket
}

output "sns_alerts_topic_arn" {
  description = "Confirm the email subscription (one-time click) after apply, or CloudWatch alarms fire silently"
  value       = aws_sns_topic.alerts.arn
}
