from __future__ import annotations

import time
from typing import Any


class Store:
    def __init__(self) -> None:
        self.drafts: dict[str, dict[str, Any]] = {}
        self.seals: dict[str, dict[str, Any]] = {}
        self.game_days: dict[str, dict[str, Any]] = {}
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
