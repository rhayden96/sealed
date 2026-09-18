"""Final static-runtime and policy-preview checks; run in Compose control."""

import json

import httpx


def main():
    results = {}
    with httpx.Client(timeout=10, trust_env=False) as client:
        for service, port in (("web", 5173), ("target-web", 5174)):
            base = f"http://{service}:{port}"
            health = client.get(base + "/healthz")
            assert health.status_code == 200
            assert health.json()["runtime"] == "built-assets"
            index = client.get(base + "/")
            assert index.status_code == 200
            assert "/assets/" in index.text and "/@vite/client" not in index.text
            assert "script-src 'self'" in index.headers["content-security-policy"]
            for source in ("/src/main.jsx", "/node_modules/vite/dist/client/client.mjs"):
                assert client.get(base + source).status_code == 404
            results[service] = "built assets, CSP, no source or Vite runtime exposed"
        config = client.get("http://web:5173/config.js")
        assert config.status_code == 200 and "http://localhost:5174/" in config.text
        assert client.get("http://target:8080/ready").status_code == 200

        base = "http://127.0.0.1:8081"
        assert client.get(base + "/active-run").json() is None
        response = client.post(base + "/game-days", json={"steps": ["redis_down", "handler_latency"]})
        assert response.status_code == 200
        day = response.json()
        try:
            future_id = day["steps"][1]["draft_id"]
            path = f"{base}/drafts/{future_id}"
            assert client.post(path + "/approve").status_code == 200
            before = client.get(path + "/events").json()
            for _ in range(2):
                preview = client.get(path + "/evaluate")
                assert preview.status_code == 200
                assert preview.json()["allowed"] is False
                assert "step_skipped" in preview.json()["reasons"]
            assert client.get(path + "/events").json() == before
            denial = client.post(path + "/unseal")
            assert denial.status_code == 403
            assert "step_skipped" in denial.json()["detail"]["reasons"]
            assert not any(event["kind"] == "inject_requested" for event in client.get(path + "/events").json())
            results["game_day_preview"] = "future step denied by GET preview and POST unseal; preview creates no events; no injection"
        finally:
            ended = client.post(f"{base}/game-days/{day['id']}/end")
            assert ended.status_code == 200
            assert all(step["status"] == "cancelled" for step in ended.json()["steps"])
        assert client.get(base + "/active-run").json() is None
        results["cleanup"] = "test game day ended, drafts cancelled, no active run"
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
