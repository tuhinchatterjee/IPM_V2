"""Gates RET-039 to RET-045 — baseline parity, shock semantics, dependencies, exports."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.retail import whatif as wif
from backend.retail.config import load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def snapshot(retail_book):
    return retail_book.latest()


def _scenario(retail_book, snapshot, **kw):
    return wif.Scenario(
        name=kw.pop("name", "test"),
        dataset_version=retail_book.manifest["dataset_version"],
        snapshot_date=str(snapshot["snapshot_date"].iloc[0]),
        **kw)


class TestRET039NeutralScenarioParity:
    def test_a_neutral_scenario_reproduces_the_baseline(self, retail_book, snapshot, cfg):
        result = wif.run(snapshot, _scenario(retail_book, snapshot, name="neutral"), cfg)
        baseline = result["baseline"]["ecl_final_sar"]
        scenario = result["scenario_result"]["ecl_final_sar"]
        assert scenario == pytest.approx(baseline, rel=1e-6), (
            f"a neutral scenario must reproduce the published allowance: "
            f"{scenario:,.2f} against {baseline:,.2f}"
        )

    def test_the_delta_is_zero(self, retail_book, snapshot, cfg):
        result = wif.run(snapshot, _scenario(retail_book, snapshot, name="neutral"), cfg)
        assert abs(result["delta"]["ecl_final_sar"]) < max(
            1.0, 1e-6 * result["baseline"]["ecl_final_sar"])

    def test_neutral_parity_holds_on_a_filtered_population(self, retail_book, snapshot, cfg):
        for product in ("CREDIT_CARD", "PERSONAL_LOAN", "AUTO_LOAN", "HOME_LOAN"):
            s = _scenario(retail_book, snapshot, filters={"product_code": [product]})
            result = wif.run(snapshot, s, cfg)
            assert result["scenario_result"]["ecl_final_sar"] == pytest.approx(
                result["baseline"]["ecl_final_sar"], rel=1e-6), product

    def test_canonical_data_is_not_mutated(self, retail_book, snapshot, cfg):
        before = snapshot["ecl_final_sar"].sum()
        checksum = pd.util.hash_pandas_object(snapshot["ecl_final_sar"]).sum()
        wif.run(snapshot, _scenario(retail_book, snapshot, shocks={"pd_relative": 0.5}), cfg)
        assert snapshot["ecl_final_sar"].sum() == before
        assert pd.util.hash_pandas_object(snapshot["ecl_final_sar"]).sum() == checksum

    def test_the_baseline_is_the_weighted_allowance_not_the_base_scenario(
            self, retail_book, snapshot, cfg):
        result = wif.run(snapshot, _scenario(retail_book, snapshot), cfg)
        assert result["baseline"]["ecl_final_sar"] != result["baseline"]["ecl_base_sar"]
        assumption = " ".join(result["assumptions"])
        assert "not its BASE macroeconomic scenario" in assumption


class TestRET040ShockSemantics:
    def test_relative_and_percentage_point_shocks_differ(self, retail_book, snapshot, cfg):
        rel = wif.run(snapshot, _scenario(retail_book, snapshot,
                                          shocks={"pd_relative": 0.20}), cfg)
        abs_ = wif.run(snapshot, _scenario(retail_book, snapshot,
                                           shocks={"pd_absolute_pp": 2.0}), cfg)
        assert rel["scenario_result"]["ecl_final_sar"] != abs_["scenario_result"]["ecl_final_sar"]

    def test_relative_twenty_percent_on_two_percent_gives_two_point_four(self):
        anchor = np.array([0.02])
        assert float(anchor * 1.20) == pytest.approx(0.024)

    def test_absolute_two_points_on_two_percent_gives_four(self):
        anchor = np.array([0.02])
        assert float(anchor + 2.0 / 100.0) == pytest.approx(0.04)

    def test_a_pd_increase_raises_ecl_for_performing_facilities(self, retail_book, snapshot, cfg):
        performing = snapshot[snapshot["ifrs9_stage"] < 3]
        base = wif.run(performing, _scenario(retail_book, snapshot), cfg)
        up = wif.run(performing, _scenario(retail_book, snapshot,
                                           shocks={"pd_relative": 0.20}), cfg)
        assert up["scenario_result"]["ecl_final_sar"] > base["scenario_result"]["ecl_final_sar"]

    def test_the_shock_propagates_through_the_whole_curve_not_one_scalar(
            self, retail_book, snapshot, cfg):
        """A Stage 2 facility's lifetime ECL must respond, not only a 12-month number."""
        stage2 = snapshot[snapshot["ifrs9_stage"] == 2]
        if stage2.empty:
            pytest.skip("no Stage 2 facilities")
        base = wif.run(stage2, _scenario(retail_book, snapshot), cfg)
        up = wif.run(stage2, _scenario(retail_book, snapshot,
                                       shocks={"pd_relative": 0.20}), cfg)
        change = (up["scenario_result"]["ecl_final_sar"]
                  / base["scenario_result"]["ecl_final_sar"]) - 1
        assert change > 0.10, (
            "a 20% relative PD shock on lifetime exposure should move lifetime ECL "
            f"materially; it moved {change:.2%}"
        )

    def test_utilisation_moves_in_percentage_points_and_only_for_cards(
            self, retail_book, snapshot, cfg):
        cards = snapshot[snapshot["product_code"] == "CREDIT_CARD"]
        loans = snapshot[snapshot["product_code"] == "PERSONAL_LOAN"]
        card_shift = wif.run(cards, _scenario(retail_book, snapshot,
                                              shocks={"utilisation_pp": 20.0}), cfg)
        loan_shift = wif.run(loans, _scenario(retail_book, snapshot,
                                              shocks={"utilisation_pp": 20.0}), cfg)
        assert (card_shift["scenario_result"]["gross_carrying_amount_sar"]
                > card_shift["baseline"]["gross_carrying_amount_sar"])
        assert loan_shift["scenario_result"]["gross_carrying_amount_sar"] == pytest.approx(
            loan_shift["baseline"]["gross_carrying_amount_sar"], rel=1e-9)


