"""Control plane. Policy/clerk is the only unseal authority. Does not inject itself."""

from __future__ import annotations

import os
import asyncio
import secrets
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sealed_agent.planner import propose as agent_propose_plan
from sealed_agent.tools import Tools
from sealed_agent.domain import DraftIn, construct_draft, validate_catalog, validate_policy
from sealed_control.lifecycle import Lifecycle, ACTIVE
from sealed_control.target import TargetAdapter
from sealed_control.ownership import ProcessOwner
from sealed_control.clerk import evaluate, evaluate_run
from sealed_control.loader import (
    load_catalog,
    load_fixture_seals,
    load_policy,
)
from sealed_control.store import Store
from sealed_control.game_days import GameDayIn, create_day, end_day, view as _game_day_view

UNSEAL_HEADER = "X-Sealed-Token"


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


def _new_draft(store, catalog, **kwargs):
    try:
        return construct_draft(store, catalog, **kwargs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _unseal_draft(app, draft):
    return await app.state.lifecycle.start(draft["id"])


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
    catalog = validate_catalog(catalog)
    policy = validate_policy(policy)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.catalog = catalog
        app.state.policy = policy
        app.state.target_url = (
            target_url if target_url is not None else os.environ.get("TARGET_URL") or ""
        )
        app.state.simulated_target = target_url == ""
        if target_url is None and app.state.target_url not in {"", "http://target:8080"}:
            raise RuntimeError("fault_target_must_be_compose_target")
        if int(os.environ.get("WEB_CONCURRENCY", "1")) != 1:
            raise RuntimeError("control_requires_single_process")
        owner_path = os.environ.get("CONTROL_OWNER_FILE")
        owner = ProcessOwner(owner_path) if owner_path and store is None else None
        try:
            app.state.store = store if store is not None else Store(os.environ.get("STORE_PATH"))
        except BaseException:
            if owner:
                owner.close()
            raise
        app.state.http = httpx.AsyncClient(trust_env=False)
        app.state.proposal_lock = asyncio.Lock()
        app.state.proposal_task = None
        app.state.proposal_id = None
        app.state.lifecycle = Lifecycle(app, TargetAdapter(app))
        await app.state.lifecycle.recover_startup()
        app.state.lifecycle.scheduler = asyncio.create_task(app.state.lifecycle.run_scheduler())
        try:
            yield
        finally:
            if app.state.proposal_task and not app.state.proposal_task.done():
                app.state.proposal_task.cancel()
                await asyncio.gather(app.state.proposal_task, return_exceptions=True)
            await app.state.lifecycle.close()
            close = app.state.http.aclose()
            if isinstance(close, Awaitable):
                await close
            if owner:
                owner.close()
            if store is None:
                app.state.store.close()

    app = FastAPI(lifespan=lifespan, title="sealed-control")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]}, status_code=422)

    @app.middleware("http")
    async def guard_mutations(request: Request, call_next):
        from fastapi.responses import JSONResponse
        from urllib.parse import urlparse
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and (urlparse(origin).hostname not in {"localhost", "127.0.0.1", "[::1]", "::1"} or urlparse(origin).scheme not in {"http", "https"}):
                return JSONResponse({"detail": "local_demo_origin_required"}, status_code=403)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65536:
                    return JSONResponse({"detail": "payload_too_large"}, status_code=413)
            request._body = bytes(body)
        return await call_next(request)


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
            draft, request.app.state.policy, request.app.state.catalog, store.list_active()
        )
        draft["policy_decision"] = decision
        draft = store.put_draft(draft)
        if decision["allowed"] and decision["auto"]:
            draft = await _unseal_draft(request.app, draft)
        return draft

    @app.get("/drafts")
    async def list_drafts(request: Request, limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0, le=100000), q: str = Query(default="", max_length=100), status: str | None = None) -> list[dict[str, Any]]:
        return request.app.state.store.list_draft_summaries(limit=limit, offset=offset, q=q, status=status)

    @app.get("/active-run")
    async def active_run(request: Request):
        active = request.app.state.store.list_active()
        return active[0] if active else None

    @app.get("/drafts/{draft_id}")
    async def get_draft(draft_id: str, request: Request) -> dict[str, Any]:
        draft = request.app.state.store.get_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="draft_not_found")
        return draft

    @app.post("/drafts/{draft_id}/approve")
    async def approve_draft(draft_id: str, request: Request) -> dict[str, Any]:
        return await request.app.state.lifecycle.approve(draft_id)

    @app.post("/drafts/{draft_id}/unseal")
    async def unseal_draft(draft_id: str, request: Request) -> dict[str, Any]:
        return await request.app.state.lifecycle.start(draft_id)

    @app.post("/drafts/{draft_id}/reseal")
    async def reseal_draft(draft_id: str, request: Request) -> dict[str, Any]:
        return await request.app.state.lifecycle.abort(draft_id)

    @app.get("/drafts/{draft_id}/events")
    async def run_events(draft_id: str, request: Request, after_seq: int = Query(default=0, ge=0), limit: int = Query(default=500, ge=1, le=500)):
        request.app.state.lifecycle.get(draft_id)
        return request.app.state.store.list_events(draft_id, after_seq=after_seq, limit=limit)

    @app.get("/drafts/{draft_id}/seal")
    async def run_seal(draft_id: str, request: Request):
        request.app.state.lifecycle.get(draft_id)
        return request.app.state.store.seal_for_run(draft_id)

    @app.post("/drafts/{draft_id}/evaluate")
    @app.get("/drafts/{draft_id}/evaluate")
    async def evaluate_draft(draft_id: str, request: Request):
        draft = request.app.state.lifecycle.get(draft_id)
        return evaluate_run(draft, request.app.state.policy, request.app.state.catalog, request.app.state.store)

    @app.post("/game-days")
    async def create_game_day(body: GameDayIn, request: Request) -> dict[str, Any]:
        return create_day(request.app.state.store, request.app.state.catalog, body.steps)

    @app.get("/game-days")
    async def list_game_days(request: Request):
        store = request.app.state.store
        return [_game_day_view(store, day) for day in store.list_game_days()[-100:]]

    @app.post("/game-days/{game_day_id}/end")
    async def end_game_day(game_day_id: str, request: Request):
        return await end_day(request.app, game_day_id)

    @app.get("/game-days/{game_day_id}")
    async def get_game_day(game_day_id: str, request: Request) -> dict[str, Any]:
        game_day = request.app.state.store.get_game_day(game_day_id)
        if game_day is None:
            raise HTTPException(status_code=404, detail="game_day_not_found")
        return _game_day_view(request.app.state.store, game_day)

    @app.post("/game-days/{game_day_id}/abort")
    async def abort_game_day(game_day_id: str, request: Request) -> dict[str, Any]:
        store: Store = request.app.state.store
        game_day = store.get_game_day(game_day_id)
        if game_day is None:
            raise HTTPException(status_code=404, detail="game_day_not_found")
        live = None
        for step in game_day["steps"]:
            draft = store.get_draft(step["draft_id"])
            if draft and draft.get("status") in ACTIVE:
                live = draft
                break
        if live is None:
            raise HTTPException(status_code=409, detail="no_live_step")
        result = await request.app.state.lifecycle.abort(live["id"])
        return {"game_day": _game_day_view(store, game_day), "seal": result["seal"]}

    @app.post("/agent/propose")
    async def agent_propose(request: Request, idempotency_key: str | None = Header(default=None, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")) -> dict[str, Any]:
        tools = Tools(
            catalog=request.app.state.catalog,
            policy=request.app.state.policy,
            store=request.app.state.store,
        )
        lock = request.app.state.proposal_lock
        if lock.locked():
            raise HTTPException(409, "proposal_in_progress")
        async with lock:
            proposal_id = idempotency_key or secrets.token_hex(16)
            request.app.state.proposal_id = proposal_id
            task = asyncio.create_task(agent_propose_plan(tools, proposal_id=proposal_id))
            request.app.state.proposal_task = task
            try:
                result = await task
            except asyncio.CancelledError:
                return {"proposal_id": proposal_id, "outcome": "cancelled", "draft": tools.proposed_draft, "explanation": "Planning cancelled. Any saved proposal remains a draft."}
        snap = request.app.state.store.agent_snapshot()
        result["planner"] = snap["planner"]
        result["trace"] = snap["trace"]
        return result

    @app.post("/agent/proposals/{proposal_id}/cancel")
    async def cancel_proposal(proposal_id: str, request: Request):
        task = request.app.state.proposal_task
        if request.app.state.proposal_id != proposal_id or task is None or task.done():
            raise HTTPException(409, "proposal_not_pending")
        task.cancel()
        return {"proposal_id": proposal_id, "outcome": "cancellation_requested"}

    @app.get("/agent/trace")
    async def agent_trace(request: Request) -> dict[str, Any]:
        return request.app.state.store.agent_snapshot()

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
    async def list_seals(request: Request, limit: int = Query(default=100, ge=1, le=200)) -> list[dict[str, Any]]:
        return request.app.state.store.list_seal_summaries(limit=limit)

    @app.get("/seals/{seal_id}")
    async def get_seal(seal_id: str, request: Request) -> dict[str, Any]:
        seal = request.app.state.store.get_seal(seal_id)
        if seal is None:
            raise HTTPException(status_code=404, detail="seal_not_found")
        return seal

    return app


app = create_app()
