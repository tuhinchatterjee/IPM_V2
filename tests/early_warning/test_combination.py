"""Tab 06 Sections D-F: EWS score = matrix anchor, then notches, then caps.
Never a multiplication — see the module docstring for why the earlier
implementation's Classifier Context Multiplier does not exist in the
corrected workbook.
"""

from __future__ import annotations

from backend.early_warning.combination import (
    FORCED_VERY_HIGH_SCORE,
    NO_SIGNAL_FRAGILE_OBLIGOR_SCORE,
    CombinationInput,
    combine,
    verdict_band,
)

_NEUTRAL_NOTCHES = {
    "network_contagion": 0, "direction_of_travel": 0, "evidence_quality": 0,
    "data_staleness": 0, "management_and_governance": 0,
}


def test_rawabi_worked_example_56_medium():
    """Tab 07: T&A 73.0775 (HIGH), Classifier 71.283 (HIGH) -> anchor 72 ->
    notches -1 (network contagion), -1 (direction of travel), 0, 0, 0 ->
    net -2 -> final EWS 56, MEDIUM."""
    result = combine(CombinationInput(
        ta_score=73.0775, ta_band="HIGH",
        classifier_score=71.283, classifier_band="HIGH",
        notch_values={"network_contagion": -1, "direction_of_travel": -1,
                      "evidence_quality": 0, "data_staleness": 0,
                      "management_and_governance": 0},
    ))
    assert result.anchor == 72
    assert result.notch_result.net_notches_capped == -2
    assert abs(result.ews_score - 56.0) < 1e-9
    assert result.ews_band == "MEDIUM"


def test_anchor_matrix_lookup_no_notches():
    result = combine(CombinationInput(
        ta_score=0, ta_band="VERY_LOW", classifier_score=0, classifier_band="VERY_LOW",
        notch_values=_NEUTRAL_NOTCHES,
    ))
    assert result.anchor == 5
    assert result.ews_score == 5.0


def test_no_trigger_stays_low_however_vulnerable():
    """"An obligor with no live signal is not an alert" — Tab 06 Section D
    reading. Classifier HIGH here (not VERY_HIGH, the one documented
    exception tested separately below)."""
    result = combine(CombinationInput(
        ta_score=0.0, ta_band="VERY_LOW", classifier_score=70, classifier_band="HIGH",
        notch_values=_NEUTRAL_NOTCHES,
    ))
    assert result.ews_score == 16.0  # matrix cell VERY_LOW x HIGH
    assert result.ews_band == "VERY_LOW"


def test_classifier_very_high_ta_very_low_floored_and_capped_at_low():
    result = combine(CombinationInput(
        ta_score=10.0, ta_band="VERY_LOW", classifier_score=90, classifier_band="VERY_HIGH",
        notch_values=_NEUTRAL_NOTCHES,
    ))
    assert result.ews_score == NO_SIGNAL_FRAGILE_OBLIGOR_SCORE
    assert result.ews_band == "LOW"
    assert "classifier_very_high_and_ta_very_low_floored_and_capped_at_low" in result.overrides_applied


def test_ifrs9_stage3_forces_very_high():
    result = combine(CombinationInput(
        ta_score=10, ta_band="VERY_LOW", classifier_score=20, classifier_band="LOW",
        notch_values=_NEUTRAL_NOTCHES, ifrs9_stage=3,
    ))
    assert result.ews_score == FORCED_VERY_HIGH_SCORE
    assert result.ews_band == "VERY_HIGH"


def test_ninety_dpd_forces_very_high():
    result = combine(CombinationInput(
        ta_score=10, ta_band="VERY_LOW", classifier_score=20, classifier_band="LOW",
        notch_values=_NEUTRAL_NOTCHES, dpd=95,
    ))
    assert result.ews_band == "VERY_HIGH"


def test_confirmed_sanctions_forces_very_high():
    result = combine(CombinationInput(
        ta_score=5, ta_band="VERY_LOW", classifier_score=10, classifier_band="VERY_LOW",
        notch_values=_NEUTRAL_NOTCHES, confirmed_sanctions_match=True,
    ))
    assert result.ews_score == FORCED_VERY_HIGH_SCORE


def test_cross_default_acceleration_served_forces_very_high():
    result = combine(CombinationInput(
        ta_score=5, ta_band="VERY_LOW", classifier_score=10, classifier_band="VERY_LOW",
        notch_values=_NEUTRAL_NOTCHES, cross_default_acceleration_served=True,
    ))
    assert result.ews_score == FORCED_VERY_HIGH_SCORE


def test_unwaived_covenant_breach_floors_high_never_lowers():
    low = combine(CombinationInput(
        ta_score=10, ta_band="VERY_LOW", classifier_score=20, classifier_band="LOW",
        notch_values=_NEUTRAL_NOTCHES, unwaived_covenant_breach=True,
    ))
    assert low.ews_band == "HIGH"

    already_high = combine(CombinationInput(
        ta_score=90, ta_band="VERY_HIGH", classifier_score=90, classifier_band="VERY_HIGH",
        notch_values=_NEUTRAL_NOTCHES, unwaived_covenant_breach=True,
    ))
    assert already_high.ews_band == "VERY_HIGH"


def test_upstream_flags_recorded_without_changing_the_score():
    result = combine(CombinationInput(
        ta_score=50, ta_band="MEDIUM", classifier_score=50, classifier_band="MEDIUM",
        notch_values=_NEUTRAL_NOTCHES,
        entity_match_confidence_below_threshold=True,
        single_unverified_tier3_source_no_corroboration=True,
    ))
    assert "entity_match_confidence_below_threshold_excluded_upstream" in result.overrides_applied
    assert "single_unverified_tier3_source_capped_severity_2_upstream" in result.overrides_applied


def test_band_scale():
    assert verdict_band(19.9) == "VERY_LOW"
    assert verdict_band(56.0) == "MEDIUM"
    assert verdict_band(95) == "VERY_HIGH"