class TestRET041Reweighting:
    def test_reweighting_recomputes_the_weighted_identity(self, retail_book, snapshot, cfg):
        weights = {"base": 0.50, "upturn": 0.10, "downturn": 0.40}
        result = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             scenario_weights=weights), cfg)
        expected = (weights["base"] * float(snapshot["ecl_base_sar"].sum())
                    + weights["upturn"] * float(snapshot["ecl_upturn_sar"].sum())
                    + weights["downturn"] * float(snapshot["ecl_downturn_sar"].sum()))
        assert result["scenario_result"]["ecl_weighted_sar"] == pytest.approx(expected, rel=1e-6)

    def test_a_heavier_downturn_weight_raises_the_allowance(self, retail_book, snapshot, cfg):
        heavy = wif.run(snapshot, _scenario(
            retail_book, snapshot,
            scenario_weights={"base": 0.40, "upturn": 0.10, "downturn": 0.50}), cfg)
        assert (heavy["scenario_result"]["ecl_final_sar"]
                > heavy["baseline"]["ecl_final_sar"])

    def test_weights_that_do_not_sum_to_one_are_refused(self, retail_book, snapshot):
        s = _scenario(retail_book, snapshot,
                      scenario_weights={"base": 0.5, "upturn": 0.2, "downturn": 0.2})
        with pytest.raises(ValueError, match="not 1.0"):
            s.validate()

    def test_a_negative_weight_is_refused(self, retail_book, snapshot):
        s = _scenario(retail_book, snapshot,
                      scenario_weights={"base": 1.2, "upturn": -0.1, "downturn": -0.1})
        with pytest.raises(ValueError, match="outside"):
            s.validate()

    def test_an_unknown_methodology_lists_the_supported_ones(self, retail_book, snapshot):
        s = _scenario(retail_book, snapshot, shocks={"rating_notch_migration": 2})
        with pytest.raises(wif.UnsupportedShock) as e:
            s.validate()
        message = str(e.value)
        assert "not a supported retail What-If methodology" in message
        assert "pd_relative" in message
        assert "scenario_weights" in message

    def test_an_invalid_staging_mode_is_refused_with_the_distinction_explained(
            self, retail_book, snapshot):
        s = _scenario(retail_book, snapshot, staging_mode="whatever")
        with pytest.raises(ValueError, match="parameter sensitivity"):
            s.validate()


