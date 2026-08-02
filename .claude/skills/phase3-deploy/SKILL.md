---
name: phase3-deploy
description: Step-by-step AWS deployment procedure for AITutorApp Phase 3 go-live (Terraform, DNS/HTTPS, EC2 backend setup, frontend S3/CloudFront deploy, CORS/API key wire-up, load testing, exam day runbook). Use when actually executing Phase 3 deployment work, not for day-to-day Phase 1/2 development.
---

# Phase 3 deployment steps

See `CLAUDE.md`'s "Phase 3 Goals" section for the objective and prerequisites, and `PRELAUNCH_CHECKLIST.md` for the authoritative execution order and recorded decisions. This file holds the detailed how-to steps referenced from there.

**Prerequisites from you before starting Phase 3:**
- Run `aws configure` (access key ID + secret + region) on your local machine — Claude handles everything after that
- EC2 access: share the `.pem` key **or** enable AWS Systems Manager on the instance (SSM = no key needed, preferred)
- Domain registrar access to add an A record for `air.da-tu.ca` → Elastic IP (one DNS click, ~2 min)
- Secrets to put in `.env`: `POSTGRES_PASSWORD`, `GOOGLE_API_KEY`, `API_KEY`

### 3.0 Security + Performance Review (before any deploy)
- Run `/security-review` on the current branch — covers session lock, CORS, API key middleware, token exposure
- Run `/code-review` ultra — full multi-agent review for correctness and regressions
- Fix any blocking findings before proceeding to 3.1

### 3.1 IaC — Provision AWS Resources
Claude will write and apply Terraform (or CDK) to create:
- S3 bucket (static website hosting, private + OAC)
- CloudFront distribution (OAC → S3, HTTPS only, cache policy)
- EC2 security group (ports 80, 443 inbound; 22 or SSM only)
- Elastic IP association
- IAM role for EC2 (SSM + CloudWatch if needed)

### 3.2 DNS + HTTPS
- Allocate Elastic IP and associate with EC2 instance
- Add A record: `air.da-tu.ca` → Elastic IP (you do this one DNS click)
- SSH/SSM into EC2, run Certbot: `certbot --nginx -d air.da-tu.ca`
- Nginx config: HTTP → HTTPS redirect + proxy `/` to uvicorn on port 8000

### 3.3 EC2 Backend Setup
```bash
git clone <repo> AITutorApp && cd AITutorApp
scp -r /path/to/prod/data ec2-user@<host>:~/AITutorApp/prod/data   # prod/data/ is gitignored, copy out-of-band
cp .env.docker.example .env   # fill secrets (Claude sets ALLOWED_ORIGIN from CloudFront domain)
docker compose up -d --build  # first build ~10-15 min
curl http://localhost/         # smoke test → {"message":"Welcome to the AI Tutor API"}
```

Install the nightly backup cron (README.md's "Backup and Restore" section, Stage 2 tooling — fill in `BACKUP_S3_URI` once the S3 bucket exists from 3.1):
```bash
crontab -e
# 0 2 * * * cd ~/AITutorApp && DOCKER_DB_SERVICE=db POSTGRES_USER=aitutor POSTGRES_DB=aitutor_db BACKUP_S3_URI=s3://<bucket>/aitutor-backups ./scripts/backup.sh >> ~/AITutorApp/backups/cron.log 2>&1
```

### 3.4 Frontend Build + S3 Deploy
```bash
cd frontend
NEXT_PUBLIC_API_URL=https://air.da-tu.ca NEXT_PUBLIC_API_KEY=<same secret as EC2's API_KEY> npm run build   # static export to out/
aws s3 sync out/ s3://<bucket> --delete
aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
```

### 3.5 CORS + API Key Wire-Up
- `ALLOWED_ORIGIN=https://<cloudfront-domain>` in EC2 `.env` — already wired in `app/main.py`
- `API_KEY=<secret>` in EC2 `.env` — middleware implemented (Stage 2), unset = disabled
- Frontend axios client already sends `X-API-Key` header from `NEXT_PUBLIC_API_KEY` build var (Stage 2)

### 3.6 Load / Smoke Test
- Run `k6` or `locust` with 50 concurrent VUs against: `POST /session/start`, `GET /questions/`, `POST /answer/`
- Pass criteria: p95 < 5 s non-LLM; LLM endpoints (hints, chat) < 90 s
- Monitor: `docker compose logs -f api` during test

### 3.7 Exam Day Runbook
1. `AWS Console → EC2 → Start` (~60 s boot)
2. `docker compose logs -f api` — confirm alembic migrate + uvicorn healthy
3. `curl https://air.da-tu.ca/` — confirm 200
4. Upload participant manifest CSV via Streamlit admin
5. Hand out tokens to students
6. Monitor Streamlit dashboard during exam
7. After exam: `AWS Console → EC2 → Stop` (EBS data safe)

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
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./certbot:/etc/letsencrypt

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
CloudFront → S3 (Next.js static export, always on, ~free)
    │
    NEXT_PUBLIC_API_URL = https://<domain or elastic IP>
    │
EC2 t3.small (start before exam, stop after)
    └── Docker Compose: api + db + nginx
    └── EBS 20GB gp3 (data persists across stop/start)
```

### Frontend Deploy Steps
1. `cd frontend && npm run build` (generates `out/`)
2. `aws s3 sync out/ s3://<bucket-name> --delete`
3. CloudFront invalidation: `aws cloudfront create-invalidation --paths "/*"`

### Backend Deploy Steps

**First-time setup on EC2:**
```bash
git clone <repo-url> AITutorApp
cd AITutorApp
scp -r /path/to/prod/data ec2-user@<host>:~/AITutorApp/prod/data   # prod/data/ is gitignored, copy out-of-band
cp .env.docker.example .env        # fill in POSTGRES_PASSWORD, GOOGLE_API_KEY, ALLOWED_ORIGIN, API_KEY (must match frontend's NEXT_PUBLIC_API_KEY)
docker compose up -d --build       # first build ~10-15 min (ML packages ~2.5GB)
docker compose logs -f api         # watch alembic migrate + uvicorn startup
curl http://localhost/             # should return {"message":"Welcome to the AI Tutor API"}
```

**Subsequent deploys:**
```bash
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
- Before exam: AWS Console → EC2 → Start (60s)
- After exam: AWS Console → EC2 → Stop (data safe on EBS)

### Security
- CORS restricted to CloudFront domain via `ALLOWED_ORIGIN` env var
- Optional API key (`X-API-Key` header) for obscurity during exam
- No auth system — user ID is the only identifier (acceptable for exam scope)
- HTTPS via Nginx + Let's Encrypt on EC2
