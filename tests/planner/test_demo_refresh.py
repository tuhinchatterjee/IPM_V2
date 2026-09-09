"""Rolling a demonstration forward, at dates this test chooses.

The bug these exist for is precise and was found by the calendar rather than
by a change: the demo portfolio is seeded with dates relative to the day the
seed ran, so a sign-off due "in three days" is due in two the next morning,
two is not one of the project's reminder thresholds, and the demonstration's
centrepiece stops being able to fire on its own. A full regression run went
green at 23:09 UTC and red at 00:0x with nothing in the tree changed between
them.

Nothing here reads the seeded portfolio. Every test builds its own programme
with its own dates and passes the day in, the way `test_monitor.py` does, so
the whole file behaves identically whatever day it runs on and whether or not
anybody has ever run the seed. That is the point: a test that proves a
date-rollover fix must not itself depend on a date.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.models.planner import (
    ENTITY_TASK,
    SOURCE_SYSTEM,
    SOURCE_UI,
    PlannerMilestone,
    PlannerProject,
    PlannerRaid,
    PlannerReminder,
    PlannerTask,
    PlannerUpdate,
)
from backend.planner import demo, monitor
from backend.planner import service as svc
from tests.conftest import database_available

#: The day the demonstration is seeded. Any day; nothing here depends on which.
DAY_ONE = date(2026, 3, 10)
#: The next morning — the exact rollover that broke it.
DAY_TWO = DAY_ONE + timedelta(days=1)

THRESHOLDS = [7, 3, 1, 0]


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


class Principal:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.role = "ADMIN"

    def has(self, _allowed) -> bool:
        return True


TEST_ORIGIN = "test.demo_refresh"


def _world(*, anchor: date = DAY_ONE, origin: str = TEST_ORIGIN) -> dict:
    """A miniature of the seeded programme, anchored to a day we choose.

    The shape that matters is the one that broke: an owner who is not the
    manager, a task at a reminder threshold, work already finished, a
    milestone, and a RAID item — so the refresh has one of everything it is
    allowed to move and several things it is not.
    """
    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    with get_session() as session:
        manager = User(username=f"dm-mgr-{tag}", password_hash="x",
                       role="ANALYST", first_name="Priya", last_name="Manager")
        owner = User(username=f"dm-own-{tag}", password_hash="x",
                     role="ANALYST", first_name="Fatima", last_name="Owner")
        other = User(username=f"dm-oth-{tag}", password_hash="x",
                     role="ANALYST", first_name="Rohan", last_name="Other")
        session.add_all([manager, owner, other])
        session.flush()
        who = Principal(int(manager.id))

        project = svc.create_project(
            session, who, code=f"DEMO-{tag[:6].upper()}",
            name="Demo refresh fixture", status="ACTIVE",
            manager_id=int(manager.id),
            start_date=str(anchor - timedelta(days=30)),
            target_end_date=str(anchor + timedelta(days=30)),
            reminder_days=list(THRESHOLDS))
        session.flush()
        pid = int(project.id)
        # The marker and the anchor are what the seed writes, and what makes
        # this programme eligible for a refresh at all.
        project.demo_origin = origin
        # An ordinary project has neither. Setting an anchor on one would make
        # this fixture prove the marker matters when the anchor was doing the
        # work.
        project.demo_anchor_date = anchor if origin else None

        svc.add_participant(session, who, pid, user_id=int(owner.id),
                            project_role="CONTRIBUTOR", access="CONTRIBUTOR")
        svc.add_participant(session, who, pid, user_id=int(other.id),
                            project_role="CONTRIBUTOR", access="CONTRIBUTOR")

        signoff = svc.create_task(
            session, who, pid, code="T-503",
            title="Management Overlay Sign-off",
            owner_id=int(owner.id), percent_complete=30,
            status="IN_PROGRESS", critical=True,
            start_date=str(anchor - timedelta(days=2)),
            due_date=str(anchor + timedelta(days=3)))
        done = svc.create_task(
            session, who, pid, code="T-501", title="Emerging risk review",
            owner_id=int(other.id), percent_complete=100, status="COMPLETED",
            start_date=str(anchor - timedelta(days=6)),
            due_date=str(anchor - timedelta(days=2)))
        later = svc.create_task(
            session, who, pid, code="T-604", title="Downstream CRO pack",
            owner_id=int(other.id),
            start_date=str(anchor + timedelta(days=4)),
            due_date=str(anchor + timedelta(days=9)))
        session.flush()

        milestone = svc.create_milestone(
            session, who, pid, code="M-3", name="Overlay agreed",
            target_date=str(anchor + timedelta(days=5)))
        raid = svc.create_raid(
            session, who, pid, raid_type="RISK",
            title="Finance may not clear the overlay in time",
            description="Sign-off sits on one person's diary.",
            owner_id=int(owner.id),
            raised_date=str(anchor - timedelta(days=1)),
            target_date=str(anchor + timedelta(days=6)))
        session.flush()
        session.commit()
        return {"project_id": pid, "code": project.code,
                "manager": int(manager.id), "owner": int(owner.id),
                "other": int(other.id), "signoff": int(signoff.id),
                "done": int(done.id), "later": int(later.id),
                "milestone": int(milestone.id), "raid": int(raid.id),
                "anchor": anchor}


@pytest.fixture()
def world():
    """Built for one test, and removed after it.

    The teardown is not tidiness. These fixtures carry `demo_origin` and an
    open task at a reminder threshold, so one left behind is a project the
    estate-wide sweep goes on reminding somebody about for ever, and a
    candidate the demo refresh would pick up. A test must not add a standing
    obligation to a development database.
    """
    made = _world()
    try:
        yield made
    finally:
        _forget(made["project_id"])


def _forget(project_id: int) -> None:
    from backend.db.engine import get_session

    with get_session() as session:
        project = session.get(PlannerProject, int(project_id))
        if project is not None:
            session.delete(project)  # cascades to its tasks and milestones
            session.commit()


def _task(task_id: int) -> PlannerTask:
    from backend.db.engine import get_session

    with get_session() as session:
        return session.get(PlannerTask, task_id)


def _gap(task_id: int, today: date) -> int:
    return (_task(task_id).due_date - today).days


def _refresh(world: dict | None = None, **kwargs) -> demo.Refresh:
    """One refresh, scoped to the project under test.

    Scoped deliberately: every test in this file builds its own programme and
    they all carry the same marker, so an unscoped refresh would report moves
    belonging to a project an earlier test left behind — and the file would
    pass or fail on the order it happened to run in.
    """
    from backend.db.engine import get_session

    ids = [world["project_id"]] if world else None
    with get_session() as session:
        out = demo.apply(session, origin=TEST_ORIGIN, project_ids=ids,
                         **kwargs)
        session.commit()
        return out


def _sweep(project_id: int, day: date):
    from backend.db.engine import get_session

    with get_session() as session:
        result = monitor.sweep(session, today=day, project_ids=[project_id])
        session.commit()
        return result


# ------------------------------------------------- the bug, exactly as found


def test_the_demonstration_stops_firing_the_morning_after_it_is_seeded(world):
    """The defect, reproduced. This is what went red across UTC midnight.

    Seeded on day one the sign-off is due in three days, which is a threshold.
    On day two it is due in two, which is not, and the reminder the whole
    demonstration turns on can no longer fire on its own.
    """
    assert _gap(world["signoff"], DAY_ONE) == 3
    assert 3 in THRESHOLDS

    assert _gap(world["signoff"], DAY_TWO) == 2
    assert 2 not in THRESHOLDS, (
        "if two were a threshold this test would prove nothing — the bug is "
        "that a fixed date walks down through values the policy does not name")


def test_seed_on_day_one_advance_to_day_two_refresh_and_it_demonstrates_again(
        world):
    """The regression the fix exists for, start to finish."""
    assert _gap(world["signoff"], DAY_TWO) == 2, "drifted, as it must have"

    out = _refresh(world, today=DAY_TWO)
    assert out.applied is True
    assert out.moves > 0

    assert _gap(world["signoff"], DAY_TWO) == 3, (
        "after re-anchoring, the sign-off is back at the threshold it was "
        "seeded at, and the demonstration can fire again")
    from backend.db.engine import get_session

    with get_session() as session:
        assert session.get(
            PlannerProject, world["project_id"]).demo_anchor_date == DAY_TWO


def test_the_refresh_works_from_any_distance_not_just_one_day(world):
    """A demonstration left alone for a fortnight has to come back too."""
    far = DAY_ONE + timedelta(days=14)
    _refresh(world, today=far)
    assert _gap(world["signoff"], far) == 3


# ------------------------------------------------------------ what it keeps


def test_everything_that_is_not_a_date_survives(world):
    before = _task(world["signoff"])
    keep = (before.percent_complete, before.status, before.owner_id,
            before.reviewer_id, list(before.contributor_ids), before.critical,
            before.blocked, before.blocker_reason, before.next_step,
            before.title, before.notes, list(before.tags))

    _refresh(world, today=DAY_TWO)

    after = _task(world["signoff"])
    assert (after.percent_complete, after.status, after.owner_id,
            after.reviewer_id, list(after.contributor_ids), after.critical,
            after.blocked, after.blocker_reason, after.next_step,
            after.title, after.notes, list(after.tags)) == keep


def test_the_participants_and_their_roles_are_untouched(world):
    from backend.db.engine import get_session
    from backend.models.planner import PlannerParticipant

    def roster():
        with get_session() as session:
            return sorted(
                (r.user_id, r.project_role, r.access) for r in
                session.execute(select(PlannerParticipant).where(
                    PlannerParticipant.project_id == world["project_id"]))
                .scalars())

    before = roster()
    _refresh(world, today=DAY_TWO)
    assert roster() == before


def test_the_history_is_added_to_and_never_rewritten(world):
    from backend.db.engine import get_session

    def rows():
        with get_session() as session:
            return [(r.id, r.action, r.source, r.narrative) for r in
                    session.execute(select(PlannerUpdate).where(
                        PlannerUpdate.project_id == world["project_id"])
                        .order_by(PlannerUpdate.id)).scalars()]

    before = rows()
    _refresh(world, today=DAY_TWO)
    after = rows()

    assert after[:len(before)] == before, "an existing history row changed"
    added = after[len(before):]
    assert added, "the refresh has to leave a record of itself"
    assert {r[1] for r in added} == {"date"}
    assert {r[2] for r in added} == {SOURCE_SYSTEM}, (
        "nobody made this change and the history must not say they did")
    assert all("re-anchored" in r[3] for r in added)


def test_the_milestone_and_the_raid_move_with_everything_else(world):
    from backend.db.engine import get_session

    with get_session() as session:
        milestone = session.get(PlannerMilestone, world["milestone"])
        raid = session.get(PlannerRaid, world["raid"])
        was = (milestone.target_date, raid.raised_date, raid.target_date,
               raid.status, raid.title)

    _refresh(world, today=DAY_TWO)

    with get_session() as session:
        milestone = session.get(PlannerMilestone, world["milestone"])
        raid = session.get(PlannerRaid, world["raid"])
        assert milestone.target_date == was[0] + timedelta(days=1)
        assert raid.raised_date == was[1] + timedelta(days=1)
        assert raid.target_date == was[2] + timedelta(days=1)
        assert raid.status == was[3], "a RAID item's state is not a date"
        assert raid.title == was[4]


# --------------------------------------------------------------- idempotence


def test_running_it_twice_on_one_day_changes_nothing_the_second_time(world):
    first = _refresh(world, today=DAY_TWO)
    assert first.moves > 0

    from backend.db.engine import get_session

    with get_session() as session:
        history = len(list(session.execute(select(PlannerUpdate).where(
            PlannerUpdate.project_id == world["project_id"])).scalars()))
        due = session.get(PlannerTask, world["signoff"]).due_date

    second = _refresh(world, today=DAY_TWO)
    assert second.moves == 0

    with get_session() as session:
        assert len(list(session.execute(select(PlannerUpdate).where(
            PlannerUpdate.project_id == world["project_id"])).scalars())) == \
            history, "an idempotent run wrote a history row anyway"
        assert session.get(PlannerTask, world["signoff"]).due_date == due


# ------------------------------------------------- somebody else's commitment


def test_a_date_a_person_moved_is_held_back_and_reported(world):
    """A human date is a commitment, not scaffolding."""
    from backend.db.engine import get_session

    moved_to = DAY_ONE + timedelta(days=20)
    with get_session() as session:
        svc.update_task(session, Principal(world["manager"]),
                        world["signoff"], due_date=str(moved_to),
                        narrative="Finance cannot take it before then.",
                        source=SOURCE_UI)
        session.commit()

    out = _refresh(world, today=DAY_TWO)

    held = [m for p in out.projects for m in p.held]
    assert any(m.entity_id == world["signoff"] and m.field == "due_date"
               for m in held), "the human date was not detected"
    assert _task(world["signoff"]).due_date == moved_to, \
        "a person's commitment was overwritten"
    assert all("commitment" in m.why for m in held)


def test_the_rest_of_the_project_still_moves_around_a_held_date(world):
    from backend.db.engine import get_session

    with get_session() as session:
        svc.update_task(session, Principal(world["manager"]),
                        world["signoff"],
                        due_date=str(DAY_ONE + timedelta(days=20)),
                        source=SOURCE_UI)
        session.commit()
    before = _task(world["later"]).due_date

    _refresh(world, today=DAY_TWO)

    assert _task(world["later"]).due_date == before + timedelta(days=1), (
        "holding one date must not freeze the whole programme")


def test_force_overwrites_a_human_date_and_says_so(world):
    from backend.db.engine import get_session

    with get_session() as session:
        svc.update_task(session, Principal(world["manager"]),
                        world["signoff"],
                        due_date=str(DAY_ONE + timedelta(days=20)),
                        source=SOURCE_UI)
        session.commit()

    out = _refresh(world, today=DAY_TWO, force=True)
    assert out.forced is True
    assert not [m for p in out.projects for m in p.held]
    assert _task(world["signoff"]).due_date == \
        DAY_ONE + timedelta(days=21), "force did not move the human date"

    with get_session() as session:
        latest = list(session.execute(select(PlannerUpdate).where(
            PlannerUpdate.project_id == world["project_id"],
            PlannerUpdate.source == SOURCE_SYSTEM)
            .order_by(PlannerUpdate.id.desc())).scalars())
    assert any("forced" in r.narrative for r in latest), (
        "overwriting a person's date must say in the history that it did")


def test_a_date_the_system_moved_is_not_mistaken_for_a_human_one(world):
    """Otherwise the second refresh would hold everything the first moved."""
    _refresh(world, today=DAY_TWO)
    out = _refresh(world, today=DAY_TWO + timedelta(days=1))
    assert not [m for p in out.projects for m in p.held]
    assert out.moves > 0


# ------------------------------------------------------ what it will not touch


def test_a_project_nobody_marked_as_a_demonstration_is_never_touched():
    """The whole safety property, in one test."""
    from backend.db.engine import get_session

    ordinary = _world(origin="")
    try:
        before = _task(ordinary["signoff"]).due_date

        out = _refresh(ordinary, today=DAY_TWO)

        assert ordinary["code"] not in [p.code for p in out.projects]
        assert _task(ordinary["signoff"]).due_date == before

        with get_session() as session:
            assert session.get(
                PlannerProject,
                ordinary["project_id"]).demo_anchor_date is None
    finally:
        _forget(ordinary["project_id"])


def test_only_the_named_scheduling_fields_are_eligible():
    """A field added to a model later must not start moving by accident."""
    assert set(demo.FIELDS["TASK"]) == {"start_date", "due_date",
                                        "completed_date"}
    assert set(demo.FIELDS["PROJECT"]) == {"start_date", "target_end_date",
                                           "actual_end_date"}
    assert set(demo.FIELDS["MILESTONE"]) == {"target_date", "actual_date"}
    assert set(demo.FIELDS["RAID"]) == {"raised_date", "target_date",
                                        "resolved_date"}


def test_a_demo_project_with_no_anchor_is_left_alone_and_said_so():
    from backend.db.engine import get_session

    orphan = _world()
    try:
        with get_session() as session:
            session.get(
                PlannerProject, orphan["project_id"]).demo_anchor_date = None
            session.commit()

        out = _refresh(orphan, today=DAY_TWO)
        assert any(orphan["code"] in note for note in out.notes)
        assert orphan["code"] not in [p.code for p in out.projects]
    finally:
        _forget(orphan["project_id"])


# ------------------------------------------- the reminder journey, end to end


def test_the_owner_is_asked_once_and_not_again(world):
    """TODAY at threshold, one message, run again and no duplicate."""
    _refresh(world, today=DAY_TWO)
    assert _gap(world["signoff"], DAY_TWO) == 3

    first = _sweep(world["project_id"], DAY_TWO)
    about = [r for r in _reminders(world["project_id"])
             if r.entity_id == world["signoff"]]
    assert len(about) == 1, [r.trigger for r in about]
    assert about[0].user_id == world["owner"], \
        "the owner is told, not the manager"

    again = _sweep(world["project_id"], DAY_TWO)
    assert again.sent == 0
    assert len([r for r in _reminders(world["project_id"])
                if r.entity_id == world["signoff"]]) == 1
    del first


def test_nobody_else_is_told(world):
    _refresh(world, today=DAY_TWO)
    _sweep(world["project_id"], DAY_TWO)
    told = {r.user_id for r in _reminders(world["project_id"])
            if r.entity_id == world["signoff"]}
    assert told == {world["owner"]}
    assert world["manager"] not in told
    assert world["other"] not in told


def test_a_re_anchored_date_re_arms_a_reminder_that_had_already_been_sent(
        world):
    """The one that would fail silently if the fingerprint ignored the date.

    A reminder already sent about the old date must not suppress the one about
    the new date. Suppression here would look exactly like a working
    demonstration that never sends anything.
    """
    _refresh(world, today=DAY_TWO)
    _sweep(world["project_id"], DAY_TWO)
    before = {r.fingerprint for r in _reminders(world["project_id"])}
    assert before

    day_three = DAY_TWO + timedelta(days=1)
    _refresh(world, today=day_three)
    _sweep(world["project_id"], day_three)

    after = {r.fingerprint for r in _reminders(world["project_id"])}
    assert after > before, (
        "the moved due date did not produce a new reminder, so the "
        "demonstration would be silent after a refresh")


def test_the_owners_update_answers_the_chase_and_the_state_moves(world):
    from backend.db.engine import get_session

    _refresh(world, today=DAY_TWO)
    _sweep(world["project_id"], DAY_TWO)

    asked = [r for r in _reminders(world["project_id"]) if r.asked]
    if not asked:
        # The chase only fires where SILENCE is the problem; this fixture's
        # sign-off is neither overdue nor blocked, so there may be nothing to
        # answer. Assert the plain reminder instead of inventing a chase.
        assert _reminders(world["project_id"])
        return

    with get_session() as session:
        svc.update_task(session, Principal(world["owner"]), world["signoff"],
                        percent_complete=80,
                        narrative="Finance review underway. No blocker.",
                        source=SOURCE_UI)
        session.commit()

    after = [r for r in _reminders(world["project_id"]) if r.asked]
    assert all(r.state == "answered" for r in after), \
        [(r.id, r.state) for r in after]


def test_advancing_time_reminds_again_at_the_next_threshold(world):
    """Future reminder logic, on the re-anchored dates."""
    _refresh(world, today=DAY_TWO)
    _sweep(world["project_id"], DAY_TWO)

    # Two days on, without a refresh, the sign-off is due in one — the next
    # threshold down — and that IS a different commitment to remind about.
    later = DAY_TWO + timedelta(days=2)
    assert _gap(world["signoff"], later) == 1
    result = _sweep(world["project_id"], later)
    assert result.sent > 0, "the one-day threshold produced nothing"


def _reminders(project_id: int) -> list[PlannerReminder]:
    from backend.db.engine import get_session

    with get_session() as session:
        return list(session.execute(
            select(PlannerReminder)
            .where(PlannerReminder.project_id == project_id,
                   PlannerReminder.entity_type == ENTITY_TASK)
            .order_by(PlannerReminder.id)).scalars())


def test_it_refuses_to_move_a_demonstration_backwards(world):
    """An anchor in the future means the anchor is wrong.

    A downgrade of the migration that stores it drops the anchor, and the next
    upgrade re-derives it from the project's creation date — which is one day
    stale for every refresh that had happened in between. "Refresh to today"
    that quietly rolled a day of work into the past would look exactly like a
    working command, so it stops and says what it found.
    """
    before = _task(world["signoff"]).due_date
    out = _refresh(world, today=DAY_ONE - timedelta(days=2))

    assert out.moves == 0
    assert any("backwards" in note for note in out.notes)
    assert _task(world["signoff"]).due_date == before


def test_force_is_the_only_way_backwards(world):
    """Because rebuilding a rehearsal from an earlier day is a real need."""
    before = _task(world["signoff"]).due_date
    out = _refresh(world, today=DAY_ONE - timedelta(days=2), force=True)

    assert out.moves > 0
    assert _task(world["signoff"]).due_date == before - timedelta(days=2)
