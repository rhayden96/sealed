# Walkthrough

Interview demo. Docker, then http://localhost:5173.

**Product choice:** the UI **Approve** button also calls unseal (one click). Clerk is still the only unseal authority. **Unseal** remains if you want the two-step AO path. The agent has no unseal key either way.

## Five steps

1. **Compose up**  
   `docker compose up --build`  
   Open http://localhost:5173  
   Target `:8080`, control `:8081`, web `:5173`. Catalog loaded. Nothing unsealed.

2. **Happy latency**  
   Catalog `handler_latency`, environment `demo`, target `api`, 5s. Create draft. It auto-unseals. Timeline shows draft → unsealed. **Abort / reseal** (or wait 5s) so the single unsealed slot is free.

3. **Abort redis_down**  
   Catalog `redis_down`, `demo`, target `redis`. Create draft. **Approve** (approve + unseal). `POST http://localhost:8080/login` fail-closed. **Abort / reseal**. Last seal `aborted`.

4. **Agent proposes, does not run**  
   **Propose**. You get a `worker_drop` draft (`· agent`).  
   `POST http://localhost:8080/_faults` without `X-Sealed-Token` is `403 not_unsealed`.  
   Still dark until a human **Unseal** (or Approve + unseal). The agent cannot press that.

5. **Fixture replay (offline story)**  
   `GET http://localhost:8081/fixtures`  
   Recorded seals: `handler_latency` `pass`, `redis_down` `aborted`. No inject. No `worker_drop` seal — that draft was never run.

## 30-second mapping

> **Catalog** — three experiments: `redis_down`, `handler_latency`, `worker_drop`.  
> **Policy** — demo only, allowlisted targets, ≤20s, one unsealed run, deny prod.  
> **Clerk** — only unseal authority. Agent proposes drafts. Humans approve/unseal.  
> **Seal** — immutable run record: `pass` / `fail` / `aborted`. Fixtures replay it.

## Deny prod (optional beat)

Create a draft with environment `prod`. Approve/Unseal → clerk **403**. Nothing injects.
