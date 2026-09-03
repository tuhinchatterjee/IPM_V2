"""Validated, permission-aware project mutations.

Every function here does the same five things in the same order, and the order
matters:

  1. resolve access, and refuse before reading anything else;
  2. validate the change against the plan's own rules;
  3. apply it, bumping the row's version;
  4. append an immutable `planner_updates` row saying what moved;
  5. write a `collaboration_audit` record naming the actor and the source.

Steps 4 and 5 are not the same thing and neither is optional. The update row is
the project's history — it is what "what changed since Friday?" reads, and what
the activity feed renders. The audit row is governance evidence, it outlives
the project, and it records the SOURCE so that an update somebody typed and an
update an agent proposed are distinguishable forever.

Nothing in this module commits. The caller owns the transaction, because an
Excel import applies four hundred of these and must do so atomically.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select

from backend.models.planner import (
    ACCESS_CONTRIBUTOR,
    ACCESS_EDITOR,
    ACCESS_LEVELS,
    ACCESS_OWNER,
    CADENCES,
    DEPENDENCY_TYPES,
    ENTITY_MILESTONE,
    ENTITY_PROJECT,
    ENTITY_RAID,
    ENTITY_TASK,
    ENTITY_TYPES,
    HEALTHS,
    MILESTONE_ACHIEVED,
    MILESTONE_STATUSES,
    PRIORITIES,
    PROJECT_ROLES,
    PROJECT_STATUSES,
    RAID_STATUSES,
    RAID_TYPES,
    SEVERITIES,
    SOURCE_UI,
    SOURCES,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_STATUSES,
    PlannerDependency,
    PlannerMilestone,
    PlannerParticipant,
    PlannerProject,
    PlannerRaid,
    PlannerTask,
    PlannerUpdate,
    PlannerWorkstream,
)
from backend.planner import access as acl
from backend.planner import control
from backend.services import collaboration

SERVICE_VERSION = "1.0.0"


class PlannerError(ValueError):
    """A change the plan's own rules refuse.

    Distinct from a permission failure: this is "you may do this, but not
    like that", and the message says which rule and what would satisfy it.
    """


class StaleWrite(PlannerError):
    """Somebody else changed this row since you read it."""


# ============================================================== small helpers


_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,39}$")


def check_code(value: str, what: str) -> str:
    """A code that is safe as an identifier, a filename and a spreadsheet cell.

    Codes travel into workbooks, URLs and log lines. A positive pattern rather
    than a blocklist, because the interesting characters are the ones nobody
    thinks of: a leading `=` makes a spreadsheet cell a formula, and a `/`
    makes a path.
    """
    text = " ".join(str(value or "").split())
    if not _CODE.match(text):
        raise PlannerError(
            f"{what} {value!r} is not a usable code. Use letters, digits, "
            "dots, hyphens and underscores, starting with a letter or digit, "
            "up to 40 characters — T-104, WS-DATA, IFRS9-2026.")
    return text


def _one_of(value: Any, allowed: tuple[str, ...], what: str,
            default: str = "") -> str:
    text = str(value or default or "").upper().strip()
    if not text and default:
        return default
    if text not in allowed:
        raise PlannerError(
            f"{value!r} is not a {what}. It is one of: "
            + ", ".join(allowed) + ".")
    return text


def _as_date(value: Any, what: str) -> date | None:
    """A date, however it arrived. Empty means 'not set', which is legitimate.

    Excel hands over datetimes, the API hands over ISO strings, and a person
    typing into a spreadsheet hands over whatever their locale does. Anything
    that is not one of the three shapes is refused by name rather than
    silently becoming None, because a due date that quietly disappears is a
    commitment that quietly disappears.
    """
    if value in (None, "", "-"):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for shape in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
                  "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, shape).date()
        except ValueError:
            continue
    raise PlannerError(
        f"{what} {value!r} is not a date. Write it as 2026-09-30.")


def _percent(value: Any, what: str = "Percent complete") -> int:
    if value in (None, ""):
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PlannerError(f"{what} {value!r} is not a number.") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise PlannerError(f"{what} {value!r} is not a number.")
    if not 0 <= number <= 100:
        raise PlannerError(
            f"{what} must be between 0 and 100. {value!r} is not.")
    return int(round(number))


def _weight(value: Any) -> float:
    if value in (None, ""):
        return 1.0
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PlannerError(f"Weight {value!r} is not a number.") from exc
    if number < 0 or number != number:
        raise PlannerError("Weight cannot be negative.")
    return number


def _now() -> datetime:
    return datetime.now(UTC)


def _text(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


# =============================================================== the history


def record(session: Any, project_id: int, *, entity_type: str,
           entity_id: int | None, entity_code: str, action: str,
           author_id: int | None, source: str = SOURCE_UI,
           old_status: str = "", new_status: str = "",
           old_percent: int | None = None, new_percent: int | None = None,
           narrative: str = "", blocker: str = "", next_step: str = "",
           changes: dict[str, Any] | None = None) -> PlannerUpdate:
    """Append one history row. Never updates, never deletes."""
    row = PlannerUpdate(
        project_id=int(project_id), entity_type=entity_type,
        entity_id=entity_id, entity_code=str(entity_code or ""),
        author_id=author_id, action=str(action),
        old_status=str(old_status or ""), new_status=str(new_status or ""),
        old_percent=old_percent, new_percent=new_percent,
        narrative=_text(narrative), blocker=_text(blocker),
        next_step=_text(next_step), changes=dict(changes or {}),
        source=_one_of(source, SOURCES, "source", SOURCE_UI))
    session.add(row)
    return row


def audit(session: Any, action: str, *, actor_id: int | None,
          project_id: int, source: str = SOURCE_UI, **detail: Any) -> None:
    """Governance evidence, inside the caller's transaction.

    Reuses the platform's own audit table rather than inventing a second one:
    "who did what to what, when" is already a solved problem here, and a
    parallel log is a log nobody reads.
    """
    collaboration.audit(
        session, action, actor_id=actor_id,
        object_type="planner_project", object_id=str(project_id),
        source=source, **detail)


def _bump(row: Any, user_id: int | None, expected: int | None = None) -> None:
    """Optimistic concurrency: refuse a write built on a stale read.

    Two managers editing the same task from two screens is not hypothetical,
    and last-write-wins loses the first one silently. A caller that sends the
    version it read gets told; a caller that sends nothing keeps the old
    behaviour, because an agent applying a change it just computed has no
    stale read to guard against.
    """
    if expected is not None and int(expected) != int(row.version or 1):
        raise StaleWrite(
            f"This was changed by somebody else while you were editing it "
            f"(you have version {expected}, it is now {row.version}). Reload "
            "and apply your change again.")
    row.version = int(row.version or 1) + 1
    if hasattr(row, "updated_by"):
        row.updated_by = user_id


# ============================================================ projects


def create_project(session: Any, principal: Any, *, code: str, name: str,
                   description: str = "", objective: str = "",
                   business_context: str = "",
                   status: str = "DRAFT", priority: str = "MEDIUM",
                   sponsor_id: int | None = None,
                   manager_id: int | None = None,
                   team_id: int | None = None,
                   start_date: Any = None, target_end_date: Any = None,
                   reporting_cadence: str = "WEEKLY",
                   reminder_days: list[int] | None = None,
                   stale_after_days: int = 7,
                   source: str = SOURCE_UI) -> PlannerProject:
    """Start a project. The creator becomes its owner.

    Somebody has to be able to administer it from the first second, and a
    project whose creator cannot add the second participant is a project that
    needs an administrator to be usable at all.
    """
    code = check_code(code, "Project code")
    if not str(name or "").strip():
        raise PlannerError("A project needs a name.")
    existing = session.execute(
        select(PlannerProject).where(
            func.lower(PlannerProject.code) == code.lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise PlannerError(
            f"Project code {code} is already used by "
            f"{existing.name!r}. Codes are unique across the platform.")

    start = _as_date(start_date, "Start date")
    target = _as_date(target_end_date, "Target end date")
    if start and target and target < start:
        raise PlannerError(
            f"The target end date ({target}) is before the start date "
            f"({start}).")

    user_id = getattr(principal, "user_id", None)
    project = PlannerProject(
        code=code, name=_text(name, 200), description=_text(description),
        objective=_text(objective), business_context=_text(business_context),
        status=_one_of(status, PROJECT_STATUSES, "project status", "DRAFT"),
        priority=_one_of(priority, PRIORITIES, "priority", "MEDIUM"),
        sponsor_id=sponsor_id, manager_id=manager_id, team_id=team_id,
        start_date=start, target_end_date=target,
        reporting_cadence=_one_of(reporting_cadence, CADENCES, "cadence",
                                  "WEEKLY"),
        reminder_days=[int(d) for d in (reminder_days
                                        or control.DEFAULT_POLICY
                                        .reminder_days)],
        stale_after_days=max(1, int(stale_after_days or 7)),
        created_by=user_id, updated_by=user_id)
    session.add(project)
    session.flush()

    session.add(PlannerParticipant(
        project_id=project.id, user_id=user_id, project_role="PROJECT_OWNER",
        access=ACCESS_OWNER, added_by=user_id))
    if manager_id and manager_id != user_id:
        session.add(PlannerParticipant(
            project_id=project.id, user_id=int(manager_id),
            project_role="PROJECT_MANAGER", access=ACCESS_EDITOR,
            added_by=user_id))
    session.flush()

    record(session, project.id, entity_type=ENTITY_PROJECT,
           entity_id=project.id, entity_code=code, action="created",
           author_id=user_id, source=source,
           new_status=project.status,
           narrative=f"{project.name} was created.")
    audit(session, "PLANNER_PROJECT_CREATED", actor_id=user_id,
          project_id=project.id, source=source, code=code, name=project.name)
    return project


def update_project(session: Any, principal: Any, project_id: int, *,
                   expected_version: int | None = None,
                   source: str = SOURCE_UI, **fields: Any) -> PlannerProject:
    """Change a project's own attributes. Editor access or better."""
    acl.require(session, project_id, principal, ACCESS_EDITOR,
                "change the project")
    project = session.get(PlannerProject, int(project_id))
    user_id = getattr(principal, "user_id", None)

    changes: dict[str, Any] = {}
    simple = {"name": 200, "description": 4000, "objective": 4000,
              "business_context": 4000}
    for key, limit in simple.items():
        if key in fields and fields[key] is not None:
            new = _text(fields[key], limit)
            if new != getattr(project, key):
                changes[key] = [getattr(project, key), new]
                setattr(project, key, new)

    if "status" in fields and fields["status"]:
        new = _one_of(fields["status"], PROJECT_STATUSES, "project status")
        if new != project.status:
            changes["status"] = [project.status, new]
            project.status = new
    if "priority" in fields and fields["priority"]:
        new = _one_of(fields["priority"], PRIORITIES, "priority")
        if new != project.priority:
            changes["priority"] = [project.priority, new]
            project.priority = new
    if "reporting_cadence" in fields and fields["reporting_cadence"]:
        project.reporting_cadence = _one_of(
            fields["reporting_cadence"], CADENCES, "cadence")

    for key in ("start_date", "target_end_date", "actual_end_date"):
        if key in fields:
            new_date = _as_date(fields[key], key.replace("_", " ").title())
            if new_date != getattr(project, key):
                changes[key] = [str(getattr(project, key) or ""),
                                str(new_date or "")]
                setattr(project, key, new_date)

    for key in ("sponsor_id", "manager_id", "team_id"):
        if key in fields:
            new_id = fields[key]
            new_id = int(new_id) if new_id else None
            if new_id != getattr(project, key):
                changes[key] = [getattr(project, key), new_id]
                setattr(project, key, new_id)

    if "stale_after_days" in fields and fields["stale_after_days"]:
        project.stale_after_days = max(1, int(fields["stale_after_days"]))
    if "reminder_days" in fields and fields["reminder_days"] is not None:
        project.reminder_days = sorted(
            {int(d) for d in fields["reminder_days"] if int(d) >= 0},
            reverse=True)

    if (project.start_date and project.target_end_date
            and project.target_end_date < project.start_date):
        raise PlannerError(
            f"The target end date ({project.target_end_date}) is before the "
            f"start date ({project.start_date}).")

    if not changes:
        return project
    _bump(project, user_id, expected_version)
    record(session, project.id, entity_type=ENTITY_PROJECT,
           entity_id=project.id, entity_code=project.code, action="updated",
           author_id=user_id, source=source, changes=changes,
           new_status=project.status)
    audit(session, "PLANNER_PROJECT_UPDATED", actor_id=user_id,
          project_id=project.id, source=source, fields=sorted(changes))
    return project


