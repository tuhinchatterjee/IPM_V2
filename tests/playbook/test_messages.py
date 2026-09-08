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

    def test_the_thread_shows_the_document_that_was_saved(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        """Not the model's first draft — what survived grounding."""
        scripted_author(REPORT_MD.replace(
            "Weighted ECL was SAR 22.77 million.",
            "Weighted ECL was SAR 22.77 million. Coverage hit 41.5 per cent."))
        service.send_message(db, scope, workspace.id, text="Write it.",
                             calculations=ledger_calcs)
        assistant = repo.messages(db, workspace.id)[1]
        assert "41.5" not in assistant.content["markdown"]
        assert "22.77" in assistant.content["markdown"]
        assert assistant.content["grounding"]["ok"] is False

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
    def test_a_failed_generation_keeps_the_question_and_says_what_happened(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author("")
        with pytest.raises(provider.AuthoringError):
            service.send_message(db, scope, workspace.id, text="Write it.",
                                 calculations=ledger_calcs)
        messages = repo.messages(db, workspace.id)
        assert messages[0].content["text"] == "Write it."
        assert messages[1].content["failed"] is True
        assert messages[1].origin == "system"

    def test_a_failed_generation_is_not_attributed_to_the_model(
            self, db, scope, workspace, scripted_author, ledger_calcs):
        scripted_author("")
        with pytest.raises(provider.AuthoringError):
            service.send_message(db, scope, workspace.id, text="Write it.",
                                 calculations=ledger_calcs)
        assert repo.messages(db, workspace.id)[1].origin == "system"

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
