# Agent (S4)

Planner only. Proposes drafts. Never injects.

**Allowed tools:** `list_experiments`, `list_targets`, `propose_experiment`, `get_run`, `get_seal`, `explain_failure`.

**Forbidden:** `unseal`, `reseal`, `execute`, `shell`, `kubectl`, `docker`, `/_faults`.

Wired as `POST /agent/propose` on control. Without `XAI_API_KEY`, the stub planner runs: after a failed/aborted `redis_down` seal it proposes `worker_drop` as a **draft**. It does not unseal.

Humans still Approve / Unseal in the UI. The agent has no Unseal button.
