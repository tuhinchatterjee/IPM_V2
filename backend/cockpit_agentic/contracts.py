"""
The typed contracts the stages exchange. Specification section 13.

These structure communication and enforcement. **None of them is an analytical
template.** `AnalysisPlan` has a `method_summary` field and no method
vocabulary; `ExecutionSubmission` carries whatever SQL or Python Opus wrote and
has no shape opinion about it. That is the point: the contracts say what must
be *present*, never what the analysis must *be*.

Where the validation lives
--------------------------
Each contract validates its own structure on construction, because a
malformed model response must fail loudly at the boundary rather than half-way
through execution. Structural validity is not analytical correctness and this
module never claims otherwise -- section 1.6.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.cockpit_agentic import DOMAIN

# ------------------------------------------------------- decision vocabulary

#: FunctionalityDecision.decision
PROCEED_COCKPIT = "PROCEED_COCKPIT"
REDIRECT = "REDIRECT"
CLARIFY_FUNCTIONALITY = "CLARIFY_FUNCTIONALITY"
UNSUPPORTED_REQUEST = "UNSUPPORTED"
DECISIONS = (PROCEED_COCKPIT, REDIRECT, CLARIFY_FUNCTIONALITY,
             UNSUPPORTED_REQUEST)

#: AnalysisReviewDecision.decision
ANSWER = "ANSWER"
REVISE_ANALYSIS = "REVISE_ANALYSIS"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
SYSTEM_ERROR = "SYSTEM_ERROR"
BUDGET_LIMITED = "BUDGET_LIMITED"
REVIEW_DECISIONS = (ANSWER, REVISE_ANALYSIS, NEEDS_CLARIFICATION,
                    INSUFFICIENT_DATA, SYSTEM_ERROR, BUDGET_LIMITED)

#: ExecutionFailurePacket.category -- section 8.2's taxonomy, complete.
SYNTAX_ERROR = "SYNTAX_ERROR"
UNRESOLVED_FIELD = "UNRESOLVED_FIELD"
UNRESOLVED_RELATION = "UNRESOLVED_RELATION"
INVALID_FILTER_VALUE = "INVALID_FILTER_VALUE"
TYPE_MISMATCH = "TYPE_MISMATCH"
INPUT_SHAPE_MISMATCH = "INPUT_SHAPE_MISMATCH"
MISSING_SOURCE_DATA = "MISSING_SOURCE_DATA"
OUT_OF_SCOPE_ACCESS = "OUT_OF_SCOPE_ACCESS"
PERMISSION_DENIED = "PERMISSION_DENIED"
UNSAFE_OPERATION = "UNSAFE_OPERATION"
RUNTIME_ERROR = "RUNTIME_ERROR"
RESOURCE_LIMIT = "RESOURCE_LIMIT"
SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"

#: Not in section 8.2's list, because 8.2 enumerates ways a SUBMISSION can
#: fail and these are ways the RUNTIME cannot start. They are stop statuses
#: rather than failure categories, and they are here so both vocabularies live
#: in one file. The Cockpit has no deterministic reader, so an unconfigured or
#: unserveable model is not a degraded mode -- it is the end of the request.
MODEL_CONFIGURATION_MISSING = "MODEL_CONFIGURATION_MISSING"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"

ERROR_CATEGORIES = (
    SYNTAX_ERROR, UNRESOLVED_FIELD, UNRESOLVED_RELATION, INVALID_FILTER_VALUE,
    TYPE_MISMATCH, INPUT_SHAPE_MISMATCH, MISSING_SOURCE_DATA,
    OUT_OF_SCOPE_ACCESS, PERMISSION_DENIED, UNSAFE_OPERATION, RUNTIME_ERROR,
    RESOURCE_LIMIT, SANDBOX_UNAVAILABLE, INFRASTRUCTURE_ERROR,
    CONTEXT_TOO_LARGE)

#: Failures that must fail closed immediately -- section 8.3. Five is a
#: ceiling, not an obligation, and a security or permission refusal does not
#: get four more tries at a cross-domain workaround.
FAIL_CLOSED = frozenset({OUT_OF_SCOPE_ACCESS, PERMISSION_DENIED,
                         UNSAFE_OPERATION})

#: value_origin -- section 4.1. Never conflated.
VALUE_ORIGINS = ("actual", "source_forecast", "derived", "carried_forward",
                 "synthetic_demo")

#: missing_reason -- section 4.1.
MISSING_REASONS = ("unknown", "not_collected", "not_applicable", "withheld",
                   "mapping_failed", "no_prior_observation", "not_yet_due",
                   "outside_coverage")

#: observation_status for macro rows -- section 4.11.
OBSERVATION_STATUSES = ("historical_actual", "current_actual", "nowcast",
                        "forecast")

SQL = "sql"
PYTHON = "python"
LANGUAGES = (SQL, PYTHON)


class ContractError(ValueError):
    """A structurally invalid contract. Raised at the boundary, never salvaged."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def fingerprint(*parts: Any) -> str:
    """A stable normalized identity for a code candidate.

    Whitespace and case are normalized so that re-indenting a failed query is
    not mistaken for a changed approach; section 8.3 requires a CHANGED
    relevant approach, not a reformatted one.
    """
    blob = "\x1f".join(
        re.sub(r"\s+", " ", str(p or "")).strip().lower() for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


# ------------------------------------------------------- 1. NormalizedQuestion

@dataclass
class CleanedQuestion:
    """Sonnet pass 1. Faithful cleanup and translation, nothing else."""

    original_text: str
    detected_language: str
    english_text: str
    #: What pass 1 was unsure of. Preserved rather than resolved.
    uncertainties: list[str] = field(default_factory=list)
    #: Entities, numbers and negations pass 1 asserts it carried through
    #: unchanged, so a test can check that it did.
    preserved_terms: list[str] = field(default_factory=list)
    failed: bool = False
    failure_reason: str = ""

    def __post_init__(self) -> None:
        _require(bool(_clean(self.original_text)),
                 "the original question text is required and is never dropped")
        if not _clean(self.english_text):
            # A failed pass 1 does not rewrite intent. The raw text stands and
            # the failure is visible downstream.
            self.english_text = self.original_text
            self.failed = True
            self.failure_reason = (self.failure_reason
                                   or "pass 1 returned no English text")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedQuestion:
    """Sonnet pass 2. The business request, with ambiguity preserved."""

    business_question: str
    subquestions: list[str] = field(default_factory=list)
    requested_measures: list[str] = field(default_factory=list)
    requested_actions: list[str] = field(default_factory=list)
    #: Scope the user stated in THIS message, versus scope inherited from the
    #: thread. Section 7.3 requires them separated, because a new explicit
    #: instruction overrides an inherited filter.
    explicit_scope: dict[str, Any] = field(default_factory=dict)
    inherited_scope: dict[str, Any] = field(default_factory=dict)
    inherited_from_exchange_ids: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    entity_references: list[str] = field(default_factory=list)
    preferred_presentation: str = ""
    response_language: str = "en"
    #: Genuine ambiguity. NOT resolved by guessing -- it travels to Opus.
    unresolved_ambiguity: list[str] = field(default_factory=list)
    failed: bool = False
    failure_reason: str = ""

    def __post_init__(self) -> None:
        _require(bool(_clean(self.business_question)),
                 "the normalized business question is required")
        if not self.subquestions:
            self.subquestions = [self.business_question]

    @property
    def effective_scope(self) -> dict[str, Any]:
        """Explicit wins. Section 7.1: a new explicit instruction overrides an
        inherited filter, and this is the only place that precedence lives."""
        merged = dict(self.inherited_scope)
        merged.update(self.explicit_scope)
        return merged

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["effective_scope"] = self.effective_scope
        return out


# ----------------------------------------------------------- 2. CockpitFieldSpec

@dataclass(frozen=True)
class CockpitFieldSpec:
    """One authorized field. Section 4's required per-field metadata."""

    name: str
    relation: str
    label: str
    definition: str
    dtype: str
    unit: str = ""
    #: additive / not_additive / ordinal / point_in_time / identifier / enum
    aggregation: str = "not_additive"
    nullable: bool = True
    enumeration: tuple[str, ...] = ()
    currency_scoped: bool = False
    value_origin: str = "synthetic_demo"
    availability: str = "demo_only"      # actual | partial | demo_only | unavailable
    missing_reason: str = ""
    source_name: str = ""
    lineage: str = ""
    #: Set for the generated per-collateral-type and per-macro-horizon columns,
    #: so the catalog can prove no `{type}` placeholder ever reaches Opus.
    generated_from: str = ""

    def __post_init__(self) -> None:
        _require(bool(_clean(self.name)), "a field needs a name")
        _require(bool(_clean(self.definition)),
                 f"{self.name}: a field without a definition is not usable "
                 f"context")
        _require("{" not in self.name and "}" not in self.name,
                 f"{self.name}: an unexpanded placeholder must never reach the "
                 f"catalog")
        _require(self.availability in
                 ("actual", "partial", "demo_only", "unavailable"),
                 f"{self.name}: {self.availability!r} is not an availability")

    def compact(self) -> dict[str, Any]:
        """The serialization that goes to Opus. Complete, never abridged to a
        top-ten list -- section 7.4-D -- but with empty keys dropped so the
        whole dictionary fits."""
        out: dict[str, Any] = {"n": self.name, "t": self.dtype,
                               "d": self.definition}
        if self.unit:
            out["u"] = self.unit
        if self.aggregation != "not_additive":
            out["agg"] = self.aggregation
        if self.enumeration:
            out["enum"] = list(self.enumeration)
        if self.availability != "demo_only":
            out["avail"] = self.availability
        if not self.nullable:
            out["req"] = True
        return out


# -------------------------------------------------------- 3. DataCoverageProfile

@dataclass
class FieldProfile:
    """One field's measured missingness. From full authorized data, not previews."""

    field_name: str
    relation: str
    total_rows: int = 0
    observed: int = 0
    null_count: int = 0
    invalid_count: int = 0
    not_applicable: int = 0
    withheld: int = 0
    #: Two denominators, kept apart when they differ -- section 5.
    missing_rate_overall: float = 0.0
    missing_rate_among_applicable: float = 0.0
    by_quarter: dict[str, float] = field(default_factory=dict)
    earliest_source_period: str = ""
    latest_source_period: str = ""
    stale_carried_forward_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def compact(self) -> dict[str, Any]:
        out: dict[str, Any] = {"n": self.field_name,
                               "miss": round(self.missing_rate_overall, 4)}
        if abs(self.missing_rate_among_applicable
               - self.missing_rate_overall) > 1e-9:
            out["miss_applicable"] = round(self.missing_rate_among_applicable, 4)
        # A global rate must not conceal a completely missing quarter. Listed
        # by name while that is short; a field empty in most quarters is
        # reported as a count and a range instead, which says MORE than twenty
        # labels do and costs a fraction of the context.
        empty = sorted(q for q, r in self.by_quarter.items() if r >= 0.9999)
        if empty:
            if len(empty) <= 4:
                out["quarters_fully_missing"] = empty
            elif len(empty) == len(self.by_quarter):
                out["quarters_fully_missing"] = "every quarter"
            else:
                out["quarters_fully_missing"] = (
                    f"{len(empty)} of {len(self.by_quarter)} quarters, "
                    f"{empty[0]} to {empty[-1]}")
        if self.stale_carried_forward_rate > 0:
            out["carried_forward"] = round(self.stale_carried_forward_rate, 4)
        return out


@dataclass
class DataCoverageProfile:
    """The versioned, release-pinned profile for one dataset release."""

    dataset_release_id: str
    catalog_version: str
    computed_at: str
    reporting_quarters: list[str] = field(default_factory=list)
    populated_quarters: list[str] = field(default_factory=list)
    missing_quarters: list[str] = field(default_factory=list)
    fields: dict[str, FieldProfile] = field(default_factory=dict)
    row_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in asdict(self).items() if k != "fields"}
        out["fields"] = {k: v.to_dict() for k, v in self.fields.items()}
        return out


