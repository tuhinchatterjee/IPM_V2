"""
Contradictory signals: detecting them, diagnosing them, and refusing to
explain them away. §81, §82, §83, §84.

    "Never invent a plausible story merely to avoid UNRESOLVED."

That is the only sentence in Part B that names the failure directly, and it is
the failure this module exists for. A contradiction — ECL falling while DPD
and downgrades rise — has a dozen plausible explanations, and a model asked
what is going on will supply one. It will be fluent, it will be economically
sensible, and there will be no evidence for it. The reader will believe it,
because it is exactly what a good analyst would say if a good analyst had
checked.

So: the signals are normalised into a shared schema (§81), the taxonomy of
explanations is closed (§82), fifteen diagnostic checks run and are RECORDED
(§83), and the outcome is one of five — one of which is UNRESOLVED and another
of which is MULTIPLE_POSSIBLE_EXPLANATIONS, because §82 says not to force one
when several remain.

Why direction is the hard part
------------------------------
Two signals contradict when they point opposite ways in RISK terms, which is
not the same as opposite signs. Rising ECL and falling DSCR both mean
deterioration. Rising ECL and improving rating contradict. So every signal
carries its own direction of deterioration, and the comparison is between what
the movements MEAN.

Timing is the commonest real explanation
-----------------------------------------
Most apparent contradictions in credit data are lag: a rating reviewed
annually against a DPD updated daily is not contradicting anything, it is
answering a question about a different month. TIMING_LAG and THRESHOLD_LAG are
first in the taxonomy because they are first in reality, and a diagnostic
sequence that checked concentration before update frequency would spend its
effort in the wrong place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.judgment import evidence as ev

CONTRADICTION_VERSION = "1.0.0"

# ------------------------------------------------------ §82's taxonomy
TIMING_LAG = "TIMING_LAG"
THRESHOLD_LAG = "THRESHOLD_LAG"
AGGREGATION_EFFECT = "AGGREGATION_EFFECT"
PORTFOLIO_MIX_EFFECT = "PORTFOLIO_MIX_EFFECT"
ACCOUNTING_VS_RISK = "ACCOUNTING_VS_RISK_EFFECT"
TEMPORARY_VS_PERSISTENT = "TEMPORARY_VS_PERSISTENT"
CONCENTRATION_EFFECT = "CONCENTRATION_EFFECT"
DATA_QUALITY_EFFECT = "DATA_QUALITY_EFFECT"
MISALIGNMENT = "RELATIONSHIP_OR_PERIOD_MISALIGNMENT"
MODEL_OR_OVERRIDE = "MODEL_OR_OVERRIDE_EFFECT"
CLASSIFICATION_LAG = "CLASSIFICATION_LAG"
TRUE_CONTRADICTION = "TRUE_UNRESOLVED_CONTRADICTION"
MULTIPLE = "MULTIPLE_POSSIBLE_EXPLANATIONS"

EXPLANATIONS: tuple[str, ...] = (
    TIMING_LAG, THRESHOLD_LAG, AGGREGATION_EFFECT, PORTFOLIO_MIX_EFFECT,
    ACCOUNTING_VS_RISK, TEMPORARY_VS_PERSISTENT, CONCENTRATION_EFFECT,
    DATA_QUALITY_EFFECT, MISALIGNMENT, MODEL_OR_OVERRIDE, CLASSIFICATION_LAG,
    TRUE_CONTRADICTION, MULTIPLE,
)

#: What each explanation actually claims, in the words a reviewer would use to
#: agree or disagree with it. A taxonomy whose entries are only labels is a
#: taxonomy people file things under by vibe.
MEANS: dict[str, str] = {
    TIMING_LAG: "The two signals are measured at different frequencies, so "
                "the slower one has not caught up yet.",
    THRESHOLD_LAG: "The slower signal is a threshold that has not been "
                   "crossed, not a measure that has not moved.",
    AGGREGATION_EFFECT: "The signals disagree at the aggregate and agree "
                        "underneath it, because they aggregate differently.",
    PORTFOLIO_MIX_EFFECT: "The composition changed, so a measure moved "
                          "without anything in it moving.",
    ACCOUNTING_VS_RISK: "One signal is an accounting outcome and the other a "
                        "risk measure, and they legitimately diverge.",
    TEMPORARY_VS_PERSISTENT: "One movement is a spike and the other a trend, "
                             "so they are not describing the same thing.",
    CONCENTRATION_EFFECT: "A small number of entities move one signal and not "
                          "the other.",
    DATA_QUALITY_EFFECT: "One signal is computed over materially incomplete "
                         "data.",
    MISALIGNMENT: "The two sides are not on the same periods, population or "
                  "join path.",
    MODEL_OR_OVERRIDE: "An overlay, override or model change moved one signal "
                       "independently of the underlying risk.",
    CLASSIFICATION_LAG: "A classification — stage, grade, bucket — is "
                        "reviewed on a cycle the other signal does not "
                        "follow.",
    TRUE_CONTRADICTION: "Every check ran and none explains it. The signals "
                        "genuinely disagree and somebody needs to look.",
    MULTIPLE: "Several explanations remain possible and the evidence does not "
              "choose between them.",
}

# ---------------------------------------------------------- §84's outcomes
EXPLAINED = "EXPLAINED"
PARTIALLY_EXPLAINED = "PARTIALLY_EXPLAINED"
UNRESOLVED = "UNRESOLVED"
NOT_A_CONTRADICTION = "NOT_A_TRUE_CONTRADICTION"
DATA_INSUFFICIENT = "DATA_INSUFFICIENT"

OUTCOMES: tuple[str, ...] = (EXPLAINED, PARTIALLY_EXPLAINED, UNRESOLVED,
                             NOT_A_CONTRADICTION, DATA_INSUFFICIENT)

# ------------------------------------------------------ §83's fifteen checks
#
# In §83's order, which is the order that matters: timing and alignment first,
# because most apparent contradictions in credit data are lag, and a sequence
# that checked concentration before update frequency would spend its effort in
# the wrong place.
CHECKS: tuple[tuple[str, str, str], ...] = (
    ("period_alignment", "Period alignment",
     "Are both signals measured over the same window?"),
    ("population_alignment", "Population alignment",
     "Are both computed over the same set of entities?"),
    ("grain_alignment", "Grain alignment",
     "Are both at the same grain?"),
    ("directional_semantics", "Directional semantics",
     "Does each movement mean what it appears to mean for credit risk?"),
    ("update_frequency", "Update frequency and lag",
     "Are the two refreshed on the same cycle?"),
    ("threshold_crossings", "Threshold crossings",
     "Is the slower signal a threshold that has simply not been crossed?"),
    ("portfolio_mix", "Portfolio-mix change",
     "Did the composition change underneath the measures?"),
    ("denominator", "Denominator change",
     "Did a denominator move independently of its numerator?"),
    ("concentration", "Concentration",
     "Do a few entities move one signal and not the other?"),
    ("new_exited", "New and exited entities",
     "Does the population change explain the divergence?"),
    ("data_quality", "Data-quality warnings",
     "Is either signal computed over materially incomplete data?"),
    ("relationship_match", "Relationship match",
     "Did the join between the two sources behave?"),
    ("overlay", "Overlay and override effects",
     "Did an overlay move one signal independently of risk?"),
    ("persistence", "Persistence",
     "Is one a spike and the other a trend?"),
    ("controls", "Controls and alternative grouping",
     "Does the divergence survive an approved alternative cut?"),
)

CHECK_IDS: tuple[str, ...] = tuple(c[0] for c in CHECKS)
CHECK_LABEL: dict[str, str] = {c[0]: c[1] for c in CHECKS}
CHECK_QUESTION: dict[str, str] = {c[0]: c[2] for c in CHECKS}

#: Which explanation a check supports when it FIRES. A check that fires is
#: evidence for one thing, not a general excuse, and mapping them here stops a
#: diagnostic sequence from concluding whatever the writer expected.
SUPPORTS: dict[str, str] = {
    "period_alignment": MISALIGNMENT,
    "population_alignment": MISALIGNMENT,
    "grain_alignment": AGGREGATION_EFFECT,
    "directional_semantics": NOT_A_CONTRADICTION,
    "update_frequency": TIMING_LAG,
    "threshold_crossings": THRESHOLD_LAG,
    "portfolio_mix": PORTFOLIO_MIX_EFFECT,
    "denominator": PORTFOLIO_MIX_EFFECT,
    "concentration": CONCENTRATION_EFFECT,
    "new_exited": PORTFOLIO_MIX_EFFECT,
    "data_quality": DATA_QUALITY_EFFECT,
    "relationship_match": MISALIGNMENT,
    "overlay": MODEL_OR_OVERRIDE,
    "persistence": TEMPORARY_VS_PERSISTENT,
    "controls": AGGREGATION_EFFECT,
}

# --------------------------------------------------------- check outcomes
CLEAR = "CLEAR"
#: The check found the thing it was looking for. This is what EXPLAINS a
#: contradiction, so "fired" is not a failure — it is the diagnostic working.
FIRED = "FIRED"
NOT_RUN = "NOT_RUN"
NOT_APPLICABLE = "NOT_APPLICABLE"

CHECK_OUTCOMES: tuple[str, ...] = (CLEAR, FIRED, NOT_RUN, NOT_APPLICABLE)


@dataclass
class Signal:
    """§81's normalised signal."""

    signal_id: str
    metric: str = ""
    entity: str = ""
    population: str = ""
    opening_period: str = ""
    closing_period: str = ""
    #: The movement, signed in the metric's own units.
    movement: float | None = None
    #: WORSE | BETTER | FLAT | UNKNOWN — what the movement MEANS.
    direction: str = ev.UNKNOWN_DIRECTION
    #: How to read it in credit terms, in one clause.
    risk_interpretation: str = ""
    #: How often the source refreshes. The commonest real explanation lives
    #: here: a rating reviewed annually against a DPD updated daily is not
    #: contradicting anything.
    timing_frequency: str = ""
    grain: str = ""
    evidence_quality: str = ev.PARTIAL
    #: Whether a governed threshold was crossed. A measure that moved without
    #: crossing anything and a classification that did not move are the same
    #: observation seen from two sides.
    threshold_status: str = ""
    source_run: str = ""
    validation: str = ev.UNVALIDATED
    fact_ids: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.validation == ev.VALIDATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id, "metric": self.metric,
            "entity": self.entity, "population": self.population,
            "opening_period": self.opening_period,
            "closing_period": self.closing_period, "movement": self.movement,
            "direction": self.direction,
            "risk_interpretation": self.risk_interpretation,
            "timing_frequency": self.timing_frequency, "grain": self.grain,
            "evidence_quality": self.evidence_quality,
            "threshold_status": self.threshold_status,
            "source_run": self.source_run, "validation": self.validation,
            "fact_ids": list(self.fact_ids),
        }


