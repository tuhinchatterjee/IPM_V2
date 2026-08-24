"""
Investigations as conversations.

Where this sits in the hierarchy
--------------------------------
    Analysis   < Investigation < Project
    one result   a conversation   a body of work

An Investigation is a THREAD: a question, the answer, the follow-up, the answer
to that, and so on. It is where thinking happens. Each answer inside it is
produced by the same executor that answers a one-off question, so nothing about
being in a thread changes how a figure is calculated.

Two things a thread remembers
-----------------------------
1. **What was said.** Every user message and every assistant answer, in order,
   with the assistant's messages carrying the full answer payload — the metrics,
   the analyses used, the interpretation, the Trace — so re-opening a thread
   shows exactly what was shown at the time rather than a re-run.

2. **What was settled.** `Investigation.context` holds the data domain and the
   period the thread has agreed on. CreditProbe asks a clarifying question ONCE
   per thread; after that the settled context is passed into every subsequent
   answer. Asking "which quarter did you mean?" on the fourth follow-up, having
   been told on the first, is the single most irritating thing an assistant can
   do, and it is entirely avoidable.

What this module does not do
----------------------------
It does not calculate. It does not summarise figures. It stores what happened
and hands questions to the executor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"

#: How many characters of a first question become the thread's default title.
TITLE_CHARS = 90


class ThreadNotFound(LookupError):
    pass


class StorageUnavailable(RuntimeError):
    """Keeping a conversation needs PostgreSQL. Asking does not."""


def _require_db() -> None:
    if not settings.has_database:
        raise StorageUnavailable(
            "Investigations are stored in PostgreSQL. Questions can still be "
            "asked and answered without it; the conversation just is not kept."
        )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _title_from(question: str) -> str:
    text = " ".join((question or "").split())
    if len(text) <= TITLE_CHARS:
        return text or "Untitled investigation"
    return text[:TITLE_CHARS].rsplit(" ", 1)[0] + "…"


# -------------------------------------------------------------------- shape


@dataclass
class MessageView:
    id: int
    sequence: int
    role: str
    content: str
    payload: dict[str, Any] = field(default_factory=dict)
    analysis_run_id: int | None = None
    created_by: int | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sequence": self.sequence,
            "role": self.role,
            "content": self.content,
            "payload": self.payload,
            "analysis_run_id": self.analysis_run_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass
class ThreadView:
    id: int
    title: str
    question: str
    status: str
    project_id: int | None
    owner_id: int | None
    context: dict[str, Any] = field(default_factory=dict)
    message_count: int = 0
    last_message_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "question": self.question,
            "status": self.status,
            "project_id": self.project_id,
            "owner_id": self.owner_id,
            "context": self.context,
            "message_count": self.message_count,
            "last_message_at": self.last_message_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
        }


def _message_view(row: Any) -> MessageView:
    return MessageView(
        id=row.id,
        sequence=row.sequence,
        role=row.role,
        content=row.content,
        payload=dict(row.payload or {}),
        analysis_run_id=row.analysis_run_id,
        created_by=row.created_by,
        created_at=_iso(row.created_at),
    )


def _thread_view(session: Any, row: Any, *, with_messages: bool = True) -> ThreadView:
    from sqlalchemy import select

    from backend.models.platform import InvestigationMessage

    messages: list[dict[str, Any]] = []
    if with_messages:
        rows = session.execute(
            select(InvestigationMessage)
            .where(InvestigationMessage.investigation_id == row.id)
            .order_by(InvestigationMessage.sequence)
        ).scalars().all()
        messages = [_message_view(m).to_dict() for m in rows]

    return ThreadView(
        id=row.id,
        title=row.title,
        question=row.question,
        status=row.status,
        project_id=row.project_id,
        owner_id=row.owner_id,
        context=dict(row.context or {}),
        message_count=row.message_count,
        last_message_at=_iso(row.last_message_at),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        messages=messages,
    )


# ------------------------------------------------------------------- context


def settled_period(context: dict[str, Any]) -> tuple[str, str] | None:
    """The comparison this thread has already agreed on, if it has agreed one.

    Returned in the shape the executor takes, so a follow-up inherits the
    period without the user being asked a second time.
    """
    from_period = (context or {}).get("from_period")
    to_period = (context or {}).get("to_period")
    if from_period and to_period:
        return str(from_period), str(to_period)
    return None


def _merged_context(existing: dict[str, Any], scope: Any) -> dict[str, Any]:
    """Carry forward what the thread knows, updated by what this answer settled.

    Only non-empty values overwrite. An answer that did not need a period must
    not erase the period the thread already agreed.
    """
    out = dict(existing or {})
    for key in ("from_period", "to_period", "period_source", "domain", "family"):
        value = getattr(scope, key, None)
        if value:
            out[key] = value
    filters = getattr(scope, "filters", None)
    if filters:
        out["filters"] = {**dict(out.get("filters") or {}), **dict(filters)}
    return out


# ------------------------------------------------------------------ writing


def create(*, question: str, title: str = "", project_id: int | None = None,
           user_id: int | None = None,
           context: dict[str, Any] | None = None) -> ThreadView:
    """Start a thread with its opening question. No answer yet."""
    _require_db()
    from sqlalchemy import func

    from backend.db.engine import get_session
    from backend.models.platform import (
        INV_LIVE,
        Investigation,
        InvestigationMessage,
        Project,
    )

    seed = dict(context or {})
    with get_session() as session:
        # A thread inside a project inherits the project's standing context,
        # so "this project is about the SME book" only has to be said once.
        if project_id is not None:
            project = session.get(Project, project_id)
            if project is not None:
                seed = {**dict(project.default_context or {}), **seed}

        row = Investigation(
            project_id=project_id,
            title=(title or _title_from(question))[:300],
            question=question,
            scope={},
            plan={},
            context=seed,
            status=INV_LIVE,
            owner_id=user_id,
            current_version=1,
            message_count=1,
        )
        session.add(row)
        session.flush()
        session.add(InvestigationMessage(
            investigation_id=row.id, sequence=0, role=ROLE_USER,
            content=question, payload={}, created_by=user_id,
        ))
        session.flush()
        row.last_message_at = func.now()
        session.commit()
        return _thread_view(session, row)


def append(thread_id: int, *, role: str, content: str,
           payload: dict[str, Any] | None = None,
           analysis_run_id: int | None = None,
           user_id: int | None = None) -> MessageView:
    """Add one message to the end of a thread."""
    _require_db()
    from sqlalchemy import func, select

    from backend.db.engine import get_session
    from backend.models.platform import Investigation, InvestigationMessage

    if role not in (ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM):
        raise ValueError(f"'{role}' is not a message role.")

    with get_session() as session:
        row = session.get(Investigation, thread_id)
        if row is None:
            raise ThreadNotFound(f"Investigation {thread_id} does not exist.")

        # The next sequence comes from the table, not from a counter that could
        # have drifted. The unique constraint on (investigation_id, sequence)
        # then makes a genuine race fail loudly rather than silently reorder.
        highest = session.execute(
            select(func.max(InvestigationMessage.sequence))
            .where(InvestigationMessage.investigation_id == thread_id)
        ).scalar()
        message = InvestigationMessage(
            investigation_id=thread_id,
            sequence=0 if highest is None else int(highest) + 1,
            role=role,
            content=content,
            payload=dict(payload or {}),
            analysis_run_id=analysis_run_id,
            created_by=user_id,
        )
        session.add(message)
        session.flush()
        row.message_count = (row.message_count or 0) + 1
        row.last_message_at = func.now()
        session.commit()
        return _message_view(message)


def record_answer(thread_id: int, run: Any, *,
                  user_id: int | None = None) -> MessageView:
    """Store an executed answer as the next assistant message.

    The whole run is kept, not a summary of it: the metrics the engine
    returned, the analyses used, the interpretation and the Trace. Re-opening a
    thread then shows what was actually shown, rather than a fresh calculation
    quietly presented as the original.
    """
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Investigation

    payload = run.to_dict() if hasattr(run, "to_dict") else dict(run)
    narrative = payload.get("narrative") or {}
    content = str(narrative.get("direct_answer") or narrative.get("summary") or "")

    message = append(
        thread_id,
        role=ROLE_ASSISTANT,
        content=content,
        payload=payload,
        analysis_run_id=payload.get("analysis_run_id"),
        user_id=user_id,
    )

    # Whatever this answer settled, the thread now knows. A clarification that
    # was answered here is not asked again on the next follow-up.
    scope = getattr(getattr(run, "plan", None), "scope", None)
    if scope is not None:
        with get_session() as session:
            row = session.get(Investigation, thread_id)
            if row is not None:
                row.context = _merged_context(row.context, scope)
                row.scope = scope.to_dict() if hasattr(scope, "to_dict") else {}
                row.plan = payload.get("plan") or {}
                session.commit()
    return message


def ask(thread_id: int, question: str, *, user_id: int | None = None,
        period: tuple[str, str] | None = None) -> dict[str, Any]:
    """Ask the next question in a thread and store both sides of the exchange.

    The thread's settled period is used unless the caller supplies one, which is
    what stops CreditProbe re-asking a clarification it has already had answered.
    """
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Investigation
    from backend.orchestration.executor import run_investigation

    with get_session() as session:
        row = session.get(Investigation, thread_id)
        if row is None:
            raise ThreadNotFound(f"Investigation {thread_id} does not exist.")
        context = dict(row.context or {})
        project_id = row.project_id

    append(thread_id, role=ROLE_USER, content=question, user_id=user_id)

    window = period or settled_period(context)
    result = run_investigation(
        question, user_id=user_id, project_id=project_id,
        chat_id=thread_id, persist=True, period=window,
    )

    if result.status == "needs_clarification":
        # A question CreditProbe cannot answer yet is still part of the
        # conversation, so it is stored — but it settles nothing, so the
        # thread's context is left exactly as it was.
        payload = result.to_dict()
        clarification = payload.get("clarification") or {}
        append(
            thread_id,
            role=ROLE_ASSISTANT,
            content=str(clarification.get("question") or "One thing first."),
            payload=payload,
            user_id=user_id,
        )
        return {"status": "needs_clarification", "run": payload,
                "thread": load(thread_id).to_dict()}

    record_answer(thread_id, result, user_id=user_id)
    return {"status": result.status, "run": result.to_dict(),
            "thread": load(thread_id).to_dict()}


def set_context(thread_id: int, context: dict[str, Any]) -> ThreadView:
    """Record what the thread has settled — usually an answered clarification."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Investigation

    with get_session() as session:
        row = session.get(Investigation, thread_id)
        if row is None:
            raise ThreadNotFound(f"Investigation {thread_id} does not exist.")
        row.context = {**dict(row.context or {}), **dict(context or {})}
        session.commit()
        return _thread_view(session, row, with_messages=False)


