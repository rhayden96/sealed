from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
import threading

import pytest

from sealed_control.store import Store


def draft(store, **changes):
    return {
        "id": store.new_id("d"), "catalog_id": "handler_latency", "target": "api",
        "environment": "demo", "duration_s": 5, "params": {"delay_ms": 300},
        "hypothesis": {"slo": {"p95_ms": 500, "error_rate": .01}, "must": ["latency_recovers_after_reseal"]},
        "status": "draft", "source": "manual", "approved": False, "created_at": 100,
        **changes,
    }


def test_restart_retains_all_records_versions_and_correlations(tmp_path):
    path = tmp_path / "audit.db"
    store = Store(path)
    record = store.put_draft(draft(store))
    record.update(status="approved", approved=True)
    record = store.put_draft(record)
    assert record["record_version"] == 2
    store.add_event(record["id"], "approved")
    day = store.put_game_day({"id": "day-1", "steps": [{"draft_id": record["id"]}], "status": "active"})
    store.set_planner("stub")
    store.append_trace("get_run", {}, record)
    seal = store.finish_run(record, "aborted", "operator_abort", {"sample_count": 3})
    before_events = store.list_events(record["id"])
    store.close()

    reopened = Store(path)
    assert reopened.get_draft(record["id"])["status"] == "resealed"
    assert reopened.get_draft(record["id"])["record_version"] == 3
    assert reopened.get_game_day(day["id"]) == day
    assert reopened.get_seal(seal["id"]) == seal
    assert reopened.list_events(record["id"]) == before_events
    assert [item["kind"] for item in before_events] == ["created", "approved", "finalized"]
    assert reopened.agent_snapshot()["last_tool"] == "get_run"
    assert reopened.agent_snapshot()["planner"] == "stub"
    reopened.close()


@pytest.mark.parametrize("status", ["reserved", "injecting", "unsealed", "cleanup_pending", "recovering"])
def test_restart_preserves_pending_owner_and_database_rejects_second_owner(tmp_path, status):
    path = tmp_path / "owner.db"
    first = Store(path)
    owner = first.put_draft(draft(first, status=status))
    second = Store(path)
    assert second.list_active() == [owner]
    other = second.put_draft(draft(second))
    other["status"] = "reserved"
    with pytest.raises(sqlite3.IntegrityError):
        second.put_draft(other)
    assert second.get_draft(other["id"])["status"] == "draft"
    assert first.list_active() == [owner]
    first.close()
    second.close()


def test_two_connections_cannot_claim_concurrent_admission(tmp_path):
    path = tmp_path / "race.db"
    first, second = Store(path), Store(path)
    drafts = [first.put_draft(draft(first)), second.put_draft(draft(second))]
    gate = threading.Barrier(2)

    def reserve(store, record):
        gate.wait()
        record["status"] = "reserved"
        try:
            store.put_draft(record)
            return "admitted"
        except sqlite3.IntegrityError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, store, record) for store, record in zip([first, second], drafts)]
        assert sorted(item.result() for item in futures) == ["admitted", "conflict"]
    assert len(first.list_active()) == 1
    first.close()
    second.close()


def test_terminal_run_cannot_reacquire_ownership():
    store = Store()
    record = store.put_draft(draft(store))
    store.finish_run(record, "aborted", "operator_abort")
    record = store.get_draft(record["id"])
    record["status"] = "reserved"
    with pytest.raises(sqlite3.IntegrityError, match="terminal_run_is_immutable"):
        store.put_draft(record)
    assert store.list_active() == []


