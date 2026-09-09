"""Who hears about a delay once telling the owner has stopped working.

A reminder is a message to the person who can fix something. An escalation is
a message to the person who can do something about the fact that they haven't.
They are different acts with different audiences, and a planner that conflates
them either nags the owner forever or surprises a sponsor with a task they
have never heard of.

The ladder, in order:

    the task's owner            gets the ordinary reminders, from monitor.py
    the task's escalation owner set on the task itself
    the milestone's            set on the milestone the task sits under
    the project's              set on the project
    the project manager        always exists
    the sponsor                the last stop, and the slowest

Two properties matter more than the individual rules.

**Every rung is skippable and none is invented.** A task with no escalation
owner escalates to its milestone's, and a milestone with none escalates to the
project's. Nothing is sent to somebody who was never named — an escalation to
a person picked by the software is worse than no escalation, because it
teaches everybody that the escalation means nothing.

**Nobody hears twice about the same thing.** Every message carries the same
kind of fingerprint the reminders use, bucketed by the project's own chase
cadence: a Light project escalates once every three days and a Critical one
every day, and running the sweep hourly changes neither. The bucket is
computed from how long the situation has lasted, not from the wall clock, so
a sweep that misses a day does not skip a rung.

Every threshold here comes from `policy.Escalation`, which is per project.
Light, Standard and Critical are genuinely different: Light does not escalate
on lateness at all, Critical escalates after one day and pages the sponsor
after three.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.models.planner import ENTITY_MILESTONE, ENTITY_TASK
from backend.planner import control
from backend.planner import policy as pol

logger = logging.getLogger(__name__)

ESCALATION_VERSION = "1.0.0"

#: An overdue task the owner has not resolved.
ESCALATED = "escalated"
#: A task blocked long enough that somebody else has to unblock it.
ESCALATED_BLOCKED = "escalated_blocked"
#: A late task the arithmetic puts on the critical path.
CRITICAL_PATH = "critical_path"
#: The last stop. Slow on purpose.
SPONSOR_ALERT = "sponsor_alert"
#: A milestone whose work is not going to land in time.
MILESTONE_AT_RISK = "milestone_at_risk"

TRIGGERS: tuple[str, ...] = (ESCALATED, ESCALATED_BLOCKED, CRITICAL_PATH,
                             SPONSOR_ALERT, MILESTONE_AT_RISK)

TITLES = {
    ESCALATED: "Escalated to you",
    ESCALATED_BLOCKED: "Blocked and escalated",
    CRITICAL_PATH: "Critical path at risk",
    SPONSOR_ALERT: "Unresolved delay",
    MILESTONE_AT_RISK: "Milestone at risk",
}

ACTIONS = {
    ESCALATED: "The owner has not resolved this. Decide what changes.",
    ESCALATED_BLOCKED: "Somebody outside the team has to move for this.",
    CRITICAL_PATH: "This slipping moves the project's finish date.",
    SPONSOR_ALERT: "This has been unresolved long enough to need you.",
    MILESTONE_AT_RISK: "The work under this will not land on the date.",
}


#: What each rung is called on screen. The words matter: "escalated to you
#: because you are the escalation owner for M02" is checkable, and "you were
#: notified" is not.
OWN = "own"
MILESTONE = "milestone"
PROJECT = "project"
MANAGER = "manager"
SPONSOR = "sponsor"


@dataclass(frozen=True)
class Rung:
    """One person on the ladder, and why they are on it."""

    user_id: int
    level: str
    from_code: str = ""

    @property
    def because(self) -> str:
        return {
            OWN: "you are the escalation owner for this task",
            MILESTONE: f"you are the escalation owner for {self.from_code}",
            PROJECT: "you are the project's escalation contact",
            MANAGER: "you manage this project",
            SPONSOR: "you sponsor this project",
        }.get(self.level, "you are on the escalation path")

    def to_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "level": self.level,
                "from_code": self.from_code, "because": self.because}


def _rung(value: Any, level: str, from_code: str = "") -> Rung | None:
    try:
        user_id = int(value) if value else 0
    except (TypeError, ValueError):
        return None
    return Rung(user_id, level, from_code) if user_id else None


def _rungs(project: Any, milestone: Any = None,
           task: Any = None) -> list[Rung]:
    """Every rung that is named, in order, WITHOUT collapsing one person.

    A rule that says "tell the sponsor" is about the role. Whether that
    person also happens to be the milestone's escalation contact is a
    question about the message, not about whether the rule applies — and
    collapsing here would silently disable the sponsor rule on every small
    project, which is exactly where it matters most.
    """
    rungs = [
        _rung(getattr(task, "escalation_id", None), OWN),
        _rung(getattr(milestone, "escalation_id", None), MILESTONE,
              str(getattr(milestone, "code", "") or "")),
        _rung(getattr(project, "escalation_id", None), PROJECT),
        _rung(getattr(project, "manager_id", None), MANAGER),
        _rung(getattr(project, "sponsor_id", None), SPONSOR),
    ]
    owner = getattr(task, "owner_id", None)
    found: list[Rung] = []
    for rung in rungs:
        if rung is None:
            continue
        # Never the owner, at any rung. On a small project one person is
        # often the task owner, the milestone's escalation contact and the
        # manager; escalating their own late task to them says nothing they
        # do not already know and arrives as a second copy of the reminder
        # they were sent an hour earlier.
        if owner and rung.user_id == int(owner):
            continue
        found.append(rung)
    return found


def ladder(project: Any, milestone: Any = None,
           task: Any = None) -> list[Rung]:
    """Everybody above the owner, nearest first, each appearing once.

    One person occupying three rungs appears at the nearest one. `findings`
    then sends them a single message — see `_one_each` — carrying the most
    serious of whatever fired.
    """
    seen: set[int] = set()
    found: list[Rung] = []
    for rung in _rungs(project, milestone, task):
        if rung.user_id in seen:
            continue
        seen.add(rung.user_id)
        found.append(rung)
    return found


def first_above(project: Any, milestone: Any = None,
                task: Any = None) -> Rung | None:
    """The nearest person above the owner, or nobody."""
    rungs = ladder(project, milestone, task)
    return rungs[0] if rungs else None


def at_level(project: Any, level: str, milestone: Any = None,
             task: Any = None) -> Rung | None:
    """A specific rung, when a rule names one — the sponsor, say.

    Read from the uncollapsed list, so "tell the sponsor after five days"
    still finds the sponsor on a project where they are also the milestone's
    escalation contact.
    """
    for rung in _rungs(project, milestone, task):
        if rung.level == level:
            return rung
    return None


def bucket(days: int, every: int) -> int:
    """Which repeat this is, counted from the situation rather than the clock.

    A project that escalates every three days does so on day 3, 6 and 9. Two
    sweeps on day 4 produce the same bucket and therefore the same
    fingerprint, so the second is suppressed; a sweep that never ran on day 6
    still produces bucket 2 on day 7, so the rung is not skipped.
    """
    step = max(1, int(every or 1))
    return max(0, int(days)) // step


@dataclass
class Finding:
    """One escalation the rules decided on, before it becomes a message."""

    trigger: str
    rung: Rung
    entity_type: str
    entity_id: int
    entity_code: str
    #: What makes this escalation THIS escalation, for the fingerprint.
    about: str
    sentence: str
    #: The owner who did not resolve it, so the message can name them.
    owner_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"trigger": self.trigger, "rung": self.rung.to_dict(),
                "entity_type": self.entity_type, "entity_id": self.entity_id,
                "entity_code": self.entity_code, "about": self.about,
                "sentence": self.sentence, "owner_id": self.owner_id}


def findings(project: Any, plan: control.Plan, milestones: list[Any],
             today: date, *, agentic: pol.Agentic,
             critical_codes: frozenset[str] = frozenset()) -> list[Finding]:
    """Every escalation this project's own policy asks for today.

    `critical_codes` comes from the CPM engine, computed once by the caller
    rather than per task: whether a task is on the critical path is a property
    of the whole network, and asking the schedule module about it once is both
    cheaper and the only way the answer is consistent within a sweep.
    """
    rules = agentic.escalation
    by_id = {int(row.id): row for row in milestones}
    out: list[Finding] = []

    for task in plan.tasks:
        if not task.open or task.owner_id is None:
            continue
        milestone = _milestone_of(by_id, task)
        late = control.days_overdue(task, today)

        if late and rules.escalate_after_days is not None \
                and late >= rules.escalate_after_days:
            rung = first_above(project, milestone, task)
            if rung:
                out.append(Finding(
                    ESCALATED, rung, ENTITY_TASK, int(task.id), task.code,
                    f"{task.due_date}:{bucket(late, rules.overdue_every_days)}",
                    f"{task.code} {task.title} was due {task.due_date} and is "
                    f"{late} day{'' if late == 1 else 's'} overdue. The owner "
                    "has not resolved it.",
                    owner_id=int(task.owner_id)))

        if task.blocked and rules.escalate_blocked_after_days is not None:
            blocked_days = _blocked_for(task, today)
            if blocked_days >= rules.escalate_blocked_after_days:
                rung = first_above(project, milestone, task)
                if rung:
                    reason = task.blocker_reason or "no reason recorded"
                    out.append(Finding(
                        ESCALATED_BLOCKED, rung, ENTITY_TASK, int(task.id),
                        task.code,
                        f"{reason[:40]}:"
                        f"{bucket(blocked_days, rules.overdue_every_days)}",
                        f"{task.code} {task.title} has been blocked for "
                        f"{blocked_days} day"
                        f"{'' if blocked_days == 1 else 's'}: {reason}",
                        owner_id=int(task.owner_id)))

        if (late and rules.notify_manager_on_critical_path
                and task.code in critical_codes):
            rung = at_level(project, MANAGER, milestone, task)
            if rung:
                out.append(Finding(
                    CRITICAL_PATH, rung, ENTITY_TASK, int(task.id), task.code,
                    f"{task.due_date}:{bucket(late, rules.overdue_every_days)}",
                    f"{task.code} {task.title} is on the critical path and is "
                    f"{late} day{'' if late == 1 else 's'} late. The project's "
                    "finish date moves with it.",
                    owner_id=int(task.owner_id)))

        if late and rules.notify_sponsor_after_days is not None \
                and late >= rules.notify_sponsor_after_days:
            rung = at_level(project, SPONSOR, milestone, task)
            if rung:
                out.append(Finding(
                    SPONSOR_ALERT, rung, ENTITY_TASK, int(task.id), task.code,
                    f"{task.due_date}:"
                    f"{bucket(late, max(rules.overdue_every_days, 1))}",
                    f"{task.code} {task.title} has been overdue for {late} "
                    f"day{'' if late == 1 else 's'} and is still not resolved.",
                    owner_id=int(task.owner_id)))

    out.extend(_milestone_findings(project, plan, milestones, today,
                                   rules=rules))
    return _one_each(out)


#: Which escalation wins when one person is on two rungs for one thing.
#: Read down: the sponsor being told about a three-week-old delay says more
#: than the escalation owner being told about it, and a person who is both
#: should get the more serious of the two rather than both.
_SERIOUSNESS = (SPONSOR_ALERT, CRITICAL_PATH, ESCALATED_BLOCKED, ESCALATED,
                MILESTONE_AT_RISK)


def _one_each(found: list[Finding]) -> list[Finding]:
    """One escalation per person per thing, however many rungs they occupy.

    On a small project the same person is often the milestone's escalation
    owner, the project's, the manager and the sponsor. Without this they would
    receive four messages about one late task, which is precisely the
    notification storm §27 forbids — and the fastest way to teach somebody to
    filter the whole feed into a folder they never open.
    """
    rank = {trigger: index for index, trigger in enumerate(_SERIOUSNESS)}
    best: dict[tuple[str, int, int], Finding] = {}
    for finding in found:
        key = (finding.entity_type, finding.entity_id, finding.rung.user_id)
        current = best.get(key)
        if current is None or rank.get(finding.trigger, 99) < rank.get(
                current.trigger, 99):
            best[key] = finding
    # Stable in the order the rules produced them, so a sweep reads the same
    # way twice and a test can assert on a list rather than on a set.
    keep = set(id(f) for f in best.values())
    return [f for f in found if id(f) in keep]


def _milestone_findings(project: Any, plan: control.Plan,
                        milestones: list[Any], today: date, *,
                        rules: pol.Escalation) -> list[Finding]:
    """A milestone whose work will not land, told before the date, not after.

    "At risk" is not the same as "late": the point of a horizon is to give
    somebody time to act. A milestone is at risk when its date is inside the
    horizon and something under it is already overdue or blocked — which is
    an arithmetic fact, not a judgement.
    """
    if rules.milestone_escalate_before_days is None:
        return []
    out: list[Finding] = []
    for row in milestones:
        if row.target_date is None or row.status in ("ACHIEVED", "CANCELLED"):
            continue
        gap = (row.target_date - today).days
        if gap < 0 or gap > rules.milestone_escalate_before_days:
            continue
        at_risk = [t for t in plan.tasks
                   if t.open and int(t.milestone_id or 0) == int(row.id)
                   and (control.days_overdue(t, today) or t.blocked)]
        if not at_risk:
            continue
        rung = first_above(project, row, None)
        if not rung:
            continue
        out.append(Finding(
            MILESTONE_AT_RISK, rung, ENTITY_MILESTONE, int(row.id), row.code,
            f"{row.target_date}:{len(at_risk)}",
            f"{row.name} is due in {gap} day{'' if gap == 1 else 's'} and "
            f"{len(at_risk)} task{'' if len(at_risk) == 1 else 's'} under it "
            + ("is" if len(at_risk) == 1 else "are")
            + " already overdue or blocked.",
            owner_id=int(row.owner_id) if row.owner_id else None))
    return out


def _milestone_of(by_id: dict[int, Any], task: Any) -> Any:
    found = getattr(task, "milestone_id", None)
    return by_id.get(int(found)) if found else None


def _blocked_for(task: Any, today: date) -> int:
    """How long a task has been blocked.

    Measured from the last update, because that is when somebody last said
    anything about it — a task blocked and then updated daily is being worked
    on, and one blocked in silence is the case this exists for. With no
    update at all, the block is treated as new rather than as ancient: an
    escalation on the strength of a missing timestamp would fire on import
    day for every blocked row in the workbook.
    """
    last = getattr(task, "last_update_at", None)
    if last is None:
        return 0
    return max(0, (today - last.date()).days)


__all__ = [
    "ACTIONS", "CRITICAL_PATH", "ESCALATED", "ESCALATED_BLOCKED",
    "ESCALATION_VERSION", "Finding", "MANAGER", "MILESTONE",
    "MILESTONE_AT_RISK", "OWN", "PROJECT", "Rung", "SPONSOR",
    "SPONSOR_ALERT", "TITLES", "TRIGGERS", "at_level", "bucket", "findings",
    "first_above", "ladder",
]
