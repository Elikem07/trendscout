"""Etsy Open API v3 adapter: active listing search by keyword.

Read only, public endpoints only (see DEPENDENCIES.md for the access
strategy). Every HTTP call spends from the daily RateBudget before it is
made. The transport is injectable so tests run against recorded
responses and CI never touches Etsy.
"""

from typing import Any, ClassVar

import httpx

from app.config import get_settings
from app.ingest.base import FetchResult, RawRecord, SourceAdapter
from app.ingest.budget import RateBudget

BASE_URL = "https://api.etsy.com/v3/application"
PAGE_SIZE = 100


class EtsyClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        settings = get_settings()
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"x-api-key": settings.etsy_api_key},
            timeout=15.0,
            transport=transport,
        )

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = self._http.get(path, params=params)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data


class EtsyListingsAdapter(SourceAdapter):
    """Pages through /listings/active for one keyword. Cursor = offset."""

    code: ClassVar[str] = "etsy"

    def __init__(
        self,
        keyword: str,
        client: EtsyClient | None = None,
        budget: RateBudget | None = None,
        max_records: int = 500,
    ) -> None:
        settings = get_settings()
        self.keyword = keyword
        self.client = client or EtsyClient()
        self.budget = budget or RateBudget(
            "etsy", int(settings.etsy_daily_quota * settings.quota_spend_ratio)
        )
        self.max_records = max_records

    def fetch_batch(self, cursor: str | None) -> FetchResult:
        offset = int(cursor or 0)
        self.budget.acquire()  # spend BEFORE the call
        data = self.client.get(
            "/listings/active",
            params={
                "keywords": self.keyword,
                "limit": PAGE_SIZE,
                "offset": offset,
                "state": "active",
            },
        )
        results: list[dict[str, Any]] = data.get("results", [])
        records = [
            RawRecord(
                kind="listing",
                external_id=str(item["listing_id"]),
                payload=item,
            )
            for item in results
        ]
        next_offset = offset + len(results)
        exhausted = (
            not results
            or next_offset >= int(data.get("count", 0))
            or next_offset >= self.max_records
        )
        return FetchResult(records=records, next_cursor=None if exhausted else str(next_offset))
