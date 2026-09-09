"""The IFRS 9 ECL bridge: does it add up, and does it land where it should.

Every assertion here is arithmetic a reader can check by hand against the table
on the screen. That is deliberate — a decomposition's whole claim is that the
steps explain the total, and a test suite that only asserted the analysis ran
would leave that claim untested.

The live book is required. A bridge that reconciles on a fixture and not on the
book is a bridge that does not reconciles, and these tests exist to catch that.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.ifrs9 import decomposition as bridge

TOLERANCE = 1e-6


@pytest.fixture(scope="module")
def book() -> pd.DataFrame:
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    source = get_data_source()
    if FACILITY not in source.datasets():
        pytest.skip("Analytical lake not built.")
    found = bridge.read_book("latest")
    if found.empty:
        pytest.skip("No facilities in the latest period.")
    return found


@pytest.fixture(scope="module")
def built(book: pd.DataFrame) -> bridge.Bridge:
    return bridge.build(book, period="latest")


class TestTheBridgeHasTheGovernedSteps:
    def test_six_steps_in_the_governed_order(self, built: bridge.Bridge):
        assert [s.key for s in built.steps] == list(bridge.STEP_ORDER)
        assert [s.number for s in built.steps] == [1, 2, 3, 4, 5, 6]

    def test_every_step_is_named_and_explained(self, built: bridge.Bridge):
        for step in built.steps:
            assert step.name and step.description
            assert step.name != step.description

    def test_the_answer_is_not_a_scalar(self, built: bridge.Bridge):
        rows = built.rows()
        assert len(rows) == 6
        assert len({r["ecl"] for r in rows}) > 1

    def test_the_overlay_is_its_own_step_and_not_hidden_in_another(
            self, built: bridge.Bridge):
        overlay = built.step(bridge.OVERLAY)
        assert overlay is not None
        assert overlay.number == 6
        assert "overlay" in overlay.name.lower()

    def test_the_steps_this_installation_cannot_measure_are_named_not_faked(
            self, built: bridge.Bridge):
        omitted = {o["step"] for o in built.omitted}
        assert omitted == {"ttc_calibration", "non_calibrated_portfolio"}
        # Omitted, not present-and-zero: a step contributing nothing reads as a
        # driver that did nothing, which is a different and untrue statement.
        assert not any("calibrat" in s.key for s in built.steps)
        for note in built.omitted:
            assert note["because"].strip()


class TestTheArithmeticOnTheScreen:
    def test_each_step_impact_is_this_step_less_the_previous(
            self, built: bridge.Bridge):
        previous = None
        for step in built.steps:
            expected = 0.0 if previous is None else step.ecl - previous
            assert step.impact == pytest.approx(expected, abs=TOLERANCE)
            previous = step.ecl

    def test_the_impacts_sum_to_the_whole_bridge(self, built: bridge.Bridge):
        moved = sum(s.impact for s in built.steps)
        assert moved == pytest.approx(built.final.ecl - built.steps[0].ecl,
                                      abs=1e-6)

    def test_each_percentage_is_the_impact_over_the_previous_step(
            self, built: bridge.Bridge):
        previous = None
        for step in built.steps:
            if previous in (None, 0):
                assert step.change_pct is None
            else:
                assert step.change_pct == pytest.approx(
                    step.impact / previous * 100.0, abs=1e-9)
            previous = step.ecl

    def test_a_percentage_of_nothing_is_not_a_number(self):
        # The zero-denominator rule, stated once and asserted directly rather
        # than left to whether the live book happens to produce a zero step.
        assert bridge._share(5.0, None) is None
        assert bridge._share(5.0, 0.0) is None
        assert bridge._share(5.0, 50.0) == pytest.approx(10.0)


class TestItReconcilesToTheReportedProvision:
    def test_the_final_step_is_the_reported_ecl(self, built: bridge.Bridge,
                                                book: pd.DataFrame):
        reported = float(pd.to_numeric(book["total_ecl"],
                                       errors="coerce").fillna(0.0).sum())
        assert built.reconciliation.reported_ecl == pytest.approx(reported)
        assert built.final.ecl == pytest.approx(
            reported, rel=bridge.RECONCILIATION_TOLERANCE_PCT / 100.0)

    def test_the_reconciliation_is_published_and_passes(
            self, built: bridge.Bridge):
        found = built.reconciliation
        assert found.reconciles is True
        assert found.residual_pct <= found.tolerance_pct
        assert found.tolerance_pct == bridge.RECONCILIATION_TOLERANCE_PCT

    def test_a_bridge_that_missed_would_say_so(self, book: pd.DataFrame):
        # The tolerance has to be able to FAIL, or asserting that it passes on
        # the live book proves nothing about the check.
        moved = book.copy()
        moved["total_ecl"] = pd.to_numeric(
            moved["total_ecl"], errors="coerce").fillna(0.0) * 1.05
        found = bridge.build(moved, period="latest").reconciliation
        assert found.reconciles is False
        assert found.residual_pct > found.tolerance_pct


class TestEachStepMeasuresTheThingItClaimsTo:
    def test_the_baseline_holds_one_pd_and_one_lgd_for_the_whole_book(
            self, built: bridge.Bridge, book: pd.DataFrame):
        ead = pd.to_numeric(book["ead"], errors="coerce").fillna(0.0)
        flat_pd = built.assumptions["flat_ttc_pd_pct"]
        flat_lgd = built.assumptions["flat_lgd_pct"]
        expected = float((ead * flat_lgd / 100.0 * flat_pd / 100.0).sum())
        assert built.steps[0].ecl == pytest.approx(expected, rel=1e-9)

    def test_the_rating_step_moves_pd_and_nothing_else(
            self, built: bridge.Bridge, book: pd.DataFrame):
        ead = pd.to_numeric(book["ead"], errors="coerce").fillna(0.0).to_numpy()
        ttc = pd.to_numeric(book[bridge.TTC_COLUMN],
                            errors="coerce").fillna(0.0).to_numpy()
        grade_pd = bridge._grade_pd(book["internal_grade"], ttc, ead)
        flat_lgd = built.assumptions["flat_lgd_pct"]
        expected = float((ead * flat_lgd / 100.0 * grade_pd / 100.0).sum())
        assert built.step(bridge.RATING).ecl == pytest.approx(expected, rel=1e-9)

    def test_the_macro_step_puts_the_point_in_time_pd_in(
            self, built: bridge.Bridge, book: pd.DataFrame):
        ead = pd.to_numeric(book["ead"], errors="coerce").fillna(0.0)
        pit = pd.to_numeric(book[bridge.PIT_COLUMN],
                            errors="coerce").fillna(0.0)
        flat_lgd = built.assumptions["flat_lgd_pct"]
        expected = float((ead * flat_lgd / 100.0 * pit / 100.0).sum())
        assert built.step(bridge.MACRO).ecl == pytest.approx(expected, rel=1e-9)

    def test_the_stage_step_applies_the_ifrs9_measurement_basis(
            self, built: bridge.Bridge, book: pd.DataFrame):
        stage = pd.to_numeric(book["ifrs9_stage"], errors="coerce").fillna(0.0)
        # Stage 1 on the twelve-month PD, Stage 2 on the lifetime PD, Stage 3
        # at the credit-impaired treatment. If that stopped being true, a stage
        # migration would stop costing anything, which is the one thing this
        # step exists to price.
        assert (stage >= 2).any(), "no staged exposure to measure"
        assert built.step(bridge.STAGE).impact != pytest.approx(0.0, abs=1e-6)

    def test_the_collateral_step_reproduces_the_reported_model_ecl(
            self, built: bridge.Bridge, book: pd.DataFrame):
        model = float(pd.to_numeric(book["model_ecl"],
                                    errors="coerce").fillna(0.0).sum())
        assert built.step(bridge.COLLATERAL).ecl == pytest.approx(
            model, rel=bridge.RECONCILIATION_TOLERANCE_PCT / 100.0)

    def test_the_overlay_step_adds_exactly_the_governed_overlay(
            self, built: bridge.Bridge, book: pd.DataFrame):
        overlay = float(pd.to_numeric(book["macro_overlay"],
                                      errors="coerce").fillna(0.0).sum())
        assert built.step(bridge.OVERLAY).impact == pytest.approx(overlay,
                                                                  rel=1e-9)


class TestTheBorrowerLevelAuditPath:
    def test_there_is_a_row_per_borrower_carrying_every_step(
            self, built: bridge.Bridge):
        rows = built.contributions
        assert len(rows) == built.borrowers > 0
        for key in bridge.STEP_ORDER:
            assert f"ecl_{key}" in rows.columns
            assert f"impact_{key}" in rows.columns

    @pytest.mark.parametrize("key", bridge.STEP_ORDER[1:])
    def test_the_borrower_impacts_sum_to_the_portfolio_step_impact(
            self, built: bridge.Bridge, key: str):
        summed = float(built.contributions[f"impact_{key}"].sum())
        assert summed == pytest.approx(built.step(key).impact, abs=1e-6)

    def test_the_contributors_are_the_largest_movers_of_that_step(
            self, built: bridge.Bridge):
        found = bridge.contributors(built, bridge.STAGE, limit=5)
        assert len(found) == 5
        impacts = found[f"impact_{bridge.STAGE}"].abs().tolist()
        assert impacts == sorted(impacts, reverse=True)
        biggest = built.contributions[f"impact_{bridge.STAGE}"].abs().max()
        assert impacts[0] == pytest.approx(biggest)

    def test_a_contributor_carries_enough_to_open_the_borrower(
            self, built: bridge.Bridge):
        found = bridge.contributors(built, bridge.COLLATERAL, limit=3)
        for column in ("customer_id", "borrower_name", "segment", "ead"):
            assert column in found.columns


class TestTheSegmentsAreTheOnesThatAreConfigured:
    def test_the_segments_come_from_the_book(self, built: bridge.Bridge,
                                             book: pd.DataFrame):
        assert built.segments == tuple(sorted({str(s) for s in
                                              book["segment"].dropna().unique()}))
        assert "Corporate" in built.segments

    def test_each_step_splits_across_those_segments_and_sums_back(
            self, built: bridge.Bridge):
        for step in built.steps:
            assert set(step.by_segment) == set(built.segments)
            assert sum(step.by_segment.values()) == pytest.approx(step.ecl,
                                                                  abs=1e-6)

    def test_the_segment_impacts_sum_to_the_step_impact(
            self, built: bridge.Bridge):
        for step in built.steps[1:]:
            assert sum(step.impact_by_segment.values()) == pytest.approx(
                step.impact, abs=1e-6)


class TestThePresentedTable:
    def test_the_columns_are_the_ones_a_reader_needs(self,
                                                     built: bridge.Bridge):
        row = built.rows()[0]
        for column in ("step", "description", "ecl", "step_impact",
                       "change_pct"):
            assert column in row
        # The step key and the method note belong to the audit trail, not to a
        # table cell.
        assert "key" not in row and "detail" not in row

    def test_the_full_row_still_carries_them(self, built: bridge.Bridge):
        full = built.steps[0].to_full_dict()
        assert full["key"] == bridge.BASELINE
        assert full["detail"]

    def test_the_unit_is_the_governed_one(self, built: bridge.Bridge):
        assert built.unit == "SAR mn"
        assert "AED" not in built.unit


class TestItRefusesRatherThanInvents:
    def test_an_empty_population_is_an_error_not_a_bridge_of_zeros(self):
        with pytest.raises(ValueError, match="at least one facility"):
            bridge.build(pd.DataFrame(), period="latest")

    def test_a_population_with_no_exposure_is_an_error(self):
        empty = pd.DataFrame({
            "account_id": ["a"], "customer_id": ["c"], "borrower_name": ["n"],
            "segment": ["Corporate"], "sector": ["Shipping"],
            "internal_grade": [5], "rating_bucket": ["BB"], "ead": [0.0],
            "lgd_pct": [40.0], "pd_12m_pct": [1.0], "pd_lifetime_pct": [4.0],
            "ifrs9_stage": [1], "collateral_value": [0.0],
            "limit_amount": [0.0], "model_ecl": [0.0], "macro_overlay": [0.0],
            "total_ecl": [0.0], bridge.TTC_COLUMN: [0.5]})
        with pytest.raises(ValueError, match="no exposure"):
            bridge.build(empty, period="latest")

    def test_a_facility_with_no_grade_keeps_its_own_pd(self):
        ttc = np.array([2.0, 4.0])
        ead = np.array([100.0, 100.0])
        grade = pd.Series([None, "5"])
        mapped = bridge._grade_pd(grade, ttc, ead)
        assert mapped[0] == pytest.approx(2.0)
        assert mapped[1] == pytest.approx(4.0)
