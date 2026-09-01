"""
Sixteen things that have to be right, scored separately. P0.7.

    "A good intent score must not hide a bad analytical plan."

That is the whole design constraint, and it is a statement about ARITHMETIC.
One number over a corpus is dominated by whatever is easiest: reading a question
as an analysis is nearly free, and a corpus of a thousand cases where the
capability is right 99% of the time and the plan is right 70% of the time
reports something in the eighties and hides the half that matters. Averaging the
two makes the weak layer invisible by construction.

So each layer is scored on its own denominator, and the report is the WEAKEST
layer rather than the mean. A product is as good as the worst thing between the
question and the answer, because that is the step a user's wrong answer came
out of.

The sixteen
-----------
    1  capability            what kind of request this is
    2  same-turn referent    what "them" refers to in this message
    3  objective             every clause the request contains
    4  concept               which governed measure each phrase means
    5  dataset               which governed source it comes from
    6  relationship          which join reaches it
    7  period and grain      when, and at what level of aggregation
    8  plan                  the analytical shape
    9  query                 the compiled, parameterised query
   10  result                the rows themselves
   11  invariants            the checks that must hold of them
   12  interpretation        what the prose says about them
   13  visualization         whether the picture is true
   14  Trace consistency     whether the record matches what ran
   15  error handling        whether a failure was named
   16  officer selection     which agent and model answered

Not applicable is not a pass
----------------------------
A layer that did not apply to a case is excluded from that layer's denominator,
never counted as a success. A corpus of metadata questions would otherwise score
100% on `query` by never compiling one — the arithmetic version of "SKIPPED is
not PASS".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CAPABILITY = "capability"
REFERENT = "same_turn_referent"
OBJECTIVE = "objective_decomposition"
CONCEPT = "concept_resolution"
DATASET = "dataset_selection"
RELATIONSHIP = "relationship_selection"
PERIOD = "period_and_grain"
PLAN = "plan"
QUERY = "compiled_query"
RESULT = "result"
INVARIANTS = "invariants"
INTERPRETATION = "interpretation"
VISUALIZATION = "visualization"
TRACE = "trace_consistency"
ERRORS = "error_handling"
OFFICER = "officer_selection"

LAYERS: tuple[str, ...] = (
    CAPABILITY, REFERENT, OBJECTIVE, CONCEPT, DATASET, RELATIONSHIP, PERIOD,
    PLAN, QUERY, RESULT, INVARIANTS, INTERPRETATION, VISUALIZATION, TRACE,
    ERRORS, OFFICER,
)

TITLES: dict[str, str] = {
    CAPABILITY: "Capability and intent",
    REFERENT: "Same-turn referent resolution",
    OBJECTIVE: "Objective decomposition",
    CONCEPT: "Concept resolution",
    DATASET: "Dataset selection",
    RELATIONSHIP: "Relationship selection",
    PERIOD: "Period and grain",
    PLAN: "Analytical plan",
    QUERY: "Compiled query",
    RESULT: "Result",
    INVARIANTS: "Invariants",
    INTERPRETATION: "Interpretation",
    VISUALIZATION: "Visualization",
    TRACE: "Trace consistency",
    ERRORS: "Error handling",
    OFFICER: "Officer and model selection",
}

#: What each layer is for, in the words a reader of the report needs. Shipped
#: with the numbers because a layer name with a percentage beside it and no
#: explanation is a number nobody can act on.
MEANINGS: dict[str, str] = {
    CAPABILITY: "Whether the request was read as the right kind of thing at "
                "all — an analysis, a metadata question, a presentation "
                "change, a refusal.",
    REFERENT: "Whether a pronoun or head noun whose antecedent is in the SAME "
              "message resolved to that antecedent rather than to the book.",
    OBJECTIVE: "Whether every clause of a multi-part request was settled. An "
               "answer to three of four clauses is not 75% right; it is a "
               "confident answer to a question nobody asked.",
    CONCEPT: "Whether each phrase resolved to the governed measure a credit "
             "officer meant, and asked where it is genuinely ambiguous.",
    DATASET: "Whether the figures came from the governed source that owns "
             "them.",
    RELATIONSHIP: "Whether the join used was a governed relationship rather "
                  "than a guess.",
    PERIOD: "Whether the answer covers the period and grain asked for.",
    PLAN: "Whether the analytical shape matches the question — a ranking "
          "where a ranking was asked for, not a distribution that contains "
          "the same rows.",
    QUERY: "Whether the compiled query is parameterised, validated and "
           "reproducible.",
    RESULT: "Whether rows came back, and whether the shape is the one the plan "
            "promised.",
    INVARIANTS: "Whether the arithmetic that must hold of the result was "
                "checked, and held.",
    INTERPRETATION: "Whether the prose is grounded in the result, complete "
                    "against its eight sections, and free of causal claims "
                    "the figures do not support.",
    VISUALIZATION: "Whether the chart says something true about the result, "
                   "or was replaced by one that does.",
    TRACE: "Whether the Trace records what actually ran — no stage claiming "
           "validation that did not happen.",
    ERRORS: "Whether a failure was categorised, safe to show, and carried a "
            "correlation id.",
    OFFICER: "Whether the officer level and model role match the complexity "
             "and risk of the request.",
}

PASS = "PASS"
FAIL = "FAIL"
NOT_APPLICABLE = "NOT_APPLICABLE"

#: A layer with fewer observations than this cannot support a claim, and the
#: report says so instead of printing a percentage. Three cases at 100% is
#: "three cases", which is the sentence P0.7 exists to prevent.
MIN_OBSERVATIONS = 30


@dataclass
class Observation:
    """One case's verdict on one layer."""

    case_id: str
    layer: str
    status: str = NOT_APPLICABLE
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "layer": self.layer,
                "status": self.status, "detail": self.detail}