# ---------------------------------------------- 4. FunctionalityRegistryEntry

@dataclass(frozen=True)
class FunctionalityRegistryEntry:
    """One module's ownership contract. Section 6.1. Descriptions come from the
    application, never from a model."""

    functionality_id: str
    ui_label: str
    description: str
    owns: tuple[str, ...]
    excludes: tuple[str, ...]
    supported_actions: tuple[str, ...]
    examples: tuple[str, ...]
    counterexamples: tuple[str, ...]
    data_domain: str
    enabled: bool
    route: str = ""
    permission_required: str = ""
    unavailable_reason: str = ""

    def __post_init__(self) -> None:
        _require(bool(_clean(self.functionality_id)),
                 "a registry entry needs an id")
        _require(bool(self.enabled) == bool(_clean(self.route)),
                 f"{self.functionality_id}: an enabled functionality must have "
                 f"a verified route and a disabled one must not offer a link")
        _require(self.enabled or bool(_clean(self.unavailable_reason)),
                 f"{self.functionality_id}: a disabled functionality must say "
                 f"why, rather than silently vanishing")

    def compact(self) -> dict[str, Any]:
        return {"id": self.functionality_id, "label": self.ui_label,
                "description": self.description, "owns": list(self.owns),
                "does_not_own": list(self.excludes),
                "actions": list(self.supported_actions),
                "examples": list(self.examples),
                "counterexamples": list(self.counterexamples),
                "enabled": self.enabled,
                "route": self.route or None,
                "unavailable_reason": self.unavailable_reason or None}