@dataclass(frozen=True)
class Pair:
    """Two signals that disagree."""

    left: Signal
    right: Signal

    @property
    def contradictory(self) -> bool:
        """Whether these genuinely point opposite ways IN RISK TERMS.

        Not opposite signs. Rising ECL and falling DSCR both mean
        deterioration, and a sign comparison calls that a contradiction; a
        rising ECL against an improving rating is one, and a sign comparison
        misses it.
        """
        directions = {self.left.direction, self.right.direction}
        return directions == {ev.WORSE, ev.BETTER} or (
            ev.FLAT in directions and ev.WORSE in directions
            and self.left.threshold_status != "crossed"
            and self.right.threshold_status != "crossed")

    def to_dict(self) -> dict[str, Any]:
        return {"left": self.left.to_dict(), "right": self.right.to_dict(),
                "contradictory": self.contradictory}


def detect(signals: list[Signal]) -> list[Pair]:
    """Every pair of signals that disagrees in risk terms.

    Only validated signals. An unvalidated signal disagreeing with a validated
    one is not a contradiction in the data — it is a contradiction between a
    measurement and a guess, and diagnosing it would be diagnosing the guess.
    """
    usable = [s for s in signals if s.usable]
    found: list[Pair] = []
    for index, left in enumerate(usable):
        for right in usable[index + 1:]:
            pair = Pair(left=left, right=right)
            if pair.contradictory:
                found.append(pair)
    return found


