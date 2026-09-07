"""The form-first creation flow, and what UAT said was missing from it.

Every test here corresponds to something a person tried in the running
application and could not do, or could do only by accident:

  * a dependency that overlapped two dates and offered no way to fix it;
  * a preview that could not say when the project would finish;
  * a project code found to be taken at the end of an eight-step form;
  * an attention list that named a project and left you to work out what
    about it needed you;
  * a reminder that did not say which project it was about.

They run against the real database and the real service layer, because the
claim being tested is about what the product does rather than about what a
function returns.
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
            row = User(username=f"uat-{name}-{tag}", password_hash="x",
                       role="ANALYST", first_name=name.title(),
                       last_name="Uat", email=f"uat-{name}-{tag}@example.invalid")
            session.add(row)
            session.flush()
            ids[name] = int(row.id)
        session.commit()
    return ids


def _overlapping(people: dict[str, int]) -> dict:
    """Two tasks whose dates overlap, so a link between them conflicts.

    M01-T02 starts the day M01-T01 is due, which is one day too early for a
    finish-to-start link: the successor cannot begin on the day its
    predecessor is still finishing.
    """
    from backend.planner import draft

    start = date.today()
    plan = draft.empty()
    plan["overview"] = {"name": f"LGD UAT {uuid.uuid4().hex[:6]}",
                        "code": f"UAT{uuid.uuid4().hex[:6].upper()}",
                        "description": "Rebuild the LGD model.",
                        "objective": "A validated model by year end."}
    plan["governance"] = {
        "sponsor_id": people["hana"], "manager_id": people["maya"],
        "owner_id": people["maya"], "escalation_id": people["hana"],
        "priority": "HIGH", "status": "ACTIVE",
        "start_date": start.isoformat(),
        "target_end_date": (start + timedelta(days=180)).isoformat(),
        "reporting_cadence": "WEEKLY"}
    plan["milestones"] = [
        {"code": "M01", "name": "Data foundation", "owner_id": people["omar"],
         "start_date": start.isoformat(),
         "target_date": (start + timedelta(days=60)).isoformat()},
    ]
    plan["tasks"] = [
        {"code": "M01-T01", "milestone_code": "M01", "title": "Extract data",
         "description": "Pull five years of recoveries.",
         "owner_id": people["omar"], "start_date": start.isoformat(),
         "due_date": (start + timedelta(days=20)).isoformat()},
        {"code": "M01-T02", "milestone_code": "M01", "title": "Reconcile",
         "description": "Tie back to the ledger.", "owner_id": people["omar"],
         "start_date": (start + timedelta(days=20)).isoformat(),
         "due_date": (start + timedelta(days=40)).isoformat()},
        {"code": "M01-T03", "milestone_code": "M01", "title": "Sign off",
         "description": "Data owner accepts the extract.",
         "owner_id": people["zaid"],
         "start_date": (start + timedelta(days=41)).isoformat(),
         "due_date": (start + timedelta(days=50)).isoformat()},
    ]
    plan["links"] = [{"predecessor": "M01-T02", "successor": "M01-T03",
                      "dependency_type": "FS", "lag_days": 0}]
    return plan


# ------------------------------------------------------- dependency impact


def test_a_link_says_which_dates_it_would_move_and_by_how_many_days(people):
    """§11. The impact is stated in items and days, not as "there may be one".

    A sentence saying two things overlap tells a person that something is
    wrong. It does not tell them what accepting the link would cost, which is
    the question they are actually being asked.
    """
    from backend.planner import draft

    plan = _overlapping(people)
    found = draft.link_preview(plan, "M01-T01", "M01-T02")

    assert found["conflict"], "the dates overlap and the preview says nothing"
    shift = found["adjustment"]
    assert shift["days"] == 1
    moved = {row["code"] for row in shift["items"]}
    # T02 moves because the link constrains it; T03 moves because it waits on
    # T02 and would otherwise inherit a new overlap nobody was shown.
    assert moved == {"M01-T02", "M01-T03"}
    assert "1 day" in shift["sentence"]


def test_a_preview_never_moves_a_date_by_being_asked_for(people):
    """Asking what a link would do is a question, not an instruction."""
    from backend.planner import draft

    plan = _overlapping(people)
    before = draft.item(plan, "M01-T02")["start_date"]
    draft.link_preview(plan, "M01-T01", "M01-T02")
    assert draft.item(plan, "M01-T02")["start_date"] == before


def test_adjusting_dates_moves_exactly_what_the_preview_named(people):
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_overlapping(people))
        session.commit()
        key = row.key
        was = {code: draft.item(row.plan, code)["due_date"]
               for code in ("M01-T02", "M01-T03")}

        draft.apply(session, who, key, "add_link",
                    {"predecessor": "M01-T01", "successor": "M01-T02",
                     "adjust": True})
        session.commit()

        plan = draft.load(session, who, key).plan
        for code, before in was.items():
            after = draft.item(plan, code)["due_date"]
            assert (date.fromisoformat(after)
                    - date.fromisoformat(before)).days == 1
        # And the link exists, with nothing flagged: the conflict was fixed
        # rather than recorded.
        link = draft.links_of(plan)[-1]
        assert (link["predecessor"], link["successor"]) == ("M01-T01",
                                                            "M01-T02")
        assert not link.get("notes")


def test_keeping_the_dates_flags_the_conflict_and_moves_nothing(people):
    """§11's middle answer, which is the one that has to survive to publish.

    A person who decides the overlap is acceptable is making a decision. If
    the product forgets it between the dialog and the publish, they made it
    for nothing.
    """
    from backend.db.engine import get_session
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_overlapping(people))
        session.commit()
        key = row.key
        was = draft.item(row.plan, "M01-T02")["start_date"]

        draft.apply(session, who, key, "add_link",
                    {"predecessor": "M01-T01", "successor": "M01-T02"})
        session.commit()
        plan = draft.load(session, who, key).plan

        assert draft.item(plan, "M01-T02")["start_date"] == was
        link = draft.links_of(plan)[-1]
        assert "Date conflict kept and flagged" in link["notes"]

        # It comes back on the way out, as a warning rather than a blocker:
        # this is a choice, not a mistake.
        warnings = [n.message for n in draft.check(plan).warnings]
        assert any("Date conflict kept and flagged" in w for w in warnings)


def test_a_flagged_conflict_reaches_the_published_dependency(people):
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.planner import PlannerDependency
    from backend.planner import draft

    who = Principal(people["maya"])
    with get_session() as session:
        row = draft.create(session, who, plan=_overlapping(people))
        session.commit()
        key = row.key
        draft.apply(session, who, key, "add_link",
                    {"predecessor": "M01-T01", "successor": "M01-T02"})
        session.commit()

        project = draft.publish(session, who, key)
        session.commit()
        notes = [d.notes for d in session.execute(
            select(PlannerDependency).where(
                PlannerDependency.project_id == int(project.id))).scalars()]
        assert any("Date conflict kept and flagged" in note for note in notes)


def test_a_link_that_would_make_a_loop_is_refused_before_anything_changes(
        people):
    from backend.planner import draft

    plan = _overlapping(people)          # T02 → T03 already exists
    with pytest.raises(draft.DraftError) as raised:
        draft.link_preview(plan, "M01-T03", "M01-T02")
    assert "loop" in str(raised.value).lower()
    assert len(draft.links_of(plan)) == 1


# ------------------------------------------------------------- the preview


def test_the_preview_carries_a_timeline_and_a_critical_path(people):
    """§12. The dates shown before publish are computed by the real engine."""
    from backend.planner import draft

    found = draft.preview(_overlapping(people))
    timeline = found["schedule"]
    assert timeline["computed"], timeline["cannot_because"]
    assert timeline["project_finish"]
    assert timeline["critical_path"]
    # The engine places what the dependencies touch: an unlinked task cannot
    # lengthen a chain, and demanding a duration for one would refuse a
    # perfectly computable path over an unrelated missing estimate.
    placed = {node["code"] for node in timeline["nodes"]}
    assert {"M01-T02", "M01-T03"} <= placed


def test_completeness_separates_what_stops_a_publish_from_what_does_not(
        people):
    """§13. Two lists, and a missing owner is not the same as a missing note."""
    from backend.planner import draft

    plan = _overlapping(people)
    plan["tasks"][0]["owner_id"] = None      # a blocker
    plan["tasks"][1]["description"] = ""     # a warning
    found = draft.check(plan)

    assert not found.publishable
    assert any("no owner" in note.message for note in found.blockers)
    assert any("no description" in note.message for note in found.warnings)


# ------------------------------------------------------------- escalations


def test_the_ladder_says_where_each_escalation_was_decided(people):
    """§8. "Inherited from milestone M01" is checkable; "Priya" is not."""
    from backend.planner import draft

    plan = _overlapping(people)
    plan["milestones"][0]["escalation_id"] = people["zaid"]

    task = draft.escalation_for(plan, "M01-T01")
    assert task == {"user_id": people["zaid"], "source": "milestone",
                    "from_code": "M01"}

    plan["tasks"][0]["escalation_id"] = people["omar"]
    assert draft.escalation_for(plan, "M01-T01")["source"] == "own"

    # And with neither, it falls to the project's contact.
    plan["milestones"][0]["escalation_id"] = None
    plan["tasks"][0]["escalation_id"] = None
    assert draft.escalation_for(plan, "M01-T01") == {
        "user_id": people["hana"], "source": "project", "from_code": ""}


# ------------------------------------------------------ needs attention §17


def test_needs_attention_says_what_to_do_about_each_thing(people):
    """One row per issue, with an owner, a date, a reason and a next action.

    The list this replaces named a project and three finding sentences, which
    told a reader that something was wrong somewhere inside it.
    """
    from backend.db.engine import get_session
    from backend.planner import draft, query

    who = Principal(people["maya"])
    plan = _overlapping(people)
    # One task that is unambiguously late.
    plan["tasks"][0]["due_date"] = (date.today() - timedelta(days=9)
                                    ).isoformat()
    plan["tasks"][0]["start_date"] = (date.today() - timedelta(days=30)
                                      ).isoformat()
    with get_session() as session:
        row = draft.create(session, who, plan=plan)
        session.commit()
        project = draft.publish(session, who, row.key)
        session.commit()
        pid = int(project.id)

        found = query.needs_attention(session, who, limit=50)
        mine = [item for item in found["items"]
                if item["project"]["id"] == pid]
        assert mine, "an overdue task produced no attention row"

        overdue = next(item for item in mine if item["rule"] == "overdue")
        assert overdue["entity_code"] == "M01-T01"
        assert overdue["owner"]["id"] == people["omar"]
        assert overdue["due_date"]
        assert "overdue" in overdue["reason"].lower()
        assert overdue["next_action"]
        # Nobody has chased it yet, and the row says so rather than leaving
        # the column blank.
        assert overdue["escalation"]["state"] == "none"
        assert overdue["escalation"]["said"]


# --------------------------------------------------------- the message §20


def test_every_message_names_the_project_the_owner_and_the_date(people):
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Notification
    from backend.planner import draft, monitor

    who = Principal(people["maya"])
    plan = _overlapping(people)
    plan["tasks"][0]["due_date"] = (date.today() - timedelta(days=4)
                                    ).isoformat()
    plan["tasks"][0]["start_date"] = (date.today() - timedelta(days=30)
                                      ).isoformat()
    with get_session() as session:
        row = draft.create(session, who, plan=plan)
        session.commit()
        project = draft.publish(session, who, row.key)
        session.commit()
        name, code = project.name, project.code

        monitor.sweep(session, project_ids=[int(project.id)])
        session.commit()

        bodies = [n.body for n in session.execute(
            select(Notification).where(
                Notification.user_id == people["omar"],
                Notification.kind == "planner")).scalars()
            if code in n.title]
        assert bodies, "the overdue task produced no message"
        body = bodies[0]
        assert f"Project: {name} ({code})" in body
        assert "Item: M01-T01" in body
        assert "Owner: Omar Uat" in body
        assert f"Due: {plan['tasks'][0]['due_date']}" in body
        assert f"Open: /delivery/{int(project.id)}" in body


def test_running_the_agent_twice_does_not_send_the_message_twice(people):
    """§20's deduplication, checked against the message table rather than a
    counter the sweep returns about itself."""
    from sqlalchemy import func, select

    from backend.db.engine import get_session
    from backend.models.platform import Notification
    from backend.planner import draft, monitor

    who = Principal(people["maya"])
    plan = _overlapping(people)
    plan["tasks"][0]["due_date"] = (date.today() - timedelta(days=6)
                                    ).isoformat()
    plan["tasks"][0]["start_date"] = (date.today() - timedelta(days=30)
                                      ).isoformat()
    with get_session() as session:
        row = draft.create(session, who, plan=plan)
        session.commit()
        project = draft.publish(session, who, row.key)
        session.commit()
        pid = int(project.id)

        def sent() -> int:
            return int(session.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.kind == "planner",
                    Notification.title.like(f"{project.code}:%"))).scalar())

        monitor.sweep(session, project_ids=[pid])
        session.commit()
        after_one = sent()
        assert after_one > 0

        second = monitor.sweep(session, project_ids=[pid])
        session.commit()
        assert sent() == after_one
        assert second.suppressed >= 1
