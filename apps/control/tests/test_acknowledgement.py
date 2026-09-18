import time
from types import SimpleNamespace

import pytest

from sealed_control.target import TargetAdapter


@pytest.mark.parametrize("change", [
    {"until": float("nan")}, {"until": float("inf")}, {"until": True},
    {"until": time.time() + 1000}, {"status": "cleanup_pending"},
    {"run_id": "other"}, {"params": {"delay_ms": 999}}, {"id": "worker_drop"},
])
def test_acknowledgement_must_match_bounded_authorized_run(change):
    draft = {"id": "d-1", "catalog_id": "handler_latency", "params": {"delay_ms": 300}, "duration_s": 5}
    ack = {"run_id": "d-1", "id": "handler_latency", "params": draft["params"], "duration_s": 5, "until": time.time() + 5, "status": "active"}
    adapter = TargetAdapter(SimpleNamespace())
    assert adapter.validate_ack(ack, draft) == ack
    with pytest.raises(RuntimeError, match="invalid_target_ack"):
        adapter.validate_ack({**ack, **change}, draft)
