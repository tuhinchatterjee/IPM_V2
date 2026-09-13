"""One spreadsheet fact, two true readings. PB-014, PB-032, PB-041.

From human UAT. An Auto Loan scorecard report was generated, rendered and then
refused at the save gate:

    the rendered file states figure(s) that are in no source:
    0.0483940782525048, 0.0578045975456491, 0.0601084363942583,
    0.477011494252873, 0.492378473835858, 0.506053268765133,
    0.54022988505747, 0.5593220338983

Those are the full-precision Brier, KS and Gini values stored in
`03_Auto_Loan_Performance_and_Validation_Results.xlsx`, whose cells are
formatted `0.000`. Two defects, and they compound.

*The reader threw the number format away.* `sheets` recorded `str(cached)` and
never looked at `cell.number_format`, so the evidence ledger quoted seventeen
significant digits. Grounding matches figures exactly — rightly — so a report
that wrote the readable 0.559 had that figure REMOVED as unsupported, and the
only way to survive the check was to print the raw float. The workbook says how
the figure is read; the pipeline was the only party not listening.

*And validation compared two representations of the same fact.* `_check_content`
built its allowed set with `figures()`, which returns only evidence-BEARING
numbers, and that classification reads the word before a number. A table row
"Note 0.559" is one line in the canonical document, where "Note" makes it a
section reference and exempt; a PDF's text layer puts each cell on its own
line, where nothing precedes it and it is an ordinary count. Present, not
allowed — so a report was refused for stating a figure out of its own table.

Whether a number needs evidence is grounding's question and was settled before
anything was rendered. Validation asks only whether the file says what the
document says, so it now compares every numeral on both sides.
"""

from __future__ import annotations

import io

import pytest

from backend.playbook import calc, grounding, render, validate
from backend.playbook import document as D
from backend.playbook import evidence as ev
from backend.playbook.ingest import docx_reader, pdf_reader, sheets

#: The AUC cell from the UAT workbook: stored exactly, displayed as 0.000.
RAW = "0.5593220338983"
SHOWN = "0.559"

#: A genuinely different figure. It is in no cell of the fixture workbook.
INVENTED = "0.659"

#: Every value the UAT run rejected, with the cell it came from.
AUTO_LOAN = [
    ("Brier score", "0.0483940782525048", "0.048"),
    ("Brier score, used", "0.0578045975456491", "0.058"),
    ("Brier score, new", "0.0601084363942583", "0.060"),
    ("Gini", "0.477011494252873", "0.477"),
    ("Gini, used", "0.492378473835858", "0.492"),
    ("KS", "0.506053268765133", "0.506"),
    ("KS, used", "0.54022988505747", "0.540"),
    ("AUC", "0.5593220338983", "0.559"),
]

FORMATS = ("docx", "pdf")


def workbook(rows: list[tuple[str, float]], *, number_format: str = "0.000",
             sheet: str = "Validation") -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(("Metric", "Value"))
    for label, value in rows:
        ws.append((label, value))
    for r in range(2, len(rows) + 2):
        ws.cell(row=r, column=2).number_format = number_format
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def ledger_for(content: bytes) -> tuple[ev.Ledger, object]:
    chunk = sheets.read(content, filename="03_Auto_Loan_Performance.xlsx"
                        ).chunks[0]
    led = ev.Ledger()
    led.add(ev.Item(chunk.locator, "sheet_range", chunk.text, data=chunk.data))
    return led, chunk


def rendered_text(doc: D.Document, fmt: str) -> str:
    content = render.render(doc, fmt)
    if fmt == "docx":
        r = docx_reader.read(content)
        return "\n".join([c.text for c in r.chunks]
                         + [" ".join(str(x) for row in c.data.get("rows", [])
                                     for x in row)
                            for c in r.chunks if c.kind == "table"])
    return "\n".join(c.text for c in pdf_reader.read(content).chunks
                     if c.kind == "page")


# ================================================= 1. ingestion provenance

