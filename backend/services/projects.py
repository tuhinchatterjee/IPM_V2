"""
Projects: the master workspace, and the one status that cannot be faked.

A Project is the top of the hierarchy — Analysis < Investigation < Project. It
holds a question somebody is working on over weeks: the investigations that
explore it, the analyses that were kept as evidence, standing instructions that
shape how CreditProbe answers inside it, and a status that says where the work
has got to.

The status vocabulary
---------------------
    DRAFT       being set up; nobody is relying on it yet
    ACTIVE      work in progress
    IN REVIEW   somebody has been asked to review it and has not yet decided
    COMPLETED   the work is finished
    ARCHIVED    kept for the record, off the working list

Four of those five are a person's declaration and can be set directly. IN REVIEW
is not. A project is IN REVIEW when, and only when, there is an open review item
against it in the workflow service — a real person asked, a real reviewer was
named, and no decision has come back. `submit_for_review()` puts it there by
creating that item; the reviewer's approve/reject decision takes it out again.
That is the whole point: a status badge that anyone can click means nothing to
the person reading it, and "In review" is exactly the badge somebody is most
likely to trust without checking.

Nothing in this module calculates anything. Projects organise analysis; they do
not perform it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


class ProjectNotFound(LookupError):
    pass


class InvalidProjectTransition(ValueError):
    """The requested status change is not one a person may make from here."""


class StorageUnavailable(RuntimeError):
    """Projects need PostgreSQL. Asking a question does not."""


def _require_db() -> None:
    if not settings.has_database:
        raise StorageUnavailable(
            "Projects are stored in PostgreSQL. Questions can still be asked "
            "and answered without it; the workspace just is not kept."
        )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


# ------------------------------------------------------------------- shape


@dataclass
class ProjectView:
    """A project as the API and the UI see it."""

    id: int
    name: str
    description: str
    status: str
    status_label: str
    instructions: str
    team_id: int | None
    created_by: int | None
    default_context: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    #: Statuses a person may move to right now. IN REVIEW never appears here.
    available_statuses: list[dict[str, str]] = field(default_factory=list)
    #: True when an open review item exists — the only thing that means IN REVIEW.
    review_open: bool = False
    review_item_id: int | None = None
    investigation_count: int = 0
    analysis_count: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "status_label": self.status_label,
            "instructions": self.instructions,
            "team_id": self.team_id,
            "created_by": self.created_by,
            "default_context": self.default_context,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "available_statuses": self.available_statuses,
            "review_open": self.review_open,
            "review_item_id": self.review_item_id,
            "investigation_count": self.investigation_count,
            "analysis_count": self.analysis_count,
            "history": self.history,
        }


def _open_review(session: Any, project_id: int) -> Any:
    """The outstanding review item for this project, if there is one."""
    from sqlalchemy import select

    from backend.models.platform import WF_OPEN_STATES, WorkflowItem

    return session.execute(
        select(WorkflowItem)
        .where(
            WorkflowItem.object_type == "project",
            WorkflowItem.object_id == str(project_id),
            WorkflowItem.state.in_(WF_OPEN_STATES),
        )
        .order_by(WorkflowItem.id.desc())
    ).scalars().first()


def _view(session: Any, row: Any, *, with_history: bool = False) -> ProjectView:
    from sqlalchemy import func, select

    from backend.models.platform import (
        PJ_IN_REVIEW,
        PROJECT_MANUAL_TRANSITIONS,
        PROJECT_STATUS_LABEL,
        Investigation,
        ProjectStatusEvent,
        SavedAnalysis,
    )

    review = _open_review(session, row.id)
    # The stored status and the review reality can disagree if a reviewer
    # decided while nobody was looking. The review is the authority.
    status = PJ_IN_REVIEW if review is not None else row.status
    if status == PJ_IN_REVIEW and review is None:  # pragma: no cover - defensive
        status = row.status

    investigations = session.execute(
        select(func.count(Investigation.id)).where(Investigation.project_id == row.id)
    ).scalar() or 0
    analyses = session.execute(
        select(func.count(SavedAnalysis.id)).where(SavedAnalysis.project_id == row.id)
    ).scalar() or 0

    history: list[dict[str, Any]] = []
    if with_history:
        events = session.execute(
            select(ProjectStatusEvent)
            .where(ProjectStatusEvent.project_id == row.id)
            .order_by(ProjectStatusEvent.id.desc())
            .limit(50)
        ).scalars().all()
        history = [{
            "from_status": e.from_status,
            "to_status": e.to_status,
            "to_label": PROJECT_STATUS_LABEL.get(e.to_status, e.to_status),
            "actor_id": e.actor_id,
            "note": e.note,
            "created_at": _iso(e.created_at),
        } for e in events]

    return ProjectView(
        id=row.id,
        name=row.name,
        description=row.description,
        status=status,
        status_label=PROJECT_STATUS_LABEL.get(status, status),
        instructions=row.instructions,
        team_id=row.team_id,
        created_by=row.created_by,
        default_context=dict(row.default_context or {}),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        available_statuses=[
            {"status": s, "label": PROJECT_STATUS_LABEL.get(s, s)}
            for s in PROJECT_MANUAL_TRANSITIONS.get(status, ())
        ],
        review_open=review is not None,
        review_item_id=review.id if review is not None else None,
        investigation_count=int(investigations),
        analysis_count=int(analyses),
        history=history,
    )


# ------------------------------------------------------------------ writing


def create(*, name: str, description: str = "", instructions: str = "",
           team_id: int | None = None, user_id: int | None = None,
           default_context: dict[str, Any] | None = None) -> ProjectView:
    """Open a new project. It starts in DRAFT: nothing relies on it yet."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import PJ_DRAFT, Project, ProjectStatusEvent

    with get_session() as session:
        row = Project(
            name=name[:200],
            description=description,
            instructions=instructions,
            status=PJ_DRAFT,
            team_id=team_id,
            created_by=user_id,
            default_context=dict(default_context or {}),
        )
        session.add(row)
        session.flush()
        session.add(ProjectStatusEvent(
            project_id=row.id, from_status=None, to_status=PJ_DRAFT,
            actor_id=user_id, note="Project created.",
        ))
        session.commit()
        return _view(session, row)


