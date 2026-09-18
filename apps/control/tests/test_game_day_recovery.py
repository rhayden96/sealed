import pytest

from sealed_control.game_days import create_day


def test_invalid_later_step_leaves_no_orphans(client):
    response = client.post("/game-days", json={"steps": ["redis_down", "unknown"]})
    assert response.status_code == 400
    assert client.get("/drafts").json() == []
    assert client.get("/game-days").json() == []


def test_game_day_write_failure_rolls_back_all_drafts(client, monkeypatch):
    store = client.app.state.store
    original = store.put_game_day

    def fail_commit(day):
        raise RuntimeError("storage write failed")

    monkeypatch.setattr(store, "put_game_day", fail_commit)
    with pytest.raises(RuntimeError):
        create_day(store, client.app.state.catalog, ["handler_latency", "redis_down"])
    monkeypatch.setattr(store, "put_game_day", original)
    assert store.list_drafts() == []
    assert store.list_game_days() == []


def test_list_resume_and_end_are_separate_from_current_step_abort(client):
    day = client.post("/game-days", json={"steps": ["handler_latency", "redis_down"]}).json()
    first, second = [step["draft_id"] for step in day["steps"]]
    assert client.get("/game-days").json()[0]["id"] == day["id"]
    assert client.post(f"/drafts/{first}/unseal").status_code == 200
    aborted = client.post(f"/game-days/{day['id']}/abort").json()
    assert aborted["game_day"]["status"] == "open"
    assert aborted["game_day"]["current_index"] == 1
    ended = client.post(f"/game-days/{day['id']}/end").json()
    assert ended["status"] == "ended"
    assert ended["steps"][1]["status"] == "cancelled"
    assert client.post(f"/drafts/{second}/approve").status_code == 409
    assert client.post(f"/drafts/{second}/unseal").status_code == 409
    assert len(client.get("/seals").json()) == 1


def test_competing_standalone_run_and_day_share_admission(client):
    day = client.post("/game-days", json={"steps": ["handler_latency"]}).json()
    standalone = client.post("/drafts", json={"catalog_id": "handler_latency", "environment": "demo", "target": "api"}).json()
    denied = client.post(f"/drafts/{day['steps'][0]['draft_id']}/unseal")
    assert denied.status_code == 403
    assert "max_concurrent_unsealed" in denied.json()["detail"]["reasons"]
    assert client.get(f"/drafts/{standalone['id']}").json()["status"] == "unsealed"
