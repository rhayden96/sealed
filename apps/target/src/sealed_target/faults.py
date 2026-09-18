"""Bounded run ownership and verified cleanup for the privileged target channel."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CATALOG: dict[str, dict[str, Any]] = {
    "redis_down": {"default_duration_s": 15, "params": {}},
    "handler_latency": {"default_duration_s": 5, "params": {"delay_ms": 300}},
    "worker_drop": {"default_duration_s": 15, "params": {"drop_rate": 0.2}},
}
MAX_DURATION_S = 20
MAX_DELAY_MS = 1000
FAULTS_KEY = "sealed:faults"
ACTIVE_KEY = "sealed:target:active"
RECEIPT_PREFIX = "sealed:target:run:"
RECEIPT_TTL_S = 120  # Longer than every signed delivery authorization.


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class FaultIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    id: Literal["redis_down", "handler_latency", "worker_drop"]
    duration_s: float = Field(gt=0, le=MAX_DURATION_S)
    params: dict[str, Any] = Field(default_factory=dict)
    authorization_expires_at: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_params(self) -> FaultIn:
        allowed = CATALOG[self.id]["params"]
        if set(self.params) - set(allowed):
            raise ValueError("unknown fault parameter")
        self.params = {**allowed, **self.params}
        for key, value in self.params.items():
            maximum = MAX_DELAY_MS if key == "delay_ms" else 1
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= maximum
            ):
                raise ValueError(f"{key} must be finite and between 0 and {maximum}")
        return self


class FaultConflict(Exception):
    pass


class CleanupPending(Exception):
    pass


class Faults:
    """Local effects stop immediately; ownership remains until cleanup is verified."""

    def __init__(self) -> None:
        self.active: dict[str, Any] | None = None
        self.stopped = asyncio.Event()

    def expire(self) -> None:
        if self.active and self.active["until"] <= time.time():
            self.stop()

    def stop(self) -> None:
        if self.active:
            self.active["status"] = "cleanup_pending"
        self.stopped.set()

    def restore(self, record: dict[str, Any]) -> None:
        body = FaultIn.model_validate(record["request"])
        ack = record["acknowledgement"]
        until = ack["until"]
        started_at = ack.get("started_at")
        if (
            isinstance(until, bool)
            or not isinstance(until, (float, int))
            or not math.isfinite(until)
            or until > body.authorization_expires_at
            or until > time.time() + MAX_DURATION_S
            or ack["run_id"] != body.run_id
            or ack["id"] != body.id
            or ack["params"] != body.params
            or ack["duration_s"] != body.duration_s
            or ack["status"] not in {"active", "cleanup_pending"}
            or (started_at is not None and (
                isinstance(started_at, bool)
                or not isinstance(started_at, (float, int))
                or not math.isfinite(started_at)
                or not 0 < started_at <= until
                or until - started_at > body.duration_s + 0.001
            ))
        ):
            raise ValueError("invalid persisted target authorization")
        self.active = copy.deepcopy(ack)
        self.stopped = asyncio.Event()
        if ack["status"] == "cleanup_pending":
            self.stopped.set()
        self.expire()

    def is_active(self, catalog_id: str) -> bool:
        self.expire()
        return bool(self.active and self.active["id"] == catalog_id and self.active["status"] == "active")

    def param(self, catalog_id: str, key: str, default: Any = None) -> Any:
        if not self.is_active(catalog_id):
            return default
        return self.active["params"].get(key, default)

    async def wait_latency(self) -> None:
        if not self.is_active("handler_latency"):
            return
        remaining = self.active["until"] - time.time()
        delay = min(self.active["params"]["delay_ms"] / 1000, remaining)
        if delay > 0:
            try:
                await asyncio.wait_for(self.stopped.wait(), timeout=delay)
            except TimeoutError:
                pass

    def snapshot(self) -> dict[str, Any]:
        self.expire()
        if not self.active or self.active["status"] != "active":
            return {}
        return {self.active["id"]: copy.deepcopy(self.active)}


class FaultCoordinator:
    """One target process owns Redis-backed receipts and a single active run.

    The active journal survives target restarts. Receipts reject delayed delivery
    after cancellation, even when cancellation arrived before injection.
    """

    def __init__(self, redis: Any, faults: Faults) -> None:
        self.redis = redis
        self.faults = faults
        self.lock = asyncio.Lock()
        self.initialized = False
        self.record: dict[str, Any] | None = None
        self.last_error: str | None = None

    async def _initialize(self) -> None:
        if self.initialized:
            return
        raw = await self.redis.get(ACTIVE_KEY)
        if raw:
            record = json.loads(raw)
            self.faults.restore(record)
            self.record = record
        self.initialized = True

    async def reconcile(self) -> None:
        async with self.lock:
            try:
                await self._initialize()
                self.faults.expire()
                if self.faults.active and self.faults.active["status"] == "cleanup_pending":
                    await self._cleanup()
                self.last_error = None
            except Exception:
                self.last_error = "target_cleanup_or_state_unavailable"

    async def status(self) -> dict[str, Any]:
        async with self.lock:
            await self._initialize()
            self.faults.expire()
            active = copy.deepcopy(self.faults.active)
            return {"active": active, "status": active["status"] if active else "idle", "cleanup_error": self.last_error}

    async def inject(self, body: FaultIn) -> dict[str, Any]:
        async with self.lock:
            await self._initialize()
            self.faults.expire()
            fingerprint = hashlib.sha256(canonical_json(body.model_dump()).encode()).hexdigest()
            active = self.faults.active
            if active:
                if active["run_id"] == body.run_id and self.record["fingerprint"] == fingerprint and active["status"] == "active":
                    return copy.deepcopy(active)
                raise FaultConflict("run_already_owned_or_cleanup_pending")
            receipt = await self.redis.get(RECEIPT_PREFIX + body.run_id)
            if receipt:
                raise FaultConflict("run_delivery_replayed")
            started_at = time.time()
            ack = {
                "run_id": body.run_id, "id": body.id, "duration_s": body.duration_s,
                "params": copy.deepcopy(body.params),
                "started_at": started_at,
                "until": min(started_at + body.duration_s, body.authorization_expires_at),
                "status": "active",
            }
            self.record = {"request": body.model_dump(), "fingerprint": fingerprint, "acknowledgement": ack}
            self.faults.restore(self.record)
            try:
                await self.redis.set(RECEIPT_PREFIX + body.run_id, canonical_json(self.record), ex=RECEIPT_TTL_S)
                await self.redis.set(ACTIVE_KEY, canonical_json(self.record))
                ttl_ms = max(1, math.ceil((ack["until"] - time.time()) * 1000))
                await self.redis.set(FAULTS_KEY, canonical_json(self.faults.snapshot()), px=ttl_ms)
            except Exception as exc:
                self.faults.stop()
                self.last_error = "injection_unconfirmed"
                raise CleanupPending("injection_unconfirmed") from exc
            return copy.deepcopy(ack)

    async def _cleanup(self) -> None:
        active = self.faults.active
        if active is None:
            return
        self.faults.stop()
        self.record["acknowledgement"] = copy.deepcopy(active)
        # Write intent before removing effects: a restart must not revive an abort.
        await self.redis.set(ACTIVE_KEY, canonical_json(self.record))
        await self.redis.delete(FAULTS_KEY)
        if await self.redis.get(FAULTS_KEY) is not None:
            raise CleanupPending("worker_fault_cleanup_unconfirmed")
        receipt = {**self.record, "status": "resealed"}
        await self.redis.set(RECEIPT_PREFIX + active["run_id"], canonical_json(receipt), ex=RECEIPT_TTL_S)
        await self.redis.delete(ACTIVE_KEY)
        if await self.redis.get(ACTIVE_KEY) is not None:
            raise CleanupPending("target_journal_cleanup_unconfirmed")
        self.faults.active = None
        self.record = None
        self.last_error = None

    async def clear(self, run_id: str) -> dict[str, Any]:
        async with self.lock:
            await self._initialize()
            try:
                if self.faults.active and self.faults.active["run_id"] == run_id:
                    await self._cleanup()
                else:
                    # A delayed clear never touches a different run's fault record.
                    await self.redis.set(RECEIPT_PREFIX + run_id, canonical_json({"run_id": run_id, "status": "resealed"}), ex=RECEIPT_TTL_S)
            except Exception as exc:
                self.last_error = "cleanup_pending"
                raise CleanupPending("cleanup_pending") from exc
            return {"run_id": run_id, "status": "resealed", "cleanup_confirmed": True}
