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
    # §44's word for it. The stored id stays `submitted`, because renaming it
    # would rewrite decisions that exist in order not to be rewritten.
    assert review["state_label"] == "Sent"

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


# ================================ §43-§46: send to many, for a named action


@pytest.fixture(scope="module")
def crowd() -> tuple[int, int, int]:
    """Three users, so "sent to several people" is genuinely several."""
    from backend.db.engine import get_session
    from backend.db.models import User

    with get_session() as session:
        ids = []
        for username in ("wf_sender", "wf_first", "wf_second"):
            user = session.query(User).filter_by(username=username).first()
            if user is None:
                user = User(username=username, role="analyst",
                            password_hash="not-a-login")
                session.add(user)
                session.flush()
            ids.append(user.id)
        session.commit()
        return ids[0], ids[1], ids[2]


@pytest.fixture
def sent_to_two(client, crowd) -> dict:
    sender, first, second = crowd
    response = client.post(
        "/api/v1/workspace/workflow",
        json={
            "object_type": "investigation",
            "object_id": "5150",
            "object_version": "3",
            "title": "Contracting deterioration",
            "recipients": [first, second],
            "action": "sign_off",
            "priority": "high",
            "note": "Needs both signatures before the committee.",
        },
        headers=_as(sender),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_one_request_can_go_to_several_people(sent_to_two, crowd):
    """§43. A set of recipients, not a column called assigned_to_2."""
    _, first, second = crowd
    assert {r["user_id"] for r in sent_to_two["recipients"]} == {first, second}
    # The head of the set is still there for callers written before this.
    assert sent_to_two["assigned_to"] == first


def test_the_request_carries_what_it_was_asked_for(sent_to_two):
    """§44. Action, message, priority and the object's version.

    The action is not the state: "sign off" is what is being asked FOR, and
    "Sent" is where the asking has got to. A list that conflates them cannot
    tell an approval nobody has looked at from one that has been granted.
    """
    assert sent_to_two["action"] == "sign_off"
    assert sent_to_two["action_label"] == "Sign-off"
    assert sent_to_two["state"] == "submitted"
    assert sent_to_two["state_label"] == "Sent"
    assert sent_to_two["priority"] == "high"
    assert sent_to_two["object_version"] == "3"
    assert "committee" in sent_to_two["message"]


def test_every_recipient_is_told(client, crowd, sent_to_two):
    _, first, second = crowd
    for who in (first, second):
        notes = client.get("/api/v1/workspace/notifications",
                           headers=_as(who)).json()["notifications"]
        mine = [n for n in notes if n["object_id"] == "5150"]
        assert mine, who
        # The notification reads as a sentence somebody wrote, not as a label
        # a program printed: it sits in a list of other people's sentences.
        assert any("Sign-off requested" in n["title"] for n in mine), who


def test_an_action_the_product_cannot_perform_is_refused(client, crowd):
    sender, first, _ = crowd
    refused = client.post(
        "/api/v1/workspace/workflow",
        json={"object_type": "investigation", "object_id": "1",
              "title": "x", "recipients": [first], "action": "delete_everything"},
        headers=_as(sender),
    )
    assert refused.status_code == 422
    assert "Sign-off" in refused.json()["detail"]["message"]


def test_a_request_with_nobody_to_send_it_to_is_refused(client, crowd):
    """A workflow request with no recipient is a note to nobody."""
    sender, _, _ = crowd
    refused = client.post(
        "/api/v1/workspace/workflow",
        json={"object_type": "investigation", "object_id": "1", "title": "x"},
        headers=_as(sender),
    )
    assert refused.status_code == 422


def test_opening_it_is_recorded_once(client, crowd, sent_to_two):
    """§44's OPENED: an observation, and idempotent.

    A reviewer who reloads the page has not opened it twice, and one who has
    already started reviewing does not go backwards.
    """
    _, first, _ = crowd
    item_id = sent_to_two["id"]

    opened = client.post(f"/api/v1/workspace/workflow/{item_id}/opened",
                         headers=_as(first)).json()
    assert opened["state"] == "opened"
    stamp = next(r["opened_at"] for r in opened["recipients"]
                 if r["user_id"] == first)
    assert stamp is not None

    again = client.post(f"/api/v1/workspace/workflow/{item_id}/opened",
                        headers=_as(first)).json()
    assert next(r["opened_at"] for r in again["recipients"]
                if r["user_id"] == first) == stamp
    assert again["state"] == "opened"


def test_saying_something_moves_it_to_commented_and_tells_the_others(
    client, crowd, sent_to_two
):
    """§45. A message is a status as well as a message.

    It tells the sender there is something to read without claiming a decision
    has been taken.
    """
    sender, first, second = crowd
    item_id = sent_to_two["id"]

    said = client.post(
        f"/api/v1/workspace/workflow/{item_id}/messages",
        json={"body": "The Q2 figure looks like it double-counts the syndication."},
        headers=_as(first),
    )
    assert said.status_code == 201, said.text
    assert said.json()["body"].startswith("The Q2 figure")

    after = client.get(f"/api/v1/workspace/workflow/{item_id}").json()
    assert after["state"] == "commented"
    assert len(after["thread"]) == 1

    for who in (sender, second):
        notes = client.get("/api/v1/workspace/notifications",
                           headers=_as(who)).json()["notifications"]
        assert any(n["kind"] == "commented" for n in notes), who


def test_a_mention_is_not_the_same_as_a_comment(client, crowd, sent_to_two):
    """Being named is a different thing from being on the thread.

    An inbox that cannot tell "somebody said something" from "somebody asked
    you specifically" is one people stop reading.
    """
    sender, first, second = crowd
    item_id = sent_to_two["id"]

    client.post(
        f"/api/v1/workspace/workflow/{item_id}/messages",
        json={"body": "Can you check the collateral, please?",
              "mentions": [{"user_id": second}]},
        headers=_as(first),
    )
    notes = client.get("/api/v1/workspace/notifications",
                       headers=_as(second)).json()["notifications"]
    assert any(n["kind"] == "mentioned" for n in notes)

    inbox = client.get("/api/v1/workspace/workflow/inbox",
                       headers=_as(second)).json()
    assert item_id in {row["id"] for row in inbox["mentions"]}


def test_a_reply_hangs_off_the_message_it_answers(client, crowd, sent_to_two):
    sender, first, _ = crowd
    item_id = sent_to_two["id"]
    first_message = client.post(
        f"/api/v1/workspace/workflow/{item_id}/messages",
        json={"body": "Where did the syndication figure come from?"},
        headers=_as(sender),
    ).json()
    reply = client.post(
        f"/api/v1/workspace/workflow/{item_id}/messages",
        json={"body": "From the facility file, at Q2.",
              "parent_id": first_message["id"]},
        headers=_as(first),
    ).json()
    assert reply["parent_id"] == first_message["id"]


def test_a_message_can_carry_the_object_it_is_about(client, crowd, sent_to_two):
    """§45: attach an analysis, an investigation or a project to a message."""
    _, first, _ = crowd
    said = client.post(
        f"/api/v1/workspace/workflow/{sent_to_two['id']}/messages",
        json={"body": "This is the one I meant.",
              "attachments": [{"type": "investigation", "id": "91",
                               "label": "Stage 2 by sector"}]},
        headers=_as(first),
    ).json()
    assert said["attachments"][0]["id"] == "91"


def test_a_message_can_be_resolved(client, crowd, sent_to_two):
    _, first, _ = crowd
    said = client.post(
        f"/api/v1/workspace/workflow/{sent_to_two['id']}/messages",
        json={"body": "Fixed in the latest run."}, headers=_as(first),
    ).json()
    resolved = client.post(
        f"/api/v1/workspace/workflow/messages/{said['id']}/resolve",
        json={"resolved": True}, headers=_as(first),
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved"] is True


def test_the_inbox_separates_the_five_views(client, crowd, sent_to_two):
    """§46. Assigned to me, sent by me, mentions, due soon, completed."""
    sender, first, _ = crowd
    item_id = sent_to_two["id"]

    mine = client.get("/api/v1/workspace/workflow/inbox",
                      headers=_as(first)).json()
    assert set(mine) >= {"assigned_to_me", "sent_by_me", "mentions",
                         "due_soon", "completed"}
    assert item_id in {row["id"] for row in mine["assigned_to_me"]}
    assert item_id not in {row["id"] for row in mine["sent_by_me"]}

    theirs = client.get("/api/v1/workspace/workflow/inbox",
                        headers=_as(sender)).json()
    assert item_id in {row["id"] for row in theirs["sent_by_me"]}


def test_completing_is_not_the_same_as_approving(client, crowd):
    """§44 lists both. "Assign action" and "FYI" are completed, not approved:
    nobody has passed judgement on them."""
    sender, first, _ = crowd
    item = client.post(
        "/api/v1/workspace/workflow",
        json={"object_type": "investigation", "object_id": "7788",
              "title": "Chase the missing collateral file",
              "recipients": [first], "action": "assign_action"},
        headers=_as(sender),
    ).json()

    done = client.post(
        f"/api/v1/workspace/workflow/{item['id']}/transition",
        json={"to_state": "completed", "comment": "File received."},
        headers=_as(first),
    )
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "completed"
    assert done.json()["state_label"] == "Completed"
    # Final, like every other decision.
    assert done.json()["next_states"] == []


def test_a_team_receives_work_and_its_members_are_told(client, crowd):
    """A team is a recipient of the item and a set of people for notifying.

    The expansion happens at read time rather than being stored, so somebody
    who joins Credit Review today sees what Credit Review was sent yesterday.
    """
    from backend.db.engine import get_session
    from backend.models.platform import Team, TeamMember

    sender, first, second = crowd
    with get_session() as session:
        team = session.query(Team).filter_by(name="wf_credit_review").first()
        if team is None:
            team = Team(name="wf_credit_review")
            session.add(team)
            session.flush()
            session.add(TeamMember(team_id=team.id, user_id=second))
        team_id = team.id
        session.commit()

    item = client.post(
        "/api/v1/workspace/workflow",
        json={"object_type": "project", "object_id": "9001",
              "title": "Q2 committee pack", "teams": [team_id],
              "action": "approve"},
        headers=_as(sender),
    )
    assert item.status_code == 201, item.text
    assert item.json()["recipients"][0]["team_id"] == team_id

    notes = client.get("/api/v1/workspace/notifications",
                       headers=_as(second)).json()["notifications"]
    assert any(n["object_id"] == "9001" for n in notes)

    inbox = client.get("/api/v1/workspace/workflow/inbox",
                       headers=_as(second)).json()
    assert item.json()["id"] in {row["id"] for row in inbox["assigned_to_me"]}


# ==================================================== §50: role enforcement


def _viewer(user_id: int) -> dict[str, str]:
    return {"X-IPM-User-Id": str(user_id), "X-IPM-Role": "VIEWER"}


def test_a_viewer_may_comment_but_may_not_send_work(client, crowd, sent_to_two):
    """§50, both halves of it.

    A Viewer reads what has been shared with them and comments where permitted.
    They do not create analytical work, and they do not assign it to anybody.
    """
    _, first, _ = crowd
    item_id = sent_to_two["id"]

    replied = client.post(
        f"/api/v1/workspace/workflow/{item_id}/messages",
        json={"body": "Agreed — the syndication line explains it."},
        headers=_viewer(first),
    )
    assert replied.status_code == 201, replied.text

    refused = client.post(
        "/api/v1/workspace/workflow",
        json={"object_type": "investigation", "object_id": "1",
              "title": "x", "recipients": [first]},
        headers=_viewer(first),
    )
    assert refused.status_code == 403
    assert "VIEWER" in refused.json()["detail"]["message"]


def test_a_viewer_may_not_decide(client, crowd, sent_to_two):
    """Approving is a judgement, and a Viewer does not make those."""
    _, first, _ = crowd
    refused = client.post(
        f"/api/v1/workspace/workflow/{sent_to_two['id']}/transition",
        json={"to_state": "approved"}, headers=_viewer(first),
    )
    assert refused.status_code == 403


def test_the_refusal_is_the_backend_s_and_says_what_is_needed(client, crowd):
    """§50: "Frontend hiding is not sufficient."

    The check is on the endpoint, so a request that never went near the UI is
    refused the same way — and the message names the roles that would work
    rather than saying no.
    """
    _, first, _ = crowd
    refused = client.post(
        "/api/v1/workspace/investigations",
        json={"question": "What is total exposure?"},
        headers=_viewer(first),
    )
    assert refused.status_code == 403
    message = refused.json()["detail"]["message"]
    assert "ANALYST" in message and "You are VIEWER" in message
