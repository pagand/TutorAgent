---
name: phase3-deploy
description: Step-by-step AWS deployment procedure for AITutorApp Phase 3 go-live (Terraform, DNS/HTTPS, EC2 backend setup, frontend S3/CloudFront deploy, CORS/API key wire-up, load testing, exam day runbook). Use when actually executing Phase 3 deployment work, not for day-to-day Phase 1/2 development.
---

# Phase 3 deployment steps

See `CLAUDE.md`'s "Phase 3 Goals" section for the objective and prerequisites, and `PRELAUNCH_CHECKLIST.md` for the authoritative execution order and recorded decisions. This file holds the detailed how-to steps referenced from there.

**Prerequisites, met as of Stage 4:**
- Terraform 1.15.8 and AWS CLI 2.36.14 installed locally
- `AdministratorAccess-434195712367` SSO profile authenticates (`aws sso login` if the session has expired)
- GitHub deploy key (read-only) registered on the repo and stored at SSM `/github/deploy-key`
- Ops bucket `aitutor-434195712367-ops` created out of band, holding Terraform state and the `artifacts/prod-data/` prefix
- SSM `SecureString`s under `/aitutor/prod/`: `google_api_key`, `postgres_password`, `api_key`

Two domains, not one: `air.da-tu.ca` serves the frontend via CloudFront, `api.air.da-tu.ca` serves the backend via the Elastic IP.

### 3.0 Security Review (before any deploy)
- Run `/security-review` on the current branch — done, twice (Stage 3)
- Fix any blocking findings before proceeding

### 3.1 IaC — Provision AWS Resources
`terraform/` (Stage 4) is the full root module — no manual resource creation. See the plan at `/Users/pedram/.claude/plans/complete-stage-5-of-snuggly-bear.md` for the full manifest and cost breakdown (36 resources, idle floor $5.66/mo).

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # defaults match the signed-off plan; edit only to deviate
terraform init
terraform fmt -check && terraform validate
```

DNS lives outside AWS, so the apply is two-phase:

```bash
# Phase 1: just the ACM cert + EIP, so their outputs exist to put in DNS
terraform plan -target=aws_acm_certificate.frontend -target=aws_eip.api -out=phase1.tfplan
terraform apply phase1.tfplan
```

Add the two DNS records the outputs print (ACM validation CNAME, `api.air.da-tu.ca` A record → the Elastic IP), then:

```bash
# Phase 2: the full stack. ACM validation completes and CloudFront builds (~10 min)
terraform plan -out=full.tfplan   # review every line against the manifest before applying
terraform apply full.tfplan
```

Add the third DNS record from the outputs (`air.da-tu.ca` CNAME → the CloudFront domain), then reboot the instance so `scripts/ec2-bootstrap.sh` re-runs with real DNS live and certbot succeeds.

### 3.2 DNS + HTTPS
Handled by Terraform + the bootstrap script, not manually:
- Elastic IP is allocated and associated by `terraform/compute.tf`
- The three DNS records above are the only manual step (registrar, not AWS)
- `scripts/ec2-bootstrap.sh` runs certbot in webroot mode on every boot, issuing the cert on first successful boot with real DNS and renewing thereafter
- nginx switches between `nginx/available/plain.conf` (no cert yet) and `nginx/available/tls.conf` (cert present) automatically

### 3.3 EC2 Backend Setup
Also automatic. `terraform/templates/user_data.sh.tftpl` runs once on first boot (docker install, swap file, deploy key, repo clone, systemd unit); `scripts/ec2-bootstrap.sh` then runs on every boot after that (git pull, render `.env` from SSM, sync `prod/data` from S3, `docker compose up -d --build`, seed `participants` from `manifest.csv` once the api container is healthy, certbot, install the backup cron). Nothing to run by hand beyond uploading the exam data once:

```bash
aws s3 sync prod/data/ s3://aitutor-434195712367-ops/artifacts/prod-data/
```

### 3.4 Frontend Build + S3 Deploy
```bash
cd frontend
NEXT_PUBLIC_API_URL=https://api.air.da-tu.ca NEXT_PUBLIC_API_KEY=<same value as the api_key SSM param> npm run build
aws s3 sync out/ s3://aitutor-frontend-434195712367 --delete
aws cloudfront create-invalidation --distribution-id <id from terraform output> --paths "/*"
```

### 3.5 CORS + API Key Wire-Up
- `ALLOWED_ORIGIN=https://air.da-tu.ca` — rendered into `.env` by `scripts/ec2-bootstrap.sh`, already wired in `app/main.py`
- `API_KEY` — read from SSM by the bootstrap script; must match the frontend's `NEXT_PUBLIC_API_KEY` build var above
- Frontend axios client already sends `X-API-Key` from that build var (Stage 2)

