"""Keyword <-> niche mapping via embedding similarity (M2.T6)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Keyword, Niche, NicheKeyword
from app.semantic.embedding import Embedder

MAP_THRESHOLD = 0.35  # max cosine distance to link keyword to niche


def embed_pending_keywords(session: Session, embedder: Embedder) -> int:
    rows = session.scalars(select(Keyword).where(Keyword.embedding.is_(None))).all()
    if not rows:
        return 0
    vectors = embedder.embed([r.phrase for r in rows])
    for row, vec in zip(rows, vectors, strict=True):
        row.embedding = vec
    session.commit()
    return len(rows)


def map_keyword_to_niches(session: Session, keyword: Keyword, top_n: int = 5) -> int:
    """Link a keyword to its nearest niches by centroid distance (pgvector)."""
    if keyword.embedding is None:
        return 0
    rows = session.execute(
        select(
            Niche.id,
            Niche.centroid.cosine_distance(keyword.embedding).label("dist"),
        )
        .where(Niche.status == "active", Niche.centroid.is_not(None))
        .order_by("dist")
        .limit(top_n)
    ).all()
    linked = 0
    for nid, dist in rows:
        if dist is None or dist > MAP_THRESHOLD:
            continue
        if not session.get(NicheKeyword, (nid, keyword.id)):
            session.add(
                NicheKeyword(niche_id=nid, keyword_id=keyword.id, similarity=1 - float(dist))
            )
            linked += 1
    session.commit()
    return linked


def niches_for_keyword(session: Session, phrase: str) -> list[Niche]:
    keyword = session.scalar(select(Keyword).where(Keyword.phrase == phrase))
    if keyword is None:
        return []
    return list(
        session.scalars(
            select(Niche)
            .join(NicheKeyword, NicheKeyword.niche_id == Niche.id)
            .where(NicheKeyword.keyword_id == keyword.id)
            .order_by(NicheKeyword.similarity.desc())
        ).all()
    )
