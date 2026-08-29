"""Independent reference validation. §7.

§7's instruction is one sentence: "Do not use one LLM to declare another LLM
correct when deterministic validation is possible." Almost everything a case
asserts is deterministically checkable - which capability was chosen, which
officer signed, which datasets were read, which join was traversed, which
period, which grain, whether the invariants held, whether it clarified when
it should have. None of that needs an opinion, and asking for one would
replace a fact with a guess that agrees with itself.

So this module compares an OBSERVATION - what a run actually did - against a
case's expectations, dimension by dimension, in ordinary code.

The honesty rule it is built around: NOT_MEASURED is not a pass. A dimension
the observation carries nothing about is reported as unmeasured and excluded
from the score, never quietly counted as agreement. A validator that scored
90% because it only looked at nine of seventeen dimensions would be worse
than no validator, because it would be believed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.brain.cases import Case

REFERENCE_VERSION = "1.0.0"

# ------------------------------------------------------------------ verdicts

PASSED = "PASSED"
FAILED = "FAILED"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_MEASURED = "NOT_MEASURED"

VERDICTS: tuple[str, ...] = (PASSED, FAILED, NOT_APPLICABLE, NOT_MEASURED)

VERDICT_MEANS: dict[str, str] = {
    PASSED: "The observation agreed with the case.",
    FAILED: "The observation disagreed with the case.",
    NOT_APPLICABLE: "The case asserts nothing about this dimension.",
    NOT_MEASURED: "The case asserts something the observation does not "
                  "carry. Not a pass.",
}

# ---------------------------------------------------------------- dimensions
#
# §7's list, in §7's order. Named as data so a report cannot silently drop
# one and still call itself complete.

CAPABILITY = "capability"
OFFICER = "officer"
AGENT_SET = "agent_set"
TOOL_SET = "tool_set"
DATASET_SET = "dataset_set"
RELATIONSHIP_PATH = "relationship_path"
PERIOD = "period"
GRAIN = "grain"
FILTERS = "filters"
OPERATION_GRAPH = "operation_graph"
RESULT_SCHEMA = "result_schema"
RESULT_IDS = "result_ids"
VALUES = "values"
INVARIANTS = "invariants"
CLARIFICATION = "clarification_abstention"
PERMISSION = "permission_approval"
ISOLATION = "project_global_isolation"

DIMENSIONS: tuple[str, ...] = (
    CAPABILITY, OFFICER, AGENT_SET, TOOL_SET, DATASET_SET, RELATIONSHIP_PATH,
    PERIOD, GRAIN, FILTERS, OPERATION_GRAPH, RESULT_SCHEMA, RESULT_IDS,
    VALUES, INVARIANTS, CLARIFICATION, PERMISSION, ISOLATION,
)


@dataclass
class Observation:
    """What a run actually did.

    Every field defaults to a sentinel that means "not observed" rather than
    to an empty value that would read as "observed to be empty". The
    distinction is the whole point: an empty agent set is a claim, and no
    agent set recorded is not.
    """

    capability: str | None = None
    officer_level: int | None = None
    agents: tuple[str, ...] | None = None
    tools: tuple[str, ...] | None = None
    datasets: tuple[str, ...] | None = None
    relationships: tuple[str, ...] | None = None
    period_rule: str | None = None
    periods: tuple[str, ...] | None = None
    grain: str | None = None
    filters: dict[str, Any] | None = None
    operations: tuple[str, ...] | None = None
    result_columns: tuple[str, ...] | None = None
    result_ids: tuple[str, ...] | None = None
    values: dict[str, float] | None = None
    invariants_held: tuple[str, ...] | None = None
    invariants_failed: tuple[str, ...] | None = None
    clarified: bool | None = None
    abstained: bool | None = None
    figure_present: bool | None = None
    permission_granted: bool | None = None
    approval_requested: bool | None = None
    state_changed: bool | None = None
    project_id: int | None = None
    visible_globally: bool | None = None
    #: Text of the answer, for the forbidden-behaviour scan.
    answer_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items()}


@dataclass
class Check:
    """One dimension's verdict and the reason for it."""

    dimension: str
    verdict: str
    expected: Any = None
    observed: Any = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "verdict": self.verdict,
                "expected": _plain(self.expected),
                "observed": _plain(self.observed), "detail": self.detail}


