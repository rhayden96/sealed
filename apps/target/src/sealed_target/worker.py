"""Compose worker: heartbeat + consume jobs; honor worker_drop from Redis."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import signal
import time
import uuid
from collections.abc import Callable

from redis.asyncio import Redis

from sealed_target.faults import FAULTS_KEY
from sealed_target.jobs import JobQueue

HEARTBEAT_KEY = "sealed:worker:heartbeat"
HEARTBEAT_FRESH_S = 3
logger = logging.getLogger(__name__)


def _drop_rate(raw: bytes | str | None) -> float:
    if not raw:
        return 0.0
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return 0.0
    if not isinstance(data, dict):
        return 0.0
    rec = data.get("worker_drop")
    if not isinstance(rec, dict) or rec.get("status") != "active":
        return 0.0
    if not isinstance(rec.get("run_id"), str) or not 1 <= len(rec["run_id"]) <= 128:
        return 0.0
    until = rec.get("until")
    params = rec.get("params")
    if not isinstance(params, dict):
        return 0.0
    rate = params.get("drop_rate")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (until, rate)):
        return 0.0
    if not time.time() < until <= time.time() + 20 or not 0 <= rate <= 1:
        return 0.0
    return rate


async def _pause(stop: asyncio.Event, delay: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except TimeoutError:
        pass


async def run(redis: Redis, *, stop: asyncio.Event | None = None, queue: JobQueue | None = None, random_value: Callable[[], float] = random.random) -> None:
    stop = stop or asyncio.Event()
    queue = queue or JobQueue(redis)
    worker_id = str(uuid.uuid4())
    backoff = 0.1
    while not stop.is_set():
        try:
            await redis.set(HEARTBEAT_KEY, json.dumps({"worker_id": worker_id, "at": time.time()}), ex=30)
            record = await queue.claim()
            if record is None:
                backoff = 0.1
                await _pause(stop, 0.1)
                continue
            # Evaluate immediately before the decision, after the leased claim.
            # Decisions already made before reseal may still commit afterward.
            raw = await redis.get(FAULTS_KEY)
            rate = _drop_rate(raw)
            dropped = rate > 0 and random_value() < rate
            fault_run_id = json.loads(raw)["worker_drop"].get("run_id") if dropped else None
            if not await queue.acknowledge(record, dropped=dropped, fault_run_id=fault_run_id):
                logger.warning("worker_claim_lost job_id=%s", record["id"])
            backoff = 0.1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Leave an unacknowledged claim for bounded lease recovery. Never
            # turn an infrastructure interruption into an intentional drop.
            logger.warning("worker_retry error_type=%s", type(exc).__name__)
            await _pause(stop, backoff)
            backoff = min(backoff * 2, 2)


async def main() -> None:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    redis = Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        await run(redis, stop=stop)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
