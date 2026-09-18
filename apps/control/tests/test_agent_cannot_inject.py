"""Prove the planner cannot inject: propose is a draft; /_faults stays 403 until human unseal."""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from sealed_control.loader import load_catalog, load_policy
from sealed_control.main import create_app
from sealed_control.store import Store

REPO = Path(__file__).resolve().parents[3]

os.environ.pop("XAI_API_KEY", None)

TOKEN = "test-unseal"


class FaultIn(BaseModel):
    id: str
    duration_s: float | None = None
    params: dict = {}


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _fake_target(injects: list) -> FastAPI:
    app = FastAPI()

    @app.post("/_faults")
    async def inject(
        body: FaultIn, x_sealed_token: str | None = Header(default=None)
    ) -> dict:
        if x_sealed_token != TOKEN:
            raise HTTPException(status_code=403, detail="not_unsealed")
        rec = body.model_dump()
        injects.append(rec)
        return rec

    @app.delete("/_faults")
    async def clear(x_sealed_token: str | None = Header(default=None)) -> dict:
        if x_sealed_token != TOKEN:
            raise HTTPException(status_code=403, detail="not_unsealed")
        injects.append({"id": "clear"})
        return {"status": "resealed"}

    return app


@pytest.fixture
def gated_control() -> tuple[TestClient, list, str]:
    injects: list = []
    os.environ["UNSEAL_TOKEN"] = TOKEN
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            _fake_target(injects),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    catalog = load_catalog(REPO / "experiments" / "catalog.yaml")
    policy = load_policy(REPO / "experiments" / "policy.yaml")
    app = create_app(
        catalog=catalog,
        policy=policy,
        store=Store(),
        target_url=f"http://127.0.0.1:{port}",
    )
    with TestClient(app) as client:
        yield client, injects, f"http://127.0.0.1:{port}"
    server.should_exit = True


def _abort_redis_down(client: TestClient) -> None:
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
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 200
    assert client.post(f"/drafts/{draft_id}/unseal").status_code == 200
    resealed = client.post(f"/drafts/{draft_id}/reseal")
    assert resealed.status_code == 200
    assert resealed.json()["seal"]["verdict"] == "aborted"


def test_propose_does_not_inject_until_human_unseal(gated_control) -> None:
    client, injects, target_url = gated_control
    _abort_redis_down(client)
    injects.clear()

    proposed = client.post("/agent/propose")
    assert proposed.status_code == 200
    draft = proposed.json()["draft"]
    assert draft["catalog_id"] == "worker_drop"
    assert draft["status"] == "draft"
    assert draft["source"] == "agent"
    assert [item["id"] for item in injects] == []

    ungated = httpx.post(
        f"{target_url}/_faults", json={"id": "worker_drop"}, timeout=5.0
    )
    assert ungated.status_code == 403
    assert ungated.json()["detail"] == "not_unsealed"
    assert [item["id"] for item in injects] == []

    approved = client.post(f"/drafts/{draft['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert [item["id"] for item in injects] == []

    fired = client.post(f"/drafts/{draft['id']}/unseal")
    assert fired.status_code == 200
    assert fired.json()["status"] == "unsealed"
    assert [item["id"] for item in injects] == ["worker_drop"]