def _plain(value: Any) -> Any:
    if isinstance(value, (tuple, set, frozenset)):
        return sorted(str(v) for v in value)
    return value


@dataclass
class Report:
    """Every dimension's verdict, and what may be concluded from them."""

    case_id: str
    checks: list[Check] = field(default_factory=list)
    kind: str = "independent_reference"
    reference_version: str = REFERENCE_VERSION

    def _of(self, verdict: str) -> list[Check]:
        return [c for c in self.checks if c.verdict == verdict]

    @property
    def failed(self) -> list[Check]:
        return self._of(FAILED)

    @property
    def passed_dimensions(self) -> tuple[str, ...]:
        return tuple(c.dimension for c in self._of(PASSED))

    @property
    def unmeasured_dimensions(self) -> tuple[str, ...]:
        return tuple(c.dimension for c in self._of(NOT_MEASURED))

    @property
    def independent(self) -> bool:
        """Whether every verdict here was reached by computation.

        Always true for this module - there is no code path that asks a model
        anything. It is a property rather than a constant so a caller that
        later mixes in a judged dimension cannot pass the result off as
        independent by accident.
        """
        return all(c.dimension in DIMENSIONS for c in self.checks)

    @property
    def settled(self) -> bool:
        """Whether anything was actually established."""
        return bool(self.passed_dimensions) and not self.failed

    @property
    def coverage(self) -> float:
        """Share of the dimensions the case asserts that were measured.

        Reported separately from the score, because a perfect score over two
        of seventeen dimensions is not a validation and a single number
        would let it look like one.
        """
        asserted = [c for c in self.checks if c.verdict != NOT_APPLICABLE]
        if not asserted:
            return 0.0
        measured = [c for c in asserted if c.verdict != NOT_MEASURED]
        return len(measured) / len(asserted)

    @property
    def summary(self) -> str:
        return (f"{len(self.passed_dimensions)} passed, "
                f"{len(self.failed)} failed, "
                f"{len(self.unmeasured_dimensions)} not measured, "
                f"coverage {self.coverage:.0%}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "kind": self.kind,
            "reference_version": self.reference_version,
            "checks": [c.to_dict() for c in self.checks],
            "passed": list(self.passed_dimensions),
            "failed": [c.dimension for c in self.failed],
            "not_measured": list(self.unmeasured_dimensions),
            "coverage": round(self.coverage, 4),
            "settled": self.settled, "independent": self.independent,
            "summary": self.summary,
        }


# --------------------------------------------------------------- primitives


def _compare(dimension: str, expected: Any, observed: Any,
             detail: str = "") -> Check:
    """The shape every dimension check shares.

    `expected` falsy means the case asserts nothing here. `observed` None
    means the run recorded nothing - which is NOT_MEASURED, never a pass.
    """
    if not expected:
        return Check(dimension, NOT_APPLICABLE, expected, observed)
    if observed is None:
        return Check(dimension, NOT_MEASURED, expected, observed,
                     "the observation carries nothing about this")
    if isinstance(expected, (tuple, list, set, frozenset)):
        want, got = set(expected), set(observed)
        if want == got:
            return Check(dimension, PASSED, expected, observed)
        missing = sorted(want - got)
        extra = sorted(got - want)
        parts = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        return Check(dimension, FAILED, expected, observed, "; ".join(parts))
    if expected == observed:
        return Check(dimension, PASSED, expected, observed)
    return Check(dimension, FAILED, expected, observed, detail)


def _subset(dimension: str, expected: Any, observed: Any,
            detail: str = "") -> Check:
    """For a dimension where the case names a MINIMUM, not an exact set.

    An answer that reads an extra governed dataset it did not need is
    wasteful, not wrong; one that failed to read a dataset the case names
    cannot have answered the question.
    """
    if not expected:
        return Check(dimension, NOT_APPLICABLE, expected, observed)
    if observed is None:
        return Check(dimension, NOT_MEASURED, expected, observed,
                     "the observation carries nothing about this")
    missing = sorted(set(expected) - set(observed))
    if missing:
        return Check(dimension, FAILED, expected, observed,
                     f"missing {', '.join(missing)}")
    return Check(dimension, PASSED, expected, observed, detail)