@dataclass
class LayerScore:
    """One layer, over the whole corpus."""

    layer: str
    title: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    #: Up to a handful of failing cases, so the number leads somewhere.
    examples: list[str] = field(default_factory=list)

    @property
    def observed(self) -> int:
        """The denominator. A layer that did not apply is NOT counted — a
        corpus of metadata questions would otherwise score 100% on the query
        layer by never compiling one."""
        return self.passed + self.failed

    @property
    def rate(self) -> float | None:
        """The pass rate, or None where too little was observed to say."""
        if self.observed < MIN_OBSERVATIONS:
            return None
        return self.passed / self.observed * 100.0

    @property
    def claimable(self) -> bool:
        return self.observed >= MIN_OBSERVATIONS

    def sentence(self) -> str:
        if not self.observed:
            return (f"{self.title}: not exercised by this corpus "
                    f"({self.skipped} cases did not reach it).")
        if not self.claimable:
            return (f"{self.title}: {self.passed} of {self.observed} — too few "
                    f"observations to state a rate (needs {MIN_OBSERVATIONS}).")
        return (f"{self.title}: {self.rate:.1f}% "
                f"({self.passed} of {self.observed})")

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "title": self.title,
                "meaning": MEANINGS.get(self.layer, ""),
                "passed": self.passed, "failed": self.failed,
                "not_applicable": self.skipped, "observed": self.observed,
                "rate": None if self.rate is None else round(self.rate, 2),
                "claimable": self.claimable,
                "examples": list(self.examples[:5]),
                "sentence": self.sentence()}


@dataclass
class Report:
    """Every layer, and the honest headline."""

    scores: list[LayerScore] = field(default_factory=list)
    cases: int = 0

    def score(self, layer: str) -> LayerScore | None:
        return next((s for s in self.scores if s.layer == layer), None)

    @property
    def measured(self) -> list[LayerScore]:
        return [s for s in self.scores if s.claimable]

    @property
    def unmeasured(self) -> list[LayerScore]:
        """Layers the corpus could not say anything about. Reported, because a
        layer nobody measured is not a layer that passed."""
        return [s for s in self.scores if not s.claimable]

    @property
    def weakest(self) -> LayerScore | None:
        """The layer the product is actually as good as."""
        measured = self.measured
        if not measured:
            return None
        return min(measured, key=lambda s: s.rate or 0.0)

    @property
    def headline(self) -> float | None:
        """The weakest measured layer's rate — NOT the mean.

        A mean over sixteen layers is dominated by the cheap ones, and hides
        exactly the layer a user's wrong answer came out of. The product is as
        good as the worst step between the question and the answer.
        """
        weakest = self.weakest
        return None if weakest is None else weakest.rate

    def sentence(self) -> str:
        if not self.scores:
            return "No layer was evaluated."
        weakest = self.weakest
        if weakest is None:
            return (f"{self.cases} cases evaluated, and no layer reached "
                    f"{MIN_OBSERVATIONS} observations. No accuracy claim can "
                    "be made from this run.")
        unmeasured = len(self.unmeasured)
        tail = (f" {unmeasured} of {len(self.scores)} layers were not "
                f"measured and are NOT counted as passing."
                if unmeasured else "")
        return (f"Weakest layer: {weakest.title} at {weakest.rate:.1f}% over "
                f"{weakest.observed} observations. Reported as the headline "
                f"because a mean would hide it.{tail}")

    def to_dict(self) -> dict[str, Any]:
        return {"cases": self.cases,
                "headline": None if self.headline is None
                else round(self.headline, 2),
                "headline_rule": ("the WEAKEST measured layer, never the mean "
                                  "— a good intent score must not hide a bad "
                                  "analytical plan"),
                "weakest_layer": self.weakest.layer if self.weakest else None,
                "measured_layers": len(self.measured),
                "unmeasured_layers": [s.layer for s in self.unmeasured],
                "minimum_observations": MIN_OBSERVATIONS,
                "sentence": self.sentence(),
                "layers": [s.to_dict() for s in self.scores]}


# ---------------------------------------------------------------------------
# Reading a case result into layer observations
# ---------------------------------------------------------------------------

