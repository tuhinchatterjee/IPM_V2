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
  Comments, shares, observations and alert events refuse UPDATE and DELETE.
* every governed write -- an object version, a Lens observation, an alert
  event, a comment, a share -- appends one entry to a per-tenant hash CHAIN
  (`ledger`) in the same transaction: the entry holds the SHA-256 of the
  stored row and chains it to the previous entry, so any later alteration of
  a row, a removed row, or a row slipped in outside this module is detected
  by `verify_ledger` rather than trusted. Rows written before the ledger
  existed are entered once at open and marked `backfilled` (attested from
  that point, not before).
* credential-shaped text (API keys, bearer tokens, passwords, private keys)
  is replaced by `[REDACTED]` before any row is written -- a secret a user
  pastes into a note is never persisted, displayed or exported.

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
CREATE TRIGGER IF NOT EXISTS lens_obs_no_delete BEFORE DELETE ON lens_observations
    BEGIN SELECT RAISE(ABORT, 'lens observations are never deleted'); END;

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
CREATE TRIGGER IF NOT EXISTS alert_events_no_delete BEFORE DELETE ON alert_events
    BEGIN SELECT RAISE(ABORT, 'alert history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS comments_no_update BEFORE UPDATE ON comments
    BEGIN SELECT RAISE(ABORT, 'comments are append-only'); END;
CREATE TRIGGER IF NOT EXISTS comments_no_delete BEFORE DELETE ON comments
    BEGIN SELECT RAISE(ABORT, 'comments are append-only'); END;
CREATE TRIGGER IF NOT EXISTS shares_no_update BEFORE UPDATE ON shares
    BEGIN SELECT RAISE(ABORT, 'shares are append-only'); END;
CREATE TRIGGER IF NOT EXISTS shares_no_delete BEFORE DELETE ON shares
    BEGIN SELECT RAISE(ABORT, 'shares are append-only'); END;

CREATE TABLE IF NOT EXISTS ledger (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    TEXT NOT NULL,
    record_kind  TEXT NOT NULL,
    record_id    TEXT NOT NULL,
    record_hash  TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    chain_hash   TEXT NOT NULL,
    backfilled   INTEGER NOT NULL DEFAULT 0,
    at           REAL NOT NULL,
    UNIQUE (tenant_id, record_kind, record_id)
);
CREATE INDEX IF NOT EXISTS ledger_tenant ON ledger(tenant_id, seq);
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
    BEGIN SELECT RAISE(ABORT, 'the ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
    BEGIN SELECT RAISE(ABORT, 'the ledger is append-only'); END;

CREATE TABLE IF NOT EXISTS subscriptions (
    tenant_id  TEXT NOT NULL,
    object_id  TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, object_id, user_id)
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str).encode("utf-8")


def content_hash(body: Any) -> str:
    return hashlib.sha256(canonical(body)).hexdigest()


#: The chain's first link.
GENESIS = "0" * 64

#: Ledgered tables: record kind -> (table, id expression, ORDER column).
LEDGERED: dict[str, tuple[str, str, str]] = {
    "object": ("objects", "object_id || '@v' || version", "created_at"),
    "observation": ("lens_observations", "observation_id", "started_at"),
    "alert_event": ("alert_events", "event_id", "at"),
    "comment": ("comments", "comment_id", "created_at"),
    "share": ("shares", "share_id", "created_at"),
}


def row_hash(row: sqlite3.Row | dict[str, Any]) -> str:
    """SHA-256 of a stored row, every column exactly as stored."""
    return content_hash({k: row[k] for k in row.keys()})


def chain(prev: str, kind: str, record_id: str, record: str) -> str:
    return hashlib.sha256(
        f"{prev}|{kind}|{record_id}|{record}".encode()).hexdigest()


def scrub(value: Any) -> Any:
    """Credential-shaped text replaced by `[REDACTED]`; everything else --
    numbers, hashes, ids, structure, order -- is returned as it was."""
    from backend.llm import exchange

    if isinstance(value, str):
        return exchange.scrub_text(value, "$", [])
    if isinstance(value, dict):
        return {k: (exchange.REDACTED if exchange.is_secret_key(k)
                    and isinstance(v, str) and v else scrub(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub(v) for v in value)
    return value


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
        self._backfill()

    # ---- the hash chain ----------------------------------------------------

    def _append(self, tenant_id: str, kind: str, record_id: str,
                record: str, *, backfilled: bool = False) -> None:
        """One chain link. Called with the lock held, inside the write's
        own transaction."""
        last = self._conn.execute(
            "SELECT chain_hash FROM ledger WHERE tenant_id=? ORDER BY seq "
            "DESC LIMIT 1", (tenant_id,)).fetchone()
        prev = last["chain_hash"] if last else GENESIS
        self._conn.execute(
            "INSERT INTO ledger (tenant_id, record_kind, record_id, "
            "record_hash, prev_hash, chain_hash, backfilled, at) VALUES "
            "(?,?,?,?,?,?,?,?)",
            (tenant_id, kind, record_id, record, prev,
             chain(prev, kind, record_id, record), 1 if backfilled else 0,
             time.time()))

    def _ledgered_insert(self, kind: str, sql: str, args: tuple[Any, ...],
                         tenant_id: str, record_id: str) -> None:
        table, id_expr, _ = LEDGERED[kind]
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(sql, args)
                stored = self._conn.execute(
                    f"SELECT * FROM {table} WHERE tenant_id=? AND "
                    f"{id_expr}=?", (tenant_id, record_id)).fetchone()
                self._append(tenant_id, kind, record_id, row_hash(stored))
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _backfill(self) -> None:
        """Enter rows that predate the ledger, oldest first -- ONCE, when the
        ledger is introduced to a store. After that a row without an entry
        was written around this module and stays reported as UNLEDGERED; a
        restart never legitimises it."""
        with self._lock:
            if self._conn.execute("SELECT 1 FROM meta WHERE key="
                                  "'ledger_since'").fetchone():
                return
            pending = []
            for kind, (table, id_expr, order) in LEDGERED.items():
                for r in self._conn.execute(
                        f"SELECT *, {id_expr} AS _rid FROM {table} t WHERE "
                        f"NOT EXISTS (SELECT 1 FROM ledger l WHERE "
                        f"l.tenant_id=t.tenant_id AND l.record_kind=? AND "
                        f"l.record_id={id_expr})", (kind,)).fetchall():
                    pending.append((r[order], kind, r))
            pending.sort(key=lambda p: (p[0], p[1], p[2]["_rid"]))
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for _, kind, r in pending:
                    row = {k: r[k] for k in r.keys() if k != "_rid"}
                    self._append(r["tenant_id"], kind, r["_rid"],
                                 row_hash(row), backfilled=True)
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES ('ledger_since', ?)",
                    (json.dumps({"at": time.time(),
                                 "backfilled": len(pending)}),))
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def ledger(self, *, tenant_id: str, record_id_prefix: str = "",
               kind: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM ledger WHERE tenant_id=?"
        args: list[Any] = [tenant_id]
        if kind:
            sql += " AND record_kind=?"
            args.append(kind)
        if record_id_prefix:
            sql += " AND record_id LIKE ?"
            args.append(record_id_prefix.replace("%", "") + "%")
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                sql + " ORDER BY seq", args).fetchall()]

    def verify_ledger(self, *, tenant_id: str) -> dict[str, Any]:
        """Re-walk the tenant's chain and re-hash every record it names.

        Reports, never repairs: a broken link, a record whose stored row no
        longer hashes to its entry, a record that has gone, and a governed
        row that was written without an entry."""
        problems: list[dict[str, Any]] = []
        prev = GENESIS
        with self._lock:
            entries = self._conn.execute(
                "SELECT * FROM ledger WHERE tenant_id=? ORDER BY seq",
                (tenant_id,)).fetchall()
            rows: dict[tuple[str, str], dict[str, Any]] = {}
            for kind, (table, id_expr, _) in LEDGERED.items():
                for r in self._conn.execute(
                        f"SELECT *, {id_expr} AS _rid FROM {table} WHERE "
                        f"tenant_id=?", (tenant_id,)).fetchall():
                    rows[(kind, r["_rid"])] = {k: r[k] for k in r.keys()
                                               if k != "_rid"}
        seen: set[tuple[str, str]] = set()
        for e in entries:
            if e["prev_hash"] != prev or e["chain_hash"] != chain(
                    prev, e["record_kind"], e["record_id"], e["record_hash"]):
                problems.append({"seq": e["seq"], "record_id": e["record_id"],
                                 "problem": "CHAIN_BROKEN"})
            prev = e["chain_hash"]
            key = (e["record_kind"], e["record_id"])
            seen.add(key)
            row = rows.get(key)
            if row is None:
                problems.append({"seq": e["seq"], "record_id": e["record_id"],
                                 "problem": "MISSING"})
            elif row_hash(row) != e["record_hash"]:
                problems.append({"seq": e["seq"], "record_id": e["record_id"],
                                 "problem": "ALTERED"})
        for kind, rid in sorted(set(rows) - seen):
            problems.append({"record_id": rid, "record_kind": kind,
                             "problem": "UNLEDGERED"})
        return {"tenant_id": tenant_id, "ok": not problems,
                "entries": len(entries),
                "backfilled": sum(1 for e in entries if e["backfilled"]),
                "chain_head": prev, "problems": problems[:200],
                "problem_count": len(problems)}

    # ---- objects -----------------------------------------------------------

    def insert_version(self, row: dict[str, Any]) -> dict[str, Any]:
        body = scrub(row["body"])
        digest = content_hash(body)
        record_id = f"{row['object_id']}@v{int(row['version'])}"
        self._ledgered_insert(
            "object",
            "INSERT INTO objects (object_id, version, kind, tenant_id, "
            "owner_id, domain_id, release_id, fingerprint, period, status,"
            " title, body, lineage, permissions, trace_refs, tags, "
            "content_hash, seeded, created_at, created_by) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["object_id"], int(row["version"]), row["kind"],
             row["tenant_id"], row["owner_id"], row.get("domain_id", ""),
             row.get("release_id", ""), row.get("fingerprint", ""),
             row.get("period", ""), row.get("status", ""),
             scrub(row.get("title", "")),
             json.dumps(body, ensure_ascii=False, default=str),
             json.dumps(row.get("lineage") or {}, default=str),
             json.dumps(row.get("permissions") or {}, default=str),
             json.dumps(row.get("trace_refs") or [], default=str),
             json.dumps(row.get("tags") or [], default=str),
             digest, 1 if row.get("seeded") else 0,
             float(row.get("created_at") or time.time()),
             row.get("created_by") or row["owner_id"]),
            row["tenant_id"], record_id)
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
               "body": scrub(body), "created_at": time.time()}
        self._ledgered_insert("comment",
                              "INSERT INTO comments VALUES (?,?,?,?,?,?,?)",
                              tuple(row.values()), tenant_id,
                              row["comment_id"])
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
        card = scrub(card)
        row = {"share_id": "shr-" + uuid.uuid4().hex[:16],
               "tenant_id": tenant_id, "object_id": object_id,
               "version": int(version), "kind": kind, "from_id": from_id,
               "to_id": to_id, "message": scrub(message),
               "card": json.dumps(card, ensure_ascii=False, default=str),
               "seeded": 1 if seeded else 0,
               "created_at": created_at or time.time()}
        self._ledgered_insert(
            "share", "INSERT INTO shares VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            tuple(row.values()), tenant_id, row["share_id"])
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

    def shares_of(self, object_id: str, *, tenant_id: str
                  ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM shares WHERE tenant_id=? AND object_id=? "
                "ORDER BY created_at", (tenant_id, object_id)).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["card"] = json.loads(item["card"])
            out.append(item)
        return out

    def ledger_entry(self, *, tenant_id: str, kind: str, record_id: str
                     ) -> dict[str, Any] | None:
        """One record's chain link, with whether it still links to the
        entry before it and whether the stored row still hashes to it."""
        table, id_expr, _ = LEDGERED[kind]
        with self._lock:
            e = self._conn.execute(
                "SELECT * FROM ledger WHERE tenant_id=? AND record_kind=? AND "
                "record_id=?", (tenant_id, kind, record_id)).fetchone()
            if e is None:
                return None
            before = self._conn.execute(
                "SELECT chain_hash FROM ledger WHERE tenant_id=? AND seq<? "
                "ORDER BY seq DESC LIMIT 1", (tenant_id, e["seq"])).fetchone()
            row = self._conn.execute(
                f"SELECT * FROM {table} WHERE tenant_id=? AND {id_expr}=?",
                (tenant_id, record_id)).fetchone()
        prev = before["chain_hash"] if before else GENESIS
        out = dict(e)
        out["links"] = e["prev_hash"] == prev and e["chain_hash"] == chain(
            prev, kind, record_id, e["record_hash"])
        out["row_matches"] = row is not None and row_hash(row) == \
            e["record_hash"]
        return out

    def mark_read(self, share_id: str, reader_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO inbox_reads VALUES (?,?,?)",
                (share_id, reader_id, time.time()))

    # ---- lens observations ---------------------------------------------------

    def add_observation(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row.setdefault("observation_id", "obs-" + uuid.uuid4().hex[:16])
        row["body"] = scrub(row.get("body") or {})
        row["error"] = scrub(row.get("error", ""))
        self._ledgered_insert(
            "observation",
            "INSERT INTO lens_observations (observation_id, tenant_id, "
            "lens_id, lens_version, trigger, release_id, fingerprint, "
            "period, status, started_at, finished_at, body, error, seeded)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["observation_id"], row["tenant_id"], row["lens_id"],
             int(row["lens_version"]), row["trigger"],
             row.get("release_id", ""), row.get("fingerprint", ""),
             row.get("period", ""), row["status"], row["started_at"],
             row["finished_at"],
             json.dumps(row["body"], default=str),
             row["error"], 1 if row.get("seeded") else 0),
            row["tenant_id"], row["observation_id"])
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
               "actor_id": actor_id, "note": scrub(note),
               "observed": observed, "at": at or time.time()}
        self._ledgered_insert(
            "alert_event", "INSERT INTO alert_events VALUES "
            "(?,?,?,?,?,?,?,?,?)", tuple(row.values()), tenant_id,
            row["event_id"])
        return row

    def alert_events(self, alert_id: str, *, tenant_id: str
                     ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM alert_events WHERE tenant_id=? AND alert_id=? "
                "ORDER BY at", (tenant_id, alert_id)).fetchall()
        return [dict(r) for r in rows]

    # ---- subscriptions (who follows a Lens's deliveries) ---------------------

    def subscribe(self, *, tenant_id: str, object_id: str, user_id: str,
                  on: bool = True) -> None:
        with self._lock:
            if on:
                self._conn.execute(
                    "INSERT OR IGNORE INTO subscriptions VALUES (?,?,?,?)",
                    (tenant_id, object_id, user_id, time.time()))
            else:
                self._conn.execute(
                    "DELETE FROM subscriptions WHERE tenant_id=? AND "
                    "object_id=? AND user_id=?",
                    (tenant_id, object_id, user_id))

    def subscribers(self, object_id: str, *, tenant_id: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id FROM subscriptions WHERE tenant_id=? AND "
                "object_id=? ORDER BY created_at", (tenant_id, object_id)
            ).fetchall()
        return [str(r["user_id"]) for r in rows]

    def tenants_with(self, kind: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT tenant_id FROM objects WHERE kind=?",
                (kind,)).fetchall()
        return [str(r["tenant_id"]) for r in rows]

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


__all__ = ["GENESIS", "IntegrityError", "LEDGERED", "SCHEMA_VERSION",
           "WorkspaceStore", "canonical", "chain", "content_hash",
           "reset_for_tests", "row_hash", "scrub", "store_at"]
