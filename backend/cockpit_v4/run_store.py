"""
Durable runs, events, messages, artifacts, leases and idempotency.

Why this is SQLite with WAL rather than a dict
-----------------------------------------------
A run that exists only in a worker's memory disappears when the worker does,
and the user is left with a spinner that never resolves and a paid provider
call nobody can account for. Every fact that a later decision depends on --
the run's state and version, the event sequence, the exact submitted code,
the result artifacts, the usage reservations, the worker lease -- is committed
here before the next side effect happens.

WAL is on because the API process reads the same file the worker writes, and
a reader that blocks behind a writer turns a status poll into a timeout.

`STORAGE_UNAVAILABLE` is a real terminal outcome. If this store cannot commit,
the caller does NOT proceed to the next paid operation and does NOT claim the
work was accepted -- see `orchestration` and `routes`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.cockpit_v4.events import Event
from backend.cockpit_v4.states import TERMINAL_STATES

SCHEMA_VERSION = 1


class StorageUnavailable(RuntimeError):
    """The durable store could not commit. Never swallowed, never assumed."""


class IdempotencyConflict(RuntimeError):
    """Same key, different body. A typed conflict, not a silent second run."""


class TerminalAlready(RuntimeError):
    """The run already settled. A late writer cannot overwrite the outcome."""


class LeaseLost(RuntimeError):
    """This worker no longer owns the run. Its writes are fenced off."""


_DDL = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  question TEXT NOT NULL,
  mode TEXT NOT NULL,
  release_id TEXT NOT NULL,
  ui_filters TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0,
  error_code TEXT NOT NULL DEFAULT '',
  error_id TEXT NOT NULL DEFAULT '',
  operation TEXT NOT NULL DEFAULT '',
  final_response TEXT NOT NULL DEFAULT '',
  budget TEXT NOT NULL DEFAULT '{}',
  startup_sha TEXT NOT NULL DEFAULT '',
  route TEXT NOT NULL DEFAULT 'cockpit_v4',
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  delivered_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deadline_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runs_thread ON runs(thread_id, created_at);
CREATE INDEX IF NOT EXISTS runs_state ON runs(state);

CREATE TABLE IF NOT EXISTS events (
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  payload TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS messages (
  run_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  PRIMARY KEY (run_id, ordinal)
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  release_id TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '{}',
  columns TEXT NOT NULL DEFAULT '[]',
  row_count INTEGER NOT NULL DEFAULT 0,
  body TEXT NOT NULL,
  code_digest TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts(run_id);

CREATE TABLE IF NOT EXISTS submissions (
  submission_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  round INTEGER NOT NULL,
  payload TEXT NOT NULL,
  status TEXT NOT NULL,
  no_progress_key TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS submissions_run ON submissions(run_id);

CREATE TABLE IF NOT EXISTS reservations (
  reservation_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  reserved_usd REAL NOT NULL,
  settled_usd REAL,
  uncertain INTEGER NOT NULL DEFAULT 0,
  usage TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reservations_run ON reservations(run_id);

CREATE TABLE IF NOT EXISTS idempotency (
  principal_id TEXT NOT NULL,
  key TEXT NOT NULL,
  body_digest TEXT NOT NULL,
  run_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (principal_id, key)
);

CREATE TABLE IF NOT EXISTS leases (
  run_id TEXT PRIMARY KEY,
  worker_id TEXT NOT NULL,
  fence INTEGER NOT NULL,
  heartbeat_at TEXT NOT NULL,
  claimed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox (
  run_id TEXT PRIMARY KEY,
  claimed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
  thread_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
  turn_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_thread ON turns(thread_id, ordinal);

CREATE TABLE IF NOT EXISTS summaries (
  thread_id TEXT PRIMARY KEY,
  covered_through_ordinal INTEGER NOT NULL,
  body TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS details (
  detail_ref TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class RunRecord:
    run_id: str
    thread_id: str
    tenant_id: str
    principal_id: str
    question: str
    mode: str
    release_id: str
    state: str
    version: int
    error_code: str = ""
    error_id: str = ""
    operation: str = ""
    final_response: dict[str, Any] | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    ui_filters: dict[str, Any] = field(default_factory=dict)
    startup_sha: str = ""
    route: str = "cockpit_v4"
    cancel_requested: bool = False
    delivered_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    deadline_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "thread_id": self.thread_id,
            "mode": self.mode, "release_id": self.release_id,
            "state": self.state, "version": self.version,
            "error_code": self.error_code, "error_id": self.error_id,
            "operation": self.operation, "final_response": self.final_response,
            "budget": self.budget, "route": self.route,
            "cancel_requested": self.cancel_requested,
            "delivered_at": self.delivered_at, "created_at": self.created_at,
            "updated_at": self.updated_at, "deadline_at": self.deadline_at}


class RunStore:
    """The durable store. One SQLite file, WAL, thread-safe connections."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._local = threading.local()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._shared: sqlite3.Connection | None = None
        if self.path == ":memory:":
            # One shared connection: a per-thread :memory: database would be a
            # different database per thread, which is not a store.
            self._shared = sqlite3.connect(
                ":memory:", check_same_thread=False, timeout=30.0)
            self._shared.row_factory = sqlite3.Row
            self._guard = threading.RLock()
        self._migrate()

    # -- connections ----------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """A usable connection, or `StorageUnavailable`.

        Wrapped deliberately: a corrupt file, a revoked mount or a full disk
        must reach the caller as the TYPED outcome the state machine declares,
        so the run stops with STORAGE_UNAVAILABLE and does not launch the next
        paid operation. A raw sqlite error here would surface as an
        unclassified internal failure and send an operator to the wrong place.
        """
        if self._shared is not None:
            return self._shared
        conn = getattr(self._local, "conn", None)
        if conn is None:
            try:
                conn = sqlite3.connect(self.path, timeout=30.0,
                                       isolation_level=None)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=30000")
            except sqlite3.Error as exc:
                raise StorageUnavailable(
                    f"the V4 state database at {self.path} is not usable: "
                    f"{exc}") from exc
            self._local.conn = conn
        return conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        lock = getattr(self, "_guard", None)
        if lock is not None:
            lock.acquire()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise StorageUnavailable(str(exc)) from exc
        finally:
            if lock is not None:
                lock.release()

    def _migrate(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_DDL)
            if self._shared is not None:
                conn.commit()
        except sqlite3.Error as exc:
            raise StorageUnavailable(
                f"the V4 state database could not be prepared: {exc}") from exc

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- threads --------------------------------------------------------

    def create_thread(self, *, tenant_id: str, principal_id: str) -> str:
        """A server-generated conversation id. Never a global constant.

        V3 shipped a hard-coded `cockpit-web` thread, which is one history
        shared by every user and every tab.
        """
        thread_id = f"th-{uuid.uuid4().hex}"
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO threads(thread_id, tenant_id, principal_id, "
                "created_at) VALUES (?,?,?,?)",
                (thread_id, tenant_id, principal_id, _now()))
        return thread_id

    def run_for_key(self, principal_id: str, key: str
                    ) -> tuple[RunRecord | None, str]:
        """The run a previous request with this key created, if any.

        Intake consults this BEFORE the concurrency check: a retry of the
        same request is the same run, and refusing it as "already running"
        would turn a dropped acceptance response into an error the caller
        cannot resolve.
        """
        if not key:
            return None, ""
        conn = self._connect()
        row = conn.execute(
            "SELECT run_id, body_digest FROM idempotency "
            "WHERE principal_id=? AND key=?",
            (principal_id, key)).fetchone()
        if row is None:
            return None, ""
        return self._read_run(conn, row["run_id"]), str(row["body_digest"])

    def thread_owner(self, thread_id: str) -> tuple[str, str] | None:
        row = self._connect().execute(
            "SELECT tenant_id, principal_id FROM threads WHERE thread_id=?",
            (thread_id,)).fetchone()
        return (row["tenant_id"], row["principal_id"]) if row else None

    # -- runs -----------------------------------------------------------

    def accept_run(self, *, thread_id: str, tenant_id: str,
                   principal_id: str, question: str, mode: str,
                   release_id: str, ui_filters: dict[str, Any],
                   idempotency_key: str, body_digest: str,
                   startup_sha: str, deadline_at: str) -> tuple[RunRecord, bool]:
        """Persist the run AND its outbox row in one transaction.

        Returning `(record, created)`. A lost HTTP acceptance response must
        not create a second paid run, so a repeated key with the same body
        returns the same run and `created=False`.
        """
        with self._tx() as conn:
            if idempotency_key:
                row = conn.execute(
                    "SELECT body_digest, run_id FROM idempotency "
                    "WHERE principal_id=? AND key=?",
                    (principal_id, idempotency_key)).fetchone()
                if row is not None:
                    if row["body_digest"] != body_digest:
                        raise IdempotencyConflict(
                            "This idempotency key was already used for a "
                            "different request.")
                    existing = self._read_run(conn, row["run_id"])
                    if existing is not None:
                        return existing, False

            run_id = f"run-{uuid.uuid4().hex}"
            now = _now()
            conn.execute(
                "INSERT INTO runs(run_id, thread_id, tenant_id, principal_id,"
                " question, mode, release_id, ui_filters, state, version,"
                " startup_sha, created_at, updated_at, deadline_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, thread_id, tenant_id, principal_id, question, mode,
                 release_id, json.dumps(ui_filters), "ACCEPTED", 0,
                 startup_sha, now, now, deadline_at))
            conn.execute(
                "INSERT INTO outbox(run_id, claimed, created_at) "
                "VALUES (?,0,?)", (run_id, now))
            if idempotency_key:
                conn.execute(
                    "INSERT INTO idempotency(principal_id, key, body_digest,"
                    " run_id, created_at) VALUES (?,?,?,?,?)",
                    (principal_id, idempotency_key, body_digest, run_id, now))
            record = self._read_run(conn, run_id)
        assert record is not None
        return record, True

    @staticmethod
    def _read_run(conn: sqlite3.Connection, run_id: str) -> RunRecord | None:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?",
                           (run_id,)).fetchone()
        if row is None:
            return None
        return RunRecord(
            run_id=row["run_id"], thread_id=row["thread_id"],
            tenant_id=row["tenant_id"], principal_id=row["principal_id"],
            question=row["question"], mode=row["mode"],
            release_id=row["release_id"], state=row["state"],
            version=int(row["version"]), error_code=row["error_code"],
            error_id=row["error_id"], operation=row["operation"],
            final_response=(json.loads(row["final_response"])
                            if row["final_response"] else None),
            budget=json.loads(row["budget"] or "{}"),
            ui_filters=json.loads(row["ui_filters"] or "{}"),
            startup_sha=row["startup_sha"], route=row["route"],
            cancel_requested=bool(row["cancel_requested"]),
            delivered_at=row["delivered_at"], created_at=row["created_at"],
            updated_at=row["updated_at"], deadline_at=row["deadline_at"])

    def get_run(self, run_id: str) -> RunRecord | None:
        return self._read_run(self._connect(), run_id)

    def update_state(self, run_id: str, *, expect_version: int, state: str,
                     operation: str = "", budget: dict[str, Any] | None = None,
                     error_code: str = "", error_id: str = "",
                     final_response: dict[str, Any] | None = None,
                     terminal: bool = False) -> RunRecord:
        """Compare-and-swap on `version`. A stale writer is refused.

        This is the fence. A worker whose lease expired, or a late provider
        callback, holds an old version and cannot overwrite a newer terminal
        state with its own.
        """
        with self._tx() as conn:
            row = conn.execute(
                "SELECT version, state FROM runs WHERE run_id=?",
                (run_id,)).fetchone()
            if row is None:
                raise StorageUnavailable(f"run {run_id} is not stored")
            if int(row["version"]) != int(expect_version):
                raise LeaseLost(
                    f"run {run_id} moved to version {row['version']} while "
                    f"this writer held {expect_version}")
            if row["state"] in TERMINAL_STATES and not terminal:
                raise TerminalAlready(
                    f"run {run_id} already settled as {row['state']}")
            if row["state"] in TERMINAL_STATES and terminal:
                raise TerminalAlready(
                    f"run {run_id} already settled as {row['state']}")
            conn.execute(
                "UPDATE runs SET state=?, version=version+1, operation=?,"
                " budget=COALESCE(?, budget), error_code=?, error_id=?,"
                " final_response=COALESCE(?, final_response), updated_at=?"
                " WHERE run_id=?",
                (state, operation,
                 json.dumps(budget) if budget is not None else None,
                 error_code, error_id,
                 json.dumps(final_response) if final_response is not None
                 else None, _now(), run_id))
            record = self._read_run(conn, run_id)
        assert record is not None
        return record

    def request_cancel(self, run_id: str) -> RunRecord | None:
        """Idempotent. Sets the flag; the terminal race is resolved by CAS."""
        with self._tx() as conn:
            conn.execute(
                "UPDATE runs SET cancel_requested=1, updated_at=? "
                "WHERE run_id=?", (_now(), run_id))
            return self._read_run(conn, run_id)

    def mark_delivered(self, run_id: str) -> None:
        """Presentation acknowledgement. Separate from the analytical status:
        an unacknowledged answer is still a completed answer."""
        with self._tx() as conn:
            conn.execute("UPDATE runs SET delivered_at=? WHERE run_id=?",
                         (_now(), run_id))

    # -- outbox and leases ----------------------------------------------

    def claim_next(self, worker_id: str) -> RunRecord | None:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT run_id FROM outbox WHERE claimed=0 "
                "ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return None
            run_id = row["run_id"]
            conn.execute("UPDATE outbox SET claimed=1 WHERE run_id=?",
                         (run_id,))
            conn.execute(
                "INSERT OR REPLACE INTO leases(run_id, worker_id, fence,"
                " heartbeat_at, claimed_at) VALUES (?,?,"
                " COALESCE((SELECT fence FROM leases WHERE run_id=?),0)+1,"
                " ?,?)", (run_id, worker_id, run_id, _now(), _now()))
            return self._read_run(conn, run_id)

    def heartbeat(self, run_id: str, worker_id: str) -> None:
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE leases SET heartbeat_at=? WHERE run_id=? "
                "AND worker_id=?", (_now(), run_id, worker_id))
            if cur.rowcount == 0:
                raise LeaseLost(f"worker {worker_id} no longer holds {run_id}")

    def lease(self, run_id: str) -> dict[str, Any] | None:
        row = self._connect().execute(
            "SELECT * FROM leases WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def stale_runs(self, *, stale_seconds: float) -> list[RunRecord]:
        """Runs whose worker stopped heartbeating, for the supervisor."""
        cutoff = datetime.now(timezone.utc).timestamp() - stale_seconds
        out: list[RunRecord] = []
        conn = self._connect()
        for row in conn.execute(
                "SELECT r.run_id, l.heartbeat_at FROM runs r JOIN leases l "
                "ON l.run_id=r.run_id WHERE r.state NOT IN "
                f"({','.join('?' * len(TERMINAL_STATES))})",
                tuple(TERMINAL_STATES)).fetchall():
            try:
                beat = datetime.fromisoformat(row["heartbeat_at"]).timestamp()
            except ValueError:
                continue
            if beat < cutoff:
                record = self._read_run(conn, row["run_id"])
                if record is not None:
                    out.append(record)
        return out

    def expiring_runs(self) -> list[RunRecord]:
        now = _now()
        conn = self._connect()
        rows = conn.execute(
            "SELECT run_id FROM runs WHERE deadline_at != '' AND "
            f"deadline_at < ? AND state NOT IN "
            f"({','.join('?' * len(TERMINAL_STATES))})",
            (now, *TERMINAL_STATES)).fetchall()
        return [r for r in (self._read_run(conn, x["run_id"]) for x in rows)
                if r is not None]

    def active_runs_for(self, *, thread_id: str = "",
                        principal_id: str = "") -> int:
        conn = self._connect()
        clause = "state NOT IN (" + ",".join("?" * len(TERMINAL_STATES)) + ")"
        params: list[Any] = list(TERMINAL_STATES)
        if thread_id:
            clause += " AND thread_id=?"
            params.append(thread_id)
        if principal_id:
            clause += " AND principal_id=?"
            params.append(principal_id)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM runs WHERE {clause}",
            tuple(params)).fetchone()
        return int(row["n"])

    # -- events ---------------------------------------------------------

    def append_event(self, event: Event) -> Event:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq),0) AS s FROM events WHERE run_id=?",
                (event.run_id,)).fetchone()
            event.seq = int(row["s"]) + 1
            conn.execute(
                "INSERT INTO events(run_id, seq, payload, occurred_at) "
                "VALUES (?,?,?,?)",
                (event.run_id, event.seq,
                 json.dumps(event.to_dict(), ensure_ascii=False),
                 event.occurred_at))
        return event

    def events_since(self, run_id: str, after_seq: int = 0,
                     limit: int = 500) -> list[Event]:
        rows = self._connect().execute(
            "SELECT payload FROM events WHERE run_id=? AND seq>? "
            "ORDER BY seq LIMIT ?", (run_id, after_seq, limit)).fetchall()
        out = []
        for row in rows:
            data = json.loads(row["payload"])
            out.append(Event(**{k: v for k, v in data.items()
                                if k in Event.__dataclass_fields__}))
        return out

    def last_seq(self, run_id: str) -> int:
        row = self._connect().execute(
            "SELECT COALESCE(MAX(seq),0) AS s FROM events WHERE run_id=?",
            (run_id,)).fetchone()
        return int(row["s"])

    def put_detail(self, run_id: str, body: dict[str, Any]) -> str:
        ref = f"dt-{uuid.uuid4().hex[:16]}"
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO details(detail_ref, run_id, body, created_at) "
                "VALUES (?,?,?,?)",
                (ref, run_id, json.dumps(body, ensure_ascii=False,
                                         default=str), _now()))
        return ref

    def get_detail(self, detail_ref: str) -> dict[str, Any] | None:
        row = self._connect().execute(
            "SELECT run_id, body FROM details WHERE detail_ref=?",
            (detail_ref,)).fetchone()
        if row is None:
            return None
        return {"run_id": row["run_id"], "body": json.loads(row["body"])}

    # -- conversation messages ------------------------------------------

    def save_messages(self, run_id: str, messages: list[dict[str, Any]]) -> None:
        """The canonical provider history, so a resumed or inspected run has
        no dangling tool_use without its tool_result."""
        with self._tx() as conn:
            conn.execute("DELETE FROM messages WHERE run_id=?", (run_id,))
            for i, message in enumerate(messages):
                conn.execute(
                    "INSERT INTO messages(run_id, ordinal, role, content) "
                    "VALUES (?,?,?,?)",
                    (run_id, i, str(message.get("role") or ""),
                     json.dumps(message.get("content"), ensure_ascii=False,
                                default=str)))

    def load_messages(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            "SELECT role, content FROM messages WHERE run_id=? "
            "ORDER BY ordinal", (run_id,)).fetchall()
        return [{"role": r["role"], "content": json.loads(r["content"])}
                for r in rows]

    # -- artifacts ------------------------------------------------------

    def put_artifact(self, *, run_id: str, tenant_id: str, kind: str,
                     release_id: str, scope: dict[str, Any],
                     columns: list[str], rows: list[dict[str, Any]],
                     code_digest: str = "") -> str:
        artifact_id = f"art-{uuid.uuid4().hex[:16]}"
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO artifacts(artifact_id, run_id, tenant_id, kind,"
                " release_id, scope, columns, row_count, body, code_digest,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (artifact_id, run_id, tenant_id, kind, release_id,
                 json.dumps(scope), json.dumps(columns), len(rows),
                 json.dumps(rows, ensure_ascii=False, default=str),
                 code_digest, _now()))
        return artifact_id

    def get_artifact(self, artifact_id: str, *,
                     tenant_id: str) -> dict[str, Any] | None:
        """Tenant-checked. An unauthorized reference returns None and the
        caller replies 'not available to you' -- it never confirms that some
        other tenant's artifact exists."""
        row = self._connect().execute(
            "SELECT * FROM artifacts WHERE artifact_id=?",
            (artifact_id,)).fetchone()
        if row is None or row["tenant_id"] != tenant_id:
            return None
        return {"artifact_id": row["artifact_id"], "run_id": row["run_id"],
                "kind": row["kind"], "release_id": row["release_id"],
                "scope": json.loads(row["scope"]),
                "columns": json.loads(row["columns"]),
                "row_count": int(row["row_count"]),
                "rows": json.loads(row["body"]),
                "code_digest": row["code_digest"],
                "created_at": row["created_at"]}

    # -- submissions and reservations -----------------------------------

    def record_submission(self, *, run_id: str, ordinal: int, round: int,
                          payload: dict[str, Any], status: str,
                          no_progress_key: str) -> str:
        submission_id = f"sub-{uuid.uuid4().hex[:12]}"
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO submissions(submission_id, run_id, ordinal,"
                " round, payload, status, no_progress_key, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (submission_id, run_id, ordinal, round,
                 json.dumps(payload, ensure_ascii=False, default=str), status,
                 no_progress_key, _now()))
        return submission_id

    def set_submission_status(self, submission_id: str, status: str) -> None:
        with self._tx() as conn:
            conn.execute("UPDATE submissions SET status=? "
                         "WHERE submission_id=?", (status, submission_id))

    def no_progress_keys(self, run_id: str) -> set[str]:
        rows = self._connect().execute(
            "SELECT no_progress_key FROM submissions WHERE run_id=? "
            "AND no_progress_key != ''", (run_id,)).fetchall()
        return {r["no_progress_key"] for r in rows}

    def reserve(self, *, run_id: str, purpose: str,
                reserved_usd: float) -> str:
        reservation_id = f"res-{uuid.uuid4().hex[:12]}"
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO reservations(reservation_id, run_id, purpose,"
                " reserved_usd, created_at) VALUES (?,?,?,?,?)",
                (reservation_id, run_id, purpose, float(reserved_usd), _now()))
        return reservation_id

    def settle(self, reservation_id: str, *, settled_usd: float | None,
               usage: dict[str, Any], uncertain: bool = False) -> None:
        """`settled_usd=None` with `uncertain=True` holds the reservation as
        PENDING. A cancelled or disconnected provider call may still have been
        billed, and booking it as zero understates real spend."""
        with self._tx() as conn:
            conn.execute(
                "UPDATE reservations SET settled_usd=?, usage=?, uncertain=? "
                "WHERE reservation_id=?",
                (settled_usd, json.dumps(usage), 1 if uncertain else 0,
                 reservation_id))

    def spend(self, run_id: str) -> dict[str, Any]:
        rows = self._connect().execute(
            "SELECT reserved_usd, settled_usd, uncertain FROM reservations "
            "WHERE run_id=?", (run_id,)).fetchall()
        committed = pending = 0.0
        uncertain = False
        for row in rows:
            if row["settled_usd"] is None:
                pending += float(row["reserved_usd"])
                uncertain = uncertain or bool(row["uncertain"])
            else:
                committed += float(row["settled_usd"])
                if row["uncertain"]:
                    pending += float(row["reserved_usd"])
                    uncertain = True
        return {"committed_usd": round(committed, 6),
                "pending_usd": round(pending, 6), "uncertain": uncertain}

    # -- thread turns and summaries -------------------------------------

    def append_turn(self, *, thread_id: str, run_id: str, question: str,
                    answer: dict[str, Any]) -> str:
        turn_id = f"turn-{uuid.uuid4().hex[:12]}"
        with self._tx() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(ordinal),0) AS n FROM turns "
                "WHERE thread_id=?", (thread_id,)).fetchone()
            conn.execute(
                "INSERT INTO turns(turn_id, thread_id, run_id, ordinal,"
                " question, answer, created_at) VALUES (?,?,?,?,?,?,?)",
                (turn_id, thread_id, run_id, int(row["n"]) + 1, question,
                 json.dumps(answer, ensure_ascii=False, default=str), _now()))
        return turn_id

    def recent_turns(self, thread_id: str, limit: int = 3
                     ) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            "SELECT turn_id, ordinal, question, answer FROM turns "
            "WHERE thread_id=? ORDER BY ordinal DESC LIMIT ?",
            (thread_id, limit)).fetchall()
        return [{"turn_id": r["turn_id"], "ordinal": int(r["ordinal"]),
                 "question": r["question"], "answer": json.loads(r["answer"])}
                for r in reversed(rows)]

    def turn_count(self, thread_id: str) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS n FROM turns WHERE thread_id=?",
            (thread_id,)).fetchone()
        return int(row["n"])

    def get_turn(self, turn_id: str, *, tenant_id: str
                 ) -> dict[str, Any] | None:
        row = self._connect().execute(
            "SELECT t.*, th.tenant_id AS owner FROM turns t JOIN threads th "
            "ON th.thread_id=t.thread_id WHERE t.turn_id=?",
            (turn_id,)).fetchone()
        if row is None or row["owner"] != tenant_id:
            return None
        return {"turn_id": row["turn_id"], "ordinal": int(row["ordinal"]),
                "question": row["question"],
                "answer": json.loads(row["answer"]),
                "created_at": row["created_at"]}

    def put_summary(self, *, thread_id: str, covered_through: int,
                    body: dict[str, Any], schema_version: str) -> bool:
        """Compare-and-swap on coverage. An older job cannot overwrite a
        newer summary just because it finished later."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT covered_through_ordinal FROM summaries "
                "WHERE thread_id=?", (thread_id,)).fetchone()
            if row is not None and int(
                    row["covered_through_ordinal"]) >= covered_through:
                return False
            conn.execute(
                "INSERT OR REPLACE INTO summaries(thread_id,"
                " covered_through_ordinal, body, schema_version, updated_at)"
                " VALUES (?,?,?,?,?)",
                (thread_id, covered_through,
                 json.dumps(body, ensure_ascii=False, default=str),
                 schema_version, _now()))
        return True

    def get_summary(self, thread_id: str) -> dict[str, Any] | None:
        row = self._connect().execute(
            "SELECT * FROM summaries WHERE thread_id=?",
            (thread_id,)).fetchone()
        if row is None:
            return None
        return {"covered_through_ordinal": int(row["covered_through_ordinal"]),
                "body": json.loads(row["body"]),
                "schema_version": row["schema_version"],
                "updated_at": row["updated_at"]}


__all__ = ["IdempotencyConflict", "LeaseLost", "RunRecord", "RunStore",
           "SCHEMA_VERSION", "StorageUnavailable", "TerminalAlready"]
