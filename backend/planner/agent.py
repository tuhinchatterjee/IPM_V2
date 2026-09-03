"""What the assistant may know about projects, and what it may not do.

Two halves, and the line between them is the point of the module.

**The handlers** are what the tool registry calls. Every one of them reads,
and every one goes through `access.py` with the requesting person's principal,
so an agent answering "what's overdue?" sees exactly the projects that person
could see by clicking. There is deliberately no handler that completes a task,
moves a date, reassigns an owner or closes a risk — and no registry entry for
one either, so the prohibition does not rest on a permission check somewhere
being written correctly.

**The brief** is a composed answer. It is assembled from the deterministic
engine's findings, not asked for from a model: the health colour, the count of
overdue tasks, what is on the critical path and who has gone quiet are all
computed. A model's job, where one is used at all, is to word what is already
established.

Everything a brief says is labelled:

  FACT           read from the database, or computed from it by control.py.
  INFERENCE      a reading of those facts by a stated rule.
  RECOMMENDATION something a person might do about it.

The labels are not decoration. A project manager reading "the vendor is the
problem" needs to know instantly whether that is in the record or a guess, and
the honest answer to "why is T-104 late?" is usually "no reason has been
recorded" — which this module says in those words rather than inventing one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from backend.models.planner import (
    RAID_LIVE,
    PlannerProject,
    PlannerRaid,
    PlannerTask,
)
from backend.planner import access as acl
from backend.planner import control
from backend.planner import query as pq

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0.0"

FACT = "FACT"
INFERENCE = "INFERENCE"
RECOMMENDATION = "RECOMMENDATION"
UNKNOWN = "NOT RECORDED"

#: The sentence, once, so that every surface says it the same way.
NO_REASON = "Reason for delay has not been recorded."


@dataclass
class Statement:
    """One line of a brief, and where it came from."""

    kind: str
    text: str
    #: What in the plan supports it — a code, a count, a date. An INFERENCE
    #: with no evidence is an opinion, and this makes that visible.
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text,
                "evidence": list(self.evidence)}


@dataclass
class Brief:
    project_id: int
    project_code: str
    project_name: str
    as_of: date
    headline: str
    statements: list[Statement]
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "project_code": self.project_code,
            "project_name": self.project_name, "as_of": self.as_of.isoformat(),
            "headline": self.headline,
            "statements": [s.to_dict() for s in self.statements],
            "open_questions": list(self.open_questions),
            "grounding": "Every FACT is read from the project record. Every "
                         "INFERENCE is a stated rule applied to those facts. "
                         "Nothing here is a guess about what is happening.",
        }


def _plural(count: int, one: str, many: str = "") -> str:
    return one if count == 1 else (many or one + "s")


# ================================================================ the brief


def project_brief(session: Any, principal: Any, project_id: int, *,
                  today: date | None = None) -> dict[str, Any]:
    """What a manager needs to know about one project this morning.

    Composed, not generated. Every number here came out of a query and every
    reading of it is a rule you can look up — which is what makes it safe to
    put in front of a steering committee.
    """
    acl.readable(session, project_id, principal)
    project = session.get(PlannerProject, int(project_id))
    plan = pq.plan_of(session, int(project_id))
    now = today or pq.today()
    verdict = control.health(plan, now)
    colour, reason, overridden = pq.effective_health(project)
    percent = control.progress(plan.tasks)

    said: list[Statement] = []
    open_questions: list[str] = []

    said.append(Statement(
        FACT,
        f"{project.name} is {project.status.replace('_', ' ').lower()} and "
        f"{percent}% complete by weighted task progress.",
        [f"{len(plan.tasks)} {_plural(len(plan.tasks), 'task')}"]))

    if overridden:
        said.append(Statement(
            FACT,
            f"Health is reported as {colour} by hand. {reason} The "
            f"calculation says {verdict.status}: {verdict.reason}",
            [f"calculated={verdict.status}", f"reported={colour}"]))
        # Worth surfacing rather than smoothing over: somebody deciding a
        # project is greener than its own numbers is a governance fact.
        if colour == "GREEN" and verdict.status in ("AMBER", "RED"):
            open_questions.append(
                f"The reported health ({colour}) is better than the "
                f"calculated one ({verdict.status}). Is the override still "
                "right?")
    else:
        said.append(Statement(FACT, f"Health is {colour}. {reason}",
                              [f"calculated={verdict.status}"]))

    overdue = [t for t in plan.tasks
               if t.open and control.days_overdue(t, now)]
    if overdue:
        worst = max(overdue, key=lambda t: control.days_overdue(t, now) or 0)
        said.append(Statement(
            FACT,
            f"{len(overdue)} {_plural(len(overdue), 'task is', 'tasks are')} "
            f"overdue. The oldest is {worst.code} {worst.title}, "
            f"{control.days_overdue(worst, now)} days past "
            f"{worst.due_date}.",
            [t.code for t in overdue[:8]]))

    blocked = [t for t in plan.tasks if t.open and t.blocked]
    for task in blocked[:5]:
        if task.blocker_reason:
            said.append(Statement(
                FACT, f"{task.code} is blocked: {task.blocker_reason}",
                [task.code]))
        else:
            said.append(Statement(
                UNKNOWN,
                f"{task.code} is marked blocked and no reason has been "
                "recorded.", [task.code]))
            open_questions.append(
                f"Why is {task.code} {task.title} blocked?")

    waiting = control.blocking(plan)
    for task in plan.tasks:
        if not task.open:
            continue
        held = waiting.get(int(task.id)) or []
        if len(held) >= 2 and (task.blocked
                               or control.days_overdue(task, now)):
            said.append(Statement(
                INFERENCE,
                f"{task.code} is the constraint: {len(held)} other items "
                f"depend on it and it is not moving.",
                [task.code, *[str(h) for h in held[:5]]]))
            said.append(Statement(
                RECOMMENDATION,
                f"Clear {task.code} before anything else on this project.",
                [task.code]))
            break

    ahead = control.milestone_findings(plan, now)
    for finding in ahead[:3]:
        said.append(Statement(
            INFERENCE if finding.rule != "milestone_overdue" else FACT,
            finding.detail,
            [finding.entity_code] if finding.entity_code else []))

    quiet = [t for t in plan.tasks
             if t.open and control.is_stale(t, now,
                                            window=plan.stale_after_days)]
    if quiet:
        said.append(Statement(
            FACT,
            f"{len(quiet)} near-term {_plural(len(quiet), 'task has', 'tasks have')} "
            "had no update recently.",
            [t.code for t in quiet[:8]]))
        said.append(Statement(
            RECOMMENDATION,
            "Ask the owners of those tasks where they have got to before the "
            "next report.",
            [t.code for t in quiet[:8]]))

    live_raid = session.execute(
        select(PlannerRaid).where(
            PlannerRaid.project_id == int(project_id),
            PlannerRaid.status.in_(RAID_LIVE))).scalars().all()
    decisions = [r for r in live_raid if r.raid_type == "DECISION"]
    risks = [r for r in live_raid
             if r.raid_type == "RISK" and r.severity in ("HIGH", "CRITICAL")]
    for row in decisions[:3]:
        said.append(Statement(
            FACT, f"A decision is outstanding: {row.title}"
            + (f" (target {row.target_date})" if row.target_date else ""),
            [row.code]))
        open_questions.append(f"{row.code}: {row.title}")
    for row in risks[:3]:
        said.append(Statement(
            FACT, f"{row.severity.title()} risk open: {row.title}",
            [row.code]))

    if not overdue and not blocked and not quiet:
        said.append(Statement(
            INFERENCE,
            "Nothing is overdue, blocked or silent. On the record, this "
            "project is running to plan.", []))

    headline = _headline(project, colour, percent, len(overdue), len(blocked))
    return Brief(int(project.id), project.code, project.name, now, headline,
                 said, open_questions).to_dict()


def _headline(project: Any, colour: str, percent: int, overdue: int,
              blocked: int) -> str:
    """One sentence a person can read without opening anything.

    Ordered by what would change somebody's morning: lateness first, then
    blockage, then progress. A headline that leads with "40% complete" when
    six things are overdue has buried the only part that mattered.
    """
    parts = [f"{project.code} is {colour}"]
    if overdue:
        parts.append(f"{overdue} {_plural(overdue, 'task')} overdue")
    if blocked:
        parts.append(f"{blocked} blocked")
    parts.append(f"{percent}% complete")
    return ", ".join(parts) + "."


# ============================================================== the estate


def portfolio_brief(session: Any, principal: Any, *,
                    today: date | None = None,
                    limit: int = 6) -> dict[str, Any]:
    """The same discipline across everything this person can see."""
    now = today or pq.today()
    book = pq.portfolio(session, principal, limit=200)
    totals = book.get("totals") or {}
    rows = book.get("projects") or []
    needs = pq.attention(session, principal, limit=limit)

    said: list[Statement] = [Statement(
        FACT,
        f"{len(rows)} open {_plural(len(rows), 'project')}: "
        f"{totals.get('red', 0)} red, {totals.get('amber', 0)} amber, "
        f"{totals.get('green', 0)} green.",
        [r["code"] for r in rows[:10]])]

    late = [r for r in rows if r.get("overdue_tasks")]
    if late:
        worst = sorted(late, key=lambda r: -int(r["overdue_tasks"]))[:3]
        said.append(Statement(
            FACT,
            f"{sum(int(r['overdue_tasks']) for r in late)} overdue tasks "
            f"across {len(late)} {_plural(len(late), 'project')}. Most: "
            + ", ".join(f"{r['code']} ({r['overdue_tasks']})"
                        for r in worst),
            [r["code"] for r in worst]))

    for row in needs[:limit]:
        said.append(Statement(
            INFERENCE, f"{row['code']} needs attention. {row['reason']}",
            [row["code"]]))

    if not needs:
        said.append(Statement(
            INFERENCE,
            "Nothing in the portfolio is amber or red on the record.", []))

    return {
        "as_of": now.isoformat(),
        "headline": (f"{totals.get('red', 0)} red, "
                     f"{totals.get('amber', 0)} amber, "
                     f"{totals.get('green', 0)} green across "
                     f"{len(rows)} open {_plural(len(rows), 'project')}."),
        "statements": [s.to_dict() for s in said],
        "attention": needs,
        "grounding": "Counts are queries. Rankings are the health engine's, "
                     "not a model's.",
    }


# ============================================================ status chases


def draft_update_request(session: Any, principal: Any, project_id: int, *,
                         task_id: int | None = None,
                         tone: str = "neutral",
                         today: date | None = None) -> dict[str, Any]:
    """Compose the text of a chase. Send nothing.

    The deterministic rules decide WHO should be asked and WHY — that is
    `control.chase_findings`, and it is not negotiable by a model. This
    function only writes the sentence, and returns it as a draft with the
    reason attached so the person sending it can see what it is based on.
    """
    acl.readable(session, project_id, principal)
    project = session.get(PlannerProject, int(project_id))
    plan = pq.plan_of(session, int(project_id))
    now = today or pq.today()
    chases = control.chase_findings(plan, now)
    if task_id is not None:
        chases = [c for c in chases if int(c.task_id) == int(task_id)]

    people = pq.people(session, [c.owner_id for c in chases])
    greeting = {"neutral": "Hello", "warm": "Hi", "formal": "Dear"}.get(
        tone, "Hello")

    drafts = []
    for chase in chases:
        who = people.get(int(chase.owner_id)) or {}
        name = who.get("first_name") or who.get("name") or "there"
        drafts.append({
            "to": who or {"id": chase.owner_id},
            "task_id": int(chase.task_id), "task_code": chase.task_code,
            "trigger": chase.trigger, "why": chase.reason,
            "subject": f"{project.code}: update on {chase.task_code}",
            "body": (
                f"{greeting} {name},\n\n{chase.reason} Could you let me know "
                f"where it has got to, and whether the date still holds?\n\n"
                f"Project: {project.code} {project.name}\n"
                f"Task: {chase.task_code} {chase.task_title}"
                + (f"\nDue: {chase.due_date}" if chase.due_date else "")),
        })

    return {
        "project_id": int(project.id), "project_code": project.code,
        "as_of": now.isoformat(), "drafts": drafts,
        "sent": False,
        "note": "These are drafts. Nothing has been sent, and nothing on the "
                "project has changed.",
    }


# ============================================================== what changed


def what_changed(session: Any, principal: Any, project_id: int, *,
                 days: int = 7,
                 since: datetime | None = None) -> dict[str, Any]:
    """Read from the history, never by comparing two snapshots.

    A task that went BLOCKED on Tuesday and back to IN_PROGRESS on Thursday
    looks unchanged in a snapshot comparison, and that round trip is exactly
    what somebody asking "what happened this week?" needs to hear about.
    """
    moment = since or (datetime.now(UTC) - timedelta(days=max(1, days)))
    return pq.changes_since(session, principal, int(project_id), moment)


# ============================================================ tool handlers


def _project_id(session: Any, principal: Any, project: Any) -> int:
    """Accept an id or a code, because a person says "IFRS9-2026"."""
    if isinstance(project, int) or str(project).isdigit():
        return int(project)
    found = session.execute(
        select(PlannerProject.id).where(
            PlannerProject.code == str(project))).scalar()
    if found is None:
        raise acl.ProjectNotFound(f"No project {project!r}.")
    return int(found)


def handlers(session: Any) -> dict[str, Any]:
    """The tool id → callable map the registry's `invoke` expects.

    Built per request and closed over the session, so the registry itself
    never imports the planner and the planner never imports the registry's
    execution machinery. Every handler takes `principal` because every one
    of these tools is marked `reads_data`, and that is what stops an agent
    from being a way around the participant list.
    """
    from backend.agentic import tools as reg

    def portfolio(principal=None, **kw):
        return pq.portfolio(session, principal,
                            status=kw.get("status") or "",
                            health=kw.get("health") or "",
                            manager_id=kw.get("manager_id"),
                            search=kw.get("search") or "",
                            limit=int(kw.get("limit") or 50))

    def detail(principal=None, project=None, **_kw):
        return pq.project_detail(session, principal,
                                 _project_id(session, principal, project))

    def my_work(principal=None, **kw):
        return pq.my_work(session, principal,
                          horizon_days=int(kw.get("horizon_days") or 30))

    def attention(principal=None, **kw):
        return {"items": pq.attention(session, principal,
                                      limit=int(kw.get("limit") or 10))}

    def changed(principal=None, project=None, **kw):
        return what_changed(session, principal,
                            _project_id(session, principal, project),
                            days=int(kw.get("days") or 7))

    def activity(principal=None, project=None, **kw):
        return pq.activity(session, principal,
                           _project_id(session, principal, project),
                           limit=int(kw.get("limit") or 50))

    def tasks(principal=None, project=None, **kw):
        pid = _project_id(session, principal, project)
        acl.readable(session, pid, principal)
        now = pq.today()
        plan = pq.plan_of(session, pid)
        rows = session.execute(
            select(PlannerTask).where(PlannerTask.project_id == pid)
            .order_by(PlannerTask.due_date, PlannerTask.code)).scalars().all()
        by_id = {int(t.id): t for t in plan.tasks}
        out = []
        for row in rows:
            view = by_id.get(int(row.id))
            if kw.get("status") and row.status != str(kw["status"]).upper():
                continue
            if kw.get("owner_id") and row.owner_id != int(kw["owner_id"]):
                continue
            if kw.get("overdue_only") and not (
                    view and control.days_overdue(view, now)):
                continue
            if kw.get("blocked_only") and not row.blocked:
                continue
            out.append({
                "id": int(row.id), "code": row.code, "title": row.title,
                "status": row.status,
                "percent_complete": int(row.percent_complete or 0),
                "due_date": row.due_date.isoformat() if row.due_date else None,
                "days_overdue": control.days_overdue(view, now)
                if view else None,
                "blocked": bool(row.blocked),
                "blocker_reason": row.blocker_reason or "",
                "owner_id": row.owner_id,
                "last_update_text": row.last_update_text or "",
            })
        return {"tasks": out[:int(kw.get("limit") or 200)]}

    def dependencies(principal=None, project=None, **kw):
        pid = _project_id(session, principal, project)
        acl.readable(session, pid, principal)
        plan = pq.plan_of(session, pid)
        waiting = control.blocking(plan)
        if kw.get("task"):
            key = int(kw["task"])
            return {"task_id": key, "blocks": waiting.get(key, []),
                    "downstream": [
                        {"type": kind, "id": entity_id} for kind, entity_id
                        in control.downstream(plan, "TASK", key)]}
        return {"blocking": {str(k): v for k, v in waiting.items()},
                "findings": [f.to_dict()
                             for f in control.dependency_findings(
                                 plan, pq.today())]}

    def raid(principal=None, project=None, **kw):
        pid = _project_id(session, principal, project)
        acl.readable(session, pid, principal)
        stmt = select(PlannerRaid).where(PlannerRaid.project_id == pid)
        if kw.get("raid_type"):
            stmt = stmt.where(
                PlannerRaid.raid_type == str(kw["raid_type"]).upper())
        stmt = stmt.where(
            PlannerRaid.status == str(kw["status"]).upper()
            if kw.get("status") else PlannerRaid.status.in_(RAID_LIVE))
        return {"items": [{
            "code": r.code, "type": r.raid_type, "title": r.title,
            "severity": r.severity, "status": r.status,
            "owner_id": r.owner_id, "mitigation": r.mitigation,
            "target_date": (r.target_date.isoformat()
                            if r.target_date else None),
        } for r in session.execute(stmt).scalars()]}

    def milestones(principal=None, project=None, **kw):
        pid = _project_id(session, principal, project)
        acl.readable(session, pid, principal)
        plan = pq.plan_of(session, pid)
        now = pq.today()
        horizon = int(kw.get("horizon_days") or 90)
        return {"items": [{
            "code": m.code, "name": m.name, "status": m.status,
            "target_date": m.target_date.isoformat() if m.target_date else None,
            "critical": bool(m.critical),
            "days_away": (m.target_date - now).days if m.target_date else None,
        } for m in plan.milestones
            if m.target_date is None
            or (m.target_date - now).days <= horizon],
            "findings": [f.to_dict()
                         for f in control.milestone_findings(plan, now)]}

    def chase_list(principal=None, project=None, **_kw):
        now = pq.today()
        if project:
            ids = [_project_id(session, principal, project)]
        else:
            ids = acl.readable_project_ids(session, principal)
        for pid in ids:
            acl.readable(session, pid, principal)
        plans = pq.plans_of(session, ids)
        out = []
        for pid, plan in plans.items():
            for chase in control.chase_findings(plan, now):
                out.append({"project_id": pid, "task_id": int(chase.task_id),
                            "task_code": chase.task_code,
                            "title": chase.task_title,
                            "owner_id": int(chase.owner_id),
                            "trigger": chase.trigger,
                            "reason": chase.reason})
        return {"chases": out}

    def draft(principal=None, project=None, **kw):
        return draft_update_request(
            session, principal, _project_id(session, principal, project),
            task_id=int(kw["task"]) if kw.get("task") else None,
            tone=str(kw.get("tone") or "neutral"))

    return {
        reg.PLANNER_PORTFOLIO: portfolio,
        reg.PLANNER_PROJECT: detail,
        reg.PLANNER_MY_WORK: my_work,
        reg.PLANNER_ATTENTION: attention,
        reg.PLANNER_CHANGES: changed,
        reg.PLANNER_ACTIVITY: activity,
        reg.PLANNER_TASKS: tasks,
        reg.PLANNER_DEPENDENCIES: dependencies,
        reg.PLANNER_RAID: raid,
        reg.PLANNER_MILESTONES: milestones,
        reg.PLANNER_CHASE_LIST: chase_list,
        reg.PLANNER_DRAFT_UPDATE: draft,
    }


__all__ = [
    "AGENT_VERSION", "FACT", "INFERENCE", "RECOMMENDATION", "UNKNOWN",
    "NO_REASON", "Statement", "Brief",
    "project_brief", "portfolio_brief", "draft_update_request",
    "what_changed", "handlers",
]