# ------------------------------------------------------- 5. FunctionalityDecision

@dataclass
class SuitabilityScore:
    functionality_id: str
    score: int
    justification: str

    def __post_init__(self) -> None:
        _require(0 <= int(self.score) <= 100,
                 f"{self.functionality_id}: a suitability score is 0-100")
        self.score = int(self.score)


@dataclass
class AlternativeQuestion:
    """A Cockpit-only suggestion that must actually be answerable."""

    question: str
    required_fields: list[str] = field(default_factory=list)
    available_periods: list[str] = field(default_factory=list)
    retained_scope: dict[str, Any] = field(default_factory=dict)
    limitation: str = ""

    def __post_init__(self) -> None:
        _require(bool(_clean(self.question)), "an alternative needs a question")
        _require(bool(self.required_fields),
                 "an alternative that names no field cannot be shown to be "
                 "answerable, and an unanswerable suggestion is worse than none")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FunctionalityDecision:
    """Opus's FIRST responsibility. Section 6.2."""

    decision: str
    scores: list[SuitabilityScore] = field(default_factory=list)
    best_fit: str = ""
    requested_actions: list[str] = field(default_factory=list)
    relevant_exclusions: list[str] = field(default_factory=list)
    mixed_scope: bool = False
    mixed_scope_explanation: str = ""
    referral_destination: str = ""
    referral_reason: str = ""
    referral_route: str = ""
    referral_enabled: bool = False
    alternatives: list[AlternativeQuestion] = field(default_factory=list)
    clarification_question: str = ""
    clarification_options: list[str] = field(default_factory=list)
    public_explanation: str = ""

    def __post_init__(self) -> None:
        _require(self.decision in DECISIONS,
                 f"{self.decision!r} is not a functionality decision")
        if self.decision == REDIRECT:
            _require(bool(_clean(self.referral_destination)),
                     "a redirect must name its destination")
            _require(bool(_clean(self.referral_reason)),
                     "a redirect must say why, in terms of the actual request")
        if self.decision == CLARIFY_FUNCTIONALITY:
            _require(bool(_clean(self.clarification_question)),
                     "a functionality clarification must ask something")
        _require(len(self.alternatives) <= 3,
                 "at most three alternative Cockpit questions")

    @property
    def may_execute(self) -> bool:
        """The single predicate the gate is read through. A referral or a
        clarification performs ZERO analytical execution -- section 9.6."""
        return self.decision == PROCEED_COCKPIT

    def cockpit_score(self) -> int:
        for s in self.scores:
            if s.functionality_id == "cockpit":
                return s.score
        return 0

    def uniquely_highest_cockpit(self) -> bool:
        """Section 6.2: proceed only if Cockpit is the UNIQUE highest scorer.
        A tie is a clarification, not a silent Cockpit execution."""
        if not self.scores:
            return False
        best = max(s.score for s in self.scores)
        winners = [s.functionality_id for s in self.scores if s.score == best]
        return winners == ["cockpit"]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["may_execute"] = self.may_execute
        return out


