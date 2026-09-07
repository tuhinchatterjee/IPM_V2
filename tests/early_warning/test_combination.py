"""Tab 4: EWS score = MIN(100, T&A * CCM). Multiplication, not a lookup
matrix — see Conflict A in the implementation plan for why this module does
NOT implement a 5x5 anchor matrix or five ±1 notch modifiers: the workbook
does not specify either mechanism, and this module implements the workbook.
"""

from __future__ import annotations

from backend.early_warning.combination import CCM, CombinationInput, combine, verdict_band


def test_ccm_table():
    assert CCM == {"VERY_LOW": 0.70, "LOW": 0.85, "MEDIUM": 1.00, "HIGH": 1.20, "VERY_HIGH": 1.40}


def test_worked_example_74_66133_high():
    """Tab 4 Section B: classifier score 62 (HIGH), T&A score 62.217775
    (HIGH), CCM 1.2 -> EWS score 74.66133, HIGH RISK."""
    result = combine(CombinationInput(
        ta_score=62.217775, classifier_score=62.0, classifier_band="HIGH",
    ))
    assert abs(result.ccm - 1.2) < 1e-9
    assert abs(result.ews_score - 74.66133) < 1e-3
    assert result.ews_band == "HIGH"


def test_no_trigger_stays_near_zero_however_vulnerable():
    """"With no live trigger the EWS score stays near zero however
    vulnerable the borrower is" — Tab 4 Section A rationale. Classifier HIGH
    rather than VERY_HIGH here, since VERY_HIGH + T&A VERY_LOW is the one
    documented exception (floored at LOW, tested separately below) precisely
    because a structurally fragile borrower still deserves a periodic look."""
    result = combine(CombinationInput(ta_score=0.0, classifier_score=70, classifier_band="HIGH"))
    assert result.ews_score == 0.0


def test_classifier_very_high_ta_very_low_floors_low_not_a_live_alert():
    result = combine(CombinationInput(ta_score=10.0, classifier_score=90, classifier_band="VERY_HIGH"))
    assert result.ews_band == "LOW"
    assert "classifier_very_high_and_ta_very_low_floors_low_periodic_review" in result.overrides_applied


def test_ifrs9_stage3_forces_very_high():
    result = combine(CombinationInput(ta_score=10, classifier_score=20, classifier_band="LOW", ifrs9_stage=3))
    assert result.ews_score == 100.0 and result.ews_band == "VERY_HIGH"


def test_ninety_dpd_forces_very_high():
    result = combine(CombinationInput(ta_score=10, classifier_score=20, classifier_band="LOW", dpd=95))
    assert result.ews_band == "VERY_HIGH"


def test_confirmed_sanctions_forces_very_high():
    result = combine(CombinationInput(ta_score=5, classifier_score=10, classifier_band="VERY_LOW",
                                       confirmed_sanctions_match=True))
    assert result.ews_score == 100.0


def test_cross_default_acceleration_served_forces_very_high():
    result = combine(CombinationInput(ta_score=5, classifier_score=10, classifier_band="VERY_LOW",
                                       cross_default_acceleration_served=True))
    assert result.ews_score == 100.0


def test_unwaived_covenant_breach_floors_high_never_lowers():
    low = combine(CombinationInput(ta_score=10, classifier_score=20, classifier_band="LOW",
                                    unwaived_covenant_breach=True))
    assert low.ews_band == "HIGH"

    already_high = combine(CombinationInput(ta_score=90, classifier_score=90, classifier_band="VERY_HIGH",
                                              unwaived_covenant_breach=True))
    assert already_high.ews_band == "VERY_HIGH"


def test_band_scale():
    assert verdict_band(19.9) == "VERY_LOW"
    assert verdict_band(74.66133) == "HIGH"
    assert verdict_band(95) == "VERY_HIGH"
