"""Lifecycle safety at the HTTP boundary with controlled target acknowledgements."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import time

import httpx
import pytest

import sealed_control.main as control
from sealed_control.loader import load_catalog, load_policy
from sealed_control.store import Store


REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ("XAI_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "UNSEAL_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PLANNER", "stub")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")


@asynccontextmanager
async def session():
    app = control.create_app(
        catalog=load_catalog(REPO / "experiments/catalog.yaml"),
        policy=load_policy(REPO / "experiments/policy.yaml"),
        store=Store(),
        target_url="",  # Explicit simulation; can never establish a passing verdict.
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield app, client


async def approved(client, catalog_id="worker_drop"):
    target = "redis" if catalog_id == "redis_down" else "worker"
    response = await client.post("/drafts", json={"catalog_id": catalog_id, "environment": "demo", "target": target})
    assert response.status_code == 200, response.text
    run_id = response.json()["id"]
    assert (await client.post(f"/drafts/{run_id}/approve")).status_code == 200
    return run_id


@pytest.mark.parametrize("same_draft", [True, False])
def test_reserved_injection_excludes_concurrent_requests(monkeypatch, same_draft):
    async def scenario():
        async with session() as (app, client):
            entered, release = asyncio.Event(), asyncio.Event()
            injections = []

            async def paused_inject(draft):
                injections.append(draft["id"])
                entered.set()
                await release.wait()
                return {"run_id": draft["id"], "until": time.time() + 15}

            monkeypatch.setattr(app.state.lifecycle.adapter, "inject", paused_inject)
            first = await approved(client)
            second = first if same_draft else await approved(client, "redis_down")
            pending = asyncio.create_task(client.post(f"/drafts/{first}/unseal"))
            await asyncio.wait_for(entered.wait(), 1)
            try:
                conflict = await asyncio.wait_for(client.post(f"/drafts/{second}/unseal"), 0.3)
                assert conflict.status_code == (409 if same_draft else 403), conflict.text
                assert injections == [first]
                assert app.state.store.get_draft(first)["status"] in {"reserved", "injecting"}
            finally:
                release.set()
                started = await asyncio.wait_for(pending, 1)
            assert started.status_code == 200, started.text
            assert started.json()["status"] == "unsealed"

    asyncio.run(scenario())


def test_abort_during_slow_injection_is_responsive_and_cleans_that_run(monkeypatch):
    async def scenario():
        async with session() as (app, client):
            entered, release = asyncio.Event(), asyncio.Event()
            cleared = []

            async def paused_inject(draft):
                entered.set()
                await release.wait()
                return {"run_id": draft["id"], "until": time.time() + 15}

            async def clear(run_id):
                cleared.append(run_id)
                return {"run_id": run_id, "cleanup_confirmed": True}

            monkeypatch.setattr(app.state.lifecycle.adapter, "inject", paused_inject)
            monkeypatch.setattr(app.state.lifecycle.adapter, "clear", clear)
            run_id = await approved(client)
            pending = asyncio.create_task(client.post(f"/drafts/{run_id}/unseal"))
            await asyncio.wait_for(entered.wait(), 1)
            try:
                response = await asyncio.wait_for(client.post(f"/drafts/{run_id}/reseal"), 0.85)
                assert response.status_code == 200
                assert response.json()["draft"]["status"] == "cleanup_pending"
                assert response.json()["seal"] is None
                assert cleared == []
                assert (await asyncio.wait_for(client.get("/health"), 0.3)).status_code == 200
            finally:
                release.set()
                await asyncio.wait_for(pending, 1)
            seal = app.state.store.seal_for_run(run_id)
            assert seal["verdict"] == "aborted"
            assert cleared == [run_id]

    asyncio.run(scenario())


def test_terminal_run_cannot_execute_again_and_abort_retries_share_one_seal():
    async def scenario():
        async with session() as (app, client):
            run_id = await approved(client)
            assert (await client.post(f"/drafts/{run_id}/unseal")).status_code == 200
            results = await asyncio.gather(*(client.post(f"/drafts/{run_id}/reseal") for _ in range(2)))
            assert all(response.status_code == 200 for response in results)
            assert len({response.json()["seal"]["id"] for response in results}) == 1
            assert len(app.state.store.list_seals()) == 1
            for operation in ("approve", "unseal"):
                assert (await client.post(f"/drafts/{run_id}/{operation}")).status_code == 409
            assert len(app.state.store.list_seals()) == 1

    asyncio.run(scenario())


def test_failed_cleanup_retains_admission_until_acknowledged_retry(monkeypatch):
    async def scenario():
        async with session() as (app, client):
            allow_cleanup = False

            async def clear(run_id):
                if not allow_cleanup:
                    raise httpx.ReadTimeout("cleanup unavailable")
                return {"run_id": run_id, "cleanup_confirmed": True}

            monkeypatch.setattr(app.state.lifecycle.adapter, "clear", clear)
            first, second = await approved(client), await approved(client, "redis_down")
            assert (await client.post(f"/drafts/{first}/unseal")).status_code == 200
            abort = await client.post(f"/drafts/{first}/reseal")
            assert abort.json()["draft"]["status"] == "cleanup_pending"
            assert abort.json()["draft"]["cleanup_error"] == "target_cleanup_unconfirmed"
            assert abort.json()["seal"] is None
            assert (await client.post(f"/drafts/{second}/unseal")).status_code == 403
            allow_cleanup = True
            retry = await client.post(f"/drafts/{first}/reseal")
            assert retry.json()["seal"]["verdict"] == "aborted"
            assert (await client.post(f"/drafts/{second}/unseal")).status_code == 200

    asyncio.run(scenario())


def test_scheduler_finalizes_without_browser_reads_and_missing_evidence_never_passes(monkeypatch):
    async def scenario():
        async with session() as (app, client):
            async def expired_ack(draft):
                return {"run_id": draft["id"], "until": time.time() - 1}

            monkeypatch.setattr(app.state.lifecycle.adapter, "inject", expired_ack)
            run_id = await approved(client)
            assert (await client.post(f"/drafts/{run_id}/unseal")).status_code == 200
            # No HTTP reads or lifecycle tick calls after injection: the server owns expiry.
            async def wait_for_seal():
                while app.state.store.seal_for_run(run_id) is None:
                    await asyncio.sleep(0.01)
                return app.state.store.seal_for_run(run_id)

            seal = await asyncio.wait_for(wait_for_seal(), 1)
            assert seal["verdict"] == "fail"
            assert seal["reason"] == "missing_or_invalid_evidence"
            assert app.state.store.get_draft(run_id)["status"] == "completed"
            assert (await client.post(f"/drafts/{run_id}/unseal")).status_code == 409

    asyncio.run(scenario())


def test_slow_planner_cannot_block_health_abort_or_admit_second_proposal(monkeypatch):
    async def scenario():
        async with session() as (app, client):
            entered, release = asyncio.Event(), asyncio.Event()

            async def slow_proposal(tools, **kwargs):
                entered.set()
                await release.wait()
                return {"outcome": "no_proposal"}

            monkeypatch.setattr(control, "agent_propose_plan", slow_proposal)
            run_id = await approved(client)
            assert (await client.post(f"/drafts/{run_id}/unseal")).status_code == 200
            pending = asyncio.create_task(client.post("/agent/propose"))
            await asyncio.wait_for(entered.wait(), 1)
            try:
                assert (await asyncio.wait_for(client.get("/health"), 0.3)).status_code == 200
                duplicate = await asyncio.wait_for(client.post("/agent/propose"), 0.3)
                assert duplicate.status_code == 409
                abort = await asyncio.wait_for(client.post(f"/drafts/{run_id}/reseal"), 0.85)
                assert abort.json()["seal"]["verdict"] == "aborted"
            finally:
                release.set()
                assert (await asyncio.wait_for(pending, 1)).status_code == 200

    asyncio.run(scenario())


def test_ambiguous_delivery_reconciles_by_run_without_second_injection(monkeypatch):
    async def scenario():
        async with session() as (app, client):
            injections = []

            async def timeout_after_inject(draft):
                injections.append(draft["id"])
                raise httpx.ReadTimeout("target accepted before connection timed out")

            async def status():
                draft = app.state.store.get_draft(injections[0])
                return {"active": {"run_id": draft["id"], "id": draft["catalog_id"], "params": draft["params"], "duration_s": draft["duration_s"], "status": "active", "until": time.time() + 15}}

            monkeypatch.setattr(app.state.lifecycle.adapter, "inject", timeout_after_inject)
            monkeypatch.setattr(app.state.lifecycle.adapter, "status", status)
            run_id = await approved(client)
            result = await client.post(f"/drafts/{run_id}/unseal")
            assert result.status_code == 200, result.text
            assert result.json()["status"] == "unsealed"
            assert result.json()["injection_ack"]["run_id"] == run_id
            assert injections == [run_id]

    asyncio.run(scenario())


def test_proposal_cancellation_is_scoped_and_releases_capacity(monkeypatch):
    async def scenario():
        async with session() as (app, client):
            entered = asyncio.Event()

            async def slow(tools, **kwargs):
                entered.set()
                await asyncio.Event().wait()

            monkeypatch.setattr(control, "agent_propose_plan", slow)
            pending = asyncio.create_task(client.post("/agent/propose", headers={"Idempotency-Key": "planning-one"}))
            await entered.wait()
            assert (await client.post("/agent/proposals/stale-id/cancel")).status_code == 409
            assert not pending.done()
            assert (await client.post("/agent/proposals/planning-one/cancel")).status_code == 200
            response = await asyncio.wait_for(pending, 0.3)
            assert response.json()["outcome"] == "cancelled"
            assert not app.state.proposal_lock.locked()
            assert app.state.store.list_drafts() == []

    asyncio.run(scenario())
