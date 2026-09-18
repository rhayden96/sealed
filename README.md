# Sealed

Nothing injects until policy unseals it.

Sealed is a local chaos control plane for a small Compose demo. The clerk admits one bounded experiment at a time. An operator can approve a draft and abort an active run; the planner can only read, explain and propose. Finished runs carry immutable seals with measured baseline, during-fault and recovery evidence.

## Start the demo

Install Docker with Compose. Initial image and dependency downloads require network access; the running stub demo does not.

```sh
docker compose up --build
```

Open the [console](http://localhost:5173) and use **Open target app** to open the [target](http://localhost:5174) in another tab. All published ports bind to loopback: target API 8080, control API 8081, console 5173 and target app 5174. No external fault targets exist.

The optional Python 3.12 launcher provides an interactive menu or an explicit noninteractive mode:

```sh
python start.py --stub
python start.py --help
```

`start.bat` and `start.sh` forward the same flags. Stub is authoritative even when provider credentials are inherited. Configuration is written atomically to gitignored `.env.local`; the launcher never prints keys. See `--help` for optional provider/model arguments.

## Walk through the controls

1. In **Console**, select **Handler latency** and use **Create & auto-unseal**. The label announces that policy may start this five-second fault immediately. Let it finish, then inspect the selected run's measured evidence and `pass` seal.
2. Select the **prod (denial example only)** environment and create a draft. **Evaluate policy** explains the denial without injecting. Prod is never deployable.
3. Return to demo, create **Redis down**, then **Approve & unseal**. In the target app, **Probe session** fails closed. Use the global **Abort / reseal active run** button; wait for cleanup and recovery evidence, then probe the session again.
4. Use **Propose draft** after that aborted Redis run. The stub proposes Worker drop with agent origin. It remains a draft and cannot inject on its own.
5. Use **Tape** to select historical runs, read actual event times, expected/observed checks and the correct associated seal. **Game day** creates a resumable three-step sequence of drafts; aborting one step and ending the day are separate actions.

See [the full walkthrough](docs/WALKTHROUGH.md), [shipping contracts](docs/SPEC.md), [acceptance records](docs/REMEDIATION.md), and [quality commands](docs/QUALITY.md).

## Offline fixture replay

After one successful web image build, no live service or provider is required:

```sh
docker compose stop control target worker redis target-web
docker compose up -d --no-deps --pull never web
```

Open [Fixtures](http://localhost:5173/?view=fixtures). The web image contains exact files from `fixtures/seals/`. Legacy examples are labelled historical/synthetic and explicitly lack measured evidence. Replay performs no mutations. Downloads during the initial build are separate from this offline path.

Restore the live stack with `docker compose up -d`. Run `docker compose ps` and inspect `docker compose logs --tail 50` if startup is incomplete. The worker heartbeat and target `/ready` check must recover before new experiments can establish valid baselines. Intentional Redis faults can temporarily make target readiness unhealthy.

## Optional inference and the local boundary

The default stub makes no provider calls. Explicit `--llama` selects an already-running Ollama provider; explicit `--xai` uses `XAI_API_KEY` from the environment. These modes enable the documented **planner-only network exception** with `ALLOW_PLANNER_NETWORK=true`. They do not download models automatically, add tools, expand fault targets, or grant the planner unseal credentials. Fault operations always stay within Compose. Provider failures expose requested/actual provider, fallback reason and saved-draft outcome.

This is a local, single-operator demo. Control mutations are available to local clients; loopback binding and origin checks do not provide multi-user authentication. The target's privileged channel requires a generated server-only credential and a signed, short-lived run authorization. Browser proxies deny its private routes. The planner runs in the control process with a restricted tool registry; it is not an isolated security principal.

## State and recovery

`control-data` holds versioned SQLite drafts, game days, ordered events and immutable seals. The generated target credential is on the separate `sealed-auth` volume, mounted only by target and control. Neither depends on Redis audit durability.

A control restart preserves history, cleans an interrupted active run and seals it as failure with a recovery reason. It never re-injects that run. Target restart or missing observations cannot produce pass. Ownership remains held while cleanup is uncertain, with bounded retry and visible cleanup state. Explicit abort is `aborted`; infrastructure and hypothesis failures use `fail` plus separate reasons.

The supported model is one target process, one control process/replica and one worker. Enforced ownership locks and SQLite uniqueness supplement lifecycle admission. Terminal run IDs cannot be reused; create a new draft to repeat an experiment. An already-made worker decision may finish committing after abort; subsequent decisions read current fault state. Handler waits are interruptible.

This is the first persistent schema, version 1. Prior in-memory history cannot be recovered. Existing fixture JSON remains readable and is never promoted to measured evidence. Stop control before copying its SQLite database for backup; restore the database as a unit with the same schema version. `docker compose down` preserves named volumes; `down -v` removes history and the generated credential. Do not delete those volumes as a routine upgrade step.

## Development

The default frontend images serve built assets through a small Node HTTP server, with same-origin `/api` and `/target` proxies and bounded deadlines. `TARGET_APP_URL` configures the local target display link at runtime; its fallback is `http://localhost:5174`. It never configures injection destinations.

For frontend hot reload inside Compose:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Python dependencies and base-image digests are pinned; both JS lockfiles are retained. Unit, type, lint, build, browser and Compose checks are described in [QUALITY.md](docs/QUALITY.md). The CI workflow runs against the stub and local Compose services. No real external LLM is required.
