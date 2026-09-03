"""The deterministic project-control engine.

Everything in this module is a pure function of a plan and a date. Nothing
here reads a model, writes a row, sends a message or looks at a clock it was
not given — `today` is always a parameter, because a scheduler that cannot be
tested at an arbitrary date is a scheduler nobody can trust.

The engine answers six questions, in this order, because each one depends on
the ones above it:

  1. Is this task late, near, or quiet?          `assess_task`
  2. Which dependencies are unsatisfied?          `dependency_findings`
  3. How complete is this workstream, project?    `progress`
  4. What is threatening a milestone?             `milestone_findings`
  5. What colour is the project, and why?         `health`
  6. Who needs chasing, and about what?           `chase_findings`

Why an explicit finding rather than a boolean
---------------------------------------------
"AMBER" on its own is a colour. `AMBER — 3 tasks overdue and 1 task due within
3 days is blocked` is a finding somebody can act on, argue with, or check. Every
rule in here produces the sentence alongside the verdict, and the health engine
composes its reason from the findings rather than from a lookup table.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from backend.models.planner import (
    DEP_FINISH_TO_FINISH,
    DEP_FINISH_TO_START,
    DEP_START_TO_START,
    ENTITY_MILESTONE,
    ENTITY_TASK,
    HEALTH_AMBER,
    HEALTH_GREEN,
    HEALTH_RED,
    HEALTH_UNKNOWN,
    MILESTONE_ACHIEVED,
    MILESTONE_OPEN,
    RAID_LIVE,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    TASK_BLOCKED,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_NOT_STARTED,
    TASK_OPEN,
)

CONTROL_VERSION = "1.0.0"


# ===================================================================== policy


@dataclass(frozen=True)
class Policy:
    """Every threshold the engine uses, in one place.

    Scattering these through the rules is how a product ends up calling a task
    "due soon" at seven days in one screen and three in another. A project may
    carry its own reminder days and staleness window; everything else is a
    platform default that an administrator can move once.
    """

    #: A task is "due soon" inside this many days.
    due_soon_days: int = 7
    #: ...and "imminent" inside this many, which is what turns a blocker amber.
    imminent_days: int = 3
    #: A near-term task nobody has updated for this long is stale.
    stale_after_days: int = 7
    #: How many ordinary overdue tasks it takes before the project is amber on
    #: volume alone, regardless of criticality.
    amber_overdue_count: int = 3
    #: How far past its date a non-critical dependency has to be before it is
    #: treated as a schedule threat rather than a slip.
    dependency_slip_days: int = 3
    #: Days before a milestone at which an unfinished predecessor is a risk.
    milestone_horizon_days: int = 14
    #: When the owner of a task due this soon has reported no progress at all,
    #: the agent asks for an update.
    chase_no_progress_days: int = 3
    #: Reminder thresholds, in days before the due date. Zero is the due date
    #: itself; the overdue reminder is separate and fires once.
    reminder_days: tuple[int, ...] = (7, 3, 1, 0)


DEFAULT_POLICY = Policy()


# ================================================================== findings


#: Severity of a finding, in the order the health engine reads them.
INFO = "info"
WARN = "warn"
CRITICAL = "critical"


@dataclass(frozen=True)
class Finding:
    """One thing the engine noticed, and the sentence that explains it."""

    #: overdue | due_soon | blocked | stale | dependency | milestone | raid |
    #: no_plan | not_started
    rule: str
    severity: str
    detail: str
    entity_type: str = ""
    entity_id: int | None = None
    entity_code: str = ""
    #: Whatever the rule measured, so a caller can sort or threshold on it.
    value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule, "severity": self.severity,
            "detail": self.detail, "entity_type": self.entity_type,
            "entity_id": self.entity_id, "entity_code": self.entity_code,
            "value": self.value,
        }


# ============================================================ reading a task


@dataclass
class TaskView:
    """What the engine needs to know about a task.

    A plain structure rather than the ORM row so every rule can be tested
    without a database, and so the same rules run over a workbook that has been
    parsed but not yet imported.
    """

    id: int
    code: str
    title: str
    status: str
    percent_complete: int
    weight: float = 1.0
    due_date: date | None = None
    start_date: date | None = None
    completed_date: date | None = None
    owner_id: int | None = None
    critical: bool = False
    blocked: bool = False
    blocker_reason: str = ""
    last_update_at: datetime | None = None
    workstream_id: int | None = None
    parent_id: int | None = None
    priority: str = ""

    @classmethod
    def of(cls, row: Any) -> TaskView:
        return cls(
            id=int(row.id), code=str(row.code), title=str(row.title),
            status=str(row.status),
            percent_complete=int(row.percent_complete or 0),
            weight=float(row.weight if row.weight is not None else 1),
            due_date=row.due_date, start_date=row.start_date,
            completed_date=row.completed_date,
            owner_id=row.owner_id, critical=bool(row.critical),
            blocked=bool(row.blocked),
            blocker_reason=str(row.blocker_reason or ""),
            last_update_at=row.last_update_at,
            workstream_id=row.workstream_id, parent_id=row.parent_id,
            priority=str(row.priority or ""))

    @property
    def open(self) -> bool:
        return self.status in TASK_OPEN


@dataclass
class MilestoneView:
    id: int
    code: str
    name: str
    status: str
    target_date: date | None = None
    actual_date: date | None = None
    owner_id: int | None = None
    critical: bool = False
    workstream_id: int | None = None

    @classmethod
    def of(cls, row: Any) -> MilestoneView:
        return cls(
            id=int(row.id), code=str(row.code), name=str(row.name),
            status=str(row.status), target_date=row.target_date,
            actual_date=row.actual_date, owner_id=row.owner_id,
            critical=bool(row.critical), workstream_id=row.workstream_id)

    @property
    def open(self) -> bool:
        return self.status in MILESTONE_OPEN


@dataclass
class DependencyView:
    predecessor_type: str
    predecessor_id: int
    successor_type: str
    successor_id: int
    dependency_type: str = DEP_FINISH_TO_START
    lag_days: int = 0

    @classmethod
    def of(cls, row: Any) -> DependencyView:
        return cls(
            predecessor_type=str(row.predecessor_type),
            predecessor_id=int(row.predecessor_id),
            successor_type=str(row.successor_type),
            successor_id=int(row.successor_id),
            dependency_type=str(row.dependency_type),
            lag_days=int(row.lag_days or 0))


@dataclass
class Plan:
    """One project's schedule, as the engine sees it."""

    project_id: int
    code: str = ""
    name: str = ""
    status: str = ""
    target_end_date: date | None = None
    tasks: list[TaskView] = field(default_factory=list)
    milestones: list[MilestoneView] = field(default_factory=list)
    dependencies: list[DependencyView] = field(default_factory=list)
    #: (severity, status, title) for each live RAID item. The engine only needs
    #: to know how bad and whether it is still open.
    raid: list[tuple[str, str, str]] = field(default_factory=list)
    stale_after_days: int = 7

    def task(self, task_id: int) -> TaskView | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def milestone(self, milestone_id: int) -> MilestoneView | None:
        return next((m for m in self.milestones if m.id == milestone_id),
                    None)


