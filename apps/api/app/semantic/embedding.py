"""Embedding backends behind one interface.

Production: bge-small-en-v1.5 via sentence-transformers (384d, CPU).
Tests and environments without model weights: injected vectors or the
deterministic fake. Nothing outside this module knows which is in use.
"""

import hashlib
from typing import Protocol

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Listing

DIM = 384


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Real backend. Lazy import so the heavy dependency (and model
    download) is only required where it is actually used (workers)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "sentence-transformers not installed; pip install "
                "sentence-transformers, or inject another Embedder"
            ) from exc
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        vectors = self._model.encode(texts, normalize_embeddings=True)
        result: list[list[float]] = vectors.tolist()
        return result


class DeterministicFakeEmbedder:
    """Hash seeded unit vectors: stable across runs, unique per text.
    Carries no semantics; tests needing geometry inject vectors directly."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "big")
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(DIM)
            out.append((v / np.linalg.norm(v)).tolist())
        return out


def listing_text(title: str, tags: list[str]) -> str:
    return f"{title} | {' '.join(tags)}"


def embed_pending_listings(session: Session, embedder: Embedder, batch_size: int = 256) -> int:
    """Embed listings without vectors. Returns how many were embedded."""
    total = 0
    while True:
        rows = session.scalars(
            select(Listing).where(Listing.embedding.is_(None)).limit(batch_size)
        ).all()
        if not rows:
            return total
        vectors = embedder.embed([listing_text(r.title, r.tags) for r in rows])
        for row, vec in zip(rows, vectors, strict=True):
            row.embedding = vec
        session.commit()
        total += len(rows)
