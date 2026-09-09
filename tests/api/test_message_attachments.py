"""What a message carries, and who is allowed to open it.

Two kinds of attachment, authorized two different ways
-------------------------------------------------------
A **governed object** — an investigation, an analysis — is not copied into the
message. Sending it writes an `object_shares` grant and a snapshot of what the
object looked like at the time. The sender must already be able to read it: you
cannot share your way into giving away something you were never shown.

A **file** is bytes this database holds. Downloading one is checked against
participation in a thread the file hangs off, per request, so losing access to
the conversation loses access to its attachments — and the bytes that come back
are the bytes that went in, which is the whole point of storing them here rather
than in a temporary directory that a restart empties.
"""

from __future__ import annotations

import hashlib
import io
import uuid
import zipfile

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("Attachments need a database.")


@pytest.fixture(scope="module")
def people():
    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    made = []
    with get_session() as session:
        for first in ("Owner", "Reader", "Stranger"):
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


@pytest.fixture
def owned_investigation(session, people):
    """An investigation with a real owner, so the read check has teeth."""
    from backend.models.platform import Investigation

    owner, _, _ = people
    row = Investigation(title=f"Shipping deterioration {uuid.uuid4().hex[:6]}",
                        question="Which shipping borrowers deteriorated?",
                        owner_id=owner, status="live",
                        context={"to_period": "Q2 2026",
                                 "domain": "corporate_credit"})
    session.add(row)
    session.flush()
    return row.id


