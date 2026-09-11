"""Structural numerals are not numeric claims. PB-015.

Written from the live failure, which rejected a generated report because the
rendered file "states figure(s) that are in no source: 10, 11, 13". Nothing in
the document claimed 10, 11 or 13. They were the tenth, eleventh and thirteenth
markers of a numbered recommendation list, which `pdf_writer` draws as literal
text (`f"{i}."`) and which the canonical `Document` does not store — the parser
keeps the item, not its ordinal. Markers 1 to 9 and 12 escaped only because
those digits happened to appear elsewhere in the prose.

The rule these tests pin: a numeral is exempt only when it occupies a
renderer-generated structural position AND the rest of its line is canonical
content of this very document. No value is ever exempt. Every test that accepts
a structural numeral has a sibling that rejects the same digits in a claim.
"""

from __future__ import annotations

from backend.playbook import document as D
from backend.playbook import render, validate

TITLE = "Committee report"


def parsed(markdown: str) -> D.Document:
    return D.parse(markdown, title=TITLE)


def rendered_figures(doc: D.Document, fmt: str = "pdf") -> validate.Validation:
    """Render, reopen with the real reader, and validate. No shortcuts."""
    return validate.validate(render.render(doc, fmt), fmt, doc)


def claims_in(text: str, doc: D.Document) -> set[str]:
    """The figures left once structural numerals are taken out."""
    stripped, _ = validate.structural_numerals(text, doc)
    return validate.figures(stripped)


# ============================================================ the live failure

class TestTheExactLiveFailure:
    """A thirteen-item numbered list whose prose carries 1-9 and 12."""

    def document(self) -> D.Document:
        items = "\n".join(
            f"{i}. Recommendation item {chr(96 + i)} for the committee to approve."
            for i in range(1, 14))
        return parsed(
            "## Executive summary\n\n"
            "The committee reviewed 3 portfolios over 12 months, with 4 "
            "scenarios, 5 obligor grades, 6 vintages, 7 model segments, 8 "
            "overlays, 9 controls and 2 challenger runs, plus 1 independent "
            "review.\n\n"
            f"## Recommendations\n\n{items}\n")

    def test_the_pdf_that_was_rejected_now_validates(self):
        v = rendered_figures(self.document(), "pdf")
        assert v.ok is True, v.issues

    def test_it_passes_because_the_markers_were_classified_not_tolerated(self):
        """The mechanism, not the outcome. A validator that stopped checking
        figures altogether would also make the assertion above pass."""
        v = rendered_figures(self.document(), "pdf")
        assert v.checked["structural_numerals"] >= 13

    def test_the_same_document_never_failed_as_docx(self):
        """Word writes ordinals as a list style and page numbers as fields, so
        only the PDF ever carried them as text. Pinned so the asymmetry cannot
        return unnoticed."""
        v = rendered_figures(self.document(), "docx")
        assert v.ok is True and v.checked["structural_numerals"] == 0

    def test_ten_eleven_and_thirteen_are_still_figures_in_prose(self):
        """The counter-test for the same three digits."""
        doc = self.document()
        assert claims_in("The book holds 10 accounts.", doc) == {"10"}
        assert claims_in("Stage 11 was reviewed.", doc) == {"11"}
        assert claims_in("Coverage moved 13 basis points.", doc) == {"13"}


# ======================================================== structural positions

