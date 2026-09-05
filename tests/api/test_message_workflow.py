"""Asking somebody to do something, and knowing what they did about it.

Three, not nine
----------------
FOR INFORMATION, REQUEST REVIEW and ACTION REQUIRED. A risk team needs to tell
those three apart; it does not need a nine-state approval ladder to do it, and
the certification ladder that genuinely needs one already exists elsewhere
(`workflow_items`). The states here are open → in review → responded → closed,
and a transition the machine does not allow is refused rather than reachable by
clicking carefully.

Every move writes an event. "It says Responded" is a much weaker fact than
"she moved it to Responded on the 4th, and this is what she said", and the
second is the one a committee asks for six months later.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("Review requests need a database.")


@pytest.fixture(scope="module")
def people():
    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    made = []
    with get_session() as session:
        for first in ("Requester", "Reviewer", "Outsider"):
            row = User(username=f"t.{uuid.uuid4().hex[:12]}",
                       password_hash=hash_password("creditprobe-demo"),
                       first_name=first, last_name="Test", role="ANALYST",
                       is_active=True)
            session.add(row)
            session.flush()
            made.append(row.id)
        session.commit()
    yield tuple(made)
    with get_session() as session:
        for user_id in made:
            row = session.get(User, user_id)
            if row is not None:
                row.is_active = False
        session.commit()


@pytest.fixture
def session():
    from backend.db.engine import get_session

    with get_session() as s:
        yield s


def _ask(session, requester, reviewer, kind="review"):
    from backend.services import collaboration as collab

    return collab.send_message(
        session, sender_id=requester, to=[reviewer],
        subject=f"Please review {uuid.uuid4().hex[:6]}",
        body="Before tomorrow's committee.", request_type=kind)


class TestWhatIsBeingAskedFor:

    def test_for_information_has_no_status_to_close(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer, kind="fyi")
        message = collab.get_thread(session, sent["thread_id"],
                                    user_id=reviewer)["messages"][0]
        assert message["request_type"] == "fyi"
        assert message["request_status"] is None

    def test_a_review_request_opens(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        message = collab.get_thread(session, sent["thread_id"],
                                    user_id=reviewer)["messages"][0]
        assert message["request_type"] == "review"
        assert message["request_status"] == "open"

    def test_an_action_request_opens_too(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer, kind="action")
        message = collab.get_thread(session, sent["thread_id"],
                                    user_id=reviewer)["messages"][0]
        assert message["request_status"] == "open"

    def test_an_unknown_kind_is_refused(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        with pytest.raises(collab.InvalidRequest):
            collab.send_message(session, sender_id=requester, to=[reviewer],
                                subject="?", body="x",
                                request_type="escalate_to_board")

    def test_a_due_date_and_priority_are_carried(self, session, people):
        from datetime import UTC, datetime, timedelta

        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        due = datetime.now(UTC) + timedelta(days=2)
        sent = collab.send_message(session, sender_id=requester, to=[reviewer],
                                   subject="Urgent", body="x",
                                   request_type="action", priority="high",
                                   due_at=due)
        message = collab.get_thread(session, sent["thread_id"],
                                    user_id=reviewer)["messages"][0]
        assert message["priority"] == "high"
        assert message["due_at"] is not None


class TestTheReviewerSeesItAsWork:

    def test_it_counts_as_action_required(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        before = collab.unread_count(session, reviewer)["action_required"]
        _ask(session, requester, reviewer)
        assert collab.unread_count(
            session, reviewer)["action_required"] == before + 1

    def test_a_for_information_message_does_not(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        before = collab.unread_count(session, reviewer)["action_required"]
        _ask(session, requester, reviewer, kind="fyi")
        assert collab.unread_count(
            session, reviewer)["action_required"] == before

    def test_it_appears_in_the_action_mailbox(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        box = collab.list_box(session, user_id=reviewer,
                              box=collab.BOX_ACTION)
        assert any(i["thread_id"] == sent["thread_id"] for i in box["items"])

    def test_closing_it_removes_it_from_that_mailbox(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="closed")
        box = collab.list_box(session, user_id=reviewer,
                              box=collab.BOX_ACTION)
        assert not any(i["thread_id"] == sent["thread_id"]
                       for i in box["items"])

    def test_the_requester_does_not_see_their_own_ask_as_their_own_work(
            self, session, people):
        # Action Required means somebody asked YOU. A requester whose own
        # request sits in their action list has a queue that never empties.
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        box = collab.list_box(session, user_id=requester,
                              box=collab.BOX_ACTION)
        assert not any(i["thread_id"] == sent["thread_id"]
                       for i in box["items"])


class TestTheStateMachine:

    def test_the_full_path(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        for state in ("in_review", "responded", "closed"):
            moved = collab.change_request_status(
                session, sent["message_id"], user_id=reviewer, status=state)
            assert moved["request_status"] == state

    def test_a_closed_request_cannot_reopen(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="closed")
        with pytest.raises(collab.InvalidRequest) as caught:
            collab.change_request_status(session, sent["message_id"],
                                         user_id=reviewer, status="open")
        assert "closed" in str(caught.value)

    def test_responded_cannot_go_back_to_open(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="responded")
        with pytest.raises(collab.InvalidRequest):
            collab.change_request_status(session, sent["message_id"],
                                         user_id=reviewer, status="open")

    def test_responded_may_go_back_into_review(self, session, people):
        # A reviewer who answers and is then asked something further should
        # not have to open a second request to say so.
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="responded")
        moved = collab.change_request_status(session, sent["message_id"],
                                             user_id=reviewer,
                                             status="in_review")
        assert moved["request_status"] == "in_review"

    def test_an_unknown_state_is_refused(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        with pytest.raises(collab.InvalidRequest):
            collab.change_request_status(session, sent["message_id"],
                                         user_id=reviewer, status="escalated")

    def test_a_for_information_message_cannot_be_moved(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer, kind="fyi")
        with pytest.raises(collab.InvalidRequest) as caught:
            collab.change_request_status(session, sent["message_id"],
                                         user_id=reviewer, status="closed")
        assert "did not ask for anything" in str(caught.value)

    def test_an_outsider_cannot_move_it(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, outsider = people
        sent = _ask(session, requester, reviewer)
        with pytest.raises(collab.NotFound):
            collab.change_request_status(session, sent["message_id"],
                                         user_id=outsider, status="closed")

    def test_the_requester_may_close_their_own_request(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        moved = collab.change_request_status(session, sent["message_id"],
                                             user_id=requester,
                                             status="closed")
        assert moved["request_status"] == "closed"


class TestTheHistoryIsEvidence:

    def test_every_transition_is_recorded_with_who_and_what(self, session,
                                                            people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="in_review",
                                     note="Taking this up.")
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="responded",
                                     note="Two names confirmed.")
        collab.change_request_status(session, sent["message_id"],
                                     user_id=requester, status="closed",
                                     note="Noted for committee.")
        events = collab.request_history(session, sent["message_id"],
                                        user_id=requester)
        assert [(e["from_status"], e["to_status"]) for e in events] == [
            (None, "open"), ("open", "in_review"),
            ("in_review", "responded"), ("responded", "closed"),
        ]
        assert events[1]["actor"] == "Reviewer Test"
        assert events[1]["note"] == "Taking this up."
        assert events[3]["actor"] == "Requester Test"
        assert all(e["at"] for e in events)

    def test_a_refused_transition_writes_nothing(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="closed")
        before = len(collab.request_history(session, sent["message_id"],
                                            user_id=requester))
        with pytest.raises(collab.InvalidRequest):
            collab.change_request_status(session, sent["message_id"],
                                         user_id=reviewer, status="open")
        after = len(collab.request_history(session, sent["message_id"],
                                           user_id=requester))
        assert after == before

    def test_an_outsider_cannot_read_the_history(self, session, people):
        from backend.services import collaboration as collab

        requester, reviewer, outsider = people
        sent = _ask(session, requester, reviewer)
        with pytest.raises(collab.NotFound):
            collab.request_history(session, sent["message_id"],
                                   user_id=outsider)

    def test_a_status_change_is_audited(self, session, people):
        from sqlalchemy import select

        from backend.models.collaboration import CollaborationAudit
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="in_review")
        rows = session.execute(
            select(CollaborationAudit).where(
                CollaborationAudit.action == collab.WORKFLOW_STATUS_CHANGED,
                CollaborationAudit.object_id == str(sent["message_id"]))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].detail["to_status"] == "in_review"
        assert rows[0].actor_id == reviewer

    def test_the_requester_is_told(self, session, people):
        # A status that changes silently is one the requester has to go and
        # look for, which is the same as not being told.
        from sqlalchemy import select

        from backend.models.platform import Notification
        from backend.services import collaboration as collab

        requester, reviewer, _ = people
        sent = _ask(session, requester, reviewer)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=reviewer, status="responded")
        rows = session.execute(
            select(Notification).where(
                Notification.user_id == requester,
                Notification.object_id == str(sent["thread_id"]))
        ).scalars().all()
        assert any("responded" in (r.title or "") for r in rows)
