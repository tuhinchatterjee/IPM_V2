"""Gate 9 — a better reader is a reason to read again, never to re-upload. §18.

The bytes are immutable. Improving a reader does not invalidate the upload; it
invalidates the READING. A source read by an older reader still holds
everything it always held — what it is missing is whatever the newer reader
would now find. So the remedy is a local re-read of the stored bytes: free, no
provider call, and no asking the user to find the file again.

Three things this suite pins:

* **provenance** — every read records which reader made it, against which
  chunk schema, and the earlier revisions stay, so a document generated three
  months ago can be traced to the reading it was actually written from;
* **staleness is computed** — a comparison against `ingest.version` made when
  asked, so deploying a better reader marks the affected sources without a
  migration and without a background job rewriting rows;
* **a stale source cannot be used silently** — it is an evidence gap, and the
  thread says so.
"""

from __future__ import annotations

import pytest

from backend.playbook import reparse, service
from backend.playbook import repository as repo
from backend.playbook.ingest import validate as fmt
from backend.playbook.ingest import version as pv


def _upload(db, scope, workspace, content: bytes, filename: str):
    return service.add_source(db, scope, workspace.id, filename=filename,
                              content=content, source_role="results")


# ================================================== what a version means


class TestTheParserVersionMeansSomething:
    """A version nobody can act on is decoration. These are the properties
    that make it load-bearing."""

    def test_every_readable_format_declares_a_version(self):
        for kind in (fmt.DOCX, fmt.PDF, fmt.XLSX, fmt.CSV, fmt.PPTX):
            assert pv.current(kind)

    def test_a_format_with_no_reader_still_records_a_version(self):
        """Every parse names a version. An empty string is not provenance."""
        assert pv.current("txt") == pv.DEFAULT_VERSION

    def test_the_same_version_is_not_stale(self):
        assert not pv.is_stale(fmt.XLSX, parser_version=pv.current(fmt.XLSX),
                               schema_version=pv.SCHEMA_VERSION)

    def test_an_older_reader_is_stale(self):
        assert pv.is_stale(fmt.XLSX, parser_version="1",
                           schema_version=pv.SCHEMA_VERSION)

    def test_an_older_schema_is_stale_whatever_the_reader(self):
        assert pv.is_stale(fmt.DOCX, parser_version=pv.current(fmt.DOCX),
                           schema_version="1")

    def test_a_newer_reader_is_left_alone(self):
        """A database restored from a later deployment is not re-read
        backwards into a worse reading."""
        assert not pv.is_stale(fmt.XLSX, parser_version="99",
                               schema_version="99")

    def test_an_unrecognisable_version_counts_as_stale(self):
        """Silently trusting a reading whose provenance cannot be established
        is the alternative, and it is worse."""
        assert pv.is_stale(fmt.DOCX, parser_version="who knows",
                           schema_version=pv.SCHEMA_VERSION)

    def test_an_improvement_is_described_in_words_a_user_can_act_on(self):
        [change] = pv.what_changed(fmt.XLSX, parser_version="1")
        assert "as displayed" in change and "stored" in change

    def test_a_current_reading_has_nothing_to_report(self):
        assert pv.what_changed(fmt.XLSX,
                               parser_version=pv.current(fmt.XLSX)) == []


# ================================================== recording every read


@pytest.mark.usefixtures("db")
class TestEveryReadIsRecorded:

    def test_an_upload_records_the_reader_that_read_it(
            self, db, scope, workspace, results_workbook_xlsx):
        source = _upload(db, scope, workspace, results_workbook_xlsx,
                         "results.xlsx")
        row = reparse.latest(db, source.id)
        assert row.revision == 1
        assert row.parser_version == pv.current(fmt.XLSX)
        assert row.schema_version == pv.SCHEMA_VERSION
        assert row.chunk_count > 0
        assert row.superseded is False

    def test_a_freshly_uploaded_source_is_not_stale(
            self, db, scope, workspace, committee_report_docx):
        source = _upload(db, scope, workspace, committee_report_docx,
                         "report.docx")
        assert reparse.state(db, source).stale is False

    def test_a_partial_read_is_recorded_as_partial_not_as_complete(
            self, db, scope, workspace, results_workbook_xlsx):
        """The workbook has a hidden sheet, so the read is honest about not
        being complete — and the parse revision says the same thing."""
        source = _upload(db, scope, workspace, results_workbook_xlsx,
                         "results.xlsx")
        assert reparse.latest(db, source.id).status == reparse.PARTIAL

    def test_a_failed_read_is_recorded_too(self, db, scope, workspace,
                                           committee_report_docx, monkeypatch):
        """"This file was tried with this reader and could not be read" is
        information. Without it a retry loop cannot tell a transient failure
        from a file that will never parse.

        The reader is made to fail rather than a file found that fails: a file
        rejected at the door never becomes a source at all, and what is under
        test is the recording, not the reader.
        """
        from backend.playbook import ingest as ing

        def unreadable(filename, content):
            raise ing.UnreadableSource(f"{filename} could not be read.")

        monkeypatch.setattr(service.ingest, "read", unreadable)
        broken = service.add_source(db, scope, workspace.id,
                                    filename="report.docx",
                                    content=committee_report_docx,
                                    source_role="results")

        row = reparse.latest(db, broken.id)
        assert row is not None and row.status == reparse.FAILED
        assert row.failure_reason == "report.docx could not be read."
        assert row.parser_version == pv.current(fmt.DOCX)

    def test_a_failed_read_is_stale_so_it_can_be_tried_again(
            self, db, scope, workspace, committee_report_docx, monkeypatch):
        from backend.playbook import ingest as ing

        def unreadable(filename, content):
            raise ing.UnreadableSource("nope")

        monkeypatch.setattr(service.ingest, "read", unreadable)
        broken = service.add_source(db, scope, workspace.id,
                                    filename="report.docx",
                                    content=committee_report_docx,
                                    source_role="results")
        reading = reparse.state(db, broken)
        assert reading.stale is True
        assert reading.reason == reparse.FAILED_PARSE

    def test_a_source_with_no_parse_revision_is_stale(
            self, db, scope, workspace, committee_report_docx):
        """Its reading exists, but nothing records which reader produced it,
        and a reading whose provenance cannot be established is not one to
        keep quoting."""
        source = _upload(db, scope, workspace, committee_report_docx,
                         "report.docx")
        for row in reparse.history(db, source.id):
            db.delete(row)
        db.flush()

        reading = reparse.state(db, source)
        assert reading.stale is True
        assert reading.reason == reparse.UNRECORDED
        assert reading.reason_label == "Read before parse revisions were recorded"


