# Sealed shipping specification

Nothing injects until policy unseals it.

## Authority and scope

Sealed is a local chaos control plane for one Compose demo. A draft is a proposal; approval is a recorded human input; the clerk alone authorizes unseal. Reseal requests stop fault effects and holds ownership until cleanup is confirmed. A seal is the immutable terminal record with verdict `pass`, `fail` or `aborted`.

The closed catalog contains exactly `redis_down`, `handler_latency` and `worker_drop`. Fault targets are only `api`, `redis` and `worker` inside Compose. No Kubernetes, external fault host, cloud fault API or production deployment exists. Prod is a denial example, never an injectable environment.

```text
web:5173 /api -> control:8081 -> signed run authorization -> target:8080
         /target ---------------------------------------> public probes
 target-web:5174 /api -----------------------------------> public probes
 target:8080 <-> redis:6379 <-> worker
 control:8081 <-> control-data (SQLite, independent of Redis)
```

All published ports bind to `127.0.0.1`. The supported process model is one control process/replica, one target process and one worker. Uvicorn workers are fixed at one; advisory locks enforce API ownership; SQLite uniqueness also prevents multiple active run records. Local operators are trusted. This is not a multi-user authentication system or a sandboxed agent process.

Optional inference is a **planner-only network exception**: an operator explicitly selects Ollama via `host.docker.internal` or xAI and enables `ALLOW_PLANNER_NETWORK=true`. These destinations never enter the fault-target allowlist. Stub mode is authoritative and requires no inference network. The product planner cannot unseal, reseal, inject, execute, invoke a shell, use Docker or issue arbitrary network requests.

## Catalog and policy contracts

The source of truth is `experiments/catalog.yaml` and `experiments/policy.yaml`, validated on startup. Unknown/duplicate catalog entries and contradictory configuration fail startup.

Admission requires demo, a compatible allowlisted target, a known catalog ID, positive finite duration at most 20 seconds, and no owner in reservation, injection, unsealed, cleanup or recovery. Only demo `handler_latency` at at most five seconds is auto-unseal eligible. All other admitted drafts require recorded approval. Manual draft creation explicitly auto-unseals eligible latency; planner proposals and game-day creation only save drafts.

The draft API retains well-formed non-demo and over-limit durations so operators can inspect policy denial. Malformed numbers, zero/negative duration, booleans in numeric fields, unexpected keys, incompatible targets and missing required assertions are rejected. Target privileged requests independently enforce the injectable bounds. Handler delay is bounded to 0–1000 ms; worker drop rate is 0–1. SLO p95 is finite within 0–60000 ms and HTTP error rate within 0–1. Custom hypotheses cannot remove the catalog's required assertion. Request bodies are bounded to 64 KiB.

## Lifecycle and recovery

```text
draft -> approved -> reserved -> injecting -> unsealed -> cleanup_pending
  |              (eligible drafts may reserve directly by policy)   |
  +-> cancelled (unused game-day draft)                    recovering
                                                                |
                                               completed or resealed
                                                                |
                                                       one immutable seal
```

Reservation and clerk evaluation happen atomically before target I/O. Same-run retries cannot start again; competing runs cannot pass admission. Terminal IDs are never replayable. Create another draft to rerun an experiment. Approval is idempotent while the run is startable. Duplicate aborts return the existing terminal outcome rather than writing another seal.

Control signs a run-scoped authorization with a generated server credential on `sealed-auth`; target checks identity, bounded expiry and HMAC. Identical duplicate delivery acknowledges the same deadline. Short-lived Redis receipts reject replay; status acknowledgements include run and target boot identity. Timed-out injection is reconciled, never blindly reinjected. Conditional cleanup for an older run cannot clear a newer run. Browser proxies strip privileged headers and reject private target routes.

The lifecycle owns a background scheduler; GETs do not drive completion. Target expiry is a bounded backstop. Cleanup failure holds admission and is retried with bounded backoff. Abort interrupts injected handler waits. The worker reads fault state at its processing decision; a decision already made before abort may still finish committing afterward. UI distinguishes requested cleanup, confirmed cleanup and measured recovery.

SQLite stores versioned drafts/game days, immutable event rows, immutable seals and configuration snapshots/hashes on `control-data`. Copies at repository boundaries prevent alias mutation. Unique constraints and transactions enforce one owner, one seal per run and atomic finalization. Startup cleans interrupted runs and fails them conservatively with a recovery reason; it does not resume injection. Target boot identity changes fail a run even after its last during-fault observation. Audit durability is independent of Redis.

This is persistent schema version 1; there is no migration for lost pre-remediation in-memory history. Existing legacy fixtures remain separate. Stop control before making a database backup. Keep named volumes during normal restarts/upgrades. Unknown future schema versions fail explicitly rather than overwriting history.

## Evidence and verdicts

The control service creates bounded business workload inside Compose: three baseline cycles, at most 24 during cycles, and three recovery cycles. Worker cycles contain three uniquely correlated jobs, at most 90 jobs across a run. Requests and job polling have deadlines. Observations record actual times, latency, HTTP status, correlation and results; session secrets are excluded. Late samples are not started when their bounded completion could extend beyond the injection deadline.

