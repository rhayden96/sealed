from copy import deepcopy

import pytest
from pydantic import ValidationError

from sealed_agent.domain import DraftIn, construct_draft, validate_catalog, validate_policy
from sealed_control.store import Store


def body(**changes):
    return {"catalog_id": "handler_latency", "target": "api", "environment": "demo", **changes}


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), float("-inf"), True, "5"])
def test_malformed_duration_rejected(value):
    with pytest.raises(ValidationError):
        DraftIn.model_validate(body(duration_s=value))


def test_well_formed_policy_denial_is_still_a_draft(catalog):
    store = Store()
    draft = construct_draft(store, catalog, **body(environment="prod", duration_s=21))
    assert draft["status"] == "draft"
    assert not draft["approved"]
    assert draft["environment"] == "prod"
    assert draft["duration_s"] == 21


@pytest.mark.parametrize("changes", [
    {"params": {"delay_ms": -1}}, {"params": {"delay_ms": 1001}},
    {"params": {"delay_ms": True}}, {"params": {"delay_ms": "300"}},
    {"params": {"delay_ms": float("nan")}}, {"params": {"duration_s": 100}},
    {"target": "worker"}, {"catalog_id": "fourth_fault"}, {"unexpected": "yes"},
    {"hypothesis": {"slo": {"p95_ms": 500, "error_rate": .1}, "must": []}},
    {"hypothesis": {"slo": {"p95_ms": 500, "error_rate": .1}, "must": ["fail_closed_on_redis_loss"]}},
    {"hypothesis": {"slo": {"p95_ms": 500, "error_rate": 2}, "must": ["latency_recovers_after_reseal"]}},
    {"hypothesis": {"slo": {"p95_ms": 500, "error_rate": .1}, "must": ["invented_assertion"]}},
])
def test_fault_contract_rejected(changes):
    with pytest.raises(ValidationError):
        DraftIn.model_validate(body(**changes))


@pytest.mark.parametrize("rate", [-.1, 1.1, True, "0.2", float("inf")])
def test_drop_rate_is_bounded(rate):
    with pytest.raises(ValidationError):
        DraftIn.model_validate(body(catalog_id="worker_drop", target="worker", params={"drop_rate": rate}))


def test_constructor_validates_before_writing_and_copies_defaults(catalog):
    store = Store()
    with pytest.raises(ValueError):
        construct_draft(store, catalog, **body(params={"unsafe": 1}))
    assert store.list_drafts() == []
    original = deepcopy(catalog)
    draft = construct_draft(store, catalog, **body())
    draft["hypothesis"]["must"].clear()
    draft["params"]["delay_ms"] = 0
    assert catalog == original


def test_duplicate_catalog_and_contradictory_policy_fail_startup(catalog, policy):
    catalog["experiments"][2] = deepcopy(catalog["experiments"][1])
    with pytest.raises(ValueError):
        validate_catalog(catalog)
    for changes in [
        {"max_duration_s": 21}, {"max_concurrent_unsealed": 2},
        {"environment_allowlist": ["prod"]}, {"catalog_id_required": False},
        {"max_duration_s": 2}, {"unknown": True},
        {"auto_unseal": {**policy["auto_unseal"], "catalog_ids": ["worker_drop"]}},
    ]:
        with pytest.raises(ValueError):
            validate_policy({**policy, **changes})


def test_same_proposal_identity_is_idempotent(catalog):
    store = Store()
    first = construct_draft(store, catalog, **body(), proposal_id="proposal-1", source="agent")
    second = construct_draft(store, catalog, **body(), proposal_id="proposal-1", source="agent")
    assert first["id"] == second["id"]
    assert len(store.list_drafts()) == 1
    with pytest.raises(ValueError, match="proposal_identity_conflict"):
        construct_draft(store, catalog, **body(duration_s=2), proposal_id="proposal-1", source="agent")
