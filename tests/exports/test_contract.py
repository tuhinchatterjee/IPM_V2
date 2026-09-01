"""
The export contract: filenames, sheet names and the limits.

Small, exact tests. Every one of these rules exists because breaking it
produces a file somebody cannot open, or two sheets Excel refuses to hold in
one workbook, and neither failure is visible until the download reaches a
laptop.
"""

from __future__ import annotations

import pytest

from backend.exports import contract


class TestFilenames:
    def test_a_filename_is_safe_on_windows(self):
        name = contract.filename_for(
            contract.RESULTS,
            analysis='EAD by rating: "latest" / Q2 2026?',
            period="Q2 2026", run_id=42, fingerprint="abc123def456",
        )
        assert not set(name) & set('<>:"/\\|?*')
        assert name.endswith("_results.xlsx")
        assert name.startswith("CreditProbe_")

    def test_the_filename_names_the_run_and_the_plan(self):
        name = contract.filename_for(
            contract.CALCULATION_PACK, analysis="Exposure by sector",
            period="Q2 2026", run_id=7, fingerprint="01bd86cdd285ffa5")
        assert "01bd86" in name
        assert "calculation_pack" in name

    def test_the_period_is_not_repeated(self):
        """An analysis is usually titled by its own scope, period included."""
        name = contract.filename_for(
            contract.RESULTS, analysis="Exposure at default by sector at Q2 2026",
            period="Q2 2026", run_id=3, fingerprint="01bd86cdd285ffa5")
        assert name.count("q2_2026") == 1, name
        assert "_at_q2_2026_q2_2026" not in name

    def test_a_title_that_does_not_carry_the_period_still_gets_one(self):
        name = contract.filename_for(
            contract.RESULTS, analysis="Exposure by sector",
            period="Q2 2026", run_id=3, fingerprint="01bd86cdd285ffa5")
        assert "q2_2026" in name

    def test_two_runs_of_the_same_question_get_different_filenames(self):
        """Otherwise a reviewer's downloads folder silently overwrites itself."""
        first = contract.filename_for(contract.RESULTS, analysis="Same question",
                                      period="Q2 2026", run_id=1,
                                      fingerprint="aaaaaaaaaaaaaaaa")
        second = contract.filename_for(contract.RESULTS, analysis="Same question",
                                       period="Q2 2026", run_id=1,
                                       fingerprint="bbbbbbbbbbbbbbbb")
        assert first != second


class TestSheetNames:
    def test_a_sheet_name_fits_excels_limit(self):
        name = contract.sheet_name("A very long sheet name that Excel will not accept")
        assert len(name) <= 31

    def test_illegal_characters_are_removed(self):
        assert not set(contract.sheet_name("Q2/2026 [draft]:*?")) & set(r"[]:*?/\\")

    def test_duplicate_names_are_numbered_apart(self):
        taken: set[str] = set()
        first = contract.sheet_name("SOURCE PROFILES", taken=taken)
        second = contract.sheet_name("SOURCE PROFILES", taken=taken)
        third = contract.sheet_name("SOURCE PROFILES", taken=taken)
        assert len({first, second, third}) == 3
        assert all(len(n) <= 31 for n in (first, second, third))


class TestLimits:
    def test_the_row_ceiling_is_below_excels_own(self):
        assert contract.ROWS_PER_SHEET < contract.EXCEL_MAX_ROWS

    def test_an_export_error_carries_a_status_and_a_message(self):
        error = contract.NotExportable("nothing to export")
        assert error.status == 409
        assert error.message == "nothing to export"

    def test_a_missing_run_is_a_different_answer_from_an_unexportable_one(self):
        assert contract.RunNotFound("no such run").status == 404
        assert contract.NotExportable("clarification").status == 409
        assert contract.TooLarge("too big").status == 413


class TestWorkbookValue:
    def test_size_is_the_length_of_the_content(self):
        book = contract.Workbook(filename="x.xlsx", content=b"1234",
                                 kind=contract.RESULTS)
        assert book.size == 4


@pytest.mark.parametrize("kind", [contract.RESULTS, contract.CALCULATION_PACK])
def test_every_kind_produces_an_xlsx_filename(kind):
    name = contract.filename_for(kind, analysis="Q", period="Q2 2026", run_id=1)
    assert name.endswith(".xlsx")
