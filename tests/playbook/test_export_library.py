"""Export to Playbook, and the boundary around it. PB-005, PB-006, PB-008, PB-010.

The rule these tests exist to hold: only an explicit export is in the library,
and re-exporting the same analysis does not multiply the evidence.
"""

from __future__ import annotations

import pytest

from backend.exports import playbook_contract as contract
from backend.playbook import library
from backend.playbook.repository import NotFound


def _snapshot(**over) -> contract.Snapshot:
    base = dict(
        source_module=contract.COCKPIT,
        title="Quarter-on-quarter ECL movement",
        question="How did ECL move between Q1 and Q2 2026?",
        narrative=("Weighted ECL rose to SAR 22.77 million from SAR 20.90 "
                   "million, an increase of SAR 1.87 million or 8.95 per cent. "
                   "The movement is driven by the downturn scenario."),
        tables=[contract.Table(
            id="ecl_by_scenario", title="ECL by scenario",
            columns=["Scenario", "Q1 2026", "Q2 2026"],
            rows=[["Base", "18.00", "19.20"], ["Downturn", "32.00", "36.00"]],
            units={"Q1 2026": "SAR million", "Q2 2026": "SAR million"},
            precision={"Q1 2026": 2, "Q2 2026": 2},
        )],
        scope={"reporting_period": "Q2 2026", "currency": "SAR"},
        source_ref={"run_id": 4101, "thread_id": 77},
        reporting_period="Q2 2026",
        insight="Weighted ECL rose 8.95 per cent quarter on quarter.",
    )
    base.update(over)
    return contract.Snapshot(**base)


class TestOnlyCompletedAnalysesExport:
    def test_a_substantive_analysis_exports(self, db, scope):
        result = library.create(db, scope, _snapshot())
        assert result.created is True
        assert result.revision == 1

    def test_a_greeting_is_not_an_analysis(self, db, scope):
        with pytest.raises(contract.InvalidExport, match="not a completed"):
            library.create(db, scope, _snapshot(narrative="Hello.", tables=[]))

    def test_an_unfinished_answer_with_no_content_is_refused(self, db, scope):
        with pytest.raises(contract.InvalidExport, match="not a completed"):
            library.create(db, scope, _snapshot(narrative="", tables=[]))

    def test_an_unknown_module_is_refused(self, db, scope):
        with pytest.raises(contract.InvalidExport, match="not a module"):
            library.create(db, scope, _snapshot(source_module="project_planner"))

    def test_a_table_alone_is_enough_to_be_substantive(self, db, scope):
        assert library.create(db, scope, _snapshot(narrative="")).created


class TestReExportingIsIdempotent:
    def test_the_same_snapshot_twice_creates_one_revision(self, db, scope):
        first = library.create(db, scope, _snapshot())
        second = library.create(db, scope, _snapshot())
        assert second.duplicate is True
        assert second.revision_id == first.revision_id
        assert second.revision == 1

    def test_a_changed_analysis_creates_a_second_revision(self, db, scope):
        first = library.create(db, scope, _snapshot())
        changed = _snapshot(narrative=_snapshot().narrative + " Revised.")
        second = library.create(db, scope, changed)
        assert second.duplicate is False
        assert second.revision == 2
        assert second.export_id == first.export_id

    def test_the_earlier_revision_is_unchanged_by_the_later_one(self, db, scope):
        first = library.create(db, scope, _snapshot())
        before = library.preview(db, scope, first.revision_id)
        library.create(db, scope,
                       _snapshot(narrative=_snapshot().narrative + " Revised."))
        after = library.preview(db, scope, first.revision_id)
        assert before["narrative"] == after["narrative"]
        assert before["content_hash"] == after["content_hash"]

    def test_a_newer_revision_is_surfaced_not_substituted(self, db, scope):
        first = library.create(db, scope, _snapshot())
        library.create(db, scope,
                       _snapshot(narrative=_snapshot().narrative + " Revised."))
        old = library.preview(db, scope, first.revision_id)
        assert old["newer_revision_available"] == 2

    def test_a_different_scope_is_different_evidence(self, db, scope):
        library.create(db, scope, _snapshot())
        wider = library.create(
            db, scope, _snapshot(scope_kind=contract.SCOPE_INVESTIGATION))
        assert wider.created is True
        assert wider.revision == 1


