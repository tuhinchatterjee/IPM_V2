"""
The simple progress panel. Chapter 12.

The whole point of these is that the four numbers move independently. A PDF
that failed must not drag eight finished sections to zero, and a full set of
files must not imply anybody has read them.
"""

from __future__ import annotations

import pytest

from backend.playbook import document as D
from backend.playbook import progress, review
from backend.playbook import repository as repo

BODY = ("The development sample covers originations in the period, with "
        "exclusions listed in the appendix and the observation window running "
        "to twelve months from origination. Performance is measured on the "
        "definition agreed with the risk committee. " * 2)


def _doc(*sections) -> D.Document:
    parts = ["# Report", ""]
    for heading, body in sections:
        parts += [f"## {heading}", "", body, ""]
    return D.parse("\n".join(parts), title="Report")


def _artifact_with(db, workspace, doc, *, formats=("docx",), validation=None):
    artifact = repo.create_artifact(db, workspace.id, kind="report",
                                    title="Report")
    version = repo.new_version(
        db, artifact, content=doc.as_dict(), source_manifest={},
        content_hash="h1", change_summary="v1",
        validation=validation or {"review": review.initial()})
    from backend.playbook import store

    for fmt in formats:
        stored = store.put_artifact(workspace.id, artifact.id, version.version,
                                    f"report-v1.{fmt}", b"PK\x03\x04 bytes" * 40)
        repo.add_file(db, version, fmt=fmt, bytes_path=stored.relative,
                      mime="application/octet-stream",
                      filename=f"report-v1.{fmt}",
                      size_bytes=stored.size_bytes, sha256=stored.sha256,
                      renderer="local", validated=True)
    db.flush()
    return artifact, version


@pytest.mark.usefixtures("db")
class TestNothingToCount:

    def test_a_workspace_with_no_document_says_so(self, db, workspace):
        got = progress.of(db, workspace.id)
        assert got.available is False
        assert "No document deliverable" in got.reason

    def test_it_is_not_reported_as_zero_or_a_hundred(self, db, workspace):
        payload = progress.of(db, workspace.id).as_dict()
        assert payload["overall"]["percent"] is None
        assert payload["overall"]["label"] == "Not applicable"


@pytest.mark.usefixtures("db")
class TestCountingWhatWasWritten:

    def test_each_section_is_an_item_and_a_full_one_counts(self, db, workspace):
        doc = _doc(("1. Scope", BODY), ("2. Data", BODY))
        _artifact_with(db, workspace, doc)
        got = progress.of(db, workspace.id)

        content = [i for i in got.items if i.kind == "content"]
        assert [i.label for i in content] == ["1. Scope", "2. Data"]
        assert got.content.delivered == 2 and got.content.total == 2
        assert got.content.percent == 100

    def test_a_section_that_only_reports_missing_evidence_is_not_complete(
            self, db, workspace):
        """Chapter 12's example, verbatim in intent."""
        doc = _doc(("1. Scope", BODY),
                   ("2. Out-of-time results",
                    "The requested OOT testing evidence is missing."))
        _artifact_with(db, workspace, doc)
        got = progress.of(db, workspace.id)

        gap = [i for i in got.items if i.label.startswith("2.")][0]
        assert gap.state == progress.NEEDS_INPUT
        assert gap.delivered is False
        assert "evidence is missing" in gap.detail
        assert got.content.delivered == 1 and got.content.total == 2

    def test_an_empty_section_has_not_started(self, db, workspace):
        doc = _doc(("1. Scope", BODY), ("2. Calibration", ""))
        _artifact_with(db, workspace, doc)
        got = progress.of(db, workspace.id)
        stub = [i for i in got.items if i.label.startswith("2.")][0]
        assert stub.state == progress.NOT_STARTED

    def test_the_fraction_shows_its_working(self, db, workspace):
        doc = _doc(("1. Scope", BODY), ("2. Data", BODY))
        _artifact_with(db, workspace, doc, formats=("docx", "pdf"))
        payload = progress.of(db, workspace.id).as_dict()

        assert payload["overall"]["label"] == "4 / 4"
        assert payload["overall"]["percent"] == 100
        assert payload["content"]["label"] == "2 / 2"
        assert payload["deliverables"]["label"] == "2 / 2"


