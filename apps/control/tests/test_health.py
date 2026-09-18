from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "control"}


def test_openapi_includes_control_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/health",
        "/drafts",
        "/drafts/{draft_id}",
        "/drafts/{draft_id}/approve",
        "/drafts/{draft_id}/unseal",
        "/drafts/{draft_id}/reseal",
        "/seals",
        "/seals/{seal_id}",
    ):
        assert path in paths, path
