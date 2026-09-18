# Sealed — spec

Nothing injects until policy unseals it.

## Product

Sealed is a chaos **control plane** in front of a tiny demo app. Operators (and a planner agent) propose **drafts**. A **clerk** evaluates **policy**. Only then is a draft **unsealed** and allowed to inject. **Reseal** aborts. A **seal** is the immutable record of the run.

Interview shape: show that chaos is gated, prod is denied, abort works, and the agent cannot execute.

## Vocabulary

| Term | Meaning |
|------|---------|
| draft | Proposed experiment. Not injectable. |
| unseal | Policy allowed this draft to inject. |
| reseal | Abort / stop. Injection ends. |
| seal | Immutable run record. |
| clerk | Control-plane policy evaluator. The only unseal authority. |
| catalog | Closed list of three experiments. |
| policy | Rules in `experiments/policy.yaml`. |

## Topology (Compose only)

```
web:5173  →  control:8081  →  target:8080
                              ├─ Redis
                              └─ worker
         toxiproxy (optional) on Compose network only
```

No Kubernetes. No hosts outside Compose. Prod is not a deployable environment.

## Target (`apps/target`, port 8080)

| method | path | contract |
|--------|------|----------|
| `POST` | `/login` | Session via Redis. **Fail closed** if Redis is down (no login, no stale session). |
| `POST` | `/jobs` | Enqueue work for the worker. |
| `GET` | `/health` | Liveness of api / redis / worker as known to the target. |
| `GET` | `/metrics` | JSON: `p95_ms`, `error_rate`, `inflight`. |
| `POST` | `/_faults` | Apply an **unsealed** catalog fault. Reject if not unsealed. |

`/_faults` accepts only catalog ids: `redis_down`, `handler_latency`, `worker_drop`.

Fault delivery:

- `handler_latency` — in-process delay on the API handler (`delay_ms`)
- `worker_drop` — in-process drop on the worker (`drop_rate`)
- `redis_down` — toxiproxy (or equivalent in-process cut) against Compose Redis, not an external host

## Control (`apps/control`, port 8081)

- Serves catalog and policy as loaded from `experiments/`
- CRUD-ish drafts: create/list/get
- `POST .../approve` sets `approved: true` (still not injectable until clerk unseals)
- Clerk **unseal** / **reseal**
- Writes **seals** when a run ends
- Fixture replay endpoint namespace: `/fixtures`

Control never injects. It authorizes. Target injects only with a current unsealed run.

## Policy v0

Loaded from `experiments/policy.yaml`. All must hold to unseal:

1. `environment == demo`
2. `target` ∈ `{api, redis, worker}`
3. `duration_s <= 20`
4. Catalog `id` is required and exists in `experiments/catalog.yaml`
5. At most **one** unsealed run (`max_concurrent_unsealed: 1`)

**Auto-unseal:** only `handler_latency` with `duration_s <= 5` and `environment == demo`.

**Else:** `approved: true` is required after clerk evaluation.

**Deny:** `environment == prod` (and any environment not `demo`).

The clerk is the only unseal authority. UI approval is an input to policy, not a bypass.

## Hypothesis

Every draft carries a hypothesis object (JSON):

```json
{
  "slo": {
    "p95_ms": 500,
    "error_rate": 0.05
  },
  "must": [
    "fail_closed_on_redis_loss"
  ]
}
```

- `slo` — numeric bounds checked against `GET /metrics` (and recovery after reseal).
- `must` — named assertions that must hold (e.g. fail-closed login). Catalog entries pin the default `must` ids.

Catalog defaults:

| id | hypothesis `must` (primary) |
|----|-----------------------------|
| `redis_down` | `fail_closed_on_redis_loss` |
| `handler_latency` | `latency_recovers_after_reseal` |
| `worker_drop` | `dropped_jobs_do_not_corrupt_queue` |

## Verdict

A seal’s verdict is exactly one of:

| verdict | when |
|---------|------|
| `pass` | Hypothesis `slo` + `must` held |
| `fail` | Injection completed; hypothesis did not hold |
| `aborted` | Operator (or timeout/policy) **resealed** before completion |

Seals are immutable. No updates after write. Replay from `fixtures/seals/`.

## Agent (`packages/agent`)

Planner only. Proposes drafts from the catalog. Does not run them.

**Allowed tools**

- read catalog / policy / seals
- propose draft (hypothesis + catalog id + target + duration)
- explain why policy would allow or deny

**Forbidden tools**

- `execute`
- `unseal`
- `shell`

The product agent must not inject, unseal, or run host commands. Policy/clerk unseals. Humans approve non-auto drafts.

## Interview demos (four)

1. **Happy latency** — draft `handler_latency` (5s, 300ms delay) in `demo`. Auto-unseals. Probes show p95 rise; reseal/end recovers. Verdict `pass` if SLO/`must` hold.
2. **Deny prod** — same or any catalog id with `environment: prod`. Clerk denies. Nothing injects.
3. **Abort `redis_down`** — approved demo draft, unseal, `/login` fail-closed, operator abort **reseals**, verdict `aborted`.
4. **Agent proposes `worker_drop` and does not run** — planner emits a draft only. No execute, no unseal, no shell. Injection happens only if a human approves and the clerk unseals (out of band for this demo).

## Non-goals

- Kubernetes, mesh, or multi-cluster
- Hosts or faults outside Compose
- A fourth catalog fault
- Production as an environment
- Agent-driven unseal or execution
