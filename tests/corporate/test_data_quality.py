"""
Is this book internally coherent, quarter after quarter?

Plausibility asks whether a credit officer would recognise the book. This asks
something narrower and harder: whether the book agrees with ITSELF. Four
identities have to hold on every row of every quarter or the numbers on the
screen cannot be defended, and each one of them failed at some point in the
build:

* **Default means one thing.** A borrower ninety days past due is presumed to
  be in default; a borrower in default is in Stage 3; a borrower in Stage 3 is
  rated D and carries a defaulted PD. The book once held twenty-seven names
  that were credit-impaired by days past due, still rated B-, still carrying a
  ten per cent probability of default — and whose Stage 3 provision then moved
  under a rating shock aimed at performing names.
* **Exposure at default is drawn plus a conversion factor times undrawn.** Not
  approximately: the identity is what makes a CCF shock mean anything.
* **The three PDs are three different things, ordered.** Lifetime is at least
  the twelve-month figure, the twelve-month figure is a point-in-time reading
  of a through-the-cycle grade, and a defaulted borrower is at the ceiling.
* **Expected credit loss is a product of the parameters, bounded by the
  exposure.** A provision larger than the exposure it provides against is not
  conservatism, it is an arithmetic error.

Everything here runs over ALL sixteen quarters. A coherence property that
holds only in the quarter the screens open on is not a property of the book.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.corporate import ratingscale as rs
from backend.ifrs9 import policy


@pytest.fixture(scope="module")
def ifrs9(universe):
    return universe.frames["corporate_ifrs9"]


@pytest.fixture(scope="module")
def ratings(universe):
    return universe.frames["corporate_ratings"]


@pytest.fixture(scope="module")
def book(ifrs9, ratings):
    """IFRS 9 with the grade beside the three PDs it already carries."""
    grade = ratings[["borrower_id", "period", "internal_rating"]]
    return ifrs9.merge(grade, on=["borrower_id", "period"], how="left",
                       validate="one_to_one")


class TestDefaultMeansOneThing:
    def test_no_borrower_is_ninety_days_past_due_without_being_in_default(
            self, ifrs9):
        """The presumption of default is not rebutted anywhere in this book.

        It could be — IFRS 9 allows rebuttal — but nothing here rebuts it, so
        a row that contradicts it is a generator defect rather than a credit
        judgement.
        """
        contradictory = ifrs9[(ifrs9["current_dpd"] >= policy.DEFAULT_DPD_DAYS)
                              & (~ifrs9["default_flag"])]
        assert contradictory.empty, (
            f"{len(contradictory)} obligor-quarters are past the default "
            "presumption without being flagged in default")

    def test_every_defaulted_borrower_is_in_stage_three(self, ifrs9):
        assert ifrs9.loc[ifrs9["default_flag"], "stage"].eq(3).all()

    def test_every_stage_three_borrower_is_in_default(self, ifrs9):
        assert ifrs9.loc[ifrs9["stage"] == 3, "default_flag"].all()

    def test_every_stage_three_borrower_is_rated_default(self, book):
        stage_three = book[book["stage"] == 3]
        assert not stage_three.empty
        assert (stage_three["internal_rating"] == rs.DEFAULT_GRADE).all()

    def test_no_performing_grade_is_in_stage_three(self, book):
        performing = book[book["internal_rating"] != rs.DEFAULT_GRADE]
        assert performing["stage"].max() <= 2

    def test_a_defaulted_borrower_carries_a_defaulted_probability(self, book):
        stage_three = book[book["stage"] == 3]
        assert stage_three["pd_12m"].min() >= 90.0


class TestEveryObligorIsAnExposure:
    def test_no_obligor_sits_in_the_book_at_zero_exposure(self, ifrs9):
        """An obligor with no exposure is not a credit exposure.

        Seventy of them once were: rated, staged and provisioned at nothing,
        because every facility they held had matured while the relationship
        was still on book.
        """
        empty = ifrs9[ifrs9["ead"] <= 0.0]
        assert empty.empty, f"{len(empty)} obligor-quarters carry no exposure"

    def test_exposure_is_drawn_plus_the_conversion_factor_times_undrawn(
            self, ifrs9):
        implied = (ifrs9["drawn_exposure"]
                   + ifrs9["credit_conversion_factor"]
                   * ifrs9["undrawn_commitment"])
        # The factor is published to four decimals, so a large undrawn
        # commitment carries that rounding into the identity. The tolerance is
        # the rounding, not a fudge: half a unit in the last published place,
        # times the commitment it multiplies.
        tolerance = 0.05 + 5e-5 * ifrs9["undrawn_commitment"]
        gap = (implied - ifrs9["ead"]).abs()
        assert (gap <= tolerance).all(), (
            f"the EAD identity is off by up to {gap.max():.4f}")

    def test_exposure_is_never_below_what_is_already_drawn(self, ifrs9):
        assert (ifrs9["ead"] >= ifrs9["drawn_exposure"] - 1e-6).all()

    def test_the_conversion_factor_is_a_proportion(self, ifrs9):
        ccf = ifrs9["credit_conversion_factor"]
        assert float(ccf.min()) >= 0.0
        assert float(ccf.max()) <= 1.0


class TestTheThreePdsAreThreeThings:
    def test_lifetime_is_never_below_the_twelve_month_reading(self, book):
        assert (book["lifetime_pd_pct"] >= book["pit_pd_12m_pct"] - 1e-9).all()

    def test_the_reported_twelve_month_pd_is_the_point_in_time_one(self, book):
        gap = (book["pd_12m"] - book["pit_pd_12m_pct"]).abs()
        assert float(gap.max()) < 1e-6

    def test_every_grade_has_its_own_through_the_cycle_pd(self, book):
        """TTC is a property of the GRADE, not of the borrower.

        Two borrowers on the same grade in the same quarter must agree on it,
        or the grade is not describing anything.
        """
        spread = book.groupby("internal_rating")["ttc_pd_pct"].nunique()
        assert spread.max() == 1

    def test_the_through_the_cycle_scale_is_strictly_ordered(self, book):
        seen = (book.groupby("internal_rating")["ttc_pd_pct"].first()
                .reindex(rs.RATING_SCALE).dropna())
        assert list(seen.values) == sorted(seen.values)

    def test_the_point_in_time_pd_is_ordered_by_grade_on_average(self, book):
        """On grades the book actually populates.

        The strongest grades hold a handful of names across sixteen quarters,
        and two adjacent means over a handful of borrowers can cross on
        idiosyncratic movement alone. That is a fact about sample size, not a
        broken scale — the TTC ordering above is the one that has to be exact.
        """
        performing = book[book["internal_rating"] != rs.DEFAULT_GRADE]
        grouped = performing.groupby("internal_rating")["pit_pd_12m_pct"]
        means = grouped.mean()[grouped.size() >= 200].reindex(
            rs.RATING_SCALE).dropna()
        assert len(means) >= 12
        assert list(means.values) == sorted(means.values)

    def test_every_probability_is_a_percentage(self, book):
        for column in ("pd_12m", "pd_lifetime", "ttc_pd_pct",
                       "pit_pd_12m_pct", "lifetime_pd_pct"):
            assert float(book[column].min()) >= 0.0
            assert float(book[column].max()) <= 100.0


class TestTheProvisionIsAProduct:
    def test_expected_credit_loss_never_exceeds_the_exposure(self, ifrs9):
        assert (ifrs9["final_ecl"] <= ifrs9["ead"] + 1e-6).all()

    def test_no_provision_is_negative(self, ifrs9):
        assert float(ifrs9["final_ecl"].min()) >= 0.0

    def test_the_measurement_basis_follows_the_stage(self, ifrs9):
        stage_one = ifrs9[ifrs9["stage"] <= 1]
        later = ifrs9[ifrs9["stage"] >= 2]
        assert (stage_one["pd_measurement_basis"] == "12-month PD").all()
        assert (later["pd_measurement_basis"] == "Lifetime PD").all()

    def test_the_applicable_pd_is_the_one_the_basis_names(self, ifrs9):
        expected = np.where(ifrs9["stage"] <= 1, ifrs9["pd_12m"],
                            ifrs9["pd_lifetime"])
        assert float(np.abs(ifrs9["pd_applicable"] - expected).max()) < 1e-9

    def test_the_provision_before_overlay_is_the_governed_product(self, ifrs9):
        expected = (ifrs9["pd_applicable"] / 100.0
                    * ifrs9["lgd"] / 100.0
                    * ifrs9["ead"] * policy.WEIGHTED_SCENARIO_FACTOR)
        capped = np.minimum(expected, ifrs9["ead"])
        gap = (ifrs9["ecl_before_overlay"] - capped).abs()
        assert float(gap.max()) < 0.05

    def test_loss_given_default_sits_between_its_secured_and_unsecured_legs(
            self, ifrs9):
        """A performing borrower's LGD is a blend of its two legs.

        A DEFAULTED one carries a documented uplift on top: the easy
        recoveries have already happened by the time a workout starts, so the
        loss is worse than on a performing name with the same security.
        """
        performing = ifrs9[~ifrs9["default_flag"]]
        floor = np.minimum(performing["secured_lgd"], performing["unsecured_lgd"])
        ceiling = np.maximum(performing["secured_lgd"], performing["unsecured_lgd"])
        assert (performing["lgd"] >= floor - 1e-6).all()
        assert (performing["lgd"] <= ceiling + 1e-6).all()

    def test_a_defaulted_borrower_carries_the_workout_uplift(self, ifrs9):
        from backend.corporate.universe import DEFAULTED_LGD_UPLIFT

        defaulted = ifrs9[ifrs9["default_flag"]]
        ceiling = np.maximum(defaulted["secured_lgd"],
                             defaulted["unsecured_lgd"])
        excess = (defaulted["lgd"] - ceiling).max()
        assert float(excess) <= DEFAULTED_LGD_UPLIFT * 100.0 + 1e-6


class TestTheBookHoldsTogetherOverTime:
    def test_every_quarter_is_present_and_populated(self, universe, ifrs9):
        counts = ifrs9.groupby("period").size()
        assert set(counts.index) == set(universe.quarters)
        assert int(counts.min()) > 3_000

    def test_the_obligor_key_is_unique_in_every_quarter(self, ifrs9):
        assert not ifrs9.duplicated(["borrower_id", "period"]).any()

    def test_the_book_never_halves_or_doubles_between_quarters(self, ifrs9):
        totals = (ifrs9.groupby("period")["ead"].sum()
                  .reindex(sorted(ifrs9["period"].unique(),
                                  key=lambda p: (p.split()[-1], p.split()[0]))))
        ratio = totals.to_numpy()[1:] / totals.to_numpy()[:-1]
        assert float(ratio.min()) > 0.80
        assert float(ratio.max()) < 1.25

    def test_stage_two_is_neither_empty_nor_half_the_book_in_any_quarter(
            self, ifrs9):
        share = (ifrs9.assign(two=ifrs9["stage"] == 2)
                 .groupby("period")["two"].mean())
        assert float(share.min()) > 0.02
        assert float(share.max()) < 0.30

    def test_coverage_stays_in_a_range_a_bank_would_report(self, ifrs9):
        coverage = (ifrs9.groupby("period")
                    .apply(lambda g: g["final_ecl"].sum() / g["ead"].sum(),
                           include_groups=False))
        assert float(coverage.min()) > 0.005
        assert float(coverage.max()) < 0.20

    def test_the_provision_moves_with_the_cycle(self, universe, ifrs9):
        """Coverage should worsen when the cycle does.

        Not a strict relationship — idiosyncratic movement is real — but a
        book whose provision is uncorrelated with its own macro series is
        describing two unrelated worlds.
        """
        macro = universe.frames["corporate_macro"].set_index("period")
        coverage = (ifrs9.groupby("period")
                    .apply(lambda g: g["final_ecl"].sum() / g["ead"].sum(),
                           include_groups=False))
        joined = macro.join(coverage.rename("coverage")).dropna()
        correlation = float(np.corrcoef(joined["credit_cycle_factor"],
                                        joined["coverage"])[0, 1])
        assert correlation < -0.30, (
            f"coverage and the credit cycle correlate at {correlation:.2f}; a "
            "worsening cycle should raise the provision")


class TestEveryGradeIsUsed:
    def test_all_nineteen_grades_appear_somewhere_in_the_book(self, ratings):
        assert set(ratings["internal_rating"].unique()) == set(rs.RATING_SCALE)

    def test_the_scale_is_nineteen_points_and_not_a_relabelled_fourteen(self):
        assert len(rs.RATING_SCALE) == 19
        assert len(set(rs.TTC_PD_PCT)) == 19
        assert len(set(rs.TTC_PD_PCT.values())) == 19

    def test_the_distribution_is_not_concentrated_on_one_grade(self, ratings):
        share = ratings["internal_rating"].value_counts(normalize=True)
        assert float(share.max()) < 0.20
