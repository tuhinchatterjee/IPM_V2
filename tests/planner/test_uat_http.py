"""The three routes the rebuilt screens depend on, through the application.

A step of the creation form that validates against a service call proves the
service validates. It does not prove the form can reach it, and every one of
these is reached by a screen that has no other way to answer its question.
"""

from __future__ import annotations

import uuid

from tests.planner.conftest import headers

PREFIX = "/api/v1/planner"


# --------------------------------------------------- §7 the duplicate code


def test_a_free_code_is_free_and_a_taken_one_names_its_project(
        client, cast, project):
    free = client.get(f"{PREFIX}/copilot/code-available",
                      params={"code": f"NEW-{uuid.uuid4().hex[:6].upper()}"},
                      headers=headers(cast["alice"]))
    assert free.status_code == 200, free.text
    assert free.json()["available"] is True

    taken = client.get(f"{PREFIX}/copilot/code-available",
                       params={"code": project["code"]},
                       headers=headers(cast["alice"]))
    assert taken.status_code == 200, taken.text
    assert taken.json()["available"] is False
    assert taken.json()["used_by"] == "Permission fixture project"


def test_a_code_check_is_not_a_way_to_read_a_project_you_are_not_on(
        client, cast, project):
    """Mallory learns the code is taken. She does not learn by what.

    The check exists so somebody is not told on step eight that their code
    collides. It is not a directory of everybody's projects, and the
    difference is one field.
    """
    asked = client.get(f"{PREFIX}/copilot/code-available",
                       params={"code": project["code"]},
                       headers=headers(cast["mallory"]))
    assert asked.status_code == 200, asked.text
    assert asked.json()["available"] is False
    assert asked.json()["used_by"] == "another project"


def test_an_empty_code_is_not_available_and_does_not_error(client, cast):
    asked = client.get(f"{PREFIX}/copilot/code-available",
                       params={"code": ""}, headers=headers(cast["alice"]))
    assert asked.status_code == 200, asked.text
    assert asked.json()["available"] is False


# -------------------------------------------------------- §17 the worklist


def test_needs_attention_is_scoped_to_what_the_caller_may_see(
        client, cast, project):
    mine = client.get(f"{PREFIX}/needs-attention",
                      headers=headers(cast["alice"]))
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert set(body) == {"items", "count", "projects"}

    theirs = client.get(f"{PREFIX}/needs-attention",
                        headers=headers(cast["mallory"]))
    assert theirs.status_code == 200, theirs.text
    ids = {row["project"]["id"] for row in theirs.json()["items"]}
    assert project["id"] not in ids


def test_every_attention_row_carries_what_it_takes_to_act_on_it(
        client, cast, project):
    """§17's field list, checked as a shape rather than as prose.

    A row missing its owner or its next action is a row that sends the reader
    back into the project to work out what it meant.
    """
    found = client.get(f"{PREFIX}/needs-attention",
                       headers=headers(cast["alice"])).json()
    for row in found["items"]:
        assert set(row["project"]) == {"id", "code", "name"}
        assert row["entity_type"]
        assert row["severity"] in ("critical", "warn")
        assert row["reason"]
        assert row["next_action"]
        assert row["escalation"]["state"] in (
            "none", "reminded", "escalated", "answered")
        assert row["escalation"]["said"]


# ------------------------------------------------- §21 what the agent did


def test_agent_activity_reads_as_project_management(client, cast, project):
    ran = client.post(f"{PREFIX}/projects/{project['id']}/sweep",
                      headers=headers(cast["alice"]))
    assert ran.status_code == 200, ran.text

    seen = client.get(f"{PREFIX}/projects/{project['id']}/agent-activity",
                      headers=headers(cast["alice"]))
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert set(body) == {"count", "kinds", "items"}
    for item in body["items"]:
        assert item["headline"]
        # No scheduler vocabulary reaches the screen: a person reading their
        # project's history should never meet `due_3` or a fingerprint.
        assert "fingerprint" not in item["headline"].lower()
        assert item["kind"] in (
            "reminder", "request", "escalation", "response", "health")


def test_agent_activity_refuses_a_project_the_caller_is_not_on(
        client, cast, project):
    refused = client.get(f"{PREFIX}/projects/{project['id']}/agent-activity",
                         headers=headers(cast["mallory"]))
    assert refused.status_code in (403, 404), refused.text


def test_a_viewer_cannot_run_the_agent(client, cast, project):
    """Carol reads everything and changes nothing, and a sweep sends messages."""
    refused = client.post(f"{PREFIX}/projects/{project['id']}/sweep",
                          headers=headers(cast["carol"], role="VIEWER"))
    assert refused.status_code in (403, 404), refused.text
