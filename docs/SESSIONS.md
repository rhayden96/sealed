# Sessions

One milestone per session. Plan before new top-level dirs. After each session, append a 10-bullet summary here.

The original S0–S5 material below is historical scaffolding. The current reliability work is recorded under Remediation A–D later in this file; current behavior is defined in SPEC.md and verified in the acceptance records.

## S0 — harness (original session)

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

## Remediation A — lifecycle and trust boundary (2026-09-18)

Plan: establish baseline, centralize validation, reserve single-run ownership before target I/O, enforce terminal transitions, scope authorization and cleanup to a run, keep planning asynchronous, and restrict the demo to loopback. Acceptance includes concurrent admission, terminal retry, ambiguous delivery, cleanup failure, malformed inputs and slow-planner responsiveness. No new top-level directories. Later remediation milestones start only after this session's checks and ten-bullet summary.

### Remediation A — 10-bullet summary

1. Baseline matched reviewed revision; 14 original tests and both frontend builds passed under Python 3.12/Node with required sandbox access.
2. Shared strict draft/catalog/policy validation rejects malformed numeric values, unsafe parameters, unknown keys, incompatible targets and missing required assertions; well-formed prod/overlimit drafts remain denyable.
3. Admission reserves ownership before network I/O and retains it through injection, abort and verified cleanup; concurrent requests admit one injection.
4. Terminal run IDs cannot execute again; duplicate abort returns the same seal. Randomized identities fix a replay collision found during actual control restart.
5. Target accepts signed, bounded run authorization, acknowledges duplicate delivery, persists short-lived replay receipts, scopes cleanup by run, and reconciles target restart.
6. Abort cancels target latency waits; worker evaluates fault state after dequeue; failed cleanup remains visible and blocks further admission.
7. Server scheduler finalizes without browser reads. Until B adds measured evidence, expiry produces fail/missing evidence, never pass.
8. Planner is asynchronous, deadline/call bounded, schema validated, cancellable, and draft-only; stub mode overrides inherited provider variables and fallback provenance is explicit.
9. Loopback Compose ports, generated private credential volume, server-only privileged proxy exclusion and single-process ownership were implemented; final live A acceptance passed (see A_ACCEPTANCE.md).
10. 121 combined regression tests passed before the final identity test; 24 affected boundary/lifecycle checks passed afterward. Before screenshots captured desktop/390px overflow. Durable history, measured verdicts, worker/queue reliability and UI remediation remain for B–D; all closed-catalog/demo/planner invariants held.

## Remediation B — durable evidence and recovery (2026-09-18)

Plan: persist versioned immutable seals and authoritative events in SQLite on a Compose volume; reconcile interrupted owners; collect bounded baseline/during/recovery workload and evaluate assertions/SLOs; expose real worker health and business metrics; implement resilient bounded job processing and transactional game days. No new top-level directories. Acceptance: restart retention, immutable snapshots, passing/failing/missing-evidence verdicts, no-browser completion, recovery after Redis/worker interruption, atomic game days and queue retention. A introduced event and identity primitives early because ownership/idempotency required them.

### Remediation B — 10-bullet summary

1. SQLite stores versioned drafts, game days, immutable seals and ordered immutable run events on a dedicated Compose volume, independently of Redis.
2. SQL uniqueness defends single ownership and one seal per run; transactions make finalization and game-day creation atomic; copies prevent alias mutation.
3. Startup safely cleans interrupted runs without re-injecting, records an infrastructure reason, and preserves prior immutable history; bounded SQL summaries support navigation.
4. Controlled baseline/during/recovery workload records real observations, counts, timestamps, expected/observed checks and effective configuration hashes; missing or simulated evidence cannot pass.
5. All three catalog assertions and SLOs are evaluated. Actual target start/deadline and boot identity prevent shortened injections or late target restarts from producing pass.
6. Target metrics cover business traffic in consistent bounded windows; worker heartbeat freshness and readiness reflect actual stopped workers; job drop metrics are independent of HTTP errors.
7. Redis scripts atomically enqueue, lease and acknowledge bounded jobs, recover interrupted claims, preserve intentional drops and exact payload numbers, and retain bounded coherent history with MGET pagination.
8. Game days list/resume from server state; abort stops the current step while end cancels unused drafts. Planner diagnostics remain separately bounded and actual secret values are redacted.
9. Final combined backend/agent regression gate passed; real Redis integration passed seven groups. Live Compose proved measured latency pass, tight-SLO fail, Redis fail-closed/recovery, worker drops/recovery, immutable restart history, late-target-restart failure and stopped-worker readiness (see B_ACCEPTANCE.md and JSONL evidence).
10. No fourth fault, verdict or deployable environment was added; planner remains draft-only. Operator correctness, offline replay independence, frontend tests, rendered polish and final tooling/docs remain C–D. No new top-level directories.

## Remediation C — operator correctness and replay (2026-09-18)

