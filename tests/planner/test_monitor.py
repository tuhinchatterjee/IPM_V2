"""The overnight sweep, at a frozen moment.

Time is a parameter everywhere in this engine, so these tests do not mock a
clock — they pass the date in. That matters more than it sounds: the single
most common defect in a reminder system is one that fires again on every run,
and you cannot demonstrate its absence without running the same day twice.

These go through the service and the database rather than the HTTP layer,
because the sweep is a background job and has no route. The permission story
is different too: nothing here has a caller, which is exactly why every
notification is addressed by looking up participants rather than by trusting
anything passed in.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.models.planner import PlannerReminder
from backend.models.platform import Notification
from backend.planner import monitor
from backend.planner import service as svc
from tests.conftest import database_available

TODAY = date(2026, 6, 15)


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


class Principal:
    """Just enough of one. The sweep never sees a caller; the setup does."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.role = "ADMIN"

    def has(self, allowed) -> bool:
        return True


@pytest.fixture(scope="module")
def world():
    """One project with a task in every interesting state.

    Committed once and read by every test, so a test that changes something
    has to say so. The dates are all relative to TODAY, which is fixed.
    """
    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    with get_session() as session:
        alice = User(username=f"mon-alice-{tag}", password_hash="x",
                     role="ANALYST", first_name="Alice", last_name="Monitor")
        bob = User(username=f"mon-bob-{tag}", password_hash="x",
                   role="ANALYST", first_name="Bob", last_name="Monitor")
        session.add_all([alice, bob])
        session.flush()
        who = Principal(int(alice.id))

        project = svc.create_project(
            session, who, code=f"MON-{tag[:6].upper()}",
            name="Monitor fixture", status="ACTIVE",
            manager_id=int(alice.id), start_date="2026-01-05",
            target_end_date="2026-12-18")
        session.flush()
        pid = int(project.id)
        svc.add_participant(session, who, pid, user_id=int(bob.id),
                            project_role="CONTRIBUTOR", access="CONTRIBUTOR")

        made = {}
        for code, title, due, extra in (
            ("M-OVERDUE", "Overdue task", TODAY - timedelta(days=4), {}),
            ("M-DUE3", "Due in three", TODAY + timedelta(days=3), {}),
            ("M-DUE7", "Due in seven", TODAY + timedelta(days=7), {}),
            ("M-DUE5", "Due in five", TODAY + timedelta(days=5), {}),
            ("M-FAR", "Due in ninety", TODAY + timedelta(days=90), {}),
            ("M-BLOCKED", "Blocked task", TODAY + timedelta(days=20),
             {"blocked": True, "blocker_reason": "Waiting on Finance"}),
        ):
            task = svc.create_task(
                session, who, pid, code=code, title=title,
                owner_id=int(bob.id), start_date=str(TODAY - timedelta(days=30)),
                due_date=str(due), **extra)
            session.flush()
            made[code] = int(task.id)

        session.commit()
        return {"project_id": pid, "alice": int(alice.id),
                "bob": int(bob.id), "tasks": made,
                "code": project.code}


def run(project_id: int, day: date = TODAY, **kwargs):
    """One sweep, committed, so the next one sees what this one wrote."""
    from backend.db.engine import get_session

    with get_session() as session:
        result = monitor.sweep(session, today=day, project_ids=[project_id],
                               **kwargs)
        session.commit()
        return result


def reminders(project_id: int) -> list[PlannerReminder]:
    from backend.db.engine import get_session

    with get_session() as session:
        return list(session.execute(
            select(PlannerReminder)
            .where(PlannerReminder.project_id == project_id)
            .order_by(PlannerReminder.id)).scalars())


class TestWhoIsTold:
    def test_the_first_sweep_reminds_the_owner(self, world):
        result = run(world["project_id"])
        assert result.projects == 1
        assert result.sent > 0
        triggers = result.by_trigger()
        assert triggers.get(monitor.OVERDUE) == 1
        assert triggers.get(monitor.BLOCKED) == 1
        assert triggers.get(monitor.DUE) == 2, \
            "the 3-day and 7-day thresholds, and not the 5-day one"

    def test_a_task_due_on_no_threshold_is_left_alone(self, world):
        """Reminding somebody at five days when the policy says 7/3/1/0
        means the policy is decoration."""
        sent = reminders(world["project_id"])
        about = {r.entity_id for r in sent if r.trigger == monitor.DUE}
        assert world["tasks"]["M-DUE5"] not in about
        assert world["tasks"]["M-FAR"] not in about

    def test_each_task_produces_at_most_one_message(self, world):
        sent = reminders(world["project_id"])
        pairs = [(r.entity_id, r.user_id) for r in sent
                 if r.entity_type == "TASK"]
        assert len(pairs) == len(set(pairs)), \
            "the same person was told twice about the same task"

    def test_the_reminder_reaches_the_owner_not_the_manager(self, world):
        sent = [r for r in reminders(world["project_id"])
                if r.entity_type == "TASK"]
        assert {r.user_id for r in sent} == {world["bob"]}

    def test_a_notification_row_is_written_for_each(self, world):
        from backend.db.engine import get_session

        sent = reminders(world["project_id"])
        ids = [r.notification_id for r in sent]
        assert all(i is not None for i in ids)
        with get_session() as session:
            rows = list(session.execute(
                select(Notification).where(Notification.id.in_(ids))).scalars())
        assert len(rows) == len(ids)
        assert all(world["code"] in r.title for r in rows)


