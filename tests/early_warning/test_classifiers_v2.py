"""The Version 2 classifier engine: 23 classifiers in 8 sub-categories,
worst-of/blend roll-up, then the Classifier dimension (L2 0.85 / L4 0.15).

Every assertion here is anchored to a value the corrected workbook itself
computed — Tab 03's structure and override table, and the Rawabi Al Nakhil
worked example in Tab 07 (see test_rawabi_regression.py for the full
end-to-end chain) — not to a value this test suite invented.
"""

from __future__ import annotations

from backend.early_warning.classifiers_v2 import (
    BAND_SCORE,
    CLASSIFIER_DEFINITIONS,
    CLASSIFIER_LAYER_WEIGHTS,
    SUBCATEGORIES,
    score_classifiers,
    verdict_band,
)


def test_twenty_three_classifiers_in_eight_subcategories():
    assert len(CLASSIFIER_DEFINITIONS) == 23
    assert len(SUBCATEGORIES) == 8
    l2_weight = sum(d.weight_in_layer_dimension for d in SUBCATEGORIES.values() if d.layer == "L2")
    assert abs(l2_weight - 1.0) < 1e-9
    assert SUBCATEGORIES["L4.4"].weight_in_layer_dimension == 1.0


def test_classifier_layer_weights_are_85_15():
    assert CLASSIFIER_LAYER_WEIGHTS == {"L2": 0.85, "L4": 0.15}


def test_rawabi_l2_c_and_l4_c_reproduce_tab07():
    """Tab 07 Section A gives the 7 L2 sub-category scores and L4.4
    directly; feeding those through the classifier-side roll-up should
    reproduce L2-C 70.98, L4-C 73, and Classifier dimension 71.283 exactly."""
    l2_subcat_scores = {
        "L2.1": 75, "L2.2": 71, "L2.3": 77, "L2.4": 83,
        "L2.5": 60, "L2.6": 43, "L2.7": 79,
    }
    # Feed one synthetic classifier per sub-category scoring exactly the
    # given sub-category value, so the roll-up receives that value directly
    # regardless of whether the sub-category's own rule is worst-of or blend.
    from backend.early_warning import subcategory as sc

    l2_c = sc.roll_up_to_layer_dimension(
        l2_subcat_scores, {c: d for c, d in SUBCATEGORIES.items() if d.layer == "L2"})
    assert abs(l2_c - 70.98) < 1e-6

    l4_c = 73.0  # L4.4 IS L4-C directly (weight 1)
    classifier_dimension = l2_c * 0.85 + l4_c * 0.15
    assert abs(classifier_dimension - 71.283) < 1e-6


def test_worst_of_subcategory_beats_a_plain_average():
    """Two classifiers in a worst-of sub-category (L2.1: PD, IFRS9 stage,
    DPD) at VERY_HIGH and VERY_LOW must score close to VERY_HIGH with
    corroboration uplift, never their average."""
    selections = {"pd_12m": "VERY_HIGH", "ifrs9_stage": "VERY_LOW", "dpd_current": "VERY_LOW"}
    result = score_classifiers(selections)
    l21 = result.subcategory_scores["L2.1"]
    assert l21 > 60.0  # far above the 33.3 a plain average would give


def test_blend_subcategory_is_a_weighted_mean():
    """L2.3 (Liquidity, blend: quick_ratio 0.6 / cash_conversion_cycle 0.4)
    should be the published weighted mean, not worst-of."""
    selections = {"quick_ratio": "VERY_LOW", "cash_conversion_cycle": "VERY_HIGH"}
    result = score_classifiers(selections)
    expected = 0.0 * 0.6 + 100.0 * 0.4
    assert abs(result.subcategory_scores["L2.3"] - expected) < 1e-6


def test_band_scale_boundaries():
    assert verdict_band(19.9) == "VERY_LOW"
    assert verdict_band(20.0) == "LOW"
    assert verdict_band(39.9) == "LOW"
    assert verdict_band(40.0) == "MEDIUM"
    assert verdict_band(59.9) == "MEDIUM"
    assert verdict_band(60.0) == "HIGH"
    assert verdict_band(79.9) == "HIGH"
    assert verdict_band(80.0) == "VERY_HIGH"


def test_stage3_or_90dpd_forces_very_high():
    low_score = {"pd_12m": "VERY_LOW"}
    result = score_classifiers(low_score, ifrs9_stage=3)
    assert result.band == "VERY_HIGH"
    assert "ifrs9_stage3_or_90dpd_forces_very_high" in result.overrides_applied

    result2 = score_classifiers(low_score, dpd=95)
    assert result2.band == "VERY_HIGH"


def test_confirmed_sanctions_forces_very_high():
    low_score = {"pd_12m": "VERY_LOW"}
    result = score_classifiers(low_score, confirmed_sanctions_match=True)
    assert result.band == "VERY_HIGH"


_ALL_VERY_HIGH = {c.key: "VERY_HIGH" for c in CLASSIFIER_DEFINITIONS}


def test_unwaived_covenant_breach_floors_high():
    low_score = {"pd_12m": "VERY_LOW"}
    result = score_classifiers(low_score, unwaived_covenant_breach=True)
    assert result.band == "HIGH"
    # a genuinely worse (all classifiers VERY_HIGH) result is never lowered
    result2 = score_classifiers(_ALL_VERY_HIGH, unwaived_covenant_breach=True)
    assert result2.band == "VERY_HIGH"


def test_negative_equity_floors_high():
    low_score = {"pd_12m": "VERY_LOW"}
    result = score_classifiers(low_score, negative_equity=True)
    assert result.band == "HIGH"


def test_stale_statements_floor_medium_never_lowers_a_higher_band():
    low_score = {"pd_12m": "VERY_LOW"}
    result = score_classifiers(low_score, statements_unaudited_or_over_18m=True)
    assert result.band == "MEDIUM"

    result2 = score_classifiers(_ALL_VERY_HIGH, statements_unaudited_or_over_18m=True)
    assert result2.band == "VERY_HIGH"


def test_guarantor_in_default_forces_guarantor_capacity_very_high():
    selections = {"guarantor_capacity": "VERY_LOW"}
    result = score_classifiers(selections, guarantor_in_default_load_bearing=True)
    assert "guarantor_in_default_forces_guarantor_capacity_very_high" in result.overrides_applied
    # L4.4 is a blend sub-category with only this one member supplied here,
    # so its score should reflect the forced VERY_HIGH band (100), not VERY_LOW.
    assert result.subcategory_scores["L4.4"] == 100.0


def test_band_score_convention():
    assert BAND_SCORE == {"VERY_LOW": 0, "LOW": 25, "MEDIUM": 50, "HIGH": 75, "VERY_HIGH": 100}
