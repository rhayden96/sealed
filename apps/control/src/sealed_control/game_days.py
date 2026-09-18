"""Transactional, resumable game-day construction and operator end semantics."""
import time

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sealed_agent.domain import construct_draft
from sealed_control.clerk import current_step_index
from sealed_control.lifecycle import ACTIVE, TERMINAL


class GameDayIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    steps: list[str] = Field(min_length=1, max_length=12)


def create_day(store, catalog, steps):
    specs = {item["id"]: item for item in catalog["experiments"]}
    if any(step not in specs for step in steps):
        raise HTTPException(400, "unknown_catalog_id")
    with store.transaction():
        day_id = store.new_id("g")
        records = []
        for catalog_id in steps:
            spec = specs[catalog_id]
            draft = construct_draft(store, catalog, catalog_id=catalog_id, environment="demo", target=spec["allowed_targets"][0], source="game_day")
            draft["game_day_id"] = day_id
            store.put_draft(draft)
            records.append({"catalog_id": catalog_id, "draft_id": draft["id"]})
        day = store.put_game_day({"id": day_id, "steps": records, "status": "open", "created_at": time.time()})
    return view(store, day)


def view(store, day):
    current = current_step_index(day, store)
    steps = []
    for index, step in enumerate(day["steps"]):
        draft = store.get_draft(step["draft_id"]) or {}
        steps.append({**step, "index": index, "status": draft.get("status", "missing"), "live": draft.get("status") in ACTIVE, "current": current == index})
    status = day.get("status", "open")
    if status == "ended" and any(step["live"] for step in steps):
        status = "ending"
    elif status == "open" and current is None:
        status = "completed"
    return {**day, "status": status, "steps": steps, "current_index": current}


async def end_day(app, day_id):
    store = app.state.store
    day = store.get_game_day(day_id)
    if day is None:
        raise HTTPException(404, "game_day_not_found")
    active = []
    with store.transaction():
        day.update(status="ended", ended_at=day.get("ended_at", time.time()))
        store.put_game_day(day)
        for step in day["steps"]:
            draft = store.get_draft(step["draft_id"])
            if draft["status"] in ACTIVE:
                active.append(draft["id"])
            elif draft["status"] not in TERMINAL:
                draft.update(status="cancelled", cancelled_at=time.time())
                store.put_draft(draft)
                store.add_event(draft["id"], "draft_cancelled", {"reason": "game_day_ended"})
    for run_id in active:
        await app.state.lifecycle.abort(run_id)
    return view(store, store.get_game_day(day_id))
