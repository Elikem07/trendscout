"""Declarative base with a stable naming convention.

Explicit constraint names make Alembic autogenerate deterministic: without
them, Postgres invents names and every autogenerate run sees phantom drift.
"""

import datetime
import uuid

from sqlalchemy import MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.ids import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PKMixin:
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