def set_health_override(session: Any, principal: Any, project_id: int, *,
                        health: str, reason: str,
                        source: str = SOURCE_UI) -> PlannerProject:
    """A person disagrees with the engine, on the record.

    The calculated value is never overwritten. Both are kept, with who
    overrode it and why, so a reader can see that a project the rules call RED
    is being reported AMBER and by whom.
    """
    acl.require(session, project_id, principal, ACCESS_EDITOR,
                "override project health")
    project = session.get(PlannerProject, int(project_id))
    user_id = getattr(principal, "user_id", None)
    wanted = "" if not health else _one_of(health, HEALTHS, "health")
    if wanted and not str(reason or "").strip():
        raise PlannerError(
            "An override needs a reason. A colour nobody can explain is worse "
            "than the calculation it replaces.")
    before = project.manual_health
    project.manual_health = wanted
    project.manual_health_reason = _text(reason)
    project.manual_health_by = user_id if wanted else None
    project.manual_health_at = _now() if wanted else None
    _bump(project, user_id)
    record(session, project.id, entity_type=ENTITY_PROJECT,
           entity_id=project.id, entity_code=project.code, action="health",
           author_id=user_id, source=source,
           old_status=before, new_status=wanted,
           narrative=(f"Health reported as {wanted}: {reason}" if wanted
                      else "Health override removed; the calculated value "
                           "applies again."))
    audit(session, "PLANNER_HEALTH_OVERRIDE", actor_id=user_id,
          project_id=project.id, source=source, health=wanted, reason=reason)
    return project