# ------------------------------------------------------------- 6. AnalysisPlan

@dataclass
class AnalysisPlan:
    """Opus's plan. Section 7.5.

    Note what is NOT here: no method enum, no template id, no required step
    vocabulary. `method_summary` is free text because the method is Opus's
    choice, and a field that constrained it would be the template this
    architecture removes.
    """

    plan_id: str
    subquestions: list[str]
    scope: dict[str, Any] = field(default_factory=dict)
    fields_required: list[str] = field(default_factory=list)
    joins_required: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    missingness_handling: str = ""
    expected_output_grain: str = ""
    expected_units: str = ""
    method_summary: str = ""
    alternative_method: str = ""
    how_it_answers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(bool(_clean(self.plan_id)), "a plan needs an id")
        _require(bool(self.subquestions),
                 "a plan that addresses no subquestion answers nothing")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -------------------------------------------------------- 7. ExecutionSubmission

@dataclass
class ExecutionStep:
    """One executable step, exactly as Opus wrote it."""

    step_id: str
    language: str
    code: str
    parameters: dict[str, Any] = field(default_factory=dict)
    #: Artifact ids from earlier steps this one consumes.
    inputs: list[str] = field(default_factory=list)
    purpose: str = ""

    def __post_init__(self) -> None:
        _require(self.language in LANGUAGES,
                 f"{self.language!r} is not an executable language here")
        _require(bool(_clean(self.code)), f"{self.step_id}: no code submitted")

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.language, self.code,
                           json.dumps(self.parameters, sort_keys=True,
                                      default=str))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionSubmission:
    """A batch of steps Opus asks CreditProbe to run. Never edited here."""

    submission_id: str
    plan_id: str
    analysis_round: int
    submission_number: int
    steps: list[ExecutionStep] = field(default_factory=list)
    authored_by: str = "opus"

    def __post_init__(self) -> None:
        _require(bool(self.steps), "an empty submission executes nothing")
        _require(self.authored_by == "opus",
                 "CreditProbe never authors a submission; section 7.6A makes "
                 "Opus the sole owner of query and code authorship")

    @property
    def fingerprint(self) -> str:
        return fingerprint(*(s.fingerprint for s in self.steps))

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["fingerprint"] = self.fingerprint
        return out


