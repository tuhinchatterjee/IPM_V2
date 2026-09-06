"""Changing a project that already exists, by saying so.

The draft tests prove a plan can be talked into being. This proves the half
that matters a month later: the project is running, somebody has left, a date
has moved, and the person who has to change it says so in the box rather than
finding the right field on the right tab.

Everything here goes through `/planner/copilot/chat` with a `project_id` and
asserts against the DATABASE afterwards — never against the Copilot's own
reply. A chat that convinced itself is exactly the failure this file exists
to catch.

The four claims:

  * a sentence about a running project changes the running project;
  * nothing changes until the person confirms it, additions included,
    because on a live project every change moves a commitment;
  * the change goes through the ordinary service layer, so the permission
    check, the history entry and the AI_CHAT audit row all happen;
  * what the service layer will not do, this will not do either — a viewer
    cannot move a task by asking politely.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from tests.planner.conftest import headers

PREFIX = "/api/v1/planner/copilot"
PLANNER = "/api/v1/planner"


@pytest.fixture(scope="module")
def named() -> dict[str, dict]:
    """Two colleagues with names nothing else in the database shares."""
    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:6]
    people: dict[str, dict] = {}
    with get_session() as session:
        for role in ("rohan", "daniel", "ananya"):
            first = f"{role.title()}{tag}"
            row = User(username=f"live-{role}-{tag}", password_hash="x",
                       role="ANALYST", first_name=first, last_name="Live",
                       email=f"live-{role}-{tag}@example.invalid")
            session.add(row)
            session.flush()
            people[role] = {"user_id": int(row.id), "first": first,
                            "name": f"{first} Live"}
        session.commit()
    return people


def _apply(client, who: int, key: str, command: str, payload: dict) -> dict:
    sent = client.post(f"{PREFIX}/drafts/{key}/apply",
                       json={"command": command, "payload": payload},
                       headers=headers(who))
    assert sent.status_code == 200, sent.text
    return sent.json()


@pytest.fixture()
def live(client, cast, named) -> dict:
    """A published project, built and published the way a person would.

    Published through the Copilot rather than inserted, so the codes, the
    milestone grouping and the escalation ladder are the real ones and a
    sentence naming `M01-T02` is naming what the product actually created.
    """
    who = cast["alice"]
    tag = uuid.uuid4().hex[:6].upper()
    made = client.post(f"{PREFIX}/drafts", json={"name": ""},
                       headers=headers(who))
    assert made.status_code == 201, made.text
    key = made.json()["key"]

    _apply(client, who, key, "set_overview", {
        "name": f"Recovery Refresh {tag}", "code": f"REC-{tag}",
        "description": "Refresh the recovery curves.",
        "objective": "A validated set of curves by the year end."})
    _apply(client, who, key, "set_governance", {
        "sponsor_id": named["ananya"]["user_id"], "manager_id": who,
        "owner_id": who, "escalation_id": named["ananya"]["user_id"],
        "start_date": "2026-10-01", "target_end_date": "2027-03-31",
        "priority": "HIGH"})
    _apply(client, who, key, "set_agentic", {"mode": "STANDARD"})
    _apply(client, who, key, "add_milestone", {
        "name": "Data Foundation", "owner_id": named["rohan"]["user_id"],
        "start_date": "2026-10-01", "target_date": "2026-12-15"})
    _apply(client, who, key, "add_task", {
        "milestone_code": "M01", "title": "Data Extraction",
        "description": "Five years of recovery history.",
        "owner_id": named["rohan"]["user_id"],
        "start_date": "2026-10-01", "due_date": "2026-11-01"})
    _apply(client, who, key, "add_task", {
        "milestone_code": "M01", "title": "Data Reconciliation",
        "description": "Tie back to the ledger.",
        "owner_id": named["rohan"]["user_id"],
        "start_date": "2026-11-02", "due_date": "2026-12-01"})

    published = client.post(f"{PREFIX}/drafts/{key}/publish",
                            json={"confirm": True}, headers=headers(who))
    assert published.status_code == 201, published.text
    project_id = int(published.json()["project_id"])

    # Everybody who will be named in a sentence below has to be on the
    # project, or the refusal under test would be an access refusal instead.
    for person in ("daniel",):
        added = client.post(
            f"{PLANNER}/projects/{project_id}/participants",
            headers=headers(who),
            json={"user_id": named[person]["user_id"],
                  "project_role": "CONTRIBUTOR", "access": "CONTRIBUTOR"})
        assert added.status_code == 200, added.text
    return {"id": project_id, "code": published.json()["code"], "key": key}


def _say(client, who: int, project_id: int, message: str, *,
         confirm: bool = False) -> dict:
    said = client.post(f"{PREFIX}/chat", headers=headers(who),
                       json={"message": message, "project_id": project_id,
                             "confirm": confirm})
    assert said.status_code == 200, said.text
    return said.json()


def _task(project_id: int, code: str):
    from backend.db.engine import get_session
    from backend.models.planner import PlannerTask

    with get_session() as session:
        return session.execute(
            select(PlannerTask).where(
                PlannerTask.project_id == int(project_id),
                PlannerTask.code == code)).scalar_one()


def _project(project_id: int):
    from backend.db.engine import get_session
    from backend.models.planner import PlannerProject

    with get_session() as session:
        return session.get(PlannerProject, int(project_id))


# ------------------------------------------------------------ the projection


def test_the_project_reads_back_as_the_plan_the_reader_speaks(client, cast,
                                                              live, named):
    """§9's other half: the conversation sees what the project page sees."""
    turn = _say(client, cast["alice"], live["id"], "What is still missing?")
    plan = turn["project_plan"]

    assert plan["overview"]["code"] == live["code"]
    assert [m["code"] for m in plan["milestones"]] == ["M01"]
    assert [t["code"] for t in plan["tasks"]] == ["M01-T01", "M01-T02"]
    assert plan["tasks"][0]["milestone_code"] == "M01", \
        "a task that lost its milestone cannot be escalated through it"
    assert plan["governance"]["escalation_id"] == named["ananya"]["user_id"]
    assert plan["agentic"]["mode"] == "STANDARD"


