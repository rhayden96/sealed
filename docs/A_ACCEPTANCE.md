# Milestone A runtime acceptance

Run on September 18, 2026, against the local Docker Compose services. These checks cover admission, target authorization, run-scoped cleanup and autonomous conservative completion. They do not claim evidence-based passing verdicts or durable control history; those belong to Milestone B.

## Commands

PowerShell, from the repository root:

```powershell
$env:PLANNER='stub'
docker compose --env-file NUL up -d --build
docker compose ps
Get-Content apps/control/tests/compose_acceptance_a.py -Raw | docker compose exec -T control python -
```

`NUL` selects an empty Compose environment file on Windows so a local `.env` is not loaded. On POSIX use `/dev/null`. Planner mode is explicitly `stub`, and provider networking is disabled by default. The acceptance script reads the private authorization file only inside control; it never prints or exports its contents.

The initial and final complete runs both exited 0 with these results:

| Check | Observed result |
|---|---|
| Compose startup | Target, control, Redis healthy; worker and both frontends running |
| Published ports | `127.0.0.1:8080`, `:8081`, `:5173`, `:5174` only |
| Direct target authorization | Missing/wrong token: GET, POST and scoped DELETE all 403 |
| Run authorization | Correct private token without signed body still returns 403 |
| Browser target boundary | 18 private proxy requests, including encoded path and scoped cleanup variants, return 404; public health routes return 200 |
| Prod denial | Approved prod draft unseal returns 403 `environment_denied`; no `inject_requested` event; authenticated target state idle before and after |
| Redis fault | Approved demo run unseals; login returns 503 `fail_closed` |
| Abort and recovery | Abort returns in 11 ms on the final run (5 ms initial) with confirmed cleanup and an `aborted` seal; target idle and login 200 afterward |
| Idempotency | Repeated abort returns the same seal; terminal unseal returns 409 |
| Product agent | Explicit stub creates an agent-origin draft only; target stays idle |
| Autonomous expiry | A 0.5-second latency run produces exactly one `fail` seal with reason `missing_measured_evidence` after 1.2 seconds without requests |

The first script draft placed the planner check after a latency seal; the stub correctly returned no proposal because its trigger is the latest failed/aborted Redis seal. The check was moved immediately after the Redis abort and the complete script passed. No product behavior was changed for that correction.

## Independent review and final rebuild

The review verified that the lifecycle reserves ownership before target I/O, keeps cleanup pending ownership in the concurrency count, refreshes abort state after I/O, and scopes target cleanup by run ID. A gap in target acknowledgement validation was reported and fixed: both the initial delivery and timeout reconciliation now verify run identity, fault, parameters, duration, active status and bounded finite deadline.

The final control image was rebuilt using:

```powershell
$env:PLANNER='stub'
docker compose --env-file NUL up -d --build control
```

The rerun exposed reuse of sequence-based run IDs after a control restart: target rejected an old `d-4` receipt, correctly preventing replay, but the new control draft failed admission. Run IDs now include a random 96-bit suffix, so a fresh control process cannot reuse a target receipt identity. This was brought into A as a run-identity prerequisite. Target receipts and state were preserved throughout.

The final rebuild and complete acceptance rerun both exited 0:

```powershell
$env:PLANNER='stub'
docker compose --env-file NUL up -d --build --no-deps control
Get-Content apps/control/tests/compose_acceptance_a.py -Raw | docker compose exec -T control python -
```

This final run includes strict target acknowledgement validation, randomized identities, and the proposal cancellation endpoint. The endpoint is present in the running OpenAPI schema; cancellation and slow-planner races are additionally covered by backend regression tests. A successful run here establishes A's service boundary behavior. Control history remains memory-only until B, and a missing-evidence `fail` is the only automatic completion verdict implemented at this milestone.

## Browser baseline

Headless Chrome with local Playwright captured unchanged running Compose pages before UI changes. No page JavaScript errors were observed.

| App | Desktop 1440 x 1000 | Narrow 390 x 844 |
|---|---|---|
| Console | [Before desktop](screenshots/before-console-desktop.png) | [Before narrow](screenshots/before-console-narrow.png) |
| Target | [Before desktop](screenshots/before-target-desktop.png) | [Before narrow](screenshots/before-target-narrow.png) |

Console document width was 532 px at a 390 px viewport; its fixed sidebar truncates the workspace and run actions. The target app fit the 390 px viewport. Responsive repair and after screenshots remain later milestone work.
