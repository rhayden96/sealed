from __future__ import annotations

import time
from typing import Any

_SECRET = ("key", "token", "secret", "password", "authorization")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            low = str(key).lower()
            if any(part in low for part in _SECRET):
                out[key] = "[redacted]"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value[:20]]
    return value


def _summary(result: Any) -> str:
    if result is None:
        return "none"
    if isinstance(result, str):
        return result[:160]
    if isinstance(result, dict):
        if result.get("id") and result.get("catalog_id"):
            return (
                f"draft {result.get('id')} {result.get('catalog_id')} "
                f"{result.get('status')}"
            )
        if "verdict" in result:
            return f"seal {result.get('id')} {result.get('catalog_id')} {result.get('verdict')}"
        return ",".join(str(key) for key in result.keys())[:160]
    if isinstance(result, list):
        return f"{len(result)} items"
    return str(result)[:160]


class Store:
    def __init__(self) -> None:
        self.drafts: dict[str, dict[str, Any]] = {}
        self.seals: dict[str, dict[str, Any]] = {}
        self.game_days: dict[str, dict[str, Any]] = {}
        self.agent_trace: list[dict[str, Any]] = []
        self.planner_name = "stub"
        self._seq = 0

    def new_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def put_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        self.drafts[draft["id"]] = draft
        return draft

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        return self.drafts.get(draft_id)

    def list_drafts(self) -> list[dict[str, Any]]:
        return list(self.drafts.values())

    def add_seal(self, *, draft: dict[str, Any], verdict: str) -> dict[str, Any]:
        seal = {
            "id": self.new_id("s"),
            "draft_id": draft["id"],
            "catalog_id": draft["catalog_id"],
            "environment": draft["environment"],
            "target": draft["target"],
            "duration_s": draft["duration_s"],
            "hypothesis": draft.get("hypothesis"),
            "verdict": verdict,
            "created_at": time.time(),
        }
        self.seals[seal["id"]] = seal
        return seal

    def get_seal(self, seal_id: str) -> dict[str, Any] | None:
        return self.seals.get(seal_id)

    def list_seals(self) -> list[dict[str, Any]]:
        return list(self.seals.values())

    def put_game_day(self, game_day: dict[str, Any]) -> dict[str, Any]:
        self.game_days[game_day["id"]] = game_day
        return game_day

    def get_game_day(self, game_day_id: str) -> dict[str, Any] | None:
        return self.game_days.get(game_day_id)

    def list_game_days(self) -> list[dict[str, Any]]:
        return list(self.game_days.values())

    def set_planner(self, name: str) -> None:
        self.planner_name = name

    def append_trace(self, tool: str, args: dict[str, Any] | None, result: Any) -> None:
        self.agent_trace.append(
            {
                "ts": time.time(),
                "tool": tool,
                "args_redacted": _redact(args or {}),
                "result_summary": _summary(result),
            }
        )
        self.agent_trace = self.agent_trace[-200:]

    def agent_snapshot(self) -> dict[str, Any]:
        last = self.agent_trace[-1]["tool"] if self.agent_trace else ""
        return {
            "planner": self.planner_name,
            "last_tool": last,
            "trace": list(self.agent_trace),
        }