def rename(thread_id: int, title: str) -> ThreadView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Investigation

    with get_session() as session:
        row = session.get(Investigation, thread_id)
        if row is None:
            raise ThreadNotFound(f"Investigation {thread_id} does not exist.")
        row.title = (title or row.title)[:300]
        session.commit()
        return _thread_view(session, row, with_messages=False)


def move(thread_id: int, *, project_id: int | None) -> ThreadView:
    """File a thread under a project, or take it out of one."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Investigation, Project

    with get_session() as session:
        row = session.get(Investigation, thread_id)
        if row is None:
            raise ThreadNotFound(f"Investigation {thread_id} does not exist.")
        if project_id is not None and session.get(Project, project_id) is None:
            raise ThreadNotFound(f"Project {project_id} does not exist.")
        row.project_id = project_id
        session.commit()
        return _thread_view(session, row, with_messages=False)


def archive(thread_id: int) -> ThreadView:
    """Take a thread off the working list. Nothing is deleted."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import INV_ARCHIVED, Investigation

    with get_session() as session:
        row = session.get(Investigation, thread_id)
        if row is None:
            raise ThreadNotFound(f"Investigation {thread_id} does not exist.")
        row.status = INV_ARCHIVED
        session.commit()
        return _thread_view(session, row, with_messages=False)


