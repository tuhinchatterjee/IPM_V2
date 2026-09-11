"""Custom is a policy, not a label. §11.

Choosing Custom used to select a word and leave the thresholds on Standard,
which is the worst of the four answers available: the screen says the policy
is yours and the agent behaves as though it is not. These tests say what
Custom has to do — be settable, be refused when it would not mean what it
says, survive a publish, and change what the monitor actually does.
"""

from __future__ import annotations

import uuid

import pytest

from backend.planner import draft as dr
from backend.planner import policy as pol
from tests.planner.conftest import headers

PREFIX = "/api/v1/planner"


# ------------------------------------------------------- the panel's fields


def test_every_field_the_panel_shows_is_a_field_the_policy_has():
    """A control for a threshold `custom()` would refuse is a dead control."""
    shown = {row["key"] for row in pol.settings()}
    assert shown == set(pol.CUSTOM_KEYS)


def test_every_field_carries_the_bound_the_server_will_enforce():
    for row in pol.settings():
        if row["kind"] == "flag" or row["key"] == "reminder_days":
            assert row["minimum"] is None and row["maximum"] is None
            continue
        assert isinstance(row["minimum"], int)
        assert isinstance(row["maximum"], int)
        assert row["minimum"] <= row["maximum"]


def test_every_field_starts_at_the_standard_value():
    """Custom is built on Standard, so the panel opens on what it inherits."""
    standard = pol.describe(pol.preset(pol.MODE_STANDARD))
    for row in pol.settings():
        assert row["default"] == standard[row["key"]], row["key"]


# --------------------------------------------------------- setting it, live


@pytest.fixture
def key(client, cast) -> str:
    made = client.post(f"{PREFIX}/copilot/drafts",
                       headers=headers(cast["alice"]),
                       json={"name": f"Custom {uuid.uuid4().hex[:6]}"})
    assert made.status_code == 201, made.text
    return made.json()["key"]


def _set(client, cast, key: str, policy: dict):
    return client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                       headers=headers(cast["alice"]),
                       json={"command": "set_agentic",
                             "payload": {"mode": "CUSTOM", "policy": policy}})


def test_thresholds_are_stored_reloaded_and_read_back_in_words(
        client, cast, key):
    wanted = {"reminder_days": [10, 5, 1], "escalate_after_days": 1,
              "overdue_every_days": 2, "notify_sponsor_after_days": 4,
              "remind_reviewers": False}
    assert _set(client, cast, key, wanted).status_code == 200

    found = client.get(f"{PREFIX}/copilot/drafts/{key}",
                       headers=headers(cast["alice"])).json()
    assert found["plan"]["agentic"]["mode"] == "CUSTOM"
    assert found["plan"]["agentic"]["policy"] == wanted

    said = found["agentic_policy"]
    assert said["mode"] == "CUSTOM"
    assert said["reminder_days"] == [10, 5, 1]
    assert said["escalate_after_days"] == 1
    assert "10, 5 and 1 days before the due date" in said["sentence"]
    assert "every 2 days" in said["sentence"]
    assert "Reviewers are not reminded" in said["sentence"]


def test_never_is_stored_as_never_rather_than_as_nothing(client, cast, key):
    assert _set(client, cast, key,
                {"escalate_after_days": None}).status_code == 200
    found = client.get(f"{PREFIX}/copilot/drafts/{key}",
                       headers=headers(cast["alice"])).json()
    assert found["plan"]["agentic"]["policy"]["escalate_after_days"] is None
    assert "Lateness alone is never escalated automatically." in \
        found["agentic_policy"]["sentence"]


def test_a_threshold_outside_its_bounds_is_refused_with_a_reason(
        client, cast, key):
    refused = _set(client, cast, key, {"overdue_every_days": 400})
    assert refused.status_code == 422, refused.text
    assert "between 1 and 30" in refused.json()["detail"]["message"]


def test_a_combination_that_cannot_mean_what_it_says_is_refused(
        client, cast, key):
    refused = _set(client, cast, key, {"escalate_after_days": 5,
                                       "notify_sponsor_after_days": 1})
    assert refused.status_code == 422, refused.text
    assert "sponsor" in refused.json()["detail"]["message"].lower()


