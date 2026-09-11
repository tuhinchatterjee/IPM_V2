"""
The neutral What-If reconciliation, explained by arithmetic rather than by size.

Revision 2 reported the neutral rebuild of the personal-finance book at 2026-08
as SAR 8,994,011.35 against a published SAR 8,994,011.87 — a residual of SAR
0.52, six parts in a hundred million — and attributed it to "stored values on a
0.002 SAR grid versus continuous recalculation". The number was right and the
explanation was not, in two ways that matter:

* **The recomputation was not continuous.** It rounded the weighted and final
  allowance to the halala, which the build never does. The build rounds each
  SCENARIO ECL to the halala and then carries the weighted and final values as
  the exact weighted combination of those published figures.

* **The net was not the error.** The per-row displacements summed to |SAR 17.86|
  and cancelled down to SAR −0.52. A tolerance justified by the net would have
  been set thirty-four times too loose, and a real per-row defect of the same
  shape would have passed it.

The 0.002 grid is derived here rather than asserted: weights of 0.6/0.2/0.2 over
per-scenario values on a 0.01 grid can only land on multiples of
gcd(0.6, 0.2, 0.2) x 0.01 = 0.002. Snapping such a value to the nearest 0.01
moves it by at most 0.004 — which is exactly the largest row residual that was
observed, so the mechanism predicted the evidence instead of being fitted to it.

With the rebuild doing the build's arithmetic, a neutral scenario reproduces the
published allowance EXACTLY. The declared tolerance is kept as a guard, not as
an allowance: these gates assert zero and check the guard separately.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.retail import ecl as ecl_mod
from backend.retail import whatif as wif
from backend.retail.config import load_config

#: The figures Revision 2 reported, kept as the thing being reconciled.
REPORTED_POPULATION = "PERSONAL_LOAN"
REPORTED_MONTH = "2026-08"
REPORTED_BASELINE_SAR = 8_994_011.868


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def snapshot(retail_book):
    return retail_book.month(REPORTED_MONTH)


def _neutral(retail_book, frame, cfg, **filters):
    scenario = wif.Scenario(
        name="neutral", dataset_version=retail_book.manifest["dataset_version"],
        snapshot_date=str(frame["snapshot_date"].iloc[0]), filters=filters)
    return wif.run(frame, scenario, cfg)


class TestTheReportedBaselineIsIdentified:
    def test_it_is_the_personal_finance_population_not_the_whole_book(self, snapshot):
        """SAR 8.99m and SAR 15.95m are two populations, not a discrepancy."""
        personal = snapshot[snapshot["product_code"] == REPORTED_POPULATION]
        assert personal["ecl_final_sar"].sum() == pytest.approx(
            REPORTED_BASELINE_SAR, abs=0.01)
        whole = snapshot["ecl_final_sar"].sum()
        assert whole > personal["ecl_final_sar"].sum()
        assert whole == pytest.approx(15_952_108.836, abs=0.01)

    def test_the_baseline_measure_is_the_final_allowance(self, retail_book, snapshot, cfg):
        """Not the base scenario, and not the weighted value before overlay."""
        result = _neutral(retail_book, snapshot, cfg, product_code=REPORTED_POPULATION)
        personal = snapshot[snapshot["product_code"] == REPORTED_POPULATION]
        assert result["baseline"]["ecl_final_sar"] == pytest.approx(
            personal["ecl_final_sar"].sum(), abs=1e-6)
        assert result["baseline"]["ecl_base_sar"] != result["baseline"]["ecl_final_sar"]

    def test_the_overlay_is_zero_so_final_equals_weighted(self, snapshot, cfg):
        assert float(cfg.ecl["management_overlay_sar"]) == 0.0
        assert snapshot["ecl_final_sar"].sum() == pytest.approx(
            snapshot["ecl_weighted_sar"].sum(), abs=1e-6)


class TestTheGridIsDerivedNotAsserted:
    def test_the_published_weights_are_six_two_two(self, snapshot):
        weights = snapshot[["scenario_weight_base", "scenario_weight_upturn",
                            "scenario_weight_downturn"]].drop_duplicates()
        assert len(weights) == 1
        assert weights.iloc[0].tolist() == [0.6, 0.2, 0.2]

    @pytest.mark.parametrize("column", ["ecl_base_sar", "ecl_upturn_sar",
                                        "ecl_downturn_sar"])
    def test_each_scenario_ecl_is_published_on_the_halala(self, snapshot, column):
        values = snapshot[column].to_numpy()
        off = np.abs(np.round(values / 0.01) * 0.01 - values)
        assert off.max() < 1e-9

    def test_the_weighted_allowance_lands_on_the_two_millihalala_grid(self, snapshot):
        """0.6a + 0.2b + 0.2c over multiples of 0.01 is a multiple of 0.002."""
        values = snapshot["ecl_final_sar"].to_numpy()
        off = np.abs(np.round(values / 0.002) * 0.002 - values)
        assert off.max() < 1e-9, "the published allowance left the 0.002 grid"
        # And it is genuinely finer than the halala: some row is NOT on 0.01.
        coarse = np.abs(np.round(values / 0.01) * 0.01 - values)
        assert coarse.max() > 1e-9

    def test_the_weighted_value_is_the_exact_combination_of_the_published_ones(
            self, snapshot):
        rebuilt = sum(snapshot[f"ecl_{s}_sar"].to_numpy()
                      * snapshot[f"scenario_weight_{s}"].to_numpy()
                      for s in ecl_mod.SCENARIOS)
        assert np.abs(rebuilt - snapshot["ecl_weighted_sar"].to_numpy()).max() < 1e-9


class TestANeutralRebuildReproducesThePublishedBookExactly:
    def test_every_scenario_ecl_reproduces_row_for_row(self, retail_book, snapshot, cfg):
        """The engine was never the problem: the per-scenario figures matched."""
        personal = snapshot[snapshot["product_code"] == REPORTED_POPULATION]
        scenario = wif.Scenario(
            name="n", dataset_version=retail_book.manifest["dataset_version"],
            snapshot_date=str(snapshot["snapshot_date"].iloc[0]),
            filters={"product_code": REPORTED_POPULATION})
        weights = {s: float(cfg.scenarios.weights[s]) for s in ecl_mod.SCENARIOS}
        out = wif._recompute(personal, scenario, weights)
        for s in ecl_mod.SCENARIOS:
            diff = out[f"ecl_{s}"] - personal[f"ecl_{s}_sar"].to_numpy()
            assert np.abs(diff).max() == 0.0, f"ecl_{s} did not reproduce"

    def test_the_reported_residual_is_now_zero_on_every_row(
            self, retail_book, snapshot, cfg):
        result = _neutral(retail_book, snapshot, cfg, product_code=REPORTED_POPULATION)
        parity = result["parity"]
        assert parity["total_residual_sar"] == 0.0
        assert parity["max_facility_residual_sar"] == 0.0
        assert parity["facilities_outside_tolerance"] == 0

    def test_it_is_zero_because_the_arithmetic_matches_not_because_of_rounding(
            self, retail_book, snapshot, cfg):
        """The rebuild must not round the weighted or final allowance at all."""
        personal = snapshot[snapshot["product_code"] == REPORTED_POPULATION]
        scenario = wif.Scenario(
            name="n", dataset_version=retail_book.manifest["dataset_version"],
            snapshot_date=str(snapshot["snapshot_date"].iloc[0]),
            filters={"product_code": REPORTED_POPULATION})
        weights = {s: float(cfg.scenarios.weights[s]) for s in ecl_mod.SCENARIOS}
        out = wif._recompute(personal, scenario, weights)
        final = out["ecl_final"]
        # If the rebuild snapped to the halala, no row could sit between two
        # halala points — and the published book has such rows.
        off_halala = np.abs(np.round(final / 0.01) * 0.01 - final)
        assert off_halala.max() > 1e-9, (
            "the rebuild is rounding to the halala again; that is the defect "
            "that produced the SAR 0.52 residual")

    def test_the_tolerance_is_a_guard_and_has_not_been_widened(self):
        assert wif.PARITY_PER_FACILITY_SAR == 0.01
        assert wif.PARITY_RELATIVE_TOTAL == 1e-6

    def test_the_old_residual_is_reproduced_by_the_old_arithmetic(
            self, retail_book, snapshot, cfg):
        """The diagnosis, proved: put the rounding back and SAR 0.52 returns."""
        personal = snapshot[snapshot["product_code"] == REPORTED_POPULATION]
        scenario = wif.Scenario(
            name="n", dataset_version=retail_book.manifest["dataset_version"],
            snapshot_date=str(snapshot["snapshot_date"].iloc[0]),
            filters={"product_code": REPORTED_POPULATION})
        weights = {s: float(cfg.scenarios.weights[s]) for s in ecl_mod.SCENARIOS}
        out = wif._recompute(personal, scenario, weights)
        as_it_was = np.round(out["ecl_final"], 2)
        residual = as_it_was.sum() - personal["ecl_final_sar"].sum()
        assert residual == pytest.approx(-0.52, abs=0.01)

    def test_the_net_hid_per_row_error_thirty_four_times_its_size(
            self, retail_book, snapshot, cfg):
        """Why the small aggregate was never evidence for the explanation."""
        personal = snapshot[snapshot["product_code"] == REPORTED_POPULATION]
        scenario = wif.Scenario(
            name="n", dataset_version=retail_book.manifest["dataset_version"],
            snapshot_date=str(snapshot["snapshot_date"].iloc[0]),
            filters={"product_code": REPORTED_POPULATION})
        weights = {s: float(cfg.scenarios.weights[s]) for s in ecl_mod.SCENARIOS}
        rows = (np.round(wif._recompute(personal, scenario, weights)["ecl_final"], 2)
                - personal["ecl_final_sar"].to_numpy())
        assert np.abs(rows).sum() == pytest.approx(17.86, abs=0.05)
        assert abs(rows.sum()) == pytest.approx(0.52, abs=0.01)
        assert (rows > 0).sum() > 0 and (rows < 0).sum() > 0
        # The mechanism's own bound: half of 0.01 minus the 0.002 offset.
        assert np.abs(rows).max() == pytest.approx(0.004, abs=1e-9)


class TestParityHoldsAcrossPopulationsAndMonths:
    @pytest.mark.parametrize("product", ["PERSONAL_LOAN", "AUTO_LOAN",
                                         "HOME_LOAN", "CREDIT_CARD"])
    def test_every_product_reproduces_exactly(self, retail_book, snapshot, cfg, product):
        parity = _neutral(retail_book, snapshot, cfg,
                          product_code=product)["parity"]
        assert parity["total_residual_sar"] == 0.0
        assert parity["max_facility_residual_sar"] == 0.0

    @pytest.mark.parametrize("stage", [1, 2, 3])
    def test_every_stage_reproduces_exactly(self, retail_book, snapshot, cfg, stage):
        result = _neutral(retail_book, snapshot, cfg, ifrs9_stage=stage)
        if result.get("population_empty"):
            pytest.skip(f"no stage {stage} facility at {REPORTED_MONTH}")
        assert result["parity"]["total_residual_sar"] == 0.0

    def test_the_whole_book_reproduces_exactly(self, retail_book, snapshot, cfg):
        parity = _neutral(retail_book, snapshot, cfg)["parity"]
        assert parity["total_residual_sar"] == 0.0
        assert parity["rebuilt_ecl_final_sar"] == pytest.approx(
            snapshot["ecl_final_sar"].sum(), abs=0.005)

    def test_the_first_and_last_published_months_both_reproduce(
            self, retail_book, cfg):
        for month in (retail_book.months()[0], retail_book.months()[-1]):
            frame = retail_book.month(month)
            parity = _neutral(retail_book, frame, cfg)["parity"]
            assert parity["total_residual_sar"] == 0.0, month

    def test_a_short_life_population_reproduces_exactly(
            self, retail_book, snapshot, cfg):
        """Zero and near-zero remaining life is where a horizon bug would show."""
        short = snapshot[snapshot["ecl_remaining_life_months"] <= 1]
        if short.empty:
            pytest.skip("no short-life facility at this month")
        parity = _neutral(retail_book, short, cfg)["parity"]
        assert parity["total_residual_sar"] == 0.0


class TestExportsCarryTheSamePrecisionAndScopeAsTheScreen:
    def test_the_export_and_the_screen_read_the_same_stored_run(self):
        """A saved run is exported from its own stored figures, never recomputed."""
        import inspect

        from backend.api.routers import retail as router

        source = inspect.getsource(router.whatif_export)
        assert "wif.run(" not in source, (
            "an export that recomputes can disagree with the screen it came from")
