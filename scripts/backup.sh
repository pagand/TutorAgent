#!/usr/bin/env bash
set -euo pipefail

# scripts/backup.sh — dumps the Postgres DB to a timestamped file, prunes old
# dumps past the retention window, and optionally uploads to S3. Safe to run
# from cron: exits non-zero on failure so cron mail is meaningful.
#
# Local dev / EC2 direct:  DATABASE_URL must point at a reachable Postgres.
# Docker Compose (EC2 prod): set DOCKER_DB_SERVICE=db so pg_dump runs inside
# the db container instead — Postgres's 5432 is intentionally not exposed to
# the host (PRELAUNCH_CHECKLIST.md section D), so it can't be reached directly.
#
# Env vars:
#   BACKUP_DIR              default ./backups
#   BACKUP_RETENTION_DAYS   default 14
#   BACKUP_S3_URI           optional, e.g. s3://my-bucket/aitutor-backups — set in Stage 4
#   DOCKER_DB_SERVICE       optional, e.g. db — use the compose service instead of DATABASE_URL
#   POSTGRES_USER/POSTGRES_DB   required when DOCKER_DB_SERVICE is set

BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="${BACKUP_DIR}/aitutor_${TIMESTAMP}.dump"

mkdir -p "$BACKUP_DIR"

if [ -n "${DOCKER_DB_SERVICE:-}" ]; then
  : "${POSTGRES_USER:?POSTGRES_USER must be set when using DOCKER_DB_SERVICE}"
  : "${POSTGRES_DB:?POSTGRES_DB must be set when using DOCKER_DB_SERVICE}"
  docker compose exec -T "$DOCKER_DB_SERVICE" \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$DUMP_FILE"
else
  : "${DATABASE_URL:?DATABASE_URL must be set}"
  PG_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"
  pg_dump -Fc "$PG_URL" > "$DUMP_FILE"
fi

echo "Backup written: $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"

# Prune dumps older than the retention window
find "$BACKUP_DIR" -name 'aitutor_*.dump' -type f -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete

if [ -n "${BACKUP_S3_URI:-}" ]; then
  aws s3 cp "$DUMP_FILE" "${BACKUP_S3_URI%/}/$(basename "$DUMP_FILE")"
  echo "Uploaded to ${BACKUP_S3_URI%/}/$(basename "$DUMP_FILE")"
fi
