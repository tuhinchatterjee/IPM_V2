"""
Ordinary Playbook use must not require the committee machinery. Chapter 05 of
the continuation brief, and chapters 11 and 13 of the specification.

The richer Document Intelligence work stays reachable through Know the Status.
What it must not be is a toll gate on writing a document.
"""

from __future__ import annotations

import pytest

from backend.playbook import chat, repository as repo

pytestmark = pytest.mark.usefixtures("db")

REPORT_MD = """# Scorecard Development Report

## 1. Executive summary

The scorecard performs within the thresholds the committee set, on the sample
supplied and over the window agreed in the methodology document.

## 2. Methodology

The target definition follows the ninety-day standard applied across the book,
with the observation and performance windows as documented in the source.
"""


def _governance_rows(db, workspace_id: int) -> dict[str, int]:
    """Every row the committee workflow would create, counted."""
    from backend.models.playbook import (
        PlaybookAction,
        PlaybookDecision,
        PlaybookFinding,
        PlaybookMetricBinding,
        PlaybookMetricSnapshot,
        PlaybookDocumentSection,
    )

    counts = {}
    for name, model in (("findings", PlaybookFinding),
                        ("decisions", PlaybookDecision),
                        ("actions", PlaybookAction),
                        ("metric_bindings", PlaybookMetricBinding)):
        counts[name] = (db.query(model)
                        .filter(model.workspace_id == workspace_id).count())
    artifacts = repo.artifacts(db, workspace_id)
    ids = [a.id for a in artifacts]
    counts["section_states"] = (
        db.query(PlaybookDocumentSection)
        .filter(PlaybookDocumentSection.artifact_id.in_(ids)).count() if ids else 0)
    counts["metric_snapshots"] = (
        db.query(PlaybookMetricSnapshot)
        .filter(PlaybookMetricSnapshot.artifact_id.in_(ids)).count()
        if ids else 0)
    return counts


class TestWritingADocumentNeedsNoGovernance:

    def test_a_question_creates_no_governance_of_any_kind(
            self, db, scope, workspace, scripted_author):
        scripted_author("", makes_document=False, chat_text="Here is the answer.")
        chat.turn(db, scope, workspace.id, text="What is the difference?")

        assert _governance_rows(db, workspace.id) == {
            "findings": 0, "decisions": 0, "actions": 0,
            "metric_bindings": 0, "section_states": 0, "metric_snapshots": 0}

    def test_a_whole_document_is_written_without_binding_a_metric(
            self, db, scope, workspace, scripted_author):
        """The file exists, is downloadable, and nobody confirmed a metric."""
        scripted_author(REPORT_MD, chat_text="Drafted.",
                        chat_formats=["docx", "pdf"])
        turn = chat.turn(db, scope, workspace.id,
                         text="Write the development report in Word and PDF.")

        [produced] = turn["produced"]
        assert sorted(produced["delivered"]) == ["docx", "pdf"]

        counts = _governance_rows(db, workspace.id)
        assert counts["metric_bindings"] == 0, (
            "no metric had to be bound to write a document")
        assert counts["findings"] == 0
        assert counts["decisions"] == 0
        assert counts["section_states"] == 0, (
            "and no section had to be signed off")

    def test_the_progress_panel_answers_without_any_of_it(
            self, db, scope, workspace, scripted_author):
        from backend.playbook import progress

        scripted_author(REPORT_MD, chat_text="Drafted.", chat_formats=["docx"])
        chat.turn(db, scope, workspace.id, text="Write it.")

        got = progress.of(db, workspace.id)
        assert got.available is True
        assert got.content.percent == 100
        assert got.review["state"] == "draft"


class TestTheRicherDashboardIsStillThere:

    def test_know_the_status_still_answers_for_a_chat_written_document(
            self, db, scope, workspace, scripted_author):
        """Optional does not mean removed.

        The Document Intelligence dashboard must still be reachable for a
        document that was written through ordinary conversation — it is simply
        not a prerequisite for having written it.
        """
        from backend.playbook.intelligence import service as intel

        scripted_author(REPORT_MD, chat_text="Drafted.", chat_formats=["docx"])
        turn = chat.turn(db, scope, workspace.id, text="Write it.")
        from backend.playbook import service

        assert service.project_status(
            lambda: _Same(db), turn["projections"][0])["ok"] is True

        state = intel.dashboard(db, workspace.id).as_dict()
        assert state["available"] is True, (
            "Know the Status opens for a document nobody governed")
        assert state["sections"], "and describes the sections it actually has"


class _Same:
    """A session factory handing back the test's own session."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *_exc):
        return False
