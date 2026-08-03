terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket       = "aitutor-434195712367-ops"
    key          = "terraform/state.tfstate"
    region       = "us-west-2"
    profile      = "AdministratorAccess-434195712367"
    use_lockfile = true
    encrypt      = true
  }
}
