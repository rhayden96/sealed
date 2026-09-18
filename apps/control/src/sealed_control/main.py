"""Control plane. Policy/clerk is the only unseal authority. Does not inject itself."""

from __future__ import annotations

import os
import time
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from sealed_agent.planner import propose as agent_propose_plan
from sealed_agent.tools import Tools
from sealed_control.clerk import current_step_index, evaluate, skip_reason
from sealed_control.loader import (
    experiments_by_id,
    load_catalog,
    load_fixture_seals,
    load_policy,
)
from sealed_control.store import Store

UNSEAL_HEADER = "X-Sealed-Token"


class DraftIn(BaseModel):
    catalog_id: str
    environment: str
    target: str
    duration_s: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    hypothesis: dict[str, Any] | None = None


class GameDayIn(BaseModel):
    steps: list[str]


def _default_paths() -> tuple[str, str]:
    catalog = os.environ.get("CATALOG_PATH")
    policy = os.environ.get("POLICY_PATH")
    if catalog and policy:
        return catalog, policy
    container_catalog = Path("/app/experiments/catalog.yaml")
    container_policy = Path("/app/experiments/policy.yaml")
    if container_catalog.is_file() and container_policy.is_file():
        return str(container_catalog), str(container_policy)
    repo = Path(__file__).resolve().parents[4]
    return (
        str(repo / "experiments" / "catalog.yaml"),
        str(repo / "experiments" / "policy.yaml"),
    )


def _fixtures_dir() -> Path:
    env = os.environ.get("FIXTURES_PATH")
    if env:
        return Path(env)
    container = Path("/app/fixtures/seals")
    if container.is_dir():
        return container
    repo = Path(__file__).resolve().parents[4]
    return repo / "fixtures" / "seals"


async def _target_inject(app: FastAPI, draft: dict[str, Any]) -> None:
    url = app.state.target_url
    if not url:
        return
    token = os.environ.get("UNSEAL_TOKEN") or ""
    response = await app.state.http.post(
        f"{url.rstrip('/')}/_faults",
        json={
            "id": draft["catalog_id"],
            "duration_s": draft["duration_s"],
            "params": draft["params"],
        },
        headers={UNSEAL_HEADER: token},
        timeout=5.0,
    )
    response.raise_for_status()


async def _target_clear(app: FastAPI) -> None:
    url = app.state.target_url
    if not url:
        return
    token = os.environ.get("UNSEAL_TOKEN") or ""
    response = await app.state.http.delete(
        f"{url.rstrip('/')}/_faults",
        headers={UNSEAL_HEADER: token},
        timeout=5.0,
    )
    response.raise_for_status()


async def expire_unsealed(app: FastAPI) -> None:
    now = time.time()
    store: Store = app.state.store
    expired = False
    for draft in store.list_drafts():
        if draft.get("status") != "unsealed":
            continue
        if draft.get("unsealed_until", 0) > now:
            continue
        draft["status"] = "completed"
        store.add_seal(draft=draft, verdict="pass")
        expired = True
    if expired:
        try:
            await _target_clear(app)
        except Exception:
            pass