Plan: bind run labels/actions to server identities, expose global active abort and actual events/evidence, model unavailable/stale state, use bounded cancellable non-overlapping API polling, add run history and policy explanations, make fixtures independently replayable, and repair the target app's probes/job feedback. Reuse the dark Sealed console identity and existing layout; extract focused panels/hooks where correctness requires it. Shared browser request helpers live under existing packages/. Fixture assets remain under fixtures/. No new top-level directories. Acceptance: browser flows for selection mismatch, refresh/abort, slow proposals, stale observations, correct seal association, policy denial, target outages and zero-mutation replay without live services; both builds and client tests.

### Remediation C — 10-bullet summary

1. Composer selection and existing run identity are independent; labels, approval, unseal, abort and evidence use the exact server run ID.
2. A global scoped abort banner survives navigation and refresh, remains usable while planning is pending, and distinguishes cleanup requests from confirmed recovery evidence.
3. History is bounded, searchable and filterable, with deep links for view, run and game day; evidence and immutable seals belong to the selected run.
4. Server event timestamps and sequence replace reconstructed audit times; effective parameters, hypotheses, origin, policy decisions and denial reasons are visible.
5. Auto-unseal actions explicitly announce immediate injection eligibility; agent proposals remain drafts, with visible provider provenance and cancellation.
6. Shared HTTP handling bounds requests and supports cancellation, malformed errors and endpoint shape validation. Independent polling retains visibly stale observations and rejects superseded responses.
7. Target handler probing uses GET /probe without enqueueing. Session, probe and job actions have separate feedback and duplicate guards; outage history remains visible.
8. Fixture contents are bundled into the web build and labelled historical/synthetic; standalone replay passed with all live services stopped and zero mutations or browser errors.
9. Both frontend builds passed; 32 console tests, 4 target state tests and the complete 205-test backend/planner suite passed. Compose browser flows passed, including the delayed pre-mutation job response regression (C_ACCEPTANCE.md / C_BROWSER_RESULTS.json).
10. Existing dark visual identity, three faults, demo-only policy, one-run ownership and draft-only planner are preserved. Rendered accessibility polish, production frontend serving, launcher, dependency gates and shipping documentation remain D; no new top-level directories were added in C.

## Remediation D — rendered polish and reproducible demo (2026-09-18)

Plan: verify and refine both apps at 360/390/768/1280/1440px and 200% zoom, keyboard focus and drawer stability; retain measured evidence and improve its presentation. Fix explicit noninteractive launcher modes and atomic secret-safe configuration; lock Python dependencies, add lint/type/build/test gates and CI; serve built frontend assets with bounded same-origin proxies and standalone fixture startup. Update scope, lifecycle, recovery and walkthrough documentation, then repeat final Compose/browser regression gates.

Layout addition planned before creation: `.github/workflows/` will contain the requested CI quality workflow only; it adds no runtime service or fault target. AGENTS.md's layout is updated alongside this plan. Shared frontend runtime/quality helpers and Python lock files stay under existing packages/. Optional inference networking is an explicit planner-only exception selected by the operator; all fault operations remain inside Compose and the default stub walkthrough makes no provider calls.

### Remediation D — 10-bullet summary

1. Both apps retain their visual identity with readable narrow layouts, labelled live status, touch/keyboard controls, visible focus and measured phase comparisons that reject absent/synthetic evidence.
2. Rendered checks passed at 360, 390, 768, 1280 and 1440px plus equivalent 200% viewport reflow; scoped abort remained reachable in short viewports. Native browser zoom itself could not be reliably automated and is not claimed as tested.
3. Planner drawer height is persisted with debouncing and viewport clamps; the focusable log preserves position, Follow state and unread counts. Eight audited states had no axe violations; offscreen clipped-log contrast was supplemented with explicit color-ratio checks.
4. Launcher flags are implemented and noninteractive; authoritative stub selection clears inherited provider settings. Fourteen launcher tests cover atomic quoting, secret-safe writes and actual read-only Compose dotenv parsing.
5. Python runtime/dev versions, frontend tooling and base-image digests are pinned. Ruff, incremental mypy, dependency consistency, ESLint, Prettier and both production builds passed. Final unit gates: 220 Python tests and 49 JavaScript tests; one upstream deprecation warning remains.
6. Default web images serve built assets as a non-root process, with same-origin public proxies, private-route/header exclusion, payload caps, absolute response deadlines, CSP and graceful shutdown. The documented Compose development override retains hot reload.
7. Target readiness and worker heartbeat health checks, restart policy and bounded shutdown are explicit. Final packaged A/B checks proved private-channel boundaries, measured pass/fail/abort, worker drops and an idle target after completion.
8. Final review fixed a game-day preview/admission mismatch and malformed HTTP200/prototype-name UI crashes; regression and live focused checks passed. Packaged browser flows and standalone offline replay passed with zero replay mutations.
9. README, SPEC, walkthrough, app READMEs, fixtures, planner scope, layout, migration/recovery and quality commands now match shipped behavior. Original scaffold prompts are marked historical. CI includes Windows/Linux Python, frontend and real Compose/browser gates; remote CI has not run because changes were not pushed.
10. Findings 01–42 are implemented with acceptance evidence in the remediation tracker. Three faults/verdicts, demo-only policy, single ownership, offline stub/replay and a draft-only product planner remain intact. All six local Compose services are healthy with no active run; no commit, push or external deployment was performed.
