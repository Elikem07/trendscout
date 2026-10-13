#!/bin/sh
# Container entrypoint: apply migrations, then serve.
# Safe for a single instance MVP. When replicas > 1, move migration to a
# Railway pre deploy command so only one runner executes it (documented in
# DEPLOY.md); alembic itself is transactional either way.
set -e

echo "[start] applying migrations"
alembic upgrade head

echo "[start] starting api"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
