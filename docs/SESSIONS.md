# Sessions

One milestone per session. Plan before new top-level dirs. After each session, append a 10-bullet summary here.

## S0 — harness (this session)

**Goal:** Repo layout, spec, catalog, policy, session prompts. No application code.

**Land:** `AGENTS.md`, `README.md`, `.gitignore`, `docs/*`, `experiments/*`, `fixtures/*`, placeholder app READMEs.

**Do not:** FastAPI, Vite, Compose services, tests, extra folders.

## S1 — target + faults

**Goal:** Demo target on Compose port 8080 with Redis + worker.

- `POST /login` (Redis, fail closed)
- `POST /jobs`
- `GET /health`
- `GET /metrics` (`p95_ms`, `error_rate`, `inflight`)
- `POST /_faults` for the three catalog ids only: `redis_down`, `handler_latency`, `worker_drop`

Faults are in-process or toxiproxy against Compose. No hosts outside Compose. No k8s.

## S2 — control plane

**Goal:** Control API on 8081.

- Load `experiments/catalog.yaml` and `experiments/policy.yaml`
- Drafts (proposed, not injectable)
- Clerk evaluates policy; policy is the only unseal authority
- Unseal / reseal; max one unsealed run
- Auto-unseal only `handler_latency` ≤ 5s in `demo`
- Else require `approved: true`
- Deny `prod`
- Persist **seals** (immutable run records) with verdict `pass | fail | aborted`

## S3 — UI

**Goal:** React + Vite on 5173.

- Approve a draft
- Probes go red while unsealed
- Abort reseals
- Trace of the run visible
- No execute/unseal from the browser except via control’s clerk

## S4 — planner (no execute)

**Goal:** `packages/agent` proposes drafts only.

- Allowed: read catalog/policy, propose a draft, explain hypothesis
- Forbidden: `execute`, `unseal`, `shell`
- Interview path: agent proposes `worker_drop` and does **not** run it

## S5 — fixtures + walkthrough

**Goal:** Offline demo.

- Seal fixtures under `fixtures/seals/`
- Replay via `/fixtures` (no live cluster required for the story)
- Execute `docs/WALKTHROUGH.md` end-to-end: compose up → approve → red probes → abort reseal → trace + fixture replay

## Session log

### S0 — 10-bullet summary

1. Harness only: docs, catalog, policy, gitignore, placeholder READMEs. No FastAPI, Vite, Compose, or tests.
2. Vocab locked: draft / unseal / reseal / seal; clerk is the only unseal authority.
3. Layout exists: `apps/{target,control,web}`, `packages/agent`, `experiments`, `fixtures/seals`, `docs`.
4. Stack recorded: Python 3.12, FastAPI, React+Vite, Docker Compose; ports 8080 / 8081 / 5173.
5. Invariants in `AGENTS.md`: no execute/unseal/shell on the product agent; no k8s; Compose-only; prod forbidden; offline `/fixtures`; three faults only.
6. Catalog: `redis_down` 15s (`fail_closed_on_redis_loss`), `handler_latency` 5s (`delay_ms` 300, auto-unseal eligible), `worker_drop` 15s (`drop_rate` 0.2).
7. Policy v0: demo only, targets `api|redis|worker`, `max_duration_s` 20, max one unsealed, auto-unseal latency ≤5s demo, else `approved: true`, deny prod.
8. Spec covers target endpoints, hypothesis `{slo, must}`, verdicts `pass|fail|aborted`, four interview demos.
9. Walkthrough: five steps + 30-second catalog / policy / clerk / seal mapping; paste-ready S0–S5 prompts in `docs/GROK_PROMPTS.md`.
10. Next session is S1 (target + faults) only. No new top-level dirs.

### S1

Target + Compose (`target` / `redis` / `worker`) + pytest: health degrades on `redis_down`. `/_faults` ungated until S2.

### S2

Control `:8081`: clerk, drafts, unseal/reseal, seals. `/_faults` token-gated. Denies prod, duration>20, two unsealed.

### S3

Web `:5173` against control: catalog, draft, approve/unseal, abort reseal, timeline, last seal. No agent. No policy changes.

### S4

Planner: `POST /agent/propose`. Stub proposes `worker_drop` draft after aborted/failed `redis_down`. No unseal. No policy changes.

### S5

Fixtures + walkthrough + README is compose up → :5173. `/fixtures` replays seals, does not inject. UI Approve also unseals (clerk still the key).
