"""Who may read a project, and who may change what.

CreditProbe has no organisation table. That is a real architectural fact, not
an omission, and it decides the shape of this module: the boundary around a
delivery project is its own participant list. A user who is not a participant
cannot read the project, list its tasks, export it, import against it, or reach
it through an agent — whatever their platform role says, and whatever id they
put in the URL.

Two ideas, kept apart on purpose
--------------------------------
`project_role` is what somebody DOES — Sponsor, Reviewer, Workstream Lead. It
is business vocabulary and it drives nothing here.

`access` is what somebody MAY CHANGE — VIEWER, CONTRIBUTOR, EDITOR, OWNER.
Collapsing the two is how a Reviewer ends up able to move a deadline they were
only meant to comment on.

One exception, stated rather than hidden
----------------------------------------
A platform ADMIN can read and administer any project. That is the same power an
administrator already has over every other object in CreditProbe, it is visible
in the audit log like any other action, and pretending otherwise would mean an
administrator cannot fix a project whose only owner has left the bank. It is
NOT a licence to update somebody's task on their behalf: `may_update_task`
still asks whether they own it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.api.permissions import Role
from backend.models.planner import (
    ACCESS_CONTRIBUTOR,
    ACCESS_EDITOR,
    ACCESS_LEVELS,
    ACCESS_OWNER,
    ACCESS_VIEWER,
    PlannerParticipant,
    PlannerProject,
    PlannerTask,
)


class ProjectNotFound(LookupError):
    """No such project — or none this caller is allowed to know about.

    Deliberately the same exception for both. A caller who can tell "this
    project does not exist" from "this project exists and is not yours" can
    enumerate the bank's project list by trying ids, and the second message is
    the one that leaks.
    """


class ProjectDenied(PermissionError):
    """The caller may read the project but not do this to it."""


@dataclass(frozen=True)
class Grant:
    """What one person may do on one project."""

    project_id: int
    user_id: int | None
    access: str
    project_role: str = ""
    #: True where the grant comes from the platform ADMIN role rather than
    #: from a participant row. Recorded so the audit log can say so.
    administrative: bool = False

    def at_least(self, level: str) -> bool:
        """Whether this grant reaches a required level.

        Compared by position in ACCESS_LEVELS, which is ordered weakest first.
        An unknown level is never satisfied rather than defaulting to allowed.
        """
        if self.access not in ACCESS_LEVELS or level not in ACCESS_LEVELS:
            return False
        return ACCESS_LEVELS.index(self.access) >= ACCESS_LEVELS.index(level)

    def to_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "user_id": self.user_id,
                "access": self.access, "project_role": self.project_role,
                "administrative": self.administrative}


def _role_of(principal: Any) -> str:
    role = getattr(principal, "role", None)
    return str(getattr(role, "value", role) or "").upper()


def _user_of(principal: Any) -> int | None:
    found = getattr(principal, "user_id", None)
    return int(found) if found is not None else None


def is_admin(principal: Any) -> bool:
    return _role_of(principal) == Role.ADMIN.value


def grant(session: Any, project_id: int, principal: Any) -> Grant:
    """What this caller may do on this project, or ProjectNotFound.

    The single door. Every service function calls it first and nothing reaches
    a project row without passing through here.
    """
    project = session.get(PlannerProject, int(project_id))
    if project is None:
        raise ProjectNotFound(f"No project {project_id}.")
    return grant_for(session, project, principal)


def grant_for(session: Any, project: Any, principal: Any) -> Grant:
    """The same decision when the row is already loaded."""
    user_id = _user_of(principal)
    if user_id is not None:
        row = session.execute(
            select(PlannerParticipant).where(
                PlannerParticipant.project_id == project.id,
                PlannerParticipant.user_id == user_id)
        ).scalar_one_or_none()
        if row is not None:
            return Grant(int(project.id), user_id, str(row.access),
                         str(row.project_role))

    if is_admin(principal):
        return Grant(int(project.id), user_id, ACCESS_OWNER,
                     "PLATFORM_ADMIN", administrative=True)

    # Not a participant and not an administrator. Same answer as a project
    # that does not exist.
    raise ProjectNotFound(f"No project {project.id}.")


def readable(session: Any, project_id: int, principal: Any) -> Grant:
    """Read access, or ProjectNotFound."""
    return grant(session, project_id, principal)


def require(session: Any, project_id: int, principal: Any, level: str,
            what: str = "do that") -> Grant:
    """A grant that reaches `level`, or a refusal that says what is missing."""
    found = grant(session, project_id, principal)
    if not found.at_least(level):
        raise ProjectDenied(
            f"You have {found.access.lower()} access to this project, and "
            f"{level.lower()} access is needed to {what}.")
    return found


def may_update_task(session: Any, task: Any, principal: Any) -> Grant:
    """Whether this caller may change this particular task.

    CONTRIBUTOR is the interesting level and the reason this function exists
    rather than a bare `require(..., CONTRIBUTOR)`: a contributor may update
    the work they are responsible for and nobody else's. Being able to update
    any task on a project you contribute to is not contribution, it is
    editing.
    """
    found = grant(session, int(task.project_id), principal)
    if found.at_least(ACCESS_EDITOR):
        return found
    if not found.at_least(ACCESS_CONTRIBUTOR):
        raise ProjectDenied(
            "Viewers can read this project but cannot change it.")

    user_id = _user_of(principal)
    mine = (
        task.owner_id == user_id
        or task.reviewer_id == user_id
        or user_id in [int(c) for c in (task.contributor_ids or [])
                       if str(c).lstrip("-").isdigit()])
    if not mine:
        raise ProjectDenied(
            f"{task.code} belongs to somebody else. Contributors update the "
            "tasks they own, review or contribute to; editing another "
            "person's task needs editor access.")
    return found


def readable_project_ids(session: Any, principal: Any) -> list[int]:
    """Every project this caller may see, cheaply.

    One query. The portfolio screen and every "across my projects" question
    start here, and doing it per project is the difference between a page that
    loads and a page that times out at fifty projects.
    """
    if is_admin(principal):
        return [int(i) for i in session.execute(
            select(PlannerProject.id)).scalars()]
    user_id = _user_of(principal)
    if user_id is None:
        return []
    return [int(i) for i in session.execute(
        select(PlannerParticipant.project_id).where(
            PlannerParticipant.user_id == user_id)).scalars()]


def grants_for(session: Any, principal: Any) -> dict[int, Grant]:
    """The caller's access to every project they can see, in one query."""
    if is_admin(principal):
        user_id = _user_of(principal)
        return {int(i): Grant(int(i), user_id, ACCESS_OWNER, "PLATFORM_ADMIN",
                              administrative=True)
                for i in session.execute(select(PlannerProject.id)).scalars()}
    user_id = _user_of(principal)
    if user_id is None:
        return {}
    rows = session.execute(
        select(PlannerParticipant).where(
            PlannerParticipant.user_id == user_id)).scalars()
    return {int(r.project_id): Grant(int(r.project_id), user_id,
                                     str(r.access), str(r.project_role))
            for r in rows}


def visible_task(session: Any, task_id: int, principal: Any
                 ) -> tuple[Any, Grant]:
    """One task and the caller's access to its project, or ProjectNotFound.

    Task ids are global, so this is where a guessed task id is refused. It
    returns the same not-found as an unknown id for a task on somebody else's
    project, for the same reason `grant` does.
    """
    task = session.get(PlannerTask, int(task_id))
    if task is None:
        raise ProjectNotFound(f"No task {task_id}.")
    found = grant(session, int(task.project_id), principal)
    return task, found


__all__ = [
    "ProjectNotFound", "ProjectDenied", "Grant", "is_admin", "grant",
    "grant_for", "readable", "require", "may_update_task",
    "readable_project_ids", "grants_for", "visible_task",
    "ACCESS_VIEWER", "ACCESS_CONTRIBUTOR", "ACCESS_EDITOR", "ACCESS_OWNER",
]
