"""Real Redis checks; pipe this file to `docker compose exec -T target python`.

Uses only an isolated, fixed key prefix. Does not flush Redis or touch demo jobs.
"""

import asyncio
import os

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sealed_target import jobs


async def main():
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
    prefix = "sealed:integration:target-reliability:"
    jobs.JOBS_KEY = prefix + "queue"
    jobs.PROCESSING_KEY = prefix + "processing"
    jobs.JOB_IDS_KEY = prefix + "history"
    jobs.JOB_PREFIX = prefix + "job:"
    now = [100000.0]
    queue = jobs.JobQueue(redis, clock=lambda: now[0])

    async def reset():
        keys = [key async for key in redis.scan_iter(match=prefix + "*")]
        if keys:
            await redis.delete(*keys)

    try:
        await reset()
        await redis.set(jobs.PROCESSING_KEY, "wrong-type")
        try:
            await queue.enqueue({"sample": "atomic"})
        except ResponseError:
            pass
        else:
            raise AssertionError("schema failure must reject enqueue")
        assert await redis.exists(jobs.JOBS_KEY) == 0
        assert await redis.exists(jobs.JOB_IDS_KEY) == 0
        assert [key async for key in redis.scan_iter(match=jobs.JOB_PREFIX + "*")] == []
        await reset()
        print("PASS atomic enqueue rejects invalid schema without partial records")

        damaged = await queue.enqueue("corrupted-history")
        assert await queue.acknowledge(await queue.claim(), dropped=False)
        damaged_key = jobs.JOB_PREFIX + damaged["id"]
        await redis.delete(damaged_key)
        await redis.lpush(damaged_key, "wrong-type")
        jobs.MAX_HISTORY = 1
        accepted = await queue.enqueue("after-corruption")
        assert await redis.llen(jobs.JOBS_KEY) == 1
        assert (await queue.claim())["id"] == accepted["id"]
        await reset()
        jobs.MAX_HISTORY = 1000
        damaged = await queue.enqueue("corrupted-claim")
        accepted = await queue.enqueue("valid-next-job")
        damaged_key = jobs.JOB_PREFIX + damaged["id"]
        await redis.delete(damaged_key)
        await redis.lpush(damaged_key, "wrong-type")
        assert (await queue.claim())["id"] == accepted["id"]
        await reset()
        print("PASS wrong-type historical/queued records do not break valid admission or claims")

        payload = {"evidence_run": "run-1", "sample": "preserved", "large_integer": 9007199254740993, "decimal": 0.1234567890123456}
        record = await queue.enqueue(payload, run_id="run-1")
        first = await queue.claim()
        assert first["id"] == record["id"] and first["attempts"] == 1
        now[0] += jobs.LEASE_S + 1
        second = await queue.claim()
        assert second["attempts"] == 2 and second["reason"] == "worker_interrupted_retry"
        assert not await queue.acknowledge(first, dropped=True, fault_run_id="old")
        assert await queue.acknowledge(second, dropped=False)
        finished = await queue.get(record["id"])
        assert finished["payload"] == payload and finished["status"] == "done"
        assert await queue.claim() is None
        print("PASS interrupted claim retries; stale owner cannot acknowledge")

        dropped = await queue.enqueue(payload, run_id="run-1")
        claim = await queue.claim()
        assert await queue.acknowledge(claim, dropped=True, fault_run_id="run-1")
        now[0] += jobs.LEASE_S + 1
        assert await queue.claim() is None
        result = await queue.get(dropped["id"])
        assert result["status"] == "dropped" and result["fault_run_id"] == "run-1"
        assert result["attempts"] == 1 and result["payload"] == payload
        print("PASS intentional drop remains terminal and preserves evidence")

        interrupted = await queue.enqueue("crash")
        for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
            claim = await queue.claim()
            assert claim["attempts"] == attempt
            now[0] += jobs.LEASE_S + 1
        assert await queue.claim() is None
        failed = await queue.get(interrupted["id"])
        assert failed["status"] == "failed" and failed["reason"] == "attempts_exhausted"
        print("PASS repeated interruption ends as failed, not simulated dropped")

        await reset()
        jobs.MAX_QUEUE = 3
        for index in range(3):
            await queue.enqueue(index)
        try:
            await queue.enqueue("overflow")
        except jobs.QueueFull:
            pass
        else:
            raise AssertionError("capacity must reject fourth active job")
        assert await redis.llen(jobs.JOBS_KEY) == 3
        claim = await queue.claim()
        assert await queue.acknowledge(claim, dropped=False)
        await queue.enqueue("capacity-recovered")
        print("PASS queue capacity enforced atomically and recovered by ack")

        await reset()
        jobs.MAX_HISTORY = 3
        records = []
        for index in range(8):
            now[0] += 1
            record = await queue.enqueue(index)
            records.append(record)
            assert await queue.acknowledge(await queue.claim(), dropped=False)
        assert await redis.zcard(jobs.JOB_IDS_KEY) == 3
        keys = [key async for key in redis.scan_iter(match=jobs.JOB_PREFIX + "*")]
        assert len(keys) == 3
        listed = (await queue.list(limit=2))["jobs"]
        assert [item["payload"] for item in listed] == [7, 6]
        ttls = [await redis.ttl(jobs.JOB_PREFIX + item["id"]) for item in listed]
        assert all(ttl > 0 for ttl in ttls)
        await redis.delete(jobs.JOB_PREFIX + listed[0]["id"])
        page = await queue.list(limit=2)
        next_page = await queue.list(offset=page["next_offset"], limit=2)
        remaining = page["jobs"] + next_page["jobs"]
        assert [item["payload"] for item in remaining] == [6, 5]
        assert await redis.zcard(jobs.JOB_IDS_KEY) == 2
        print("PASS aligned bounded history/results, batched pagination, expired-history pruning")
    finally:
        await reset()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
