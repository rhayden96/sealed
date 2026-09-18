# Reliability remediation

Baseline: clean `main` at `0d1dcb9`, 2026-09-18. The supplied audit matches the checked-out source; none of its confirmed findings were already fixed. Findings 31 and 33 are design proposals requiring rendered verification.

## Sequence and acceptance

Work completed through four separate remediation sessions. Each session finished its checks and ten-bullet log before the next started. D planned and documented the requested `.github/workflows/` CI directory before creating it; all runtime code remains within the existing app/package layout.

- A: strict shared draft construction, admission reservation, terminal lifecycle, run-scoped target authorization and cleanup, responsive planning, loopback demo boundary.
- B: durable immutable records/events, autonomous lifecycle recovery, measured verdicts, worker/queue resilience, atomic game days.
- C: correct operator selection/status/actions/history, resilient clients, independent offline fixture details, target feedback.
- D: rendered accessibility/responsiveness, launcher and reproducible packaging, final integration gates and documentation.

An item is resolved only with implementation evidence and the applicable acceptance result. Runtime checks blocked by the environment remain explicitly unverified.

Final local acceptance: **220 Python tests**, **49 JavaScript tests**, Ruff, incremental mypy, dependency consistency, both frontend lint/format/build gates, real Redis integration, packaged Compose fault checks, responsive/accessibility browser checks and standalone offline replay passed. See [D acceptance](D_ACCEPTANCE.md) and [exact quality commands](QUALITY.md). All 42 findings are implemented; no implementation finding remains open. Native browser zoom was evaluated through equivalent 200% viewport reflow rather than a native zoom setting, and remote GitHub CI has not run. Optional real LLM providers were intentionally mocked, as requested.

## Baseline checks

- Both existing frontend production builds pass using `npm.cmd --prefix apps/web run build` and `npm.cmd --prefix apps/target-web run build` outside the sandbox (sandbox prevents esbuild child processes).
- Docker Desktop is available with escalated access; sandbox access to its named pipe is denied.
- Default `python` is 3.10; test environment uses installed Python 3.12 via `py -3.12 -m venv apps/control/.venv` and editable repository dependencies.
- Existing backend suite: **14 passed**. A final combined suite: **121 passed**, plus the subsequently added restart-identity test passed in the affected 24-test run. Live A acceptance: [commands and results](A_ACCEPTANCE.md).

## Findings

| ID | Priority | Finding | Status | Evidence / acceptance |
|---|---|---|---|---|
| 01 | P0 | Measured verdicts | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 02 | P0 | Atomic admission | Implemented A | A regression suite + live boundary checks; see A_ACCEPTANCE.md |
| 03 | P0 | Terminal lifecycle | Implemented A | A regression suite + live boundary checks; see A_ACCEPTANCE.md |
| 04 | P0 | Scoped injection/cleanup | Implemented A | A regression suite + live boundary checks; see A_ACCEPTANCE.md |
| 05 | P0 | Scheduler/reconciliation | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 06 | P0 | Verified abort | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 07 | P0 | Trust-boundary validation | Implemented A | A regression suite + live boundary checks; see A_ACCEPTANCE.md |
| 08 | P0 | Responsive planning | Implemented A | A regression suite + live boundary checks; see A_ACCEPTANCE.md |
| 09 | P0 | Local demo boundary | Implemented A | A regression suite + live boundary checks; see A_ACCEPTANCE.md |
| 10 | P1 | Durable immutable seals | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 11 | P1 | Worker health | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 12 | P1 | Useful metrics/workload | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 13 | P1 | Worker recovery | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 14 | P1 | Atomic job delivery | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 15 | P1 | Redis retention | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 16 | P1 | Atomic recoverable game days | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 17 | P1 | Shared construction/config | Implemented A | A regression suite + live boundary checks; see A_ACCEPTANCE.md |
| 18 | P1 | Planner output/fallback | Implemented A | A regression suite + live boundary checks; see A_ACCEPTANCE.md |
| 19 | P1 | Run events/redaction | Implemented B | Regression and Compose acceptance; see B_ACCEPTANCE.md and B_ACCEPTANCE_RESULTS.jsonl |
| 20 | P1 | Independent replay | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 21 | P1 | Truthful status | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 22 | P1 | Correct action/run binding | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 23 | P1 | Global abort | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 24 | P1 | Honest auto-unseal UX | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 25 | P1 | Mutation feedback | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 26 | P1 | Polling/API resilience | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 27 | P1 | Run history/seal association | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 28 | P1 | Actual event times | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 29 | P1 | Policy explanation | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 30 | P1 | Target feedback | Implemented C | Unit/build and Compose browser acceptance; see C_ACCEPTANCE.md and C_BROWSER_RESULTS.json |
| 31 | P2 | Responsive layout | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 32 | P2 | Accessibility | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 33 | P2 | Hierarchy | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 34 | P2 | Stable drawer | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 35 | P2 | Navigation/target link | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 36 | P2 | Cohesive modules | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 37 | P2 | Reproducible gates | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 38 | P2 | Failure matrix | Implemented A-D | 220 Python / 49 JS checks plus Redis, Compose and browser failure matrix; see D_ACCEPTANCE.md |
| 39 | P2 | Launcher modes | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 40 | P2 | Planner network scope | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 41 | P2 | Runtime/replay packaging | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
| 42 | P2 | Shipping documentation | Implemented D | Quality gates and packaged/browser acceptance; see D_ACCEPTANCE.md and QUALITY.md |
