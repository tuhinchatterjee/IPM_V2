"""
The client-presentability rubric: eighteen dimensions, two kinds of failure.
§94.

    "Safety failures block display.
     Quality failures trigger repair or a deterministic summary."

That distinction is the module. Eighteen scored dimensions with one verdict
between them would either withhold answers over a repeated phrase or show
answers with ungrounded figures in them, depending on where the threshold
landed — and neither is defensible in front of a credit committee.

So a failure is one of two things. A SAFETY failure means the answer asserts
something that is not true or not established: an ungrounded figure, a causal
claim from an association, the wrong period, a chart that does not reconcile.
Those block display outright; there is no version of showing them that is
better than not showing them. A QUALITY failure means the answer is true and
badly delivered: repetitive, indirect, over-long, missing its limitations.
Those get one repair attempt, and if repair does not fix them the reader gets
a deterministic summary built from the facts — which is plainer than the model
would have written and is never wrong.

Why a deterministic summary rather than nothing
------------------------------------------------
A withheld answer to a question whose analysis succeeded wastes the analysis.
The facts are computed, validated and grounded; what failed was the prose. So
the fallback renders the facts themselves in a fixed form. It reads like a
machine wrote it, because one did, and every figure in it came from the
Evidence Fact Graph.

This is not the P0.8 gate
--------------------------
`orchestration.presentable` gates an ANSWER on fourteen checks and is in the
live path. This rubric scores an INVESTIGATION's presentability on §94's
eighteen dimensions, several of which only exist once Part B's engines have
run — driver quality, breadth, persistence, contradictions. They agree where
they overlap and neither replaces the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RUBRIC_VERSION = "1.0.0"

# ------------------------------------------------------- §94's eighteen
DIRECTNESS = "DIRECTNESS"
OBJECTIVE_COMPLETENESS = "OBJECTIVE_COMPLETENESS"
MATERIALITY = "MATERIALITY"
DRIVER_QUALITY = "DRIVER_QUALITY"
BREADTH_CONCENTRATION = "BREADTH_CONCENTRATION"
PERSISTENCE = "PERSISTENCE"
EXCEPTIONS = "EXCEPTIONS"
CONTRADICTIONS = "CONTRADICTIONS"
PERIOD_POPULATION_ACCURACY = "PERIOD_POPULATION_ACCURACY"
GROUNDING = "GROUNDING"
NON_CAUSAL_LANGUAGE = "NON_CAUSAL_LANGUAGE"
LIMITATIONS = "LIMITATIONS"
ACTIONABILITY = "ACTIONABILITY"
CONCISION = "CONCISION"
NO_REPETITION = "NO_REPETITION"
NUMBER_FORMATTING = "NUMBER_FORMATTING"
VISUAL_VALIDITY = "VISUAL_VALIDITY"
TRACE_CONSISTENCY = "TRACE_CONSISTENCY"

DIMENSIONS: tuple[str, ...] = (
    DIRECTNESS, OBJECTIVE_COMPLETENESS, MATERIALITY, DRIVER_QUALITY,
    BREADTH_CONCENTRATION, PERSISTENCE, EXCEPTIONS, CONTRADICTIONS,
    PERIOD_POPULATION_ACCURACY, GROUNDING, NON_CAUSAL_LANGUAGE, LIMITATIONS,
    ACTIONABILITY, CONCISION, NO_REPETITION, NUMBER_FORMATTING,
    VISUAL_VALIDITY, TRACE_CONSISTENCY,
)

#: What each dimension asks, in the words a reviewer would use.
ASKS: dict[str, str] = {
    DIRECTNESS: "Does the first sentence answer the question that was asked?",
    OBJECTIVE_COMPLETENESS: "Is every objective in the question addressed or "
                            "explicitly declined?",
    MATERIALITY: "Is the size of what is reported stated in terms that "
                 "distinguish a large movement from a large percentage?",
    DRIVER_QUALITY: "Do the named drivers reconcile to the movement they "
                    "explain?",
    BREADTH_CONCENTRATION: "Is broad-or-concentrated stated from measures "
                           "rather than asserted?",
    PERSISTENCE: "Is a movement distinguished from a trend, with the history "
                 "that supports it?",
    EXCEPTIONS: "Is what does not fit the pattern reported?",
    CONTRADICTIONS: "Are disagreeing signals reported rather than netted "
                    "away?",
    PERIOD_POPULATION_ACCURACY: "Are the period and the population the answer "
                                "describes the ones it was computed over?",
    GROUNDING: "Does every figure trace to a validated fact?",
    NON_CAUSAL_LANGUAGE: "Are associations described as associations?",
    LIMITATIONS: "Is what could not be established stated?",
    ACTIONABILITY: "Does the answer name something specific to do next?",
    CONCISION: "Is the answer as short as the content allows?",
    NO_REPETITION: "Does the answer say each thing once?",
    NUMBER_FORMATTING: "Is every figure formatted to the display contract?",
    VISUAL_VALIDITY: "Did the chart pass the Visual Critic?",
    TRACE_CONSISTENCY: "Does the Trace match what actually ran?",
}

# ---------------------------------------------------------- failure classes
#: The answer asserts something untrue or unestablished. There is no version
#: of showing it that is better than not showing it.
SAFETY: frozenset[str] = frozenset({
    GROUNDING, NON_CAUSAL_LANGUAGE, PERIOD_POPULATION_ACCURACY,
    DRIVER_QUALITY, CONTRADICTIONS, VISUAL_VALIDITY, TRACE_CONSISTENCY,
    NUMBER_FORMATTING})

#: The answer is true and badly delivered. Repairable.
QUALITY: frozenset[str] = frozenset(DIMENSIONS) - SAFETY

#: Why each safety dimension is one. Written out because "safety" is the word
#: every dimension's owner will want applied to theirs.
SAFETY_BECAUSE: dict[str, str] = {
    GROUNDING: "A figure with no fact behind it was invented, and the reader "
               "cannot tell which one it was.",
    NON_CAUSAL_LANGUAGE: "A causal claim from an association is a different "
                         "statement from the one the evidence supports, and "
                         "it is the one that gets acted on.",
    PERIOD_POPULATION_ACCURACY: "An answer about the wrong quarter or the "
                                "wrong book is a correct calculation of "
                                "something nobody asked about.",
    DRIVER_QUALITY: "Contributions that do not reconcile mean the named "
                    "drivers are not what moved it.",
    CONTRADICTIONS: "Netting away a disagreement hides the one thing that "
                    "needed a person to look.",
    VISUAL_VALIDITY: "A chart that does not reconcile to its own table puts "
                     "two numbers on screen with only one of them right.",
    TRACE_CONSISTENCY: "A Trace that does not match what ran removes the "
                       "only way to check any of the above.",
    NUMBER_FORMATTING: "A figure shown to four decimals claims a precision "
                       "the calculation does not have.",
}

PASS = "PASS"
FAIL = "FAIL"
NOT_APPLICABLE = "NOT_APPLICABLE"
#: Nothing was supplied to check. Never PASS, and for a safety dimension it
#: blocks: an unchecked grounding check is an ungrounded answer nobody looked
#: at.
UNCHECKED = "UNCHECKED"

OUTCOMES: tuple[str, ...] = (PASS, FAIL, NOT_APPLICABLE, UNCHECKED)

# --------------------------------------------------------------- verdicts
SHOW = "SHOW"
#: One attempt at fixing the prose, then re-score.
REPAIR = "REPAIR"
#: The facts, rendered plainly. Reads like a machine wrote it, because one
#: did, and every figure came from the Evidence Fact Graph.
DETERMINISTIC_SUMMARY = "DETERMINISTIC_SUMMARY"
BLOCK = "BLOCK"

VERDICTS: tuple[str, ...] = (SHOW, REPAIR, DETERMINISTIC_SUMMARY, BLOCK)


@dataclass
class Finding:
    """One dimension's outcome."""

    dimension: str
    outcome: str = UNCHECKED
    detail: str = ""

    @property
    def asks(self) -> str:
        return ASKS.get(self.dimension, "")

    @property
    def safety(self) -> bool:
        return self.dimension in SAFETY

    @property
    def blocks(self) -> bool:
        """Whether this finding alone stops the answer being shown.

        UNCHECKED blocks on a safety dimension for the same reason FAIL does:
        a grounding check nobody ran is not evidence that the answer is
        grounded.
        """
        return self.safety and self.outcome in (FAIL, UNCHECKED)

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "asks": self.asks,
                "outcome": self.outcome, "detail": self.detail,
                "safety": self.safety, "blocks": self.blocks,
                "because": SAFETY_BECAUSE.get(self.dimension, "")}


