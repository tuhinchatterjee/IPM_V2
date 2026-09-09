"""The demonstration has to keep demonstrating.

These do not re-seed anything — they check the four programmes as they stand,
so a change to the health rules or the chase rules that would quietly turn the
demonstration into four green projects with nothing to say fails here rather
than in front of somebody.

Skipped, not failed, when the portfolio has not been seeded: a developer who
has never run the seed should not see red.

They DO re-anchor the dates first, and that is not the same thing as re-seeding
--------------------------------------------------------------------------
Every date in the portfolio is an offset from the day the seed ran, so a
sign-off due in three days is due in two the next morning and the reminder
threshold assertion below goes red on the calendar rather than on a change.
This file went green at 23:09 UTC and red at 00:0x with nothing in the tree
touched between the two runs.

The fixture calls `planner.demo.apply`, which moves only the scheduling fields
and only on projects CreditProbe seeded. It creates nothing, deletes nothing,
and preserves progress, status, owners, narrative, RAID and history — so what
these tests then check is the demonstration as it is supposed to stand today,
rather than as it stood on whatever day somebody last ran the seed. Not one
assertion below was weakened to make that work; the dates were made honest
instead.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from backend.models.planner import PlannerProject, PlannerTask
from backend.planner import control, monitor
from backend.planner import query as pq
from backend.planner import schedule as sch
from tests.conftest import database_available

CODES = ("RET-IFRS9", "RET-SCORECARD", "RET-COLLECTIONS", "RET-DATA-REM")


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


@pytest.fixture(scope="module")
def portfolio():
    from backend.db.engine import get_session
    from backend.planner import demo

    with get_session() as session:
        found = {c: int(i) for c, i in session.execute(
            select(PlannerProject.code, PlannerProject.id)
            .where(PlannerProject.code.in_(CODES))).all()}
    if len(found) < len(CODES):
        pytest.skip("run scripts/seed_retail_portfolio.py to check the demo")

    # Roll the dates to today before reading anything. Idempotent — on a
    # portfolio seeded this morning the shift is zero and nothing is written —
    # and it moves dates only, so every other property these tests assert is
    # the one the seed produced. A date a person moved by hand is held back,
    # which is also the right answer here: if somebody has taken the sign-off
    # out of its reminder window deliberately, this file should say so.
    with get_session() as session:
        demo.apply(session, origin=demo.RETAIL_DEMO)
        session.commit()
    return found


@pytest.fixture()
def session():
    from backend.db.engine import get_session

    with get_session() as s:
        yield s


def test_the_portfolio_is_not_all_one_colour(session, portfolio):
    """Four green projects demonstrate a table, not a planner."""
    today = date.today()
    colours = {}
    for code, pid in portfolio.items():
        plan = pq.plan_of(session, pid)
        colours[code] = control.health(plan, today).status
    assert len(set(colours.values())) >= 3, colours
    assert "RED" in colours.values()
    assert "GREEN" in colours.values()


def test_every_colour_carries_a_reason(session, portfolio):
    today = date.today()
    for code, pid in portfolio.items():
        verdict = control.health(pq.plan_of(session, pid), today)
        assert verdict.reason, f"{code} is {verdict.status} for no stated reason"


def test_the_awkward_states_are_all_present(session, portfolio):
    """Complete, in progress, overdue, blocked, stale and in review."""
    today = date.today()
    states = {"completed": 0, "in_progress": 0, "overdue": 0,
              "blocked": 0, "stale": 0, "in_review": 0}
    for pid in portfolio.values():
        plan = pq.plan_of(session, pid)
        for task in plan.tasks:
            if task.status == "COMPLETED":
                states["completed"] += 1
            if task.status == "IN_PROGRESS":
                states["in_progress"] += 1
            if task.status == "IN_REVIEW":
                states["in_review"] += 1
            if task.blocked:
                states["blocked"] += 1
            if control.days_overdue(task, today):
                states["overdue"] += 1
            if control.is_stale(task, today, window=plan.stale_after_days):
                states["stale"] += 1
    for name, count in states.items():
        assert count > 0, f"the demonstration has nothing {name}"


def test_the_overlay_scenario_is_set_up_to_fire(session, portfolio):
    """T-503 must be due inside a reminder threshold, at low progress, and
    owned by somebody who is not the project manager."""
    pid = portfolio["RET-IFRS9"]
    task = session.execute(
        select(PlannerTask).where(PlannerTask.project_id == pid,
                                  PlannerTask.code == "T-503")).scalar_one()
    project = session.get(PlannerProject, pid)
    gap = (task.due_date - date.today()).days
    assert gap in tuple(project.reminder_days or (7, 3, 1, 0)), (
        f"T-503 is due in {gap} days, which is not a reminder threshold, so "
        "the demonstration's reminder would not fire on its own")
    assert task.percent_complete <= 50
    assert task.owner_id != project.manager_id, (
        "the scenario needs the owner and the manager to be different people")


def test_the_scenario_task_is_on_the_calculated_critical_path(session,
                                                              portfolio):
    """A reminder about something with three weeks of float is a reminder
    nobody needed."""
    pid = portfolio["RET-IFRS9"]
    project = session.get(PlannerProject, pid)
    found = sch.compute(pq.plan_of(session, pid),
                        project_start=project.start_date)
    assert found.computed, found.cannot_because
    assert "T-503" in found.critical_path


def test_a_sweep_over_the_demonstration_says_something(session, portfolio):
    outcome = monitor.sweep(session, project_ids=list(portfolio.values()),
                            send=False)
    triggers = outcome.by_trigger()
    assert outcome.suppressed > 5, "the demonstration produces no reminders"
    for wanted in ("overdue", "due", "blocked"):
        assert triggers.get(wanted), f"nothing would produce a {wanted} reminder"
    for message in outcome.messages:
        assert message.action, f"{message.trigger} tells nobody what to do"


def test_the_critical_path_calculates_on_every_programme(session, portfolio):
    for code, pid in portfolio.items():
        project = session.get(PlannerProject, pid)
        found = sch.compute(pq.plan_of(session, pid),
                            project_start=project.start_date)
        assert found.computed, f"{code}: {found.cannot_because}"
        assert found.critical_path, f"{code} has no critical path"


def test_the_access_levels_are_actually_varied(session, portfolio):
    """A demonstration where everybody is an owner proves nothing about
    permissions."""
    from backend.models.planner import PlannerParticipant

    levels = set(session.execute(
        select(PlannerParticipant.access)
        .where(PlannerParticipant.project_id.in_(portfolio.values()))
    ).scalars())
    assert {"OWNER", "EDITOR", "CONTRIBUTOR", "VIEWER"} <= levels, levels
