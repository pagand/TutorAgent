# Dedicated VPC rather than the account default, so destroy/re-apply is
# genuinely clean and never touches account-default resources.
resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "aitutor-vpc"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.0.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "us-west-2a"

  tags = {
    Name = "aitutor-public"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "aitutor-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "aitutor-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

data "aws_ec2_managed_prefix_list" "cloudfront_origin_facing" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# No 22: SSM Session Manager is the only shell access path (recorded
# decision, checklist section J). No 443: certbot is gone (D2), TLS
# terminates at CloudFront (D1), and the CloudFront-to-origin hop is
# plaintext by design (D3). Port 80 accepts only CloudFront's published
# origin-facing ranges, not the open internet - direct requests to the
# Elastic IP now time out at the SG rather than reaching nginx (V5).
# Egress is open so docker pulls, dnf updates, and SSM's own outbound
# channel all work.
resource "aws_security_group" "app" {
  # name_prefix, not a fixed name: description is immutable on this
  # resource, so this Stage 5 edit forces a replace. aws_instance.app
  # references this SG by id (compute.tf), never by name, so a generated
  # suffix is safe - but a fixed name would collide with itself under
  # create_before_destroy, since AWS requires SG names to be unique per
  # VPC and the old SG is still alive when the new one is created.
  name_prefix = "aitutor-app-"
  description = "AITutorApp EC2: port 80 from CloudFront only, no SSH, no direct HTTPS"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from CloudFront origin-facing ranges only"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront_origin_facing.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aitutor-app-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}
