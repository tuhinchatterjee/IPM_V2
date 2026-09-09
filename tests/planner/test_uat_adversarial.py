"""The things a careless or hostile person does to the new creation flow.

`test_adversarial.py` covers the project routes. These are about the FORM and
the publish behind it: what it refuses, what it merely warns about, and what
it leaves behind when it fails.

Each name says what a person did, because that is what a reviewer is checking.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from tests.conftest import database_available
from tests.planner.conftest import headers

PREFIX = "/api/v1/planner"
COPILOT = f"{PREFIX}/copilot"


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


@dataclass
class Principal:
    user_id: int
    role: str = "ANALYST"


def _start(client, who: int) -> str:
    made = client.post(f"{COPILOT}/drafts", json={"name": ""},
                       headers=headers(who))
    assert made.status_code == 201, made.text
    return made.json()["key"]


def _apply(client, who: int, key: str, command: str, payload: dict):
    return client.post(f"{COPILOT}/drafts/{key}/apply",
                       json={"command": command, "payload": payload},
                       headers=headers(who))


def _blockers(client, who: int, key: str) -> list[dict]:
    found = client.get(f"{COPILOT}/drafts/{key}", headers=headers(who))
    assert found.status_code == 200, found.text
    return found.json()["completeness"]["blockers"]


def _complete(client, who: int, cast: dict[str, int]) -> str:
    """A publishable plan, built the way the form builds one."""
    key = _start(client, who)
    start = date.today()
    _apply(client, who, key, "set_overview", {
        "name": f"Adversarial {uuid.uuid4().hex[:6]}",
        "code": f"ADV{uuid.uuid4().hex[:6].upper()}",
        "description": "A plan built to be attacked.",
        "objective": "That it refuses the right things."})
    _apply(client, who, key, "set_governance", {
        "sponsor_id": cast["carol"], "manager_id": cast["alice"],
        "owner_id": cast["alice"], "escalation_id": cast["carol"],
        "start_date": start.isoformat(),
        "target_end_date": (start + timedelta(days=120)).isoformat()})
    _apply(client, who, key, "set_agentic", {"mode": "STANDARD"})
    _apply(client, who, key, "add_milestone", {
        "name": "Data foundation", "owner_id": cast["bob"],
        "start_date": start.isoformat(),
        "target_date": (start + timedelta(days=60)).isoformat()})
    for index, title in enumerate(("Extract", "Reconcile")):
        _apply(client, who, key, "add_task", {
            "milestone_code": "M01", "title": title,
            "description": f"{title} the data.", "owner_id": cast["bob"],
            "start_date": (start + timedelta(days=index * 20)).isoformat(),
            "due_date": (start + timedelta(days=index * 20 + 15)).isoformat()})
    return key


# ------------------------------------------------------ what publish refuses


def test_a_plan_with_no_sponsor_or_manager_cannot_be_published(client, cast):
    who = cast["alice"]
    key = _complete(client, who, cast)
    _apply(client, who, key, "set_governance",
           {"sponsor_id": None, "manager_id": None})

    messages = " ".join(n["message"] for n in _blockers(client, who, key))
    assert "no sponsor" in messages and "no manager" in messages

    refused = client.post(f"{COPILOT}/drafts/{key}/publish",
                          json={"confirm": True}, headers=headers(who))
    assert refused.status_code >= 400, refused.text
    assert "not ready" in refused.text.lower()


def test_a_plan_with_nobody_to_escalate_to_cannot_be_published(client, cast):
    who = cast["alice"]
    key = _complete(client, who, cast)
    _apply(client, who, key, "set_governance", {"escalation_id": None})

    messages = " ".join(n["message"] for n in _blockers(client, who, key))
    assert "nobody to escalate to" in messages
    refused = client.post(f"{COPILOT}/drafts/{key}/publish",
                          json={"confirm": True}, headers=headers(who))
    assert refused.status_code >= 400


def test_a_task_with_no_owner_stops_the_publish(client, cast):
    """The agent reminds the owner. A task with none is one nobody is asked
    about, which is worse than a task that does not exist."""
    who = cast["alice"]
    key = _complete(client, who, cast)
    _apply(client, who, key, "update_task",
           {"code": "M01-T01", "owner_id": None})

    stopping = [n for n in _blockers(client, who, key)
                if n["code"] == "M01-T01"]
    assert stopping and "no owner" in stopping[0]["message"]


def test_a_milestone_with_no_tasks_is_a_warning_and_not_a_blocker(client,
                                                                  cast):
    """A date with nothing behind it is a bad plan, not an invalid one, and a
    check that refused it would stop somebody laying a plan out top-down."""
    who = cast["alice"]
    key = _complete(client, who, cast)
    _apply(client, who, key, "add_milestone", {
        "name": "Nothing under this", "owner_id": cast["bob"],
        "start_date": date.today().isoformat(),
        "target_date": (date.today() + timedelta(days=90)).isoformat()})

    found = client.get(f"{COPILOT}/drafts/{key}",
                       headers=headers(who)).json()["completeness"]
    warnings = " ".join(n["message"] for n in found["warnings"])
    assert "no tasks under it" in warnings
    assert found["publishable"], "an empty milestone must not stop a publish"


def test_dates_that_run_backwards_are_refused_when_they_are_typed(client,
                                                                  cast):
    """Refused by the step that takes them, not carried to the publish.

    A form that accepted the date and told you on step eight would be the
    unstructured page again with extra clicks.
    """
    who = cast["alice"]
    key = _complete(client, who, cast)
    start = date.today()
    refused = _apply(client, who, key, "set_governance", {
        "start_date": start.isoformat(),
        "target_end_date": (start - timedelta(days=1)).isoformat()})
    assert refused.status_code >= 400, refused.text
    assert "before" in refused.text.lower()

    # And the good dates are still there: a refusal changes nothing.
    governance = client.get(f"{COPILOT}/drafts/{key}",
                            headers=headers(who)).json()["plan"]["governance"]
    assert governance["target_end_date"] > governance["start_date"]


# ------------------------------------------------------------ dependencies


def test_the_same_link_twice_is_refused_with_a_sentence(client, cast):
    who = cast["alice"]
    key = _complete(client, who, cast)
    first = _apply(client, who, key, "add_link",
                   {"predecessor": "M01-T01", "successor": "M01-T02"})
    assert first.status_code == 200, first.text

    again = _apply(client, who, key, "add_link",
                   {"predecessor": "M01-T01", "successor": "M01-T02"})
    assert again.status_code >= 400
    assert "already linked" in again.text


def test_something_cannot_wait_for_itself(client, cast):
    who = cast["alice"]
    key = _complete(client, who, cast)
    refused = _apply(client, who, key, "add_link",
                     {"predecessor": "M01-T01", "successor": "M01-T01"})
    assert refused.status_code >= 400
    assert "itself" in refused.text


def test_a_link_that_would_make_a_loop_changes_nothing(client, cast):
    who = cast["alice"]
    key = _complete(client, who, cast)
    _apply(client, who, key, "add_link",
           {"predecessor": "M01-T01", "successor": "M01-T02"})
    before = client.get(f"{COPILOT}/drafts/{key}",
                        headers=headers(who)).json()["plan"]["links"]

    refused = _apply(client, who, key, "add_link",
                     {"predecessor": "M01-T02", "successor": "M01-T01"})
    assert refused.status_code >= 400
    assert "loop" in refused.text.lower()

    after = client.get(f"{COPILOT}/drafts/{key}",
                       headers=headers(who)).json()["plan"]["links"]
    assert after == before


def test_adjusting_dates_on_a_link_with_no_conflict_is_refused(client, cast):
    """`adjust` moves committed dates. Asking for it where there is nothing to
    fix would move them for no reason, so it is an error rather than a no-op."""
    who = cast["alice"]
    key = _complete(client, who, cast)
    refused = _apply(client, who, key, "add_link",
                     {"predecessor": "M01-T01", "successor": "M01-T02",
                      "adjust": True})
    assert refused.status_code >= 400
    assert "nothing" in refused.text.lower()


# --------------------------------------------------------------- who may act


def test_a_stranger_cannot_read_or_change_somebody_elses_draft(client, cast):
    key = _complete(client, cast["alice"], cast)

    read = client.get(f"{COPILOT}/drafts/{key}",
                      headers=headers(cast["mallory"]))
    assert read.status_code in (403, 404), read.text

    changed = _apply(client, cast["mallory"], key, "set_overview",
                     {"name": "Mine now"})
    assert changed.status_code in (403, 404), changed.text

    published = client.post(f"{COPILOT}/drafts/{key}/publish",
                            json={"confirm": True},
                            headers=headers(cast["mallory"]))
    assert published.status_code in (403, 404), published.text


def test_a_viewer_cannot_publish_a_project_into_existence(client, cast):
    """Carol reads everything and changes nothing. Publishing creates a
    project, seats people on it and starts the agent chasing them."""
    refused = client.post(f"{COPILOT}/drafts",
                          json={"name": "A viewer's plan"},
                          headers=headers(cast["carol"], role="VIEWER"))
    assert refused.status_code in (401, 403), refused.text


def test_publishing_the_same_draft_twice_creates_one_project(client, cast):
    who = cast["alice"]
    key = _complete(client, who, cast)
    first = client.post(f"{COPILOT}/drafts/{key}/publish",
                        json={"confirm": True}, headers=headers(who))
    assert first.status_code == 201, first.text

    again = client.post(f"{COPILOT}/drafts/{key}/publish",
                        json={"confirm": True}, headers=headers(who))
    assert again.status_code >= 400
    assert "already published" in again.text.lower()


def test_publish_without_saying_yes_creates_nothing(client, cast):
    who = cast["alice"]
    key = _complete(client, who, cast)
    refused = client.post(f"{COPILOT}/drafts/{key}/publish",
                          json={"confirm": False}, headers=headers(who))
    assert refused.status_code >= 400, refused.text
    assert client.get(f"{COPILOT}/drafts/{key}",
                      headers=headers(who)).json()["status"] == "DRAFTING"


# ------------------------------------------------------------- all or nothing


def test_a_publish_that_fails_halfway_leaves_no_project(client, cast,
                                                        monkeypatch):
    """§13's atomicity, proved by breaking the last step rather than by
    reading the code that claims it.

    A half-created project is worse than none: somebody finds it on Monday and
    starts working on it.
    """
    from sqlalchemy import func, select

    from backend.db.engine import get_session
    from backend.models.planner import PlannerProject
    from backend.planner import draft as dr
    from backend.planner import service as svc

    who = Principal(cast["alice"])
    key = _complete(client, cast["alice"], cast)
    # The link is created last, so failing it means everything else already
    # exists inside the transaction.
    _apply(client, cast["alice"], key, "add_link",
           {"predecessor": "M01-T01", "successor": "M01-T02"})

    code = client.get(f"{COPILOT}/drafts/{key}",
                      headers=headers(cast["alice"])).json()["plan"][
        "overview"]["code"]

    def explode(*args, **kwargs):
        raise RuntimeError("the last dependency could not be written")

    monkeypatch.setattr(svc, "create_dependency", explode)

    with get_session() as session:
        with pytest.raises(RuntimeError):
            dr.publish(session, who, key)
        session.rollback()

    with get_session() as session:
        left = session.execute(
            select(func.count()).select_from(PlannerProject).where(
                func.lower(PlannerProject.code) == code.lower())).scalar()
    assert left == 0, f"a half-created project {code} was left behind"

    # And the draft is still a draft, so the person can try again.
    assert client.get(f"{COPILOT}/drafts/{key}",
                      headers=headers(cast["alice"])).json()[
        "status"] == "DRAFTING"


# ------------------------------------------------------------- the messages


def test_a_message_never_links_somebody_to_a_project_they_cannot_open(
        client, cast, project):
    """§20's deep link, checked from the recipient's side.

    Every planner message is addressed to somebody the plan names, and
    publishing seats everybody it names. A message whose link 404s for its own
    recipient would be the agent telling somebody to go and look at something
    they are not allowed to see.
    """
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Notification
    from backend.planner import access as acl
    from backend.planner import monitor

    with get_session() as session:
        monitor.sweep(session, project_ids=[project["id"]])
        session.commit()
        notes = [note for note in session.execute(
            select(Notification).where(
                Notification.kind == "planner")).scalars()
            # Only the messages this sweep can have produced. The table is
            # shared with every other test in the package, and asserting over
            # all of it would be asserting about their fixtures.
            if str(note.object_id or "").startswith(f"{project['id']}:")
            or str(note.object_id or "") == str(project["id"])]
        assert notes, "the sweep produced no message to check"
        for note in notes:
            project_id = int(str(note.object_id).split(":")[0])
            # `grant` REFUSES rather than returning false, so reaching the
            # next line at all is the assertion.
            acl.grant(session, project_id, Principal(int(note.user_id)))


def test_running_the_agent_twice_sends_one_message(client, cast, project):
    first = client.post(f"{PREFIX}/projects/{project['id']}/sweep",
                        headers=headers(cast["alice"]))
    assert first.status_code == 200, first.text
    second = client.post(f"{PREFIX}/projects/{project['id']}/sweep",
                         headers=headers(cast["alice"]))
    assert second.status_code == 200, second.text
    # Whatever the first run sent, the second suppressed rather than repeated.
    assert second.json()["sent"] == 0 or (
        second.json()["suppressed"] >= second.json()["sent"])
