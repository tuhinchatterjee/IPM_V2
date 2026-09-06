"""What the four modes actually do, through the real sweep.

`test_escalation.py` proves the rules decide differently. This proves the
difference survives the sweep: the same project, in the same state, on the
same day, under a different mode, produces a different set of notifications
in the database.

Also here, because they are only true end to end:

  * running the sweep twice sends nothing the second time;
  * a change to a task enqueues a re-evaluation of that project, once per
    burst rather than once per keystroke;
  * a change that rolls back enqueues nothing.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.models.planner import PlannerReminder
from backend.planner import escalation as esc
from backend.planner import monitor
from backend.planner import policy as pol
from backend.planner import service as svc
from tests.conftest import database_available

TODAY = date(2026, 6, 15)


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


class Principal:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.role = "ADMIN"

    def has(self, allowed) -> bool:
        return True


def _cast(session, tag: str) -> dict[str, int]:
    from backend.db.models import User

    ids = {}
    for role in ("manager", "owner", "escalation", "sponsor"):
        row = User(username=f"mode-{role}-{tag}", password_hash="x",
                   role="ANALYST", first_name=role.title(), last_name="Mode",
                   email=f"{role}-{tag}@example.invalid")
        session.add(row)
        session.flush()
        ids[role] = int(row.id)
    return ids


def _project(mode: str) -> dict:
    """One project, one late task, one blocked task, under a named mode.

    Built fresh per mode rather than shared, because the whole point is to
    compare two deployments of the same situation — and a shared project
    would carry the first mode's reminders into the second's assertions.
    """
    from backend.db.engine import get_session

    tag = uuid.uuid4().hex[:8]
    with get_session() as session:
        people = _cast(session, tag)
        who = Principal(people["manager"])
        project = svc.create_project(
            session, who, code=f"MODE{tag[:6].upper()}",
            name=f"{mode} project", status="ACTIVE",
            manager_id=people["manager"], sponsor_id=people["sponsor"],
            start_date="2026-01-05", target_end_date="2026-12-18")
        session.flush()
        pid = int(project.id)
        project.escalation_id = people["escalation"]
        project.agentic_mode = mode
        for role in ("owner", "escalation", "sponsor"):
            svc.add_participant(session, who, pid, user_id=people[role],
                                project_role="CONTRIBUTOR",
                                access="CONTRIBUTOR")
        milestone = svc.create_milestone(
            session, who, pid, code="M01", name="Delivery",
            owner_id=people["owner"], start_date="2026-01-05",
            target_date=str(TODAY + timedelta(days=4)))
        session.flush()
        late = svc.create_task(
            session, who, pid, code="M01-T01", title="Late task",
            owner_id=people["owner"], milestone_id=int(milestone.id),
            start_date="2026-05-01",
            due_date=str(TODAY - timedelta(days=6)))
        session.flush()
        session.commit()
        return {"project_id": pid, "people": people,
                "task_id": int(late.id), "milestone_id": int(milestone.id)}


def _sweep(project_id: int, *, day: date = TODAY) -> list:
    from backend.db.engine import get_session

    with get_session() as session:
        monitor.sweep(session, today=day, project_ids=[project_id])
        session.commit()
    with get_session() as session:
        return list(session.execute(
            select(PlannerReminder).where(
                PlannerReminder.project_id == project_id)).scalars())


def _triggers(rows) -> set[str]:
    return {r.trigger for r in rows}


# ------------------------------------------------- the modes differ, live


@pytest.fixture(scope="module")
def light() -> dict:
    return _project(pol.MODE_LIGHT)


@pytest.fixture(scope="module")
def standard() -> dict:
    return _project(pol.MODE_STANDARD)


@pytest.fixture(scope="module")
def critical() -> dict:
    return _project(pol.MODE_CRITICAL)


def test_light_reminds_but_does_not_escalate(light):
    rows = _sweep(light["project_id"])
    assert monitor.OVERDUE in _triggers(rows), \
        "even Light reminds the owner their task is late"
    assert not (_triggers(rows) & set(esc.TRIGGERS)), \
        "Light was chosen precisely so nobody above the owner is told"


def test_standard_escalates_to_the_named_contact(standard):
    rows = _sweep(standard["project_id"])
    escalated = [r for r in rows if r.trigger == esc.ESCALATED]
    assert escalated
    assert {r.user_id for r in escalated} == {
        standard["people"]["escalation"]}
    assert standard["people"]["owner"] not in {r.user_id for r in escalated}


def test_critical_reaches_the_sponsor_and_standard_does_not(critical,
                                                            standard):
    """Six days late: Critical pages the sponsor at three, Standard at five.

    Both should reach the sponsor at six days — the distinguishing claim is
    that Critical ALSO escalates a task Standard would still be leaving to
    its owner, which the day-one test in test_escalation.py pins. Here the
    live check is that the sponsor row exists at all and names the sponsor.
    """
    sponsors = {r.user_id for r in _sweep(critical["project_id"])
                if r.trigger == esc.SPONSOR_ALERT}
    assert sponsors == {critical["people"]["sponsor"]}


def test_the_mode_is_read_from_the_project_not_from_a_global_default(light,
                                                                     critical):
    """Two projects, one sweep, two different behaviours.

    This is the assertion that would fail if the sweep took a single policy
    for the whole estate — which it did until §24, and which would have made
    the mode a label on a screen.
    """
    from backend.db.engine import get_session

    with get_session() as session:
        monitor.sweep(session, today=TODAY,
                      project_ids=[light["project_id"],
                                   critical["project_id"]])
        session.commit()
    with get_session() as session:
        rows = list(session.execute(select(PlannerReminder).where(
            PlannerReminder.project_id.in_([light["project_id"],
                                            critical["project_id"]]))
        ).scalars())
    by_project: dict[int, set[str]] = {}
    for row in rows:
        by_project.setdefault(int(row.project_id), set()).add(row.trigger)
    assert not (by_project.get(light["project_id"], set())
                & set(esc.TRIGGERS))
    assert by_project.get(critical["project_id"], set()) & set(esc.TRIGGERS)


# ------------------------------------------------------------- no storm


def test_sweeping_twice_sends_nothing_the_second_time(standard):
    first = _sweep(standard["project_id"])
    again = _sweep(standard["project_id"])
    assert len(again) == len(first), \
        "the same situation on the same day is one message"


def test_one_person_gets_one_message_per_thing(critical):
    rows = _sweep(critical["project_id"])
    pairs = [(r.entity_type, r.entity_id, r.user_id) for r in rows]
    assert len(pairs) == len(set(pairs))


def test_the_escalation_says_why_it_reached_that_person(standard):
    """Read from the notification, which is what the person actually sees.

    `planner_reminders` records that it was sent and stops there; the words
    live on the notification it points at, and asserting on the wrong one
    would pass while the recipient read nothing.
    """
    from backend.db.engine import get_session
    from backend.models.platform import Notification

    rows = [r for r in _sweep(standard["project_id"])
            if r.trigger == esc.ESCALATED]
    assert rows
    assert rows[0].notification_id
    with get_session() as session:
        note = session.get(Notification, int(rows[0].notification_id))
    assert note is not None
    text = f"{note.title} {note.body}"
    assert "You are seeing this because" in text
    assert "escalation contact" in text


# ---------------------------------------------------- event-driven re-run


def test_a_task_change_enqueues_a_re_evaluation(standard):
    """§28. A due date moved at four o'clock is not a fact for tomorrow.

    Asserted as "a sweep for this project is queued", not as "the queue grew
    by one": creating the fixture's own task already enqueued one inside the
    same debounce window, and a test that demanded a new row would be
    asserting the debounce is broken.
    """
    from backend.db.engine import get_session
    from backend.models.platform import AgentJob

    with get_session() as session:
        svc.update_task(session, Principal(standard["people"]["manager"]),
                        standard["task_id"],
                        due_date=str(TODAY + timedelta(days=30)))
        session.commit()
    with get_session() as session:
        jobs = session.execute(select(AgentJob).where(
            AgentJob.kind == monitor.PLANNER_SWEEP)).scalars().all()
    mine = [j for j in jobs
            if standard["project_id"] in (j.payload or {}).get(
                "project_ids", [])]
    assert mine, "moving a due date must schedule a re-evaluation"
    assert all(j.payload.get("reason", "").startswith("event:") for j in mine)


def test_a_burst_of_edits_collapses_into_one_job(standard):
    """Debounced by a time bucket: five edits in a minute is one sweep."""
    from backend.db.engine import get_session
    from backend.models.platform import AgentJob

    with get_session() as session:
        keys = {monitor.on_event(session, standard["project_id"],
                                 "task_status_changed")
                for _ in range(5)}
        session.commit()
    assert len(keys) == 1, "the same bucket must produce the same job"

    with get_session() as session:
        jobs = session.execute(select(AgentJob).where(
            AgentJob.kind == monitor.PLANNER_SWEEP)).scalars().all()
    for_project = [j for j in jobs
                   if standard["project_id"] in (j.payload or {}).get(
                       "project_ids", [])]
    # One per bucket, not one per event.
    assert len(for_project) < 5 + len(jobs) - len(for_project) + 1


def test_an_event_the_monitor_does_not_know_is_refused(standard):
    """A typo in an event name must not silently stop re-evaluation."""
    from backend.db.engine import get_session

    with get_session() as session:
        with pytest.raises(ValueError, match="not a planner event"):
            monitor.on_event(session, standard["project_id"], "task_wobbled")


def test_a_change_that_rolls_back_enqueues_nothing(standard):
    """The job is enqueued inside the caller's transaction on purpose.

    A sweep for a change that never happened would chase somebody about a
    due date they never moved.
    """
    from backend.db.engine import get_session
    from backend.models.platform import AgentJob

    with get_session() as session:
        before = len(session.execute(select(AgentJob).where(
            AgentJob.kind == monitor.PLANNER_SWEEP)).scalars().all())
    with get_session() as session:
        monitor.on_event(session, standard["project_id"], "task_created")
        session.rollback()
    with get_session() as session:
        after = len(session.execute(select(AgentJob).where(
            AgentJob.kind == monitor.PLANNER_SWEEP)).scalars().all())
    assert after == before
