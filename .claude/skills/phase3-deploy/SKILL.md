---
name: phase3-deploy
description: Step-by-step AWS deployment procedure for AITutorApp Phase 3 go-live (Terraform, CloudFront/HTTPS, EC2 backend setup, frontend S3/CloudFront deploy, load testing, exam day runbook). Use when actually executing Phase 3 deployment work, not for day-to-day Phase 1/2 development.
---

# Phase 3 deployment steps

See `CLAUDE.md`'s "Phase 3 Goals" section for the objective and prerequisites, and `PRELAUNCH_CHECKLIST.md` for the authoritative execution order and recorded decisions. This file holds the detailed how-to steps referenced from there.

**Prerequisites, met as of Stage 4:**
- Terraform 1.15.8 and AWS CLI 2.36.14 installed locally
- `AdministratorAccess-434195712367` SSO profile authenticates (`aws sso login` if the session has expired — Terraform's S3 backend and the `aws` CLI cache tokens separately, so a CLI-working session can still fail for Terraform; re-run `aws sso login` if `terraform state list` errors with `InvalidGrantException`)
- GitHub deploy key (read-only) registered on the repo and stored at SSM `/github/deploy-key`
- Ops bucket `aitutor-434195712367-ops` created out of band, holding Terraform state and the `artifacts/prod-data/` prefix
- SSM `SecureString`s under `/aitutor/prod/`: `google_api_key`, `postgres_password`, `api_key`, `origin_secret` (the last one added Stage 5 — the shared secret CloudFront attaches to every origin request, which nginx checks before proxying anything)

**One domain, not two, since Stage 5.** `air.da-tu.ca` serves both the frontend (static export from S3) and the API (`/api/*`) from the same CloudFront distribution. `api.air.da-tu.ca` no longer exists — deleted along with certbot, whose renewal path never actually worked (it checked a host path certbot never wrote to). The CloudFront-to-origin hop is plaintext HTTP by explicit, recorded tradeoff — see `docs/OPS_RUNBOOK.html` §1 for the full reasoning and the exact tradeoff statement.

### 3.0 Security Review (before any deploy)
- Run `/security-review` on the current branch — done, twice (Stage 3)
- Fix any blocking findings before proceeding

### 3.1 IaC — Provision AWS Resources
`terraform/` (Stage 4, revised Stage 5) is the full root module — no manual resource creation.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # defaults match the signed-off plan; edit only to deviate
terraform init
terraform fmt -check && terraform validate
```

The apply is two-phase, but unlike the original plan, phase 1 alone gets the distribution fully live and testable — the registrar dependency only gates attaching the real domain name at the end:

```bash
# Phase 1: everything, with enable_custom_domain left at its default (false).
# The distribution is created immediately on its own d<xxxx>.cloudfront.net
# domain and default certificate - no DNS record has to exist yet for this
# to succeed. The API's /api/* behavior, the origin secret, the security
# group lockdown, everything else in the stack comes up in this one apply.
terraform plan -out=stage5.tfplan   # review every line
terraform apply stage5.tfplan
terraform output cloudfront_domain_name   # d<xxxx>.cloudfront.net
```

Everything downstream — frontend deploy, backend verification, load testing — can now proceed against that `cloudfront.net` domain with zero DNS dependency. Add the two DNS records the `dns_records_to_add` output prints (the ACM validation CNAME, and a CNAME for `air.da-tu.ca` pointing at the CloudFront domain from the step above) whenever the registrar is ready — it is no longer a blocker for anything else in this list.

Once the registrar confirms both records are live:

```bash
# Phase 2: attach the real domain and cert
terraform apply -var enable_custom_domain=true
```

CloudFront takes 5-15 minutes to redeploy with the new alias and certificate. Re-run the verification checks below against `https://air.da-tu.ca` afterward.

### 3.2 DNS + HTTPS
- Elastic IP is allocated and associated by `terraform/compute.tf`, with `prevent_destroy` — it's CloudFront's origin address now, not a DNS target, and has to stay stable across every stop/start of a box that's deliberately stopped between exams
- TLS terminates entirely at CloudFront. The two DNS records above are the only manual step (registrar, not AWS) and both can go in a single message — see `docs/OPS_RUNBOOK.html` §1 for the exact wording used
- No certbot anywhere in the stack. `nginx/available/app.conf` is the only nginx server block; it speaks plain HTTP only and rejects any request missing the `X-Origin-Secret` header CloudFront attaches

### 3.3 EC2 Backend Setup
Also automatic. `terraform/templates/user_data.sh.tftpl` runs once on first boot (docker install, swap file, deploy key, repo clone, systemd unit); `scripts/ec2-bootstrap.sh` then runs on every boot after that (git pull, render `.env` from SSM, sync `prod/data` from S3, refresh CloudFront's origin-facing IP list, `docker compose up -d --build`, seed `participants` from `manifest.csv` once the api container is healthy, install the backup cron). Nothing to run by hand beyond uploading the exam data once:

```bash
aws s3 sync prod/data/ s3://aitutor-434195712367-ops/artifacts/prod-data/
```

**Gotcha, found live during Stage 5 and worth knowing before touching this script again:** `ec2-bootstrap.sh`'s own first action (`git reset --hard`) rewrites the file the running process is currently executing. The already-running process keeps executing its own stale copy to completion — so the *first* SSM trigger after pushing a change to this script correctly updates the repo on disk but still runs the *old* logic end to end. A *second* trigger (`systemctl reset-failed aitutor-bootstrap.service && systemctl start aitutor-bootstrap.service`) reads the file fresh and runs correctly. A full `aws ec2 reboot-instances` doesn't have this problem. See `docs/OPS_RUNBOOK.html` §2 for the two real incidents this caused this stage.

### 3.4 Frontend Build + S3 Deploy
```bash
cd frontend
NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_API_KEY=<same value as the api_key SSM param> npm run build
aws s3 sync out/ s3://aitutor-frontend-434195712367 --delete
aws cloudfront create-invalidation --distribution-id <id from terraform output> --paths "/*"
```

`NEXT_PUBLIC_API_URL=/api` is relative, not an absolute URL — since Stage 5 the API is same-origin with the frontend (both served from the same CloudFront distribution), so a relative base resolves correctly in the browser with no CORS involved at all. Local dev and the E2E suite keep their own absolute URLs (`frontend/e2e/README.md`, unaffected).

### 3.5 Auth Wire-Up
- `ALLOWED_ORIGIN=https://air.da-tu.ca` — rendered into `.env` by `scripts/ec2-bootstrap.sh`, already wired in `app/main.py`. Largely moot post-Stage-5 since real browser traffic is same-origin and never triggers CORS; kept as defense-in-depth for any direct cross-origin caller
- `API_KEY` — read from SSM by the bootstrap script; must match the frontend's `NEXT_PUBLIC_API_KEY` build var above. Frontend axios client already sends `X-API-Key` from that build var (Stage 2)
- `origin_secret` (SSM) — read by the bootstrap script and substituted into nginx's config; CloudFront attaches it as a custom origin header on every request. Not something the frontend ever sees or sends

### 3.6 Verification (V1-V10)
The full post-migration verification gate, run once against the `cloudfront.net` domain (no DNS needed) and again against the real domain once attached. See the Stage 5 plan (`~/.claude/plans/do-the-stage-5-velvety-duckling.md`) for the exact command for each — summarized:

| # | Check | Why it matters |
|---|---|---|
| V1-V2 | Every router prefix resolves through `/api/*`, no `correct_answer` leak | Confirms nginx's prefix-strip + proxy config is correct end to end |
| V3 | **Cache isolation** ⚠️ exam-breaking if wrong | `/api/*` must never be cached — different users must never see each other's data |
| V4 | **Client IP rate limiting** ⚠️ exam-breaking if wrong | nginx must resolve the true client IP from `X-Forwarded-For`, not key every student on one shared CloudFront edge IP |
| V5 | Origin unreachable directly | Laptop curl to the Elastic IP must time out; missing/wrong `X-Origin-Secret` must 403 |
| V6 | Auth survives the edge, zero cookies | `X-API-Key` reaches the app; a missing key 401s |
| V8 | 502/504 debugging matrix | With the box locked down to CloudFront-only, the only debugging path is SSM session → `curl localhost/api/...` — there is no laptop-curl fallback anymore |
| V9 | Real hint/chat latency | Measure through CloudFront, not just locally — this is also where `LLM_PROVIDER` misconfiguration would surface (see the incident below) |
| V10 | Closed-state UX with the box fully stopped | Confirms the frontend's own 5s client-side timeout, not CloudFront's (much slower) origin-timeout, is what drives the closed-state screen |

**Incident worth knowing before your first post-deploy smoke test:** `scripts/ec2-bootstrap.sh` never wrote `LLM_PROVIDER=google` to `.env`, despite `.env.docker.example` documenting it as required. The code default (`ollama`) silently broke hints (canned fallback, `hint_style: "error"`) and hard-failed chat. Fixed Stage 5, but check `docker compose exec api env | grep LLM_PROVIDER` reads `google` on any fresh deploy — a 200 status on `/hints/` does **not** mean a real hint was generated.

### 3.7 Load / Smoke Test
- Run `k6` or `locust` with 50 concurrent VUs against: `POST /session/start`, `GET /questions/`, `POST /answer/` — through CloudFront, not localhost, so the real edge + rate-limit + real-IP path is exercised
- Pass criteria: p95 < 5 s non-LLM; p50 < 6s / p95 < 15s for hints and chat (the UX budget — 90s stays as the hard timeout, but CloudFront's own origin read timeout ceiling is 60s without a quota increase, so that's the effective worst case now)
- Capture `docker stats` during the run
- Monitor: `docker compose logs -f api` during test

### 3.8 Exam Day Runbook
1. `aws ec2 start-instances --instance-ids <id>` (~60s boot; `scripts/ec2-bootstrap.sh` runs automatically). RAG cold start (PDF ingestion + embedding on a fresh EBS volume) measured at ~2s against the real source doc and Google embedding API — not a factor, no separate warming step needed.
2. EBS snapshot immediately, before traffic starts
3. `aws ssm start-session --target <id>`, then `docker compose logs -f api` — confirm alembic migrate + uvicorn healthy
4. `curl -H "X-API-Key: <key>" https://air.da-tu.ca/api/` — confirm 200; check `LLM_PROVIDER=google` per §3.6's incident note
5. Smoke test one real token end to end before handing tokens out — including a real hint and chat call, checking actual content
6. Hand out tokens to students
7. `aws ssm start-session --document-name AWS-StartPortForwardingSession --parameters portNumber=8501` for the Streamlit tunnel; monitor during exam
8. Immediately **before** stopping the instance (not "after the exam" as a loose end): EBS snapshot + `pg_dump`. This is the real backup — the nightly cron only runs while the box is running, which during a single exam day it likely never does. See `docs/OPS_RUNBOOK.html` §5b.
9. `aws ec2 stop-instances --instance-ids <id>` (EBS data safe). Per standing operational practice, never leave the instance running once a work session's testing or the exam itself is done.

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
    ports: ["80:80"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./nginx/cloudfront-origin-ips.conf:/etc/nginx/cloudfront-origin-ips.conf:ro

volumes:
  postgres_data:
  chroma_data:
```

No port 443, no certbot mounts — TLS terminates at CloudFront (Stage 5).

- `docker compose up -d` to start all
- `docker compose restart api` to restart API only (no data loss, DB keeps running)
- `docker compose down` to stop (data volumes persist)
- `docker compose down -v` only if explicitly asked — destroys data

## AWS Deployment Architecture

```
Students (browser)
    │
CloudFront  [air.da-tu.ca]
    ├── default behavior → S3 (Next.js static export, always on, ~free)
    └── /api/* behavior  → EC2 origin (plain HTTP, X-Origin-Secret required)
                              │
                          EC2 t3.medium (start before exam, stop after)
                          └── Docker Compose: api + db + nginx (port 80 only) + streamlit (127.0.0.1:8501 only)
                          └── EBS 30GB gp3 (data persists across stop/start)
                          └── Elastic IP - stable target for CloudFront's origin, not a DNS record
                          └── Security group: port 80 from CloudFront's origin-facing ranges only, no port 22/443
```

`NEXT_PUBLIC_API_URL=/api` — same-origin, no separate API domain, no CORS on real traffic.

### Frontend Deploy Steps
1. `cd frontend && NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_API_KEY=<key> npm run build` (generates `out/`)
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

Or, to run the exact same path a reboot would (recommended — picks up `.env` and nginx config changes too, not just code):

```bash
sudo systemctl reset-failed aitutor-bootstrap.service
sudo systemctl start aitutor-bootstrap.service
# run this command a second time if it's the first pull of a change
# to ec2-bootstrap.sh itself - see the self-modifying-script gotcha above
```

**Day-to-day ops:**
- `docker compose restart api` — restart API only, DB keeps running
- `docker compose down` — stop all (data volumes persist)
- `docker compose down -v` — ONLY if explicitly asked, destroys all data
- `docker compose logs -f api` — tail logs

### Toggle Process
- Before exam: `aws ec2 start-instances` (~60s; bootstrap re-runs, picks up any `git pull`-able changes)
- After exam, immediately before stopping: dump the DB and snapshot (§3.8 step 8) — the nightly cron is not the safety net
- `aws ec2 stop-instances` (data safe on EBS)
- No automatic monthly boot anymore — the EventBridge schedules that used to exist purely for certbot renewal are deleted along with certbot. Nothing boots this box unattended.

### Security
- Origin locked down two ways: the security group admits port 80 only from CloudFront's published origin-facing IP ranges (nothing else can reach the box, full stop — not even from a laptop for debugging, see §3.6's V5/V8), and nginx rejects any request missing the `X-Origin-Secret` header CloudFront attaches
- `X-API-Key` header required once `API_KEY` is set (obscurity, not secrecy — the key ships in the public frontend bundle)
- No auth system — user ID is the only identifier, but (Stage 4.5) `POST /users/` and every session-owner-gated endpoint reject any `user_id` with no manifest `Participant` row (`REQUIRE_PARTICIPANT_TOKEN=true`, the production default) — a token is required to use the API at all, not just to act as a specific student
- In-app LLM spend cap (Stage 4.5): `LLM_MAX_CALLS_PER_USER_PER_DAY` / `LLM_MAX_CALLS_PER_DAY`, rolling 24h — nginx's rate limit is per source IP and can't see `user_id`, so it can't bound cost; these can
- `APP_ENV=production` trips a boot-time assertion (`app/main.py`) refusing to start unless `API_KEY`, `ALLOWED_ORIGIN` and `REQUIRE_PARTICIPANT_TOKEN` are all set to their production posture. `LLM_PROVIDER` is not yet part of this assertion — see the recommendation in `docs/OPS_RUNBOOK.html` §11 to add it
- HTTPS terminates at CloudFront, not on the box. The CloudFront-to-origin hop is plaintext by explicit, recorded tradeoff (`docs/OPS_RUNBOOK.html` §1) — mitigated by the security-group lock and the origin secret, not by encryption
- No SSH; SSM Session Manager only
