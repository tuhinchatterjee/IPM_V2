"""
Lab-owned sidecar storage.

A small SQLite index plus content-addressed artifact files, all under the lab
runtime directory. The frozen schema is never migrated: child investigations
live in a SEPARATE frozen-format `RunStore` (`lab_runs.sqlite3`) that only the
lab's own workers touch, and this index refers to them by run id.

Invariants:
* `lab_events` is append-only. There is no UPDATE or DELETE on it.
* Reviews and evaluations are append-only revisions; a new version never
  overwrites an old one, it supersedes it.
* State transitions use compare-and-swap on `version`, so two workers cannot
  both claim one child.
* Every row carries `owner_scope` (tenant); reads filter on it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS comparisons (
  comparison_id TEXT PRIMARY KEY, owner_scope TEXT NOT NULL,
  principal_id TEXT NOT NULL, idempotency_key TEXT, spec_json TEXT NOT NULL,
  spec_hash TEXT NOT NULL, state TEXT NOT NULL, version INTEGER NOT NULL,
  created_at REAL NOT NULL, created_monotonic REAL, settled_at REAL,
  accepted_monotonic REAL, parent_id TEXT, label TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cmp_idem
  ON comparisons(owner_scope, idempotency_key) WHERE idempotency_key <> '';
CREATE TABLE IF NOT EXISTS children (
  child_run_id TEXT PRIMARY KEY, comparison_id TEXT NOT NULL,
  owner_scope TEXT NOT NULL, profile_id TEXT NOT NULL,
  profile_digest TEXT NOT NULL, profile_json TEXT NOT NULL,
  repetition INTEGER NOT NULL, attempt_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL, lane TEXT NOT NULL, state TEXT NOT NULL,
  version INTEGER NOT NULL, claimed_by TEXT, reason TEXT,
  thread_id TEXT, current_run_id TEXT, parent_child_id TEXT,
  lineage TEXT, enqueued_monotonic REAL, admitted_monotonic REAL,
  finished_monotonic REAL, enqueued_wall REAL, finished_wall REAL,
  user_wait_ms REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_child_cmp ON children(comparison_id);
CREATE TABLE IF NOT EXISTS child_runs (
  child_run_id TEXT NOT NULL, turn_index INTEGER NOT NULL,
  run_id TEXT NOT NULL, kind TEXT NOT NULL, question TEXT NOT NULL,
  started_monotonic REAL, finished_monotonic REAL, state TEXT,
  error_code TEXT, PRIMARY KEY (child_run_id, turn_index));
CREATE TABLE IF NOT EXISTS lab_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
  comparison_id TEXT NOT NULL, child_run_id TEXT, owner_scope TEXT NOT NULL,
  event_type TEXT NOT NULL, envelope TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_ev_cmp ON lab_events(comparison_id, seq);
CREATE TABLE IF NOT EXISTS evaluations (
  evaluation_id TEXT PRIMARY KEY, comparison_id TEXT NOT NULL,
  owner_scope TEXT NOT NULL, evaluator_version TEXT NOT NULL,
  revision INTEGER NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL,
  created_at REAL NOT NULL, superseded_by TEXT);
CREATE TABLE IF NOT EXISTS reviews (
  review_id TEXT PRIMARY KEY, comparison_id TEXT NOT NULL,
  owner_scope TEXT NOT NULL, reviewer TEXT NOT NULL, target TEXT NOT NULL,
  decision TEXT NOT NULL, reason TEXT NOT NULL, prior TEXT,
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS exports (
  export_id TEXT PRIMARY KEY, comparison_id TEXT NOT NULL,
  owner_scope TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL,
  path TEXT, sha256 TEXT, created_at REAL NOT NULL, error TEXT,
  evaluation_id TEXT);
"""


class Conflict(RuntimeError):
    """A compare-and-swap lost: somebody else moved the row first."""


class LabStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        self.db_path = self.root / "lab_index.sqlite3"
        self.runs_db_path = self.root / "lab_runs.sqlite3"
        self._lock = threading.RLock()
        c = self._conn()        # executescript manages its own transaction
        try:
            c.executescript(SCHEMA)
        finally:
            c.close()

    # -- plumbing ------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            c = self._conn()
            try:
                c.execute("BEGIN IMMEDIATE")
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            finally:
                c.close()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        c = self._conn()
        try:
            return list(c.execute(sql, args))
        finally:
            c.close()

    # -- blobs (content-addressed) ---------------------------------------
    def put_blob(self, data: bytes | str) -> str:
        raw = data.encode() if isinstance(data, str) else data
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / "blobs" / digest[:2] / digest
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(raw)
            tmp.replace(path)
        return digest

    def get_blob(self, digest: str) -> bytes:
        if not all(ch in "0123456789abcdef" for ch in digest) or \
                len(digest) != 64:
            raise ValueError("not a blob digest")
        return (self.root / "blobs" / digest[:2] / digest).read_bytes()

    # -- comparisons -----------------------------------------------------
    def create_comparison(self, *, owner_scope: str, principal_id: str,
                          idempotency_key: str, spec: dict[str, Any],
                          spec_hash: str, parent_id: str | None = None,
                          label: str = "") -> tuple[dict[str, Any], bool]:
        """Idempotent: the same key in the same scope returns the first."""
        with self._tx() as c:
            if idempotency_key:
                row = c.execute(
                    "SELECT * FROM comparisons WHERE owner_scope=? AND "
                    "idempotency_key=?", (owner_scope, idempotency_key)
                ).fetchone()
                if row:
                    return dict(row), False
            cid = f"cmp-{uuid.uuid4().hex[:12]}"
            spec = dict(spec, comparison_id=cid)
            c.execute(
                "INSERT INTO comparisons VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, owner_scope, principal_id, idempotency_key or "",
                 json.dumps(spec, sort_keys=True), spec_hash, "PREFLIGHT", 1,
                 time.time(), time.monotonic(), None, None, parent_id, label))
            row = c.execute("SELECT * FROM comparisons WHERE comparison_id=?",
                            (cid,)).fetchone()
            return dict(row), True

    def get_comparison(self, cid: str, owner_scope: str
                       ) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM comparisons WHERE comparison_id=? AND "
                       "owner_scope=?", (cid, owner_scope))
        return dict(rows[0]) if rows else None

    def list_comparisons(self, owner_scope: str, limit: int = 50
                         ) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT * FROM comparisons WHERE owner_scope=? ORDER BY "
            "created_at DESC LIMIT ?", (owner_scope, limit))]

    def set_comparison_state(self, cid: str, state: str, *,
                             expect: tuple[str, ...] | None = None,
                             settled: bool = False,
                             accepted_monotonic: float | None = None) -> bool:
        with self._tx() as c:
            row = c.execute("SELECT state, version FROM comparisons WHERE "
                            "comparison_id=?", (cid,)).fetchone()
            if row is None or (expect and row["state"] not in expect):
                return False
            c.execute(
                "UPDATE comparisons SET state=?, version=version+1, "
                "settled_at=COALESCE(?, settled_at), accepted_monotonic="
                "COALESCE(?, accepted_monotonic) WHERE comparison_id=? AND "
                "version=?",
                (state, time.time() if settled else None, accepted_monotonic,
                 cid, row["version"]))
            return True

    # -- children ----------------------------------------------------------
    def add_child(self, **row: Any) -> None:
        cols = ",".join(row)
        with self._tx() as c:
            c.execute(f"INSERT INTO children ({cols}) VALUES "
                      f"({','.join('?' * len(row))})", tuple(row.values()))

    def children(self, cid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT * FROM children WHERE comparison_id=? ORDER BY ordinal",
            (cid,))]

    def child(self, child_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM children WHERE child_run_id=?",
                       (child_id,))
        return dict(rows[0]) if rows else None

    def transition_child(self, child_id: str, to: str, *,
                         expect: tuple[str, ...], worker: str | None = None,
                         **fields: Any) -> bool:
        """CAS transition. Returns False if the child was not in `expect`."""
        with self._tx() as c:
            row = c.execute("SELECT state, version FROM children WHERE "
                            "child_run_id=?", (child_id,)).fetchone()
            if row is None or row["state"] not in expect:
                return False
            sets = ["state=?", "version=version+1"]
            args: list[Any] = [to]
            if worker is not None:
                sets.append("claimed_by=?")
                args.append(worker)
            for k, v in fields.items():
                sets.append(f"{k}=?")
                args.append(v)
            args += [child_id, row["version"]]
            cur = c.execute(f"UPDATE children SET {', '.join(sets)} WHERE "
                            f"child_run_id=? AND version=?", tuple(args))
            return cur.rowcount == 1

    def update_child(self, child_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._tx() as c:
            c.execute(f"UPDATE children SET {sets} WHERE child_run_id=?",
                      (*fields.values(), child_id))

    def add_child_run(self, child_id: str, run_id: str, kind: str,
                      question: str) -> int:
        with self._tx() as c:
            n = c.execute("SELECT COUNT(*) FROM child_runs WHERE "
                          "child_run_id=?", (child_id,)).fetchone()[0]
            c.execute("INSERT INTO child_runs VALUES (?,?,?,?,?,?,?,?,?)",
                      (child_id, n, run_id, kind, question, time.monotonic(),
                       None, None, None))
            return n

    def finish_child_run(self, child_id: str, turn: int, state: str,
                         error_code: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE child_runs SET finished_monotonic=?, state=?, "
                      "error_code=? WHERE child_run_id=? AND turn_index=?",
                      (time.monotonic(), state, error_code, child_id, turn))

    def child_runs(self, child_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT * FROM child_runs WHERE child_run_id=? ORDER BY "
            "turn_index", (child_id,))]

    # -- events (append-only) --------------------------------------------
    def append_event(self, envelope: dict[str, Any]) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO lab_events (event_id, comparison_id, "
                "child_run_id, owner_scope, event_type, envelope) VALUES "
                "(?,?,?,?,?,?)",
                (envelope["event_id"], envelope["comparison_id"],
                 envelope.get("child_run_id"), envelope["owner_scope"],
                 envelope["event_type"], json.dumps(envelope, default=str,
                                                    sort_keys=True)))
            return int(cur.lastrowid)

    def events(self, cid: str, owner_scope: str, after: int = 0,
               limit: int = 1000) -> list[dict[str, Any]]:
        out = []
        for r in self._q("SELECT seq, envelope FROM lab_events WHERE "
                         "comparison_id=? AND owner_scope=? AND seq>? ORDER "
                         "BY seq LIMIT ?", (cid, owner_scope, after, limit)):
            e = json.loads(r["envelope"])
            e["seq"] = r["seq"]
            out.append(e)
        return out

    # -- evaluations / reviews / exports (append-only revisions) ----------
    def add_evaluation(self, cid: str, owner_scope: str, version: str,
                       body: dict[str, Any]) -> dict[str, Any]:
        with self._tx() as c:
            prev = c.execute(
                "SELECT evaluation_id, revision FROM evaluations WHERE "
                "comparison_id=? AND superseded_by IS NULL ORDER BY revision "
                "DESC LIMIT 1", (cid,)).fetchone()
            rev = (prev["revision"] + 1) if prev else 1
            eid = f"eval-{uuid.uuid4().hex[:12]}"
            c.execute("INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?,?)",
                      (eid, cid, owner_scope, version, rev, "CURRENT",
                       json.dumps(body, default=str), time.time(), None))
            if prev:
                c.execute("UPDATE evaluations SET superseded_by=?, "
                          "status='SUPERSEDED' WHERE evaluation_id=?",
                          (eid, prev["evaluation_id"]))
            return {"evaluation_id": eid, "revision": rev}

    def current_evaluation(self, cid: str, owner_scope: str
                           ) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM evaluations WHERE comparison_id=? AND "
                       "owner_scope=? AND superseded_by IS NULL ORDER BY "
                       "revision DESC LIMIT 1", (cid, owner_scope))
        if not rows:
            return None
        r = dict(rows[0])
        r["body"] = json.loads(r["body"])
        return r

    def evaluation_history(self, cid: str, owner_scope: str
                           ) -> list[dict[str, Any]]:
        return [{k: r[k] for k in ("evaluation_id", "revision", "status",
                                   "evaluator_version", "created_at",
                                   "superseded_by")}
                for r in self._q("SELECT * FROM evaluations WHERE "
                                 "comparison_id=? AND owner_scope=? ORDER BY "
                                 "revision", (cid, owner_scope))]

    def add_review(self, cid: str, owner_scope: str, reviewer: str,
                   target: str, decision: str, reason: str,
                   prior: dict[str, Any] | None) -> str:
        rid = f"rev-{uuid.uuid4().hex[:12]}"
        with self._tx() as c:
            c.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?)",
                      (rid, cid, owner_scope, reviewer, target, decision,
                       reason, json.dumps(prior, default=str), time.time()))
        return rid

    def reviews(self, cid: str, owner_scope: str) -> list[dict[str, Any]]:
        out = []
        for r in self._q("SELECT * FROM reviews WHERE comparison_id=? AND "
                         "owner_scope=? ORDER BY created_at",
                         (cid, owner_scope)):
            d = dict(r)
            d["prior"] = json.loads(d["prior"]) if d["prior"] else None
            out.append(d)
        return out

    def add_export(self, cid: str, owner_scope: str, state: str, *,
                   path: str = "", sha: str = "", error: str = "",
                   evaluation_id: str = "") -> dict[str, Any]:
        with self._tx() as c:
            n = c.execute("SELECT COUNT(*) FROM exports WHERE "
                          "comparison_id=?", (cid,)).fetchone()[0]
            xid = f"exp-{uuid.uuid4().hex[:12]}"
            c.execute("INSERT INTO exports VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (xid, cid, owner_scope, n + 1, state, path, sha,
                       time.time(), error, evaluation_id))
            return {"export_id": xid, "revision": n + 1}

    def latest_export(self, cid: str, owner_scope: str
                      ) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM exports WHERE comparison_id=? AND "
                       "owner_scope=? ORDER BY revision DESC LIMIT 1",
                       (cid, owner_scope))
        return dict(rows[0]) if rows else None