# ============================================================ the task rules


def days_overdue(task: TaskView, today: date) -> int:
    """How many days past its due date an OPEN task is. Zero otherwise.

    A completed or cancelled task is never overdue however old its due date
    is: it is not owed any more. Getting this wrong is the single most common
    way a project planner reports a hundred red items nobody can close.
    """
    if not task.open or task.due_date is None:
        return 0
    return max(0, (today - task.due_date).days)


def days_until_due(task: TaskView, today: date) -> int | None:
    if not task.open or task.due_date is None:
        return None
    return (task.due_date - today).days


def is_stale(task: TaskView, today: date, *, policy: Policy = DEFAULT_POLICY,
             window: int | None = None) -> bool:
    """Nobody has said anything about a task that needs saying something about.

    Staleness is only meaningful for work that is NEAR — a task due in four
    months and untouched for a fortnight is not stale, it is not started yet.
    Applying the rule to the whole plan is how a monitor generates three
    hundred update requests on its first run and is switched off the same day.
    """
    if not task.open:
        return False
    near = days_until_due(task, today)
    if near is None or near > policy.due_soon_days:
        return False
    limit = window if window is not None else policy.stale_after_days
    if task.last_update_at is None:
        # Nothing has been said about it. That is only evidence of silence
        # where there is also nothing to show: a task standing at 60% with no
        # update row is a plan that was imported with progress already on it,
        # and calling that "never updated" tells the owner off for somebody
        # else's spreadsheet.
        return task.percent_complete == 0
    seen = task.last_update_at.date()
    return (today - seen).days >= limit


