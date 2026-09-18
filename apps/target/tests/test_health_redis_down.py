from fastapi.testclient import TestClient
from .conftest import authorization, fault_body


def test_faults_ungated_is_forbidden(client: TestClient) -> None:
    denied = client.post("/_faults", json={"id": "redis_down"})
    assert denied.status_code == 403


def test_health_degrades_on_redis_down(client: TestClient) -> None:
    before = client.get("/health")
    assert before.status_code == 200
    body = before.json()
    assert body["status"] == "ok"
    assert body["redis"] == "ok"

    payload = fault_body()
    injected = client.post("/_faults", json=payload, headers=authorization(payload))
    assert injected.status_code == 200
    assert injected.json()["id"] == "redis_down"

    after = client.get("/health")
    assert after.status_code == 200
    degraded = after.json()
    assert degraded["status"] == "degraded"
    assert degraded["redis"] == "down"
