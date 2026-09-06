"""The Copilot through the real application, because the routes are the product.

A service called directly with a hand-made principal proves the service
checks. It does not prove the route does, and §40's whole point is that the
LLM is not authorization — which is a claim about the edge, not the middle.
So every test here goes through `TestClient`, and the only thing that varies
is the header naming who is calling.
"""

from __future__ import annotations

import uuid

from tests.planner.conftest import headers

PREFIX = "/api/v1/planner/copilot"


def _start(client, who: int, name: str = "") -> str:
    made = client.post(f"{PREFIX}/drafts", json={"name": name},
                       headers=headers(who))
    assert made.status_code == 201, made.text
    return made.json()["key"]


def _complete(client, who: int, key: str, cast: dict[str, int]) -> None:
    """Fill a draft in until it is publishable, one command at a time."""
    def apply(command: str, payload: dict) -> dict:
        sent = client.post(f"{PREFIX}/drafts/{key}/apply",
                           json={"command": command, "payload": payload},
                           headers=headers(who))
        assert sent.status_code == 200, sent.text
        return sent.json()

    apply("set_overview", {"name": f"LGD Redevelopment {uuid.uuid4().hex[:6]}",
                           "code": f"LGD{uuid.uuid4().hex[:6].upper()}",
                           "description": "Rebuild the LGD model.",
                           "objective": "A validated model by year end."})
    apply("set_governance", {
        "sponsor_id": cast["carol"], "manager_id": cast["alice"],
        "owner_id": cast["alice"], "escalation_id": cast["carol"],
        "start_date": "2026-10-01", "target_end_date": "2027-06-30",
        "priority": "HIGH"})
    apply("set_agentic", {"mode": "STANDARD"})
    apply("add_milestone", {"name": "Data foundation", "owner_id": cast["bob"],
                            "start_date": "2026-10-01",
                            "target_date": "2026-12-15"})
    apply("add_task", {"milestone_code": "M01", "title": "Extract recoveries",
                       "description": "Five years of recovery history.",
                       "owner_id": cast["bob"], "start_date": "2026-10-01",
                       "due_date": "2026-11-01"})
    apply("add_task", {"milestone_code": "M01", "title": "Reconcile",
                       "description": "Tie back to the ledger.",
                       "owner_id": cast["bob"], "start_date": "2026-11-02",
                       "due_date": "2026-12-01"})


# ------------------------------------------------------------- the boundary


def test_capabilities_names_the_allowlist(client, cast):
    shown = client.get(f"{PREFIX}/capabilities", headers=headers(cast["bob"]))
    assert shown.status_code == 200
    body = shown.json()
    assert body["agent"]["allowed_data_domains"] == []
    assert all(t["tool_id"].startswith("planner_") for t in body["tools"])
    assert {a["area"] for a in body["out_of_scope"]} >= {
        "ifrs9", "scorecard", "early_warning", "lenses", "playbook"}


def test_an_out_of_domain_question_is_refused_by_the_route(client, cast):
    asked = client.post(f"{PREFIX}/chat",
                        json={"message": "What is the ECL for stage 2?"},
                        headers=headers(cast["alice"]))
    assert asked.status_code == 200
    body = asked.json()
    assert body["in_scope"] is False
    assert "IFRS 9" in body["message"]
    # No draft, no tool, no model: a refusal is a cheap answer.
    assert "draft" not in body


def test_a_delivery_question_reaches_the_copilot(client, cast):
    asked = client.post(f"{PREFIX}/chat",
                        json={"message": "What is overdue this week?"},
                        headers=headers(cast["alice"]))
    assert asked.status_code == 200
    assert asked.json()["in_scope"] is True


def test_the_scope_route_explains_itself(client, cast):
    checked = client.post(
        f"{PREFIX}/scope",
        json={"message": "Show me the gini of the application scorecard."},
        headers=headers(cast["alice"]))
    assert checked.status_code == 200
    body = checked.json()
    assert body["in_scope"] is False
    assert body["area"] == "scorecard"
    assert body["matched"] == "gini"


# ------------------------------------------------------------------ drafts


