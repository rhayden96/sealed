from fastapi.testclient import TestClient


def test_fixtures_replay_without_inject(client: TestClient) -> None:
    response = client.get("/fixtures")
    assert response.status_code == 200
    seals = response.json()["seals"]
    by_id = {item["id"]: item for item in seals}
    assert by_id["s-fx-latency"]["verdict"] == "pass"
    assert by_id["s-fx-latency"]["catalog_id"] == "handler_latency"
    assert by_id["s-fx-redis-down"]["verdict"] == "aborted"
    assert by_id["s-fx-redis-down"]["catalog_id"] == "redis_down"
    assert "worker_drop" not in {item["catalog_id"] for item in seals}

    one = client.get("/fixtures/s-fx-redis-down")
    assert one.status_code == 200
    assert one.json()["verdict"] == "aborted"