def update(project_id: int, *, name: str | None = None,
           description: str | None = None, instructions: str | None = None,
           default_context: dict[str, Any] | None = None) -> ProjectView:
    """Edit the parts of a project that are simply text. Not the status."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Project

    with get_session() as session:
        row = session.get(Project, project_id)
        if row is None:
            raise ProjectNotFound(f"Project {project_id} does not exist.")
        if name is not None:
            row.name = name[:200]
        if description is not None:
            row.description = description
        if instructions is not None:
            row.instructions = instructions
        if default_context is not None:
            row.default_context = dict(default_context)
        session.commit()
        return _view(session, row)


def set_status(project_id: int, to_status: str, *, actor_id: int | None = None,
               note: str = "") -> ProjectView:
    """Move a project to a status a person is entitled to declare.

    IN REVIEW is refused here on purpose. It is not a label somebody applies;
    it is a fact about whether a review is outstanding. Use
    `submit_for_review()`.
    """
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import (
        PJ_IN_REVIEW,
        PROJECT_MANUAL_TRANSITIONS,
        PROJECT_STATUS_LABEL,
        Project,
        ProjectStatusEvent,
    )

    if to_status == PJ_IN_REVIEW:
        raise InvalidProjectTransition(
            "'In review' cannot be set directly. It means a review is genuinely "
            "outstanding, so send the project for review instead."
        )

    with get_session() as session:
        row = session.get(Project, project_id)
        if row is None:
            raise ProjectNotFound(f"Project {project_id} does not exist.")

        current = PJ_IN_REVIEW if _open_review(session, project_id) else row.status
        permitted = PROJECT_MANUAL_TRANSITIONS.get(current, ())
        if to_status not in permitted:
            if current == PJ_IN_REVIEW:
                raise InvalidProjectTransition(
                    "This project is with a reviewer. It moves when they decide."
                )
            raise InvalidProjectTransition(
                f"'{PROJECT_STATUS_LABEL.get(current, current)}' cannot become "
                f"'{PROJECT_STATUS_LABEL.get(to_status, to_status)}'. "
                + (
                    "Available from here: "
                    + ", ".join(PROJECT_STATUS_LABEL[s] for s in permitted) + "."
                    if permitted else "Nothing can be set from here."
                )
            )

        previous = row.status
        row.status = to_status
        session.add(ProjectStatusEvent(
            project_id=project_id, from_status=previous, to_status=to_status,
            actor_id=actor_id, note=note,
        ))
        session.commit()
        return _view(session, row, with_history=True)


def submit_for_review(project_id: int, *, assigned_to: int | None,
                      requested_by: int | None = None,
                      note: str = "") -> ProjectView:
    """Ask somebody to review the project. This is what makes it IN REVIEW."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import PJ_IN_REVIEW, Project, ProjectStatusEvent
    from backend.services import workflow as wf

    with get_session() as session:
        row = session.get(Project, project_id)
        if row is None:
            raise ProjectNotFound(f"Project {project_id} does not exist.")
        if _open_review(session, project_id) is not None:
            raise InvalidProjectTransition(
                "This project is already with a reviewer."
            )
        name, previous = row.name, row.status

    wf.submit(
        object_type="project", object_id=str(project_id), title=name,
        assigned_to=assigned_to, requested_by=requested_by, note=note,
    )

    with get_session() as session:
        row = session.get(Project, project_id)
        session.add(ProjectStatusEvent(
            project_id=project_id, from_status=previous, to_status=PJ_IN_REVIEW,
            actor_id=requested_by, note=note or "Sent for review.",
        ))
        session.commit()
        return _view(session, row, with_history=True)


