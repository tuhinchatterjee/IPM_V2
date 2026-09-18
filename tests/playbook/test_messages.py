"""Sending a message, and not sending it twice. PB-024, PB-038, PB-039.

The failures these cover are the ones a user actually causes: pressing send
twice, refreshing mid-generation, and a generation that fails after the question
was already asked.
"""

from __future__ import annotations

import pytest

from backend.playbook import provider, service
from backend.playbook import repository as repo

REPORT_MD = """# Committee report

## 1. Executive summary

Weighted ECL was SAR 22.77 million.
"""


@pytest.fixture
def ledger_calcs():
    from backend.playbook.fixtures import ecl_oracle as oracle

    return list(oracle.headline().values())


class TestOneTurn:
    def test_the_question_and_the_answer_are_both_persisted(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author(REPORT_MD)
        result = service.send_message(db, scope, workspace.id,
                                      text="Write the report.",
                                      calculations=ledger_calcs)
        assert result["state"] == "ready"
        messages = repo.messages(db, workspace.id)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content["text"] == "Write the report."
        assert messages[1].content["version"] == 1

    def test_the_assistant_turn_is_marked_as_live_not_as_a_fixture(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author(REPORT_MD)
        service.send_message(db, scope, workspace.id, text="Write it.",
                             calculations=ledger_calcs)
        assistant = repo.messages(db, workspace.id)[1]
        assert assistant.origin == "assistant_live"
        assert assistant.model == "scripted-author"

    def test_the_thread_shows_the_answer_and_a_record_of_each_file(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        """What the assistant said, plus what it produced.

        This once asserted that the assistant's message carried the DOCUMENT
        as Markdown, because the document was the only thing a turn could
        produce. A conversation puts the assistant's own words in the thread
        and the document in a file card beside it — chapter 03 — so the
        message is checked for the answer, and the files for the files.
        """
        scripted_author(REPORT_MD, chat_text="I have drafted the report.")
        result = service.send_message(db, scope, workspace.id, text="Write it.",
                                      calculations=ledger_calcs)
        assistant = repo.messages(db, workspace.id)[1]

        said = assistant.content["text"]
        assert "I have drafted the report." in said, (
            "the thread carries what the assistant said, not the document")
        assert "22.77" not in said, (
            "and not the document's own prose, which lives in the file")
        assert assistant.content["interrupted"] is False
        [record] = assistant.content["files"]
        assert record["version"] == 1
        assert sorted(record["delivered"]) == ["docx", "pdf"]
        assert record["failed"] == {}

        # And the document itself is where a document belongs.
        versions = repo.versions(db, result["artifact_id"])
        assert [v.version for v in versions] == [1]
        assert sorted(f.format for f in repo.files(db, versions[0].id)) == [
            "docx", "pdf"]

    def test_evidence_gaps_travel_with_the_answer(
            self, db, scope, workspace, scripted_author, ledger_calcs,
            results_workbook_xlsx):
        source = service.add_source(db, scope, workspace.id,
                                    filename="results.xlsx",
                                    content=results_workbook_xlsx,
                                    source_role="results")
        scripted_author(REPORT_MD)
        service.send_message(db, scope, workspace.id, text="Write it.",
                             source_ids=[source.id], calculations=ledger_calcs)
        assistant = repo.messages(db, workspace.id)[1]
        assert assistant.content["evidence_complete"] is False
        assert any("Working" in g["what"]
                   for g in assistant.content["evidence_gaps"])


class TestSendingTwiceDoesNotGenerateTwice:
    def test_the_same_idempotency_key_returns_the_existing_job(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author(REPORT_MD)
        first = service.send_message(db, scope, workspace.id, text="Write it.",
                                     idempotency_key="press-once",
                                     calculations=ledger_calcs)
        second = service.send_message(db, scope, workspace.id, text="Write it.",
                                      idempotency_key="press-once",
                                      calculations=ledger_calcs)
        assert second["duplicate"] is True
        assert second["job_id"] == first["job_id"]

    def test_a_duplicate_send_creates_no_second_version(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author(REPORT_MD)
        service.send_message(db, scope, workspace.id, text="Write it.",
                             idempotency_key="once", calculations=ledger_calcs)
        service.send_message(db, scope, workspace.id, text="Write it.",
                             idempotency_key="once", calculations=ledger_calcs)
        artifacts = repo.artifacts(db, workspace.id)
        assert len(artifacts) == 1
        assert len(repo.versions(db, artifacts[0].id)) == 1

    def test_a_duplicate_send_adds_no_second_question(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author(REPORT_MD)
        for _ in range(2):
            service.send_message(db, scope, workspace.id, text="Write it.",
                                 idempotency_key="once",
                                 calculations=ledger_calcs)
        assert len(repo.messages(db, workspace.id)) == 2


class TestFailureLeavesAUsableThread:
    """A document that cannot be made no longer costs the user the turn.

    These once asserted that an empty authoring result raised out of
    `send_message` and left a system row saying so, because a turn WAS a
    document: if the document failed, there was nothing else to deliver.

    A conversation has something else to deliver. Chapter 07 makes the answer
    and the file independent outcomes, so an authoring call that comes back
    with nothing is reported to the assistant, which tells the user — and the
    thread keeps the question, the explanation, and no invented success.
    """

    def test_a_document_that_could_not_be_made_is_explained_not_erased(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author("", chat_text="I could not produce that document.")
        result = service.send_message(db, scope, workspace.id, text="Write it.",
                                      calculations=ledger_calcs)

        messages = repo.messages(db, workspace.id)
        assert messages[0].content["text"] == "Write it.", "the question stays"
        assert "I could not produce that document." in messages[1].content["text"]
        assert messages[1].origin == "assistant_live"

        # Nothing was invented: no file, no version, no claim of success.
        assert result["files"] == []
        assert repo.artifacts(db, workspace.id) == []
        [tool] = messages[1].content["tools"]
        assert tool["name"] == "create_document"
        assert tool["ok"] is False
        assert "no document" in tool["detail"].lower()

    def test_the_runtime_failing_is_still_a_failed_turn(
            self, db, scope, workspace, scripted_author, ledger_calcs,
            monkeypatch):
        """The distinction the change turns on.

        A document that could not be written is a tool failure the
        conversation survives. The RUNTIME being unavailable is not: there is
        no assistant left to explain anything, and pretending otherwise would
        spend another call to say so.
        """
        scripted_author(REPORT_MD)

        def unavailable(*_a, **_kw):
            raise provider.ProviderNotConfigured("no model configured")

        monkeypatch.setattr(provider, "author", unavailable)
        monkeypatch.setattr("backend.playbook.service.provider.author",
                            unavailable)
        with pytest.raises(provider.ProviderNotConfigured):
            service.send_message(db, scope, workspace.id, text="Write it.",
                                 calculations=ledger_calcs)

        messages = repo.messages(db, workspace.id)
        assert messages[0].content["text"] == "Write it.", "the question stays"
        assert messages[1].content["failed"] is True
        assert messages[1].origin == "system", (
            "a runtime failure is not attributed to the assistant")

    def test_cancelling_saves_nothing_and_says_so(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author(REPORT_MD)
        with pytest.raises(provider.Cancelled):
            service.send_message(db, scope, workspace.id, text="Write it.",
                                 calculations=ledger_calcs,
                                 is_cancelled=lambda: True)
        assert repo.artifacts(db, workspace.id) == []
        assert "stopped" in repo.messages(db, workspace.id)[1].content["text"]


class TestAttachmentsAreCheckedServerSide:
    def test_a_foreign_export_revision_cannot_be_attached_to_a_message(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        from backend.exports import playbook_contract as pc
        from backend.playbook import library

        other = repo.Scope(tenant="another-bank")
        snapshot = pc.Snapshot(
            source_module=pc.COCKPIT, title="Their analysis",
            narrative="A long enough narrative to count as a completed "
                      "analysis for the purposes of this test, easily.",
            source_ref={"run_id": 5})
        theirs = library.create(db, other, snapshot)

        scripted_author(REPORT_MD)
        with pytest.raises(repo.NotFound):
            service.send_message(db, scope, workspace.id, text="Write it.",
                                 export_revision_ids=[theirs.revision_id],
                                 calculations=ledger_calcs)


class TestStoppingAGeneration:
    """PB-038. A stop that leaves nothing half-written."""

    def _job(self, db, scope, workspace, state="drafting"):
        from backend.models.playbook import PlaybookJob

        job = PlaybookJob(workspace_id=workspace.id, tenant=scope.tenant,
                          idempotency_key=f"ws{workspace.id}:stop-test",
                          state=state)
        db.add(job)
        db.flush()
        return job

    def test_a_running_generation_can_be_asked_to_stop(
            self, db, scope, workspace):
        job = self._job(db, scope, workspace)
        result = service.request_cancel(db, scope, job.id)

        assert result["cancelled"] is True
        assert "Nothing will be saved" in result["message"]
        assert job.cancelled is True

    def test_stopping_something_that_finished_undoes_nothing(
            self, db, scope, workspace):
        from backend.playbook.service import _now

        job = self._job(db, scope, workspace, state="ready")
        job.finished_at = _now()
        db.flush()

        result = service.request_cancel(db, scope, job.id)
        assert result["cancelled"] is False
        assert result["state"] == "ready"
        assert "already finished" in result["message"]

    def test_another_tenants_generation_cannot_be_stopped(
            self, db, scope, workspace):
        job = self._job(db, scope, workspace)
        other = repo.Scope(tenant="somebody-else", user_id=None)
        with pytest.raises(repo.NotFound):
            service.request_cancel(db, other, job.id)
        assert job.cancelled is False

    def test_the_status_reports_milestones_and_no_percentage(
            self, db, scope, workspace):
        job = self._job(db, scope, workspace)
        job.milestones = [{"state": "reviewing_sources", "detail": "3 sources"},
                          {"state": "drafting", "detail": ""}]
        db.flush()

        status = service.job_status(db, scope, job.id)
        assert status["state"] == "drafting"
        assert [m["state"] for m in status["milestones"]] == [
            "reviewing_sources", "drafting"]
        assert "percent" not in status and "progress" not in status

    def test_a_cancelled_run_writes_no_version_and_keeps_the_last_good_one(
            self, db, scope, workspace, ledger_calcs, scripted_author):
        from backend.playbook import evidence as ev

        ledger = ev.Ledger()
        ev.add_calculations(ledger, ledger_calcs)

        scripted_author("# Report\n\n## 1. Summary\n\nThe good version.\n")
        good = service.author_document(
            db, scope, workspace.id, instruction="Draft it.",
            ledger=ledger, title="Report")

        scripted_author("# Report\n\n## 1. Summary\n\nA revision.\n")
        with pytest.raises(provider.Cancelled):
            service.author_document(
                db, scope, workspace.id, instruction="Revise it.",
                ledger=ledger, title="Report", artifact_id=good.artifact_id,
                base_version_id=good.version_id,
                is_cancelled=lambda: True)

        from backend.models.playbook import PlaybookArtifact
        artifact = db.get(PlaybookArtifact, good.artifact_id)
        assert artifact.current_version_id == good.version_id
