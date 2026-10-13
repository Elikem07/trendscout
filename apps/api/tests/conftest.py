"""Test fixtures.

Auth and webhook tests need a real database (CI provides a Postgres
service; local dev uses docker compose). Schema is brought to alembic head
once per session; user rows are truncated between tests.
"""

import os
import subprocess

import pytest
from sqlalchemy import text

os.environ.setdefault(
    "DATABASE_URL", "postgresql://trendscout:trendscout@localhost:5432/trendscout"
)
os.environ.setdefault("CLERK_ISSUER", "https://test-issuer.clerk.local")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MDAwMDAwMDAwMDAwMDAwMDAwMDAwMA==")

from app.db.session import get_engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> None:
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@pytest.fixture
def clean_users() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE api_keys, users CASCADE"))
