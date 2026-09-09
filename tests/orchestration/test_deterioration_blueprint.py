"""The Sector / Segment Deterioration Investigation Blueprint.

Two kinds of test, and the second is the point.

The first kind checks the blueprint's own mechanism — window resolution,
aggregation types, what it refuses and why.

The second RECONCILES. `deterioration.review()` computes the measures directly
from `ifrs9_staging`, and `deterioration.questions()` asks for the same
measures as ordinary governed questions that go through the whole reader,
validator and runtime. Those two paths must agree. If they ever disagree, one
of them is wrong and a review is quoting a figure nobody can reproduce — which
is the failure mode the blueprint exists to make impossible.
"""

from __future__ import annotations

import pytest

from backend.orchestration import deterioration as dt

# ------------------------------------------------------------------- windows


class TestWhichTwoDatesAreCompared:

    @pytest.mark.parametrize("text,expected", [
        ("Shipping has deteriorated. Show me everything.", dt.QOQ),
        ("Show me Shipping year on year.", dt.YOY),
        ("How has Shipping moved quarter on quarter?", dt.QOQ),
        ("Give me the Shipping YoY picture.", dt.YOY),
        ("Shipping month on month, please.", dt.MOM),
        ("Full review of Shipping.", dt.QOQ),
    ])
    def test_the_window_is_read_from_the_sentence(self, text, expected) -> None:
        assert dt.read_window(text) == expected

    def test_quarter_on_quarter_steps_back_one_published_period(self) -> None:
        published = ["Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025", "Q1 2026"]
        opening, closing, refusal = dt.periods_for(dt.QOQ, published)
        assert (opening, closing, refusal) == ("Q4 2025", "Q1 2026", "")

    def test_year_on_year_steps_back_four(self) -> None:
        published = [f"Q{q} {y}" for y in (2025, 2026) for q in (1, 2, 3, 4)]
        opening, closing, refusal = dt.periods_for(dt.YOY, published)
        assert (opening, closing) == ("Q4 2025", "Q4 2026")
        assert refusal == ""

    def test_a_window_longer_than_the_history_is_refused_not_clamped(self) -> None:
        """A year-on-year movement quietly measured over two quarters is a
        wrong answer wearing a right label."""
        opening, closing, refusal = dt.periods_for(
            dt.YOY, ["Q3 2025", "Q4 2025", "Q1 2026"])
        assert not opening and not closing
        assert "not far enough back" in refusal

    def test_month_on_month_is_refused_with_the_reason(self) -> None:
        opening, closing, refusal = dt.periods_for(
            dt.MOM, ["Q1 2026", "Q2 2026"])
        assert not opening and not closing
        assert "quarterly" in refusal

    def test_an_explicit_pair_must_both_be_published(self) -> None:
        published = ["Q1 2026", "Q2 2026"]
        assert dt.periods_for(dt.EXPLICIT, published,
                              opening="Q1 2026", closing="Q2 2026") == (
            "Q1 2026", "Q2 2026", "")
        _, _, refusal = dt.periods_for(dt.EXPLICIT, published,
                                       opening="Q3 2024", closing="Q2 2026")
        assert "not a published period" in refusal

    def test_no_published_periods_is_refused(self) -> None:
        _, _, refusal = dt.periods_for(dt.QOQ, [])
        assert "no published periods" in refusal


# -------------------------------------------------------------------- lenses


class TestTheMeasuresAreTypedCorrectly:

    def test_a_ratio_is_never_summed(self) -> None:
        """Summing DSCR across a portfolio is a type error with a unit
        printed after it. The same is true of a PD, an LGD and a coverage."""
        for lens in dt.LENSES:
            if lens.unit == "%":
                assert lens.aggregation != "sum", lens.key

    def test_a_ratio_is_weighted_by_exposure(self) -> None:
        """An unweighted average PD lets a 50,000 riyal facility move the
        portfolio number as far as a 500 million riyal one."""
        for lens in dt.LENSES:
            if lens.aggregation == "weighted_mean":
                assert lens.weight == "ead", lens.key

    def test_an_amount_is_summed(self) -> None:
        amounts = [lens for lens in dt.LENSES if lens.unit == "SAR mn"]
        assert amounts
        assert all(lens.aggregation == "sum" for lens in amounts)

    def test_every_lens_says_why_it_is_in_the_review(self) -> None:
        assert all(len(lens.because) > 40 for lens in dt.LENSES)

    def test_the_blueprint_names_what_it_cannot_read(self) -> None:
        """A review that silently drops the rating migration reads as one that
        looked and found nothing there."""
        assert dt.UNAVAILABLE
        assert all(measure and why for measure, why in dt.UNAVAILABLE)


