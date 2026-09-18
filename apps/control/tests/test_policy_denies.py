from fastapi.testclient import TestClient


def _unsealed(client: TestClient) -> list[dict]:
    return [d for d in client.get("/drafts").json() if d.get("status") == "unsealed"]


def test_deny_prod(client: TestClient) -> None:
    created = client.post(
        "/drafts",
        json={
            "catalog_id": "redis_down",
            "environment": "prod",
            "target": "redis",
            "duration_s": 15,
        },
    )
    assert created.status_code == 200
    draft_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    client.post(f"/drafts/{draft_id}/approve")
    denied = client.post(f"/drafts/{draft_id}/unseal")
    assert denied.status_code == 403
    body = denied.json()["detail"]
    assert body["allowed"] is False
    assert "environment_denied" in body["reasons"]
    assert _unsealed(client) == []


def test_deny_duration_over_20(client: TestClient) -> None:
    created = client.post(
        "/drafts",
        json={
            "catalog_id": "redis_down",
            "environment": "demo",
            "target": "redis",
            "duration_s": 21,
        },
    )
    assert created.status_code == 200
    draft_id = created.json()["id"]
    client.post(f"/drafts/{draft_id}/approve")
    denied = client.post(f"/drafts/{draft_id}/unseal")
    assert denied.status_code == 403
    body = denied.json()["detail"]
    assert body["allowed"] is False
    assert "duration_exceeded" in body["reasons"]
    assert _unsealed(client) == []


def test_deny_two_unsealed_at_once(client: TestClient) -> None:
    first = client.post(
        "/drafts",
        json={
            "catalog_id": "handler_latency",
            "environment": "demo",
            "target": "api",
            "duration_s": 5,
        },
    )
    assert first.status_code == 200
    assert first.json()["status"] == "unsealed"

    second = client.post(
        "/drafts",
        json={
            "catalog_id": "handler_latency",
            "environment": "demo",
            "target": "api",
            "duration_s": 5,
        },
    )
    assert second.status_code == 200
    assert second.json()["status"] == "draft"
    denied = client.post(f"/drafts/{second.json()['id']}/unseal")
    assert denied.status_code == 403
    body = denied.json()["detail"]
    assert body["allowed"] is False
    assert "max_concurrent_unsealed" in body["reasons"]
    assert len(_unsealed(client)) == 1
