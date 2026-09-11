"""Work is assigned to people, and a person either exists or is a mistake.

Naming somebody who is not in the directory used to reach the database and
come back as a foreign-key violation, which the API could only report as
"Something went wrong that CreditProbe does not recognise" — an HTTP 500, a
stack trace in the log, and nothing the person at the screen could act on.
On `escalation_id` it did not even fail: the value was accepted and the task
quietly had no escalation contact, which is the worse of the two outcomes
because nothing anywhere says so.

Every field that names a person now goes through one check, on creation and
on edit, for tasks, milestones, RAID items and projects alike.
"""

from __future__ import annotations

import uuid

import pytest

from backend.planner import service as svc
from tests.conftest import database_available

GHOST = 99_999_999


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


class Principal:
    def __init__(self, user_id: int, role: str = "ANALYST") -> None:
        self.user_id = user_id
        self.role = role

    def has(self, _allowed) -> bool:
        return True


@pytest.fixture()
def world():
    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    with get_session() as session:
        boss = User(username=f"ghost-{tag}", password_hash="x",
                    role="ANALYST", first_name="Gita", last_name="Boss")
        session.add(boss)
        session.flush()
        who = Principal(int(boss.id))
        project = svc.create_project(
            session, who, code=f"GHO-{tag[:6].upper()}", name="Ghost fixture",
            status="ACTIVE", manager_id=int(boss.id),
            start_date="2026-01-05", target_end_date="2026-12-18")
        session.flush()
        task = svc.create_task(session, who, int(project.id), code="T-1",
                               title="Real work", owner_id=int(boss.id),
                               start_date="2026-02-02", due_date="2026-03-02")
        session.flush()
        session.commit()
        return {"project_id": int(project.id), "boss": int(boss.id),
                "task_id": int(task.id)}


@pytest.fixture()
def session():
    from backend.db.engine import get_session

    with get_session() as s:
        yield s


@pytest.mark.parametrize("field", ["owner_id", "reviewer_id",
                                   "escalation_id"])
def test_a_task_cannot_be_given_to_somebody_who_is_not_there(
        session, world, field):
    with pytest.raises(svc.PlannerError) as refused:
        svc.update_task(session, Principal(world["boss"]),
                        world["task_id"], **{field: GHOST})
    said = str(refused.value)
    assert "No such person" in said
    assert str(GHOST) in said
    session.rollback()


def test_the_refusal_names_the_field_in_words_a_person_recognises(
        session, world):
    with pytest.raises(svc.PlannerError) as refused:
        svc.update_task(session, Principal(world["boss"]),
                        world["task_id"], escalation_id=GHOST)
    # "escalation" rather than "escalation_id" — the label on the form.
    assert "escalation" in str(refused.value)
    assert "_id" not in str(refused.value)
    session.rollback()


def test_a_task_cannot_be_created_for_a_person_who_is_not_there(
        session, world):
    with pytest.raises(svc.PlannerError):
        svc.create_task(session, Principal(world["boss"]),
                        world["project_id"], code="T-9", title="For nobody",
                        owner_id=GHOST,
                        start_date="2026-02-02", due_date="2026-03-02")
    session.rollback()


def test_nor_a_milestone_nor_a_risk(session, world):
    for make in (
        lambda: svc.create_milestone(
            session, Principal(world["boss"]), world["project_id"],
            code="M-9", name="For nobody", owner_id=GHOST),
        lambda: svc.create_raid(
            session, Principal(world["boss"]), world["project_id"],
            raid_type="RISK", title="Owned by nobody", owner_id=GHOST),
    ):
        with pytest.raises(svc.PlannerError):
            make()
        session.rollback()


@pytest.mark.parametrize("field", ["sponsor_id", "manager_id", "owner_id",
                                   "escalation_id"])
def test_nor_a_project(session, world, field):
    with pytest.raises(svc.PlannerError):
        svc.update_project(session, Principal(world["boss"]),
                           world["project_id"], **{field: GHOST})
    session.rollback()


def test_naming_a_real_person_still_works(session, world):
    task = svc.update_task(session, Principal(world["boss"]),
                           world["task_id"], owner_id=world["boss"])
    assert task.owner_id == world["boss"]
    session.rollback()


def test_naming_nobody_still_means_nobody(session, world):
    """Clearing a field is not the same as naming somebody who is not there."""
    task = svc.update_task(session, Principal(world["boss"]),
                           world["task_id"], reviewer_id=None)
    assert task.reviewer_id is None
    session.rollback()