class TestRET042Dependencies:
    def test_an_income_shock_reaches_ecl(self, retail_book, snapshot, cfg):
        result = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             shocks={"income_pct": -0.15}), cfg)
        assert result["scenario_result"]["ecl_final_sar"] > result["baseline"]["ecl_final_sar"]

    def test_an_income_shock_does_not_touch_origination_values(self, retail_book, snapshot, cfg):
        before = snapshot["application_score_at_origination"].copy()
        wif.run(snapshot, _scenario(retail_book, snapshot, shocks={"income_pct": -0.15}), cfg)
        assert snapshot["application_score_at_origination"].equals(before)

    def test_the_limitation_says_so_explicitly(self, retail_book, snapshot, cfg):
        result = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             shocks={"income_pct": -0.15}), cfg)
        text = " ".join(result["limitations"])
        assert "does NOT change the application score" in text
        assert "bureau score at origination" in text

    def test_two_shocks_are_not_applied_twice_over(self, retail_book, snapshot, cfg):
        once = wif.run(snapshot, _scenario(retail_book, snapshot,
                                           shocks={"pd_relative": 0.20}), cfg)
        combined = wif.run(snapshot, _scenario(
            retail_book, snapshot,
            shocks={"pd_relative": 0.20, "lgd_relative": 0.10}), cfg)
        # The combination must exceed each single shock but fall far short of
        # applying the PD shock twice.
        double = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             shocks={"pd_relative": 0.44}), cfg)
        assert (once["scenario_result"]["ecl_final_sar"]
                < combined["scenario_result"]["ecl_final_sar"]
                < double["scenario_result"]["ecl_final_sar"])

    def test_a_behavioural_score_shift_reaches_pd_through_the_mapping(
            self, retail_book, snapshot, cfg):
        worse = wif.run(snapshot, _scenario(retail_book, snapshot,
                                            shocks={"behavioural_score_points": -50}), cfg)
        better = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             shocks={"behavioural_score_points": 50}), cfg)
        assert (worse["scenario_result"]["ecl_final_sar"]
                > better["scenario_result"]["ecl_final_sar"])

    def test_frozen_and_reevaluated_staging_are_distinguished(self, retail_book, snapshot, cfg):
        frozen = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             shocks={"pd_relative": 1.5},
                                             staging_mode=wif.FROZEN_STAGE), cfg)
        moving = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             shocks={"pd_relative": 1.5},
                                             staging_mode=wif.REEVALUATE_STAGE), cfg)
        assert (frozen["scenario_result"]["stage_counts"]
                != moving["scenario_result"]["stage_counts"]), (
            "re-evaluated staging must be able to migrate facilities"
        )
        assert (moving["scenario_result"]["ecl_final_sar"]
                > frozen["scenario_result"]["ecl_final_sar"])


