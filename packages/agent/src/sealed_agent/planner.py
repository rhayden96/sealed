"""Bounded asynchronous planner. A proposal never unseals a draft."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from typing import Any

from sealed_agent.tools import TOOL_SCHEMAS, Tools

PROPOSAL_TIMEOUT_S = 15.0
LLM_TIMEOUT_S = 10.0
MAX_MODEL_ROUNDS = 4
MAX_TOOL_CALLS = 12
MAX_MODEL_TEXT = 16384


class PlannerOutputError(ValueError):
    pass


def planner_label() -> str:
    """Requested mode is explicit; inherited credentials never enable a provider."""
    return (os.environ.get("PLANNER") or "stub").strip().lower()


def _trace_fields(tools: Tools) -> dict[str, Any]:
    snap = getattr(tools.store, "agent_snapshot", None)
    return {"trace": (snap().get("trace") or []) if callable(snap) else []}


def _result(
    tools: Tools, *, draft: dict[str, Any] | None, explanation: str,
    actual: str, requested: str | None = None, reason: str | None = None,
    outcome: str | None = None,
) -> dict[str, Any]:
    set_planner = getattr(tools.store, "set_planner", None)
    if callable(set_planner):
        set_planner(actual)
    return {
        "draft": draft, "explanation": explanation, "planner": actual,
        "requested_provider": requested or planner_label(), "actual_provider": actual,
        "fallback_reason": reason, "proposal_id": tools.proposal_id,
        "outcome": outcome or ("proposed" if draft else "no_proposal"),
        **_trace_fields(tools),
    }


def stub_propose(tools: Tools) -> dict[str, Any]:
    seal = tools.call("get_seal")
    tools.call("list_experiments")
    tools.call("list_targets")
    if not seal or seal.get("catalog_id") != "redis_down" or seal.get("verdict") not in {"fail", "aborted"}:
        explanation = tools.call("explain_failure") if seal else "No failed or aborted redis_down seal; nothing to propose."
        return _result(tools, draft=None, explanation=explanation, actual="stub")
    existing = [
        draft for draft in tools.store.list_drafts()
        if draft.get("catalog_id") == "worker_drop" and draft.get("source") == "agent"
        and draft.get("status") == "draft"
    ]
    explanation = tools.call("explain_failure")
    if existing:
        return _result(
            tools, draft=existing[-1], explanation=explanation + " Existing worker_drop draft retained; no execution.",
            actual="stub", outcome="existing_proposal",
        )
    draft = tools.call("propose_experiment", catalog_id="worker_drop", target="worker", environment="demo")
    return _result(tools, draft=draft, explanation=explanation + " Proposed worker_drop as a draft only.", actual="stub")


def _llm_settings() -> tuple[str, str, str] | None:
    mode = planner_label()
    if mode == "stub" or os.environ.get("ALLOW_PLANNER_NETWORK", "").lower() != "true":
        return None
    if mode not in {"llama", "llm", "xai"}:
        return None
    base = (os.environ.get("LLM_BASE_URL") or "").strip()
    if mode == "xai":
        base = base or "https://api.x.ai/v1"
        key = (os.environ.get("XAI_API_KEY") or "").strip()
        model = (os.environ.get("LLM_MODEL") or "").strip() or "grok-4.5"
    else:
        key = (os.environ.get("LLM_API_KEY") or "").strip() or ("ollama" if mode == "llama" else "")
        model = (os.environ.get("LLM_MODEL") or "").strip() or "llama3.2"
    if not base or not key:
        return None
    return base.rstrip("/"), key, model


def _reject_constant(value: str) -> None:
    raise PlannerOutputError("nonfinite_model_number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlannerOutputError("duplicate_model_argument")
        result[key] = value
    return result


def parse_arguments(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MODEL_TEXT:
        raise PlannerOutputError("model_arguments_too_large")
    value = json.loads(raw or "{}", parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise PlannerOutputError("model_arguments_must_be_object")
    return value


async def llm_propose(tools: Tools) -> dict[str, Any]:
    from openai import AsyncOpenAI

    settings = _llm_settings()
    if settings is None:
        raise ValueError("planner_not_configured")
    base_url, api_key, model = settings
    schemas = [
        {"type": "function", "function": {"name": name, "description": "Read or propose only; never execute.", "parameters": schema.model_json_schema()}}
        for name, schema in TOOL_SCHEMAS.items()
    ]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are the Sealed planner. Use only the provided read/propose tools. Never unseal, reseal, execute, or inject. Propose at most one draft. After a failed or aborted redis_down seal, propose worker_drop."},
        {"role": "user", "content": "Inspect seals and propose the next experiment if appropriate."},
    ]
    explanation = ""
    total_calls = 0
    async with AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=LLM_TIMEOUT_S, max_retries=0) as client:
        for _ in range(MAX_MODEL_ROUNDS):
            response = await client.chat.completions.create(
                model=model, messages=messages, tools=schemas, timeout=LLM_TIMEOUT_S,
                max_tokens=2048,
            )
            if len(response.choices) != 1:
                raise PlannerOutputError("model_choice_count")
            choice = response.choices[0].message
            serialized = choice.model_dump(exclude_unset=True)
            if len(json.dumps(serialized).encode("utf-8")) > MAX_MODEL_TEXT:
                raise PlannerOutputError("model_response_too_large")
            messages.append(serialized)
            if not choice.tool_calls:
                return _result(
                    tools, draft=tools.proposed_draft,
                    explanation=choice.content or explanation or "Planner completed without a proposal.", actual=planner_label(),
                )
            total_calls += len(choice.tool_calls)
            if total_calls > MAX_TOOL_CALLS:
                raise PlannerOutputError("model_tool_budget_exceeded")
            for call in choice.tool_calls:
                result = tools.call(call.function.name, **parse_arguments(call.function.arguments))
                if call.function.name == "explain_failure":
                    explanation = result
                content = json.dumps(result, allow_nan=False)
                if len(content.encode("utf-8")) > MAX_MODEL_TEXT:
                    raise PlannerOutputError("tool_output_too_large")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
    raise PlannerOutputError("model_round_budget_exceeded")


async def propose(tools: Tools, *, proposal_id: str | None = None) -> dict[str, Any]:
    tools.proposed_draft = None
    tools.proposal_id = proposal_id or tools.proposal_id or secrets.token_hex(16)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", tools.proposal_id):
        raise ValueError("invalid_proposal_id")
    requested = planner_label()
    for existing in tools.store.list_drafts():
        if existing.get("proposal_id") == tools.proposal_id:
            return _result(
                tools, draft=existing, explanation="Existing proposal recovered by identity; no new draft or execution.",
                actual=existing.get("planner_provider", "unknown"), outcome="existing_proposal",
            )
    if _llm_settings() is None:
        result = stub_propose(tools)
        if requested != "stub":
            result["fallback_reason"] = (
                "planner_network_disabled" if os.environ.get("ALLOW_PLANNER_NETWORK", "").lower() != "true"
                else "planner_not_configured"
            )
        _record_provider(tools, result)
        return result
    try:
        async with asyncio.timeout(PROPOSAL_TIMEOUT_S):
            result = await llm_propose(tools)
    except Exception as exc:
        # Never publish raw SDK errors: they may contain credential-bearing URLs.
        reason = "proposal_timeout" if isinstance(exc, TimeoutError) else f"provider_failure:{type(exc).__name__}"
        if tools.proposed_draft is not None:
            result = _result(
                tools, draft=tools.proposed_draft, explanation="A draft was saved before planning failed. The planner did not execute it or create a replacement.",
                actual=requested, reason=reason, outcome="partial_failure",
            )
        else:
            result = stub_propose(tools)
            result["fallback_reason"] = reason
    _record_provider(tools, result)
    return result


def _record_provider(tools: Tools, result: dict[str, Any]) -> None:
    draft = result.get("draft")
    if draft is not None and draft.get("proposal_id") == tools.proposal_id:
        # Another control request may have approved the persisted draft during
        # a model await. Preserve the latest lifecycle state, never a snapshot.
        current = tools.store.get_draft(draft["id"])
        if current is not None:
            current["planner_provider"] = result["actual_provider"]
            tools.store.put_draft(current)
            result["draft"] = current
