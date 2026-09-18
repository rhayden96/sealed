"""A bounded Redis queue with atomic enqueue, leased claims and conditional ack."""

import json
import time
import uuid
from typing import Any

JOBS_KEY = "sealed:jobs"
PROCESSING_KEY = "sealed:jobs:processing"
JOB_IDS_KEY = "sealed:job-history:v2"
JOB_PREFIX = "sealed:job:"
RETENTION_S = 3600
MAX_HISTORY = 1000
MAX_QUEUE = 200
MAX_PAYLOAD_BYTES = 8192
LEASE_S = 5
MAX_ATTEMPTS = 3

# Validate key types before writing: Redis Lua provides atomicity, not rollback.
CHECK_TYPES = """
local expected = {'list', 'zset', 'zset'}
for i=1,3 do
  local actual = redis.call('TYPE', KEYS[i]).ok
  if actual ~= 'none' and actual ~= expected[i] then return redis.error_reply('queue_schema_invalid') end
end
"""

ENQUEUE = CHECK_TYPES + """
local record = cjson.decode(ARGV[1])
local now, retention = tonumber(ARGV[2]), tonumber(ARGV[3])
local prefix = ARGV[6]
-- Remove expired queued references before applying the capacity bound.
for _, id in ipairs(redis.call('LRANGE', KEYS[1], 0, -1)) do
  if redis.call('EXISTS', prefix .. id) == 0 then redis.call('LREM', KEYS[1], 0, id) end
end
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now - retention)
if redis.call('LLEN', KEYS[1]) + redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then return 0 end
redis.call('SET', prefix .. record.id, ARGV[1], 'EX', retention)
redis.call('ZADD', KEYS[3], now, record.id)
redis.call('LPUSH', KEYS[1], record.id)
-- Retain at most the recent history plus active records; both are bounded.
local excess = redis.call('ZCARD', KEYS[3]) - tonumber(ARGV[5])
if excess > 0 then
  for _, id in ipairs(redis.call('ZRANGE', KEYS[3], 0, -1)) do
    if excess <= 0 then break end
    local raw = redis.pcall('GET', prefix .. id)
    local valid, old = pcall(cjson.decode, type(raw) == 'string' and raw or 'null')
    if not valid or type(old) ~= 'table' then old = nil end
    if not old or (old.status ~= 'queued' and old.status ~= 'processing') then
      redis.call('DEL', prefix .. id)
      redis.call('ZREM', KEYS[3], id)
      excess = excess - 1
    end
  end
end
return 1
"""

CLAIM = CHECK_TYPES + """
local now, lease, retention, maximum = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])
local prefix = ARGV[6]
for _, id in ipairs(redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now, 'LIMIT', 0, 200)) do
  local raw = redis.pcall('GET', prefix .. id)
  if type(raw) == 'string' then
    local valid, record = pcall(cjson.decode, raw)
    if valid and type(record) == 'table' and record.status == 'processing' then
      record.updated_at = now
      record.claim_token = nil
      record.lease_until = nil
      if type(record.attempts) ~= 'number' or record.attempts >= maximum then
        record.status, record.reason = 'failed', 'attempts_exhausted'
      else
        record.status, record.reason = 'queued', 'worker_interrupted_retry'
        redis.call('LPUSH', KEYS[1], id)
      end
      redis.call('SET', prefix .. id, cjson.encode(record), 'EX', retention)
    end
  end
  redis.call('ZREM', KEYS[2], id)
end
for i=1,200 do
  local id = redis.call('RPOP', KEYS[1])
  if not id then return nil end
  local raw = redis.pcall('GET', prefix .. id)
  if type(raw) == 'string' then
    local valid, record = pcall(cjson.decode, raw)
    if valid and type(record) == 'table' and record.status == 'queued' and type(record.attempts) == 'number' then
      record.status, record.updated_at = 'processing', now
      record.attempts = record.attempts + 1
      record.claim_token, record.lease_until = ARGV[5], now + lease
      local encoded = cjson.encode(record)
      redis.call('SET', prefix .. id, encoded, 'EX', retention)
      redis.call('ZADD', KEYS[2], now + lease, id)
      return encoded
    end
  end
end
return nil
"""

