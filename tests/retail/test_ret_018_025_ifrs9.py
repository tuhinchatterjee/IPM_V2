"""Gates RET-018 to RET-025 — scenario identities, PD curves, stages, fixtures, reconciliation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.retail import ecl as ecl_mod
from backend.retail.config import load_config
from backend.retail.policy import STAGING_POLICY

#: Row-level rounding tolerance. Each scenario ECL is stored rounded to the
#: halala, so a weighted combination of three rounded numbers can differ from
#: the rounded weighted number by a fraction of a halala.
ROW_TOLERANCE_SAR = 0.001


def _fixture(pd12: float, *, ead=10_000.0, lgd=0.50, stage=1, months=12, rate=0.0):
    hazard = ecl_mod.constant_hazard_from_pd12(np.array([pd12]))[:, None] * np.ones((1, months))
    return ecl_mod.EclInputs(
        stage=np.array([stage]),
        ead_path=np.full((1, months), ead),
        hazard_path=hazard,
        lgd=np.array([lgd]),
        monthly_discount_rate=np.array([rate]),
        remaining_life_months=np.array([months]),
        gross_carrying_amount=np.array([ead]),
        stage3_recovery_rate_nominal=np.array([0.0]),
        stage3_delay_months=np.array([0.0]),
    )


class TestRET018WeightedIdentity:
    def test_weights_are_valid(self, retail_book):
        latest = retail_book.latest()
        total = (latest["scenario_weight_base"] + latest["scenario_weight_upturn"]
                 + latest["scenario_weight_downturn"])
        assert float((total - 1.0).abs().max()) < 1e-9
        for c in ("scenario_weight_base", "scenario_weight_upturn", "scenario_weight_downturn"):
            assert (latest[c] >= 0).all() and (latest[c] <= 1).all()

    def test_row_wise_weighted_identity(self, retail_book):
        latest = retail_book.latest()
        expected = (latest["scenario_weight_base"] * latest["ecl_base_sar"]
                    + latest["scenario_weight_upturn"] * latest["ecl_upturn_sar"]
                    + latest["scenario_weight_downturn"] * latest["ecl_downturn_sar"])
        assert float((latest["ecl_weighted_sar"] - expected).abs().max()) <= ROW_TOLERANCE_SAR

    def test_aggregate_weighted_identity(self, retail_book):
        cols = ["ecl_base_sar", "ecl_upturn_sar", "ecl_downturn_sar", "ecl_weighted_sar"]
        for m in retail_book.months():
            f = retail_book.month(m, cols)
            expected = (0.60 * f["ecl_base_sar"].sum() + 0.20 * f["ecl_upturn_sar"].sum()
                        + 0.20 * f["ecl_downturn_sar"].sum())
            assert f["ecl_weighted_sar"].sum() == pytest.approx(expected, abs=1.0), m

    def test_overlay_is_separate_and_visible(self, retail_book):
        latest = retail_book.latest()
        expected = latest["ecl_weighted_sar"] + latest["management_overlay_sar"]
        assert float((latest["ecl_final_sar"] - expected).abs().max()) <= 0.01
        assert "management_overlay_sar" in latest.columns

    def test_invalid_weights_are_refused_not_normalised(self):
        with pytest.raises(ValueError, match="not 1.0"):
            ecl_mod.weighted_ecl(
                {s: np.array([1.0]) for s in ecl_mod.SCENARIOS},
                {"base": 0.5, "upturn": 0.2, "downturn": 0.2})

    def test_coverage_ratio_is_defined_not_infinite(self, retail_book):
        latest = retail_book.latest()
        ratio = latest["ecl_coverage_ratio"]
        assert not np.isinf(ratio.dropna().to_numpy()).any()
        zero_exposure = latest[latest["gross_carrying_amount_sar"] == 0]
        if len(zero_exposure):
            assert zero_exposure["ecl_coverage_ratio"].isna().all()


class TestRET019ScenarioOrdering:
    def test_row_wise_ordering_holds_in_every_month(self, retail_book):
        cols = ["ecl_upturn_sar", "ecl_base_sar", "ecl_downturn_sar"]
        for m in retail_book.months():
            f = retail_book.month(m, cols)
            bad = ((f["ecl_upturn_sar"] > f["ecl_base_sar"] + ROW_TOLERANCE_SAR)
                   | (f["ecl_base_sar"] > f["ecl_downturn_sar"] + ROW_TOLERANCE_SAR))
            assert int(bad.sum()) == 0, f"{m}: {int(bad.sum())} rows out of order"

    def test_ordering_comes_from_ordered_inputs_not_sorted_outputs(self, retail_book):
        latest = retail_book.latest()
        performing = latest[latest["ifrs9_stage"] < 3]
        assert (performing["pd_pit_12m_upturn"] <= performing["pd_pit_12m_base"] + 1e-12).all()
        assert (performing["pd_pit_12m_base"] <= performing["pd_pit_12m_downturn"] + 1e-12).all()
        assert (performing["lgd_upturn"] <= performing["lgd_base"] + 1e-12).all()
        assert (performing["lgd_base"] <= performing["lgd_downturn"] + 1e-12).all()

    def test_the_multipliers_themselves_are_ordered(self):
        s = load_config().scenarios
        s.validate()
        assert s.hazard_multiplier["upturn"] < s.hazard_multiplier["base"] < s.hazard_multiplier["downturn"]


class TestRET020PdCurves:
    def test_marginal_probabilities_sum_to_the_stated_twelve_month_pd(self):
        for p in (0.001, 0.02, 0.15, 0.5, 0.95):
            h = ecl_mod.constant_hazard_from_pd12(np.array([p]))[:, None] * np.ones((1, 12))
            _, marginal = ecl_mod.survival_and_marginal(h)
            assert marginal.sum() == pytest.approx(p, abs=1e-12)

    def test_survival_is_not_double_counted(self):
        h = np.full((1, 24), 0.03)
        surv_before, marginal = ecl_mod.survival_and_marginal(h)
        assert surv_before[0, 0] == pytest.approx(1.0)
        for t in range(1, 24):
            assert surv_before[0, t] == pytest.approx(surv_before[0, t - 1] * (1 - h[0, t - 1]))
        assert marginal.sum() <= 1.0 + 1e-12

    def test_probabilities_stay_in_range_at_the_extremes(self):
        for p in (0.0, 1e-12, 1 - 1e-9):
            h = ecl_mod.constant_hazard_from_pd12(np.array([p]))
            assert 0.0 <= float(h[0]) <= 1.0

    def test_lifetime_is_at_least_the_capped_twelve_month_measure(self, retail_book):
        latest = retail_book.latest()
        performing = latest[latest["ifrs9_stage"] < 3]
        assert (performing["pd_pit_lifetime_base"]
                >= performing["pd_pit_12m_base"] - 1e-9).all()

    def test_short_life_facilities_use_a_capped_measure(self, retail_book):
        latest = retail_book.latest()
        # Performing facilities only: a Stage 3 horizon is the recovery delay,
        # which is a different measure and can outlast a short remaining life.
        latest = latest[latest["ifrs9_stage"] < 3]
        short = latest[pd.to_numeric(latest["ecl_expected_life_months"]) < 12]
        if len(short):
            # For a life shorter than twelve months the two measures coincide,
            # because both count default events over the same shorter window.
            diff = (pd.to_numeric(short["pd_pit_lifetime_base"])
                    - pd.to_numeric(short["pd_pit_12m_base"])).abs()
            assert float(diff.max()) < 1e-9
            assert (pd.to_numeric(short["ecl_horizon_months"])
                    <= pd.to_numeric(short["ecl_expected_life_months"])).all()


class TestRET021StageHorizons:
    def test_stage_one_counts_twelve_months_of_default_events(self):
        r = ecl_mod.compute_ecl(_fixture(0.02, stage=1, months=36))
        assert int(r.horizon_months[0]) == 12
        assert r.horizon_type[0] == "TWELVE_MONTH_OR_SHORTER_LIFE"

    def test_stage_one_does_not_truncate_the_loss_from_those_defaults(self):
        """LGD embeds recoveries discounted to the default date, so a long
        recovery is fully costed even though the default window is 12 months."""
        fast = ecl_mod.lgd_from_recovery(np.array([0.6]), np.array([3.0]), np.array([0.005]))
        slow = ecl_mod.lgd_from_recovery(np.array([0.6]), np.array([36.0]), np.array([0.005]))
        assert slow[0] > fast[0], "a longer recovery must cost more, not be cut off at month 12"

    def test_stage_two_uses_the_remaining_life(self):
        r = ecl_mod.compute_ecl(_fixture(0.02, stage=2, months=36))
        assert int(r.horizon_months[0]) == 36
        assert r.horizon_type[0] == "REMAINING_LIFETIME"

    def test_stage_two_costs_more_than_stage_one_on_the_same_facility(self):
        one = ecl_mod.compute_ecl(_fixture(0.02, stage=1, months=36)).ecl[0]
        two = ecl_mod.compute_ecl(_fixture(0.02, stage=2, months=36)).ecl[0]
        assert two > one

    def test_stage_three_is_a_recovery_calculation_not_a_hazard_one(self):
        inp = _fixture(0.02, stage=3, months=36)
        inp = ecl_mod.EclInputs(
            **{**inp.__dict__,
               "stage3_recovery_rate_nominal": np.array([0.40]),
               "stage3_delay_months": np.array([12.0]),
               "monthly_discount_rate": np.array([0.005])})
        r = ecl_mod.compute_ecl(inp)
        expected = 10_000.0 - 10_000.0 * 0.40 * (1.005 ** -12)
        assert r.ecl[0] == pytest.approx(expected, abs=1e-6)
        assert r.horizon_type[0] == "STAGE3_RECOVERY"
        assert r.pd_12m[0] == 1.0, "a defaulted facility's PD is one by reporting convention"

    def test_revolving_life_is_behavioural_not_contractual(self, retail_book):
        latest = retail_book.latest()
        cards = latest[latest["product_code"] == "CREDIT_CARD"]
        life = pd.to_numeric(cards["behavioural_expected_life_months"]).dropna()
        assert (life > 12).all(), (
            "a credit card must not be assumed to have a fixed twelve-month life"
        )
        assert life.nunique() == 1


class TestRET022StagePolicy:
    def test_stage_three_matches_the_default_flag(self, retail_book):
        latest = retail_book.latest()
        assert ((latest["ifrs9_stage"] == 3) == latest["current_default_flag"]).all()

    def test_every_stage_two_row_has_at_least_one_reason(self, retail_book):
        latest = retail_book.latest()
        s2 = latest[latest["ifrs9_stage"] == 2]
        assert s2["sicr_reason"].notna().all()
        assert (s2["sicr_quantitative_flag"] | s2["sicr_qualitative_flag"]
                | s2["sicr_dpd_backstop_flag"]).all()

    def test_stage_two_is_reachable_before_arrears(self, retail_book):
        latest = retail_book.latest()
        early = latest[(latest["ifrs9_stage"] == 2) & (latest["dpd"] < 30)]
        assert len(early) > 0, "SICR evidence must be able to stage a current facility"

    def test_stage_three_is_reachable_before_ninety_days(self, retail_book):
        latest = retail_book.latest()
        utp = latest[(latest["ifrs9_stage"] == 3) & (latest["dpd"] < 90)]
        assert len(utp) > 0, "unlikeliness to pay must be able to impair before the backstop"
        assert utp["unlikeliness_to_pay_flag"].all()
        assert (utp["default_reason"] == "UNLIKELINESS_TO_PAY").all()

    def test_the_dpd_backstop_is_never_missed(self, retail_book):
        latest = retail_book.latest()
        over = latest[latest["dpd"] >= STAGING_POLICY.stage2_dpd_backstop]
        assert (over["ifrs9_stage"] >= 2).all()
        assert over["sicr_dpd_backstop_flag"].all()

    def test_sicr_compares_like_horizons(self, retail_book):
        latest = retail_book.latest()
        performing = latest[latest["ifrs9_stage"] < 3]
        ratio = pd.to_numeric(performing["sicr_pd_ratio"]).dropna()
        assert (ratio > 0).all()
        # The ratio's numerator and denominator are both remaining-life measures.
        assert "pd_origination_curve_remaining_life" in latest.columns

    def test_policy_version_travels_with_the_decision(self, retail_book):
        latest = retail_book.latest()
        assert (latest["staging_policy_version"] == STAGING_POLICY.version).all()
        assert latest["default_definition_id"].nunique() == 1

    def test_a_cured_facility_keeps_its_default_history(self, retail_book):
        latest = retail_book.latest()
        cured = latest[latest["cure_flag"].fillna(False) & ~latest["current_default_flag"]]
        if len(cured):
            assert cured["first_default_date"].notna().all(), (
                "curing ends the default state; it does not erase that it happened"
            )


class TestRET023GoldenFixtures:
    def test_the_specification_fixture(self):
        """EAD 10,000, LGD 0.50, zero discount, PDs 2%/1.5%/3%, weights 60/20/20."""
        base = ecl_mod.compute_ecl(_fixture(0.020)).ecl[0]
        up = ecl_mod.compute_ecl(_fixture(0.015)).ecl[0]
        down = ecl_mod.compute_ecl(_fixture(0.030)).ecl[0]
        assert base == pytest.approx(100.0, abs=1e-9)
        assert up == pytest.approx(75.0, abs=1e-9)
        assert down == pytest.approx(150.0, abs=1e-9)
        weighted = ecl_mod.weighted_ecl(
            {"base": np.array([base]), "upturn": np.array([up]), "downturn": np.array([down])},
            {"base": 0.60, "upturn": 0.20, "downturn": 0.20})
        assert weighted[0] == pytest.approx(105.0, abs=1e-9)

    def test_overlay_fixture(self):
        assert ecl_mod.final_ecl(np.array([105.0]), np.array([12.5]))[0] == pytest.approx(117.5)

    def test_discounting_fixture(self):
        """One certain default in month 12 at a 6% annual effective rate."""
        h = np.zeros((1, 12)); h[0, 11] = 1.0
        inp = ecl_mod.EclInputs(
            stage=np.array([1]), ead_path=np.full((1, 12), 1_000.0), hazard_path=h,
            lgd=np.array([1.0]),
            monthly_discount_rate=ecl_mod.monthly_rate(np.array([0.06])),
            remaining_life_months=np.array([12]),
            gross_carrying_amount=np.array([1_000.0]),
            stage3_recovery_rate_nominal=np.array([0.0]),
            stage3_delay_months=np.array([0.0]))
        assert ecl_mod.compute_ecl(inp).ecl[0] == pytest.approx(1_000.0 / 1.06, abs=1e-6)

    def test_lifetime_fixture(self):
        """Constant hazard over 24 months costs more than the same over 12."""
        twelve = ecl_mod.compute_ecl(_fixture(0.02, stage=2, months=12)).ecl[0]
        h = ecl_mod.constant_hazard_from_pd12(np.array([0.02]))[:, None] * np.ones((1, 24))
        inp = ecl_mod.EclInputs(
            stage=np.array([2]), ead_path=np.full((1, 24), 10_000.0), hazard_path=h,
            lgd=np.array([0.5]), monthly_discount_rate=np.array([0.0]),
            remaining_life_months=np.array([24]),
            gross_carrying_amount=np.array([10_000.0]),
            stage3_recovery_rate_nominal=np.array([0.0]),
            stage3_delay_months=np.array([0.0]))
        lifetime = ecl_mod.compute_ecl(inp).ecl[0]
        assert lifetime > twelve
        expected = (1 - (1 - 0.02) ** 2) * 10_000.0 * 0.5
        assert lifetime == pytest.approx(expected, abs=1e-6)

    def test_short_life_fixture(self):
        r = ecl_mod.compute_ecl(_fixture(0.02, stage=1, months=5))
        assert int(r.horizon_months[0]) == 5
        expected = (1 - (1 - 0.02) ** (5 / 12)) * 10_000.0 * 0.5
        assert r.ecl[0] == pytest.approx(expected, abs=1e-6)

    def test_recovery_fixture_is_not_discounted_twice(self):
        """LGD discounts to the default date; ECL discounts to the reporting date."""
        rate = ecl_mod.monthly_rate(np.array([0.06]))
        lgd = ecl_mod.lgd_from_recovery(np.array([0.5]), np.array([12.0]), rate)
        expected_lgd = 1 - 0.5 * (1 + rate[0]) ** -12
        assert lgd[0] == pytest.approx(expected_lgd, abs=1e-9)


class TestRET024CrossModuleReconciliation:
    def test_whatif_baseline_equals_the_cockpit_total(self, retail_book):
        from backend.retail import whatif as wif
        latest = retail_book.latest()
        cfg = load_config()
        scenario = wif.Scenario(
            name="reconciliation", dataset_version=retail_book.manifest["dataset_version"],
            snapshot_date=str(latest["snapshot_date"].iloc[0]))
        result = wif.run(latest, scenario, cfg)
        assert result["baseline"]["ecl_final_sar"] == pytest.approx(
            float(latest["ecl_final_sar"].sum()), abs=0.01)
        assert result["baseline"]["gross_carrying_amount_sar"] == pytest.approx(
            float(latest["gross_carrying_amount_sar"].sum()), abs=0.01)

    def test_ews_affected_population_reconciles_with_the_book(self, retail_book):
        from backend.retail import ews
        latest = retail_book.latest()
        alerts = ews.evaluate_snapshot(latest)
        if alerts.empty:
            pytest.skip("no alerts at this snapshot")
        exposure = ews.affected_exposure(alerts)
        assert 0 < exposure <= float(latest["gross_carrying_amount_sar"].sum()) + 0.01

    def test_manifest_totals_match_the_parquet(self, retail_book):
        cols = ["gross_carrying_amount_sar", "ecl_final_sar"]
        for entry in retail_book.manifest["months"]:
            f = retail_book.month(entry["reporting_month"], cols)
            assert float(f["gross_carrying_amount_sar"].sum()) == pytest.approx(
                entry["gross_carrying_amount_sar"], rel=1e-9)
            assert float(f["ecl_final_sar"].sum()) == pytest.approx(
                entry["ecl_final_sar"], rel=1e-9)
            assert len(f) == entry["rows"]

    def test_the_same_filter_gives_the_same_total_everywhere(self, retail_book):
        from backend.retail import whatif as wif
        latest = retail_book.latest()
        direct = float(latest[latest["product_code"] == "CREDIT_CARD"]["ecl_final_sar"].sum())
        through_filter = float(
            wif.select(latest, {"product_code": ["CREDIT_CARD"]})["ecl_final_sar"].sum())
        assert direct == pytest.approx(through_filter, abs=0.01)


class TestRET025EclMovementBridge:
    def test_bridge_reconciles_opening_to_closing(self, retail_book):
        from backend.retail.movement import decompose
        months = retail_book.months()
        opening = retail_book.month(months[-2])
        closing = retail_book.month(months[-1])
        bridge = decompose(opening, closing)
        total = sum(c["amount_sar"] for c in bridge["contributions"])
        assert bridge["opening_ecl_sar"] + total == pytest.approx(
            bridge["closing_ecl_sar"], abs=0.05)

    def test_entrants_and_exits_are_separate_categories(self, retail_book):
        from backend.retail.movement import decompose
        months = retail_book.months()
        bridge = decompose(retail_book.month(months[-2]), retail_book.month(months[-1]))
        names = {c["driver"] for c in bridge["contributions"]}
        assert "New originations" in names
        assert "Exits and closures" in names

    def test_methodology_is_disclosed_and_order_is_published(self, retail_book):
        from backend.retail.movement import decompose
        months = retail_book.months()
        bridge = decompose(retail_book.month(months[-2]), retail_book.month(months[-1]))
        assert bridge["methodology"] == "sequential_replacement"
        assert bridge["replacement_order"]
        assert "order-dependent" in bridge["methodology_note"].lower()
        assert "shapley" not in bridge["methodology"].lower()

    def test_no_unexplained_plug(self, retail_book):
        from backend.retail.movement import decompose
        months = retail_book.months()
        bridge = decompose(retail_book.month(months[-2]), retail_book.month(months[-1]))
        assert bridge["unexplained_residual_sar"] == pytest.approx(0.0, abs=0.05)