### 3.6 Load / Smoke Test
- Run `k6` or `locust` with 50 concurrent VUs against: `POST /session/start`, `GET /questions/`, `POST /answer/`
- Pass criteria: p95 < 5 s non-LLM; LLM endpoints (hints, chat) < 90 s
- Capture `docker stats` during the run — this is what turns Stage 4's memory estimate into a real number
- Monitor: `docker compose logs -f api` during test

### 3.7 Exam Day Runbook
1. `aws ec2 start-instances --instance-ids <id>` (~60s boot; `scripts/ec2-bootstrap.sh` runs automatically). RAG cold start (PDF ingestion + embedding on a fresh EBS volume) measured at ~2s against the real source doc and Google embedding API — not a factor, no separate warming step needed.
2. EBS snapshot immediately, before traffic starts
3. `aws ssm start-session --target <id>`, then `docker compose logs -f api` — confirm alembic migrate + uvicorn healthy
4. `curl https://api.air.da-tu.ca/` — confirm 200; verify cert expiry with `openssl s_client`
5. Smoke test one real token end to end before handing tokens out
6. Hand out tokens to students
7. `aws ssm start-session --document-name AWS-StartPortForwardingSession --parameters portNumber=8501` for the Streamlit tunnel; monitor during exam
8. After exam: EBS snapshot + `pg_dump`, then `aws ec2 stop-instances --instance-ids <id>` (EBS data safe)

## Docker Compose (EC2 deployment)

```yaml
services:
  api:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - chroma_data:/app/chroma_db
      - ./prod/data:/app/prod/data:ro
    depends_on: [db]

  db:
    image: postgres:16-alpine
    restart: unless-stopped
    env_file: .env
    volumes:
      - postgres_data:/var/lib/postgresql/data

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./certbot:/etc/letsencrypt
      - ./certbot-www:/var/www/certbot

volumes:
  postgres_data:
  chroma_data:
```

- `docker compose up -d` to start all
- `docker compose restart api` to restart API only (no data loss, DB keeps running)
- `docker compose down` to stop (data volumes persist)
- `docker compose down -v` only if explicitly asked — destroys data

## AWS Deployment Architecture

```
Students (browser)
    │
CloudFront → S3 (Next.js static export, always on, ~free)  [air.da-tu.ca]
    │
    NEXT_PUBLIC_API_URL = https://api.air.da-tu.ca
    │
EC2 t3.medium (start before exam, stop after)
    └── Docker Compose: api + db + nginx + streamlit (127.0.0.1:8501 only)
    └── EBS 20GB gp3 (data persists across stop/start)
    └── Elastic IP, no port 22 - SSM Session Manager only
```

### Frontend Deploy Steps
1. `cd frontend && npm run build` (generates `out/`)
2. `aws s3 sync out/ s3://<bucket-name> --delete`
3. CloudFront invalidation: `aws cloudfront create-invalidation --paths "/*"`

### Backend Deploy Steps

First boot and every boot after that are both automatic — see 3.1-3.3 above. Manual steps only apply to a re-deploy of application code onto an already-provisioned box:

```bash
aws ssm start-session --target <id>
cd AITutorApp
git pull
docker compose build api           # rebuild only api image
docker compose up -d               # rolling restart
```

**Day-to-day ops:**
- `docker compose restart api` — restart API only, DB keeps running
- `docker compose down` — stop all (data volumes persist)
- `docker compose down -v` — ONLY if explicitly asked, destroys all data
- `docker compose logs -f api` — tail logs

### Toggle Process
- Before exam: `aws ec2 start-instances` (~60s; bootstrap re-runs, picks up any `git pull`-able changes and renews the cert if due)
- After exam: `aws ec2 stop-instances` (data safe on EBS)
- Monthly, automatically: EventBridge starts the box for 30 minutes on the 1st so certbot can renew even with no exam scheduled

### Security
- CORS restricted to `https://air.da-tu.ca` via `ALLOWED_ORIGIN` env var
- `X-API-Key` header required once `API_KEY` is set (obscurity, not secrecy — the key ships in the public frontend bundle)
- No auth system — user ID is the only identifier, but (Stage 4.5) `POST /users/` and every session-owner-gated endpoint reject any `user_id` with no manifest `Participant` row (`REQUIRE_PARTICIPANT_TOKEN=true`, the production default) — a token is required to use the API at all, not just to act as a specific student
- In-app LLM spend cap (Stage 4.5): `LLM_MAX_CALLS_PER_USER_PER_DAY` / `LLM_MAX_CALLS_PER_DAY`, rolling 24h — nginx's rate limit is per source IP and can't see `user_id`, so it can't bound cost; these can
- `APP_ENV=production` trips a boot-time assertion (`app/main.py`) refusing to start unless `API_KEY`, `ALLOWED_ORIGIN` and `REQUIRE_PARTICIPANT_TOKEN` are all set to their production posture
- Real HTTPS via nginx + Let's Encrypt, auto-renewed monthly
- No SSH; SSM Session Manager only