def assess_task(task: TaskView, today: date, *,
                policy: Policy = DEFAULT_POLICY,
                stale_window: int | None = None) -> list[Finding]:
    """Everything the engine has to say about one task."""
    found: list[Finding] = []
    if not task.open:
        return found

    late = days_overdue(task, today)
    if late:
        found.append(Finding(
            "overdue", CRITICAL if task.critical else WARN,
            f"{task.code} — {task.title} is {late} day"
            f"{'' if late == 1 else 's'} overdue.",
            ENTITY_TASK, task.id, task.code, float(late)))
    else:
        near = days_until_due(task, today)
        if near is not None and near <= policy.due_soon_days:
            found.append(Finding(
                "due_soon", WARN if near <= policy.imminent_days else INFO,
                f"{task.code} — {task.title} is due in {near} day"
                f"{'' if near == 1 else 's'} and is "
                f"{task.percent_complete}% complete.",
                ENTITY_TASK, task.id, task.code, float(near)))

    if task.blocked or task.status == TASK_BLOCKED:
        reason = task.blocker_reason.strip() or "no reason has been recorded"
        found.append(Finding(
            "blocked", CRITICAL if task.critical else WARN,
            f"{task.code} — {task.title} is blocked: {reason}.",
            ENTITY_TASK, task.id, task.code))

    if is_stale(task, today, policy=policy, window=stale_window):
        if task.last_update_at is None:
            detail = (f"{task.code} — {task.title} is due soon and has never "
                      "been updated.")
            quiet = None
        else:
            quiet = (today - task.last_update_at.date()).days
            detail = (f"{task.code} — {task.title} is due soon and has not "
                      f"been updated for {quiet} days.")
        found.append(Finding("stale", WARN, detail, ENTITY_TASK, task.id,
                             task.code, float(quiet) if quiet else None))

    return found


# ====================================================== the dependency graph


def _key(kind: str, entity_id: int) -> tuple[str, int]:
    return (kind, int(entity_id))


def cycle(dependencies: Iterable[DependencyView]) -> list[tuple[str, int]]:
    """The first dependency cycle, as the path around it. Empty if there is none.

    Returned as a path rather than a boolean so the error message can name the
    tasks involved. "This creates a circular dependency" tells somebody they
    have a problem; "T-104 → T-110 → T-104" tells them where it is.
    """
    edges: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    nodes: set[tuple[str, int]] = set()
    for dep in dependencies:
        a = _key(dep.predecessor_type, dep.predecessor_id)
        b = _key(dep.successor_type, dep.successor_id)
        edges[a].append(b)
        nodes.add(a)
        nodes.add(b)

    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[tuple[str, int], int] = {n: WHITE for n in nodes}
    parent: dict[tuple[str, int], tuple[str, int] | None] = {}

    for start in sorted(nodes):
        if colour[start] != WHITE:
            continue
        # Iterative rather than recursive: a plan with a thousand chained
        # tasks would overflow the stack, and a project planner that crashes
        # on a big plan is worse than one that is slow on it.
        stack: list[tuple[tuple[str, int], bool]] = [(start, False)]
        parent[start] = None
        while stack:
            node, leaving = stack.pop()
            if leaving:
                colour[node] = BLACK
                continue
            if colour[node] != WHITE:
                continue
            colour[node] = GREY
            stack.append((node, True))
            for nxt in edges.get(node, ()):
                if colour.get(nxt) == GREY:
                    path = [nxt]
                    walk: tuple[str, int] | None = node
                    while walk is not None and walk != nxt:
                        path.append(walk)
                        walk = parent.get(walk)
                    path.append(nxt)
                    return list(reversed(path))
                if colour.get(nxt, WHITE) == WHITE:
                    parent[nxt] = node
                    stack.append((nxt, False))
    return []


def _finished(plan: Plan, kind: str, entity_id: int) -> bool:
    if kind == ENTITY_TASK:
        task = plan.task(entity_id)
        return task is not None and task.status == TASK_COMPLETED
    milestone = plan.milestone(entity_id)
    return milestone is not None and milestone.status == MILESTONE_ACHIEVED


def _started(plan: Plan, kind: str, entity_id: int) -> bool:
    if kind == ENTITY_TASK:
        task = plan.task(entity_id)
        if task is None:
            return False
        return task.status != TASK_NOT_STARTED or task.percent_complete > 0
    return _finished(plan, kind, entity_id)