class TestRET043ProductSemantics:
    def test_a_defaulted_facility_does_not_respond_to_a_pd_shock(self, retail_book, snapshot, cfg):
        stage3 = snapshot[snapshot["ifrs9_stage"] == 3]
        if stage3.empty:
            pytest.skip("no Stage 3 facilities")
        result = wif.run(stage3, _scenario(retail_book, snapshot,
                                           shocks={"pd_relative": 1.0}), cfg)
        assert result["scenario_result"]["ecl_final_sar"] == pytest.approx(
            result["baseline"]["ecl_final_sar"], rel=1e-6)
        assert any("already credit-impaired" in x for x in result["limitations"])

    def test_a_defaulted_facility_does_respond_to_a_recovery_shock(
            self, retail_book, snapshot, cfg):
        stage3 = snapshot[snapshot["ifrs9_stage"] == 3]
        if stage3.empty:
            pytest.skip("no Stage 3 facilities")
        result = wif.run(stage3, _scenario(retail_book, snapshot,
                                           shocks={"recovery_delay_months": 6}), cfg)
        assert result["scenario_result"]["ecl_final_sar"] > result["baseline"]["ecl_final_sar"]

    def test_collateral_shock_moves_secured_products_only(self, retail_book, snapshot, cfg):
        secured = snapshot[snapshot["secured_flag"].fillna(False)]
        unsecured = snapshot[~snapshot["secured_flag"].fillna(False)]
        s = wif.run(secured, _scenario(retail_book, snapshot,
                                       shocks={"collateral_value_pct": -0.10}), cfg)
        u = wif.run(unsecured, _scenario(retail_book, snapshot,
                                         shocks={"collateral_value_pct": -0.10}), cfg)
        assert s["scenario_result"]["ecl_final_sar"] > s["baseline"]["ecl_final_sar"]
        assert u["scenario_result"]["ecl_final_sar"] == pytest.approx(
            u["baseline"]["ecl_final_sar"], rel=1e-6)

    def test_a_short_life_facility_is_not_given_a_longer_horizon(self, retail_book, snapshot, cfg):
        short = snapshot[pd.to_numeric(snapshot["ecl_expected_life_months"]) <= 6]
        if short.empty:
            pytest.skip("no short-life facilities")
        result = wif.run(short, _scenario(retail_book, snapshot), cfg)
        assert result["scenario_result"]["ecl_final_sar"] == pytest.approx(
            result["baseline"]["ecl_final_sar"], rel=1e-6)


class TestRET044BookedOnlyCutoff:
    def test_the_replay_is_labelled_booked_only(self, snapshot):
        result = wif.cutoff_replay(snapshot, {
            "CREDIT_CARD": 600.0, "PERSONAL_LOAN": 620.0,
            "AUTO_LOAN": 610.0, "HOME_LOAN": 640.0})
        assert result["population"] == "BOOKED_ORIGINATIONS_ONLY"

    def test_a_tighter_cutoff_excludes_real_booked_accounts(self, snapshot):
        result = wif.cutoff_replay(snapshot, {
            "CREDIT_CARD": 600.0, "PERSONAL_LOAN": 620.0,
            "AUTO_LOAN": 610.0, "HOME_LOAN": 640.0})
        assert result["would_be_excluded"] > 0
        assert result["excluded_exposure_sar"] > 0

    def test_no_rejected_applicant_outcome_is_invented(self, snapshot):
        result = wif.cutoff_replay(snapshot, {p: 600.0 for p in
                                              ("CREDIT_CARD", "PERSONAL_LOAN",
                                               "AUTO_LOAN", "HOME_LOAN")})
        keys = " ".join(result.keys()).lower()
        assert "rejected" not in keys
        assert "future_approval_rate" not in keys
        assert "loss_avoided" not in keys

    def test_the_limitations_are_explicit(self, snapshot):
        result = wif.cutoff_replay(snapshot, {p: 600.0 for p in
                                              ("CREDIT_CARD", "PERSONAL_LOAN",
                                               "AUTO_LOAN", "HOME_LOAN")})
        text = " ".join(result["limitations"]).lower()
        assert "not the bank's future approval rate" in text
        assert "descriptive, not causal" in text
        assert "declined" in text
        assert "lower cutoff cannot be evaluated" in text