def test_a_field_the_policy_does_not_have_is_refused(client, cast, key):
    refused = _set(client, cast, key, {"chase_everybody_always": 1})
    assert refused.status_code == 422, refused.text
    assert "chase_everybody_always" in refused.json()["detail"]["message"]


# ------------------------------------------------------ it reaches the agent


def test_a_published_project_carries_the_custom_thresholds(client, cast, key):
    """And carries them as the document, not as the preset they came from."""
    who = cast["alice"]
    for command, payload in (
            ("set_overview", {"name": "Custom policy project",
                              "code": f"CUS-{uuid.uuid4().hex[:6].upper()}",
                              "description": "x", "objective": "y"}),
            ("set_governance", {"sponsor_id": who, "manager_id": who,
                                "owner_id": who, "escalation_id": who,
                                "start_date": "2026-02-02",
                                "target_end_date": "2026-09-30"}),
            ("set_agentic", {"mode": "CUSTOM",
                             "policy": {"reminder_days": [21, 14],
                                        "escalate_after_days": 1,
                                        "overdue_every_days": 2}}),
            ("add_milestone", {"name": "Only milestone", "owner_id": who,
                               "start_date": "2026-02-02",
                               "target_date": "2026-06-30"}),
            ("add_task", {"milestone_code": "M01", "title": "Only task",
                          "owner_id": who, "description": "z",
                          "start_date": "2026-02-02",
                          "due_date": "2026-03-02"})):
        done = client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                           headers=headers(who),
                           json={"command": command, "payload": payload})
        assert done.status_code == 200, done.text

    made = client.post(f"{PREFIX}/copilot/drafts/{key}/publish",
                       headers=headers(who), json={"confirm": True})
    assert made.status_code == 201, made.text

    from backend.db.engine import get_session
    from backend.models.planner import PlannerProject

    with get_session() as session:
        project = session.get(PlannerProject, made.json()["project_id"])
        assert project.agentic_mode == "CUSTOM"
        assert project.agentic_policy["reminder_days"] == [21, 14]
        # And what the agent will actually read off the row:
        agentic = pol.of(project)
        assert agentic.mode == "CUSTOM"
        assert agentic.policy.reminder_days == (21, 14)
        assert agentic.escalation.escalate_after_days == 1
        assert agentic.escalation.overdue_every_days == 2


def test_the_monitor_obeys_a_custom_threshold_a_preset_would_not():
    """The same project, one day overdue: Standard waits, this Custom does not.

    Run against the rules directly, because the claim is about the rules. A
    Custom policy that produced the same findings as the preset it was built
    on would be a setting nobody could tell was on.
    """
    from datetime import date, datetime, time, timedelta

    from backend.planner import control
    from backend.planner import escalation as esc

    today = date(2026, 9, 6)
    midnight = datetime.combine(today, time.min)

    class Project:
        id, code, name = 100, "CUS", "Custom"
        escalation_id, manager_id, sponsor_id = 4, 5, 6
        agentic_mode, agentic_policy = pol.MODE_STANDARD, {}
        reminder_days = stale_after_days = None

    class Milestone:
        id, code, name = 10, "M01", "Only"
        owner_id, escalation_id = 1, 3
        target_date, status = None, "PENDING"

    task = control.TaskView(
        id=1, code="M01-T01", title="Only task", status="IN_PROGRESS",
        percent_complete=40, due_date=today - timedelta(days=1), owner_id=1,
        blocked=False, blocker_reason="",
        last_update_at=midnight.replace(tzinfo=None).astimezone(),
        milestone_id=10, critical=False)
    plan = control.Plan(project_id=100, tasks=[task])

    def escalated(agentic):
        return [f for f in esc.findings(Project(), plan, [Milestone()], today,
                                        agentic=agentic,
                                        critical_codes=frozenset())
                if f.trigger == esc.ESCALATED]

    assert not escalated(pol.preset(pol.MODE_STANDARD))
    assert escalated(pol.custom({"escalate_after_days": 1}))


def test_the_draft_refuses_to_be_left_holding_an_invalid_policy():
    """A stored policy the engine would reject blocks publish, loudly."""
    plan = dr.empty()
    plan["agentic"] = {"mode": "CUSTOM", "policy": {"overdue_every_days": 0}}
    said = [note.message for note in dr.check(plan).blockers]
    assert any("monitoring policy is not valid" in message
               for message in said)