# ========================================================== participants


def add_participant(session: Any, principal: Any, project_id: int, *,
                    user_id: int, project_role: str = "CONTRIBUTOR",
                    access: str = ACCESS_CONTRIBUTOR,
                    workstream_id: int | None = None,
                    notifications_enabled: bool = True, notes: str = "",
                    source: str = SOURCE_UI) -> PlannerParticipant:
    """Put somebody on the project.

    Owner access is required, and an EDITOR cannot grant OWNER: a participant
    who can promote themselves has, in effect, owner access already, and that
    is the escalation this check exists to stop.
    """
    granted = acl.require(session, project_id, principal, ACCESS_OWNER,
                          "manage participants")
    wanted = _one_of(access, ACCESS_LEVELS, "access level",
                     ACCESS_CONTRIBUTOR)
    role = _one_of(project_role, PROJECT_ROLES, "project role", "CONTRIBUTOR")
    if (ACCESS_LEVELS.index(wanted) > ACCESS_LEVELS.index(granted.access)
            and not granted.administrative):
        raise acl.ProjectDenied(
            f"You cannot grant {wanted} access, which is above your own "
            f"{granted.access} access on this project.")

    actor = getattr(principal, "user_id", None)
    existing = session.execute(
        select(PlannerParticipant).where(
            PlannerParticipant.project_id == int(project_id),
            PlannerParticipant.user_id == int(user_id))
    ).scalar_one_or_none()
    if existing is not None:
        before = existing.access
        existing.access = wanted
        existing.project_role = role
        existing.workstream_id = workstream_id
        existing.notifications_enabled = bool(notifications_enabled)
        existing.notes = _text(notes, 500)
        record(session, project_id, entity_type=ENTITY_PROJECT,
               entity_id=int(project_id), entity_code="", action="membership",
               author_id=actor, source=source,
               changes={"user_id": user_id, "access": [before, wanted]},
               narrative=f"Access changed from {before} to {wanted}.")
        audit(session, "PLANNER_PARTICIPANT_UPDATED", actor_id=actor,
              project_id=int(project_id), source=source,
              subject_user=int(user_id), access=wanted, role=role)
        return existing

    row = PlannerParticipant(
        project_id=int(project_id), user_id=int(user_id), project_role=role,
        access=wanted, workstream_id=workstream_id,
        notifications_enabled=bool(notifications_enabled),
        notes=_text(notes, 500), added_by=actor)
    session.add(row)
    session.flush()
    record(session, project_id, entity_type=ENTITY_PROJECT,
           entity_id=int(project_id), entity_code="", action="membership",
           author_id=actor, source=source,
           changes={"user_id": int(user_id), "access": ["", wanted],
                    "role": role},
           narrative=f"Added to the project as {role.replace('_', ' ').lower()}.")
    audit(session, "PLANNER_PARTICIPANT_ADDED", actor_id=actor,
          project_id=int(project_id), source=source,
          subject_user=int(user_id), access=wanted, role=role)
    return row