class TestThePreviewShowsTheAnalysisNotASummary:
    def test_it_carries_narrative_tables_scope_and_provenance(self, db, scope):
        result = library.create(db, scope, _snapshot(
            assumptions=["Weights unchanged"], limitations=["Excludes PMAs"],
            provenance={"trace_id": "tr-1"}))
        payload = library.preview(db, scope, result.revision_id)
        assert "22.77" in payload["narrative"]
        assert payload["tables"][0]["rows"]
        assert payload["tables"][0]["units"]["Q2 2026"] == "SAR million"
        assert payload["scope"]["reporting_period"] == "Q2 2026"
        assert payload["assumptions"] == ["Weights unchanged"]
        assert payload["limitations"] == ["Excludes PMAs"]
        assert payload["provenance"]["trace_id"] == "tr-1"
        assert payload["question"]

    def test_the_original_question_is_kept(self, db, scope):
        result = library.create(db, scope, _snapshot())
        assert "How did ECL move" in library.preview(
            db, scope, result.revision_id)["question"]


class TestTheBackendEnforcesTheBoundary:
    def test_a_foreign_tenants_revision_is_not_found(self, db, scope):
        from backend.playbook.repository import Scope

        result = library.create(db, scope, _snapshot())
        with pytest.raises(NotFound):
            library.preview(db, Scope(tenant="another-bank"), result.revision_id)

    def test_an_unexported_id_is_not_found(self, db, scope):
        with pytest.raises(NotFound):
            library.preview(db, scope, 99_999_999)

    def test_attaching_a_foreign_revision_is_refused(self, db, scope):
        """The backend half of PB-005: bypassing the picker changes nothing."""
        from backend.playbook import repository as repo

        result = library.create(db, scope, _snapshot())
        with pytest.raises(NotFound):
            repo.find_export_revision(db, repo.Scope(tenant="another-bank"),
                                      result.revision_id)


class TestBrowsingTheLibrary:
    def test_search_filter_and_sort(self, db, scope):
        library.create(db, scope, _snapshot())
        library.create(db, scope, _snapshot(
            source_module=contract.LENSES, title="Corporate portfolio review",
            source_ref={"lens_id": 9}, insight="Concentration rose."))

        found, total = library.browse(db, scope, query="corporate")
        assert total == 1
        assert found[0].source_module == contract.LENSES

        by_module, _ = library.browse(db, scope, modules=[contract.COCKPIT])
        assert all(c.source_module == contract.COCKPIT for c in by_module)

        by_period, _ = library.browse(db, scope, period="Q2 2026")
        assert by_period

    def test_a_card_reports_how_many_revisions_exist(self, db, scope):
        library.create(db, scope, _snapshot())
        library.create(db, scope,
                       _snapshot(narrative=_snapshot().narrative + " Revised."))
        cards, _ = library.browse(db, scope)
        card = next(c for c in cards if c.source_module == contract.COCKPIT)
        assert card.revisions == 2
        assert card.revision == 2


class TestTheContractIsExplicitAboutWhatIsDeferred:
    def test_what_if_is_in_the_contract_but_not_implemented_here(self):
        assert contract.WHAT_IF in contract.SOURCE_MODULES
        assert contract.WHAT_IF not in contract.IMPLEMENTED_MODULES

    def test_project_planner_is_not_a_source_module(self):
        assert "project_planner" not in contract.SOURCE_MODULES

    def test_a_what_if_snapshot_still_validates_against_the_contract(self):
        """The adapter contract is real even though no surface produces it."""
        snapshot = _snapshot(source_module=contract.WHAT_IF,
                             title="Downturn sensitivity")
        snapshot.validate()
        assert snapshot.content_hash()