# ------------------------------------------------------------ the dimensions


def _capability(case: Case, obs: Observation) -> Check:
    return _compare(CAPABILITY, case.expected_capability, obs.capability)


def _officer(case: Case, obs: Observation) -> Check:
    if case.expected_officer_level is None:
        return Check(OFFICER, NOT_APPLICABLE)
    if obs.officer_level is None:
        return Check(OFFICER, NOT_MEASURED, case.expected_officer_level,
                     None, "no officer level recorded")
    if obs.officer_level == case.expected_officer_level:
        return Check(OFFICER, PASSED, case.expected_officer_level,
                     obs.officer_level)
    direction = ("below" if obs.officer_level < case.expected_officer_level
                 else "above")
    return Check(OFFICER, FAILED, case.expected_officer_level,
                 obs.officer_level,
                 f"signed {direction} the level this scope requires")


def _agents(case: Case, obs: Observation) -> Check:
    return _subset(AGENT_SET, case.expected_agents, obs.agents)


def _tools(case: Case, obs: Observation) -> Check:
    return _subset(TOOL_SET, case.expected_tools, obs.tools)


def _datasets(case: Case, obs: Observation) -> Check:
    return _subset(DATASET_SET, case.expected_datasets, obs.datasets)


def _relationships(case: Case, obs: Observation) -> Check:
    return _subset(RELATIONSHIP_PATH, case.expected_relationships,
                   obs.relationships)


def _period(case: Case, obs: Observation) -> Check:
    if not case.expected_period_rule:
        return Check(PERIOD, NOT_APPLICABLE)
    if obs.period_rule is None:
        # A run that produced periods but recorded no rule has still shown
        # something: that it chose without saying why. That is a real defect
        # under §5, and reporting it as unmeasured would hide it.
        if obs.periods:
            return Check(PERIOD, FAILED, case.expected_period_rule,
                         list(obs.periods),
                         "periods were used but no period rule was recorded, "
                         "so the answer cannot say which window it chose or "
                         "why")
        return Check(PERIOD, NOT_MEASURED, case.expected_period_rule, None)
    if obs.period_rule == case.expected_period_rule:
        return Check(PERIOD, PASSED, case.expected_period_rule,
                     obs.period_rule)
    return Check(PERIOD, FAILED, case.expected_period_rule, obs.period_rule)


def _grain(case: Case, obs: Observation) -> Check:
    return _compare(GRAIN, case.expected_grain, obs.grain,
                    "the output grain is not the one the question implies")


def _filters(case: Case, obs: Observation) -> Check:
    if not case.expected_filters:
        return Check(FILTERS, NOT_APPLICABLE)
    if obs.filters is None:
        return Check(FILTERS, NOT_MEASURED, case.expected_filters, None)
    wrong = {k: (v, obs.filters.get(k))
             for k, v in case.expected_filters.items()
             if obs.filters.get(k) != v}
    if wrong:
        return Check(FILTERS, FAILED, case.expected_filters, obs.filters,
                     "; ".join(f"{k}: expected {w}, got {g}"
                               for k, (w, g) in sorted(wrong.items())))
    return Check(FILTERS, PASSED, case.expected_filters, obs.filters)


def _operations(case: Case, obs: Observation) -> Check:
    return _subset(OPERATION_GRAPH, case.expected_operations, obs.operations)


def _result_schema(case: Case, obs: Observation) -> Check:
    """Whether the result's columns can carry the shape the case expects."""
    if not case.expected_result_shape:
        return Check(RESULT_SCHEMA, NOT_APPLICABLE)
    if obs.result_columns is None:
        return Check(RESULT_SCHEMA, NOT_MEASURED, case.expected_result_shape,
                     None)
    columns = list(obs.result_columns)
    shape = case.expected_result_shape
    needs_grouping = shape in ("grouped total", "grouped average",
                               "grouped rate", "ranked list",
                               "share of total", "concentration",
                               "distribution")
    if needs_grouping and case.expected_grain and \
            case.expected_grain not in columns:
        return Check(RESULT_SCHEMA, FAILED, case.expected_grain, columns,
                     f"a {shape} has no column for {case.expected_grain}, so "
                     "the rows cannot be attributed to anything")
    if shape == "single figure" and len(columns) > 3:
        return Check(RESULT_SCHEMA, FAILED, shape, columns,
                     "a single figure came back as a table")
    return Check(RESULT_SCHEMA, PASSED, shape, columns)


