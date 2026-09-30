"""
The workspace's durable store: versioned governed objects, and their history.

One SQLite file (`workspace.sqlite3`) beside the V4 state database, WAL mode.
The design rule is that nothing a banker saved is ever silently changed:

* `objects` is keyed by `(object_id, version)` and is INSERT-only -- a trigger
  refuses every UPDATE and DELETE. Editing a scenario, a Lens or a cohort
  writes version n+1 with its lineage; the earlier version is still there,
  still readable, still hashable.
* the content hash of every version is computed over its canonical body when
  it is written, and re-verified when it is read, so a row altered outside
  this module (the trigger aside) is refused rather than served.
* append-only side tables carry what is naturally a log: comments on a
  version, shares, inbox reads, lens observations, alert state events.

Tenancy is a column on every row and every read filters on it. A tenant id is
never taken from a request: callers pass the principal's tenant.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS objects (
    object_id     TEXT NOT NULL,
    version       INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    owner_id      TEXT NOT NULL,
    domain_id     TEXT NOT NULL DEFAULT '',
    release_id    TEXT NOT NULL DEFAULT '',
    fingerprint   TEXT NOT NULL DEFAULT '',
    period        TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL,
    lineage       TEXT NOT NULL DEFAULT '{}',
    permissions   TEXT NOT NULL DEFAULT '{}',
    trace_refs    TEXT NOT NULL DEFAULT '[]',
    tags          TEXT NOT NULL DEFAULT '[]',
    content_hash  TEXT NOT NULL,
    seeded        INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    created_by    TEXT NOT NULL,
    PRIMARY KEY (object_id, version)
);
CREATE INDEX IF NOT EXISTS objects_kind ON objects(tenant_id, kind);
CREATE TRIGGER IF NOT EXISTS objects_no_update BEFORE UPDATE ON objects
    BEGIN SELECT RAISE(ABORT, 'workspace objects are immutable; write a new version'); END;
CREATE TRIGGER IF NOT EXISTS objects_no_delete BEFORE DELETE ON objects
    BEGIN SELECT RAISE(ABORT, 'workspace objects are never deleted; archive with a new version'); END;

CREATE TABLE IF NOT EXISTS comments (
    comment_id  TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    object_id   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    author_id   TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_object ON comments(tenant_id, object_id);

CREATE TABLE IF NOT EXISTS shares (
    share_id    TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    object_id   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    from_id     TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    message     TEXT NOT NULL DEFAULT '',
    card        TEXT NOT NULL DEFAULT '{}',
    seeded      INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS shares_to ON shares(tenant_id, to_id);

CREATE TABLE IF NOT EXISTS inbox_reads (
    share_id   TEXT NOT NULL,
    reader_id  TEXT NOT NULL,
    read_at    REAL NOT NULL,
    PRIMARY KEY (share_id, reader_id)
);

CREATE TABLE IF NOT EXISTS lens_observations (
    observation_id TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    lens_id        TEXT NOT NULL,
    lens_version   INTEGER NOT NULL,
    trigger        TEXT NOT NULL,
    release_id     TEXT NOT NULL DEFAULT '',
    fingerprint    TEXT NOT NULL DEFAULT '',
    period         TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL,
    started_at     REAL NOT NULL,
    finished_at    REAL NOT NULL,
    body           TEXT NOT NULL,
    error          TEXT NOT NULL DEFAULT '',
    seeded         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS lens_obs ON lens_observations(tenant_id, lens_id, started_at);
CREATE TRIGGER IF NOT EXISTS lens_obs_no_update BEFORE UPDATE ON lens_observations
    BEGIN SELECT RAISE(ABORT, 'lens observations are immutable'); END;

CREATE TABLE IF NOT EXISTS alert_events (
    event_id    TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    alert_id    TEXT NOT NULL,
    from_state  TEXT NOT NULL DEFAULT '',
    to_state    TEXT NOT NULL,
    actor_id    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    observed    TEXT NOT NULL DEFAULT '',
    at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS alert_events_alert ON alert_events(tenant_id, alert_id, at);
CREATE TRIGGER IF NOT EXISTS alert_events_no_update BEFORE UPDATE ON alert_events
    BEGIN SELECT RAISE(ABORT, 'alert history is append-only'); END;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str).encode("utf-8")


def content_hash(body: Any) -> str:
    return hashlib.sha256(canonical(body)).hexdigest()


class IntegrityError(RuntimeError):
    """A stored version no longer hashes to what was written."""


class WorkspaceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False,
                                     isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_DDL)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema', ?)",
            (str(SCHEMA_VERSION),))

    # ---- objects -----------------------------------------------------------

    def insert_version(self, row: dict[str, Any]) -> dict[str, Any]:
        body = row["body"]
        digest = content_hash(body)
        with self._lock:
            self._conn.execute(
                "INSERT INTO objects (object_id, version, kind, tenant_id, "
                "owner_id, domain_id, release_id, fingerprint, period, status,"
                " title, body, lineage, permissions, trace_refs, tags, "
                "content_hash, seeded, created_at, created_by) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["object_id"], int(row["version"]), row["kind"],
                 row["tenant_id"], row["owner_id"], row.get("domain_id", ""),
                 row.get("release_id", ""), row.get("fingerprint", ""),
                 row.get("period", ""), row.get("status", ""),
                 row.get("title", ""),
                 json.dumps(body, ensure_ascii=False, default=str),
                 json.dumps(row.get("lineage") or {}, default=str),
                 json.dumps(row.get("permissions") or {}, default=str),
                 json.dumps(row.get("trace_refs") or [], default=str),
                 json.dumps(row.get("tags") or [], default=str),
                 digest, 1 if row.get("seeded") else 0,
                 float(row.get("created_at") or time.time()),
                 row.get("created_by") or row["owner_id"]))
        return self.get(row["object_id"], tenant_id=row["tenant_id"],
                        version=int(row["version"]))

    def _decode(self, r: sqlite3.Row) -> dict[str, Any]:
        body = json.loads(r["body"])
        if content_hash(body) != r["content_hash"]:
            raise IntegrityError(
                f"{r['object_id']} v{r['version']} no longer hashes to the "
                f"content written; it is refused rather than served.")
        return {
            "object_id": r["object_id"], "version": r["version"],
            "kind": r["kind"], "tenant_id": r["tenant_id"],
            "owner_id": r["owner_id"], "domain_id": r["domain_id"],
            "release_id": r["release_id"], "fingerprint": r["fingerprint"],
            "period": r["period"], "status": r["status"], "title": r["title"],
            "body": body, "lineage": json.loads(r["lineage"]),
            "permissions": json.loads(r["permissions"]),
            "trace_refs": json.loads(r["trace_refs"]),
            "tags": json.loads(r["tags"]),
            "content_hash": r["content_hash"], "seeded": bool(r["seeded"]),
            "created_at": r["created_at"], "created_by": r["created_by"]}

    def get(self, object_id: str, *, tenant_id: str,
            version: int | None = None) -> dict[str, Any] | None:
        with self._lock:
            if version is None:
                r = self._conn.execute(
                    "SELECT * FROM objects WHERE object_id=? AND tenant_id=? "
                    "ORDER BY version DESC LIMIT 1",
                    (object_id, tenant_id)).fetchone()
            else:
                r = self._conn.execute(
                    "SELECT * FROM objects WHERE object_id=? AND tenant_id=? "
                    "AND version=?", (object_id, tenant_id, int(version))
                ).fetchone()
        return self._decode(r) if r else None

    def versions(self, object_id: str, *, tenant_id: str
                 ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM objects WHERE object_id=? AND tenant_id=? "
                "ORDER BY version", (object_id, tenant_id)).fetchall()
        return [self._decode(r) for r in rows]

    def latest_of_kind(self, kind: str, *, tenant_id: str,
                       domain_id: str = "") -> list[dict[str, Any]]:
        sql = ("SELECT o.* FROM objects o JOIN (SELECT object_id, "
               "MAX(version) AS v FROM objects WHERE tenant_id=? AND kind=? "
               "GROUP BY object_id) m ON o.object_id=m.object_id AND "
               "o.version=m.v WHERE o.tenant_id=?")
        args: list[Any] = [tenant_id, kind, tenant_id]
        if domain_id:
            sql += " AND (o.domain_id=? OR o.domain_id='both')"
            args.append(domain_id)
        sql += " ORDER BY o.object_id"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._decode(r) for r in rows]

    def count(self, kind: str, *, tenant_id: str) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(DISTINCT object_id) FROM objects WHERE "
                "tenant_id=? AND kind=?", (tenant_id, kind)).fetchone()[0])

    def children_of(self, object_id: str, *, tenant_id: str
                    ) -> list[dict[str, Any]]:
        """Objects whose lineage names this one as a parent (any version)."""
        pattern = f'%"{object_id}"%'
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM objects WHERE tenant_id=? AND lineage LIKE ? "
                "ORDER BY created_at", (tenant_id, pattern)).fetchall()
        return [self._decode(r) for r in rows]

    # ---- comments, shares, inbox -------------------------------------------

    def add_comment(self, *, tenant_id: str, object_id: str, version: int,
                    author_id: str, body: str) -> dict[str, Any]:
        row = {"comment_id": "cmt-" + uuid.uuid4().hex[:16],
               "tenant_id": tenant_id, "object_id": object_id,
               "version": int(version), "author_id": author_id,
               "body": body, "created_at": time.time()}
        with self._lock:
            self._conn.execute(
                "INSERT INTO comments VALUES (?,?,?,?,?,?,?)",
                tuple(row.values()))
        return row

    def comments(self, object_id: str, *, tenant_id: str
                 ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM comments WHERE tenant_id=? AND object_id=? "
                "ORDER BY created_at", (tenant_id, object_id)).fetchall()
        return [dict(r) for r in rows]

    def add_share(self, *, tenant_id: str, object_id: str, version: int,
                  kind: str, from_id: str, to_id: str, message: str,
                  card: dict[str, Any], seeded: bool = False,
                  created_at: float | None = None) -> dict[str, Any]:
        row = {"share_id": "shr-" + uuid.uuid4().hex[:16],
               "tenant_id": tenant_id, "object_id": object_id,
               "version": int(version), "kind": kind, "from_id": from_id,
               "to_id": to_id, "message": message,
               "card": json.dumps(card, ensure_ascii=False, default=str),
               "seeded": 1 if seeded else 0,
               "created_at": created_at or time.time()}
        with self._lock:
            self._conn.execute(
                "INSERT INTO shares VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                tuple(row.values()))
        row["card"] = card
        return row

    def shares_for(self, *, tenant_id: str, recipients: Iterable[str],
                   sent_by: str = "") -> list[dict[str, Any]]:
        wanted = list(recipients)
        marks = ",".join("?" for _ in wanted) or "''"
        sql = (f"SELECT s.*, r.read_at FROM shares s LEFT JOIN inbox_reads r "
               f"ON r.share_id=s.share_id AND r.reader_id=? WHERE "
               f"s.tenant_id=? AND (s.to_id IN ({marks})")
        args: list[Any] = [sent_by or (wanted[0] if wanted else ""),
                           tenant_id, *wanted]
        if sent_by:
            sql += " OR s.from_id=?"
            args.append(sent_by)
        sql += ") ORDER BY s.created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["card"] = json.loads(item["card"])
            item["seeded"] = bool(item["seeded"])
            out.append(item)
        return out

    def share(self, share_id: str, *, tenant_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM shares WHERE share_id=? AND tenant_id=?",
                (share_id, tenant_id)).fetchone()
        if not r:
            return None
        item = dict(r)
        item["card"] = json.loads(item["card"])
        return item

    def mark_read(self, share_id: str, reader_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO inbox_reads VALUES (?,?,?)",
                (share_id, reader_id, time.time()))

    # ---- lens observations ---------------------------------------------------

    def add_observation(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row.setdefault("observation_id", "obs-" + uuid.uuid4().hex[:16])
        with self._lock:
            self._conn.execute(
                "INSERT INTO lens_observations (observation_id, tenant_id, "
                "lens_id, lens_version, trigger, release_id, fingerprint, "
                "period, status, started_at, finished_at, body, error, seeded)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["observation_id"], row["tenant_id"], row["lens_id"],
                 int(row["lens_version"]), row["trigger"],
                 row.get("release_id", ""), row.get("fingerprint", ""),
                 row.get("period", ""), row["status"], row["started_at"],
                 row["finished_at"],
                 json.dumps(row.get("body") or {}, default=str),
                 row.get("error", ""), 1 if row.get("seeded") else 0))
        return row

    def observations(self, lens_id: str, *, tenant_id: str, limit: int = 50
                     ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM lens_observations WHERE tenant_id=? AND "
                "lens_id=? ORDER BY started_at DESC LIMIT ?",
                (tenant_id, lens_id, limit)).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["body"] = json.loads(item["body"])
            item["seeded"] = bool(item["seeded"])
            out.append(item)
        return out

    # ---- alert events --------------------------------------------------------

    def add_alert_event(self, *, tenant_id: str, alert_id: str,
                        from_state: str, to_state: str, actor_id: str,
                        note: str = "", observed: str = "",
                        at: float | None = None) -> dict[str, Any]:
        row = {"event_id": "ae-" + uuid.uuid4().hex[:16],
               "tenant_id": tenant_id, "alert_id": alert_id,
               "from_state": from_state, "to_state": to_state,
               "actor_id": actor_id, "note": note, "observed": observed,
               "at": at or time.time()}
        with self._lock:
            self._conn.execute(
                "INSERT INTO alert_events VALUES (?,?,?,?,?,?,?,?,?)",
                tuple(row.values()))
        return row

    def alert_events(self, alert_id: str, *, tenant_id: str
                     ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM alert_events WHERE tenant_id=? AND alert_id=? "
                "ORDER BY at", (tenant_id, alert_id)).fetchall()
        return [dict(r) for r in rows]

    # ---- meta ----------------------------------------------------------------

    def meta(self, key: str) -> str | None:
        with self._lock:
            r = self._conn.execute("SELECT value FROM meta WHERE key=?",
                                   (key,)).fetchone()
        return r["value"] if r else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value", (key, value))


_STORES: dict[str, WorkspaceStore] = {}
_STORES_LOCK = threading.Lock()


def store_at(path: str | Path) -> WorkspaceStore:
    key = str(path)
    with _STORES_LOCK:
        if key not in _STORES:
            _STORES[key] = WorkspaceStore(key)
        return _STORES[key]


def reset_for_tests() -> None:
    with _STORES_LOCK:
        _STORES.clear()


__all__ = ["IntegrityError", "SCHEMA_VERSION", "WorkspaceStore",
           "canonical", "content_hash", "reset_for_tests", "store_at"]