@pytest.mark.usefixtures("db")
class TestTheFourNumbersMoveApart:
    """The requirement this module exists for."""

    def test_a_failed_pdf_does_not_reduce_finished_content(self, db, workspace):
        doc = _doc(("1. Scope", BODY), ("2. Data", BODY),
                   ("3. Performance", BODY), ("4. Calibration", BODY))
        # Word made it; PDF was attempted and did not.
        _artifact_with(db, workspace, doc, formats=("docx",),
                       validation={"review": review.initial(),
                                   "docx": {"ok": True},
                                   "pdf": {"ok": False,
                                           "issues": ["could not be reopened"]}})
        got = progress.of(db, workspace.id)

        assert got.content.delivered == 4, "content is untouched by a file failure"
        assert got.content.percent == 100
        assert got.deliverables.delivered == 1
        assert got.deliverables.total == 2
        assert got.overall.as_dict()["label"] == "5 / 6"
        assert got.overall.percent == 83

    def test_the_failed_format_is_still_named_rather_than_vanishing(
            self, db, workspace):
        doc = _doc(("1. Scope", BODY))
        _artifact_with(db, workspace, doc, formats=("docx",),
                       validation={"review": review.initial(),
                                   "pdf": {"ok": False}})
        got = progress.of(db, workspace.id)

        pdf = [i for i in got.items if i.label == "PDF"][0]
        assert pdf.delivered is False
        assert pdf.detail == "could not be produced"
        assert got.files["pdf"]["present"] is False
        assert got.files["docx"]["present"] is True

    def test_complete_files_do_not_imply_a_human_read_them(self, db, workspace):
        doc = _doc(("1. Scope", BODY))
        _artifact_with(db, workspace, doc, formats=("docx", "pdf"))
        got = progress.of(db, workspace.id)

        assert got.deliverables.percent == 100
        assert got.review["state"] == review.DRAFT
        assert got.review["label"] == "Draft"
        assert got.review["by"] == ""

    def test_review_moves_without_touching_the_counts(self, db, workspace):
        doc = _doc(("1. Scope", BODY))
        _artifact, version = _artifact_with(db, workspace, doc)
        before = progress.of(db, workspace.id)

        review.advance(version, to=review.REVIEWED, actor="user:7")
        db.flush()
        after = progress.of(db, workspace.id)

        assert after.content.as_dict() == before.content.as_dict()
        assert after.review["state"] == review.REVIEWED
        assert after.review["by"] == "user:7"

    def test_open_review_items_are_shown_beside_the_state(self, db, workspace):
        doc = _doc(("1. Scope", BODY))
        _artifact_with(db, workspace, doc, validation={
            "review": review.initial(
                [{"kind": "unsupported_figure", "figures": ["41.5"]},
                 {"kind": "unsupported_figure", "figures": ["88.3"]}])})
        got = progress.of(db, workspace.id)

        assert got.review["open_items"] == 2
        assert got.review["summary"] == "Draft — 2 review items"


@pytest.mark.usefixtures("db")
class TestNoModelIsInvolved:

    def test_the_numbers_come_from_rows_only(self, db, workspace, monkeypatch):
        """A progress panel that calls a provider is a progress panel that can
        bill the user for looking at it."""
        from backend.playbook import provider

        def explode(*_a, **_kw):
            raise AssertionError("progress must not call a provider")

        monkeypatch.setattr(provider, "author", explode)
        monkeypatch.setattr(provider, "_call", explode)

        doc = _doc(("1. Scope", BODY))
        _artifact_with(db, workspace, doc)
        assert progress.of(db, workspace.id).content.percent == 100
