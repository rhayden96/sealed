# Draft-only planner

The product planner can read the catalog, policy and seals, propose one validated draft, and explain a policy decision. It has no execute, unseal, reseal, inject, shell, Docker or arbitrary-network tool. Shared domain construction validates manual, game-day and agent drafts without giving proposal creation execution authority.

PLANNER=stub is authoritative even if provider variables are inherited. Optional explicitly selected llama/xai modes also require ALLOW_PLANNER_NETWORK=true; this is a planner-only inference exception, never a fault-target exception. Provider calls are asynchronous, cancellable and bounded by an overall deadline and round/tool/output budgets, with no provider retries. A failed proposal reports requested/actual provider and fallback/partial outcome honestly. Idempotency preserves a single saved draft.

The tool allowlist is enforced in the application; the planner is not process-isolated from control. See [SPEC](../../docs/SPEC.md) for the trust boundary and [QUALITY](../../docs/QUALITY.md) for mocked-provider regression tests. No real provider is required for tests or the walkthrough.
