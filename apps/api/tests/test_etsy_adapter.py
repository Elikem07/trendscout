"""Etsy adapter against recorded responses; quota budget against Redis."""

import json
import pathlib
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import Listing, ListingSnapshot, Shop
from app.db.session import get_engine, get_sessionmaker
from app.ingest.budget import BudgetExhausted, RateBudget
from app.ingest.etsy import EtsyClient, EtsyListingsAdapter
from app.ingest.normalize import transform_etsy_listings
from app.ingest.runner import run_ingest

CASSETTES = pathlib.Path(__file__).parent / "cassettes"


def cassette_transport() -> httpx.MockTransport:
    pages = [
        json.loads((CASSETTES / "etsy_active_p1.json").read_text()),
        json.loads((CASSETTES / "etsy_active_p2.json").read_text()),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == get_settings().etsy_api_key
        offset = int(dict(request.url.params).get("offset", 0))
        page = pages[0] if offset == 0 else pages[1]
        return httpx.Response(200, json=page)

    return httpx.MockTransport(handler)


def fresh_budget(cap: int = 1000) -> RateBudget:
    b = RateBudget(f"etsy-test-{uuid.uuid4().hex[:6]}", cap)
    return b


def make_adapter(cap: int = 1000) -> EtsyListingsAdapter:
    return EtsyListingsAdapter(
        keyword="moss wall art",
        client=EtsyClient(transport=cassette_transport()),
        budget=fresh_budget(cap),
    )


@pytest.fixture
def clean_catalog() -> None:
    from sqlalchemy import text

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE listing_snapshots, listings, shops, "
                "raw_ingest_archive, ingest_runs CASCADE"
            )
        )


def test_adapter_pages_to_exhaustion() -> None:
    adapter = make_adapter()
    p1 = adapter.fetch_batch(None)
    assert len(p1.records) == 2 and p1.next_cursor == "2"
    assert p1.records[0].kind == "listing"
    assert p1.records[0].external_id == "101"
    p2 = adapter.fetch_batch(p1.next_cursor)
    assert len(p2.records) == 1 and p2.next_cursor is None


def test_budget_spent_before_call_and_exhausts() -> None:
    adapter = make_adapter(cap=1)
    adapter.fetch_batch(None)
    assert adapter.budget.spent() == 1
    with pytest.raises(BudgetExhausted):
        adapter.fetch_batch("2")


def test_budget_refund_keeps_cap_exact() -> None:
    b = fresh_budget(cap=2)
    b.acquire()
    b.acquire()
    with pytest.raises(BudgetExhausted):
        b.acquire()
    assert b.spent() == 2  # failed acquire refunded


def test_redis_backing_shared_across_instances() -> None:
    name = f"etsy-shared-{uuid.uuid4().hex[:6]}"
    a = RateBudget(name, 10)
    b = RateBudget(name, 10)
    a.acquire(4)
    assert b.spent() == 4


def test_full_pipeline_ingest_normalize(clean_catalog: None) -> None:
    run = run_ingest(make_adapter(), get_sessionmaker(), transform=transform_etsy_listings)
    assert run.status == "success" and run.records_fetched == 3

    with get_sessionmaker()() as s:
        assert s.scalar(select(func.count(Listing.id))) == 3
        assert s.scalar(select(func.count(Shop.id))) == 2
        assert s.scalar(select(func.count(ListingSnapshot.listing_id))) == 3
        one = s.scalar(select(Listing).where(Listing.external_id == "101"))
        assert one is not None
        assert one.price_usd == Decimal("45.00")
        assert one.tags == ["moss", "wall art"]
        assert one.favorites_count == 12
        assert one.shop_id is not None


def test_normalize_idempotent_and_snapshot_updates(clean_catalog: None) -> None:
    run_ingest(make_adapter(), get_sessionmaker(), transform=transform_etsy_listings)
    run_ingest(make_adapter(), get_sessionmaker(), transform=transform_etsy_listings)
    with get_sessionmaker()() as s:
        assert s.scalar(select(func.count(Listing.id))) == 3  # no dupes
        assert s.scalar(select(func.count(ListingSnapshot.listing_id))) == 3
        assert s.scalar(select(func.count(Shop.id))) == 2


def test_fulltext_generated_column(clean_catalog: None) -> None:
    run_ingest(make_adapter(), get_sessionmaker(), transform=transform_etsy_listings)
    from sqlalchemy import text

    with get_engine().connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM listings "
                "WHERE search_tsv @@ plainto_tsquery('english', 'moss wall')"
            )
        ).scalar()
    assert n == 3
