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
    WF_ACTIONS,
    WF_APPROVED,
    WF_CLOSED_STATES,
    WF_COMMENTED,
    WF_COMPLETED,
    WF_DRAFT,
    WF_IN_REVIEW,
    WF_OPEN_STATES,
    WF_OPENED,
    WF_PRIORITIES,
    WF_REJECTED,
    WF_REVIEW,
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
    # OPENED and COMMENTED are things that HAPPEN to a sent item rather than
    # decisions taken about it, so every open state can reach them and none of
    # them closes anything.
    WF_SUBMITTED: {WF_OPENED, WF_IN_REVIEW, WF_COMMENTED, WF_APPROVED,
                   WF_REJECTED, WF_COMPLETED, WF_WITHDRAWN},
    WF_OPENED: {WF_IN_REVIEW, WF_COMMENTED, WF_APPROVED, WF_REJECTED,
                WF_COMPLETED, WF_WITHDRAWN},
    WF_IN_REVIEW: {WF_COMMENTED, WF_APPROVED, WF_REJECTED, WF_COMPLETED,
                   WF_WITHDRAWN},
    WF_COMMENTED: {WF_IN_REVIEW, WF_APPROVED, WF_REJECTED, WF_COMPLETED,
                   WF_WITHDRAWN},
    # An approval, a rejection or a completion is final for that submission.
    # Wanting another look means sending again, which creates a new item and
    # leaves the first decision standing.
    WF_APPROVED: set(),
    WF_REJECTED: set(),
    WF_COMPLETED: set(),
    WF_WITHDRAWN: set(),
}

#: What a state means, in the language of the person reading it.
#:
#: These are §44's nine names. Two of the stored ids read differently — see the
#: vocabulary in models/platform.py for why they are not renamed.
STATE_LABEL: dict[str, str] = {
    WF_DRAFT: "Draft",
    WF_SUBMITTED: "Sent",
    WF_OPENED: "Opened",
    WF_IN_REVIEW: "In review",
    WF_COMMENTED: "Commented",
    WF_APPROVED: "Approved",
    WF_REJECTED: "Changes requested",
    WF_COMPLETED: "Completed",
    WF_WITHDRAWN: "Cancelled",
}

#: What a notification about each action SAYS.
#:
#: Not the chip label. "Review: Q2 committee pack" is what a program writes;
#: "Review requested: Q2 committee pack" is what a person reads, and a
#: notification is read in a list of other people's sentences.
ACTION_ASKED: dict[str, str] = {
    "review": "Review requested",
    "comment": "Comment requested",
    "approve": "Approval requested",
    "request_changes": "Changes requested",
    "fyi": "For your information",
    "sign_off": "Sign-off requested",
    "assign_action": "Action assigned",
}

#: What is being ASKED FOR. §43's seven, in the words a sender picks from.
ACTION_LABEL: dict[str, str] = {
    "review": "Review",
    "comment": "Comment",
    "approve": "Approve",
    "request_changes": "Request changes",
    "fyi": "FYI",
    "sign_off": "Sign-off",
    "assign_action": "Assign action",
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
    object_version: str | None
    title: str
    state: str
    state_label: str
    action: str
    action_label: str
    message: str
    priority: str
    requested_by: int | None
    assigned_to: int | None
    recipients: list[dict[str, Any]]
    due_at: str | None
    created_at: str | None
    updated_at: str | None
    events: list[dict[str, Any]]
    thread: list[dict[str, Any]]
    next_states: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "object_type": self.object_type,
            "object_type_label": REVIEWABLE.get(self.object_type, self.object_type),
            "object_id": self.object_id,
            "object_version": self.object_version,
            "title": self.title,
            "state": self.state,
            "state_label": self.state_label,
            "action": self.action,
            "action_label": self.action_label,
            "message": self.message,
            "priority": self.priority,
            "requested_by": self.requested_by,
            "assigned_to": self.assigned_to,
            "recipients": self.recipients,
            "due_at": self.due_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "events": self.events,
            "thread": self.thread,
            "next_states": self.next_states,
            "next_state_labels": {s: STATE_LABEL[s] for s in self.next_states},
        }


