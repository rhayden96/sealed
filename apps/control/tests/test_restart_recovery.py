import asyncio
import time

import httpx

from sealed_control.main import create_app
from sealed_control.store import Store
from sealed_control.target import TargetAdapter


def test_restart_reconciles_reserved_run_without_reinjecting(tmp_path, monkeypatch):
    path = tmp_path / "control.sqlite3"
    initial = Store(path)
    run = initial.put_draft({"id": "interrupted", "catalog_id": "handler_latency", "environment": "demo", "target": "api", "duration_s": 5, "params": {"delay_ms": 300}, "hypothesis": {"slo": {"p95_ms": 500, "error_rate": .01}, "must": ["latency_recovers_after_reseal"]}, "approved": True, "status": "injecting", "created_at": time.time(), "evidence": {"baseline": [], "during": [], "recovery": []}})
    initial.close()

    async def scenario():
        release = asyncio.Event()
        clears = []

        async def clear(self, run_id):
            clears.append(run_id)
            await release.wait()
            return {"run_id": run_id, "cleanup_confirmed": True}

        async def forbidden_inject(self, draft):
            raise AssertionError("restart must never inject")

        monkeypatch.setattr(TargetAdapter, "clear", clear)
        monkeypatch.setattr(TargetAdapter, "inject", forbidden_inject)
        recovered = Store(path)
        app = create_app(store=recovered, target_url="")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://control") as client:
                assert (await client.get("/active-run")).json()["id"] == run["id"]
                created = (await client.post("/drafts", json={"catalog_id": "handler_latency", "environment": "demo", "target": "api"})).json()
                assert created["status"] == "draft"
                assert (await client.post(f"/drafts/{created['id']}/unseal")).status_code == 403
                release.set()

                async def complete():
                    while recovered.seal_for_run(run["id"]) is None:
                        await asyncio.sleep(.01)

                await asyncio.wait_for(complete(), 1)
                seal = recovered.seal_for_run(run["id"])
                assert seal["verdict"] == "fail"
                assert seal["reason"] == "control_restarted"
                assert clears == [run["id"]]
                assert (await client.post(f"/drafts/{run['id']}/unseal")).status_code == 409
        recovered.close()
        again = Store(path)
        assert again.get_seal(seal["id"]) == seal
        assert [event["kind"] for event in again.list_events(run["id"])].count("finalized") == 1
        again.close()

    asyncio.run(scenario())


def test_late_target_restart_cannot_pass_complete_measured_evidence(monkeypatch):
    """Restart after the last during sample must be detected at cleanup.

    Both cases use identical, otherwise passing evidence and the real evaluator;
    only the target process identity in the cleanup acknowledgement changes.
    """
    from copy import deepcopy
    from types import SimpleNamespace

    from sealed_control.evidence import evaluate
    from sealed_control.lifecycle import Lifecycle
    from .test_evidence import example

    monkeypatch.setattr("sealed_control.lifecycle.time.time", lambda: 220.0)

    async def scenario(cleanup_boot):
        draft, evidence = example()
        draft.update(
            environment="demo", target="api", status="unsealed", approved=True,
            source="manual", created_at=99.0, target_boot_id="original-boot",
            unsealed_until=evidence["injection_ack"]["until"],
        )
        evidence["injection_ack"]["boot_id"] = "original-boot"
        assert evaluate(draft, evidence)["verdict"] == "pass"
        recovery = deepcopy(evidence["recovery"])
        evidence.update(recovery=[], cleanup_confirmed=False, injection_complete=False)
        draft["evidence"] = evidence
        store = Store()
        store.put_draft(draft)
        clears = []

        class Adapter:
            url = "http://target:8080"

            async def clear(self, run_id):
                clears.append(run_id)
                return {"run_id": run_id, "cleanup_confirmed": True, "boot_id": cleanup_boot}

        class RecoveryObserver:
            async def phase(self, observed_draft, phase, **kwargs):
                assert phase == "recovery"
                assert observed_draft["id"] == draft["id"]
                return deepcopy(recovery)

            def forget(self, run_id):
                assert run_id == draft["id"]

        app = SimpleNamespace(state=SimpleNamespace(store=store, target_url="http://target:8080", simulated_target=False))
        lifecycle = Lifecycle(app, Adapter())
        lifecycle.observer = RecoveryObserver()
        try:
            # Expiry happens with no additional during sampling/browser reads.
            await lifecycle.tick()
            await lifecycle.tasks[draft["id"]]
            seal = store.seal_for_run(draft["id"])
            assert clears == [draft["id"]]
            assert seal["evidence"]["during"] == evidence["during"]
            assert seal["evidence"]["recovery"] == recovery
            return seal
        finally:
            await lifecycle.close()
            store.close()

    uninterrupted = asyncio.run(scenario("original-boot"))
    restarted = asyncio.run(scenario("replacement-boot"))
    assert uninterrupted["verdict"] == "pass"
    assert uninterrupted["reason"] == "measured_hypothesis_satisfied"
    assert restarted["verdict"] == "fail"
    assert restarted["reason"] == "infrastructure_failure"
    checks = restarted["evidence"]["evaluation"]["checks"]
    assert [check["id"] for check in checks if not check["passed"]] == ["injection_complete"]
