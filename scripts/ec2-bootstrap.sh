#!/usr/bin/env bash
set -euo pipefail

# scripts/ec2-bootstrap.sh — runs on every boot via the systemd oneshot that
# Terraform's user-data installs (terraform/templates/user_data.sh.tftpl).
# Lives in-repo rather than in user-data so it evolves with `git pull`
# instead of requiring an instance replacement.
#
# Idempotent by design: a re-run (any reboot) must be safe.
#
# Required env (set by /etc/aitutor/bootstrap.env, sourced by the systemd
# unit — see terraform/templates/user_data.sh.tftpl):
#   REPO_DIR       e.g. /home/ec2-user/AITutorApp
#   REPO_REF       e.g. main
#   OPS_BUCKET     e.g. aitutor-434195712367-ops
#   DOMAIN_FRONTEND  e.g. air.da-tu.ca
#   AWS_REGION     e.g. us-west-2
#
# DOMAIN_API is still written to this env file by user_data (unused here,
# Stage 5 D1) - deliberately left alone, since editing the rendered
# user-data at all forces a full instance replacement
# (user_data_replace_on_change = true) and the AMI is still unpinned.

: "${REPO_DIR:?REPO_DIR must be set}"
: "${REPO_REF:?REPO_REF must be set}"
: "${OPS_BUCKET:?OPS_BUCKET must be set}"
: "${DOMAIN_FRONTEND:?DOMAIN_FRONTEND must be set}"
: "${AWS_REGION:?AWS_REGION must be set}"

