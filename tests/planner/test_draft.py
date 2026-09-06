"""A plan that is not a project yet, and the moment it becomes one.

These tests run against the real database and the real service layer, because
the whole claim of the draft module is that publish goes through the ordinary
planner path. A test that stubbed `service` would prove the draft document is
well-formed and nothing about whether the project it becomes is governed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


@dataclass
class Principal:
    user_id: int
    role: str = "ANALYST"


@pytest.fixture(scope="module")
def people() -> dict[str, int]:
    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    ids: dict[str, int] = {}
    with get_session() as session:
        for name in ("maya", "omar", "hana", "zaid"):
            row = User(username=f"draft-{name}-{tag}", password_hash="x",
                       role="ANALYST", first_name=name.title(),
                       last_name="Test", email=f"{name}-{tag}@example.invalid")
            session.add(row)
            session.flush()
            ids[name] = int(row.id)
        session.commit()
    return ids


def _plan(people: dict[str, int]) -> dict:
    """A small but complete plan: two milestones, three tasks, one link."""
    from backend.planner import draft

    start = date.today()
    plan = draft.empty()
    plan["overview"] = {"name": f"LGD Redevelopment {uuid.uuid4().hex[:6]}",
                        "code": f"LGD{uuid.uuid4().hex[:6].upper()}",
                        "description": "Rebuild the LGD model.",
                        "objective": "A validated model by year end."}
    plan["governance"] = {
        "sponsor_id": people["hana"], "manager_id": people["maya"],
        "owner_id": people["maya"], "escalation_id": people["hana"],
        "priority": "HIGH", "status": "ACTIVE",
        "start_date": start.isoformat(),
        "target_end_date": (start + timedelta(days=180)).isoformat(),
        "reporting_cadence": "WEEKLY"}
    plan["agentic"] = {"mode": "STANDARD", "policy": {}}
    plan["milestones"] = [
        {"code": "M01", "name": "Data foundation", "owner_id": people["omar"],
         "start_date": start.isoformat(),
         "target_date": (start + timedelta(days=60)).isoformat(),
         "priority": "HIGH", "critical": True},
        {"code": "M02", "name": "Model build", "owner_id": people["zaid"],
         "start_date": (start + timedelta(days=61)).isoformat(),
         "target_date": (start + timedelta(days=150)).isoformat(),
         "priority": "MEDIUM", "critical": False},
    ]
    plan["tasks"] = [
        {"code": "M01-T01", "milestone_code": "M01", "title": "Extract data",
         "description": "Pull five years of recoveries.",
         "owner_id": people["omar"], "start_date": start.isoformat(),
         "due_date": (start + timedelta(days=20)).isoformat(),
         "priority": "HIGH"},
        {"code": "M01-T02", "milestone_code": "M01", "title": "Reconcile",
         "description": "Tie back to the ledger.", "owner_id": people["omar"],
         "start_date": (start + timedelta(days=21)).isoformat(),
         "due_date": (start + timedelta(days=55)).isoformat()},
        {"code": "M02-T01", "milestone_code": "M02", "title": "Fit the model",
         "description": "Candidate specifications.",
         "owner_id": people["zaid"],
         "start_date": (start + timedelta(days=61)).isoformat(),
         "due_date": (start + timedelta(days=140)).isoformat()},
    ]
    plan["links"] = [{"predecessor": "M01-T01", "successor": "M01-T02",
                      "dependency_type": "FS", "lag_days": 0}]
    return plan


# ------------------------------------------------------------------- codes


def test_codes_read_the_way_people_quote_them():
    from backend.planner import draft

    assert draft.suggest_code("LGD Model Redevelopment",
                              today=date(2026, 3, 1)) == "LMR-2026"
    # "the", "of" and "project" are noise in a code somebody has to say aloud.
    assert draft.suggest_code("The Project for Recovery Data",
                              today=date(2026, 3, 1)) == "RD-2026"
    assert draft.milestone_code(1) == "M01"
    assert draft.task_code("M01", 7) == "M01-T07"


def test_a_published_code_is_never_regenerated(people):
    """Moving a task to another milestone keeps the code it was given.

    §37: a code is how a task is referred to in chat, in an export and in
    whatever somebody has already written down. Renaming it on a move would
    silently invalidate all three.
    """
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        key = row.key

        draft.apply(session, who, key, "update_task",
                    {"code": "M01-T01", "milestone_code": "M02"})
        session.commit()
        plan = draft.load(session, who, key).plan
        moved = draft.item(plan, "M01-T01")
        assert moved is not None
        assert moved["milestone_code"] == "M02"
        assert moved["code"] == "M01-T01"


# ------------------------------------------------------------ escalation


def test_escalation_is_inherited_and_says_where_from(people):
    from backend.planner import draft

    plan = _plan(people)
    # Nothing on the task, nothing on its milestone: the project answers.
    assert draft.escalation_for(plan, "M01-T01") == {
        "user_id": people["hana"], "source": "project", "from_code": ""}

    plan["milestones"][0]["escalation_id"] = people["maya"]
    assert draft.escalation_for(plan, "M01-T01") == {
        "user_id": people["maya"], "source": "milestone", "from_code": "M01"}

    plan["tasks"][0]["escalation_id"] = people["zaid"]
    assert draft.escalation_for(plan, "M01-T01") == {
        "user_id": people["zaid"], "source": "own", "from_code": "M01-T01"}


# ----------------------------------------------------------- dependencies


def test_a_link_states_itself_before_it_exists(people):
    from backend.planner import draft

    plan = _plan(people)
    preview = draft.link_preview(plan, "M01", "M02")
    assert preview["predecessor"] == "M01"
    assert "Model build" in preview["sentence"]
    # Nothing was applied by asking.
    assert len(draft.links_of(plan)) == 1


def test_a_link_that_would_loop_is_refused_by_the_existing_engine(people):
    from backend.planner import draft

    plan = _plan(people)
    with pytest.raises(draft.DraftError, match="loop"):
        draft.link_preview(plan, "M01-T02", "M01-T01")


def test_the_same_link_twice_is_refused(people):
    from backend.planner import draft

    plan = _plan(people)
    with pytest.raises(draft.DraftError, match="already linked"):
        draft.link_preview(plan, "M01-T01", "M01-T02")


def test_nothing_depends_on_itself(people):
    from backend.planner import draft

    plan = _plan(people)
    with pytest.raises(draft.DraftError, match="itself"):
        draft.link_preview(plan, "M01", "M01")


def test_previous_task_stays_inside_its_milestone(people):
    from backend.planner import draft

    plan = _plan(people)
    assert draft.previous_task(plan, "M01-T02") == "M01-T01"
    assert draft.previous_task(plan, "M01-T01") == ""
    # M02-T01 is the first under M02; guessing across milestones would link
    # things the person did not mean.
    assert draft.previous_task(plan, "M02-T01") == ""


# ------------------------------------------------------------ completeness


def test_an_empty_plan_names_every_blocker_and_publishes_nothing():
    from backend.planner import draft

    found = draft.check(draft.empty())
    assert not found.publishable
    messages = " ".join(note.message for note in found.blockers)
    for expected in ("no name", "no code", "no sponsor", "no manager",
                     "escalate to", "no start date", "no milestones"):
        assert expected in messages


def test_a_warning_does_not_stop_publication(people):
    from backend.planner import draft

    plan = _plan(people)
    plan["milestones"].append({
        "code": "M03", "name": "Documentation", "owner_id": people["maya"],
        "start_date": date.today().isoformat(),
        "target_date": (date.today() + timedelta(days=90)).isoformat()})
    found = draft.check(plan)
    assert found.publishable
    assert any("no tasks under it" in note.message for note in found.warnings)


def test_a_task_after_its_milestone_is_a_warning_not_a_refusal(people):
    from backend.planner import draft

    plan = _plan(people)
    plan["tasks"][0]["due_date"] = (
        date.today() + timedelta(days=400)).isoformat()
    found = draft.check(plan)
    assert found.publishable
    assert any(note.code == "M01-T01" for note in found.warnings)


# ------------------------------------------------------------- the writer


def test_chat_and_the_panel_use_one_writer(people):
    """The same command applied twice from two callers builds one document."""
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, name="Recovery Data Refresh")
        session.commit()
        key = row.key
        assert row.code.startswith("RDR-")

        draft.apply(session, who, key, "add_milestone",
                    {"name": "Discovery", "owner_id": people["omar"],
                     "target_date": (date.today()
                                     + timedelta(days=30)).isoformat()})
        session.commit()
        draft.apply(session, who, key, "add_task",
                    {"milestone_code": "M01", "title": "Interview the users",
                     "owner_id": people["omar"],
                     "due_date": (date.today()
                                  + timedelta(days=10)).isoformat()})
        session.commit()
        plan = draft.load(session, who, key).plan
        assert [m["code"] for m in draft.milestones_of(plan)] == ["M01"]
        assert [t["code"] for t in draft.tasks_of(plan)] == ["M01-T01"]


def test_a_second_task_offers_the_link_rather_than_making_it(people):
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        outcome = draft.apply(
            session, who, row.key, "add_task",
            {"milestone_code": "M02", "title": "Validate",
             "owner_id": people["zaid"],
             "due_date": (date.today() + timedelta(days=145)).isoformat()})
        session.commit()
        assert outcome["suggest_link"] == {"predecessor": "M02-T01",
                                           "successor": "M02-T02"}
        plan = draft.load(session, who, row.key).plan
        assert len(draft.links_of(plan)) == 1  # still only the seeded one


def test_a_command_that_fails_leaves_the_stored_plan_untouched(people):
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        before = draft.load(session, who, row.key).plan

        with pytest.raises(draft.DraftError):
            draft.apply(session, who, row.key, "update_milestone",
                        {"code": "M01",
                         "start_date": (date.today()
                                        + timedelta(days=500)).isoformat()})
        session.rollback()
        after = draft.load(session, who, row.key).plan
        assert after == before


def test_an_unknown_command_is_refused_in_words(people):
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        with pytest.raises(draft.DraftError, match="do not know how to"):
            draft.apply(session, who, row.key, "delete_project", {})


def test_removing_a_milestone_takes_its_tasks_and_links(people):
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        outcome = draft.apply(session, who, row.key, "remove_milestone",
                              {"code": "M01"})
        session.commit()
        assert outcome["removed_tasks"] == ["M01-T01", "M01-T02"]
        plan = draft.load(session, who, row.key).plan
        assert draft.links_of(plan) == []
        assert [t["code"] for t in draft.tasks_of(plan)] == ["M02-T01"]


def test_a_stale_write_is_refused(people):
    from backend.db.engine import get_session
    from backend.planner import draft, service

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        stale = int(row.version)
        draft.apply(session, who, row.key, "set_step", {"step": "TASKS"})
        session.commit()
        with pytest.raises(service.StaleWrite):
            draft.apply(session, who, row.key, "set_step",
                        {"step": "REVIEW"}, expected_version=stale)


def test_a_draft_belongs_to_whoever_started_it(people):
    from backend.db.engine import get_session
    from backend.planner import access as acl
    from backend.planner import draft

    mine = Principal(people["maya"])
    theirs = Principal(people["zaid"])
    with get_session() as session:
        row = draft.create(session, mine, plan=_plan(people))
        session.commit()
        with pytest.raises(acl.ProjectDenied):
            draft.load(session, theirs, row.key)
        assert draft.load(session, Principal(people["zaid"], "ADMIN"),
                          row.key).key == row.key


# ------------------------------------------------------ agentic behaviour


def test_the_agentic_mode_is_captured_and_said_back(people):
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        outcome = draft.apply(session, who, row.key, "set_agentic",
                              {"mode": "CRITICAL"})
        session.commit()
        assert outcome["sentence"]
        assert draft.load(session, who, row.key).plan["agentic"]["mode"] \
            == "CRITICAL"


def test_an_incoherent_custom_policy_is_refused(people):
    from backend.db.engine import get_session
    from backend.planner import draft, policy

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        with pytest.raises(policy.PolicyError):
            draft.apply(session, who, row.key, "set_agentic",
                        {"mode": "CUSTOM",
                         "policy": {"escalate_after_days": 10,
                                    "notify_sponsor_after_days": 2}})


# ------------------------------------------------------------------ publish


def test_publish_creates_the_whole_plan_through_the_service_layer(people):
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.planner import (
        PlannerDependency,
        PlannerMilestone,
        PlannerParticipant,
        PlannerTask,
    )
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        project = draft.publish(session, who, row.key)
        session.commit()
        project_id = int(project.id)

        milestones = list(session.execute(
            select(PlannerMilestone).where(
                PlannerMilestone.project_id == project_id)).scalars())
        tasks = list(session.execute(
            select(PlannerTask).where(
                PlannerTask.project_id == project_id)).scalars())
        links = list(session.execute(
            select(PlannerDependency).where(
                PlannerDependency.project_id == project_id)).scalars())
        seats = list(session.execute(
            select(PlannerParticipant).where(
                PlannerParticipant.project_id == project_id)).scalars())

        assert sorted(m.code for m in milestones) == ["M01", "M02"]
        assert sorted(t.code for t in tasks) == ["M01-T01", "M01-T02",
                                                 "M02-T01"]
        assert len(links) == 1
        # Everybody the plan named can open the project they are chased about.
        assert {int(s.user_id) for s in seats} >= {
            people["maya"], people["omar"], people["hana"], people["zaid"]}
        # The agentic answer reached the project row.
        assert project.agentic_mode == "STANDARD"
        assert int(project.escalation_id) == people["hana"]
        assert int(project.owner_id) == people["maya"]

        published = draft.load(session, who, row.key)
        assert published.status == "PUBLISHED"
        assert int(published.project_id) == project_id


def test_publish_writes_the_ordinary_history_and_audit(people):
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.planner import PlannerUpdate
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        project = draft.publish(session, who, row.key)
        session.commit()
        updates = list(session.execute(
            select(PlannerUpdate).where(
                PlannerUpdate.project_id == int(project.id))).scalars())
        # Created rows announce themselves the same way the UI's do.
        assert {u.entity_code for u in updates} >= {
            "M01", "M02", "M01-T01", "M01-T02", "M02-T01"}


def test_an_incomplete_plan_is_not_published(people):
    from sqlalchemy import func, select

    from backend.db.engine import get_session
    from backend.models.planner import PlannerProject
    from backend.planner import draft

    who = Principal(people["maya"])
    plan = _plan(people)
    plan["governance"]["sponsor_id"] = None
    with get_session() as session:
        before = session.execute(
            select(func.count()).select_from(PlannerProject)).scalar_one()
        row = draft.create(session, who, plan=plan)
        session.commit()
        with pytest.raises(draft.DraftError, match="not ready to publish"):
            draft.publish(session, who, row.key)
        session.rollback()
        after = session.execute(
            select(func.count()).select_from(PlannerProject)).scalar_one()
        assert after == before


def test_a_publish_that_fails_halfway_leaves_no_project(people, monkeypatch):
    """§21: a half-created project is worse than no project.

    The failure is injected at the third task, which is past the project, the
    participants, both milestones and two tasks — the exact shape of partial
    state somebody would find on Monday and start working on.
    """
    from sqlalchemy import func, select

    from backend.db.engine import get_session
    from backend.models.planner import PlannerProject
    from backend.planner import draft, service

    real = service.create_task
    calls = {"n": 0}

    def explode(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise service.PlannerError("injected failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "create_task", explode)

    who = Principal(people["maya"])
    plan = _plan(people)
    code = plan["overview"]["code"]
    with get_session() as session:
        before = session.execute(
            select(func.count()).select_from(PlannerProject)).scalar_one()
        row = draft.create(session, who, plan=plan)
        session.commit()
        with pytest.raises(service.PlannerError, match="injected"):
            draft.publish(session, who, row.key)
        session.commit()
        after = session.execute(
            select(func.count()).select_from(PlannerProject)).scalar_one()
        assert after == before
        assert session.execute(
            select(PlannerProject).where(
                PlannerProject.code == code)).scalar_one_or_none() is None
        # And the draft is still a draft, so the person can fix it and retry.
        assert draft.load(session, who, row.key).status == "DRAFTING"


def test_a_draft_is_published_once(people):
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        draft.publish(session, who, row.key)
        session.commit()
        with pytest.raises(draft.DraftError, match="already published"):
            draft.publish(session, who, row.key)


def test_a_published_draft_is_kept_not_deleted(people):
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_plan(people))
        session.commit()
        draft.publish(session, who, row.key)
        session.commit()
        with pytest.raises(draft.DraftError, match="record of what was"):
            draft.discard(session, who, row.key)


# ------------------------------------------------------------------ preview


def test_the_preview_shows_the_whole_plan(people):
    from backend.planner import draft

    plan = _plan(people)
    shown = draft.preview(plan)
    assert shown["totals"] == {"milestones": 2, "tasks": 3, "links": 1,
                               "people": 4}
    assert len(shown["milestones"]) == 2
    assert sum(len(m["tasks"]) for m in shown["milestones"]) == 3
    # Every item says who a delay reaches, including the inherited ones.
    assert all(m["escalation"]["user_id"] == people["hana"]
               for m in shown["milestones"])
    assert shown["agentic"]["sentence"]
    assert shown["completeness"]["publishable"] is True
