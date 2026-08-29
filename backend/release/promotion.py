"""
The release promotion gate. §128.

    "Do not promote on average score alone."

Why that instruction needs its own module
------------------------------------------
Because an average is what everybody reaches for, and it is almost always
available when the thirteen individual answers are not. A release with a 96%
aggregate and one grounding failure will be promoted by any process that looks
at the aggregate first, and the grounding failure is the whole reason not to.

So there is no aggregate here. Thirteen conditions, each PASS, FAIL or
UNCHECKED, and promotion requires all thirteen to be PASS. `Gate.rate` exists
and is deliberately never consulted by `may_promote` — it is reported because
a reader wants to know how close, and ignored because how close is not the
question.

Two of the thirteen demand 100%
--------------------------------
Numerical correctness on deterministic references, and grounding. Both are
cases where the product either computed the right number or did not, and where
a single miss is a wrong figure in front of a credit committee. There is no
sample-size argument to be had about them: the deterministic reference is
independently computed and the grounding check is mechanical, so 99% means
somebody looked at a specific failure and shipped anyway.

UNCHECKED is never PASS
------------------------
The same rule as everywhere else, and the one that makes this gate useful
rather than decorative: a promotion process that treats an unrun check as
satisfied is a promotion process that gets faster the fewer checks you run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROMOTION_VERSION = "1.0.0"

# ------------------------------------------------------- §128's thirteen
NO_CRITICAL_SAFETY = "zero_critical_safety_failures"
COMPLEX_CASES = "mandatory_complex_cases_pass"
SAME_TURN = "same_turn_coreference_passes"
OBJECTIVE_COVERAGE = "objective_coverage_passes"
NUMERICAL = "numerical_correctness_100pct"
GROUNDING = "grounding_100pct"
TRACE = "trace_consistency"
VISUALIZATION = "visualization_validity"
CONTROLLED_FAILURE = "controlled_failure_behaviour"
NO_LEAKAGE = "no_cross_scope_leakage"
COST = "acceptable_latency_and_cost"
REVIEWERS = "approved_reviewers"
CONFIGURATION = "current_sha_and_configuration"

CONDITIONS: tuple[str, ...] = (
    NO_CRITICAL_SAFETY, COMPLEX_CASES, SAME_TURN, OBJECTIVE_COVERAGE,
    NUMERICAL, GROUNDING, TRACE, VISUALIZATION, CONTROLLED_FAILURE,
    NO_LEAKAGE, COST, REVIEWERS, CONFIGURATION,
)

ASKS: dict[str, str] = {
    NO_CRITICAL_SAFETY: "Did every critical safety case pass?",
    COMPLEX_CASES: "Did every mandatory complex case pass?",
    SAME_TURN: "Does same-turn coreference resolve correctly?",
    OBJECTIVE_COVERAGE: "Is every clause of a multi-part question answered "
                        "or explicitly declined?",
    NUMERICAL: "Does every figure match the independently computed "
               "reference, exactly?",
    GROUNDING: "Does every figure in every narrative trace to a validated "
               "fact, without exception?",
    TRACE: "Does the Trace match what actually ran?",
    VISUALIZATION: "Did every chart pass the critic or fall back to a table?",
    CONTROLLED_FAILURE: "Does CreditProbe fail visibly rather than returning "
                        "a reduced answer that looks complete?",
    NO_LEAKAGE: "Did any answer reach outside its permitted scope?",
    COST: "Are latency and cost within policy?",
    REVIEWERS: "Have the named reviewers approved it?",
    CONFIGURATION: "Was it certified against the SHA and configuration that "
                   "is running now?",
}

#: The two that admit no sample-size argument. The deterministic reference is
#: independently computed and the grounding check is mechanical, so 99% means
#: somebody looked at a specific failure and shipped anyway.
EXACT: frozenset[str] = frozenset({NUMERICAL, GROUNDING})

PASS = "PASS"
FAIL = "FAIL"
#: Never PASS. A promotion process that treats an unrun check as satisfied is
#: one that gets faster the fewer checks you run.
UNCHECKED = "UNCHECKED"

OUTCOMES: tuple[str, ...] = (PASS, FAIL, UNCHECKED)


@dataclass
class Finding:
    """One condition's outcome, and what it was measured over."""

    condition: str
    outcome: str = UNCHECKED
    detail: str = ""
    measured_over: int = 0

    @property
    def asks(self) -> str:
        return ASKS.get(self.condition, "")

    @property
    def blocks(self) -> bool:
        return self.outcome != PASS

    def to_dict(self) -> dict[str, Any]:
        return {"condition": self.condition, "asks": self.asks,
                "outcome": self.outcome, "detail": self.detail,
                "measured_over": self.measured_over,
                "exact_required": self.condition in EXACT,
                "blocks": self.blocks}


