"""In-process catalog faults. S1 injects immediately; S2 will gate on unseal."""

from __future__ import annotations

import json
import time
from typing import Any

CATALOG: dict[str, dict[str, Any]] = {
    "redis_down": {
        "default_duration_s": 15,
        "params": {},
    },
    "handler_latency": {
        "default_duration_s": 5,
        "params": {"delay_ms": 300},
    },
    "worker_drop": {
        "default_duration_s": 15,
        "params": {"drop_rate": 0.2},
    },
}

MAX_DURATION_S = 20
FAULTS_KEY = "sealed:faults"


class UnknownCatalogId(ValueError):
    pass


class Faults:
    def __init__(self) -> None:
        self._active: dict[str, dict[str, Any]] = {}

    def expire(self) -> None:
        now = time.time()
        self._active = {k: v for k, v in self._active.items() if v["until"] > now}

    def inject(
        self,
        catalog_id: str,
        duration_s: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if catalog_id not in CATALOG:
            raise UnknownCatalogId(catalog_id)
        spec = CATALOG[catalog_id]
        dur = spec["default_duration_s"] if duration_s is None else float(duration_s)
        dur = min(max(dur, 0.001), float(MAX_DURATION_S))
        merged = {**spec["params"], **(params or {})}
        rec = {"until": time.time() + dur, "params": merged, "duration_s": dur}
        self._active = {catalog_id: rec}
        return {"id": catalog_id, **rec}

    def is_active(self, catalog_id: str) -> bool:
        self.expire()
        return catalog_id in self._active

    def param(self, catalog_id: str, key: str, default: Any = None) -> Any:
        self.expire()
        rec = self._active.get(catalog_id)
        if not rec:
            return default
        return rec["params"].get(key, default)

    def clear(self) -> None:
        self._active = {}

    def snapshot(self) -> dict[str, Any]:
        self.expire()
        return {
            k: {"until": v["until"], "params": v["params"]}
            for k, v in self._active.items()
        }


async def publish_faults(redis: Any, faults: Faults) -> None:
    if faults.is_active("redis_down"):
        return
    try:
        await redis.set(FAULTS_KEY, json.dumps(faults.snapshot()))
    except Exception:
        return
