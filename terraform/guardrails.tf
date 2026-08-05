# Shared notification target for both CloudWatch alarms. AWS Budgets and
# Cost Anomaly Detection support email natively; CloudWatch alarms need
# an SNS topic. Confirming the email subscription is a manual one-time
# click after apply.
resource "aws_sns_topic" "alerts" {
  name = "aitutor-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "status_check_failed" {
  alarm_name          = "aitutor-status-check-failed"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  alarm_description   = "EC2 instance status check failed"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    InstanceId = aws_instance.app.id
  }
}

resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "aitutor-sustained-high-cpu"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 90
  alarm_description   = "Sustained CPU above 90% for 15 minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    InstanceId = aws_instance.app.id
  }
}

# The budget below filters on the Project tag, but a tag only carries cost
# data once it is activated as a cost allocation tag. It was not, so the
# budget reported $0.00 spend indefinitely no matter what the account was
# actually billed - a guardrail that could never fire. Activating it here
# keeps that from silently regressing. Note this is account-wide and applies
# going forward only; historical months need `aws ce
# start-cost-allocation-tag-backfill`, and new data takes up to 24h to appear.
resource "aws_ce_cost_allocation_tag" "project" {
  tag_key = "Project"
  status  = "Active"
}

resource "aws_budgets_budget" "monthly" {
  name         = "aitutor-monthly-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$AITutorApp"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

resource "aws_ce_anomaly_monitor" "aitutor" {
  name              = "aitutor-cost-anomaly"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "aitutor" {
  name      = "aitutor-cost-anomaly-alerts"
  frequency = "DAILY"

  monitor_arn_list = [aws_ce_anomaly_monitor.aitutor.arn]

  subscriber {
    type    = "EMAIL"
    address = var.alert_email
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = ["1"]
    }
  }
}

# Stage 5, D2: the monthly boot-for-cert-renewal schedules are gone along
# with certbot itself. Their only purpose was keeping a Let's Encrypt cert
# alive on a box that sits stopped between exams; TLS now terminates at
# CloudFront (D1), which needs no renewal on this side at all.
