"""ORM models. Schema source of truth: /docs architecture section 4.

M0.T3 scope: identity tables only (users, sources, api_keys). Catalog,
signal, and computed tables arrive with their milestones (M1, M2, M3).
"""

import datetime
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Date, ForeignKey, Index, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin
from app.ids import uuid7


class User(PKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    clerk_id: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    plan: Mapped[str] = mapped_column(Text, server_default=text("'free'"))
    stripe_customer_id: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")


class Source(PKMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)


class ApiKey(PKMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    key_hash: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    user: Mapped[User] = relationship(back_populates="api_keys")


class IngestRun(PKMixin, TimestampMixin, Base):
    """One execution of a source adapter. Operational visibility and the
    anchor for archived raw records."""

    __tablename__ = "ingest_runs"
    __table_args__ = (Index("ix_ingest_runs_source_started", "source_id", "started_at"),)

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    started_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default=text("'running'"))
    records_fetched: Mapped[int] = mapped_column(server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)


class RawIngestArchive(Base):
    """Raw API responses, archived before any transformation. Monthly
    range partitioned on fetched_at; 90 day retention via
    partitions.drop_partitions_before. Composite PK because Postgres
    requires the partition key in the primary key."""

    __tablename__ = "raw_ingest_archive"
    __table_args__ = (
        Index("ix_raw_ingest_archive_run", "run_id"),
        {"postgresql_partition_by": "RANGE (fetched_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, server_default=func.now()
    )
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingest_runs.id"))
    kind: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Shop(PKMixin, TimestampMixin, Base):
    __tablename__ = "shops"
    __table_args__ = (Index("uq_shops_source_external", "source_id", "external_id", unique=True),)

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, server_default=text("''"))
    url: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    total_sales_est: Mapped[int | None]
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class Listing(PKMixin, TimestampMixin, Base):
    __tablename__ = "listings"
    __table_args__ = (
        Index("uq_listings_source_external", "source_id", "external_id", unique=True),
        Index("ix_listings_shop", "shop_id"),
        Index("ix_listings_niche_status", "niche_id", "status"),
        Index("ix_listings_tags", "tags", postgresql_using="gin"),
        Index("ix_listings_tsv", "search_tsv", postgresql_using="gin"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(Text)
    shop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shops.id"))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    price_usd: Mapped[float | None] = mapped_column(Numeric(10, 2))
    currency_orig: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    category: Mapped[str | None] = mapped_column(Text)
    listing_created_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    review_count: Mapped[int | None]
    favorites_count: Mapped[int | None]
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', title)", persisted=True)
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    niche_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("niches.id"))


class ListingSnapshot(Base):
    """Daily per listing metrics. Monthly range partitioned on date;
    18 month retention (architecture section 4)."""

    __tablename__ = "listing_snapshots"
    __table_args__ = ({"postgresql_partition_by": "RANGE (date)"},)

    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    price_usd: Mapped[float | None] = mapped_column(Numeric(10, 2))
    review_count: Mapped[int | None]
    favorites_count: Mapped[int | None]


class DeadLetter(PKMixin, TimestampMixin, Base):
    """Tasks that exhausted retries. Reviewed manually; replayable."""

    __tablename__ = "dead_letters"

    task_name: Mapped[str] = mapped_column(Text)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error: Mapped[str] = mapped_column(Text)


class Niche(PKMixin, TimestampMixin, Base):
    __tablename__ = "niches"

    label: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    category: Mapped[str | None] = mapped_column(Text)
    centroid: Mapped[list[float] | None] = mapped_column(Vector(384))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    discovered_via: Mapped[str] = mapped_column(Text, server_default=text("'clustering'"))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("niches.id"))


class Keyword(PKMixin, TimestampMixin, Base):
    __tablename__ = "keywords"

    phrase: Mapped[str] = mapped_column(Text, unique=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    category: Mapped[str | None] = mapped_column(Text)


class NicheKeyword(Base):
    __tablename__ = "niche_keywords"

    niche_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id"), primary_key=True)
    similarity: Mapped[float] = mapped_column()


class SearchTrend(Base):
    """Search interest per keyword per day. Monthly partitioned."""

    __tablename__ = "search_trends"
    __table_args__ = ({"postgresql_partition_by": "RANGE (date)"},)

    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id"), primary_key=True)
    geo: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("'US'"))
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    interest: Mapped[float] = mapped_column()
    provider: Mapped[str | None] = mapped_column(Text)


class SocialSignal(Base):
    """Daily social activity per niche per source. Monthly partitioned."""

    __tablename__ = "social_signals"
    __table_args__ = ({"postgresql_partition_by": "RANGE (date)"},)

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    niche_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    mentions: Mapped[int] = mapped_column(server_default=text("0"))
    engagement: Mapped[int] = mapped_column(server_default=text("0"))
    top_urls: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class NicheDailySignal(Base):
    """The single aggregated input to scoring and forecasting.
    Monthly partitioned; kept forever (long term asset)."""

    __tablename__ = "niche_daily_signals"
    __table_args__ = ({"postgresql_partition_by": "RANGE (date)"},)

    niche_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    active_listings: Mapped[int] = mapped_column(server_default=text("0"))
    new_listings: Mapped[int] = mapped_column(server_default=text("0"))
    median_price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    price_iqr: Mapped[float | None] = mapped_column(Numeric(10, 2))
    favorites_delta: Mapped[int] = mapped_column(server_default=text("0"))
    reviews_delta: Mapped[int] = mapped_column(server_default=text("0"))
    hhi: Mapped[float | None] = mapped_column()
    top20_median_reviews: Mapped[float | None] = mapped_column()
    young_listing_share: Mapped[float | None] = mapped_column()
    search_interest: Mapped[float | None] = mapped_column()
    social_mentions: Mapped[int] = mapped_column(server_default=text("0"))
    social_engagement: Mapped[int] = mapped_column(server_default=text("0"))


class LLMGeneration(PKMixin, TimestampMixin, Base):
    """Cache for grounded LLM outputs, keyed by input hash."""

    __tablename__ = "llm_generations"
    __table_args__ = (
        Index("uq_llm_generations_key", "niche_id", "kind", "input_hash", unique=True),
    )

    niche_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("niches.id"))
    kind: Mapped[str] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(Text)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(Text)


