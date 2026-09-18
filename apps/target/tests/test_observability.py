import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from sealed_target.faults import FAULTS_KEY
from sealed_target.main import create_app
from sealed_target.metrics import Metrics
from sealed_target.worker import HEARTBEAT_KEY, run
from .conftest import FakeRedis, TEST_TOKEN


def test_metrics_uses_known_percentile_same_window_and_run_population():
    now = [100.0]
    metrics = Metrics(clock=lambda: now[0])
    assert metrics.snapshot()["p95_ms"] is None
    for duration in range(1, 101):
        metrics.record(duration, duration > 90, route="GET /probe", run_id="a")
    result = metrics.snapshot(run_id="a")
    assert result["sample_count"] == 100
    assert result["p95_ms"] == 95
    assert result["error_rate"] == 0.1
    assert result["first_at"] == 100
    now[0] = 161
    metrics.record(2, False, route="POST /login", run_id="b")
    recovered = metrics.snapshot()
    assert recovered["sample_count"] == 1
    assert recovered["p95_ms"] == 2
    assert recovered["error_rate"] == 0
    assert metrics.snapshot(run_id="a")["sample_count"] == 0


def test_metrics_bounded_and_management_requests_do_not_pollute(client):
    for _ in range(5):
        assert client.get("/health").status_code == 200
        assert client.get("/metrics").json()["sample_count"] == 0
    assert client.get("/probe", headers={"X-Sealed-Run": "run-a"}).status_code == 200
    assert client.get("/metrics?run_id=run-a").json()["sample_count"] == 1
    assert client.get("/metrics?run_id=run-b").json()["sample_count"] == 0
    assert client.get("/metrics?since=NaN").status_code == 422
    metrics = Metrics(limit=10)
    for number in range(100):
        metrics.record(number, False, route="GET /probe")
    assert metrics.snapshot()["sample_count"] == 10


@pytest.mark.parametrize("heartbeat,expected,reason", [
    (None, "unknown", "heartbeat_missing"),
    ({"at": time.time() - 30}, "down", "heartbeat_stale"),
    ({"at": "yesterday"}, "unknown", "heartbeat_invalid"),
    ([], "unknown", "heartbeat_invalid"),
])
def test_worker_health_requires_valid_fresh_heartbeat(heartbeat, expected, reason):
    redis = FakeRedis()
    if heartbeat is None:
        redis.store.pop(HEARTBEAT_KEY, None)
    else:
        redis.store[HEARTBEAT_KEY] = json.dumps(heartbeat)
    with TestClient(create_app(redis_factory=lambda: redis, token=TEST_TOKEN)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["worker"] == expected
        assert response.json()["worker_reason"] == reason
        assert client.get("/ready").status_code == 503


def test_fresh_worker_is_ready(client):
    assert client.get("/ready").status_code == 200


def test_job_api_contract_retains_payload_and_scoped_outcomes(client):
    class Queue:
        records = {}

        async def enqueue(self, payload, *, run_id):
            self.records["j1"] = {"id": "j1", "payload": payload, "run_id": run_id, "status": "queued"}
            return self.records["j1"]

        async def get(self, job_id):
            return self.records.get(job_id)

    client.app.state.jobs = Queue()
    payload = {"evidence_run": "r1", "sample": "during-1"}
    response = client.post("/jobs", json={"payload": payload}, headers={"X-Sealed-Run": "r1"})
    assert response.status_code == 202
    job = client.get("/jobs/j1").json()
    assert job["payload"] == payload
    assert job["run_id"] == "r1"
    assert client.get("/jobs/missing").status_code == 404
    assert client.post("/jobs", json={"payload": "a" * 20000}).status_code == 413
    assert client.get("/jobs?limit=101").status_code == 422


def test_worker_retries_transient_redis_failures_and_keeps_drop_distinct():
    async def scenario():
        class Redis(FakeRedis):
            failures = 1

            async def set(self, key, value, **kwargs):
                if self.failures:
                    self.failures -= 1
                    raise ConnectionError("transient")
                return await super().set(key, value, **kwargs)

        stop = asyncio.Event()
        outcomes = []

        class Queue:
            async def claim(self):
                return {"id": "j1"}

            async def acknowledge(self, record, *, dropped, fault_run_id):
                outcomes.append((dropped, fault_run_id))
                stop.set()
                return True

        redis = Redis()
        redis.store[FAULTS_KEY] = json.dumps({"worker_drop": {"status": "active", "run_id": "r1", "until": time.time() + 10, "params": {"drop_rate": 1}}})
        await asyncio.wait_for(run(redis, stop=stop, queue=Queue(), random_value=lambda: 0.5), timeout=1)
        assert outcomes == [(True, "r1")]
        assert json.loads(redis.store[HEARTBEAT_KEY])["at"] > 0
    asyncio.run(scenario())


def test_malformed_fault_record_does_not_kill_worker():
    async def scenario():
        stop = asyncio.Event()
        results = []
        class Queue:
            async def claim(self):
                return {"id": "j1"}
            async def acknowledge(self, record, *, dropped, fault_run_id):
                results.append(dropped)
                stop.set()
                return True
        redis = FakeRedis()
        redis.store[FAULTS_KEY] = "[]"
        await asyncio.wait_for(run(redis, stop=stop, queue=Queue()), timeout=1)
        assert results == [False]
    asyncio.run(scenario())