def test_a_draft_is_built_one_command_at_a_time(client, cast):
    key = _start(client, cast["alice"], "LGD Model Redevelopment")
    read = client.get(f"{PREFIX}/drafts/{key}", headers=headers(cast["alice"]))
    assert read.status_code == 200
    body = read.json()
    assert body["code"].startswith("LMR-")
    assert body["completeness"]["publishable"] is False
    assert body["agentic_choices"]

    _complete(client, cast["alice"], key, cast)
    read = client.get(f"{PREFIX}/drafts/{key}", headers=headers(cast["alice"]))
    assert read.json()["completeness"]["publishable"] is True


def test_a_draft_is_private_to_its_author(client, cast):
    key = _start(client, cast["alice"], "Private plan")
    denied = client.get(f"{PREFIX}/drafts/{key}", headers=headers(cast["bob"]))
    assert denied.status_code == 403
    mine = client.get(f"{PREFIX}/drafts", headers=headers(cast["bob"]))
    assert all(row["key"] != key for row in mine.json()["drafts"])


def test_an_unknown_command_is_a_422_with_a_sentence(client, cast):
    key = _start(client, cast["alice"])
    refused = client.post(f"{PREFIX}/drafts/{key}/apply",
                          json={"command": "drop_database", "payload": {}},
                          headers=headers(cast["alice"]))
    assert refused.status_code == 422
    assert "do not know how to" in refused.json()["detail"]["message"]


def test_a_stale_write_is_a_409(client, cast):
    key = _start(client, cast["alice"])
    read = client.get(f"{PREFIX}/drafts/{key}", headers=headers(cast["alice"]))
    stale = read.json()["version"]
    client.post(f"{PREFIX}/drafts/{key}/apply",
                json={"command": "set_step", "payload": {"step": "TASKS"}},
                headers=headers(cast["alice"]))
    clash = client.post(
        f"{PREFIX}/drafts/{key}/apply",
        json={"command": "set_step", "payload": {"step": "REVIEW"},
              "expected_version": stale},
        headers=headers(cast["alice"]))
    assert clash.status_code == 409


def test_an_incoherent_policy_is_refused_in_words(client, cast):
    key = _start(client, cast["alice"])
    refused = client.post(
        f"{PREFIX}/drafts/{key}/apply",
        json={"command": "set_agentic",
              "payload": {"mode": "CUSTOM",
                          "policy": {"escalate_after_days": 10,
                                     "notify_sponsor_after_days": 2}}},
        headers=headers(cast["alice"]))
    assert refused.status_code == 422
    assert "sponsor" in refused.json()["detail"]["message"]


# ------------------------------------------------------------ dependencies


def test_a_link_states_itself_before_it_exists(client, cast):
    key = _start(client, cast["alice"])
    _complete(client, cast["alice"], key, cast)
    shown = client.post(f"{PREFIX}/drafts/{key}/link-preview",
                        json={"predecessor": "M01-T01",
                              "successor": "M01-T02"},
                        headers=headers(cast["alice"]))
    assert shown.status_code == 200
    assert "Reconcile" in shown.json()["sentence"]

    # Nothing was applied by asking.
    read = client.get(f"{PREFIX}/drafts/{key}", headers=headers(cast["alice"]))
    assert read.json()["plan"]["links"] == []

    made = client.post(f"{PREFIX}/drafts/{key}/apply",
                       json={"command": "add_link",
                             "payload": {"predecessor": "M01-T01",
                                         "successor": "M01-T02"}},
                       headers=headers(cast["alice"]))
    assert made.status_code == 200
    read = client.get(f"{PREFIX}/drafts/{key}", headers=headers(cast["alice"]))
    assert len(read.json()["plan"]["links"]) == 1


def test_a_loop_is_refused_by_the_route(client, cast):
    key = _start(client, cast["alice"])
    _complete(client, cast["alice"], key, cast)
    client.post(f"{PREFIX}/drafts/{key}/apply",
                json={"command": "add_link",
                      "payload": {"predecessor": "M01-T01",
                                  "successor": "M01-T02"}},
                headers=headers(cast["alice"]))
    refused = client.post(f"{PREFIX}/drafts/{key}/link-preview",
                          json={"predecessor": "M01-T02",
                                "successor": "M01-T01"},
                          headers=headers(cast["alice"]))
    assert refused.status_code == 422
    assert "loop" in refused.json()["detail"]["message"]


