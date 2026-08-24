"""
The workspace API: review, comments and notifications.

These are the behaviours that make a workflow trustworthy rather than
decorative:

  * the state machine refuses a transition it does not permit, and says which
    ones it does
  * the history is append-only, so every decision stays on the record
  * the person who needs to know is told — the reviewer on submission, the
    requester on the outcome
  * an inbox separates what I have to do from what I am waiting on
  * an object that CreditProbe cannot open cannot be sent for review
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
    """Two real users: one who asks for a review, one who does it."""
    from backend.db.engine import get_session
    from backend.db.models import User

    with get_session() as session:
        ids = []
        for username in ("wf_author", "wf_reviewer"):
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


@pytest.fixture
def review(client, people):
    author, reviewer = people
    response = client.post(
        "/api/v1/workspace/workflow",
        json={
            "object_type": "investigation",
            "object_id": "1",
            "title": "Sector deterioration, Q1 2026",
            "assigned_to": reviewer,
            "note": "Please sanity-check the Contracting move.",
        },
        headers=_as(author),
    )
    assert response.status_code == 201
    return response.json()


# ------------------------------------------------------------------ submit


def test_submitting_puts_it_in_front_of_the_reviewer(client, people, review):
    author, reviewer = people
    assert review["state"] == "submitted"
    assert review["state_label"] == "Awaiting review"

    inbox = client.get("/api/v1/workspace/workflow/inbox", headers=_as(reviewer)).json()
    assert any(item["id"] == review["id"] for item in inbox["my_work"])

    sent = client.get("/api/v1/workspace/workflow/inbox", headers=_as(author)).json()
    assert any(item["id"] == review["id"] for item in sent["sent_by_me"])


def test_the_reviewer_is_notified(client, people, review):
    _, reviewer = people
    body = client.get("/api/v1/workspace/notifications", headers=_as(reviewer)).json()
    titles = [n["title"] for n in body["notifications"]]
    assert any("Review requested" in t for t in titles)


def test_something_ipm_cannot_open_cannot_be_sent_for_review(client, people):
    author, reviewer = people
    response = client.post(
        "/api/v1/workspace/workflow",
        json={"object_type": "spreadsheet", "object_id": "9", "title": "Ad hoc",
              "assigned_to": reviewer},
        headers=_as(author),
    )
    assert response.status_code == 422
    assert "cannot be sent for review" in response.json()["detail"]["message"]


# -------------------------------------------------------------- transitions


def test_the_decision_history_is_append_only(client, people, review):
    _, reviewer = people
    client.post(f"/api/v1/workspace/workflow/{review['id']}/transition",
                json={"to_state": "in_review", "comment": "Taking a look."},
                headers=_as(reviewer))
    final = client.post(f"/api/v1/workspace/workflow/{review['id']}/transition",
                        json={"to_state": "approved", "comment": "Agreed."},
                        headers=_as(reviewer)).json()

    assert final["state"] == "approved"
    transitions = [(e["from_state"], e["to_state"]) for e in final["events"]]
    assert transitions == [
        ("draft", "submitted"),
        ("submitted", "in_review"),
        ("in_review", "approved"),
    ]
    assert [e["comment"] for e in final["events"]][-1] == "Agreed."


def test_a_closed_review_cannot_be_reopened_by_a_transition(client, people, review):
    _, reviewer = people
    client.post(f"/api/v1/workspace/workflow/{review['id']}/transition",
                json={"to_state": "approved"}, headers=_as(reviewer))
    response = client.post(f"/api/v1/workspace/workflow/{review['id']}/transition",
                           json={"to_state": "rejected"}, headers=_as(reviewer))
    assert response.status_code == 422
    assert "closed" in response.json()["detail"]["message"]


def test_the_requester_is_told_the_outcome(client, people, review):
    author, reviewer = people
    client.post("/api/v1/workspace/notifications/read", headers=_as(author))
    client.post(f"/api/v1/workspace/workflow/{review['id']}/transition",
                json={"to_state": "rejected", "comment": "Needs the borrower detail."},
                headers=_as(reviewer))

    body = client.get("/api/v1/workspace/notifications?unread_only=true",
                      headers=_as(author)).json()
    assert body["unread"] >= 1
    assert any(n["kind"] == "rejected" for n in body["notifications"])


def test_a_completed_review_moves_out_of_my_work(client, people, review):
    _, reviewer = people
    client.post(f"/api/v1/workspace/workflow/{review['id']}/transition",
                json={"to_state": "approved"}, headers=_as(reviewer))
    inbox = client.get("/api/v1/workspace/workflow/inbox", headers=_as(reviewer)).json()
    assert not any(item["id"] == review["id"] for item in inbox["my_work"])
    assert any(item["id"] == review["id"] for item in inbox["completed"])


# ---------------------------------------------------------------- comments


def test_a_comment_can_be_left_and_read_back(client, people):
    author, reviewer = people
    posted = client.post(
        "/api/v1/workspace/comments/investigation/1",
        json={"body": "The Contracting move looks like one large name.",
              "notify_user_id": author},
        headers=_as(reviewer),
    )
    assert posted.status_code == 201

    body = client.get("/api/v1/workspace/comments/investigation/1").json()
    assert any("one large name" in c["body"] for c in body["comments"])


def test_an_empty_comment_is_refused(client, people):
    _, reviewer = people
    response = client.post("/api/v1/workspace/comments/investigation/1",
                           json={"body": "   "}, headers=_as(reviewer))
    assert response.status_code in (400, 422)


def test_marking_notifications_read_clears_the_count(client, people):
    author, _ = people
    client.post("/api/v1/workspace/notifications/read", headers=_as(author))
    body = client.get("/api/v1/workspace/notifications", headers=_as(author)).json()
    assert body["unread"] == 0
