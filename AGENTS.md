# Sealed — agent rules

Sealed is a chaos **control plane**. Nothing injects until **policy unseals** it.

This file is binding for every Grok Build session in this repo.

## Vocabulary

| Term | Meaning |
|------|---------|
| **draft** | A proposed experiment. Not injectable. |
| **unseal** | Policy has allowed this draft to inject. |
| **reseal** | Abort / stop an unsealed run. Injection ends. |
| **seal** | Immutable record of a finished run (pass, fail, or aborted). |

Policy is the only unseal authority. Humans approve; the clerk evaluates; the product agent never unseals.

## Stack

- Python 3.12
- FastAPI (target + control)
- React + Vite (web)
- Docker Compose (the only runtime)

Do not introduce Kubernetes, Helm, Terraform, cloud fault APIs, or fault targets outside Compose. Optional planner inference has the narrow exception documented below.

## Layout

```
apps/target/        demo API + in-process / toxiproxy faults
apps/control/       drafts, clerk (policy), unseal/reseal, seals
apps/web/           approve drafts, probes, abort, trace
apps/target-web/    synthetic session, handler and job probes
packages/agent/     planner — proposes drafts only
packages/web/       shared browser client and static demo server
packages/           pinned dependency and quality configuration
experiments/        catalog.yaml + policy.yaml
fixtures/           offline seal replay
docs/               SPEC, sessions, walkthrough, prompts
.github/workflows/  CI quality gates; no runtime infrastructure
```

Do not add new top-level directories without an explicit plan in the session and an update to this layout.

## Invariants (never violate)

1. **Product agent has no `execute`, `unseal`, or `shell` tool.** It may propose drafts and explain. It must not inject, unseal, or run host commands as part of the product.
2. **Policy is the only unseal authority.** `experiments/policy.yaml` decides. UI/API may set `approved=true`; they do not bypass the clerk.
3. **No Kubernetes.** Faults are in-process on the target or toxiproxy against Compose services.
4. **No fault hosts outside Compose.** Target, Redis, worker, control and the two web apps are the runtime. Optional toxiproxy must remain inside Compose. An operator may explicitly enable a planner-only Ollama or xAI provider using `PLANNER` plus `ALLOW_PLANNER_NETWORK=true`; this grants no fault tool, target, credential or execution authority. Stub is the default and offline walkthrough mode.
5. **Prod is forbidden.** Environment must be `demo`. Any `prod` draft is denied.
6. **Demo works offline** via console `/?view=fixtures` and its bundled replay assets. `/fixtures` remains a control API compatibility path. No live cluster or internet dependency for the cached stub walkthrough.
7. **Only three faults:** `redis_down`, `handler_latency`, `worker_drop`. No fourth catalog id.

## Fault catalog (closed)

| id | default duration | notes |
|----|------------------|-------|
| `redis_down` | 15s | Redis unreachable; `/login` fail-closed |
| `handler_latency` | 5s | `delay_ms: 300`; auto-unseal eligible in demo |
| `worker_drop` | 15s | `drop_rate: 0.2` |

Ids, actions, durations, targets, and hypotheses live in `experiments/catalog.yaml`. Policy lives in `experiments/policy.yaml`.

## Policy v0 (must match `experiments/policy.yaml`)

Unseal only when **all** hold:

- `environment == demo`
- `target` in `{api, redis, worker}`
- `duration_s <= 20`
- catalog `id` is present and known
- at most **one** unsealed run at a time

**Auto-unseal** only for `handler_latency` with `duration_s <= 5` in `demo`.

Every other draft requires `approved: true` after clerk evaluation.

Deny `environment == prod` (and any non-demo environment).

## Done means

A session that claims the product is demoable must satisfy:

1. `docker compose up` brings target (8080), control (8081), web (5173).
2. Operator approves a draft in the UI (or auto-unseal on eligible latency).
3. Probes go red while the fault is unsealed.
4. Abort **reseals**; injection stops.
5. Trace of the run is visible.
6. Fixture replay from `fixtures/` works offline.

Until those exist, this repo is **harness only**.

## Grok Build session rules

1. **Plan before new top-level dirs.** If a session needs a new root folder, write the plan in the session notes first and update this layout. Prefer the directories above.
2. **One milestone per session.** Follow `docs/SESSIONS.md`. Do not start S(n+1) work in Sn. Do not implement FastAPI/Vite/Compose in a harness-only session.
3. **10-bullet summary after each session.** Append it to `docs/SESSIONS.md` under that session: what landed, what did not, invariants still held.
4. Read `docs/SPEC.md` and `experiments/*.yaml` before changing behavior.
5. Paste-ready session prompts: `docs/GROK_PROMPTS.md`.
6. No application code, Docker implementation, or tests in S0. Later sessions implement only their milestone.
7. Do not add extra catalog faults, extra environments, or UUID-named directories.
8. Keep secrets out of git (`.env` is gitignored). Demo config is files in `experiments/` and `fixtures/`.

## Ports (loopback-only Compose bindings)

| service | port |
|---------|------|
| target  | 8080 |
| control | 8081 |
| web     | 5173 |
| target-web | 5174 |

## Supported runtime ownership

One target API process and one control process/replica are supported. Keep Uvicorn workers at one, the advisory ownership locks, SQLite active-run uniqueness and the scoped target authorization checks. SQLite on `control-data` is independent of the faulted Redis service. Admission stays owned through reservation, injection, cleanup and recovery. On restart, clean up interrupted runs and record failure; never re-inject automatically. Local demo ports are unauthenticated operator access, not a multi-user authorization system. The planner tool allowlist is an application boundary, not process isolation.