@dataclass
class Check:
    """One of §83's fifteen, and what it found."""

    check_id: str
    outcome: str = NOT_RUN
    detail: str = ""
    fact_ids: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return CHECK_LABEL.get(self.check_id, self.check_id)

    @property
    def supports(self) -> str:
        return SUPPORTS.get(self.check_id, "") if self.outcome == FIRED else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id, "label": self.label,
            "question": CHECK_QUESTION.get(self.check_id, ""),
            "outcome": self.outcome, "detail": self.detail,
            "supports": self.supports, "fact_ids": list(self.fact_ids),
        }


@dataclass
class Diagnosis:
    """§83's sequence and §84's outcome, for one contradiction."""

    pair: Pair | None = None
    checks: list[Check] = field(default_factory=list)
    #: Explanations the evidence supports. Plural on purpose: §82 says not to
    #: force one when several remain possible.
    explanations: list[str] = field(default_factory=list)
    outcome: str = UNRESOLVED
    review_candidates: list[str] = field(default_factory=list)
    next_analysis: list[str] = field(default_factory=list)

    def record(self, check_id: str, outcome: str, *, detail: str = "",
               facts: list[str] | None = None) -> Check:
        if check_id not in CHECK_IDS:
            raise KeyError(f"{check_id!r} is not one of §83's checks")
        if outcome not in CHECK_OUTCOMES:
            raise ValueError(f"{outcome!r} is not a check outcome")
        if outcome == FIRED and not detail:
            raise ValueError(
                "a check that fired must say what it found; a diagnosis that "
                "explains a contradiction without evidence is the story §84 "
                "forbids")
        found = Check(check_id=check_id, outcome=outcome, detail=detail,
                      fact_ids=list(facts or []))
        self.checks.append(found)
        return found

    @property
    def run(self) -> set[str]:
        return {c.check_id for c in self.checks if c.outcome != NOT_RUN}

    @property
    def not_run(self) -> list[str]:
        return [c for c in CHECK_IDS if c not in self.run]

    @property
    def fired(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == FIRED]

    @property
    def complete(self) -> bool:
        """Whether all fifteen were attempted.

        §83: "Record every check." An unrun check is not a clear one, and a
        diagnosis that ran four checks and concluded EXPLAINED has concluded
        from four checks.
        """
        return not self.not_run

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONTRADICTION_VERSION,
            "pair": self.pair.to_dict() if self.pair else None,
            "checks": [c.to_dict() for c in self.checks],
            "not_run": list(self.not_run),
            "complete": self.complete,
            "explanations": [{"id": e, "means": MEANS.get(e, "")}
                             for e in self.explanations],
            "outcome": self.outcome,
            "review_candidates": list(self.review_candidates),
            "next_analysis": list(self.next_analysis),
            "statement": self.statement(),
        }

    def statement(self) -> str:
        """§84's required content, as a paragraph a reader can check.

        Names the signals, the checks, what is supported and what is not.
        Deliberately says how many checks ran: a diagnosis is only as good as
        its coverage, and a confident conclusion from four of fifteen checks
        should look like what it is.
        """
        if self.pair is None:
            return ""
        left, right = self.pair.left, self.pair.right
        head = (f"{left.metric} moved {left.direction.lower()} while "
                f"{right.metric} moved {right.direction.lower()}.")
        coverage = (f" {len(self.run)} of {len(CHECK_IDS)} diagnostic checks "
                    "ran.")
        if self.outcome == NOT_A_CONTRADICTION:
            return head + coverage + (
                " These do not in fact disagree: " +
                "; ".join(c.detail for c in self.fired) + ".")
        if self.outcome == DATA_INSUFFICIENT:
            return head + coverage + (
                " Too few checks could be run to diagnose it.")
        if self.outcome == UNRESOLVED:
            return head + coverage + (
                " No check explains the divergence. The signals genuinely "
                "disagree and this needs somebody to look.")
        supported = "; ".join(MEANS.get(e, e) for e in self.explanations)
        if self.outcome == PARTIALLY_EXPLAINED:
            return head + coverage + f" Part of it is explained: {supported} " \
                                     "The rest is not."
        return head + coverage + f" {supported}"


