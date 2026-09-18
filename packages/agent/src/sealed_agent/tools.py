"""Planner tools. Drafts only. No unseal, reseal, execute, or inject."""

from __future__ import annotations

import time
from typing import Any

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


class Tools:
    def __init__(self, catalog: dict[str, Any], policy: dict[str, Any], store: Any) -> None:
        self.catalog = catalog
        self.policy = policy
        self.store = store

    def names(self) -> frozenset[str]:
        return ALLOWED_TOOLS

    def list_experiments(self) -> list[dict[str, Any]]:
        return list(self.catalog.get("experiments") or [])

    def list_targets(self) -> list[str]:
        return list(self.policy.get("target_allowlist") or [])

    def get_seal(self, seal_id: str | None = None) -> dict[str, Any] | None:
        if seal_id:
            return self.store.get_seal(seal_id)
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
        experiments = {item["id"]: item for item in self.list_experiments()}
        spec = experiments.get(catalog_id)
        if spec is None:
            raise ValueError("unknown_catalog_id")
        duration = (
            float(duration_s)
            if duration_s is not None
            else float(spec.get("default_duration_s") or 0)
        )
        draft = {
            "id": self.store.new_id("d"),
            "catalog_id": catalog_id,
            "environment": environment,
            "target": target,
            "duration_s": duration,
            "params": {**(spec.get("params") or {}), **(params or {})},
            "hypothesis": hypothesis if hypothesis is not None else spec.get("hypothesis"),
            "approved": False,
            "status": "draft",
            "source": "agent",
            "created_at": time.time(),
        }
        return self.store.put_draft(draft)

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in ALLOWED_TOOLS:
            raise PermissionError(f"tool not allowed: {name}")
        if name in FORBIDDEN_TOOLS:
            raise PermissionError(f"tool forbidden: {name}")
        method = getattr(self, name)
        result = method(**kwargs)
        append = getattr(self.store, "append_trace", None)
        if callable(append):
            append(name, kwargs, result)
        return result
