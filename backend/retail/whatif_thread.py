"""A What-If conversation, kept where it can be reopened.

The failure this exists for
---------------------------
The Early Warning thread held its turns in React state. Close the tab and the
conversation was gone: the SELECTION survived, so reopening the URL showed the
cohort and its baseline and none of the four scenarios that had been run on
it. A presenter who reopened a thread in front of a committee found an empty
one, and §8.3 names selection-only persistence with per-session conversation
loss as a failure rather than a limitation.

The standalone page had the same shape and the same hole, from a different
implementation.

Where this lives
----------------
`stress_scenarios`, the table saved runs already use, under its own `kind`.
A second table would mean a second ownership check and a second chance for the
two to disagree about who may read what — and a thread is a named, versioned,
parameterised object, which is what that table is for.

What a thread holds
-------------------
The selection it runs on, the method the reader chose, the staging mode, and
every turn in order: what was asked, how it was interpreted, which method ran,
and a reference to the result. Results themselves are stored with the turn, so
reopening shows the figures that were on screen rather than recomputing them
against a book that may have moved underneath.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.retail.whatif_store import Unavailable, _session

KIND = "retail_whatif_thread"
STORE_VERSION = "retail-thread-1.0.0"

#: Where a thread was opened from. Different entry, same thread.
FROM_STANDALONE = "standalone"
FROM_GUIDED = "guided_card"
FROM_EARLY_WARNING = "early_warning_export"

#: Turn kinds. `asked` is the reader; everything else is the product.
SAID = "said"
INTERPRETED = "interpreted"
RESULT = "result"
CLARIFICATION = "clarification"
NOTE = "note"

#: How many turns one thread keeps. A thread is a conversation, not a log;
#: beyond this the oldest results are dropped to keep the row readable, and
#: the thread says so rather than silently forgetting.
MAX_TURNS = 200


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return f"WFT-{uuid.uuid4().hex[:12].upper()}"


@dataclass
class Thread:
    """One conversation about one cohort."""

    thread_id: str
    title: str
    selection_id: str
    month: str
    opened_from: str
    method: str = ""
    staging_mode: str = ""
    turns: list[dict[str, Any]] = field(default_factory=list)
    created_by: int | None = None
    created_at: str = ""
    updated_at: str = ""
    row_id: int | None = None
    store_version: str = STORE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"thread_id": self.thread_id, "title": self.title,
                "selection_id": self.selection_id, "month": self.month,
                "opened_from": self.opened_from, "method": self.method,
                "staging_mode": self.staging_mode, "turns": list(self.turns),
                "turn_count": len(self.turns),
                "created_by": self.created_by, "created_at": self.created_at,
                "updated_at": self.updated_at,
                "store_version": self.store_version}


def _body(thread: Thread) -> dict[str, Any]:
    return {"kind": KIND, "thread_id": thread.thread_id,
            "selection_id": thread.selection_id, "month": thread.month,
            "opened_from": thread.opened_from, "method": thread.method,
            "staging_mode": thread.staging_mode, "turns": thread.turns,
            "created_at": thread.created_at, "updated_at": thread.updated_at}


def _read(row: Any) -> Thread:
    body = dict(row.parameters or {})
    return Thread(
        thread_id=str(body.get("thread_id") or ""),
        title=row.name, selection_id=str(body.get("selection_id") or ""),
        month=str(body.get("month") or ""),
        opened_from=str(body.get("opened_from") or ""),
        method=str(body.get("method") or ""),
        staging_mode=str(body.get("staging_mode") or ""),
        turns=list(body.get("turns") or []),
        created_by=row.created_by,
        created_at=str(body.get("created_at") or ""),
        updated_at=str(body.get("updated_at") or ""),
        row_id=row.id)


def create(*, title: str, selection_id: str, month: str, opened_from: str,
           method: str = "", staging_mode: str = "",
           owner: int | None = None) -> Thread:
    """Open a thread. Both entry points call this; only `opened_from` differs."""
    from backend.models.platform import StressScenario

    thread = Thread(thread_id=new_id(), title=title[:200],
                    selection_id=selection_id, month=month,
                    opened_from=opened_from, method=method,
                    staging_mode=staging_mode, created_by=owner,
                    created_at=_now(), updated_at=_now())
    with _session() as session:
        row = StressScenario(
            name=f"{title[:160]} · {thread.thread_id}",
            description=f"What-If thread on {selection_id} at {month}.",
            parameters=_body(thread), severity="moderate",
            version=STORE_VERSION[:24], status="open", created_by=owner)
        session.add(row)
        session.commit()
        session.refresh(row)
        thread.row_id = row.id
    return thread


def _find(session: Any, thread_id: str, owner: int | None) -> Any:
    from backend.models.platform import StressScenario

    query = session.query(StressScenario).filter(
        StressScenario.version == STORE_VERSION[:24])
    if owner is not None:
        query = query.filter(StressScenario.created_by == owner)
    for row in query.order_by(StressScenario.id.desc()).all():
        if str((row.parameters or {}).get("thread_id")) == thread_id:
            return row
    return None


def get(thread_id: str, *, owner: int | None = None) -> Thread | None:
    with _session() as session:
        row = _find(session, thread_id, owner)
        return _read(row) if row is not None else None


def append(thread_id: str, turn: dict[str, Any], *,
           owner: int | None = None) -> Thread | None:
    """Add one turn and persist it immediately.

    Written on every turn rather than on a Save button: a conversation the
    reader has to remember to save is one they will lose.
    """
    from sqlalchemy.orm.attributes import flag_modified

    with _session() as session:
        row = _find(session, thread_id, owner)
        if row is None:
            return None
        body = dict(row.parameters or {})
        turns = list(body.get("turns") or [])
        turns.append({**turn, "at": _now(), "n": len(turns) + 1})
        dropped = 0
        if len(turns) > MAX_TURNS:
            dropped = len(turns) - MAX_TURNS
            turns = turns[dropped:]
        body["turns"] = turns
        body["updated_at"] = _now()
        if dropped:
            body["dropped_turns"] = int(body.get("dropped_turns", 0)) + dropped
        row.parameters = body
        flag_modified(row, "parameters")
        session.commit()
        session.refresh(row)
        return _read(row)


def set_method(thread_id: str, *, method: str = "", staging_mode: str = "",
               owner: int | None = None) -> Thread | None:
    """Record the method the reader chose, so the next turn uses it."""
    from sqlalchemy.orm.attributes import flag_modified

    with _session() as session:
        row = _find(session, thread_id, owner)
        if row is None:
            return None
        body = dict(row.parameters or {})
        if method:
            body["method"] = method
        if staging_mode:
            body["staging_mode"] = staging_mode
        body["updated_at"] = _now()
        row.parameters = body
        flag_modified(row, "parameters")
        session.commit()
        session.refresh(row)
        return _read(row)


def listing(*, owner: int | None = None, limit: int = 25) -> list[Thread]:
    """Recent threads, newest first — the "Recent What-Ifs" panel §8.1 asks for."""
    from backend.models.platform import StressScenario

    with _session() as session:
        query = session.query(StressScenario).filter(
            StressScenario.version == STORE_VERSION[:24])
        if owner is not None:
            query = query.filter(StressScenario.created_by == owner)
        rows = query.order_by(StressScenario.id.desc()).limit(limit).all()
        return [_read(row) for row in rows]


def rename(thread_id: str, title: str, *,
           owner: int | None = None) -> Thread | None:
    with _session() as session:
        row = _find(session, thread_id, owner)
        if row is None:
            return None
        body = dict(row.parameters or {})
        row.name = f"{title[:160]} · {thread_id}"
        body["updated_at"] = _now()
        row.parameters = body
        session.commit()
        session.refresh(row)
        return _read(row)


def remove_last_result(thread_id: str, *,
                       owner: int | None = None) -> Thread | None:
    """Undo: drop the most recent result and the turn that asked for it.

    §8.3 lists Undo beside Remove Step and Reset to Baseline. Undo removes the
    last exchange; it does not roll the cohort back, because the cohort was
    never changed — a scenario is a reading of the book, not a write to it.
    """
    from sqlalchemy.orm.attributes import flag_modified

    with _session() as session:
        row = _find(session, thread_id, owner)
        if row is None:
            return None
        body = dict(row.parameters or {})
        turns = list(body.get("turns") or [])
        while turns and turns[-1].get("kind") != SAID:
            turns.pop()
        if turns:
            turns.pop()
        body["turns"] = turns
        body["updated_at"] = _now()
        row.parameters = body
        flag_modified(row, "parameters")
        session.commit()
        session.refresh(row)
        return _read(row)