def _new_draft(
    store: Store,
    catalog: dict[str, Any],
    *,
    catalog_id: str,
    environment: str,
    target: str,
    duration_s: float | None = None,
    params: dict[str, Any] | None = None,
    hypothesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    experiments = experiments_by_id(catalog)
    spec = experiments.get(catalog_id)
    duration = duration_s
    if duration is None:
        duration = float((spec or {}).get("default_duration_s") or 0)
    merged = {**((spec or {}).get("params") or {}), **(params or {})}
    hypo = hypothesis if hypothesis is not None else (spec or {}).get("hypothesis")
    draft = {
        "id": store.new_id("d"),
        "catalog_id": catalog_id,
        "environment": environment,
        "target": target,
        "duration_s": duration,
        "params": merged,
        "hypothesis": hypo,
        "approved": False,
        "status": "draft",
        "created_at": time.time(),
    }
    return store.put_draft(draft)


def _game_day_view(store: Store, game_day: dict[str, Any]) -> dict[str, Any]:
    current = current_step_index(game_day, store)
    steps = []
    for index, step in enumerate(game_day.get("steps") or []):
        draft = store.get_draft(step["draft_id"]) or {}
        steps.append(
            {
                "index": index,
                "catalog_id": step["catalog_id"],
                "draft_id": step["draft_id"],
                "status": draft.get("status", "missing"),
                "live": draft.get("status") == "unsealed",
                "current": current == index,
            }
        )
    return {"id": game_day["id"], "steps": steps, "current_index": current}


async def _unseal_draft(app: FastAPI, draft: dict[str, Any]) -> dict[str, Any]:
    await expire_unsealed(app)
    skipped = skip_reason(draft, app.state.store)
    if skipped:
        raise HTTPException(
            status_code=403,
            detail={"allowed": False, "reasons": [skipped]},
        )
    decision = evaluate(
        draft, app.state.policy, app.state.catalog, app.state.store.list_drafts()
    )
    if not decision["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={"allowed": False, "reasons": decision["reasons"]},
        )
    try:
        await _target_inject(app, draft)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="target_inject_failed") from exc
    now = time.time()
    draft["status"] = "unsealed"
    draft["unsealed_at"] = now
    draft["unsealed_until"] = now + float(draft["duration_s"])
    return draft


