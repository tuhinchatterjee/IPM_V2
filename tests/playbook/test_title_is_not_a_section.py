"""A document's title is a title, not a missing section. PB-020, PB-041.

From human UAT. A real Auto Loan scorecard report was generated, rendered and
then refused:

    The generated files did not pass validation, so nothing was saved.
    1 section(s) are missing from the rendered file:
    Auto Loan Application Scorecard (AL-AS-v1.0) — Model Development and
    Validation Report

That string is the document's title. Two independent defects put it there.

*The title was in the canonical model twice.* `parse` is given a title — the
artifact's label — and the author writes the report's own title as an H1. When
the two differed word for word, the H1 fell through and became an ordinary,
empty Section, so the document carried its title as `Document.title` AND as a
section. Every writer rendered both, and the validator, which compares
canonical sections against the rendered file, looked for a chapter that was
never meant to exist.

*And a long heading wraps.* reportlab breaks a long heading across lines, so
the PDF text layer holds "…Model Development\\nand Validation Report". The
validator's presence test was a raw substring match, which cannot see across
that break — so ANY section heading long enough to wrap was reported missing.
That is why the DOCX passed and the PDF failed on the same document, and it
would have rejected a genuine section just as readily as a title.

Both are fixed at their own boundary: the title is folded back into
`Document.title` by `parse`, and the validator checks the title as a title
with its own diagnostic while comparing whitespace-flattened text.
"""

from __future__ import annotations

import pytest

from backend.playbook import document as D
from backend.playbook import render, validate

#: The exact title from the UAT run, em dash, parentheses, version and all.
TITLE = ("Auto Loan Application Scorecard (AL-AS-v1.0) — "
         "Model Development and Validation Report")

#: The artifact label the workspace carried, which does not match it.
LABEL = "Auto Loan Application Scorecard Model Development Report"

#: A heading long enough that reportlab wraps it. Substantive, not a title.
LONG_HEADING = ("7. Independent Validation of Calibration Stability and "
                "Downturn Sensitivity Across Segments")

REPORT_MD = f"""# {TITLE}

## 1. Executive summary

The scorecard was redeveloped on the attached population.

## 2. Data and population

Records were drawn from the application system.

## 3. Methodology

Weight-of-evidence binning followed by logistic regression.

## 4. Results

| Segment | Gini |
| --- | --- |
| New | 0.62 |
| Used | 0.58 |

## 5. Limitations

Behavioural data was out of scope.

## 6. Conclusions and recommendations

- Approve the scorecard for implementation
- Review after two quarters

## {LONG_HEADING}

Calibration held across both segments.
"""

FORMATS = ("docx", "pdf")


@pytest.fixture
def report() -> D.Document:
    """Parsed exactly as `author_document` parses a model reply: with the
    artifact's label supplied, which the author did not match."""
    return D.parse(REPORT_MD, title=LABEL)


def checked(doc: D.Document, fmt: str) -> validate.Validation:
    return validate.validate(render.render(doc, fmt), fmt, doc)


# ============================================ the canonical boundary

class TestTheTitleIsRepresentedOnce:

    def test_the_title_is_the_documents_own_wording(self, report):
        assert report.title == TITLE

    def test_the_title_is_not_also_a_section(self, report):
        assert TITLE not in [s.heading for s in report.sections]

    def test_the_substantive_sections_are_all_there(self, report):
        assert [s.heading for s in report.sections] == [
            "1. Executive summary", "2. Data and population",
            "3. Methodology", "4. Results", "5. Limitations",
            "6. Conclusions and recommendations", LONG_HEADING]

    def test_no_section_was_swallowed_with_the_title(self, report):
        """The fold only takes a first heading with no content of its own."""
        assert all(s.blocks for s in report.sections)

    def test_a_first_heading_that_has_content_stays_a_section(self):
        """An author who uses H1 for real sections keeps them. This is the
        case the fold must never take."""
        doc = D.parse("# 1. Executive summary\n\nThe position is stated.\n"
                      "\n# 2. Methodology\n\nLogistic regression.\n",
                      title=LABEL)
        assert [s.heading for s in doc.sections] == ["1. Executive summary",
                                                     "2. Methodology"]
        assert doc.title == LABEL

    def test_a_single_section_document_is_left_alone(self):
        """Nothing follows it, so it is not a title line."""
        doc = D.parse("# Findings\n", title=LABEL)
        assert [s.heading for s in doc.sections] == ["Findings"]

    def test_a_matching_title_behaves_the_same_way(self):
        doc = D.parse(f"# {LABEL}\n\n## 1. Summary\n\nText.\n", title=LABEL)
        assert doc.title == LABEL and len(doc.sections) == 1


