"""Bounded real workload observations and conservative, pure hypothesis evaluation.

One phase has at most three baseline/recovery cycles or 24 during cycles. A
worker cycle creates three jobs and polls at most eight times per job for at
most two seconds. A complete run therefore creates at most 90 jobs. Every HTTP
request has a two-second total deadline; observations never contain credentials
or login session values. The lifecycle owns phase scheduling and persists data.
"""

from __future__ import annotations

import asyncio
import math
import statistics
import time
from typing import Any


PHASES = ("baseline", "during", "recovery")
HTTP_DEADLINE_S = 2.0
WORKER_BATCH = 3
WORKER_POLL_ROUNDS = 8
WORKER_POLL_BUDGET_S = 2.0
WORKER_POLL_INTERVAL_S = 0.1


class Observer:
    def __init__(self, app, *, clock=time.time, monotonic=time.monotonic, sleep=asyncio.sleep):
        self.app = app
        self.clock = clock
        self.monotonic = monotonic
        self.sleep = sleep
        self.sequence = 0
        self.counts = {}

    @property
    def real(self):
        return bool(self.app.state.target_url) and not getattr(self.app.state, "simulated_target", False)

    def forget(self, run_id):
        """Release counters only after lifecycle has persisted a terminal seal."""
        for phase in PHASES:
            self.counts.pop((run_id, phase), None)

    async def _request(self, draft, method, path, **kwargs):
        started_at, started = self.clock(), self.monotonic()
        result = {"started_at": started_at, "status_code": None, "data": None, "transport_error": None}
        if not self.real:
            result["transport_error"] = "target_not_configured"
        else:
            try:
                response = await asyncio.wait_for(
                    self.app.state.http.request(
                        method, self.app.state.target_url.rstrip("/") + path,
                        headers={"X-Sealed-Run": draft["id"]}, timeout=HTTP_DEADLINE_S, **kwargs,
                    ), timeout=HTTP_DEADLINE_S,
                )
                result["status_code"] = response.status_code
                try:
                    body = response.json()
                    result["data"] = body if isinstance(body, dict) else None
                except (TypeError, ValueError):
                    pass
                if result["data"] is None:
                    result["transport_error"] = "invalid_response"
            except TimeoutError:
                result["transport_error"] = "timeout"
            except Exception:
                result["transport_error"] = "request_unavailable"
        result.update(finished_at=self.clock(), latency_ms=max(0.0, (self.monotonic() - started) * 1000))
        return result

    def _sample(self, draft, phase, kind, cycle, response, observation):
        code = response["status_code"]
        return {
            "run_id": draft["id"], "phase": phase, "kind": kind, "cycle": cycle,
            "started_at": response["started_at"], "finished_at": response["finished_at"],
            "latency_ms": response["latency_ms"], "status_code": code,
            "real": self.real, "transport_error": response["transport_error"],
            "error": response["transport_error"] is not None or code is None or code >= 400,
            "observed": observation,
        }

    async def _simple(self, draft, phase, cycle):
        if draft["catalog_id"] == "redis_down":
            response = await self._request(draft, "POST", "/login", json={"username": "sealed-evidence"})
            data = response["data"] or {}
            observation = {"session_present": bool(data.get("session_id")), "fail_closed": data.get("detail") == "fail_closed"}
            kind = "login"
        else:
            response = await self._request(draft, "GET", "/probe")
            observation = {"response_ok": response["status_code"] == 200 and response["transport_error"] is None}
            kind = "handler"
        return [self._sample(draft, phase, kind, cycle, response, observation)]

    async def _worker(self, draft, phase, cycle):
        payloads = [{"evidence_run": draft["id"], "sample": f"{phase}-{cycle}-{index}"} for index in range(WORKER_BATCH)]
        responses = await asyncio.gather(*(self._request(draft, "POST", "/jobs", json={"payload": payload}) for payload in payloads))
        records = []
        for payload, response in zip(payloads, responses, strict=True):
            job_id = (response["data"] or {}).get("job_id")
            valid_id = isinstance(job_id, str) and 0 < len(job_id) <= 128 and all(character.isalnum() or character in "_.-" for character in job_id)
            records.append({"payload": payload, "response": response, "job_id": job_id if valid_id else None, "job": None, "poll_count": 0, "poll_error": None})
        deadline = self.monotonic() + WORKER_POLL_BUDGET_S
        for iteration in range(WORKER_POLL_ROUNDS):
            waiting = [record for record in records if record["job_id"] and (record["job"] or {}).get("status") not in ("done", "dropped", "failed")]
            remaining = deadline - self.monotonic()
            if not waiting or remaining <= 0:
                break
            try:
                polled = await asyncio.wait_for(asyncio.gather(*(self._request(draft, "GET", f"/jobs/{record['job_id']}") for record in waiting)), timeout=remaining)
            except TimeoutError:
                for record in waiting:
                    record["poll_error"] = "job_poll_timeout"
                break
            for record, response in zip(waiting, polled, strict=True):
                record["poll_count"] += 1
                if response["status_code"] == 200 and response["transport_error"] is None:
                    record["job"] = response["data"]
                else:
                    record["poll_error"] = "job_observation_unavailable"
            if iteration + 1 < WORKER_POLL_ROUNDS and any((record["job"] or {}).get("status") not in ("done", "dropped", "failed") for record in waiting):
                await self.sleep(min(WORKER_POLL_INTERVAL_S, max(0, deadline - self.monotonic())))
        samples = []
        for record in records:
            job = record["job"] or {}
            status = job.get("status")
            observation = {
                "job_id": record["job_id"], "job_status": status,
                "terminal": status in ("done", "dropped", "failed"),
                "id_matches": bool(record["job_id"]) and job.get("id") == record["job_id"],
                "payload_matches": job.get("payload") == record["payload"],
                "fault_run_id": job.get("fault_run_id"), "poll_count": record["poll_count"],
                "poll_error": record["poll_error"], "observed_at": self.clock(),
            }
            sample = self._sample(draft, phase, "job", cycle, record["response"], observation)
            samples.append(sample)
        return samples

    async def phase(self, draft, phase, budget=None):
        if phase not in PHASES:
            raise ValueError("unknown_evidence_phase")
        maximum = 24 if phase == "during" else 3
        cycles = (1 if phase == "during" else 3) if budget is None else budget
        if isinstance(cycles, bool) or not isinstance(cycles, int) or not 1 <= cycles <= maximum:
            raise ValueError("invalid_observation_budget")
        key = (draft["id"], phase)
        if self.counts.get(key, 0) + cycles > maximum:
            raise ValueError("observation_budget_exhausted")
        self.counts[key] = self.counts.get(key, 0) + cycles
        samples = []
        for _ in range(cycles):
            self.sequence += 1
            observe = self._worker if draft["catalog_id"] == "worker_drop" else self._simple
            samples.extend(await observe(draft, phase, self.sequence))
        return samples


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _p95(values):
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)] if values else None


