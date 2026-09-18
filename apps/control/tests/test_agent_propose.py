import os

from fastapi.testclient import TestClient

from sealed_agent.tools import ALLOWED_TOOLS, FORBIDDEN_TOOLS, Tools

os.environ.pop("XAI_API_KEY", None)
os.environ.pop("LLM_BASE_URL", None)
os.environ.pop("LLM_MODEL", None)
os.environ.pop("LLM_API_KEY", None)


def test_tool_registry_has_no_inject() -> None:
    assert ALLOWED_TOOLS.isdisjoint(FORBIDDEN_TOOLS)
    for name in (
        "list_experiments",
        "list_targets",
        "propose_experiment",
        "get_run",
        "get_seal",
        "explain_failure",
    ):
        assert name in ALLOWED_TOOLS
        assert hasattr(Tools, name)
    for name in FORBIDDEN_TOOLS:
        assert not hasattr(Tools, name)


def test_propose_without_redis_down_seal(client: TestClient) -> None:
    response = client.post("/agent/propose")
    assert response.status_code == 200
    body = response.json()
    assert body["draft"] is None
    assert body["planner"] == "stub"


def test_propose_worker_drop_after_aborted_redis_down(client: TestClient) -> None:
    created = client.post(
        "/drafts",
        json={
            "catalog_id": "redis_down",
            "environment": "demo",
            "target": "redis",
            "duration_s": 15,
        },
    )
    assert created.status_code == 200
    draft_id = created.json()["id"]
    client.post(f"/drafts/{draft_id}/approve")
    unsealed = client.post(f"/drafts/{draft_id}/unseal")
    assert unsealed.status_code == 200
    resealed = client.post(f"/drafts/{draft_id}/reseal")
    assert resealed.status_code == 200
    assert resealed.json()["seal"]["verdict"] == "aborted"

    proposed = client.post("/agent/propose")
    assert proposed.status_code == 200
    body = proposed.json()
    draft = body["draft"]
    assert draft is not None
    assert draft["catalog_id"] == "worker_drop"
    assert draft["target"] == "worker"
    assert draft["status"] == "draft"
    assert draft["approved"] is False
    assert draft["source"] == "agent"
    assert body["planner"] == "stub"
    unsealed_now = [
        item for item in client.get("/drafts").json() if item.get("status") == "unsealed"
    ]
    assert unsealed_now == []
