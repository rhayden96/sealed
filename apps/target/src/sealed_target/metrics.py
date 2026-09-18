"""Business observations share one bounded time window and sample population."""

from collections import deque
from collections.abc import Callable
import math
import time
from typing import Any, TypedDict


class Sample(TypedDict):
    duration_ms: float
    error: bool
    route: str
    run_id: str | None
    at: float


class Metrics:
    def __init__(self, *, window_s: float = 60, limit: int = 200, clock: Callable[[], float] = time.time) -> None:
        self.window_s = window_s
        self.limit = limit
        self.clock = clock
        self.samples: deque[Sample] = deque(maxlen=limit)
        self.inflight = 0

    def record(self, duration_ms: float, error: bool, *, route: str, run_id: str | None = None) -> None:
        self.samples.append({"duration_ms": duration_ms, "error": error, "route": route, "run_id": run_id, "at": self.clock()})

    @staticmethod
    def _summary(samples: list[Sample]) -> dict[str, Any]:
        ordered = sorted(sample["duration_ms"] for sample in samples)
        return {
            "sample_count": len(samples),
            "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None,
            "error_rate": sum(sample["error"] for sample in samples) / len(samples) if samples else None,
            "first_at": min((sample["at"] for sample in samples), default=None),
            "last_at": max((sample["at"] for sample in samples), default=None),
        }

    def snapshot(self, *, run_id: str | None = None, since: float | None = None) -> dict[str, Any]:
        now = self.clock()
        cutoff = max(now - self.window_s, since or 0)
        while self.samples and self.samples[0]["at"] < now - self.window_s:
            self.samples.popleft()
        samples = [sample for sample in self.samples if sample["at"] >= cutoff and (run_id is None or sample["run_id"] == run_id)]
        routes = {route: self._summary([sample for sample in samples if sample["route"] == route]) for route in sorted({sample["route"] for sample in samples})}
        return {**self._summary(samples), "inflight": self.inflight, "window_s": self.window_s, "limit": self.limit, "observed_at": now, "run_id": run_id, "routes": routes}
