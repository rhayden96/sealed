from fastapi.testclient import TestClient


DEMO = ["handler_latency", "redis_down", "worker_drop"]


def _start_day(client: TestClient) -> dict:
    created = client.post("/game-days", json={"steps": DEMO})
    assert created.status_code == 200
    body = created.json()
    assert [step["catalog_id"] for step in body["steps"]] == DEMO
    assert all(step["status"] == "draft" for step in body["steps"])
    assert body["current_index"] == 0
    return body


def test_game_day_cannot_skip_a_step(client: TestClient) -> None:
    day = _start_day(client)
    later = day["steps"][1]
    denied = client.post(f"/drafts/{later['draft_id']}/unseal")
    assert denied.status_code == 403
    assert "step_skipped" in denied.json()["detail"]["reasons"]
    first = client.get(f"/drafts/{day['steps'][0]['draft_id']}").json()
    assert first["status"] == "draft"
    second = client.get(f"/drafts/{later['draft_id']}").json()
    assert second["status"] == "draft"


def test_abort_mid_day_reseals_live_step_only(client: TestClient) -> None:
    day = _start_day(client)
    first_id = day["steps"][0]["draft_id"]
    second_id = day["steps"][1]["draft_id"]
    client.post(f"/drafts/{first_id}/approve")
    unsealed = client.post(f"/drafts/{first_id}/unseal")
    assert unsealed.status_code == 200
    assert unsealed.json()["status"] == "unsealed"

    aborted = client.post(f"/game-days/{day['id']}/abort")
    assert aborted.status_code == 200
    assert aborted.json()["seal"]["verdict"] == "aborted"
    view = aborted.json()["game_day"]
    by_id = {step["draft_id"]: step for step in view["steps"]}
    assert by_id[first_id]["status"] == "resealed"
    assert by_id[second_id]["status"] == "draft"
    assert by_id[day["steps"][2]["draft_id"]]["status"] == "draft"
    unsealed_now = [
        item for item in client.get("/drafts").json() if item.get("status") == "unsealed"
    ]
    assert unsealed_now == []
