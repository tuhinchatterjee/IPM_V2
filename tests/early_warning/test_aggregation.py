"""Tab 06 Section C Steps 1-3: causal-chain dedup, then sub-category
roll-up, then the layer/dimension roll-up that produces the T&A score.

This replaces an earlier implementation's flat rank-weighted breadth
formula (lambda = 0.60), which does not exist in the corrected workbook.
The full chain is verified end-to-end against the Rawabi Al Nakhil worked
example (Tab 07) — see also test_rawabi_regression.py for the complete
matrix+notch continuation.
"""

from __future__ import annotations

from backend.early_warning.aggregation import (
    TA_LAYER_WEIGHTS,
    TA_SUBCATEGORIES,
    FiredSignal,
    aggregate_ta_score,
    dedupe_causal_chains,
    ta_verdict_band,
)

_RAWABI_SUBCATEGORY_SCORES = {
    "L1.1": 60, "L1.2": 76, "L1.3": 75, "L1.4": 67,
    "L2.T1": 77, "L2.T2": 87,
    "L3.1": 82, "L3.2": 71, "L3.3": 69, "L3.4": 98, "L3.5": 69,
    "L4.1": 64, "L4.2": 61, "L4.3": 73,
}


def _rawabi_fired() -> tuple[FiredSignal, ...]:
    """One synthetic signal per sub-category scoring exactly Tab 07's given
    sub-category value — since each sub-category there has only one member
    reported, worst-of-with-one-member and a single-key blend both reduce
    to that value directly, regardless of the sub-category's own rule."""
    return tuple(
        FiredSignal(signal_key=f"given_{code}", signal_score=score,
                    causal_chain_id=f"chain_{code}", sub_category=code)
        for code, score in _RAWABI_SUBCATEGORY_SCORES.items()
    )


def test_fourteen_subcategories_weights_sum_to_one_per_layer():
    assert len(TA_SUBCATEGORIES) == 14
    for layer in ("L1", "L2", "L3", "L4"):
        total = sum(d.weight_in_layer_dimension for d in TA_SUBCATEGORIES.values() if d.layer == layer)
        assert abs(total - 1.0) < 1e-9, layer


def test_ta_layer_weights_are_40_15_30_15():
    assert TA_LAYER_WEIGHTS == {"L1": 0.40, "L2": 0.15, "L3": 0.30, "L4": 0.15}


def test_causal_chain_dedup_keeps_only_the_strongest_per_chain():
    fired = (
        FiredSignal("a", 46.0, "chain1", "L1.1"),
        FiredSignal("b", 30.0, "chain1", "L1.1"),
    )
    effective = dedupe_causal_chains(fired)
    by_key = {e.signal_key: e for e in effective}
    assert by_key["a"].effective_score == 46.0
    assert by_key["b"].effective_score == 0.0


def test_rawabi_layer_scores_and_ta_dimension_reproduce_tab07():
    result = aggregate_ta_score(_rawabi_fired())
    assert abs(result.layer_scores["L1"] - 69.2) < 1e-6
    assert abs(result.layer_scores["L2"] - 81.0) < 1e-6
    assert abs(result.layer_scores["L3"] - 78.0) < 1e-6
    assert abs(result.layer_scores["L4"] - 65.65) < 1e-6
    assert abs(result.ta_score - 73.0775) < 1e-4
    assert ta_verdict_band(result.ta_score) == "HIGH"


def test_ta_verdict_band_scale():
    assert ta_verdict_band(19.9) == "VERY_LOW"
    assert ta_verdict_band(73.0775) == "HIGH"
    assert ta_verdict_band(85) == "VERY_HIGH"


def test_no_fired_signals_gives_zero():
    result = aggregate_ta_score(())
    assert result.ta_score == 0.0
    assert result.dominant_driver is None


def test_worst_of_subcategory_uplift_from_corroboration():
    """Two signals in one worst-of sub-category should score above the
    worse one alone, via the bounded uplift — never a plain average."""
    fired = (
        FiredSignal("a", 80.0, "chain_a", "L1.2"),
        FiredSignal("b", 60.0, "chain_b", "L1.2"),
    )
    result = aggregate_ta_score(fired)
    assert result.subcategory_scores["L1.2"] > 80.0


def test_confirmed_sanctions_override_sets_ta_to_100():
    result = aggregate_ta_score(_rawabi_fired(), confirmed_sanctions_match=True)
    assert result.ta_score == 100.0
    assert result.override_applied == "confirmed_sanctions_match"


def test_cross_default_override_sets_ta_to_100():
    result = aggregate_ta_score((), cross_default_acceleration_served=True)
    assert result.ta_score == 100.0
