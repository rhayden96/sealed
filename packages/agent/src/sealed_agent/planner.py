"""Stub planner (default). Optional SpaceXAI if XAI_API_KEY is set — still no unseal."""

from __future__ import annotations

import json
import os
from typing import Any

from sealed_agent.tools import ALLOWED_TOOLS, Tools


def stub_propose(tools: Tools) -> dict[str, Any]:
    seal = tools.get_seal()
    if (
        not seal
        or seal.get("catalog_id") != "redis_down"
        or seal.get("verdict") not in {"fail", "aborted"}
    ):
        return {
            "draft": None,
            "explanation": (
                tools.explain_failure(seal)
                if seal
                else "No failed or aborted redis_down seal; nothing to propose."
            ),
            "planner": "stub",
        }

    existing = [
        draft
        for draft in tools.store.list_drafts()
        if draft.get("catalog_id") == "worker_drop"
        and draft.get("source") == "agent"
        and draft.get("status") == "draft"
    ]
    if existing:
        return {
            "draft": existing[-1],
            "explanation": tools.explain_failure(seal)
            + " worker_drop draft already proposed; not unsealing.",
            "planner": "stub",
        }

    explanation = tools.explain_failure(seal)
    targets = tools.list_targets()
    target = "worker" if "worker" in targets else (targets[0] if targets else "worker")
    draft = tools.propose_experiment(
        catalog_id="worker_drop",
        target=target,
        environment="demo",
    )
    return {
        "draft": draft,
        "explanation": explanation + " Proposed worker_drop as a draft. Not unsealing.",
        "planner": "stub",
    }


def llm_propose(tools: Tools) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["XAI_API_KEY"],
        base_url="https://api.x.ai/v1",
    )
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
            model="grok-4.5",
            messages=messages,
            tools=schemas,
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
    return {
        "draft": draft,
        "explanation": explanation
        or "LLM proposed a draft only; not unsealing.",
        "planner": "llm",
    }


def propose(tools: Tools) -> dict[str, Any]:
    if os.environ.get("XAI_API_KEY"):
        try:
            return llm_propose(tools)
        except Exception:
            return stub_propose(tools)
    return stub_propose(tools)