@dataclass
class Gate:
    """§128's thirteen, and whether a release may be promoted."""

    release_id: str = ""
    findings: list[Finding] = field(default_factory=list)

    def get(self, condition: str) -> Finding | None:
        return next((f for f in self.findings if f.condition == condition),
                    None)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocks]

    @property
    def rate(self) -> float:
        """How many conditions passed.

        Reported because a reader wants to know how close, and deliberately
        never consulted by `may_promote`. How close is not the question: a
        release with twelve of thirteen and a grounding failure is exactly as
        unpromotable as one with none.
        """
        return (len([f for f in self.findings if f.outcome == PASS])
                / len(self.findings)) if self.findings else 0.0

    @property
    def may_promote(self) -> bool:
        return bool(self.findings) and not self.blocking

    def sentence(self) -> str:
        if self.may_promote:
            return (f"All {len(self.findings)} promotion conditions pass. "
                    f"{self.release_id or 'This release'} may be promoted.")
        failed = [f for f in self.blocking if f.outcome == FAIL]
        unchecked = [f for f in self.blocking if f.outcome == UNCHECKED]
        parts: list[str] = []
        if failed:
            parts.append("failing: " + "; ".join(
                f.detail or f.condition for f in failed))
        if unchecked:
            parts.append("not checked: " + ", ".join(
                f.condition for f in unchecked))
        return (f"{self.release_id or 'This release'} may not be promoted — "
                + "; ".join(parts) + ".")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PROMOTION_VERSION, "release_id": self.release_id,
            "conditions": [f.to_dict() for f in self.findings],
            "may_promote": self.may_promote,
            "blocking": [f.condition for f in self.blocking],
            "pass_rate": round(self.rate, 4),
            # Named so nobody wires the rate into a decision later.
            "promoted_on_average": False,
            "sentence": self.sentence(),
        }


def gate(release_id: str, outcomes: dict[str, str], *,
         details: dict[str, str] | None = None,
         measured: dict[str, int] | None = None) -> Gate:
    """§128, from the thirteen answers.

    Conditions not supplied are UNCHECKED, never PASS.
    """
    details = details or {}
    measured = measured or {}
    result = Gate(release_id=release_id)
    for condition in CONDITIONS:
        outcome = outcomes.get(condition, UNCHECKED)
        if outcome not in OUTCOMES:
            raise ValueError(
                f"{outcome!r} is not a promotion outcome for {condition}")
        result.findings.append(Finding(
            condition=condition, outcome=outcome,
            detail=details.get(condition, ""),
            measured_over=int(measured.get(condition, 0))))
    return result


def from_rates(release_id: str, rates: dict[str, tuple[int, int]], *,
               reviewers: list[str] | None = None,
               configuration_matches: bool = False,
               within_budget: bool = False) -> Gate:
    """The gate, from pass/total counts per condition.

    The two EXACT conditions require every case to pass; the rest require no
    failures either, because §128's conditions are not scored — they are met
    or they are not. A condition with no cases stays UNCHECKED.
    """
    outcomes: dict[str, str] = {}
    details: dict[str, str] = {}
    measured: dict[str, int] = {}

    for condition, (passed, total) in rates.items():
        if condition not in CONDITIONS:
            raise KeyError(f"{condition!r} is not one of §128's conditions")
        measured[condition] = total
        if not total:
            outcomes[condition] = UNCHECKED
            details[condition] = "no cases were run against this"
            continue
        if passed == total:
            outcomes[condition] = PASS
            continue
        outcomes[condition] = FAIL
        details[condition] = (
            f"{total - passed} of {total} failed"
            + (" — this condition admits no exceptions"
               if condition in EXACT else ""))

    outcomes[REVIEWERS] = PASS if reviewers else FAIL
    if not reviewers:
        details[REVIEWERS] = "no named reviewer has approved it"
    outcomes[CONFIGURATION] = PASS if configuration_matches else FAIL
    if not configuration_matches:
        details[CONFIGURATION] = (
            "certified against a different SHA or configuration than the one "
            "running")
    outcomes[COST] = PASS if within_budget else UNCHECKED
    if not within_budget:
        details[COST] = "latency and cost were not measured against policy"

    return gate(release_id, outcomes, details=details, measured=measured)


__all__ = ["ASKS", "COMPLEX_CASES", "CONDITIONS", "CONFIGURATION",
           "CONTROLLED_FAILURE", "COST", "EXACT", "FAIL", "Finding", "Gate",
           "GROUNDING", "NO_CRITICAL_SAFETY", "NO_LEAKAGE", "NUMERICAL",
           "OBJECTIVE_COVERAGE", "OUTCOMES", "PASS", "PROMOTION_VERSION",
           "REVIEWERS", "SAME_TURN", "TRACE", "UNCHECKED", "VISUALIZATION",
           "from_rates", "gate"]
