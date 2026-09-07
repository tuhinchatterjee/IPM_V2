"""Tab 4b: Layer 4 propagation. Turns an event at a connected party into a
scored signal on the borrower, with direction, dependency, distance and edge
confidence all changing how much of the event actually arrives.

Formulas (Tab 4b Section D, verbatim):

    D (dependency weight)     = MIN(1, share_base_weight * substitutability_modifier)
    T (transmission factor)   = directional_factor * hop_decay * edge_confidence_factor
    propagated_score          = MIN(counterparty_score, counterparty_score * D * T)

The propagated score can never exceed the counterparty's own score — distance,
weak dependency and an unverified edge can only reduce it.

Verified against all six of Tab 4b Section D's worked rows:
  Al Faris Trading (upstream, 1 hop):        D=0.8,   T=0.6,      -> 38.4
  Tier-2 resin producer (upstream, 2 hops):  D=0.455, T=0.2475,   -> 10.135125
  Gulf Contracting Group (downstream, 1 hop):D=0.45,  T=0.765,    -> 24.0975
  Offtaker of Gulf Contracting (downstream, 2 hops): D=0.15, T=0.257125 -> 3.27834375
  Parent holding company (ownership, 1 hop): D=0.8,   T=0.9,      -> 43.2
  Guarantor, group treasury (credit support, 1 hop): D=1.0, T=1.0 -> 55.0
`test_network.py` reproduces all six exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Propagation parameters — Tab 4b Section C, verbatim.
# ---------------------------------------------------------------------------

#: Parameter[band] for bands 1-5.
DEPENDENCY_SHARE_BASE_WEIGHT: dict[int, float] = {1: 0.15, 2: 0.35, 3: 0.60, 4: 0.80, 5: 1.00}
SUBSTITUTABILITY_MODIFIER: dict[int, float] = {1: 0.50, 2: 0.75, 3: 1.00, 4: 1.15, 5: 1.30}
EDGE_CONFIDENCE_FACTOR: dict[int, float] = {1: 1.00, 2: 0.90, 3: 0.75, 4: 0.55, 5: 0.30}

#: Hop decay is zero beyond three hops. Two hops is the recommended default.
HOP_DECAY: dict[int, float] = {1: 1.00, 2: 0.55, 3: 0.25}

#: Directional transmission factor by relationship type. Tab 4b Section C.
DIRECTIONAL_FACTOR: dict[str, float] = {
    "upstream": 0.60,
    "downstream": 0.85,
    "ownership": 0.90,
    "credit_support": 1.00,
    "group_cross_default": 0.95,
}

# ---------------------------------------------------------------------------
# Governance rules — Tab 4b Section G.
# ---------------------------------------------------------------------------

MAX_PROPAGATION_HOPS_DEFAULT = 2
MAX_PROPAGATION_HOPS_WITH_APPROVAL = 3
MIN_EDGE_CONFIDENCE_BAND = 3  # band 3 or better (lower number); worse is logged, not scored
EDGE_REVALIDATION_MONTHS = 12


def dependency_weight(share_band: int, substitutability_band: int) -> float:
    """Tab 4b Section D: D = MIN(1, share_base_weight * substitutability_modifier)."""
    return min(1.0, DEPENDENCY_SHARE_BASE_WEIGHT[share_band] * SUBSTITUTABILITY_MODIFIER[substitutability_band])


def transmission_factor(relationship_type: str, hops: int, edge_confidence_band: int) -> float:
    """Tab 4b Section D: T = directional_factor * hop_decay * edge_confidence_factor."""
    hop_decay = HOP_DECAY.get(hops, 0.0)  # zero beyond three hops
    return DIRECTIONAL_FACTOR[relationship_type] * hop_decay * EDGE_CONFIDENCE_FACTOR[edge_confidence_band]


@dataclass(frozen=True)
class PropagationInput:
    counterparty_score: float
    relationship_type: str  # upstream|downstream|ownership|credit_support|group_cross_default
    hops: int
    dependency_share_band: int
    substitutability_band: int
    edge_confidence_band: int


@dataclass(frozen=True)
class PropagationResult:
    dependency_weight: float
    transmission_factor: float
    propagated_score: float
    scored: bool  # False if edge confidence is worse than the minimum band (logged, not scored)


def propagate(inp: PropagationInput) -> PropagationResult:
    """Tab 4b Section D formula, computed exactly as the workbook's own
    worked examples do (including the "single credible source", band-4-edge
    row, which the workbook itself still computes and displays a score for).

    `scored` separately flags Section G's governance policy ("minimum edge
    confidence: band 3 or better ... below band 3 the edge is logged but not
    scored") as metadata for the caller — this is a policy the aggregation
    layer applies when deciding which propagated signals to feed into the
    T&A ranking, not a change to the arithmetic itself. Zeroing the computed
    D/T/score here would silently disagree with the workbook's own
    Section D worked table.
    """
    d = dependency_weight(inp.dependency_share_band, inp.substitutability_band)
    t = transmission_factor(inp.relationship_type, inp.hops, inp.edge_confidence_band)
    propagated = min(inp.counterparty_score, inp.counterparty_score * d * t)
    scored = inp.edge_confidence_band <= MIN_EDGE_CONFIDENCE_BAND
    return PropagationResult(dependency_weight=d, transmission_factor=t,
                              propagated_score=propagated, scored=scored)


def portfolio_weighted_exposure(exposure: float, propagated_score: float) -> float:
    """Tab 4b Section F: "score-weighted exposure" — the portion of a
    borrower's exposure genuinely at risk from one failing counterparty.
    Verified against all four worked rows (ABC 120*38.4/100=46.08,
    DEF 85*44.6/100=37.91, GHI 45*24.8/100=11.16, JKL 30*20.8/100=6.24)."""
    return exposure * (propagated_score / 100.0)