def review_decided(project_id: int, *, approved: bool,
                   actor_id: int | None = None, note: str = "") -> ProjectView:
    """Record where a project lands once its reviewer has decided.

    Approval completes the project; a rejection sends it back to ACTIVE so the
    work can continue. Either way the workflow item is already closed by the
    workflow service, so the project stops being IN REVIEW the moment that
    happens — this only records the landing status and the reason.
    """
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import (
        PJ_ACTIVE,
        PJ_COMPLETED,
        PJ_IN_REVIEW,
        Project,
        ProjectStatusEvent,
    )

    landing = PJ_COMPLETED if approved else PJ_ACTIVE
    with get_session() as session:
        row = session.get(Project, project_id)
        if row is None:
            raise ProjectNotFound(f"Project {project_id} does not exist.")
        row.status = landing
        session.add(ProjectStatusEvent(
            project_id=project_id, from_status=PJ_IN_REVIEW, to_status=landing,
            actor_id=actor_id,
            note=note or ("Review approved." if approved else "Review returned."),
        ))
        session.commit()
        return _view(session, row, with_history=True)


# ------------------------------------------------------------------ reading


def get(project_id: int) -> ProjectView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Project

    with get_session() as session:
        row = session.get(Project, project_id)
        if row is None:
            raise ProjectNotFound(f"Project {project_id} does not exist.")
        return _view(session, row, with_history=True)


def listing(*, status: str | None = None, owner_id: int | None = None,
            limit: int = 100) -> list[dict[str, Any]]:
    """Projects, most recently touched first. Archived ones only if asked for."""
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import PJ_ARCHIVED, Project

    with get_session() as session:
        query = select(Project).order_by(Project.updated_at.desc()).limit(limit)
        if status:
            query = query.where(Project.status == status)
        else:
            query = query.where(Project.status != PJ_ARCHIVED)
        if owner_id is not None:
            query = query.where(Project.created_by == owner_id)
        rows = session.execute(query).scalars().all()
        return [_view(session, row).to_dict() for row in rows]


def contents(project_id: int, *, limit: int = 200) -> dict[str, Any]:
    """Everything filed under a project: its investigations and its analyses."""
    _require_db()
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Investigation, Project, SavedAnalysis

    with get_session() as session:
        row = session.get(Project, project_id)
        if row is None:
            raise ProjectNotFound(f"Project {project_id} does not exist.")

        # A project's investigations live here and in no other list: the global
        # Work > Investigations view is scoped to threads with no project. See
        # backend/services/threads.listing().
        threads = session.execute(
            select(Investigation)
            .where(Investigation.project_id == project_id)
            .order_by(Investigation.updated_at.desc())
            .limit(limit)
        ).scalars().all()
        saved = session.execute(
            select(SavedAnalysis)
            .where(SavedAnalysis.project_id == project_id)
            .order_by(SavedAnalysis.id.desc())
            .limit(limit)
        ).scalars().all()

        return {
            "project": _view(session, row, with_history=True).to_dict(),
            "investigations": [{
                "id": t.id,
                "title": t.title,
                "question": t.question,
                "status": t.status,
                "message_count": t.message_count,
                "last_message_at": _iso(t.last_message_at),
                "updated_at": _iso(t.updated_at),
            } for t in threads],
            "analyses": [{
                "id": a.id,
                "title": a.title,
                "analysis_id": a.analysis_id,
                "certification": a.certification,
                "investigation_id": a.investigation_id,
                "period": dict(a.period or {}),
                "created_at": _iso(a.created_at),
            } for a in saved],
        }


__all__ = [
    "InvalidProjectTransition",
    "ProjectNotFound",
    "ProjectView",
    "StorageUnavailable",
    "contents",
    "create",
    "get",
    "listing",
    "review_decided",
    "set_status",
    "submit_for_review",
    "update",
]
