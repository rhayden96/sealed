from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sealed_control.loader import load_catalog, load_policy
from sealed_control.main import create_app
from sealed_control.store import Store

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    catalog = load_catalog(REPO / "experiments" / "catalog.yaml")
    policy = load_policy(REPO / "experiments" / "policy.yaml")
    app = create_app(
        catalog=catalog, policy=policy, store=Store(), target_url=""
    )
    with TestClient(app) as test_client:
        yield test_client