def _result_ids(case: Case, obs: Observation) -> Check:
    """Whether the rows are identified by governed keys.

    A result that names borrowers in prose but carries no identifier cannot
    be traced back, and a reader cannot tell an invented name from a real
    one - which is the fabricated-borrower failure class.
    """
    if case.expected_result_shape in ("", "metadata", "refusal",
                                      "clarifying question", "abstention"):
        return Check(RESULT_IDS, NOT_APPLICABLE)
    if obs.result_ids is None:
        return Check(RESULT_IDS, NOT_MEASURED, "governed identifiers", None)
    if not obs.result_ids:
        return Check(RESULT_IDS, FAILED, "governed identifiers", [],
                     "the result carries no identifier, so nothing in it can "
                     "be traced back to a governed row")
    return Check(RESULT_IDS, PASSED, "governed identifiers",
                 list(obs.result_ids))


def _values(case: Case, obs: Observation,
            computed: dict[str, float] | None) -> Check:
    """The figures, against an independently computed reference.

    `computed` comes from running the case's reference spec - a separate
    deterministic path, not the path that produced the answer. Without it
    this is NOT_MEASURED, because comparing a number to itself establishes
    nothing.
    """
    if not case.reference.independent:
        return Check(VALUES, NOT_APPLICABLE)
    if computed is None or obs.values is None:
        return Check(VALUES, NOT_MEASURED, case.reference.kind, None,
                     "no independently computed reference was supplied, so "
                     "the figures have not been checked against anything")
    tolerance = case.reference.tolerance
    wrong: list[str] = []
    for key, want in computed.items():
        got = obs.values.get(key)
        if got is None:
            wrong.append(f"{key} missing from the result")
            continue
        scale = max(abs(want), 1e-9)
        if abs(got - want) / scale > tolerance:
            wrong.append(f"{key} differs by more than the tolerance")
    if wrong:
        return Check(VALUES, FAILED, case.reference.kind, obs.values,
                     "; ".join(wrong))
    return Check(VALUES, PASSED, case.reference.kind, obs.values,
                 f"within {tolerance:.3%}")


def _invariants(case: Case, obs: Observation) -> Check:
    if not case.required_invariants:
        return Check(INVARIANTS, NOT_APPLICABLE)
    if obs.invariants_held is None and obs.invariants_failed is None:
        return Check(INVARIANTS, NOT_MEASURED, case.required_invariants, None)
    failed = list(obs.invariants_failed or ())
    if failed:
        return Check(INVARIANTS, FAILED, case.required_invariants, failed,
                     "an invariant did not hold and the answer was still "
                     "shown")
    held = set(obs.invariants_held or ())
    missing = [i for i in case.required_invariants if i not in held]
    if missing:
        return Check(INVARIANTS, FAILED, case.required_invariants,
                     sorted(held),
                     f"{len(missing)} required invariant(s) were never "
                     "checked, which is not the same as holding")
    return Check(INVARIANTS, PASSED, case.required_invariants, sorted(held))


def _clarification(case: Case, obs: Observation) -> Check:
    wants_clarify = case.expected_clarification
    wants_abstain = case.expected_abstention
    if not (wants_clarify or wants_abstain):
        # The case expects an answer. Clarifying instead is a failure, and a
        # silent one: the user reads it as diligence.
        if obs.clarified is None and obs.abstained is None:
            return Check(CLARIFICATION, NOT_APPLICABLE)
        if obs.clarified or obs.abstained:
            return Check(CLARIFICATION, FAILED, "an answer",
                         "clarified" if obs.clarified else "abstained",
                         "stopped on a question it had everything to answer")
        return Check(CLARIFICATION, PASSED, "an answer", "answered")
    if obs.clarified is None and obs.abstained is None:
        return Check(CLARIFICATION, NOT_MEASURED,
                     "clarify" if wants_clarify else "abstain", None)
    if wants_clarify and not obs.clarified:
        return Check(CLARIFICATION, FAILED, "clarify",
                     "abstained" if obs.abstained else "answered",
                     "answered a question that needed one more word from the "
                     "user")
    if wants_abstain and not obs.abstained:
        return Check(CLARIFICATION, FAILED, "abstain",
                     "clarified" if obs.clarified else "answered",
                     "there is no reading of this question that it could "
                     "answer, so offering a menu invites the user to accept "
                     "an answer to a different question")
    if obs.figure_present:
        return Check(CLARIFICATION, FAILED,
                     "no figure alongside a clarification or abstention",
                     "figure present",
                     "a figure beside a refusal reads as the answer")
    return Check(CLARIFICATION, PASSED,
                 "clarify" if wants_clarify else "abstain", "as expected")


