"""
The materiality engine. §75.

    "The LLM may explain the result. It may not independently assign the
     materiality band."

That is the whole point of the module existing rather than the band being a
field on a prompt. Materiality decides what gets escalated, what goes in front
of a committee and what a credit officer spends a week on, and a model asked
for it will produce a plausible one every time — including for a finding that
is two borrowers and a rounding difference.

So the band comes from a policy: named components, stated weights, stated
thresholds, a version. A model may say what the band means. It may not choose
it, and the reason it may not is that nobody could ever tell it had chosen
wrongly.

Why a weighted score rather than a rule tree
---------------------------------------------
A rule tree ("critical if above X and above Y") is easier to read and wrong in
a specific way: findings sit just under two thresholds and score nothing, and
findings that clear one enormously score the same as ones that scrape it. The
components here are continuous, so a finding that is small in every dimension
but breaches a risk-appetite limit still lands somewhere, and one that is
enormous on exposure does not need six other things to be true.

Two things override the score
------------------------------
A risk-appetite breach and a critical threshold breach set a FLOOR on the band
regardless of the weighted score, because those are the cases where the bank
has already decided in advance that it cares. A score that could average them
away would be a policy that quietly reverses a policy.

Evidence quality cuts the other way
------------------------------------
A finding computed from thin evidence has its band CAPPED, not reduced. The
distinction matters: reducing it would say the finding is smaller than it is,
and capping says we cannot yet claim it is as large as it looks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MATERIALITY_VERSION = "1.0.0"

IMMATERIAL = "IMMATERIAL"
LOW = "LOW"
MODERATE = "MODERATE"
HIGH = "HIGH"
CRITICAL = "CRITICAL"

BANDS: tuple[str, ...] = (IMMATERIAL, LOW, MODERATE, HIGH, CRITICAL)

#: Where each band starts, on a 0-100 score.
THRESHOLDS: dict[str, float] = {
    IMMATERIAL: 0.0, LOW: 15.0, MODERATE: 35.0, HIGH: 60.0, CRITICAL: 82.0,
}

#: §75's components, and what each is worth. The weights are the policy: they
#: are here to be argued with, changed and versioned, which is the difference
#: between a materiality policy and a number somebody picked.
WEIGHTS: dict[str, float] = {
    #: How big the movement is in money.
    "absolute_amount": 14.0,
    #: How big it is relative to what it moved from.
    "relative_movement": 12.0,
    #: How much of the book it touches.
    "portfolio_share": 14.0,
    #: How much of the segment it touches. A finding can be immaterial to the
    #: book and decisive for the segment somebody manages.
    "segment_share": 10.0,
    #: Exposure actually affected, which is not the same as the movement.
    "exposure_affected": 12.0,
    #: How many names or accounts. A large number is a systemic signal even
    #: where each one is small.
    "entities_affected": 8.0,
    #: Concentrated findings are more actionable and more dangerous.
    "concentration": 8.0,
    #: A persistent movement matters more than a spike of the same size.
    "persistence": 10.0,
    #: How far past a stated limit.
    "threshold_severity": 12.0,
}

#: A breach of something the bank has already decided it cares about sets a
#: floor. §75 lists risk-appetite threshold as a component; treating it only
#: as a weighted component would let six small components average away a
#: breach, which reverses a policy the bank wrote down.
APPETITE_FLOOR = HIGH
CRITICAL_BREACH_FLOOR = CRITICAL

#: What thin evidence caps the band at. A cap, not a reduction: reducing would
#: say the finding is smaller than it is, and capping says we cannot yet claim
#: it is as large as it looks.
EVIDENCE_CAPS: dict[str, str] = {"THIN": MODERATE, "PARTIAL": HIGH}


@dataclass
class Inputs:
    """What is known about a finding. Every field optional; absent means the
    component scores nothing rather than scoring badly."""

    absolute_amount: float | None = None
    #: What "large" means for this metric, supplied by the caller. Without it
    #: the absolute amount cannot be scored — a million is enormous on a
    #: covenant headroom and invisible on a book.
    amount_scale: float | None = None
    relative_movement: float | None = None
    portfolio_share: float | None = None
    segment_share: float | None = None
    exposure_affected: float | None = None
    portfolio_exposure: float | None = None
    entities_affected: int | None = None
    population: int | None = None
    #: From the breadth engine: 1.0 when fully concentrated.
    concentration: float | None = None
    #: From the persistence engine.
    persistent: bool | None = None
    #: How far past a stated limit, as a fraction of the limit.
    threshold_severity: float | None = None
    appetite_breach: bool = False
    critical_breach: bool = False
    #: COMPLETE | PARTIAL | THIN
    evidence_quality: str = "PARTIAL"
    #: Whether the analysis behind it passed its invariants.
    validated: bool = True


@dataclass
class Assessment:
    """§75's output, with everything that produced it."""

    score: float = 0.0
    band: str = IMMATERIAL
    component_scores: dict[str, float] = field(default_factory=dict)
    policy_version: str = MATERIALITY_VERSION
    reasons: list[str] = field(default_factory=list)
    #: Set when a floor or a cap moved the band away from the score.
    adjusted: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "band": self.band,
            "component_scores": {k: round(v, 2)
                                 for k, v in self.component_scores.items()},
            "policy_version": self.policy_version,
            "reasons": list(self.reasons),
            "adjusted": self.adjusted,
            "weights": dict(WEIGHTS),
            "thresholds": dict(THRESHOLDS),
        }


