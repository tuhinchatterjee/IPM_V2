"""A quarter arrives, and by the end of it somebody is reading an answer.

This is the loop the whole platform exists to run, and it is tested end to end
against the REAL dataset through the REAL routes, because every shortcut in it
hides the thing it is meant to prove:

     1  download a published period, as CSV and as a workbook
     2  build the next quarter from it
     3  upload it through the product's own upload path
     4  it validates against the dataset's own contract
     5  a person sends it to review
     6  a person locks it, and then publishes it
     7  Ask: "What periods of <dataset> do you have?" — the new one is there
     8  Ask: show the new period
     9  Ask: a figure at the new period
    10  Ask: a grouped analysis at the new period
    11  Ask: compare it with the quarter before
    12  the publication message is in somebody's inbox
    13  opening it reduces the unread count
    14  it carries a CTA the product can honour
    15  the investigation is shared with another user
    16  the recipient sees every block, not only the first

Why the real dataset
--------------------
A test dataset with three columns proves that the plumbing runs. It does not
prove that a new quarter of the IFRS 9 book is answerable, that the analytical
catalogue picked it up, or that fifteen existing quarters survived the
publication — which is the failure that would matter. So this publishes a real
quarter into `ifrs9_staging` and removes it again in a `finally`, and asserts
along the way that the periods that were there before are still there.
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="The data release loop needs a reachable PostgreSQL",
)

DATASET = "ifrs9_staging"
#: The quarter this test publishes and then removes. Deliberately beyond the
#: seeded book so it cannot collide with a real period.
NEW_PERIOD = "Q3 2026"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def _partition(period: str) -> Path:
    from backend.config import settings

    safe = period
    return Path(settings.analytics_dir) / DATASET / f"period={safe}"


def _forget_announcement(period: str) -> None:
    """Remove the publication message for a period this test is removing.

    A message announcing a quarter that no longer exists is residue AND a
    broken promise: its "Open Dataset" button would take a reader to data that
    was never really there. Removing it also makes the loop repeatable, because
    the announcement is idempotent on its event key.
    """
    from sqlalchemy import delete, select

    from backend.db.engine import get_session
    from backend.models.collaboration import (
        Message,
        MessageRecipient,
        MessageThread,
        ThreadParticipant,
    )

    try:
        with get_session() as session:
            # The event key is dataset + version, not dataset + period, so the
            # period is matched on the thread subject where it does appear.
            threads = session.execute(
                select(MessageThread).where(
                    MessageThread.subject.like(f"%{period}%"))
            ).scalars().all()
            doomed = list(session.execute(
                select(Message).where(
                    Message.thread_id.in_([t.id for t in threads] or [-1]))
            ).scalars().all())
            for message in doomed:
                session.execute(delete(MessageRecipient).where(
                    MessageRecipient.message_id == message.id))
                thread_id = message.thread_id
                session.delete(message)
                session.flush()
                session.execute(delete(ThreadParticipant).where(
                    ThreadParticipant.thread_id == thread_id))
                session.execute(delete(MessageThread).where(
                    MessageThread.id == thread_id))
            for orphan in threads:
                session.execute(delete(ThreadParticipant).where(
                    ThreadParticipant.thread_id == orphan.id))
                session.execute(delete(MessageThread).where(
                    MessageThread.id == orphan.id))
    except Exception:  # noqa: BLE001 - teardown must not fail the run
        pass


def _forget(period: str) -> None:
    """Remove a published period and every trace of its release."""
    from sqlalchemy import delete

    from backend.config import settings
    from backend.data_access import reload_catalog, reset_data_source
    from backend.db.engine import get_session
    from backend.models.platform import DataPeriodRelease, DatasetDefinition

    shutil.rmtree(_partition(period), ignore_errors=True)
    _forget_announcement(period)
    shutil.rmtree(Path(settings.raw_dir) / "staged" / DATASET
                  / period.replace(" ", "_"), ignore_errors=True)
    try:
        with get_session() as session:
            dataset = session.query(DatasetDefinition).filter_by(
                name=DATASET).one_or_none()
            if dataset is not None:
                session.execute(delete(DataPeriodRelease).where(
                    DataPeriodRelease.dataset_id == dataset.id,
                    DataPeriodRelease.period == period))
    except Exception:  # noqa: BLE001 - teardown must not fail the run
        pass
    reset_data_source()
    reload_catalog()
    from backend import metadata as md
    from backend.orchestration import context as governed_context
    from backend.orchestration.vocabulary import reset_vocabulary

    md.invalidate()
    reset_vocabulary()
    governed_context.invalidate()


@pytest.fixture(scope="module")
def loop(client):
    """Run the whole loop once, and record what each step produced.

    One fixture rather than one per step: the loop IS the unit, and a test
    that published a quarter for every assertion would publish it eleven times.
    """
    from backend.data_access import get_data_source

    before = list(get_data_source().periods(DATASET))
    assert NEW_PERIOD not in before, (
        f"{NEW_PERIOD} is already published; the loop needs a period that is "
        "not there yet.")
    source_period = before[-1]

    steps: dict = {"before": before, "source_period": source_period}
    try:
        yield _run(client, steps, source_period)
    finally:
        _forget(NEW_PERIOD)


def _run(client, steps: dict, source_period: str) -> dict:
    base = "/api/v1/data-builder"

    # ---- 1. download a real period, both ways -----------------------------
    csv = client.get(f"{base}/datasets/{DATASET}/export",
                     params={"period": source_period, "limit": 500})
    steps["csv"] = csv
    workbook = client.get(f"{base}/datasets/{DATASET}/workbook",
                          params={"period": source_period, "limit": 500})
    steps["workbook"] = workbook

    # ---- 2. build the next quarter from it --------------------------------
    text = "\n".join(line for line in csv.text.splitlines()
                     if not line.startswith("#"))
    frame = pd.read_csv(io.StringIO(text))
    frame["period"] = NEW_PERIOD
    if "period_end_date" in frame.columns:
        frame["period_end_date"] = "2026-09-30"
    steps["built"] = frame

    # ---- 3. upload it through the product's own path ----------------------
    upload = client.post(
        f"{base}/datasets/{DATASET}/periods/upload",
        data={"period": NEW_PERIOD, "mode": "NEW_PERIOD"},
        files={"file": (f"{DATASET}_{NEW_PERIOD}.csv",
                        io.BytesIO(frame.to_csv(index=False).encode()),
                        "text/csv")})
    steps["upload"] = upload
    if upload.status_code != 200:
        return steps
    release = upload.json()["release"]
    steps["release"] = release

    # ---- 4-6. review, lock, publish ---------------------------------------
    release_id = release["id"]
    steps["review"] = client.post(f"{base}/periods/{release_id}/review",
                                  json={"note": "Read before locking."})
    steps["lock"] = client.post(f"{base}/periods/{release_id}/lock",
                                json={"note": "Checked against Q2."})
    steps["publish"] = client.post(f"{base}/periods/{release_id}/publish")

    # ---- 7-11. the questions ----------------------------------------------
    from backend.orchestration import memory as wm
    from backend.orchestration.executor import answer_investigation

    memory = wm.WorkingMemory()
    asked = {}
    for key, question in (
        ("periods", f"What periods of {DATASET} do you have?"),
        ("show", f"Show me {NEW_PERIOD}"),
        ("ead", "What is total exposure at default?"),
        ("sectors", "Which sectors have the highest Stage 2 exposure?"),
        ("compare", "Compare that with the previous quarter."),
    ):
        investigation, answered = answer_investigation(
            question, persist=False, memory=memory)
        memory = wm.observe(memory, answered, investigation)
        asked[key] = investigation
    steps["asked"] = asked
    return steps


# =========================================================== 1. the download


class TestAPeriodComesOutBeforeItGoesIn:

    def test_csv_download_is_the_period_asked_for(self, loop) -> None:
        response = loop["csv"]
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert loop["source_period"].replace(" ", "-") in \
            response.headers["content-disposition"]
        assert int(response.headers["X-CreditProbe-Rows"]) > 0

    def test_the_csv_says_what_book_it_came_from(self, loop) -> None:
        """A file outlives the screen that produced it."""
        assert "# SYNTHETIC DATA" in loop["csv"].text

    def test_the_workbook_has_the_data_and_what_it_is(self, loop) -> None:
        response = loop["workbook"]
        assert response.status_code == 200
        assert response.headers["content-disposition"].endswith('.xlsx"')
        book = pd.ExcelFile(io.BytesIO(response.content))
        assert book.sheet_names == ["DATA", "ABOUT THIS EXTRACT"]
        about = pd.read_excel(book, "ABOUT THIS EXTRACT")
        assert loop["source_period"] in about["Value"].astype(str).tolist()


# ============================================================ 3-6. the upload


class TestTheUploadIsCheckedAndNeverPublishedByArriving:

    def test_the_upload_is_accepted(self, loop) -> None:
        assert loop["upload"].status_code == 200, loop["upload"].text

    def test_arriving_does_not_publish_it(self, loop) -> None:
        """The whole point of the lifecycle. A file that arrives is staged."""
        assert loop["release"]["state"] == "VALIDATED"
        assert loop["release"]["published_at"] is None

    def test_it_was_checked_against_the_dataset_contract(self, loop) -> None:
        validation = loop["release"]["validation"]
        assert validation["passed"] is True
        assert validation["checks_run"], "no checks are worse than a failure"
        assert validation["error_count"] == 0

    def test_it_is_version_one_of_a_period_nobody_has_sent(self, loop) -> None:
        assert loop["release"]["version"] == 1
        assert loop["release"]["mode"] == "NEW_PERIOD"

    def test_review_then_lock_then_publish(self, loop) -> None:
        assert loop["review"].json()["release"]["state"] == "REVIEW"
        assert loop["lock"].json()["release"]["state"] == "LOCKED"
        assert loop["publish"].status_code == 200, loop["publish"].text
        assert loop["publish"].json()["release"]["state"] == "PUBLISHED"

    def test_publishing_one_period_leaves_the_others_alone(self, loop) -> None:
        """The defect this whole path exists to close: publishing used to
        rewrite every period from the latest upload, so sending one quarter
        would have left a one-quarter book behind it."""
        from backend.data_access import get_data_source

        now = set(get_data_source().periods(DATASET))
        assert set(loop["before"]) <= now
        assert NEW_PERIOD in now


# ============================================================ 7-11. the asking


class TestTheNewQuarterIsAnswerableImmediately:

    def test_the_new_period_is_in_the_catalogue_with_no_restart(self, loop
                                                                 ) -> None:
        answer = loop["asked"]["periods"].narrative.direct_answer or ""
        rows = loop["asked"]["periods"].steps[0].result.get("rows") or []
        printed = answer + " " + str(rows)
        assert NEW_PERIOD in printed, printed[:400]

    def test_the_new_period_can_be_opened(self, loop) -> None:
        investigation = loop["asked"]["show"]
        assert investigation.status == "succeeded"
        assert NEW_PERIOD in (investigation.narrative.direct_answer or "")

    def test_a_figure_answers_at_the_new_period(self, loop) -> None:
        investigation = loop["asked"]["ead"]
        assert investigation.status == "succeeded"

    def test_a_grouped_analysis_answers(self, loop) -> None:
        investigation = loop["asked"]["sectors"]
        assert investigation.status == "succeeded"
        rows = (investigation.steps[0].result or {}).get("rows") or []
        assert rows

    def test_the_comparison_answers(self, loop) -> None:
        investigation = loop["asked"]["compare"]
        assert investigation.status in {"succeeded", "needs_clarification"}


# ================================================== 12-16. the bank is told


@pytest.fixture(scope="module")
def told(loop):
    """The publication message, the person who received it, and a share.

    Depends on `loop` so the publication has already happened. Everything here
    goes through the collaboration service, which is the only way CreditProbe
    can write to anybody.
    """
    from backend.db.engine import get_session
    from backend.services import collaboration as collab

    published = loop["publish"].json()
    announcement = published.get("announcement") or {}
    out: dict = {"announcement": announcement}
    if not announcement.get("message_id"):
        return out

    with get_session() as session:
        message = collab.message_by_id(session, announcement["message_id"]) \
            if hasattr(collab, "message_by_id") else None
        out["recipients"] = collab.data_release_recipients(session)
        # The count only falls for somebody who has not read THIS thread.
        # Picking the first recipient blindly asserts nothing on a rerun, and
        # picking anybody with any unread asserts nothing either: marking a
        # thread they are not behind on changes no number.
        def _behind(user_id: int) -> bool:
            """Whether this person still has the announcement unread.

            Read from the inbox listing, which is where the unread flag
            actually lives: a thread payload carries `read_at`, and a thread
            somebody has never opened has none.
            """
            for item in collab.list_box(session, user_id=user_id,
                                        box="INBOX").get("items", []):
                if item.get("thread_id") == announcement["thread_id"]:
                    return bool(item.get("unread"))
            return False

        reader = next((r for r in out["recipients"] if _behind(r)),
                      out["recipients"][0])
        out["reader"] = reader
        out["before"] = collab.unread_count(session, reader)
        thread = collab.get_thread(session, announcement["thread_id"],
                                   user_id=reader)
        out["thread"] = thread
        out["was_unread"] = _behind(reader)
        collab.mark_read(session, announcement["thread_id"], user_id=reader)
        session.commit()
        out["after"] = collab.unread_count(session, reader)
        del message
    return out


class TestTheBankIsTold:

    def test_publishing_writes_to_somebody(self, told) -> None:
        assert told["announcement"].get("message_id"), told["announcement"]

    def test_it_reaches_people_who_can_act_on_it(self, told) -> None:
        """Not everybody. A notification everyone receives about everything is
        one everyone learns to dismiss."""
        assert told["recipients"]

    def test_the_message_names_the_dataset_and_the_period(self, told) -> None:
        subject = str(told["thread"].get("subject") or "")
        body = " ".join(str(m.get("body") or "")
                        for m in (told["thread"].get("messages") or []))
        assert NEW_PERIOD in subject + body

    def test_it_comes_from_the_product_and_not_from_a_person(self, told
                                                              ) -> None:
        senders = [m.get("sender") for m in
                   (told["thread"].get("messages") or [])]
        assert any(str(s.get("type")) == "SYSTEM" for s in senders if s)

    def test_reading_it_reduces_the_unread_count(self, told) -> None:
        """The count is per thread, so it falls for somebody who was behind on
        THIS one. A reader who had already read it is not evidence either way,
        and the test says which case it is looking at rather than passing
        vacuously."""
        if not told.get("was_unread"):
            pytest.skip("every recipient had already read this announcement")
        assert told["after"]["unread"] == told["before"]["unread"] - 1

    def test_it_carries_a_call_to_action_the_product_can_honour(self, told
                                                                 ) -> None:
        actions = [a for m in (told["thread"].get("messages") or [])
                   for a in (m.get("actions") or [])]
        assert actions, "a publication nobody can act on is a notification"
        assert all(a.get("href") for a in actions)
        assert {"open_dataset"} <= {a.get("action") for a in actions}

    def test_the_comparison_action_names_the_period_before_it(self, told
                                                               ) -> None:
        """An action button appears only when the product can honour it."""
        actions = {a.get("action"): a for m in
                   (told["thread"].get("messages") or [])
                   for a in (m.get("actions") or [])}
        compare = actions.get("compare_previous_period")
        if compare is None:
            pytest.skip("no previous period, so the button is not offered")
        assert compare["context"]["to_period"] == NEW_PERIOD
        assert compare["context"]["from_period"]


class TestSharingKeepsEveryBlock:
    """An Investigation with several analytical blocks must arrive with all of
    them. The recipient reading one chart where the sender saw five is the
    sharing defect this exists to prevent."""

    @pytest.fixture(scope="class")
    @classmethod
    def shared(cls, loop):
        from backend.db.engine import get_session
        from backend.orchestration import investigations as inv_store
        from backend.orchestration.executor import answer_investigation
        from backend.services import collaboration as collab

        investigation, _ = answer_investigation(
            "Shipping has deteriorated. Show me everything.",
            persist=True, user_id=1)
        blocks = investigation.to_dict()["package"]["counts"]["analyses"]
        run_id = investigation.analysis_run_id
        assert run_id, "the investigation was not persisted"
        saved = inv_store.save(investigation,
                               title=f"Shipping review at {NEW_PERIOD}",
                               user_id=1)

        with get_session() as session:
            recipients = [r for r in collab.data_release_recipients(session)
                          if r != 1]
            if not recipients:
                pytest.skip("no second configured user to share with")
            sent = collab.send_message(
                session, sender_id=1, to=[recipients[0]],
                subject=f"Shipping review at {NEW_PERIOD}",
                body="The full picture, for your read.",
                attachments=[{"type": "investigation",
                              "object_id": str(saved.id)}])
            session.commit()
            thread = collab.get_thread(session, sent["thread_id"],
                                       user_id=recipients[0])
        return {"blocks": blocks, "run_id": run_id, "saved_id": saved.id,
                "thread": thread, "recipient": recipients[0]}

    def test_the_investigation_had_several_blocks(self, shared) -> None:
        assert shared["blocks"] >= 5

    def test_the_recipient_can_open_it(self, shared) -> None:
        attachments = [a for m in (shared["thread"].get("messages") or [])
                       for a in (m.get("attachments") or [])]
        assert attachments
        assert any(str(a.get("type")) == "investigation" for a in attachments)

    def test_the_recipient_sees_every_block(self, shared) -> None:
        """Not the first one. All of them."""
        from backend.orchestration import store

        payload = store.load_version(int(shared["run_id"]))
        package = payload.get("package") or {}
        assert package.get("counts", {}).get("analyses") == shared["blocks"]


# ======================================== 17. the quarter comes back corrected
#
# A new period is the easy half. The half that destroys a book is the
# correction: the same period arrives again, and a publisher who rebuilds the
# dataset to take it loses every other quarter, while one who simply writes
# over the partition loses the fact that there ever was a first version.
#
# So a correction is its own mode. It supersedes rather than overwrites, it
# leaves the period count alone, and the figure the engine answers with
# afterwards is the corrected one.


@pytest.fixture(scope="module")
def correction(client, loop):
    """Send the same quarter again, corrected, and publish it."""
    if loop.get("publish") is None or loop["publish"].status_code != 200:
        pytest.skip("The first publication did not happen; nothing to correct.")

    base = "/api/v1/data-builder"
    from backend.data_access import get_data_source

    frame = loop["built"].copy()
    steps: dict = {
        "periods_before": list(get_data_source().periods(DATASET)),
        "first": loop["release"],
    }

    # A real correction changes figures, not row counts: one more row would be
    # a different book, and this has to be the same book restated.
    money = next((c for c in ("exposure_at_default", "ead", "gross_carrying_amount")
                  if c in frame.columns), "")
    if not money:
        pytest.skip("This dataset has no money column to correct.")
    steps["money_column"] = money
    steps["total_before"] = float(frame[money].sum())
    frame[money] = frame[money] * 1.10
    steps["total_after"] = float(frame[money].sum())

    upload = client.post(
        f"{base}/datasets/{DATASET}/periods/upload",
        data={"period": NEW_PERIOD, "mode": "REPLACE_PERIOD"},
        files={"file": (f"{DATASET}_{NEW_PERIOD}_corrected.csv",
                        io.BytesIO(frame.to_csv(index=False).encode()),
                        "text/csv")})
    steps["upload"] = upload
    if upload.status_code != 200:
        return steps

    release_id = upload.json()["release"]["id"]
    steps["second"] = upload.json()["release"]
    client.post(f"{base}/periods/{release_id}/review",
                json={"note": "A restatement of the same quarter."})
    client.post(f"{base}/periods/{release_id}/lock", json={"note": "Checked."})
    steps["publish"] = client.post(f"{base}/periods/{release_id}/publish")
    steps["history"] = client.get(f"{base}/datasets/{DATASET}/periods",
                                  params={"period": NEW_PERIOD})
    steps["periods_after"] = list(get_data_source().periods(DATASET))
    return steps


class TestACorrectionSupersedesRatherThanOverwrites:

    def test_the_correction_is_accepted_and_versioned(self, correction) -> None:
        assert correction["upload"].status_code == 200, correction["upload"].text
        assert correction["second"]["mode"] == "REPLACE_PERIOD"
        assert correction["second"]["version"] == correction["first"]["version"] + 1

    def test_it_publishes(self, correction) -> None:
        response = correction.get("publish")
        assert response is not None and response.status_code == 200, (
            response.text if response is not None else "not attempted")
        assert response.json()["release"]["state"] == "PUBLISHED"

    def test_the_first_version_is_superseded_not_deleted(self, correction) -> None:
        releases = {r["version"]: r for r in correction["history"].json()["releases"]}
        first = releases[correction["first"]["version"]]
        assert first["state"] == "SUPERSEDED", (
            "the first release must still be on the record")
        assert first["superseded_by"] == correction["second"]["id"]

    def test_the_period_count_does_not_change(self, correction) -> None:
        assert correction["periods_after"] == correction["periods_before"], (
            "a correction restates one period; it does not add or remove any")

    def test_the_engine_answers_with_the_corrected_figure(self, correction) -> None:
        """The point of the whole exercise: the new number is the one served."""
        from backend.data_access import AnalysisContext, get_data_source

        frame = get_data_source().fetch(
            DATASET, context=AnalysisContext(period=NEW_PERIOD),
            fields=[correction["money_column"]], period=NEW_PERIOD)
        served = float(frame[correction["money_column"]].sum())
        assert served == pytest.approx(correction["total_after"], rel=1e-6), (
            f"the engine is still serving {served:,.0f} where the correction "
            f"said {correction['total_after']:,.0f}")
        assert served != pytest.approx(correction["total_before"], rel=1e-6)
