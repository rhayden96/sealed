# Milestone D rendered and packaged acceptance

Final acceptance passed on September 18, 2026. All six Compose services were left running and healthy, with no active experiment. The final runtime serves built browser assets, uses pinned dependency versions and base images, and defaults to the stub planner with provider networking disabled.

The reproducible browser harnesses are [operator correctness](../apps/web/tests/browser-acceptance.mjs) and [rendered acceptance](../apps/web/tests/rendered-acceptance.mjs). Results are retained as [36 rendered checks](D_BROWSER_RESULTS.json) and [15 packaged operator checks](D_PACKAGED_BROWSER_RESULTS.json), all passing. The final static-server and policy-preview check is [compose_acceptance_d.py](../apps/control/tests/compose_acceptance_d.py).

## Build and runtime verification

From the repository root in PowerShell:

```powershell
$env:PLANNER='stub'
$env:ALLOW_PLANNER_NETWORK='false'
$env:LLM_BASE_URL=''
$env:LLM_MODEL=''
$env:LLM_API_KEY=''
$env:XAI_API_KEY=''
docker compose --env-file NUL up -d --build
Get-Content -Raw apps/control/tests/compose_acceptance_a.py | docker compose exec -T control python -
Get-Content -Raw apps/control/tests/compose_acceptance_b.py | docker compose exec -T control python - smoke
Get-Content -Raw apps/control/tests/compose_acceptance_d.py | docker compose exec -T control python -
```

Use `/dev/null` instead of `NUL` on POSIX. The provider variables are cleared without printing any values. Every command exited 0. The A and B checks ran after the static/runtime rebuild; final review changes to game-day preview and defensive response handling were rebuilt and checked with focused D and browser regressions afterward. Unaffected restart and queue durability cases remain documented in [B_ACCEPTANCE.md](B_ACCEPTANCE.md).

| Packaged scenario | Observed result |
|---|---|
| Target fault administration | Missing/wrong token rejected for GET, POST and DELETE with 403; token without signed authorization also rejected |
| Browser boundary | All 18 privileged target-proxy requests returned 404; public health routes returned 200 |
| Prod approval and unseal attempt | Denied with no injection event and idle target |
| Redis abort | Login returned 503 during injection and 200 after cleanup; scoped abort took 20 ms and repeated abort returned the same seal |
| Stub proposal | Persisted as a draft while target remained idle |
| Half-second experiment without usable during evidence | Scheduler completed independently and recorded one conservative failure |
| Default handler latency | Pass; baseline/during/recovery p95 approximately 3.20 / 303.58 / 1.76 ms |
| Latency with a 100 ms p95 budget | Fail based on measured during-fault latency, with recovery evidence preserved |
| Redis completion | Pass with real fail-closed observations and successful recovery |
| Default worker drop | Pass: 54 during jobs, 44 done and 10 correlated drops, zero HTTP error rate; all nine baseline and nine recovery jobs done |
| Static web serving | Both `/healthz` responses identify `built-assets`; index references built assets and has CSP; application source and Vite client files return 404 |
| Game-day preview | Future step denied consistently by read-only GET evaluation and POST unseal with `step_skipped`; repeated evaluation creates no events; no injection occurred |

The focused game-day check ends its own test day, cancels both remaining drafts and verifies `/active-run` is null. Final `docker compose ps` reported `running / healthy` for control, Redis, target, target-web, web and worker.

## Browser reproduction

Install the pinned development dependencies and browser as described in [QUALITY.md](QUALITY.md). The final local run used repository-installed Playwright 1.61.1 and axe-core 4.11.2, with installed Chrome selected by `PLAYWRIGHT_CHANNEL`. Neither harness starts a host application server.

```powershell
$env:PLAYWRIGHT_CHANNEL='chrome'
$env:BROWSER_RESULTS_PATH='docs/D_PACKAGED_BROWSER_RESULTS.json'
$env:BROWSER_SCREENSHOT_PREFIX='packaged'
npm --prefix apps/web run test:rendered -- full
npm --prefix apps/web run test:browser -- live
npm --prefix apps/web run test:browser -- target-race
npm --prefix apps/web run test:browser -- target-invalid
docker compose stop control target worker redis target-web
docker compose up -d --no-deps --pull never web
docker compose ps --services --status running
npm --prefix apps/web run test:browser -- replay
docker compose --env-file NUL up -d
```

With Playwright's pinned Chromium installed, omit `PLAYWRIGHT_CHANNEL`. The offline service listing contained only `web`. Fixture replay rendered historical contents, hypothesis and the explicit legacy/missing-measured-evidence warning, with zero POST, PUT, PATCH or DELETE requests and zero browser page errors. All live services were restored after this check.

