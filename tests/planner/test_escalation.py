"""The ladder, the modes, and the promise that nobody is told twice.

Four claims are under test, and only one of them is about a rule firing.

**The modes are real.** Light, Standard and Critical must produce genuinely
different behaviour on the SAME project in the SAME state, or the question
"how do you want the Agentic AI to work?" is a label on a screen. Every test
below that names a mode compares it against another mode on identical data.

**The ladder is walked, not guessed.** task → milestone → project → manager →
sponsor, skipping every rung nobody was named on, and never landing on the
owner — who already had the reminder.

**Nobody hears twice.** Not within one sweep (one message per person per
thing, however many rungs they occupy), and not across sweeps (the same
situation on the same day is one message, whatever the sweep schedule).

**Silence that continues is a different fact each cadence.** A project that
chases every three days escalates on day 3, 6 and 9 — not daily, and not once
ever.

These run against constructed plans rather than the database, because the
question is what the rules decide. The HTTP and browser layers are proven
elsewhere; a rule tested through four layers is a rule whose failure could be
in any of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import pytest

from backend.planner import control
from backend.planner import escalation as esc
from backend.planner import policy as pol

TODAY = date(2026, 9, 6)

OWNER = 1
TASK_ESCALATION = 2
MILESTONE_ESCALATION = 3
PROJECT_ESCALATION = 4
MANAGER = 5
SPONSOR = 6


@dataclass
class FakeProject:
    id: int = 100
    code: str = "DEMO"
    name: str = "Demo"
    escalation_id: int | None = PROJECT_ESCALATION
    manager_id: int | None = MANAGER
    sponsor_id: int | None = SPONSOR
    agentic_mode: str = pol.MODE_STANDARD
    agentic_policy: dict = field(default_factory=dict)
    reminder_days: list | None = None
    stale_after_days: int | None = None


@dataclass
class FakeMilestone:
    id: int = 10
    code: str = "M01"
    name: str = "Data Foundation"
    owner_id: int | None = OWNER
    escalation_id: int | None = MILESTONE_ESCALATION
    target_date: date | None = None
    status: str = "PENDING"


def _task(*, code="M01-T01", days_late=0, blocked=False, quiet_days=0,
          owner=OWNER, escalation=None, milestone=10,
          critical=False) -> control.TaskView:
    due = TODAY - timedelta(days=days_late) if days_late else None
    return control.TaskView(
        id=int(code[-1]) if code[-1].isdigit() else 1, code=code,
        title=code, status="IN_PROGRESS", percent_complete=40,
        due_date=due, owner_id=owner, blocked=blocked,
        blocker_reason="waiting on Finance" if blocked else "",
        # Anchored to TODAY, not to the wall clock. The sweep is run with
        # `today=TODAY`, a fixed date, so measuring quiet_days from
        # datetime.now() made the two agree only on 2026-09-06 and drift
        # by a day every day after it — a task three days quiet read as
        # zero days quiet, and the blocked-escalation cases stopped
        # firing. Same intent, no calendar coupling.
        last_update_at=datetime.combine(
            TODAY - timedelta(days=quiet_days), time.min, tzinfo=UTC),
        milestone_id=milestone, critical=critical)


def _plan(tasks) -> control.Plan:
    return control.Plan(project_id=100, tasks=list(tasks))


def _findings(mode=pol.MODE_STANDARD, *, tasks=None, milestones=None,
              project=None, policy_document=None, critical=frozenset()):
    project = project or FakeProject(agentic_mode=mode,
                                     agentic_policy=policy_document or {})
    stones = milestones if milestones is not None else [FakeMilestone()]
    agentic = pol.resolve(mode, policy_document)
    return esc.findings(project, _plan(tasks or []), stones, TODAY,
                        agentic=agentic, critical_codes=critical)


# ------------------------------------------------------------- the ladder


def test_the_ladder_is_walked_in_order():
    rungs = esc.ladder(FakeProject(), FakeMilestone(),
                       _task(escalation=TASK_ESCALATION))
    # The task's own escalation owner is not set on the TaskView, so the
    # first rung available is the milestone's.
    assert [r.level for r in rungs] == [esc.MILESTONE, esc.PROJECT,
                                        esc.MANAGER, esc.SPONSOR]
    assert [r.user_id for r in rungs] == [MILESTONE_ESCALATION,
                                          PROJECT_ESCALATION, MANAGER,
                                          SPONSOR]


def test_an_unnamed_rung_is_skipped_rather_than_invented():
    """A milestone with no escalation owner escalates to the project's.

    Nothing is sent to somebody the software picked: an escalation to a
    person nobody named teaches everybody that escalations mean nothing.
    """
    stone = FakeMilestone(escalation_id=None)
    project = FakeProject(escalation_id=None)
    rungs = esc.ladder(project, stone, _task())
    assert [r.level for r in rungs] == [esc.MANAGER, esc.SPONSOR]


def test_a_project_that_names_nobody_escalates_to_nobody():
    project = FakeProject(escalation_id=None, manager_id=None,
                          sponsor_id=None)
    assert esc.ladder(project, FakeMilestone(escalation_id=None),
                      _task()) == []
    assert esc.first_above(project, FakeMilestone(escalation_id=None),
                           _task()) is None


def test_a_task_never_escalates_to_its_own_owner():
    """On a small project one person is the owner, the manager and the
    milestone's escalation contact. They get the reminder once, not four
    times under a different heading."""
    project = FakeProject(escalation_id=OWNER, manager_id=OWNER,
                          sponsor_id=OWNER)
    stone = FakeMilestone(escalation_id=OWNER)
    assert esc.ladder(project, stone, _task(owner=OWNER)) == []


def test_the_message_says_why_it_reached_this_person():
    rung = esc.first_above(FakeProject(), FakeMilestone(), _task())
    assert rung is not None
    assert rung.because == "you are the escalation owner for M01"


# --------------------------------------------------- the modes differ


def test_light_does_not_escalate_on_lateness_at_all():
    """Light is a genuine choice, not a smaller number.

    A project whose manager chose Light has said "chase gently and do not
    escalate a late task" — so a task ten days overdue reaches nobody above
    the owner. The same task under Standard does.
    """
    ten_days_late = [_task(days_late=10)]
    light = _findings(pol.MODE_LIGHT, tasks=ten_days_late)
    standard = _findings(pol.MODE_STANDARD, tasks=ten_days_late)

    assert [f.trigger for f in light if f.trigger == esc.ESCALATED] == []
    assert any(f.trigger == esc.ESCALATED for f in standard)


def test_critical_escalates_after_one_day_and_standard_does_not():
    one_day_late = [_task(days_late=1)]
    assert not [f for f in _findings(pol.MODE_STANDARD, tasks=one_day_late)
                if f.trigger == esc.ESCALATED]
    assert [f for f in _findings(pol.MODE_CRITICAL, tasks=one_day_late)
            if f.trigger == esc.ESCALATED]


def test_the_sponsor_hears_sooner_under_critical():
    """Three days under Critical, five under Standard, never under Light."""
    four_days_late = [_task(days_late=4)]

    def sponsor(mode):
        return [f for f in _findings(mode, tasks=four_days_late)
                if f.rung.level == esc.SPONSOR]

    assert sponsor(pol.MODE_CRITICAL)
    assert not sponsor(pol.MODE_STANDARD)
    assert not sponsor(pol.MODE_LIGHT)


def test_light_waits_longer_before_escalating_a_blocked_task():
    """Light escalates a block after five days; Critical after one."""
    three_days_blocked = [_task(blocked=True, quiet_days=3)]

    def blocked(mode):
        return [f for f in _findings(mode, tasks=three_days_blocked)
                if f.trigger == esc.ESCALATED_BLOCKED]

    assert blocked(pol.MODE_CRITICAL)
    assert blocked(pol.MODE_STANDARD)
    assert not blocked(pol.MODE_LIGHT)


def test_light_does_not_page_the_manager_about_the_critical_path():
    late_and_critical = [_task(days_late=4, critical=True)]
    codes = frozenset({"M01-T01"})

    def paged(mode):
        return [f for f in _findings(mode, tasks=late_and_critical,
                                     critical=codes)
                if f.trigger == esc.CRITICAL_PATH]

    assert paged(pol.MODE_CRITICAL)
    assert paged(pol.MODE_STANDARD)
    assert not paged(pol.MODE_LIGHT)


def test_a_custom_policy_sets_its_own_threshold():
    """A custom threshold is a real setting, not a preset with a new name.

    Standard escalates after two days, so the case that distinguishes Custom
    is a task ONE day late: Standard leaves it alone and a project that asked
    for one day does not.
    """
    one_day_late = [_task(days_late=1)]
    assert not [f for f in _findings(pol.MODE_STANDARD, tasks=one_day_late)
                if f.trigger == esc.ESCALATED]
    found = _findings(pol.MODE_CUSTOM, tasks=one_day_late,
                      policy_document={"escalate_after_days": 1})
    assert [f for f in found if f.trigger == esc.ESCALATED]


@pytest.mark.parametrize("mode,expected", [
    (pol.MODE_LIGHT, False), (pol.MODE_STANDARD, True),
    (pol.MODE_CRITICAL, True),
])
def test_only_some_modes_remind_reviewers(mode, expected):
    assert pol.resolve(mode, None).escalation.remind_reviewers is expected


# ------------------------------------------------- no notification storm


def test_one_person_on_four_rungs_gets_one_message():
    """§27. The storm this exists to prevent.

    On a small project the same person is the milestone's escalation owner,
    the project's, the manager AND the sponsor. Four rules fire; one message
    is sent, and it is the most serious of them.
    """
    everyone = FakeProject(escalation_id=9, manager_id=9, sponsor_id=9)
    stone = FakeMilestone(escalation_id=9)
    found = _findings(pol.MODE_CRITICAL, project=everyone, milestones=[stone],
                      tasks=[_task(days_late=10, critical=True)],
                      critical=frozenset({"M01-T01"}))
    for_nine = [f for f in found if f.rung.user_id == 9
                and f.entity_type == "TASK"]
    assert len(for_nine) == 1
    # The sponsor alert outranks the plain escalation and the critical-path
    # notice: it says the most about how long this has gone on.
    assert for_nine[0].trigger == esc.SPONSOR_ALERT


def test_different_people_on_different_rungs_each_hear_once():
    found = _findings(pol.MODE_CRITICAL,
                      tasks=[_task(days_late=10, critical=True)],
                      critical=frozenset({"M01-T01"}))
    pairs = [(f.entity_type, f.entity_id, f.rung.user_id) for f in found]
    assert len(pairs) == len(set(pairs))
    # The ladder reached three different people about one task, each once.
    assert len({f.rung.user_id for f in found if f.entity_type == "TASK"}) >= 2


def test_the_same_situation_twice_produces_the_same_fingerprint():
    """Two sweeps on one day is one message; the monitor's unique index does
    the suppressing, and it can only do so if `about` is stable."""
    late = [_task(days_late=4)]
    first = _findings(pol.MODE_CRITICAL, tasks=late)
    again = _findings(pol.MODE_CRITICAL, tasks=late)
    assert [f.about for f in first] == [f.about for f in again]


# ------------------------------------------------------- the chase cadence


def test_a_light_project_escalates_every_third_day_not_daily():
    """Cadence lives in the fingerprint, so a missed sweep does not skip a
    rung and two sweeps in an hour do not send two messages."""
    every_three = [esc.bucket(day, 3) for day in range(0, 10)]
    assert every_three == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3]
    # Day 4 and day 5 are the same bucket: the second is suppressed.
    assert esc.bucket(4, 3) == esc.bucket(5, 3)
    # A sweep that never ran on day 6 still produces bucket 2 on day 7.
    assert esc.bucket(7, 3) == 2


def test_a_critical_project_escalates_every_day():
    assert [esc.bucket(day, 1) for day in range(0, 4)] == [0, 1, 2, 3]


def test_the_cadence_reaches_the_fingerprint():
    """Different days, different `about` — under Critical, daily."""
    day_four = _findings(pol.MODE_CRITICAL, tasks=[_task(days_late=4)])
    day_five = _findings(pol.MODE_CRITICAL, tasks=[_task(days_late=5)])
    assert {f.about for f in day_four} != {f.about for f in day_five}


# ----------------------------------------------------- milestones at risk


def test_a_milestone_is_escalated_before_its_date_not_after():
    """The point of a horizon is to leave time to act."""
    soon = FakeMilestone(target_date=TODAY + timedelta(days=3))
    found = _findings(pol.MODE_CRITICAL, milestones=[soon],
                      tasks=[_task(days_late=2)])
    at_risk = [f for f in found if f.trigger == esc.MILESTONE_AT_RISK]
    assert at_risk
    assert at_risk[0].rung.user_id == MILESTONE_ESCALATION
    assert "3 days" in at_risk[0].sentence


def test_a_milestone_with_nothing_late_under_it_is_not_escalated():
    """"At risk" is arithmetic, not pessimism."""
    soon = FakeMilestone(target_date=TODAY + timedelta(days=3))
    found = _findings(pol.MODE_CRITICAL, milestones=[soon],
                      tasks=[_task(days_late=0)])
    assert not [f for f in found if f.trigger == esc.MILESTONE_AT_RISK]


def test_light_never_escalates_a_milestone_early():
    soon = FakeMilestone(target_date=TODAY + timedelta(days=3))
    found = _findings(pol.MODE_LIGHT, milestones=[soon],
                      tasks=[_task(days_late=2)])
    assert not [f for f in found if f.trigger == esc.MILESTONE_AT_RISK]


def test_a_blocked_task_with_no_update_is_not_treated_as_ancient():
    """A workbook import arrives with blocked rows and no timestamps.

    Escalating on the strength of a missing value would page the sponsor
    about every blocked row on import day.
    """
    never = control.TaskView(
        id=1, code="M01-T01", title="t", status="IN_PROGRESS",
        percent_complete=0, owner_id=OWNER, blocked=True,
        blocker_reason="unknown", last_update_at=None, milestone_id=10)
    found = _findings(pol.MODE_CRITICAL, tasks=[never])
    assert not [f for f in found if f.trigger == esc.ESCALATED_BLOCKED]
