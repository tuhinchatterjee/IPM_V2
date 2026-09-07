"""The Version 2 classifier engine: 35 classifiers, weighted sum, overrides.

Every assertion here is anchored to a value the workbook itself computed —
Tab 2 Section B's worked example and Section C's override table — not to a
value this test suite invented. If the workbook changes, these numbers
change with it.
"""

from __future__ import annotations

from backend.early_warning.classifiers_v2 import (
    BAND_SCORE,
    CLASSIFIER_DEFINITIONS,
    TOTAL_WEIGHT,
    score_classifiers,
    verdict_band,
)

_BAND_BY_NUM = {1: "VERY_LOW", 2: "LOW", 3: "MEDIUM", 4: "HIGH", 5: "VERY_HIGH"}

#: Tab 2 Section B's worked example, band selections 1-35 in row order.
_WORKED_EXAMPLE_BANDS = [4, 4, 3, 4, 3, 3, 5, 4, 4, 3, 3, 3, 3, 3, 3, 4, 3, 4,
                         4, 3, 2, 2, 4, 4, 2, 2, 3, 4, 3, 2, 4, 4, 4, 3, 2]


def test_thirty_five_classifiers_weights_sum_to_100():
    assert len(CLASSIFIER_DEFINITIONS) == 35
    assert abs(TOTAL_WEIGHT - 100.0) < 1e-9


def test_worked_example_reproduces_62_high():
    selections = {
        c.key: _BAND_BY_NUM[n]
        for c, n in zip(CLASSIFIER_DEFINITIONS, _WORKED_EXAMPLE_BANDS)
    }
    result = score_classifiers(selections)
    assert abs(result.score - 62.0) < 1e-6
    assert result.band == "HIGH"


def test_missing_classifiers_renormalise_rather_than_default_to_zero():
    only_one = {CLASSIFIER_DEFINITIONS[0].key: "VERY_HIGH"}
    result = score_classifiers(only_one)
    assert result.score == 100.0  # the one observed classifier is VERY_HIGH


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
    low_score = {CLASSIFIER_DEFINITIONS[0].key: "VERY_LOW"}
    result = score_classifiers(low_score, ifrs9_stage=3)
    assert result.band == "VERY_HIGH"
    assert "ifrs9_stage3_or_90dpd_forces_very_high" in result.overrides_applied

    result2 = score_classifiers(low_score, dpd=95)
    assert result2.band == "VERY_HIGH"


def test_confirmed_sanctions_forces_very_high():
    low_score = {CLASSIFIER_DEFINITIONS[0].key: "VERY_LOW"}
    result = score_classifiers(low_score, confirmed_sanctions_match=True)
    assert result.band == "VERY_HIGH"


def test_unwaived_covenant_breach_floors_high():
    low_score = {CLASSIFIER_DEFINITIONS[0].key: "VERY_LOW"}
    result = score_classifiers(low_score, unwaived_covenant_breach=True)
    assert result.band == "HIGH"
    # a genuinely worse score is never lowered by the floor
    high_score = {CLASSIFIER_DEFINITIONS[0].key: "VERY_HIGH"}
    result2 = score_classifiers(high_score, unwaived_covenant_breach=True)
    assert result2.band == "VERY_HIGH"


def test_negative_equity_floors_high():
    low_score = {CLASSIFIER_DEFINITIONS[0].key: "VERY_LOW"}
    result = score_classifiers(low_score, negative_equity=True)
    assert result.band == "HIGH"


def test_stale_statements_floor_medium_never_lowers_a_higher_band():
    low_score = {CLASSIFIER_DEFINITIONS[0].key: "VERY_LOW"}
    result = score_classifiers(low_score, statements_unaudited_or_over_18m=True)
    assert result.band == "MEDIUM"

    high_score = {CLASSIFIER_DEFINITIONS[0].key: "VERY_HIGH"}
    result2 = score_classifiers(high_score, statements_unaudited_or_over_18m=True)
    assert result2.band == "VERY_HIGH"


def test_band_score_convention():
    assert BAND_SCORE == {"VERY_LOW": 0, "LOW": 25, "MEDIUM": 50, "HIGH": 75, "VERY_HIGH": 100}