class TestIngestionKeepsEverything:

    @pytest.fixture
    def chunk(self):
        return sheets.read(workbook([("AUC", float(RAW))]),
                           filename="perf.xlsx").chunks[0]

    def test_the_raw_value_is_retained(self, chunk):
        assert chunk.data["raw_rows"] == [["AUC", RAW]]

    def test_the_displayed_value_is_what_the_format_says(self, chunk):
        assert chunk.data["rows"] == [["AUC", SHOWN]]

    def test_the_locator_and_the_cell_are_retained(self, chunk):
        assert chunk.locator == "xlsx://Validation!A1"
        assert chunk.data["cells"] == [["A2", "B2"]]

    def test_a_cell_with_no_stated_format_is_left_exactly_as_stored(self):
        """`General` states no precision, so none is invented."""
        chunk = sheets.read(workbook([("AUC", float(RAW))],
                                     number_format="General"),
                            filename="perf.xlsx").chunks[0]
        assert chunk.data["rows"] == [["AUC", RAW]]
        assert chunk.data["raw_rows"] == [["AUC", RAW]]

    def test_currency_keeps_its_own_precision(self):
        chunk = sheets.read(workbook([("Exposure", 1234567.891)],
                                     number_format="#,##0.00"),
                            filename="perf.xlsx").chunks[0]
        assert chunk.data["rows"] == [["Exposure", "1234567.89"]]

    def test_a_whole_number_format_keeps_no_decimals(self):
        chunk = sheets.read(workbook([("Accounts", 1050.4)],
                                     number_format="#,##0"),
                            filename="perf.xlsx").chunks[0]
        assert chunk.data["rows"] == [["Accounts", "1050"]]

    def test_text_is_not_touched(self):
        chunk = sheets.read(workbook([("Segment", 0.5)]),
                            filename="perf.xlsx").chunks[0]
        assert chunk.data["columns"] == ["Metric", "Value"]


# ================================================= 2. the governed precision

class TestThePrecisionPolicyIsOneTable:
    """`calc` already separates a value from the way it is shown. The
    spreadsheet path borrows that rather than growing a second policy."""

    def test_a_discrimination_statistic_is_shown_to_three_decimals(self):
        assert calc.DISPLAY_DP[calc.STATISTIC] == 3

    @pytest.mark.parametrize("label", [
        "AUC", "Gini coefficient", "KS statistic", "Brier score",
        "ROC area", "AUROC"])
    def test_the_metric_names_that_fix_their_own_precision(self, label):
        assert calc.statistic_dp(label) == 3

    def test_a_label_that_implies_nothing_gets_nothing(self):
        assert calc.statistic_dp("Exposure at default") is None

    @pytest.mark.parametrize("unit,dp", [
        (calc.COUNT, 0), (calc.CURRENCY, 2), (calc.PERCENT, 2),
        (calc.PERCENTAGE_POINT, 2), (calc.BASIS_POINT, 0),
        (calc.RATIO, 4), (calc.STATISTIC, 3)])
    def test_each_unit_has_its_own_precision(self, unit, dp):
        assert calc.display_dp(unit) == dp

    def test_an_unknown_unit_is_refused_rather_than_defaulted(self):
        with pytest.raises(calc.CalculationError):
            calc.display_dp("furlongs")

    def test_presentation_is_half_even_and_returns_a_string(self):
        assert calc.present(RAW, 3) == SHOWN
        assert isinstance(calc.present(RAW, 3), str)


# ================================================= 3. grounding the same fact

class TestTheSameFactGroundsEitherWay:

    @pytest.fixture
    def led(self):
        return ledger_for(workbook([("AUC", float(RAW))]))[0]

    def test_the_ledger_carries_both_readings(self, led):
        assert {RAW, SHOWN} <= led.figures()

    @pytest.mark.parametrize("claim", [RAW, SHOWN])
    def test_a_report_quoting_either_reading_is_grounded(self, led, claim):
        doc = D.parse(f"## 1. Results\n\nThe AUC was {claim}.\n", title="R")
        assert grounding.check(doc, led, remove=False).ok is True

    def test_a_genuinely_different_figure_is_still_refused(self, led):
        doc = D.parse(f"## 1. Results\n\nThe AUC was {INVENTED}.\n", title="R")
        assert grounding.check(doc, led, remove=False).ok is False

    @pytest.mark.parametrize("near", ["0.558", "0.56", "0.5593", "0.55932"])
    def test_no_epsilon_was_introduced(self, led, near):
        """Any rounding the workbook did not state is not a reading of the
        cell. Nothing is accepted for being close."""
        doc = D.parse(f"## 1. Results\n\nThe AUC was {near}.\n", title="R")
        assert grounding.check(doc, led, remove=False).ok is False

    def test_the_readings_admitted_are_exactly_two(self, led):
        assert led.figures() == {RAW, SHOWN}


