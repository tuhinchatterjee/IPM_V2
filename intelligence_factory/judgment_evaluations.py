"""
Analytical-judgment evaluations. §96.

    "Evaluate separately: INVESTIGATION / INTERPRETATION / CONTRADICTION /
     VISUALIZATION."

"Separately" is the whole instruction
--------------------------------------
One aggregate judgment score would be the most misleading number this system
could produce, because the four suites fail for unrelated reasons and each
one masks the others. A system that picks blueprints perfectly and invents
contradiction explanations would score well; so would one that never
contradicts itself and cannot choose a chart. The failure that matters is
always the one the average hid.

So there are four suites, thirty dimensions between them, and no combined
figure anywhere in this module. `report()` returns four blocks and a list of
critical failures, and the closest thing to an overall verdict is a boolean
that is False if any single critical dimension failed.

Every rate carries its interval
--------------------------------
The same discipline as `metrics.py`: a hundred cases with no errors is
consistent with a true error rate of 3%, so the lower bound is what a claim
is compared against. A judgment suite is exactly where a point estimate of
100% is most tempting and least meaningful, because the case counts are small
and the dimensions are many.

Nothing here calls a provider
------------------------------
Every dimension is scored from structures the deterministic engines produced —
a blueprint Selection, an interpretation Contract, a Diagnosis, a visual
Verdict. The evaluation runs offline, against fixtures, and a run of it costs
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intelligence_factory import metrics as me

EVALUATION_VERSION = "1.0.0"

# ------------------------------------------------------------ §96's suites
INVESTIGATION = "INVESTIGATION"
INTERPRETATION = "INTERPRETATION"
CONTRADICTION = "CONTRADICTION"
VISUALIZATION = "VISUALIZATION"

SUITES: tuple[str, ...] = (INVESTIGATION, INTERPRETATION, CONTRADICTION,
                           VISUALIZATION)

#: §96's dimensions, per suite, in the brief's order.
DIMENSIONS: dict[str, tuple[str, ...]] = {
    INVESTIGATION: ("blueprint_selection", "objective_coverage",
                    "hypothesis_coverage", "driver_identification",
                    "challenge_quality", "evidence_coverage",
                    "no_duplicate_work", "coherent_synthesis"),
    INTERPRETATION: ("directness", "materiality", "facts", "drivers",
                     "exceptions", "period_population_accuracy",
                     "non_causality", "limitations", "actionability",
                     "repetition"),
    CONTRADICTION: ("detection", "taxonomy", "diagnostics",
                    "explanation_grounding", "unresolved_honesty"),
    VISUALIZATION: ("chart_validity", "semantic_axes", "reconciliation",
                    "readability", "precision", "accessibility", "fallback"),
}

#: What each dimension asks. Written out because a suite whose dimensions
#: nobody can define gets scored against whatever the implementation happens
#: to check.
ASKS: dict[str, str] = {
    # investigation
    "blueprint_selection": "Was the blueprint a competent analyst would have "
                           "worked from selected?",
    "objective_coverage": "Was every mandatory objective run or explicitly "
                          "declined with a reason?",
    "hypothesis_coverage": "Were the candidate explanations enumerated before "
                           "one was tested?",
    "driver_identification": "Do the named drivers reconcile to the movement "
                             "they explain?",
    "challenge_quality": "Did the challenge pass find the flaw that was "
                         "there?",
    "evidence_coverage": "Does a validated fact exist for everything the "
                         "investigation asserts?",
    "no_duplicate_work": "Did the investigation avoid running the same "
                         "analysis twice?",
    "coherent_synthesis": "Do the conclusions follow from the tasks that "
                          "ran?",
    # interpretation
    "directness": "Does the first sentence answer the question?",
    "materiality": "Is size reported in terms that separate a large movement "
                   "from a large percentage?",
    "facts": "Does every figure trace to a validated fact?",
    "drivers": "Are the drivers the ones the decomposition found?",
    "exceptions": "Is what does not fit reported?",
    "period_population_accuracy": "Are the period and population the ones the "
                                  "figures were computed over?",
    "non_causality": "Are associations described as associations?",
    "limitations": "Is what could not be established stated?",
    "actionability": "Is the next step specific to this analysis?",
    "repetition": "Is each thing said once?",
    # contradiction
    "detection": "Were the disagreeing signals found at all?",
    "taxonomy": "Was the explanation drawn from §82's closed list?",
    "diagnostics": "Did the fifteen checks run and get recorded?",
    "explanation_grounding": "Is every explanation supported by a check that "
                             "actually fired?",
    "unresolved_honesty": "Was UNRESOLVED reported when nothing explained "
                          "it?",
    # visualization
    "chart_validity": "Was a chart the shape supports chosen?",
    "semantic_axes": "Does each axis carry a role it can take?",
    "reconciliation": "Do the plotted values equal the table's?",
    "readability": "Is the chart legible at the size it renders?",
    "precision": "Is display precision within the contract?",
    "accessibility": "Is there a table or summary beside the chart?",
    "fallback": "When no chart passed, did a table render?",
}

#: Dimensions where a single failure blocks release regardless of the rest.
#: Each one is a case where the output asserts something untrue rather than
#: something clumsy — the same line §94 draws between safety and quality.
CRITICAL: frozenset[str] = frozenset({
    "driver_identification", "evidence_coverage", "facts",
    "period_population_accuracy", "non_causality", "explanation_grounding",
    "unresolved_honesty", "semantic_axes", "reconciliation",
})

#: The lower bound a non-critical dimension must clear. Compared against the
#: LOWER bound, never the point estimate: a point estimate of 100% over
#: twenty cases supports a claim of about 84%.
TARGET_PCT = 85.0
#: Critical dimensions are held higher, and still by their lower bound.
CRITICAL_TARGET_PCT = 95.0


@dataclass
class Case:
    """One evaluated case: what was expected, what happened."""

    case_id: str
    suite: str
    #: Dimension -> whether it was met. A dimension absent from this mapping
    #: was NOT MEASURED and is counted as such rather than as a pass.
    outcomes: dict[str, bool] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "suite": self.suite,
                "outcomes": dict(self.outcomes), "note": self.note}


@dataclass
class SuiteResult:
    """One suite's dimensions, each with its interval."""

    suite: str
    rates: dict[str, me.Rate] = field(default_factory=dict)
    #: Dimensions no case exercised. Reported by name: a suite that silently
    #: omitted a dimension would report a perfect score for the seven it did
    #: run, and §96 asks for eight.
    unmeasured: list[str] = field(default_factory=list)
    cases: int = 0

    @property
    def underpowered(self) -> list[str]:
        """Dimensions with no observed errors that the sample cannot support.

        A clean run of sixty cases has a Wilson lower bound around 94%, so it
        does not support a 95% claim — which is correct and would otherwise
        read as a defect. Naming these separately turns a mysteriously red
        gate into an actionable one: the answer is more cases, not a fix.
        """
        return sorted(name for name, rate in self.rates.items()
                      if name in CRITICAL and rate.successes == rate.total
                      and rate.total and not rate.supports(
                          CRITICAL_TARGET_PCT))

    @property
    def critical_failures(self) -> list[str]:
        failed = [name for name, rate in self.rates.items()
                  if name in CRITICAL
                  and not rate.supports(CRITICAL_TARGET_PCT)]
        # An unmeasured critical dimension fails too. A grounding check nobody
        # ran is not evidence that the answers were grounded.
        return sorted([*failed, *[d for d in self.unmeasured
                                  if d in CRITICAL]])

    @property
    def below_target(self) -> list[str]:
        return sorted(name for name, rate in self.rates.items()
                      if name not in CRITICAL and not rate.supports(
                          TARGET_PCT))

    @property
    def clean(self) -> bool:
        return not self.critical_failures and not self.below_target \
            and not self.unmeasured

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite, "cases": self.cases,
            "dimensions": {name: rate.to_dict()
                           for name, rate in self.rates.items()},
            "unmeasured": list(self.unmeasured),
            "critical_failures": self.critical_failures,
            "underpowered": self.underpowered,
            "below_target": self.below_target,
            "clean": self.clean,
            "sentence": self.sentence(),
        }

    def sentence(self) -> str:
        if not self.cases:
            return f"{self.suite}: nothing was evaluated."
        if self.clean:
            return (f"{self.suite}: {len(self.rates)} dimensions over "
                    f"{self.cases} cases, all at or above target on the lower "
                    "bound.")
        parts = []
        underpowered = set(self.underpowered)
        real = [d for d in self.critical_failures if d not in underpowered]
        if real:
            parts.append("critical: " + ", ".join(real))
        if underpowered:
            parts.append(
                "clean but underpowered (more cases, not a fix): "
                + ", ".join(sorted(underpowered)))
        if self.below_target:
            parts.append("below target: " + ", ".join(self.below_target))
        if self.unmeasured:
            parts.append("not measured: " + ", ".join(self.unmeasured))
        return f"{self.suite} over {self.cases} cases — " + "; ".join(parts)


