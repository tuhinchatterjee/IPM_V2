"""A scoped edit is scoped by construction. PB-017.

Written from the live failure: version 2 came back carrying a figure that was
in no evidence, and the check could say only "v1 intact, v2 written". The prompt
had asked for everything outside the scope to come back byte-for-byte unchanged.
Asking is not enforcing.
"""

from __future__ import annotations

import pytest

from backend.playbook import document as D
from backend.playbook import merge

BASE_MD = """# IFRS 9 Committee Report

## 1. Executive summary

Weighted ECL rose to SAR 22.77 million, an increase of 8.95 per cent.

## 2. Scenario results

| Scenario | ECL |
| --- | --- |
| Base | 19.20 |

## 3. Limitations

Post-model adjustments are outside scope.
"""


TITLE = "IFRS 9 Committee Report"


def parsed(markdown: str) -> D.Document:
    """Every fixture through one parse, so a difference in the test setup can
    never be mistaken for a difference the merge produced.

    Note the parser emits an empty leading section for the H1 title; parsing
    both sides the same way is what keeps that out of the comparisons.
    """
    return D.parse(markdown, title=TITLE)


def base() -> D.Document:
    return parsed(BASE_MD)


class TestOnlyTheRequestedSectionIsTaken:
    def test_the_target_section_comes_from_the_draft(self):
        drafted = parsed(BASE_MD.replace(
            "Weighted ECL rose to SAR 22.77 million, an increase of 8.95 per cent.",
            "ECL rose to SAR 22.77 million, up 8.95 per cent."))
        result = merge.scoped_merge(base(), drafted, "the executive summary")

        summary = result.document.section("1. Executive summary")
        assert "up 8.95 per cent" in summary.text
        assert result.target == "1. Executive summary"

    def test_an_unrelated_section_the_model_rewrote_is_discarded(self):
        """The live shape: the model paraphrases a section nobody asked about."""
        drafted = parsed(BASE_MD.replace(
            "Post-model adjustments are outside scope.",
            "Post-model adjustments fall outside the scope of this paper."))
        result = merge.scoped_merge(base(), drafted, "the executive summary")

        limitations = result.document.section("3. Limitations")
        assert limitations.text == "Post-model adjustments are outside scope."
        assert result.rejected == ["3. Limitations"]
        assert "without being asked" in result.note()

    def test_a_figure_invented_outside_the_scope_never_enters_the_document(self):
        """It is not removed by grounding — it never arrives."""
        drafted = parsed(BASE_MD.replace(
            "Post-model adjustments are outside scope.",
            "Post-model adjustments of SAR 4.10 million are outside scope."))
        result = merge.scoped_merge(base(), drafted, "the executive summary")
        assert "4.10" not in result.document.plain_text()

    def test_a_section_the_model_added_is_refused(self):
        drafted = parsed(BASE_MD + "\n## 4. Recommendations\n\nApprove it.\n")
        result = merge.scoped_merge(base(), drafted, "the executive summary")
        assert result.added == ["4. Recommendations"]
        assert result.document.section("4. Recommendations") is None
        assert "added" in result.note()

    def test_a_section_the_model_dropped_is_kept(self):
        drafted = parsed(BASE_MD.split("## 3. Limitations")[0])
        result = merge.scoped_merge(base(), drafted, "the executive summary")
        assert result.dropped == ["3. Limitations"]
        assert result.document.section("3. Limitations") is not None

    def test_a_well_behaved_revision_reports_no_drift(self):
        drafted = parsed(BASE_MD.replace(
            "Weighted ECL rose to SAR 22.77 million",
            "Weighted ECL reached SAR 22.77 million"))
        result = merge.scoped_merge(base(), drafted, "the executive summary")
        assert result.drifted is False
        assert result.note() == ""

    def test_the_scope_is_matched_the_way_people_name_sections(self):
        """"the executive summary" has to find "1. Executive summary"."""
        drafted = parsed(BASE_MD)
        for named in ("the executive summary", "Executive summary",
                      "1. Executive summary"):
            assert merge.scoped_merge(base(), drafted, named).target == \
                "1. Executive summary"

    def test_retitling_the_target_is_inside_the_scope_of_editing_it(self):
        drafted = parsed(BASE_MD.replace("## 1. Executive summary",
                                          "## 1. Summary for the committee"))
        result = merge.scoped_merge(base(), drafted, "the executive summary")
        headings = [s.heading for s in result.document.sections]
        assert "1. Summary for the committee" in headings
        assert "1. Executive summary" not in headings


class TestARefusalIsBetterThanASilentNoOp:
    def test_a_scope_that_is_in_no_section_is_refused(self):
        with pytest.raises(merge.ScopeNotFound) as exc:
            merge.scoped_merge(base(), parsed(BASE_MD), "the appendix")
        assert "nothing to revise" in str(exc.value)

    def test_a_draft_missing_the_target_section_is_refused(self):
        """Editing nothing and reporting success is the worst outcome: the user
        believes their change was made."""
        drafted = parsed(
            "# IFRS 9 Committee Report\n\n## 3. Limitations\n\nUnchanged.\n")
        with pytest.raises(merge.ScopeNotFound) as exc:
            merge.scoped_merge(base(), drafted, "the executive summary")
        assert "did not contain" in str(exc.value)


class TestTheInvariantTheLiveCheckAsserts:
    def test_unchanged_outside_is_empty_after_a_merge(self):
        drafted = parsed(BASE_MD.replace(
            "Post-model adjustments are outside scope.",
            "Something else entirely, with SAR 9.99 million in it."))
        result = merge.scoped_merge(base(), drafted, "the executive summary")
        assert merge.unchanged_outside(
            base(), result.document, "the executive summary") == []

    def test_unchanged_outside_names_a_section_that_did_drift(self):
        """Without the merge, this is what the live run was producing."""
        drifted = parsed(BASE_MD.replace(
            "Post-model adjustments are outside scope.",
            "Post-model adjustments fall outside scope."))
        assert merge.unchanged_outside(
            base(), drifted, "the executive summary") == ["3. Limitations"]

    def test_a_citation_change_alone_counts_as_a_change(self):
        """Comparing rendered text would let a locator change silently."""
        after = base()
        after.section("3. Limitations").blocks[0].sources = ["docx://para/9"]
        assert merge.unchanged_outside(
            base(), after, "the executive summary") == ["3. Limitations"]


class TestTheDiagnosticsALiveFailureNeeds:
    def test_a_diff_names_the_section_and_shows_both_sides(self):
        after = parsed(BASE_MD.replace(
            "Post-model adjustments are outside scope.",
            "Adjustments are out of scope."))
        entries = merge.diff_sections(base(), after)
        assert len(entries) == 1
        assert entries[0]["section"] == "3. Limitations"
        assert entries[0]["change"] == "changed"
        assert "Post-model adjustments" in entries[0]["before"]
        assert "Adjustments are out of scope." in entries[0]["after"]

    def test_a_diff_reports_additions_and_removals_by_name(self):
        after = parsed(BASE_MD.split("## 3. Limitations")[0]
                        + "\n## 4. Next steps\n\nReview it.\n")
        changes = {e["section"]: e["change"]
                   for e in merge.diff_sections(base(), after)}
        assert changes == {"3. Limitations": "dropped", "4. Next steps": "added"}

    def test_an_identical_document_produces_no_diff(self):
        assert merge.diff_sections(base(), base()) == []