class TestTheBlueprintAsksRatherThanComputes:

    def test_every_measure_becomes_a_governed_question(self) -> None:
        asked = dt.questions("Shipping", window=dt.QOQ)
        keys = {item["key"] for item in asked}
        assert {lens.key for lens in dt.LENSES} <= keys

    def test_the_structural_analyses_are_asked_too(self) -> None:
        keys = {item["key"] for item in dt.questions("Shipping")}
        assert {"stage_balance", "stage_count", "notches",
                "contributors"} <= keys

    def test_balance_and_account_count_are_two_analyses(self) -> None:
        """They routinely disagree, and the disagreement is the finding: a
        stage 2 balance up 30% while the count is up 3% is three borrowers,
        not a trend."""
        asked = {i["key"]: i for i in dt.questions("Shipping")}
        assert asked["stage_balance"]["question"] != \
            asked["stage_count"]["question"]

    def test_the_window_reaches_the_questions(self) -> None:
        quarterly = dt.questions("Shipping", window=dt.QOQ)
        yearly = dt.questions("Shipping", window=dt.YOY)
        assert any("latest quarter" in i["question"] for i in quarterly)
        assert any("latest year" in i["question"] for i in yearly)

    def test_an_explicit_pair_is_named_in_the_questions(self) -> None:
        asked = dt.questions("Shipping", opening="Q1 2025", closing="Q1 2026")
        assert any("between Q1 2025 and Q1 2026" in i["question"]
                   for i in asked)

    @pytest.mark.parametrize("text,wanted", [
        ("Shipping has deteriorated. Show me everything.", True),
        ("Give me the full review of Real Estate.", True),
        ("What is driving the deterioration in Contracting?", True),
        ("What is total ECL?", False),
        ("Which customers have covenant headroom below 15%?", False),
    ])
    def test_only_a_complete_review_asks_for_the_blueprint(self, text, wanted
                                                           ) -> None:
        assert dt.wants_complete_review(text) is wanted


# -------------------------------------------------------------- reconciliation


@pytest.fixture(scope="module")
def shipping():
    return dt.review("Shipping", window=dt.YOY)


class TestTheReviewReadsTheBook:

    def test_it_runs(self, shipping) -> None:
        assert not shipping.refusal
        assert shipping.ok

    def test_it_reads_one_dataset(self, shipping) -> None:
        """A join costs a relationship path, a grain contract and a
        reconciliation, and buys nothing when the fields are in one table."""
        assert shipping.to_dict()["dataset"] == dt.DATASET

    def test_it_is_more_than_one_analysis(self, shipping) -> None:
        assert shipping.analysis_count >= 10

    def test_every_lens_was_measured_at_both_dates(self, shipping) -> None:
        assert len(shipping.movements) == len(dt.LENSES)
        assert all(m.opening_rows and m.closing_rows
                   for m in shipping.movements)

    def test_stage_balance_and_stage_count_disagree_in_shape(self, shipping
                                                             ) -> None:
        """Both are per stage; one is money and one is names."""
        assert shipping.stage_balance and shipping.stage_count
        assert len(shipping.stage_balance) == len(shipping.stage_count)
        balances = [row[shipping.closing] for row in shipping.stage_balance]
        counts = [row[shipping.closing] for row in shipping.stage_count]
        assert all(isinstance(c, int) for c in counts)
        assert balances != counts

    def test_the_contributors_are_ordered_by_what_they_contributed(
            self, shipping) -> None:
        changes = [row["ecl_change"] for row in shipping.contributors]
        assert changes == sorted(changes, reverse=True)

    def test_grade_slippage_is_banded_rather_than_averaged(self, shipping
                                                           ) -> None:
        """"0.4 notches on average" describes no facility."""
        assert {row["band"] for row in shipping.notches} == {
            "At origination", "1 notch below", "2 notches below",
            "3 or more notches below"}


class TestTheTwoPathsAgree:
    """The blueprint's direct read and the Ask path must produce one book."""

    def test_exposure_reconciles_with_the_stage_balance(self, shipping) -> None:
        exposure = next(m for m in shipping.movements
                        if m.lens.key == "exposure")
        by_stage = sum(float(row[shipping.closing])
                       for row in shipping.stage_balance)
        assert by_stage == pytest.approx(exposure.closing, rel=1e-6)

    def test_the_account_count_reconciles_with_the_rows_read(self, shipping
                                                              ) -> None:
        counted = sum(int(row[shipping.closing])
                      for row in shipping.stage_count)
        exposure = next(m for m in shipping.movements
                        if m.lens.key == "exposure")
        assert counted == exposure.closing_rows

    def test_a_deterioration_is_named_by_direction_not_by_sign(self, shipping
                                                                ) -> None:
        for movement in shipping.movements:
            if movement.change == 0:
                continue
            expected = (movement.change > 0 if movement.lens.higher_is_worse
                        else movement.change < 0)
            assert movement.deteriorated is expected


class TestItRefusesRatherThanGuesses:

    def test_an_unknown_segmentation_is_refused(self) -> None:
        out = dt.review("Shipping", dimension="colour")
        assert "not a segmentation" in out.refusal
        assert not out.movements

    def test_a_segment_with_no_rows_is_refused_with_the_reason(self) -> None:
        out = dt.review("Interstellar Freight")
        assert out.refusal
        assert not out.movements
