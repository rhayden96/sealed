# Walkthrough

Console: http://localhost:5173  
App: http://localhost:5174

Game day is a wizard. Unseal is still the clerk. The agent has no unseal key.

## Buttons (in order)

1. `docker compose up --build`
2. Open :5173 → **Game day**.
3. No active day: one primary **Start demo day**.
4. Headline becomes **Step 1 of 3 — handler_latency is pending**. **Start demo day** is hidden.
5. Primary **Approve + unseal**. Never shown while the current step is already unsealed.
6. Headline: **Step 1 of 3 — handler_latency is unsealed**. Big **Open target app :5174**. Watch slowness.
7. Primary **Abort this step**. LIVE pill: if `/health` is still ok, **LIVE · health unchanged — watch the app**.
8. **Step 2 of 3 — redis_down is pending** → **Approve + unseal**. On :5174, login fail-closes.
9. **Abort this step** → **Step 3 of 3 — worker_drop is pending** → **Approve + unseal**. Watch dropped jobs.
10. **Abort this step** → **End day**.

Step cards use sealed vocab only: `pending` | `unsealed` | `resealed` | `sealed`.

## Deny prod (optional)

On **Run**, set environment `prod` and try **Approve + unseal**. Clerk **403**. Nothing injects.

## 30-second mapping

> **Catalog** — three experiments: `redis_down`, `handler_latency`, `worker_drop`.  
> **Policy** — demo only, allowlisted targets, ≤20s, one unsealed run, deny prod.  
> **Clerk** — only unseal authority. Agent proposes drafts. Humans approve/unseal.  
> **Seal** — immutable run record: `pass` / `fail` / `aborted`.