def remove_participant(session: Any, principal: Any, project_id: int, *,
                       user_id: int, source: str = SOURCE_UI) -> None:
    """Take somebody off. The last owner cannot be removed.

    A project with no owner cannot be administered by anybody except a
    platform administrator, which is a support ticket rather than a state the
    product should let somebody create by accident.
    """
    acl.require(session, project_id, principal, ACCESS_OWNER,
                "manage participants")
    actor = getattr(principal, "user_id", None)
    row = session.execute(
        select(PlannerParticipant).where(
            PlannerParticipant.project_id == int(project_id),
            PlannerParticipant.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        return
    if row.access == ACCESS_OWNER:
        owners = session.execute(
            select(func.count()).select_from(PlannerParticipant).where(
                PlannerParticipant.project_id == int(project_id),
                PlannerParticipant.access == ACCESS_OWNER)).scalar_one()
        if int(owners) <= 1:
            raise PlannerError(
                "This is the project's only owner. Give somebody else owner "
                "access first, or the project cannot be administered.")
    session.delete(row)
    record(session, project_id, entity_type=ENTITY_PROJECT,
           entity_id=int(project_id), entity_code="", action="membership",
           author_id=actor, source=source,
           changes={"user_id": int(user_id), "access": [row.access, ""]},
           narrative="Removed from the project.")
    audit(session, "PLANNER_PARTICIPANT_REMOVED", actor_id=actor,
          project_id=int(project_id), source=source,
          subject_user=int(user_id))


# =========================================================== workstreams


def create_workstream(session: Any, principal: Any, project_id: int, *,
                      code: str, name: str, description: str = "",
                      lead_id: int | None = None, status: str = "ACTIVE",
                      start_date: Any = None, target_end_date: Any = None,
                      sequence: int = 0,
                      source: str = SOURCE_UI) -> PlannerWorkstream:
    acl.require(session, project_id, principal, ACCESS_EDITOR,
                "add a workstream")
    code = check_code(code, "Workstream code")
    if not str(name or "").strip():
        raise PlannerError("A workstream needs a name.")
    clash = session.execute(
        select(PlannerWorkstream).where(
            PlannerWorkstream.project_id == int(project_id),
            PlannerWorkstream.code == code)).scalar_one_or_none()
    if clash is not None:
        raise PlannerError(
            f"Workstream {code} already exists on this project.")
    actor = getattr(principal, "user_id", None)
    row = PlannerWorkstream(
        project_id=int(project_id), code=code, name=_text(name, 200),
        description=_text(description), lead_id=lead_id,
        status=_one_of(status, PROJECT_STATUSES, "status", "ACTIVE"),
        start_date=_as_date(start_date, "Start date"),
        target_end_date=_as_date(target_end_date, "Target end date"),
        sequence=int(sequence or 0))
    session.add(row)
    session.flush()
    record(session, project_id, entity_type="WORKSTREAM", entity_id=row.id,
           entity_code=code, action="created", author_id=actor, source=source,
           narrative=f"Workstream {name} was created.")
    return row


# ================================================================= tasks


def _resolve_workstream(session: Any, project_id: int,
                        workstream_id: int | None) -> int | None:
    """A workstream id that belongs to THIS project, or a refusal.

    Without this check a caller can attach a task to a workstream on somebody
    else's project by sending its id, which is a cross-project write dressed
    up as a foreign key.
    """
    if workstream_id in (None, ""):
        return None
    row = session.get(PlannerWorkstream, int(workstream_id))
    if row is None or int(row.project_id) != int(project_id):
        raise PlannerError(
            f"Workstream {workstream_id} is not part of this project.")
    return int(workstream_id)


def create_task(session: Any, principal: Any, project_id: int, *,
                code: str, title: str, description: str = "",
                workstream_id: int | None = None,
                parent_id: int | None = None,
                owner_id: int | None = None, reviewer_id: int | None = None,
                contributor_ids: list[int] | None = None,
                status: str = "NOT_STARTED", priority: str = "MEDIUM",
                start_date: Any = None, due_date: Any = None,
                effort_days: Any = None, weight: Any = 1,
                percent_complete: Any = 0, critical: bool = False,
                blocked: bool = False, blocker_reason: str = "",
                next_step: str = "", tags: list[str] | None = None,
                notes: str = "", source: str = SOURCE_UI) -> PlannerTask:
    acl.require(session, project_id, principal, ACCESS_EDITOR, "add a task")
    code = check_code(code, "Task code")
    if not str(title or "").strip():
        raise PlannerError("A task needs a title.")
    clash = session.execute(
        select(PlannerTask).where(
            PlannerTask.project_id == int(project_id),
            PlannerTask.code == code)).scalar_one_or_none()
    if clash is not None:
        raise PlannerError(f"Task {code} already exists on this project.")

    parent = None
    if parent_id:
        parent = session.get(PlannerTask, int(parent_id))
        if parent is None or int(parent.project_id) != int(project_id):
            raise PlannerError(
                f"Parent task {parent_id} is not part of this project.")

    start = _as_date(start_date, "Start date")
    due = _as_date(due_date, "Due date")
    if start and due and due < start:
        raise PlannerError(
            f"{code}: the due date ({due}) is before the start date "
            f"({start}).")

    actor = getattr(principal, "user_id", None)
    state = _one_of(status, TASK_STATUSES, "task status", "NOT_STARTED")
    row = PlannerTask(
        project_id=int(project_id), code=code, title=_text(title, 300),
        description=_text(description),
        workstream_id=_resolve_workstream(session, project_id, workstream_id),
        parent_id=int(parent_id) if parent else None,
        owner_id=owner_id, reviewer_id=reviewer_id,
        contributor_ids=[int(c) for c in (contributor_ids or [])],
        status=state,
        priority=_one_of(priority, PRIORITIES, "priority", "MEDIUM"),
        start_date=start, due_date=due,
        effort_days=int(effort_days) if effort_days not in (None, "") else None,
        weight=_weight(weight),
        percent_complete=_percent(percent_complete),
        critical=bool(critical), blocked=bool(blocked),
        blocker_reason=_text(blocker_reason), next_step=_text(next_step),
        tags=[str(t) for t in (tags or [])], notes=_text(notes),
        created_by=actor, updated_by=actor)
    _align_task_state(row)
    session.add(row)
    session.flush()
    record(session, project_id, entity_type=ENTITY_TASK, entity_id=row.id,
           entity_code=code, action="created", author_id=actor, source=source,
           new_status=row.status, new_percent=row.percent_complete,
           narrative=f"{code} — {row.title} was created.")
    return row


def _align_task_state(task: Any) -> None:
    """Keep status, progress, the blocked flag and the completion date honest.

    These four are separate columns that describe one situation, and letting
    them disagree is how a task shows COMPLETED at 40% or BLOCKED with no
    blocker. The rules are deliberately one-directional — status leads — so a
    person setting a status never has to also remember to fix three fields.
    """
    if task.status == TASK_COMPLETED:
        task.percent_complete = 100
        task.blocked = False
        task.blocker_reason = ""
        if task.completed_date is None:
            task.completed_date = date.today()
    elif task.status == TASK_CANCELLED:
        task.blocked = False
        task.blocker_reason = ""
    else:
        task.completed_date = None
        if task.percent_complete >= 100:
            # 100% but not marked complete is a status somebody has not
            # pressed yet, not a completion. Held at 99 so the two agree
            # without the engine deciding on somebody's behalf that the work
            # is done.
            task.percent_complete = 99
    if task.status == "BLOCKED":
        task.blocked = True
    if task.blocked and task.status not in ("BLOCKED",) and task.status not in (
            TASK_COMPLETED, TASK_CANCELLED):
        task.status = "BLOCKED"


def update_task(session: Any, principal: Any, task_id: int, *,
                expected_version: int | None = None,
                narrative: str = "", source: str = SOURCE_UI,
                **fields: Any) -> PlannerTask:
    """Change a task, and say what changed.

    This is the function the whole product turns on: it is what a person uses
    to say "70% done, waiting on Finance, expect Friday", what the API exposes
    and what the agent calls. One implementation, one permission check, one
    history row, whichever door the change came through.
    """
    task, _granted = acl.visible_task(session, task_id, principal)
    acl.may_update_task(session, task, principal)
    actor = getattr(principal, "user_id", None)

    before_status = task.status
    before_percent = int(task.percent_complete or 0)
    changes: dict[str, Any] = {}

    if "title" in fields and fields["title"] is not None:
        new = _text(fields["title"], 300)
        if new and new != task.title:
            changes["title"] = [task.title, new]
            task.title = new
    if "description" in fields and fields["description"] is not None:
        task.description = _text(fields["description"])
    if "notes" in fields and fields["notes"] is not None:
        task.notes = _text(fields["notes"])

    if "status" in fields and fields["status"]:
        new = _one_of(fields["status"], TASK_STATUSES, "task status")
        if new != task.status:
            changes["status"] = [task.status, new]
            task.status = new
    if "percent_complete" in fields and fields["percent_complete"] is not None:
        new_pct = _percent(fields["percent_complete"])
        if new_pct != task.percent_complete:
            changes["percent_complete"] = [task.percent_complete, new_pct]
            task.percent_complete = new_pct
    if "priority" in fields and fields["priority"]:
        task.priority = _one_of(fields["priority"], PRIORITIES, "priority")

    # Reassignment and date changes are editor work. A contributor updating
    # their own task can say how it is going; handing it to somebody else or
    # moving the date is a change to the commitment, not a report on it.
    restricted = {"owner_id", "reviewer_id", "contributor_ids", "due_date",
                  "start_date", "weight", "critical", "workstream_id",
                  "parent_id", "code"}
    wanted = restricted & {k for k, v in fields.items() if v is not None}
    if wanted:
        acl.require(session, int(task.project_id), principal, ACCESS_EDITOR,
                    "change " + ", ".join(sorted(
                        k.replace("_id", "").replace("_", " ")
                        for k in wanted)))

    for key in ("owner_id", "reviewer_id"):
        if key in fields:
            new_id = int(fields[key]) if fields[key] else None
            if new_id != getattr(task, key):
                changes[key] = [getattr(task, key), new_id]
                setattr(task, key, new_id)
    if "contributor_ids" in fields and fields["contributor_ids"] is not None:
        task.contributor_ids = [int(c) for c in fields["contributor_ids"]]
    for key in ("start_date", "due_date"):
        if key in fields:
            new_date = _as_date(fields[key], key.replace("_", " ").title())
            if new_date != getattr(task, key):
                changes[key] = [str(getattr(task, key) or ""),
                                str(new_date or "")]
                setattr(task, key, new_date)
    if "weight" in fields and fields["weight"] is not None:
        task.weight = _weight(fields["weight"])
    if "critical" in fields and fields["critical"] is not None:
        task.critical = bool(fields["critical"])
    if "workstream_id" in fields:
        task.workstream_id = _resolve_workstream(
            session, int(task.project_id), fields["workstream_id"])

    if "blocked" in fields and fields["blocked"] is not None:
        was = bool(task.blocked)
        task.blocked = bool(fields["blocked"])
        if task.blocked != was:
            changes["blocked"] = [was, task.blocked]
    if "blocker_reason" in fields and fields["blocker_reason"] is not None:
        task.blocker_reason = _text(fields["blocker_reason"])
    if "next_step" in fields and fields["next_step"] is not None:
        task.next_step = _text(fields["next_step"])
    if "tags" in fields and fields["tags"] is not None:
        task.tags = [str(t) for t in fields["tags"]]

    if task.blocked and not task.blocker_reason.strip():
        raise PlannerError(
            "A blocked task needs a reason. 'Blocked' with no explanation "
            "tells the project manager nothing they can act on.")
    if (task.start_date and task.due_date
            and task.due_date < task.start_date):
        raise PlannerError(
            f"{task.code}: the due date ({task.due_date}) is before the "
            f"start date ({task.start_date}).")

    _align_task_state(task)

    said = _text(narrative)
    if not changes and not said:
        return task

    _bump(task, actor, expected_version)
    task.last_update_at = _now()
    task.last_update_by = actor
    if said:
        task.last_update_text = said

    record(session, int(task.project_id), entity_type=ENTITY_TASK,
           entity_id=int(task.id), entity_code=task.code,
           action=("status" if "status" in changes
                   else "progress" if "percent_complete" in changes
                   else "comment" if said and not changes else "updated"),
           author_id=actor, source=source,
           old_status=before_status, new_status=task.status,
           old_percent=before_percent, new_percent=task.percent_complete,
           narrative=said, blocker=task.blocker_reason,
           next_step=task.next_step, changes=changes)
    audit(session, "PLANNER_TASK_UPDATED", actor_id=actor,
          project_id=int(task.project_id), source=source,
          task=task.code, fields=sorted(changes))
    return task


def delete_task(session: Any, principal: Any, task_id: int, *,
                source: str = SOURCE_UI) -> None:
    """Remove a task, and the dependencies that pointed at it.

    Leaving the edges behind produces dependency findings about a task that no
    longer exists, which reads as a bug in the engine. The history rows stay:
    they record what happened, and what happened does not stop having happened
    because the task was deleted.
    """
    task, _ = acl.visible_task(session, task_id, principal)
    acl.require(session, int(task.project_id), principal, ACCESS_EDITOR,
                "delete a task")
    actor = getattr(principal, "user_id", None)
    project_id, code = int(task.project_id), task.code

    orphans = session.execute(
        select(PlannerDependency).where(
            PlannerDependency.project_id == project_id,
            ((PlannerDependency.predecessor_type == ENTITY_TASK)
             & (PlannerDependency.predecessor_id == int(task.id)))
            | ((PlannerDependency.successor_type == ENTITY_TASK)
               & (PlannerDependency.successor_id == int(task.id))))
    ).scalars().all()
    for edge in orphans:
        session.delete(edge)
    session.delete(task)
    record(session, project_id, entity_type=ENTITY_TASK, entity_id=None,
           entity_code=code, action="deleted", author_id=actor, source=source,
           narrative=f"{code} was deleted."
                     + (f" {len(orphans)} dependency link"
                        f"{'' if len(orphans) == 1 else 's'} removed with it."
                        if orphans else ""))
    audit(session, "PLANNER_TASK_DELETED", actor_id=actor,
          project_id=project_id, source=source, task=code,
          dependencies_removed=len(orphans))


# ============================================================ milestones


def create_milestone(session: Any, principal: Any, project_id: int, *,
                     code: str, name: str, description: str = "",
                     workstream_id: int | None = None,
                     owner_id: int | None = None, target_date: Any = None,
                     status: str = "PENDING", critical: bool = False,
                     source: str = SOURCE_UI) -> PlannerMilestone:
    acl.require(session, project_id, principal, ACCESS_EDITOR,
                "add a milestone")
    code = check_code(code, "Milestone code")
    if not str(name or "").strip():
        raise PlannerError("A milestone needs a name.")
    clash = session.execute(
        select(PlannerMilestone).where(
            PlannerMilestone.project_id == int(project_id),
            PlannerMilestone.code == code)).scalar_one_or_none()
    if clash is not None:
        raise PlannerError(f"Milestone {code} already exists on this project.")
    actor = getattr(principal, "user_id", None)
    row = PlannerMilestone(
        project_id=int(project_id), code=code, name=_text(name, 300),
        description=_text(description),
        workstream_id=_resolve_workstream(session, project_id, workstream_id),
        owner_id=owner_id, target_date=_as_date(target_date, "Target date"),
        status=_one_of(status, MILESTONE_STATUSES, "milestone status",
                       "PENDING"),
        critical=bool(critical), created_by=actor, updated_by=actor)
    session.add(row)
    session.flush()
    record(session, project_id, entity_type=ENTITY_MILESTONE,
           entity_id=row.id, entity_code=code, action="created",
           author_id=actor, source=source, new_status=row.status,
           narrative=f"Milestone {name} was created.")
    return row


def update_milestone(session: Any, principal: Any, milestone_id: int, *,
                     expected_version: int | None = None,
                     narrative: str = "", source: str = SOURCE_UI,
                     **fields: Any) -> PlannerMilestone:
    row = session.get(PlannerMilestone, int(milestone_id))
    if row is None:
        raise acl.ProjectNotFound(f"No milestone {milestone_id}.")
    acl.require(session, int(row.project_id), principal, ACCESS_EDITOR,
                "change a milestone")
    actor = getattr(principal, "user_id", None)
    before = row.status
    changes: dict[str, Any] = {}

    if "name" in fields and fields["name"]:
        row.name = _text(fields["name"], 300)
    if "description" in fields and fields["description"] is not None:
        row.description = _text(fields["description"])
    if "owner_id" in fields:
        row.owner_id = int(fields["owner_id"]) if fields["owner_id"] else None
    if "critical" in fields and fields["critical"] is not None:
        row.critical = bool(fields["critical"])
    if "target_date" in fields:
        new_date = _as_date(fields["target_date"], "Target date")
        if new_date != row.target_date:
            changes["target_date"] = [str(row.target_date or ""),
                                      str(new_date or "")]
            row.target_date = new_date
    if "actual_date" in fields:
        row.actual_date = _as_date(fields["actual_date"], "Actual date")
    if "status" in fields and fields["status"]:
        new = _one_of(fields["status"], MILESTONE_STATUSES,
                      "milestone status")
        if new != row.status:
            changes["status"] = [row.status, new]
            row.status = new
        if new == MILESTONE_ACHIEVED and row.actual_date is None:
            row.actual_date = date.today()

    if not changes and not narrative:
        return row
    _bump(row, actor, expected_version)
    record(session, int(row.project_id), entity_type=ENTITY_MILESTONE,
           entity_id=int(row.id), entity_code=row.code,
           action="status" if "status" in changes else "updated",
           author_id=actor, source=source, old_status=before,
           new_status=row.status, narrative=_text(narrative),
           changes=changes)
    audit(session, "PLANNER_MILESTONE_UPDATED", actor_id=actor,
          project_id=int(row.project_id), source=source, milestone=row.code,
          fields=sorted(changes))
    return row


# ========================================================== dependencies


def _entity_in_project(session: Any, project_id: int, kind: str,
                       entity_id: int) -> Any:
    kind = _one_of(kind, ENTITY_TYPES, "entity type", ENTITY_TASK)
    model = PlannerTask if kind == ENTITY_TASK else PlannerMilestone
    row = session.get(model, int(entity_id))
    if row is None or int(row.project_id) != int(project_id):
        raise PlannerError(
            f"{kind.title()} {entity_id} is not part of this project.")
    return row


def create_dependency(session: Any, principal: Any, project_id: int, *,
                      predecessor_type: str, predecessor_id: int,
                      successor_type: str, successor_id: int,
                      dependency_type: str = "FS", lag_days: int = 0,
                      notes: str = "",
                      source: str = SOURCE_UI) -> PlannerDependency:
    """Link two things, unless that would make a cycle.

    The cycle check runs over the graph AS IT WOULD BE, not as it is. Checking
    afterwards and rolling back leaves the caller with a partially applied
    import and no explanation.
    """
    acl.require(session, project_id, principal, ACCESS_EDITOR,
                "add a dependency")
    pred_kind = _one_of(predecessor_type, ENTITY_TYPES, "entity type",
                        ENTITY_TASK)
    succ_kind = _one_of(successor_type, ENTITY_TYPES, "entity type",
                        ENTITY_TASK)
    _entity_in_project(session, project_id, pred_kind, predecessor_id)
    _entity_in_project(session, project_id, succ_kind, successor_id)
    if (pred_kind, int(predecessor_id)) == (succ_kind, int(successor_id)):
        raise PlannerError("Something cannot depend on itself.")

    existing = [control.DependencyView.of(d) for d in session.execute(
        select(PlannerDependency).where(
            PlannerDependency.project_id == int(project_id))).scalars()]
    proposed = control.DependencyView(
        pred_kind, int(predecessor_id), succ_kind, int(successor_id))
    found = control.cycle([*existing, proposed])
    if found:
        trail = " → ".join(_pretty(session, k, i) for k, i in found)
        raise PlannerError(
            f"That dependency would create a circular chain: {trail}. "
            "Nothing in it could ever start.")

    actor = getattr(principal, "user_id", None)
    row = PlannerDependency(
        project_id=int(project_id), predecessor_type=pred_kind,
        predecessor_id=int(predecessor_id), successor_type=succ_kind,
        successor_id=int(successor_id),
        dependency_type=_one_of(dependency_type, DEPENDENCY_TYPES,
                                "dependency type", "FS"),
        lag_days=int(lag_days or 0), notes=_text(notes, 500),
        created_by=actor)
    session.add(row)
    session.flush()
    record(session, project_id, entity_type=succ_kind,
           entity_id=int(successor_id),
           entity_code=_code_of(session, succ_kind, successor_id),
           action="dependency", author_id=actor, source=source,
           narrative=(f"Now waits on "
                      f"{_pretty(session, pred_kind, predecessor_id)}."))
    return row


def _code_of(session: Any, kind: str, entity_id: int) -> str:
    model = PlannerTask if kind == ENTITY_TASK else PlannerMilestone
    row = session.get(model, int(entity_id))
    return str(row.code) if row is not None else ""


def _pretty(session: Any, kind: str, entity_id: int) -> str:
    model = PlannerTask if kind == ENTITY_TASK else PlannerMilestone
    row = session.get(model, int(entity_id))
    if row is None:
        return f"{kind.lower()} {entity_id}"
    return str(row.code)


def delete_dependency(session: Any, principal: Any, dependency_id: int, *,
                      source: str = SOURCE_UI) -> None:
    row = session.get(PlannerDependency, int(dependency_id))
    if row is None:
        raise acl.ProjectNotFound(f"No dependency {dependency_id}.")
    acl.require(session, int(row.project_id), principal, ACCESS_EDITOR,
                "remove a dependency")
    actor = getattr(principal, "user_id", None)
    project_id = int(row.project_id)
    session.delete(row)
    record(session, project_id, entity_type=row.successor_type,
           entity_id=int(row.successor_id), entity_code="",
           action="dependency", author_id=actor, source=source,
           narrative="A dependency was removed.")


# ================================================================== RAID


def create_raid(session: Any, principal: Any, project_id: int, *,
                code: str = "", raid_type: str = "RISK", title: str,
                description: str = "", workstream_id: int | None = None,
                owner_id: int | None = None, raised_date: Any = None,
                target_date: Any = None, probability: str = "",
                impact: str = "", severity: str = "MEDIUM",
                status: str = "OPEN", mitigation: str = "",
                resolution: str = "", linked_entity_type: str = "",
                linked_entity_id: int | None = None,
                source: str = SOURCE_UI) -> PlannerRaid:
    """Open a risk, assumption, issue or decision.

    Contributors may raise one. Somebody who spots a risk while doing the work
    is exactly who should be able to record it, and making them ask an editor
    first is how risks stay in people's heads.
    """
    acl.require(session, project_id, principal, ACCESS_CONTRIBUTOR,
                "raise a RAID item")
    if not str(title or "").strip():
        raise PlannerError("A RAID item needs a title.")
    kind = _one_of(raid_type, RAID_TYPES, "RAID type", "RISK")
    code = check_code(code, "RAID code") if code else _next_raid_code(
        session, project_id, kind)
    clash = session.execute(
        select(PlannerRaid).where(
            PlannerRaid.project_id == int(project_id),
            PlannerRaid.code == code)).scalar_one_or_none()
    if clash is not None:
        raise PlannerError(f"RAID item {code} already exists on this project.")

    actor = getattr(principal, "user_id", None)
    row = PlannerRaid(
        project_id=int(project_id), code=code, raid_type=kind,
        title=_text(title, 300), description=_text(description),
        workstream_id=_resolve_workstream(session, project_id, workstream_id),
        owner_id=owner_id,
        raised_date=_as_date(raised_date, "Date raised") or date.today(),
        target_date=_as_date(target_date, "Target resolution date"),
        probability=_text(probability, 16).upper(),
        impact=_text(impact, 16).upper(),
        severity=_one_of(severity, SEVERITIES, "severity", "MEDIUM"),
        status=_one_of(status, RAID_STATUSES, "RAID status", "OPEN"),
        mitigation=_text(mitigation), resolution=_text(resolution),
        linked_entity_type=(_one_of(linked_entity_type, ENTITY_TYPES,
                                    "entity type")
                            if linked_entity_type else ""),
        linked_entity_id=int(linked_entity_id) if linked_entity_id else None,
        created_by=actor, updated_by=actor)
    session.add(row)
    session.flush()
    record(session, project_id, entity_type=ENTITY_RAID, entity_id=row.id,
           entity_code=code, action="created", author_id=actor, source=source,
           new_status=row.status,
           narrative=f"{kind.title()} raised: {row.title}")
    audit(session, "PLANNER_RAID_RAISED", actor_id=actor,
          project_id=int(project_id), source=source, code=code, kind=kind,
          severity=row.severity)
    return row


def _next_raid_code(session: Any, project_id: int, kind: str) -> str:
    prefix = {"RISK": "R", "ASSUMPTION": "A", "ISSUE": "I",
              "DECISION": "D"}.get(kind, "R")
    used = {str(c) for c in session.execute(
        select(PlannerRaid.code).where(
            PlannerRaid.project_id == int(project_id))).scalars()}
    n = 1
    while f"{prefix}-{n:03d}" in used:
        n += 1
    return f"{prefix}-{n:03d}"


def update_raid(session: Any, principal: Any, raid_id: int, *,
                expected_version: int | None = None,
                narrative: str = "", source: str = SOURCE_UI,
                **fields: Any) -> PlannerRaid:
    row = session.get(PlannerRaid, int(raid_id))
    if row is None:
        raise acl.ProjectNotFound(f"No RAID item {raid_id}.")
    acl.require(session, int(row.project_id), principal, ACCESS_CONTRIBUTOR,
                "update a RAID item")
    actor = getattr(principal, "user_id", None)
    before = row.status
    changes: dict[str, Any] = {}

    for key, limit in (("title", 300), ("description", 4000),
                       ("mitigation", 4000), ("resolution", 4000)):
        if key in fields and fields[key] is not None:
            setattr(row, key, _text(fields[key], limit))
    if "owner_id" in fields:
        row.owner_id = int(fields["owner_id"]) if fields["owner_id"] else None
    if "severity" in fields and fields["severity"]:
        new = _one_of(fields["severity"], SEVERITIES, "severity")
        if new != row.severity:
            changes["severity"] = [row.severity, new]
            row.severity = new
    if "status" in fields and fields["status"]:
        new = _one_of(fields["status"], RAID_STATUSES, "RAID status")
        if new != row.status:
            changes["status"] = [row.status, new]
            row.status = new
        if new in ("RESOLVED", "CLOSED") and row.resolved_date is None:
            row.resolved_date = date.today()
    if "target_date" in fields:
        row.target_date = _as_date(fields["target_date"], "Target date")
    if "probability" in fields and fields["probability"] is not None:
        row.probability = _text(fields["probability"], 16).upper()
    if "impact" in fields and fields["impact"] is not None:
        row.impact = _text(fields["impact"], 16).upper()

    if not changes and not narrative:
        return row
    _bump(row, actor, expected_version)
    record(session, int(row.project_id), entity_type=ENTITY_RAID,
           entity_id=int(row.id), entity_code=row.code,
           action="status" if "status" in changes else "updated",
           author_id=actor, source=source, old_status=before,
           new_status=row.status, narrative=_text(narrative),
           changes=changes)
    audit(session, "PLANNER_RAID_UPDATED", actor_id=actor,
          project_id=int(row.project_id), source=source, code=row.code,
          fields=sorted(changes))
    return row


def post_update(session: Any, principal: Any, project_id: int, *,
                narrative: str, entity_type: str = ENTITY_PROJECT,
                entity_id: int | None = None, blocker: str = "",
                next_step: str = "", source: str = SOURCE_UI) -> PlannerUpdate:
    """Say something about the project without changing anything.

    The weekly report, the answer to a chase, the note that Finance have
    finally come back. It is deliberately separate from `update_task`: a
    person who has nothing to change but something to say should not have to
    invent a percentage to be heard, and the reminder engine needs a way to
    see that somebody DID respond.

    Contributor access, because saying something is not changing something.
    """
    acl.require(session, project_id, principal, ACCESS_CONTRIBUTOR,
                "post an update")
    said = _text(narrative)
    if not said:
        raise PlannerError("An update needs something in it.")
    kind = _one_of(entity_type, ENTITY_TYPES, "entity type", ENTITY_PROJECT)

    code = ""
    if kind == ENTITY_PROJECT:
        project = session.get(PlannerProject, int(project_id))
        code = project.code
        entity_id = int(project_id)
    elif entity_id is not None:
        # An update filed against a task in somebody else's project would be
        # a way to write into a project you cannot see. Check the entity is
        # this project's before the row is written, not after.
        if not _entity_in_project(session, int(project_id), kind,
                                  int(entity_id)):
            raise PlannerError(
                f"{kind.title()} {entity_id} is not part of this project.")
        code = _code_of(session, kind, int(entity_id))

    actor = getattr(principal, "user_id", None)
    row = record(session, int(project_id), entity_type=kind,
                 entity_id=entity_id, entity_code=code, action="comment",
                 author_id=actor, source=source, narrative=said,
                 blocker=_text(blocker), next_step=_text(next_step))

    if kind == ENTITY_TASK and entity_id is not None:
        # A comment IS an update as far as staleness is concerned: the task
        # has been spoken about today, so nothing should chase it tomorrow.
        task = session.get(PlannerTask, int(entity_id))
        if task is not None:
            task.last_update_at = _now()
            task.last_update_by = actor
            task.last_update_text = said

    audit(session, "PLANNER_UPDATE_POSTED", actor_id=actor,
          project_id=int(project_id), source=source,
          entity_type=kind, entity_code=code)
    return row


__all__ = [
    "SERVICE_VERSION", "PlannerError", "StaleWrite", "check_code", "record",
    "audit", "create_project", "update_project", "set_health_override",
    "add_participant", "remove_participant", "create_workstream",
    "create_task", "update_task", "delete_task", "create_milestone",
    "update_milestone", "create_dependency", "delete_dependency",
    "create_raid", "update_raid", "post_update",
]