# ============================================ render, parse back, validate

class TestTheRenderedFilePasses:

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_report_that_was_refused_now_validates(self, report, fmt):
        v = checked(report, fmt)
        assert v.ok is True, v.issues

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_title_is_present_and_correct(self, report, fmt):
        v = checked(report, fmt)
        assert v.checked["title_expected"] == TITLE
        assert validate._flat(TITLE) in validate._flat(
            _rendered_text(report, fmt))

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_every_substantive_section_is_present(self, report, fmt):
        v = checked(report, fmt)
        assert v.checked["sections_found"] == v.checked["sections_expected"] == 7

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_a_heading_long_enough_to_wrap_is_found(self, report, fmt):
        """The defect that made the PDF fail where the DOCX passed. Asserted
        on an ordinary section, because it was never about the title."""
        assert LONG_HEADING in [s.heading for s in report.sections]
        assert checked(report, fmt).ok is True


# ============================================ the checks must still bite

class TestWhatMustStillFail:

    @pytest.mark.parametrize("fmt", FORMATS)
    @pytest.mark.parametrize("dropped", [
        "3. Methodology", "4. Results", "5. Limitations",
        "6. Conclusions and recommendations"])
    def test_a_missing_substantive_section_fails(self, report, fmt, dropped):
        """Rendered without the section, validated against a document that
        still has it — a genuinely missing chapter."""
        rendered = D.Document.from_dict(report.as_dict())
        rendered.sections = [s for s in rendered.sections
                             if s.heading != dropped]
        content = render.render(rendered, fmt)

        v = validate.validate(content, fmt, report)
        assert v.ok is False
        assert "section(s) are missing" in " ".join(v.issues)
        assert dropped in " ".join(v.issues)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_a_wrong_title_fails_with_a_title_diagnostic(self, report, fmt):
        content = render.render(report, fmt)
        expected = D.Document.from_dict(report.as_dict())
        expected.title = "Personal Loan Behavioural Scorecard Review"

        v = validate.validate(content, fmt, expected)
        assert v.ok is False
        joined = " ".join(v.issues)
        assert "title" in joined
        assert "section(s) are missing" not in joined

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_a_missing_title_fails_with_a_title_diagnostic(self, report, fmt):
        untitled = D.Document.from_dict(report.as_dict())
        untitled.title = ""
        content = render.render(untitled, fmt)

        v = validate.validate(content, fmt, report)
        assert v.ok is False
        joined = " ".join(v.issues)
        assert "title" in joined and "section(s) are missing" not in joined

    def test_an_invented_figure_is_still_refused(self, report):
        """The other half of validation is untouched by any of this."""
        rendered = D.Document.from_dict(report.as_dict())
        rendered.sections[0].blocks[0].text = "Gini reached 0.91."
        v = validate.validate(render.render(rendered, "docx"), "docx", report)
        assert v.ok is False
        assert "0.91" in " ".join(v.issues)


# ============================================ normalisation, and its limits

class TestOnlyWhitespaceIsNormalised:
    """Structural representation differences are absorbed. Nothing else is."""

    def test_a_wrapped_line_matches_the_unwrapped_heading(self):
        assert validate._flat("Model Development\nand Validation") == \
            validate._flat("Model Development and Validation")

    def test_repeated_spaces_and_tabs_match(self):
        assert validate._flat("A  B\tC") == validate._flat("A B C")

    def test_case_matches_because_word_title_style_may_restyle_it(self):
        assert validate._flat("Executive Summary") == \
            validate._flat("EXECUTIVE SUMMARY")

    def test_an_em_dash_is_not_a_hyphen(self):
        """No punctuation tolerance. The writers preserve the em dash exactly,
        verified below, so accepting a hyphen for it would be fuzziness with
        nothing to justify it."""
        assert validate._flat("Model — Report") != validate._flat(
            "Model - Report")

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_em_dash_survives_rendering_and_parse_back(self, report, fmt):
        assert "—" in _rendered_text(report, fmt)

    def test_a_changed_word_is_not_absorbed(self):
        assert validate._flat("Validation Report") != validate._flat(
            "Verification Report")

    def test_a_changed_digit_is_not_absorbed(self):
        assert validate._flat("(AL-AS-v1.0)") != validate._flat("(AL-AS-v2.0)")


def _rendered_text(doc: D.Document, fmt: str) -> str:
    """What the real reader gets back out of the real file."""
    from backend.playbook.ingest import docx_reader, pdf_reader

    content = render.render(doc, fmt)
    if fmt == "docx":
        return "\n".join(c.text for c in docx_reader.read(content).chunks)
    return "\n".join(c.text for c in pdf_reader.read(content).chunks
                     if c.kind == "page")
