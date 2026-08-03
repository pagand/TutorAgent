data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_eip" "api" {
  domain = "vpc"

  tags = {
    Name = "aitutor-api-eip"
  }
}

resource "aws_eip_association" "api" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.api.id
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
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
