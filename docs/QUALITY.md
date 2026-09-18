# Quality gates

The demo runtime is Docker Compose. Python and Node on the host are development/test tools. Tests mock model providers; browser acceptance uses the stub planner. CI runs the Python gate on Windows and Linux, both frontend gates, then a Compose/browser job including standalone replay.

## Reproducible dependencies

Use Python 3.12 and Node 22. `packages/runtime.lock.txt` records exact versions exercised by the remediation environment and Linux demo images. `packages/dev.lock.txt` includes that runtime resolution plus exact test, lint, type-check and build tools. Platform markers select Windows colorama and Linux/macOS CPython uvloop. Local distributions are installed without additional dependency or build-isolation resolution:

```sh
python -m venv .venv
# Activate .venv (Windows: .venv\Scripts\Activate.ps1; POSIX: source .venv/bin/activate).
python -m pip install -r packages/dev.lock.txt
python -m pip install --no-deps --no-build-isolation -e packages/agent -e apps/control -e apps/target
python -m pip check
npm --prefix apps/web ci
npm --prefix apps/target-web ci
```

The lock captures versions, not an artifact hash manifest. Dependency changes are explicit: update the relevant lock/package-lock, reinstall in an isolated environment, run every affected gate, and rebuild Compose. Initial dependency, image and browser downloads require network access; the cached stub walkthrough and fixture replay do not.

Both JavaScript package locks remain authoritative through `npm ci`. Added developer tools are exact-pinned, including Playwright 1.61.1 and axe-core 4.11.2. ESLint 9 is pinned for the React ESLint plugin's supported peer range; it can be upgraded together with that plugin separately from runtime dependencies.

## Backend, planner and launcher

Run from the repository root with the development environment's Python:

```sh
python -m ruff check start.py apps/control apps/target packages/agent
python -m mypy
python -m pytest -q --tb=short
```

Ruff checks Python syntax/name errors, unused imports and other correctness rules throughout backend, planner, launcher and tests. The incremental mypy gate requires typed functions in the shared validated domain, policy clerk and metrics module; it does not claim the entire backend is fully typed. Pytest covers admission, lifecycle, evidence, restart, queue effects, planner isolation and input boundaries. Launcher tests mock every launch/provider operation. When Docker CLI is installed, an additional read-only `docker compose config` test verifies literal dotenv round-tripping; no engine or containers are required for that check.

The supported launcher flags are `python start.py --stub`, `--llama [--model NAME]`, `--xai [--model NAME]`, and `--help`. Explicit flags never prompt. Stub blanks inherited provider settings and disables planner networking in both the subprocess environment and atomically written `.env.local`. xAI requires an inherited `XAI_API_KEY`; the command never prints it. Noninteractive Llama requires an installed local model and does not download one. The optional interactive menu is retained when no flag is supplied in a terminal. Configuration rejects newline/NUL values, quotes special characters for Compose, and replaces files atomically with private POSIX permissions. Quoting follows the [Compose interpolation syntax](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/) and is verified with the installed Compose parser.

## Frontends and shared static server

```sh
npm --prefix apps/web run lint
npm --prefix apps/web run format:check
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/target-web run lint
npm --prefix apps/target-web run format:check
npm --prefix apps/target-web test
npm --prefix apps/target-web run build
```

Console tests include shared HTTP parsing, schema boundaries and the dependency-free static server/proxy tests under `packages/web`. ESLint checks both app sources and shared browser/server code, including hook dependency/rule checks. Formatting is enforced with Prettier; `npm run format` applies the same scope.

## Compose boundaries and browser evidence

```sh
docker compose up --build -d --wait --wait-timeout 180
# POSIX:
docker compose exec -T target python < apps/target/tests/redis_integration.py
docker compose exec -T control python < apps/control/tests/compose_acceptance_a.py
docker compose exec -T control python - smoke < apps/control/tests/compose_acceptance_b.py
# PowerShell equivalent:
# Get-Content -Raw apps/target/tests/redis_integration.py | docker compose exec -T target python
npm --prefix apps/web exec -- playwright install chromium
npm --prefix apps/web run test:browser -- live
npm --prefix apps/web run test:browser -- target-race
npm --prefix apps/web run test:browser -- target-invalid
npm --prefix apps/web run test:rendered -- full
docker compose stop control target worker redis target-web
npm --prefix apps/web run test:browser -- replay
docker compose up -d
```

Real Redis checks use a fixed isolated key prefix and remove only their own keys. They verify atomic admission, corrupted records, claim recovery, stale acknowledgement rejection, intentional drops, exhausted retries, queue capacity and exact retained payloads. Browser checks cover real Redis/worker effects, action identity, stale observations, pending abort, refresh, fixture-only operation, keyboard interaction, zoom and narrow layouts. Rendered checks run axe against the served pages and save screenshots/results under `docs/`. `PLAYWRIGHT_CHANNEL=chrome` optionally selects a locally installed Chrome; CI installs pinned Playwright Chromium.

The workflow is `.github/workflows/quality.yml`. Local results and runtime limitations belong in the remediation acceptance documents. A workflow file being present is not evidence that a remote CI run has occurred.
