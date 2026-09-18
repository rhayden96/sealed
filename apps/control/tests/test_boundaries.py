import json

import pytest
from sealed_control.store import Store


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), -float("inf"), True, "5"])
def test_malformed_duration_never_admitted(client, value):
    response = client.post("/drafts", content=json.dumps({"catalog_id": "handler_latency", "environment": "demo", "target": "api", "duration_s": value}), headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert client.get("/drafts").json() == []


@pytest.mark.parametrize("overrides", [
    {"params": {"delay_ms": 1001}},
    {"params": {"delay_ms": "300"}},
    {"params": {"extra": 1}},
    {"target": "worker"},
    {"hypothesis": {"slo": {"p95_ms": 500, "error_rate": 0.1}, "must": []}},
])
def test_invalid_fault_contract(client, overrides):
    body = {"catalog_id": "handler_latency", "environment": "demo", "target": "api", **overrides}
    assert client.post("/drafts", json=body).status_code == 422
    assert client.get("/drafts").json() == []


def test_cross_origin_mutations_and_payload_bound(client):
    assert client.post("/agent/propose", headers={"Origin": "https://unrelated.example"}).status_code == 403
    assert client.post("/drafts", content=b"x" * 65537).status_code == 413


def test_seal_snapshot_not_mutable(client):
    draft = client.post("/drafts", json={"catalog_id": "handler_latency", "environment": "demo", "target": "api"}).json()
    response = client.post(f"/drafts/{draft['id']}/reseal").json()
    seal = response["seal"]
    copied = client.app.state.store.get_seal(seal["id"])
    copied["hypothesis"]["slo"]["p95_ms"] = -1
    assert client.app.state.store.get_seal(seal["id"])["hypothesis"]["slo"]["p95_ms"] == 500


def test_fresh_process_does_not_reuse_run_identity():
    first_process = Store()
    restarted_process = Store()
    assert first_process.new_id("d") != restarted_process.new_id("d")


def test_policy_preview_is_read_only_and_terminal_runs_are_denied(client, monkeypatch):
    async def forbidden_injection(draft):
        raise AssertionError("policy preview must never inject")

    monkeypatch.setattr(client.app.state.lifecycle.adapter, "inject", forbidden_injection)
    draft = client.post("/drafts", json={"catalog_id": "worker_drop", "environment": "demo", "target": "worker"}).json()
    run_id = draft["id"]
    before = client.get(f"/drafts/{run_id}/events").json()
    decision = client.get(f"/drafts/{run_id}/evaluate").json()
    assert decision["allowed"] is False
    assert client.get(f"/drafts/{run_id}/events").json() == before
    assert client.get(f"/drafts/{run_id}").json() == draft
    client.post(f"/drafts/{run_id}/approve").raise_for_status()
    assert client.get(f"/drafts/{run_id}/evaluate").json()["allowed"] is True
    cancelled = client.app.state.store.get_draft(run_id)
    cancelled["status"] = "cancelled"
    client.app.state.store.put_draft(cancelled)
    terminal = client.get(f"/drafts/{run_id}/evaluate").json()
    assert terminal["allowed"] is False
    assert "run_not_startable" in terminal["reasons"]


def test_policy_preview_and_unseal_agree_on_game_day_order(client, monkeypatch):
    async def forbidden_injection(draft):
        raise AssertionError("future game-day step must never inject")

    monkeypatch.setattr(client.app.state.lifecycle.adapter, "inject", forbidden_injection)
    day = client.post("/game-days", json={"steps": ["redis_down", "handler_latency"]}).json()
    run_id = day["steps"][1]["draft_id"]
    before = client.get(f"/drafts/{run_id}/events").json()
    preview = client.get(f"/drafts/{run_id}/evaluate").json()
    assert preview["allowed"] is False
    assert "step_skipped" in preview["reasons"]
    assert client.get(f"/drafts/{run_id}/events").json() == before
    denied = client.post(f"/drafts/{run_id}/unseal")
    assert denied.status_code == 403
    assert denied.json()["detail"] == preview