def evaluate(suite: str, cases: list[Case]) -> SuiteResult:
    """One suite, scored dimension by dimension with intervals.

    Only cases belonging to the suite are counted, and a dimension is measured
    only over the cases that recorded it. A case that did not exercise
    `challenge_quality` should not push that dimension's denominator up and
    its rate down; that would make a suite look worse the more unrelated cases
    it grew.
    """
    if suite not in SUITES:
        raise KeyError(f"{suite!r} is not one of §96's suites")
    mine = [c for c in cases if c.suite == suite]
    result = SuiteResult(suite=suite, cases=len(mine))

    for dimension in DIMENSIONS[suite]:
        measured = [c for c in mine if dimension in c.outcomes]
        if not measured:
            result.unmeasured.append(dimension)
            continue
        successes = sum(1 for c in measured if c.outcomes[dimension])
        result.rates[dimension] = me.rate(dimension, successes, len(measured))
    return result


def report(cases: list[Case]) -> dict[str, Any]:
    """§96's four suites, separately, and deliberately no combined score.

    One aggregate would be the most misleading number this system could
    produce: the four fail for unrelated reasons and each masks the others,
    and the failure that matters is always the one the average hid.
    """
    results = {suite: evaluate(suite, cases) for suite in SUITES}
    critical = sorted(
        f"{suite}.{dimension}"
        for suite, result in results.items()
        for dimension in result.critical_failures)
    #: Critical dimensions that failed with errors observed, as opposed to
    #: those a clean-but-small sample cannot support. Both block release; only
    #: the first is a defect, and telling them apart is what stops a team
    #: hunting a bug that is a sample size.
    observed = sorted(
        f"{suite}.{dimension}"
        for suite, result in results.items()
        for dimension in result.critical_failures
        if dimension not in result.underpowered)

    return {
        "version": EVALUATION_VERSION,
        "suites": {suite: result.to_dict()
                   for suite, result in results.items()},
        "critical_failures": critical,
        "critical_failures_with_errors": observed,
        "underpowered": sorted(
            f"{suite}.{dimension}"
            for suite, result in results.items()
            for dimension in result.underpowered),
        "cases_for_critical_target": me.cases_needed(CRITICAL_TARGET_PCT),
        # The nearest thing to an overall verdict, and deliberately a boolean
        # rather than a percentage. A number invites an average.
        "releasable": not critical and all(r.clean for r in results.values()),
        "target_pct": TARGET_PCT,
        "critical_target_pct": CRITICAL_TARGET_PCT,
        "no_combined_score": True,
        "sentence": "; ".join(r.sentence() for r in results.values()),
    }


__all__ = ["ASKS", "CONTRADICTION", "CRITICAL", "CRITICAL_TARGET_PCT",
           "Case", "DIMENSIONS", "EVALUATION_VERSION", "INTERPRETATION",
           "INVESTIGATION", "SUITES", "SuiteResult", "TARGET_PCT",
           "VISUALIZATION", "evaluate", "report"]