@dataclass
class Score:
    """§94's rubric over one answer."""

    findings: list[Finding] = field(default_factory=list)
    #: How many repair attempts have already been made. One is the limit:
    #: a second repair is a model arguing with a rubric.
    repairs_attempted: int = 0

    def get(self, dimension: str) -> Finding | None:
        return next((f for f in self.findings if f.dimension == dimension),
                    None)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocks]

    @property
    def quality_failures(self) -> list[Finding]:
        return [f for f in self.findings
                if not f.safety and f.outcome == FAIL]

    @property
    def applicable(self) -> list[Finding]:
        return [f for f in self.findings if f.outcome in (PASS, FAIL)]

    @property
    def passed(self) -> list[Finding]:
        return [f for f in self.findings if f.outcome == PASS]

    @property
    def rate(self) -> float:
        """Share of applicable dimensions passed.

        Reported and deliberately NOT used to decide anything. A high average
        with a blocking failure under it is exactly the shape §94 refuses, and
        the same shape the assurance rules refuse everywhere else.
        """
        applicable = self.applicable
        return len(self.passed) / len(applicable) if applicable else 0.0

    def verdict(self) -> str:
        if self.blocking:
            return BLOCK
        if self.quality_failures:
            return REPAIR if not self.repairs_attempted \
                else DETERMINISTIC_SUMMARY
        return SHOW

    def sentence(self) -> str:
        verdict = self.verdict()
        if verdict == SHOW:
            return (f"Presentable: {len(self.passed)} of "
                    f"{len(self.applicable)} applicable checks passed.")
        if verdict == BLOCK:
            return ("Not shown. "
                    + "; ".join(f.detail or f.asks for f in self.blocking))
        if verdict == REPAIR:
            return ("Sent back for one repair: "
                    + "; ".join(f.detail or f.asks
                                for f in self.quality_failures))
        return ("The written answer did not come back clean after a repair, "
                "so the findings are shown as computed rather than as prose: "
                + "; ".join(f.detail or f.asks
                            for f in self.quality_failures))

    def to_dict(self) -> dict[str, Any]:
        return {"version": RUBRIC_VERSION,
                "findings": [f.to_dict() for f in self.findings],
                "verdict": self.verdict(),
                "blocking": [f.dimension for f in self.blocking],
                "quality_failures": [f.dimension
                                     for f in self.quality_failures],
                "repairs_attempted": self.repairs_attempted,
                "pass_rate": round(self.rate, 4),
                "sentence": self.sentence()}


