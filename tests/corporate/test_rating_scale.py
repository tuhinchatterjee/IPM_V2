"""
The governed rating scale, its ordering, and what a Stage 3 borrower is
measured on.

These are the tests that would have caught the UAT defect: a scale that ended
in `D`, an ordinal that disagreed with the grade beside it, and a Stage 3
applicable PD that was a rating-linked performing number rather than one
hundred per cent. They assert the ORDER, grade by grade, rather than counting
to nineteen — a scale can have nineteen entries and still be wrong.

Nothing here reads the data lake, so the scale is checked even when no book has
been generated.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.corporate import ratingscale as rs
from backend.ifrs9 import policy
from backend.whatif import delta, masterscale
from backend.whatif import profiles as pf

#: The authoritative order, written out longhand. If this list and the module
#: ever disagree, one of them is a typo and the test says which cell.
EXPECTED: tuple[str, ...] = (
    "AAA", "AA+", "AA", "AA-",
    "A+", "A", "A-",
    "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-",
    "B+", "B", "B-",
    "CCC", "CC", "C",
)


class TestTheOrder:

    def test_the_scale_is_the_nineteen_performing_grades_in_this_exact_order(self):
        assert rs.PERFORMING == EXPECTED
        assert rs.PERFORMING_COUNT == 19

    def test_the_scale_ends_in_C_and_not_in_D(self):
        assert rs.PERFORMING[-1] == "C"
        assert rs.WEAKEST_PERFORMING == "C"
        assert "D" not in rs.PERFORMING

    def test_default_is_a_separate_state_not_a_twentieth_grade(self):
        assert rs.DEFAULT_GRADE == "D"
        assert rs.DEFAULT_ORDINAL == 20
        assert rs.ALL_STATES == (*EXPECTED, "D")
        assert rs.ALL_STATES[rs.DEFAULT_STATE_INDEX] == "D"
        # The masterscale of performing grades does not carry it.
        assert "D" not in rs.TTC_PD_PCT

    @pytest.mark.parametrize("position,grade", list(enumerate(EXPECTED, start=1)))
    def test_every_ordinal_is_the_position_on_the_scale(self, position, grade):
        assert rs.ORDINAL[grade] == position
        assert rs.BY_ORDINAL[position] == grade

    def test_the_order_is_not_alphabetical(self):
        """The one mistake a screen makes when it sorts instead of reading."""
        assert list(rs.PERFORMING) != sorted(rs.PERFORMING)
        assert rs.ORDINAL["AA-"] > rs.ORDINAL["AA+"]
        assert rs.ORDINAL["B-"] > rs.ORDINAL["B+"]
        assert rs.ORDINAL["CCC"] < rs.ORDINAL["CC"] < rs.ORDINAL["C"]

    def test_investment_grade_ends_at_BBB_minus(self):
        assert rs.INVESTMENT_GRADE == EXPECTED[:10]
        assert rs.SPECULATIVE_GRADE == EXPECTED[10:]
        assert len(rs.INVESTMENT_GRADE) + len(rs.SPECULATIVE_GRADE) == 19

    def test_the_bands_resolve_including_the_new_weakest_one(self):
        assert rs.grades_in("C") == ("C",)
        assert rs.grades_in("CCC") == ("CCC",)
        assert rs.grades_in("BBB") == ("BBB+", "BBB", "BBB-")
        assert rs.grades_in("investment grade") == rs.INVESTMENT_GRADE

    def test_the_whatif_masterscale_carries_the_same_order(self):
        assert masterscale.PERFORMING == EXPECTED
        assert set(masterscale.MASTERSCALE) == set(EXPECTED)
        assert masterscale.BANDS["C"] == ("C",)

    def test_the_profile_grades_are_the_scale_and_the_states_add_default(self):
        assert pf.GRADES == EXPECTED
        assert pf.STATES == (*EXPECTED, "D")


class TestNotching:
    """A downgrade moves along the governed ordinal, and stops at C."""

    @pytest.mark.parametrize("start,notches,landed", [
        ("BBB", 1, "BBB-"), ("BBB", 2, "BB+"), ("BBB", 3, "BB"),
        ("AAA", 1, "AA+"), ("AA+", -1, "AAA"), ("AAA", -3, "AAA"),
        ("B-", 1, "CCC"), ("CCC", 1, "CC"), ("CC", 1, "C"),
        ("BB-", 4, "CCC"), ("A-", 5, "BB"), ("BBB-", 6, "B-"),
    ])
    def test_a_notch_move_lands_on_the_next_grade(self, start, notches, landed):
        assert masterscale.shift(start, notches) == landed
        assert rs.shift([start], notches)[0] == landed

    @pytest.mark.parametrize("start", EXPECTED)
    def test_a_downgrade_never_manufactures_a_default(self, start):
        assert masterscale.shift(start, 30) == "C"
        assert rs.shift([start], 30)[0] == "C"

    @pytest.mark.parametrize("start", EXPECTED)
    def test_every_boundary_moves_by_exactly_one_ordinal(self, start):
        here = rs.ORDINAL[start]
        if here < rs.PERFORMING_COUNT:
            assert rs.ORDINAL[masterscale.shift(start, 1)] == here + 1
        if here > 1:
            assert rs.ORDINAL[masterscale.shift(start, -1)] == here - 1

    def test_a_defaulted_name_stays_defaulted(self):
        assert masterscale.shift("D", 3) == "D"
        assert rs.shift(["D"], 3)[0] == "D"

    def test_notches_between_grades_is_a_subtraction(self):
        assert rs.notches("BBB", "BB+") == 2
        assert rs.notches("BB+", "BBB") == -2
        assert rs.notches("AAA", "C") == 18


class TestTheTTCMaster:

    def test_the_ttc_pd_is_strictly_monotonic_across_all_nineteen(self):
        values = [rs.TTC_PD_PCT[g] for g in EXPECTED]
        for left, right, worse in zip(EXPECTED, EXPECTED[1:], values[1:], strict=False):
            assert worse > rs.TTC_PD_PCT[left], (
                f"{right} must carry a higher TTC PD than {left}")

    def test_no_two_adjacent_grades_share_a_central_pd(self):
        values = [rs.TTC_PD_PCT[g] for g in EXPECTED]
        assert len(set(values)) == 19

    def test_the_investment_grade_end_is_low_and_the_tail_is_high(self):
        assert rs.TTC_PD_PCT["AAA"] < 0.02
        assert rs.TTC_PD_PCT["BBB-"] < 0.50
        assert rs.TTC_PD_PCT["C"] > 50.0
        # C is very high risk and still plainly not default.
        assert rs.TTC_PD_PCT["C"] < rs.DEFAULT_PD_PCT

    def test_the_increase_accelerates_rather_than_being_linear(self):
        """The property that rules out interpolation in percent space."""
        ratios = [rs.TTC_PD_PCT[b] / rs.TTC_PD_PCT[a]
                  for a, b in zip(EXPECTED, EXPECTED[1:], strict=False)]
        investment = ratios[:9]
        crossover = ratios[9:15]
        assert max(investment) < min(crossover), (
            "each notch through BB and B must widen the PD by more than a "
            "notch inside investment grade")
        assert ratios[16] > max(investment)

    def test_the_published_table_is_what_the_construction_produces(self):
        """The master and the constants that generate it cannot drift apart."""
        anchor = rs.TTC_ANCHOR_PD_PCT / 100.0
        base = math.log(anchor / (1.0 - anchor))

        def distance(low: int, high: int) -> float:
            return sum(max(0, min(high, b) - max(low, a)) * step
                       for a, b, step in rs.TTC_LOG_ODDS_STEPS)

        at = rs.ORDINAL[rs.TTC_ANCHOR_GRADE]
        for grade in EXPECTED:
            here = rs.ORDINAL[grade]
            logit = (base + distance(at, here) if here >= at
                     else base - distance(here, at))
            expected = 100.0 / (1.0 + math.exp(-logit))
            assert rs.TTC_PD_PCT[grade] == pytest.approx(expected, abs=5e-6), grade

    def test_the_band_edges_sit_between_the_grades_they_separate(self):
        assert len(rs.RATING_BOUNDS) == 18
        for i, (left, right) in enumerate(zip(EXPECTED, EXPECTED[1:], strict=False)):
            assert rs.TTC_PD_PCT[left] < rs.RATING_BOUNDS[i] < rs.TTC_PD_PCT[right]

    def test_a_pd_reads_back_to_a_performing_grade_and_never_to_default(self):
        read = rs.grade_from_pd(np.array([0.0, 0.18, 5.0, 99.0, 1e6]))
        assert read.max() <= rs.PERFORMING_COUNT - 1
        assert rs.PERFORMING[int(read[-1])] == "C"

    def test_the_anchor_sits_inside_the_published_corporate_evidence(self):
        """Moody's Baa 0.170% and S&P BBB 0.26%, per the calibration note."""
        assert 0.17 <= rs.TTC_PD_PCT["BBB"] <= 0.26
        assert 0.85 <= rs.TTC_PD_PCT["BB"] <= 1.13
        assert 4.60 <= rs.TTC_PD_PCT["B"] <= 4.99


