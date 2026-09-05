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
REVIEW = "review"
#: A chase: a reminder the recipient is expected to answer. Separate from the
#: plain nudges above because the project manager's screen filters on it, and
#: because "we asked and heard nothing" is a different fact from "we told
#: them".
UPDATE_REQUESTED = "update_requested"

#: How each reads to the person receiving it.
_TITLES = {
    DUE: "Due soon",
    OVERDUE: "Overdue",
    STALE: "No recent update",
    BLOCKED: "Blocked",
    MILESTONE_DUE: "Milestone approaching",
    MILESTONE_OVERDUE: "Milestone missed",
    HEALTH_RED: "Project needs attention",
    REVIEW: "Review required",
    UPDATE_REQUESTED: "Action required",
}

#: What the reader is being asked to do. A notification that says a task is
#: overdue and stops has told somebody something they can only act on by
#: working out where to go; the line below is the difference between a feed
#: and an inbox.
_ACTIONS = {
    DUE: "Please update your progress, blocker and next step.",
    OVERDUE: "Please update your progress, blocker and next step.",
    STALE: "Please update your progress, blocker and next step.",
    BLOCKED: "Say what you are waiting for, and who owes it.",
    MILESTONE_DUE: "Confirm the milestone will be met, or say what is at risk.",
    MILESTONE_OVERDUE: "Mark it achieved, or say what is outstanding.",
    HEALTH_RED: "Review the project and decide what changes.",
    REVIEW: "Review the work and accept it or send it back.",
    UPDATE_REQUESTED: "Please update your progress, blocker and next step.",
}

