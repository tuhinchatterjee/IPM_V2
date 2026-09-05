"""The seeded example workflow: enough to review, and safe to run twice.

Why a test rather than eyeballing it
-------------------------------------
A seed runs on every bootstrap, and the failure mode is not a crash — it is a
second copy. An inbox that gains one more "Shipping deterioration" every time a
container restarts looks like the messaging feature is duplicating mail, and by
the time anybody notices there are nine of them.

The determinism test earns its place the hard way: the first version of
`seed_data_release` ordered published datasets by `published_at`, which is a
tie across everything a build script installed in the same second. Two calls
picked two different datasets and produced two notifications, each individually
idempotent and collectively wrong.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("The workflow seed needs a database.")


@pytest.fixture
def session():
    from backend.db.engine import get_session

    with get_session() as s:
        yield s


class TestTheExampleConversations:

    def test_running_it_twice_creates_nothing_new(self, session):
        from backend.services import demo_workflow

        demo_workflow.seed(session)
        session.flush()
        again = demo_workflow.seed(session)
        assert again.created == []

    def test_it_reports_what_it_kept(self, session):
        from backend.services import demo_workflow

        demo_workflow.seed(session)
        session.flush()
        again = demo_workflow.seed(session)
        assert len(again.kept) >= 1

    def test_it_says_so_rather_than_half_seeding_without_the_accounts(
            self, session, monkeypatch):
        # A conversation needs a sender and a recipient. Seeding one with a
        # missing participant would produce a thread nobody can answer.
        from backend.services import demo_workflow

        monkeypatch.setattr(demo_workflow, "_user", lambda *a, **k: None)
        result = demo_workflow.seed(session)
        assert result.created == []
        assert result.skipped

    def test_the_attachments_point_at_objects_that_exist(self, session):
        from backend.models.platform import Investigation, SavedAnalysis
        from backend.services import collaboration as collab
        from backend.services import demo_workflow

        demo_workflow.seed(session)
        session.flush()
        sarah = demo_workflow._user(session, "sarah.khan")
        if sarah is None:
            pytest.skip("The demonstration accounts are not seeded here.")
        # Whatever the seed chose, it must be readable by the sender AND
        # actually be there. A card that opens onto a 404 teaches a reviewer
        # that the cards are decorative.
        investigation = demo_workflow._an_investigation(session, sarah.id)
        if investigation:
            assert session.get(Investigation, int(investigation)) is not None
            assert collab.can_read_object(session, "investigation",
                                          investigation, sarah.id)
        analysis = demo_workflow._an_analysis(session, sarah.id)
        if analysis:
            assert session.get(SavedAnalysis, int(analysis)) is not None
            assert collab.can_read_object(session, "analysis", analysis,
                                          sarah.id)

    def test_the_seed_does_not_fail_when_nothing_is_readable(
            self, session, monkeypatch):
        """The bug this replaces took `docker compose up` down.

        `_an_analysis` used to pick the newest analysis whose title matched,
        and failing that the newest analysis anywhere, without asking whether
        the sender could read it. On a fresh database every saved analysis
        belongs to the account that generated the portfolio, so the answer was
        always no: `send_message` refused with "You cannot share an analysis
        you do not have access to", the bootstrap step recorded FAILED, the
        readiness marker recorded `ok: false`, and the container never went
        healthy. The web container waits on that health, so the stack came up
        with no user interface.

        Pinned by making every analysis unreadable to the sender and asserting
        the seed still produces its conversations — with no attachment rather
        than with no thread.
        """
        from backend.services import collaboration as collab
        from backend.services import demo_workflow

        sarah = demo_workflow._user(session, "sarah.khan")
        if sarah is None:
            pytest.skip("The demonstration accounts are not seeded here.")

        monkeypatch.setattr(collab, "can_read_object",
                            lambda *a, **k: False)

        assert demo_workflow._an_analysis(session, sarah.id) == ""
        made = demo_workflow.seed(session)
        session.flush()

        assert made.skipped == [], (
            "the seed refused to run rather than sending an unattached note")
        assert made.created or made.kept, "no conversation was produced"


class TestTheDataReleaseNotification:

    def test_the_dataset_choice_is_stable(self, session):
        from backend.services import demo_workflow

        keys = set()
        for _ in range(3):
            made = demo_workflow.seed_data_release(session)
            session.flush()
            if made.get("created") is False and made.get("event_key"):
                keys.add(made["event_key"])
            elif made.get("event_key"):
                keys.add(made["event_key"])
        if not keys:
            pytest.skip("No governed release to describe on this deployment.")
        assert len(keys) == 1, f"the seed described {len(keys)} datasets: {keys}"

    def test_running_it_twice_creates_nothing_new(self, session):
        from backend.services import demo_workflow

        first = demo_workflow.seed_data_release(session)
        session.flush()
        if first.get("reason"):
            pytest.skip(f"No governed release: {first['reason']}")
        again = demo_workflow.seed_data_release(session)
        assert again["created"] is False
        assert again["message_id"] == first["message_id"]

    def test_it_explains_itself_when_there_is_nothing_to_describe(self, session):
        # Silence would make the absent message look like a defect in the
        # messaging feature rather than a fact about this deployment.
        from backend.services import demo_workflow

        made = demo_workflow.seed_data_release(session,
                                               dataset="no_such_dataset_here")
        assert made["created"] is False
        assert made["reason"]

    def test_every_figure_it_prints_came_from_somewhere(self, session):
        from backend.services import collaboration as collab
        from backend.services import demo_workflow

        made = demo_workflow.seed_data_release(session)
        session.flush()
        if made.get("reason"):
            pytest.skip(f"No governed release: {made['reason']}")
        thread = collab.get_thread(session, made["thread_id"],
                                   user_id=_a_recipient(session, made))
        message = thread["messages"][0]
        context = message["context"]
        # If the body claims a record count, the context must carry it. A
        # number in the prose with nothing behind it is the exact failure the
        # governed-facts rule exists to prevent.
        if "records" in message["body"]:
            assert context.get("row_count") is not None
        if "borrowers" in message["body"]:
            assert context.get("borrower_count") is not None
        if "validated" in message["body"]:
            assert context.get("validated") is True

    def test_the_actions_it_offers_are_all_supported(self, session):
        from backend.services import collaboration as collab
        from backend.services import demo_workflow

        made = demo_workflow.seed_data_release(session)
        session.flush()
        if made.get("reason"):
            pytest.skip(f"No governed release: {made['reason']}")
        message = collab.get_thread(
            session, made["thread_id"],
            user_id=_a_recipient(session, made))["messages"][0]
        actions = {a["action"] for a in message["actions"]}
        assert actions <= {"open_dataset", "start_investigation",
                           "compare_previous_period"}
        # And the compare button only where there is something to compare to.
        if "compare_previous_period" in actions:
            assert message["context"].get("previous_period")

    def test_it_is_signed_by_the_product_and_by_no_provider(self, session):
        from backend.services import collaboration as collab
        from backend.services import demo_workflow

        made = demo_workflow.seed_data_release(session)
        session.flush()
        if made.get("reason"):
            pytest.skip(f"No governed release: {made['reason']}")
        message = collab.get_thread(
            session, made["thread_id"],
            user_id=_a_recipient(session, made))["messages"][0]
        assert message["sender"]["name"] == "CreditProbe AI"
        blob = (message["body"] + str(message["actions"])).lower()
        for name in ("claude", "anthropic", "openai", "gpt-", "sonnet",
                     "opus", "gemini"):
            assert name not in blob


def _a_recipient(session, made) -> int:
    """Somebody the notification was actually sent to.

    Reading the thread as a non-participant is refused, which is the point of
    the design — so the test has to ask as one of the people it went to rather
    than as an arbitrary id.
    """
    from sqlalchemy import select

    from backend.models.collaboration import ThreadParticipant

    return session.execute(
        select(ThreadParticipant.user_id)
        .where(ThreadParticipant.thread_id == made["thread_id"]).limit(1)
    ).scalars().one()