#: Which expectation on a curriculum turn belongs to which layer. The
#: evaluator's checks are named after what they verify; this is the map from
#: those names to the layer they are evidence about.
CHECK_LAYERS: dict[str, str] = {
    "capability": CAPABILITY,
    "action": CAPABILITY,
    "outcome": CAPABILITY,
    "referent": REFERENT,
    "objectives": OBJECTIVE,
    "concept": CONCEPT,
    "concepts": CONCEPT,
    "dataset": DATASET,
    "datasets": DATASET,
    "relationship": RELATIONSHIP,
    "period": PERIOD,
    "grain": PERIOD,
    "plan": PLAN,
    "query": QUERY,
    "rows": RESULT,
    "result": RESULT,
    "invariant": INVARIANTS,
    "invariants": INVARIANTS,
    "interpretation": INTERPRETATION,
    "grounding": INTERPRETATION,
    "visual": VISUALIZATION,
    "chart": VISUALIZATION,
    "trace": TRACE,
    "error": ERRORS,
    "officer": OFFICER,
    "model": OFFICER,
}

#: A forbidden behaviour is evidence about a layer too, and usually about a
#: different one from the check that shares its case.
FORBIDDEN_LAYERS: dict[str, str] = {
    "whole_portfolio": REFERENT,
    "partial_objectives": OBJECTIVE,
    "single_cohort": PLAN,
    "single_condition": PLAN,
    "single_measure": PLAN,
    "movement_by_dimension": PLAN,
    "causal_claim": INTERPRETATION,
    "population_drift": PERIOD,
    "measure_as_axis": VISUALIZATION,
    "categorical_axis": VISUALIZATION,
    "overplotting": VISUALIZATION,
    "mixed_units": VISUALIZATION,
    "table_only": VISUALIZATION,
    "validated_without_checks": TRACE,
    "trace_disagrees": TRACE,
    "uncategorised_failure": ERRORS,
    "stack_trace": ERRORS,
    "substituted_measure": CAPABILITY,
    "ANALYSIS": CAPABILITY,
    "CLARIFY": CAPABILITY,
    "UNSUPPORTED": CAPABILITY,
}


def observe(result: Any) -> list[Observation]:
    """Every layer this case said something about.

    Reads the evaluator's own per-check verdicts rather than re-running
    anything: a second opinion about whether a case passed can disagree with
    the first, and then nobody knows which number is the score.
    """
    case_id = str(getattr(result, "case_id", ""))
    out: list[Observation] = []
    if getattr(result, "error", ""):
        # A case that could not run is evidence about error handling and about
        # nothing else. Counting it as a failure of every layer would make one
        # crash look like sixteen defects.
        return [Observation(case_id, ERRORS, FAIL,
                            str(result.error)[:200])]

    for turn in getattr(result, "turns", []) or []:
        for name, held in (getattr(turn, "checks", {}) or {}).items():
            layer = _layer_for(name)
            if layer is None:
                continue
            out.append(Observation(
                case_id, layer, PASS if held else FAIL,
                "" if held else f"{name} did not hold"))
    return out


def _layer_for(check: str) -> str | None:
    """Which layer a named check is evidence about.

    Matched on the check's leading token so `forbidden:causal_claim` and
    `invariants:share_bounds` both land, without the evaluator having to know
    this map exists.
    """
    name = str(check or "").strip().lower()
    if not name:
        return None
    if name.startswith("forbidden"):
        tail = name.split(":", 1)[-1].strip()
        return FORBIDDEN_LAYERS.get(tail, CAPABILITY)
    head = name.split(":", 1)[0].strip()
    return CHECK_LAYERS.get(head) or CHECK_LAYERS.get(name)


def score(results: list[Any]) -> Report:
    """The sixteen layers, over a whole run."""
    scores = {layer: LayerScore(layer=layer, title=TITLES[layer])
              for layer in LAYERS}
    for result in results or []:
        seen: set[str] = set()
        for observation in observe(result):
            found = scores[observation.layer]
            if observation.status == FAIL:
                found.failed += 1
                if len(found.examples) < 5:
                    found.examples.append(
                        f"{observation.case_id}: {observation.detail}")
            elif observation.status == PASS:
                found.passed += 1
            seen.add(observation.layer)
        for layer in LAYERS:
            if layer not in seen:
                scores[layer].skipped += 1

    return Report(scores=[scores[layer] for layer in LAYERS],
                  cases=len(results or []))


__all__ = [
    "CAPABILITY",
    "CHECK_LAYERS",
    "CONCEPT",
    "DATASET",
    "ERRORS",
    "FAIL",
    "FORBIDDEN_LAYERS",
    "INTERPRETATION",
    "INVARIANTS",
    "LAYERS",
    "MEANINGS",
    "MIN_OBSERVATIONS",
    "NOT_APPLICABLE",
    "OBJECTIVE",
    "OFFICER",
    "PASS",
    "PERIOD",
    "PLAN",
    "QUERY",
    "REFERENT",
    "RELATIONSHIP",
    "RESULT",
    "TITLES",
    "TRACE",
    "VISUALIZATION",
    "LayerScore",
    "Observation",
    "Report",
    "observe",
    "score",
]
