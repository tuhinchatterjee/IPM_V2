"""
Sending work to someone, and knowing when it comes back.

An analysis that only its author ever sees is not governance. The point of this
module is the short institutional loop credit risk actually runs on:

    someone produces something  ->  sends it for review
    the reviewer comments       ->  approves or rejects
    the author is told          ->  and the decision is on the record for ever

Two rules shape everything below.

**The history is append-only.** A workflow item has a current state, and every
transition into it is written as its own row with the actor, the time and the
comment. A decision is evidence; editing it would make the record worthless. So
there is no update path for events — only inserts.

**A transition that makes no sense is refused.** ALLOWED below is the whole
state machine. "Approve something that was withdrawn" is not a workflow you can
reach by clicking carefully; it is a state the code will not enter.

Notifications are in-app only, on purpose. Email and push are a deployment
decision with their own approvals; what the product owes a user is that work
assigned to them is visible the moment they open CreditProbe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.config import settings
from backend.models.platform import (
    WF_APPROVED,
    WF_DRAFT,
    WF_IN_REVIEW,
    WF_OPEN_STATES,
    WF_REJECTED,
    WF_SUBMITTED,
    WF_WITHDRAWN,
)

logger = logging.getLogger(__name__)


class WorkflowUnavailable(RuntimeError):
    """Workflow needs PostgreSQL."""


class InvalidTransition(ValueError):
    """A state change the workflow does not permit."""


class WorkflowNotFound(LookupError):
    pass


#: The whole state machine. A state not listed as a destination cannot be
#: reached, whatever the caller asks for.
ALLOWED: dict[str, set[str]] = {
    WF_DRAFT: {WF_SUBMITTED, WF_WITHDRAWN},
    WF_SUBMITTED: {WF_IN_REVIEW, WF_APPROVED, WF_REJECTED, WF_WITHDRAWN},
    WF_IN_REVIEW: {WF_APPROVED, WF_REJECTED, WF_WITHDRAWN},
    # An approval or a rejection is final for that submission. Wanting another
    # look means submitting again, which creates a new item and leaves the first
    # decision standing.
    WF_APPROVED: set(),
    WF_REJECTED: set(),
    WF_WITHDRAWN: set(),
}

#: What a state means, in the language of the person reading it.
STATE_LABEL: dict[str, str] = {
    WF_DRAFT: "Draft",
    WF_SUBMITTED: "Awaiting review",
    WF_IN_REVIEW: "In review",
    WF_APPROVED: "Approved",
    WF_REJECTED: "Changes requested",
    WF_WITHDRAWN: "Withdrawn",
}

#: The objects that can be sent for review. Anything else is refused, so a
#: workflow can never point at something the product cannot open.
REVIEWABLE = {
    "project": "Project",
    "investigation": "Investigation",
    "analysis": "Engine analysis",
    "dataset": "Dataset",
    "scenario": "Stress scenario",
    "document": "Document",
}


def _require_db() -> None:
    if not settings.has_database:
        raise WorkflowUnavailable(
            "Review and approval need PostgreSQL. Analysis works without it; "
            "sending something for review does not."
        )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass
class WorkflowView:
    """One workflow item and its full decision history."""

    id: int
    object_type: str
    object_id: str
    title: str
    state: str
    state_label: str
    requested_by: int | None
    assigned_to: int | None
    due_at: str | None
    created_at: str | None
    updated_at: str | None
    events: list[dict[str, Any]]
    next_states: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "title": self.title,
            "state": self.state,
            "state_label": self.state_label,
            "requested_by": self.requested_by,
            "assigned_to": self.assigned_to,
            "due_at": self.due_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "events": self.events,
            "next_states": self.next_states,
            "next_state_labels": {s: STATE_LABEL[s] for s in self.next_states},
        }


def _view(session: Any, item: Any) -> WorkflowView:
    from sqlalchemy import select

    from backend.models.platform import WorkflowEvent

    events = session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.workflow_item_id == item.id)
        .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
    ).scalars().all()

    return WorkflowView(
        id=item.id,
        object_type=item.object_type,
        object_id=item.object_id,
        title=item.title,
        state=item.state,
        state_label=STATE_LABEL.get(item.state, item.state),
        requested_by=item.requested_by,
        assigned_to=item.assigned_to,
        due_at=_iso(item.due_at),
        created_at=_iso(item.created_at),
        updated_at=_iso(item.updated_at),
        events=[
            {
                "from_state": e.from_state,
                "to_state": e.to_state,
                "to_state_label": STATE_LABEL.get(e.to_state, e.to_state),
                "actor_id": e.actor_id,
                "comment": e.comment,
                "created_at": _iso(e.created_at),
            }
            for e in events
        ],
        next_states=sorted(ALLOWED.get(item.state, set())),
    )


def submit(*, object_type: str, object_id: str, title: str,
           assigned_to: int | None, requested_by: int | None = None,
           note: str = "") -> WorkflowView:
    """Send something for review, and tell the reviewer."""
    _require_db()
    if object_type not in REVIEWABLE:
        raise InvalidTransition(
            f"'{object_type}' cannot be sent for review. "
            f"Reviewable objects: {', '.join(sorted(REVIEWABLE))}."
        )

    from backend.db.engine import get_session
    from backend.models.platform import WorkflowEvent, WorkflowItem

    with get_session() as session:
        item = WorkflowItem(
            object_type=object_type,
            object_id=str(object_id),
            title=title[:300],
            state=WF_SUBMITTED,
            requested_by=requested_by,
            assigned_to=assigned_to,
        )
        session.add(item)
        session.flush()
        session.add(WorkflowEvent(
            workflow_item_id=item.id, from_state=WF_DRAFT, to_state=WF_SUBMITTED,
            actor_id=requested_by, comment=note,
        ))
        if assigned_to:
            _notify(
                session,
                user_id=assigned_to,
                kind="assigned",
                title=f"Review requested: {title}"[:300],
                body=note,
                object_type=object_type,
                object_id=str(object_id),
                actor_id=requested_by,
            )
        session.commit()
        return _view(session, item)


def transition(item_id: int, to_state: str, *, actor_id: int | None = None,
               comment: str = "") -> WorkflowView:
    """Move a workflow item, if the state machine allows it."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import WorkflowEvent, WorkflowItem

    with get_session() as session:
        item = session.get(WorkflowItem, item_id)
        if item is None:
            raise WorkflowNotFound(f"Workflow item {item_id} does not exist.")

        permitted = ALLOWED.get(item.state, set())
        if to_state not in permitted:
            raise InvalidTransition(
                f"'{STATE_LABEL.get(item.state, item.state)}' cannot become "
                f"'{STATE_LABEL.get(to_state, to_state)}'. "
                + (
                    f"Permitted from here: "
                    f"{', '.join(STATE_LABEL[s] for s in sorted(permitted))}."
                    if permitted else "This item is closed."
                )
            )

        previous = item.state
        item.state = to_state
        session.add(WorkflowEvent(
            workflow_item_id=item.id, from_state=previous, to_state=to_state,
            actor_id=actor_id, comment=comment,
        ))

        # The person who asked for the review is the one who needs the outcome.
        if item.requested_by and to_state in (WF_APPROVED, WF_REJECTED):
            _notify(
                session,
                user_id=item.requested_by,
                kind=to_state,
                title=f"{STATE_LABEL[to_state]}: {item.title}"[:300],
                body=comment,
                object_type=item.object_type,
                object_id=item.object_id,
                actor_id=actor_id,
            )
        session.commit()
        view = _view(session, item)
        object_type, object_id = item.object_type, item.object_id

    # A project's status is not a label somebody types; it follows the review.
    # The reviewer deciding is what takes it out of "In review", so the landing
    # status is recorded here rather than left for the interface to guess.
    if object_type == "project" and to_state in (WF_APPROVED, WF_REJECTED):
        from backend.services import projects as pj

        try:
            pj.review_decided(int(object_id), approved=to_state == WF_APPROVED,
                              actor_id=actor_id, note=comment)
        except (pj.ProjectNotFound, ValueError):  # pragma: no cover - deleted project
            logger.warning("Review decided for missing project %s", object_id)
    return view