def create_app(
    *,
    catalog: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    store: Store | None = None,
    target_url: str | None = None,
) -> FastAPI:
    if catalog is None or policy is None:
        catalog_path, policy_path = _default_paths()
        catalog = load_catalog(catalog_path) if catalog is None else catalog
        policy = load_policy(policy_path) if policy is None else policy

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.catalog = catalog
        app.state.policy = policy
        app.state.store = store or Store()
        app.state.target_url = (
            target_url if target_url is not None else os.environ.get("TARGET_URL") or ""
        )
        app.state.http = httpx.AsyncClient()
        yield
        close = app.state.http.aclose()
        if isinstance(close, Awaitable):
            await close

    app = FastAPI(lifespan=lifespan, title="sealed-control")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "control"}

    @app.get("/catalog")
    async def get_catalog(request: Request) -> dict[str, Any]:
        return request.app.state.catalog

    @app.get("/policy")
    async def get_policy(request: Request) -> dict[str, Any]:
        return request.app.state.policy

    @app.post("/drafts")
    async def create_draft(body: DraftIn, request: Request) -> dict[str, Any]:
        store: Store = request.app.state.store
        draft = _new_draft(
            store,
            request.app.state.catalog,
            catalog_id=body.catalog_id,
            environment=body.environment,
            target=body.target,
            duration_s=body.duration_s,
            params=body.params,
            hypothesis=body.hypothesis,
        )
        decision = evaluate(
            draft, request.app.state.policy, request.app.state.catalog, store.list_drafts()
        )
        if decision["allowed"] and decision["auto"]:
            await _unseal_draft(request.app, draft)
        return draft

    @app.get("/drafts")
    async def list_drafts(request: Request) -> list[dict[str, Any]]:
        await expire_unsealed(request.app)
        return request.app.state.store.list_drafts()

    @app.get("/drafts/{draft_id}")
    async def get_draft(draft_id: str, request: Request) -> dict[str, Any]:
        await expire_unsealed(request.app)
        draft = request.app.state.store.get_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="draft_not_found")
        return draft

    @app.post("/drafts/{draft_id}/approve")
    async def approve_draft(draft_id: str, request: Request) -> dict[str, Any]:
        await expire_unsealed(request.app)
        draft = request.app.state.store.get_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="draft_not_found")
        if draft["status"] == "unsealed":
            raise HTTPException(status_code=409, detail="already_unsealed")
        draft["approved"] = True
        if draft["status"] == "draft":
            draft["status"] = "approved"
        return draft

    @app.post("/drafts/{draft_id}/unseal")
    async def unseal_draft(draft_id: str, request: Request) -> dict[str, Any]:
        draft = request.app.state.store.get_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="draft_not_found")
        if draft["status"] == "unsealed":
            raise HTTPException(status_code=409, detail="already_unsealed")
        return await _unseal_draft(request.app, draft)

    @app.post("/drafts/{draft_id}/reseal")
    async def reseal_draft(draft_id: str, request: Request) -> dict[str, Any]:
        await expire_unsealed(request.app)
        store: Store = request.app.state.store
        draft = store.get_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="draft_not_found")
        if draft["status"] != "unsealed":
            raise HTTPException(status_code=409, detail="not_unsealed")
        try:
            await _target_clear(request.app)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="target_clear_failed") from exc
        draft["status"] = "resealed"
        seal = store.add_seal(draft=draft, verdict="aborted")
        return {"draft": draft, "seal": seal}

    @app.post("/game-days")
    async def create_game_day(body: GameDayIn, request: Request) -> dict[str, Any]:
        await expire_unsealed(request.app)
        if not body.steps:
            raise HTTPException(status_code=400, detail="steps_required")
        experiments = experiments_by_id(request.app.state.catalog)
        store: Store = request.app.state.store
        steps = []
        for catalog_id in body.steps:
            spec = experiments.get(catalog_id)
            if spec is None:
                raise HTTPException(status_code=400, detail="unknown_catalog_id")
            target = (spec.get("allowed_targets") or ["api"])[0]
            draft = _new_draft(
                store,
                request.app.state.catalog,
                catalog_id=catalog_id,
                environment="demo",
                target=target,
            )
            steps.append(
                {
                    "catalog_id": catalog_id,
                    "draft_id": draft["id"],
                }
            )
        game_day = store.put_game_day(
            {"id": store.new_id("g"), "steps": steps, "created_at": time.time()}
        )
        return _game_day_view(store, game_day)

    @app.get("/game-days/{game_day_id}")
    async def get_game_day(game_day_id: str, request: Request) -> dict[str, Any]:
        await expire_unsealed(request.app)
        game_day = request.app.state.store.get_game_day(game_day_id)
        if game_day is None:
            raise HTTPException(status_code=404, detail="game_day_not_found")
        return _game_day_view(request.app.state.store, game_day)

    @app.post("/game-days/{game_day_id}/abort")
    async def abort_game_day(game_day_id: str, request: Request) -> dict[str, Any]:
        await expire_unsealed(request.app)
        store: Store = request.app.state.store
        game_day = store.get_game_day(game_day_id)
        if game_day is None:
            raise HTTPException(status_code=404, detail="game_day_not_found")
        live = None
        for step in game_day["steps"]:
            draft = store.get_draft(step["draft_id"])
            if draft and draft.get("status") == "unsealed":
                live = draft
                break
        if live is None:
            raise HTTPException(status_code=409, detail="no_live_step")
        try:
            await _target_clear(request.app)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="target_clear_failed") from exc
        live["status"] = "resealed"
        seal = store.add_seal(draft=live, verdict="aborted")
        view = _game_day_view(store, game_day)
        return {"game_day": view, "seal": seal}

    @app.post("/agent/propose")
    async def agent_propose(request: Request) -> dict[str, Any]:
        await expire_unsealed(request.app)
        tools = Tools(
            catalog=request.app.state.catalog,
            policy=request.app.state.policy,
            store=request.app.state.store,
        )
        return agent_propose_plan(tools)

    @app.get("/fixtures")
    async def list_fixtures() -> dict[str, Any]:
        seals = load_fixture_seals(_fixtures_dir())
        return {"seals": seals}

    @app.get("/fixtures/{seal_id}")
    async def get_fixture(seal_id: str) -> dict[str, Any]:
        for seal in load_fixture_seals(_fixtures_dir()):
            if seal.get("id") == seal_id:
                return seal
        raise HTTPException(status_code=404, detail="fixture_not_found")

    @app.get("/seals")
    async def list_seals(request: Request) -> list[dict[str, Any]]:
        return request.app.state.store.list_seals()

    @app.get("/seals/{seal_id}")
    async def get_seal(seal_id: str, request: Request) -> dict[str, Any]:
        seal = request.app.state.store.get_seal(seal_id)
        if seal is None:
            raise HTTPException(status_code=404, detail="seal_not_found")
        return seal

    return app


app = create_app()
