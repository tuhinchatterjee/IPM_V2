"""The authoring pipeline, persisted. PB-015, PB-020, PB-022, PB-023, PB-024.

The provider is scripted here so that everything AROUND it can be tested:
evidence assembly, grounding, rendering, validation, versioning and the refusal
to write a version when any of those fail. The live provider path is exercised
separately and is never proven by these tests.
"""

from __future__ import annotations

import pytest

from backend.playbook import provider, repository as repo, service
from backend.playbook.fixtures import ecl_oracle as oracle

REPORT_MD = """# IFRS 9 Committee Report — Q2 2026

## 1. Executive summary

Weighted ECL rose to SAR 22.77 million from SAR 20.90 million, an increase of
SAR 1.87 million [[calc://weighted_ECL_(current)]].

## 2. Scenario results

| Scenario | ECL, SAR million |
| --- | --- |
| Base | 19.20 |
| Downturn | 36.00 |

## 3. Limitations

Post-model adjustments are outside scope.
"""


@pytest.fixture
def ledger():
    from backend.playbook import evidence as ev

    led = ev.Ledger()
    ev.add_calculations(led, list(oracle.headline().values()))
    led.add(ev.Item("xlsx://ECL!B2", "sheet_range", "Base 19.20 Downturn 36.00"))
    return led


def _run(db, scope, workspace, ledger, **kwargs):
    return service.author_document(
        db, scope, workspace.id,
        instruction="Write the committee report.",
        ledger=ledger, title="IFRS 9 Committee Report", **kwargs,
    )


