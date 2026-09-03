"""The sweep that notices things nobody looked at.

A project planner that only knows what somebody typed into it is a filing
cabinet. What makes this one useful on a Monday morning is that something ran
overnight, worked out which commitments moved into trouble while everybody was
away, and told exactly the people who can do something about it.

Three rules shape the whole module:

**Deterministic first, and mostly only.** Every decision here — who is
reminded, about what, on which day, and whether the project is red — is made
by `control.py` from the database. No model is asked whether a task is late.
A model may later be asked to word a summary; it is never asked what is true.

**One reminder is a reminder. Two is noise.** Every message is fingerprinted
with what it is about, and the fingerprint is a unique constraint. A task due
in three days generates one three-day reminder however many times the monitor
runs. Move the due date and the fingerprint changes, so the new date is
reminded about — which is right, because it is a different commitment.

**Cheap by construction.** One pass over the projects, five queries each
batch, and no per-task model call. §23 is explicit about this and it is also
just correct: a bank with two hundred projects and eight thousand tasks would
otherwise spend a fortune every hour to discover that nothing had changed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from backend.models.planner import (
    ENTITY_MILESTONE,
    ENTITY_PROJECT,
    ENTITY_TASK,
    PROJECT_OPEN,
    SOURCE_SYSTEM,
    PlannerMilestone,
    PlannerParticipant,
    PlannerProject,
    PlannerReminder,
)
from backend.planner import control
from backend.planner import query as pq
from backend.planner import service as svc

logger = logging.getLogger(__name__)

MONITOR_VERSION = "1.0.0"

#: The job kind, registered with the platform's existing worker rather than a
#: second scheduler. A project planner does not need its own cron.
PLANNER_SWEEP = "planner_sweep"

#: What a reminder is called. The vocabulary is closed so that a screen can
#: group by it and a test can assert on it.
DUE = "due"
OVERDUE = "overdue"
STALE = "stale"
BLOCKED = "blocked"
MILESTONE_DUE = "milestone_due"
MILESTONE_OVERDUE = "milestone_overdue"
HEALTH_RED = "health_red"

#: How each reads to the person receiving it.
_TITLES = {
    DUE: "Due soon",
    OVERDUE: "Overdue",
    STALE: "No recent update",
    BLOCKED: "Blocked",
    MILESTONE_DUE: "Milestone approaching",
    MILESTONE_OVERDUE: "Milestone missed",
    HEALTH_RED: "Project needs attention",
}


@dataclass
class Message:
    """One thing to tell one person, and the fingerprint that makes it once."""

    user_id: int
    project_id: int
    project_code: str
    entity_type: str
    entity_id: int
    entity_code: str
    trigger: str
    fingerprint: str
    title: str
    body: str


@dataclass
class Sweep:
    """What one run did. Returned, logged and asserted on in tests."""

    at: datetime
    projects: int = 0
    tasks: int = 0
    sent: int = 0
    suppressed: int = 0
    health_changed: list[dict[str, Any]] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(), "projects": self.projects,
            "tasks": self.tasks, "sent": self.sent,
            "suppressed": self.suppressed,
            "health_changed": self.health_changed,
            "by_trigger": self.by_trigger(),
        }

    def by_trigger(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for message in self.messages:
            out[message.trigger] = out.get(message.trigger, 0) + 1
        return out


# ============================================================ what to send


def _print(project_id: int, entity_type: str, entity_id: int, user_id: int,
           trigger: str, about: Any) -> str:
    """The fingerprint. `about` is what makes this reminder THIS reminder.

    For a due-date reminder it is the date and the threshold, so moving the
    date re-arms it and running the sweep twice on Tuesday does not. For a
    staleness nudge it is the day, so somebody silent for a fortnight is asked
    once a day rather than once ever — silence that goes on is a different
    fact each morning, where a due date that has not moved is the same one.
    """
    return f"{project_id}:{entity_type}:{entity_id}:{user_id}:{trigger}:{about}"


def _task_messages(project: Any, plan: control.Plan, today: date,
                   policy: control.Policy) -> list[Message]:
    """Reminders about tasks, at most one per task per person.

    Ordered by seriousness and stopping at the first hit: an overdue, blocked,
    silent task must not send its owner three messages that all mean "look at
    T-104".
    """
    out: list[Message] = []
    days = tuple(project.reminder_days or policy.reminder_days)
    for task in plan.tasks:
        if not task.open or task.owner_id is None:
            continue
        owner = int(task.owner_id)
        late = control.days_overdue(task, today)
        near = control.days_until_due(task, today)

        if late:
            out.append(Message(
                owner, int(project.id), project.code, ENTITY_TASK,
                int(task.id), task.code, OVERDUE,
                _print(int(project.id), ENTITY_TASK, int(task.id), owner,
                       OVERDUE, f"{task.due_date}:{today}"),
                _TITLES[OVERDUE],
                f"{task.code} {task.title} was due {task.due_date} and is "
                f"{late} day{'' if late == 1 else 's'} overdue."))
            continue

        if task.blocked:
            reason = task.blocker_reason or "no reason recorded"
            out.append(Message(
                owner, int(project.id), project.code, ENTITY_TASK,
                int(task.id), task.code, BLOCKED,
                _print(int(project.id), ENTITY_TASK, int(task.id), owner,
                       BLOCKED, reason[:40]),
                _TITLES[BLOCKED],
                f"{task.code} {task.title} is blocked: {reason}"))
            continue

        if near is not None and near in days:
            out.append(Message(
                owner, int(project.id), project.code, ENTITY_TASK,
                int(task.id), task.code, DUE,
                _print(int(project.id), ENTITY_TASK, int(task.id), owner,
                       DUE, f"{task.due_date}:{near}"),
                _TITLES[DUE],
                f"{task.code} {task.title} is due "
                + ("today." if near == 0 else
                   f"in {near} day{'' if near == 1 else 's'} "
                   f"({task.due_date}).")))
            continue

        if control.is_stale(task, today, policy=policy,
                            window=plan.stale_after_days):
            quiet = ((today - task.last_update_at.date()).days
                     if task.last_update_at else None)
            out.append(Message(
                owner, int(project.id), project.code, ENTITY_TASK,
                int(task.id), task.code, STALE,
                _print(int(project.id), ENTITY_TASK, int(task.id), owner,
                       STALE, today.isoformat()),
                _TITLES[STALE],
                f"{task.code} {task.title} is coming up and has "
                + ("no update on it at all."
                   if quiet is None
                   else f"not been updated for {quiet} days.")))
    return out


def _milestone_messages(project: Any, milestones: list[Any], today: date,
                        policy: control.Policy) -> list[Message]:
    out: list[Message] = []
    for row in milestones:
        if row.owner_id is None or row.target_date is None:
            continue
        if row.status in ("ACHIEVED", "CANCELLED"):
            continue
        owner = int(row.owner_id)
        gap = (row.target_date - today).days
        if gap < 0:
            out.append(Message(
                owner, int(project.id), project.code, ENTITY_MILESTONE,
                int(row.id), row.code, MILESTONE_OVERDUE,
                _print(int(project.id), ENTITY_MILESTONE, int(row.id), owner,
                       MILESTONE_OVERDUE, f"{row.target_date}:{today}"),
                _TITLES[MILESTONE_OVERDUE],
                f"{row.name} was due {row.target_date} and has not been "
                f"marked achieved ({abs(gap)} day"
                f"{'' if abs(gap) == 1 else 's'} ago)."))
        elif gap <= policy.milestone_horizon_days:
            out.append(Message(
                owner, int(project.id), project.code, ENTITY_MILESTONE,
                int(row.id), row.code, MILESTONE_DUE,
                _print(int(project.id), ENTITY_MILESTONE, int(row.id), owner,
                       MILESTONE_DUE, f"{row.target_date}:{gap}"),
                _TITLES[MILESTONE_DUE],
                f"{row.name} is due in {gap} day"
                f"{'' if gap == 1 else 's'} ({row.target_date})."))
    return out


def _health_messages(project: Any, verdict: Any, was: str,
                     managers: list[int]) -> list[Message]:
    """The manager hears when the project turns red. Not while it stays red.

    Fingerprinted on the transition and the reason, so a project that is red
    all quarter says so once, and says so again when the reason changes —
    which is the thing a manager actually needs to know.
    """
    if verdict.status != "RED" or was == "RED":
        return []
    return [Message(
        user_id, int(project.id), project.code, ENTITY_PROJECT,
        int(project.id), project.code, HEALTH_RED,
        _print(int(project.id), ENTITY_PROJECT, int(project.id), user_id,
               HEALTH_RED, verdict.reason[:60]),
        _TITLES[HEALTH_RED],
        f"{project.code} {project.name} is RED. {verdict.reason}")
        for user_id in dict.fromkeys(managers)]


# ================================================================ the sweep


def sweep(session: Any, *, today: date | None = None,
          policy: control.Policy = control.DEFAULT_POLICY,
          project_ids: list[int] | None = None,
          send: bool = True) -> Sweep:
    """One pass over the open projects. Nothing commits; the caller owns that.

    `today` is a parameter and never `date.today()` inside a rule, so the
    whole engine can be tested at a frozen moment — which is the only way to
    prove that a reminder fires once rather than on every run.
    """
    now = datetime.now(UTC)
    day = today or now.date()
    result = Sweep(at=now)

    stmt = select(PlannerProject).where(
        PlannerProject.archived.is_(False),
        PlannerProject.status.in_(PROJECT_OPEN))
    if project_ids:
        stmt = stmt.where(PlannerProject.id.in_([int(i) for i in project_ids]))
    projects = session.execute(stmt).scalars().all()
    if not projects:
        return result

    ids = [int(p.id) for p in projects]
    plans = pq.plans_of(session, ids)
    milestones: dict[int, list[Any]] = {i: [] for i in ids}
    for row in session.execute(
            select(PlannerMilestone).where(
                PlannerMilestone.project_id.in_(ids))).scalars():
        milestones[int(row.project_id)].append(row)

    watchers: dict[int, list[int]] = {i: [] for i in ids}
    for row in session.execute(
            select(PlannerParticipant).where(
                PlannerParticipant.project_id.in_(ids),
                PlannerParticipant.notifications_enabled.is_(True),
                PlannerParticipant.access.in_(("OWNER", "EDITOR")))).scalars():
        watchers[int(row.project_id)].append(int(row.user_id))

    pending: list[Message] = []
    for project in projects:
        pid = int(project.id)
        plan = plans.get(pid)
        if plan is None:
            continue
        result.projects += 1
        result.tasks += len(plan.tasks)

        was = project.calculated_health or "UNKNOWN"
        verdict = control.health(plan, day, policy=policy)
        percent = control.progress(plan.tasks)
        if (verdict.status != was
                or verdict.reason != (project.calculated_health_reason or "")
                or percent != int(project.calculated_percent_complete or 0)):
            project.calculated_health = verdict.status
            project.calculated_health_reason = verdict.reason
            project.calculated_percent_complete = percent
            project.calculated_at = now
            if verdict.status != was:
                result.health_changed.append({
                    "project_id": pid, "code": project.code,
                    "from": was, "to": verdict.status,
                    "reason": verdict.reason})
                # A colour change is a fact about the project, so it belongs
                # in the project's own history rather than only in a
                # notification somebody may never open.
                svc.record(session, pid, entity_type=ENTITY_PROJECT,
                           entity_id=pid, entity_code=project.code,
                           action="health", author_id=None,
                           source=SOURCE_SYSTEM, old_status=was,
                           new_status=verdict.status,
                           narrative=verdict.reason)

        pending.extend(_task_messages(project, plan, day, policy))
        pending.extend(_milestone_messages(project, milestones[pid], day,
                                           policy))
        managers = [i for i in ([project.manager_id] if project.manager_id
                                else []) + watchers[pid] if i]
        pending.extend(_health_messages(project, verdict, was, managers))

    if send:
        _deliver(session, pending, result)
    else:
        result.messages = pending
        result.suppressed = len(pending)
    return result


def _deliver(session: Any, pending: list[Message], result: Sweep) -> None:
    """Write the notifications that have not been written before.

    The already-sent set is read in ONE query rather than one per message:
    a sweep over a large estate produces thousands of candidate reminders,
    almost all of which were sent yesterday.
    """
    from backend.models.platform import Notification

    if not pending:
        return
    prints = [m.fingerprint for m in pending]
    already = {row for row in session.execute(
        select(PlannerReminder.fingerprint).where(
            PlannerReminder.fingerprint.in_(prints))).scalars()}

    seen: set[str] = set()
    for message in pending:
        if message.fingerprint in already or message.fingerprint in seen:
            result.suppressed += 1
            continue
        seen.add(message.fingerprint)
        note = Notification(
            user_id=message.user_id, kind="planner",
            title=f"{message.project_code}: {message.title}",
            body=message.body, object_type="planner_project",
            object_id=str(message.project_id), actor_id=None)
        session.add(note)
        session.flush()
        session.add(PlannerReminder(
            project_id=message.project_id, entity_type=message.entity_type,
            entity_id=message.entity_id, user_id=message.user_id,
            trigger=message.trigger, fingerprint=message.fingerprint,
            notification_id=int(note.id)))
        result.messages.append(message)
        result.sent += 1


# ================================================== the platform's scheduler


def run_sweep_job(session: Any, job: Any) -> dict[str, Any]:
    """The handler the existing agentic worker calls. Signature is theirs.

    Registered as a job kind rather than given its own scheduler: CreditProbe
    already has a durable Postgres queue with idempotency, retries and
    heartbeats, and a second one would be a second thing to operate.
    """
    payload = getattr(job, "payload", None) or {}
    today = payload.get("today")
    day = (date.fromisoformat(today) if isinstance(today, str) and today
           else None)
    outcome = sweep(session, today=day,
                    project_ids=payload.get("project_ids") or None)
    logger.info("planner sweep: %s", outcome.to_dict())
    return outcome.to_dict()


def schedule(session: Any, *, today: date | None = None) -> tuple[int, bool]:
    """Queue one sweep for a given day, at most once.

    The idempotency key is the day, so two ticks an hour apart on the same
    date find the first job rather than running the estate twice.
    """
    from backend.agentic import queue

    day = (today or datetime.now(UTC).date()).isoformat()
    return queue.enqueue(session, kind=PLANNER_SWEEP,
                         idempotency_key=f"planner-sweep:{day}",
                         payload={"today": day})


__all__ = [
    "MONITOR_VERSION", "PLANNER_SWEEP", "Sweep", "Message",
    "DUE", "OVERDUE", "STALE", "BLOCKED", "MILESTONE_DUE",
    "MILESTONE_OVERDUE", "HEALTH_RED",
    "sweep", "run_sweep_job", "schedule",
]