# ------------------------------------------------------ 8. ExecutionResultPacket

@dataclass
class StepResult:
    step_id: str
    status: str                     # success | empty | truncated | skipped
    executed_code: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    columns: list[dict[str, str]] = field(default_factory=list)
    grain: str = ""
    row_count: int = 0
    artifact_id: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    join_multiplicity: dict[str, Any] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResultPacket:
    """Section 7.7. What actually came back, told apart honestly."""

    request_id: str
    plan_id: str
    submission_id: str
    submission_number: int
    analysis_round: int
    dataset_release_id: str
    status: str                     # complete | partial | empty | failed
    steps: list[StepResult] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------- 9. ExecutionFailurePacket

@dataclass
class CatalogAlternative:
    """A field that DOES exist. Offered as a fact, never as a chosen substitute."""

    field_name: str
    meaning: str
    unit: str = ""
    dtype: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field_name, "meaning": self.meaning,
                "unit": self.unit, "type": self.dtype}


@dataclass
class ExecutionFailurePacket:
    """Section 8.2. The factual packet CreditProbe returns to Opus.

    It contains diagnostics and catalog facts. It contains NO repaired code,
    because CreditProbe never writes any -- section 7.6A. `available_alternatives`
    reports what exists; choosing among them is Opus's analytical decision.
    """

    request_id: str
    plan_id: str
    analysis_round: int
    submission_id: str
    submission_number: int
    failing_step_id: str
    phase: str
    language: str
    category: str
    message: str
    submitted_code: str
    parameters: dict[str, Any] = field(default_factory=dict)
    sqlstate: str = ""
    line: int | None = None
    column: int | None = None
    unresolved_name: str = ""
    invalid_value: str = ""
    available_alternatives: list[CatalogAlternative] = field(default_factory=list)
    available_filter_values: dict[str, list[str]] = field(default_factory=dict)
    relevant_grains: dict[str, str] = field(default_factory=dict)
    valid_join_keys: dict[str, list[str]] = field(default_factory=dict)
    field_coverage: dict[str, Any] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    reusable_artifacts: list[str] = field(default_factory=list)
    previous_failed_approaches: list[dict[str, Any]] = field(default_factory=list)
    partial_results_complete_for: list[str] = field(default_factory=list)
    repairable: bool = True
    user_input_needed: bool = False
    suggested_clarification: str = ""
    operator_fix_required: bool = False
    dataset_release_id: str = ""
    duplicate_fingerprint: str = ""
    budget: dict[str, Any] = field(default_factory=dict)
    permitted_next_actions: list[str] = field(default_factory=list)
    #: Named, not embedded. Section 8.1: the static context belongs ONCE in the
    #: assembled input, not redundantly inside every error JSON as well. The
    #: runtime asserts each named part is actually present in the outbound
    #: request.
    context_attached: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require(self.category in ERROR_CATEGORIES,
                 f"{self.category!r} is not in the section 8.2 taxonomy")
        _require(bool(_clean(self.submitted_code)),
                 "a failure packet without the exact submitted code is an "
                 "error-only retry, which section 8.1 forbids")
        if self.category in FAIL_CLOSED:
            self.repairable = False

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["available_alternatives"] = [a.to_dict()
                                         for a in self.available_alternatives]
        return out