class TestRET045SavedScenariosAndExports:
    def test_a_run_id_is_deterministic_for_the_same_definition(self, retail_book, snapshot):
        a = _scenario(retail_book, snapshot, name="s", shocks={"pd_relative": 0.2})
        b = _scenario(retail_book, snapshot, name="s", shocks={"pd_relative": 0.2})
        assert a.run_id() == b.run_id()

    def test_a_different_definition_gives_a_different_run_id(self, retail_book, snapshot):
        a = _scenario(retail_book, snapshot, name="s", shocks={"pd_relative": 0.2})
        b = _scenario(retail_book, snapshot, name="s", shocks={"pd_relative": 0.3})
        assert a.run_id() != b.run_id()

    def test_a_saved_scenario_reloads_to_the_same_numbers(self, retail_book, snapshot, cfg):
        original = _scenario(retail_book, snapshot, name="saved",
                             shocks={"pd_relative": 0.2, "lgd_relative": 0.05},
                             filters={"product_code": ["PERSONAL_LOAN"]})
        first = wif.run(snapshot, original, cfg)
        stored = json.loads(json.dumps(original.to_dict()))
        reloaded = wif.Scenario(
            name=stored["name"], dataset_version=stored["dataset_version"],
            snapshot_date=stored["snapshot_date"], filters=stored["filters"],
            shocks=stored["shocks"], staging_mode=stored["staging_mode"],
            scenario_weights=stored["scenario_weights"])
        second = wif.run(snapshot, reloaded, cfg)
        assert second["scenario_result"] == first["scenario_result"]
        assert reloaded.run_id() == original.run_id()

    def test_the_result_pins_its_inputs(self, retail_book, snapshot, cfg):
        result = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             shocks={"pd_relative": 0.2}), cfg)
        evidence = result["evidence"]
        assert evidence["dataset_version"] == retail_book.manifest["dataset_version"]
        assert evidence["snapshot_date"] == str(snapshot["snapshot_date"].iloc[0])
        assert evidence["facility_count"] == len(snapshot)
        assert evidence["run_id"]

    def test_every_advertised_methodology_actually_runs(self, retail_book, snapshot, cfg):
        sample = snapshot.head(2000)
        values = {
            "pd_relative": 0.1, "pd_absolute_pp": 1.0, "lgd_relative": 0.1,
            "collateral_value_pct": -0.05, "recovery_delay_months": 3,
            "utilisation_pp": 5.0, "ccf_absolute": 0.5, "income_pct": -0.05,
            "behavioural_score_points": -20,
        }
        for name in wif.SUPPORTED_METHODOLOGIES:
            if name == "scenario_weights":
                s = _scenario(retail_book, snapshot,
                              scenario_weights={"base": 0.5, "upturn": 0.2, "downturn": 0.3})
            elif name == "staging_mode":
                s = _scenario(retail_book, snapshot, staging_mode=wif.REEVALUATE_STAGE)
            elif name == "cutoff_replay":
                assert wif.cutoff_replay(sample, {p: 600.0 for p in
                                                  ("CREDIT_CARD", "PERSONAL_LOAN",
                                                   "AUTO_LOAN", "HOME_LOAN")})
                continue
            else:
                s = _scenario(retail_book, snapshot, shocks={name: values[name]})
            result = wif.run(sample, s, cfg)
            assert result["scenario_result"]["ecl_final_sar"] >= 0, name

    def test_an_empty_filter_gives_an_honest_empty_result_not_infinity(
            self, retail_book, snapshot, cfg):
        s = _scenario(retail_book, snapshot, filters={"product_code": ["NOT_A_PRODUCT"]})
        result = wif.run(snapshot, s, cfg)
        assert result["population_empty"] is True
        assert result["delta"]["ecl_final_pct"] is None
        assert result["baseline"]["facilities"] == 0
        assert any("empty result, not a zero" in x for x in result["limitations"])

    def test_an_unknown_filter_column_is_a_clear_error(self, retail_book, snapshot, cfg):
        s = _scenario(retail_book, snapshot, filters={"internal_rating_grade": ["BBB"]})
        with pytest.raises(KeyError, match="no such column"):
            wif.run(snapshot, s, cfg)

    def test_no_nan_or_infinity_reaches_the_result(self, retail_book, snapshot, cfg):
        result = wif.run(snapshot, _scenario(retail_book, snapshot,
                                             shocks={"pd_relative": 0.2}), cfg)
        serialised = json.dumps(result, default=str)
        assert "Infinity" not in serialised
        assert "NaN" not in serialised
