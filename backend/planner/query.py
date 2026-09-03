"""Reading the plan.

One module, because the portfolio screen, My Work, the project detail page,
the scheduled monitor and every AI tool are all asking versions of the same
question, and four implementations of "which tasks are overdue" is four
opportunities for them to disagree in front of a user.

Everything here is permission-scoped at the query, not after it. `WHERE
project_id IN (the ones you may see)` is one round trip and cannot be
forgotten; filtering a full result set in Python is a filter somebody removes
during a refactor and nobody notices until the wrong project appears on
somebody's dashboard.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from backend.db.models import User
from backend.models.planner import (
    ENTITY_MILESTONE,
    HEALTH_UNKNOWN,
    MILESTONE_OPEN,
    PROJECT_OPEN,
    RAID_LIVE,
    TASK_OPEN,
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

QUERY_VERSION = "1.0.0"


def today() -> date:
    return datetime.now(UTC).date()


# ============================================================ people, once


def people(session: Any, user_ids: Any) -> dict[int, dict[str, Any]]:
    """Names for a set of user ids, in one query.

    Every screen shows owners, and looking each one up as the rows are
    rendered is the N+1 that makes a two-hundred-task plan take four seconds.
    """
    wanted = {int(u) for u in user_ids if u is not None}
    if not wanted:
        return {}
    rows = session.execute(select(User).where(User.id.in_(wanted))).scalars()
    return {int(u.id): {
        "id": int(u.id),
        "name": (f"{u.first_name} {u.last_name}".strip() or u.username),
        "username": u.username, "email": u.email or "",
        "job_title": u.job_title or "", "team": u.team or "",
    } for u in rows}


def _person(directory: dict[int, dict[str, Any]],
            user_id: int | None) -> dict[str, Any] | None:
    return directory.get(int(user_id)) if user_id is not None else None


# ================================================================== plans


def plan_of(session: Any, project_id: int) -> control.Plan:
    """Everything the control engine needs about one project, in five queries.

    Not per task, not per milestone. The monitor runs this over every active
    project and the difference between five queries and five hundred is the
    difference between a sweep that finishes and one that is killed.
    """
    project = session.get(PlannerProject, int(project_id))
    tasks = session.execute(
        select(PlannerTask).where(PlannerTask.project_id == int(project_id))
    ).scalars().all()
    milestones = session.execute(
        select(PlannerMilestone).where(
            PlannerMilestone.project_id == int(project_id))).scalars().all()
    deps = session.execute(
        select(PlannerDependency).where(
            PlannerDependency.project_id == int(project_id))).scalars().all()
    raid = session.execute(
        select(PlannerRaid.severity, PlannerRaid.status, PlannerRaid.title)
        .where(PlannerRaid.project_id == int(project_id))).all()
    return control.Plan(
        project_id=int(project_id),
        code=str(project.code) if project else "",
        name=str(project.name) if project else "",
        status=str(project.status) if project else "",
        target_end_date=project.target_end_date if project else None,
        tasks=[control.TaskView.of(t) for t in tasks],
        milestones=[control.MilestoneView.of(m) for m in milestones],
        dependencies=[control.DependencyView.of(d) for d in deps],
        raid=[(str(a), str(b), str(c)) for a, b, c in raid],
        stale_after_days=int(project.stale_after_days) if project else 7)


def plans_of(session: Any, project_ids: list[int]
             ) -> dict[int, control.Plan]:
    """The same for many projects, still in five queries in total."""
    ids = [int(i) for i in project_ids]
    if not ids:
        return {}
    projects = {int(p.id): p for p in session.execute(
        select(PlannerProject).where(PlannerProject.id.in_(ids))).scalars()}
    grouped_tasks: dict[int, list] = defaultdict(list)
    for row in session.execute(
            select(PlannerTask).where(
                PlannerTask.project_id.in_(ids))).scalars():
        grouped_tasks[int(row.project_id)].append(control.TaskView.of(row))
    grouped_ms: dict[int, list] = defaultdict(list)
    for row in session.execute(
            select(PlannerMilestone).where(
                PlannerMilestone.project_id.in_(ids))).scalars():
        grouped_ms[int(row.project_id)].append(control.MilestoneView.of(row))
    grouped_deps: dict[int, list] = defaultdict(list)
    for row in session.execute(
            select(PlannerDependency).where(
                PlannerDependency.project_id.in_(ids))).scalars():
        grouped_deps[int(row.project_id)].append(
            control.DependencyView.of(row))
    grouped_raid: dict[int, list] = defaultdict(list)
    for pid, sev, status, title in session.execute(
            select(PlannerRaid.project_id, PlannerRaid.severity,
                   PlannerRaid.status, PlannerRaid.title)
            .where(PlannerRaid.project_id.in_(ids))).all():
        grouped_raid[int(pid)].append((str(sev), str(status), str(title)))

    out: dict[int, control.Plan] = {}
    for pid in ids:
        project = projects.get(pid)
        out[pid] = control.Plan(
            project_id=pid,
            code=str(project.code) if project else "",
            name=str(project.name) if project else "",
            status=str(project.status) if project else "",
            target_end_date=project.target_end_date if project else None,
            tasks=grouped_tasks.get(pid, []),
            milestones=grouped_ms.get(pid, []),
            dependencies=grouped_deps.get(pid, []),
            raid=grouped_raid.get(pid, []),
            stale_after_days=(int(project.stale_after_days) if project
                              else 7))
    return out


def refresh_calculations(session: Any, project: Any, *,
                         now: date | None = None) -> control.Health:
    """Recompute a project's cached progress and health, and stamp it.

    Called after a mutation and by the monitor. The cache is what makes the
    portfolio screen one query; the stamp is what stops it claiming to be
    live when it is an hour old.
    """
    when = now or today()
    plan = plan_of(session, int(project.id))
    verdict = control.health(plan, when)
    project.calculated_percent_complete = control.progress(plan.tasks)
    project.calculated_health = verdict.status
    project.calculated_health_reason = verdict.reason
    project.calculated_at = datetime.now(UTC)
    return verdict


def effective_health(project: Any) -> tuple[str, str, bool]:
    """What to show, why, and whether a person overrode the calculation."""
    if project.manual_health:
        return (str(project.manual_health),
                str(project.manual_health_reason or ""), True)
    return (str(project.calculated_health or HEALTH_UNKNOWN),
            str(project.calculated_health_reason or ""), False)


# ============================================================== portfolio


def portfolio(session: Any, principal: Any, *, status: str = "",
              health: str = "", manager_id: int | None = None,
              search: str = "", include_archived: bool = False,
              limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """Every project this caller may see, with its live counts.

    The counts come from three grouped queries rather than from loading each
    plan. A portfolio of a hundred projects with two hundred tasks each is
    twenty thousand rows, and no dashboard needs to read them to say how many
    are overdue.
    """
    allowed = acl.readable_project_ids(session, principal)
    if not allowed:
        return {"projects": [], "count": 0, "totals": _empty_totals()}

    stmt = select(PlannerProject).where(PlannerProject.id.in_(allowed))
    if not include_archived:
        stmt = stmt.where(PlannerProject.archived.is_(False))
    if status:
        stmt = stmt.where(PlannerProject.status == status.upper())
    if manager_id:
        stmt = stmt.where(PlannerProject.manager_id == int(manager_id))
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(PlannerProject.name).like(like),
                              func.lower(PlannerProject.code).like(like)))
    projects = session.execute(
        stmt.order_by(PlannerProject.status, PlannerProject.name)).scalars(
        ).all()
    if health:
        wanted = health.upper()
        projects = [p for p in projects
                    if effective_health(p)[0] == wanted]

    ids = [int(p.id) for p in projects]
    counts = _counts(session, ids)
    directory = people(session, [p.manager_id for p in projects]
                       + [p.sponsor_id for p in projects])
    grants = acl.grants_for(session, principal)

    rows = []
    for project in projects[offset:offset + limit]:
        colour, reason, overridden = effective_health(project)
        pid = int(project.id)
        seen = counts.get(pid, {})
        rows.append({
            "id": pid, "code": project.code, "name": project.name,
            "status": project.status, "priority": project.priority,
            "health": colour, "health_reason": reason,
            "health_overridden": overridden,
            "percent_complete": int(project.calculated_percent_complete or 0),
            "calculated_at": (project.calculated_at.isoformat()
                              if project.calculated_at else None),
            "manager": _person(directory, project.manager_id),
            "sponsor": _person(directory, project.sponsor_id),
            "start_date": _iso(project.start_date),
            "target_end_date": _iso(project.target_end_date),
            "overdue_tasks": seen.get("overdue", 0),
            "blocked_tasks": seen.get("blocked", 0),
            "open_tasks": seen.get("open", 0),
            "due_soon_tasks": seen.get("due_soon", 0),
            "next_milestone": seen.get("next_milestone"),
            "next_milestone_date": seen.get("next_milestone_date"),
            "open_raid": seen.get("raid", 0),
            "updated_at": _iso(project.updated_at),
            "access": grants.get(pid).access if grants.get(pid) else "",
        })

    totals = _empty_totals()
    for row in rows:
        totals["projects"] += 1
        totals["by_health"][row["health"]] = (
            totals["by_health"].get(row["health"], 0) + 1)
        totals["by_status"][row["status"]] = (
            totals["by_status"].get(row["status"], 0) + 1)
        totals["overdue_tasks"] += row["overdue_tasks"]
        totals["blocked_tasks"] += row["blocked_tasks"]
        totals["due_soon_tasks"] += row["due_soon_tasks"]
    return {"projects": rows, "count": len(projects), "totals": totals}


def _empty_totals() -> dict[str, Any]:
    return {"projects": 0, "by_health": {}, "by_status": {},
            "overdue_tasks": 0, "blocked_tasks": 0, "due_soon_tasks": 0}


def _counts(session: Any, project_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Per-project counts, in three grouped queries."""
    if not project_ids:
        return {}
    now = today()
    soon = now + timedelta(days=control.DEFAULT_POLICY.due_soon_days)
    out: dict[int, dict[str, Any]] = defaultdict(dict)

    for pid, overdue, blocked, open_count, due_soon in session.execute(
        select(
            PlannerTask.project_id,
            func.count(func.nullif(
                (PlannerTask.due_date < now)
                & PlannerTask.status.in_(TASK_OPEN), False)),
            func.count(func.nullif(PlannerTask.blocked.is_(True), False)),
            func.count(func.nullif(PlannerTask.status.in_(TASK_OPEN), False)),
            func.count(func.nullif(
                (PlannerTask.due_date >= now) & (PlannerTask.due_date <= soon)
                & PlannerTask.status.in_(TASK_OPEN), False)),
        ).where(PlannerTask.project_id.in_(project_ids))
        .group_by(PlannerTask.project_id)
    ).all():
        out[int(pid)].update({
            "overdue": int(overdue or 0), "blocked": int(blocked or 0),
            "open": int(open_count or 0), "due_soon": int(due_soon or 0)})

    for pid, count in session.execute(
        select(PlannerRaid.project_id, func.count())
        .where(PlannerRaid.project_id.in_(project_ids),
               PlannerRaid.status.in_(RAID_LIVE))
        .group_by(PlannerRaid.project_id)
    ).all():
        out[int(pid)]["raid"] = int(count or 0)

    # The next milestone per project: the earliest open one with a date.
    for row in session.execute(
        select(PlannerMilestone)
        .where(PlannerMilestone.project_id.in_(project_ids),
               PlannerMilestone.status.in_(MILESTONE_OPEN),
               PlannerMilestone.target_date.is_not(None))
        .order_by(PlannerMilestone.project_id, PlannerMilestone.target_date)
    ).scalars():
        pid = int(row.project_id)
        if "next_milestone" not in out[pid]:
            out[pid]["next_milestone"] = str(row.name)
            out[pid]["next_milestone_date"] = _iso(row.target_date)
    return dict(out)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