def score(outcomes: dict[str, str], *, details: dict[str, str] | None = None,
          repairs_attempted: int = 0) -> Score:
    """The rubric, from the outcome of each dimension.

    Dimensions not mentioned are UNCHECKED, never PASS. The permissive default
    would make a caller that forgot to run the grounding check produce a
    perfect score, which is the failure mode the whole rubric exists to catch.
    """
    details = details or {}
    result = Score(repairs_attempted=repairs_attempted)
    for dimension in DIMENSIONS:
        outcome = outcomes.get(dimension, UNCHECKED)
        if outcome not in OUTCOMES:
            raise ValueError(
                f"{outcome!r} is not a rubric outcome for {dimension}")
        result.findings.append(Finding(dimension=dimension, outcome=outcome,
                                       detail=details.get(dimension, "")))
    return result


def summarise(observations: list[Any], limitations: list[str] | None = None
              ) -> str:
    """The deterministic summary. §94's fallback when repair does not work.

    Built by rendering each observation's template. It cannot assert more than
    its slots, so it cannot introduce the defect the repair failed to fix —
    which is the entire reason the fallback is this and not another model
    call.
    """
    lines = [o.render() if hasattr(o, "render") else str(o)
             for o in observations]
    text = " ".join(line.rstrip(".") + "." for line in lines if line)
    if limitations:
        text += " Not established: " + "; ".join(limitations) + "."
    return text or ("Nothing could be established that may be stated as a "
                    "finding.")


__all__ = ["ACTIONABILITY", "ASKS", "BLOCK", "BREADTH_CONCENTRATION",
           "CONCISION", "CONTRADICTIONS", "DETERMINISTIC_SUMMARY",
           "DIMENSIONS", "DIRECTNESS", "DRIVER_QUALITY", "EXCEPTIONS",
           "FAIL", "Finding", "GROUNDING", "LIMITATIONS", "MATERIALITY",
           "NON_CAUSAL_LANGUAGE", "NOT_APPLICABLE", "NO_REPETITION",
           "NUMBER_FORMATTING", "OBJECTIVE_COMPLETENESS", "OUTCOMES", "PASS",
           "PERIOD_POPULATION_ACCURACY", "PERSISTENCE", "QUALITY", "REPAIR",
           "RUBRIC_VERSION", "SAFETY", "SAFETY_BECAUSE", "SHOW", "Score",
           "TRACE_CONSISTENCY", "UNCHECKED", "VERDICTS", "VISUAL_VALIDITY",
           "score", "summarise"]
