"""M2 semantic layer: clustering geometry, labeling contract + cache,
daily aggregation goldens, keyword mapping."""

import datetime
import json
import uuid as uuidlib

import numpy as np
import pytest
from sqlalchemy import func, select, text

from app.db.models import (
    Keyword,
    Listing,
    ListingSnapshot,
    LLMGeneration,
    Niche,
    NicheDailySignal,
    NicheKeyword,
    Shop,
    Source,
)
from app.db.partitions import ensure_monthly_partition
from app.db.session import get_engine, get_sessionmaker
from app.ids import uuid7
from app.semantic.aggregate import compute_niche_daily_signals
from app.semantic.clustering import cluster_category
from app.semantic.embedding import DIM, DeterministicFakeEmbedder, embed_pending_listings
from app.semantic.keywords import (
    embed_pending_keywords,
    map_keyword_to_niches,
    niches_for_keyword,
)
from app.semantic.labeling import label_niche

pytestmark = []


@pytest.fixture
def clean() -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE niche_daily_signals, niche_keywords, keywords, "
                "llm_generations, listing_snapshots, listings, niches, shops CASCADE"
            )
        )


def blob(center: np.ndarray, n: int, spread: float = 0.02) -> list[np.ndarray]:
    rng = np.random.default_rng(int(abs(center.sum()) * 1000) % 2**32)
    return [center + rng.standard_normal(DIM) * spread for _ in range(n)]


def seed_listings(vectors_by_group: dict[str, list[np.ndarray]]) -> None:
    batch = uuidlib.uuid4().hex[:6]
    with get_sessionmaker()() as s:
        source_id = s.execute(select(Source.id).where(Source.code == "etsy")).scalar_one()
        shop = s.scalar(select(Shop).where(Shop.external_id == "shop-1"))
        if shop is None:
            shop = Shop(id=uuid7(), source_id=source_id, external_id="shop-1")
            s.add(shop)
            s.flush()
        i = 0
        for group, vectors in vectors_by_group.items():
            for v in vectors:
                i += 1
                s.add(
                    Listing(
                        id=uuid7(),
                        source_id=source_id,
                        external_id=f"L-{batch}-{i}",
                        shop_id=shop.id,
                        title=f"{group} item {i}",
                        tags=[group],
                        category="home_decor",
                        price_usd=20 + i,
                        favorites_count=i,
                        status="active",
                        embedding=(v / np.linalg.norm(v)).tolist(),
                        listing_created_at=datetime.datetime.now(datetime.UTC)
                        - datetime.timedelta(days=10),
                    )
                )
        s.commit()


def three_centers() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(42)
    return {f"group{k}": rng.standard_normal(DIM) for k in range(3)}


def test_clustering_discovers_three_niches(clean: None) -> None:
    centers = three_centers()
    seed_listings({g: blob(c, 8) for g, c in centers.items()})
    with get_sessionmaker()() as s:
        result = cluster_category(s, "home_decor")
        assert result["niches_created"] == 3
        assert s.scalar(select(func.count(Niche.id))) == 3
        # every member of a group shares one niche
        for g in centers:
            nids = set(s.scalars(select(Listing.niche_id).where(Listing.tags.contains([g]))).all())
            assert len(nids) == 1 and None not in nids


def test_recluster_is_stable_and_adopts_new_members(clean: None) -> None:
    centers = three_centers()
    seed_listings({g: blob(c, 8) for g, c in centers.items()})
    with get_sessionmaker()() as s:
        cluster_category(s, "home_decor")
        before = dict(s.execute(select(Listing.external_id, Listing.niche_id)).all())
    # add two new listings near group0's center -> adopted, not new niche
    seed_listings({"group0late": blob(list(centers.values())[0], 2)})
    with get_sessionmaker()() as s:
        result = cluster_category(s, "home_decor")
        assert result["adopted"] == 2
        assert result["niches_created"] == 0
        after = dict(s.execute(select(Listing.external_id, Listing.niche_id)).all())
        for ext, nid in before.items():
            assert after[ext] == nid  # prior assignments untouched
        new_assignments = {after[e] for e in after if e not in before}
        g0_ids = set(
            s.scalars(select(Listing.niche_id).where(Listing.tags.contains(["group0"]))).all()
        )
        assert new_assignments == g0_ids


class ScriptedLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        payload = json.loads(user)
        assert "titles" in payload and "tags" in payload  # grounding present
        return self.response


def one_labeled_niche(s, llm) -> Niche:  # type: ignore[no-untyped-def]
    seed_listings({"moss": blob(three_centers()["group0"], 8)})
    cluster_category(s, "home_decor")
    niche = s.scalars(select(Niche)).one()
    label_niche(s, llm, niche)
    return niche


