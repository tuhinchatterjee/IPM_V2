"""Phase 5, §13: three report families, one service, real Word documents.

Checked by OPENING the .docx and reading its headings, tables and text. §13
names the failure to avoid — downloading an HTML error page with a .docx
extension — so the tests also check that a report which cannot be built is
refused rather than produced.
"""
from __future__ import annotations

import io
import re

import docx
import pytest

from backend.retail import analysis_delinquency as AD
from backend.retail import analysis_traits as AT
from backend.retail import report_service as RS


@pytest.fixture(scope="module")
def investigation():
    analysis = AD.run(product="CREDIT_CARD",
                      question="what is the reason of this rise?")
    bundle = RS.investigation_bundle(
        analysis, prepared_by="tester",
        comments=[{"section": "Transition matrix", "author": "S. Nishtha",
                   "at": "2026-09-15", "assessment": "Concern",
                   "text": "Cures are holding; the driver is new arrears.",
                   "status": "Open"}],
        actions=[{"action": "Review collections capacity",
                  "owner": "Head of Collections", "due": "2026-10-15",
                  "status": "Proposed"}])
    payload, name = RS.render(RS.INVESTIGATION, bundle)
    return docx.Document(io.BytesIO(payload)), name, analysis, payload


@pytest.fixture(scope="module")
def traits():
    analysis = AT.run(question="Tell me what customer traits have "
                               "deteriorated and what is the impact on ECL "
                               "because of them.")
    bundle = RS.traits_bundle(analysis, prepared_by="tester")
    payload, name = RS.render(RS.TRAITS, bundle)
    return docx.Document(io.BytesIO(payload)), name, analysis, payload


def _headings(document):
    return [(int(p.style.name[-1]), p.text) for p in document.paragraphs
            if p.style.name.startswith("Heading") and p.text.strip()]


def _text(document):
    out = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            out += [cell.text for cell in row.cells]
    return "\n".join(out)


# ======================= the document furniture §13 asks for ===============

def test_rep_01_it_has_a_cover_and_document_control(investigation) -> None:
    document, _, _, _ = investigation
    headings = [text for _, text in _headings(document)]
    assert "Document control" in headings
    assert "Contents" in headings
    control = document.tables[0]
    fields = {row.cells[0].text for row in control.rows}
    for wanted in ("Report", "Scope", "Reporting month", "Population",
                   "Prepared at (UTC)", "Service version"):
        assert wanted in fields, wanted


def test_rep_02_section_numbers_are_contiguous(investigation) -> None:
    """The defect this guards: hand-written numbers drifted, so a contents
    page ran 5, 7, 9, 10, 12 — a document that looks like it lost six
    sections."""
    document, _, _, _ = investigation
    tops = [text for level, text in _headings(document)
            if level == 1 and re.match(r"^\d+\.", text)]
    numbers = [int(re.match(r"^(\d+)\.", one).group(1)) for one in tops]
    assert numbers == list(range(1, len(numbers) + 1)), numbers


def test_rep_03_a_subsection_carries_its_parents_number(investigation) -> None:
    document, _, _, _ = investigation
    for level, text in _headings(document):
        if level == 2 and re.match(r"^\d+\.\d+", text):
            parent = text.split(".")[0]
            assert parent.isdigit()


def test_rep_04_the_page_number_field_is_present(investigation) -> None:
    document, _, _, _ = investigation
    footer = document.sections[0].footer
    xml = footer.paragraphs[0]._p.xml
    assert "PAGE" in xml and "NUMPAGES" in xml


def test_rep_05_a_table_repeats_its_header_across_pages(investigation) -> None:
    document, _, _, _ = investigation
    long_tables = [t for t in document.tables if len(t.rows) > 8]
    assert long_tables, "no table long enough to span a page"
    for table in long_tables:
        assert "tblHeader" in table.rows[0]._tr.xml, (
            "a table that spans a page break does not repeat its heading")


# ===================== the investigation report's contents =================

def test_rep_06_it_carries_the_decomposition_not_a_summary(investigation
                                                           ) -> None:
    document, _, analysis, _ = investigation
    headings = " ".join(text for _, text in _headings(document)).lower()
    for wanted in ("attention issue", "findings", "trend",
                   "where facilities moved", "transition matrix",
                   "how that moved the rate", "flows behind the numerator",
                   "where the change sits", "loss allowance",
                   "what improved", "customers carrying"):
        assert wanted in headings, wanted


def test_rep_07_the_figures_are_the_analysis_figures(investigation) -> None:
    document, _, analysis, _ = investigation
    text = _text(document)
    bridge = analysis["rate_bridge"]
    assert f"{bridge['closing']['rate_pct']:.2f}%" in text
    assert f"{bridge['change_pp']:+}" in text
    flows = {one["flow"]: one for one in bridge["numerator_flows"]}
    assert f"{flows['New arrears']['facilities']:,}" in text