class TestItOnlyFiresOnce:
    def test_the_same_day_twice_sends_nothing_new(self, world):
        before = len(reminders(world["project_id"]))
        again = run(world["project_id"])
        assert again.sent == 0, [m.body for m in again.messages]
        assert again.suppressed > 0
        assert len(reminders(world["project_id"])) == before

    def test_the_next_day_does_not_repeat_a_due_reminder(self, world):
        """The 3-day reminder must not become a 2-day reminder tomorrow.

        Tomorrow the task is due in two days, which is not a threshold, so
        nothing is sent about it at all.
        """
        before = {r.fingerprint for r in reminders(world["project_id"])}
        run(world["project_id"], day=TODAY + timedelta(days=1))
        after = reminders(world["project_id"])
        new = [r for r in after if r.fingerprint not in before]
        assert not [r for r in new
                    if r.entity_id == world["tasks"]["M-DUE3"]
                    and r.trigger == monitor.DUE]

    def test_moving_the_due_date_re_arms_the_reminder(self, world):
        """A commitment that moves is a different commitment.

        Silence after a date change would be the worse failure: the person
        would never be told about the new date because they were told about
        the old one.
        """
        from backend.db.engine import get_session

        task_id = world["tasks"]["M-DUE7"]
        with get_session() as session:
            svc.update_task(session, Principal(world["alice"]), task_id,
                            due_date=str(TODAY + timedelta(days=10)))
            session.commit()

        moved = run(world["project_id"], day=TODAY + timedelta(days=3))
        due_again = [m for m in moved.messages
                     if m.entity_id == task_id and m.trigger == monitor.DUE]
        assert due_again, "the moved date was never reminded about"
        assert "2026-06-25" in due_again[0].body

    def test_an_overdue_task_is_chased_daily(self, world):
        """Unlike a due date, going on being late IS new information.

        The fingerprint carries the day, so silence is not mistaken for
        resolution — but it is one message a day, not one per sweep.
        """
        day = TODAY + timedelta(days=5)
        first = run(world["project_id"], day=day)
        overdue = [m for m in first.messages if m.trigger == monitor.OVERDUE]
        assert overdue

        second = run(world["project_id"], day=day)
        assert not [m for m in second.messages
                    if m.trigger == monitor.OVERDUE]


class TestHealth:
    def test_the_sweep_recalculates_and_records_the_colour(self, world):
        from backend.db.engine import get_session
        from backend.models.planner import PlannerProject, PlannerUpdate

        run(world["project_id"])
        with get_session() as session:
            project = session.get(PlannerProject, world["project_id"])
            assert project.calculated_health in ("GREEN", "AMBER", "RED")
            assert project.calculated_health_reason
            assert project.calculated_at is not None

            said = list(session.execute(
                select(PlannerUpdate).where(
                    PlannerUpdate.project_id == world["project_id"],
                    PlannerUpdate.action == "health")).scalars())
        assert said, "a colour change was not recorded in the history"
        assert said[0].source == "SYSTEM"
        assert said[0].author_id is None, \
            "a calculation must not be attributed to a person"

    def test_the_colour_is_not_re_announced_while_it_holds(self, world):
        from backend.db.engine import get_session
        from backend.models.planner import PlannerUpdate

        def count() -> int:
            with get_session() as session:
                return len(list(session.execute(
                    select(PlannerUpdate).where(
                        PlannerUpdate.project_id == world["project_id"],
                        PlannerUpdate.action == "health")).scalars()))

        before = count()
        run(world["project_id"])
        run(world["project_id"])
        assert count() == before


class TestDryRun:
    def test_send_false_writes_nothing(self, world):
        before = len(reminders(world["project_id"]))
        preview = run(world["project_id"], day=TODAY + timedelta(days=30),
                      send=False)
        assert preview.messages, "there was nothing to preview"
        assert preview.sent == 0
        assert len(reminders(world["project_id"])) == before


class TestItReachesTheNotificationCentre:
    """The reminders must appear where every other notification appears.

    A planner that built its own inbox would be a second place to look, and
    the second place is the one nobody looks at.
    """

    def test_a_reminder_shows_up_in_the_existing_centre(self, world):
        from backend.services import workflow as wf

        run(world["project_id"])
        mine = wf.notifications(world["bob"], limit=100)
        planner = [n for n in mine if n["kind"] == "planner"]
        assert planner, "nothing from the planner reached the centre"
        assert planner[0]["object_type"] == "planner_project"
        assert planner[0]["object_id"] == str(world["project_id"])

    def test_they_count_towards_unread(self, world):
        from backend.services import workflow as wf

        run(world["project_id"])
        assert wf.unread_count(world["bob"]) > 0
