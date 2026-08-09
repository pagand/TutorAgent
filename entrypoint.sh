#!/bin/bash
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting uvicorn..."
# --proxy-headers/--forwarded-allow-ips so X-Forwarded-Proto from nginx is
# honored (nginx is the only thing that can reach this container's port).
# --no-access-log because app/main.py's request-logging middleware already emits
# one structured line per request; uvicorn's own access log would be the same
# information again in a second format, and docker-compose.yml's x-logging anchor
# caps this container at 10MB x 3.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --no-access-log