#: How many of the fifteen must run before an outcome other than
#: DATA_INSUFFICIENT may be claimed. Two-thirds: below that, a diagnosis is a
#: sample of the diagnostics rather than the sequence.
MIN_CHECKS = 10


def conclude(diagnosis: Diagnosis) -> Diagnosis:
    """§84's outcome, from the checks and nothing else.

    The whole module comes down to this function refusing to be clever. It
    reads which checks fired, maps them to explanations, and picks the outcome
    the evidence supports — including UNRESOLVED, which is the right answer
    more often than any narrative wants it to be.
    """
    fired = diagnosis.fired
    diagnosis.explanations = sorted({c.supports for c in fired if c.supports}
                                    - {NOT_A_CONTRADICTION})

    directional = next((c for c in fired
                        if c.check_id == "directional_semantics"), None)
    if directional:
        diagnosis.outcome = NOT_A_CONTRADICTION
        diagnosis.explanations = []
        return diagnosis

    if len(diagnosis.run) < MIN_CHECKS:
        diagnosis.outcome = DATA_INSUFFICIENT
        diagnosis.next_analysis = [
            f"run the {len(diagnosis.not_run)} diagnostic checks that could "
            "not be run"]
        return diagnosis

    if not diagnosis.explanations:
        diagnosis.outcome = UNRESOLVED
        diagnosis.explanations = [TRUE_CONTRADICTION]
        diagnosis.review_candidates = [
            f"{diagnosis.pair.left.entity or 'the population'}: "
            f"{diagnosis.pair.left.metric} against "
            f"{diagnosis.pair.right.metric}"] if diagnosis.pair else []
        return diagnosis

    if len(diagnosis.explanations) > 1:
        # §82: "Do not force one explanation when several remain possible."
        diagnosis.outcome = PARTIALLY_EXPLAINED
        diagnosis.explanations = [*diagnosis.explanations, MULTIPLE]
        diagnosis.next_analysis = [
            "an analysis that would distinguish between the remaining "
            "explanations"]
        return diagnosis

    # One explanation, and enough checks ran to trust it. Still only
    # PARTIALLY_EXPLAINED if a material check could not run: an explanation
    # that survives ten checks and is untested against five is a hypothesis
    # that has done well, not a conclusion.
    diagnosis.outcome = (EXPLAINED if diagnosis.complete
                         else PARTIALLY_EXPLAINED)
    if not diagnosis.complete:
        diagnosis.next_analysis = [
            f"the {len(diagnosis.not_run)} checks that did not run"]
    return diagnosis