ACK = """
local expected = {'string', 'zset', 'zset'}
for i=1,3 do
  local actual = redis.call('TYPE', KEYS[i]).ok
  if actual ~= 'none' and actual ~= expected[i] then return redis.error_reply('queue_schema_invalid') end
end
local raw = redis.call('GET', KEYS[1])
if not raw then return 0 end
local record = cjson.decode(raw)
if record.status ~= 'processing' or record.claim_token ~= ARGV[1] then return 0 end
local outcome = cjson.decode(ARGV[2])
record.status, record.updated_at = outcome.status, tonumber(ARGV[3])
record.reason, record.fault_run_id = outcome.reason, outcome.fault_run_id
record.claim_token, record.lease_until = nil, nil
redis.call('SET', KEYS[1], cjson.encode(record), 'EX', tonumber(ARGV[4]))
redis.call('ZREM', KEYS[2], record.id)
redis.call('ZADD', KEYS[3], record.updated_at, record.id)
return 1
"""


class QueueFull(Exception):
    pass


class JobQueue:
    def __init__(self, redis: Any, *, clock=time.time) -> None:
        self.redis = redis
        self.clock = clock

    async def enqueue(self, payload: Any, *, run_id: str | None = None) -> dict[str, Any]:
        now = self.clock()
        record = {"id": str(uuid.uuid4()), "payload": payload, "status": "queued", "attempts": 0, "created_at": now, "updated_at": now, "run_id": run_id}
        payload_json = json.dumps(payload, allow_nan=False)
        if len(payload_json.encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload_too_large")
        # Lua cjson numbers use double precision. Keep payload JSON opaque so
        # bookkeeping cannot round user integers or alter precise decimals.
        stored = {key: value for key, value in record.items() if key != "payload"}
        encoded = json.dumps({**stored, "payload_json": payload_json}, allow_nan=False)
        admitted = await self.redis.eval(ENQUEUE, 3, JOBS_KEY, PROCESSING_KEY, JOB_IDS_KEY, encoded, now, RETENTION_S, MAX_QUEUE, MAX_HISTORY, JOB_PREFIX)
        if not admitted:
            raise QueueFull
        return record

    async def claim(self) -> dict[str, Any] | None:
        raw = await self.redis.eval(CLAIM, 3, JOBS_KEY, PROCESSING_KEY, JOB_IDS_KEY, self.clock(), LEASE_S, RETENTION_S, MAX_ATTEMPTS, str(uuid.uuid4()), JOB_PREFIX)
        return json.loads(raw) if raw else None

    async def acknowledge(self, record: dict[str, Any], *, dropped: bool, fault_run_id: str | None = None) -> bool:
        outcome = {"status": "dropped" if dropped else "done", "reason": "injected_worker_drop" if dropped else "processed", "fault_run_id": fault_run_id if dropped else None}
        return bool(await self.redis.eval(ACK, 3, JOB_PREFIX + record["id"], PROCESSING_KEY, JOB_IDS_KEY, record["claim_token"], json.dumps(outcome), self.clock(), RETENTION_S))

    async def get(self, job_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(JOB_PREFIX + job_id)
        if not raw:
            return None
        return self._public_record(raw)

    @staticmethod
    def _public_record(raw: str) -> dict[str, Any]:
        record = json.loads(raw)
        if "payload_json" in record:
            record["payload"] = json.loads(record.pop("payload_json"))
        record.pop("claim_token", None)
        return record

    async def list(self, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        ids = await self.redis.zrevrange(JOB_IDS_KEY, offset, offset + limit - 1)
        raw = await self.redis.mget([JOB_PREFIX + (key.decode() if isinstance(key, bytes) else key) for key in ids]) if ids else []
        records = []
        expired = []
        for job_id, value in zip(ids, raw):
            if value:
                records.append(self._public_record(value))
            else:
                expired.append(job_id)
        if expired:
            await self.redis.zrem(JOB_IDS_KEY, *expired)
        # Pruning expired IDs shifts subsequent sorted-set offsets; advance only
        # by retained rows so the next page cannot silently skip live records.
        return {"jobs": records, "next_offset": offset + len(records) if len(ids) == limit else None, "retention_s": RETENTION_S}

    async def outcomes(self, *, run_id: str | None = None, since: float | None = None) -> dict[str, Any]:
        records = (await self.list(limit=200))["jobs"]
        records = [record for record in records if (run_id is None or record.get("run_id") == run_id) and record["updated_at"] >= max(self.clock() - 60, since or 0)]
        counts = {status: sum(record["status"] == status for record in records) for status in ("queued", "processing", "done", "dropped", "failed")}
        finished = counts["done"] + counts["dropped"] + counts["failed"]
        return {"available": True, "sample_count": len(records), **counts, "drop_rate": counts["dropped"] / finished if finished else None, "window_s": 60, "limit": 200}
