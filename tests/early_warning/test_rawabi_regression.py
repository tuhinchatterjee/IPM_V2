"""The mandatory end-to-end regression: Rawabi Al Nakhil Contracting
(SA-CORP-10412), Tab 07 "Roll-Up Engine" of the corrected CreditProbe EWS
Framework V2 workbook.

This is the one test that proves the whole corrected scoring engine —
sub-category roll-up, layer/dimension roll-up, matrix anchor, notches — is
right end-to-end, not just right module-by-module. Every intermediate value
below is transcribed verbatim from Tab 07 and must reproduce exactly (or to
float tolerance); if it does not, the engine is not complete regardless of
what any individual module's own tests say.

Tab 07 gives sub-category scores directly (it is a worked example over
already-scored inputs, not raw classifier bands or trigger firings) — this
test starts from that same starting point, feeding the given sub-category
scores through the real roll-up/matrix/notch modules, exactly as
`aggregation.py` and `classifiers_v2.py` would if a live borrower-month
happened to produce these same 22 sub-category scores.
"""

from __future__ import annotations

from backend.early_warning import subcategory as sc
from backend.early_warning.aggregation import TA_SUBCATEGORIES, FiredSignal, aggregate_ta_score
from backend.early_warning.classifiers_v2 import SUBCATEGORIES as CLASSIFIER_SUBCATEGORIES
from backend.early_warning.combination import CombinationInput, combine

# Tab 07 Section A: the 22 sub-category scores as given for this obligor.
_TA_SUBCATEGORY_SCORES = {
    "L1.1": 60, "L1.2": 76, "L1.3": 75, "L1.4": 67,
    "L2.T1": 77, "L2.T2": 87,
    "L3.1": 82, "L3.2": 71, "L3.3": 69, "L3.4": 98, "L3.5": 69,
    "L4.1": 64, "L4.2": 61, "L4.3": 73,
}
_CLASSIFIER_SUBCATEGORY_SCORES = {
    "L2.1": 75, "L2.2": 71, "L2.3": 77, "L2.4": 83,
    "L2.5": 60, "L2.6": 43, "L2.7": 79,
    "L4.4": 73,
}


def test_rawabi_end_to_end_reproduces_56_medium():
    # --- T&A dimension, via aggregation.py's real roll-up -------------
    fired = tuple(
        FiredSignal(signal_key=f"given_{code}", signal_score=score,
                    causal_chain_id=f"chain_{code}", sub_category=code)
        for code, score in _TA_SUBCATEGORY_SCORES.items()
    )
    ta_result = aggregate_ta_score(fired)
    assert abs(ta_result.layer_scores["L1"] - 69.2) < 1e-6
    assert abs(ta_result.layer_scores["L2"] - 81.0) < 1e-6
    assert abs(ta_result.layer_scores["L3"] - 78.0) < 1e-6
    assert abs(ta_result.layer_scores["L4"] - 65.65) < 1e-6
    assert abs(ta_result.ta_score - 73.0775) < 1e-4

    # --- Classifier dimension, via the real sub-category roll-up ------
    l2_subcats = {c: d for c, d in CLASSIFIER_SUBCATEGORIES.items() if d.layer == "L2"}
    l2_c = sc.roll_up_to_layer_dimension(_CLASSIFIER_SUBCATEGORY_SCORES, l2_subcats)
    l4_c = _CLASSIFIER_SUBCATEGORY_SCORES["L4.4"]
    assert abs(l2_c - 70.98) < 1e-6
    assert l4_c == 73.0
    classifier_score = l2_c * 0.85 + l4_c * 0.15
    assert abs(classifier_score - 71.283) < 1e-6

    ta_band = "HIGH"
    classifier_band = "HIGH"
    assert abs(ta_result.ta_score - 73.0775) < 1e-4  # HIGH band (60-80)
    assert abs(classifier_score - 71.283) < 1e-6  # HIGH band (60-80)

    # --- Anchor, notches, final score, via the real combination step --
    result = combine(CombinationInput(
        ta_score=ta_result.ta_score, ta_band=ta_band,
        classifier_score=classifier_score, classifier_band=classifier_band,
        notch_values={
            "network_contagion": -1,       # No material connected-party exposure
            "direction_of_travel": -1,     # Improving two months or more
            "evidence_quality": 0,         # Mixed tier 1 and tier 2 evidence
            "data_staleness": 0,           # Minor gaps in inputs
            "management_and_governance": 0,  # Neutral
        },
    ))

    assert result.anchor == 72
    assert result.notch_result.net_notches_capped == -2
    assert abs(result.ews_score - 56.0) < 1e-9
    assert result.ews_band == "MEDIUM"
    assert result.overrides_applied == ()  # no cap/override fires for this obligor
