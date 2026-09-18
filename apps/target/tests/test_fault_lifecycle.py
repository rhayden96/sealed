import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from sealed_target.faults import FAULTS_KEY, FaultIn
from sealed_target.main import create_app
from sealed_target.worker import _drop_rate, run
from .conftest import FakeRedis, TEST_TOKEN, authorization, fault_body

TOKEN = {"X-Sealed-Token": TEST_TOKEN}


def deliver(client, body):
    return client.post("/_faults", json=body, headers=authorization(body))


def test_run_delivery_is_idempotent_and_cannot_overwrite(client):
    body = fault_body()
    first = deliver(client, body)
    assert first.status_code == 200
    assert first.json()["until"] - first.json()["started_at"] == 15
    assert deliver(client, body).json() == first.json()
    status = client.get("/_faults", headers=TOKEN).json()
    assert status["active"] == {key: value for key, value in first.json().items() if key != "boot_id"}
    assert status["boot_id"] == first.json()["boot_id"]
    assert deliver(client, {**body, "params": {"extra": 1}}).status_code == 422
    assert deliver(client, fault_body("run-b")).status_code == 409
    assert deliver(client, {**body, "duration_s": 14}).status_code == 409


def test_run_cleanup_cannot_clear_a_new_run_and_replay_is_denied(client):
    first = fault_body()
    assert deliver(client, first).status_code == 200
    assert client.delete("/_faults/run-a", headers=TOKEN).json()["cleanup_confirmed"] is True
    assert deliver(client, first).status_code == 409
    second = fault_body("run-b")
    assert deliver(client, second).status_code == 200
    assert client.delete("/_faults/run-a", headers=TOKEN).status_code == 200
    assert client.get("/_faults", headers=TOKEN).json()["active"]["run_id"] == "run-b"
    assert client.delete("/_faults", headers=TOKEN).status_code == 405


def test_abort_before_delayed_delivery_creates_a_tombstone(client):
    body = fault_body()
    assert client.delete("/_faults/run-a", headers=TOKEN).status_code == 200
    assert deliver(client, body).status_code == 409


def test_late_authorized_delivery_ack_exposes_shortened_effect_duration(client):
    body = fault_body(duration=15, authorization_expires_at=time.time() + 1)
    response = deliver(client, body)
    assert response.status_code == 200
    ack = response.json()
    assert 0 < ack["until"] - ack["started_at"] < 1
    assert ack["duration_s"] == 15


def test_target_restart_preserves_ack_and_completed_replay_protection():
    redis = FakeRedis()
    body = fault_body()
    with TestClient(create_app(redis_factory=lambda: redis, token=TEST_TOKEN)) as first:
        ack = deliver(first, body).json()
        boot = first.get("/_faults", headers=TOKEN).json()["boot_id"]
    with TestClient(create_app(redis_factory=lambda: redis, token=TEST_TOKEN)) as restarted:
        state = restarted.get("/_faults", headers=TOKEN).json()
        assert state["boot_id"] != boot
        assert state["active"] == {key: value for key, value in ack.items() if key != "boot_id"}
        assert deliver(restarted, body).json() == {**ack, "boot_id": state["boot_id"]}
        cleanup = restarted.delete("/_faults/run-a", headers=TOKEN)
        assert cleanup.status_code == 200
        assert cleanup.json()["boot_id"] == state["boot_id"]
    with TestClient(create_app(redis_factory=lambda: redis, token=TEST_TOKEN)) as finished:
        assert finished.get("/_faults", headers=TOKEN).json()["active"] is None
        assert deliver(finished, body).status_code == 409


def test_lost_post_response_is_reconciled_by_status_without_reinjecting(client):
    body = fault_body()
    deliver(client, body)  # Caller loses/ignores the successful response.
    found = client.get("/_faults", headers=TOKEN).json()["active"]
    assert found["run_id"] == "run-a"
    assert found["id"] == "redis_down"
    assert client.delete("/_faults/run-a", headers=TOKEN).json()["cleanup_confirmed"]


def test_cleanup_error_retains_owner_until_verified_recovery():
    class RedisWithDeleteFailure(FakeRedis):
        broken = True

        async def delete(self, key):
            if self.broken and key == FAULTS_KEY:
                raise ConnectionError("unavailable")
            return await super().delete(key)

    redis = RedisWithDeleteFailure()
    with TestClient(create_app(redis_factory=lambda: redis, token=TEST_TOKEN)) as client:
        assert deliver(client, fault_body(fault_id="worker_drop")).status_code == 200
        assert client.delete("/_faults/run-a", headers=TOKEN).status_code == 503
        assert client.get("/_faults", headers=TOKEN).json()["status"] == "cleanup_pending"
        assert FAULTS_KEY in redis.store
        assert deliver(client, fault_body("run-b")).status_code == 409
        redis.broken = False
        assert client.delete("/_faults/run-a", headers=TOKEN).json()["cleanup_confirmed"]
        assert FAULTS_KEY not in redis.store
        assert client.get("/_faults", headers=TOKEN).json()["active"] is None


