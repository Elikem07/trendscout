"""SourceAdapter contract tests against a fake adapter (M1.T1 acceptance)."""

import datetime
from typing import ClassVar

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import RawIngestArchive, Source
from app.db.partitions import (
    drop_partitions_before,
    ensure_monthly_partition,
    partition_name,
)
from app.db.session import get_engine, get_sessionmaker
from app.ingest.base import FetchResult, RawRecord, SourceAdapter
from app.ingest.runner import run_ingest


def rec(i: int) -> RawRecord:
    return RawRecord(kind="listing", external_id=f"ext-{i}", payload={"n": i})


class FakeAdapter(SourceAdapter):
    code: ClassVar[str] = "etsy"  # seeded source

    def __init__(self, pages: list[list[RawRecord]]) -> None:
        self.pages = pages

    def fetch_batch(self, cursor: str | None) -> FetchResult:
        idx = int(cursor or 0)
        nxt = str(idx + 1) if idx + 1 < len(self.pages) else None
        return FetchResult(records=self.pages[idx], next_cursor=nxt)


class ExplodingAdapter(FakeAdapter):
    def fetch_batch(self, cursor: str | None) -> FetchResult:
        if cursor == "1":
            raise RuntimeError("source returned 500")
        return super().fetch_batch(cursor)


@pytest.fixture
def clean_ingest() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE raw_ingest_archive, ingest_runs"))


def archive_count(session: Session) -> int:
    return session.scalar(select(func.count(RawIngestArchive.id))) or 0


def test_two_page_run_success(clean_ingest: None) -> None:
    adapter = FakeAdapter([[rec(1), rec(2)], [rec(3)]])
    run = run_ingest(adapter, get_sessionmaker())

    assert run.status == "success"
    assert run.records_fetched == 3
    assert run.error is None
    assert run.finished_at is not None

    with get_sessionmaker()() as session:
        rows = session.scalars(select(RawIngestArchive)).all()
        assert len(rows) == 3
        assert {r.external_id for r in rows} == {"ext-1", "ext-2", "ext-3"}
        assert all(r.run_id == run.id for r in rows)
        assert all(r.payload["n"] in (1, 2, 3) for r in rows)
        source = session.scalar(select(Source).where(Source.code == "etsy"))
        assert source is not None and all(r.source_id == source.id for r in rows)


def test_archive_committed_before_transform(clean_ingest: None) -> None:
    """The acceptance invariant: at transform time, the records it is
    handed are already durably archived (visible from a separate
    connection, i.e. committed, not just flushed)."""
    seen: list[tuple[int, int]] = []

    def transform(session: Session, records: list[RawRecord]) -> None:
        with get_sessionmaker()() as separate:  # separate connection
            seen.append((archive_count(separate), len(records)))

    run = run_ingest(
        FakeAdapter([[rec(1), rec(2)], [rec(3)]]),
        get_sessionmaker(),
        transform=transform,
    )
    assert run.status == "success"
    assert seen == [(2, 2), (3, 1)]  # archived count >= handed count, per batch


def test_midrun_failure_recorded_and_prior_pages_kept(clean_ingest: None) -> None:
    run = run_ingest(ExplodingAdapter([[rec(1), rec(2)], [rec(3)]]), get_sessionmaker())

    assert run.status == "failed"
    assert run.error is not None and "source returned 500" in run.error
    assert run.records_fetched == 2  # page 1 counted
    with get_sessionmaker()() as session:
        assert archive_count(session) == 2  # page 1 archived despite failure


def test_transform_failure_marks_run_failed_but_archive_survives(
    clean_ingest: None,
) -> None:
    def bad_transform(session: Session, records: list[RawRecord]) -> None:
        raise ValueError("transform bug")

    run = run_ingest(FakeAdapter([[rec(1)]]), get_sessionmaker(), transform=bad_transform)
    assert run.status == "failed"
    assert run.error is not None and "transform bug" in run.error
    with get_sessionmaker()() as session:
        assert archive_count(session) == 1


def test_unknown_source_code_raises(clean_ingest: None) -> None:
    class BadAdapter(FakeAdapter):
        code: ClassVar[str] = "does-not-exist"

    with pytest.raises(ValueError, match="Unknown source"):
        run_ingest(BadAdapter([[rec(1)]]), get_sessionmaker())


def test_max_batches_guard(clean_ingest: None) -> None:
    class InfiniteAdapter(SourceAdapter):
        code: ClassVar[str] = "etsy"

        def fetch_batch(self, cursor: str | None) -> FetchResult:
            return FetchResult(records=[rec(0)], next_cursor="again")

    run = run_ingest(InfiniteAdapter(), get_sessionmaker(), max_batches=3)
    assert run.status == "failed"
    assert run.error is not None and "max_batches" in run.error
    assert run.records_fetched == 3


def test_partition_lifecycle() -> None:
    table = RawIngestArchive.__tablename__
    old = datetime.date(2025, 1, 15)
    with get_engine().begin() as conn:
        name = ensure_monthly_partition(conn, table, old)
        assert name == partition_name(table, old) == f"{table}_y2025m01"
        # idempotent
        assert ensure_monthly_partition(conn, table, old) == name

    with get_engine().begin() as conn:
        dropped = drop_partitions_before(
            conn, table, datetime.date.today() - datetime.timedelta(days=90)
        )
    assert f"{table}_y2025m01" in dropped

    with get_engine().begin() as conn:
        current = ensure_monthly_partition(conn, table, datetime.date.today())
        remaining = drop_partitions_before(
            conn, table, datetime.date.today() - datetime.timedelta(days=90)
        )
    assert current not in remaining  # current month never dropped