class TestStageThreeIsMeasuredAtOneHundred:

    def test_the_applicable_pd_is_exactly_one_hundred_in_stage_three(self):
        applicable = rs.applicable_pd(np.array([1, 2, 3]),
                                      np.array([1.5, 1.5, 1.5]),
                                      np.array([6.0, 6.0, 6.0]))
        assert list(applicable) == [1.5, 6.0, 100.0]

    def test_it_is_not_ninety_nine_point_nine_and_not_the_ceiling(self):
        assert rs.stage_three_pd() == 100.0
        assert rs.DEFAULT_PD_PCT == 100.0
        assert rs.PD_CEILING_PCT < rs.DEFAULT_PD_PCT

    def test_a_rating_linked_performing_pd_never_becomes_the_measurement(self):
        """Even a C-rated defaulted name is measured at 100, not at 62."""
        applicable = rs.applicable_pd(np.array([3]),
                                      np.array([rs.TTC_PD_PCT["C"]]),
                                      np.array([rs.TTC_PD_PCT["C"]]))
        assert float(applicable[0]) == 100.0

    def test_every_module_that_picks_a_basis_picks_the_same_one(self):
        import pandas as pd
        index = pd.Index([0, 1, 2])
        frame = pd.DataFrame({"stage": [1, 2, 3], "pd_12m": [1.5, 1.5, 1.5],
                              "pd_lifetime": [6.0, 6.0, 6.0]}, index=index)
        governed = list(rs.applicable_pd(np.array([1, 2, 3]),
                                         np.array([1.5, 1.5, 1.5]),
                                         np.array([6.0, 6.0, 6.0])))
        assert list(pf.stage_appropriate_pd(frame)) == governed
        assert list(delta.applicable_pd([1, 2, 3], [1.5] * 3, [6.0] * 3,
                                        index)) == governed

    def test_a_pd_of_one_hundred_is_not_a_loss_of_one_hundred(self):
        """A defaulted borrower with collateral still recovers."""
        import pandas as pd
        ecl = policy.measured_ecl(pd.Series([3]), pd.Series([1.5]),
                                  pd.Series([40.0]), pd.Series([1_000_000.0]),
                                  lifetime_pd_pct=pd.Series([6.0]))
        # 1.00 x 40% x EAD, with no scenario uplift on a resolved default.
        assert float(ecl[0]) == pytest.approx(400_000.0)

    def test_the_scenario_weighting_never_lifts_a_default_above_its_lgd(self):
        import pandas as pd
        ead = 1_000_000.0
        for lgd in (10.0, 45.0, 95.0, 100.0):
            ecl = float(policy.measured_ecl(
                pd.Series([3]), pd.Series([2.0]), pd.Series([lgd]),
                pd.Series([ead]), lifetime_pd_pct=pd.Series([9.0]))[0])
            assert ecl == pytest.approx(lgd / 100.0 * ead)
            assert ecl <= ead

    def test_a_performing_exposure_still_carries_the_scenario_weighting(self):
        import pandas as pd
        ecl = float(policy.measured_ecl(
            pd.Series([1]), pd.Series([2.0]), pd.Series([40.0]),
            pd.Series([1_000_000.0]))[0])
        assert ecl == pytest.approx(
            0.02 * 0.40 * 1_000_000.0 * policy.WEIGHTED_SCENARIO_FACTOR)