def _recipient_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "team_id": row.team_id,
        "opened_at": _iso(row.opened_at),
    }


def _message_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "parent_id": row.parent_id,
        "body": row.body,
        "author_id": row.author_id,
        "resolved": row.resolved,
        "mentions": list(row.mentions or []),
        "attachments": list(row.attachments or []),
        "created_at": _iso(row.created_at),
    }


def _view(session: Any, item: Any) -> WorkflowView:
    from sqlalchemy import select

    from backend.models.platform import (
        WorkflowEvent,
        WorkflowMessage,
        WorkflowRecipient,
    )

    events = session.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.workflow_item_id == item.id)
        .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
    ).scalars().all()
    recipients = session.execute(
        select(WorkflowRecipient)
        .where(WorkflowRecipient.workflow_item_id == item.id)
        .order_by(WorkflowRecipient.id)
    ).scalars().all()
    thread = session.execute(
        select(WorkflowMessage)
        .where(WorkflowMessage.workflow_item_id == item.id)
        .order_by(WorkflowMessage.created_at, WorkflowMessage.id)
    ).scalars().all()

    return WorkflowView(
        id=item.id,
        object_type=item.object_type,
        object_id=item.object_id,
        object_version=item.object_version,
        title=item.title,
        state=item.state,
        state_label=STATE_LABEL.get(item.state, item.state),
        action=item.action,
        action_label=ACTION_LABEL.get(item.action, item.action),
        message=item.message,
        priority=item.priority,
        requested_by=item.requested_by,
        assigned_to=item.assigned_to,
        recipients=[_recipient_dict(r) for r in recipients],
        thread=[_message_dict(m) for m in thread],
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
    """Send something to one reviewer.

    The single-recipient shape every caller written before §43 uses. It is a
    thin call onto `send`, which is where the behaviour lives, so there is one
    implementation rather than two that can drift.
    """
    return send(
        object_type=object_type, object_id=object_id, title=title,
        recipients=[assigned_to] if assigned_to else [],
        requested_by=requested_by, message=note,
    )


def send(*, object_type: str, object_id: str, title: str,
         recipients: list[int] | None = None,
         teams: list[int] | None = None,
         requested_by: int | None = None,
         action: str = WF_REVIEW,
         message: str = "",
         priority: str = "normal",
         due_at: Any = None,
         object_version: str | None = None) -> WorkflowView:
    """Send an object to people and teams, for a named action. §43, §44.

    Everything §44 asks a request to carry: who sent it, who it went to, what
    object and at which version, what is being asked for, what the sender said,
    when it is wanted by, and how urgent it is.

    The action is not the state. "Approve" is what is being asked FOR;
    "Approved" is where the asking got to. Conflating them is why a workflow
    list ends up unable to distinguish an approval nobody has looked at from
    one that has been granted.
    """
    _require_db()
    if object_type not in REVIEWABLE:
        raise InvalidTransition(
            f"'{object_type}' cannot be sent for review. "
            f"Reviewable objects: {', '.join(sorted(REVIEWABLE))}."
        )
    if action not in WF_ACTIONS:
        raise InvalidTransition(
            f"'{action}' is not something CreditProbe can be asked for. "
            f"Available: {', '.join(ACTION_LABEL[a] for a in WF_ACTIONS)}."
        )
    if priority not in WF_PRIORITIES:
        raise InvalidTransition(
            f"'{priority}' is not a priority. "
            f"Available: {', '.join(WF_PRIORITIES)}."
        )

    people = _unique(recipients or [])
    groups = _unique(teams or [])
    if not people and not groups:
        raise InvalidTransition(
            "Send it to somebody: a workflow request with no recipient is a "
            "note to nobody."
        )

    from backend.db.engine import get_session
    from backend.models.platform import (
        WorkflowEvent,
        WorkflowItem,
        WorkflowRecipient,
    )

    with get_session() as session:
        item = WorkflowItem(
            object_type=object_type,
            object_id=str(object_id),
            object_version=object_version,
            title=title[:300],
            state=WF_SUBMITTED,
            action=action,
            message=message,
            priority=priority,
            requested_by=requested_by,
            # The head of the recipient set, kept so "my work" has an index and
            # so every caller written before multi-recipient still works.
            assigned_to=people[0] if people else None,
            due_at=due_at,
        )
        session.add(item)
        session.flush()

        for user_id in people:
            session.add(WorkflowRecipient(
                workflow_item_id=item.id, user_id=user_id))
        for team_id in groups:
            session.add(WorkflowRecipient(
                workflow_item_id=item.id, team_id=team_id))

        session.add(WorkflowEvent(
            workflow_item_id=item.id, from_state=WF_DRAFT, to_state=WF_SUBMITTED,
            actor_id=requested_by, comment=message,
        ))

        for user_id in _people_of(session, people, groups):
            if user_id == requested_by:
                continue
            _notify(
                session,
                user_id=user_id,
                kind="assigned",
                title=f"{ACTION_ASKED[action]}: {title}"[:300],
                body=message,
                object_type=object_type,
                object_id=str(object_id),
                actor_id=requested_by,
            )
        session.commit()
        return _view(session, item)


def _unique(values: list[int]) -> list[int]:
    """The same list with duplicates removed, in the order given.

    Sending to somebody twice should not notify them twice, and the recipient
    table's unique constraint would refuse the whole send rather than the
    duplicate.
    """
    seen: set[int] = set()
    out: list[int] = []
    for value in values:
        if value is None or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _people_of(session: Any, people: list[int], teams: list[int]) -> list[int]:
    """Everybody who should be told, teams expanded into their members.

    A team is a recipient of the ITEM and a set of people for the purpose of
    NOTIFYING: the item says "sent to Credit Review", and every member of Credit
    Review is told. Storing the expansion would freeze the membership as it was
    on the day it was sent.
    """
    if not teams:
        return list(people)
    from sqlalchemy import select

    from backend.models.platform import TeamMember

    members = session.execute(
        select(TeamMember.user_id).where(TeamMember.team_id.in_(teams))
    ).scalars().all()
    return _unique([*people, *[m for m in members if m is not None]])


def opened(item_id: int, *, user_id: int | None) -> WorkflowView:
    """Record that a recipient has looked at it. §44's OPENED.

    An observation, not a decision: it stamps the recipient row and moves the
    item to OPENED only from SENT. A reviewer who has already started reviewing
    does not go backwards because they reloaded the page.
    """
    _require_db()
    from datetime import UTC, datetime

    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import (
        WorkflowEvent,
        WorkflowItem,
        WorkflowRecipient,
    )

    with get_session() as session:
        item = session.get(WorkflowItem, item_id)
        if item is None:
            raise WorkflowNotFound(f"Workflow item {item_id} does not exist.")

        if user_id is not None:
            row = session.execute(
                select(WorkflowRecipient).where(
                    WorkflowRecipient.workflow_item_id == item_id,
                    WorkflowRecipient.user_id == user_id,
                )
            ).scalars().first()
            if row is not None and row.opened_at is None:
                row.opened_at = datetime.now(UTC)

        if item.state == WF_SUBMITTED:
            item.state = WF_OPENED
            session.add(WorkflowEvent(
                workflow_item_id=item.id, from_state=WF_SUBMITTED,
                to_state=WF_OPENED, actor_id=user_id, comment="",
            ))
        session.commit()
        return _view(session, item)


def say(item_id: int, *, body: str, author_id: int | None = None,
        parent_id: int | None = None,
        mentions: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Add a message to the conversation about a workflow item. §45.

    Everybody who is part of the item — its sender and its recipients — is told,
    except the person who wrote it. Anybody named in `mentions` is told as a
    mention rather than as a comment, because "somebody said something on a
    thread you are on" and "somebody asked you specifically" are different
    things and an inbox that cannot tell them apart is one people stop reading.
    """
    _require_db()
    if not body.strip():
        raise ValueError("A message needs something in it.")

    from backend.db.engine import get_session
    from backend.models.platform import (
        WorkflowEvent,
        WorkflowItem,
        WorkflowMessage,
    )

    named = [m for m in (mentions or []) if isinstance(m, dict)]

    with get_session() as session:
        item = session.get(WorkflowItem, item_id)
        if item is None:
            raise WorkflowNotFound(f"Workflow item {item_id} does not exist.")

        row = WorkflowMessage(
            workflow_item_id=item_id,
            parent_id=parent_id,
            body=body.strip(),
            author_id=author_id,
            mentions=named,
            attachments=[a for a in (attachments or []) if isinstance(a, dict)],
        )
        session.add(row)

        # Saying something on an open item is itself a status: it tells the
        # sender there is something to read without claiming a decision.
        if item.state in (WF_SUBMITTED, WF_OPENED):
            previous = item.state
            item.state = WF_COMMENTED
            session.add(WorkflowEvent(
                workflow_item_id=item.id, from_state=previous,
                to_state=WF_COMMENTED, actor_id=author_id,
                comment=body.strip()[:500],
            ))

        mentioned = {
            int(m["user_id"]) for m in named
            if isinstance(m.get("user_id"), int)
        }
        involved = set(_involved(session, item)) - mentioned
        for user_id in sorted(involved):
            if user_id == author_id:
                continue
            _notify(
                session, user_id=user_id, kind="commented",
                title=f"New message: {item.title}"[:300],
                body=body.strip()[:500],
                object_type=item.object_type, object_id=item.object_id,
                actor_id=author_id,
            )
        for user_id in sorted(mentioned):
            if user_id == author_id:
                continue
            _notify(
                session, user_id=user_id, kind="mentioned",
                title=f"You were mentioned: {item.title}"[:300],
                body=body.strip()[:500],
                object_type=item.object_type, object_id=item.object_id,
                actor_id=author_id,
            )
        session.flush()
        session.commit()
        return _message_dict(row)


def _involved(session: Any, item: Any) -> list[int]:
    """The sender and every recipient, teams expanded."""
    from sqlalchemy import select

    from backend.models.platform import WorkflowRecipient

    rows = session.execute(
        select(WorkflowRecipient).where(
            WorkflowRecipient.workflow_item_id == item.id)
    ).scalars().all()
    people = [r.user_id for r in rows if r.user_id is not None]
    teams = [r.team_id for r in rows if r.team_id is not None]
    everybody = _people_of(session, people, teams)
    if item.requested_by:
        everybody = _unique([*everybody, item.requested_by])
    return everybody


def resolve_message(message_id: int, *, resolved: bool = True) -> dict[str, Any]:
    """Mark one message in a workflow thread resolved, or unresolve it. §45."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import WorkflowMessage

    with get_session() as session:
        row = session.get(WorkflowMessage, message_id)
        if row is None:
            raise WorkflowNotFound(f"Message {message_id} does not exist.")
        row.resolved = resolved
        session.commit()
        return _message_dict(row)


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
    """The five lists a Workflow Inbox is made of. §46.

    assigned_to_me — open and sent to me, directly or through a team I am in.
                     What I have to do.
    sent_by_me     — open and sent by me. What I am waiting on.
    mentions       — open items where somebody named me in the thread. Distinct
                     from assigned: being asked a question is not the same as
                     being given the work, and an inbox that cannot tell them
                     apart is one people stop reading.
    due_soon       — assigned to me, open, with a due date inside a week.
    completed      — closed, however it closed, that I was part of.

    A team's work reaches its members here. The expansion is done at read time
    rather than stored, so somebody who joins Credit Review today sees what
    Credit Review was sent yesterday.
    """
    empty: dict[str, list[dict[str, Any]]] = {
        "assigned_to_me": [], "sent_by_me": [], "mentions": [],
        "due_soon": [], "completed": [],
        # The names the first Workflow screen used. Kept so a caller written
        # before §46 still finds its lists rather than two empty ones.
        "my_work": [], "sent": [],
    }
    if not settings.has_database or user_id is None:
        return empty

    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, or_, select

    from backend.db.engine import get_session
    from backend.models.platform import (
        TeamMember,
        WorkflowItem,
        WorkflowMessage,
        WorkflowRecipient,
    )

    def row(item: Any, *, unread: int = 0) -> dict[str, Any]:
        return {
            "id": item.id,
            "object_type": item.object_type,
            "object_type_label": REVIEWABLE.get(item.object_type, item.object_type),
            "object_id": item.object_id,
            "object_version": item.object_version,
            "title": item.title,
            "state": item.state,
            "state_label": STATE_LABEL.get(item.state, item.state),
            "action": item.action,
            "action_label": ACTION_LABEL.get(item.action, item.action),
            "message": item.message,
            "priority": item.priority,
            "requested_by": item.requested_by,
            "assigned_to": item.assigned_to,
            "due_at": _iso(item.due_at),
            "updated_at": _iso(item.updated_at),
            "messages": unread,
        }

    with get_session() as session:
        my_teams = session.execute(
            select(TeamMember.team_id).where(TeamMember.user_id == user_id)
        ).scalars().all()

        #: Items sent to me directly or to a team I am in.
        addressed_to_me = [WorkflowRecipient.user_id == user_id]
        if my_teams:
            addressed_to_me.append(WorkflowRecipient.team_id.in_(my_teams))
        addressed = select(WorkflowRecipient.workflow_item_id).where(
            or_(*addressed_to_me)
        )

        counts = dict(session.execute(
            select(WorkflowMessage.workflow_item_id,
                   func.count(WorkflowMessage.id))
            .group_by(WorkflowMessage.workflow_item_id)
        ).all())

        def fetch(*where: Any) -> list[dict[str, Any]]:
            items = session.execute(
                select(WorkflowItem).where(*where)
                .order_by(WorkflowItem.updated_at.desc()).limit(100)
            ).scalars().all()
            return [row(i, unread=counts.get(i.id, 0)) for i in items]

        assigned = fetch(
            or_(WorkflowItem.assigned_to == user_id, WorkflowItem.id.in_(addressed)),
            WorkflowItem.state.in_(WF_OPEN_STATES),
        )
        sent = fetch(
            WorkflowItem.requested_by == user_id,
            WorkflowItem.state.in_(WF_OPEN_STATES),
        )

        # A mention is recorded in the message document rather than in a column,
        # so it is matched there. The alternative — a mentions table — would be
        # a second place a mention could exist and disagree with the message.
        mentioned_ids = [
            m.workflow_item_id
            for m in session.execute(
                select(WorkflowMessage).order_by(WorkflowMessage.id.desc()).limit(500)
            ).scalars().all()
            if any(
                isinstance(entry, dict) and entry.get("user_id") == user_id
                for entry in (m.mentions or [])
            )
        ]
        mentions = fetch(
            WorkflowItem.id.in_(mentioned_ids or [-1]),
            WorkflowItem.state.in_(WF_OPEN_STATES),
        )

        soon = datetime.now(UTC) + timedelta(days=7)
        due_soon = [
            item for item in assigned
            if item["due_at"] and item["due_at"] <= soon.isoformat()
        ]

        completed = fetch(
            or_(
                WorkflowItem.assigned_to == user_id,
                WorkflowItem.requested_by == user_id,
                WorkflowItem.id.in_(addressed),
            ),
            WorkflowItem.state.in_(WF_CLOSED_STATES),
        )

        return {
            "assigned_to_me": assigned,
            "sent_by_me": sent,
            "mentions": mentions,
            "due_soon": due_soon,
            "completed": completed,
            "my_work": assigned,
            "sent": sent,
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


def notify_playbook_finding(*, user_id: int, playbook: str, title: str,
                            body: str, actor_id: int | None = None) -> None:
    """Tell somebody what a playbook found.

    The one public way to raise a notification, and it is narrow on purpose. A
    playbook run IS "something else happening" — it executed analyses and a
    threshold was crossed — so this is not a notification about nothing. It
    still cannot be raised without naming the playbook that produced it.
    """
    _require_db()
    from backend.db.engine import get_session

    with get_session() as session:
        _notify(
            session,
            user_id=user_id,
            kind="playbook",
            title=title[:300],
            body=body,
            object_type="playbook",
            object_id=playbook[:120],
            actor_id=actor_id,
        )
        session.commit()


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
