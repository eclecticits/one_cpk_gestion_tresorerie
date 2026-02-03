#!/usr/bin/env sh
set -e

echo "[entrypoint] Checking Alembic revision..."
alembic current || {
  echo "[entrypoint] Alembic current failed" >&2
  exit 1
}

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head || {
  echo "[entrypoint] Alembic upgrade failed" >&2
  exit 1
}

echo "[entrypoint] Alembic revision after upgrade:"
alembic current || {
  echo "[entrypoint] Alembic current failed" >&2
  exit 1
}

echo "[entrypoint] Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
