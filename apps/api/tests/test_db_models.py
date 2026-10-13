"""Schema level assertions that do not require a database connection."""

from app.db import models
from app.db.base import Base


def test_expected_tables_registered() -> None:
    assert {"users", "sources", "api_keys"} <= set(Base.metadata.tables.keys())


def test_constraints_have_deterministic_names() -> None:
    """Naming convention applied: unnamed constraints break autogenerate."""
    users = Base.metadata.tables["users"]
    names = {c.name for c in users.constraints}
    assert "pk_users" in names
    assert "uq_users_clerk_id" in names
    assert "uq_users_email" in names


def test_api_keys_fk_targets_users() -> None:
    fks = list(Base.metadata.tables["api_keys"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "users"
    assert models.ApiKey.__table__.indexes  # user_id lookup index exists