log() { echo "[ec2-bootstrap] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

cd "$REPO_DIR"

log "Pulling $REPO_REF"
git fetch origin "$REPO_REF"
git checkout "$REPO_REF"
git reset --hard "origin/$REPO_REF"

# Stage 5, F2: the backups bucket is a separate resource from the ops
# bucket (terraform/backups.tf) - naming it here needs the account id,
# which isn't otherwise available to this script.
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BACKUPS_BUCKET="aitutor-backups-${ACCOUNT_ID}"

log "Rendering .env from SSM"
ssm_get() {
  aws ssm get-parameter --region "$AWS_REGION" --name "$1" --with-decryption --query 'Parameter.Value' --output text
}
GOOGLE_API_KEY="$(ssm_get /aitutor/prod/google_api_key)"
POSTGRES_PASSWORD="$(ssm_get /aitutor/prod/postgres_password)"
API_KEY="$(ssm_get /aitutor/prod/api_key)"
ORIGIN_SECRET="$(ssm_get /aitutor/prod/origin_secret)"

cat > .env <<EOF
# Found live during Stage 5 verification: this line was missing from every
# prior boot of this box. The code default for LLM_PROVIDER is "ollama"
# (app/utils/config.py:37), not "google" - with it unset, hints silently
# degraded to the "..."/hint_style="error" fallback (rag_agent.py's own
# try/except) and chat hard-failed outright, both trying to reach a
# nonexistent localhost:11434. .env.docker.example already documented
# LLM_PROVIDER=google as required; it just never made it into this render.
LLM_PROVIDER=google
GOOGLE_API_KEY=${GOOGLE_API_KEY}
POSTGRES_USER=aitutor
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=aitutor_db
API_KEY=${API_KEY}
ALLOWED_ORIGIN=https://${DOMAIN_FRONTEND}
EXAM_DURATION_MS=1500000
LOG_LEVEL=INFO
BACKUP_S3_URI=s3://${BACKUPS_BUCKET}/backups
# Stage 4.5: APP_ENV=production trips app/main.py's boot assertion, which
# refuses to start unless API_KEY, ALLOWED_ORIGIN and REQUIRE_PARTICIPANT_TOKEN
# are all set to their production posture - fail loud on a misconfigured box
# instead of silently serving a weaker one. REQUIRE_PARTICIPANT_TOKEN and the
# two LLM cap vars are spelled out here even though their code defaults
# already match production, so the real production values are visible on the
# box rather than implicit.
APP_ENV=production
REQUIRE_PARTICIPANT_TOKEN=true
LLM_MAX_CALLS_PER_USER_PER_DAY=150
LLM_MAX_CALLS_PER_DAY=10000
EOF
chmod 600 .env
unset GOOGLE_API_KEY POSTGRES_PASSWORD API_KEY

log "Syncing prod/data from S3"
mkdir -p prod/data
aws s3 sync "s3://${OPS_BUCKET}/artifacts/prod-data/" prod/data/ --delete

# Stage 5, D2: certbot is gone - TLS terminates at CloudFront (D1), so
# there is only ever one server block. The origin secret CloudFront
# attaches on every request (terraform/frontend.tf's ec2-api origin) is
# substituted in here, not committed - see nginx/available/app.conf.
log "Rendering nginx config"
mkdir -p nginx/conf.d
sed "s/__ORIGIN_SECRET__/${ORIGIN_SECRET}/g" nginx/available/app.conf > nginx/conf.d/app.conf
unset ORIGIN_SECRET

# Best-effort refresh of CloudFront's origin-facing ranges (nginx.conf's
# real_ip config, C9) from the live AWS feed. Falls back to the committed
# snapshot (nginx/cloudfront-origin-ips.conf) on any failure - a stale-but-
# present file is far safer than an empty one, which would make nginx fail
# to start.
log "Refreshing CloudFront origin-facing IP ranges"
if CF_RANGES_JSON="$(curl -sf https://ip-ranges.amazonaws.com/ip-ranges.json)"; then
  echo "$CF_RANGES_JSON" | python3 -c '
import json, sys
d = json.load(sys.stdin)
prefixes = sorted(p["ip_prefix"] for p in d["prefixes"] if p["service"] == "CLOUDFRONT_ORIGIN_FACING")
print("# Auto-refreshed by scripts/ec2-bootstrap.sh at boot.")
for p in prefixes:
    print(f"set_real_ip_from {p};")
' > nginx/cloudfront-origin-ips.conf.new \
    && mv nginx/cloudfront-origin-ips.conf.new nginx/cloudfront-origin-ips.conf \
    || log "Failed to parse ip-ranges.json, keeping committed snapshot"
else
  log "Failed to fetch ip-ranges.json, keeping committed snapshot"
fi

log "docker compose up"
docker compose up -d --build

# nginx.conf is bind-mounted as a single *file*, and a single-file bind mount
# binds the inode, not the path. `git pull` writes a new file and renames it
# over the old one, so a container started before the pull keeps serving the
# old config forever - and compose won't recreate nginx on its own, because
# the service definition didn't change, only a file it mounts. On 2026-08-05
# that produced a half-applied deploy: conf.d/app.conf (a *directory* mount,
# resolved by path) picked up the new config while nginx.conf did not, and
# `nginx -s reload` failed with `unknown "api_upstream" variable`. A fresh box
# is unaffected, since its containers are created after the clone - this only
# bites in-place updates, which is exactly what this script does on re-run.
log "Recreating nginx so it picks up any config change from this run"
docker compose up -d --force-recreate nginx

docker image prune -f

log "Waiting for api to report healthy"
# entrypoint.sh runs alembic upgrade head before uvicorn starts, so seeding
# before the container is healthy would hit a participants table that
# doesn't exist yet on a fresh DB. start_period below mirrors the
# healthcheck's own start_period in docker-compose.yml.
api_healthy=false
for _ in $(seq 1 24); do
  api_cid="$(docker compose ps -q api)"
  status="$(docker inspect -f '{{.State.Health.Status}}' "$api_cid" 2>/dev/null || true)"
  if [ "$status" = "healthy" ]; then
    api_healthy=true
    break
  fi
  sleep 10
done

if [ "$api_healthy" != true ]; then
  log "FATAL: api container never reported healthy, aborting bootstrap before seeding"
  exit 1
fi

log "Seeding participants from prod/data/manifest.csv"
docker compose exec -T api python prod/seed_participants.py

# No backup cron is installed. `0 2 * * *` only fires while the instance
# runs, and this box is stopped between exams by design, so on a
# single-day exam it very likely never fires at all. Backups are explicit
# runbook steps instead (docs/OPS_RUNBOOK.html section 10), run on demand.
# BACKUP_S3_URI is still rendered into .env above so a manual
# ./scripts/backup.sh run uploads to the right bucket with no extra args.
#
# Removing a previously-installed cron line from a box that already has
# one: `crontab -l | grep -vF './scripts/backup.sh' | crontab -` by hand.
# Not done here, because on a fresh ec2-user with no crontab `crontab -l`
# exits 1 and `grep -v` on empty input also exits 1, which under
# `set -o pipefail` would kill this script on every first boot - the exact
# bug that was fixed once already when the cron was installed here.
log "Bootstrap complete"