def test_seal_snapshots_are_immutable_and_include_authorization_inputs(tmp_path):
    store = Store(tmp_path / "sealed.db")
    catalog = {"version": 1, "experiments": [{"id": "handler_latency"}]}
    policy = {"version": 1, "max_duration_s": 20}
    record = store.put_draft(draft(store, catalog_version=1, policy_version=1, catalog_snapshot=catalog, policy_snapshot=policy))
    evidence = {"during": {"samples": [{"p95_ms": 321}]} }
    seal = store.finish_run(record, "pass", "hypothesis_satisfied", evidence)
    original = deepcopy(seal)
    record["hypothesis"]["must"].clear()
    evidence["during"]["samples"].clear()
    catalog["experiments"].clear()
    policy["max_duration_s"] = 100
    seal["hypothesis"]["slo"]["p95_ms"] = -1
    retrieved = store.get_seal(original["id"])
    retrieved["params"].clear()
    assert store.get_seal(original["id"]) == original
    assert original["effective_params"] == {"delay_ms": 300}
    assert len(original["catalog_hash"]) == len(original["policy_hash"]) == 64
    assert original["schema_version"] == original["record_version"] == 1
    assert original["catalog_snapshot"]["experiments"]


def test_sql_cannot_update_delete_or_replace_seals_or_events(tmp_path):
    path = tmp_path / "immutable.db"
    store = Store(path)
    record = store.put_draft(draft(store))
    seal = store.finish_run(record, "aborted", "operator_abort")
    connection = sqlite3.connect(path)
    attempts = [
        ("UPDATE seals SET verdict='pass' WHERE id=?", (seal["id"],)),
        ("DELETE FROM seals WHERE id=?", (seal["id"],)),
        ("INSERT OR REPLACE INTO seals(id,draft_id,verdict,created_at,data) VALUES(?,?,?,?,?)", (seal["id"], record["id"], "pass", 1, "{}")),
        ("UPDATE events SET kind='fabricated' WHERE run_id=?", (record["id"],)),
        ("DELETE FROM events WHERE run_id=?", (record["id"],)),
    ]
    for sql, args in attempts:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(sql, args)
        connection.rollback()
    assert store.get_seal(seal["id"]) == seal
    connection.close()
    store.close()


def test_finish_is_atomic_unique_and_idempotent(monkeypatch):
    store = Store()
    record = store.put_draft(draft(store, status="cleanup_pending"))
    original_add_event = store.add_event

    def fail_finalized(*args, **kwargs):
        if args[1] == "finalized":
            raise RuntimeError("simulated_disk_failure")
        return original_add_event(*args, **kwargs)

    monkeypatch.setattr(store, "add_event", fail_finalized)
    with pytest.raises(RuntimeError, match="simulated_disk_failure"):
        store.finish_run(record, "aborted", "operator_abort")
    assert store.get_draft(record["id"])["status"] == "cleanup_pending"
    assert store.seal_for_run(record["id"]) is None
    assert [event["kind"] for event in store.list_events(record["id"])] == ["created"]
    monkeypatch.setattr(store, "add_event", original_add_event)
    first = store.finish_run(record, "aborted", "operator_abort")
    second = store.finish_run(record, "pass", "changed_verdict")
    assert first == second
    assert len(store.list_seals()) == 1
    assert len([item for item in store.list_events(record["id"]) if item["kind"] == "finalized"]) == 1


def test_outer_transaction_rolls_back_drafts_days_events_together():
    store = Store()
    with pytest.raises(ValueError, match="later_step_invalid"):
        with store.transaction():
            first = store.put_draft(draft(store))
            store.put_game_day({"id": "day-1", "steps": [{"draft_id": first["id"]}]})
            raise ValueError("later_step_invalid")
    assert store.list_drafts() == store.list_game_days() == []
    assert store.list_events(first["id"]) == []


def test_nested_savepoint_rolls_back_failed_step_without_poisoning_outer_transaction():
    store = Store()
    with store.transaction():
        owner = store.put_draft(draft(store, status="reserved"))
        with pytest.raises(sqlite3.IntegrityError):
            with store.transaction():
                store.put_draft(draft(store, status="reserved"))
        other = store.put_draft(draft(store))
    assert len(store.list_drafts()) == 2
    assert store.list_active() == [owner]
    assert store.get_draft(other["id"])["status"] == "draft"


