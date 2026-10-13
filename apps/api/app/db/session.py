"""Engine and session factory. Sync engine for now; workers and API share it.

Async is a deliberate non decision until an endpoint measurably needs it:
psycopg3 + SQLAlchemy 2 make the switch mechanical later.
"""

from collections.abc import Generator, Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    with get_sessionmaker()() as session:
        yield session


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with get_sessionmaker()() as session:
        yield session
