"""
The product hierarchy: Analysis < Investigation < Project.

The behaviours worth defending here are the ones a user would notice if they
broke:

  * a project starts in DRAFT and moves only where the vocabulary allows
  * "In review" cannot be typed. It is reached by asking somebody to review, and
    left when they decide — which is what makes the badge mean anything
  * an Investigation is a conversation: messages stay in order, and what the
    thread settled is carried into the next question so the same clarification
    is not asked twice
  * a saved Analysis records a run that already happened, at the certification
    the registry declares, and deleting the record leaves the run alone
  * moving things between projects works in both directions
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL not reachable")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def people() -> tuple[int, int]:
    """An author and a reviewer, both real rows."""
    from backend.db.engine import get_session
    from backend.db.models import User

    with get_session() as session:
        ids = []
        for username in ("hier_author", "hier_reviewer"):
            user = session.query(User).filter_by(username=username).first()
            if user is None:
                user = User(username=username, role="analyst", password_hash="not-a-login")
                session.add(user)
                session.flush()
            ids.append(user.id)
        session.commit()
        return ids[0], ids[1]


def _as(user_id: int) -> dict[str, str]:
    return {"X-IPM-User-Id": str(user_id), "X-IPM-Role": "ANALYST"}


def _steward(user_id: int) -> dict[str, str]:
    return {"X-IPM-User-Id": str(user_id), "X-IPM-Role": "DATA_STEWARD"}


@pytest.fixture
def project(client, people) -> dict:
    author, _ = people
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "Contracting concentration review",
            "description": "Whether the Contracting exposure needs an action plan.",
            "instructions": "Answer for the corporate book unless told otherwise.",
        },
        headers=_as(author),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ================================================================= projects


def test_a_project_starts_in_draft(project):
    assert project["status"] == "draft"
    assert project["status_label"] == "Draft"
    assert project["review_open"] is False


def test_draft_offers_only_the_moves_it_permits(project):
    offered = {s["status"] for s in project["available_statuses"]}
    assert offered == {"active", "archived"}
    assert "in_review" not in offered


def test_a_project_moves_through_its_vocabulary(client, people, project):
    author, _ = people
    activated = client.post(
        f"/api/v1/projects/{project['id']}/status",
        json={"status": "active", "note": "Kick-off done."},
        headers=_as(author),
    )
    assert activated.status_code == 200, activated.text
    body = activated.json()
    assert body["status"] == "active"
    assert body["history"][0]["from_status"] == "draft"
    assert body["history"][0]["to_status"] == "active"


def test_a_status_the_vocabulary_forbids_is_refused_with_the_alternatives(
    client, people, project
):
    author, _ = people
    refused = client.post(
        f"/api/v1/projects/{project['id']}/status",
        json={"status": "completed"},
        headers=_as(author),
    )
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["error"] == "invalid_transition"
    # It says what IS available rather than only what is not.
    assert "Active" in detail["message"]


def test_in_review_cannot_simply_be_declared(client, people, project):
    """The whole point of the badge: nobody can apply it to themselves."""
    author, _ = people
    refused = client.post(
        f"/api/v1/projects/{project['id']}/status",
        json={"status": "in_review"},
        headers=_as(author),
    )
    assert refused.status_code == 422
    assert "cannot be set directly" in refused.json()["detail"]["message"]


def test_in_review_means_a_review_is_genuinely_outstanding(client, people, project):
    author, reviewer = people
    client.post(f"/api/v1/projects/{project['id']}/status",
                json={"status": "active"}, headers=_as(author))

    sent = client.post(
        f"/api/v1/projects/{project['id']}/review",
        json={"assigned_to": reviewer, "note": "Ready for your eyes."},
        headers=_as(author),
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["status"] == "in_review"
    assert body["review_open"] is True
    # With a reviewer holding it, nobody can move it by hand.
    assert body["available_statuses"] == []

    stuck = client.post(
        f"/api/v1/projects/{project['id']}/status",
        json={"status": "completed"},
        headers=_as(author),
    )
    assert stuck.status_code == 422
    assert "reviewer" in stuck.json()["detail"]["message"]


def test_the_reviewer_deciding_is_what_takes_it_out_of_review(client, people, project):
    author, reviewer = people
    client.post(f"/api/v1/projects/{project['id']}/status",
                json={"status": "active"}, headers=_as(author))
    sent = client.post(
        f"/api/v1/projects/{project['id']}/review",
        json={"assigned_to": reviewer},
        headers=_as(author),
    ).json()

    item_id = sent["review_item_id"]
    assert item_id is not None
    client.post(f"/api/v1/workspace/workflow/{item_id}/transition",
                json={"to_state": "in_review"}, headers=_as(reviewer))
    approved = client.post(
        f"/api/v1/workspace/workflow/{item_id}/transition",
        json={"to_state": "approved", "comment": "Agreed."},
        headers=_as(reviewer),
    )
    assert approved.status_code == 200, approved.text

    after = client.get(f"/api/v1/projects/{project['id']}").json()
    assert after["review_open"] is False
    assert after["status"] == "completed"


# ========================================================== investigations


@pytest.fixture
def thread(client, people, project) -> dict:
    """A thread opened without asking, so the test does not depend on an LLM."""
    author, _ = people
    response = client.post(
        "/api/v1/investigations",
        json={
            "question": "Where is the Contracting exposure concentrated?",
            "project_id": project["id"],
            "ask": False,
        },
        headers=_as(author),
    )
    assert response.status_code == 201, response.text
    return response.json()["thread"]


def test_a_thread_opens_with_the_question_as_its_first_message(thread):
    assert thread["message_count"] == 1
    assert thread["messages"][0]["sequence"] == 0
    assert thread["messages"][0]["role"] == "user"
    assert thread["messages"][0]["content"].startswith("Where is the Contracting")


def test_the_title_is_taken_from_the_question(thread):
    assert thread["title"].startswith("Where is the Contracting")


def test_messages_keep_their_order(client, people, thread):
    from backend.services import threads as th

    author, _ = people
    th.append(thread["id"], role="assistant", content="First answer.", user_id=author)
    th.append(thread["id"], role="user", content="And by region?", user_id=author)
    th.append(thread["id"], role="assistant", content="Second answer.", user_id=author)

    loaded = client.get(f"/api/v1/investigations/{thread['id']}").json()
    assert [m["sequence"] for m in loaded["messages"]] == [0, 1, 2, 3]
    assert [m["role"] for m in loaded["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]
    assert loaded["message_count"] == 4


def test_a_thread_inherits_its_project_standing_context(client, people, project):
    """Said once on the project, not again in every question."""
    from backend.services import projects as pj

    author, _ = people
    pj.update(project["id"], default_context={"segment": "corporate"})
    response = client.post(
        "/api/v1/investigations",
        json={"question": "How did coverage move?", "project_id": project["id"],
              "ask": False},
        headers=_as(author),
    )
    assert response.json()["thread"]["context"]["segment"] == "corporate"


def test_what_the_thread_settles_is_remembered(client, people, thread):
    author, _ = people
    settled = client.post(
        f"/api/v1/investigations/{thread['id']}/context",
        json={"context": {"from_period": "2025Q4", "to_period": "2026Q1"}},
        headers=_as(author),
    )
    assert settled.status_code == 200

    from backend.services import threads as th

    reloaded = th.load(thread["id"])
    assert th.settled_period(reloaded.context) == ("2025Q4", "2026Q1")


def test_a_thread_can_be_renamed_and_moved_out_of_its_project(client, people, thread):
    author, _ = people
    renamed = client.post(f"/api/v1/investigations/{thread['id']}/rename",
                          json={"title": "Contracting concentration"},
                          headers=_as(author))
    assert renamed.json()["title"] == "Contracting concentration"

    moved = client.post(f"/api/v1/investigations/{thread['id']}/move",
                        json={"project_id": None}, headers=_as(author))
    assert moved.json()["project_id"] is None


def test_archiving_hides_a_thread_without_deleting_it(client, people, thread):
    author, _ = people
    archived = client.post(f"/api/v1/investigations/{thread['id']}/archive",
                           headers=_steward(author))
    assert archived.json()["status"] == "archived"

    # Scoped to "all" because this fixture's thread lives inside a project, and
    # the standalone list correctly excludes it either way.
    listed = client.get(
        "/api/v1/investigations", params={"scope": "all"}
    ).json()["investigations"]
    assert all(t["id"] != thread["id"] for t in listed)

    with_archived = client.get(
        "/api/v1/investigations",
        params={"scope": "all", "include_archived": True},
    ).json()["investigations"]
    assert any(t["id"] == thread["id"] for t in with_archived)


def test_a_missing_thread_is_a_404(client):
    assert client.get("/api/v1/investigations/99999999").status_code == 404


# ================================================================ analyses


@pytest.fixture
def saved(client, people, project, thread) -> dict:
    author, _ = people
    response = client.post(
        "/api/v1/analyses",
        json={
            "analysis_id": "portfolio_summary",
            "title": "Portfolio summary, Q1 2026",
            "result": {"total_exposure": 1234.5},
            "period": {"period": "2026Q1"},
            "investigation_id": thread["id"],
            "project_id": project["id"],
        },
        headers=_as(author),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_saved_analysis_keeps_the_result_it_was_given(saved):
    assert saved["result"] == {"total_exposure": 1234.5}
    assert saved["analysis_id"] == "portfolio_summary"


def test_certification_comes_from_the_registry_not_the_caller(client, people, project):
    """A save request does not get to assert that something is certified."""
    from backend.engine.registry import get_registry

    author, _ = people
    registry = get_registry()
    analysis_id = next(
        (c.id for c in registry.contracts()
         if getattr(c.certification, "value", c.certification) == "certified"),
        None,
    )
    if analysis_id is None:  # pragma: no cover - registry always has certified work
        pytest.skip("No certified analysis registered")

    body = client.post(
        "/api/v1/analyses",
        json={"analysis_id": analysis_id, "result": {}, "project_id": project["id"]},
        headers=_as(author),
    ).json()
    assert body["certification"] == "certified"


def test_an_unknown_analysis_is_saved_as_draft_not_as_certified(client, people):
    author, _ = people
    body = client.post(
        "/api/v1/analyses",
        json={"analysis_id": "not_a_registered_analysis", "result": {}},
        headers=_as(author),
    ).json()
    assert body["certification"] == "draft"


def test_analyses_can_be_listed_by_project_and_by_investigation(
    client, project, thread, saved
):
    by_project = client.get("/api/v1/analyses",
                            params={"project_id": project["id"]}).json()["analyses"]
    assert any(a["id"] == saved["id"] for a in by_project)

    by_thread = client.get(
        "/api/v1/analyses", params={"investigation_id": thread["id"]}
    ).json()["analyses"]
    assert any(a["id"] == saved["id"] for a in by_thread)


def test_a_saved_analysis_can_be_moved_between_projects(client, people, saved):
    author, _ = people
    out = client.post(f"/api/v1/analyses/{saved['id']}/move",
                      json={"project_id": None}, headers=_as(author))
    assert out.json()["project_id"] is None


def test_deleting_a_saved_analysis_removes_only_the_record(client, people, saved):
    author, _ = people
    assert client.delete(f"/api/v1/analyses/{saved['id']}",
                         headers=_as(author)).status_code == 204
    assert client.get(f"/api/v1/analyses/{saved['id']}").status_code == 404


def test_saving_from_an_answer_that_has_no_analysis_is_refused(client, people, thread):
    """Nothing calculated means nothing to keep, and saying so beats an empty save."""
    from backend.services import threads as th

    author, _ = people
    message = th.append(thread["id"], role="assistant", content="I could not run that.",
                        payload={"steps": []}, user_id=author)
    refused = client.post(
        "/api/v1/analyses/from-message",
        json={"investigation_id": thread["id"], "sequence": message.sequence},
        headers=_as(author),
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"] == "nothing_to_save"


def test_saving_from_an_answer_keeps_each_certified_step(client, people, thread):
    from backend.services import threads as th

    author, _ = people
    message = th.append(
        thread["id"],
        role="assistant",
        content="Exposure is concentrated in Contracting.",
        payload={
            "analysis_run_id": None,
            "plan": {"scope": {"from_period": "2025Q4", "to_period": "2026Q1"}},
            "steps": [
                {"analysis_id": "step_one", "title": "Exposure by sector",
                 "status": "succeeded", "result": {"top": "Contracting"},
                 "params": {}, "filters": {}, "period": "2026Q1", "node_hashes": {}},
                {"analysis_id": "step_two", "title": "Coverage",
                 "status": "failed", "result": None,
                 "params": {}, "filters": {}, "period": "2026Q1", "node_hashes": {}},
            ],
        },
        user_id=author,
    )
    body = client.post(
        "/api/v1/analyses/from-message",
        json={"investigation_id": thread["id"], "sequence": message.sequence},
        headers=_as(author),
    ).json()

    # Only the step that succeeded: a failed step produced no figure to keep.
    assert body["count"] == 1
    kept = body["analyses"][0]
    assert kept["analysis_id"] == "step_one"
    assert kept["result"] == {"top": "Contracting"}
    assert kept["period"]["from_period"] == "2025Q4"


# ================================================================ contents


def test_a_project_reports_what_is_filed_under_it(client, people, project):
    author, _ = people
    client.post("/api/v1/investigations",
                json={"question": "How is coverage trending?",
                      "project_id": project["id"], "ask": False},
                headers=_as(author))
    client.post("/api/v1/analyses",
                json={"analysis_id": "portfolio_summary", "result": {},
                      "project_id": project["id"]},
                headers=_as(author))

    body = client.get(f"/api/v1/projects/{project['id']}/contents").json()
    assert body["project"]["id"] == project["id"]
    assert len(body["investigations"]) >= 1
    assert len(body["analyses"]) >= 1
    assert body["project"]["investigation_count"] >= 1
    assert body["project"]["analysis_count"] >= 1


# ============================================================== the principal


def test_an_unknown_user_id_is_treated_as_anonymous_not_as_an_error(client):
    """Several tables record who acted, with a foreign key to `users`. An id that
    names nobody used to fail that constraint deep inside a service and surface
    as "something went wrong on the server" — for what is really "that is not a
    user here". The action happens and is recorded as having no named actor."""
    response = client.post(
        "/api/v1/projects",
        json={"name": "Opened by a caller nobody knows"},
        headers={"X-IPM-User-Id": "99999999", "X-IPM-Role": "ANALYST"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["created_by"] is None


def test_a_real_user_id_is_still_recorded(client, people):
    author, _ = people
    response = client.post(
        "/api/v1/projects",
        json={"name": "Opened by a real user"},
        headers=_as(author),
    )
    assert response.status_code == 201
    assert response.json()["created_by"] == author


# ================================================== project vs standalone


def test_a_cockpit_chat_becomes_a_standalone_investigation(client, people):
    """Started outside a project, it belongs to the global list."""
    author, _ = people
    thread = client.post(
        "/api/v1/investigations",
        json={"question": "Started from the Cockpit", "ask": False},
        headers=_as(author),
    ).json()["thread"]
    assert thread["project_id"] is None

    listed = client.get("/api/v1/investigations").json()["investigations"]
    assert any(t["id"] == thread["id"] for t in listed)


def test_a_project_chat_stays_inside_its_project(client, people, project):
    """The rule that makes a Project a container rather than a tag.

    A thread started inside a project must NOT also appear in the global list,
    or Work > Investigations becomes an undifferentiated pile of everything
    anybody ever asked.
    """
    author, _ = people
    thread = client.post(
        "/api/v1/investigations",
        json={
            "question": "Started inside the project",
            "project_id": project["id"],
            "ask": False,
        },
        headers=_as(author),
    ).json()["thread"]
    assert thread["project_id"] == project["id"]

    standalone = client.get("/api/v1/investigations").json()["investigations"]
    assert all(t["id"] != thread["id"] for t in standalone), (
        "A project's investigation leaked into the standalone list."
    )

    inside = client.get(
        "/api/v1/investigations",
        params={"scope": "project", "project_id": project["id"]},
    ).json()["investigations"]
    assert any(t["id"] == thread["id"] for t in inside)

    contents = client.get(f"/api/v1/projects/{project['id']}/contents").json()
    assert any(t["id"] == thread["id"] for t in contents["investigations"])


def test_listing_a_project_scope_without_a_project_is_refused(client):
    response = client.get("/api/v1/investigations", params={"scope": "project"})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_scope"


def test_copying_leaves_the_original_where_it_is(client, people, project):
    """Distinct from moving. A project's record of what was explored should
    usually survive somebody taking a copy elsewhere."""
    author, _ = people
    thread = client.post(
        "/api/v1/investigations",
        json={"question": "Worth copying", "project_id": project["id"], "ask": False},
        headers=_as(author),
    ).json()["thread"]

    copied = client.post(
        f"/api/v1/investigations/{thread['id']}/copy",
        json={"project_id": None},
        headers=_as(author),
    )
    assert copied.status_code == 201
    body = copied.json()
    assert body["id"] != thread["id"]
    assert body["project_id"] is None
    assert body["message_count"] == thread["message_count"]

    still_there = client.get(f"/api/v1/projects/{project['id']}/contents").json()
    assert any(t["id"] == thread["id"] for t in still_there["investigations"])


def test_a_project_can_be_started_from_a_standalone_investigation(client, people):
    author, _ = people
    thread = client.post(
        "/api/v1/investigations",
        json={"question": "This turned out to matter", "ask": False},
        headers=_as(author),
    ).json()["thread"]

    response = client.post(
        f"/api/v1/investigations/{thread['id']}/project",
        json={"name": "Grew out of a conversation", "move": True},
        headers=_as(author),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["project"]["investigation_count"] == 1
    assert body["investigation"]["project_id"] == body["project"]["id"]

    # Moved, so it is no longer standalone.
    standalone = client.get("/api/v1/investigations").json()["investigations"]
    assert all(t["id"] != thread["id"] for t in standalone)