def _label(plan: Plan, kind: str, entity_id: int) -> str:
    if kind == ENTITY_TASK:
        task = plan.task(entity_id)
        return f"{task.code} — {task.title}" if task else f"task {entity_id}"
    milestone = plan.milestone(entity_id)
    return (f"{milestone.code} — {milestone.name}" if milestone
            else f"milestone {entity_id}")


def _due(plan: Plan, kind: str, entity_id: int) -> date | None:
    if kind == ENTITY_TASK:
        task = plan.task(entity_id)
        return task.due_date if task else None
    milestone = plan.milestone(entity_id)
    return milestone.target_date if milestone else None


def _start(plan: Plan, kind: str, entity_id: int) -> date | None:
    if kind == ENTITY_TASK:
        task = plan.task(entity_id)
        return task.start_date if task else None
    return _due(plan, kind, entity_id)


def dependency_findings(plan: Plan, today: date, *,
                        policy: Policy = DEFAULT_POLICY) -> list[Finding]:
    """Where a dependency is not satisfied and the successor is due to move.

    Only reported when it MATTERS: a predecessor that is unfinished but whose
    successor does not start for another two months is a plan, not a problem.
    The rule fires when the successor's own date has arrived or is imminent and
    the thing it waits on has not happened.
    """
    found: list[Finding] = []
    for dep in plan.dependencies:
        kind = dep.dependency_type
        # Which end of the predecessor has to have happened, and which end of
        # the successor is the one at risk.
        if kind in (DEP_FINISH_TO_START, DEP_FINISH_TO_FINISH):
            satisfied = _finished(plan, dep.predecessor_type,
                                  dep.predecessor_id)
            want = "completed"
        else:
            satisfied = _started(plan, dep.predecessor_type,
                                 dep.predecessor_id)
            want = "started"
        if satisfied:
            continue

        if kind in (DEP_FINISH_TO_START, DEP_START_TO_START):
            at_risk = _start(plan, dep.successor_type, dep.successor_id)
            moment = "start"
        else:
            at_risk = _due(plan, dep.successor_type, dep.successor_id)
            moment = "finish"
        if at_risk is None:
            continue
        gate = at_risk - timedelta(days=dep.lag_days)
        near = (gate - today).days
        if near > policy.imminent_days:
            continue

        successor_open = (
            plan.task(dep.successor_id).open
            if dep.successor_type == ENTITY_TASK
            and plan.task(dep.successor_id) is not None
            else (plan.milestone(dep.successor_id).open
                  if plan.milestone(dep.successor_id) is not None else False))
        if not successor_open:
            continue

        late = -near
        severity = CRITICAL if late >= policy.dependency_slip_days else WARN
        when = (f"was due to {moment} {late} day"
                f"{'' if late == 1 else 's'} ago" if late > 0
                else f"is due to {moment} in {near} day"
                     f"{'' if near == 1 else 's'}")
        found.append(Finding(
            "dependency", severity,
            f"{_label(plan, dep.successor_type, dep.successor_id)} {when}, "
            f"and {_label(plan, dep.predecessor_type, dep.predecessor_id)} "
            f"has not {want}.",
            dep.successor_type, dep.successor_id,
            (plan.task(dep.successor_id).code
             if dep.successor_type == ENTITY_TASK
             and plan.task(dep.successor_id) else ""),
            float(late)))
    return found


def blocking(plan: Plan) -> dict[int, list[int]]:
    """Task id → the ids of open things waiting on it.

    "What is blocking the next milestone?" is this map read backwards, and a
    task with three unfinished successors is a different management problem
    from one with none.
    """
    out: dict[int, list[int]] = defaultdict(list)
    for dep in plan.dependencies:
        if dep.predecessor_type != ENTITY_TASK:
            continue
        task = plan.task(dep.predecessor_id)
        if task is None or not task.open:
            continue
        out[dep.predecessor_id].append(dep.successor_id)
    return dict(out)


