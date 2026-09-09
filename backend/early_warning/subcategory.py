"""Sub-category aggregation — Tab 06 ("Aggregation Methodology") Section C,
Step 1: signal/classifier to sub-category. Shared by both dimensions: the
Classifier dimension's 8 sub-categories (`classifiers_v2.py`, L2.1-L2.7 and
L4.4) and the T&A dimension's 14 (`aggregation.py`, L1.1-L1.4, L2.T1-L2.T2,
L3.1-L3.5, L4.1-L4.3) use the exact same two combination rules, so the
arithmetic lives once, here.

Two rules, never mixed within one sub-category (Tab 09 Section D states the
rule per sub-category explicitly; nothing here infers which rule applies):

Worst-of, plus a bounded corroboration uplift (Tab 06 Section C):

    score = worst + 0.35 * (100 - worst) * breadth

`breadth` is "the corroborating weight behind the worst signal" — the
workbook gives the shape of the formula, not an exact breadth definition, so
one is fixed here and documented as an implementation choice rather than a
workbook-given number: the fraction of the OTHER members currently scoring
50 or more (MEDIUM or worse), capped to [0, 1], and 0 when there is only one
member. This is the same treatment the workbook gives its own judgment calls
(Tab 02 Section D: "deliberately coarse... not estimates from this bank's
portfolio").

Weighted blend: a plain weighted mean over whichever members are present
that month, renormalised over their own weights — sub-categories measure
different things here, so a blend is legitimate (Tab 02 Section A).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

WORST_OF = "WORST_OF"
BLEND = "BLEND"
CombinationRule = Literal["WORST_OF", "BLEND"]

#: The bounded-uplift coefficient, Tab 06 Section C Step 1, verbatim.
UPLIFT_COEFFICIENT = 0.35

#: Threshold for "corroborating" in the breadth calculation (documented
#: implementation choice — see module docstring).
CORROBORATION_THRESHOLD = 50.0


@dataclass(frozen=True)
class SubCategoryDefinition:
    """One of the 22 sub-category roll-up nodes (Tab 03 Section A for the
    8 Classifier-dimension nodes; Tab 07 Section A's own weight column for
    the 14 T&A-dimension nodes)."""

    code: str
    name: str
    layer: str
    dimension: str  # "C" or "TA"
    weight_in_layer_dimension: float
    rule: CombinationRule
    #: Member weights, used only when rule == BLEND. Keys are classifier or
    #: trigger keys; values sum to 1.0 within the sub-category.
    member_weights: dict[str, float] | None = None


def worst_of_with_uplift(scores: list[float]) -> float:
    """Tab 06 Section C Step 1: score = worst + 0.35*(100-worst)*breadth.

    `scores` are the current scores of every member with a value this month
    (classifiers are always present; triggers only when fired). An empty
    list scores 0 (no live signal in this sub-category)."""
    if not scores:
        return 0.0
    worst = max(scores)  # higher = worse on this 0-100 scale
    # Breadth is computed over every OTHER member — remove one occurrence of
    # the worst value (not all matches, in case several members tie).
    remaining = list(scores)
    remaining.remove(worst)
    if not remaining:
        return worst
    corroborating = sum(1 for s in remaining if s >= CORROBORATION_THRESHOLD)
    breadth = min(1.0, corroborating / len(remaining))
    return worst + UPLIFT_COEFFICIENT * (100.0 - worst) * breadth


def weighted_blend(scores: dict[str, float], weights: dict[str, float]) -> float:
    """Plain weighted mean over whichever keys of `weights` are present in
    `scores` this month, renormalised over their own weights. Empty
    intersection scores 0 (no live signal / no data this month)."""
    present = {k: w for k, w in weights.items() if k in scores}
    total_weight = sum(present.values())
    if total_weight <= 0:
        return 0.0
    return sum(scores[k] * w for k, w in present.items()) / total_weight


def score_subcategory(definition: SubCategoryDefinition,
                       member_scores: dict[str, float]) -> float:
    """Roll up whichever of a sub-category's members have a score this
    month, per its declared rule."""
    if definition.rule == WORST_OF:
        return worst_of_with_uplift(list(member_scores.values()))
    if definition.member_weights is not None:
        return weighted_blend(member_scores, definition.member_weights)
    # No published per-member weight (the two T&A blend sub-categories,
    # L1.4 and L3.5, have no such table in Tab 04 — an equal-weight mean
    # across whichever triggers actually fired this month is the documented
    # implementation choice; see aggregation.py's module docstring).
    if not member_scores:
        return 0.0
    equal_weights = {k: 1.0 for k in member_scores}
    return weighted_blend(member_scores, equal_weights)


def roll_up_to_layer_dimension(subcategory_scores: dict[str, float],
                                definitions: dict[str, SubCategoryDefinition]) -> float:
    """Tab 06 Section C Step 2: weighted blend of sub-categories into one
    layer-dimension score (e.g. all of L1's T&A sub-categories into L1-T&A).
    The published weights are fixed regardless of which sub-categories fired
    this month — a sub-category with nothing live scores 0 and still counts
    at its full published weight, so the weights stay hand-reconstructable."""
    weights = {code: d.weight_in_layer_dimension for code, d in definitions.items()}
    scores = {code: subcategory_scores.get(code, 0.0) for code in weights}
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0.0
    return sum(scores[c] * w for c, w in weights.items()) / total_weight


__all__ = [
    "BLEND", "CORROBORATION_THRESHOLD", "CombinationRule",
    "SubCategoryDefinition", "UPLIFT_COEFFICIENT", "WORST_OF",
    "roll_up_to_layer_dimension", "score_subcategory", "weighted_blend",
    "worst_of_with_uplift",
]
