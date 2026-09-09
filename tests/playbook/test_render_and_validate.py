"""Rendering real files and opening them again. PB-019, PB-020, PB-021, PB-041.

Every test here renders bytes, then reads those bytes back with the same
parsers Playbook uses on user uploads. Nothing asserts on the renderer's own
report of what it did — a writer that believes it wrote a table is exactly the
witness not to trust.
"""

from __future__ import annotations

import pytest

from backend.playbook import capabilities, render, validate
from backend.playbook import document as D
from backend.playbook.fixtures import ecl_oracle as oracle


@pytest.fixture
def report() -> D.Document:
    """A small committee report whose figures all come from the oracle."""
    head = oracle.headline()
    current = head["weighted_ecl_current"].rounded
    prior = head["weighted_ecl_prior"].rounded
    move = head["weighted_ecl_movement"].rounded
    pct = head["weighted_ecl_percent_change"].rounded
    cov = head["coverage_current"].rounded

    md = f"""# IFRS 9 Committee Report — Q2 2026

## 1. Executive summary

Weighted ECL rose to SAR {current} million from SAR {prior} million, an increase
of SAR {move} million or {pct} per cent. Coverage stood at {cov} per cent
[[fixture://playbook-ecl-oracle@1.0.0#weighted_ecl.current]].

## 2. Scenario results

| Scenario | ECL, SAR million |
| --- | --- |
| Base | 19.20 |
| Upturn | 15.00 |
| Downturn | 36.00 |

- Scenario weights were unchanged
- Ordering remains economically coherent

## 3. Limitations

Post-model adjustments are outside the scope of this report.
"""
    doc = D.parse(md)
    doc.subtitle = "Prepared for the Credit Risk Committee"
    doc.meta = {"reporting_period": "Q2 2026", "currency": "SAR million"}
    return doc


class TestEveryFormatIsRealAndReopens:
    @pytest.mark.parametrize("fmt", ["docx", "pdf", "pptx", "xlsx"])
    def test_the_bytes_are_a_real_file_of_that_type(self, report, fmt):
        content = render.render(report, fmt)
        assert len(content) > 1000, "a few hundred bytes is not a document"
        if fmt == "pdf":
            assert content.startswith(b"%PDF-")
        else:
            assert content[:4] == b"PK\x03\x04"

    @pytest.mark.parametrize("fmt", ["docx", "pdf", "pptx", "xlsx"])
    def test_it_passes_its_own_validation(self, report, fmt):
        content = render.render(report, fmt)
        result = validate.validate(content, fmt, report)
        assert result.ok, result.issues

    def test_word_keeps_the_sections_and_the_table(self, report):
        content = render.render(report, "docx")
        result = validate.validate(content, "docx", report)
        assert result.checked["sections_found"] == result.checked["sections_expected"]
        assert result.checked["tables"] >= 1

    def test_the_pdf_has_pages(self, report):
        result = validate.validate(render.render(report, "pdf"), "pdf", report)
        assert result.checked["pages"] >= 1

    def test_the_deck_is_editable_text_not_pictures(self, report):
        from backend.playbook.ingest import pptx_reader

        content = render.render(report, "pptx")
        read = pptx_reader.read(content, filename="d.pptx")
        slides = [c for c in read.chunks if c.kind == "slide"]
        assert len(slides) >= 3
        assert any(c.kind == "table" for c in read.chunks), (
            "the deck must carry a native PowerPoint table, not an image of one"
        )
        assert all("picture" not in w for w in read.manifest.warnings)

    def test_the_workbook_carries_the_report_tables(self, report):
        from backend.playbook.ingest import sheets

        content = render.render(report, "xlsx")
        read = sheets.read(content, filename="w.xlsx", kind="xlsx")
        names = {c.data.get("sheet") for c in read.chunks}
        assert "CONTENTS" in names
        assert any(n not in {"CONTENTS", "SOURCES"} for n in names)


class TestWordAndPdfCarryTheSameFacts:
    def test_both_state_every_headline_figure(self, report):
        from backend.playbook.ingest import docx_reader, pdf_reader

        docx_text = " ".join(
            c.text + " " + " ".join(str(x) for row in c.data.get("rows", [])
                                    for x in row)
            for c in docx_reader.read(render.render(report, "docx")).chunks
        )
        pdf_text = " ".join(
            c.text for c in pdf_reader.read(render.render(report, "pdf")).chunks
        )
        for figure in ("22.77", "20.90", "1.87", "8.95"):
            assert figure in docx_text, f"{figure} missing from the Word file"
            assert figure in pdf_text, f"{figure} missing from the PDF"

    def test_the_formats_are_rendered_from_one_document(self, report):
        results = validate.validate_all(
            {fmt: render.render(report, fmt) for fmt in ("docx", "pdf", "xlsx")},
            report,
        )
        assert validate.consistent(results) == []


class TestValidationRefusesWhatItShould:
    def test_an_invented_figure_fails_validation(self, report):
        """The check that matters: a rendered file may not state a number that
        is in no source."""
        tampered = D.Document.from_dict(report.as_dict())
        tampered.sections[0].blocks[0].text += " Coverage reached 41.5 per cent."
        content = render.render(tampered, "docx")
        # Validated against the ORIGINAL document, so 41.5 is unsupported.
        result = validate.validate(content, "docx", report)
        assert result.ok is False
        assert any("41.5" in issue for issue in result.issues)

    def test_a_missing_section_fails_validation(self, report):
        shortened = D.Document.from_dict(report.as_dict())
        shortened.sections = shortened.sections[:1]
        content = render.render(shortened, "docx")
        result = validate.validate(content, "docx", report)
        assert result.ok is False
        assert any("missing" in issue for issue in result.issues)

    def test_a_file_that_is_not_a_document_fails_rather_than_crashing(self, report):
        result = validate.validate(b"not a document at all", "docx", report)
        assert result.ok is False
        assert any("could not be reopened" in i for i in result.issues)


class TestTheCapabilityRegistryIsTruthful:
    def test_every_supported_format_actually_renders(self, report):
        for fmt in capabilities.SUPPORTED:
            assert render.render(report, fmt)

    def test_an_unsupported_format_is_refused_with_what_is_available(self):
        with pytest.raises(capabilities.UnsupportedFormat, match=r"\.docx"):
            capabilities.require("odt")

    def test_the_refusal_names_the_format_that_was_asked_for(self):
        with pytest.raises(capabilities.UnsupportedFormat, match="rtf"):
            capabilities.require("rtf")