def downstream(plan: Plan, kind: str, entity_id: int) -> list[tuple[str, int]]:
    """Everything that transitively waits on one thing.

    Breadth-first with a seen set, so a cycle that slipped past validation
    cannot hang the caller. The engine must never be the reason a page does
    not load.
    """
    edges: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    for dep in plan.dependencies:
        edges[_key(dep.predecessor_type, dep.predecessor_id)].append(
            _key(dep.successor_type, dep.successor_id))
    seen: set[tuple[str, int]] = {_key(kind, entity_id)}
    queue = deque(edges.get(_key(kind, entity_id), ()))
    out: list[tuple[str, int]] = []
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        out.append(node)
        queue.extend(edges.get(node, ()))
    return out


def milestone_findings(plan: Plan, today: date, *,
                       policy: Policy = DEFAULT_POLICY) -> list[Finding]:
    """Milestones that are late, or that something unfinished is threatening."""
    found: list[Finding] = []
    waiting: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for dep in plan.dependencies:
        if dep.successor_type == ENTITY_MILESTONE:
            waiting[dep.successor_id].append(
                (dep.predecessor_type, dep.predecessor_id))

    for milestone in plan.milestones:
        if not milestone.open or milestone.target_date is None:
            continue
        near = (milestone.target_date - today).days
        if near < 0:
            found.append(Finding(
                "milestone", CRITICAL if milestone.critical else WARN,
                f"{milestone.code} — {milestone.name} was due "
                f"{-near} day{'' if near == -1 else 's'} ago and has not been "
                "achieved.",
                ENTITY_MILESTONE, milestone.id, milestone.code, float(-near)))
            continue
        if near > policy.milestone_horizon_days:
            continue

        outstanding = [
            (kind, ident) for kind, ident in waiting.get(milestone.id, ())
            if not _finished(plan, kind, ident)]
        if not outstanding:
            continue
        names = ", ".join(_label(plan, k, i) for k, i in outstanding[:3])
        more = ("" if len(outstanding) <= 3
                else f" and {len(outstanding) - 3} more")
        found.append(Finding(
            "milestone", CRITICAL if milestone.critical else WARN,
            f"{milestone.code} — {milestone.name} is due in {near} day"
            f"{'' if near == 1 else 's'} and waits on {names}{more}.",
            ENTITY_MILESTONE, milestone.id, milestone.code, float(near)))
    return found


# =================================================================== progress


def progress(tasks: Iterable[TaskView]) -> int:
    """Weighted percent complete, as a whole number.

    Cancelled tasks are excluded entirely rather than counted as complete or
    as zero. Counting them complete flatters the project; counting them zero
    punishes it for work somebody correctly decided not to do. A project of
    ten tasks that cancels two is a project of eight.

    A completed task counts as 100 whatever its recorded percentage says,
    because the status is the commitment and the percentage is a progress
    note somebody forgot to finish typing.
    """
    counted = [t for t in tasks if t.status != TASK_CANCELLED]
    total = sum(max(0.0, t.weight) for t in counted)
    if total <= 0:
        return 0
    done = 0.0
    for task in counted:
        pct = 100.0 if task.status == TASK_COMPLETED else float(
            max(0, min(100, task.percent_complete)))
        done += max(0.0, task.weight) * pct
    return int(round(done / total))


def workstream_progress(tasks: Iterable[TaskView]) -> dict[int, int]:
    """The same calculation, per workstream. Tasks with no workstream are
    counted in the project but in no workstream, which is the honest reading:
    they are real work that belongs to nobody's strand."""
    grouped: dict[int, list[TaskView]] = defaultdict(list)
    for task in tasks:
        if task.workstream_id is not None:
            grouped[int(task.workstream_id)].append(task)
    return {ws: progress(rows) for ws, rows in grouped.items()}


# ===================================================================== health


@dataclass(frozen=True)
class Health:
    """A colour, the sentence behind it, and the findings that produced it."""

    status: str
    reason: str
    findings: tuple[Finding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason,
                "findings": [f.to_dict() for f in self.findings]}


def _plan_is_readable(plan: Plan) -> bool:
    """Whether there is enough of a plan to judge.

    A project with no tasks, or with tasks that carry no dates at all, cannot
    be late. Reporting it GREEN would be a lie of omission — it says "nothing
    is wrong" when the truth is "nobody has written down what is meant to
    happen".
    """
    if not plan.tasks and not plan.milestones:
        return False
    dated = [t for t in plan.tasks if t.due_date is not None]
    milestoned = [m for m in plan.milestones if m.target_date is not None]
    return bool(dated or milestoned)


