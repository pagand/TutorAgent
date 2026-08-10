#!/usr/bin/env bash
set -euo pipefail

# scripts/snapshot.sh - one on-demand bundle of everything on the instance
# that CANNOT be rebuilt from Terraform, git and S3: the Postgres dump, the
# chroma_data Docker volume (vector store + llm_cache.db), and the container
# logs. Uploaded as ONE timestamped key to the backups bucket.
#
# Scope is deliberate. A fresh box rebuilds the OS, the code, the schema, the
# questions, the participant roster and the RAG index unattended in about four
# minutes, so none of that belongs in the artifact you reach for when an exam
# has to be recovered. Postgres is the only irreplaceable state; the logs die
# with the container and so cannot be regenerated either; chroma_data is kept
# because llm_cache.db lives inside it and rebuilding the cache costs real
# Gemini calls.
#
# Not a cron. Run on demand and as a post-exam runbook step
# (docs/OPS_RUNBOOK.html), same reasoning as backup.sh: the box is stopped
# between exams, so nothing scheduled on it is real coverage.
#
# Must run on the box, from the repo root, with docker compose up - it
# needs docker compose to resolve and capture the chroma_data named volume
# and to read container logs, so unlike backup.sh there is no "local
# DATABASE_URL" mode.
#
# Env vars:
#   POSTGRES_USER, POSTGRES_DB   required - passed straight through to backup.sh
#   SNAPSHOT_DIR                 default ./backups/snapshots - local staging + retained copy
#   AWS_REGION                   default us-west-2
#
# Usage (on the box, repo root):
#   POSTGRES_USER=aitutor POSTGRES_DB=aitutor_db ./scripts/snapshot.sh

: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${POSTGRES_DB:?POSTGRES_DB must be set}"
AWS_REGION="${AWS_REGION:-us-west-2}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-./backups/snapshots}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BUNDLE_NAME="aitutor_snapshot_${TIMESTAMP}"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/${BUNDLE_NAME}.XXXXXX")"
BUNDLE_ROOT="${WORK_DIR}/${BUNDLE_NAME}"

log() { echo "[snapshot] $*"; }

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$BUNDLE_ROOT"/{dump,logs}

# --- 1. Container logs first, before anything below touches the stack ---
log "Capturing container logs"
for svc in api db nginx; do
  docker compose logs --no-color "$svc" > "${BUNDLE_ROOT}/logs/${svc}.log" 2>&1 || \
    log "WARNING: could not capture logs for $svc (continuing)"
done

# --- 2. Postgres dump, via the existing backup.sh - no BACKUP_S3_URI here,  ---
# --- so it stays local; snapshot.sh does the one upload for the whole bundle ---
log "Running backup.sh for the Postgres dump"
BACKUP_DIR="${BUNDLE_ROOT}/dump" \
  DOCKER_DB_SERVICE=db \
  POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_DB="$POSTGRES_DB" \
  "${SCRIPT_DIR}/backup.sh"

# --- 3 and 4 removed deliberately: the bundle holds only what cannot be   ---
# --- rebuilt. The per-table CSV export is derivable from dump/ at any time ---
# --- (pg_restore then \copy), and prod/data is restored on every boot by   ---
# --- ec2-bootstrap.sh's sync from the ops bucket, so carrying either here  ---
# --- inflated the artifact you depend on to recover an exam with copies of ---
# --- things that recover themselves.                                       ---

# --- 5. Data dictionary, so the bundle is self-describing ---
cat > "${BUNDLE_ROOT}/README.md" <<'EOF'
# AITutorApp instance snapshot

Captured by scripts/snapshot.sh. Contents:

- dump/aitutor_*.dump      Postgres dump (pg_dump -Fc, all tables incl. alembic_version).
                           Restore with scripts/restore.sh or scripts/snapshot_restore.sh.
- chroma_data.tar.gz        Tar of the chroma_data Docker named volume (Chroma vector store
                           plus llm_cache.db, which lives inside chroma_persist_dir).
                           NOT PRESENT if the API container could not be stopped during capture
                           (see snapshot.sh output for a warning) - check before relying on it.
- logs/*.log                docker compose logs for api/db/nginx at capture time,
                           capped at whatever the 10MB x 3 file x-logging retention held.

## user_action_logs.action_type - the real values

app/models/user.py's UserActionLog docstring is STALE (documents intervention_offered /
intervention_accepted / intervention_rejected / session_complete / timer_expired /
chat_message_sent / chat_response_received, none of which the app emits). The 19 values the
application actually writes, verified against frontend/src usage and app/endpoints/action_log.py's
validation whitelist, are:

session_start, session_submit, session_expire, timer_warning, question_view,
question_navigate, choice_select, answer_focus, answer_submit, answer_skip,
hint_request, hint_display, hint_feedback, intervention_offer, intervention_accept,
intervention_reject, chat_send, profile_view, preference_update

Do not filter action_type on the docstring's names - they do not occur in the data.
EOF

# --- 6. chroma_data volume: resolve the real volume name, stop api for a  ---
# --- consistent copy (llm_cache.db is a live SQLite file), tar, restart   ---
log "Resolving chroma_data volume from the api container's mounts"
API_CID="$(docker compose ps -q api || true)"
CHROMA_VOLUME=""
if [ -n "$API_CID" ]; then
  CHROMA_VOLUME="$(docker inspect --format '{{ range .Mounts }}{{ if eq .Destination "/app/chroma_db" }}{{ .Name }}{{ end }}{{ end }}' "$API_CID")"
fi

if [ -z "$CHROMA_VOLUME" ]; then
  log "WARNING: could not resolve the chroma_data volume (api container not found or not mounting /app/chroma_db) - skipping volume capture. Bundle will NOT contain chroma_data.tar.gz."
else
  log "Stopping api for a consistent chroma_data capture (volume: $CHROMA_VOLUME)"
  docker compose stop api
  docker run --rm \
    -v "${CHROMA_VOLUME}:/source:ro" \
    -v "${BUNDLE_ROOT}:/backup" \
    alpine:3 \
    tar czf /backup/chroma_data.tar.gz -C /source .
  log "Restarting api"
  docker compose start api
fi

# --- 7. Bundle and upload under one timestamped key ---
log "Creating bundle archive"
BUNDLE_FILE="${BUNDLE_NAME}.tar.gz"
tar czf "${WORK_DIR}/${BUNDLE_FILE}" -C "$WORK_DIR" "$BUNDLE_NAME"

mkdir -p "$SNAPSHOT_DIR"
cp "${WORK_DIR}/${BUNDLE_FILE}" "${SNAPSHOT_DIR}/${BUNDLE_FILE}"
log "Bundle staged locally: ${SNAPSHOT_DIR}/${BUNDLE_FILE} ($(du -h "${SNAPSHOT_DIR}/${BUNDLE_FILE}" | cut -f1))"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")"
BACKUPS_BUCKET="aitutor-backups-${ACCOUNT_ID}"
S3_KEY="snapshots/${BUNDLE_FILE}"

log "Uploading to s3://${BACKUPS_BUCKET}/${S3_KEY}"
aws s3 cp "${SNAPSHOT_DIR}/${BUNDLE_FILE}" "s3://${BACKUPS_BUCKET}/${S3_KEY}" --region "$AWS_REGION"

log "Done. s3://${BACKUPS_BUCKET}/${S3_KEY}"
log "Local copy retained at ${SNAPSHOT_DIR}/${BUNDLE_FILE} - contains student names, identifiers and full chat transcripts inside dump/ and logs/; delete it once you no longer need it on this box."
