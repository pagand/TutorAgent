#!/usr/bin/env bash
set -euo pipefail

# scripts/snapshot_restore.sh BUNDLE_FILE
#
# Restores a scripts/snapshot.sh bundle onto a FRESH box: Postgres (via the
# existing scripts/restore.sh, unchanged) plus the chroma_data Docker volume
# (vector store + llm_cache.db). Assumes the box already exists and its
# containers are up - Terraform + ec2-bootstrap.sh create the box and start
# it with an empty database; this script brings that empty box up to the
# snapshot's captured state (docs/OPS_RUNBOOK.html has the full sequence,
# including the alembic ordering hazard).
#
# This is a NEW script, not an extension of restore.sh, on purpose:
# restore.sh's whole reason for existing is "restore Postgres, nothing else,
# explicit target required, no default" - a small, safety-reviewed,
# single-purpose script. Bolting volume handling, log/CSV extraction, and
# multi-step orchestration onto it would turn a script whose safety
# property is easy to audit at a glance into one that isn't, for both the
# old callers and the new one. This script instead CALLS restore.sh for the
# Postgres half rather than duplicating pg_restore logic.
#
# Same safety property as restore.sh: BUNDLE_FILE is a required, explicit
# argument (no "latest in S3" default), and POSTGRES_USER/POSTGRES_DB must be
# set explicitly. There is no path through this script that picks a target
# on its own.
#
# Does NOT restore prod/data from the bundle. On a rebuilt box, prod/data
# arrives via ec2-bootstrap.sh's S3 sync from the ops bucket - the bundle's
# prod_data/ copy is a point-in-time record for analysis/audit, not a
# restore source (see the bundle's own README.md).
#
# Env vars:
#   POSTGRES_USER, POSTGRES_DB   required - passed straight through to restore.sh
#   AWS_REGION                   default us-west-2
#
# Usage (on the box, repo root, containers already up from ec2-bootstrap.sh):
#   POSTGRES_USER=aitutor POSTGRES_DB=aitutor_db \
#     ./scripts/snapshot_restore.sh s3://aitutor-backups-<account>/snapshots/aitutor_snapshot_<ts>.tar.gz
#
# BUNDLE_FILE may be a local path (already downloaded) or an s3:// URI, which
# is downloaded first.

BUNDLE_FILE="${1:?Usage: POSTGRES_USER=... POSTGRES_DB=... $0 BUNDLE_FILE (local path or s3:// URI)}"
: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${POSTGRES_DB:?POSTGRES_DB must be set}"
AWS_REGION="${AWS_REGION:-us-west-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[snapshot_restore] $*"; }

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aitutor_snapshot_restore.XXXXXX")"
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

LOCAL_BUNDLE="$BUNDLE_FILE"
if [[ "$BUNDLE_FILE" == s3://* ]]; then
  LOCAL_BUNDLE="${WORK_DIR}/$(basename "$BUNDLE_FILE")"
  log "Downloading $BUNDLE_FILE"
  aws s3 cp "$BUNDLE_FILE" "$LOCAL_BUNDLE" --region "$AWS_REGION"
fi

[ -f "$LOCAL_BUNDLE" ] || { echo "Bundle file not found: $LOCAL_BUNDLE" >&2; exit 1; }

log "Unpacking $LOCAL_BUNDLE"
tar xzf "$LOCAL_BUNDLE" -C "$WORK_DIR"

# find | head under pipefail can SIGPIPE the find side if it ever produced
# more than head wants; read the first match via process substitution
# instead so there's no pipe to close early.
BUNDLE_ROOT=""
while IFS= read -r d; do BUNDLE_ROOT="$d"; break; done \
  < <(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d -name 'aitutor_snapshot_*')
[ -n "$BUNDLE_ROOT" ] || { echo "Unrecognized bundle layout: no aitutor_snapshot_* directory found after unpacking" >&2; exit 1; }

# --- 1. Postgres, via the existing restore.sh, unchanged ---
DUMP_FILE=""
while IFS= read -r f; do DUMP_FILE="$f"; break; done \
  < <(find "${BUNDLE_ROOT}/dump" -name 'aitutor_*.dump')
[ -n "$DUMP_FILE" ] || { echo "No Postgres dump found in bundle under dump/" >&2; exit 1; }

log "Restoring Postgres from $DUMP_FILE"
DOCKER_DB_SERVICE=db POSTGRES_USER="$POSTGRES_USER" POSTGRES_DB="$POSTGRES_DB" \
  "${SCRIPT_DIR}/restore.sh" "$DUMP_FILE"

# --- 2. chroma_data volume: resolve the real volume name, stop api, untar in, restart ---
CHROMA_ARCHIVE="${BUNDLE_ROOT}/chroma_data.tar.gz"
if [ ! -f "$CHROMA_ARCHIVE" ]; then
  log "WARNING: bundle has no chroma_data.tar.gz (snapshot.sh could not capture the volume at the time) - skipping vector store / llm_cache.db restore."
else
  log "Resolving chroma_data volume from the api container's mounts"
  API_CID="$(docker compose ps -q api || true)"
  [ -n "$API_CID" ] || { echo "api container not found - bring the stack up first (ec2-bootstrap.sh / docker compose up -d)" >&2; exit 1; }
  CHROMA_VOLUME="$(docker inspect --format '{{ range .Mounts }}{{ if eq .Destination "/app/chroma_db" }}{{ .Name }}{{ end }}{{ end }}' "$API_CID")"
  [ -n "$CHROMA_VOLUME" ] || { echo "api container does not mount /app/chroma_db - cannot resolve chroma_data volume" >&2; exit 1; }

  log "Stopping api to restore chroma_data volume: $CHROMA_VOLUME"
  docker compose stop api
  # --clean first: this replaces the volume's contents with the snapshot's,
  # it does not merge - a freshly-booted box's chroma_db is regenerable
  # ingestion output, not data to preserve.
  docker run --rm \
    -v "${CHROMA_VOLUME}:/target" \
    -v "${BUNDLE_ROOT}:/backup:ro" \
    alpine:3 \
    sh -c "find /target -mindepth 1 -delete; tar xzf /backup/chroma_data.tar.gz -C /target"
  log "Restarting api"
  docker compose start api
fi

log "Done. Postgres and (if present) chroma_data restored from $LOCAL_BUNDLE."
log "Verify with: docker compose exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB -c 'SELECT COUNT(*) FROM users;'"
log "The extracted bundle (including its csv/ export) was under $WORK_DIR - already removed on exit. Re-download and untar the same bundle yourself if you need a full per-table comparison against its CSVs."
log "Reminder: prod/data was NOT restored from this bundle (by design) - it arrives via ec2-bootstrap.sh's S3 sync from the ops bucket."
