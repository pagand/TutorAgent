# Pinned, deliberately (F5). This used to be a `most_recent = true` lookup,
# which meant every AWS release of a new AL2023 image silently changed the
# resolved AMI id. `ami` forces replacement on aws_instance, so the next
# `terraform apply` for any unrelated reason would have destroyed the running
# box and its root volume, taking the Postgres and chroma_data Docker volumes
# with it. That was caught on 2026-08-05 by a plan for a DNS-only change that
# came back wanting to replace the instance.
#
# This is the AMI the live instance was actually built from, so pinning it
# is a no-op against current state rather than a migration. Changing it is now
# an explicit, reviewed decision: bump the value, confirm the new image's root
# snapshot still fits root_volume_gb, and expect a full instance replacement.
variable "ami_id" {
  description = "AMI for the app instance. Pinned so an upstream AL2023 release cannot silently force instance replacement."
  type        = string
  default     = "ami-06503266fb468d937"
}

# Stage 5, F4/D5: it's the CloudFront origin hostname and is already with
# the registrar (indirectly, via the CNAME pointing at CloudFront, but
# re-obtaining a released address means new DNS work regardless). Guard
# against an untargeted `terraform destroy` releasing it permanently.
resource "aws_eip" "api" {
  domain = "vpc"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = "aitutor-api-eip"
  }
}

resource "aws_eip_association" "api" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.api.id
}

resource "aws_instance" "app" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  # t3 is burstable with a 20% baseline. A box started cold on exam
  # morning has no accrued credits, and Chroma retrieval runs synchronous
  # embedding calls in an executor, so CPU is a live constraint on cold
  # start. Unlimited mode prices this away: worst case ~$0.80/exam day,
  # realistically ~$0.10.
  credit_specification {
    cpu_credits = "unlimited"
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    repo_url        = var.repo_url
    repo_ref        = var.repo_ref
    ops_bucket      = local.ops_bucket
    account_id      = data.aws_caller_identity.current.account_id
    domain_api      = var.domain_api
    domain_frontend = var.domain_frontend
    aws_region      = "us-west-2"
  })

  # The bootstrap script (scripts/ec2-bootstrap.sh, in-repo) does the
  # real work on every boot via a systemd oneshot user-data installs.
  # Changing user_data itself should still force a clean re-provision.
  user_data_replace_on_change = true

  tags = {
    Name = "aitutor-app"
  }
}
