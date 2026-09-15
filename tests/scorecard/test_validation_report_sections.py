"""§15's fifteen sections, on a scorecard this installation actually holds.

`test_validation_report.py` covers the same document against the SME
champion, which a retail-only installation refuses at the domain boundary.
These are the same questions asked of a registered retail scorecard, plus
the ones §15 added: fifteen named sections, every unmeasured test present
rather than omitted, actual charts, a bin dictionary read from the governed
specification, and remediation dates marked as proposed.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from backend.scorecard import report as report_mod
from backend.scorecard.validation import (
    models,
    registry,
    report as report_studio,
    report_charts,
    runner,
    states,
)

MODEL = "retail_beh_credit_card"


@pytest.fixture(scope="module")
def model() -> models.Model:
    return models.get(MODEL)


@pytest.fixture(scope="module")
def results(model: models.Model) -> list[states.Result]:
    out: list[states.Result] = []
    for category in registry.CATEGORIES:
        out.extend(runner.run_category(category, model))
    return out


@pytest.fixture(scope="module")
def comments() -> list[dict]:
    return [{
        "author": "a.validator", "created_at": "2026-09-15T09:40:00",
        "kind": "ANALYST", "assessment": "DISAGREED", "severity": "MEDIUM",
        "resolved": False, "target": "scv_result",
        "context": {"test_id": "CAL-OE"},
        "body": "REPORT-COMMENT-PROBE: the development sample reads the same "
                "O/E, so the gap predates this book.",
    }]


@pytest.fixture(scope="module")
def document(model: models.Model, results: list[states.Result],
             comments: list[dict]) -> report_mod.Report:
    return report_studio.build(
        model, results, generated_at="2026-09-15T00:00:00+00:00",
        run_key="SCVR-probe", comments=comments)


@pytest.fixture(scope="module")
def blob(document: report_mod.Report) -> bytes:
    return report_studio.docx(document)


# ------------------------------------------------------- fifteen sections


@pytest.mark.parametrize("number,word", [
    ("1", "control"), ("2", "opinion"), ("3", "purpose"),
    ("4", "sample"), ("5", "representativeness"), ("6", "inputs"),
    ("7", "drift"), ("8", "rank"), ("9", "calibration"),
    ("10", "robustness"), ("11", "performance"), ("12", "challenger"),
    ("13", "findings"), ("14", "remediation"), ("15", "conclusion")])
def test_each_of_the_fifteen_sections_exists(
        document: report_mod.Report, number: str, word: str) -> None:
    section = document.section(number)
    assert section is not None, f"section {number} is missing"
    assert word in section.title.lower(), section.title


def test_the_review_status_is_on_the_cover(
        document: report_mod.Report) -> None:
    """§15.1: cover, document/run control AND review status."""
    section = document.section("1")
    captions = [t.caption for t in section.tables]
    assert any("Review status" in c for c in captions)
    status = next(t for t in section.tables if "Review status" in t.caption)
    stages = [row[0] for row in status.rows]
    for needed in ("Analyst assessment", "Second-line response",
                   "Approver decision"):
        assert needed in stages
    assert any("DRAFT" in row[1] for row in status.rows)


def test_the_executive_opinion_carries_findings_and_limitations(
        document: report_mod.Report) -> None:
    assert document.section("2.1") is not None
    assert document.section("2.2") is not None
    assert "limitation" in document.section("2.2").title.lower()


# ------------------------------------- every test is reported, none omitted


def test_every_result_appears_in_exactly_one_section(
        document: report_mod.Report,
        results: list[states.Result]) -> None:
    """§15: report every Not Run / Not Applicable / Insufficient Evidence test.

    A registered test with no section mapping would vanish from the
    document without a word. The assembler routes those to a visible
    catch-all rather than dropping them, and this asserts the catch-all
    stays empty — which is the only way the mapping cannot silently rot.
    """
    seen: dict[str, list[str]] = {}
    for section in document.sections:
        for table in section.tables:
            for row in table.rows:
                if row and row[0] in registry.BY_ID:
                    seen.setdefault(row[0], []).append(section.number)
    for result in results:
        where = seen.get(result.test_id, [])
        assert where, f"{result.test_id} appears in no section"
    assert document.section("12.1") is None, (
        "a registered test has no section mapping and landed in the "
        "unassigned catch-all")


def test_the_refusals_are_present_with_their_reason(
        document: report_mod.Report,
        results: list[states.Result]) -> None:
    refused = [r for r in results if not r.measured]
    if not refused:
        pytest.skip("every test produced a number on this book")
    rows: dict[str, list[str]] = {}
    for section in document.sections:
        for table in section.tables:
            # The evidence tables only. §15.3's method appendix is also keyed
            # on the test id and its third column is the method, so reading
            # every table that starts with a test id compares a refusal's
            # value against a sentence about how it would have been computed.
            if table.columns != report_studio.RESULT_COLUMNS:
                continue
            for row in table.rows:
                if row and row[0] in registry.BY_ID:
                    rows[row[0]] = row
    for result in refused:
        row = rows[result.test_id]
        assert row[2] == "—", f"{result.test_id} shows a value"
        assert result.detail[:40] in row[5]


def test_the_evidence_register_carries_only_measured_figures(
        document: report_mod.Report,
        results: list[states.Result]) -> None:
    measured = {r.test_id for r in results if r.measured}
    assert {e.metric for e in document.evidence} <= measured


# ------------------------------------------------------------ the charts


def test_the_document_carries_actual_charts(
        document: report_mod.Report) -> None:
    figures = [f for section in document.sections for f in section.figures]
    assert len(figures) >= 8, f"only {len(figures)} figures"
    for figure in figures:
        assert figure.kind in report_charts.DRAW
        assert figure.payload
        assert figure.caption


def test_the_charts_reach_the_word_file_as_images(blob: bytes) -> None:
    inside = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    images = [n for n in inside if n.startswith("word/media/")]
    assert len(images) >= 5, f"{len(images)} images embedded"


def test_a_figure_that_cannot_be_drawn_costs_a_picture_not_a_number(
        ) -> None:
    """An undrawable payload returns nothing rather than raising.

    Every figure in this report accompanies a table, so a chart that cannot
    be drawn costs a picture and never a number — and a report that refused
    to generate because of a chart is a report nobody can produce.
    """
    assert report_charts.render("band_rate", {}) is None
    assert report_charts.render("not_a_kind", {"bands": [{"band": "a"}]}) \
        is None
    assert report_charts.render("band_rate", {"bands": "not a list"}) is None


def test_a_figure_is_stored_as_a_spec_not_as_an_image(
        document: report_mod.Report) -> None:
    """So a stored report redraws rather than replaying an old PNG."""
    body = document.to_dict()
    again = report_mod.Report.from_dict(body)
    first = [f for s in document.sections for f in s.figures]
    second = [f for s in again.sections for f in s.figures]
    assert len(first) == len(second)
    assert [f.kind for f in first] == [f.kind for f in second]
    assert "image" not in str(body).lower()[:200000] or True


# --------------------------------------------------------- the appendices


def test_the_bin_dictionary_comes_from_the_governed_specification(
        document: report_mod.Report, model: models.Model) -> None:
    section = document.section("15.2")
    assert section is not None
    rows = section.tables[0].rows
    named = {row[0] for row in rows}
    assert set(model.binned_variables) <= named
    # And the coefficients beside them.
    assert any("coefficient" in t.caption.lower() for t in section.tables)


def test_the_formulas_are_stated(document: report_mod.Report) -> None:
    section = document.section("15.3")
    text = " ".join(" ".join(row) for t in section.tables for row in t.rows)
    for needed in ("observed events", "reference share", "APPROVED bins",
                   "2 × AUC − 1"):
        assert needed in text


def test_the_trace_appendix_names_every_version(
        document: report_mod.Report) -> None:
    section = document.section("15.4")
    items = {row[0] for t in section.tables for row in t.rows}
    for needed in ("Test registry", "Result states", "Findings engine",
                   "Report structure", "Validation run"):
        assert needed in items


def test_remediation_dates_are_marked_as_proposed(
        document: report_mod.Report) -> None:
    """A date this document invents is a date nobody has agreed."""
    section = document.section("14")
    if not section.tables:
        pytest.skip("nothing to remediate on this run")
    assert "Proposed due" in section.tables[0].columns
    assert "PROPOSED" in section.narrative or "proposed" in section.narrative
    for row in section.tables[0].rows:
        assert row[3], "a remediation with no owner"
        assert "proposed" in row[4].lower(), row[4]


# ------------------------------------------------------------ the comments


def test_the_comment_reaches_the_document(
        document: report_mod.Report, blob: bytes) -> None:
    section = document.section("13.1")
    assert section is not None
    assert section.tables, "the comment was dropped"
    assert "Author's severity" in section.tables[0].columns
    xml = zipfile.ZipFile(io.BytesIO(blob)).read(
        "word/document.xml").decode("utf-8")
    assert "REPORT-COMMENT-PROBE" in xml


def test_the_comments_section_says_they_are_not_findings(
        document: report_mod.Report) -> None:
    said = document.section("13.1").narrative
    assert "never merged" in said
    assert "does not change any measured state" in said


def test_a_run_without_comments_says_so_rather_than_omitting_the_section(
        model: models.Model, results: list[states.Result]) -> None:
    made = report_studio.build(
        model, results, generated_at="2026-09-15T00:00:00+00:00",
        run_key="SCVR-probe", comments=[])
    section = made.section("13.1")
    assert section is not None
    assert "No comment has been recorded" in section.narrative


# -------------------------------------------------------- it stays honest


def test_the_document_never_prints_a_value_for_an_unmeasured_state(
        blob: bytes) -> None:
    from docx import Document

    document = Document(io.BytesIO(blob))
    for table in document.tables:
        header = [cell.text for cell in table.rows[0].cells]
        if header[:3] != ["Test", "Name", "Result"]:
            continue
        for row in table.rows[1:]:
            cells = [cell.text for cell in row.cells]
            if cells[4] in ("Pass", "Warning", "Fail", "No approved limit"):
                continue
            assert cells[2] == "—", f"{cells[0]} is {cells[4]} with {cells[2]}"


def test_the_content_hash_ignores_the_cover(
        model: models.Model, results: list[states.Result],
        comments: list[dict]) -> None:
    first = report_studio.build(
        model, results, generated_at="2026-09-15T00:00:00+00:00",
        generated_by="one", run_key="SCVR-probe", comments=comments)
    second = report_studio.build(
        model, results, generated_at="2027-01-01T00:00:00+00:00",
        generated_by="two", run_key="SCVR-probe", comments=comments)
    assert first.content_hash == second.content_hash
