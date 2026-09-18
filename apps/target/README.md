# Target (S1/S2)

Demo API. Python 3.12 + FastAPI. Compose port **8080**.

- `POST /login` — Redis session; fail closed if Redis is cut or unreachable
- `POST /jobs` — enqueue for the worker
- `GET /health` — `{status, api, redis, worker}`; any `down` ⇒ `degraded`
- `GET /metrics` — `{p95_ms, error_rate, inflight}`
- `POST /_faults` — `redis_down` | `handler_latency` | `worker_drop`
- `DELETE /_faults` — clear (reseal)

Faults are **in-process**. `POST`/`DELETE /_faults` require header `X-Sealed-Token` matching `UNSEAL_TOKEN`. Control is the only caller. Ungated inject is **403**.

## Pytest

```
cd apps/target
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest tests/test_health_redis_down.py
```

## Compose

From repo root: `docker compose up --build`.
