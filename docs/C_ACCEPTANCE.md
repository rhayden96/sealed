# Milestone C operator correctness acceptance

Final acceptance passed on September 18, 2026. The browser harness is [browser-acceptance.mjs](../apps/web/tests/browser-acceptance.mjs). It drives only the local Docker Compose applications. The live checks create bounded demo runs using the stub planner, abort their own active runs during cleanup, and leave immutable run history available for review. All 13 browser results are retained in [C_BROWSER_RESULTS.json](C_BROWSER_RESULTS.json).

## Reproduction

From the repository root in PowerShell, build the current UI and control source:

```powershell
$env:PLANNER='stub'
docker compose --env-file NUL up -d --build --no-deps web target-web control
$env:PLAYWRIGHT_MODULE='C:/Users/hayde/AppData/Local/npm-cache/_npx/420ff84f11983ee5/node_modules/playwright'
$env:PLAYWRIGHT_CHANNEL='chrome'
node apps/web/tests/browser-acceptance.mjs live
node apps/web/tests/browser-acceptance.mjs target-race
```

The milestone C run uses an already installed Playwright package and Chrome. `PLAYWRIGHT_MODULE` can name another installed Playwright package; with the repository test dependency installed, omit the override. The application servers remain inside Compose. Test dependency installation and the final packaged runtime are part of milestone D.

The standalone offline replay check stops every live backend and the target browser application, retaining only the console container:

```powershell
docker compose stop control target worker redis target-web
docker compose up -d --no-deps --pull never web
docker compose ps --services --status running
node apps/web/tests/browser-acceptance.mjs replay
$env:PLANNER='stub'
docker compose --env-file NUL up -d
```

Use `/dev/null` instead of `NUL` on POSIX. Fixture files are copied into the web image at build time. Replaying them does not depend on the control, target, worker, Redis, an external provider, or internet access.

## Scope of browser assertions

The live harness verifies actual request routing and persisted outcomes for handler auto-unseal; Redis approval and scoped abort; prod policy denial; selected-run evidence; target handler probing; queued jobs; and Redis fail-closed login. It also deliberately holds a planner response to verify that pending planning cannot disable the global abort. Health polling failures and malformed successful responses are intercepted to exercise stale-cache rendering. A separate target polling case uses intercepted job responses to establish that a pre-mutation response cannot overwrite the last valid observation after a refresh.

The harness records request methods and paths. It verifies that the handler action sends `GET /probe` without creating jobs, rapid repeated enqueue sends only one POST while pending, and offline replay sends zero POST, PUT, PATCH or DELETE requests. Both applications must finish with no unhandled browser page errors.

## Final results

Both browser frontends and control were rebuilt after the final response validation and polling revision fixes. Every command above exited 0. `docker compose ps --services --status running` returned only `web` for the offline run; all six services were restored afterward.

| Scenario | Observed result |
|---|---|
| Handler action | One `GET /api/probe`, zero job-creation requests |
| Repeated enqueue activation while pending | Exactly one POST; pending button disabled |
| Explicit latency auto-unseal | Five-second run completed with measured `pass` seal |
| Composer switched to Worker during selected latency | Selected metadata and run ID remained latency |
| Composer switched to Worker before Redis approval | Approve and unseal requests both addressed the selected Redis run |
| Target during Redis outage | Last-known job list remained visible; session probe returned 503 and explained fail-closed behavior |
| Navigation, refresh, and pending planner | Global active-run banner recovered the same Redis ID; abort remained enabled and resealed in 86 ms; final verdict `aborted` |
| Failed or malformed successful health polling | Prior observations remained labeled stale; malformed HTTP 200 HTML did not replace them |
| Prod denial example | Explicit clerk evaluation returned `environment_denied` with no injection |
| Historical selection | Earlier latency seal and evidence identified the selected run, independently of newer aborted/denied runs |
| Target stale request race | A held pre-mutation GET could not replace the initial cache after mutation-triggered refresh; subsequent failed polling retained the original jobs as stale |
| Standalone fixture replay | Historical fixture, hypothesis and explicit missing-measured-evidence warning rendered with no live services, zero mutations and zero browser page errors |

The planner delay, health failure payloads and isolated polling-race responses are browser interceptions, not live backend assertions. The fault lifecycle, job enqueue, fail-closed login, policy denial and persisted seals use actual Compose services. Intermediate harness attempts exposed a text matcher, an exact-label selector, and a StrictMode initial-fetch assumption; the corrected harness produced the final passing artifact.

## Review artifacts

Desktop and narrow screenshots preserve the original Sealed and Shop visual direction while recording the corrected states:

- [Selected latency with Worker composer](screenshots/c-console-auto-unseal-desktop.png)
- [Global abort while planner is pending](screenshots/c-console-planner-pending-active-abort.png)
- [Stale health with retained observations](screenshots/c-console-stale-health-desktop.png)
- [Prod policy denial](screenshots/c-console-prod-denied-desktop.png)
- [Selected historical evidence, desktop](screenshots/c-console-selected-evidence-desktop.png) and [narrow](screenshots/c-console-selected-evidence-narrow.png)
- [Target Redis outage](screenshots/c-target-redis-outage-desktop.png) and [target after recovery, narrow](screenshots/c-target-recovered-narrow.png)
- [Standalone fixture replay, desktop](screenshots/c-offline-fixture-desktop.png) and [narrow](screenshots/c-offline-fixture-narrow.png)

These are operator-correctness artifacts. Final spacing, contrast, keyboard interaction, accessibility audit and packaged static runtime checks belong to milestone D.
