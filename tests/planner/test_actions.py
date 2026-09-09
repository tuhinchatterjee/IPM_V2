"""What a person may change by saying so, and what they may not.

The interesting assertions here are the refusals. A conversational write that
can reach a due date is a product where a deadline moved and nobody knows who
moved it, so the tests that matter are the ones proving those paths do not
exist rather than that they are guarded.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from backend.models.planner import SOURCE_AI_CHAT, PlannerUpdate
from backend.planner import actions
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
    """A manager, a task owner, and a stranger with a project of her own."""
    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    with get_session() as session:
        boss = User(username=f"act-boss-{tag}", password_hash="x",
                    role="ANALYST", first_name="Ada", last_name="Boss")
        owner = User(username=f"act-own-{tag}", password_hash="x",
                     role="ANALYST", first_name="Owen", last_name="Owner")
        stranger = User(username=f"act-str-{tag}", password_hash="x",
                        role="ANALYST", first_name="Mal", last_name="Stranger")
        session.add_all([boss, owner, stranger])
        session.flush()
        who = Principal(int(boss.id))
        project = svc.create_project(
            session, who, code=f"ACT-{tag[:6].upper()}", name="Actions fixture",
            status="ACTIVE", manager_id=int(boss.id),
            start_date="2026-01-05", target_end_date="2026-12-18")
        session.flush()
        pid = int(project.id)
        svc.add_participant(session, who, pid, user_id=int(owner.id),
                            project_role="CONTRIBUTOR", access="CONTRIBUTOR")
        task = svc.create_task(session, who, pid, code="T-104",
                               title="Data Mapping", owner_id=int(owner.id),
                               start_date="2026-02-02", due_date="2026-03-02",
                               percent_complete=30)
        session.flush()
        session.commit()
        return {"project_id": pid, "boss": int(boss.id),
                "owner": int(owner.id), "stranger": int(stranger.id),
                "task_id": int(task.id)}


@pytest.fixture()
def session():
    from backend.db.engine import get_session

    with get_session() as s:
        yield s


# ================================================================ what works


def test_the_owner_can_report_progress_in_their_own_words(session, world):
    out = actions.post_task_update(
        session, Principal(world["owner"]), world["project_id"],
        code="T-104", percent_complete=80,
        narrative="Overlay calculation is complete. Finance review underway.",
        next_step="Obtain Finance approval and submit for CRO sign-off.")
    assert out["applied"] is True
    assert out["was"]["percent_complete"] == 30
    assert out["now"]["percent_complete"] == 80
    assert out["source"] == SOURCE_AI_CHAT


def test_it_writes_history_naming_the_person_not_the_agent(session, world):
    actions.post_task_update(
        session, Principal(world["owner"]), world["project_id"],
        code="T-104", percent_complete=55, narrative="Half way.")
    session.flush()
    row = session.execute(
        select(PlannerUpdate)
        .where(PlannerUpdate.project_id == world["project_id"],
               PlannerUpdate.source == SOURCE_AI_CHAT)
        .order_by(PlannerUpdate.id.desc())).scalars().first()
    assert row is not None
    assert row.author_id == world["owner"], \
        "the record must name the person, not a service identity"
    assert row.new_percent == 55


def test_a_blocker_needs_a_reason(session, world):
    with pytest.raises(svc.PlannerError, match="waiting for"):
        actions.set_task_blocker(session, Principal(world["owner"]),
                                 world["project_id"], code="T-104", reason=" ")


def test_saying_it_is_blocked_records_what_it_waits_for(session, world):
    out = actions.set_task_blocker(
        session, Principal(world["owner"]), world["project_id"], code="T-104",
        reason="Legal has not approved the wording.")
    assert out["blocked"] is True
    assert "Legal" in out["reason"]


def test_clearing_a_block_that_is_not_set_is_refused(session, world):
    with pytest.raises(svc.PlannerError, match="not blocked"):
        actions.set_task_blocker(session, Principal(world["owner"]),
                                 world["project_id"], code="T-104", clear=True)


def test_unblocking_clears_the_reason_as_well(session, world):
    actions.set_task_blocker(session, Principal(world["owner"]),
                             world["project_id"], code="T-104",
                             reason="Waiting on Legal.")
    session.flush()
    actions.set_task_blocker(session, Principal(world["owner"]),
                             world["project_id"], code="T-104", clear=True)
    session.flush()
    from backend.models.planner import PlannerTask

    task = session.get(PlannerTask, world["task_id"])
    assert task.blocked is False
    assert task.blocker_reason == "", \
        "a cleared block that keeps its reason reads as still waiting"


def test_a_risk_can_be_raised_by_saying_so(session, world):
    out = actions.create_raid_item(
        session, Principal(world["boss"]), world["project_id"],
        title="The regulator may change the interpretation",
        raid_type="RISK", severity="HIGH")
    assert out["applied"] is True
    assert out["severity"] == "HIGH"
    assert out["source"] == SOURCE_AI_CHAT


# ============================================================ what does not


def test_there_is_no_way_to_move_a_due_date_from_here():
    """Not a guarded parameter — an absent one.

    `post_task_update` has no `due_date`, and passing one is a TypeError
    rather than something a permission check has to catch correctly.
    """
    import inspect

    signature = inspect.signature(actions.post_task_update)
    forbidden = {"due_date", "start_date", "owner_id", "reviewer_id",
                 "status", "critical", "weight"}
    assert not forbidden & set(signature.parameters)


def test_no_conversational_capability_closes_a_risk():
    import inspect

    names = {n for n, _ in inspect.getmembers(actions, inspect.isfunction)}
    assert "close_raid_item" not in names
    assert "complete_task" not in names
    assert "set_project_health" not in names


def test_the_commitment_guard_refuses_a_widened_call():
    with pytest.raises(actions.Refused, match="commitment"):
        actions._guard_commitments(due_date="2026-12-31")


def test_the_prohibited_names_have_no_registry_entry():
    from backend.agentic import tools as reg

    for name in actions.NEVER_CONVERSATIONAL:
        slug = name.replace("a task's ", "").replace("a ", "").replace(
            "'s", "").replace(" ", "_")
        assert slug not in {t.tool_id for t in reg.TOOLS}


def test_a_stranger_cannot_report_on_a_project_she_is_not_on(session, world):
    from backend.planner import access as acl

    with pytest.raises((acl.ProjectNotFound, acl.ProjectDenied)):
        actions.post_task_update(
            session, Principal(world["stranger"]), world["project_id"],
            code="T-104", percent_complete=100, narrative="Done, trust me.")


def test_a_task_code_from_another_project_is_not_found(session, world):
    with pytest.raises(svc.PlannerError, match="no task called"):
        actions.post_task_update(
            session, Principal(world["owner"]), world["project_id"],
            code="T-999", narrative="Nothing to see here.")


def test_an_empty_report_is_refused_rather_than_recorded(session, world):
    with pytest.raises(svc.PlannerError, match="nothing to record"):
        actions.post_task_update(session, Principal(world["owner"]),
                                 world["project_id"], code="T-104")


def test_every_writer_is_registered_as_a_writer_and_reads_data():
    from backend.agentic import tools as reg

    for tool_id in (reg.PLANNER_POST_TASK_UPDATE, reg.PLANNER_SET_TASK_BLOCKER,
                    reg.PLANNER_CREATE_RAID_ITEM):
        found = reg.require(tool_id)
        assert found.writes is True
        assert found.reads_data is True, \
            "without reads_data the principal never reaches the handler"


def test_the_handlers_are_wired(session):
    from backend.agentic import tools as reg
    from backend.planner import agent

    wired = agent.handlers(session)
    for tool_id in (reg.PLANNER_POST_TASK_UPDATE, reg.PLANNER_SET_TASK_BLOCKER,
                    reg.PLANNER_CREATE_RAID_ITEM):
        assert tool_id in wired
