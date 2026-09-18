import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from sealed_target.main import create_app

TEST_TOKEN = "test-unseal"


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def ping(self) -> bool:
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
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
    os.environ["UNSEAL_TOKEN"] = TEST_TOKEN
    app = create_app(redis_factory=FakeRedis)
    with TestClient(app) as test_client:
        yield test_client
