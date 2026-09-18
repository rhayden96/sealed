"""Demo target API. Fault administration requires bounded control authorization."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from starlette.responses import Response
from starlette.responses import JSONResponse

from sealed_target.faults import (
    FaultConflict,
    FaultCoordinator,
    FaultIn,
    Faults,
    canonical_json,
)
from sealed_target.ownership import ProcessOwner
from sealed_target.jobs import JobQueue, MAX_PAYLOAD_BYTES, QueueFull
from sealed_target.metrics import Metrics
from sealed_target.worker import HEARTBEAT_FRESH_S, HEARTBEAT_KEY

LATENCY_EXEMPT = {"/health", "/ready", "/metrics"}
UNSEAL_HEADER = "X-Sealed-Token"
AUTHORIZATION_HEADER = "X-Sealed-Authorization"


def unseal_token() -> str:
    path = os.environ.get("UNSEAL_TOKEN_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get("UNSEAL_TOKEN", "")


def require_unseal_token(request: Request) -> None:
    expected = request.app.state.unseal_token
    provided = request.headers.get(UNSEAL_HEADER) or ""
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="not_unsealed")


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(default="demo", min_length=1, max_length=128)


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    payload: Any = ""


def request_run_id(request: Request) -> str | None:
    run_id = request.headers.get("X-Sealed-Run")
    if run_id and len(run_id) <= 128 and run_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return run_id
    active = request.app.state.faults.active
    return active["run_id"] if active and active["status"] == "active" else None


def create_app(*, redis_factory: Callable[[], Any] | None = None, token: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if int(os.environ.get("WEB_CONCURRENCY", "1")) != 1:
            raise RuntimeError("target_requires_single_process")
        owner = None
        if redis_factory is None:
            owner = ProcessOwner(os.environ.get("TARGET_OWNER_FILE", str(Path(tempfile.gettempdir()) / "sealed-target.lock")))
        app.state.faults = Faults()
        app.state.metrics = Metrics()
        app.state.unseal_token = token if token is not None else unseal_token()
        app.state.boot_id = str(uuid.uuid4())
        if redis_factory is not None:
            app.state.redis = redis_factory()
        else:
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            app.state.redis = Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        coordinator = FaultCoordinator(app.state.redis, app.state.faults)
        app.state.jobs = JobQueue(app.state.redis)
        app.state.fault_coordinator = coordinator
        await coordinator.reconcile()

        async def reconcile_faults() -> None:
            while True:
                await asyncio.sleep(0.1)
                await coordinator.reconcile()

        supervisor = asyncio.create_task(reconcile_faults())
        try:
            yield
        finally:
            supervisor.cancel()
            try:
                await supervisor
            except asyncio.CancelledError:
                pass
            app.state.faults.stopped.set()
            if owner:
                owner.close()
        redis = app.state.redis
        close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
        if close is not None:
            result = close()
            if isinstance(result, Awaitable):
                await result

    app = FastAPI(lifespan=lifespan, title="sealed-target")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Echoing NaN/Infinity or exception contexts makes JSON error responses fail.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
            for error in exc.errors()
        ]})

    @app.middleware("http")
    async def _observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        metrics: Metrics = request.app.state.metrics
        faults: Faults = request.app.state.faults
        if request.method == "POST" and request.url.path in {"/jobs", "/login"}:
            if len(await request.body()) > MAX_PAYLOAD_BYTES + 1024:
                return JSONResponse(status_code=413, content={"detail": "payload_too_large"})
        if request.url.path.startswith("/_faults"):
            try:
                require_unseal_token(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            if request.method == "POST":
                raw = await request.body()
                if len(raw) > 16384:
                    return JSONResponse(status_code=413, content={"detail": "fault_payload_too_large"})
                try:
                    payload = json.loads(raw)
                    message = canonical_json(payload).encode()
                except (TypeError, ValueError):
                    return JSONResponse(status_code=422, content={"detail": "invalid_fault_json"})
                signature = hmac.new(request.app.state.unseal_token.encode(), message, hashlib.sha256).hexdigest()
                supplied = request.headers.get(AUTHORIZATION_HEADER, "")
                if not hmac.compare_digest(supplied, signature):
                    return JSONResponse(status_code=403, content={"detail": "invalid_run_authorization"})
        faults.expire()
        business = (request.method, request.url.path) in {("GET", "/probe"), ("POST", "/login"), ("POST", "/jobs")}
        run_id = request_run_id(request)
        if business:
            metrics.inflight += 1
        start = time.perf_counter()
        error = False
        try:
            if (
                business and faults.is_active("handler_latency")
            ):
                await faults.wait_latency()
            response = await call_next(request)
            error = response.status_code >= 400
            return response
        except Exception:
            error = True
            raise
        finally:
            if business:
                metrics.inflight -= 1
                metrics.record((time.perf_counter() - start) * 1000.0, error, route=f"{request.method} {request.url.path}", run_id=run_id)

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        faults: Faults = request.app.state.faults
        faults.expire()
        if faults.is_active("redis_down"):
            redis_status = "down"
        else:
            try:
                ok = await request.app.state.redis.ping()
                redis_status = "ok" if ok else "down"
            except Exception:
                redis_status = "down"
        worker_status = "unknown"
        heartbeat_age = None
        worker_reason = "redis_unavailable"
        if redis_status == "ok":
            try:
                raw = await request.app.state.redis.get(HEARTBEAT_KEY)
                worker_reason = "heartbeat_missing"
                if raw:
                    heartbeat = json.loads(raw)
                    at = heartbeat.get("at") if isinstance(heartbeat, dict) else None
                    if isinstance(at, (int, float)) and not isinstance(at, bool) and math.isfinite(at) and at <= time.time() + 1:
                        heartbeat_age = max(0, time.time() - at)
                        worker_status = "ok" if heartbeat_age <= HEARTBEAT_FRESH_S else "down"
                        worker_reason = "heartbeat_fresh" if worker_status == "ok" else "heartbeat_stale"
                    else:
                        worker_reason = "heartbeat_invalid"
            except Exception:
                worker_reason = "heartbeat_unavailable"
        api_status = "ok"
        status = (
            "ok"
            if api_status == "ok" and redis_status == "ok" and worker_status == "ok"
            else "degraded"
        )
        return {
            "status": status,
            "api": api_status,
            "redis": redis_status,
            "worker": worker_status,
            "worker_reason": worker_reason,
            "worker_heartbeat_age_s": heartbeat_age,
            "observed_at": time.time(),
        }

    @app.get("/ready")
    async def readiness(request: Request) -> JSONResponse:
        result = await health(request)
        return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=result)

    @app.get("/probe")
    async def probe() -> dict[str, Any]:
        return {"status": "ok", "observed_at": time.time()}

    @app.get("/metrics")
    async def metrics_view(request: Request, run_id: str | None = Query(None, max_length=128), since: float | None = Query(None, ge=0, allow_inf_nan=False)) -> dict[str, Any]:
        metrics = request.app.state.metrics.snapshot(run_id=run_id, since=since)
        try:
            if request.app.state.faults.is_active("redis_down"):
                raise ConnectionError
            outcomes = await request.app.state.jobs.outcomes(run_id=run_id, since=since)
        except Exception:
            outcomes = {"available": False, "reason": "job_observations_unavailable"}
        return {**metrics, "job_outcomes": outcomes}

    @app.post("/login")
    async def login(body: LoginIn, request: Request) -> dict[str, str]:
        faults: Faults = request.app.state.faults
        faults.expire()
        if faults.is_active("redis_down"):
            raise HTTPException(status_code=503, detail="fail_closed")
        session_id = str(uuid.uuid4())
        try:
            await request.app.state.redis.set(
                f"sealed:session:{session_id}", body.username, ex=3600
            )
        except Exception:
            raise HTTPException(status_code=503, detail="fail_closed") from None
        return {"session_id": session_id}

    @app.post("/jobs", status_code=202)
    async def enqueue_job(body: JobIn, request: Request) -> dict[str, str]:
        faults: Faults = request.app.state.faults
        faults.expire()
        if faults.is_active("redis_down"):
            raise HTTPException(status_code=503, detail="fail_closed")
        try:
            record = await request.app.state.jobs.enqueue(body.payload, run_id=request_run_id(request))
        except QueueFull:
            raise HTTPException(status_code=429, detail="queue_full") from None
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid_or_oversized_payload") from None
        except Exception:
            raise HTTPException(status_code=503, detail="fail_closed") from None
        return {"job_id": record["id"], "status": "queued"}

    @app.get("/jobs")
    async def list_jobs(request: Request, offset: int = Query(0, ge=0, le=1000), limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
        faults: Faults = request.app.state.faults
        faults.expire()
        if faults.is_active("redis_down"):
            raise HTTPException(status_code=503, detail="fail_closed")
        try:
            return await request.app.state.jobs.list(offset=offset, limit=limit)
        except Exception:
            raise HTTPException(status_code=503, detail="fail_closed") from None

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str, request: Request) -> dict[str, Any]:
        if request.app.state.faults.is_active("redis_down"):
            raise HTTPException(status_code=503, detail="fail_closed")
        if len(job_id) > 128:
            raise HTTPException(status_code=422, detail="invalid_job_id")
        try:
            record = await request.app.state.jobs.get(job_id)
        except Exception:
            raise HTTPException(status_code=503, detail="jobs_unavailable") from None
        if record is None:
            raise HTTPException(status_code=404, detail="job_missing_or_expired")
        return record

    @app.post("/_faults")
    async def inject_fault(body: FaultIn, request: Request) -> dict[str, Any]:
        now = time.time()
        if not now < body.authorization_expires_at <= now + 25:
            raise HTTPException(status_code=403, detail="expired_or_unbounded_run_authorization")
        try:
            acknowledgement = await request.app.state.fault_coordinator.inject(body)
            return {**acknowledgement, "boot_id": request.app.state.boot_id}
        except FaultConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except Exception:
            raise HTTPException(status_code=503, detail={"reason": "injection_unconfirmed", "run_id": body.run_id}) from None

    @app.get("/_faults")
    async def fault_status(request: Request) -> dict[str, Any]:
        try:
            status = await request.app.state.fault_coordinator.status()
        except Exception:
            raise HTTPException(status_code=503, detail="target_state_unavailable") from None
        return {**status, "boot_id": request.app.state.boot_id}

    @app.delete("/_faults/{run_id}")
    async def clear_faults(run_id: str, request: Request) -> dict[str, Any]:
        if len(run_id) > 128 or not run_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise HTTPException(status_code=422, detail="invalid_run_id")
        try:
            acknowledgement = await request.app.state.fault_coordinator.clear(run_id)
            return {**acknowledgement, "boot_id": request.app.state.boot_id}
        except Exception:
            raise HTTPException(status_code=503, detail={"reason": "cleanup_pending", "run_id": run_id}) from None

    return app


app = create_app()