def test_rep_08_both_weightings_are_stated(investigation) -> None:
    document, _, analysis, _ = investigation
    text = _text(document)
    assert "By account count" in text or "by account" in text.lower()
    assert "exposure-weighted" in text.lower()


def test_rep_09_the_offsets_are_reported(investigation) -> None:
    document, _, analysis, _ = investigation
    text = _text(document)
    assert "Cures" in text
    assert f"{analysis['offsets']['cured_facilities']:,}" in text


def test_rep_10_a_pd_change_is_not_offered_as_a_reason(investigation) -> None:
    document, _, _, _ = investigation
    assert "cannot be a reason" in _text(document)


# ===================== the trait report's contents ========================

def test_rep_11_the_whole_inventory_is_in_the_document(traits) -> None:
    """§7.1: a shortlist hides the variables that did not move."""
    document, _, analysis, _ = traits
    rows = max(len(t.rows) - 1 for t in document.tables)
    assert rows == len(analysis["inventory"]), (
        f"{rows} rows for {len(analysis['inventory'])} inputs")
    assert rows > 100


def test_rep_12_origination_inputs_are_labelled_historical(traits) -> None:
    document, _, _, _ = traits
    assert "historical or fixed at origination" in _text(document)


def test_rep_13_the_periods_are_named(traits) -> None:
    document, _, analysis, _ = traits
    text = _text(document)
    assert analysis["periods"]["current"]["label"] in text
    assert analysis["periods"]["prior"]["label"] in text


def test_rep_14_matched_and_mix_are_separated(traits) -> None:
    document, _, _, _ = traits
    text = _text(document).lower()
    assert "matched facilities" in text
    assert "entered the book" in text and "left the book" in text


# ============== comments, actions and the honesty requirements ============

def test_rep_15_an_analyst_comment_survives_into_the_document(investigation
                                                              ) -> None:
    document, _, _, _ = investigation
    text = _text(document)
    assert "Cures are holding; the driver is new arrears." in text
    assert "S. Nishtha" in text


def test_rep_16_a_proposed_action_carries_its_owner_and_date(investigation
                                                             ) -> None:
    text = _text(investigation[0])
    assert "Head of Collections" in text and "2026-10-15" in text


def test_rep_17_the_disclosure_is_said_once_not_on_every_page(investigation
                                                              ) -> None:
    """§13: "not repeat disclaimers on every page"."""
    text = _text(investigation[0])
    assert "Synthetic" in text
    assert text.count("No credit decision should rest on it.") == 1


def test_rep_18_it_claims_nothing_it_cannot_support(investigation) -> None:
    text = _text(investigation[0]).lower()
    for forbidden in ("approved by sama", "sama approval", "anb approved",
                      "independently validated", "auditor certified"):
        claimed = re.search(rf"(?<!not )(?<!not been ){re.escape(forbidden)}",
                            text)
        assert claimed is None, (
            f"claims {forbidden!r}: "
            f"…{text[max(0, claimed.start() - 60):claimed.end() + 20]}…")


def test_rep_19_a_historical_bundle_is_badged(investigation) -> None:
    _, _, analysis, _ = investigation
    bundle = RS.investigation_bundle(analysis)
    bundle.historical = True
    bundle.as_of = "2026-02"
    document = docx.Document(io.BytesIO(RS.write_investigation(bundle)))
    assert "HISTORICAL" in _text(document)
    assert "2026-02" in _text(document)


# ================= the download path refuses rather than lies =============

def test_rep_20_an_unavailable_analysis_raises(investigation) -> None:
    bundle = RS.investigation_bundle({"available": False,
                                      "because": "nothing to report"})
    with pytest.raises(RS.ReportUnavailable, match="nothing to report"):
        RS.write_investigation(bundle)


def test_rep_21_an_unknown_family_raises(investigation) -> None:
    _, _, analysis, _ = investigation
    with pytest.raises(RS.ReportUnavailable, match="not a report"):
        RS.render("something_else", RS.investigation_bundle(analysis))


def test_rep_22_the_filename_names_the_family_and_scope(investigation,
                                                        traits) -> None:
    assert investigation[1].startswith("investigation_")
    assert "Credit_Card" in investigation[1]
    assert investigation[1].endswith(".docx")
    assert traits[1].startswith("trait_attribution_")


def test_rep_23_the_bytes_really_are_a_word_document(investigation) -> None:
    payload = investigation[3]
    assert payload[:2] == b"PK", "not a zip, so not a .docx"
    import zipfile

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert "word/document.xml" in archive.namelist()
        assert b"<html" not in archive.read("word/document.xml")[:400].lower()
