"""Privileged Compose target adapter. Credentials never enter public responses."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import math
from pathlib import Path


def credential():
    path = os.environ.get("UNSEAL_TOKEN_FILE")
    return Path(path).read_text().strip() if path else os.environ.get("UNSEAL_TOKEN", "")


class TargetAdapter:
    def __init__(self, app):
        self.app = app

    @property
    def url(self):
        return self.app.state.target_url.rstrip("/")

    def headers(self):
        return {"X-Sealed-Token": credential()}

    def validate_ack(self, ack, draft):
        until = ack.get("until") if isinstance(ack, dict) else None
        if (
            not isinstance(ack, dict)
            or ack.get("run_id") != draft["id"]
            or ack.get("id") != draft["catalog_id"]
            or ack.get("params") != draft["params"]
            or ack.get("duration_s") != draft["duration_s"]
            or ack.get("status") != "active"
            or isinstance(until, bool)
            or not isinstance(until, (float, int))
            or not math.isfinite(until)
            or not time.time() - 5 < until <= time.time() + draft["duration_s"] + 2
        ):
            raise RuntimeError("invalid_target_ack")
        return ack

    async def inject(self, draft):
        if not self.url:
            if not self.app.state.simulated_target:
                raise RuntimeError("target_not_configured")
            return {"run_id": draft["id"], "until": time.time() + draft["duration_s"], "simulated": True}
        body = {"run_id": draft["id"], "id": draft["catalog_id"], "duration_s": draft["duration_s"], "params": draft["params"], "authorization_expires_at": time.time() + draft["duration_s"] + 2}
        signature = hmac.new(credential().encode(), json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(), hashlib.sha256).hexdigest()
        response = await self.app.state.http.post(f"{self.url}/_faults", json=body, headers={**self.headers(), "X-Sealed-Authorization": signature}, timeout=3)
        response.raise_for_status()
        ack = response.json()
        self.validate_ack(ack, draft)
        if ack["until"] > body["authorization_expires_at"]:
            raise RuntimeError("invalid_target_ack")
        return ack

    async def status(self):
        if not self.url:
            return {"active": None}
        response = await self.app.state.http.get(f"{self.url}/_faults", headers=self.headers(), timeout=2)
        response.raise_for_status()
        return response.json()

    async def clear(self, run_id):
        if not self.url:
            return {"run_id": run_id, "cleanup_confirmed": True, "simulated": True}
        response = await self.app.state.http.delete(f"{self.url}/_faults/{run_id}", headers=self.headers(), timeout=2)
        response.raise_for_status()
        return response.json()
