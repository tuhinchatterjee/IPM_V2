"""Tab 06 Section C, Steps 1-3: causal-chain dedup, then sub-category
worst-of/blend, then the layer and dimension roll-up that turns many fired
triggers into one T&A score.

This replaces an earlier implementation built against a different,
incorrect workbook draft, which combined every fired signal — from every
layer — in one flat rank-weighted "breadth" formula with a single constant
(lambda = 0.60). That mechanism does not exist in the corrected workbook and
has been removed, not preserved for compatibility. The corrected model is a
genuine hierarchy (Tab 06 Section C):

Step 1 — causal-chain dedup (Tab 05 Section D "Governance rules", carried
forward unchanged from the earlier draft — this part was already right)
--------------------------------------------------------------------------
Several signals can describe one underlying deterioration (a supplier
failure shows up as a propagated network signal AND as the borrower's own
utilisation rise AND as a turnover fall). Only the single highest-scoring
member of each causal chain counts toward its sub-category; the rest are
recorded (for evidence) but score zero.

Step 2 — sub-category roll-up (`subcategory.py`, shared with the Classifier
dimension's L2/L4 sub-categories)
--------------------------------------------------------------------------
The chain-deduplicated, still-in-scope signal scores for each of the 14
T&A sub-categories (L1.1-L1.4, L2.T1-L2.T2, L3.1-L3.5, L4.1-L4.3) combine by
that sub-category's own published rule — worst-of plus a bounded
corroboration uplift, or a weighted blend (Tab 09 Section D's own
combination-rule column, transcribed in `TA_SUBCATEGORIES` below).

Step 3 — layer and dimension roll-up (Tab 06 Section C Steps 2-3)
--------------------------------------------------------------------------
Sub-categories roll into four layer-T&A scores by their published
within-layer weight (`roll_up_to_layer_dimension`), and the four layers roll
into the final T&A dimension score at the published layer weights:

    T&A = L1*0.40 + L2*0.15 + L3*0.30 + L4*0.15

Verified end-to-end against the Rawabi Al Nakhil worked example (Tab 07):
L1 T&A 69.2, L2 T&A 81, L3 T&A 78, L4 T&A 65.65 -> T&A 73.0775, HIGH.
`test_rawabi_regression.py` reproduces this exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.early_warning import subcategory as sc

#: T&A layer weights combining the four layer-T&A scores into the T&A
#: dimension (Tab 06 Section C Step 3).
TA_LAYER_WEIGHTS: dict[str, float] = {"L1": 0.40, "L2": 0.15, "L3": 0.30, "L4": 0.15}
assert abs(sum(TA_LAYER_WEIGHTS.values()) - 1.0) < 1e-9

#: The 14 T&A sub-categories, transcribed verbatim from Tab 07 Section A's
#: own "Weight" column, with the combination rule from Tab 09 Section D.
#: L1.4 and L3.5 are the two T&A sub-categories the workbook marks
#: "Weighted blend" with no published per-member weight — an equal-weight
#: mean across whichever triggers fired that month (`subcategory.py`'s
#: documented default for this case), not a workbook-given number.
TA_SUBCATEGORIES: dict[str, sc.SubCategoryDefinition] = {
    "L1.1": sc.SubCategoryDefinition("L1.1", "Cash flow and inflows", "L1", "TA", 0.35, sc.WORST_OF),
    "L1.2": sc.SubCategoryDefinition("L1.2", "Limit and utilisation stress", "L1", "TA", 0.25, sc.WORST_OF),
    "L1.3": sc.SubCategoryDefinition("L1.3", "Payment performance", "L1", "TA", 0.30, sc.WORST_OF),
    "L1.4": sc.SubCategoryDefinition("L1.4", "Account and relationship activity", "L1", "TA", 0.10, sc.BLEND),
    "L2.T1": sc.SubCategoryDefinition("L2.T1", "Rating, PD and stage migration", "L2", "TA", 0.6, sc.WORST_OF),
    "L2.T2": sc.SubCategoryDefinition("L2.T2", "Covenant and collateral events", "L2", "TA", 0.4, sc.WORST_OF),
    "L3.1": sc.SubCategoryDefinition("L3.1", "Official and regulatory events", "L3", "TA", 0.2, sc.WORST_OF),
    "L3.2": sc.SubCategoryDefinition("L3.2", "Legal and distress events", "L3", "TA", 0.3, sc.WORST_OF),
    "L3.3": sc.SubCategoryDefinition("L3.3", "Ratings and market signals", "L3", "TA", 0.2, sc.WORST_OF),
    "L3.4": sc.SubCategoryDefinition("L3.4", "News and operating events", "L3", "TA", 0.2, sc.WORST_OF),
    "L3.5": sc.SubCategoryDefinition("L3.5", "Macro and sector shocks", "L3", "TA", 0.1, sc.BLEND),
    "L4.1": sc.SubCategoryDefinition("L4.1", "Upstream propagation", "L4", "TA", 0.35, sc.WORST_OF),
    "L4.2": sc.SubCategoryDefinition("L4.2", "Downstream propagation", "L4", "TA", 0.35, sc.WORST_OF),
    "L4.3": sc.SubCategoryDefinition("L4.3", "Ownership and credit support propagation", "L4", "TA", 0.3, sc.WORST_OF),
}

for _layer in ("L1", "L2", "L3", "L4"):
    _total = sum(d.weight_in_layer_dimension for d in TA_SUBCATEGORIES.values() if d.layer == _layer)
    assert abs(_total - 1.0) < 1e-9, (_layer, _total)


@dataclass(frozen=True)
class FiredSignal:
    """One trigger that fired this period, before chain dedup."""

    signal_key: str
    signal_score: float
    causal_chain_id: str  # signals with the same id belong to one deterioration
    sub_category: str  # one of TA_SUBCATEGORIES' keys


@dataclass(frozen=True)
class EffectiveSignal:
    signal_key: str
    causal_chain_id: str
    sub_category: str
    effective_score: float
    is_chain_representative: bool


@dataclass(frozen=True)
class AggregationResult:
    effective_signals: tuple[EffectiveSignal, ...]  # chain-deduplicated
    subcategory_scores: dict[str, float]
    layer_scores: dict[str, float]  # L1, L2, L3, L4 -> layer-T&A score
    ta_score: float
    dominant_driver: str | None
    dominant_subcategory: str | None
    override_applied: str | None


def dedupe_causal_chains(fired: tuple[FiredSignal, ...]) -> list[EffectiveSignal]:
    """Only the strongest member of each causal chain counts."""
    by_chain: dict[str, list[FiredSignal]] = {}
    for f in fired:
        by_chain.setdefault(f.causal_chain_id, []).append(f)

    out: list[EffectiveSignal] = []
    for chain_id, members in by_chain.items():
        best = max(members, key=lambda m: m.signal_score)
        for m in members:
            out.append(EffectiveSignal(
                signal_key=m.signal_key, causal_chain_id=chain_id,
                sub_category=m.sub_category,
                effective_score=m.signal_score if m is best else 0.0,
                is_chain_representative=(m is best),
            ))
    return out


def aggregate_ta_score(
    fired: tuple[FiredSignal, ...],
    *,
    confirmed_sanctions_match: bool = False,
    cross_default_acceleration_served: bool = False,
) -> AggregationResult:
    effective = dedupe_causal_chains(fired)
    representatives = [e for e in effective if e.is_chain_representative]

    if confirmed_sanctions_match or cross_default_acceleration_served:
        override = ("confirmed_sanctions_match" if confirmed_sanctions_match
                    else "cross_default_acceleration_served")
        ranked = sorted(representatives, key=lambda e: e.effective_score, reverse=True)
        dominant = ranked[0] if ranked else None
        return AggregationResult(
            effective_signals=tuple(effective),
            subcategory_scores={}, layer_scores={"L1": 100.0, "L2": 100.0, "L3": 100.0, "L4": 100.0},
            ta_score=100.0,
            dominant_driver=dominant.signal_key if dominant else None,
            dominant_subcategory=dominant.sub_category if dominant else None,
            override_applied=override,
        )

    scores_by_subcat: dict[str, dict[str, float]] = {code: {} for code in TA_SUBCATEGORIES}
    for e in representatives:
        scores_by_subcat.setdefault(e.sub_category, {})[e.signal_key] = e.effective_score

    subcategory_scores = {
        code: sc.score_subcategory(definition, scores_by_subcat.get(code, {}))
        for code, definition in TA_SUBCATEGORIES.items()
    }

    layer_scores: dict[str, float] = {}
    for layer in ("L1", "L2", "L3", "L4"):
        layer_defs = {c: d for c, d in TA_SUBCATEGORIES.items() if d.layer == layer}
        layer_scores[layer] = sc.roll_up_to_layer_dimension(subcategory_scores, layer_defs)

    ta_score = sum(layer_scores[layer] * weight for layer, weight in TA_LAYER_WEIGHTS.items())

    dominant = max(representatives, key=lambda e: e.effective_score, default=None)

    return AggregationResult(
        effective_signals=tuple(effective),
        subcategory_scores=subcategory_scores,
        layer_scores=layer_scores,
        ta_score=round(ta_score, 6),
        dominant_driver=dominant.signal_key if dominant else None,
        dominant_subcategory=dominant.sub_category if dominant else None,
        override_applied=None,
    )


def ta_verdict_band(score: float) -> str:
    """Tab 06 band scale — identical convention to classifiers: <20/<40/<60/<80/else."""
    if score < 20.0:
        return "VERY_LOW"
    if score < 40.0:
        return "LOW"
    if score < 60.0:
        return "MEDIUM"
    if score < 80.0:
        return "HIGH"
    return "VERY_HIGH"
