"""Run in the Compose control container; never prints or exports its credential."""

import json
import os
from pathlib import Path
import time

import httpx


def main():
    token = Path(os.environ["UNSEAL_TOKEN_FILE"]).read_text().strip()
    headers = {"X-Sealed-Token": token}
    result = {}
    with httpx.Client(timeout=5, trust_env=False) as client:
        def request(method, url, expected=200, **kwargs):
            response = client.request(method, url, **kwargs)
            assert response.status_code == expected, f"{method} {url}: {response.status_code} {response.text}"
            return response.json() if response.content else None

        def target_state():
            return request("GET", "http://target:8080/_faults", headers=headers)

        for supplied in ({}, {"X-Sealed-Token": "wrong"}):
            request("GET", "http://target:8080/_faults", expected=403, headers=supplied)
            request("POST", "http://target:8080/_faults", expected=403, headers=supplied, json={})
            request("DELETE", "http://target:8080/_faults/not-authorized", expected=403, headers=supplied)
        request("POST", "http://target:8080/_faults", expected=403, headers=headers, json={})
        result["private_target_auth"] = "missing/wrong token: GET POST DELETE 403; token without signature POST 403"

        for base, prefix in (("http://web:5173", "/target"), ("http://target-web:5174", "/api")):
            for suffix in ("/_faults", "/_faults/unknown", "/%5Ffaults"):
                for method in ("GET", "POST", "DELETE"):
                    response = client.request(method, base + prefix + suffix, headers={"Host": "localhost"})
                    assert response.status_code == 404, f"private browser proxy returned {response.status_code}"
            response = client.get(base + prefix + "/health", headers={"Host": "localhost"})
            assert response.status_code == 200
        result["browser_boundary"] = "18 privileged proxy requests blocked with 404; public health routes 200"

        assert target_state()["active"] is None
        draft = request("POST", "http://127.0.0.1:8081/drafts", json={
            "catalog_id": "handler_latency", "environment": "prod", "target": "api", "duration_s": 5,
        })
        request("POST", f"http://127.0.0.1:8081/drafts/{draft['id']}/approve")
        denial = request("POST", f"http://127.0.0.1:8081/drafts/{draft['id']}/unseal", expected=403)
        assert "environment_denied" in denial["detail"]["reasons"]
        events = request("GET", f"http://127.0.0.1:8081/drafts/{draft['id']}/events")
        assert not any(event["kind"] == "inject_requested" for event in events)
        assert target_state()["active"] is None
        result["prod_denial"] = "403 environment_denied; no injection event; target idle before/after"

        redis = request("POST", "http://127.0.0.1:8081/drafts", json={
            "catalog_id": "redis_down", "environment": "demo", "target": "redis", "duration_s": 15,
        })
        assert redis["status"] == "draft"
        request("POST", f"http://127.0.0.1:8081/drafts/{redis['id']}/approve")
        active = request("POST", f"http://127.0.0.1:8081/drafts/{redis['id']}/unseal")
        assert active["status"] == "unsealed"
        assert target_state()["active"]["run_id"] == redis["id"]
        failure = request("POST", "http://target:8080/login", expected=503, json={"username": "acceptance"})
        assert failure["detail"] == "fail_closed"
        started = time.monotonic()
        abort = request("POST", f"http://127.0.0.1:8081/drafts/{redis['id']}/reseal")
        elapsed = time.monotonic() - started
        assert abort["draft"]["cleanup_confirmed"] is True
        assert abort["seal"]["verdict"] == "aborted"
        assert target_state()["active"] is None
        request("POST", "http://target:8080/login", json={"username": "acceptance"})
        repeated = request("POST", f"http://127.0.0.1:8081/drafts/{redis['id']}/reseal")
        assert repeated["seal"]["id"] == abort["seal"]["id"]
        request("POST", f"http://127.0.0.1:8081/drafts/{redis['id']}/unseal", expected=409)
        result["redis_abort_recovery"] = {"login_during": 503, "login_after": 200, "verdict": "aborted", "abort_ms": round(elapsed * 1000), "idempotent_seal": True}

        assert os.environ.get("PLANNER") == "stub"
        proposal = request("POST", "http://127.0.0.1:8081/agent/propose")
        assert proposal["draft"]["status"] == "draft"
        assert proposal["draft"]["source"] == "agent"
        assert target_state()["active"] is None
        result["planner"] = "explicit stub; proposal persisted as draft; target remains idle"

        latency = request("POST", "http://127.0.0.1:8081/drafts", json={
            "catalog_id": "handler_latency", "environment": "demo", "target": "api", "duration_s": 0.5,
        })
        assert latency["status"] == "unsealed"
        # No requests while the timer elapses: completion must not depend on browser polling.
        time.sleep(1.2)
        seals = request("GET", "http://127.0.0.1:8081/seals")
        matching = [seal for seal in seals if seal["draft_id"] == latency["id"]]
        assert len(matching) == 1
        assert matching[0]["verdict"] == "fail"
        assert matching[0]["reason"] in {"missing_measured_evidence", "missing_or_invalid_evidence"}
        assert target_state()["active"] is None
        result["autonomous_completion"] = f"one fail seal with {matching[0]['reason']} after 1.2 seconds without requests"

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