# ---------------------------------------------------------- moving the work


def test_moving_a_task_to_somebody_else_by_saying_so(client, cast, live,
                                                     named):
    who, daniel = cast["alice"], named["daniel"]

    asked = _say(client, who, live["id"],
                 f"Move M01-T02 to {daniel['first']}.")
    assert asked["needs_confirmation"] is True, asked
    assert asked["applied"] == []
    assert _task(live["id"], "M01-T02").owner_id != daniel["user_id"], \
        "the preview moved the task, which makes the preview a change"

    done = _say(client, who, live["id"],
                f"Move M01-T02 to {daniel['first']}.", confirm=True)
    assert done["needs_confirmation"] is False
    assert [c["command"] for c in done["applied"]] == ["update_task"]
    assert _task(live["id"], "M01-T02").owner_id == daniel["user_id"]


def test_a_date_moves_and_the_project_records_who_moved_it(client, cast,
                                                           live):
    from backend.db.engine import get_session
    from backend.models.planner import SOURCE_AI_CHAT, PlannerUpdate

    _say(client, cast["alice"], live["id"],
         "M01-T01 is due on 20 November.", confirm=True)

    task = _task(live["id"], "M01-T01")
    assert str(task.due_date) == "2026-11-20"

    with get_session() as session:
        rows = list(session.execute(
            select(PlannerUpdate).where(
                PlannerUpdate.project_id == int(live["id"]),
                PlannerUpdate.entity_code == "M01-T01",
                PlannerUpdate.source == SOURCE_AI_CHAT)).scalars())
    assert rows, "a change made by chat left no trace on the project"
    assert any("due_date" in (r.changes or {}) for r in rows), \
        [r.changes for r in rows]


