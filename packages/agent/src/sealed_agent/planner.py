"""Stub planner (default). Optional Ollama or SpaceXAI — still no unseal."""

from __future__ import annotations

import json
import os
from typing import Any

from sealed_agent.tools import ALLOWED_TOOLS, Tools

LLM_TIMEOUT_S = 20.0


def planner_label() -> str:
    settings = _llm_settings()
    if settings is None:
        return "stub"
    base_url, _, _ = settings
    if "11434" in base_url or "ollama" in base_url.lower():
        return "llama"
    return "llm"


def stub_propose(tools: Tools) -> dict[str, Any]:
    set_planner = getattr(tools.store, "set_planner", None)
    if callable(set_planner):
        set_planner("stub")
    seal = tools.call("get_seal")
    tools.call("list_experiments")
    targets = tools.call("list_targets")
    if (
        not seal
        or seal.get("catalog_id") != "redis_down"
        or seal.get("verdict") not in {"fail", "aborted"}
    ):
        explanation = (
            tools.call("explain_failure")
            if seal
            else "No failed or aborted redis_down seal; nothing to propose."
        )
        return {
            "draft": None,
            "explanation": explanation,
            "planner": "stub",
            **_trace_fields(tools),
        }

    existing = [
        draft
        for draft in tools.store.list_drafts()
        if draft.get("catalog_id") == "worker_drop"
        and draft.get("source") == "agent"
        and draft.get("status") == "draft"
    ]
    if existing:
        explanation = tools.call("explain_failure") + " worker_drop draft already proposed; not unsealing."
        return {
            "draft": existing[-1],
            "explanation": explanation,
            "planner": "stub",
            **_trace_fields(tools),
        }

    explanation = tools.call("explain_failure")
    target = "worker" if "worker" in (targets or []) else ((targets or ["worker"])[0])
    draft = tools.call(
        "propose_experiment",
        catalog_id="worker_drop",
        target=target,
        environment="demo",
    )
    return {
        "draft": draft,
        "explanation": explanation + " Proposed worker_drop as a draft. Not unsealing.",
        "planner": "stub",
        **_trace_fields(tools),
    }


def _trace_fields(tools: Tools) -> dict[str, Any]:
    snap = getattr(tools.store, "agent_snapshot", None)
    if callable(snap):
        data = snap()
        return {"trace": data.get("trace") or []}
    return {"trace": []}


def _llm_settings() -> tuple[str, str, str] | None:
    base = (os.environ.get("LLM_BASE_URL") or "").strip()
    if base:
        key = (
            (os.environ.get("LLM_API_KEY") or "").strip()
            or (os.environ.get("OPENAI_API_KEY") or "").strip()
            or "ollama"
        )
        model = (os.environ.get("LLM_MODEL") or "").strip() or "llama3.2"
        return base.rstrip("/"), key, model
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    if key:
        model = (os.environ.get("LLM_MODEL") or "").strip() or "grok-4.5"
        return "https://api.x.ai/v1", key, model
    return None


def llm_propose(tools: Tools) -> dict[str, Any]:
    from openai import OpenAI

    settings = _llm_settings()
    if settings is None:
        return stub_propose(tools)
    base_url, api_key, model = settings
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=LLM_TIMEOUT_S)
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "list_experiments",
                "description": "List catalog experiments.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_targets",
                "description": "List policy target allowlist.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_seal",
                "description": "Get latest or named seal.",
                "parameters": {
                    "type": "object",
                    "properties": {"seal_id": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_run",
                "description": "Get a draft/run by id, or the current one.",
                "parameters": {
                    "type": "object",
                    "properties": {"draft_id": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "explain_failure",
                "description": "Explain the latest failed or aborted seal.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_experiment",
                "description": "Write a draft only. Do not unseal or inject.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "catalog_id": {"type": "string"},
                        "target": {"type": "string"},
                        "environment": {"type": "string"},
                        "duration_s": {"type": "number"},
                    },
                    "required": ["catalog_id", "target"],
                },
            },
        },
    ]
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are the Sealed planner. You may only use the provided tools. "
                "You propose drafts. You never unseal, reseal, execute, or inject. "
                "After a failed or aborted redis_down seal, propose worker_drop."
            ),
        },
        {
            "role": "user",
            "content": "Inspect seals and propose the next experiment if appropriate.",
        },
    ]
    draft = None
    explanation = ""
    for _ in range(6):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=schemas,
            timeout=LLM_TIMEOUT_S,
        )
        choice = response.choices[0].message
        messages.append(choice.model_dump(exclude_unset=True))
        if not choice.tool_calls:
            explanation = choice.content or explanation
            break
        for call in choice.tool_calls:
            name = call.function.name
            if name not in ALLOWED_TOOLS:
                result = f"rejected forbidden tool: {name}"
            else:
                args = json.loads(call.function.arguments or "{}")
                result = tools.call(name, **args)
                if name == "propose_experiment":
                    draft = result
            if name == "explain_failure" and isinstance(result, str):
                explanation = result
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                }
            )
    if draft is None:
        return stub_propose(tools)
    label = planner_label()
    set_planner = getattr(tools.store, "set_planner", None)
    if callable(set_planner):
        set_planner(label)
    return {
        "draft": draft,
        "explanation": explanation or "LLM proposed a draft only; not unsealing.",
        "planner": label,
        **_trace_fields(tools),
    }


def propose(tools: Tools) -> dict[str, Any]:
    label = planner_label()
    set_planner = getattr(tools.store, "set_planner", None)
    if callable(set_planner):
        set_planner(label)
    if _llm_settings() is None:
        return stub_propose(tools)
    try:
        return llm_propose(tools)
    except Exception:
        return stub_propose(tools)
