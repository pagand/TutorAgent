variable "aws_profile" {
  description = "AWS CLI/SSO profile to use for all Terraform operations"
  type        = string
  default     = "AdministratorAccess-434195712367"
}

variable "domain_frontend" {
  description = "Domain serving the Next.js static export via CloudFront"
  type        = string
  default     = "air.da-tu.ca"
}

variable "domain_api" {
  description = "Domain serving the backend API via the Elastic IP"
  type        = string
  default     = "api.air.da-tu.ca"
}

variable "repo_ref" {
  description = "Git ref the EC2 bootstrap clones/pulls on every boot"
  type        = string
  default     = "main"
}

variable "repo_url" {
  description = "SSH clone URL for the AITutorApp repo, reachable via the SSM-stored deploy key"
  type        = string
  default     = "git@github.com:pagand/TutorAgent.git"
}

variable "instance_type" {
  description = "EC2 instance type for the backend box"
  type        = string
  default     = "t3.medium"
}

variable "root_volume_gb" {
  description = "Root EBS gp3 volume size in GB. Estimated real steady-state is ~9.2GB (see plan); this is estimate + 100% headroom, rounded up."
  type        = number
  default     = 20
}

variable "budget_limit_usd" {
  description = "Monthly AWS Budgets threshold in USD"
  type        = number
  default     = 15
}

variable "alert_email" {
  description = "Email address for budget, CloudWatch alarm, and cost anomaly notifications"
  type        = string
  default     = "pedram.agand@gmail.com"
}

variable "backup_retention_days" {
  description = "Days to retain objects in the Postgres backup bucket before lifecycle expiry"
  type        = number
  default     = 90
}
