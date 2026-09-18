"""Compose worker: heartbeat + consume jobs; honor worker_drop from Redis."""

from __future__ import annotations

import asyncio
import json
import os
import random
import time

from redis.asyncio import Redis

from sealed_target.faults import FAULTS_KEY

JOBS_KEY = "sealed:jobs"
HEARTBEAT_KEY = "sealed:worker:heartbeat"


def _drop_rate(raw: bytes | str | None) -> float:
    if not raw:
        return 0.0
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return 0.0
    rec = data.get("worker_drop")
    if not rec:
        return 0.0
    if rec.get("until", 0) <= time.time():
        return 0.0
    return float(rec.get("params", {}).get("drop_rate", 0.2))


async def run(redis: Redis) -> None:
    while True:
        await redis.set(HEARTBEAT_KEY, "ok", ex=10)
        try:
            raw = await redis.get(FAULTS_KEY)
            rate = _drop_rate(raw)
        except Exception:
            rate = 0.0
        item = await redis.brpop(JOBS_KEY, timeout=1)
        if item is None:
            continue
        try:
            data = json.loads(item[1] if isinstance(item, (list, tuple)) else item)
        except (TypeError, json.JSONDecodeError, IndexError):
            continue
        job_id = data.get("id")
        if rate > 0 and random.random() < rate:
            data["status"] = "dropped"
            if job_id:
                await redis.set(f"sealed:job:{job_id}", json.dumps(data))
            continue
        data["status"] = "done"
        if job_id:
            await redis.set(f"sealed:job:{job_id}", json.dumps(data))


async def main() -> None:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    redis = Redis.from_url(url, decode_responses=True)
    try:
        await run(redis)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