# ============================================================== my work


def my_work(session: Any, principal: Any) -> dict[str, Any]:
    """What this person has to do, grouped the way they think about it.

    Six buckets, and a task appears in exactly one: whichever is most urgent.
    A task that is overdue AND blocked is in Blocked, because the blocker is
    what has to be dealt with first and listing it twice makes the page look
    twice as bad as the day actually is.

    Everything the person owns is here, however far out it is. There used to
    be a `horizon_days` parameter; it did nothing — both branches that
    consulted it appended to the same bucket — and a knob in an API that
    changes nothing is worse than no knob, because somebody will eventually
    tune it and believe the result. Hiding far-off work would be the wrong fix
    anyway: this is the one screen that shows a person everything with their
    name on it.
    """
    user_id = getattr(principal, "user_id", None)
    if user_id is None:
        return _empty_work()
    allowed = acl.readable_project_ids(session, principal)
    if not allowed:
        return _empty_work()

    now = today()
    rows = session.execute(
        select(PlannerTask).where(
            PlannerTask.project_id.in_(allowed),
            PlannerTask.status.in_(TASK_OPEN),
            or_(PlannerTask.owner_id == int(user_id),
                PlannerTask.reviewer_id == int(user_id),
                PlannerTask.contributor_ids.contains([int(user_id)])))
    ).scalars().all()

    projects = {int(p.id): p for p in session.execute(
        select(PlannerProject).where(PlannerProject.id.in_(
            {int(t.project_id) for t in rows} or {0}))).scalars()}
    directory = people(session, [t.owner_id for t in rows])

    buckets: dict[str, list] = {"overdue": [], "today": [], "blocked": [],
                                "reviews": [], "upcoming": [], "later": []}
    for row in rows:
        item = _task_row(row, projects.get(int(row.project_id)), directory,
                         now)
        if row.blocked:
            buckets["blocked"].append(item)
        elif item["days_overdue"]:
            buckets["overdue"].append(item)
        elif row.reviewer_id == int(user_id) and row.status == "IN_REVIEW":
            buckets["reviews"].append(item)
        elif row.due_date == now:
            buckets["today"].append(item)
        elif (row.due_date is not None
              and 0 < (row.due_date - now).days
              <= control.DEFAULT_POLICY.due_soon_days):
            buckets["upcoming"].append(item)
        else:
            buckets["later"].append(item)

    for key in buckets:
        buckets[key].sort(key=lambda r: (r["due_date"] or "9999-12-31",
                                         r["project_code"], r["code"]))
    buckets["counts"] = {k: len(v) for k, v in buckets.items()}
    return buckets