A passing simple run requires at least 3 baseline, 1 during and 3 recovery valid samples; worker runs require at least 9, 3 and 9 terminal job samples. Acknowledged effective duration must match the requested duration. Simulated, absent, malformed, incomplete or missing-recovery evidence cannot pass. Infrastructure errors remain explicit even if earlier samples looked good.

Checks evaluate each configured SLO and required assertion against recorded observations:

- `latency_recovers_after_reseal`: measurable latency increase during the handler fault, bounded by the configured SLO, followed by measured recovery.
- `fail_closed_on_redis_loss`: real 503 fail-closed session probes with no session credentials while faulted, and successful baseline/recovery probes. The Redis catalog permits the intentional during-fault HTTP error rate.
- `dropped_jobs_do_not_corrupt_queue`: uniquely correlated terminal jobs preserve exact payloads; intentional drops match the run; nonzero configured drop rate must produce observed drops; baseline/recovery jobs complete. HTTP error rate and job drop rate are separate measurements.

`pass` means all measured assertions, SLOs, authorization completeness and recovery checks succeeded. `fail` covers hypothesis, missing evidence and infrastructure failure with separate reasons. Explicit operator interruption is `aborted`, with available evidence and cleanup outcome retained. Natural expiry is never sufficient for pass.

The target's live metrics cover business `/probe`, `/login` and `/jobs` traffic only, using a consistent 60-second/200-sample window with per-route/run attribution. No samples is null, never a fabricated zero. Dashboard health/management requests do not dilute experiment measurements. Seal evidence is evaluated from the controlled workload, independently of dashboard polling frequency.

## Target and worker API

| Method/path | Behavior |
|---|---|
| `GET /health` | Observed API, Redis and worker states with timestamp/heartbeat age; 200 may be degraded |
| `GET /ready` | 200 only when dependencies are observed healthy, otherwise 503 |
| `GET /probe` | Non-mutating handler workload; latency faults apply |
| `POST /login` | Synthetic Redis session probe; failure is closed, never production authentication |
| `POST /jobs` | Atomic bounded enqueue; returns 202 and job identity |
| `GET /jobs?limit=&offset=` | Bounded retained history using batched reads; includes next offset |
| `GET /jobs/{id}` | Individual queued/processing/done/dropped/failed outcome |
| `GET/POST /_faults`, `DELETE /_faults/{run_id}` | Private authenticated run status, signed injection, conditional cleanup |

Worker readiness uses heartbeat freshness, not a constant green status. Temporary Redis failures use bounded backoff. Atomic Redis scripts enqueue, claim with a lease/token, and acknowledge. Interrupted claims have at most three attempts; intentional drops are terminal and are not retried. Queue capacity is 200, history is bounded to 1000 entries, job payloads to 8192 encoded bytes and terminal retention to 3600 seconds. Expired history entries are skipped coherently. Malformed historical job data produces an explicit read failure instead of a fabricated empty history.

## Control and operator API

- `/catalog`, `/policy`, `/health` expose configuration and control liveness.
- `/drafts` creates or lists bounded/searchable run summaries; `/drafts/{id}` returns the full run.
- `/drafts/{id}/approve`, `/unseal`, `/reseal` capture lifecycle operations for that exact identity.
- `GET /drafts/{id}/evaluate` is read-only policy preview; terminal runs are denied. The compatible POST preview also remains non-mutating.
- `/active-run` exposes current ownership; `/drafts/{id}/events` gives deterministic sequence pagination; `/drafts/{id}/seal` gives that run's terminal record.
- `/seals` lists bounded summaries; `/seals/{id}` returns immutable detail.
- `/game-days` creates all validated steps transactionally and lists resumable days. `/game-days/{id}/abort` aborts the active step. `/end` ends the day and cancels unused drafts without manufacturing seals for unexecuted work.
- `/agent/propose` accepts a bounded idempotency key and permits one proposal at a time. Planning is asynchronous with a 15-second overall deadline, bounded rounds/tools/output and no provider retries. Cancellation is scoped by proposal ID. Partial failure preserves at most one saved draft and reports actual provenance.
- `/agent/trace` contains bounded, sanitized planner diagnostics, distinct from immutable run events. Actual secret values and credential-bearing summaries are redacted.
- `/fixtures` remains a control API compatibility path. The web uses bundled `/replay/seals/` assets so replay does not require control or live dependencies.

The console separates its composer from selected run state, keeps scoped abort globally reachable, uses actual events/evidence and recovers selection from the URL/server. Per-action deduplication does not block abort behind planning. Polls are cancellable, non-overlapping and reject stale results. Missing or failed observations show loading, unknown, unavailable or stale states with last success; they cannot become healthy by default. Fixture contents are historical/synthetic and legacy absence of measured evidence is explicit.

## Packaging and verification

Default Compose web images contain built Vite assets, served by a non-root Node server with same-origin proxies, payload limits, absolute upstream deadlines and graceful shutdown. `/healthz` checks each web server alone. The optional `docker-compose.dev.yml` uses Vite hot reload inside Compose. `TARGET_APP_URL` affects only the local display link, with a localhost:5174 fallback.

Base-image digests, Python resolution and JS lockfiles are pinned. The default stub walkthrough and replay have no provider dependency. Initial builds/downloads are separate from offline operation. See `QUALITY.md` for executable gates, `WALKTHROUGH.md` for operator steps and `REMEDIATION.md` for finding-by-finding acceptance evidence.
