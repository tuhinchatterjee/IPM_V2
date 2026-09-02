"""
Sending something to a colleague, and knowing what happened to it.

The one rule the whole module is built around
----------------------------------------------
**Participation is authorization.** A `thread_participants` row is the only
thing that lets anybody read a thread. Not the sender, not a role, not a URL
somebody was given — the row. Every read path here starts by asking for it, and
a thread you are not in returns exactly what a thread that does not exist
returns, so an id cannot be probed for existence.

That has a consequence worth stating plainly: an ADMIN is not a participant in
other people's conversations. Administering users and reading their mail are
different powers, and collapsing them would make the inbox a place nobody says
anything real in. Where governance genuinely needs to see who sent what, the
audit log answers it without exposing bodies.

Drafts
------
A draft has no recipients. That is not an omission — the addressee list on an
unsent message is part of a private document, and writing `message_recipients`
at compose time would put a row in somebody's name for a message they may never
be sent. Recipients, participants and notifications are all written in one
transaction at SEND, which is also the moment the body stops being editable.

Attachments
-----------
Two kinds, and they are authorized differently.

* A **governed object** (investigation, analysis) is not copied. Sending it
  writes an `object_shares` grant and records what it looked like at the time.
  The sender must be able to read it themselves — you cannot share your way into
  giving away something you were never shown.
* A **file** is bytes this database holds, with a SHA-256. Downloading one
  requires participation in the thread it hangs off, checked per request rather
  than at attach time, so losing access to a thread loses access to its files.

System messages
---------------
CreditProbe is a sender, not a user. `sender_type = SYSTEM` with no
`sender_user_id`, enforced by a check constraint, so there is no account to log
into and no request body that can claim to be the product. System messages carry
an `event_key`: the same publication replayed after a restart hits a unique
index and is a no-op rather than a second copy in everyone's inbox.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select

from backend.config import settings
from backend.models.collaboration import (
    ATT_ANALYSIS,
    ATT_INVESTIGATION,
    ATTACHMENT_TYPES,
    MSG_DRAFT,
    MSG_SENT,
    PRIORITIES,
    PRIORITY_NORMAL,
    REQ_ACTION,
    REQ_CLOSED,
    REQ_FYI,
    REQ_IN_REVIEW,
    REQ_OPEN,
    REQ_RESPONDED,
    REQ_REVIEW,
    REQUEST_OPEN_STATES,
    REQUEST_STATES,
    REQUEST_TYPES,
    SENDER_SYSTEM,
    SENDER_USER,
    SHAREABLE_OBJECTS,
)

logger = logging.getLogger(__name__)

# What this module offers. The lifecycle VOCABULARY is not re-exported here:
# it belongs to `models.collaboration` and callers import it from there, so
# there is one place a state is named rather than two that can drift.
__all__ = [
    "ALLOWED_UPLOAD_TYPES", "ATT_ANALYSIS", "ATT_INVESTIGATION",
    "ATTACHMENT_TYPES", "BOX_ACTION", "BOX_ARCHIVED", "BOX_DRAFTS",
    "BOX_INBOX", "BOX_SENT", "SYSTEM_SENDER_NAME",
    "CollaborationUnavailable", "InvalidRequest", "NotFound", "NotPermitted",
    "audit", "can_read_object", "change_request_status", "create_draft",
    "data_release_recipients", "directory", "download_artifact",
    "download_artifact_view", "get_thread", "grant_share", "list_box",
    "mark_read", "publish_data_release_event", "request_history",
    "send_message", "send_system_message", "set_archived", "shared_with_me",
    "store_artifact", "store_artifact_view", "unread_count", "update_draft",
]

#: How the product signs its own messages. Never a provider name: the reader is
#: told which product spoke to them, and which foundation model produced the
#: text is an implementation detail they did not ask about and must not be shown.
SYSTEM_SENDER_NAME = "CreditProbe AI"

#: What a message body may be. Long enough for a real covering note, short
#: enough that the column is not a place somebody pastes a workbook.
MAX_BODY = 20_000
MAX_SUBJECT = 300
#: Enough for a quarter's workbook; beyond this the answer is a link to the
#: governed object, not a copy of it in a mailbox.
MAX_FILE_BYTES = 25 * 1024 * 1024

#: Formats a mailbox may carry. A whitelist, not a blacklist: the interesting
#: property is that nothing executable is on it, and a blacklist of executables
#: is a list somebody will always find one more item for.
ALLOWED_UPLOAD_TYPES: dict[str, str] = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": ("application/vnd.openxmlformats-officedocument"
              ".wordprocessingml.document"),
    ".txt": "text/plain",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

#: The states a request may move to from each state. "Reopen a closed request"
#: is not a workflow you reach by clicking carefully; it is a transition the
#: code refuses. Responded may still be closed by the requester.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    REQ_OPEN: (REQ_IN_REVIEW, REQ_RESPONDED, REQ_CLOSED),
    REQ_IN_REVIEW: (REQ_RESPONDED, REQ_CLOSED),
    REQ_RESPONDED: (REQ_CLOSED, REQ_IN_REVIEW),
    REQ_CLOSED: (),
}


# ==========================================================================
# Errors. Each maps to exactly one HTTP status in the router, so a caller
# never has to read a message to find out what went wrong.
# ==========================================================================


class CollaborationUnavailable(RuntimeError):
    """This capability needs PostgreSQL."""


class NotFound(LookupError):
    """It is not there, or it is not yours. Deliberately the same answer."""


class NotPermitted(PermissionError):
    """The caller may not do this to this."""


class InvalidRequest(ValueError):
    """The caller asked for something incoherent."""


def _require_db() -> None:
    if not settings.has_database:
        raise CollaborationUnavailable(
            "Messages need the application database, which is not configured "
            "here."
        )


def _now() -> datetime:
    return datetime.now(UTC)


# ==========================================================================
# Audit
# ==========================================================================

# Every action worth answering a question about later. Named constants rather
# than free strings at the call sites, so a typo is an ImportError rather than
# a row nobody will ever find again.
USER_CREATED = "USER_CREATED"
USER_UPDATED = "USER_UPDATED"
USER_DEACTIVATED = "USER_DEACTIVATED"
USER_REACTIVATED = "USER_REACTIVATED"
MESSAGE_SENT = "MESSAGE_SENT"
MESSAGE_READ = "MESSAGE_READ"
MESSAGE_ARCHIVED = "MESSAGE_ARCHIVED"
MESSAGE_REPLIED = "MESSAGE_REPLIED"
OBJECT_SHARED = "OBJECT_SHARED"
FILE_DOWNLOADED = "FILE_DOWNLOADED"
WORKFLOW_STATUS_CHANGED = "WORKFLOW_STATUS_CHANGED"
SYSTEM_NOTIFICATION_CREATED = "SYSTEM_NOTIFICATION_CREATED"


def audit(session: Any, action: str, *, actor_id: int | None = None,
          actor_type: str = SENDER_USER, object_type: str = "",
          object_id: str = "", subject_user_id: int | None = None,
          **detail: Any) -> None:
    """Write one audit row inside the caller's transaction.

    Inside the caller's transaction on purpose: an audit record that commits
    separately from the thing it describes can outlive a rolled-back action, and
    "the log says it happened and it did not" is worse than no log.
    """
    from backend.models.collaboration import CollaborationAudit

    session.add(CollaborationAudit(
        action=action, actor_type=actor_type, actor_id=actor_id,
        object_type=object_type, object_id=str(object_id),
        subject_user_id=subject_user_id, detail=detail or {},
    ))


# ==========================================================================
# People
# ==========================================================================


def _person(row: Any) -> dict[str, Any]:
    """A user, as a message shows them.

    Never the password hash, and never the raw role alone: a directory that
    shows four people all labelled ANALYST cannot tell a sender which of them
    owns the shipping book, so the job title is the primary label and the role
    is the secondary one.
    """
    if row is None:
        return {}
    full = f"{getattr(row, 'first_name', '')} {getattr(row, 'last_name', '')}"
    return {
        "id": row.id,
        "username": row.username,
        "name": full.strip() or row.username,
        "email": getattr(row, "email", "") or "",
        "job_title": getattr(row, "job_title", "") or "",
        "department": getattr(row, "department", "") or "",
        "team": getattr(row, "team", "") or "",
        "role": getattr(row, "role", "") or "",
        "is_active": bool(getattr(row, "is_active", True)),
    }


def _people(session: Any, ids: set[int]) -> dict[int, dict[str, Any]]:
    """Every named person in one query.

    An inbox names a sender per row. Looking each one up as the row is rendered
    is the N+1 that turns a 50-row page into 51 round trips, and it grows with
    the mailbox rather than with the schema.
    """
    from backend.db.models import User

    clean = {int(i) for i in ids if i}
    if not clean:
        return {}
    rows = session.execute(
        select(User).where(User.id.in_(clean))
    ).scalars().all()
    return {r.id: _person(r) for r in rows}


def directory(session: Any, *, query: str = "", limit: int = 50,
              include_inactive: bool = False) -> list[dict[str, Any]]:
    """Who a message can be addressed to.

    Suspended accounts are excluded by default. Offering somebody who cannot
    sign in as a recipient produces a message that is delivered and never read,
    which looks exactly like a message that was ignored.
    """
    from backend.db.models import User

    stmt = select(User)
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    text = (query or "").strip()
    if text:
        like = f"%{text.lower()}%"
        stmt = stmt.where(or_(
            func.lower(User.first_name).like(like),
            func.lower(User.last_name).like(like),
            func.lower(User.username).like(like),
            func.lower(User.email).like(like),
            func.lower(User.job_title).like(like),
            func.lower(User.department).like(like),
            func.lower(User.team).like(like),
            func.lower(User.role).like(like),
        ))
    rows = session.execute(
        stmt.order_by(User.first_name, User.last_name, User.username)
        .limit(max(1, min(int(limit or 50), 200)))
    ).scalars().all()
    return [_person(r) for r in rows]


# ==========================================================================
# Reading a thread
# ==========================================================================


def _participation(session: Any, thread_id: int, user_id: int) -> Any:
    """The row that says this person may read this thread, or None."""
    from backend.models.collaboration import ThreadParticipant

    return session.execute(
        select(ThreadParticipant).where(
            ThreadParticipant.thread_id == thread_id,
            ThreadParticipant.user_id == user_id,
        )
    ).scalars().first()


def _must_participate(session: Any, thread_id: int, user_id: int) -> Any:
    """Participation, or the same answer an absent thread gives.

    NotFound rather than NotPermitted, on purpose. "You may not read thread
    4193" confirms that thread 4193 exists and that somebody is talking in it,
    and an inbox that answers that question for strangers is an inbox that
    leaks its own shape.
    """
    row = _participation(session, thread_id, user_id)
    if row is None:
        raise NotFound(f"Thread {thread_id} is not available.")
    return row


def _attachment_view(row: Any, artifact: Any = None) -> dict[str, Any]:
    """One attachment card.

    `meta` is the snapshot taken at share time, not a fresh read of the object.
    A renamed investigation must not rewrite the history of what was sent, and
    "the card said Q2 2026" has to stay true after the thread moves on.
    """
    view = {
        "id": row.id,
        "type": row.attachment_type,
        "object_id": row.object_id or "",
        "object_version": row.object_version or "",
        "label": row.label or "",
        "meta": dict(row.meta or {}),
    }
    if artifact is not None:
        view["file"] = {
            "artifact_id": artifact.id,
            "filename": artifact.filename,
            "content_type": artifact.content_type,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
        }
    return view


def _message_view(row: Any, people: dict[int, dict[str, Any]],
                  artifacts: dict[int, Any]) -> dict[str, Any]:
    sender = (
        {"type": SENDER_SYSTEM, "name": SYSTEM_SENDER_NAME, "user": None}
        if row.sender_type == SENDER_SYSTEM
        else {"type": SENDER_USER,
              "name": (people.get(row.sender_user_id) or {}).get("name", ""),
              "user": people.get(row.sender_user_id)}
    )
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "parent_id": row.parent_id,
        "sender": sender,
        "body": row.body or "",
        "status": row.status,
        "request_type": row.request_type,
        "request_status": row.request_status,
        "priority": row.priority,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "actions": list(row.actions or []),
        "context": dict(row.context or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "recipients": [people.get(r.user_id) or {"id": r.user_id}
                       for r in row.recipients],
        "attachments": [
            _attachment_view(a, artifacts.get(a.artifact_id))
            for a in row.attachments
        ],
    }


def get_thread(session: Any, thread_id: int, *, user_id: int) -> dict[str, Any]:
    """One conversation, in full, for somebody entitled to read it."""
    from backend.models.collaboration import (
        Message,
        MessageArtifact,
        MessageThread,
        ThreadParticipant,
    )

    mine = _must_participate(session, thread_id, user_id)
    thread = session.get(MessageThread, thread_id)
    if thread is None:
        raise NotFound(f"Thread {thread_id} is not available.")

    messages = session.execute(
        select(Message).where(
            Message.thread_id == thread_id,
            # A draft is private to its author even inside a shared thread: a
            # half-written reply is not part of the conversation yet.
            or_(Message.status == MSG_SENT,
                Message.sender_user_id == user_id),
        ).order_by(Message.created_at, Message.id)
    ).scalars().all()

    participants = session.execute(
        select(ThreadParticipant).where(ThreadParticipant.thread_id == thread_id)
    ).scalars().all()

    ids = {m.sender_user_id for m in messages if m.sender_user_id}
    ids |= {p.user_id for p in participants}
    for m in messages:
        ids |= {r.user_id for r in m.recipients}
    people = _people(session, ids)

    artifact_ids = {a.artifact_id for m in messages for a in m.attachments
                    if a.artifact_id}
    artifacts = {
        a.id: a for a in session.execute(
            select(MessageArtifact).where(MessageArtifact.id.in_(artifact_ids))
        ).scalars().all()
    } if artifact_ids else {}

    return {
        "id": thread.id,
        "subject": thread.subject,
        "origin": thread.origin,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
        "last_message_at": (thread.last_message_at.isoformat()
                            if thread.last_message_at else None),
        "participants": [people.get(p.user_id) or {"id": p.user_id}
                         for p in participants],
        "messages": [_message_view(m, people, artifacts) for m in messages],
        "read_at": mine.read_at.isoformat() if mine.read_at else None,
        "archived": mine.archived_at is not None,
    }


# ==========================================================================
# Listing a mailbox
# ==========================================================================

#: The four mailboxes. Not folders a message is moved between — views over the
#: same rows, which is why archiving one person's copy leaves everyone else's
#: inbox alone.
BOX_INBOX = "inbox"
BOX_SENT = "sent"
BOX_DRAFTS = "drafts"
BOX_ARCHIVED = "archived"
BOX_ACTION = "action"
BOXES = (BOX_INBOX, BOX_SENT, BOX_DRAFTS, BOX_ARCHIVED, BOX_ACTION)


def _summary(thread: Any, last: Any, mine: Any, people: dict[int, Any],
             counts: dict[int, int]) -> dict[str, Any]:
    """One inbox row.

    Deliberately without message bodies beyond a short preview and without any
    attachment bytes: a 50-row inbox that loads 50 workbooks to draw itself is
    a page nobody waits for.
    """
    sender = (
        {"type": SENDER_SYSTEM, "name": SYSTEM_SENDER_NAME, "user": None}
        if last is None or last.sender_type == SENDER_SYSTEM
        else {"type": SENDER_USER,
              "name": (people.get(last.sender_user_id) or {}).get("name", ""),
              "user": people.get(last.sender_user_id)}
    )
    body = (last.body if last is not None else "") or ""
    preview = " ".join(body.split())[:180]
    return {
        "thread_id": thread.id,
        "subject": thread.subject,
        "origin": thread.origin,
        "sender": sender,
        "preview": preview,
        "message_count": thread.message_count,
        "attachment_count": counts.get(thread.id, 0),
        "attachment_types": sorted({
            a.attachment_type for a in (last.attachments if last else [])
        }),
        "request_type": last.request_type if last is not None else REQ_FYI,
        "request_status": last.request_status if last is not None else None,
        "priority": last.priority if last is not None else PRIORITY_NORMAL,
        "due_at": (last.due_at.isoformat()
                   if last is not None and last.due_at else None),
        "last_message_at": (thread.last_message_at.isoformat()
                            if thread.last_message_at else None),
        "unread": mine is not None and mine.read_at is None,
        "archived": mine is not None and mine.archived_at is not None,
    }


def _thread_summaries(session: Any, thread_ids: list[int], user_id: int,
                      ) -> list[dict[str, Any]]:
    """Summaries for a page of threads, in a fixed number of queries.

    Four, whatever the page size: the threads, my participation, the last sent
    message of each, and the people named. The alternative walks the ORM
    relationship per row and turns a page into a hundred round trips.
    """
    from backend.models.collaboration import (
        Message,
        MessageAttachment,
        MessageThread,
        ThreadParticipant,
    )

    if not thread_ids:
        return []
    threads = {
        t.id: t for t in session.execute(
            select(MessageThread).where(MessageThread.id.in_(thread_ids))
        ).scalars().all()
    }
    mine = {
        p.thread_id: p for p in session.execute(
            select(ThreadParticipant).where(
                ThreadParticipant.thread_id.in_(thread_ids),
                ThreadParticipant.user_id == user_id,
            )
        ).scalars().all()
    }
    # The newest SENT message per thread. A draft reply must not become the
    # preview line of a conversation other people are looking at.
    newest = session.execute(
        select(Message.thread_id, func.max(Message.id))
        .where(Message.thread_id.in_(thread_ids), Message.status == MSG_SENT)
        .group_by(Message.thread_id)
    ).all()
    last_ids = [row[1] for row in newest if row[1]]
    lasts = {
        m.thread_id: m for m in session.execute(
            select(Message).where(Message.id.in_(last_ids))
        ).scalars().all()
    } if last_ids else {}

    counts = dict(session.execute(
        select(Message.thread_id, func.count(MessageAttachment.id))
        .join(MessageAttachment, MessageAttachment.message_id == Message.id)
        .where(Message.thread_id.in_(thread_ids), Message.status == MSG_SENT)
        .group_by(Message.thread_id)
    ).all())

    people = _people(session, {m.sender_user_id for m in lasts.values()
                               if m.sender_user_id})
    out = []
    for tid in thread_ids:
        thread = threads.get(tid)
        if thread is not None:
            out.append(_summary(thread, lasts.get(tid), mine.get(tid),
                                people, counts))
    return out


def list_box(session: Any, *, user_id: int, box: str = BOX_INBOX,
             limit: int = 50, offset: int = 0, query: str = "",
             unread_only: bool = False,
             attachment_type: str = "") -> dict[str, Any]:
    """One mailbox, paginated.

    `sent` and `drafts` are message-shaped; the rest are thread-shaped. Sent
    lists what you sent even after the thread has moved on, which is a
    different question from "what is happening in my conversations".
    """
    from backend.models.collaboration import (
        Message,
        MessageAttachment,
        MessageRecipient,
        MessageThread,
        ThreadParticipant,
    )

    box = (box or BOX_INBOX).strip().lower()
    if box not in BOXES:
        raise InvalidRequest(f"'{box}' is not a mailbox.")
    limit = max(1, min(int(limit or 50), 100))
    offset = max(0, int(offset or 0))

    if box == BOX_DRAFTS:
        stmt = select(Message).where(
            Message.sender_user_id == user_id, Message.status == MSG_DRAFT
        ).order_by(Message.created_at.desc())
        rows = session.execute(stmt.limit(limit).offset(offset)).scalars().all()
        total = session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        threads = {
            t.id: t for t in session.execute(
                select(MessageThread).where(
                    MessageThread.id.in_([r.thread_id for r in rows])
                )
            ).scalars().all()
        } if rows else {}
        return {
            "box": box, "total": int(total), "limit": limit, "offset": offset,
            "items": [{
                "message_id": r.id,
                "thread_id": r.thread_id,
                "subject": (threads.get(r.thread_id).subject
                            if threads.get(r.thread_id) else ""),
                "preview": " ".join((r.body or "").split())[:180],
                "attachment_count": len(r.attachments),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in rows],
        }

    if box == BOX_SENT:
        stmt = select(Message).where(
            Message.sender_user_id == user_id, Message.status == MSG_SENT
        ).order_by(Message.sent_at.desc(), Message.id.desc())
        rows = session.execute(stmt.limit(limit).offset(offset)).scalars().all()
        total = session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        threads = {
            t.id: t for t in session.execute(
                select(MessageThread).where(
                    MessageThread.id.in_([r.thread_id for r in rows])
                )
            ).scalars().all()
        } if rows else {}
        ids: set[int] = set()
        for r in rows:
            ids |= {x.user_id for x in r.recipients}
        people = _people(session, ids)
        return {
            "box": box, "total": int(total), "limit": limit, "offset": offset,
            "items": [{
                "message_id": r.id,
                "thread_id": r.thread_id,
                "subject": (threads.get(r.thread_id).subject
                            if threads.get(r.thread_id) else ""),
                "preview": " ".join((r.body or "").split())[:180],
                "recipients": [people.get(x.user_id) or {"id": x.user_id}
                               for x in r.recipients],
                "attachment_count": len(r.attachments),
                "attachment_types": sorted({a.attachment_type
                                            for a in r.attachments}),
                "request_type": r.request_type,
                "request_status": r.request_status,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            } for r in rows],
        }

    # inbox | archived | action — all thread views over my participation.
    stmt = (
        select(MessageThread.id)
        .join(ThreadParticipant,
              ThreadParticipant.thread_id == MessageThread.id)
        .where(ThreadParticipant.user_id == user_id,
               ThreadParticipant.addressed.is_(True))
    )
    if box == BOX_ARCHIVED:
        stmt = stmt.where(ThreadParticipant.archived_at.is_not(None))
    else:
        stmt = stmt.where(ThreadParticipant.archived_at.is_(None))
    if unread_only:
        stmt = stmt.where(ThreadParticipant.read_at.is_(None))
    if box == BOX_ACTION:
        # A request addressed to me that nobody has closed. Joined against
        # `message_recipients` rather than participation, because being copied
        # into a thread is not the same as being asked to do something.
        stmt = stmt.where(MessageThread.id.in_(
            select(Message.thread_id)
            .join(MessageRecipient, MessageRecipient.message_id == Message.id)
            .where(MessageRecipient.user_id == user_id,
                   Message.status == MSG_SENT,
                   Message.request_type.in_((REQ_REVIEW, REQ_ACTION)),
                   Message.request_status.in_(REQUEST_OPEN_STATES))
        ))
    if attachment_type:
        if attachment_type not in ATTACHMENT_TYPES:
            raise InvalidRequest(f"'{attachment_type}' is not an attachment type.")
        stmt = stmt.where(MessageThread.id.in_(
            select(Message.thread_id)
            .join(MessageAttachment, MessageAttachment.message_id == Message.id)
            .where(MessageAttachment.attachment_type == attachment_type,
                   Message.status == MSG_SENT)
        ))
    text = (query or "").strip()
    if text:
        like = f"%{text.lower()}%"
        # Subject, body and attachment label — and always inside the
        # participation join above, so search can never surface a thread the
        # searcher is not in.
        stmt = stmt.where(or_(
            func.lower(MessageThread.subject).like(like),
            MessageThread.id.in_(
                select(Message.thread_id).where(
                    Message.status == MSG_SENT,
                    func.lower(Message.body).like(like))
            ),
            MessageThread.id.in_(
                select(Message.thread_id)
                .join(MessageAttachment,
                      MessageAttachment.message_id == Message.id)
                .where(func.lower(MessageAttachment.label).like(like))
            ),
        ))

    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    ordered = session.execute(
        stmt.order_by(MessageThread.last_message_at.desc(),
                      MessageThread.id.desc())
        .limit(limit).offset(offset)
    ).scalars().all()
    return {
        "box": box, "total": int(total), "limit": limit, "offset": offset,
        "items": _thread_summaries(session, list(ordered), user_id),
    }


def unread_count(session: Any, user_id: int) -> dict[str, int]:
    """The badge. Three numbers a personal dashboard reconciles to."""
    from backend.models.collaboration import (
        Message,
        MessageRecipient,
        ObjectShare,
        ThreadParticipant,
    )

    unread = session.execute(
        select(func.count()).select_from(ThreadParticipant).where(
            ThreadParticipant.user_id == user_id,
            ThreadParticipant.addressed.is_(True),
            ThreadParticipant.archived_at.is_(None),
            ThreadParticipant.read_at.is_(None),
        )
    ).scalar_one()
    action = session.execute(
        select(func.count(func.distinct(Message.id)))
        .join(MessageRecipient, MessageRecipient.message_id == Message.id)
        .where(MessageRecipient.user_id == user_id,
               Message.status == MSG_SENT,
               Message.request_type.in_((REQ_REVIEW, REQ_ACTION)),
               Message.request_status.in_(REQUEST_OPEN_STATES))
    ).scalar_one()
    shared = session.execute(
        select(func.count()).select_from(ObjectShare).where(
            ObjectShare.user_id == user_id, ObjectShare.revoked_at.is_(None)
        )
    ).scalar_one()
    return {"unread": int(unread), "action_required": int(action),
            "shared_with_me": int(shared)}


# ==========================================================================
# Attaching things
# ==========================================================================


def _investigation_card(session: Any, object_id: str,
                        viewer_id: int) -> tuple[dict[str, Any], str]:
    """The snapshot an investigation attachment carries, and its version.

    Raises NotPermitted when the would-be sender cannot read it themselves.
    You cannot share your way into giving away something you were never shown,
    and checking that at ATTACH time means the refusal names the object rather
    than arriving as a silent gap in the recipient's inbox.
    """
    from backend.models.platform import Investigation

    row = session.get(Investigation, int(object_id))
    if row is None:
        raise NotFound(f"Investigation {object_id} does not exist.")
    if not can_read_object(session, ATT_INVESTIGATION, object_id, viewer_id):
        raise NotPermitted(
            "You cannot share an investigation you do not have access to."
        )
    context = dict(row.context or {})
    scope = dict(row.scope or {})
    owner = _people(session, {row.owner_id} if row.owner_id else set())
    return ({
        "title": row.title,
        "owner": (owner.get(row.owner_id) or {}).get("name", ""),
        "period": (context.get("to_period") or context.get("period")
                   or scope.get("to_period") or ""),
        "from_period": context.get("from_period") or scope.get("from_period") or "",
        "domain": context.get("domain") or "",
        "status": row.status,
        "message_count": row.message_count,
        "updated_at": (row.last_message_at.isoformat()
                       if row.last_message_at else None),
    }, str(row.current_version or 1))


def _analysis_card(session: Any, object_id: str,
                   viewer_id: int) -> tuple[dict[str, Any], str]:
    """The snapshot an analysis attachment carries, and its version."""
    from backend.models.platform import SavedAnalysis

    row = session.get(SavedAnalysis, int(object_id))
    if row is None:
        raise NotFound(f"Analysis {object_id} does not exist.")
    if not can_read_object(session, ATT_ANALYSIS, object_id, viewer_id):
        raise NotPermitted(
            "You cannot share an analysis you do not have access to."
        )
    period = dict(row.period or {})
    return ({
        "title": row.title,
        "analysis_id": row.analysis_id,
        "certification": row.certification,
        "period": period.get("period") or period.get("to_period") or "",
        "from_period": period.get("from_period") or "",
        "scope": ", ".join(str(v) for v in (row.filters or {}).values()) or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }, str(row.analysis_version or ""))


#: How each governed object describes itself on a card. A registry rather than
#: a chain of ifs, so adding a shareable object type is one entry and cannot
#: half-exist — a type with no reader here simply cannot be attached.
OBJECT_CARDS = {
    ATT_INVESTIGATION: _investigation_card,
    ATT_ANALYSIS: _analysis_card,
}


def can_read_object(session: Any, object_type: str, object_id: str,
                    user_id: int) -> bool:
    """Whether this person may open this governed object, right now.

    Three ways in, checked in this order because the cheapest and most common
    is first: you own it, it was explicitly shared with you, or you are an
    administrator. Note what is NOT here — being sent a message about it. The
    message records that it was shared; the SHARE decides whether you may read
    it, and revoking the share closes the door while the message stays as
    evidence that it was once open.
    """
    from backend.db.models import User
    from backend.models.collaboration import ObjectShare
    from backend.models.platform import Investigation, SavedAnalysis

    if not user_id:
        return False
    owner_id = None
    if object_type == ATT_INVESTIGATION:
        row = session.get(Investigation, int(object_id))
        owner_id = getattr(row, "owner_id", None) if row is not None else None
        if row is None:
            return False
    elif object_type == ATT_ANALYSIS:
        row = session.get(SavedAnalysis, int(object_id))
        if row is None:
            return False
        # A saved analysis records no owner column of its own; it inherits the
        # investigation it came out of, and a standalone one is readable by
        # anyone who may run analyses. Treated as "no owner" here rather than
        # invented, so the share grant and the admin path still decide.
        inv = (session.get(Investigation, row.investigation_id)
               if row.investigation_id else None)
        owner_id = getattr(inv, "owner_id", None) if inv is not None else None
    else:
        return False

    if owner_id is not None and int(owner_id) == int(user_id):
        return True
    share = session.execute(
        select(ObjectShare).where(
            ObjectShare.object_type == object_type,
            ObjectShare.object_id == str(object_id),
            ObjectShare.user_id == user_id,
            ObjectShare.revoked_at.is_(None),
        )
    ).scalars().first()
    if share is not None:
        return True
    if owner_id is None:
        # Nobody owns it. An unowned object is one nothing has claimed, and
        # refusing everybody would make older rows permanently unshareable.
        return True
    caller = session.get(User, user_id)
    return bool(caller is not None
                and str(caller.role or "").upper() == "ADMIN")


def store_artifact(session: Any, *, filename: str, content: bytes,
                   created_by: int | None, content_type: str = "",
                   source_object_type: str = "",
                   source_object_id: str = "") -> Any:
    """Put bytes in the database and hand back the row.

    Whitelisted by extension, capped by size, hashed. The whitelist is the
    security control and the hash is the governance one: neither substitutes
    for the other.
    """
    from backend.models.collaboration import MessageArtifact

    name = (filename or "").strip().replace("\\", "/").split("/")[-1]
    if not name:
        raise InvalidRequest("A file needs a name.")
    suffix = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if suffix not in ALLOWED_UPLOAD_TYPES:
        raise InvalidRequest(
            f"'{suffix or name}' is not a format CreditProbe accepts. "
            f"Allowed: {', '.join(sorted(ALLOWED_UPLOAD_TYPES))}."
        )
    if not content:
        raise InvalidRequest("The file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise InvalidRequest(
            f"That file is {len(content) // (1024 * 1024)} MB. The limit is "
            f"{MAX_FILE_BYTES // (1024 * 1024)} MB."
        )
    row = MessageArtifact(
        filename=name,
        content_type=content_type or ALLOWED_UPLOAD_TYPES[suffix],
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        source_object_type=source_object_type,
        source_object_id=str(source_object_id or ""),
        created_by=created_by,
    )
    session.add(row)
    session.flush()
    return row


def _attach(session: Any, message: Any, spec: dict[str, Any],
            sender_id: int) -> Any:
    """One attachment, validated and snapshotted.

    A governed object is looked up and read-checked here; a file is resolved to
    an artifact the sender owns. Either way the row that lands carries the label
    and metadata AS THEY WERE, because the card is a record of what was sent
    rather than a live view of what the object has since become.
    """
    from backend.models.collaboration import MessageArtifact, MessageAttachment

    kind = str(spec.get("type") or "").strip().lower()
    if kind not in ATTACHMENT_TYPES:
        raise InvalidRequest(f"'{kind}' is not something you can attach.")

    if kind in SHAREABLE_OBJECTS:
        object_id = str(spec.get("object_id") or "").strip()
        if not object_id:
            raise InvalidRequest(f"A {kind} attachment needs an id.")
        meta, version = OBJECT_CARDS[kind](session, object_id, sender_id)
        row = MessageAttachment(
            message_id=message.id, attachment_type=kind, object_id=object_id,
            object_version=version, label=meta.get("title") or f"{kind} {object_id}",
            meta=meta,
        )
        session.add(row)
        return row

    # report | file — both resolve to stored bytes.
    artifact_id = spec.get("artifact_id")
    if not artifact_id:
        raise InvalidRequest(f"A {kind} attachment needs an uploaded file.")
    artifact = session.get(MessageArtifact, int(artifact_id))
    if artifact is None:
        raise NotFound(f"File {artifact_id} does not exist.")
    if artifact.created_by is not None and int(artifact.created_by) != int(sender_id):
        # Attaching somebody else's stored bytes by guessing an id is the
        # cheapest way to exfiltrate a file out of a thread you are not in.
        raise NotPermitted("That file is not yours to attach.")
    row = MessageAttachment(
        message_id=message.id, attachment_type=kind,
        object_id="", object_version="", artifact_id=artifact.id,
        label=str(spec.get("label") or artifact.filename),
        meta={"filename": artifact.filename, "size_bytes": artifact.size_bytes,
              "content_type": artifact.content_type,
              "source_object_type": artifact.source_object_type,
              "source_object_id": artifact.source_object_id},
    )
    session.add(row)
    return row


# ==========================================================================
# Composing and sending
# ==========================================================================


def _clean_body(text: str) -> str:
    """The body, as text and only as text.

    No markup is interpreted anywhere in this feature: the composer takes plain
    text with paragraphs, and the renderer prints it. Stripping tags here as
    well as escaping at render time is belt and braces on the one input in the
    product that one user writes and another user's browser displays.
    """
    import re

    body = str(text or "")
    if len(body) > MAX_BODY:
        raise InvalidRequest(
            f"That message is {len(body):,} characters. The limit is "
            f"{MAX_BODY:,}."
        )
    # Anything that looks like a tag becomes visible text rather than markup.
    body = re.sub(r"<[^>]{0,200}>", "", body)
    return body.strip()


def _clean_subject(text: str) -> str:
    subject = " ".join(str(text or "").split())[:MAX_SUBJECT]
    if not subject:
        raise InvalidRequest("A message needs a subject.")
    import re
    return re.sub(r"<[^>]{0,200}>", "", subject).strip() or "(no subject)"


def _resolve_recipients(session: Any, user_ids: list[int],
                        sender_id: int) -> list[Any]:
    """The people a message may actually be sent to.

    A suspended account is refused rather than silently dropped: a sender who
    is told "delivered" and was not is worse off than one who is told the
    person has left.
    """
    from backend.db.models import User

    wanted = []
    seen: set[int] = set()
    for raw in user_ids or []:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            raise InvalidRequest(f"'{raw}' is not a user.") from None
        if uid in seen or uid == int(sender_id):
            # Addressing yourself is a no-op, not an error: the sender is
            # already a participant and would otherwise get their own message
            # in their own inbox.
            continue
        seen.add(uid)
        wanted.append(uid)
    if not wanted:
        raise InvalidRequest("A message needs at least one recipient.")
    rows = session.execute(
        select(User).where(User.id.in_(wanted))
    ).scalars().all()
    found = {r.id: r for r in rows}
    missing = [u for u in wanted if u not in found]
    if missing:
        raise InvalidRequest(f"No such user: {', '.join(str(m) for m in missing)}.")
    inactive = [found[u] for u in wanted if not found[u].is_active]
    if inactive:
        names = ", ".join(r.username for r in inactive)
        raise InvalidRequest(
            f"{names} no longer has an active account and cannot be sent work."
        )
    return [found[u] for u in wanted]


def create_draft(session: Any, *, sender_id: int, subject: str = "",
                 body: str = "", thread_id: int | None = None) -> dict[str, Any]:
    """Start a message nobody can see but its author.

    A draft in a NEW conversation still needs a thread — the subject lives
    there — so one is created with the author as its only participant. Nobody
    else is added until it is sent, which is what keeps an abandoned draft out
    of everybody's inbox.
    """
    from backend.models.collaboration import (
        Message,
        MessageThread,
        ThreadParticipant,
    )

    if thread_id is not None:
        _must_participate(session, int(thread_id), sender_id)
        thread = session.get(MessageThread, int(thread_id))
    else:
        thread = MessageThread(
            subject=_clean_subject(subject or "(no subject)"),
            created_by=sender_id, origin=SENDER_USER,
        )
        session.add(thread)
        session.flush()
        session.add(ThreadParticipant(
            thread_id=thread.id, user_id=sender_id, addressed=False,
            read_at=_now(),
        ))

    message = Message(
        thread_id=thread.id, sender_type=SENDER_USER, sender_user_id=sender_id,
        body=_clean_body(body), status=MSG_DRAFT,
    )
    session.add(message)
    session.flush()
    return {"message_id": message.id, "thread_id": thread.id,
            "subject": thread.subject, "status": MSG_DRAFT}


def update_draft(session: Any, message_id: int, *, user_id: int,
                 subject: str | None = None, body: str | None = None,
                 attachments: list[dict[str, Any]] | None = None,
                 ) -> dict[str, Any]:
    """Rewrite an unsent message. Only its author, and only while unsent."""
    from backend.models.collaboration import (
        Message,
        MessageAttachment,
        MessageThread,
    )

    row = session.get(Message, int(message_id))
    if row is None or row.sender_user_id != user_id or row.status != MSG_DRAFT:
        # One answer for "not there", "not yours" and "already sent". A draft
        # is private, so confirming that somebody else's exists is a leak.
        raise NotFound(f"Draft {message_id} is not available.")
    if body is not None:
        row.body = _clean_body(body)
    if subject is not None:
        thread = session.get(MessageThread, row.thread_id)
        if thread is not None and thread.message_count == 0:
            # Only before the conversation has started. Renaming a thread
            # other people have already replied in rewrites their history.
            thread.subject = _clean_subject(subject)
    if attachments is not None:
        session.execute(
            MessageAttachment.__table__.delete().where(
                MessageAttachment.message_id == row.id)
        )
        session.flush()
        for spec in attachments:
            _attach(session, row, spec, user_id)
    session.flush()
    return {"message_id": row.id, "thread_id": row.thread_id,
            "status": row.status}


def send_message(session: Any, *, sender_id: int, to: list[int],
                 subject: str = "", body: str = "",
                 attachments: list[dict[str, Any]] | None = None,
                 cc: list[int] | None = None,
                 request_type: str = REQ_FYI,
                 priority: str = PRIORITY_NORMAL,
                 due_at: datetime | None = None,
                 thread_id: int | None = None,
                 draft_id: int | None = None) -> dict[str, Any]:
    """Send one message. The whole act, in one transaction.

    Recipients, participation, attachments, share grants, the notification and
    the audit row all land together or none of them do. A message that is
    delivered but grants no access to what it carries, or one whose recipient
    never gets a badge, is a half-sent message — and half-sent is the state
    this function exists to make unreachable.
    """
    from backend.models.collaboration import (
        Message,
        MessageRecipient,
        MessageThread,
        ThreadParticipant,
    )

    request_type = (request_type or REQ_FYI).strip().lower()
    if request_type not in REQUEST_TYPES:
        raise InvalidRequest(f"'{request_type}' is not a kind of request.")
    priority = (priority or PRIORITY_NORMAL).strip().lower()
    if priority not in PRIORITIES:
        raise InvalidRequest(f"'{priority}' is not a priority.")

    people = _resolve_recipients(session, list(to or []), sender_id)
    copied = ([p for p in _resolve_recipients(session, list(cc), sender_id)
               if p.id not in {r.id for r in people}] if cc else [])

    if draft_id is not None:
        message = session.get(Message, int(draft_id))
        if (message is None or message.sender_user_id != sender_id
                or message.status != MSG_DRAFT):
            raise NotFound(f"Draft {draft_id} is not available.")
        thread = session.get(MessageThread, message.thread_id)
        if body:
            message.body = _clean_body(body)
    elif thread_id is not None:
        _must_participate(session, int(thread_id), sender_id)
        thread = session.get(MessageThread, int(thread_id))
        message = Message(thread_id=thread.id, sender_type=SENDER_USER,
                          sender_user_id=sender_id, body=_clean_body(body))
        session.add(message)
    else:
        thread = MessageThread(subject=_clean_subject(subject),
                               created_by=sender_id, origin=SENDER_USER)
        session.add(thread)
        session.flush()
        session.add(ThreadParticipant(thread_id=thread.id, user_id=sender_id,
                                      addressed=False, read_at=_now()))
        message = Message(thread_id=thread.id, sender_type=SENDER_USER,
                          sender_user_id=sender_id, body=_clean_body(body))
        session.add(message)

    if thread is None:
        raise NotFound("That conversation is not available.")
    session.flush()

    if subject and thread.message_count == 0 and draft_id is not None:
        thread.subject = _clean_subject(subject)

    message.status = MSG_SENT
    message.sent_at = _now()
    message.request_type = request_type
    message.request_status = (None if request_type == REQ_FYI else REQ_OPEN)
    message.priority = priority
    message.due_at = due_at

    if attachments is not None:
        from backend.models.collaboration import MessageAttachment
        session.execute(
            MessageAttachment.__table__.delete().where(
                MessageAttachment.message_id == message.id)
        )
        session.flush()
        for spec in attachments:
            _attach(session, message, spec, sender_id)
    session.flush()

    everyone = people + copied
    for person, kind in ([(p, "to") for p in people]
                         + [(p, "cc") for p in copied]):
        session.add(MessageRecipient(message_id=message.id, user_id=person.id,
                                     kind=kind))
        existing = _participation(session, thread.id, person.id)
        if existing is None:
            session.add(ThreadParticipant(thread_id=thread.id,
                                          user_id=person.id, addressed=True))
        else:
            # A new message makes an old thread unread again, and un-archives
            # it: filing a conversation away is a statement about what has
            # happened so far, not a subscription cancelled for ever.
            existing.addressed = True
            existing.read_at = None
            existing.archived_at = None

    thread.message_count = (thread.message_count or 0) + 1
    thread.last_message_at = message.sent_at

    # Share grants for every governed object carried.
    for attachment in message.attachments:
        if attachment.attachment_type in SHAREABLE_OBJECTS:
            for person in everyone:
                grant_share(session, object_type=attachment.attachment_type,
                            object_id=attachment.object_id, user_id=person.id,
                            granted_by=sender_id, message_id=message.id,
                            object_version=attachment.object_version)

    _notify_recipients(session, message, thread, everyone)
    if request_type != REQ_FYI:
        from backend.models.collaboration import RequestStatusEvent
        session.add(RequestStatusEvent(message_id=message.id, from_status=None,
                                       to_status=REQ_OPEN, actor_id=sender_id,
                                       note="Requested"))
    audit(session, MESSAGE_REPLIED if thread.message_count > 1 else MESSAGE_SENT,
          actor_id=sender_id, object_type="message", object_id=str(message.id),
          thread_id=thread.id, request_type=request_type,
          recipients=[p.id for p in everyone],
          attachments=[{"type": a.attachment_type, "object_id": a.object_id,
                        "artifact_id": a.artifact_id}
                       for a in message.attachments])
    session.flush()
    return {"message_id": message.id, "thread_id": thread.id,
            "subject": thread.subject, "status": MSG_SENT,
            "recipients": [p.id for p in everyone]}


def _notify_recipients(session: Any, message: Any, thread: Any,
                       people: list[Any]) -> None:
    """The bell count, through the notification table everything else uses.

    Not a second notification system. The badge in the header already reads
    `notifications`, and a messaging feature that invented its own counter
    would give the product two numbers that disagree.
    """
    from backend.models.platform import Notification

    sender = (SYSTEM_SENDER_NAME if message.sender_type == SENDER_SYSTEM
              else (_people(session, {message.sender_user_id})
                    .get(message.sender_user_id, {}).get("name", "")))
    kind = ("assigned" if message.request_type in (REQ_REVIEW, REQ_ACTION)
            else "shared")
    for person in people:
        session.add(Notification(
            user_id=person.id, kind=kind, title=thread.subject,
            body=f"From {sender}" if sender else "",
            object_type="message_thread", object_id=str(thread.id),
            actor_id=message.sender_user_id,
        ))


def mark_read(session: Any, thread_id: int, *, user_id: int,
              read: bool = True) -> dict[str, Any]:
    """Read or unread, for one person only."""
    mine = _must_participate(session, thread_id, user_id)
    mine.read_at = _now() if read else None
    mine.last_seen_at = _now()
    if read:
        audit(session, MESSAGE_READ, actor_id=user_id,
              object_type="message_thread", object_id=str(thread_id))
    session.flush()
    return {"thread_id": thread_id, "read": read}


def set_archived(session: Any, thread_id: int, *, user_id: int,
                 archived: bool = True) -> dict[str, Any]:
    """File a conversation away, or take it back out. Personal, not shared."""
    mine = _must_participate(session, thread_id, user_id)
    mine.archived_at = _now() if archived else None
    audit(session, MESSAGE_ARCHIVED, actor_id=user_id,
          object_type="message_thread", object_id=str(thread_id),
          archived=archived)
    session.flush()
    return {"thread_id": thread_id, "archived": archived}


# ==========================================================================
# Sharing and workflow
# ==========================================================================


def grant_share(session: Any, *, object_type: str, object_id: str,
                user_id: int, granted_by: int | None,
                message_id: int | None = None,
                object_version: str = "") -> Any:
    """Record that this person may now open this object.

    Idempotent: sharing the same investigation with the same person twice is
    one grant, un-revoked. The audit log keeps both acts.
    """
    from backend.models.collaboration import ObjectShare

    existing = session.execute(
        select(ObjectShare).where(
            ObjectShare.object_type == object_type,
            ObjectShare.object_id == str(object_id),
            ObjectShare.user_id == user_id,
        )
    ).scalars().first()
    if existing is not None:
        existing.revoked_at = None
        row = existing
    else:
        row = ObjectShare(object_type=object_type, object_id=str(object_id),
                          user_id=user_id, granted_by=granted_by,
                          message_id=message_id, object_version=object_version)
        session.add(row)
    audit(session, OBJECT_SHARED, actor_id=granted_by, object_type=object_type,
          object_id=str(object_id), subject_user_id=user_id,
          message_id=message_id, object_version=object_version)
    session.flush()
    return row


def shared_with_me(session: Any, user_id: int,
                   limit: int = 25) -> list[dict[str, Any]]:
    """What other people have given this person access to.

    Read back through the same card readers the attachment used, so the entry
    on the dashboard and the card in the message describe the object the same
    way. An object whose card can no longer be built — deleted, or access since
    revoked — is skipped rather than shown as a broken row.
    """
    from backend.models.collaboration import ObjectShare

    rows = session.execute(
        select(ObjectShare).where(
            ObjectShare.user_id == user_id, ObjectShare.revoked_at.is_(None)
        ).order_by(ObjectShare.created_at.desc()).limit(max(1, int(limit)))
    ).scalars().all()
    out: list[dict[str, Any]] = []
    granters = _people(session, {r.granted_by for r in rows if r.granted_by})
    for row in rows:
        reader = OBJECT_CARDS.get(row.object_type)
        if reader is None:
            continue
        try:
            meta, _ = reader(session, row.object_id, user_id)
        except (NotFound, NotPermitted, ValueError):
            continue
        out.append({
            "object_type": row.object_type,
            "object_id": row.object_id,
            "object_version": row.object_version,
            "label": meta.get("title") or "",
            "meta": meta,
            "shared_by": (granters.get(row.granted_by) or {}).get("name", ""),
            "shared_at": row.created_at.isoformat() if row.created_at else None,
        })
    return out


def change_request_status(session: Any, message_id: int, *, user_id: int,
                          status: str, note: str = "") -> dict[str, Any]:
    """Move a review or action request along, and record who moved it.

    Only a participant may. Only through a transition the state machine
    allows. And every move writes an event, because "it says Responded" is a
    much weaker fact than "she moved it to Responded on the 4th, saying this".
    """
    from backend.models.collaboration import Message, RequestStatusEvent

    row = session.get(Message, int(message_id))
    if row is None or row.status != MSG_SENT:
        raise NotFound(f"Request {message_id} is not available.")
    _must_participate(session, row.thread_id, user_id)
    if row.request_type == REQ_FYI or row.request_status is None:
        raise InvalidRequest("That message did not ask for anything.")
    status = (status or "").strip().lower()
    if status not in REQUEST_STATES:
        raise InvalidRequest(f"'{status}' is not a status.")
    allowed = ALLOWED_TRANSITIONS.get(row.request_status, ())
    if status not in allowed:
        raise InvalidRequest(
            f"A {row.request_status.replace('_', ' ')} request cannot become "
            f"{status.replace('_', ' ')}."
            + (f" It can become: {', '.join(a.replace('_', ' ') for a in allowed)}."
               if allowed else " It is closed.")
        )
    previous, row.request_status = row.request_status, status
    session.add(RequestStatusEvent(message_id=row.id, from_status=previous,
                                   to_status=status, actor_id=user_id,
                                   note=_clean_body(note)[:2000]))
    audit(session, WORKFLOW_STATUS_CHANGED, actor_id=user_id,
          object_type="message", object_id=str(row.id),
          from_status=previous, to_status=status)

    # Tell the person who asked. A status that changes silently is a status
    # the requester has to go and look for.
    if row.sender_user_id and row.sender_user_id != user_id:
        from backend.models.platform import Notification
        thread = row.thread
        actor = _people(session, {user_id}).get(user_id, {}).get("name", "")
        session.add(Notification(
            user_id=row.sender_user_id, kind="approved" if status == REQ_CLOSED
            else "commented",
            title=f"{thread.subject} — {status.replace('_', ' ')}",
            body=f"{actor} moved your request to {status.replace('_', ' ')}."
                 if actor else "",
            object_type="message_thread", object_id=str(row.thread_id),
            actor_id=user_id,
        ))
    session.flush()
    return {"message_id": row.id, "request_status": status,
            "previous_status": previous}


def request_history(session: Any, message_id: int,
                    *, user_id: int) -> list[dict[str, Any]]:
    """Every transition of one request, oldest first."""
    from backend.models.collaboration import Message, RequestStatusEvent

    row = session.get(Message, int(message_id))
    if row is None:
        raise NotFound(f"Request {message_id} is not available.")
    _must_participate(session, row.thread_id, user_id)
    events = session.execute(
        select(RequestStatusEvent)
        .where(RequestStatusEvent.message_id == row.id)
        .order_by(RequestStatusEvent.created_at, RequestStatusEvent.id)
    ).scalars().all()
    actors = _people(session, {e.actor_id for e in events if e.actor_id})
    return [{
        "from_status": e.from_status,
        "to_status": e.to_status,
        "actor": (actors.get(e.actor_id) or {}).get("name", ""),
        "note": e.note,
        "at": e.created_at.isoformat() if e.created_at else None,
    } for e in events]


def download_artifact(session: Any, artifact_id: int,
                      *, user_id: int) -> tuple[Any, bytes]:
    """The bytes of an attached file, for somebody entitled to them.

    Entitlement is checked HERE, per request, not at attach time: a file is
    downloadable because you are in a thread it hangs off today. Its creator
    may always fetch their own upload back.
    """
    from backend.models.collaboration import (
        Message,
        MessageArtifact,
        MessageAttachment,
        ThreadParticipant,
    )

    artifact = session.get(MessageArtifact, int(artifact_id))
    if artifact is None:
        raise NotFound(f"File {artifact_id} is not available.")
    allowed = (artifact.created_by is not None
               and int(artifact.created_by) == int(user_id))
    if not allowed:
        allowed = session.execute(
            select(func.count())
            .select_from(MessageAttachment)
            .join(Message, Message.id == MessageAttachment.message_id)
            .join(ThreadParticipant,
                  ThreadParticipant.thread_id == Message.thread_id)
            .where(MessageAttachment.artifact_id == artifact.id,
                   Message.status == MSG_SENT,
                   ThreadParticipant.user_id == user_id)
        ).scalar_one() > 0
    if not allowed:
        # Same answer as an absent file. Confirming that artifact 91 exists
        # tells a prober they have found something real.
        raise NotFound(f"File {artifact_id} is not available.")
    audit(session, FILE_DOWNLOADED, actor_id=user_id, object_type="artifact",
          object_id=str(artifact.id), filename=artifact.filename,
          sha256=artifact.sha256)
    session.flush()
    return artifact, artifact.content


# ==========================================================================
# CreditProbe as a sender
# ==========================================================================

#: The governed events that can produce a message. A closed list: a system
#: message is a promise that something happened, and an event nobody has
#: designed a message for should raise rather than invent one.
EVENT_DATA_RELEASE_PUBLISHED = "DATA_RELEASE_PUBLISHED"
EVENT_ANALYSIS_SHARED = "ANALYSIS_SHARED"
EVENT_INVESTIGATION_SHARED = "INVESTIGATION_SHARED"
EVENT_REPORT_SHARED = "REPORT_SHARED"
EVENT_REVIEW_REQUESTED = "WORKFLOW_REVIEW_REQUESTED"
EVENT_STATUS_CHANGED = "WORKFLOW_STATUS_CHANGED"
SYSTEM_EVENTS = (
    EVENT_DATA_RELEASE_PUBLISHED, EVENT_ANALYSIS_SHARED,
    EVENT_INVESTIGATION_SHARED, EVENT_REPORT_SHARED,
    EVENT_REVIEW_REQUESTED, EVENT_STATUS_CHANGED,
)


def send_system_message(session: Any, *, event: str, event_key: str,
                        subject: str, body: str, recipients: list[int],
                        actions: list[dict[str, Any]] | None = None,
                        context: dict[str, Any] | None = None,
                        attachments: list[dict[str, Any]] | None = None,
                        ) -> dict[str, Any]:
    """CreditProbe writes to somebody. The only way it can.

    `event_key` is the idempotency. A publication that is retried, or replayed
    after a restart, produces the same key, hits the unique index and returns
    the message that already exists — nobody is told twice. That is checked
    here AND enforced by the schema, because a service that is the only guard
    is a service somebody will eventually call from a second place.

    No `sender_user_id` is accepted. There is no parameter for it, the column is
    NULL, and the check constraint refuses the row if it were not: the product
    cannot be impersonated by naming a user, because naming a user is not
    something this function can do.
    """
    from backend.models.collaboration import (
        Message,
        MessageRecipient,
        MessageThread,
        ThreadParticipant,
    )

    if event not in SYSTEM_EVENTS:
        raise InvalidRequest(f"'{event}' is not a governed event.")
    key = f"{event}:{str(event_key or '').strip()}"
    if not event_key:
        raise InvalidRequest("A system message needs a stable event key.")

    existing = session.execute(
        select(Message).where(Message.event_key == key)
    ).scalars().first()
    if existing is not None:
        return {"message_id": existing.id, "thread_id": existing.thread_id,
                "created": False, "event_key": key}

    people = [
        r for r in session.execute(
            select_users_active(list(recipients))
        ).scalars().all()
    ] if recipients else []
    if not people:
        raise InvalidRequest(
            "A system message needs at least one active recipient."
        )

    thread = MessageThread(subject=_clean_subject(subject), created_by=None,
                           origin=SENDER_SYSTEM)
    session.add(thread)
    session.flush()

    message = Message(
        thread_id=thread.id, sender_type=SENDER_SYSTEM, sender_user_id=None,
        body=_clean_body(body), status=MSG_SENT, sent_at=_now(),
        request_type=REQ_FYI, request_status=None, event_key=key,
        actions=list(actions or []), context=dict(context or {}),
    )
    session.add(message)
    session.flush()

    for spec in (attachments or []):
        # A system attachment is snapshotted with no sender to read-check
        # against, so only stored artifacts are permitted here. Granting a
        # governed object on the product's own authority would be exactly the
        # silent permission escalation the design forbids.
        if str(spec.get("type")) in SHAREABLE_OBJECTS:
            raise InvalidRequest(
                "A system message may not grant access to a governed object."
            )
        _attach(session, message, spec, sender_id=0)

    for person in people:
        session.add(MessageRecipient(message_id=message.id, user_id=person.id,
                                     kind="to"))
        session.add(ThreadParticipant(thread_id=thread.id, user_id=person.id,
                                      addressed=True))
    thread.message_count = 1
    thread.last_message_at = message.sent_at

    _notify_recipients(session, message, thread, people)
    audit(session, SYSTEM_NOTIFICATION_CREATED, actor_id=None,
          actor_type=SENDER_SYSTEM, object_type="message",
          object_id=str(message.id), event=event, event_key=key,
          recipients=[p.id for p in people])
    session.flush()
    return {"message_id": message.id, "thread_id": thread.id, "created": True,
            "event_key": key}


def select_users_active(user_ids: list[int]):
    """Statement: the active users among these ids."""
    from backend.db.models import User

    clean = {int(u) for u in user_ids if u}
    return select(User).where(User.id.in_(clean or {-1}),
                              User.is_active.is_(True))


def data_release_recipients(session: Any, *,
                            explicit: list[int] | None = None) -> list[int]:
    """Who hears about a new governed data release.

    The mechanism chosen for this first implementation, and the reason:

    * If the publisher named people, those people. An explicit choice at
      publication time is the most accurate signal there is, and it is the one
      the existing Data Builder screen can carry with the least new surface.
    * Otherwise, everyone holding a role that can act on new data — ADMIN and
      DATA_STEWARD, who govern it, and ANALYST, who analyse it. A VIEWER is not
      notified: they can read what others produce, and a dataset arriving is not
      a thing they can do anything about.

    Not "everybody", on purpose. A notification everyone receives about
    everything is a notification everyone learns to dismiss, and the first
    thing that gets dismissed with it is the one that mattered.
    """
    from backend.db.models import User

    if explicit:
        rows = session.execute(select_users_active(list(explicit))).scalars().all()
        return [r.id for r in rows]
    rows = session.execute(
        select(User).where(
            User.is_active.is_(True),
            func.upper(User.role).in_(("ADMIN", "DATA_STEWARD", "ANALYST")),
        )
    ).scalars().all()
    return [r.id for r in rows]


def publish_data_release_event(
    session: Any, *, dataset: str, dataset_label: str = "", period: str = "",
    previous_period: str = "", version: str = "", row_count: int | None = None,
    borrower_count: int | None = None, published_at: str = "",
    published_by_id: int | None = None, validated: bool | None = None,
    recipients: list[int] | None = None, domain: str = "",
) -> dict[str, Any]:
    """THE HOOK Data Builder calls when a governed release goes live.

    This is the integration contract for Data Builder 2.0. Call it once, after
    the release is durable, with the facts the publication actually produced.
    Everything it needs is a parameter; nothing is looked up behind the caller's
    back, and nothing is composed:

    * `row_count` and `borrower_count` appear only if they are given. A count
      nobody supplied is absent from the message, not estimated. The rule that
      matters here is that a reader must be able to trust a number in a
      CreditProbe message the way they trust one in an answer.
    * `validated` prints "validated and published" only when it is True. None
      means the publisher did not say, and the message says the narrower thing.
    * An action button appears only when the product can honour it. "Compare
      with the previous quarter" needs a previous period; without one the button
      is simply not offered, rather than offered and then apologised for.

    Idempotent through `event_key`: dataset + version, or dataset + period when
    the publication is not versioned. Replaying a publication after a restart
    returns the existing message.
    """
    label = dataset_label or dataset.replace("_", " ").title()
    key = f"{dataset}:{version or period or 'latest'}"

    facts: list[str] = []
    if row_count is not None:
        facts.append(f"{int(row_count):,} records")
    if borrower_count is not None:
        facts.append(f"{int(borrower_count):,} borrowers")

    lines = [f"{label}{f' — {period}' if period else ''}", ""]
    lines.append(
        "The dataset has been validated and published, and is now available "
        "for governed analysis."
        if validated
        else "The dataset has been published and is now available for "
             "governed analysis."
    )
    if facts:
        lines += ["", " · ".join(facts)]
    if published_by_id:
        who = _people(session, {published_by_id}).get(published_by_id, {})
        if who.get("name"):
            lines += ["", f"Published by {who['name']}"]
    if published_at:
        lines.append(f"Published {published_at}")

    actions: list[dict[str, Any]] = [{
        "action": "open_dataset",
        "label": "Open Dataset",
        "href": f"/data-builder/browse?dataset={dataset}",
    }, {
        "action": "start_investigation",
        "label": "Start Investigation",
        # Structured context, not decorative text: the Cockpit composer opens
        # pre-filled with a question about THIS dataset at THIS period.
        "href": ("/?focus=ask&q=" + _quote(
            f"What changed in {label}"
            + (f" in {period}?" if period else "?"))),
        "context": {"dataset": dataset, "domain": domain, "period": period},
    }]
    if previous_period and period:
        actions.append({
            "action": "compare_previous_period",
            "label": "Compare with Previous Period",
            "href": ("/?focus=ask&q=" + _quote(
                f"Compare {label} between {previous_period} and {period}.")),
            "context": {"dataset": dataset, "domain": domain,
                        "from_period": previous_period, "to_period": period},
        })

    return send_system_message(
        session,
        event=EVENT_DATA_RELEASE_PUBLISHED,
        event_key=key,
        subject=f"New {label} data is available"
                + (f" — {period}" if period else ""),
        body="\n".join(lines),
        recipients=data_release_recipients(session, explicit=recipients),
        actions=actions,
        context={
            "dataset": dataset, "dataset_label": label, "domain": domain,
            "period": period, "previous_period": previous_period,
            "version": version, "row_count": row_count,
            "borrower_count": borrower_count, "validated": validated,
            "published_at": published_at,
        },
    )


def _quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text, safe="")


# ==========================================================================
# Plain-dict wrappers for the API
# ==========================================================================
#
# The session closes when the router's transaction ends, and a detached ORM
# instance raises on attribute access afterwards. Anything a route returns has
# to be a plain structure built while the session is still open, so these two
# exist rather than letting the router touch rows it cannot safely read.


def store_artifact_view(session: Any, **kwargs: Any) -> dict[str, Any]:
    """Store a file and describe it. Never returns the bytes."""
    row = store_artifact(session, **kwargs)
    return {"id": row.id, "filename": row.filename,
            "content_type": row.content_type, "size_bytes": row.size_bytes,
            "sha256": row.sha256}


def download_artifact_view(session: Any, artifact_id: int,
                           *, user_id: int) -> dict[str, Any]:
    """The bytes and what to call them, for an entitled caller."""
    artifact, content = download_artifact(session, artifact_id,
                                          user_id=user_id)
    return {"content": content, "filename": artifact.filename,
            "content_type": artifact.content_type, "sha256": artifact.sha256}
