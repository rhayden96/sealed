import hashlib
import hmac
import json
import time
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from sealed_target.main import create_app
from sealed_target.worker import HEARTBEAT_KEY

TEST_TOKEN = "test-unseal"


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {HEARTBEAT_KEY: json.dumps({"at": time.time(), "worker_id": "test-worker"})}

    async def ping(self) -> bool:
        return True

    async def set(self, key: str, value: str, ex: int | None = None, px: int | None = None) -> bool:
        self.store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def lpush(self, key: str, value: str) -> int:
        cur = self.store.get(key)
        if not isinstance(cur, list):
            cur = [] if cur is None else [cur]
        cur.insert(0, value)
        self.store[key] = cur
        return len(cur)

    async def lrange(self, key: str, start: int, end: int) -> list:
        cur = self.store.get(key, [])
        if not isinstance(cur, list):
            return []
        if end < 0:
            return cur[start:]
        return cur[start : end + 1]

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    async def aclose(self) -> None:
        return None


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app = create_app(redis_factory=FakeRedis, token=TEST_TOKEN)
    with TestClient(app) as test_client:
        yield test_client


def authorization(body: dict) -> dict[str, str]:
    message = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"X-Sealed-Token": TEST_TOKEN, "X-Sealed-Authorization": hmac.new(TEST_TOKEN.encode(), message, hashlib.sha256).hexdigest()}


def fault_body(run_id: str = "run-a", fault_id: str = "redis_down", duration: float = 15, **overrides) -> dict:
    return {"run_id": run_id, "id": fault_id, "duration_s": duration, "params": {}, "authorization_expires_at": time.time() + duration + 2, **overrides}