def _empty_work() -> dict[str, Any]:
    empty = {"overdue": [], "today": [], "blocked": [], "reviews": [],
             "upcoming": [], "later": []}
    empty["counts"] = {k: 0 for k in empty}
    return empty


def _task_row(row: Any, project: Any, directory: dict[int, dict[str, Any]],
              now: date) -> dict[str, Any]:
    view = control.TaskView.of(row)
    return {
        "id": int(row.id), "code": row.code, "title": row.title,
        "project_id": int(row.project_id),
        "project_code": project.code if project else "",
        "project_name": project.name if project else "",
        "status": row.status, "priority": row.priority,
        "percent_complete": int(row.percent_complete or 0),
        "due_date": _iso(row.due_date), "start_date": _iso(row.start_date),
        "days_overdue": control.days_overdue(view, now),
        "days_until_due": control.days_until_due(view, now),
        "blocked": bool(row.blocked),
        "blocker_reason": row.blocker_reason or "",
        "next_step": row.next_step or "",
        "critical": bool(row.critical),
        "owner": _person(directory, row.owner_id),
        "workstream_id": row.workstream_id,
        "last_update_at": _iso(row.last_update_at),
        "last_update_text": row.last_update_text or "",
        "version": int(row.version or 1),
    }


def task_detail(session: Any, principal: Any, task_id: int) -> dict[str, Any]:
    """One task and the project header it just moved.

    What a quick update returns. Returning the whole project detail instead
    would be simpler to write and wrong to ship: a person ticking four tasks
    off on a Monday morning would pull the entire plan four times, and the
    reason to return anything at all is that progress and health are
    recalculated by the write — so those two, and the task, are exactly what
    the screen needs to redraw.
    """
    task, _granted = acl.visible_task(session, task_id, principal)
    project = session.get(PlannerProject, int(task.project_id))
    directory = people(session, [task.owner_id, task.reviewer_id])
    plan = plan_of(session, int(task.project_id))
    colour, reason, overridden = effective_health(project)
    return {
        "task": _task_row(task, project, directory, today()),
        "project": {
            "id": int(project.id), "code": project.code,
            "percent_complete": control.progress(plan.tasks),
            "health": colour, "health_reason": reason,
            "health_overridden": overridden,
            "version": int(project.version or 1),
        },
    }


