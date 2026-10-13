"""M4 API endpoints via ASGI test client with auth override."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.auth import get_current_user
from app.db.models import Niche, User
from app.db.session import get_engine, get_sessionmaker
from app.ids import uuid7
from app.main import app
from app.scoring.engine import compute_scores
from tests.test_scoring import TODAY, four_personas


@pytest.fixture
def client() -> TestClient:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE watchlist_items, scores, revenue_estimates, "
                "niche_daily_signals, listings, niches, users CASCADE"
            )
        )
    with get_sessionmaker()() as s:
        user = User(id=uuid7(), clerk_id="user_test", email="t@example.com")
        s.add(user)
        s.commit()
        uid = user.id

    def fake_user() -> User:
        with get_sessionmaker()() as s:
            found = s.get(User, uid)
            assert found is not None
            return found

    app.dependency_overrides[get_current_user] = fake_user
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def scored(client: TestClient) -> dict[str, object]:
    ids = four_personas()
    with get_sessionmaker()() as s:
        compute_scores(s, TODAY)
    return ids


def test_list_niches_sorted_and_filtered(client: TestClient, scored: dict) -> None:
    r = client.get("/api/v1/niches")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 4
    opps = [n["score"]["opportunity"] for n in body]
    assert opps == sorted(opps, reverse=True)
    r = client.get("/api/v1/niches", params={"label": "emerging"})
    assert [n["slug"] for n in r.json()] == ["emerging-a"]


def test_niche_detail_history_and_revenue(client: TestClient, scored: dict) -> None:
    r = client.get("/api/v1/niches/hot-d")
    assert r.status_code == 200
    body = r.json()
    assert body["score"]["trend_label"] in ("rising", "flat", "hot", "emerging")
    assert len(body["history"]) >= 1
    assert body["revenue_low_usd"] is not None
    assert body["revenue_low_usd"] < body["revenue_high_usd"]
    assert client.get("/api/v1/niches/nope").status_code == 404


def test_feeds_endpoint(client: TestClient, scored: dict) -> None:
    r = client.get("/api/v1/feeds/emerging")
    assert r.status_code == 200
    assert "emerging-a" in [n["slug"] for n in r.json()]
    assert client.get("/api/v1/feeds/bogus").status_code == 404


def test_watchlist_crud(client: TestClient, scored: dict) -> None:
    with get_sessionmaker()() as s:
        nid = str(s.scalars(select(Niche.id)).first())
    assert client.get("/api/v1/watchlist").json() == []
    assert client.post("/api/v1/watchlist", json={"niche_id": nid}).status_code == 201
    # idempotent add
    assert client.post("/api/v1/watchlist", json={"niche_id": nid}).status_code == 201
    items = client.get("/api/v1/watchlist").json()
    assert len(items) == 1 and items[0]["id"] == nid
    assert client.delete(f"/api/v1/watchlist/{nid}").status_code == 204
    assert client.get("/api/v1/watchlist").json() == []


def test_search_requires_min_length_and_finds_titles(client: TestClient, scored: dict) -> None:
    assert client.get("/api/v1/search", params={"q": "x"}).status_code == 422
    # four_personas seeds signals only; search needs listings -> seed some
    from app.db.models import Listing, Source

    with get_sessionmaker()() as s:
        source_id = s.execute(select(Source.id).where(Source.code == "etsy")).scalar_one()
        niche = s.scalars(select(Niche).where(Niche.slug == "emerging-a")).one()
        for i in range(3):
            s.add(
                Listing(
                    id=uuid7(),
                    source_id=source_id,
                    external_id=f"S{i}",
                    title=f"handmade moss terrarium kit {i}",
                    tags=[],
                    niche_id=niche.id,
                    status="active",
                )
            )
        s.commit()
    r = client.get("/api/v1/search", params={"q": "moss terrarium"})
    assert r.status_code == 200
    assert r.json()[0]["slug"] == "emerging-a"
