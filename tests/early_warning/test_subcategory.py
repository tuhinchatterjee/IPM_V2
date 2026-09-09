"""Sub-category aggregation, Tab 06 Section C Step 1: worst-of plus a
bounded corroboration uplift, or a weighted blend.
"""

from __future__ import annotations

from backend.early_warning.subcategory import (
    BLEND,
    UPLIFT_COEFFICIENT,
    WORST_OF,
    SubCategoryDefinition,
    roll_up_to_layer_dimension,
    score_subcategory,
    weighted_blend,
    worst_of_with_uplift,
)


def test_empty_scores_zero():
    assert worst_of_with_uplift([]) == 0.0


def test_single_member_is_its_own_score_no_uplift():
    assert worst_of_with_uplift([60.0]) == 60.0


def test_uplift_formula_with_one_corroborating_member():
    """score = worst + 0.35*(100-worst)*breadth. Worst=80, one other member
    at 60 (>= 50 threshold) -> breadth=1.0 (the only other member
    corroborates) -> 80 + 0.35*20*1.0 = 87.0."""
    result = worst_of_with_uplift([80.0, 60.0])
    assert abs(result - (80.0 + UPLIFT_COEFFICIENT * 20.0 * 1.0)) < 1e-9
    assert abs(result - 87.0) < 1e-9


def test_uplift_zero_when_no_other_member_corroborates():
    """Worst=80, other member at 10 (< 50 threshold) -> breadth=0 -> score
    stays exactly at the worst member."""
    result = worst_of_with_uplift([80.0, 10.0])
    assert result == 80.0


def test_worst_of_never_below_the_single_worst_member():
    assert worst_of_with_uplift([40.0, 90.0]) >= 90.0


def test_weighted_blend_basic():
    result = weighted_blend({"a": 0.0, "b": 100.0}, {"a": 0.6, "b": 0.4})
    assert abs(result - 40.0) < 1e-9


def test_weighted_blend_renormalises_over_present_members():
    """A member absent this month doesn't drag the blend toward zero — the
    present members' weights are renormalised."""
    result = weighted_blend({"b": 100.0}, {"a": 0.6, "b": 0.4})
    assert result == 100.0


def test_weighted_blend_empty_is_zero():
    assert weighted_blend({}, {"a": 1.0}) == 0.0


def test_score_subcategory_worst_of():
    d = SubCategoryDefinition("X.1", "test", "L1", "TA", 1.0, WORST_OF)
    assert score_subcategory(d, {"a": 80.0, "b": 60.0}) > 80.0


def test_score_subcategory_blend_with_weights():
    d = SubCategoryDefinition("X.2", "test", "L2", "C", 1.0, BLEND,
                               member_weights={"a": 0.6, "b": 0.4})
    assert abs(score_subcategory(d, {"a": 0.0, "b": 100.0}) - 40.0) < 1e-9


def test_score_subcategory_blend_without_weights_is_equal_weight_mean():
    d = SubCategoryDefinition("X.3", "test", "L1", "TA", 1.0, BLEND)
    assert abs(score_subcategory(d, {"a": 0.0, "b": 100.0}) - 50.0) < 1e-9


def test_score_subcategory_blend_requires_weights_or_none():
    d = SubCategoryDefinition("X.4", "test", "L2", "C", 1.0, BLEND)
    # no member_weights declared -> falls back to equal weight, does not raise
    assert score_subcategory(d, {}) == 0.0


def test_roll_up_to_layer_dimension_fixed_weights_missing_subcat_scores_zero():
    defs = {
        "A": SubCategoryDefinition("A", "a", "L1", "TA", 0.6, WORST_OF),
        "B": SubCategoryDefinition("B", "b", "L1", "TA", 0.4, WORST_OF),
    }
    result = roll_up_to_layer_dimension({"A": 80.0}, defs)
    assert abs(result - 80.0 * 0.6) < 1e-9  # B absent -> scores 0, weight stays fixed
