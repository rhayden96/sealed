"""Measured Compose acceptance. Run inside control; no credential is printed.

Default mode exercises all faults and leaves one active run for a control
restart. After `docker compose restart control`, run with `verify-restart`.
Use `smoke` to exercise the measured runs without leaving an interrupted run.
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx


BASE = "http://127.0.0.1:8081"
CHECKPOINT = Path("/data/b-acceptance-checkpoint.json")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main(mode="run"):
    token = Path(os.environ["UNSEAL_TOKEN_FILE"]).read_text().strip()
    with httpx.Client(timeout=20, trust_env=False) as client:
        def request(method, path, expected=200, **kwargs):
            response = client.request(method, path if path.startswith("http") else BASE + path, **kwargs)
            assert response.status_code == expected, f"{method} {path}: {response.status_code} {response.text}"
            return response.json() if response.content else None

        def status():
            return request("GET", "http://target:8080/_faults", headers={"X-Sealed-Token": token})

        def create(catalog_id, duration=None, hypothesis=None, environment="demo"):
            target = {"handler_latency": "api", "redis_down": "redis", "worker_drop": "worker"}[catalog_id]
            body = {"catalog_id": catalog_id, "environment": environment, "target": target}
            if duration is not None:
                body["duration_s"] = duration
            if hypothesis is not None:
                body["hypothesis"] = hypothesis
            return request("POST", "/drafts", json=body)

        def start(draft):
            if draft["status"] == "unsealed":
                return draft
            request("POST", f"/drafts/{draft['id']}/approve")
            return request("POST", f"/drafts/{draft['id']}/unseal")

        def seal_for(run_id, timeout=8):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                seal = request("GET", f"/drafts/{run_id}/seal")
                if seal:
                    return seal
                time.sleep(0.1)
            raise AssertionError(f"run {run_id} did not finalize")

        def describe(seal):
            evaluation = (seal.get("evidence") or {}).get("evaluation") or {}
            return {"run_id": seal["draft_id"], "verdict": seal["verdict"], "reason": seal["reason"],
                    "phases": evaluation.get("summary"), "failed_checks": [item for item in evaluation.get("checks", []) if not item["passed"]]}

        def finished(draft, verdict):
            # No browser/poll requests during the entire authorized fault duration.
            time.sleep(max(0, draft["unsealed_until"] - time.time()) + 1)
            seal = seal_for(draft["id"])
            assert seal["verdict"] == verdict, describe(seal)
            assert status()["active"] is None
            print(json.dumps(describe(seal)), flush=True)
            return seal

        if mode == "worker-stopped":
            time.sleep(4)
            health = request("GET", "http://target:8080/health")
            assert health["worker"] == "down", health
            request("GET", "http://target:8080/ready", expected=503)
            print("PASS stopped worker reports down and readiness returns 503", flush=True)
            return

        if mode == "worker-recovered":
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                health = request("GET", "http://target:8080/health")
                if health["worker"] == "ok":
                    request("GET", "http://target:8080/ready")
                    print("PASS restarted worker heartbeat restores readiness", flush=True)
                    return
                time.sleep(0.1)
            raise AssertionError("worker did not regain readiness")

        if mode == "prepare-target-restart":
            assert status()["active"] is None
            draft = start(create("handler_latency", duration=10))
            checkpoint = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {}
            checkpoint["target_interrupted_id"] = draft["id"]
            CHECKPOINT.write_text(json.dumps(checkpoint))
            # Lifecycle stops starting new simple samples with <=2.1 seconds left.
            time.sleep(max(0, draft["unsealed_until"] - time.time() - 1.5))
            print(json.dumps({"restart_target_now": draft["id"], "remaining_s": draft["unsealed_until"] - time.time()}), flush=True)
            return

        if mode == "verify-target-restart":
            checkpoint = json.loads(CHECKPOINT.read_text())
            seal = seal_for(checkpoint["target_interrupted_id"])
            assert seal["verdict"] == "fail", describe(seal)
            assert seal["reason"] == "infrastructure_failure", describe(seal)
            assert status()["active"] is None
            print(json.dumps({"late_target_restart": "passed", "seal": describe(seal)}), flush=True)
            return

        if mode == "verify-restart":
            ready_by = time.monotonic() + 10
            while True:
                try:
                    response = client.get(BASE + "/health", timeout=0.5)
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= ready_by:
                    raise AssertionError("control did not become healthy after restart")
                time.sleep(0.1)
            checkpoint = json.loads(CHECKPOINT.read_text())
            for saved in checkpoint["history"]:
                seal = request("GET", f"/seals/{saved['id']}")
                assert fingerprint(seal) == saved["fingerprint"], "immutable prior seal changed across restart"
            interrupted = seal_for(checkpoint["interrupted_id"])
            assert interrupted["verdict"] == "fail", describe(interrupted)
            assert interrupted["reason"] == "control_restarted", describe(interrupted)
            assert status()["active"] is None
            all_seals = request("GET", "/seals?limit=200")
            assert sum(seal["draft_id"] == checkpoint["interrupted_id"] for seal in all_seals) == 1
            assert seal_for(checkpoint["interrupted_id"])["id"] == interrupted["id"]
            print(json.dumps({"restart": "passed", "immutable_prior_seals": len(checkpoint["history"]), "interrupted_run": describe(interrupted)}), flush=True)
            return

        assert status()["active"] is None
        healthy = request("GET", "http://target:8080/health")
        assert healthy["worker"] == "ok" and healthy["redis"] == "ok", healthy
        history = []
        latency = finished(start(create("handler_latency")), "pass")
        history.append(latency)
        assert latency["reason"] == "measured_hypothesis_satisfied"

        tight = {"slo": {"p95_ms": 100, "error_rate": 0.01}, "must": ["latency_recovers_after_reseal"]}
        history.append(finished(start(create("handler_latency", hypothesis=tight)), "fail"))

        prod = create("handler_latency", environment="prod")
        request("POST", f"/drafts/{prod['id']}/approve")
        request("POST", f"/drafts/{prod['id']}/unseal", expected=403)
        assert not any(event["kind"] == "inject_requested" for event in request("GET", f"/drafts/{prod['id']}/events"))
        assert status()["active"] is None
        print("PASS prod denied with no injection event", flush=True)

        redis_abort = start(create("redis_down"))
        response = request("POST", "http://target:8080/login", expected=503, json={"username": "acceptance"})
        assert response["detail"] == "fail_closed"
        request("POST", f"/drafts/{redis_abort['id']}/reseal")
        aborted = seal_for(redis_abort["id"])
        assert aborted["verdict"] == "aborted"
        request("POST", "http://target:8080/login", json={"username": "acceptance"})
        assert status()["active"] is None
        history.append(aborted)
        print("PASS Redis fail-closed and acknowledged abort/recovery", flush=True)

        history.append(finished(start(create("redis_down", duration=5)), "pass"))
        worker = finished(start(create("worker_drop")), "pass")
        history.append(worker)
        summary = worker["evidence"]["evaluation"]["summary"]["during"]
        assert summary["job_outcomes"]["dropped"] > 0
        assert summary["error_rate"] == 0, "intentional dropped jobs must not count as HTTP failures"
        assert summary["drop_rate"] > 0

        if mode == "smoke":
            print(json.dumps({"core_acceptance": "passed", "history_seals": len(history), "target_idle": status()["active"] is None}), flush=True)
            return

        interrupted = start(create("redis_down", duration=20))
        CHECKPOINT.write_text(json.dumps({"interrupted_id": interrupted["id"], "history": [{"id": seal["id"], "fingerprint": fingerprint(seal)} for seal in history]}))
        print(json.dumps({"core_acceptance": "passed", "restart_required_now": interrupted["id"], "history_seals": len(history)}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "run")
