"""Niche discovery: assign listings to niches by embedding geometry.

Two phase nightly job per category:
1. Adopt: unassigned listings within ADOPT_THRESHOLD cosine distance of
   an existing niche centroid join that niche (keeps clusters stable
   across reruns instead of re-deriving the world nightly).
2. Discover: HDBSCAN over the remaining unassigned embeddings creates
   new niches; HDBSCAN noise stays unassigned for a future night.
Centroids are recomputed from members after both phases.
"""

import uuid

import numpy as np
from sklearn.cluster import HDBSCAN
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import Listing, Niche
from app.ids import uuid7

ADOPT_THRESHOLD = 0.25  # cosine distance
MIN_CLUSTER_SIZE = 5


def _unassigned(session: Session, category: str | None) -> list[Listing]:
    q = select(Listing).where(
        Listing.niche_id.is_(None),
        Listing.embedding.is_not(None),
        Listing.status == "active",
    )
    if category is not None:
        q = q.where(Listing.category == category)
    return list(session.scalars(q).all())


def _adopt_into_existing(session: Session, listings: list[Listing]) -> int:
    niches = session.scalars(
        select(Niche).where(Niche.status == "active", Niche.centroid.is_not(None))
    ).all()
    if not niches:
        return 0
    centroids = np.array([n.centroid for n in niches])
    centroids = centroids / np.linalg.norm(centroids, axis=1, keepdims=True)
    adopted = 0
    for listing in listings:
        v = np.array(listing.embedding)
        v = v / np.linalg.norm(v)
        dists = 1 - centroids @ v
        best = int(np.argmin(dists))
        if dists[best] <= ADOPT_THRESHOLD:
            listing.niche_id = niches[best].id
            adopted += 1
    session.commit()
    return adopted


def _discover_new(session: Session, listings: list[Listing], category: str | None) -> int:
    remaining = [li for li in listings if li.niche_id is None]
    if len(remaining) < MIN_CLUSTER_SIZE:
        return 0
    x = np.array([li.embedding for li in remaining])
    x = x / np.linalg.norm(x, axis=1, keepdims=True)
    labels = HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE, metric="euclidean", allow_single_cluster=True
    ).fit_predict(x)

    created = 0
    for label in sorted(set(labels)):
        if label == -1:
            continue
        members = [remaining[i] for i in range(len(remaining)) if labels[i] == label]
        niche = Niche(
            id=uuid7(),
            label=f"unlabeled cluster {uuid.uuid4().hex[:6]}",
            slug=f"cluster-{uuid.uuid4().hex[:10]}",
            category=category,
            discovered_via="clustering",
        )
        session.add(niche)
        session.flush()
        for m in members:
            m.niche_id = niche.id
        created += 1
    session.commit()
    return created


def recompute_centroids(session: Session) -> None:
    niche_ids = session.scalars(select(Niche.id).where(Niche.status == "active")).all()
    for nid in niche_ids:
        vectors = [
            list(v)
            for v in session.scalars(
                select(Listing.embedding).where(
                    Listing.niche_id == nid, Listing.embedding.is_not(None)
                )
            ).all()
            if v is not None
        ]
        if vectors:
            centroid = np.mean(np.array(vectors), axis=0)
            session.execute(update(Niche).where(Niche.id == nid).values(centroid=centroid.tolist()))
    session.commit()


def cluster_category(session: Session, category: str | None = None) -> dict[str, int]:
    listings = _unassigned(session, category)
    adopted = _adopt_into_existing(session, listings)
    created = _discover_new(session, listings, category)
    recompute_centroids(session)
    noise = session.scalar(
        select(func.count(Listing.id)).where(
            Listing.niche_id.is_(None), Listing.embedding.is_not(None)
        )
    )
    return {"adopted": adopted, "niches_created": created, "noise": int(noise or 0)}