class TestAVersionIsOnlyWrittenWhenEverythingHeld:
    def test_a_run_produces_a_version_with_real_files(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD)
        outcome = _run(db, scope, workspace, ledger)

        assert outcome.ok
        assert outcome.version == 1
        assert set(outcome.files) == {"docx", "pdf"}
        assert all(len(b) > 1000 for b in outcome.files.values())

    def test_the_files_are_on_disk_and_readable_back(
            self, db, scope, workspace, ledger, scripted_author):
        from backend.playbook import store

        scripted_author(REPORT_MD)
        outcome = _run(db, scope, workspace, ledger)
        rows = repo.files(db, outcome.version_id)
        assert {r.format for r in rows} == {"docx", "pdf"}
        for row in rows:
            content = store.read(row.bytes_path)
            assert store.sha256(content) == row.sha256
            assert row.validated is True

    def test_an_empty_answer_writes_no_version(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author("")
        with pytest.raises(provider.AuthoringError, match="no document"):
            _run(db, scope, workspace, ledger)
        assert repo.artifacts(db, workspace.id) == []

    def test_a_failed_generation_leaves_the_previous_version_current(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD)
        first = _run(db, scope, workspace, ledger)

        scripted_author("")
        with pytest.raises(provider.AuthoringError):
            _run(db, scope, workspace, ledger, artifact_id=first.artifact_id)

        from backend.models.playbook import PlaybookArtifact

        artifact = db.get(PlaybookArtifact, first.artifact_id)
        assert artifact.current_version_id == first.version_id
        assert len(repo.versions(db, artifact.id)) == 1


class TestVersionsAreImmutableAndLineal:
    def test_a_second_run_creates_version_two_and_keeps_version_one(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD)
        first = _run(db, scope, workspace, ledger)

        scripted_author(REPORT_MD.replace(
            "Post-model adjustments are outside scope.",
            "Post-model adjustments are outside scope and will be added next quarter."))
        second = _run(db, scope, workspace, ledger,
                      artifact_id=first.artifact_id,
                      base_version_id=first.version_id,
                      change_summary="Expanded the limitations section.")

        versions = repo.versions(db, first.artifact_id)
        assert [v.version for v in versions] == [1, 2]
        assert versions[1].parent_version_id == first.version_id
        assert versions[0].content != versions[1].content
        assert second.version == 2

    def test_the_two_versions_have_genuinely_different_content_hashes(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD)
        first = _run(db, scope, workspace, ledger)
        scripted_author(REPORT_MD.replace("outside scope", "outside this scope"))
        _run(db, scope, workspace, ledger, artifact_id=first.artifact_id,
             base_version_id=first.version_id)
        versions = repo.versions(db, first.artifact_id)
        assert versions[0].content_hash != versions[1].content_hash

    def test_a_stale_base_version_is_refused_rather_than_overwriting(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD)
        first = _run(db, scope, workspace, ledger)
        scripted_author(REPORT_MD.replace("outside scope", "outside this scope"))
        _run(db, scope, workspace, ledger, artifact_id=first.artifact_id,
             base_version_id=first.version_id)

        # A third run still believing v1 is current must not win.
        scripted_author(REPORT_MD.replace("outside scope", "changed again"))
        with pytest.raises(repo.StaleBaseVersion, match="since been revised"):
            _run(db, scope, workspace, ledger, artifact_id=first.artifact_id,
                 base_version_id=first.version_id)
        assert len(repo.versions(db, first.artifact_id)) == 2


class TestGroundingIsEnforcedOnTheWayToDisk:
    def test_an_invented_figure_never_reaches_the_file(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD.replace(
            "Post-model adjustments are outside scope.",
            "Coverage reached 41.5 per cent."))
        outcome = _run(db, scope, workspace, ledger)

        assert outcome.grounding.ok is False
        assert "41.5" not in outcome.document.plain_text()
        from backend.playbook.ingest import docx_reader
        text = " ".join(c.text for c in
                        docx_reader.read(outcome.files["docx"]).chunks)
        assert "41.5" not in text

    def test_the_removal_is_reported_to_the_user(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD.replace(
            "Post-model adjustments are outside scope.",
            "Coverage reached 41.5 per cent."))
        outcome = _run(db, scope, workspace, ledger)
        assert any("could not be traced" in n for n in outcome.notes)

    def test_skill_files_are_discarded_when_grounding_changed_the_document(
            self, db, scope, workspace, ledger, scripted_author):
        """A file written before a figure was retracted must not be shipped."""
        stale = provider.GeneratedFile("file_x", "report.docx", b"PK\x03\x04stale")
        scripted_author(
            REPORT_MD.replace("Post-model adjustments are outside scope.",
                              "Coverage reached 41.5 per cent."),
            files=[stale],
        )
        outcome = _run(db, scope, workspace, ledger)
        assert outcome.renderer == "local"
        assert outcome.files["docx"] != stale.content


class TestEvidenceSelection:
    def test_only_attached_sources_reach_the_ledger(
            self, db, scope, workspace, committee_report_docx,
            results_workbook_xlsx):
        a = service.add_source(db, scope, workspace.id,
                               filename="prior.docx",
                               content=committee_report_docx,
                               source_role="previous_report")
        service.add_source(db, scope, workspace.id, filename="results.xlsx",
                           content=results_workbook_xlsx, source_role="results")

        only_a = service.ledger_for(db, scope, workspace.id, source_ids=[a.id])
        assert any("prior.docx" in i.label for i in only_a.items)
        assert not any("results.xlsx" in i.label for i in only_a.items)

    def test_a_skipped_sheet_is_carried_into_the_ledger_as_a_gap(
            self, db, scope, workspace, results_workbook_xlsx):
        source = service.add_source(db, scope, workspace.id,
                                    filename="results.xlsx",
                                    content=results_workbook_xlsx,
                                    source_role="results")
        led = service.ledger_for(db, scope, workspace.id, source_ids=[source.id])
        assert led.complete is False
        assert any("Working" in o["what"] for o in led.omissions)

    def test_an_unreadable_source_is_recorded_and_does_not_stop_the_workspace(
            self, db, scope, workspace, image_only_pdf):
        source = service.add_source(db, scope, workspace.id, filename="scan.pdf",
                                    content=image_only_pdf)
        assert source.status == "failed"
        led = service.ledger_for(db, scope, workspace.id, source_ids=[source.id])
        assert any("scan.pdf" in o["what"] for o in led.omissions)


class TestForeignTenantIdsAreRefused:
    def test_another_tenants_workspace_is_not_found(self, db, workspace):
        other = repo.Scope(tenant="someone-else")
        with pytest.raises(repo.NotFound):
            repo.get_workspace(db, other, workspace.id)