def test_returned_drafts_days_events_and_trace_are_copies():
    store = Store()
    record = store.put_draft(draft(store))
    record["params"].clear()
    listed = store.list_drafts()
    listed[0]["params"].clear()
    assert store.get_draft(record["id"])["params"] == {"delay_ms": 300}
    day = store.put_game_day({"id": "day-1", "steps": [{"draft_id": record["id"]}]})
    day["steps"].clear()
    assert store.get_game_day("day-1")["steps"]
    events = store.list_events(record["id"])
    events[0]["details"]["params"].clear()
    assert store.list_events(record["id"])[0]["details"]["params"]
    store.append_trace("read", {"nested": ["value"]}, "result")
    store.agent_snapshot()["trace"][0]["args_redacted"]["nested"].clear()
    assert store.agent_snapshot()["trace"][0]["args_redacted"]["nested"] == ["value"]


def test_trace_is_bounded_but_authoritative_events_are_retained():
    store = Store()
    record = store.put_draft(draft(store))
    for index in range(210):
        store.append_trace("get_run", {"index": index}, record)
        store.add_event(record["id"], "observation", {"index": index})
    trace = store.agent_snapshot()["trace"]
    events = store.list_events(record["id"])
    assert len(trace) == 200
    assert trace[0]["args_redacted"]["index"] == 10
    assert len(events) == 211
    assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)


def test_redacts_actual_secret_values_errors_urls_and_credential_files(monkeypatch, tmp_path):
    token_path = tmp_path / "credential"
    token_path.write_text("private-file-token", encoding="utf-8")
    monkeypatch.setenv("UNSEAL_TOKEN_FILE", str(token_path))
    monkeypatch.setenv("XAI_API_KEY", "private-xai-value")
    store = Store()
    record = store.put_draft(draft(store))
    diagnostic = {
        "message": "failed private-xai-value and private-file-token",
        "url": "https://user:hidden-password@provider.example/path?api_key=unknown-key&x=ok",
        "nested": ["Bearer raw-bearer-value"], "credential": "hidden",
    }
    store.add_event(record["id"], "cleanup_failed", diagnostic)
    store.append_trace("get_seal", diagnostic, RuntimeError("private-xai-value"))
    output = json.dumps([store.list_events(record["id"]), store.agent_snapshot()])
    for forbidden in ["private-xai-value", "private-file-token", "hidden-password", "unknown-key", "raw-bearer-value"]:
        assert forbidden not in output
    assert "[redacted]" in output
    assert "cleanup_failed" in output


def test_repository_rejects_future_schema(tmp_path):
    path = tmp_path / "future.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=999")
    connection.close()
    with pytest.raises(RuntimeError, match="repository_schema_newer"):
        Store(path)


def test_bounded_queries_preserve_selection_metadata_and_detail_evidence():
    store = Store()
    ids = []
    for index in range(6):
        record = store.put_draft(draft(store, created_at=index, evidence={"during": [index]}, catalog_snapshot={"version": 1}, policy_snapshot={"version": 1}))
        ids.append(record["id"])
        store.finish_run(record, "aborted", "operator_abort", {"during": [index]})
    page = store.list_draft_summaries(limit=2, offset=1)
    assert [item["id"] for item in page] == ids[3:5]
    assert all("evidence" not in item and "policy_snapshot" not in item for item in page)
    assert page[0]["params"] == {"delay_ms": 300}
    assert store.get_draft(ids[3])["evidence"] == {"during": [3]}
    assert store.list_draft_summaries(q="handler_latency", status="resealed", limit=2)
    assert store.list_draft_summaries(q="%") == []
    assert store.list_draft_summaries(status="unsealed") == []
    seals = store.list_seal_summaries(limit=2)
    assert [item["draft_id"] for item in seals] == ids[-2:]
    assert "evidence" not in seals[0]
    assert store.get_latest_seal()["draft_id"] == ids[-1]
    first = store.list_events(ids[0], limit=1)
    second = store.list_events(ids[0], limit=1, after_seq=first[0]["seq"])
    assert first[0]["kind"] == "created"
    assert second[0]["kind"] == "finalized"
    assert store.list_events(ids[0], limit=1, after_seq=second[0]["seq"]) == []


@pytest.mark.parametrize("limit", [0, -1, 1001, True, "5"])
def test_repository_query_limits_are_bounded(limit):
    store = Store()
    with pytest.raises(ValueError, match="invalid_query_limit"):
        store.list_draft_summaries(limit=limit)
