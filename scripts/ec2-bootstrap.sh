#!/usr/bin/env bash
set -euo pipefail

# scripts/ec2-bootstrap.sh — runs on every boot via the systemd oneshot that
# Terraform's user-data installs (terraform/templates/user_data.sh.tftpl).
# Lives in-repo rather than in user-data so it evolves with `git pull`
# instead of requiring an instance replacement.
#
# Idempotent by design: a re-run (reboot, or the monthly EventBridge
# auto-boot for cert renewal) must be safe.
#
# Required env (set by /etc/aitutor/bootstrap.env, sourced by the systemd
# unit — see terraform/templates/user_data.sh.tftpl):
#   REPO_DIR       e.g. /home/ec2-user/AITutorApp
#   REPO_REF       e.g. main
#   OPS_BUCKET     e.g. aitutor-434195712367-ops
#   DOMAIN_API     e.g. api.air.da-tu.ca
#   DOMAIN_FRONTEND  e.g. air.da-tu.ca
#   AWS_REGION     e.g. us-west-2

: "${REPO_DIR:?REPO_DIR must be set}"
: "${REPO_REF:?REPO_REF must be set}"
: "${OPS_BUCKET:?OPS_BUCKET must be set}"
: "${DOMAIN_API:?DOMAIN_API must be set}"
: "${DOMAIN_FRONTEND:?DOMAIN_FRONTEND must be set}"
: "${AWS_REGION:?AWS_REGION must be set}"

log() { echo "[ec2-bootstrap] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

cd "$REPO_DIR"

log "Pulling $REPO_REF"
git fetch origin "$REPO_REF"
git checkout "$REPO_REF"
git reset --hard "origin/$REPO_REF"

log "Rendering .env from SSM"
ssm_get() {
  aws ssm get-parameter --region "$AWS_REGION" --name "$1" --with-decryption --query 'Parameter.Value' --output text
}
GOOGLE_API_KEY="$(ssm_get /aitutor/prod/google_api_key)"
POSTGRES_PASSWORD="$(ssm_get /aitutor/prod/postgres_password)"
API_KEY="$(ssm_get /aitutor/prod/api_key)"

cat > .env <<EOF
GOOGLE_API_KEY=${GOOGLE_API_KEY}
POSTGRES_USER=aitutor
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=aitutor_db
API_KEY=${API_KEY}
ALLOWED_ORIGIN=https://${DOMAIN_FRONTEND}
EXAM_DURATION_MS=1500000
LOG_LEVEL=INFO
BACKUP_S3_URI=s3://${OPS_BUCKET}/backups
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

CERT_LIVE="/etc/letsencrypt/live/${DOMAIN_API}/fullchain.pem"
mkdir -p nginx/conf.d certbot-www

if [ -f "$CERT_LIVE" ]; then
  log "Cert exists, starting with TLS config"
  sed "s/__DOMAIN_API__/${DOMAIN_API}/g" nginx/available/tls.conf > nginx/conf.d/app.conf
else
  log "No cert yet, starting with plain-HTTP config"
  cp nginx/available/plain.conf nginx/conf.d/app.conf
fi

log "docker compose up"
docker compose up -d --build
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

if [ ! -f "$CERT_LIVE" ]; then
  log "Requesting certificate for ${DOMAIN_API}"
  docker run --rm \
    -v "$(pwd)/certbot:/etc/letsencrypt" \
    -v "$(pwd)/certbot-www:/var/www/certbot" \
    certbot/certbot certonly --webroot -w /var/www/certbot \
    -d "${DOMAIN_API}" --non-interactive --agree-tos \
    -m "pedram.agand@gmail.com" --no-eff-email || log "certbot issuance failed, staying on plain HTTP"

  if [ -f "$CERT_LIVE" ]; then
    log "Cert issued, switching to TLS config"
    sed "s/__DOMAIN_API__/${DOMAIN_API}/g" nginx/available/tls.conf > nginx/conf.d/app.conf
    docker compose exec -T nginx nginx -s reload
  fi
else
  log "Renewing certificate for ${DOMAIN_API}"
  docker run --rm \
    -v "$(pwd)/certbot:/etc/letsencrypt" \
    -v "$(pwd)/certbot-www:/var/www/certbot" \
    certbot/certbot renew --webroot -w /var/www/certbot --quiet || log "certbot renew failed"
  docker compose exec -T nginx nginx -s reload
fi

log "Installing nightly backup cron"
CRON_LINE="0 2 * * * cd ${REPO_DIR} && DOCKER_DB_SERVICE=db POSTGRES_USER=aitutor POSTGRES_DB=aitutor_db BACKUP_S3_URI=s3://${OPS_BUCKET}/backups ./scripts/backup.sh >> ${REPO_DIR}/backups/cron.log 2>&1"
# `|| true` on the listing: under set -o pipefail, a brand-new ec2-user with
# no existing crontab makes `crontab -l` exit 1 with empty output, and grep
# -v on empty input also exits 1 (no lines selected) - without the guard,
# set -e kills the whole script right here on every box's very first boot.
( crontab -l 2>/dev/null | grep -vF './scripts/backup.sh' || true; echo "$CRON_LINE" ) | crontab -

log "Bootstrap complete"
