# Operator walkthrough

Run `docker compose up --build`, then open http://localhost:5173 and **Open target app** in a second tab. Use the default stub planner. After the initial cached build, this walkthrough requires no internet connection. Wait for observed services to become healthy; `docker compose ps` reports readiness and `docker compose logs --tail 50` supplies startup diagnostics.

## Measured latency pass

1. Open **Console** and choose **Handler latency** in **New experiment**. Keep environment **demo**. Inspect the parameters (`delay_ms: 300`), hypothesis and auto-unseal explanation.
2. Select **Create & auto-unseal**. Policy may immediately admit this five-second experiment. The global banner and selected run show the same run ID, fault, effective parameters and status.
3. In the target app select **Hit handler**. It probes a handler without creating a job. Latency rises; service liveness can remain healthy. The console names the active fault separately from service health.
4. Let the run expire. The control workload proceeds without manual clicks or browser polling. Wait until cleanup and recovery complete and a terminal seal appears.
5. In **Run evidence & tape**, inspect baseline/during/recovery counts, measured p95, expected versus observed checks, verdict reason and raw observations. The default hypothesis passes only if its actual measurements succeed; a slow/unhealthy machine may correctly produce failure. Never treat a timer expiry or legacy fixture as proof of pass.

## Prod denial with no injection

1. In **New experiment**, choose **prod (denial example only)**. The action becomes **Create draft**.
2. Create it, then choose **Evaluate policy** on that selected run. The clerk explains that only demo may unseal. This preview writes no event or mutation and makes no target call.
3. Attempting **Approve & unseal** still receives policy denial; approval cannot bypass the clerk. The run never gains injection events, and the target has no active fault.
4. Set the composer back to **demo**. Prod is not a runtime/deployment choice.

## Redis fail-closed and scoped abort

1. Select **Redis down**, then **Create draft**. Inspect the selected run ID, effective parameters, source, hypothesis and recorded decision.
2. Select **Approve & unseal**. The clerk re-evaluates approval, environment, target, duration and ownership. Changing the composer afterward cannot relabel this run or change the identity its actions affect.
3. In the target tab use **Probe session**. It reports a synthetic Redis session failure without a usable session; the API response is HTTP 503. Job reads retain labelled last-known history during the outage; they do not claim the queue became empty.
4. Navigate to **Tape** or refresh the console. The global banner still identifies the active run and exposes **Abort / reseal active run**. It stays usable while a planner request is pending.
5. Abort. A request is not the same as confirmed cleanup: if target cleanup is uncertain, the banner shows cleanup pending and admission remains held. Wait for cleanup/recovery evidence and the `aborted` seal.
6. Probe the session again in the target app. The earlier failed action remains labelled with its observation time until another action replaces it. Successful recovery supplies a new observation.

## Planner proposal without execution

After the aborted Redis run, choose **Propose draft**. The stub reads the latest seal and proposes **Worker drop**. The console shows requested/actual provider, outcome and **agent** origin; the result remains a draft and does not create an active run. Inspect planner diagnostics separately from authoritative run events. There is no execute, unseal, reseal, shell or Docker tool in the product-agent registry.

Optional configured providers are unnecessary for this walkthrough. Their failures report actual fallback provenance; a partially saved draft remains a draft. A new proposal request does not authorize execution.

## History and game days

Use **Tape** and **Search runs** to select any recorded run. Refresh preserves the URL selection; evidence and seal IDs stay associated with that run. Event times are actual server timestamps, rendered in the operator's labelled local timezone and sorted by server sequence.

**Game day → Create demo day** saves all three steps as drafts in one transaction. Choose **Inspect current step** to approve/unseal it. Abort stops that step and allows progression; **End game day & cancel remaining steps** also cancels unused drafts. Saved days can be resumed from the selector after refresh. Terminal runs and ended days cannot replay old run IDs.

## Standalone historical replay

After building the console once:

```sh
docker compose stop control target worker redis target-web
docker compose up -d --no-deps --pull never web
```

Open http://localhost:5173/?view=fixtures and select a fixture. Its hypothesis, recorded verdict, legacy reason/evidence absence and exact JSON are available even while live services are unavailable. These are historical/synthetic examples, not fresh measurements. Replay issues no mutations. Restore live services with `docker compose up -d`.

## What to say while showing it

The catalog has three experiments. Policy admits only demo, compatible Compose targets, at most 20 seconds and one owner. A human approval is an input to the clerk; the clerk remains the sole unseal authority. Abort retains ownership until verified cleanup. A passing seal requires measured hypothesis and recovery evidence. The planner only proposes.

Reproducible automated evidence is linked from [REMEDIATION.md](REMEDIATION.md), with [quality commands](QUALITY.md) and the [runtime contract](SPEC.md).
