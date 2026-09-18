from pathlib import Path

import pytest

from sealed_agent.tools import Tools
from sealed_control.loader import load_catalog, load_policy
from sealed_control.store import Store

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def catalog():
    return load_catalog(ROOT / "experiments/catalog.yaml")


@pytest.fixture
def policy():
    return load_policy(ROOT / "experiments/policy.yaml")


@pytest.fixture
def agent_tools(catalog, policy, monkeypatch):
    monkeypatch.setenv("PLANNER", "stub")
    return Tools(catalog, policy, Store())
