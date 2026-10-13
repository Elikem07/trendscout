"""Product API v1 (M4): niches, feeds, search, watchlist."""

import datetime
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db.models import (
    Listing,
    Niche,
    RevenueEstimate,
    Score,
    User,
    WatchlistItem,
)
from app.db.session import get_session
from app.scoring.feeds import FEEDS, feed

router = APIRouter(prefix="/api/v1", tags=["niches"])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


class ScoreOut(BaseModel):
    date: datetime.date
    demand: float
    competition: float
    opportunity: float
    momentum: float
    confidence: float
    trend_label: str
    algo_version: str
    subscores: dict[str, Any]


class NicheOut(BaseModel):
    id: uuid.UUID
    label: str
    slug: str
    category: str | None
    score: ScoreOut | None = None


class NicheDetailOut(NicheOut):
    history: list[ScoreOut]
    revenue_low_usd: float | None = None
    revenue_high_usd: float | None = None
    active_listings: int


def _score_out(s: Score) -> ScoreOut:
    return ScoreOut(
        date=s.date,
        demand=s.demand,
        competition=s.competition,
        opportunity=s.opportunity,
        momentum=s.momentum,
        confidence=s.confidence,
        trend_label=s.trend_label,
        algo_version=s.algo_version,
        subscores=s.subscores,
    )


def _latest_scores(session: Session) -> dict[uuid.UUID, Score]:
    rows = session.scalars(
        select(Score).distinct(Score.niche_id).order_by(Score.niche_id, Score.date.desc())
    ).all()
    return {r.niche_id: r for r in rows}


@router.get("/niches", response_model=list[NicheOut])
def list_niches(
    session: SessionDep,
    user: UserDep,
    category: str | None = None,
    label: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> list[NicheOut]:
    latest = _latest_scores(session)
    q = select(Niche).where(Niche.status == "active")
    if category:
        q = q.where(Niche.category == category)
    niches = session.scalars(q).all()
    out = []
    for n in niches:
        s = latest.get(n.id)
        if label and (s is None or s.trend_label != label):
            continue
        out.append(
            NicheOut(
                id=n.id,
                label=n.label,
                slug=n.slug,
                category=n.category,
                score=_score_out(s) if s else None,
            )
        )
    out.sort(key=lambda x: x.score.opportunity if x.score else -1, reverse=True)
    return out[offset : offset + limit]


@router.get("/niches/{slug}", response_model=NicheDetailOut)
def niche_detail(
    slug: str,
    session: SessionDep,
    user: UserDep,
) -> NicheDetailOut:
    niche = session.scalar(select(Niche).where(Niche.slug == slug))
    if niche is None:
        raise HTTPException(404, "niche not found")
    history = session.scalars(
        select(Score).where(Score.niche_id == niche.id).order_by(Score.date.desc()).limit(28)
    ).all()
    revenue = session.scalars(
        select(RevenueEstimate)
        .where(RevenueEstimate.niche_id == niche.id)
        .order_by(RevenueEstimate.date.desc())
        .limit(1)
    ).first()
    active = session.scalar(
        select(func.count(Listing.id)).where(
            Listing.niche_id == niche.id, Listing.status == "active"
        )
    )
    return NicheDetailOut(
        id=niche.id,
        label=niche.label,
        slug=niche.slug,
        category=niche.category,
        score=_score_out(history[0]) if history else None,
        history=[_score_out(s) for s in reversed(history)],
        revenue_low_usd=float(revenue.low_usd) if revenue else None,
        revenue_high_usd=float(revenue.high_usd) if revenue else None,
        active_listings=int(active or 0),
    )


@router.get("/feeds/{name}", response_model=list[NicheOut])
def get_feed(
    name: str,
    session: SessionDep,
    user: UserDep,
    day: datetime.date | None = None,
) -> list[NicheOut]:
    if name not in FEEDS:
        raise HTTPException(404, f"unknown feed; valid: {', '.join(FEEDS)}")
    scores = feed(session, name, day)
    niches = {
        n.id: n
        for n in session.scalars(select(Niche).where(Niche.id.in_([s.niche_id for s in scores])))
    }
    return [
        NicheOut(
            id=s.niche_id,
            label=niches[s.niche_id].label,
            slug=niches[s.niche_id].slug,
            category=niches[s.niche_id].category,
            score=_score_out(s),
        )
        for s in scores
        if s.niche_id in niches
    ]


@router.get("/search", response_model=list[NicheOut])
def search(
    session: SessionDep,
    user: UserDep,
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(20, le=50),
) -> list[NicheOut]:
    """Full text search over listing titles, ranked by matching listing
    count per niche."""
    matches = session.execute(
        select(Listing.niche_id, func.count(Listing.id).label("n"))
        .where(
            Listing.niche_id.is_not(None),
            Listing.search_tsv.op("@@")(func.plainto_tsquery("english", q)),
        )
        .group_by(Listing.niche_id)
        .order_by(func.count(Listing.id).desc())
        .limit(limit)
    ).all()
    latest = _latest_scores(session)
    niches = {
        n.id: n for n in session.scalars(select(Niche).where(Niche.id.in_([m[0] for m in matches])))
    }
    return [
        NicheOut(
            id=nid,
            label=niches[nid].label,
            slug=niches[nid].slug,
            category=niches[nid].category,
            score=_score_out(latest[nid]) if nid in latest else None,
        )
        for nid, _ in matches
        if nid in niches
    ]


class WatchlistAdd(BaseModel):
    niche_id: uuid.UUID


@router.get("/watchlist", response_model=list[NicheOut])
def get_watchlist(
    session: SessionDep,
    user: UserDep,
) -> list[NicheOut]:
    latest = _latest_scores(session)
    rows = session.scalars(
        select(Niche)
        .join(WatchlistItem, WatchlistItem.niche_id == Niche.id)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.created_at.desc())
    ).all()
    return [
        NicheOut(
            id=n.id,
            label=n.label,
            slug=n.slug,
            category=n.category,
            score=_score_out(latest[n.id]) if n.id in latest else None,
        )
        for n in rows
    ]


@router.post("/watchlist", status_code=201)
def add_to_watchlist(
    body: WatchlistAdd,
    session: SessionDep,
    user: UserDep,
) -> dict[str, str]:
    if session.get(Niche, body.niche_id) is None:
        raise HTTPException(404, "niche not found")
    if session.get(WatchlistItem, (user.id, body.niche_id)) is None:
        session.add(WatchlistItem(user_id=user.id, niche_id=body.niche_id))
        session.commit()
    return {"status": "watching"}


@router.delete("/watchlist/{niche_id}", status_code=204)
def remove_from_watchlist(
    niche_id: uuid.UUID,
    session: SessionDep,
    user: UserDep,
) -> None:
    item = session.get(WatchlistItem, (user.id, niche_id))
    if item is not None:
        session.delete(item)
        session.commit()