# ================================================== re-reading


@pytest.mark.usefixtures("db")
class TestReReading:

    def _staled(self, db, scope, workspace, content, filename):
        source = _upload(db, scope, workspace, content, filename)
        row = reparse.latest(db, source.id)
        row.parser_version = "0"
        db.flush()
        return source

    def test_a_stale_source_says_what_a_re_read_would_find(
            self, db, scope, workspace, results_workbook_xlsx):
        source = self._staled(db, scope, workspace, results_workbook_xlsx,
                              "results.xlsx")
        reading = reparse.state(db, source)
        assert reading.stale and reading.reason == reparse.BEHIND
        assert any("as displayed" in i for i in reading.improvements)

    def test_a_re_read_uses_the_stored_bytes_and_makes_a_new_revision(
            self, db, scope, workspace, results_workbook_xlsx):
        source = self._staled(db, scope, workspace, results_workbook_xlsx,
                              "results.xlsx")
        before = len(repo.chunks(db, source.id))

        reading = reparse.reread(db, scope, source.id)

        assert reading.stale is False
        assert reading.revision == 2
        assert reading.parser_version == pv.current(fmt.XLSX)
        assert len(repo.chunks(db, source.id)) == before

    def test_the_earlier_reading_is_superseded_not_deleted(
            self, db, scope, workspace, results_workbook_xlsx):
        """A document generated three months ago can still be traced to the
        reading it was actually written from."""
        source = self._staled(db, scope, workspace, results_workbook_xlsx,
                              "results.xlsx")
        reparse.reread(db, scope, source.id)

        revisions = reparse.history(db, source.id)
        assert [r.revision for r in revisions] == [1, 2]
        assert revisions[0].superseded is True
        assert revisions[1].superseded is False
        assert revisions[0].parser_version == "0"

    def test_a_re_read_makes_no_provider_call(
            self, db, scope, workspace, results_workbook_xlsx, monkeypatch):
        from backend.playbook import provider

        source = self._staled(db, scope, workspace, results_workbook_xlsx,
                              "results.xlsx")
        monkeypatch.setattr(provider, "author", _never)
        reparse.reread(db, scope, source.id)

    def test_a_re_read_does_not_touch_the_document(
            self, db, scope, workspace, results_workbook_xlsx):
        """§16's governed refresh is where rewriting belongs, and it is a
        person's decision."""
        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="Report")
        db.flush()
        version = repo.new_version(db, artifact,
                                   content={"title": "Report", "sections": []},
                                   source_manifest={}, content_hash="h",
                                   validation={})
        db.flush()
        source = self._staled(db, scope, workspace, results_workbook_xlsx,
                              "results.xlsx")

        reparse.reread(db, scope, source.id)

        assert len(repo.versions(db, artifact.id)) == 1
        assert repo.versions(db, artifact.id)[0].id == version.id

    def test_re_reading_a_source_whose_bytes_are_gone_says_so(
            self, db, scope, workspace, committee_report_docx):
        source = _upload(db, scope, workspace, committee_report_docx,
                         "report.docx")
        source.bytes_path = "playbook/gone/nothing.docx"
        db.flush()
        with pytest.raises(reparse.BytesGone) as raised:
            reparse.reread(db, scope, source.id)
        assert "Upload it once more" in str(raised.value)

    def test_re_reading_a_source_from_another_tenant_is_refused(
            self, db, scope, workspace, committee_report_docx):
        source = _upload(db, scope, workspace, committee_report_docx,
                         "report.docx")
        elsewhere = repo.Scope(tenant="somebody-else", user_id=1)
        with pytest.raises(repo.NotFound):
            reparse.reread(db, elsewhere, source.id)