def test_labeling_contract_cache_and_keywords(clean: None) -> None:
    llm = ScriptedLLM(
        '{"label": "Moss Wall Art", "keywords": ["moss wall art", "preserved moss", "moss decor"]}'
    )
    with get_sessionmaker()() as s:
        niche = one_labeled_niche(s, llm)
        assert niche.label == "Moss Wall Art"
        assert niche.slug == "moss-wall-art"
        assert llm.calls == 1
        assert s.scalar(select(func.count(Keyword.id))) == 3
        assert s.scalar(select(func.count(NicheKeyword.keyword_id))) == 3
        # second call with identical membership hits cache
        label_niche(s, llm, niche)
        assert llm.calls == 1
        assert s.scalar(select(func.count(LLMGeneration.id))) == 1


def test_labeling_rejects_invalid_output(clean: None) -> None:
    llm = ScriptedLLM('{"label": "x"}')  # fails schema
    with get_sessionmaker()() as s:
        seed_listings({"moss": blob(three_centers()["group0"], 8)})
        cluster_category(s, "home_decor")
        niche = s.scalars(select(Niche)).one()
        with pytest.raises(ValueError, match="validation"):
            label_niche(s, llm, niche)
        assert s.scalar(select(func.count(LLMGeneration.id))) == 0  # not cached


def test_slug_collision_gets_suffix(clean: None) -> None:
    llm = ScriptedLLM('{"label": "Moss Wall Art", "keywords": ["moss wall art", "a", "b"]}')
    with get_sessionmaker()() as s:
        one_labeled_niche(s, llm)
        seed_listings({"other": blob(three_centers()["group1"], 8)})
        cluster_category(s, "home_decor")
        second = s.scalars(select(Niche).where(Niche.slug.like("cluster-%"))).one()
        label_niche(s, llm, second)
        assert second.slug == "moss-wall-art-2"


def test_daily_aggregation_golden(clean: None) -> None:
    """Hand computed expectations over a fixed fixture."""
    centers = three_centers()
    seed_listings({"g0": blob(centers["group0"], 8)})
    today = datetime.date.today()
    with get_sessionmaker()() as s:
        niche = Niche(id=uuid7(), label="Golden", slug="golden", category="home_decor")
        s.add(niche)
        s.flush()
        for listing in s.scalars(select(Listing)).all():
            listing.niche_id = niche.id
        s.commit()
        niche_id = niche.id
        ensure_monthly_partition(s.connection(), "listing_snapshots", today)
        for lid, fav in s.execute(select(Listing.id, Listing.favorites_count)).all():
            s.add(
                ListingSnapshot(
                    listing_id=lid,
                    date=today - datetime.timedelta(days=1),
                    favorites_count=fav - 1,
                    review_count=0,
                )
            )
            s.add(ListingSnapshot(listing_id=lid, date=today, favorites_count=fav, review_count=2))
        s.commit()
        n = compute_niche_daily_signals(s, today)
        assert n == 1
        row = s.get_one(NicheDailySignal, (niche_id, today))
        assert row.active_listings == 8
        assert row.favorites_delta == 8  # +1 per listing
        assert row.reviews_delta == 16  # +2 per listing
        assert row.young_listing_share == 1.0
        assert row.hhi == 1.0  # single shop owns everything
        assert float(row.median_price) == pytest.approx(24.5)  # prices 21..28
        # idempotent
        assert compute_niche_daily_signals(s, today) == 1
        assert s.scalar(select(func.count()).select_from(NicheDailySignal)) == 1


def test_keyword_embedding_and_mapping(clean: None) -> None:
    centers = three_centers()
    seed_listings({"g0": blob(centers["group0"], 6)})
    with get_sessionmaker()() as s:
        cluster_category(s, "home_decor")
        niche = s.scalars(select(Niche)).one()
        kw = Keyword(id=uuid7(), phrase="near group zero")
        s.add(kw)
        s.commit()
        # embed keyword right on the niche centroid -> must map
        kw.embedding = niche.centroid
        s.commit()
        assert map_keyword_to_niches(s, kw) == 1
        found = niches_for_keyword(s, "near group zero")
        assert [n.id for n in found] == [niche.id]

        far = Keyword(id=uuid7(), phrase="totally unrelated")
        s.add(far)
        s.commit()
        embed_pending_keywords(s, DeterministicFakeEmbedder())
        s.refresh(far)
        assert far.embedding is not None
        assert map_keyword_to_niches(s, far) == 0  # random vector: too distant


def test_embed_pending_listings_uses_injected_backend(clean: None) -> None:
    with get_sessionmaker()() as s:
        source_id = s.execute(select(Source.id).where(Source.code == "etsy")).scalar_one()
        s.add(
            Listing(
                id=uuid7(),
                source_id=source_id,
                external_id="pending-1",
                title="needs vector",
                tags=[],
            )
        )
        s.commit()
        assert embed_pending_listings(s, DeterministicFakeEmbedder()) == 1
        row = s.scalars(select(Listing).where(Listing.external_id == "pending-1")).one()
        assert row.embedding is not None and len(list(row.embedding)) == DIM
