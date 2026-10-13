"""Data quality report (M1.T6). Run via `make dq-report` or the daily
schedule; exit code 1 on any failing check so alerts can key off it."""

import datetime
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import IngestRun, Listing, ListingSnapshot, Source
from app.db.session import get_sessionmaker

FRESHNESS_HOURS = {"etsy": 26}  # sources with an expectation; others informational
MAX_NULL_PRICE_RATIO = 0.20
MAX_SNAPSHOT_GAP_RATIO = 0.30
PRICE_OUTLIER_USD = 10000


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def _freshness(session: Session) -> list[Check]:
    checks = []
    for code, max_hours in FRESHNESS_HOURS.items():
        last = session.scalar(
            select(func.max(IngestRun.finished_at))
            .join(Source, Source.id == IngestRun.source_id)
            .where(Source.code == code, IngestRun.status == "success")
        )
        if last is None:
            checks.append(Check(f"freshness:{code}", False, "no successful run ever"))
            continue
        age = datetime.datetime.now(datetime.UTC) - last
        checks.append(
            Check(
                f"freshness:{code}",
                age <= datetime.timedelta(hours=max_hours),
                f"last success {age.total_seconds() / 3600:.1f}h ago",
            )
        )
    return checks


def _listing_quality(session: Session) -> list[Check]:
    total = session.scalar(select(func.count(Listing.id))) or 0
    if total == 0:
        return [Check("listings:exist", False, "zero listings")]
    null_price = (
        session.scalar(select(func.count(Listing.id)).where(Listing.price_usd.is_(None))) or 0
    )
    empty_title = session.scalar(select(func.count(Listing.id)).where(Listing.title == "")) or 0
    outliers = (
        session.scalar(
            select(func.count(Listing.id)).where(
                (Listing.price_usd > PRICE_OUTLIER_USD) | (Listing.price_usd <= 0)
            )
        )
        or 0
    )
    return [
        Check("listings:exist", True, f"{total} rows"),
        Check(
            "listings:price_nulls",
            null_price / total <= MAX_NULL_PRICE_RATIO,
            f"{null_price}/{total} null prices",
        ),
        Check("listings:titles", empty_title == 0, f"{empty_title} empty titles"),
        Check("listings:price_outliers", outliers == 0, f"{outliers} outliers"),
    ]


def _snapshot_coverage(session: Session) -> list[Check]:
    active = session.scalar(select(func.count(Listing.id)).where(Listing.status == "active")) or 0
    if active == 0:
        return []
    today_snaps = (
        session.scalar(
            select(func.count(ListingSnapshot.listing_id)).where(
                ListingSnapshot.date == datetime.date.today()
            )
        )
        or 0
    )
    gap = 1 - (today_snaps / active)
    return [
        Check(
            "snapshots:coverage_today",
            gap <= MAX_SNAPSHOT_GAP_RATIO,
            f"{today_snaps}/{active} active listings snapshotted today",
        )
    ]


def run_report(session: Session) -> dict[str, Any]:
    checks = _freshness(session) + _listing_quality(session) + _snapshot_coverage(session)
    return {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "passed": all(c.passed for c in checks),
        "checks": [asdict(c) for c in checks],
    }


def main() -> int:
    with get_sessionmaker()() as session:
        report = run_report(session)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
