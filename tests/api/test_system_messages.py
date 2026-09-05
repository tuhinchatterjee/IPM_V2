"""CreditProbe as a sender: what it may say, and what it may never claim.

Three properties, in order of how much they matter
----------------------------------------------------
1. **It cannot be impersonated.** `sender_type = SYSTEM` implies no
   `sender_user_id`, enforced by a database check constraint rather than by a
   service remembering to leave the field alone. There is no account called
   "CreditProbe AI" for an administrator to sign into, and no request body that
   can name one.

2. **It does not invent figures.** A row count appears in the message only if
   the publication supplied it. This is the same rule the answer path lives by,
   applied to notifications: a reader must be able to trust a number in a
   CreditProbe message the way they trust one in an answer.

3. **It does not offer what it cannot do.** "Compare with the previous quarter"
   requires a previous quarter. Without one the button is absent, rather than
   present and then apologetic.

And one operational property: the same publication, replayed after a restart or
a retry, produces one message rather than two. The idempotency is a unique
index on the event key, so it holds even if a second caller appears later.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("System messages need a database.")


@pytest.fixture(scope="module")
def people():
    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    made = []
    with get_session() as session:
        for first, role in (("Steward", "DATA_STEWARD"), ("Analyst", "ANALYST"),
                            ("Onlooker", "VIEWER")):
            row = User(username=f"t.{uuid.uuid4().hex[:12]}",
                       password_hash=hash_password("creditprobe-demo"),
                       first_name=first, last_name="Test", role=role,
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


def _publish(session, recipients, **kw):
    from backend.services import collaboration as collab

    kw.setdefault("dataset", f"ds_{uuid.uuid4().hex[:8]}")
    kw.setdefault("dataset_label", "Corporate IFRS 9")
    kw.setdefault("period", "Q3 2026")
    kw.setdefault("version", "7")
    return collab.publish_data_release_event(session, recipients=list(recipients),
                                             **kw)


class TestTheProductIsTheSender:

    def test_the_message_has_no_user_behind_it(self, session, people):
        from backend.models.collaboration import Message

        steward, analyst, _ = people
        made = _publish(session, [steward])
        row = session.get(Message, made["message_id"])
        assert row.sender_type == "SYSTEM"
        assert row.sender_user_id is None

    def test_it_is_shown_as_creditprobe_ai(self, session, people):
        from backend.services import collaboration as collab

        steward, _, _ = people
        made = _publish(session, [steward])
        message = collab.get_thread(session, made["thread_id"],
                                    user_id=steward)["messages"][0]
        assert message["sender"]["type"] == "SYSTEM"
        assert message["sender"]["name"] == "CreditProbe AI"
        assert message["sender"]["user"] is None

    def test_no_provider_name_reaches_the_reader(self, session, people):
        # The product speaks to the user. Which foundation model produced any
        # of it is an implementation detail they did not ask about.
        from backend.services import collaboration as collab

        steward, _, _ = people
        made = _publish(session, [steward], row_count=16521,
                        borrower_count=4128, validated=True)
        thread = collab.get_thread(session, made["thread_id"],
                                   user_id=steward)
        blob = (thread["subject"] + thread["messages"][0]["body"]
                + str(thread["messages"][0]["actions"])).lower()
        for name in ("claude", "anthropic", "openai", "gpt", "sonnet", "opus",
                     "gemini", "llama"):
            assert name not in blob

    def test_the_database_refuses_a_forged_system_row(self, session, people):
        # Not "the service declines to write it" — the schema refuses it. A
        # guard that lives only in one function is a guard a second caller
        # walks around.
        import sqlalchemy.exc

        from backend.models.collaboration import Message, MessageThread

        steward, _, _ = people
        thread = MessageThread(subject="Forged", created_by=None,
                               origin="SYSTEM")
        session.add(thread)
        session.flush()
        session.add(Message(thread_id=thread.id, sender_type="SYSTEM",
                            sender_user_id=steward, body="I am the product.",
                            status="sent"))
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            session.flush()
        session.rollback()

    def test_a_user_message_must_name_its_sender(self, session, people):
        import sqlalchemy.exc

        from backend.models.collaboration import Message, MessageThread

        thread = MessageThread(subject="Anonymous", created_by=None)
        session.add(thread)
        session.flush()
        session.add(Message(thread_id=thread.id, sender_type="USER",
                            sender_user_id=None, body="x", status="sent"))
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            session.flush()
        session.rollback()

    def test_a_system_message_cannot_grant_a_governed_object(self, session,
                                                             people):
        # Granting access on the product's own authority, with no sender whose
        # own access could be checked, is exactly the silent escalation the
        # design forbids.
        from backend.services import collaboration as collab

        steward, _, _ = people
        with pytest.raises(collab.InvalidRequest):
            collab.send_system_message(
                session, event=collab.EVENT_DATA_RELEASE_PUBLISHED,
                event_key=uuid.uuid4().hex, subject="s", body="b",
                recipients=[steward],
                attachments=[{"type": "investigation", "object_id": "1"}])


class TestItDoesNotInventFigures:

    def test_supplied_counts_appear(self, session, people):
        from backend.services import collaboration as collab

        steward, _, _ = people
        made = _publish(session, [steward], row_count=16521,
                        borrower_count=4128, validated=True)
        body = collab.get_thread(session, made["thread_id"],
                                 user_id=steward)["messages"][0]["body"]
        assert "16,521 records" in body
        assert "4,128 borrowers" in body

    def test_absent_counts_are_absent_rather_than_estimated(self, session,
                                                            people):
        from backend.services import collaboration as collab

        steward, _, _ = people
        made = _publish(session, [steward])
        message = collab.get_thread(session, made["thread_id"],
                                    user_id=steward)["messages"][0]
        assert "records" not in message["body"]
        assert "borrowers" not in message["body"]
        assert message["context"]["row_count"] is None

    def test_validation_is_only_claimed_when_it_was_stated(self, session,
                                                           people):
        from backend.services import collaboration as collab

        steward, _, _ = people
        unstated = _publish(session, [steward])
        stated = _publish(session, [steward], validated=True)
        unstated_body = collab.get_thread(
            session, unstated["thread_id"], user_id=steward)["messages"][0]["body"]
        stated_body = collab.get_thread(
            session, stated["thread_id"], user_id=steward)["messages"][0]["body"]
        assert "validated" not in unstated_body
        assert "validated and published" in stated_body

    def test_the_governed_facts_are_kept_beside_the_prose(self, session,
                                                          people):
        # So a reader, or a later audit, can check the sentence against what
        # the publication actually reported.
        from backend.services import collaboration as collab

        steward, _, _ = people
        made = _publish(session, [steward], row_count=16521, period="Q3 2026",
                        version="7")
        context = collab.get_thread(session, made["thread_id"],
                                    user_id=steward)["messages"][0]["context"]
        assert context["row_count"] == 16521
        assert context["period"] == "Q3 2026"
        assert context["version"] == "7"


class TestItOnlyOffersWhatItCanDo:

    def test_open_dataset_and_start_investigation_are_always_offered(
            self, session, people):
        from backend.services import collaboration as collab

        steward, _, _ = people
        made = _publish(session, [steward])
        actions = collab.get_thread(session, made["thread_id"],
                                    user_id=steward)["messages"][0]["actions"]
        assert {a["action"] for a in actions} >= {"open_dataset",
                                                  "start_investigation"}

    def test_compare_appears_only_with_a_previous_period(self, session,
                                                         people):
        from backend.services import collaboration as collab

        steward, _, _ = people
        without = _publish(session, [steward])
        with_previous = _publish(session, [steward], previous_period="Q2 2026")
        a = {x["action"] for x in collab.get_thread(
            session, without["thread_id"],
            user_id=steward)["messages"][0]["actions"]}
        b = {x["action"] for x in collab.get_thread(
            session, with_previous["thread_id"],
            user_id=steward)["messages"][0]["actions"]}
        assert "compare_previous_period" not in a
        assert "compare_previous_period" in b

    def test_start_investigation_carries_structured_context(self, session,
                                                            people):
        # Not decorative text. The Cockpit opens on a question about THIS
        # dataset at THIS period, which is what makes the button worth having.
        from backend.services import collaboration as collab

        steward, _, _ = people
        # A dataset name of this run's own. `publish_data_release_event` is
        # idempotent on dataset+version across the whole database, so a fixed
        # name would return whatever an earlier run already published — a
        # thread this test's user is correctly not a participant in.
        dataset = f"portfolio_facility_{uuid.uuid4().hex[:8]}"
        made = _publish(session, [steward], dataset=dataset,
                        domain="corporate_credit", period="Q3 2026")
        actions = collab.get_thread(session, made["thread_id"],
                                    user_id=steward)["messages"][0]["actions"]
        start = next(a for a in actions if a["action"] == "start_investigation")
        assert start["context"]["dataset"] == dataset
        assert start["context"]["period"] == "Q3 2026"
        assert start["href"].startswith("/?focus=ask&q=")

    def test_compare_names_both_periods(self, session, people):
        from urllib.parse import unquote

        from backend.services import collaboration as collab

        steward, _, _ = people
        made = _publish(session, [steward], period="Q3 2026",
                        previous_period="Q2 2026")
        actions = collab.get_thread(session, made["thread_id"],
                                    user_id=steward)["messages"][0]["actions"]
        compare = next(a for a in actions
                       if a["action"] == "compare_previous_period")
        assert compare["context"]["from_period"] == "Q2 2026"
        assert compare["context"]["to_period"] == "Q3 2026"
        assert "Q2 2026" in unquote(compare["href"])
        assert "Q3 2026" in unquote(compare["href"])


class TestItHappensOnce:

    def test_a_replayed_publication_creates_nothing_new(self, session, people):

        steward, _, _ = people
        dataset = f"ds_{uuid.uuid4().hex[:8]}"
        first = _publish(session, [steward], dataset=dataset, version="7")
        again = _publish(session, [steward], dataset=dataset, version="7")
        assert first["created"] is True
        assert again["created"] is False
        assert again["message_id"] == first["message_id"]

    def test_a_different_version_is_a_different_event(self, session, people):

        steward, _, _ = people
        dataset = f"ds_{uuid.uuid4().hex[:8]}"
        first = _publish(session, [steward], dataset=dataset, version="7")
        second = _publish(session, [steward], dataset=dataset, version="8")
        assert second["message_id"] != first["message_id"]

    def test_the_key_is_unique_in_the_schema_not_just_in_the_service(
            self, session, people):
        import sqlalchemy.exc

        from backend.models.collaboration import Message, MessageThread

        steward, _, _ = people
        key = f"DATA_RELEASE_PUBLISHED:{uuid.uuid4().hex}"
        for _ in range(2):
            thread = MessageThread(subject="Dup", created_by=None,
                                   origin="SYSTEM")
            session.add(thread)
            session.flush()
            session.add(Message(thread_id=thread.id, sender_type="SYSTEM",
                                sender_user_id=None, body="x", status="sent",
                                event_key=key))
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            session.flush()
        session.rollback()

    def test_an_unknown_event_is_refused(self, session, people):
        from backend.services import collaboration as collab

        steward, _, _ = people
        with pytest.raises(collab.InvalidRequest):
            collab.send_system_message(
                session, event="SOMETHING_HAPPENED",
                event_key=uuid.uuid4().hex, subject="s", body="b",
                recipients=[steward])


class TestWhoIsTold:

    def test_the_publisher_may_name_the_recipients(self, session, people):
        from backend.services import collaboration as collab

        steward, analyst, onlooker = people
        made = _publish(session, [steward, analyst])
        thread = collab.get_thread(session, made["thread_id"],
                                   user_id=steward)
        assert {p["id"] for p in thread["participants"]} == {steward, analyst}

    def test_without_an_explicit_list_it_goes_to_people_who_can_act(
            self, session, people):
        # Not everybody. A notification everyone receives about everything is
        # one everyone learns to dismiss, and the first thing dismissed with
        # it is the one that mattered.
        from backend.services import collaboration as collab

        recipients = collab.data_release_recipients(session)
        roles = _roles_of(session, recipients)
        assert roles <= {"ADMIN", "DATA_STEWARD", "ANALYST"}
        assert "VIEWER" not in roles

    def test_a_viewer_is_not_notified_of_a_data_release(self, session, people):
        from backend.services import collaboration as collab

        _, _, onlooker = people
        assert onlooker not in collab.data_release_recipients(session)

    def test_a_deactivated_person_is_not_notified(self, session, people):
        from backend.db.models import User
        from backend.services import collaboration as collab

        steward, analyst, _ = people
        row = session.get(User, analyst)
        row.is_active = False
        session.flush()
        try:
            assert analyst not in collab.data_release_recipients(session)
            assert analyst not in collab.data_release_recipients(
                session, explicit=[steward, analyst])
        finally:
            row.is_active = True
            session.flush()

    def test_nobody_to_tell_is_refused_rather_than_silently_dropped(
            self, session, people):
        from backend.services import collaboration as collab

        with pytest.raises(collab.InvalidRequest):
            collab.send_system_message(
                session, event=collab.EVENT_DATA_RELEASE_PUBLISHED,
                event_key=uuid.uuid4().hex, subject="s", body="b",
                recipients=[])

    def test_the_recipient_is_notified_in_the_normal_way(self, session,
                                                         people):
        # Through the same `notifications` table the header badge already
        # reads, not a second counter that can disagree with it.
        from sqlalchemy import select

        from backend.models.platform import Notification

        steward, _, _ = people
        made = _publish(session, [steward])
        rows = session.execute(
            select(Notification).where(
                Notification.user_id == steward,
                Notification.object_type == "message_thread",
                Notification.object_id == str(made["thread_id"]))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].body == "From CreditProbe AI"


def _roles_of(session, user_ids):
    from sqlalchemy import select

    from backend.db.models import User

    return {str(r or "").upper() for r in session.execute(
        select(User.role).where(User.id.in_(user_ids or [-1]))
    ).scalars().all()}


class TestSystemMessagesAreAudited:

    def test_creating_one_writes_a_system_actor_row(self, session, people):
        from sqlalchemy import select

        from backend.models.collaboration import CollaborationAudit
        from backend.services import collaboration as collab

        steward, _, _ = people
        made = _publish(session, [steward])
        rows = session.execute(
            select(CollaborationAudit).where(
                CollaborationAudit.action == collab.SYSTEM_NOTIFICATION_CREATED,
                CollaborationAudit.object_id == str(made["message_id"]))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_type == "SYSTEM"
        assert rows[0].actor_id is None
        assert rows[0].detail["event"] == collab.EVENT_DATA_RELEASE_PUBLISHED