# ---------------------------------------------------- 10. AnalysisReviewDecision

@dataclass
class SubquestionEvidence:
    subquestion: str
    answered: bool
    evidence_fact_ids: list[str] = field(default_factory=list)
    gap: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisReviewDecision:
    """Section 7.8. When evidence suffices this carries the answer with it."""

    decision: str
    per_subquestion: list[SubquestionEvidence] = field(default_factory=list)
    revised_plan: AnalysisPlan | None = None
    revised_submission: ExecutionSubmission | None = None
    gap_addressed: str = ""
    clarification_question: str = ""
    clarification_options: list[str] = field(default_factory=list)
    answer: "AnswerEnvelope | None" = None

    def __post_init__(self) -> None:
        _require(self.decision in REVIEW_DECISIONS,
                 f"{self.decision!r} is not a review decision")
        if self.decision == REVISE_ANALYSIS:
            _require(self.revised_submission is not None,
                     "a revision must carry the new Opus-authored code; "
                     "CreditProbe does not write it")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "per_subquestion": [s.to_dict() for s in self.per_subquestion],
            "revised_plan": (self.revised_plan.to_dict()
                             if self.revised_plan else None),
            "revised_submission": (self.revised_submission.to_dict()
                                   if self.revised_submission else None),
            "gap_addressed": self.gap_addressed,
            "clarification_question": self.clarification_question,
            "clarification_options": list(self.clarification_options),
            "answer": self.answer.to_dict() if self.answer else None,
        }


