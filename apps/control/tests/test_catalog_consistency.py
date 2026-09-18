from sealed_control.loader import experiments_by_id
from sealed_target.faults import CATALOG, MAX_DELAY_MS, MAX_DURATION_S
from sealed_agent.domain import MAX_DELAY_MS as SHARED_MAX_DELAY_MS


def test_independent_target_contract_matches_closed_catalog(client):
    specs = experiments_by_id(client.app.state.catalog)
    assert set(CATALOG) == set(specs) == {"redis_down", "handler_latency", "worker_drop"}
    for fault_id, target_spec in CATALOG.items():
        assert target_spec["params"] == specs[fault_id]["params"]
        assert target_spec["default_duration_s"] == specs[fault_id]["default_duration_s"]
    assert MAX_DELAY_MS == SHARED_MAX_DELAY_MS == 1000
    assert MAX_DURATION_S == client.app.state.policy["max_duration_s"] == 20
