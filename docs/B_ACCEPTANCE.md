# Milestone B evidence and recovery acceptance

Final acceptance passed on September 18, 2026. All application runtime checks use local Docker Compose, the three catalog faults, and the stub planner. No external provider is called. The reproducible scripts are [control acceptance](../apps/control/tests/compose_acceptance_b.py) and [isolated Redis integration](../apps/target/tests/redis_integration.py). Detailed measured output from the final boot-identity-aware runtime is retained in [B_ACCEPTANCE_RESULTS.jsonl](B_ACCEPTANCE_RESULTS.jsonl).

## Evidence contract

The control samples actual workloads before injection, while it is active, and after acknowledged cleanup. A baseline/recovery phase has three cycles; the fault phase has at most 24. Latency cycles call the non-mutating handler. Redis cycles attempt a synthetic login. Worker cycles submit three tagged jobs and inspect their terminal records, preserving ID, payload and fault-run correlation. This limits a run to 90 synthetic jobs, eight polls per job per cycle, and a two-second job-poll budget. Every individual HTTP request has a two-second total deadline.

The evaluator requires real samples, an acknowledged full-duration injection, cleanup confirmation, correct phase ordering and all configured SLO/assertion checks. It records expected and observed values, timestamps and sample counts. Login session values and transport exception text are never retained. Intentional job drops are reported separately from HTTP error rate. A target restart, control restart, missing observation phase or clipped authorization cannot produce a passing verdict.

The latency assertion requires a measured median rise of at least half the configured delay, successful requests, and recovery p95 no greater than the baseline median plus the larger of 75 ms or half that baseline. The Redis assertion requires observed 503 `fail_closed` responses without sessions, with successful baseline/recovery logins. The worker assertion requires at least one correlated drop when the configured probability is positive, unique intact terminal jobs, and all baseline/recovery jobs completed normally. A small positive drop probability can legitimately fail the assertion if no drop is observed within the bounded sample budget.

## Commands and results

From the repository root, in PowerShell:

```powershell
$env:PLANNER='stub'
docker compose --env-file NUL up -d --build target worker control
Get-Content apps/target/tests/redis_integration.py -Raw | docker compose exec -T target python -
Get-Content apps/control/tests/compose_acceptance_b.py -Raw | docker compose exec -T control python -
docker compose restart control
Get-Content apps/control/tests/compose_acceptance_b.py -Raw | docker compose exec -T control python - verify-restart
```

Use `/dev/null` instead of `NUL` on POSIX. The first control script deliberately leaves one bounded run active for the immediately following restart. Its checkpoint contains only run/seal IDs and hashes in `/data/b-acceptance-checkpoint.json`; credentials remain inside the control container.

The isolated Redis script passed seven groups: atomic enqueue without partial records; malformed history/queue records cannot break valid operations; abandoned-claim retry and stale-owner rejection; intentional drops remain terminal; exhausted recovery retries become failed jobs; capacity is atomic and released by completion; bounded history/results, pagination and expiry pruning. It additionally checks exact preservation of large-integer and decimal payloads. Its dedicated `sealed:integration:target-reliability:*` prefix is cleaned without touching live queue keys.

The measured run sequence verified:

| Scenario | Result |
|---|---|
| Default five-second handler latency | Pass, based on three baseline, four during and three recovery observations; final run p95 approximately 3.08 / 303.48 / 1.71 ms |
| Same latency with a 100 ms p95 SLO | Fails the measured during-fault SLO while preserving successful recovery evidence |
| Approved prod draft | Denied with 403, no injection event and idle target |
| Redis abort | Login fails closed while active; acknowledged scoped abort yields `aborted`; login recovers |
| Five-second Redis completion | Pass with actual fail-closed during observations and successful baseline/recovery |
| Default fifteen-second worker drop | Pass: 54 during jobs, 48 done and 6 correlated drops, unchanged payloads, zero HTTP error rate, all 9 baseline and 9 recovery jobs done |
| Control restart during an active run | Earlier seals retain identical hashes; interrupted run is cleaned and recorded exactly once as `fail / control_restarted` |

Runs complete while the acceptance client sends no requests during the entire authorized fault duration. Container health checks continue, but neither they nor browser polling drive control finalization.

## Final restart and health edge checks

The target restart check deliberately waits until only 1.5 seconds remain, after the scheduler stops starting new during-fault samples. Injection and cleanup acknowledgements include the target boot identity, allowing cleanup to detect this otherwise unobserved restart:

```powershell
Get-Content apps/control/tests/compose_acceptance_b.py -Raw | docker compose exec -T control python - prepare-target-restart
docker compose restart target
Get-Content apps/control/tests/compose_acceptance_b.py -Raw | docker compose exec -T control python - verify-target-restart
```

The final target-restart test passed: despite ten valid during observations and successful recovery, the changed boot identity yielded `fail / infrastructure_failure`, with confirmed cleanup and an idle target. It did not produce a false pass from the earlier good samples.

The real worker stop/recovery checks also passed:

```powershell
docker compose stop worker
try {
  Get-Content apps/control/tests/compose_acceptance_b.py -Raw | docker compose exec -T control python - worker-stopped
} finally {
  docker compose start worker
}
Get-Content apps/control/tests/compose_acceptance_b.py -Raw | docker compose exec -T control python - worker-recovered
```

After four seconds with the worker stopped, health reported `worker: down` and readiness returned 503. Restart restored a fresh heartbeat, `worker: ok` and readiness 200. The worker was left running. Every final acceptance command exited 0. The control-restart script includes a bounded readiness wait because Docker's restart command returns before the HTTP server necessarily accepts connections; an earlier attempt exposed that harness startup timing and was corrected without changing the application.

## Regression checks and boundaries

```powershell
$env:PYTHONPATH='apps/control/src;apps/target/src;packages/agent/src'
apps/control/.venv/Scripts/python.exe -m pytest apps/control/tests/test_evidence.py --import-mode=importlib -q --tb=short -p no:cacheprovider
```

Result: 41 passed, including measured passing examples for every catalog assertion; SLO failures; missing, simulated and malformed observations; incomplete authorization duration; phase timing; queue corruption/correlation; sample budgets; and secret-value omission. One existing Starlette deprecation warning was reported.

Control history now resides on the independent `control-data` volume. An interrupted run is failed conservatively after recovery instead of being resumed as a passing experiment. These results establish backend evidence and recovery behavior. Operator rendering, stale-state presentation, replay independence and visual/accessibility checks remain later milestone work.