def test_expiry_cleans_up_without_browser_reads():
    async def scenario():
        redis = FakeRedis()
        app = create_app(redis_factory=lambda: redis, token=TEST_TOKEN)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://target") as client:
                body = fault_body(fault_id="worker_drop", duration=0.05)
                assert (await client.post("/_faults", json=body, headers=authorization(body))).status_code == 200
                await asyncio.sleep(0.22)
                assert FAULTS_KEY not in redis.store
                assert app.state.faults.active is None
    asyncio.run(scenario())


def test_abort_cancels_an_inflight_latency_wait():
    async def scenario():
        app = create_app(redis_factory=FakeRedis, token=TEST_TOKEN)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://target") as client:
                body = fault_body(fault_id="handler_latency", duration=5, params={"delay_ms": 1000})
                assert (await client.post("/_faults", json=body, headers=authorization(body))).status_code == 200
                pending = asyncio.create_task(client.post("/login", json={}))
                await asyncio.sleep(0.05)
                assert not pending.done()
                start = time.perf_counter()
                response = await client.delete("/_faults/run-a", headers=TOKEN)
                assert response.status_code == 200
                assert (await asyncio.wait_for(pending, 0.3)).status_code == 200
                assert time.perf_counter() - start < 0.3
    asyncio.run(scenario())


@pytest.mark.parametrize("duration", [0, -1, 20.1, "5", True])
def test_target_rejects_unsafe_duration(client, duration):
    body = fault_body(duration=5)
    body["duration_s"] = duration
    assert deliver(client, body).status_code == 422


@pytest.mark.parametrize("fault_id,params", [
    ("handler_latency", {"delay_ms": -1}), ("handler_latency", {"delay_ms": 1001}),
    ("handler_latency", {"delay_ms": "300"}), ("handler_latency", {"delay_ms": True}),
    ("worker_drop", {"drop_rate": -0.1}), ("worker_drop", {"drop_rate": 1.1}),
    ("worker_drop", {"delay_ms": 3}), ("redis_down", {"drop_rate": 0.2}),
])
def test_target_rejects_unsafe_parameters(client, fault_id, params):
    assert deliver(client, fault_body(fault_id=fault_id, params=params)).status_code == 422


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_target_schema_rejects_nonfinite_numbers(value):
    from pydantic import ValidationError
    for changes in ({"duration_s": value}, {"authorization_expires_at": value}, {"params": {"delay_ms": value}}):
        with pytest.raises(ValidationError):
            FaultIn.model_validate(fault_body(fault_id="handler_latency", **changes))


def test_privileged_channel_requires_both_credential_and_current_signature(client):
    body = fault_body()
    assert client.post("/_faults", json=body).status_code == 403
    assert client.post("/_faults", json=body, headers=TOKEN).status_code == 403
    assert client.post("/_faults", json=body, headers={**authorization(body), "X-Sealed-Token": "wrong"}).status_code == 403
    assert client.post("/_faults", json={**body, "duration_s": 1}, headers=authorization(body)).status_code == 403
    assert deliver(client, {**body, "authorization_expires_at": time.time() - 1}).status_code == 403
    assert deliver(client, {**body, "authorization_expires_at": time.time() + 60}).status_code == 403
    assert client.get("/_faults").status_code == 403
    assert client.delete("/_faults/run-a").status_code == 403
    assert client.post("/_faults", content=" " * 16385, headers=TOKEN).status_code == 413


def test_worker_reads_fault_at_decision_after_claim():
    class WorkerRedis(FakeRedis):
        popped = False

        async def get(self, key):
            if key == FAULTS_KEY:
                assert self.popped, "must not snapshot fault before blocking pop"
            return await super().get(key)

    async def scenario():
        redis = WorkerRedis()
        redis.store[FAULTS_KEY] = json.dumps({"worker_drop": {"status": "active", "until": time.time() + 10, "params": {"drop_rate": 1}}})
        class Queue:
            async def claim(self):
                if redis.popped:
                    raise asyncio.CancelledError
                redis.popped = True
                redis.store.pop(FAULTS_KEY, None)  # Abort while waiting for a claim.
                return {"id": "first-after-abort", "payload": "demo"}

            async def acknowledge(self, record, *, dropped, fault_run_id):
                redis.store["sealed:job:first-after-abort"] = json.dumps({**record, "status": "dropped" if dropped else "done"})
                return True
        with pytest.raises(asyncio.CancelledError):
            await run(redis, queue=Queue())
        assert json.loads(redis.store["sealed:job:first-after-abort"])["status"] == "done"
    asyncio.run(scenario())


@pytest.mark.parametrize("raw", ["null", "[]", '{"worker_drop":[]}', '{"worker_drop":{"until":"forever"}}'])
def test_malformed_worker_fault_records_cannot_apply(raw):
    assert _drop_rate(raw) == 0
