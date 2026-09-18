import os

from fastapi.testclient import TestClient


def _token_header() -> dict[str, str]:
    return {"X-Sealed-Token": os.environ["UNSEAL_TOKEN"]}


def test_faults_ungated_is_forbidden(client: TestClient) -> None:
    denied = client.post("/_faults", json={"id": "redis_down"})
    assert denied.status_code == 403


def test_health_degrades_on_redis_down(client: TestClient) -> None:
    before = client.get("/health")
    assert before.status_code == 200
    body = before.json()
    assert body["status"] == "ok"
    assert body["redis"] == "ok"

    injected = client.post(
        "/_faults", json={"id": "redis_down"}, headers=_token_header()
    )
    assert injected.status_code == 200
    assert injected.json()["id"] == "redis_down"

    after = client.get("/health")
    assert after.status_code == 200
    degraded = after.json()
    assert degraded["status"] == "degraded"
    assert degraded["redis"] == "down"