# =========================================================== one project


def _entity_code(kind: str, entity_id: Any, tasks: Any, milestones: Any
                 ) -> str:
    """The human-readable code of one end of a dependency.

    Falls back to the id rather than to an empty string: a link to something
    that has since been deleted should read as "115" and be obviously wrong,
    not vanish and leave the arrow pointing at nothing.
    """
    if entity_id is None:
        return ""
    rows = milestones if str(kind).upper() == "MILESTONE" else tasks
    for row in rows:
        if int(row.id) == int(entity_id):
            return row.code
    return str(entity_id)


def project_detail(session: Any, principal: Any, project_id: int
                   ) -> dict[str, Any]:
    """A whole project, as the detail page reads it."""
    granted = acl.readable(session, project_id, principal)
    project = session.get(PlannerProject, int(project_id))
    plan = plan_of(session, int(project_id))
    now = today()
    verdict = control.health(plan, now)
    colour, reason, overridden = effective_health(project)

    tasks = session.execute(
        select(PlannerTask).where(PlannerTask.project_id == int(project_id))
        .order_by(PlannerTask.workstream_id, PlannerTask.due_date,
                  PlannerTask.code)).scalars().all()
    milestones = session.execute(
        select(PlannerMilestone).where(
            PlannerMilestone.project_id == int(project_id))
        .order_by(PlannerMilestone.target_date)).scalars().all()
    workstreams = session.execute(
        select(PlannerWorkstream).where(
            PlannerWorkstream.project_id == int(project_id))
        .order_by(PlannerWorkstream.sequence,
                  PlannerWorkstream.name)).scalars().all()
    raid = session.execute(
        select(PlannerRaid).where(PlannerRaid.project_id == int(project_id))
        .order_by(PlannerRaid.status, PlannerRaid.severity)).scalars().all()
    participants = session.execute(
        select(PlannerParticipant).where(
            PlannerParticipant.project_id == int(project_id))).scalars().all()
    deps = session.execute(
        select(PlannerDependency).where(
            PlannerDependency.project_id == int(project_id))).scalars().all()

    directory = people(session, (
        [t.owner_id for t in tasks] + [t.reviewer_id for t in tasks]
        + [m.owner_id for m in milestones] + [r.owner_id for r in raid]
        + [p.user_id for p in participants] + [w.lead_id for w in workstreams]
        + [project.manager_id, project.sponsor_id,
           project.manual_health_by]))
    ws_progress = control.workstream_progress(plan.tasks)
    waiting = control.blocking(plan)

    return {
        "project": {
            "id": int(project.id), "code": project.code,
            "name": project.name, "description": project.description,
            "objective": project.objective,
            "business_context": project.business_context,
            "status": project.status, "priority": project.priority,
            "health": colour, "health_reason": reason,
            "health_overridden": overridden,
            "calculated_health": project.calculated_health,
            "calculated_health_reason": project.calculated_health_reason,
            "manual_health_by": _person(directory, project.manual_health_by),
            "manual_health_at": _iso(project.manual_health_at),
            "percent_complete": control.progress(plan.tasks),
            "manager": _person(directory, project.manager_id),
            "sponsor": _person(directory, project.sponsor_id),
            "start_date": _iso(project.start_date),
            "target_end_date": _iso(project.target_end_date),
            "actual_end_date": _iso(project.actual_end_date),
            "reporting_cadence": project.reporting_cadence,
            "reminder_days": list(project.reminder_days or []),
            "stale_after_days": int(project.stale_after_days or 7),
            "archived": bool(project.archived),
            "version": int(project.version or 1),
            "created_at": _iso(project.created_at),
            "updated_at": _iso(project.updated_at),
        },
        "access": granted.to_dict(),
        "findings": [f.to_dict() for f in verdict.findings],
        "workstreams": [{
            "id": int(w.id), "code": w.code, "name": w.name,
            "description": w.description, "status": w.status,
            "lead": _person(directory, w.lead_id),
            "start_date": _iso(w.start_date),
            "target_end_date": _iso(w.target_end_date),
            "sequence": int(w.sequence or 0),
            "percent_complete": ws_progress.get(int(w.id), 0),
            "task_count": sum(1 for t in tasks
                              if t.workstream_id == w.id),
        } for w in workstreams],
        "tasks": [{
            **_task_row(t, project, directory, now),
            "description": t.description or "",
            "reviewer": _person(directory, t.reviewer_id),
            "contributors": [_person(directory, c)
                             for c in (t.contributor_ids or [])
                             if _person(directory, c)],
            "parent_id": t.parent_id, "weight": float(t.weight or 1),
            "effort_days": t.effort_days, "tags": list(t.tags or []),
            "completed_date": _iso(t.completed_date),
            "blocks": waiting.get(int(t.id), []),
        } for t in tasks],
        "milestones": [{
            "id": int(m.id), "code": m.code, "name": m.name,
            "description": m.description or "", "status": m.status,
            "target_date": _iso(m.target_date),
            "actual_date": _iso(m.actual_date),
            "critical": bool(m.critical),
            "owner": _person(directory, m.owner_id),
            "workstream_id": m.workstream_id,
            "days_overdue": (max(0, (now - m.target_date).days)
                             if m.target_date and m.status in MILESTONE_OPEN
                             else 0),
            "version": int(m.version or 1),
        } for m in milestones],
        # The codes as well as the ids. A dependency shown as "115 → 119" is
        # unreadable, and every caller that had only the ids was re-deriving
        # the codes from the task list — three lookups, three chances to get
        # the type branch wrong.
        "dependencies": [{
            "id": int(d.id),
            "predecessor_type": d.predecessor_type,
            "predecessor_id": int(d.predecessor_id),
            "predecessor_code": _entity_code(
                d.predecessor_type, d.predecessor_id, tasks, milestones),
            "successor_type": d.successor_type,
            "successor_id": int(d.successor_id),
            "successor_code": _entity_code(
                d.successor_type, d.successor_id, tasks, milestones),
            "dependency_type": d.dependency_type,
            "lag_days": int(d.lag_days or 0), "notes": d.notes or "",
        } for d in deps],
        "raid": [{
            "id": int(r.id), "code": r.code, "type": r.raid_type,
            "title": r.title, "description": r.description or "",
            "status": r.status, "severity": r.severity,
            "probability": r.probability, "impact": r.impact,
            "owner": _person(directory, r.owner_id),
            "raised_date": _iso(r.raised_date),
            "target_date": _iso(r.target_date),
            "resolved_date": _iso(r.resolved_date),
            "mitigation": r.mitigation or "", "resolution": r.resolution or "",
            "workstream_id": r.workstream_id,
            "version": int(r.version or 1),
        } for r in raid],
        "participants": [{
            "id": int(p.id), "user": _person(directory, p.user_id),
            "project_role": p.project_role, "access": p.access,
            "workstream_id": p.workstream_id,
            "notifications_enabled": bool(p.notifications_enabled),
            "notes": p.notes or "",
        } for p in participants],
    }


