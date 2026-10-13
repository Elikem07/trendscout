"""Celery application: queues, tasks, schedule, dead lettering (M1.T4).

Queues: ingest (source crawls), compute (M2/M3 jobs), notify (M6).
Retry policy: transient task failures retry with exponential backoff up
to 3 times; terminal failures are written to dead_letters for manual
replay. BudgetExhausted is terminal by design (tomorrow's budget will
cover it), not an error worth retrying.
"""

import datetime
import logging
from typing import Any

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings
from app.db.models import DeadLetter
from app.db.partitions import drop_partitions_before
from app.db.session import get_engine, get_sessionmaker
from app.ingest.budget import BudgetExhausted
from app.ingest.etsy import EtsyListingsAdapter
from app.ingest.normalize import transform_etsy_listings
from app.ingest.runner import run_ingest

logger = logging.getLogger(__name__)

celery_app = Celery("trendscout", broker=get_settings().redis_url)
celery_app.conf.update(
    task_default_queue="ingest",
    task_routes={
        "app.worker.ingest_etsy_keyword": {"queue": "ingest"},
        "app.worker.dispatch_daily_crawl": {"queue": "ingest"},
        "app.worker.retention_sweep": {"queue": "compute"},
        "app.worker.nightly_compute": {"queue": "compute"},
        "app.worker.etsy_keepalive": {"queue": "ingest"},
    },
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "daily-etsy-crawl": {
            "task": "app.worker.dispatch_daily_crawl",
            "schedule": crontab(hour=6, minute=0),
        },
        "etsy-keepalive": {  # dormancy guard, DEPENDENCIES.md item 1
            "task": "app.worker.etsy_keepalive",
            "schedule": crontab(day_of_week=1, hour=5, minute=0),
        },
        "retention-sweep": {
            "task": "app.worker.retention_sweep",
            "schedule": crontab(hour=3, minute=30),
        },
        "nightly-compute": {  # after the 6:00 crawl finishes
            "task": "app.worker.nightly_compute",
            "schedule": crontab(hour=9, minute=0),
        },
    },
)


def dead_letter(task_name: str, args: dict[str, Any], error: str) -> None:
    with get_sessionmaker()() as session:
        session.add(DeadLetter(task_name=task_name, args=args, error=error))
        session.commit()
    logger.error("dead lettered %s(%s): %s", task_name, args, error)


@celery_app.task(bind=True, max_retries=3, retry_backoff=60, retry_backoff_max=900)
def ingest_etsy_keyword(self: Any, keyword: str) -> str:
    run = run_ingest(
        EtsyListingsAdapter(keyword=keyword),
        get_sessionmaker(),
        transform=transform_etsy_listings,
    )
    if run.status == "failed":
        error = run.error or "unknown"
        if "BudgetExhausted" in error:
            logger.info("budget exhausted; %r deferred to tomorrow", keyword)
            return "deferred"
        if self.request.retries >= 3:
            dead_letter("ingest_etsy_keyword", {"keyword": keyword}, error)
            return "dead-lettered"
        raise self.retry(exc=RuntimeError(error))
    return f"ok:{run.records_fetched}"


@celery_app.task
def dispatch_daily_crawl() -> int:
    from app.data.seed_keywords import crawl_plan

    plan = crawl_plan()
    for kw in plan:
        ingest_etsy_keyword.delay(kw)
    return len(plan)


@celery_app.task
def etsy_keepalive() -> str:
    try:
        run = run_ingest(
            EtsyListingsAdapter(keyword="handmade", max_records=1),
            get_sessionmaker(),
        )
        return run.status
    except BudgetExhausted:
        return "deferred"


@celery_app.task
def nightly_compute() -> dict[str, int]:
    """Embed -> cluster -> label -> aggregate -> score, in order."""
    import datetime

    from app.config import get_settings
    from app.scoring.engine import compute_scores
    from app.semantic.aggregate import compute_niche_daily_signals
    from app.semantic.clustering import cluster_category
    from app.semantic.embedding import SentenceTransformerEmbedder, embed_pending_listings
    from app.semantic.labeling import AnthropicLLM, label_unlabeled

    stats: dict[str, int] = {}
    with get_sessionmaker()() as session:
        stats["embedded"] = embed_pending_listings(session, SentenceTransformerEmbedder())
        stats["niches_created"] = cluster_category(session)["niches_created"]
        if get_settings().anthropic_api_key != "unset":
            stats["labeled"] = label_unlabeled(session, AnthropicLLM())
        stats["signals"] = compute_niche_daily_signals(session)
        stats["scored"] = compute_scores(session, datetime.date.today())
    return stats


@celery_app.task
def retention_sweep() -> dict[str, list[str]]:
    today = datetime.date.today()
    with get_engine().begin() as conn:
        return {
            "raw_ingest_archive": drop_partitions_before(
                conn, "raw_ingest_archive", today - datetime.timedelta(days=90)
            ),
            "listing_snapshots": drop_partitions_before(
                conn, "listing_snapshots", today - datetime.timedelta(days=548)
            ),
        }