def diagnose(pair: Pair) -> Diagnosis:
    """An empty diagnosis for a pair, with every check unrun.

    Starts complete-but-unrun rather than empty so `not_run` is meaningful
    from the first moment: a diagnosis that has not started and one that ran
    nothing look the same otherwise.
    """
    return Diagnosis(pair=pair)


__all__ = ["ACCOUNTING_VS_RISK", "AGGREGATION_EFFECT", "CHECKS", "CHECK_IDS",
           "CHECK_LABEL", "CHECK_OUTCOMES", "CHECK_QUESTION",
           "CLASSIFICATION_LAG", "CLEAR", "CONCENTRATION_EFFECT",
           "CONTRADICTION_VERSION", "Check", "DATA_INSUFFICIENT",
           "DATA_QUALITY_EFFECT", "Diagnosis", "EXPLAINED", "EXPLANATIONS",
           "FIRED", "MEANS", "MIN_CHECKS", "MISALIGNMENT", "MODEL_OR_OVERRIDE",
           "MULTIPLE", "NOT_APPLICABLE", "NOT_A_CONTRADICTION", "NOT_RUN",
           "OUTCOMES", "PARTIALLY_EXPLAINED", "PORTFOLIO_MIX_EFFECT", "Pair",
           "SUPPORTS", "Signal", "TEMPORARY_VS_PERSISTENT", "THRESHOLD_LAG",
           "TIMING_LAG", "TRUE_CONTRADICTION", "UNRESOLVED", "conclude",
           "detect", "diagnose"]
