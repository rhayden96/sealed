# Control (S2)

Chaos control plane. Python 3.12 + FastAPI. Compose port **8081**.

- Loads `experiments/catalog.yaml` and `experiments/policy.yaml`
- Drafts → clerk (policy) → unseal / reseal → **seal**
- Policy is the only unseal authority
- Auto-unseal: `handler_latency` ≤ 5s in `demo` only
- Else `approved: true`; deny `prod`; `duration_s > 20`; max one unsealed
- Target `POST /_faults` is token-gated; control is the only caller

## Pytest

```
cd apps/control
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest tests/test_policy_denies.py
```

## Compose

From repo root: `docker compose up --build` — `target`, `redis`, `worker`, `control`.
