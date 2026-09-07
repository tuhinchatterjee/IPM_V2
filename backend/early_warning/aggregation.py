"""Tab 3 Section D: causal-chain dedup, then the rank-weighted breadth
aggregation that turns many fired signals into one T&A score.

This is the mechanism the workbook actually specifies. There is no per-layer
sub-score here and no weighted blend of "L1 T&A / L2 T&A / L3 T&A / L4 T&A"
(0.40/0.15/0.30/0.15) — every fired signal, from every layer, competes in one
flat ranking. See Section 0 of the implementation plan for the full
reconciliation against an earlier design description that assumed a 4-level
weighted hierarchy; the workbook does not implement one.

Step 1 — causal-chain dedup (Tab 4b Section E, applied here)
--------------------------------------------------------------
Several signals can describe one underlying deterioration (a supplier
failure shows up as a propagated network signal AND as the borrower's own
utilisation rise AND as a turnover fall). Only the single highest-scoring
member of each causal chain counts; the rest are recorded (for evidence) but
contribute zero to the ranking. Without this, one real failure could look
like several independent corroborating signals.

Step 2 — rank and blend (Tab 3 Section D, verbatim)
--------------------------------------------------------------
Rank the chain-deduplicated ("effective") scores S1 >= S2 >= ... >= Sn.

    B    = MIN(1, (0.30*S2 + 0.15*S3 + 0.10*S4 + 0.05*SUM(S5..Sn)) / 100)
    T&A  = MIN(100, S1 + (100 - S1) * lambda * B),   lambda = 0.60

The worst single signal (S1) sets the floor; breadth (B) then lifts the
score into the remaining headroom, so a wide-but-mild pattern cannot alone
reach the top band, and a single severe signal is never averaged away.

Verified against Tab 3 Section D's worked example (S1=55, S2=46, S3=44.2,
S4=38.4, remaining sum=49.25 -> B=0.267325 -> T&A=62.217775).
`test_aggregation.py` reproduces this exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

LAMBDA = 0.60


@dataclass(frozen=True)
class FiredSignal:
    """One signal that fired this period, before chain dedup."""

    signal_key: str
    signal_score: float
    causal_chain_id: str  # signals with the same id belong to one deterioration


@dataclass(frozen=True)
class EffectiveSignal:
    signal_key: str
    causal_chain_id: str
    effective_score: float
    is_chain_representative: bool


@dataclass(frozen=True)
class AggregationResult:
    effective_signals: tuple[EffectiveSignal, ...]  # chain-deduplicated, ranked desc
    breadth_index: float
    ta_score: float
    dominant_driver: str | None
    override_applied: str | None


def dedupe_causal_chains(fired: tuple[FiredSignal, ...]) -> list[EffectiveSignal]:
    """Tab 4b Section E: only the strongest member of each chain counts."""
    by_chain: dict[str, list[FiredSignal]] = {}
    for f in fired:
        by_chain.setdefault(f.causal_chain_id, []).append(f)

    out: list[EffectiveSignal] = []
    for chain_id, members in by_chain.items():
        best = max(members, key=lambda m: m.signal_score)
        for m in members:
            out.append(EffectiveSignal(
                signal_key=m.signal_key, causal_chain_id=chain_id,
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

    if confirmed_sanctions_match or cross_default_acceleration_served:
        override = ("confirmed_sanctions_match" if confirmed_sanctions_match
                    else "cross_default_acceleration_served")
        ranked = sorted(
            [e for e in effective if e.is_chain_representative],
            key=lambda e: e.effective_score, reverse=True,
        )
        dominant = ranked[0].signal_key if ranked else None
        return AggregationResult(
            effective_signals=tuple(ranked), breadth_index=1.0,
            ta_score=100.0, dominant_driver=dominant, override_applied=override,
        )

    representatives = sorted(
        [e for e in effective if e.is_chain_representative],
        key=lambda e: e.effective_score, reverse=True,
    )
    scores = [e.effective_score for e in representatives]

    if not scores:
        return AggregationResult(
            effective_signals=tuple(representatives), breadth_index=0.0,
            ta_score=0.0, dominant_driver=None, override_applied=None,
        )

    s1 = scores[0]
    s2 = scores[1] if len(scores) > 1 else 0.0
    s3 = scores[2] if len(scores) > 2 else 0.0
    s4 = scores[3] if len(scores) > 3 else 0.0
    remaining = sum(scores[4:]) if len(scores) > 4 else 0.0

    breadth = min(1.0, (0.30 * s2 + 0.15 * s3 + 0.10 * s4 + 0.05 * remaining) / 100.0)
    ta_score = min(100.0, s1 + (100.0 - s1) * LAMBDA * breadth)

    return AggregationResult(
        effective_signals=tuple(representatives),
        breadth_index=round(breadth, 6),
        ta_score=round(ta_score, 6),
        dominant_driver=representatives[0].signal_key,
        override_applied=None,
    )


def ta_verdict_band(score: float) -> str:
    """Tab 3 Section D band scale — identical convention to classifiers."""
    if score < 20.0:
        return "VERY_LOW"
    if score < 40.0:
        return "LOW"
    if score < 60.0:
        return "MEDIUM"
    if score < 80.0:
        return "HIGH"
    return "VERY_HIGH"
