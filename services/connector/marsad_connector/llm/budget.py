"""
A hard ceiling on model calls.

Why this exists
---------------
A public demo puts an LLM behind an HTTP endpoint on the open internet. Without a
ceiling that is someone else's free compute: anyone who finds the URL can spend the
operator's CPU indefinitely, and on a small VPS a handful of concurrent extractions is
enough to make the whole federation unresponsive.

Rate limiting at the edge (see deploy/caddy/Caddyfile) handles bursts from one client.
This handles the other case — sustained, distributed, or simply popular use — by
capping total calls in a window regardless of who makes them.

What happens when the budget is gone
------------------------------------
Extraction **falls back to the deterministic extractor**. It does not fail, and it does
not queue. That is the same stance the rest of the system takes: the connector is never
allowed to become the reason an institution cannot file an incident, and MARSAD is
additive by design. On this project's own measurements the deterministic path is the
more accurate one anyway (docs/model-path-results.md), so the degraded mode is not
much of a degradation — it is slower to nothing and better on most fields.

The fallback is recorded on the draft, never silent. `ExtractionDraft.method` says
which extractor ran, so an analyst and a reviewer can both tell.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger("marsad.llm.budget")


@dataclass(frozen=True)
class BudgetState:
    used: int
    limit: int
    window_seconds: int
    resets_at: datetime

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    def as_dict(self) -> dict:
        return {
            "used": self.used, "limit": self.limit, "remaining": self.remaining,
            "exhausted": self.exhausted, "window_seconds": self.window_seconds,
            "resets_at": self.resets_at.isoformat(),
        }


class CallBudget:
    """
    A counter with a window, and a lock because uvicorn serves concurrently.

    Deliberately in-process and deliberately simple. A distributed budget would need
    shared state, and shared state between connectors is exactly what this
    architecture refuses to have — two institutions must not be able to observe each
    other's usage. Each connector limits itself.
    """

    def __init__(self, limit: int, window_seconds: int = 86_400,
                 now: datetime | None = None) -> None:
        if limit < 0:
            raise ValueError("a negative budget is not a budget")
        self._limit = limit
        self._window = timedelta(seconds=window_seconds)
        self._window_seconds = window_seconds
        self._used = 0
        self._started = now or datetime.now(timezone.utc)
        self._lock = threading.Lock()

    def _roll(self, now: datetime) -> None:
        if now - self._started >= self._window:
            log.info("budget.window_reset used=%d limit=%d", self._used, self._limit)
            self._used = 0
            self._started = now

    def state(self, now: datetime | None = None) -> BudgetState:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._roll(now)
            return BudgetState(self._used, self._limit, self._window_seconds,
                               self._started + self._window)

    def try_spend(self, now: datetime | None = None) -> bool:
        """
        Claim one model call. False when the budget is gone.

        Claimed BEFORE the call rather than after, so a slow or hanging request still
        counts. Counting on completion would let a stream of timeouts run the budget
        past its ceiling — which is precisely the shape of an abusive request.
        """
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._roll(now)
            if self._used >= self._limit:
                log.warning(
                    "budget.exhausted limit=%d window_s=%d — falling back to the "
                    "deterministic extractor", self._limit, self._window_seconds,
                )
                return False
            self._used += 1
            return True


__all__ = ["BudgetState", "CallBudget"]
