"""
Filters a reader stated, applied — and filters nobody stated, not invented.

Three defects found by asking the Cockpit an ordinary question.

**A condition stated in the question was dropped in silence.**

    "aug 2026 personal finance salary transfer stage2 ecl vs jul"

came back with the ECL of the whole personal-finance book — SAR 8,012,419 to
8,994,012 — under a heading reading "PERSONAL FINANCE". The salary-transfer and
Stage 2 conditions were both gone and nothing said so. The true figure is SAR
1,476,382 to 1,700,845: the answer was **five times too large**, and a reader
had no way to see it.

Two causes. `salary_transfer_flag` was not a governed dimension at all, so the
strongest affordability control in a Saudi retail book could be neither filtered
on nor broken out by. And a two-valued dimension cannot be matched by its VALUE
— the values are "True" and "False", and nobody types either — so the phrase
that names it had to be taught.

**A filter nobody asked for was invented.**

    "give me a breakdown by product"

resolved `application_score_band = A` out of the indefinite article, because
that dimension's values are the single letters A to E and the entity matcher
looked for each as a bare word. Any question containing "a" was scoped to score
band A — correctly computed, wrongly scoped, under a note a reader skims past.

**And "stage2" was not "stage 2".** The pattern required whitespace after the
noun.
"""

from __future__ import annotations

import pytest

from backend.orchestration import entities as en
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")


@pytest.fixture(scope="module")
def dimensions():
    from backend.orchestration.vocabulary import get_vocabulary

    return get_vocabulary().dimensions


def resolved(question: str, dimensions) -> set[tuple[str, str]]:
    return {(m.kind, m.value) for m in en.match_all(question, dimensions)}


class TestThePolicyFlagsAreGoverned:
    @pytest.mark.parametrize("column", [
        "salary_transfer_flag", "secured_flag", "forbearance_flag",
        "restructured_flag", "credit_impaired_flag", "current_default_flag",
        "sicr_flag", "policy_exception_flag", "score_override_flag",
        "origination_vintage"])
    def test_it_is_a_governed_dimension(self, column):
        assert column in profile.RETAIL_DIMENSIONS

    def test_every_governed_dimension_is_a_real_column(self, retail_book):
        columns = set(retail_book.latest().columns)
        missing = [d for d in profile.RETAIL_DIMENSIONS if d not in columns]
        assert not missing, f"governed but not in the book: {missing}"

    def test_every_governed_flag_carries_both_values(self, retail_book):
        """A flag that is always False is not a filter, it is a constant."""
        frame = retail_book.latest()
        for name in profile.RETAIL_DIMENSIONS:
            if not name.endswith("_flag"):
                continue
            values = set(frame[name].dropna().astype(str).unique())
            assert len(values) >= 2, (
                f"{name} only ever takes {values}; filtering on it would "
                "select everything or nothing")


class TestAStatedConditionIsApplied:
    def test_the_question_that_lost_five_sixths_of_its_filters(self, dimensions):
        found = resolved(
            "aug 2026 personal finance salary transfer stage2 ecl vs jul",
            dimensions)
        assert ("product_label", "Personal Finance") in found
        assert ("salary_transfer_flag", "True") in found
        assert ("ifrs9_stage", "2") in found

    @pytest.mark.parametrize("question,expected", [
        ("salary transfer customers", ("salary_transfer_flag", "True")),
        ("non-salary-transfer customers", ("salary_transfer_flag", "False")),
        ("unsecured personal finance", ("secured_flag", "False")),
        ("secured facilities", ("secured_flag", "True")),
        ("forborne accounts", ("forbearance_flag", "True")),
        ("restructured facilities", ("restructured_flag", "True")),
        ("facilities with a policy exception", ("policy_exception_flag", "True")),
        ("where the score was overridden", ("score_override_flag", "True")),
        ("thin-file customers", ("bureau_thin_file_flag", "True")),
        ("new-to-bank customers", ("new_to_bank_at_origination_flag", "True")),
    ])
    def test_a_flag_is_named_by_the_phrase_people_type(
            self, question, expected, dimensions):
        assert expected in resolved(question, dimensions)

    def test_a_negation_beats_the_phrase_inside_it(self, dimensions):
        """"non-salary-transfer" contains "salary transfer"."""
        found = resolved("non salary transfer customers", dimensions)
        assert ("salary_transfer_flag", "False") in found
        assert ("salary_transfer_flag", "True") not in found

    @pytest.mark.parametrize("spelling", ["stage 2", "stage2", "stages 2",
                                          "Stage  2"])
    def test_the_stage_is_read_however_it_is_spaced(self, spelling, dimensions):
        assert ("ifrs9_stage", "2") in resolved(
            f"personal finance {spelling} ecl", dimensions)


class TestAFilterNobodyAskedForIsNotInvented:
    @pytest.mark.parametrize("question", [
        "give me a breakdown by product",
        "show me a summary of the book",
        "what is a reasonable coverage ratio",
        "is there a concentration in one product",
        "which borrowers have a DSCR below 1.2?",
    ])
    def test_the_indefinite_article_is_not_a_score_band(self, question,
                                                        dimensions):
        found = resolved(question, dimensions)
        bands = {k for k, _ in found
                 if k in ("application_score_band", "behavioural_score_band")}
        assert not bands, (
            f"{question!r} invented {bands} out of an ordinary English word")

    def test_a_named_band_is_still_matched(self, dimensions):
        assert ("application_score_band", "A") in resolved(
            "exposure in application score band A", dimensions)

    def test_a_bare_digit_is_not_a_stage(self, dimensions):
        found = resolved("which facilities have 3 missed payments",
                         dimensions)
        assert ("ifrs9_stage", "3") not in found

    def test_a_decimal_is_not_two_stages(self, dimensions):
        """`\\b1\\b` matches inside "1.2"; a stage filter of 1 AND 2 matches no
        row at all, and the question came back as "could not complete"."""
        found = resolved("which borrowers have a DSCR below 1.2?", dimensions)
        stages = {v for k, v in found if k == "ifrs9_stage"}
        assert not stages


class TestTheTwoReadersOfTheVocabularyAgree:
    """`match_all` and `resolve_dimension_value` read the same vocabulary. They
    disagreed: one refused a value shorter than four characters and the other
    did not, which is how the indefinite article became a filter."""

    @pytest.mark.parametrize("question", [
        "give me a breakdown by product",
        "salary transfer customers",
        "unsecured personal finance",
    ])
    def test_neither_reader_invents_what_the_other_refuses(self, question,
                                                           dimensions):
        from backend.orchestration.vocabulary import get_vocabulary

        one = resolved(question, dimensions)
        other = get_vocabulary().resolve_dimension_value(question)
        if other is not None:
            assert other in one, (
                f"{other} was resolved by one reader and not the other")
