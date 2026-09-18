"""SQLite audit repository; one process owns lifecycle, SQL defends ownership.

Transactions are synchronous and must never span an await. Each public boundary
serializes/deserializes its data, so callers cannot mutate an audit record by
holding a Python reference. Planner diagnostics are separate from run events.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import quote, quote_plus

SCHEMA_VERSION = 1
ACTIVE_STATUSES = ("reserved", "injecting", "unsealed", "cleanup_pending", "recovering")
TERMINAL_STATUSES = {"completed", "resealed", "cancelled"}
_SECRET = ("key", "token", "secret", "password", "authorization", "credential")
_SECRET_ENV = ("UNSEAL_TOKEN", "XAI_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY", "REDIS_PASSWORD")
_SECRET_FILES = ("UNSEAL_TOKEN_FILE", "LLM_API_KEY_FILE", "XAI_API_KEY_FILE", "OPENAI_API_KEY_FILE")


def _secret_values() -> set[str]:
    values = {os.environ[name] for name in _SECRET_ENV if os.environ.get(name)}
    for name in _SECRET_FILES:
        path = os.environ.get(name)
        if path:
            try:
                # Credentials are small; never read arbitrary unbounded files.
                with Path(path).open(encoding="utf-8") as stream:
                    value = stream.read(4097).strip()
                if value and len(value) <= 4096:
                    values.add(value)
            except (OSError, UnicodeError):
                continue
    return values | {quote(value, safe="") for value in values} | {quote_plus(value) for value in values}


def _redact(value: Any, *, known: set[str] | None = None, depth: int = 0) -> Any:
    known = _secret_values() if known is None else known
    if depth > 12:
        return "[depth limited]"
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if any(part in str(key).lower() for part in _SECRET)
            else _redact(item, known=known, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, known=known, depth=depth + 1) for item in value]
    if isinstance(value, BaseException):
        value = f"{type(value).__name__}: {value}"
    if isinstance(value, str):
        for secret in sorted(known, key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        value = re.sub(r"(?i)(https?://|redis://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", value)
        value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9_.~+/=-]+", "Bearer [redacted]", value)
        value = re.sub(r"(?i)((?:api[_-]?key|token|password|secret|authorization)\s*[=:]\s*)[^\s&\"']+", r"\1[redacted]", value)
        return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value)[:8192]
    return value


def _summary(result: Any) -> str:
    if result is None:
        value = "none"
    elif isinstance(result, dict):
        if "verdict" in result:
            value = f"seal {result.get('id')} {result.get('catalog_id')} {result.get('verdict')}"
        elif result.get("id") and result.get("catalog_id"):
            value = f"draft {result.get('id')} {result.get('catalog_id')} {result.get('status')}"
        else:
            value = ",".join(str(key) for key in result)
    elif isinstance(result, list):
        value = f"{len(result)} items"
    else:
        value = str(result)
    return _redact(value)[:240]


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _hash(snapshot: Any) -> str | None:
    return hashlib.sha256(_encode(snapshot).encode()).hexdigest() if snapshot is not None else None


class Store:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(path) if path is not None else ":memory:"
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        self._closed = False
        # TestClient can create the repository on its caller's thread. A short
        # busy timeout bounds contention; production also enforces ProcessOwner.
        self._conn = sqlite3.connect(self.path, timeout=.25, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA recursive_triggers=ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._initialize()

    def _initialize(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self._conn.close()
            raise RuntimeError("repository_schema_newer_than_application")
        self._conn.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY, status TEXT NOT NULL,
                proposal_id TEXT UNIQUE, record_version INTEGER NOT NULL,
                created_at REAL NOT NULL, data TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON drafts((1))
                WHERE status IN ('reserved','injecting','unsealed','cleanup_pending','recovering');
            CREATE TRIGGER IF NOT EXISTS terminal_draft_cannot_restart
                BEFORE UPDATE OF status ON drafts
                WHEN OLD.status IN ('completed','resealed','cancelled') AND NEW.status != OLD.status
                BEGIN SELECT RAISE(ABORT, 'terminal_run_is_immutable'); END;
            CREATE TABLE IF NOT EXISTS seals (
                id TEXT PRIMARY KEY, draft_id TEXT NOT NULL UNIQUE,
                verdict TEXT NOT NULL CHECK(verdict IN ('pass','fail','aborted')),
                created_at REAL NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(draft_id) REFERENCES drafts(id)
            );
            CREATE TRIGGER IF NOT EXISTS seals_no_update BEFORE UPDATE ON seals
                BEGIN SELECT RAISE(ABORT, 'seal_is_immutable'); END;
            CREATE TRIGGER IF NOT EXISTS seals_no_delete BEFORE DELETE ON seals
                BEGIN SELECT RAISE(ABORT, 'seal_is_immutable'); END;
            CREATE TRIGGER IF NOT EXISTS seals_no_replace BEFORE INSERT ON seals
                WHEN EXISTS(SELECT 1 FROM seals WHERE id=NEW.id OR draft_id=NEW.draft_id)
                BEGIN SELECT RAISE(ABORT, 'seal_is_immutable'); END;
            CREATE TABLE IF NOT EXISTS game_days (
                id TEXT PRIMARY KEY, record_version INTEGER NOT NULL,
                created_at REAL NOT NULL, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                run_id TEXT NOT NULL, kind TEXT NOT NULL, ts REAL NOT NULL, details TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES drafts(id)
            );
            CREATE INDEX IF NOT EXISTS events_by_run ON events(run_id, seq);
            CREATE UNIQUE INDEX IF NOT EXISTS one_finalized_event ON events(run_id) WHERE kind='finalized';
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'event_is_immutable'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'event_is_immutable'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_replace BEFORE INSERT ON events
                WHEN EXISTS(SELECT 1 FROM events WHERE id=NEW.id OR seq=NEW.seq
                    OR (NEW.kind='finalized' AND kind='finalized' AND run_id=NEW.run_id))
                BEGIN SELECT RAISE(ABORT, 'event_is_immutable'); END;
            CREATE TABLE IF NOT EXISTS planner_trace (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                tool TEXT NOT NULL, args TEXT NOT NULL, result_summary TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=1;
            COMMIT;
        """)

    @contextmanager
    def transaction(self):
        """Synchronous transaction, nested operations use rollbackable savepoints."""
        with self._lock:
            if self._closed:
                raise RuntimeError("repository_closed")
            nested = self._depth > 0
            savepoint = f"sealed_sp_{self._depth}"
            self._conn.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint}" if nested else "COMMIT")
            except BaseException:
                if nested:
                    self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    self._conn.execute("ROLLBACK")
                raise
            finally:
                self._depth -= 1

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                if self._depth:
                    raise RuntimeError("cannot_close_active_transaction")
                self._conn.close()
                self._closed = True

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{secrets.token_hex(16)}"

    def _get(self, table: str, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(f"SELECT data FROM {table} WHERE id=?", (record_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def _list(self, table: str) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(row["data"]) for row in self._conn.execute(f"SELECT data FROM {table} ORDER BY created_at, rowid")]

    def put_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        with self.transaction():
            existing = self.get_draft(draft["id"])
            record = deepcopy(draft)
            record["record_version"] = (existing or {}).get("record_version", 0) + 1
            record.setdefault("created_at", time.time())
            # Run identity and experiment inputs cannot change after creation.
            if existing:
                for key in ("catalog_id", "environment", "target", "duration_s", "params", "hypothesis", "source", "proposal_id", "created_at"):
                    if record.get(key) != existing.get(key):
                        raise ValueError(f"draft_identity_field_changed:{key}")
            self._conn.execute(
                "INSERT INTO drafts(id,status,proposal_id,record_version,created_at,data) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, record_version=excluded.record_version, data=excluded.data",
                (record["id"], record["status"], record.get("proposal_id"), record["record_version"], record["created_at"], _encode(record)),
            )
            if existing is None:
                self.add_event(record["id"], "created", {
                    "source": record.get("source", "manual"), "catalog_id": record["catalog_id"],
                    "target": record["target"], "duration_s": record["duration_s"],
                    "params": record.get("params"), "hypothesis": record.get("hypothesis"),
                })
            return deepcopy(record)

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        return self._get("drafts", draft_id)

    def list_drafts(self) -> list[dict[str, Any]]:
        # Admission must inspect all active runs; HTTP lists can bound separately.
        return self._list("drafts")

    @staticmethod
    def _page(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("invalid_query_limit")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1000000:
            raise ValueError("invalid_query_offset")
        return limit, offset

    def list_draft_summaries(self, *, limit: int = 100, offset: int = 0, q: str = "", status: str | None = None) -> list[dict[str, Any]]:
        """Newest page, returned oldest-first within the page for compatibility.

        SQLite projects out large evidence/config snapshots before decoding;
        historical run count therefore does not expand the HTTP response.
        Search uses instr rather than LIKE so operator input is always literal.
        """
        limit, offset = self._page(limit, offset)
        with self._lock:
            rows = self._conn.execute(
                "SELECT json_remove(data,'$.evidence','$.catalog_snapshot','$.policy_snapshot') AS summary "
                "FROM drafts WHERE (? IS NULL OR status=?) AND "
                "(?='' OR instr(lower(id || ' ' || json_extract(data,'$.catalog_id') || ' ' || coalesce(json_extract(data,'$.source'),'')), lower(?))>0) "
                "ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?",
                (status, status, q, q, limit, offset),
            )
            return list(reversed([json.loads(row["summary"]) for row in rows]))

    def list_active(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM drafts WHERE status IN (?,?,?,?,?) ORDER BY created_at", ACTIVE_STATUSES)
            return [json.loads(row["data"]) for row in rows]

    def add_seal(self, *, draft: dict[str, Any], verdict: str, reason: str | None = None, evidence: dict | None = None) -> dict[str, Any]:
        with self.transaction():
            existing = self.seal_for_run(draft["id"])
            if existing:
                return existing
            if verdict not in {"pass", "fail", "aborted"}:
                raise ValueError("invalid_verdict")
            seal = {
                "id": self.new_id("s"), "draft_id": draft["id"], "run_id": draft["id"],
                "schema_version": SCHEMA_VERSION, "record_version": 1,
                "catalog_id": draft["catalog_id"], "environment": draft["environment"],
                "target": draft["target"], "duration_s": draft["duration_s"],
                "source": draft.get("source", "manual"), "hypothesis": draft.get("hypothesis"),
                "params": draft.get("params"), "effective_params": draft.get("params"),
                "reason": _redact(reason), "evidence": _redact(evidence), "verdict": verdict,
                "catalog_version": draft.get("catalog_version"), "policy_version": draft.get("policy_version"),
                "catalog_hash": draft.get("catalog_hash") or _hash(draft.get("catalog_snapshot")),
                "policy_hash": draft.get("policy_hash") or _hash(draft.get("policy_snapshot")),
                "catalog_snapshot": draft.get("catalog_snapshot"), "policy_snapshot": draft.get("policy_snapshot"),
                "approved_at": draft.get("approved_at"), "unsealed_at": draft.get("unsealed_at"),
                "abort_requested_at": draft.get("abort_requested_at"),
                "cleanup_confirmed_at": draft.get("cleanup_confirmed_at"), "completed_at": draft.get("completed_at"),
                "created_at": time.time(),
            }
            self._conn.execute("INSERT INTO seals(id,draft_id,verdict,created_at,data) VALUES(?,?,?,?,?)", (seal["id"], seal["draft_id"], verdict, seal["created_at"], _encode(seal)))
            return deepcopy(seal)

    def finish_run(self, draft: dict[str, Any], verdict: str, reason: str | None = None, evidence: dict | None = None) -> dict[str, Any]:
        with self.transaction():
            existing = self.seal_for_run(draft["id"])
            if existing:
                return existing
            terminal = deepcopy(draft)
            terminal["status"] = "resealed" if verdict == "aborted" else "completed"
            terminal.setdefault("completed_at", time.time())
            terminal = self.put_draft(terminal)
            seal = self.add_seal(draft=terminal, verdict=verdict, reason=reason, evidence=evidence)
            self.add_event(terminal["id"], "finalized", {"seal_id": seal["id"], "verdict": verdict, "reason": reason})
            return seal

    def seal_for_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM seals WHERE draft_id=?", (run_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def add_event(self, run_id: str, kind: str, details: dict | None = None) -> dict[str, Any]:
        with self.transaction():
            event = {"id": self.new_id("e"), "run_id": run_id, "kind": kind, "ts": time.time(), "details": _redact(details or {})}
            cursor = self._conn.execute("INSERT INTO events(id,run_id,kind,ts,details) VALUES(?,?,?,?,?)", (event["id"], run_id, kind, event["ts"], _encode(event["details"])))
            event["seq"] = cursor.lastrowid
            return deepcopy(event)

    def list_events(self, run_id: str, *, limit: int | None = None, after_seq: int = 0) -> list[dict[str, Any]]:
        if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
            raise ValueError("invalid_event_cursor")
        sql = "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq"
        args: tuple = (run_id, after_seq)
        if limit is not None:
            self._page(limit, 0)
            sql += " LIMIT ?"
            args += (limit,)
        with self._lock:
            return [{**dict(row), "details": json.loads(row["details"])} for row in self._conn.execute(sql, args)]

    def get_seal(self, seal_id: str) -> dict[str, Any] | None:
        return self._get("seals", seal_id)

    def list_seals(self) -> list[dict[str, Any]]:
        return self._list("seals")

    def get_latest_seal(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM seals ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
            return json.loads(row["data"]) if row else None

    def list_seal_summaries(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        limit, offset = self._page(limit, offset)
        with self._lock:
            rows = self._conn.execute(
                "SELECT json_remove(data,'$.evidence','$.catalog_snapshot','$.policy_snapshot') AS summary "
                "FROM seals ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?", (limit, offset),
            )
            return list(reversed([json.loads(row["summary"]) for row in rows]))

    def put_game_day(self, game_day: dict[str, Any]) -> dict[str, Any]:
        with self.transaction():
            existing = self.get_game_day(game_day["id"])
            record = deepcopy(game_day)
            record["record_version"] = (existing or {}).get("record_version", 0) + 1
            record.setdefault("created_at", time.time())
            self._conn.execute(
                "INSERT INTO game_days(id,record_version,created_at,data) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET record_version=excluded.record_version,data=excluded.data",
                (record["id"], record["record_version"], record["created_at"], _encode(record)),
            )
            return deepcopy(record)

    def get_game_day(self, game_day_id: str) -> dict[str, Any] | None:
        return self._get("game_days", game_day_id)

    def list_game_days(self) -> list[dict[str, Any]]:
        return self._list("game_days")

    def set_planner(self, name: str) -> None:
        with self.transaction():
            self._conn.execute("INSERT INTO metadata(key,value) VALUES('planner',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_encode(_redact(name)),))

    def append_trace(self, tool: str, args: dict[str, Any] | None, result: Any) -> None:
        with self.transaction():
            args = _redact(args or {})
            encoded = _encode(args)
            if len(encoded.encode()) > 16384:
                encoded = _encode({"summary": "[arguments exceed diagnostic limit]"})
            self._conn.execute("INSERT INTO planner_trace(ts,tool,args,result_summary) VALUES(?,?,?,?)", (time.time(), _redact(tool), encoded, _summary(result)))
            self._conn.execute("DELETE FROM planner_trace WHERE seq NOT IN (SELECT seq FROM planner_trace ORDER BY seq DESC LIMIT 200)")

    def agent_snapshot(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM metadata WHERE key='planner'").fetchone()
            trace = [{"seq": item["seq"], "ts": item["ts"], "tool": item["tool"], "args_redacted": json.loads(item["args"]), "result_summary": item["result_summary"]} for item in self._conn.execute("SELECT * FROM planner_trace ORDER BY seq")]
            return {"planner": json.loads(row["value"]) if row else "stub", "last_tool": trace[-1]["tool"] if trace else "", "trace": trace}
