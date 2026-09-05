"""The schedule through the running application, as the four people.

`test_schedule.py` proves the arithmetic. This proves the route: that it is
reachable, that it refuses a stranger the same way every other planner route
does, and that a project with no dependency network gets an explanation
rather than an empty answer.
"""

from __future__ import annotations

import uuid

import pytest

from tests.planner.conftest import PREFIX, headers


@pytest.fixture(scope="module")
def network(client, cast):
    """A project of this module's own, with a two-task chain in it.

    Deliberately not the shared `project` fixture: a critical path is a
    statement about the whole dependency graph, so a test that asserted "no
    dependencies" over a project another module had linked would fail for a
    reason that has nothing to do with the schedule.
    """
    tag = uuid.uuid4().hex[:6].upper()
    made = client.post(
        f"{PREFIX}/projects", headers=headers(cast["alice"]),
        json={"code": f"CPM-{tag}", "name": "Schedule fixture",
              "status": "ACTIVE", "manager_id": cast["alice"],
              "start_date": "2026-01-05", "target_end_date": "2026-12-18"})
    assert made.status_code == 201, made.text
    pid = made.json()["project"]["id"]

    for name, role, access in (("bob", "CONTRIBUTOR", "CONTRIBUTOR"),
                               ("carol", "REVIEWER", "VIEWER")):
        added = client.post(
            f"{PREFIX}/projects/{pid}/participants",
            headers=headers(cast["alice"]),
            json={"user_id": cast[name], "project_role": role,
                  "access": access})
        assert added.status_code == 200, added.text

    first = client.post(
        f"{PREFIX}/projects/{pid}/tasks", headers=headers(cast["alice"]),
        json={"code": "T-BOB", "title": "Bob's task", "owner_id": cast["bob"],
              "start_date": "2026-02-02", "due_date": "2026-03-02"})
    assert first.status_code == 201, first.text
    second = client.post(
        f"{PREFIX}/projects/{pid}/tasks", headers=headers(cast["alice"]),
        json={"code": "T-ALICE", "title": "Alice's task",
              "owner_id": cast["alice"],
              "start_date": "2026-02-02", "due_date": "2026-04-02"})
    assert second.status_code == 201, second.text
    return {"id": pid, "bob_task": first.json()["id"],
            "alice_task": second.json()["id"]}


def test_a_project_with_no_dependencies_is_told_why(client, cast, network):
    reply = client.get(f"{PREFIX}/projects/{network['id']}/schedule",
                       headers=headers(cast["alice"]))
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["computed"] is False
    assert body["cannot_because"], "a refusal with no reason is not a refusal"
    assert "No dependencies" in body["cannot_because"][0]
    assert body["critical_path"] == []


def test_the_path_calculates_once_a_dependency_exists(client, cast, network):
    made = client.post(
        f"{PREFIX}/projects/{network['id']}/dependencies",
        headers=headers(cast["alice"]),
        json={"predecessor_type": "TASK", "predecessor_id": network["bob_task"],
              "successor_type": "TASK", "successor_id": network["alice_task"],
              "dependency_type": "FS"})
    assert made.status_code in (200, 201), made.text

    reply = client.get(f"{PREFIX}/projects/{network['id']}/schedule",
                       headers=headers(cast["alice"]))
    body = reply.json()
    assert body["computed"] is True, body["cannot_because"]
    assert body["critical_path"] == ["T-BOB", "T-ALICE"]
    assert body["basis"] == "calendar_days"
    codes = {n["code"]: n for n in body["nodes"]}
    # T-BOB runs 2 Feb – 2 Mar; T-ALICE starts the day after and its own due
    # date is later than that, so the chain sets the finish.
    assert codes["T-ALICE"]["early_start"] == "2026-03-03"
    for node in body["nodes"]:
        assert "marked_critical" in node
        assert "calculated_critical" in node


def test_a_stranger_gets_a_404_not_a_403(client, cast, network):
    """The same rule as every other planner route: 403 confirms existence."""
    reply = client.get(f"{PREFIX}/projects/{network['id']}/schedule",
                       headers=headers(cast["mallory"]))
    assert reply.status_code == 404


def test_a_viewer_may_read_the_schedule(client, cast, network):
    reply = client.get(f"{PREFIX}/projects/{network['id']}/schedule",
                       headers=headers(cast["carol"], role="VIEWER"))
    assert reply.status_code == 200


def test_the_slip_question_is_answered_from_the_network(client, cast, network):
    reply = client.get(
        f"{PREFIX}/projects/{network['id']}/slip",
        params={"code": "T-BOB", "days": 2},
        headers=headers(cast["alice"]))
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["computed"] is True
    assert body["finish_moves_by"] == 2
    assert [m["code"] for m in body["moved"]] == ["T-ALICE"]


def test_a_task_outside_the_network_says_so(client, cast, network):
    reply = client.get(
        f"{PREFIX}/projects/{network['id']}/slip",
        params={"code": "NOT-A-TASK", "days": 1},
        headers=headers(cast["alice"]))
    assert reply.status_code == 200
    body = reply.json()
    assert body["computed"] is False
    assert body["cannot_because"]


def test_the_slip_route_refuses_a_stranger(client, cast, network):
    reply = client.get(
        f"{PREFIX}/projects/{network['id']}/slip",
        params={"code": "T-BOB", "days": 1},
        headers=headers(cast["mallory"]))
    assert reply.status_code == 404


def test_update_requests_are_scoped_to_projects_you_can_see(client, cast,
                                                            network):
    reply = client.get(f"{PREFIX}/requests", headers=headers(cast["mallory"]))
    assert reply.status_code == 200
    for row in reply.json()["requests"]:
        assert row["project_id"] != network["id"], \
            "a stranger read a chase list for a project she is not on"


def test_the_project_request_list_refuses_a_stranger(client, cast, network):
    reply = client.get(f"{PREFIX}/projects/{network['id']}/requests",
                       headers=headers(cast["mallory"]))
    assert reply.status_code == 404


def test_the_same_dependency_twice_is_a_sentence_not_a_stack_trace(
        client, cast, network):
    """The unique constraint reached the caller as a 500 with SQL in it.

    An ordinary mistake — two people linking the same pair, or an import run
    again — and the platform's rule is that no raw 500 reaches a user.
    """
    body = {"predecessor_type": "TASK", "predecessor_id": network["bob_task"],
            "successor_type": "TASK", "successor_id": network["alice_task"],
            "dependency_type": "FS"}
    again = client.post(f"{PREFIX}/projects/{network['id']}/dependencies",
                        headers=headers(cast["alice"]), json=body)
    assert again.status_code == 422, again.text
    assert "already waits on" in again.text
    assert "INSERT INTO" not in again.text