#: The button the notification effectively is.
_LABELS = {
    DUE: "Update task", OVERDUE: "Update task", STALE: "Update task",
    BLOCKED: "Open task", MILESTONE_DUE: "Open milestone",
    MILESTONE_OVERDUE: "Open milestone", HEALTH_RED: "Review project",
    REVIEW: "Review task", UPDATE_REQUESTED: "Update task",
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
    #: True when the recipient is expected to answer, not merely to know.
    asked: bool = False
    #: The engine's own sentence for why they were asked. Empty for a nudge.
    reason: str = ""

    @property
    def action(self) -> str:
        return _ACTIONS.get(self.trigger, "")

    @property
    def label(self) -> str:
        return _LABELS.get(self.trigger, "Open")

    @property
    def link_type(self) -> str:
        """What the notification should open. §1.2's deep link.

        A task reminder that opens the portfolio makes the reader do the
        search again. `planner_task` carries both ids because a task page is
        reached through its project.
        """
        if self.entity_type == ENTITY_TASK:
            return "planner_task"
        if self.entity_type == ENTITY_MILESTONE:
            return "planner_milestone"
        return "planner_project"

    @property
    def link_id(self) -> str:
        if self.entity_type == ENTITY_PROJECT:
            return str(self.project_id)
        return f"{self.project_id}:{self.entity_id}"


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


def _chase_messages(project: Any, plan: control.Plan, today: date,
                    policy: control.Policy) -> list[Message]:
    """Update requests: the chases `control.chase_findings` decided on.

    A chase is not a second reminder about the same thing. `chase_findings`
    only asks where the *silence* is the problem — overdue and quiet, blocked
    and quiet, due and nothing recorded at all — which is exactly the case a
    plain "this is overdue" nudge does not cover, because the owner already
    knows it is overdue and has said nothing about why.

    Fingerprinted on the reason rather than on the day, so a person is asked
    once per situation. When the situation changes — a new blocker, a moved
    date — the reason changes and a new request is right.
    """
    out: list[Message] = []
    for chase in control.chase_findings(plan, today, policy=policy):
        owner = int(chase.owner_id)
        out.append(Message(
            owner, int(project.id), project.code, ENTITY_TASK,
            int(chase.task_id), chase.task_code, UPDATE_REQUESTED,
            _print(int(project.id), ENTITY_TASK, int(chase.task_id), owner,
                   UPDATE_REQUESTED, f"{chase.trigger}:{chase.reason[:60]}"),
            _TITLES[UPDATE_REQUESTED],
            f"{chase.task_code} {chase.task_title} — {chase.reason}",
            asked=True, reason=chase.reason))
    return out


def _merge_chases(nudges: list[Message],
                  chases: list[Message]) -> list[Message]:
    """One message per task per person, even when both rules fire.

    An overdue task whose owner has said nothing produces two findings that
    mean the same thing to the person reading them: "this is late" and "we
    need an update on this". Sending both is how a notification centre stops
    being read.

    So they merge rather than compete. The nudge keeps its trigger — which is
    what preserves the vocabulary a screen groups by, and the fingerprint that
    makes an overdue reminder daily and a due-date reminder once — and takes
    on the chase's obligation: it becomes the update request, with the
    engine's reason attached. A chase with no matching nudge, such as "due in
    two days and no progress recorded at all" where two is not a reminder
    threshold, still stands on its own.
    """
    by_task = {(m.entity_id, m.user_id): m for m in nudges}
    out = list(nudges)
    for chase in chases:
        nudge = by_task.get((chase.entity_id, chase.user_id))
        if nudge is None:
            out.append(chase)
            continue
        nudge.asked = True
        nudge.reason = chase.reason
    return out


def _review_messages(project: Any, plan: control.Plan) -> list[Message]:
    """A task waiting on a reviewer tells the reviewer, not the owner.

    Without this, "in review" is a state the owner can see and the reviewer
    cannot: the work stops on somebody who was never told it had arrived.
    """
    out: list[Message] = []
    for task in plan.tasks:
        if task.status != "IN_REVIEW" or task.reviewer_id is None:
            continue
        out.append(Message(
            int(task.reviewer_id), int(project.id), project.code, ENTITY_TASK,
            int(task.id), task.code, REVIEW,
            _print(int(project.id), ENTITY_TASK, int(task.id),
                   int(task.reviewer_id), REVIEW,
                   f"{task.percent_complete}:{task.last_update_at}"),
            _TITLES[REVIEW],
            f"{task.code} {task.title} is waiting for your review."))
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

        pending.extend(_merge_chases(
            _task_messages(project, plan, day, policy),
            _chase_messages(project, plan, day, policy)))
        pending.extend(_review_messages(project, plan))
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
        body = message.body
        if message.action:
            body = f"{body}\n\n{message.action}"
        note = Notification(
            user_id=message.user_id, kind="planner",
            title=f"{message.project_code}: {message.title}",
            body=body, object_type=message.link_type,
            object_id=message.link_id, actor_id=None)
        session.add(note)
        session.flush()
        session.add(PlannerReminder(
            project_id=message.project_id, entity_type=message.entity_type,
            entity_id=message.entity_id, user_id=message.user_id,
            trigger=message.trigger, fingerprint=message.fingerprint,
            notification_id=int(note.id),
            asked=bool(message.asked), reason=message.reason,
            state="sent"))
        result.messages.append(message)
        result.sent += 1


# ================================================== the platform's scheduler


def run_sweep_job(job: Any, should_stop: Any = None) -> dict[str, Any]:
    """The handler the existing agentic worker calls.

    The signature is the worker's, not this module's: `handler(job,
    should_stop)`. It opens its own session for the same reason
    `run_schedule_tick` does — a worker handler is given a job, never a
    transaction, and a sweep that borrowed one would be holding it open for
    the length of the estate.

    `should_stop` is accepted and honoured before the write: a drain signal
    part-way through a sweep should leave the queue able to re-run it, and the
    reminder fingerprints make the re-run produce the same messages once.
    """
    from backend.db.engine import get_session

    payload = getattr(job, "payload", None) or {}
    today = payload.get("today")
    day = (date.fromisoformat(today) if isinstance(today, str) and today
           else None)
    ids = payload.get("project_ids") or None

    if should_stop is not None and should_stop():
        logger.info("planner sweep asked to stop before it started")
        return {"stopped": True}

    with get_session() as session:
        outcome = sweep(session, today=day, project_ids=ids)
    logger.info("planner sweep (%s): %s",
                payload.get("reason") or "scheduled", outcome.to_dict())
    return outcome.to_dict()


def schedule(session: Any, *, today: date | None = None) -> tuple[int, bool]:
    """Queue one estate-wide sweep for a given day, at most once at a time.

    The idempotency key is the day, so two ticks an hour apart on the same
    date find the queued job rather than running the estate twice. Once that
    job has completed the key is free again, which is what lets a schedule
    running several times a day work: the fingerprints, not the key, are what
    stop a person hearing the same thing twice.
    """
    from backend.agentic import queue

    day = (today or datetime.now(UTC).date()).isoformat()
    return queue.enqueue(session, kind=PLANNER_SWEEP,
                         idempotency_key=f"planner-sweep:{day}",
                         payload={"today": day, "reason": "scheduled"},
                         priority=queue.PRIORITY_SCHEDULED,
                         timeout_seconds=600)


# ----------------------------------------------------- answering a chase


def answer_requests(session: Any, *, task_id: int, user_id: int | None,
                    update_id: int | None) -> int:
    """Close the update requests this person has just answered.

    Only the requests made OF them: somebody else reporting on the task does
    not discharge the owner's obligation, and a manager's screen that showed
    it did would tell them the chase worked when it did not.

    Returns how many were closed, so a caller can say "and that answered two
    outstanding requests" rather than guessing.
    """
    if user_id is None:
        return 0
    rows = list(session.execute(
        select(PlannerReminder).where(
            PlannerReminder.entity_type == ENTITY_TASK,
            PlannerReminder.entity_id == int(task_id),
            PlannerReminder.user_id == int(user_id),
            PlannerReminder.asked.is_(True),
            PlannerReminder.state == "sent")).scalars())
    now = datetime.now(UTC)
    for row in rows:
        row.state = "answered"
        row.responded_at = now
        if update_id is not None:
            row.response_update_id = int(update_id)
    return len(rows)


def cancel_requests(session: Any, *, task_id: int, why: str = "") -> int:
    """Close outstanding requests about a task nobody needs to report on.

    A completed or cancelled task is not a person who owes an update. Left
    open, it sits on the manager's screen as somebody who never replied — a
    reading of the record that is precisely wrong.
    """
    _ = why
    rows = list(session.execute(
        select(PlannerReminder).where(
            PlannerReminder.entity_type == ENTITY_TASK,
            PlannerReminder.entity_id == int(task_id),
            PlannerReminder.asked.is_(True),
            PlannerReminder.state == "sent")).scalars())
    for row in rows:
        row.state = "cancelled"
        row.responded_at = datetime.now(UTC)
    return len(rows)


def requests(session: Any, project_ids: list[int], *,
             state: str = "", limit: int = 200) -> list[dict[str, Any]]:
    """Who has been asked for an update, why, and whether they came back.

    §1.3's screen, as data. Ordered oldest first: the request nobody has
    answered for a week is the one the manager needs, and burying it under
    this morning's is how a chase list stops being read.
    """
    from backend.db.models import User
    from backend.models.planner import PlannerProject, PlannerTask, PlannerUpdate

    if not project_ids:
        return []
    stmt = (select(PlannerReminder)
            .where(PlannerReminder.project_id.in_([int(i) for i in project_ids]),
                   PlannerReminder.asked.is_(True))
            .order_by(PlannerReminder.sent_at.asc())
            .limit(int(limit)))
    if state:
        stmt = stmt.where(PlannerReminder.state == state)
    rows = list(session.execute(stmt).scalars())
    if not rows:
        return []

    people = {u.id: u for u in session.execute(
        select(User).where(User.id.in_({r.user_id for r in rows}
                                       | {r.requested_by for r in rows
                                          if r.requested_by}))).scalars()}
    tasks = {t.id: t for t in session.execute(
        select(PlannerTask).where(
            PlannerTask.id.in_({r.entity_id for r in rows}))).scalars()}
    projects = {p.id: p for p in session.execute(
        select(PlannerProject).where(
            PlannerProject.id.in_({r.project_id for r in rows}))).scalars()}
    answers = {u.id: u for u in session.execute(
        select(PlannerUpdate).where(
            PlannerUpdate.id.in_({r.response_update_id for r in rows
                                  if r.response_update_id}))).scalars()}

    def person(user_id: int | None) -> dict[str, Any] | None:
        row = people.get(user_id) if user_id else None
        if row is None:
            return None
        return {"id": int(row.id),
                "name": getattr(row, "full_name", "") or row.username,
                "username": row.username}

    out: list[dict[str, Any]] = []
    for row in rows:
        task = tasks.get(row.entity_id)
        project = projects.get(row.project_id)
        answer = answers.get(row.response_update_id) if row.response_update_id else None
        out.append({
            "id": int(row.id),
            "project_id": int(row.project_id),
            "project_code": project.code if project else "",
            "project_name": project.name if project else "",
            "task_id": int(row.entity_id),
            "task_code": task.code if task else "",
            "task_title": task.title if task else "",
            "task_status": task.status if task else "",
            "task_percent": int(task.percent_complete or 0) if task else None,
            "person": person(row.user_id),
            "requested_by": person(row.requested_by),
            "reason": row.reason,
            "trigger": row.trigger,
            "state": row.state,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            "responded_at": (row.responded_at.isoformat()
                             if row.responded_at else None),
            "response": ({"narrative": answer.narrative,
                          "blocker": answer.blocker,
                          "next_step": answer.next_step,
                          "new_percent": answer.new_percent,
                          "new_status": answer.new_status}
                         if answer else None),
        })
    return out


# ------------------------------------------------------- event-driven

#: How long an event-driven re-evaluation waits before it runs. Long enough
#: that somebody editing five tasks in a row produces one sweep rather than
#: five, short enough that "I have just been made owner of something overdue"
#: reaches them while they are still at the screen.
EVENT_DELAY_SECONDS = 45

#: The planner changes worth re-evaluating a project for. A change to a
#: description or a title is not here: it moves no commitment, and a sweep
#: that ran for it would be a sweep that ran for everything.
EVENTS: tuple[str, ...] = (
    "task_created", "task_due_date_changed", "task_status_changed",
    "task_progress_changed", "task_blocked", "task_unblocked",
    "task_owner_changed", "task_deleted",
    "milestone_changed", "dependency_changed",
    "raid_severity_changed", "participant_changed",
    "project_dates_changed", "imported",
)


def on_event(session: Any, project_id: int, event: str) -> tuple[int, bool]:
    """Re-evaluate one project shortly after something material happened.

    Enqueued inside the caller's transaction on purpose: if the mutation rolls
    back, so does the job. A sweep for a change that never happened would
    chase somebody about a due date they never moved.

    Debounced by a coarse time bucket rather than by "is one already queued":
    a burst of edits inside the same bucket collapses to one job, and an edit
    after the bucket rolls over gets its own. Both are correct; a per-edit job
    is not.
    """
    from backend.agentic import queue

    pid = int(project_id)
    if event not in EVENTS:
        raise ValueError(
            f"'{event}' is not a planner event the monitor knows about. "
            f"Known: {', '.join(EVENTS)}.")
    now = datetime.now(UTC)
    bucket = int(now.timestamp()) // EVENT_DELAY_SECONDS
    return queue.enqueue(
        session, kind=PLANNER_SWEEP,
        idempotency_key=f"planner-event:{pid}:{bucket}",
        payload={"project_ids": [pid], "reason": f"event:{event}"},
        priority=queue.PRIORITY_EVENT,
        delay_seconds=EVENT_DELAY_SECONDS,
        timeout_seconds=300)


__all__ = [
    "MONITOR_VERSION", "PLANNER_SWEEP", "Sweep", "Message",
    "DUE", "OVERDUE", "STALE", "BLOCKED", "MILESTONE_DUE",
    "MILESTONE_OVERDUE", "HEALTH_RED",
    "EVENTS", "EVENT_DELAY_SECONDS",
    "REVIEW", "UPDATE_REQUESTED",
    "sweep", "run_sweep_job", "schedule", "on_event",
    "answer_requests", "cancel_requests", "requests",
]