class Score(Base):
    """Daily deterministic scores per niche. Monthly partitioned.
    algo_version pins the formula that produced the row."""

    __tablename__ = "scores"
    __table_args__ = (
        Index("ix_scores_date_opportunity", "date", text("opportunity DESC")),
        {"postgresql_partition_by": "RANGE (date)"},
    )

    niche_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    demand: Mapped[float] = mapped_column()
    competition: Mapped[float] = mapped_column()
    opportunity: Mapped[float] = mapped_column()
    momentum: Mapped[float] = mapped_column()
    confidence: Mapped[float] = mapped_column()
    trend_label: Mapped[str] = mapped_column(Text)
    algo_version: Mapped[str] = mapped_column(Text)
    subscores: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class RevenueEstimate(Base):
    """Monthly revenue range per niche per day. Ranges only, never a
    point estimate. Monthly partitioned."""

    __tablename__ = "revenue_estimates"
    __table_args__ = ({"postgresql_partition_by": "RANGE (date)"},)

    niche_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    low_usd: Mapped[float] = mapped_column(Numeric(12, 0))
    high_usd: Mapped[float] = mapped_column(Numeric(12, 0))
    basis: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Forecast(Base):
    """Demand forecasts (populated by M5.T5's model; schema ready now).
    Monthly partitioned."""

    __tablename__ = "forecasts"
    __table_args__ = ({"postgresql_partition_by": "RANGE (date)"},)

    niche_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    horizon_days: Mapped[int] = mapped_column(primary_key=True)
    predicted_demand: Mapped[float] = mapped_column()
    lo: Mapped[float] = mapped_column()
    hi: Mapped[float] = mapped_column()
    model_version: Mapped[str] = mapped_column(Text)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    niche_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
