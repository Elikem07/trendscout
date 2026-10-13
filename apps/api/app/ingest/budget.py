"""Per source daily quota budgets, Redis backed.

Each source gets a hard daily spend cap (default 80% of the provider's
quota) so a runaway crawl can never exhaust the real limit. Counters
reset naturally by keying on the UTC date.
"""

import datetime
from typing import cast

import redis

from app.config import get_settings


class BudgetExhausted(Exception):
    def __init__(self, source: str, cap: int) -> None:
        super().__init__(f"{source} daily budget exhausted (cap={cap})")
        self.source, self.cap = source, cap


class RateBudget:
    def __init__(self, source: str, daily_cap: int, client: redis.Redis | None = None):
        self.source = source
        self.daily_cap = daily_cap
        self._redis = client or redis.Redis.from_url(get_settings().redis_url)

    def _key(self) -> str:
        return f"quota:{self.source}:{datetime.date.today().isoformat()}"

    def spent(self) -> int:
        return int(cast(int | None, self._redis.get(self._key())) or 0)

    def acquire(self, cost: int = 1) -> None:
        """Reserve quota or raise. Atomic via INCRBY; refunds on overshoot
        so concurrent callers cannot jointly exceed the cap."""
        key = self._key()
        new_total = cast(int, self._redis.incrby(key, cost))
        if new_total == cost:
            self._redis.expire(key, 172800)  # 2 days, self cleaning
        if new_total > self.daily_cap:
            self._redis.decrby(key, cost)
            raise BudgetExhausted(self.source, self.daily_cap)