def get(item_id: int) -> WorkflowView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import WorkflowItem

    with get_session() as session:
        item = session.get(WorkflowItem, item_id)
        if item is None:
            raise WorkflowNotFound(f"Workflow item {item_id} does not exist.")
        return _view(session, item)


def inbox(user_id: int | None) -> dict[str, list[dict[str, Any]]]:
    """The three lists a Workflow Inbox is made of.

    My work      — open and assigned to me. What I have to do.
    Sent by me   — open and requested by me. What I am waiting on.
    Completed    — closed, either way, that I was part of.
    """
    if not settings.has_database or user_id is None:
        return {"my_work": [], "sent_by_me": [], "completed": []}

    from sqlalchemy import or_, select

    from backend.db.engine import get_session
    from backend.models.platform import WorkflowItem

    def row(item: Any) -> dict[str, Any]:
        return {
            "id": item.id,
            "object_type": item.object_type,
            "object_type_label": REVIEWABLE.get(item.object_type, item.object_type),
            "object_id": item.object_id,
            "title": item.title,
            "state": item.state,
            "state_label": STATE_LABEL.get(item.state, item.state),
            "requested_by": item.requested_by,
            "assigned_to": item.assigned_to,
            "due_at": _iso(item.due_at),
            "updated_at": _iso(item.updated_at),
        }

    with get_session() as session:
        def fetch(*where: Any) -> list[dict[str, Any]]:
            items = session.execute(
                select(WorkflowItem).where(*where)
                .order_by(WorkflowItem.updated_at.desc()).limit(100)
            ).scalars().all()
            return [row(i) for i in items]

        return {
            "my_work": fetch(
                WorkflowItem.assigned_to == user_id,
                WorkflowItem.state.in_(WF_OPEN_STATES),
            ),
            "sent_by_me": fetch(
                WorkflowItem.requested_by == user_id,
                WorkflowItem.state.in_(WF_OPEN_STATES),
            ),
            "completed": fetch(
                or_(
                    WorkflowItem.assigned_to == user_id,
                    WorkflowItem.requested_by == user_id,
                ),
                WorkflowItem.state.in_((WF_APPROVED, WF_REJECTED, WF_WITHDRAWN)),
            ),
        }