def _never(*args, **kwargs):
    raise AssertionError("re-reading must never reach a provider")


# ================================================== the workspace view


@pytest.mark.usefixtures("db")
class TestTheWorkspaceView:

    def test_a_workspace_with_no_sources_says_so(self, db, workspace):
        assert reparse.summary(db, workspace.id)["message"] == (
            "No sources attached")

    def test_current_sources_are_reported_as_current(
            self, db, scope, workspace, committee_report_docx):
        _upload(db, scope, workspace, committee_report_docx, "report.docx")
        state = reparse.summary(db, workspace.id)
        assert state["needs_reread"] == 0
        assert state["message"] == "1 source current"

    def test_the_count_is_the_line_the_dashboard_shows(
            self, db, scope, workspace, committee_report_docx,
            results_workbook_xlsx):
        _upload(db, scope, workspace, committee_report_docx, "report.docx")
        stale = _upload(db, scope, workspace, results_workbook_xlsx,
                        "results.xlsx")
        reparse.latest(db, stale.id).parser_version = "0"
        db.flush()

        state = reparse.summary(db, workspace.id)
        assert state["sources"] == 2 and state["current"] == 1
        assert state["message"] == "1 source needs re-read"

    def test_re_reading_all_stale_leaves_the_current_ones_alone(
            self, db, scope, workspace, committee_report_docx,
            results_workbook_xlsx):
        fine = _upload(db, scope, workspace, committee_report_docx,
                       "report.docx")
        stale = _upload(db, scope, workspace, results_workbook_xlsx,
                        "results.xlsx")
        reparse.latest(db, stale.id).parser_version = "0"
        db.flush()

        result = reparse.reread_stale(db, scope, workspace.id)

        assert [r["source_id"] for r in result["reread"]] == [stale.id]
        assert result["needs_reread"] == 0
        assert reparse.latest(db, fine.id).revision == 1
        assert reparse.latest(db, stale.id).revision == 2

    def test_one_missing_file_does_not_stop_the_others(
            self, db, scope, workspace, committee_report_docx,
            results_workbook_xlsx):
        gone = _upload(db, scope, workspace, committee_report_docx,
                       "report.docx")
        gone.bytes_path = "playbook/gone/nothing.docx"
        recoverable = _upload(db, scope, workspace, results_workbook_xlsx,
                              "results.xlsx")
        for source in (gone, recoverable):
            reparse.latest(db, source.id).parser_version = "0"
        db.flush()

        result = reparse.reread_stale(db, scope, workspace.id)

        assert [r["source_id"] for r in result["reread"]] == [recoverable.id]
        assert [f["source_id"] for f in result["failed"]] == [gone.id]
        assert result["needs_reread"] == 1


# ================================================== generation cannot rest on it


@pytest.mark.usefixtures("db")
class TestAStaleSourceIsNeverUsedSilently:
    """§19 item 13. A source read by an older reader is evidence read WORSE
    than it can be — not missing, but not a complete reading either."""

    def test_a_stale_source_is_an_evidence_gap(
            self, db, scope, workspace, results_workbook_xlsx):
        source = _upload(db, scope, workspace, results_workbook_xlsx,
                         "results.xlsx")
        reparse.latest(db, source.id).parser_version = "0"
        db.flush()

        ledger = service.ledger_for(db, scope, workspace.id)
        assert ledger.complete is False
        [gap] = [o for o in ledger.omissions if "older version" in o["what"]]
        assert "as displayed" in gap["why"]

    def test_the_source_is_still_read_not_withheld(
            self, db, scope, workspace, results_workbook_xlsx):
        """A worse reading is still a reading. Withholding it would replace a
        stated caveat with a silent absence, which is the worse failure."""
        source = _upload(db, scope, workspace, results_workbook_xlsx,
                         "results.xlsx")
        reparse.latest(db, source.id).parser_version = "0"
        db.flush()

        ledger = service.ledger_for(db, scope, workspace.id)
        assert any(i.locator.startswith("xlsx://") for i in ledger.items)

    def test_re_reading_closes_the_gap(
            self, db, scope, workspace, results_workbook_xlsx):
        source = _upload(db, scope, workspace, results_workbook_xlsx,
                         "results.xlsx")
        reparse.latest(db, source.id).parser_version = "0"
        db.flush()
        reparse.reread(db, scope, source.id)

        ledger = service.ledger_for(db, scope, workspace.id)
        assert not [o for o in ledger.omissions if "older version" in o["what"]]

    def test_a_current_source_adds_no_gap_of_its_own(
            self, db, scope, workspace, committee_report_docx):
        _upload(db, scope, workspace, committee_report_docx, "report.docx")
        ledger = service.ledger_for(db, scope, workspace.id)
        assert ledger.complete is True