def _permission(case: Case, obs: Observation) -> Check:
    needs_confirm = bool(
        case.expected_plan_properties.get("requires_confirmation"))
    denied = bool(case.expected_plan_properties.get("permission_denied"))
    mutates = bool(case.expected_plan_properties.get("changes_state"))
    if not (needs_confirm or denied or mutates):
        return Check(PERMISSION, NOT_APPLICABLE)
    if obs.state_changed is None:
        return Check(PERMISSION, NOT_MEASURED, "an approval gate", None)
    if denied and obs.state_changed:
        return Check(PERMISSION, FAILED, "no change", "changed",
                     "acted where the actor's role does not reach")
    if needs_confirm:
        if obs.approval_requested is None:
            return Check(PERMISSION, NOT_MEASURED, "confirmation", None)
        if obs.state_changed and not obs.approval_requested:
            return Check(PERMISSION, FAILED, "confirm then change",
                         "changed without confirming",
                         "the human approval gate was skipped")
    return Check(PERMISSION, PASSED, "the approval gate held",
                 "no unapproved change")


def _isolation(case: Case, obs: Observation) -> Check:
    """Project-scoped work must not become globally visible on its own."""
    if obs.project_id is None and obs.visible_globally is None:
        return Check(ISOLATION, NOT_APPLICABLE)
    if obs.project_id is None:
        return Check(ISOLATION, NOT_MEASURED, "project scope", None)
    if obs.project_id and obs.visible_globally:
        return Check(ISOLATION, FAILED, "project-only",
                     "globally visible",
                     "work scoped to a Project became visible outside it "
                     "without anyone publishing it")
    return Check(ISOLATION, PASSED, "project scope respected",
                 obs.project_id)


def check(case: Case, observation: Observation, *,
          computed_values: dict[str, float] | None = None) -> Report:
    """Every dimension, in §7's order. No model is consulted."""
    return Report(case_id=case.case_id, checks=[
        _capability(case, observation),
        _officer(case, observation),
        _agents(case, observation),
        _tools(case, observation),
        _datasets(case, observation),
        _relationships(case, observation),
        _period(case, observation),
        _grain(case, observation),
        _filters(case, observation),
        _operations(case, observation),
        _result_schema(case, observation),
        _result_ids(case, observation),
        _values(case, observation, computed_values),
        _invariants(case, observation),
        _clarification(case, observation),
        _permission(case, observation),
        _isolation(case, observation),
    ])


def check_many(pairs: Sequence[tuple[Case, Observation]]) -> list[Report]:
    return [check(case, obs) for case, obs in pairs]


def aggregate(reports: Sequence[Report]) -> dict[str, Any]:
    """Per-dimension totals across a run.

    Unmeasured is reported beside passed and failed rather than folded into
    either, so a dimension nothing observed shows up as a gap in the
    measurement instead of as a result.
    """
    tally: dict[str, dict[str, int]] = {
        d: dict.fromkeys(VERDICTS, 0) for d in DIMENSIONS}
    for report in reports:
        for item in report.checks:
            tally[item.dimension][item.verdict] += 1
    return {
        "cases": len(reports),
        "dimensions": tally,
        "settled": sum(1 for r in reports if r.settled),
        "with_failures": sum(1 for r in reports if r.failed),
        "mean_coverage": (
            sum(r.coverage for r in reports) / len(reports)
            if reports else 0.0),
    }