def _workbook() -> bytes:
    """A genuine OOXML package, so a byte-for-byte claim means something."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("xl/worksheets/sheet1.xml", "<worksheet><sheetData/></worksheet>")
    return buf.getvalue()


class TestSharingAnInvestigation:

    def test_the_card_carries_the_metadata_it_had_at_the_time(
            self, session, people, owned_investigation):
        from backend.services import collaboration as collab

        owner, reader, _ = people
        sent = collab.send_message(
            session, sender_id=owner, to=[reader], subject="Please review",
            body="Attached.",
            attachments=[{"type": "investigation",
                          "object_id": str(owned_investigation)}])
        thread = collab.get_thread(session, sent["thread_id"], user_id=reader)
        card = thread["messages"][0]["attachments"][0]
        assert card["type"] == "investigation"
        assert card["object_id"] == str(owned_investigation)
        assert card["meta"]["period"] == "Q2 2026"
        assert card["meta"]["owner"] == "Owner Test"
        assert card["object_version"]

    def test_the_recipient_can_now_read_the_object(
            self, session, people, owned_investigation):
        from backend.services import collaboration as collab

        owner, reader, stranger = people
        assert not collab.can_read_object(session, "investigation",
                                          str(owned_investigation), reader)
        collab.send_message(
            session, sender_id=owner, to=[reader], subject="Please review",
            body="x", attachments=[{"type": "investigation",
                                    "object_id": str(owned_investigation)}])
        assert collab.can_read_object(session, "investigation",
                                      str(owned_investigation), reader)
        # And nobody else did.
        assert not collab.can_read_object(session, "investigation",
                                          str(owned_investigation), stranger)

    def test_a_sender_cannot_share_what_they_cannot_read(
            self, session, people, owned_investigation):
        from backend.services import collaboration as collab

        owner, reader, stranger = people
        with pytest.raises(collab.NotPermitted):
            collab.send_message(
                session, sender_id=stranger, to=[reader], subject="Not mine",
                body="x", attachments=[{"type": "investigation",
                                        "object_id": str(owned_investigation)}])

    def test_the_refusal_happens_before_anything_is_sent(
            self, session, people, owned_investigation):
        # A half-sent message — delivered, but granting nothing — is the state
        # the single transaction exists to make unreachable.
        from backend.services import collaboration as collab

        owner, reader, stranger = people
        before = collab.list_box(session, user_id=reader,
                                 box=collab.BOX_INBOX)["total"]
        with pytest.raises(collab.NotPermitted):
            collab.send_message(
                session, sender_id=stranger, to=[reader], subject="Not mine",
                body="x", attachments=[{"type": "investigation",
                                        "object_id": str(owned_investigation)}])
        session.rollback()
        assert collab.list_box(session, user_id=reader,
                               box=collab.BOX_INBOX)["total"] == before

    def test_an_absent_investigation_is_refused(self, session, people):
        from backend.services import collaboration as collab

        owner, reader, _ = people
        with pytest.raises(collab.NotFound):
            collab.send_message(session, sender_id=owner, to=[reader],
                                subject="Ghost", body="x",
                                attachments=[{"type": "investigation",
                                              "object_id": "99999999"}])

    def test_it_appears_under_shared_with_me(self, session, people,
                                             owned_investigation):
        from backend.services import collaboration as collab

        owner, reader, _ = people
        collab.send_message(session, sender_id=owner, to=[reader],
                            subject="Review", body="x",
                            attachments=[{"type": "investigation",
                                          "object_id": str(owned_investigation)}])
        items = collab.shared_with_me(session, reader)
        assert any(i["object_id"] == str(owned_investigation)
                   and i["shared_by"] == "Owner Test" for i in items)


class TestSharingAnAnalysis:

    @pytest.fixture
    def analysis(self, session):
        from backend.models.platform import SavedAnalysis

        row = SavedAnalysis(title=f"Top deteriorating {uuid.uuid4().hex[:6]}",
                            analysis_id="top_deteriorating_borrowers",
                            analysis_version="1.0.0", certification="certified",
                            period={"period": "Q2 2026"},
                            filters={"sector": "Shipping"})
        session.add(row)
        session.flush()
        return row.id

    def test_the_card_names_the_analysis_and_its_period(self, session, people,
                                                        analysis):
        from backend.services import collaboration as collab

        owner, reader, _ = people
        sent = collab.send_message(
            session, sender_id=owner, to=[reader], subject="Numbers",
            body="x", attachments=[{"type": "analysis",
                                    "object_id": str(analysis)}])
        card = collab.get_thread(session, sent["thread_id"], user_id=reader)[
            "messages"][0]["attachments"][0]
        assert card["type"] == "analysis"
        assert card["meta"]["analysis_id"] == "top_deteriorating_borrowers"
        assert card["meta"]["period"] == "Q2 2026"
        assert card["meta"]["certification"] == "certified"
        assert card["object_version"] == "1.0.0"

    def test_the_version_at_share_time_is_recorded(self, session, people,
                                                   analysis):
        # A decision recorded against version 1.0.0 must not silently become a
        # decision about 2.0.0 because the analysis moved on.
        from backend.models.platform import SavedAnalysis
        from backend.services import collaboration as collab

        owner, reader, _ = people
        sent = collab.send_message(
            session, sender_id=owner, to=[reader], subject="Numbers", body="x",
            attachments=[{"type": "analysis", "object_id": str(analysis)}])
        session.get(SavedAnalysis, analysis).analysis_version = "2.0.0"
        session.flush()
        card = collab.get_thread(session, sent["thread_id"], user_id=reader)[
            "messages"][0]["attachments"][0]
        assert card["object_version"] == "1.0.0"


class TestSharingAFile:

    def test_the_bytes_come_back_exactly(self, session, people):
        from backend.services import collaboration as collab

        owner, reader, _ = people
        content = _workbook()
        artifact = collab.store_artifact(
            session, filename="Shipping_Q2_2026.xlsx", content=content,
            created_by=owner)
        collab.send_message(session, sender_id=owner, to=[reader],
                            subject="Workbook", body="x",
                            attachments=[{"type": "file",
                                          "artifact_id": artifact.id}])
        _, back = collab.download_artifact(session, artifact.id,
                                           user_id=reader)
        assert back == content
        assert hashlib.sha256(back).hexdigest() == artifact.sha256

    def test_a_stranger_cannot_download_it(self, session, people):
        from backend.services import collaboration as collab

        owner, reader, stranger = people
        artifact = collab.store_artifact(session, filename="x.xlsx",
                                         content=_workbook(), created_by=owner)
        collab.send_message(session, sender_id=owner, to=[reader],
                            subject="Workbook", body="x",
                            attachments=[{"type": "file",
                                          "artifact_id": artifact.id}])
        with pytest.raises(collab.NotFound):
            collab.download_artifact(session, artifact.id, user_id=stranger)

    def test_the_refusal_looks_like_absence(self, session, people):
        # NotFound, not NotPermitted. "You may not have artifact 91" tells a
        # prober that artifact 91 is real.
        from backend.services import collaboration as collab

        _, _, stranger = people
        with pytest.raises(collab.NotFound):
            collab.download_artifact(session, 99999999, user_id=stranger)

    def test_the_creator_can_always_fetch_their_own_upload(self, session,
                                                           people):
        from backend.services import collaboration as collab

        owner, _, _ = people
        artifact = collab.store_artifact(session, filename="mine.csv",
                                         content=b"a,b\n1,2\n", created_by=owner)
        _, back = collab.download_artifact(session, artifact.id, user_id=owner)
        assert back == b"a,b\n1,2\n"

    def test_only_whitelisted_formats(self, session, people):
        from backend.services import collaboration as collab

        owner, _, _ = people
        for name in ("payload.exe", "run.sh", "lib.dll", "macro.xlsm",
                     "noextension"):
            with pytest.raises(collab.InvalidRequest):
                collab.store_artifact(session, filename=name, content=b"x",
                                      created_by=owner)

    def test_the_whitelist_admits_what_a_risk_team_actually_sends(
            self, session, people):
        from backend.services import collaboration as collab

        owner, _, _ = people
        for name in ("book.xlsx", "extract.csv", "opinion.pdf", "memo.docx"):
            row = collab.store_artifact(session, filename=name, content=b"x",
                                        created_by=owner)
            assert row.size_bytes == 1

    def test_an_empty_file_is_refused(self, session, people):
        from backend.services import collaboration as collab

        owner, _, _ = people
        with pytest.raises(collab.InvalidRequest):
            collab.store_artifact(session, filename="empty.csv", content=b"",
                                  created_by=owner)

    def test_an_oversized_file_is_refused(self, session, people):
        from backend.services import collaboration as collab

        owner, _, _ = people
        with pytest.raises(collab.InvalidRequest):
            collab.store_artifact(session, filename="huge.csv",
                                  content=b"x" * (collab.MAX_FILE_BYTES + 1),
                                  created_by=owner)

    def test_a_path_in_the_filename_is_stripped(self, session, people):
        from backend.services import collaboration as collab

        owner, _, _ = people
        row = collab.store_artifact(session, filename="../../etc/passwd.csv",
                                    content=b"x", created_by=owner)
        assert row.filename == "passwd.csv"

    def test_somebody_elses_upload_cannot_be_attached(self, session, people):
        # Guessing an artifact id would otherwise be a way to pull a file out
        # of a thread you are not in and into one you are.
        from backend.services import collaboration as collab

        owner, reader, stranger = people
        artifact = collab.store_artifact(session, filename="theirs.xlsx",
                                         content=_workbook(), created_by=owner)
        with pytest.raises(collab.NotPermitted):
            collab.send_message(session, sender_id=stranger, to=[reader],
                                subject="Not mine", body="x",
                                attachments=[{"type": "file",
                                              "artifact_id": artifact.id}])


class TestSeveralThingsAtOnce:

    def test_one_message_carries_all_three(self, session, people,
                                           owned_investigation):
        from backend.models.platform import SavedAnalysis
        from backend.services import collaboration as collab

        owner, reader, _ = people
        analysis = SavedAnalysis(title="Shipping PD increase",
                                 analysis_id="pd_increase",
                                 analysis_version="1.0.0",
                                 period={"period": "Q2 2026"})
        session.add(analysis)
        session.flush()
        artifact = collab.store_artifact(session, filename="Shipping.xlsx",
                                         content=_workbook(), created_by=owner)
        sent = collab.send_message(
            session, sender_id=owner, to=[reader],
            subject="Shipping deterioration — please review",
            body="Please review before tomorrow's portfolio review.",
            request_type="review",
            attachments=[
                {"type": "investigation", "object_id": str(owned_investigation)},
                {"type": "analysis", "object_id": str(analysis.id)},
                {"type": "file", "artifact_id": artifact.id},
            ])
        cards = collab.get_thread(session, sent["thread_id"],
                                  user_id=reader)["messages"][0]["attachments"]
        assert [c["type"] for c in cards] == ["investigation", "analysis",
                                              "file"]
        assert cards[2]["file"]["filename"] == "Shipping.xlsx"

    def test_the_inbox_row_says_what_is_attached_without_loading_it(
            self, session, people, owned_investigation):
        from backend.services import collaboration as collab

        owner, reader, _ = people
        artifact = collab.store_artifact(session, filename="a.xlsx",
                                         content=_workbook(), created_by=owner)
        sent = collab.send_message(
            session, sender_id=owner, to=[reader], subject="Mixed", body="x",
            attachments=[
                {"type": "investigation", "object_id": str(owned_investigation)},
                {"type": "file", "artifact_id": artifact.id}])
        row = next(i for i in collab.list_box(
            session, user_id=reader, box=collab.BOX_INBOX)["items"]
            if i["thread_id"] == sent["thread_id"])
        assert row["attachment_count"] == 2
        assert row["attachment_types"] == ["file", "investigation"]
        # The summary carries no bytes and no object payloads.
        assert "attachments" not in row

    def test_the_inbox_can_be_filtered_by_attachment_kind(
            self, session, people, owned_investigation):
        from backend.services import collaboration as collab

        owner, reader, _ = people
        plain = collab.send_message(session, sender_id=owner, to=[reader],
                                    subject="No attachments", body="x")
        with_inv = collab.send_message(
            session, sender_id=owner, to=[reader], subject="With one", body="x",
            attachments=[{"type": "investigation",
                          "object_id": str(owned_investigation)}])
        found = collab.list_box(session, user_id=reader,
                                box=collab.BOX_INBOX,
                                attachment_type="investigation")
        ids = {i["thread_id"] for i in found["items"]}
        assert with_inv["thread_id"] in ids
        assert plain["thread_id"] not in ids


class TestDownloadsAreAudited:

    def test_a_download_writes_a_row_with_the_hash(self, session, people):
        from sqlalchemy import select

        from backend.models.collaboration import CollaborationAudit
        from backend.services import collaboration as collab

        owner, reader, _ = people
        artifact = collab.store_artifact(session, filename="audited.xlsx",
                                         content=_workbook(), created_by=owner)
        collab.send_message(session, sender_id=owner, to=[reader],
                            subject="Audited", body="x",
                            attachments=[{"type": "file",
                                          "artifact_id": artifact.id}])
        collab.download_artifact(session, artifact.id, user_id=reader)
        rows = session.execute(
            select(CollaborationAudit).where(
                CollaborationAudit.action == collab.FILE_DOWNLOADED,
                CollaborationAudit.object_id == str(artifact.id))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_id == reader
        assert rows[0].detail["sha256"] == artifact.sha256

    def test_sharing_writes_its_own_row(self, session, people,
                                        owned_investigation):
        from sqlalchemy import select

        from backend.models.collaboration import CollaborationAudit
        from backend.services import collaboration as collab

        owner, reader, _ = people
        collab.send_message(session, sender_id=owner, to=[reader],
                            subject="Shared", body="x",
                            attachments=[{"type": "investigation",
                                          "object_id": str(owned_investigation)}])
        rows = session.execute(
            select(CollaborationAudit).where(
                CollaborationAudit.action == collab.OBJECT_SHARED,
                CollaborationAudit.object_id == str(owned_investigation))
        ).scalars().all()
        assert any(r.subject_user_id == reader for r in rows)
