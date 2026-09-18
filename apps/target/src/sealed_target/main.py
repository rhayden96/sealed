"""Demo target API. POST /_faults requires X-Sealed-Token (control is the caller)."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from starlette.responses import Response

from sealed_target.faults import (
    CATALOG,
    FAULTS_KEY,
    Faults,
    UnknownCatalogId,
    publish_faults,
)

JOBS_KEY = "sealed:jobs"
JOB_IDS_KEY = "sealed:job-ids"
LATENCY_EXEMPT = {"/health", "/metrics", "/_faults"}
UNSEAL_HEADER = "X-Sealed-Token"


def require_unseal_token(request: Request) -> None:
    expected = os.environ.get("UNSEAL_TOKEN") or ""
    provided = request.headers.get(UNSEAL_HEADER) or ""
    if not expected or provided != expected:
        raise HTTPException(status_code=403, detail="not_unsealed")


class Metrics:
    def __init__(self) -> None:
        self.samples_ms: list[float] = []
        self.requests = 0
        self.errors = 0
        self.inflight = 0

    def record(self, duration_ms: float, error: bool) -> None:
        self.requests += 1
        if error:
            self.errors += 1
        self.samples_ms.append(duration_ms)
        if len(self.samples_ms) > 200:
            self.samples_ms = self.samples_ms[-200:]

    def snapshot(self) -> dict[str, float | int]:
        if self.samples_ms:
            ordered = sorted(self.samples_ms)
            idx = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
            p95 = ordered[idx]
        else:
            p95 = 0.0
        rate = (self.errors / self.requests) if self.requests else 0.0
        return {
            "p95_ms": p95,
            "error_rate": rate,
            "inflight": self.inflight,
        }


class LoginIn(BaseModel):
    username: str = "demo"


class JobIn(BaseModel):
    payload: Any = ""


class FaultIn(BaseModel):
    id: str
    duration_s: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)


def create_app(*, redis_factory: Callable[[], Any] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.faults = Faults()
        app.state.metrics = Metrics()
        if redis_factory is not None:
            app.state.redis = redis_factory()
        else:
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            app.state.redis = Redis.from_url(url, decode_responses=True)
        yield
        redis = app.state.redis
        close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
        if close is not None:
            result = close()
            if isinstance(result, Awaitable):
                await result

    app = FastAPI(lifespan=lifespan, title="sealed-target")

    @app.middleware("http")
    async def _observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        metrics: Metrics = request.app.state.metrics
        faults: Faults = request.app.state.faults
        faults.expire()
        metrics.inflight += 1
        start = time.perf_counter()
        error = False
        try:
            if (
                faults.is_active("handler_latency")
                and request.url.path not in LATENCY_EXEMPT
            ):
                delay_ms = float(faults.param("handler_latency", "delay_ms", 300))
                await asyncio.sleep(max(delay_ms, 0) / 1000.0)
            response = await call_next(request)
            error = response.status_code >= 400
            return response
        except Exception:
            error = True
            raise
        finally:
            metrics.inflight -= 1
            metrics.record((time.perf_counter() - start) * 1000.0, error)

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
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
        api_status = "ok"
        worker_status = "ok"
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
        }

    @app.get("/metrics")
    async def metrics_view(request: Request) -> dict[str, float | int]:
        return request.app.state.metrics.snapshot()

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

    @app.post("/jobs")
    async def enqueue_job(body: JobIn, request: Request) -> dict[str, str]:
        faults: Faults = request.app.state.faults
        faults.expire()
        if faults.is_active("redis_down"):
            raise HTTPException(status_code=503, detail="fail_closed")
        job_id = str(uuid.uuid4())
        record = {"id": job_id, "payload": body.payload, "status": "queued"}
        try:
            redis = request.app.state.redis
            await redis.set(f"sealed:job:{job_id}", json.dumps(record))
            await redis.lpush(JOB_IDS_KEY, job_id)
            await redis.lpush(JOBS_KEY, json.dumps({"id": job_id, "payload": body.payload}))
        except Exception:
            raise HTTPException(status_code=503, detail="fail_closed") from None
        return {"job_id": job_id}

    @app.get("/jobs")
    async def list_jobs(request: Request) -> dict[str, Any]:
        faults: Faults = request.app.state.faults
        faults.expire()
        if faults.is_active("redis_down"):
            raise HTTPException(status_code=503, detail="fail_closed")
        try:
            redis = request.app.state.redis
            ids = await redis.lrange(JOB_IDS_KEY, 0, 49)
            jobs = []
            for job_id in ids:
                raw = await redis.get(f"sealed:job:{job_id}")
                if raw:
                    jobs.append(json.loads(raw))
                else:
                    jobs.append({"id": job_id, "status": "unknown"})
        except Exception:
            raise HTTPException(status_code=503, detail="fail_closed") from None
        return {"jobs": jobs}

    @app.post("/_faults")
    async def inject_fault(body: FaultIn, request: Request) -> dict[str, Any]:
        require_unseal_token(request)
        faults: Faults = request.app.state.faults
        try:
            rec = faults.inject(body.id, body.duration_s, body.params)
        except UnknownCatalogId:
            raise HTTPException(
                status_code=400,
                detail=f"unknown catalog id (allowed: {', '.join(CATALOG)})",
            ) from None
        await publish_faults(request.app.state.redis, faults)
        return rec

    @app.delete("/_faults")
    async def clear_faults(request: Request) -> dict[str, str]:
        require_unseal_token(request)
        faults: Faults = request.app.state.faults
        faults.clear()
        try:
            await request.app.state.redis.delete(FAULTS_KEY)
        except Exception:
            pass
        return {"status": "resealed"}

    return app


app = create_app()
