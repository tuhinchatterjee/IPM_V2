"""Nothing may be BLOCKED without saying what it is waiting for.

The rule was already written down, and the service's own docstring said why:
letting the four columns that describe one situation disagree "is how a task
shows COMPLETED at 40% or BLOCKED with no blocker".

It was enforced in the wrong place. "Blocked" reaches a task two ways — as
the `blocked` flag, and as the STATUS somebody picks from a dropdown, which
is how a person actually does it — and `_align_task_state` is what turns the
second into the first. The check read the flag BEFORE that alignment ran, so
the ordinary route through the product walked straight past it: set the
status to BLOCKED, say nothing, and the task is saved blocked with an empty
reason. The project manager's screen then says something is stuck and offers
no way to find out what about.

These tests pin the RULE rather than the ordering, so that moving the code
around again cannot quietly reopen it: whichever way a task arrives at
blocked, and whichever entry point it comes through, it carries a reason or
it is refused.
"""

from __future__ import annotations

import uuid

import pytest

from backend.planner import service as svc
from tests.conftest import database_available


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
        boss = User(username=f"blk-{tag}", password_hash="x", role="ANALYST",
                    first_name="Bea", last_name="Boss")
        session.add(boss)
        session.flush()
        who = Principal(int(boss.id))
        project = svc.create_project(
            session, who, code=f"BLK-{tag[:6].upper()}",
            name="Blocked fixture", status="ACTIVE", manager_id=int(boss.id),
            start_date="2026-01-05", target_end_date="2026-12-18")
        session.flush()
        task = svc.create_task(session, who, int(project.id), code="T-1",
                               title="Waiting on something",
                               owner_id=int(boss.id),
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


# ------------------------------------------------------- the way it happens

def test_setting_the_status_to_blocked_without_a_reason_is_refused(
        session, world):
    """The dropdown route — the one a person uses."""
    with pytest.raises(svc.PlannerError) as refused:
        svc.update_task(session, Principal(world["boss"]),
                        world["task_id"], status="BLOCKED")
    assert "reason" in str(refused.value).lower()
    session.rollback()


def test_and_the_task_is_left_alone_when_it_is(session, world):
    """A refusal that half-applied would be worse than no rule at all."""
    with pytest.raises(svc.PlannerError):
        svc.update_task(session, Principal(world["boss"]),
                        world["task_id"], status="BLOCKED")
    session.rollback()
    from backend.models.planner import PlannerTask

    task = session.get(PlannerTask, world["task_id"])
    session.refresh(task)
    assert task.status != "BLOCKED"
    assert task.blocked is False


def test_setting_the_flag_without_a_reason_is_refused_too(session, world):
    with pytest.raises(svc.PlannerError) as refused:
        svc.update_task(session, Principal(world["boss"]),
                        world["task_id"], blocked=True)
    assert "reason" in str(refused.value).lower()
    session.rollback()


def test_whitespace_is_not_a_reason(session, world):
    with pytest.raises(svc.PlannerError):
        svc.update_task(session, Principal(world["boss"]),
                        world["task_id"], status="BLOCKED",
                        blocker_reason="   ")
    session.rollback()


# ------------------------------------------------------------ and what works

def test_blocked_with_a_reason_is_saved_and_keeps_it(session, world):
    why = "Waiting on the data team for the treatment history extract."
    svc.update_task(session, Principal(world["boss"]),
                    world["task_id"], status="BLOCKED", blocker_reason=why)
    session.flush()
    from backend.models.planner import PlannerTask

    task = session.get(PlannerTask, world["task_id"])
    assert task.status == "BLOCKED"
    assert task.blocked is True
    assert task.blocker_reason == why
    session.rollback()


def test_a_task_cannot_be_created_blocked_with_nothing_written_down(
        session, world):
    """The creation path had no check at all, not even a misplaced one."""
    with pytest.raises(svc.PlannerError) as refused:
        svc.create_task(session, Principal(world["boss"]),
                        world["project_id"], code="T-2",
                        title="Born stuck", owner_id=world["boss"],
                        status="BLOCKED",
                        start_date="2026-02-02", due_date="2026-03-02")
    assert "reason" in str(refused.value).lower()
    session.rollback()


def test_completing_a_blocked_task_clears_the_block_rather_than_refusing(
        session, world):
    """The rule must not trap somebody in the state it is protecting.

    Finishing the work is the answer to being blocked, so the alignment
    clears the flag and the reason together — and the check, which now runs
    after it, has nothing to object to.
    """
    svc.update_task(session, Principal(world["boss"]),
                    world["task_id"], status="BLOCKED",
                    blocker_reason="Waiting on the extract.")
    session.flush()
    svc.update_task(session, Principal(world["boss"]),
                    world["task_id"], status="COMPLETED")
    session.flush()
    from backend.models.planner import PlannerTask

    task = session.get(PlannerTask, world["task_id"])
    assert task.status == "COMPLETED"
    assert task.blocked is False
    assert task.blocker_reason == ""
    session.rollback()
