"""Stage 2: raw Etsy records -> canonical listings, shops, snapshots.

Idempotent by construction: upserts keyed on (source_id, external_id) and
(listing_id, date). Rerunning a batch can never duplicate rows.
"""

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Listing, ListingSnapshot, Shop, Source
from app.db.partitions import ensure_monthly_partition
from app.fx import to_usd
from app.ids import uuid7
from app.ingest.base import RawRecord


def _price_usd(payload: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    price = payload.get("price") or {}
    amount, divisor = price.get("amount"), price.get("divisor") or 100
    currency = price.get("currency_code")
    if amount is None or currency is None:
        return None, None
    return to_usd(Decimal(amount) / Decimal(divisor), currency), currency


def _epoch_to_dt(value: Any) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromtimestamp(int(value), tz=datetime.UTC)
    except (TypeError, ValueError):
        return None


def transform_etsy_listings(session: Session, records: list[RawRecord]) -> None:
    listings = [r for r in records if r.kind == "listing"]
    if not listings:
        return

    source_id = session.execute(select(Source.id).where(Source.code == "etsy")).scalar_one()
    today = datetime.date.today()
    ensure_monthly_partition(session.connection(), ListingSnapshot.__tablename__, today)

    # Shop stubs (name enriched by a later shop fetch task)
    shop_ext_ids = {str(r.payload["shop_id"]) for r in listings if r.payload.get("shop_id")}
    if shop_ext_ids:
        session.execute(
            pg_insert(Shop)
            .values(
                [
                    {"id": uuid7(), "source_id": source_id, "external_id": ext}
                    for ext in shop_ext_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
        )
    shop_map: dict[str, uuid.UUID] = {
        ext: sid
        for ext, sid in session.execute(
            select(Shop.external_id, Shop.id).where(
                Shop.source_id == source_id, Shop.external_id.in_(shop_ext_ids)
            )
        )
    }

    listing_rows = []
    for r in listings:
        p = r.payload
        usd, currency = _price_usd(p)
        listing_rows.append(
            {
                "id": uuid7(),
                "source_id": source_id,
                "external_id": str(p["listing_id"]),
                "shop_id": shop_map.get(str(p.get("shop_id"))),
                "title": p.get("title") or "",
                "url": p.get("url"),
                "price_usd": usd,
                "currency_orig": currency,
                "tags": p.get("tags") or [],
                "category": str(p["taxonomy_id"]) if p.get("taxonomy_id") else None,
                "listing_created_at": _epoch_to_dt(p.get("created_timestamp")),
                "status": p.get("state") or "active",
                "favorites_count": p.get("num_favorers"),
            }
        )
    stmt = pg_insert(Listing).values(listing_rows)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["source_id", "external_id"],
            set_={
                "title": stmt.excluded.title,
                "url": stmt.excluded.url,
                "price_usd": stmt.excluded.price_usd,
                "currency_orig": stmt.excluded.currency_orig,
                "tags": stmt.excluded.tags,
                "status": stmt.excluded.status,
                "favorites_count": stmt.excluded.favorites_count,
                "updated_at": stmt.excluded.updated_at,
            },
        )
    )

    ext_ids: list[str] = [str(row["external_id"]) for row in listing_rows]
    id_map: dict[str, uuid.UUID] = {
        ext: lid
        for ext, lid in session.execute(
            select(Listing.external_id, Listing.id).where(
                Listing.source_id == source_id, Listing.external_id.in_(ext_ids)
            )
        )
    }
    by_ext = {row["external_id"]: row for row in listing_rows}
    snap = pg_insert(ListingSnapshot).values(
        [
            {
                "listing_id": id_map[ext],
                "date": today,
                "price_usd": by_ext[ext]["price_usd"],
                "review_count": None,
                "favorites_count": by_ext[ext]["favorites_count"],
            }
            for ext in ext_ids
        ]
    )
    session.execute(
        snap.on_conflict_do_update(
            index_elements=["listing_id", "date"],
            set_={
                "price_usd": snap.excluded.price_usd,
                "favorites_count": snap.excluded.favorites_count,
            },
        )
    )
