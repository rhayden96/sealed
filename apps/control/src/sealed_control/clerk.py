"""Policy clerk. The only unseal authority."""

from __future__ import annotations

import time
import math
from typing import Any, TypedDict

from sealed_control.loader import experiments_by_id

STEP_DONE = frozenset({"resealed", "completed", "cancelled"})


class PolicyDecision(TypedDict):
    allowed: bool
    reasons: list[str]
    auto: bool


def current_step_index(game_day: dict[str, Any], store: Any) -> int | None:
    if game_day.get("status") == "ended":
        return None
    for index, step in enumerate(game_day.get("steps") or []):
        draft = store.get_draft(step["draft_id"])
        if not draft or draft.get("status") not in STEP_DONE:
            return index
    return None


def skip_reason(draft: dict[str, Any], store: Any) -> str | None:
    for game_day in store.list_game_days():
        ids = [step["draft_id"] for step in game_day.get("steps") or []]
        if draft.get("id") not in ids:
            continue
        if game_day.get("status") == "ended":
            return "game_day_ended"
        index = ids.index(draft["id"])
        current = current_step_index(game_day, store)
        if current is not None and index != current:
            return "step_skipped"
    return None


def unsealed_count(drafts: list[dict[str, Any]], now: float | None = None) -> int:
    return sum(
        1
        for d in drafts
        if d.get("status") in {"reserved", "injecting", "unsealed", "cleanup_pending", "recovering"}
    )


def is_auto_unseal(draft: dict[str, Any], policy: dict[str, Any]) -> bool:
    auto = policy.get("auto_unseal") or {}
    if not auto.get("enabled"):
        return False
    if draft.get("environment") != auto.get("environment", "demo"):
        return False
    if draft.get("catalog_id") not in set(auto.get("catalog_ids") or []):
        return False
    max_dur = float(auto.get("max_duration_s", 5))
    return float(draft.get("duration_s") or 0) <= max_dur


def evaluate(
    draft: dict[str, Any],
    policy: dict[str, Any],
    catalog: dict[str, Any],
    drafts: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> PolicyDecision:
    now = time.time() if now is None else now
    reasons: list[str] = []
    experiments = experiments_by_id(catalog)

    env = draft.get("environment")
    denylist = set(policy.get("environment_denylist") or [])
    allowlist = set(policy.get("environment_allowlist") or [])
    if env in denylist or env == "prod":
        reasons.append("environment_denied")
    elif env not in allowlist:
        reasons.append("environment_not_allowed")

    duration = float(draft.get("duration_s") or 0)
    max_duration = float(policy.get("max_duration_s", 20))
    if duration > max_duration:
        reasons.append("duration_exceeded")
    if not math.isfinite(duration) or duration <= 0:
        reasons.append("invalid_duration")

    catalog_id = draft.get("catalog_id")
    if policy.get("catalog_id_required", True) and not catalog_id:
        reasons.append("catalog_id_required")
    elif catalog_id not in experiments:
        reasons.append("unknown_catalog_id")

    target = draft.get("target")
    target_allow = set(policy.get("target_allowlist") or [])
    if target not in target_allow:
        reasons.append("target_not_allowed")
    elif catalog_id in experiments:
        allowed_targets = set(experiments[catalog_id].get("allowed_targets") or [])
        if target not in allowed_targets:
            reasons.append("target_not_in_experiment")

    max_conc = int(policy.get("max_concurrent_unsealed", 1))
    if unsealed_count(drafts, now=now) >= max_conc:
        reasons.append("max_concurrent_unsealed")

    auto = is_auto_unseal(draft, policy)
    if not auto and not draft.get("approved"):
        reasons.append("not_approved")

    return {"allowed": len(reasons) == 0, "reasons": reasons, "auto": auto}


def evaluate_run(
    draft: dict[str, Any], policy: dict[str, Any], catalog: dict[str, Any], store: Any
) -> PolicyDecision:
    """Read-only admission preview shared by the UI and actual reservation."""
    decision = evaluate(draft, policy, catalog, store.list_active())
    if draft["status"] not in {"draft", "approved"}:
        decision["reasons"].insert(0, "run_not_startable")
    skipped = skip_reason(draft, store)
    if skipped:
        decision["reasons"].append(skipped)
    decision["allowed"] = not decision["reasons"]
    return decision
