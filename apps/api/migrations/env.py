"""Alembic environment. Reads DATABASE_URL via app settings so migrations,
API, and workers can never disagree about which database they target."""

import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import models  # noqa: F401  (imports register all tables)
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_PARTITION_CHILD = re.compile(r".+_y\d{4}m\d{2}$")


def include_name(name, type_, parent_names):  # type: ignore[no-untyped-def]
    is_partition_child = type_ == "table" and name is not None and _PARTITION_CHILD.match(name)
    return not is_partition_child


def _url() -> str:
    return get_settings().database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_server_default=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
