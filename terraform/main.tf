provider "aws" {
  region  = "us-west-2"
  profile = var.aws_profile

  default_tags {
    tags = {
      Project    = "AITutorApp"
      CostCenter = "exam"
    }
  }
}

# CloudFront requires ACM certificates to live in us-east-1, regardless of
# where the rest of the stack runs.
provider "aws" {
  alias   = "us_east_1"
  region  = "us-east-1"
  profile = var.aws_profile

  default_tags {
    tags = {
      Project    = "AITutorApp"
      CostCenter = "exam"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  ops_bucket = "aitutor-434195712367-ops"
}