# ------------------------------------------------------------ 11. AnswerEnvelope

@dataclass
class AnswerTable:
    title: str
    columns: list[str]
    rows: list[list[Any]]
    units: dict[str, str] = field(default_factory=dict)
    fact_ids: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerChart:
    """A declared chart SPECIFICATION. Never model-provided HTML or JavaScript
    -- section 7.9 forbids executing either."""

    kind: str                       # bar | line | waterfall | scatter
    title: str
    series: list[dict[str, Any]] = field(default_factory=list)
    x_label: str = ""
    y_label: str = ""
    unit: str = ""
    fact_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require(self.kind in ("bar", "line", "waterfall", "scatter"),
                 f"{self.kind!r} is not a permitted chart kind")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerEnvelope:
    """Section 7.8/7.9. The final answer, a referral, or an honest stop."""

    kind: str                       # answer | referral | clarification | stop
    narrative: str
    status: str = ""
    complete: bool = True
    approximate: bool = False
    tables: list[AnswerTable] = field(default_factory=list)
    charts: list[AnswerChart] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    #: Claims the evidence supports as association only. Never stated as cause.
    hypotheses: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    referral: dict[str, Any] = field(default_factory=dict)
    alternatives: list[AlternativeQuestion] = field(default_factory=list)
    clarification_question: str = ""
    clarification_options: list[str] = field(default_factory=list)
    stop_reason: str = ""
    what_was_understood: str = ""
    what_was_tried: list[str] = field(default_factory=list)
    what_would_help: str = ""

    def __post_init__(self) -> None:
        _require(self.kind in ("answer", "referral", "clarification", "stop"),
                 f"{self.kind!r} is not an answer kind")
        _require(bool(_clean(self.narrative)),
                 "an envelope with no prose says nothing to the user")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "narrative": self.narrative,
            "status": self.status, "complete": self.complete,
            "approximate": self.approximate,
            "tables": [t.to_dict() for t in self.tables],
            "charts": [c.to_dict() for c in self.charts],
            "limitations": list(self.limitations),
            "assumptions": list(self.assumptions),
            "hypotheses": list(self.hypotheses),
            "fact_ids": list(self.fact_ids),
            "referral": dict(self.referral),
            "alternatives": [a.to_dict() for a in self.alternatives],
            "clarification_question": self.clarification_question,
            "clarification_options": list(self.clarification_options),
            "stop_reason": self.stop_reason,
            "what_was_understood": self.what_was_understood,
            "what_was_tried": list(self.what_was_tried),
            "what_would_help": self.what_would_help,
        }


# -------------------------------------------------------------- 12. ThreadSummary

@dataclass
class ThreadSummary:
    """Section 7.9. The rolling summary, with the exchange it is current to."""

    thread_id: str
    summary_through_exchange_id: str
    current_topic: str = ""
    settled_definitions: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    authorized_references: list[str] = field(default_factory=list)
    supported_conclusions: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    version: int = 1
    #: Exchanges completed after this summary was written, to be included
    #: verbatim next time because the summary does not yet cover them.
    unsummarized_exchange_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Exchange:
    """One COMPLETE question and its final answer, referral or clarification.
    Not an individual message -- section 12."""

    exchange_id: str
    question: str
    answer: str
    kind: str = "answer"            # answer | referral | clarification | stop
    fact_ids: list[str] = field(default_factory=list)
    domain_id: str = DOMAIN
    dataset_release_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------- 13. ArtifactManifest