class TestWhatCountsAsStructural:

    def test_a_numbered_heading_ordinal(self):
        doc = parsed("## 10. Conclusions\n\nThe position is noted.\n")
        text, removed = validate.structural_numerals(
            "10. Conclusions\nThe position is noted.", doc)
        assert removed == 1 and "10." not in text

    def test_a_numbered_recommendation(self):
        doc = parsed("## Recommendations\n\n11. Approve the revised limit.\n")
        assert claims_in("11. Approve the revised limit.", doc) == set()

    def test_a_page_number(self):
        doc = parsed("## Summary\n\nNothing numeric here.\n")
        assert claims_in("Page 13", doc) == set()
        assert claims_in("Page 13 of 20", doc) == set()

    def test_page_furniture_is_a_whole_line_or_it_is_prose(self):
        doc = parsed("## Summary\n\nNothing numeric here.\n")
        assert claims_in("Page 10 of the annex was reviewed.", doc) == {"10"}

    def test_a_long_list_item_wrapped_across_lines_keeps_its_marker_exempt(self):
        doc = parsed("## Recommendations\n\n"
                     "10. Approve the revised single-obligor limit framework "
                     "and instruct management to report back.\n")
        assert claims_in("10. Approve the revised single-obligor limit",
                         doc) == set()

    def test_an_ordinal_on_a_line_that_is_not_canonical_content_is_kept(self):
        """The conservative direction. If the line is not something this
        document says, nothing about it is structural."""
        doc = parsed("## Recommendations\n\n1. Approve the limit.\n")
        assert claims_in("1. Approve a facility of SAR 40 million.",
                         doc) == {"1", "40"}

    def test_a_bare_leading_figure_is_not_a_marker(self):
        """Punctuation is required. Otherwise a sentence opening with a number
        would have that number quietly removed."""
        doc = parsed("## Findings\n\n10 accounts breached the limit.\n")
        assert claims_in("10 accounts breached the limit.", doc) == {"10"}

    def test_a_bullet_confers_no_exemption(self):
        """Bullets have no ordinals, so no numeral can hide behind one."""
        doc = parsed("## Findings\n\n- 10 accounts breached the limit.\n")
        assert claims_in("• 10 accounts breached the limit.", doc) == {"10"}


# ========================================================= evidence-bearing

class TestWhatMustStillBeEvidenced:
    """Same shapes, same digits, in positions where they are claims."""

    def document(self) -> D.Document:
        return parsed("## 1. Summary\n\nThe portfolio was reviewed.\n")

    def test_currency(self):
        assert claims_in("Exposure of SAR 10 million was drawn.",
                         self.document()) == {"10"}

    def test_a_percentage(self):
        assert claims_in("Coverage stood at 10%.", self.document()) == {"10"}

    def test_basis_points(self):
        assert claims_in("The spread widened by 10 basis points.",
                         self.document()) == {"10"}

    def test_a_stage_label(self):
        assert claims_in("Stage 10 exposures were immaterial.",
                         self.document()) == {"10"}

    def test_a_count(self):
        assert claims_in("10 accounts migrated.", self.document()) == {"10"}

    def test_a_model_result(self):
        assert claims_in("The model returned 10.0.", self.document()) == {"10"}

    def test_a_structural_marker_does_not_launder_the_rest_of_its_line(self):
        """The case that would make the exemption worth abusing: a genuine
        marker in front of a fabricated figure."""
        doc = parsed("## Recommendations\n\n10. Approve the limit.\n")
        assert claims_in("10. Approve the limit of SAR 10 million.",
                         doc) == {"10"}

    def test_a_year_is_not_a_reported_figure(self):
        assert claims_in("The 2026 review cycle begins in June.",
                         self.document()) == set()

    def test_a_date_fragment_is_not_a_reported_figure_but_its_day_is(self):
        """30 June is a date; the check has never pretended otherwise for the
        year, and the day is a small integer the document itself states."""
        doc = parsed("## 1. Summary\n\nThe position is stated as at 30 June "
                     "2026.\n")
        v = rendered_figures(doc, "pdf")
        assert v.ok is True, v.issues


# ============================================================== end to end

class TestThroughTheRealRenderers:

    def test_page_furniture_on_a_long_pdf_with_no_numerals_in_prose(self):
        body = "\n\n".join(
            "A paragraph of committee prose carrying no numeral whatsoever."
            for _ in range(200))
        doc = parsed(f"## Long section\n\n{body}\n")
        v = rendered_figures(doc, "pdf")
        assert v.ok is True, v.issues
        assert v.checked["pages"] > 1

    def test_the_document_header_block_is_readable_content(self):
        """`meta` is rendered by every writer. A validator that could not see
        it rejected the reporting period as an unsourced figure."""
        doc = parsed("## Summary\n\nThe book performed as expected.\n")
        doc.meta = {"period": "H1 to 30 June", "exposures": "1,050 accounts",
                    "threshold": "10 bp"}
        for fmt in ("docx", "pdf"):
            v = rendered_figures(doc, fmt)
            assert v.ok is True, (fmt, v.issues)

    def test_a_rendered_file_stating_a_figure_the_document_does_not_fails(self):
        """The check this whole module must not have weakened."""
        stated = parsed("## 1. Summary\n\nCoverage is 41.9 per cent.\n")
        claimed = parsed("## 1. Summary\n\nCoverage is 41.3 per cent.\n")
        v = validate.validate(render.render(stated, "pdf"), "pdf", claimed)
        assert v.ok is False
        assert "41.9" in " ".join(v.issues)
