"""Monthly range partition management.

Partitioned tables (raw_ingest_archive now; snapshot and signal tables in
later milestones) get child partitions created on demand by the writers
and dropped by retention jobs. Child partitions follow the naming pattern
<table>_yYYYYmMM, which migrations/env.py excludes from drift detection.
"""

import datetime

from sqlalchemy import Connection, text

PARTITION_SUFFIX = "_y{year:04d}m{month:02d}"


def month_start(day: datetime.date) -> datetime.date:
    return day.replace(day=1)


def next_month(day: datetime.date) -> datetime.date:
    first = month_start(day)
    return (first + datetime.timedelta(days=32)).replace(day=1)


def partition_name(table: str, day: datetime.date) -> str:
    return table + PARTITION_SUFFIX.format(year=day.year, month=day.month)


def ensure_monthly_partition(conn: Connection, table: str, day: datetime.date) -> str:
    """Create the partition covering `day` if absent. Returns its name."""
    name = partition_name(table, day)
    start = month_start(day)
    end = next_month(day)
    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF {table} "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )
    )
    return name


def drop_partitions_before(conn: Connection, table: str, cutoff: datetime.date) -> list[str]:
    """Drop child partitions whose entire range is before `cutoff`.
    Returns dropped partition names. Used by retention jobs."""
    rows = conn.execute(
        text(
            "SELECT c.relname FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = :table"
        ),
        {"table": table},
    ).scalars()

    dropped: list[str] = []
    prefix = f"{table}_y"
    for name in rows:
        if not name.startswith(prefix):
            continue
        year = int(name[len(prefix) : len(prefix) + 4])
        month = int(name[len(prefix) + 5 : len(prefix) + 7])
        part_end = next_month(datetime.date(year, month, 1))
        if part_end <= month_start(cutoff):
            conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
            dropped.append(name)
    return dropped