@dataclass
class Artifact:
    """A stored result. Carries the scope that authorizes it, checked on every
    fetch rather than only at creation -- section 10.4."""

    artifact_id: str
    kind: str                       # table | facts | chart_spec
    domain_id: str
    tenant_id: str
    dataset_release_id: str
    step_id: str
    row_count: int
    byte_size: int
    columns: list[dict[str, str]] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        _require(self.domain_id == DOMAIN,
                 f"{self.artifact_id}: an artifact outside {DOMAIN} is not "
                 f"reachable from the Cockpit")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactManifest:
    request_id: str
    artifacts: dict[str, Artifact] = field(default_factory=dict)

    def add(self, artifact: Artifact) -> Artifact:
        self.artifacts[artifact.artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str, *, tenant_id: str,
            dataset_release_id: str) -> Artifact:
        """Validated on FETCH, not just on creation. A forged or stale id, or
        one from another tenant or release, is refused here."""
        art = self.artifacts.get(str(artifact_id))
        if art is None:
            raise ContractError(f"{artifact_id!r} is not an artifact of this "
                                f"request")
        if art.tenant_id != tenant_id:
            raise ContractError(f"{artifact_id!r} does not belong to this "
                                f"principal")
        if art.dataset_release_id != dataset_release_id:
            raise ContractError(
                f"{artifact_id!r} was produced under release "
                f"{art.dataset_release_id!r}, and this request is pinned to "
                f"{dataset_release_id!r}. Releases are never silently mixed.")
        return art

    def to_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id,
                "artifacts": {k: v.to_dict()
                              for k, v in self.artifacts.items()}}


# ------------------------------------------------------- 14. CockpitContextPacket
# Defined in `context.py`, where the builder that fills it lives.
# ------------------------------------------------------- 15. RequestBudgetLedger
# Defined in `ledger.py`, where the enforcement lives.


__all__ = [
    "ANSWER", "AlternativeQuestion", "AnalysisPlan", "AnalysisReviewDecision",
    "AnswerChart", "AnswerEnvelope", "AnswerTable", "Artifact",
    "ArtifactManifest", "BUDGET_LIMITED", "CLARIFY_FUNCTIONALITY",
    "CONTEXT_TOO_LARGE", "CatalogAlternative", "CleanedQuestion",
    "CockpitFieldSpec", "ContractError", "DECISIONS", "DataCoverageProfile",
    "ERROR_CATEGORIES", "Exchange", "ExecutionFailurePacket",
    "ExecutionResultPacket", "ExecutionStep", "ExecutionSubmission",
    "FAIL_CLOSED", "FieldProfile", "FunctionalityDecision",
    "FunctionalityRegistryEntry", "INFRASTRUCTURE_ERROR", "INSUFFICIENT_DATA",
    "INPUT_SHAPE_MISMATCH", "INVALID_FILTER_VALUE", "LANGUAGES",
    "MISSING_REASONS", "MISSING_SOURCE_DATA", "NEEDS_CLARIFICATION",
    "NormalizedQuestion", "OBSERVATION_STATUSES", "OUT_OF_SCOPE_ACCESS",
    "MODEL_CONFIGURATION_MISSING", "MODEL_UNAVAILABLE",
    "PERMISSION_DENIED", "PROCEED_COCKPIT", "PYTHON", "REDIRECT",
    "RESOURCE_LIMIT", "REVIEW_DECISIONS", "REVISE_ANALYSIS", "RUNTIME_ERROR",
    "SANDBOX_UNAVAILABLE", "SQL", "SYNTAX_ERROR", "SYSTEM_ERROR", "StepResult",
    "SubquestionEvidence", "SuitabilityScore", "TYPE_MISMATCH", "ThreadSummary",
    "UNRESOLVED_FIELD", "UNRESOLVED_RELATION", "UNSAFE_OPERATION",
    "UNSUPPORTED_REQUEST", "VALUE_ORIGINS", "fingerprint",
]