The packaged operator checks again verified selected-run identity after composer changes, correct approval/unseal routing, auto-unseal completion, target job retention during real Redis failure, fail-closed login, prod denial, and selected historical evidence. Global abort worked after navigation and refresh while a planner response was deliberately held pending; the packaged run resealed in 40 ms. Both frontends had no unhandled page errors.

Focused response tests additionally verified that malformed HTTP 200 health/jobs bodies retain labeled last-known observations. Prototype-named status strings render `Unknown` without a React crash. The older-poll regression confirmed that an observation begun before mutation-triggered refresh cannot overwrite cached jobs afterward.

## Rendered review and accessibility

Both frontends had no document-level horizontal overflow at 360, 390, 768, 1280 and 1440 CSS pixels. The effective 200% reflow check used a 720 × 450 CSS viewport corresponding to a 1440 × 900 display at 200%. This is viewport-equivalent reflow testing, not a claim that native browser zoom was automated; an attempted headless Chrome zoom preference did not alter its viewport and was not counted as proof.

The axe audits used WCAG 2 A/AA and 2.1 AA tags. All eight audited states reported zero violations: desktop/narrow console and target, fixture detail, measured evidence, recovery ownership, and planner diagnostics with fallback. The original narrow drawer's keyboard-scrollability issue was resolved. Tests reached navigation, replay, the target handler action and global abort by keyboard and verified visible two-pixel focus outlines.

The retained `D_RENDER_AUDIT.json` is the earlier exploratory audit, which identified that drawer issue before its fix. `D_BROWSER_RESULTS.json` contains the final passing rendered checks.

Long diagnostic logs produced axe contrast results marked incomplete for rows clipped by their scroll container. Their shared computed text styles were checked separately: secondary text has 8.33:1 contrast and primary text 16.36:1 against the opaque drawer background. These checks do not claim complete accessibility conformance or replace assistive-technology review.

At both 390 × 420 and 720 × 420, global abort stayed unobscured after scrolling, between approximately y=18 and y=62. Drawer height persisted at 540 pixels and clamped to 252 pixels in a 420-pixel viewport. Collapse state survived reload. Manual log scrolling paused Follow, three added entries increased the unread count without moving the log, and resuming Follow cleared the count and returned to the end. Requested xAI versus actual stub fallback provenance remained visible at 390 pixels.

Cleanup-pending, recovery-pending, long-log and provider-fallback screenshots use intercepted browser responses with the run ID `d-rendered-browser-fixture`. Their filenames end in `-mocked`; they are rendering checks, not new live failure or provider claims. The fallback response explicitly states that no provider was contacted. Real lifecycle and failure evidence comes from the Compose tests and packaged operator run.

## Screenshots

The Sealed and Shop visual direction is retained. Before/after images and focused states are available below; intermediate width captures also exist in `docs/screenshots/`.

| View | Before | After |
|---|---|---|
| Console desktop | [Original](screenshots/before-console-desktop.png) | [1440 px](screenshots/after-console-1440.png) |
| Console narrow | [Original](screenshots/before-console-narrow.png) | [390 px](screenshots/after-console-390.png) |
| Target desktop | [Original](screenshots/before-target-desktop.png) | [1440 px](screenshots/after-target-1440.png) |
| Target narrow | [Original](screenshots/before-target-narrow.png) | [390 px](screenshots/after-target-390.png) |

- [Measured evidence and phase comparison](screenshots/after-measured-evidence-desktop.png)
- [Active abort in a short narrow viewport](screenshots/after-active-abort-390-short-mocked.png)
- [Cleanup pending](screenshots/after-cleanup-pending-mocked.png) and [recovery pending](screenshots/after-recovery-pending-mocked.png)
- [Narrow planner fallback provenance](screenshots/after-planner-fallback-narrow-mocked.png)
- [Malformed target response with retained observations](screenshots/packaged-target-invalid-response-stale.png)
- [Standalone static fixture replay](screenshots/packaged-c-offline-fixture-desktop.png)

## Quality gates and limits

The final local quality run passed 220 Python tests, Ruff, the documented incremental mypy scope and `pip check`; 49 JavaScript tests passed across the console, shared static server and target browser. Both frontend ESLint, Prettier and production builds passed. The last additions to the acceptance harness passed their focused lint/format checks. Exact commands, dependency setup, launcher behavior and CI scope are documented in [QUALITY.md](QUALITY.md).

The remote CI workflow was added but was not executed remotely during this session. Legacy fixtures remain explicitly synthetic historical examples without measured evidence. Initial installation still requires dependency/image/browser downloads; the cached stub walkthrough and bundled fixture replay run without provider or internet dependencies.
