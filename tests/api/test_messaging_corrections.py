"""The five defects the 1.1 correction was raised for, pinned so they stay fixed.

Each class below is one reported defect, tested at the layer where it actually
lived. Four of the five were backend semantics rather than presentation, which
is why they are here and not in a component test:

1. The recipient directory returned nothing useful without a search term.
2. A message addressed to yourself was refused as having no recipients, so it
   reached neither Sent nor Inbox.
3. Workflow aggregates were reachable by anybody.
4. Reading did not move a number the whole product could agree on.
5. "Shared with me" stayed at zero for the person who shared something.
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
    """An admin and two colleagues, named the way real accounts are named."""
    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    made = []
    with get_session() as session:
        for first, last, title, role in (
            ("Corr", "Admin", "Head of Credit Risk", "ADMIN"),
            ("Corr", "Sarah", "Corporate Credit Manager", "ANALYST"),
            ("Corr", "Ahmed", "IFRS 9 Manager", "ANALYST"),
        ):
            row = User(username=f"c.{uuid.uuid4().hex[:12]}",
                       password_hash=hash_password("creditprobe-demo"),
                       first_name=first, last_name=last,
                       email=f"{uuid.uuid4().hex[:8]}@example-bank.com",
                       role=role, team="Credit Risk Analytics",
                       job_title=title, department="Credit Risk",
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


def _send(session, sender, to, **kw):
    from backend.services import collaboration as collab

    kw.setdefault("subject", f"Subject {uuid.uuid4().hex[:6]}")
    kw.setdefault("body", "Please take a look.")
    return collab.send_message(session, sender_id=sender, to=list(to), **kw)


# ======================================================================
# Defect 1 — the recipient picker showed nobody
# ======================================================================


class TestTheDirectoryAnswersWithoutASearch:

    def test_it_lists_people_when_nothing_has_been_typed(self, session, people):
        """The picker opens on focus, so an empty query must return the list.

        Returning nothing until somebody types is what made a fully configured
        institution look like an empty one.
        """
        from backend.services import collaboration as collab

        rows = collab.directory(session, query="", limit=50)
        assert len(rows) > 0
        assert all(r["is_active"] for r in rows)

    @pytest.mark.parametrize("field", ["first_name", "job_title", "team",
                                       "role", "email", "username"])
    def test_it_searches_every_field_a_sender_would_use(self, session, people,
                                                        field):
        from backend.db.models import User
        from backend.services import collaboration as collab

        who = session.get(User, people[1])
        term = str(getattr(who, field))
        assert term, f"the fixture needs a {field}"
        found = collab.directory(session, query=term.upper(), limit=200)
        assert any(r["id"] == who.id for r in found), (
            f"searching {field}={term!r} did not find the account"
        )

    def test_it_finds_somebody_by_their_whole_name(self, session, people):
        """"Corr Sarah" is what a sender types. No column holds both words."""
        from backend.db.models import User
        from backend.services import collaboration as collab

        who = session.get(User, people[1])
        whole = f"{who.first_name} {who.last_name}"
        found = collab.directory(session, query=whole, limit=50)
        assert any(r["id"] == who.id for r in found), (
            f"searching for the whole name {whole!r} found nobody"
        )
        assert any(r["id"] == who.id for r in
                   collab.directory(session, query=whole.lower(), limit=50))

    def test_a_suspended_account_is_not_offered(self, session, people):
        from backend.db.models import User
        from backend.services import collaboration as collab

        who = session.get(User, people[2])
        who.is_active = False
        session.flush()
        try:
            assert not any(r["id"] == who.id
                           for r in collab.directory(session, query="Corr",
                                                     limit=200))
        finally:
            who.is_active = True
            session.flush()

    def test_every_row_carries_a_name_never_a_bare_identifier(self, session,
                                                              people):
        from backend.services import collaboration as collab

        for row in collab.directory(session, query="Corr", limit=50):
            assert row["name"]
            assert row["name"] != str(row["id"])


# ======================================================================
# Defect 2 — a sent message reached neither Sent nor Inbox
# ======================================================================


class TestSendingToYourself:

    def test_it_is_allowed(self, session, people):
        admin, _, _ = people
        sent = _send(session, admin, [admin], subject="A note to myself")
        assert sent["status"] == "sent"
        assert sent["recipients"] == [admin]

    def test_it_appears_in_sent(self, session, people):
        from backend.services import collaboration as collab

        admin, _, _ = people
        sent = _send(session, admin, [admin], subject="Filed for tomorrow")
        box = collab.list_box(session, user_id=admin, box=collab.BOX_SENT)
        assert any(i["message_id"] == sent["message_id"]
                   for i in box["items"])

    def test_it_appears_in_the_inbox_too_and_is_unread(self, session, people):
        from backend.services import collaboration as collab

        admin, _, _ = people
        sent = _send(session, admin, [admin], subject="Read me tomorrow")
        rows = [i for i in collab.list_box(session, user_id=admin,
                                           box=collab.BOX_INBOX)["items"]
                if i["thread_id"] == sent["thread_id"]]
        assert len(rows) == 1, "exactly one inbox row, never two"
        assert rows[0]["unread"] is True

    def test_it_counts_once_in_each_box(self, session, people):
        from backend.services import collaboration as collab

        admin, _, _ = people
        before = collab.attention_summary(session, admin)
        _send(session, admin, [admin], subject="Counted once")
        after = collab.attention_summary(session, admin)
        assert after["sent"] == before["sent"] + 1
        assert after["inbox"] == before["inbox"] + 1
        assert after["unread"] == before["unread"] + 1

    def test_addressing_yourself_twice_is_still_one_recipient(self, session,
                                                              people):
        admin, _, _ = people
        sent = _send(session, admin, [admin, admin], subject="Deduplicated")
        assert sent["recipients"] == [admin]


class TestSentIsWhatIActuallySent:

    def test_sent_is_decided_by_the_sender_not_by_workflow_status(
            self, session, people):
        """Moving a review along must not take it out of Sent.

        Sent answers "what did I send", which nothing that happens afterwards
        can change. Deciding it from `request_status` made messages disappear
        from the sender's own record the moment somebody responded.
        """
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        sent = _send(session, admin, [sarah], subject="Please review",
                     request_type=collab.REQ_REVIEW)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=sarah, status=collab.REQ_RESPONDED)
        box = collab.list_box(session, user_id=admin, box=collab.BOX_SENT)
        assert any(i["message_id"] == sent["message_id"] for i in box["items"])

    def test_the_conversation_stays_in_the_recipients_inbox_after_a_status_move(
            self, session, people):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        sent = _send(session, admin, [sarah], subject="Still a message",
                     request_type=collab.REQ_ACTION)
        collab.change_request_status(session, sent["message_id"],
                                     user_id=sarah,
                                     status=collab.REQ_IN_REVIEW)
        rows = collab.list_box(session, user_id=sarah,
                               box=collab.BOX_INBOX)["items"]
        assert any(i["thread_id"] == sent["thread_id"] for i in rows), (
            "a request that moved status left the inbox — it is still a message"
        )

    def test_a_message_carrying_an_analysis_is_still_a_message(
            self, session, people, analysis_id):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        sent = _send(session, admin, [sarah], subject="Shipping deterioration",
                     attachments=[{"type": collab.ATT_ANALYSIS,
                                   "object_id": analysis_id}])
        inbox = collab.list_box(session, user_id=sarah,
                                box=collab.BOX_INBOX)["items"]
        row = next(i for i in inbox if i["thread_id"] == sent["thread_id"])
        assert collab.ATT_ANALYSIS in row["attachment_types"]
        assert any(i["message_id"] == sent["message_id"]
                   for i in collab.list_box(session, user_id=admin,
                                            box=collab.BOX_SENT)["items"])


class TestSendingTwiceIsSendingOnce:

    def test_the_same_token_returns_the_first_message(self, session, people):
        """A double-clicked Send must not deliver two copies."""
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        token = f"t-{uuid.uuid4().hex}"
        first = collab.send_message(session, sender_id=admin, to=[sarah],
                                    subject="Only once", body="Hello",
                                    client_token=token)
        second = collab.send_message(session, sender_id=admin, to=[sarah],
                                     subject="Only once", body="Hello",
                                     client_token=token)
        assert second["message_id"] == first["message_id"]
        assert second["duplicate"] is True
        rows = collab.list_box(session, user_id=sarah,
                               box=collab.BOX_INBOX)["items"]
        assert sum(1 for i in rows if i["thread_id"] == first["thread_id"]) == 1

    def test_without_a_token_two_sends_are_two_messages(self, session, people):
        # The guard must not silently collapse genuinely repeated messages.
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        one = _send(session, admin, [sarah], subject="Chasing this")
        two = _send(session, admin, [sarah], subject="Chasing this")
        assert one["message_id"] != two["message_id"]
        del collab


class TestSendingToSeveralPeople:

    def test_both_recipients_receive_it_and_the_sender_has_one_sent_row(
            self, session, people, analysis_id):
        from backend.services import collaboration as collab

        admin, sarah, ahmed = people
        sent = _send(session, admin, [sarah, ahmed],
                     subject="Q2 shipping deterioration",
                     attachments=[{"type": collab.ATT_ANALYSIS,
                                   "object_id": analysis_id}])
        for who in (sarah, ahmed):
            rows = collab.list_box(session, user_id=who,
                                   box=collab.BOX_INBOX)["items"]
            assert sum(1 for i in rows
                       if i["thread_id"] == sent["thread_id"]) == 1
        sent_rows = collab.list_box(session, user_id=admin,
                                    box=collab.BOX_SENT)["items"]
        mine = [i for i in sent_rows if i["message_id"] == sent["message_id"]]
        assert len(mine) == 1, "one message, not one row per recipient"
        assert {p["id"] for p in mine[0]["recipients"]} == {sarah, ahmed}


# ======================================================================
# Defect 3 — Workflow is oversight, and only for an administrator
# ======================================================================


class TestWorkflowOversight:

    def test_it_counts_what_is_actually_in_the_database(self, session, people):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        before = collab.attention_summary(session, sarah)
        _send(session, admin, [sarah], subject="Counted by oversight")
        page = collab.admin_overview(session, query="Corr", limit=200)
        row = next(u for u in page["users"] if u["id"] == sarah)
        assert row["activity"]["unread"] == before["unread"] + 1
        assert row["activity"]["received"] >= 1

    def test_it_never_returns_a_subject_or_a_body(self, session, people):
        """Oversight, not surveillance. Nothing here carries message content."""
        import json

        from backend.services import collaboration as collab

        admin, sarah, _ = people
        secret = f"CONFIDENTIAL-{uuid.uuid4().hex}"
        _send(session, admin, [sarah], subject=secret, body=secret)
        blob = json.dumps(collab.admin_overview(session, query="Corr",
                                                limit=200))
        assert secret not in blob
        blob = json.dumps(collab.admin_user_profile(session, sarah))
        assert secret not in blob

    def test_the_profile_reports_acts_rather_than_contents(self, session,
                                                           people):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        _send(session, admin, [sarah], subject="An act was performed")
        profile = collab.admin_user_profile(session, admin)
        assert "recent_activity" in profile
        for event in profile["recent_activity"]:
            assert set(event) == {"action", "object_type", "at"}

    def test_an_analyst_cannot_reach_the_aggregates_over_http(self, client,
                                                              people):
        """Hiding the navigation entry is not the control. The route is."""
        _, sarah, _ = people
        with _signed_in(client, sarah):
            assert client.get(
                "/api/v1/messages/admin/overview").status_code == 403
            assert client.get(
                f"/api/v1/messages/admin/users/{sarah}").status_code == 403

    def test_an_administrator_can(self, client, people):
        admin, _, _ = people
        with _signed_in(client, admin):
            assert client.get(
                "/api/v1/messages/admin/overview").status_code == 200


# ======================================================================
# Defect 4 — reading did not clear the badge
# ======================================================================


class TestReadingMovesTheNumber:

    def test_three_then_two_then_one_then_none(self, session, people):
        """Three messages, read one at a time. 3 → 2 → 1 → 0, never 3 → 0."""
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        start = collab.attention_summary(session, sarah)["unread"]
        threads = [_send(session, admin, [sarah],
                         subject=f"Item {n}")["thread_id"] for n in (1, 2, 3)]
        assert collab.attention_summary(session, sarah)["unread"] == start + 3

        for read, thread_id in enumerate(threads, start=1):
            collab.mark_read(session, thread_id, user_id=sarah)
            assert (collab.attention_summary(session, sarah)["unread"]
                    == start + 3 - read)

    def test_reading_a_conversation_reads_every_message_in_it(self, session,
                                                              people):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        first = _send(session, admin, [sarah], subject="Two in one thread")
        _send(session, admin, [sarah], thread_id=first["thread_id"])
        collab.mark_read(session, first["thread_id"], user_id=sarah)
        rows = collab.list_box(session, user_id=sarah,
                               box=collab.BOX_INBOX)["items"]
        row = next(i for i in rows if i["thread_id"] == first["thread_id"])
        assert row["unread"] is False

    def test_a_new_message_makes_the_conversation_unread_again(self, session,
                                                               people):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        sent = _send(session, admin, [sarah], subject="It comes back")
        collab.mark_read(session, sent["thread_id"], user_id=sarah)
        before = collab.attention_summary(session, sarah)["unread"]
        _send(session, admin, [sarah], thread_id=sent["thread_id"])
        assert collab.attention_summary(session, sarah)["unread"] == before + 1

    def test_my_own_message_is_never_unread_to_me(self, session, people):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        before = collab.attention_summary(session, admin)["unread"]
        _send(session, admin, [sarah], subject="Not my problem to read")
        assert collab.attention_summary(session, admin)["unread"] == before

    def test_replying_reads_the_conversation_i_replied_in(self, session,
                                                          people):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        sent = _send(session, admin, [sarah], subject="Reply reads it")
        # Sarah replies without opening it first.
        collab.send_message(session, sender_id=sarah, to=[admin],
                            thread_id=sent["thread_id"], body="Looking now.")
        rows = collab.list_box(session, user_id=sarah,
                               box=collab.BOX_INBOX)["items"]
        row = next(i for i in rows if i["thread_id"] == sent["thread_id"])
        assert row["unread"] is False

    def test_read_state_survives_being_read_back_from_the_database(
            self, people):
        """Persistence, not a value cached in one request."""
        from backend.db.engine import get_session
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        with get_session() as s:
            sent = _send(s, admin, [sarah], subject="Persisted read state")
            s.commit()
        with get_session() as s:
            collab.mark_read(s, sent["thread_id"], user_id=sarah)
            s.commit()
        with get_session() as s:
            rows = collab.list_box(s, user_id=sarah,
                                   box=collab.BOX_INBOX)["items"]
            row = next(i for i in rows if i["thread_id"] == sent["thread_id"])
            assert row["unread"] is False


class TestOneSummaryReconcilesWithTheBoxes:

    def test_every_count_matches_the_box_it_names(self, session, people):
        """The badge is only trustworthy if it equals what the list shows."""
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        _send(session, admin, [sarah], subject="Reconciliation")
        _send(session, sarah, [admin], subject="Something outgoing")
        counts = collab.attention_summary(session, sarah)

        for key, box in (("inbox", collab.BOX_INBOX),
                         ("sent", collab.BOX_SENT),
                         ("drafts", collab.BOX_DRAFTS),
                         ("archived", collab.BOX_ARCHIVED),
                         ("action_required", collab.BOX_ACTION)):
            listed = collab.list_box(session, user_id=sarah, box=box,
                                     limit=100)["total"]
            if key == "action_required":
                # Action Required lists CONVERSATIONS with an open request;
                # the count counts the REQUESTS. One conversation can hold
                # two, so the list can only ever be the smaller of the pair.
                assert listed <= counts[key]
            else:
                assert listed == counts[key], f"{key} disagrees with {box}"

    def test_unread_equals_the_unread_filter(self, session, people):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        _send(session, admin, [sarah], subject="Unread reconciliation")
        counts = collab.attention_summary(session, sarah)
        listed = collab.list_box(session, user_id=sarah, box=collab.BOX_INBOX,
                                 unread_only=True, limit=100)["total"]
        assert listed == counts["unread"]


class TestTheTwoHeaderBadgesDoNotOverlap:
    """One toolbar, two badges, and they must not count the same thing.

    Delivering a message writes a `notifications` row — the record that the
    person was told. The envelope badge counts unread messages; the bell counts
    everything else that happened. When the bell also counted the message rows,
    a reader with one unread message saw a 1 beside a 20 and had no way to tell
    whether the two were about the same thing.
    """

    def test_a_message_is_counted_by_the_envelope_and_not_by_the_bell(
            self, people):
        from backend.db.engine import get_session
        from backend.services import collaboration as collab
        from backend.services import workflow as wf

        admin, sarah, _ = people
        with get_session() as session:
            before_bell = wf.unread_count(sarah)
            before_mail = collab.attention_summary(session, sarah)["unread"]
            _send(session, admin, [sarah], subject="Counted once, not twice")
            session.commit()

        with get_session() as session:
            after_mail = collab.attention_summary(session, sarah)["unread"]
        after_bell = wf.unread_count(sarah)

        assert after_mail == before_mail + 1, "the envelope must count it"
        assert after_bell == before_bell, "the bell must not count it as well"

    def test_the_notification_row_is_still_written(self, people):
        # The bell not counting it is a presentation decision. The record that
        # the person was told is not, and other things read it.
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import Notification

        admin, sarah, _ = people
        with get_session() as session:
            sent = _send(session, admin, [sarah], subject="Still recorded")
            session.commit()
        with get_session() as session:
            row = session.execute(
                select(Notification).where(
                    Notification.user_id == sarah,
                    Notification.object_type == "message_thread",
                    Notification.object_id == str(sent["thread_id"]))
            ).scalars().first()
            assert row is not None

    def test_the_bell_still_reports_everything_that_is_not_a_message(
            self, people):
        from backend.db.engine import get_session
        from backend.models.platform import Notification
        from backend.services import workflow as wf

        _, sarah, _ = people
        before = wf.unread_count(sarah)
        with get_session() as session:
            session.add(Notification(user_id=sarah, kind="assigned",
                                     title="A review was raised",
                                     object_type="workflow_item",
                                     object_id="1"))
            session.commit()
        assert wf.unread_count(sarah) == before + 1


# ======================================================================
# Defect 5 — "Shared with me" stayed at zero
# ======================================================================


class TestSharedWithMeReconciles:

    def test_sharing_an_analysis_shows_up_for_the_recipient(self, session,
                                                            people,
                                                            analysis_id):
        """The reported defect: a real share, and the tile still said zero."""
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        _send(session, admin, [sarah], subject="Have a look at this",
              attachments=[{"type": collab.ATT_ANALYSIS,
                            "object_id": analysis_id}])
        assert collab.attention_summary(session, sarah)["shared_with_me"] >= 1
        listed = collab.shared_with_me(session, sarah, limit=50)
        assert any(o["object_id"] == str(analysis_id) for o in listed)

    def test_sharing_the_same_thing_twice_is_one_grant(self, session, people,
                                                       analysis_id):
        """Not an increment on every send: the count is of ACCESS, not of acts.

        Two people sending the same analysis to the same colleague have given
        them one thing to open, and a tile that counted two would send them
        looking for a second object that does not exist.
        """
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        _send(session, admin, [sarah], subject="First time",
              attachments=[{"type": collab.ATT_ANALYSIS,
                            "object_id": analysis_id}])
        before = collab.attention_summary(session, sarah)["shared_with_me"]
        _send(session, admin, [sarah], subject="Second time",
              attachments=[{"type": collab.ATT_ANALYSIS,
                            "object_id": analysis_id}])
        assert collab.attention_summary(session, sarah)["shared_with_me"] == before

    def test_the_count_and_the_list_agree(self, session, people, analysis_id):
        from backend.services import collaboration as collab

        admin, sarah, _ = people
        _send(session, admin, [sarah], subject="Reconcile the tile",
              attachments=[{"type": collab.ATT_ANALYSIS,
                            "object_id": analysis_id}])
        counts = collab.attention_summary(session, sarah)
        listed = collab.shared_with_me(session, sarah, limit=500)
        assert counts["shared_with_me"] >= len(listed) > 0

    def test_sending_an_analysis_to_myself_grants_it_to_myself(
            self, session, people, analysis_id):
        """The self-send path must write the share like any other recipient."""
        from backend.services import collaboration as collab

        admin, _, _ = people
        _send(session, admin, [admin], subject="Filing this where I find it",
              attachments=[{"type": collab.ATT_ANALYSIS,
                            "object_id": analysis_id}])
        assert any(o["object_id"] == str(analysis_id)
                   for o in collab.shared_with_me(session, admin, limit=500))


class TestTheSharePickerOffersOnlyWhatICanShare:

    def test_it_returns_cards_not_identifiers(self, session, people,
                                              analysis_id):
        from backend.services import collaboration as collab

        admin, _, _ = people
        items = collab.shareable_objects(session, user_id=admin,
                                         object_type=collab.ATT_ANALYSIS,
                                         limit=20)
        assert items, "an administrator can read analyses, so some should list"
        for item in items:
            assert item["object_id"]
            assert "meta" in item
        del analysis_id

    def test_everything_it_offers_can_actually_be_attached(self, session,
                                                           people):
        from backend.services import collaboration as collab

        admin, _, _ = people
        for item in collab.shareable_objects(session, user_id=admin,
                                             object_type=collab.ATT_ANALYSIS,
                                             limit=10):
            assert collab.can_read_object(session, collab.ATT_ANALYSIS,
                                          item["object_id"], admin)

    def test_an_unknown_kind_is_refused(self, session, people):
        from backend.services import collaboration as collab

        admin, _, _ = people
        with pytest.raises(collab.InvalidRequest):
            collab.shareable_objects(session, user_id=admin,
                                     object_type="borrower")


# ======================================================================
# Fixtures and helpers used above
# ======================================================================


@pytest.fixture(scope="module")
def analysis_id():
    """A real saved analysis to attach. Skips rather than inventing one."""
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import SavedAnalysis

    with get_session() as session:
        row = session.execute(
            select(SavedAnalysis).order_by(SavedAnalysis.id.desc()).limit(1)
        ).scalars().first()
        if row is None:
            pytest.skip("No saved analysis in this database to share.")
        return str(row.id)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    with TestClient(app) as c:
        yield c


class _signed_in:
    """Sign a real account in for the duration of a block.

    Through the login route rather than by forging a header: the point of the
    authorization tests above is that the posture is the product's own.
    """

    def __init__(self, client, user_id: int):
        self.client = client
        self.user_id = user_id

    def __enter__(self):
        from backend.db.engine import get_session
        from backend.db.models import User

        with get_session() as session:
            row = session.get(User, self.user_id)
            username = row.username
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "creditprobe-demo"},
        )
        assert response.status_code == 200, response.text
        return self.client

    def __exit__(self, *exc):
        self.client.post("/api/v1/auth/logout")
        self.client.cookies.clear()
        return False