def test_the_monitoring_mode_changes_and_takes_its_own_numbers(client, cast,
                                                               live):
    """"Change this project's monitoring to Critical", end to end.

    Asserting the reminder days as well as the mode, because a mode that
    changed the label and left the cadence at the creation default would be
    the same silent half-change `policy.stamp` exists to prevent.
    """
    _say(client, cast["alice"], live["id"],
         "Change this project's monitoring to Critical.", confirm=True)

    project = _project(live["id"])
    assert project.agentic_mode == "CRITICAL"
    assert project.reminder_days == [14, 7, 3, 1, 0]
    assert project.stale_after_days == 3


def test_a_task_and_a_dependency_can_be_added_in_conversation(client, cast,
                                                              live, named):
    _say(client, cast["alice"], live["id"],
         "Under Data Foundation add Data Quality Review.", confirm=True)
    added = _task(live["id"], "M01-T03")
    assert added.title == "Data Quality Review"
    assert added.milestone_id is not None, \
        "a task added by chat must hang off the milestone it was put under"

    _say(client, cast["alice"], live["id"],
         "Link Data Quality Review to Data Reconciliation.", confirm=True)

    from backend.db.engine import get_session
    from backend.models.planner import PlannerDependency

    with get_session() as session:
        links = list(session.execute(
            select(PlannerDependency).where(
                PlannerDependency.project_id == int(live["id"]))).scalars())
    assert links, "the dependency was not made"
    assert {int(link.successor_id) for link in links} == {int(added.id)}


# ------------------------------------------------------------- the refusals


def test_a_viewer_cannot_move_a_task_by_asking_politely(client, cast, live,
                                                        named):
    """§40. The reader is not authorization; the service layer is."""
    added = client.post(
        f"{PLANNER}/projects/{live['id']}/participants",
        headers=headers(cast["alice"]),
        json={"user_id": cast["carol"], "project_role": "REVIEWER",
              "access": "VIEWER"})
    assert added.status_code == 200, added.text

    before = _task(live["id"], "M01-T01").owner_id
    refused = client.post(
        f"{PREFIX}/chat", headers=headers(cast["carol"]),
        json={"message": f"Move M01-T01 to {named['daniel']['first']}.",
              "project_id": live["id"], "confirm": True})
    assert refused.status_code == 403, refused.text
    assert _task(live["id"], "M01-T01").owner_id == before


def test_a_stranger_cannot_even_see_the_project_to_talk_about_it(client, cast,
                                                                 live):
    refused = client.post(
        f"{PREFIX}/chat", headers=headers(cast["mallory"]),
        json={"message": "What is overdue here?", "project_id": live["id"]})
    assert refused.status_code == 404, refused.text


def test_removing_a_milestone_is_refused_with_a_reason(client, cast, live):
    """Not a stack trace and not a silent no-op: a sentence and a next step."""
    said = client.post(
        f"{PREFIX}/chat", headers=headers(cast["alice"]),
        json={"message": "Remove the Data Foundation milestone.",
              "project_id": live["id"], "confirm": True})
    assert said.status_code == 400, said.text
    detail = said.json()["detail"]
    message = detail["message"] if isinstance(detail, dict) else str(detail)
    assert "orphaned" in message.lower() or "milestones tab" in message.lower(), \
        message

    from backend.db.engine import get_session
    from backend.models.planner import PlannerMilestone

    with get_session() as session:
        still = session.execute(
            select(PlannerMilestone).where(
                PlannerMilestone.project_id == int(live["id"]))).scalars()
        assert [m.code for m in still] == ["M01"]


def test_the_boundary_still_holds_on_a_project(client, cast, live):
    """A scorecard question is refused even with a project in hand."""
    said = _say(client, cast["alice"], live["id"],
                "What is the gini of the application scorecard?")
    assert said["in_scope"] is False
    assert "Scorecard Validation" in said["message"], said["message"]
