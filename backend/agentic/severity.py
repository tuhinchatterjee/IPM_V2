"""
How severe a Risk Case is. §39.

    "Do not let the LLM invent severity.
     The LLM may explain the score. It may not calculate an opaque score
     independently."

That is the whole reason this module exists as arithmetic rather than as a
prompt. A severity is an ordering: it decides which case a credit officer opens
first on a Monday morning. An ordering produced by a language model is one that
changes between two runs over identical data, cannot be explained the same way
twice, and cannot be argued with — and "why is this case above that one" is a
question somebody will eventually ask in a room where the answer matters.

The nine components are §39's own list. Each is scored 0–1 from figures the
governed runtime produced, multiplied by a published weight, and summed. The
components, the weights and the version are all stored on the case, so the
arithmetic is visible on screen and reproducible from the row.

Weights
-------
Materiality and magnitude carry the most, because a large movement on a large
exposure is what a credit function is for. Evidence quality carries real weight
in the *negative* direction: a case built on incomplete data scores lower than
the same case built on complete data, which is the correct incentive — it sends
the officer to the case that is actually established.

Bands
-----
    0.75+   CRITICAL
    0.55+   HIGH
    0.35+   MEDIUM
    below   LOW

Bands rather than a raw number on screen, because 0.62 implies a precision the
inputs do not support. The number is available underneath for ordering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

VERSION = "1.0"

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

BANDS: tuple[tuple[float, str], ...] = (
    (0.75, CRITICAL),
    (0.55, HIGH),
    (0.35, MEDIUM),
    (0.0, LOW),
)

ORDER: dict[str, int] = {CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1}

# ---------------------------------------------------------------------------
# The components — §39's list, with the weight each carries
# ---------------------------------------------------------------------------

MATERIALITY = "materiality"
MAGNITUDE = "magnitude"
SIGNALS = "adverse_signals"
PERSISTENCE = "persistence"
CONCENTRATION = "concentration"
APPETITE = "risk_appetite"
DATA_CONFIDENCE = "data_confidence"
VALIDATION = "validation"
EVIDENCE = "evidence_completeness"

WEIGHTS: dict[str, float] = {
    MATERIALITY: 0.22,
    MAGNITUDE: 0.22,
    SIGNALS: 0.12,
    PERSISTENCE: 0.10,
    CONCENTRATION: 0.08,
    APPETITE: 0.12,
    DATA_CONFIDENCE: 0.05,
    VALIDATION: 0.05,
    EVIDENCE: 0.04,
}

LABELS: dict[str, str] = {
    MATERIALITY: "Exposure at stake",
    MAGNITUDE: "Size of the movement",
    SIGNALS: "Adverse signals",
    PERSISTENCE: "How long it has been moving",
    CONCENTRATION: "Concentration",
    APPETITE: "Risk appetite",
    DATA_CONFIDENCE: "Data and relationship confidence",
    VALIDATION: "Method and invariant validation",
    EVIDENCE: "Evidence completeness",
}

#: Which components describe the RISK, and which describe how well the risk is
#: EVIDENCED. Kept apart because the quality components score high when things
#: are missing, and mixing the two produces explanations that read backwards.
RISK_COMPONENTS: frozenset[str] = frozenset(
    {MATERIALITY, MAGNITUDE, SIGNALS, PERSISTENCE, CONCENTRATION, APPETITE})
QUALITY_COMPONENTS: frozenset[str] = frozenset(
    {DATA_CONFIDENCE, VALIDATION, EVIDENCE})


def _and_list(items: list[str]) -> str:
    """"a", "a and b", "a, b and c"."""
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


#: What "material" means in the demonstration universe, in USD millions. A
#: constant rather than a magic number in a formula, and one an administrator's
#: policy can override — a bank whose smallest exposure is a billion has a
#: different idea of material.
MATERIAL_EXPOSURE = 500.0

#: A movement this large is as bad as the scale goes. 50% is not arbitrary: a
#: measure that moved by half in one quarter is at the point where a credit
#: officer stops asking how much and starts asking what happened.
FULL_MAGNITUDE = 0.50


@dataclass
class Component:
    """One part of the score, and where its number came from."""

    key: str
    value: float
    weight: float
    detail: str
    #: The raw figure behind it, so the arithmetic is checkable.
    observed: Any = None

    @property
    def label(self) -> str:
        return LABELS.get(self.key, self.key)

    @property
    def contribution(self) -> float:
        return round(self.value * self.weight, 4)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label,
                "value": round(self.value, 4), "weight": self.weight,
                "contribution": self.contribution, "detail": self.detail,
                "observed": self.observed}


@dataclass
class Score:
    """A severity, and the arithmetic behind it."""

    score: float = 0.0
    band: str = LOW
    components: list[Component] = field(default_factory=list)
    version: str = VERSION

    @property
    def rank(self) -> int:
        return ORDER.get(self.band, 1)

    def component(self, key: str) -> Component | None:
        return next((c for c in self.components if c.key == key), None)

    def explain(self) -> str:
        """The components that drove it, as a sentence.

        This is what the LLM is permitted to elaborate on (§39) and what it may
        not replace: the sentence is generated from the arithmetic, so it
        cannot disagree with the number beside it.

        Risk and quality are described separately, and that separation is not
        cosmetic. `evidence_completeness` scores HIGH when evidence is MISSING,
        so a low-severity case with thin evidence has "evidence completeness"
        as its largest single contributor — and "low severity, driven by
        evidence completeness" reads as though completeness caused the risk,
        which is the opposite of what the component measures.
        """
        risk = [c for c in self.components if c.key in RISK_COMPONENTS
                and c.contribution > 0.01]
        # A quality component now scores HIGH when things are complete, so
        # what is worth naming is a WEAK one.
        quality = [c for c in self.components
                   if c.key in {DATA_CONFIDENCE, EVIDENCE} and c.value < 0.5]
        risk.sort(key=lambda c: -c.contribution)

        if risk:
            said = (f"{self.band.title()} severity, driven by "
                    f"{_and_list([c.label.lower() for c in risk[:3]])}.")
        else:
            said = ("Nothing in the governed risk signals makes this "
                    "material.")
        if quality:
            said += (f" Thin on "
                     f"{_and_list([c.label.lower() for c in quality[:2]])}.")
        return said

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "band": self.band,
            "rank": self.rank,
            "version": self.version,
            "explanation": self.explain(),
            "weights": dict(WEIGHTS),
            "components": [c.to_dict() for c in self.components],
        }


# ---------------------------------------------------------------------------
# Computing it
# ---------------------------------------------------------------------------


def compute(*, exposure: float | None = None,
            portfolio_exposure: float | None = None,
            movement: float | None = None,
            adverse_signals: int = 0, total_signals: int = 0,
            periods_moving: int = 0,
            concentration_share: float | None = None,
            appetite_breached: bool = False,
            appetite_headroom: float | None = None,
            data_confidence: float = 1.0,
            invariants_passed: bool = True,
            invariants_checked: int = 0,
            evidence_present: int = 0, evidence_expected: int = 0,
            material_exposure: float = MATERIAL_EXPOSURE) -> Score:
    """Score a case from what the governed runtime measured.

    Every argument is an observation, not a judgement. `movement` is a
    proportion — 0.18 for an 18% deterioration — and its SIGN is ignored here
    because the caller has already established, from the ontology's
    `higher_is_worse`, that the movement is adverse. Deciding that inside a
    severity formula would be the formula having an opinion about credit.
    """
    found: list[Component] = []

    found.append(_materiality(exposure, portfolio_exposure, material_exposure))
    found.append(_magnitude(movement))
    found.append(_signals(adverse_signals, total_signals))
    found.append(_persistence(periods_moving))
    found.append(_concentration(concentration_share))
    found.append(_appetite(appetite_breached, appetite_headroom))
    found.append(_data(data_confidence))
    found.append(_validation(invariants_passed, invariants_checked))
    found.append(_evidence(evidence_present, evidence_expected))

    total = sum(c.contribution for c in found)
    return Score(score=round(min(1.0, max(0.0, total)), 4),
                 band=band_for(total), components=found)


def band_for(score: float) -> str:
    for floor, name in BANDS:
        if score >= floor:
            return name
    return LOW


# -- individual components --------------------------------------------------


def _materiality(exposure: float | None, portfolio: float | None,
                 material: float) -> Component:
    """How much money is at stake.

    Measured two ways and the larger taken: an absolute threshold, so a large
    single exposure scores, and a share of the portfolio, so a case that is
    small in absolute terms but large for this book still scores.
    """
    if exposure is None:
        return Component(MATERIALITY, 0.0, WEIGHTS[MATERIALITY],
                         "No exposure figure is attached to this case.", None)
    absolute = min(1.0, max(0.0, float(exposure) / material)) if material else 0.0
    share = 0.0
    if portfolio:
        share = min(1.0, max(0.0, float(exposure) / float(portfolio)) * 5)
    value = max(absolute, share)
    return Component(
        MATERIALITY, value, WEIGHTS[MATERIALITY],
        f"{float(exposure):,.0f} of exposure is affected.", float(exposure))


def _magnitude(movement: float | None) -> Component:
    if movement is None:
        return Component(MAGNITUDE, 0.0, WEIGHTS[MAGNITUDE],
                         "No movement was measured.", None)
    size = abs(float(movement))
    value = min(1.0, size / FULL_MAGNITUDE) if FULL_MAGNITUDE else 0.0
    return Component(MAGNITUDE, value, WEIGHTS[MAGNITUDE],
                     f"The measure moved {size:.1%} against the prior period.",
                     round(float(movement), 6))


def _signals(adverse: int, total: int) -> Component:
    """How many governed signals point the wrong way.

    Scored against the number that were LOOKED AT, not against a fixed
    expectation: three adverse signals out of three checked is worse than three
    out of nine, and a formula that ignores the denominator says they are the
    same.
    """
    if adverse <= 0:
        return Component(SIGNALS, 0.0, WEIGHTS[SIGNALS],
                         "No adverse signal was found.", 0)
    denominator = max(total, adverse, 1)
    ratio = adverse / denominator
    # Two adverse signals is meaningfully worse than one even where many were
    # checked, so the count contributes alongside the ratio.
    count = min(1.0, adverse / 4.0)
    value = min(1.0, 0.5 * ratio + 0.5 * count)
    return Component(SIGNALS, value, WEIGHTS[SIGNALS],
                     f"{adverse} of {denominator} governed signals are "
                     f"adverse.", adverse)


def _persistence(periods: int) -> Component:
    if periods <= 1:
        return Component(PERSISTENCE, 0.0 if periods < 1 else 0.25,
                         WEIGHTS[PERSISTENCE],
                         "This is the first period the measure has moved."
                         if periods == 1 else
                         "Movement over time was not measured.", periods)
    value = min(1.0, (periods - 1) / 3.0)
    return Component(PERSISTENCE, value, WEIGHTS[PERSISTENCE],
                     f"It has moved in the same direction for {periods} "
                     f"consecutive periods.", periods)


def _concentration(share: float | None) -> Component:
    if share is None:
        return Component(CONCENTRATION, 0.0, WEIGHTS[CONCENTRATION],
                         "Concentration was not measured.", None)
    value = min(1.0, max(0.0, float(share)))
    return Component(CONCENTRATION, value, WEIGHTS[CONCENTRATION],
                     f"{value:.0%} of the movement sits in the largest "
                     f"contributors.", round(float(share), 4))


def _appetite(breached: bool, headroom: float | None) -> Component:
    if breached:
        return Component(APPETITE, 1.0, WEIGHTS[APPETITE],
                         "A risk-appetite threshold is breached.", True)
    if headroom is None:
        return Component(APPETITE, 0.0, WEIGHTS[APPETITE],
                         "No risk-appetite threshold applies.", None)
    # Headroom as a proportion of the limit: 0.05 left is nearly breached.
    left = max(0.0, min(1.0, float(headroom)))
    value = max(0.0, 1.0 - left * 4)
    return Component(APPETITE, value, WEIGHTS[APPETITE],
                     f"{left:.0%} of the risk-appetite headroom remains.",
                     round(float(headroom), 4))


def _data(confidence: float) -> Component:
    """How much of the picture the governed data actually shows.

    Scores HIGH when confidence is high, like every other component. The first
    version inverted it — poor data raised severity, on the argument that a
    case nobody can see properly is itself worrying — and the evaluation corpus
    caught what that costs: a case built on incomplete data outranked the same
    case built on complete data, which sends an officer to the least
    established finding first.

    "We cannot see this clearly" is a real concern, and it belongs in a
    DATA_QUALITY case of its own (§44), where somebody can fix the data. It
    does not belong inflating the severity of a borrower case.
    """
    level = max(0.0, min(1.0, float(confidence)))
    return Component(DATA_CONFIDENCE, level, WEIGHTS[DATA_CONFIDENCE],
                     f"Data and relationship confidence is {level:.0%}."
                     if level < 1.0 else
                     "The data and relationships behind this are complete.",
                     round(level, 4))


def _validation(passed: bool, checked: int) -> Component:
    if not checked:
        return Component(VALIDATION, 0.3, WEIGHTS[VALIDATION],
                         "No invariant applied to these figures.", 0)
    if not passed:
        return Component(VALIDATION, 1.0, WEIGHTS[VALIDATION],
                         "A business invariant did not hold; the figures need "
                         "review before they are acted on.", checked)
    return Component(VALIDATION, 0.0, WEIGHTS[VALIDATION],
                     f"All {checked} invariant(s) held.", checked)


def _evidence(present: int, expected: int) -> Component:
    """How much of the expected evidence is actually attached.

    Scores with coverage, so a complete case outranks a thin one. This is the
    direction the module's own docstring always argued for and the arithmetic
    originally did the opposite of — the evaluation corpus caught it (PRI-2).
    Sending a credit officer to the case with the least behind it is exactly
    backwards.
    """
    if not expected:
        return Component(EVIDENCE, 0.0, WEIGHTS[EVIDENCE],
                         "No evidence was expected for this case.", None)
    coverage = max(0.0, min(1.0, present / expected))
    return Component(EVIDENCE, coverage, WEIGHTS[EVIDENCE],
                     f"{present} of {expected} pieces of expected evidence "
                     f"are attached.", round(coverage, 4))


def coverage_of(present: int, expected: int) -> float:
    """The evidence-coverage figure stored on the case."""
    if not expected:
        return 0.0
    return round(max(0.0, min(1.0, present / expected)), 4)


def priority(score: Score, *, exposure: float | None = None,
             unresolved_days: int = 0, overdue: bool = False) -> int:
    """The order cases appear in. §46.

    Severity first, then the things that make one severe case more urgent than
    another: money, age, and a date somebody committed to. An integer so the
    database can sort on it without recomputing.

    §46's "do not let UI ordering depend solely on model prose" is satisfied by
    there being no prose in this function at all.
    """
    base = score.rank * 1_000_000
    money = int(min(999, (exposure or 0) / 10)) * 1_000
    age = min(500, unresolved_days) * 2
    due = 400 if overdue else 0
    return int(base + money + age + due)


__all__ = [
    "APPETITE",
    "BANDS",
    "CONCENTRATION",
    "CRITICAL",
    "DATA_CONFIDENCE",
    "EVIDENCE",
    "HIGH",
    "LABELS",
    "LOW",
    "MAGNITUDE",
    "MATERIALITY",
    "MATERIAL_EXPOSURE",
    "MEDIUM",
    "ORDER",
    "QUALITY_COMPONENTS",
    "RISK_COMPONENTS",
    "PERSISTENCE",
    "SIGNALS",
    "VALIDATION",
    "VERSION",
    "WEIGHTS",
    "Component",
    "Score",
    "band_for",
    "compute",
    "coverage_of",
    "priority",
]