# ================================================= 4. render and validate

class TestTheReportSurvivesTheSaveGate:

    def report(self, value: str) -> D.Document:
        rows = "\n".join(f"| {label} | {value} |" for label, _, _ in AUTO_LOAN)
        return D.parse(
            "# Auto Loan Application Scorecard Report\n\n"
            "## 1. Summary\n\nDiscrimination was assessed.\n\n"
            "## 2. Validation results\n\n| Metric | Value |\n| --- | --- |\n"
            f"{rows}\n", title="Auto Loan Application Scorecard Report")

    @pytest.mark.parametrize("fmt", FORMATS)
    @pytest.mark.parametrize("value", [SHOWN, RAW])
    def test_both_readings_validate_in_both_formats(self, fmt, value):
        doc = self.report(value)
        v = validate.validate(render.render(doc, fmt), fmt, doc)
        assert v.ok is True, v.issues

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_governed_value_is_rendered_consistently(self, fmt):
        assert SHOWN in rendered_text(self.report(SHOWN), fmt)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_a_figure_the_document_does_not_state_still_fails(self, fmt):
        content = render.render(self.report(INVENTED), fmt)
        v = validate.validate(content, fmt, self.report(SHOWN))
        assert v.ok is False
        assert INVENTED in " ".join(v.issues)


# ================================================= the exact UAT failure

class TestTheExactAutoLoanFailure:
    """Reproduced from the workbook side, and shown to be fixed."""

    @pytest.fixture
    def led(self):
        return ledger_for(workbook(
            [(label, float(raw)) for label, raw, _ in AUTO_LOAN]))[0]

    @pytest.mark.parametrize("label,raw,shown", AUTO_LOAN)
    def test_every_rejected_value_has_both_readings(self, led, label, raw,
                                                    shown):
        # Compared through `figures()` on both sides, because it has always
        # normalised trailing zeros — "0.060" and "0.06" are one token, and
        # that predates all of this and applies symmetrically.
        assert validate.figures(raw) <= led.figures()
        assert validate.figures(shown) <= led.figures()

    def test_trailing_zero_normalisation_is_symmetric_and_not_new(self):
        """The one normalisation that was already there: 1,050 == 1050.00.
        It is applied to both sides of every comparison, so it can neither
        invent a figure nor excuse one."""
        assert validate.figures("0.060") == validate.figures("0.06")
        assert validate.figures("1,050") == validate.figures("1050.00")
        assert validate.figures("0.06") != validate.figures("0.061")

    @pytest.mark.parametrize("label,raw,shown", AUTO_LOAN)
    def test_the_readable_value_is_now_groundable(self, led, label, raw,
                                                  shown):
        doc = D.parse(f"## 1. Results\n\nThe {label} was {shown}.\n", title="R")
        assert grounding.check(doc, led, remove=False).ok is True

    @pytest.mark.parametrize("label", [
        "Note", "Item", "Row", "Line", "Table", "Section", "Step", "Phase",
        "Page", "Figure", "Column", "Part", "June", "Dec", "Metric"])
    @pytest.mark.parametrize("fmt", FORMATS)
    def test_a_row_label_can_no_longer_change_the_verdict(self, label, fmt):
        """The classification asymmetry. Before the fix these row labels made
        a PDF reject a value taken straight out of its own table, because the
        label exempted it on one side of the comparison and not the other."""
        doc = D.parse(
            "# R\n\n## 1. Summary\n\nIntro.\n\n## 2. Results\n\n"
            f"| Descriptor | Value |\n| --- | --- |\n| {label} | {RAW} |\n",
            title="R")
        v = validate.validate(render.render(doc, fmt), fmt, doc)
        assert v.ok is True, (label, fmt, v.issues)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_and_an_invented_figure_is_still_caught_in_those_rows(self, fmt):
        doc = D.parse(
            "# R\n\n## 1. Summary\n\nIntro.\n\n## 2. Results\n\n"
            f"| Descriptor | Value |\n| --- | --- |\n| Note | {RAW} |\n",
            title="R")
        other = D.parse(
            "# R\n\n## 1. Summary\n\nIntro.\n\n## 2. Results\n\n"
            f"| Descriptor | Value |\n| --- | --- |\n| Note | {INVENTED} |\n",
            title="R")
        v = validate.validate(render.render(other, fmt), fmt, doc)
        assert v.ok is False and INVENTED in " ".join(v.issues)
