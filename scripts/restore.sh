#!/usr/bin/env bash
set -euo pipefail

# scripts/restore.sh DUMP_FILE TARGET_DATABASE_URL
# Restores a pg_dump -Fc archive (from backup.sh) into TARGET_DATABASE_URL with
# --clean --if-exists. TARGET_DATABASE_URL is a required, explicit argument —
# there is no default target, so this script cannot silently overwrite
# production by being run with a stale environment.
#
# Docker Compose: set DOCKER_DB_SERVICE=db and omit the second argument;
# POSTGRES_USER/POSTGRES_DB from the environment select the target instead,
# matching backup.sh's Docker path.

if [ -n "${DOCKER_DB_SERVICE:-}" ]; then
  DUMP_FILE="${1:?Usage: DOCKER_DB_SERVICE=db $0 DUMP_FILE}"
  [ -f "$DUMP_FILE" ] || { echo "Dump file not found: $DUMP_FILE" >&2; exit 1; }
  : "${POSTGRES_USER:?POSTGRES_USER must be set when using DOCKER_DB_SERVICE}"
  : "${POSTGRES_DB:?POSTGRES_DB must be set when using DOCKER_DB_SERVICE}"
  docker compose exec -T "$DOCKER_DB_SERVICE" \
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < "$DUMP_FILE"
else
  DUMP_FILE="${1:?Usage: $0 DUMP_FILE TARGET_DATABASE_URL}"
  TARGET_URL="${2:?Usage: $0 DUMP_FILE TARGET_DATABASE_URL}"
  [ -f "$DUMP_FILE" ] || { echo "Dump file not found: $DUMP_FILE" >&2; exit 1; }
  PG_URL="${TARGET_URL/postgresql+asyncpg:\/\//postgresql://}"
  pg_restore --clean --if-exists -d "$PG_URL" "$DUMP_FILE"
fi

echo "Restored $DUMP_FILE"
