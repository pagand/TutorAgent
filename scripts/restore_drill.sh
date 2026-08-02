#!/usr/bin/env bash
set -euo pipefail

# scripts/restore_drill.sh [DUMP_FILE]
# A backup that has never been restored is not a backup. Creates a scratch
# database on the same Postgres server as DATABASE_URL, restores the most
# recent dump (or the one given) into it, compares every public-schema
# table's row count against the source DB, reports any mismatch, then drops
# the scratch database.
#
# Local dev / EC2 direct only — Docker Compose's Postgres is not reachable
# from the host by design (5432 stays unexposed), so this always runs against
# DATABASE_URL, never DOCKER_DB_SERVICE.

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DUMP_FILE="${1:-$(ls -t "$BACKUP_DIR"/aitutor_*.dump 2>/dev/null | head -n1)}"
if [ -z "$DUMP_FILE" ] || [ ! -f "$DUMP_FILE" ]; then
  echo "No dump file found in $BACKUP_DIR. Run backup.sh first, or pass a path." >&2
  exit 1
fi

: "${DATABASE_URL:?DATABASE_URL must be set}"
SOURCE_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"
BASE_URL="${SOURCE_URL%/*}"

SCRATCH_DB="aitutor_restore_drill_$(date -u +%Y%m%d%H%M%S)"
SCRATCH_URL="${BASE_URL}/${SCRATCH_DB}"

echo "Creating scratch DB: $SCRATCH_DB"
psql "$SOURCE_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$SCRATCH_DB\";" > /dev/null

cleanup() {
  echo "Dropping scratch DB: $SCRATCH_DB"
  psql "$SOURCE_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\";" > /dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Restoring $DUMP_FILE into $SCRATCH_DB"
pg_restore -d "$SCRATCH_URL" "$DUMP_FILE"

TABLES=$(psql "$SOURCE_URL" -tAc "SELECT tablename FROM pg_tables WHERE schemaname='public'")

echo
printf '%-25s %12s %12s %s\n' "table" "source" "scratch" "status"
MISMATCH=0
for t in $TABLES; do
  SRC_COUNT=$(psql "$SOURCE_URL" -tAc "SELECT COUNT(*) FROM \"$t\"")
  DST_COUNT=$(psql "$SCRATCH_URL" -tAc "SELECT COUNT(*) FROM \"$t\"" 2>/dev/null || echo "ERR")
  STATUS="OK"
  if [ "$SRC_COUNT" != "$DST_COUNT" ]; then
    STATUS="MISMATCH"
    MISMATCH=1
  fi
  printf '%-25s %12s %12s %s\n' "$t" "$SRC_COUNT" "$DST_COUNT" "$STATUS"
done

if [ "$MISMATCH" -eq 1 ]; then
  echo
  echo "RESTORE DRILL FAILED: row count mismatch found." >&2
  exit 1
fi

echo
echo "Restore drill passed: all table row counts match."