def evaluate(draft: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Evaluate measured evidence only; missing/invalid observations always fail."""
    checks = []

    def check(name, passed, expected, observed, phase=None):
        checks.append({"id": name, "phase": phase, "passed": bool(passed), "expected": expected, "observed": observed})

    catalog_id = draft["catalog_id"]
    phases = {phase: evidence.get(phase) if isinstance(evidence.get(phase), list) else [] for phase in PHASES}
    raw_ack = evidence.get("injection_ack") or draft.get("injection_ack")
    ack = raw_ack if isinstance(raw_ack, dict) else {}
    acknowledged = (isinstance(ack, dict) and ack.get("run_id") == draft["id"]
                    and ack.get("id") == catalog_id and ack.get("duration_s") == draft["duration_s"]
                    and ack.get("params") == draft["params"] and _finite(ack.get("until")) and _finite(ack.get("started_at"))
                    and draft["duration_s"] - 0.05 <= ack["until"] - ack["started_at"] <= draft["duration_s"] + 0.05
                    and not ack.get("simulated") and ack.get("status") == "active")
    check("injection_complete", acknowledged and evidence.get("injection_complete") is True and not draft.get("execution_error"),
          {"acknowledged": True, "complete": True, "simulated": False, "authorized_duration_s": draft["duration_s"], "duration_tolerance_s": 0.05},
          {"acknowledged": acknowledged, "complete": evidence.get("injection_complete") is True, "execution_error": bool(draft.get("execution_error")),
           "authorized_duration_s": ack["until"] - ack["started_at"] if _finite(ack.get("until")) and _finite(ack.get("started_at")) else None})
    check("cleanup_confirmed", evidence.get("cleanup_confirmed") is True, True, evidence.get("cleanup_confirmed") is True)

    summaries = {}
    expected_kind = {"redis_down": "login", "handler_latency": "handler", "worker_drop": "job"}[catalog_id]
    minimum = {"baseline": 9 if catalog_id == "worker_drop" else 3, "during": 3 if catalog_id == "worker_drop" else 1, "recovery": 9 if catalog_id == "worker_drop" else 3}
    for phase, samples in phases.items():
        valid = [sample for sample in samples if (
            isinstance(sample, dict) and sample.get("run_id") == draft["id"]
            and sample.get("phase") == phase and sample.get("kind") == expected_kind
            and sample.get("real") is True and sample.get("transport_error") is None
            and _finite(sample.get("latency_ms")) and sample["latency_ms"] >= 0
            and _finite(sample.get("started_at")) and _finite(sample.get("finished_at"))
            and sample["finished_at"] >= sample["started_at"]
            and isinstance(sample.get("status_code"), int) and not isinstance(sample["status_code"], bool)
            and isinstance(sample.get("error"), bool) and isinstance(sample.get("observed"), dict)
            and (expected_kind != "job" or _finite(sample["observed"].get("observed_at")))
        )]
        complete = len(valid) == len(samples) and len(valid) >= minimum[phase]
        check("measured_samples", complete, {"minimum": minimum[phase], "real_and_valid": True}, {"total": len(samples), "valid": len(valid)}, phase)
        latencies = [sample["latency_ms"] for sample in valid]
        rate = sum(sample["error"] for sample in valid) / len(valid) if valid else None
        summary = {"sample_count": len(samples), "valid_count": len(valid), "p95_ms": _p95(latencies), "error_rate": rate,
                   "first_at": min((sample["started_at"] for sample in valid), default=None), "last_at": max((sample["finished_at"] for sample in valid), default=None)}
        if catalog_id == "worker_drop":
            outcomes = {status: sum(sample["observed"].get("job_status") == status for sample in valid) for status in ("done", "dropped", "failed", "queued", "processing")}
            summary.update(job_outcomes=outcomes, drop_rate=outcomes["dropped"] / len(valid) if valid else None)
        summaries[phase] = summary
        for metric in ("p95_ms", "error_rate"):
            bound = draft["hypothesis"]["slo"][metric]
            observed = summary[metric]
            check(f"slo_{metric}", complete and observed is not None and observed <= bound, {"at_most": bound}, observed, phase)
        if phase != "during":
            check("healthy_outside_fault", complete and rate == 0, {"error_rate": 0}, rate, phase)

    # Assertions use only measurements that passed the per-phase shape checks.
    shape_ok = all(item["passed"] for item in checks if item["id"] == "measured_samples")
    if shape_ok:
        baseline, during, recovery = (phases[phase] for phase in PHASES)
        ordered = (summaries["baseline"]["last_at"] <= summaries["during"]["first_at"]
                   and summaries["during"]["last_at"] <= summaries["recovery"]["first_at"])
        inside_authorization = _finite(ack.get("until")) and all(sample["started_at"] < ack["until"] and sample["finished_at"] <= ack["until"] and sample["observed"].get("observed_at", sample["finished_at"]) <= ack["until"] for sample in during)
        if _finite(draft.get("unsealed_at")):
            ordered = ordered and summaries["baseline"]["last_at"] <= draft["unsealed_at"]
            inside_authorization = inside_authorization and all(sample["started_at"] >= draft["unsealed_at"] for sample in during)
        if _finite(draft.get("cleanup_confirmed_at")):
            ordered = ordered and summaries["recovery"]["first_at"] >= draft["cleanup_confirmed_at"]
        check("observation_phase_order", ordered and inside_authorization,
              "baseline precedes authorized during observations; recovery follows during", {"ordered": ordered, "during_before_expiry": inside_authorization})
        if catalog_id == "redis_down":
            closed = all(sample["status_code"] == 503 and sample["observed"].get("fail_closed") is True and not sample["observed"].get("session_present") for sample in during)
            restored = all(sample["status_code"] == 200 and sample["observed"].get("session_present") is True for sample in baseline + recovery)
            check("fail_closed_on_redis_loss", closed and restored,
                  {"during": "503 without session", "baseline_and_recovery": "200 with session"},
                  {"closed_samples": sum(sample["status_code"] == 503 and not sample["observed"].get("session_present") for sample in during), "during_samples": len(during), "recovered": restored})
        elif catalog_id == "handler_latency":
            base = statistics.median(sample["latency_ms"] for sample in baseline)
            fault = statistics.median(sample["latency_ms"] for sample in during)
            recovered = summaries["recovery"]["p95_ms"]
            delay = draft["params"]["delay_ms"]
            minimum_rise = delay * 0.5
            recovery_limit = base + max(75.0, base * 0.5)
            successful = all(sample["status_code"] == 200 and sample["observed"].get("response_ok") is True for sample in baseline + during + recovery)
            check("latency_recovers_after_reseal", successful and fault - base >= minimum_rise and recovered <= recovery_limit,
                  {"minimum_median_rise_ms": minimum_rise, "recovery_p95_at_most_ms": recovery_limit, "all_http_status": 200},
                  {"baseline_median_ms": base, "during_median_ms": fault, "rise_ms": fault - base, "recovery_p95_ms": recovered, "all_requests_successful": successful})
        else:
            all_samples = baseline + during + recovery
            observations = [sample["observed"] for sample in all_samples]
            ids = [observation.get("job_id") for observation in observations]
            intact = all(observation.get("terminal") is True and observation.get("id_matches") is True and observation.get("payload_matches") is True and observation.get("job_status") in ("done", "dropped") and not observation.get("poll_error") for observation in observations)
            unique = all(isinstance(job_id, str) and bool(job_id) for job_id in ids) and len(set(ids)) == len(ids)
            dropped = [sample for sample in during if sample["observed"].get("job_status") == "dropped"]
            rate = draft["params"]["drop_rate"]
            expected_drops = bool(dropped) if rate > 0 else not dropped
            correlated = all(sample["observed"].get("fault_run_id") == draft["id"] for sample in dropped)
            restored = all(sample["observed"].get("job_status") == "done" for sample in baseline + recovery)
            check("dropped_jobs_do_not_corrupt_queue", intact and unique and expected_drops and correlated and restored,
                  {"terminal_statuses": ["done", "dropped"], "payloads_intact": True, "unique_jobs": True, "drop_observed": rate > 0, "baseline_and_recovery": "all done"},
                  {"terminal_and_intact": intact, "unique_jobs": unique, "drop_count": len(dropped), "during_jobs": len(during), "drops_match_run": correlated, "recovered": restored})
    else:
        assertion = {"redis_down": "fail_closed_on_redis_loss", "handler_latency": "latency_recovers_after_reseal", "worker_drop": "dropped_jobs_do_not_corrupt_queue"}[catalog_id]
        check(assertion, False, "complete measured baseline, during and recovery evidence", "missing_or_invalid_evidence")

    evaluated_assertions = {item["id"] for item in checks}
    for assertion in draft["hypothesis"]["must"]:
        if assertion not in evaluated_assertions:
            check(assertion, False, "supported measured assertion", "assertion_not_applicable_to_fault")
    failures = [item["id"] for item in checks if not item["passed"]]
    if not failures:
        reason = "measured_hypothesis_satisfied"
    elif "measured_samples" in failures:
        reason = "missing_or_invalid_evidence"
    elif "injection_complete" in failures:
        reason = "incomplete_injection"
    elif "cleanup_confirmed" in failures:
        reason = "cleanup_unconfirmed"
    else:
        reason = "hypothesis_not_satisfied"
    return {"verdict": "fail" if failures else "pass", "reason": reason, "checks": checks, "summary": summaries}