def health(plan: Plan, today: date, *,
           policy: Policy = DEFAULT_POLICY) -> Health:
    """What colour this project is, and the reason in one sentence.

    Read top to bottom: the first band whose conditions are met wins, and the
    reason names the specific things that met them. Nothing here is weighted,
    scored or tuned — a steering committee can be walked through every step.
    """
    if not _plan_is_readable(plan):
        return Health(
            HEALTH_UNKNOWN,
            "There is not enough of a plan to judge: no task or milestone "
            "carries a date.", ())

    findings: list[Finding] = []
    for task in plan.tasks:
        findings.extend(assess_task(task, today, policy=policy,
                                    stale_window=plan.stale_after_days))
    findings.extend(dependency_findings(plan, today, policy=policy))
    findings.extend(milestone_findings(plan, today, policy=policy))

    for severity, status, title in plan.raid:
        if status in RAID_LIVE and severity in (SEVERITY_HIGH,
                                                SEVERITY_CRITICAL):
            findings.append(Finding(
                "raid", CRITICAL if severity == SEVERITY_CRITICAL else WARN,
                f"A {severity.lower()}-severity item is open: {title}.",
                "", None, "", None))

    reasons: list[str] = []

    # ---- RED --------------------------------------------------------------
    critical_milestone = [f for f in findings
                          if f.rule == "milestone" and f.severity == CRITICAL
                          and (f.value or 0) > 0 and _overdue_milestone(plan,
                                                                        f)]
    if critical_milestone:
        reasons.append(f"{len(critical_milestone)} critical milestone"
                       f"{'' if len(critical_milestone) == 1 else 's'} overdue")
    critical_overdue = [f for f in findings
                        if f.rule == "overdue" and f.severity == CRITICAL]
    if critical_overdue:
        reasons.append(f"{len(critical_overdue)} critical task"
                       f"{'' if len(critical_overdue) == 1 else 's'} overdue")
    critical_dependency = [f for f in findings
                           if f.rule == "dependency"
                           and f.severity == CRITICAL]
    if critical_dependency:
        reasons.append(f"{len(critical_dependency)} critical dependency"
                       f"{'' if len(critical_dependency) == 1 else 'ies'} "
                       "unresolved".replace("dependencyies", "dependencies"))
    breached = (plan.target_end_date is not None
                and plan.target_end_date < today
                and any(t.open for t in plan.tasks))
    if breached:
        reasons.append("the target completion date has passed with work still "
                       "open")
    if reasons:
        return Health(HEALTH_RED, _sentence(reasons), tuple(findings))

    # ---- AMBER ------------------------------------------------------------
    overdue = [f for f in findings if f.rule == "overdue"]
    if len(overdue) >= policy.amber_overdue_count:
        reasons.append(f"{len(overdue)} tasks overdue")
    elif overdue:
        reasons.append(f"{len(overdue)} task"
                       f"{'' if len(overdue) == 1 else 's'} overdue")
    imminent_blocked = [
        f for f in findings if f.rule == "blocked"
        and _imminent(plan, f, today, policy)]
    if imminent_blocked:
        reasons.append(f"{len(imminent_blocked)} task"
                       f"{'' if len(imminent_blocked) == 1 else 's'} due "
                       "shortly is blocked" if len(imminent_blocked) == 1
                       else f"{len(imminent_blocked)} tasks due shortly are "
                            "blocked")
    # Counted per TASK and net of the ones already named. A task that is
    # overdue AND silent is one problem the reader has to deal with, and
    # reporting it in two clauses of the same sentence makes a project look
    # worse than it is — which is exactly as misleading as making it look
    # better.
    named = {f.entity_id for f in findings
             if f.rule in ("overdue", "blocked") and f.entity_id is not None}
    stale = [f for f in findings
             if f.rule == "stale" and f.entity_id not in named]
    if stale:
        reasons.append(f"{len(stale)} near-term task"
                       f"{'' if len(stale) == 1 else 's'} without a recent "
                       "update")
    threatened = [f for f in findings if f.rule == "milestone"]
    if threatened:
        reasons.append(f"{len(threatened)} milestone"
                       f"{'' if len(threatened) == 1 else 's'} at risk")
    open_raid = [f for f in findings if f.rule == "raid"]
    if open_raid:
        reasons.append(f"{len(open_raid)} high-severity item"
                       f"{'' if len(open_raid) == 1 else 's'} open")
    dependency = [f for f in findings if f.rule == "dependency"]
    if dependency:
        reasons.append(f"{len(dependency)} unresolved dependenc"
                       f"{'y' if len(dependency) == 1 else 'ies'}")
    if reasons:
        return Health(HEALTH_AMBER, _sentence(reasons), tuple(findings))

    return Health(
        HEALTH_GREEN,
        "Nothing overdue, blocked or stale, and no milestone is at risk.",
        tuple(findings))


