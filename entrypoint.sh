#!/bin/bash
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting uvicorn..."
# --proxy-headers/--forwarded-allow-ips so X-Forwarded-Proto from nginx is
# honored (nginx is the only thing that can reach this container's port).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
