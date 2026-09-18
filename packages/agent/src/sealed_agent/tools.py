"""Planner tools. Drafts only. No unseal, reseal, execute, or inject."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import Field

from sealed_agent.domain import DraftIn, StrictModel, construct_draft

ALLOWED_TOOLS = frozenset(
    {
        "list_experiments",
        "list_targets",
        "propose_experiment",
        "get_run",
        "get_seal",
        "explain_failure",
    }
)

FORBIDDEN_TOOLS = frozenset(
    {
        "unseal",
        "reseal",
        "execute",
        "shell",
        "kubectl",
        "docker",
        "_faults",
        "inject",
    }
)


class SealArgs(StrictModel):
    seal_id: str | None = Field(default=None, min_length=1, max_length=80)


class RunArgs(StrictModel):
    draft_id: str | None = Field(default=None, min_length=1, max_length=80)


class ProposeArgs(DraftIn):
    environment: str = Field(default="demo", min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")


TOOL_SCHEMAS = {
    "list_experiments": StrictModel,
    "list_targets": StrictModel,
    "get_seal": SealArgs,
    "get_run": RunArgs,
    "explain_failure": StrictModel,
    "propose_experiment": ProposeArgs,
}

assert set(TOOL_SCHEMAS) == ALLOWED_TOOLS
assert ALLOWED_TOOLS.isdisjoint(FORBIDDEN_TOOLS)


class Tools:
    def __init__(self, catalog: dict[str, Any], policy: dict[str, Any], store: Any, *, proposal_id: str | None = None) -> None:
        self.catalog = deepcopy(catalog)
        self.policy = deepcopy(policy)
        self.store = store
        self.proposal_id = proposal_id
        self.proposed_draft: dict[str, Any] | None = None

    def names(self) -> frozenset[str]:
        return ALLOWED_TOOLS

    def list_experiments(self) -> list[dict[str, Any]]:
        return deepcopy(self.catalog.get("experiments") or [])

    def list_targets(self) -> list[str]:
        return list(self.policy.get("target_allowlist") or [])

    def get_seal(self, seal_id: str | None = None) -> dict[str, Any] | None:
        if seal_id:
            return self.store.get_seal(seal_id)
        latest = getattr(self.store, "get_latest_seal", None)
        if latest:
            return latest()
        seals = self.store.list_seals()
        if not seals:
            return None
        return max(seals, key=lambda item: item.get("created_at") or 0)

    def get_run(self, draft_id: str | None = None) -> dict[str, Any] | None:
        if draft_id:
            return self.store.get_draft(draft_id)
        drafts = self.store.list_drafts()
        unsealed = [d for d in drafts if d.get("status") == "unsealed"]
        if unsealed:
            return unsealed[-1]
        return drafts[-1] if drafts else None

    def explain_failure(self, seal: dict[str, Any] | None = None) -> str:
        seal = seal or self.get_seal()
        if not seal:
            return "No seal to explain."
        verdict = seal.get("verdict")
        catalog_id = seal.get("catalog_id")
        must = (seal.get("hypothesis") or {}).get("must") or []
        if catalog_id == "redis_down" and verdict in {"fail", "aborted"}:
            return (
                f"redis_down seal {seal.get('id')} is {verdict}. "
                f"Login must fail closed ({', '.join(must) or 'fail_closed_on_redis_loss'}). "
                "Next experiment from the catalog is worker_drop — draft only, not unsealed."
            )
        return f"Seal {seal.get('id')} catalog={catalog_id} verdict={verdict}."

    def propose_experiment(
        self,
        catalog_id: str,
        target: str,
        environment: str = "demo",
        duration_s: float | None = None,
        params: dict[str, Any] | None = None,
        hypothesis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        draft = construct_draft(
            self.store, self.catalog, catalog_id=catalog_id, target=target,
            environment=environment, duration_s=duration_s, params=params,
            hypothesis=hypothesis, source="agent", proposal_id=self.proposal_id,
        )
        self.proposed_draft = deepcopy(draft)
        return draft

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in ALLOWED_TOOLS:
            raise PermissionError(f"tool not allowed: {name}")
        if name in FORBIDDEN_TOOLS:
            raise PermissionError(f"tool forbidden: {name}")
        validated = TOOL_SCHEMAS[name].model_validate(kwargs).model_dump()
        method = getattr(self, name)
        result = method(**validated)
        append = getattr(self.store, "append_trace", None)
        if callable(append):
            append(name, kwargs, result)
        return deepcopy(result)
