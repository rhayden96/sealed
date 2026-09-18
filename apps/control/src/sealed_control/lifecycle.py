"""One owner from admission through verified cleanup; reads never drive lifecycle."""
from __future__ import annotations

import asyncio
import contextlib
import time
import hashlib
import json
import logging
from enum import StrEnum

from fastapi import HTTPException

from sealed_control.clerk import evaluate_run
from sealed_control.evidence import Observer, evaluate as evaluate_evidence

logger = logging.getLogger(__name__)


class Status(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RESERVED = "reserved"
    INJECTING = "injecting"
    UNSEALED = "unsealed"
    CLEANUP = "cleanup_pending"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    RESEALED = "resealed"


ACTIVE = frozenset({"reserved", "injecting", "unsealed", "cleanup_pending", "recovering"})
TERMINAL = frozenset({"completed", "resealed", "cancelled"})


class Lifecycle:
    def __init__(self, app, adapter):
        self.app = app
        self.store = app.state.store
        self.adapter = adapter
        self.lock = asyncio.Lock()
        self.tasks: dict[str, asyncio.Task] = {}
        self.observations: dict[str, asyncio.Task] = {}
        self.observer = Observer(app)
        self.scheduler = None

    def get(self, run_id):
        draft = self.store.get_draft(run_id)
        if draft is None:
            raise HTTPException(404, "draft_not_found")
        return draft

    def save(self, draft, event=None, **details):
        with self.store.transaction():
            result = self.store.put_draft(draft)
            if event:
                self.store.add_event(draft["id"], event, details)
        return result

    async def approve(self, run_id):
        async with self.lock:
            draft = self.get(run_id)
            if draft["status"] not in {"draft", "approved"}:
                raise HTTPException(409, "illegal_transition")
            if not draft["approved"]:
                draft.update(approved=True, status="approved", approved_at=time.time())
                self.save(draft, "approved")
            return draft

    async def start(self, run_id):
        async with self.lock:
            draft = self.get(run_id)
            if draft["status"] not in {"draft", "approved"}:
                raise HTTPException(409, "run_not_startable")
            decision = evaluate_run(draft, self.app.state.policy, self.app.state.catalog, self.store)
            draft["policy_decision"] = decision
            self.save(draft, "policy_evaluated", **decision)
            if not decision["allowed"]:
                raise HTTPException(403, decision)
            draft.update(status="reserved", reserved_at=time.time(), abort_requested=False)
            for name in ("policy", "catalog"):
                config = getattr(self.app.state, name)
                draft[f"{name}_version"] = config["version"]
                draft[f"{name}_hash"] = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                draft[f"{name}_snapshot"] = config
            draft["evidence"] = {"baseline": [], "during": [], "recovery": [], "injection_complete": False}
            self.save(draft, "reserved")
            task = asyncio.create_task(self._deliver(run_id), name=f"run-{run_id}")
            self.tasks[run_id] = task
        # Shield ownership from a browser disconnect. Abort can acquire the lock immediately.
        await asyncio.shield(task)
        result = self.get(run_id)
        if result.get("execution_error"):
            raise HTTPException(502, {"reason": result["execution_error"], "draft_id": run_id, "status": result["status"]})
        return result

    async def _deliver(self, run_id):
        draft = self.get(run_id)
        baseline = await self._phase(draft, "baseline")
        draft = self.get(run_id)
        draft["evidence"]["baseline"] = baseline
        self.save(draft, "baseline_observed", samples=len(baseline))
        if draft.get("abort_requested") or draft.get("execution_error"):
            await self._cleanup(run_id)
            return
        draft["status"] = "injecting"
        self.save(draft, "inject_requested")
        try:
            ack = await self.adapter.inject(draft)
        except Exception:
            # A timeout is ambiguous. Never issue another POST to find out.
            try:
                status = await self.adapter.status()
                ack = status.get("active")
                if not ack or ack.get("run_id") != run_id or ack.get("status", "active") != "active":
                    raise RuntimeError("injection_not_acknowledged")
                self.adapter.validate_ack(ack, draft)
                ack = {**ack, "boot_id": status.get("boot_id")}
            except Exception:
                draft = self.get(run_id)
                draft.update(status="cleanup_pending", execution_error="injection_not_acknowledged", completion_reason="infrastructure_failure")
                self.save(draft, "injection_ambiguous")
                await self._cleanup(run_id)
                return
        draft = self.get(run_id)
        now = time.time()
        draft.update(injection_ack=ack, unsealed_at=ack.get("started_at", now), unsealed_until=ack["until"])
        if ack.get("boot_id"):
            draft["target_boot_id"] = ack["boot_id"]
        draft["evidence"]["injection_ack"] = ack
        if draft.get("abort_requested"):
            draft["status"] = "cleanup_pending"
            self.save(draft, "inject_acknowledged", acknowledgement=ack)
            await self._cleanup(run_id)
        else:
            draft["status"] = "unsealed"
            self.save(draft, "inject_acknowledged", acknowledgement=ack)

    async def _observe_during(self, run_id):
        draft = self.get(run_id)
        if self.adapter.url:
            try:
                status = await self.adapter.status()
                draft = self.get(run_id)
                if draft["status"] != "unsealed":
                    return
                active = status.get("active")
                if time.time() < draft["unsealed_until"] - 0.15 and (not active or active.get("run_id") != run_id or active.get("status") != "active"):
                    raise RuntimeError("target_interrupted")
                previous_boot = draft.get("target_boot_id")
                if previous_boot and previous_boot != status.get("boot_id"):
                    raise RuntimeError("target_restarted")
                draft["target_boot_id"] = status.get("boot_id")
                self.save(draft)
            except Exception:
                draft = self.get(run_id)
                if draft["status"] == "unsealed":
                    draft.update(status="cleanup_pending", execution_error="target_observation_unavailable", completion_reason="infrastructure_failure")
                    self.save(draft, "target_reconciliation_failed")
                return
        samples = await self._phase(draft, "during", budget=1)
        draft = self.get(run_id)
        if draft["status"] in TERMINAL:
            return
        draft["evidence"]["during"].extend(samples)
        draft["observation_cycles"] = draft.get("observation_cycles", 0) + 1
        draft["next_observation_at"] = time.time() + 0.35
        self.save(draft, "during_observed", samples=len(samples))

    async def _phase(self, draft, phase, **kwargs):
        try:
            return await self.observer.phase(draft, phase, **kwargs)
        except Exception as exc:
            logger.error("observation_failed:%s:%s", phase, type(exc).__name__)
            current = self.get(draft["id"])
            current.update(execution_error=f"{phase}_observation_failed", completion_reason="infrastructure_failure")
            self.save(current, "observation_failed", phase=phase)
            return []

    async def abort(self, run_id):
        async with self.lock:
            draft = self.get(run_id)
            if draft["status"] == "resealed":
                return {"draft": draft, "seal": self.store.seal_for_run(run_id)}
            if draft["status"] not in ACTIVE:
                raise HTTPException(409, "run_not_active")
            if not draft.get("abort_requested"):
                draft.update(abort_requested=True, abort_requested_at=time.time(), status="cleanup_pending", completion_reason="operator_abort")
                self.save(draft, "abort_requested")
            task = self.tasks.get(run_id)
            if task is None or task.done():
                task = asyncio.create_task(self._cleanup(run_id))
                self.tasks[run_id] = task
        # Do not hold an HTTP request hostage to a target outage.
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
        except TimeoutError:
            pass
        return {"draft": self.get(run_id), "seal": self.store.seal_for_run(run_id)}

    async def _cleanup(self, run_id):
        draft = self.get(run_id)
        if draft["status"] in TERMINAL:
            return
        draft["status"] = "cleanup_pending"
        self.save(draft)
        try:
            ack = await self.adapter.clear(run_id)
            if ack.get("run_id") != run_id or ack.get("cleanup_confirmed") is not True:
                raise RuntimeError("cleanup_not_acknowledged")
        except Exception:
            draft = self.get(run_id)
            draft["cleanup_error"] = "target_cleanup_unconfirmed"
            draft["cleanup_attempts"] = draft.get("cleanup_attempts", 0) + 1
            draft["next_cleanup_at"] = time.time() + min(5, 0.5 * 2 ** min(draft["cleanup_attempts"], 4))
            self.save(draft, "cleanup_failed", reason="target_cleanup_unconfirmed")
            return
        draft = self.get(run_id)
        if self.adapter.url and (not draft.get("target_boot_id") or draft.get("target_boot_id") != ack.get("boot_id")):
            draft["execution_error"] = "target_restarted_or_identity_unconfirmed"
            draft.setdefault("completion_reason", "infrastructure_failure")
            draft["evidence"]["injection_complete"] = False
        draft.update(cleanup_confirmed=True, cleanup_confirmed_at=time.time(), cleanup_error=None)
        draft["evidence"]["cleanup_confirmed"] = True
        draft["status"] = "recovering"
        self.save(draft, "cleanup_confirmed")
        pending = self.observations.get(run_id)
        if pending and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        recovery = await self._phase(draft, "recovery")
        draft = self.get(run_id)
        draft["evidence"]["recovery"] = recovery
        result = evaluate_evidence(draft, draft["evidence"])
        draft["evidence"]["evaluation"] = result
        verdict = "aborted" if draft.get("abort_requested") else result["verdict"]
        reason = draft.get("completion_reason") or result["reason"]
        if draft.get("execution_error") and verdict == "pass":
            verdict = "fail"
        draft.update(status="resealed" if verdict == "aborted" else "completed", completed_at=time.time())
        self.store.finish_run(draft, verdict, reason, draft["evidence"])
        self.observer.forget(run_id)

    async def tick(self):
        for registry in (self.tasks, self.observations):
            for run_id, task in list(registry.items()):
                if task.done():
                    if not task.cancelled() and task.exception():
                        logger.error("run_task_failed:%s", type(task.exception()).__name__)
                    del registry[run_id]
        for draft in self.store.list_active():
            run_id = draft["id"]
            task = self.tasks.get(run_id)
            if task is not None and not task.done():
                continue
            if draft["status"] == "unsealed" and draft["unsealed_until"] <= time.time():
                draft["status"] = "cleanup_pending"
                draft["evidence"]["injection_complete"] = not draft.get("execution_error")
                self.save(draft, "duration_elapsed")
            elif draft["status"] == "unsealed":
                pending = self.observations.get(run_id)
                sample_budget = 4.2 if draft["catalog_id"] == "worker_drop" else 2.1
                if (pending is None or pending.done()) and draft.get("observation_cycles", 0) < 24 and draft.get("next_observation_at", 0) <= time.time() and draft["unsealed_until"] - time.time() > sample_budget:
                    self.observations[run_id] = asyncio.create_task(self._observe_during(run_id))
            if draft["status"] in {"reserved", "injecting", "cleanup_pending", "recovering"}:
                if draft.get("next_cleanup_at", 0) > time.time():
                    continue
                if draft["status"] in {"reserved", "injecting"}:
                    draft.update(status="cleanup_pending", execution_error="control_restarted", completion_reason="infrastructure_failure")
                    self.save(draft, "startup_reconciliation")
                self.tasks[run_id] = asyncio.create_task(self._cleanup(run_id))

    async def run_scheduler(self):
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.error("lifecycle_tick_failed:%s", type(exc).__name__)
            await asyncio.sleep(0.2)

    async def recover_startup(self):
        for draft in self.store.list_active():
            draft.setdefault("evidence", {"baseline": [], "during": [], "recovery": []})
            draft["evidence"]["injection_complete"] = False
            draft.update(status="cleanup_pending", execution_error="control_restarted", completion_reason="control_restarted")
            self.save(draft, "startup_reconciliation")
        await self.tick()

    async def close(self):
        if self.scheduler:
            self.scheduler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.scheduler
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        for task in self.observations.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), *self.observations.values(), return_exceptions=True)
