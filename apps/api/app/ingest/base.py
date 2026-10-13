"""Source adapter contract.

Every data source (Etsy, eBay, Reddit, YouTube, trends provider)
implements this interface. The runner (runner.py) owns run tracking,
archival, and error handling; adapters own only fetching and pagination.
Adapters must be side effect free with respect to our database.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class RawRecord:
    """One fetched item, exactly as the source returned it.

    kind: source specific record type ("listing", "shop", "post", ...)
    external_id: the source's identifier, when it has one
    payload: unmodified response object; transformation happens downstream
    """

    kind: str
    payload: dict[str, Any]
    external_id: str | None = None


@dataclass(frozen=True)
class FetchResult:
    records: list[RawRecord] = field(default_factory=list)
    next_cursor: str | None = None


class SourceAdapter(ABC):
    """code must match a row in the sources table."""

    code: ClassVar[str]

    @abstractmethod
    def fetch_batch(self, cursor: str | None) -> FetchResult:
        """Fetch one page. cursor=None means the first page. Return
        next_cursor=None when there are no further pages."""