def _overdue_milestone(plan: Plan, finding: Finding) -> bool:
    milestone = plan.milestone(int(finding.entity_id or 0))
    return bool(milestone and milestone.critical
                and "was due" in finding.detail)


def _imminent(plan: Plan, finding: Finding, today: date,
              policy: Policy) -> bool:
    task = plan.task(int(finding.entity_id or 0))
    if task is None:
        return False
    near = days_until_due(task, today)
    return near is not None and near <= policy.imminent_days


def _sentence(reasons: list[str]) -> str:
    """Join the reasons the way a person would say them."""
    if len(reasons) == 1:
        return reasons[0][0].upper() + reasons[0][1:] + "."
    joined = ", ".join(reasons[:-1]) + f" and {reasons[-1]}"
    return joined[0].upper() + joined[1:] + "."


# ================================================================== chasing


@dataclass(frozen=True)
class Chase:
    """Somebody who owes an update, and what about."""

    task_id: int
    task_code: str
    task_title: str
    owner_id: int
    reason: str
    #: no_progress | stale | overdue_quiet | blocked_quiet
    trigger: str
    due_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "task_code": self.task_code,
                "task_title": self.task_title, "owner_id": self.owner_id,
                "reason": self.reason, "trigger": self.trigger,
                "due_date": self.due_date.isoformat() if self.due_date
                else None}


def chase_findings(plan: Plan, today: date, *,
                   policy: Policy = DEFAULT_POLICY) -> list[Chase]:
    """Which owners the agent should ask for an update, and why.

    Deterministic on purpose. A model decides how to word the request; it does
    not decide who gets one. Each task produces at most one chase, taking the
    most serious reason, so an overdue task nobody has touched does not
    generate three separate messages to the same person.
    """
    out: list[Chase] = []
    for task in plan.tasks:
        if not task.open or task.owner_id is None:
            continue
        late = days_overdue(task, today)
        near = days_until_due(task, today)
        quiet = ((today - task.last_update_at.date()).days
                 if task.last_update_at else None)
        stale = is_stale(task, today, policy=policy,
                         window=plan.stale_after_days)

        if late and (quiet is None or quiet >= policy.imminent_days):
            out.append(Chase(
                task.id, task.code, task.title, int(task.owner_id),
                f"{task.code} is {late} day{'' if late == 1 else 's'} overdue "
                + ("and has never been updated."
                   if quiet is None
                   else f"and was last updated {quiet} days ago."),
                "overdue_quiet", task.due_date))
            continue
        if (task.blocked or task.status == TASK_BLOCKED) and (
                quiet is None or quiet >= policy.imminent_days):
            out.append(Chase(
                task.id, task.code, task.title, int(task.owner_id),
                f"{task.code} is blocked and there has been no update "
                + ("at all." if quiet is None else f"for {quiet} days."),
                "blocked_quiet", task.due_date))
            continue
        if (near is not None and 0 <= near <= policy.chase_no_progress_days
                and task.percent_complete == 0):
            out.append(Chase(
                task.id, task.code, task.title, int(task.owner_id),
                f"{task.code} is due in {near} day"
                f"{'' if near == 1 else 's'} and no progress has been "
                "recorded.",
                "no_progress", task.due_date))
            continue
        if stale:
            out.append(Chase(
                task.id, task.code, task.title, int(task.owner_id),
                f"{task.code} is due soon and "
                + ("has never been updated."
                   if quiet is None else f"has not been updated for "
                                         f"{quiet} days."),
                "stale", task.due_date))
    return out


__all__ = [
    "CONTROL_VERSION", "Policy", "DEFAULT_POLICY", "INFO", "WARN", "CRITICAL",
    "Finding", "TaskView", "MilestoneView", "DependencyView", "Plan",
    "days_overdue", "days_until_due", "is_stale", "assess_task",
    "cycle", "dependency_findings", "blocking", "downstream",
    "milestone_findings", "progress", "workstream_progress",
    "Health", "health", "Chase", "chase_findings",
]
