resource "aws_s3_bucket" "frontend" {
  bucket = "aitutor-frontend-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "aitutor-frontend"
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_acm_certificate" "frontend" {
  provider          = aws.us_east_1
  domain_name       = var.domain_frontend
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Waits on the registrar to publish the validation CNAME, so it stays
# conditional on enable_custom_domain: without that, `apply` blocks for up
# to 45 minutes on a record that doesn't exist yet. aws_acm_certificate
# itself stays unconditional - it's what produces the validation CNAME to
# hand the registrar in the first place.
resource "aws_acm_certificate_validation" "frontend" {
  count = var.enable_custom_domain ? 1 : 0

  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.frontend.arn
  validation_record_fqdns = [for r in aws_acm_certificate.frontend.domain_validation_options : r.resource_record_name]
}

# Shared secret the origin (nginx) requires on every request, so the SG
# prefix-list lock (network.tf) isn't the only thing standing between the
# public internet and the box.
data "aws_ssm_parameter" "origin_secret" {
  name            = "/aitutor/prod/origin_secret"
  with_decryption = true
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "aitutor-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# next.config.ts sets trailingSlash: true, so the static export writes
# login/index.html rather than login.html. An S3 REST origin behind OAC
# doesn't resolve directory indexes, so without this every route except
# / returns 403. Free at this scale (2M invocations/mo free tier, an exam
# uses roughly 1,500).
resource "aws_cloudfront_function" "index_rewrite" {
  name    = "aitutor-index-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite /foo/ -> /foo/index.html for the Next.js trailingSlash export"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      var uri = request.uri;

      if (uri.endsWith('/')) {
        request.uri += 'index.html';
      } else if (!uri.includes('.')) {
        request.uri += '/index.html';
      }

      return request;
    }
  EOT
}

# nginx already sets these for the API (Stage 3); the static frontend had
# none. Cost: $0. connect-src is 'self' - Stage 5 moved the API behind this
# same distribution at /api/*, so it's same-origin now, not a separate
# domain. style-src allows 'unsafe-inline' because Tailwind's compiled
# output and Next's static export rely on it.
#
# script-src must also allow 'unsafe-inline'. An earlier version of this
# policy asserted "there is no inline script anywhere in the export" and
# kept script-src strict. That was wrong, and it broke the site completely:
# Next's static export bootstraps through inline
# <script>self.__next_f.push(...)</script> tags carrying the RSC flight
# payload. Blocking them means React never receives the stream, throws
# "Connection closed.", and wipes the server-rendered markup, leaving every
# visitor a blank white page. Nonces are the strict alternative but need a
# server to generate them per-request, which output:'export' does not have.
# Verified by loading the deployed page in a real browser, which is the only
# check that catches this; curl neither executes JS nor enforces CSP.
resource "aws_cloudfront_response_headers_policy" "frontend" {
  name = "aitutor-frontend-security-headers"

  security_headers_config {
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "same-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 63072000
      include_subdomains         = true
      preload                    = false
      override                   = true
    }
    content_security_policy {
      content_security_policy = "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; font-src 'self' data:; frame-ancestors 'none'"
      override                = true
    }
  }
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  aliases             = var.enable_custom_domain ? [var.domain_frontend] : []

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "frontend-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # Stage 5, D1: the API lives behind this same distribution rather than
  # its own domain. Plaintext to the origin (D3) - CloudFront requires a
  # publicly-trusted cert to speak HTTPS to a custom origin, and keeping
  # one alive would mean keeping certbot (D2). Origin traffic is not
  # encrypted between CloudFront and EC2. This is accepted because the
  # threat model prioritizes operational reliability over protection from
  # network interception. origin_ssl_protocols is required by the provider
  # schema even though origin_protocol_policy never uses it here.
  origin {
    domain_name = aws_eip.api.public_dns
    origin_id   = "ec2-api"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60
    }

    custom_header {
      name  = "X-Origin-Secret"
      value = data.aws_ssm_parameter.origin_secret.value
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "frontend-s3"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # AWS managed: CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.frontend.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.index_rewrite.arn
    }
  }

  # nginx (not a CloudFront Function) strips the /api prefix before
  # proxying to the app - see nginx/available/app.conf. No response-headers
  # policy here: nginx already sets the API's security headers, and the
  # frontend policy's CSP is meaningless on JSON responses.
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "ec2-api"
    viewer_protocol_policy = "https-only"
    compress               = true

    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # AWS managed: CachingDisabled
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AWS managed: AllViewerExceptHostHeader
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # Serves on the default d<xxxx>.cloudfront.net cert until
  # enable_custom_domain flips true (see aws_acm_certificate_validation
  # above) - lets everything downstream (frontend deploy, /api/*
  # migration, V1-V9 verification) proceed without waiting on DNS.
  dynamic "viewer_certificate" {
    for_each = var.enable_custom_domain ? [1] : []
    content {
      acm_certificate_arn      = aws_acm_certificate_validation.frontend[0].certificate_arn
      ssl_support_method       = "sni-only"
      minimum_protocol_version = "TLSv1.2_2021"
    }
  }

  dynamic "viewer_certificate" {
    for_each = var.enable_custom_domain ? [] : [1]
    content {
      cloudfront_default_certificate = true
    }
  }

  tags = {
    Name = "aitutor-frontend-cdn"
  }
}

data "aws_iam_policy_document" "frontend_bucket" {
  statement {
    sid       = "AllowCloudFrontOAC"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_bucket.json
}