def _ratio(value: float | None, scale: float | None) -> float:
    """A value against its own scale, clamped to 0-1.

    Clamped rather than allowed to exceed 1 because a component worth twelve
    points should be worth twelve points, not thirty; a finding four times the
    scale is enormous, and it is the FLOOR mechanism that reflects that, not
    an unbounded component.
    """
    if value is None or not scale:
        return 0.0
    return max(0.0, min(1.0, abs(float(value)) / abs(float(scale))))


def _band_for(score: float) -> str:
    band = IMMATERIAL
    for name in BANDS:
        if score >= THRESHOLDS[name]:
            band = name
    return band


def _at_least(band: str, floor: str) -> str:
    return band if BANDS.index(band) >= BANDS.index(floor) else floor


def _at_most(band: str, cap: str) -> str:
    return band if BANDS.index(band) <= BANDS.index(cap) else cap


def assess(inputs: Inputs) -> Assessment:
    """The band, from the policy. Never from a model.

    Components that cannot be computed score zero and are recorded as zero
    rather than omitted, so a low score is distinguishable from a thin one:
    "immaterial" and "we could only measure two of nine things" are different
    findings and a reader needs to tell them apart.
    """
    scores: dict[str, float] = {}
    reasons: list[str] = []

    scores["absolute_amount"] = WEIGHTS["absolute_amount"] * _ratio(
        inputs.absolute_amount, inputs.amount_scale)
    scores["relative_movement"] = WEIGHTS["relative_movement"] * _ratio(
        inputs.relative_movement, 0.25)
    scores["portfolio_share"] = WEIGHTS["portfolio_share"] * _ratio(
        inputs.portfolio_share, 0.10)
    scores["segment_share"] = WEIGHTS["segment_share"] * _ratio(
        inputs.segment_share, 0.25)
    scores["exposure_affected"] = WEIGHTS["exposure_affected"] * _ratio(
        inputs.exposure_affected, inputs.portfolio_exposure)
    scores["entities_affected"] = WEIGHTS["entities_affected"] * _ratio(
        inputs.entities_affected,
        inputs.population if inputs.population else None)
    scores["concentration"] = WEIGHTS["concentration"] * _ratio(
        inputs.concentration, 1.0)
    scores["persistence"] = (WEIGHTS["persistence"]
                             if inputs.persistent else 0.0)
    scores["threshold_severity"] = WEIGHTS["threshold_severity"] * _ratio(
        inputs.threshold_severity, 0.50)

    total = sum(scores.values())
    band = _band_for(total)
    assessment = Assessment(score=total, band=band, component_scores=scores)

    unmeasured = [k for k, v in scores.items() if v == 0.0]
    if len(unmeasured) >= len(WEIGHTS) - 2:
        reasons.append(
            f"only {len(WEIGHTS) - len(unmeasured)} of {len(WEIGHTS)} "
            "components could be measured; the score is a floor, not an "
            "estimate")

    # ---- the floors --------------------------------------------------------
    if inputs.critical_breach:
        assessment.band = _at_least(assessment.band, CRITICAL_BREACH_FLOOR)
        assessment.adjusted = "floor"
        reasons.append("a critical threshold was breached, which the bank has "
                       "already decided it cares about regardless of size")
    elif inputs.appetite_breach:
        assessment.band = _at_least(assessment.band, APPETITE_FLOOR)
        assessment.adjusted = "floor"
        reasons.append("a stated risk-appetite limit was breached")

    # ---- the caps ----------------------------------------------------------
    cap = EVIDENCE_CAPS.get(str(inputs.evidence_quality or "").upper())
    if cap:
        capped = _at_most(assessment.band, cap)
        if capped != assessment.band:
            assessment.band = capped
            assessment.adjusted = "cap"
            reasons.append(
                f"evidence quality is {inputs.evidence_quality}, so the band "
                f"is capped at {cap}. This is a cap, not a reduction: we "
                "cannot yet claim the finding is as large as it looks.")
    if not inputs.validated:
        assessment.band = _at_most(assessment.band, LOW)
        assessment.adjusted = "cap"
        reasons.append("the analysis behind this did not pass its invariants, "
                       "so nothing may be claimed from it")

    assessment.reasons = reasons
    return assessment


def explainable(assessment: Assessment) -> dict[str, Any]:
    """What a model is allowed to be given about a materiality decision.

    The band, the components and the reasons — everything needed to write a
    sentence, and nothing that would let a model produce a band of its own.
    §75: it may explain the result; it may not assign it.
    """
    return {
        "band": assessment.band,
        "score": round(assessment.score, 1),
        "top_components": [
            {"component": name, "points": round(points, 1)}
            for name, points in sorted(assessment.component_scores.items(),
                                       key=lambda kv: -kv[1])[:3]
            if points > 0],
        "reasons": list(assessment.reasons),
        "policy_version": assessment.policy_version,
        "instruction": ("Explain what this band means for the reader. Do not "
                        "restate it as your own judgement and do not assign a "
                        "different one."),
    }


__all__ = ["APPETITE_FLOOR", "Assessment", "BANDS", "CRITICAL",
           "CRITICAL_BREACH_FLOOR", "EVIDENCE_CAPS", "HIGH", "IMMATERIAL",
           "Inputs", "LOW", "MATERIALITY_VERSION", "MODERATE", "THRESHOLDS",
           "WEIGHTS", "assess", "explainable"]