# ------------------------------------------------------------------ reading


def load(thread_id: int) -> ThreadView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Investigation

    with get_session() as session:
        row = session.get(Investigation, thread_id)
        if row is None:
            raise ThreadNotFound(f"Investigation {thread_id} does not exist.")
        return _thread_view(session, row)


def listing(*, project_id: int | None = None, owner_id: int | None = None,
            include_archived: bool = False,
            limit: int = 50) -> list[dict[str, Any]]:
    """Threads, most recently spoken in first, with a one-line preview."""
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import (
        INV_ARCHIVED,
        Investigation,
        InvestigationMessage,
    )

    with get_session() as session:
        query = (
            select(Investigation)
            .order_by(Investigation.updated_at.desc())
            .limit(limit)
        )
        if project_id is not None:
            query = query.where(Investigation.project_id == project_id)
        if owner_id is not None:
            query = query.where(Investigation.owner_id == owner_id)
        if not include_archived:
            query = query.where(Investigation.status != INV_ARCHIVED)
        rows = session.execute(query).scalars().all()

        out: list[dict[str, Any]] = []
        for row in rows:
            last = session.execute(
                select(InvestigationMessage)
                .where(
                    InvestigationMessage.investigation_id == row.id,
                    InvestigationMessage.role == ROLE_ASSISTANT,
                )
                .order_by(InvestigationMessage.sequence.desc())
            ).scalars().first()
            out.append({
                "id": row.id,
                "title": row.title,
                "question": row.question,
                "status": row.status,
                "project_id": row.project_id,
                "owner_id": row.owner_id,
                "context": dict(row.context or {}),
                "message_count": row.message_count,
                "last_answer": last.content if last else "",
                "last_message_at": _iso(row.last_message_at),
                "updated_at": _iso(row.updated_at),
            })
        return out


__all__ = [
    "MessageView",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "ROLE_USER",
    "StorageUnavailable",
    "ThreadNotFound",
    "ThreadView",
    "append",
    "archive",
    "ask",
    "create",
    "listing",
    "load",
    "move",
    "record_answer",
    "rename",
    "set_context",
    "settled_period",
]
