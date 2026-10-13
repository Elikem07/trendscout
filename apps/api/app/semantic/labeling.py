"""LLM labeling of discovered niches (M2.T4).

Grounding contract (architecture section 7): the LLM receives listing
titles and tags and returns ONLY language — a human readable label and
representative keywords, schema validated. Cached in llm_generations by
input hash; a cluster is labeled at most once per distinct membership.
"""

import hashlib
import json
import re
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Keyword, Listing, LLMGeneration, Niche, NicheKeyword
from app.ids import uuid7

LABEL_MODEL = "claude-sonnet-4-6"


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicLLM:
    def __init__(self, model: str = LABEL_MODEL) -> None:
        self.model = model
        self._http = httpx.Client(
            base_url="https://api.anthropic.com",
            headers={
                "x-api-key": get_settings().anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=30.0,
        )

    def complete(self, system: str, user: str) -> str:  # pragma: no cover
        resp = self._http.post(
            "/v1/messages",
            json={
                "model": self.model,
                "max_tokens": 300,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        parts = resp.json()["content"]
        return "".join(p.get("text", "") for p in parts)


class NicheLabel(BaseModel):
    label: str = Field(min_length=3, max_length=60)
    keywords: list[str] = Field(min_length=3, max_length=8)


SYSTEM = (
    "You name product niches for a marketplace research tool. Given listing "
    "titles and tags from one cluster, respond with ONLY a JSON object: "
    '{"label": <2-4 word niche name>, "keywords": [<3-8 short search phrases>]}. '
    "No prose, no markdown fences."
)


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or "niche"


def _grounding(session: Session, niche: Niche, sample: int = 15) -> dict[str, Any]:
    rows = session.execute(
        select(Listing.title, Listing.tags).where(Listing.niche_id == niche.id).limit(sample)
    ).all()
    return {
        "titles": [r[0] for r in rows],
        "tags": sorted({t for r in rows for t in r[1]})[:30],
    }


def label_niche(session: Session, llm: LLMClient, niche: Niche) -> NicheLabel:
    payload = _grounding(session, niche)
    input_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    cached = session.scalar(
        select(LLMGeneration).where(
            LLMGeneration.niche_id == niche.id,
            LLMGeneration.kind == "niche_label",
            LLMGeneration.input_hash == input_hash,
        )
    )
    if cached is not None:
        parsed = NicheLabel.model_validate(cached.output)
    else:
        raw = llm.complete(SYSTEM, json.dumps(payload))
        try:
            parsed = NicheLabel.model_validate_json(raw.strip())
        except ValidationError as exc:
            raise ValueError(f"LLM label failed validation: {exc}") from exc
        session.add(
            LLMGeneration(
                niche_id=niche.id,
                kind="niche_label",
                input_hash=input_hash,
                output=parsed.model_dump(),
                model=LABEL_MODEL,
            )
        )

    niche.label = parsed.label
    base = slugify(parsed.label)
    slug, n = base, 2
    while session.scalar(select(Niche.id).where(Niche.slug == slug, Niche.id != niche.id)):
        slug, n = f"{base}-{n}", n + 1
    niche.slug = slug

    for phrase in parsed.keywords:
        keyword = session.scalar(select(Keyword).where(Keyword.phrase == phrase))
        if keyword is None:
            keyword = Keyword(id=uuid7(), phrase=phrase, category=niche.category)
            session.add(keyword)
            session.flush()
        if not session.get(NicheKeyword, (niche.id, keyword.id)):
            session.add(NicheKeyword(niche_id=niche.id, keyword_id=keyword.id, similarity=1.0))
    session.commit()
    return parsed


def label_unlabeled(session: Session, llm: LLMClient, limit: int = 50) -> int:
    niches = session.scalars(
        select(Niche)
        .where(Niche.status == "active", Niche.label.like("unlabeled cluster%"))
        .limit(limit)
    ).all()
    count = 0
    for niche in niches:
        try:
            label_niche(session, llm, niche)
            count += 1
        except ValueError:
            continue  # retried next run with fresh membership hash
    return count
