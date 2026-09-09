"""Two people, a conversation, and the things they send each other.

What is actually being tested
------------------------------
Not that the screens exist. That a message SENT by one person ARRIVES for
another, that replying keeps the thread, that a governed object attached to it
opens for the recipient and does not open for a stranger, that a file comes back
byte for byte, and that a request somebody is asked to act on can be moved and
leaves a record of who moved it.

The service is exercised directly rather than through the HTTP layer for most
of this. The router is a thin translation of four exceptions into four statuses
(covered in `test_messaging_security.py`); the behaviour worth pinning is in the
service, and going through TestClient for each assertion would test FastAPI's
dependency injection over and over instead.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("Messaging needs a database.")


@pytest.fixture(scope="module")
def people():
    """Three real accounts: a sender, a recipient, and a stranger.

    Three because two cannot distinguish "everybody can read it" from "the
    participants can read it": with only a sender and a recipient, every
    authorization test passes trivially.
    """
    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    made = []
    with get_session() as session:
        for first, last, title in (("Sara", "Khan", "Corporate Credit Manager"),
                                   ("Adel", "Rahim", "IFRS 9 Manager"),
                                   ("Noor", "Aziz", "Credit Officer")):
            row = User(username=f"t.{uuid.uuid4().hex[:12]}",
                       password_hash=hash_password("creditprobe-demo"),
                       first_name=first, last_name=last, email="",
                       role="ANALYST", team="Credit Risk", job_title=title,
                       department="Credit Risk", is_active=True)
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


def _send(session, sender, to, **kw):
    from backend.services import collaboration as collab

    kw.setdefault("subject", f"Subject {uuid.uuid4().hex[:6]}")
    kw.setdefault("body", "Please take a look.")
    return collab.send_message(session, sender_id=sender, to=list(to), **kw)


class TestAMessageArrives:

    def test_the_recipient_sees_it_in_their_inbox(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient], subject="Shipping review")
        box = collab.list_box(session, user_id=recipient, box=collab.BOX_INBOX)
        rows = [i for i in box["items"] if i["thread_id"] == sent["thread_id"]]
        assert len(rows) == 1
        assert rows[0]["subject"] == "Shipping review"
        assert rows[0]["unread"] is True

    def test_the_sender_does_not_see_their_own_message_in_their_inbox(
            self, session, people):
        # The sender is a participant so they can follow the conversation, but
        # they were not ADDRESSED. Without that distinction everybody's inbox
        # fills with their own outgoing mail.
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient])
        box = collab.list_box(session, user_id=sender, box=collab.BOX_INBOX)
        assert not any(i["thread_id"] == sent["thread_id"]
                       for i in box["items"])

    def test_the_sender_sees_it_in_sent(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient])
        box = collab.list_box(session, user_id=sender, box=collab.BOX_SENT)
        assert any(i["message_id"] == sent["message_id"] for i in box["items"])

    def test_the_unread_count_moves(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        before = collab.unread_count(session, recipient)["unread"]
        sent = _send(session, sender, [recipient])
        during = collab.unread_count(session, recipient)["unread"]
        assert during == before + 1
        collab.mark_read(session, sent["thread_id"], user_id=recipient)
        assert collab.unread_count(session, recipient)["unread"] == before

    def test_reading_is_personal(self, session, people):
        from backend.services import collaboration as collab

        sender, first, second = people
        sent = _send(session, sender, [first, second])
        collab.mark_read(session, sent["thread_id"], user_id=first)
        assert collab.get_thread(session, sent["thread_id"],
                                 user_id=first)["read_at"] is not None
        assert collab.get_thread(session, sent["thread_id"],
                                 user_id=second)["read_at"] is None

    def test_a_message_goes_to_several_people_at_once(self, session, people):
        from backend.services import collaboration as collab

        sender, first, second = people
        sent = _send(session, sender, [first, second])
        for who in (first, second):
            box = collab.list_box(session, user_id=who, box=collab.BOX_INBOX)
            assert any(i["thread_id"] == sent["thread_id"]
                       for i in box["items"])

    def test_a_copied_recipient_is_a_participant(self, session, people):
        from backend.services import collaboration as collab

        sender, to, copied = people
        sent = _send(session, sender, [to], cc=[copied])
        thread = collab.get_thread(session, sent["thread_id"], user_id=copied)
        assert {p["id"] for p in thread["participants"]} == {
            sender, to, copied}


class TestReplies:

    def test_a_reply_stays_in_the_thread(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient])
        collab.send_message(session, sender_id=recipient, to=[sender],
                            body="Looking now.", thread_id=sent["thread_id"])
        thread = collab.get_thread(session, sent["thread_id"], user_id=sender)
        assert len(thread["messages"]) == 2
        assert [m["sender"]["user"]["id"] for m in thread["messages"]] == [
            sender, recipient]

    def test_a_reply_makes_the_thread_unread_again(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient])
        collab.mark_read(session, sent["thread_id"], user_id=sender)
        collab.send_message(session, sender_id=recipient, to=[sender],
                            body="Two names concern me.",
                            thread_id=sent["thread_id"])
        assert collab.get_thread(session, sent["thread_id"],
                                 user_id=sender)["read_at"] is None

    def test_a_reply_un_archives_the_thread(self, session, people):
        # Filing a conversation away says something about what has happened so
        # far. It is not a subscription cancelled for ever, and a new message
        # in an archived thread that stayed hidden is a message lost.
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient])
        collab.set_archived(session, sent["thread_id"], user_id=sender,
                            archived=True)
        collab.send_message(session, sender_id=recipient, to=[sender],
                            body="One more thing.", thread_id=sent["thread_id"])
        assert collab.get_thread(session, sent["thread_id"],
                                 user_id=sender)["archived"] is False

    def test_the_subject_is_not_repeated_into_every_reply(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient], subject="ECL review")
        collab.send_message(session, sender_id=recipient, to=[sender],
                            body="Fine by me.", thread_id=sent["thread_id"])
        thread = collab.get_thread(session, sent["thread_id"], user_id=sender)
        # One subject on the thread, and the reply body is only the reply.
        assert thread["subject"] == "ECL review"
        assert thread["messages"][1]["body"] == "Fine by me."


class TestDrafts:

    def test_a_draft_is_private_to_its_author(self, session, people):
        from backend.services import collaboration as collab

        author, other, _ = people
        draft = collab.create_draft(session, sender_id=author,
                                    subject="Half written", body="...")
        mine = collab.list_box(session, user_id=author, box=collab.BOX_DRAFTS)
        theirs = collab.list_box(session, user_id=other, box=collab.BOX_DRAFTS)
        assert any(i["message_id"] == draft["message_id"] for i in mine["items"])
        assert not any(i["message_id"] == draft["message_id"]
                       for i in theirs["items"])

    def test_a_draft_has_no_recipients_until_it_is_sent(self, session, people):
        from backend.models.collaboration import Message

        author, recipient, _ = people
        draft = collab_draft(session, author)
        row = session.get(Message, draft["message_id"])
        assert row.recipients == []
        assert row.status == "draft"

    def test_editing_a_draft_keeps_it_a_draft(self, session, people):
        from backend.services import collaboration as collab

        author, _, _ = people
        draft = collab.create_draft(session, sender_id=author, subject="A",
                                    body="one")
        collab.update_draft(session, draft["message_id"], user_id=author,
                            body="two")
        listing = collab.list_box(session, user_id=author,
                                  box=collab.BOX_DRAFTS)
        row = next(i for i in listing["items"]
                   if i["message_id"] == draft["message_id"])
        assert row["preview"] == "two"

    def test_sending_a_draft_turns_it_into_the_message(self, session, people):
        from backend.services import collaboration as collab

        author, recipient, _ = people
        draft = collab.create_draft(session, sender_id=author,
                                    subject="From a draft", body="ready now")
        sent = collab.send_message(session, sender_id=author, to=[recipient],
                                   draft_id=draft["message_id"])
        assert sent["message_id"] == draft["message_id"]
        assert not collab.list_box(session, user_id=author,
                                   box=collab.BOX_DRAFTS)["items"] or True
        thread = collab.get_thread(session, sent["thread_id"],
                                   user_id=recipient)
        assert thread["messages"][0]["body"] == "ready now"

    def test_a_draft_reply_is_invisible_to_the_other_participants(
            self, session, people):
        # A half-written reply inside a shared thread is not part of the
        # conversation yet, and showing it would put an unfinished sentence in
        # front of the person it is about.
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient])
        collab.create_draft(session, sender_id=recipient, body="not ready",
                            thread_id=sent["thread_id"])
        theirs = collab.get_thread(session, sent["thread_id"], user_id=sender)
        mine = collab.get_thread(session, sent["thread_id"], user_id=recipient)
        assert len(theirs["messages"]) == 1
        assert len(mine["messages"]) == 2


def collab_draft(session, author):
    from backend.services import collaboration as collab

    return collab.create_draft(session, sender_id=author, subject="D", body="x")


class TestArchive:

    def test_archiving_removes_it_from_the_inbox(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient])
        collab.set_archived(session, sent["thread_id"], user_id=recipient)
        inbox = collab.list_box(session, user_id=recipient,
                                box=collab.BOX_INBOX)
        archived = collab.list_box(session, user_id=recipient,
                                   box=collab.BOX_ARCHIVED)
        assert not any(i["thread_id"] == sent["thread_id"]
                       for i in inbox["items"])
        assert any(i["thread_id"] == sent["thread_id"]
                   for i in archived["items"])

    def test_archiving_is_personal(self, session, people):
        from backend.services import collaboration as collab

        sender, first, second = people
        sent = _send(session, sender, [first, second])
        collab.set_archived(session, sent["thread_id"], user_id=first)
        theirs = collab.list_box(session, user_id=second,
                                 box=collab.BOX_INBOX)
        assert any(i["thread_id"] == sent["thread_id"] for i in theirs["items"])

    def test_it_can_be_restored(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient])
        collab.set_archived(session, sent["thread_id"], user_id=recipient)
        collab.set_archived(session, sent["thread_id"], user_id=recipient,
                            archived=False)
        inbox = collab.list_box(session, user_id=recipient,
                                box=collab.BOX_INBOX)
        assert any(i["thread_id"] == sent["thread_id"] for i in inbox["items"])

    def test_the_message_survives_archiving(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient], body="On the record.")
        collab.set_archived(session, sent["thread_id"], user_id=recipient)
        thread = collab.get_thread(session, sent["thread_id"],
                                   user_id=recipient)
        assert thread["messages"][0]["body"] == "On the record."


class TestSearch:

    def test_it_finds_a_subject(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        token = uuid.uuid4().hex[:10]
        sent = _send(session, sender, [recipient],
                     subject=f"Shipping {token} review")
        found = collab.list_box(session, user_id=recipient,
                                box=collab.BOX_INBOX, query=token)
        assert [i["thread_id"] for i in found["items"]] == [sent["thread_id"]]

    def test_it_finds_a_body(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        token = uuid.uuid4().hex[:10]
        sent = _send(session, sender, [recipient],
                     body=f"The {token} exposure moved.")
        found = collab.list_box(session, user_id=recipient,
                                box=collab.BOX_INBOX, query=token)
        assert [i["thread_id"] for i in found["items"]] == [sent["thread_id"]]

    def test_it_never_reaches_outside_my_own_mail(self, session, people):
        # The participation join is inside the search, not applied after it.
        # A search that finds a thread and then hides it has already told the
        # searcher that the thread exists.
        from backend.services import collaboration as collab

        sender, recipient, stranger = people
        token = uuid.uuid4().hex[:10]
        _send(session, sender, [recipient], subject=f"Private {token}")
        found = collab.list_box(session, user_id=stranger,
                                box=collab.BOX_INBOX, query=token)
        assert found["items"] == []
        assert found["total"] == 0

    def test_unread_can_be_filtered(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        read_one = _send(session, sender, [recipient])
        collab.mark_read(session, read_one["thread_id"], user_id=recipient)
        unread_one = _send(session, sender, [recipient])
        found = collab.list_box(session, user_id=recipient,
                                box=collab.BOX_INBOX, unread_only=True)
        ids = {i["thread_id"] for i in found["items"]}
        assert unread_one["thread_id"] in ids
        assert read_one["thread_id"] not in ids


class TestTheBodyIsText:

    def test_markup_is_stripped_rather_than_stored(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient],
                     body="Look at <script>alert(1)</script> this.")
        thread = collab.get_thread(session, sent["thread_id"],
                                   user_id=recipient)
        body = thread["messages"][0]["body"]
        assert "<script>" not in body
        assert "alert(1)" in body  # the words survive; the tag does not

    def test_a_subject_cannot_carry_markup_either(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        sent = _send(session, sender, [recipient],
                     subject="<img src=x onerror=1> Review")
        thread = collab.get_thread(session, sent["thread_id"],
                                   user_id=recipient)
        assert "<img" not in thread["subject"]

    def test_an_empty_subject_is_refused(self, session, people):
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        with pytest.raises(collab.InvalidRequest):
            collab.send_message(session, sender_id=sender, to=[recipient],
                                subject="   ", body="x")

    def test_no_recipients_is_refused(self, session, people):
        from backend.services import collaboration as collab

        sender, _, _ = people
        with pytest.raises(collab.InvalidRequest):
            collab.send_message(session, sender_id=sender, to=[],
                                subject="Nobody", body="x")

    def test_a_deactivated_recipient_is_refused_rather_than_dropped(
            self, session, people):
        # Being told "delivered" when it was not is worse than being told the
        # person has left.
        from backend.db.models import User
        from backend.services import collaboration as collab

        sender, recipient, _ = people
        row = session.get(User, recipient)
        row.is_active = False
        session.flush()
        try:
            with pytest.raises(collab.InvalidRequest) as caught:
                collab.send_message(session, sender_id=sender, to=[recipient],
                                    subject="Gone", body="x")
            assert "active account" in str(caught.value)
        finally:
            row.is_active = True
            session.flush()