def test_link_to_previous_task_is_offered_from_the_plan(client, cast):
    key = _start(client, cast["alice"])
    _complete(client, cast["alice"], key, cast)
    found = client.get(f"{PREFIX}/drafts/{key}/previous-task",
                       params={"code": "M01-T02"},
                       headers=headers(cast["alice"]))
    assert found.status_code == 200
    assert found.json()["code"] == "M01-T01"


# ---------------------------------------------------------- preview/publish


def test_the_preview_shows_the_whole_plan(client, cast):
    key = _start(client, cast["alice"])
    _complete(client, cast["alice"], key, cast)
    shown = client.get(f"{PREFIX}/drafts/{key}/preview",
                       headers=headers(cast["alice"]))
    assert shown.status_code == 200
    body = shown.json()
    assert body["totals"]["milestones"] == 1
    assert body["totals"]["tasks"] == 2
    assert body["agentic"]["sentence"]
    assert body["completeness"]["publishable"] is True
    # Inherited escalation is shown with where it came from.
    assert body["milestones"][0]["escalation"]["source"] == "project"


def test_publishing_without_confirmation_is_refused(client, cast):
    key = _start(client, cast["alice"])
    _complete(client, cast["alice"], key, cast)
    refused = client.post(f"{PREFIX}/drafts/{key}/publish",
                          json={"confirm": False},
                          headers=headers(cast["alice"]))
    assert refused.status_code == 428
    assert refused.json()["detail"]["error"] == "not_confirmed"


def test_an_incomplete_plan_is_refused_with_its_blockers(client, cast):
    key = _start(client, cast["alice"], "Half a plan")
    refused = client.post(f"{PREFIX}/drafts/{key}/publish",
                          json={"confirm": True},
                          headers=headers(cast["alice"]))
    assert refused.status_code == 422
    assert "not ready to publish" in refused.json()["detail"]["message"]


def test_publishing_creates_a_project_the_planner_routes_can_see(client, cast):
    key = _start(client, cast["alice"])
    _complete(client, cast["alice"], key, cast)
    made = client.post(f"{PREFIX}/drafts/{key}/publish",
                       json={"confirm": True}, headers=headers(cast["alice"]))
    assert made.status_code == 201, made.text
    project_id = made.json()["project_id"]

    # The project is an ordinary planner project from here on.
    seen = client.get(f"/api/v1/planner/projects/{project_id}",
                      headers=headers(cast["alice"]))
    assert seen.status_code == 200
    body = seen.json()
    assert [m["code"] for m in body["milestones"]] == ["M01"]
    assert sorted(t["code"] for t in body["tasks"]) == ["M01-T01", "M01-T02"]

    # And the people the plan named can open it.
    assert client.get(f"/api/v1/planner/projects/{project_id}",
                      headers=headers(cast["bob"])).status_code == 200
    # Somebody it did not name cannot.
    assert client.get(f"/api/v1/planner/projects/{project_id}",
                      headers=headers(cast["mallory"])).status_code == 404


def test_a_published_draft_cannot_be_published_again(client, cast):
    key = _start(client, cast["alice"])
    _complete(client, cast["alice"], key, cast)
    client.post(f"{PREFIX}/drafts/{key}/publish", json={"confirm": True},
                headers=headers(cast["alice"]))
    again = client.post(f"{PREFIX}/drafts/{key}/publish",
                        json={"confirm": True}, headers=headers(cast["alice"]))
    assert again.status_code == 422
    assert "already published" in again.json()["detail"]["message"]


# ------------------------------------------------------------------ people


def test_people_lookup_returns_names_not_contact_details(client, cast):
    found = client.get(f"{PREFIX}/people", params={"search": "planner-alice"},
                       headers=headers(cast["alice"]))
    assert found.status_code == 200
    rows = found.json()["people"]
    assert rows
    assert set(rows[0]) == {"user_id", "name", "username", "role"}