def for_object(object_type: str, object_id: str) -> list[dict[str, Any]]:
    """Every review this object has been through."""
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import WorkflowItem

    with get_session() as session:
        items = session.execute(
            select(WorkflowItem)
            .where(
                WorkflowItem.object_type == object_type,
                WorkflowItem.object_id == str(object_id),
            )
            .order_by(WorkflowItem.created_at.desc())
        ).scalars().all()
        return [_view(session, item).to_dict() for item in items]


# ------------------------------------------------------------------ comments


def comment(*, object_type: str, object_id: str, body: str,
            author_id: int | None = None, parent_id: int | None = None,
            notify_user_id: int | None = None) -> dict[str, Any]:
    """Attach a comment to anything — a result, a Trace node, a dataset."""
    _require_db()
    if not body.strip():
        raise ValueError("A comment needs something in it.")

    from backend.db.engine import get_session
    from backend.models.platform import Comment

    with get_session() as session:
        row = Comment(
            object_type=object_type, object_id=str(object_id),
            parent_id=parent_id, body=body.strip(), author_id=author_id,
        )
        session.add(row)
        session.flush()
        if notify_user_id and notify_user_id != author_id:
            _notify(
                session,
                user_id=notify_user_id,
                kind="commented",
                title=f"New comment on {REVIEWABLE.get(object_type, object_type)}",
                body=body.strip()[:500],
                object_type=object_type,
                object_id=str(object_id),
                actor_id=author_id,
            )
        session.commit()
        return _comment_dict(row)


def _comment_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "parent_id": row.parent_id,
        "body": row.body,
        "resolved": row.resolved,
        "author_id": row.author_id,
        "created_at": _iso(row.created_at),
    }


def comments(object_type: str, object_id: str) -> list[dict[str, Any]]:
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Comment

    with get_session() as session:
        rows = session.execute(
            select(Comment)
            .where(Comment.object_type == object_type, Comment.object_id == str(object_id))
            .order_by(Comment.created_at)
        ).scalars().all()
        return [_comment_dict(r) for r in rows]


def resolve_comment(comment_id: int, *, resolved: bool = True) -> dict[str, Any]:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Comment

    with get_session() as session:
        row = session.get(Comment, comment_id)
        if row is None:
            raise WorkflowNotFound(f"Comment {comment_id} does not exist.")
        row.resolved = resolved
        session.commit()
        return _comment_dict(row)


# ------------------------------------------------------------- notifications


def _notify(session: Any, **fields: Any) -> None:
    """Write one notification inside the caller's transaction.

    Deliberately not a public function: a notification is always a consequence of
    something else happening, and one that can be raised on its own is one that
    will eventually be raised about nothing.
    """
    from backend.models.platform import Notification

    session.add(Notification(**fields))


def notifications(user_id: int | None, *, unread_only: bool = False,
                  limit: int = 50) -> list[dict[str, Any]]:
    if not settings.has_database or user_id is None:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Notification

    with get_session() as session:
        query = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        return [
            {
                "id": n.id,
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "object_type": n.object_type,
                "object_id": n.object_id,
                "actor_id": n.actor_id,
                "read": n.read_at is not None,
                "created_at": _iso(n.created_at),
            }
            for n in session.execute(query).scalars().all()
        ]


def mark_read(user_id: int, notification_id: int | None = None) -> int:
    """Mark one notification read, or all of a user's. Returns how many."""
    _require_db()
    from sqlalchemy import func, update

    from backend.db.engine import get_session
    from backend.models.platform import Notification

    with get_session() as session:
        statement = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=func.now())
        )
        if notification_id is not None:
            statement = statement.where(Notification.id == notification_id)
        result = session.execute(statement)
        session.commit()
        return int(result.rowcount or 0)


def unread_count(user_id: int | None) -> int:
    if not settings.has_database or user_id is None:
        return 0
    from sqlalchemy import func, select

    from backend.db.engine import get_session
    from backend.models.platform import Notification

    with get_session() as session:
        return int(session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        ).scalar() or 0)


__all__ = [
    "ALLOWED",
    "REVIEWABLE",
    "STATE_LABEL",
    "InvalidTransition",
    "WorkflowNotFound",
    "WorkflowUnavailable",
    "WorkflowView",
    "comment",
    "comments",
    "for_object",
    "get",
    "inbox",
    "mark_read",
    "notifications",
    "resolve_comment",
    "submit",
    "transition",
    "unread_count",
]
