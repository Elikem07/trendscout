"""Celery task logic, dead lettering, retention wiring, DQ report."""

import datetime

import pytest
from sqlalchemy import func, select, text

from app.db.models import DeadLetter
from app.db.session import get_engine, get_sessionmaker
from app.dq import run_report
from app.worker import celery_app, dead_letter, ingest_etsy_keyword, retention_sweep


@pytest.fixture
def clean_all() -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE dead_letters, listing_snapshots, listings, shops, "
                "raw_ingest_archive, ingest_runs CASCADE"
            )
        )


@pytest.fixture(autouse=True)
def eager() -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False


def seeded_pipeline() -> None:
    from app.ingest.normalize import transform_etsy_listings
    from app.ingest.runner import run_ingest
    from tests.test_etsy_adapter import make_adapter

    run_ingest(make_adapter(), get_sessionmaker(), transform=transform_etsy_listings)


def test_dead_letter_written(clean_all: None) -> None:
    dead_letter("ingest_etsy_keyword", {"keyword": "x"}, "boom")
    with get_sessionmaker()() as s:
        row = s.scalar(select(DeadLetter))
        assert row is not None
        assert row.task_name == "ingest_etsy_keyword"
        assert row.args == {"keyword": "x"}
        assert row.error == "boom"


def test_budget_exhausted_is_deferred_not_retried(
    clean_all: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.worker as w

    class FakeRun:
        status, error, records_fetched = "failed", "BudgetExhausted: cap", 0

    monkeypatch.setattr(w, "run_ingest", lambda *a, **k: FakeRun())
    assert ingest_etsy_keyword.apply(args=("moss",)).result == "deferred"
    with get_sessionmaker()() as s:
        assert (s.scalar(select(func.count(DeadLetter.id))) or 0) == 0


def test_crawl_plan_interleaves_categories() -> None:
    from app.data.seed_keywords import SEED_KEYWORDS, all_keywords, crawl_plan

    plan = crawl_plan()
    assert len(plan) == len(all_keywords()) >= 150
    first_eight = plan[: len(SEED_KEYWORDS)]
    firsts = {kws[0] for kws in SEED_KEYWORDS.values()}
    assert set(first_eight) == firsts  # one keyword per category first


def test_retention_sweep_drops_old_partitions(clean_all: None) -> None:
    from app.db.partitions import ensure_monthly_partition

    with get_engine().begin() as conn:
        ensure_monthly_partition(conn, "raw_ingest_archive", datetime.date(2025, 6, 1))
        ensure_monthly_partition(conn, "listing_snapshots", datetime.date(2024, 1, 1))
    result = retention_sweep.apply().result
    assert "raw_ingest_archive_y2025m06" in result["raw_ingest_archive"]
    assert "listing_snapshots_y2024m01" in result["listing_snapshots"]


def test_dq_report_fails_on_empty_db(clean_all: None) -> None:
    with get_sessionmaker()() as s:
        report = run_report(s)
    assert report["passed"] is False
    names = {c["name"]: c["passed"] for c in report["checks"]}
    assert names["freshness:etsy"] is False


def test_dq_report_passes_after_pipeline(clean_all: None) -> None:
    seeded_pipeline()
    with get_sessionmaker()() as s:
        report = run_report(s)
    assert report["passed"] is True, report
