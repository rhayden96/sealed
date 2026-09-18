# Grok Build prompts (S0–S5)

Paste one prompt per session. Read `AGENTS.md` and `docs/SPEC.md` first. One milestone only. End with a 10-bullet summary appended to `docs/SESSIONS.md`.

---

## S0 — harness only

```
This repo is empty. Create ONLY the Sealed harness. No application code, no Docker implementation, no Python/React yet.

Product: Sealed — chaos control plane. Nothing injects until policy unseals it.
Vocab: draft = proposed experiment; unseal = allowed to inject; reseal = abort/stop; seal = immutable run record.

Create these files exactly (paths from repo root):

AGENTS.md
- Stack: Python 3.12, FastAPI, React+Vite, Docker Compose
- Invariants: product agent has no execute/unseal/shell tool; policy is the only unseal authority; no k8s; faults are in-process or toxiproxy against Compose; no hosts outside Compose; prod forbidden; demo must work offline via /fixtures; only three faults: redis_down, handler_latency, worker_drop
- Layout: apps/target, apps/control, apps/web, packages/agent, experiments, fixtures, docs
- Done means: compose up, approve a draft in UI, probes go red, abort reseals, trace visible, fixture replay works
- Grok Build session rules: plan before new top-level dirs; one milestone per session; 10-bullet summary after each session

README.md
- One-liner and “harness only, app built in later sessions”
- Placeholder compose ports: target 8080, control 8081, web 5173

.gitignore
- node_modules, dist, .venv, __pycache__, .env, .grok, .pytest_cache

docs/SESSIONS.md — S0 plan, S1 target+faults, S2 control plane, S3 UI, S4 planner no execute, S5 fixtures+walkthrough

docs/SPEC.md
- Target: POST /login (Redis, fail closed), POST /jobs, GET /health, GET /metrics (p95_ms, error_rate, inflight), POST /_faults
- Policy v0: environment==demo, target in api|redis|worker, duration_s<=20, catalog id required, max one unsealed run; auto-unseal only handler_latency <=5s demo; else approved=true
- Hypothesis JSON with slo + must
- Verdict pass|fail|aborted
- Agent tools allowed/forbidden as above
- Four interview demos: happy latency, deny prod, abort redis_down, agent proposes worker_drop and does not run

docs/WALKTHROUGH.md — five-step demo outline + 30-second mapping (catalog/policy/seal/clerk)

docs/GROK_PROMPTS.md — paste-ready prompts for S0–S5

experiments/catalog.yaml — the three experiments with ids, actions, default durations, allowed_targets, hypotheses:
- redis_down 15s, fail_closed_on_redis_loss
- handler_latency 5s, delay_ms 300, auto-unseal eligible
- worker_drop 15s, drop_rate 0.2

experiments/policy.yaml — demo only, target allowlist, max_duration_s 20, max_concurrent_unsealed 1, auto_unseal rule, deny prod

fixtures/README.md + fixtures/seals/.gitkeep
apps/target/README.md
apps/control/README.md
apps/web/README.md
packages/agent/README.md

Do not implement FastAPI, Vite, compose services, or tests.
Do not add extra folders or UUID directories.
When finished, list every file created and wait.
```

---

## S1 — target + faults

```
Read AGENTS.md, docs/SPEC.md, docs/SESSIONS.md (S1), and experiments/catalog.yaml.

Implement ONLY the demo target (apps/target) and Compose services it needs: API, Redis, worker, and toxiproxy if required for redis_down. Python 3.12 + FastAPI. Port 8080.

Endpoints:
- POST /login — Redis-backed; fail closed if Redis is down
- POST /jobs — enqueue for the worker
- GET /health
- GET /metrics — p95_ms, error_rate, inflight
- POST /_faults — only catalog ids redis_down, handler_latency, worker_drop

Faults: in-process or toxiproxy against Compose. No k8s. No hosts outside Compose. No prod. No control plane, no UI, no agent.

handler_latency: delay_ms 300 on the API handler.
worker_drop: drop_rate 0.2 at the worker.
redis_down: cut Redis so /login fails closed.

Do not add a fourth fault. Do not add new top-level dirs without a plan.
When done, append a 10-bullet summary under S1 in docs/SESSIONS.md.
```

---

## S2 — control plane

```
Read AGENTS.md, docs/SPEC.md, docs/SESSIONS.md (S2), experiments/catalog.yaml, and experiments/policy.yaml.

Implement ONLY apps/control (FastAPI, port 8081). Load catalog + policy from experiments/.

- Drafts are proposed experiments; they do not inject
- Clerk evaluates policy; policy is the only unseal authority
- Unseal requires: environment==demo, target in api|redis|worker, duration_s<=20, catalog id required, max one unsealed run
- Auto-unseal only handler_latency with duration_s<=5 in demo
- Else approved=true
- Deny environment==prod
- Reseal aborts / stops
- Seals are immutable records with verdict pass|fail|aborted
- Hypothesis JSON: { slo, must }

Control authorizes; it does not inject. Target injects only when unsealed.
No UI, no agent execute/unseal/shell, no k8s, no extra faults.
When done, append a 10-bullet summary under S2 in docs/SESSIONS.md.
```

---

## S3 — UI

```
Read AGENTS.md, docs/SPEC.md, docs/SESSIONS.md (S3), and docs/WALKTHROUGH.md.

Implement ONLY apps/web (React + Vite, port 5173) against the control plane.

Must:
- Approve a draft in the UI
- Show probes going red while a run is unsealed (p95_ms, error_rate, inflight)
- Abort reseals; injection stops
- Trace of the run visible (draft → unseal → metrics → reseal → seal)

No execute/unseal/shell in the product agent. UI approval is an input to the clerk, not a bypass of policy.
Do not start the planner package. Do not add extra catalog faults or top-level dirs.
When done, append a 10-bullet summary under S3 in docs/SESSIONS.md.
```

---

## S4 — planner, no execute

```
Read AGENTS.md, docs/SPEC.md, and docs/SESSIONS.md (S4).

Implement ONLY packages/agent: a planner that proposes drafts from the catalog.

Allowed: read catalog/policy/seals, propose a draft, explain allow/deny.
Forbidden: execute, unseal, shell. The agent must not inject or unseal.

Interview demo 4: agent proposes worker_drop and does not run it.
Policy remains the only unseal authority. Humans approve non-auto drafts.

Do not add Compose services, extra faults, or new top-level dirs.
When done, append a 10-bullet summary under S4 in docs/SESSIONS.md.
```

---

## S5 — fixtures + walkthrough

```
Read AGENTS.md, docs/SPEC.md, docs/WALKTHROUGH.md, and docs/SESSIONS.md (S5).

Implement fixtures and finish the demo path. No new product features beyond fixtures + walkthrough wiring.

- Store replayable seals under fixtures/seals/
- Demo must work offline via /fixtures
- Walk the five steps: compose up, approve a draft, probes go red, abort reseals, trace visible + fixture replay
- Cover the four interview demos: happy latency, deny prod, abort redis_down, agent proposes worker_drop and does not run

Done means: compose up, approve a draft in UI, probes go red, abort reseals, trace visible, fixture replay works.

When done, append a 10-bullet summary under S5 in docs/SESSIONS.md.
```