# =========================================================== the history


def activity(session: Any, principal: Any, project_id: int, *,
             since: datetime | None = None, limit: int = 100,
             offset: int = 0) -> dict[str, Any]:
    """The project's own timeline, newest first."""
    acl.readable(session, project_id, principal)
    stmt = select(PlannerUpdate).where(
        PlannerUpdate.project_id == int(project_id))
    if since is not None:
        stmt = stmt.where(PlannerUpdate.created_at >= since)
    total = session.execute(
        select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = session.execute(
        stmt.order_by(PlannerUpdate.created_at.desc(), PlannerUpdate.id.desc())
        .limit(limit).offset(offset)).scalars().all()
    directory = people(session, [r.author_id for r in rows])
    return {
        "count": int(total),
        "items": [{
            "id": int(r.id), "entity_type": r.entity_type,
            "entity_id": r.entity_id, "entity_code": r.entity_code,
            "action": r.action, "author": _person(directory, r.author_id),
            "old_status": r.old_status, "new_status": r.new_status,
            "old_percent": r.old_percent, "new_percent": r.new_percent,
            "narrative": r.narrative, "blocker": r.blocker,
            "next_step": r.next_step, "changes": dict(r.changes or {}),
            "source": r.source, "at": _iso(r.created_at),
        } for r in rows],
    }


def changes_since(session: Any, principal: Any, project_id: int,
                  since: datetime) -> dict[str, Any]:
    """What actually moved, from the history rather than from the snapshot.

    This is the whole reason `planner_updates` is append-only. Comparing
    today's state with a remembered one cannot see a task that went to BLOCKED
    on Tuesday and back to IN_PROGRESS on Thursday — and that round trip is
    exactly what a project manager asking "what changed this week?" needs to
    know about.
    """
    acl.readable(session, project_id, principal)
    rows = session.execute(
        select(PlannerUpdate).where(
            PlannerUpdate.project_id == int(project_id),
            PlannerUpdate.created_at >= since)
        .order_by(PlannerUpdate.created_at)).scalars().all()
    directory = people(session, [r.author_id for r in rows])

    progressed, completed, blocked, unblocked, raised, closed = (
        [], [], [], [], [], [])
    dates_moved, owners_moved, created, milestones = [], [], [], []
    for row in rows:
        who = _person(directory, row.author_id)
        base = {"code": row.entity_code, "at": _iso(row.created_at),
                "author": who, "source": row.source,
                "narrative": row.narrative}
        if row.action == "created":
            created.append(base)
        if row.new_status == "COMPLETED" and row.old_status != "COMPLETED":
            completed.append(base)
        elif row.new_status == "BLOCKED" and row.old_status != "BLOCKED":
            blocked.append({**base, "blocker": row.blocker})
        elif row.old_status == "BLOCKED" and row.new_status not in ("",
                                                                    "BLOCKED"):
            unblocked.append(base)
        if (row.old_percent is not None and row.new_percent is not None
                and row.new_percent != row.old_percent):
            progressed.append({**base, "from": row.old_percent,
                               "to": row.new_percent})
        changed = dict(row.changes or {})
        if "due_date" in changed or "target_date" in changed:
            moved = changed.get("due_date") or changed.get("target_date")
            dates_moved.append({**base, "from": moved[0], "to": moved[1]})
        if "owner_id" in changed:
            owners_moved.append({**base, "from": changed["owner_id"][0],
                                 "to": changed["owner_id"][1]})
        if row.entity_type == "RAID":
            (closed if row.new_status in ("RESOLVED", "CLOSED")
             else raised).append(base)
        if row.entity_type == ENTITY_MILESTONE and row.new_status:
            milestones.append({**base, "status": row.new_status})

    return {
        "since": since.isoformat(), "events": len(rows),
        "created": created, "completed": completed,
        "progressed": progressed, "blocked": blocked, "unblocked": unblocked,
        "dates_moved": dates_moved, "owners_moved": owners_moved,
        "raid_raised": raised, "raid_closed": closed,
        "milestones": milestones,
    }


# ========================================================= what needs me


def attention(session: Any, principal: Any, *, limit: int = 10
              ) -> list[dict[str, Any]]:
    """Projects that need somebody to do something, worst first.

    Deterministic. This is what the dashboard panel renders and what the
    portfolio brief opens with, and both have to say the same thing.
    """
    allowed = acl.readable_project_ids(session, principal)
    if not allowed:
        return []
    projects = {int(p.id): p for p in session.execute(
        select(PlannerProject).where(
            PlannerProject.id.in_(allowed),
            PlannerProject.status.in_(PROJECT_OPEN),
            PlannerProject.archived.is_(False))).scalars()}
    if not projects:
        return []
    plans = plans_of(session, list(projects))
    now = today()

    ranked = []
    for pid, project in projects.items():
        verdict = control.health(plans[pid], now)
        colour, reason, overridden = effective_health(project)
        if colour == "GREEN":
            continue
        worst = [f for f in verdict.findings if f.severity == control.CRITICAL]
        rank = (0 if colour == "RED" else 1, -len(worst),
                -len(verdict.findings))
        ranked.append((rank, {
            "id": pid, "code": project.code, "name": project.name,
            "health": colour, "reason": reason,
            "health_overridden": overridden,
            "percent_complete": int(project.calculated_percent_complete or 0),
            "findings": [f.to_dict() for f in
                         (worst or verdict.findings)[:3]],
        }))
    ranked.sort(key=lambda pair: pair[0])
    return [row for _rank, row in ranked[:limit]]


__all__ = [
    "QUERY_VERSION", "today", "people", "plan_of", "plans_of",
    "refresh_calculations", "effective_health", "portfolio", "my_work",
    "project_detail", "activity", "changes_since", "attention",
]
