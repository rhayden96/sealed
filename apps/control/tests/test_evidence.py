"""Measured pass/fail examples and bounded workload behavior, without network."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from sealed_control.evidence import Observer, evaluate


def example(catalog_id="handler_latency"):
    worker = catalog_id == "worker_drop"
    kind = {"handler_latency": "handler", "redis_down": "login", "worker_drop": "job"}[catalog_id]
    assertion = {"handler_latency": "latency_recovers_after_reseal", "redis_down": "fail_closed_on_redis_loss", "worker_drop": "dropped_jobs_do_not_corrupt_queue"}[catalog_id]
    draft = {"id": "run-evidence", "catalog_id": catalog_id, "duration_s": 15 if worker else 5,
             "params": {"delay_ms": 300} if catalog_id == "handler_latency" else {"drop_rate": 0.2} if worker else {},
             "hypothesis": {"slo": {"p95_ms": 500, "error_rate": 1 if catalog_id == "redis_down" else 0.25 if worker else 0.01}, "must": [assertion]},
             "unsealed_at": 200.0, "cleanup_confirmed_at": 220.0}
    evidence = {"injection_complete": True, "cleanup_confirmed": True,
                "injection_ack": {"run_id": draft["id"], "id": catalog_id, "status": "active", "started_at": 200.0, "until": 200.0 + draft["duration_s"], "duration_s": draft["duration_s"], "params": draft["params"]}}
    for phase, stamp in (("baseline", 100), ("during", 201), ("recovery", 230)):
        samples = []
        for index in range(9 if worker else 3):
            observation = {"response_ok": True}
            status, latency = 200, 10.0
            if catalog_id == "handler_latency" and phase == "during":
                latency = 310.0
            if catalog_id == "redis_down":
                status = 503 if phase == "during" else 200
                observation = {"session_present": phase != "during", "fail_closed": phase == "during"}
            if worker:
                status = 202
                dropped = phase == "during" and index in {3, 8}
                observation = {"job_id": f"{phase}-{index}", "job_status": "dropped" if dropped else "done", "terminal": True,
                               "id_matches": True, "payload_matches": True, "fault_run_id": draft["id"] if dropped else None,
                               "poll_error": None, "observed_at": stamp + index * 0.05 + 0.02}
            started = stamp + index * 0.05
            samples.append({"run_id": draft["id"], "phase": phase, "kind": kind, "cycle": index,
                            "started_at": started, "finished_at": started + latency / 1000, "latency_ms": latency,
                            "status_code": status, "real": True, "transport_error": None, "error": status >= 400, "observed": observation})
        evidence[phase] = samples
    return draft, evidence


@pytest.mark.parametrize("catalog_id", ["handler_latency", "redis_down", "worker_drop"])
def test_measured_hypothesis_passes_for_each_catalog_assertion(catalog_id):
    draft, evidence = example(catalog_id)
    before = deepcopy(evidence)
    result = evaluate(draft, evidence)
    assert result["verdict"] == "pass", result
    assert result["reason"] == "measured_hypothesis_satisfied"
    assert all(check["passed"] for check in result["checks"])
    assert result["summary"]["recovery"]["sample_count"] >= 3
    assert evidence == before


@pytest.mark.parametrize("damage", ["empty", "missing_recovery", "simulated", "partial_injection", "cleanup_pending", "transport_failure", "nan_latency", "wrong_run", "bad_kind", "missing_ack", "wrong_ack_fault"])
def test_incomplete_or_untrusted_evidence_never_passes(damage):
    draft, evidence = example()
    if damage == "empty":
        evidence = {}
    elif damage == "missing_recovery":
        evidence["recovery"] = []
    elif damage == "simulated":
        evidence["injection_ack"]["simulated"] = True
    elif damage == "partial_injection":
        evidence["injection_complete"] = False
    elif damage == "cleanup_pending":
        evidence["cleanup_confirmed"] = False
    elif damage == "transport_failure":
        evidence["during"][0]["transport_error"] = "timeout"
    elif damage == "nan_latency":
        evidence["during"][0]["latency_ms"] = float("nan")
    elif damage == "wrong_run":
        evidence["during"][0]["run_id"] = "different"
    elif damage == "bad_kind":
        evidence["during"][0]["kind"] = "health"
    elif damage == "missing_ack":
        evidence["injection_ack"] = []
    else:
        evidence["injection_ack"]["id"] = "redis_down"
    result = evaluate(draft, evidence)
    assert result["verdict"] == "fail"
    assert any(not item["passed"] for item in result["checks"])


def test_tight_slo_fails_despite_recovery_and_correct_fault():
    draft, evidence = example()
    draft["hypothesis"]["slo"]["p95_ms"] = 100
    result = evaluate(draft, evidence)
    assert result["verdict"] == "fail"
    assert any(item["id"] == "slo_p95_ms" and item["phase"] == "during" and not item["passed"] for item in result["checks"])


@pytest.mark.parametrize("duration", [None, float("nan"), 1.0, 6.0])
def test_missing_shortened_or_unbounded_authorization_cannot_pass(duration):
    draft, evidence = example()
    if duration is None:
        evidence["injection_ack"].pop("started_at")
    else:
        evidence["injection_ack"]["until"] = 200.0 + duration
    result = evaluate(draft, evidence)
    assert result["verdict"] == "fail"
    assert any(check["id"] == "injection_complete" and not check["passed"] for check in result["checks"])


@pytest.mark.parametrize("damage", ["no_rise", "no_recovery", "late_sample", "early_recovery", "baseline_after_inject"])
def test_latency_requires_observed_effect_recovery_and_phase_timing(damage):
    draft, evidence = example()
    if damage == "no_rise":
        for sample in evidence["during"]:
            sample["latency_ms"] = 10
    elif damage == "no_recovery":
        for sample in evidence["recovery"]:
            sample["latency_ms"] = 310
    elif damage == "late_sample":
        evidence["during"][-1]["finished_at"] = 221
    elif damage == "early_recovery":
        draft["cleanup_confirmed_at"] = 250
    else:
        draft["unsealed_at"] = 90
    assert evaluate(draft, evidence)["verdict"] == "fail"


@pytest.mark.parametrize("damage", ["session_on_denial", "wrong_error", "no_recovered_session", "baseline_error"])
def test_redis_requires_fail_closed_and_successful_baseline_recovery(damage):
    draft, evidence = example("redis_down")
    if damage == "session_on_denial":
        evidence["during"][0]["observed"]["session_present"] = True
    elif damage == "wrong_error":
        evidence["during"][0]["observed"]["fail_closed"] = False
    elif damage == "no_recovered_session":
        evidence["recovery"][0]["observed"]["session_present"] = False
    else:
        evidence["baseline"][0]["error"] = True
        evidence["baseline"][0]["status_code"] = 503
    assert evaluate(draft, evidence)["verdict"] == "fail"


@pytest.mark.parametrize("damage", ["no_drop", "queue_stuck", "wrong_run_drop", "corrupt_payload", "duplicate_job", "failed_job", "drop_after_cleanup"])
def test_worker_requires_correlated_drops_intact_terminal_jobs_and_recovery(damage):
    draft, evidence = example("worker_drop")
    if damage == "no_drop":
        for sample in evidence["during"]:
            sample["observed"]["job_status"] = "done"
    elif damage == "queue_stuck":
        evidence["during"][0]["observed"].update(terminal=False, job_status="queued")
    elif damage == "wrong_run_drop":
        evidence["during"][3]["observed"]["fault_run_id"] = "another-run"
    elif damage == "corrupt_payload":
        evidence["during"][0]["observed"]["payload_matches"] = False
    elif damage == "duplicate_job":
        evidence["during"][0]["observed"]["job_id"] = evidence["baseline"][0]["observed"]["job_id"]
    elif damage == "failed_job":
        evidence["during"][0]["observed"]["job_status"] = "failed"
    else:
        evidence["recovery"][0]["observed"]["job_status"] = "dropped"
    assert evaluate(draft, evidence)["verdict"] == "fail"


def test_worker_drop_outcomes_are_separate_from_http_error_rate():
    draft, evidence = example("worker_drop")
    result = evaluate(draft, evidence)
    assert result["summary"]["during"]["error_rate"] == 0
    assert result["summary"]["during"]["drop_rate"] == 2 / 9
    assert result["summary"]["during"]["job_outcomes"]["dropped"] == 2


def test_zero_drop_configuration_does_not_require_a_drop():
    draft, evidence = example("worker_drop")
    draft["params"]["drop_rate"] = 0
    for sample in evidence["during"]:
        sample["observed"]["job_status"] = "done"
    assert evaluate(draft, evidence)["verdict"] == "pass"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    async def sleep(self, duration):
        self.now += duration


class Workload:
    def __init__(self, clock, *, pending=False, unavailable=False):
        self.clock, self.pending, self.unavailable = clock, pending, unavailable
        self.calls, self.jobs = [], {}

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        self.clock.now += 0.01
        if self.unavailable:
            raise httpx.ReadTimeout("private credential must never appear in observation")
        if method == "POST" and url.endswith("/jobs"):
            job_id = f"job-{len(self.jobs)}"
            self.jobs[job_id] = {"id": job_id, "status": "queued" if self.pending else "done", "payload": kwargs["json"]["payload"]}
            return httpx.Response(202, json={"job_id": job_id, "status": "queued"})
        if "/jobs/" in url:
            return httpx.Response(200, json=self.jobs[url.rsplit("/", 1)[-1]])
        if url.endswith("/login"):
            return httpx.Response(200, json={"session_id": "secret-session-value"})
        return httpx.Response(200, json={"status": "ok"})


def observer(workload, clock, *, simulated=False):
    app = SimpleNamespace(state=SimpleNamespace(target_url="http://target:8080", simulated_target=simulated, http=workload))
    return Observer(app, clock=clock, monotonic=clock, sleep=clock.sleep)


def test_sampler_never_records_login_session_values_or_transport_errors():
    async def scenario():
        clock = FakeClock()
        workload = Workload(clock)
        subject = observer(workload, clock)
        draft, _ = example("redis_down")
        samples = await subject.phase(draft, "baseline")
        assert len(samples) == 3
        assert all(sample["observed"]["session_present"] for sample in samples)
        assert "secret-session-value" not in str(samples)
        workload.unavailable = True
        failures = await subject.phase(draft, "during")
        assert failures[0]["transport_error"] == "request_unavailable"
        assert "private credential" not in str(failures)
        assert all(call[2]["headers"]["X-Sealed-Run"] == draft["id"] for call in workload.calls)
    asyncio.run(scenario())


def test_simulated_sampler_performs_zero_requests_and_cannot_report_real_samples():
    async def scenario():
        clock = FakeClock()
        workload = Workload(clock)
        draft, _ = example()
        samples = await observer(workload, clock, simulated=True).phase(draft, "baseline")
        assert len(samples) == 3
        assert workload.calls == []
        assert all(not sample["real"] and sample["transport_error"] for sample in samples)
    asyncio.run(scenario())


def test_worker_sampling_has_bounded_jobs_polling_and_preserves_unfinished_evidence():
    async def scenario():
        clock = FakeClock()
        workload = Workload(clock, pending=True)
        draft, _ = example("worker_drop")
        subject = observer(workload, clock)
        samples = await subject.phase(draft, "during", budget=1)
        assert len(samples) == 3
        assert len(workload.jobs) == 3
        assert len(workload.calls) <= 3 + 3 * 8
        assert all(sample["observed"]["terminal"] is False for sample in samples)
        assert all(sample["error"] is False for sample in samples)  # Queue outcomes are separate.
        assert all(sample["observed"]["poll_count"] <= 8 for sample in samples)
    asyncio.run(scenario())


def test_cumulative_phase_budgets_are_enforced_across_calls():
    async def scenario():
        clock = FakeClock()
        workload = Workload(clock)
        draft, _ = example()
        subject = observer(workload, clock)
        await subject.phase(draft, "baseline")
        with pytest.raises(ValueError, match="budget_exhausted"):
            await subject.phase(draft, "baseline", budget=1)
        await subject.phase(draft, "during", budget=24)
        with pytest.raises(ValueError, match="budget_exhausted"):
            await subject.phase(draft, "during")
        with pytest.raises(ValueError, match="invalid_observation_budget"):
            await subject.phase(draft, "recovery", budget=True)
        assert len(workload.calls) == 27
    asyncio.run(scenario())
