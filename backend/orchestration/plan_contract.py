"""
The strict structured planner document. §20.

    "The planner must return a strict schema. … Do not parse free-form prose
     into execution logic."

What "strict" means here
------------------------
Three things, and each of them closes a different way a plan goes wrong.

**No prose in an execution field.** Every field that decides what runs is a
list, a mapping or an enum. `read` refuses a string where a list belongs rather
than splitting it on commas, because a planner that returns
`"sector, segment"` and gets away with it will one day return
`"sector and segment where stage is 2"` and get away with that too.

**No unknown keys.** A misspelled key is worse than a missing one: the field it
was meant to be is silently empty, and the plan then answers a slightly
different question with complete confidence. `additionalProperties: false` in
the schema, and `read` reports what it dropped.

**Every field present.** Twenty-nine names, and an absent one is an empty value
with a recorded reason rather than a key that is simply not there. A caller
reading `document.get("invariants")` and getting `None` cannot tell "no
invariants apply" from "the planner forgot".

Why a separate module from `capability.SCHEMA`
----------------------------------------------
The capability reader is the first call — is this a catalogue question or an
analysis? — and it is deliberately small and fast. §20's document is the whole
plan: the reading, the objectives and their coverage plan, the data, the
method, the invariants, the visualization, the risk flags, and which teaching
cases were used. It is assembled across the run rather than returned by one
call, and the Trace (§45) and the Full Calculation Pack (§46) both show it.

Keeping them apart means the router's schema does not grow twenty fields it
never fills, and this document does not have to pretend it came from a single
model reply.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any

from backend.orchestration import objectives as ob

CONTRACT_VERSION = "1.0.0"

#: §20's field list, verbatim and in order.
FIELDS: tuple[str, ...] = (
    "capability",
    "conversation_action",
    "same_turn_referents",
    "prior_context_referents",
    "objectives",
    "objective_coverage_plan",
    "concepts",
    "ambiguities",
    "entities",
    "cohorts",
    "metrics",
    "dimensions",
    "filters",
    "period",
    "grain",
    "population",
    "domains",
    "datasets",
    "relationships",
    "joins",
    "operations",
    "method",
    "analytical_plan",
    "invariants",
    "visualization",
    "clarification",
    "risk_flags",
    "confidence_components",
    "teaching_case_ids_used",
)

#: Fields whose value decides what runs. A string here is a bug, not a
#: shorthand — see the module docstring.
STRUCTURED: frozenset[str] = frozenset({
    "same_turn_referents", "prior_context_referents", "objectives",
    "objective_coverage_plan", "concepts", "entities", "cohorts", "metrics",
    "dimensions", "filters", "period", "population", "domains", "datasets",
    "relationships", "joins", "operations", "method", "analytical_plan",
    "invariants", "visualization", "clarification", "risk_flags",
    "confidence_components", "teaching_case_ids_used", "ambiguities",
})

#: The two that are legitimately scalar: an enum and an enum.
ENUMS: dict[str, tuple[str, ...]] = {
    "capability": ("ANALYSIS", "DATA_DISCOVERY", "DATA_DICTIONARY",
                   "DATA_RELATIONSHIP", "DATA_QUALITY", "METHOD_DISCOVERY",
                   "UNSUPPORTED"),
    "conversation_action": ("NEW_REQUEST", "CONTINUE", "MODIFY_PREVIOUS",
                            "MODIFY_PRESENTATION", "ENRICH_PREVIOUS",
                            "WIDEN_SCOPE", "RESET_SCOPE",
                            "METADATA_FOLLOWUP", "NAVIGATE",
                            "ASSESS_PREVIOUS_RESULT",
                            "CORRECT_INCOMPLETE_RESPONSE", "CLARIFY"),
}

#: The risk flags a plan may raise. A free-text flag cannot be counted, and
#: §45 shows these on the Trace.
RISK_FLAGS: tuple[str, ...] = (
    "AMBIGUOUS_MEASURE",
    "AMBIGUOUS_POPULATION",
    "AMBIGUOUS_PERIOD",
    "UNRESOLVED_REFERENT",
    "CROSS_GRAIN_JOIN",
    "MIXED_PERIOD_BASIS",
    "RATIO_AGGREGATION",
    "SMALL_POPULATION",
    "SCOPE_MISMATCH",
    "NO_GOVERNED_METHOD",
    "OBJECTIVE_UNCOVERED",
)

#: What confidence is made of. §20 asks for components rather than a number,
#: because one number cannot be argued with: a plan that is 0.4 because the
#: period is ambiguous needs a different response from one that is 0.4 because
#: no governed method exists.
CONFIDENCE_COMPONENTS: tuple[str, ...] = (
    "reading",
    "data_availability",
    "method_fit",
    "referent_resolution",
    "objective_coverage",
)


@dataclass(frozen=True)
class Problem:
    """One reason a planner document is not usable."""

    field: str
    detail: str

    def __str__(self) -> str:
        return f"{self.field}: {self.detail}"


@dataclass
class Plan:
    """§20's document."""

    capability: str = ""
    conversation_action: str = ""
    #: {surface form: cohort id} inside this message (§10).
    same_turn_referents: dict[str, str] = field(default_factory=dict)
    #: {surface form: what it resolved to} from earlier turns.
    prior_context_referents: dict[str, str] = field(default_factory=dict)
    objectives: list[dict[str, Any]] = field(default_factory=list)
    #: {objective_id: status} — §21's statuses, as PLANNED before execution.
    objective_coverage_plan: dict[str, str] = field(default_factory=dict)
    concepts: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    cohorts: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)
    period: dict[str, Any] = field(default_factory=dict)
    grain: str = ""
    population: dict[str, Any] = field(default_factory=dict)
    domains: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    joins: list[dict[str, Any]] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    method: dict[str, Any] = field(default_factory=dict)
    analytical_plan: dict[str, Any] = field(default_factory=dict)
    invariants: list[str] = field(default_factory=list)
    visualization: dict[str, Any] = field(default_factory=dict)
    clarification: dict[str, Any] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    confidence_components: dict[str, float] = field(default_factory=dict)
    #: §17 and §45: which teaching cases shaped this plan. Ids only — the
    #: content is in the pack, and repeating it here would put a worked
    #: example inside a Trace an ordinary user reads.
    teaching_case_ids_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {name: asdict(self)[name] for name in FIELDS}

    @property
    def confidence(self) -> float:
        """The components, combined — never stored, always derived.

        The minimum rather than the mean: a plan whose referent resolution is
        0.2 and everything else is 1.0 is a plan about the wrong population,
        and a mean would report it at 0.84.
        """
        values = [float(v) for v in self.confidence_components.values()]
        return round(min(values), 3) if values else 0.0


# ---------------------------------------------------------------- the schema

def _array(description: str, item: dict[str, Any] | None = None
           ) -> dict[str, Any]:
    return {"type": "array", "items": item or {"type": "string"},
            "description": description}


SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(FIELDS),
    "properties": {
        "capability": {
            "type": "string", "enum": list(ENUMS["capability"]),
            "description": "What KIND of request this is. Only ANALYSIS "
                           "computes a figure.",
        },
        "conversation_action": {
            "type": "string", "enum": list(ENUMS["conversation_action"]),
            "description": "How this message relates to the conversation so "
                           "far.",
        },
        "same_turn_referents": {
            "type": "object", "additionalProperties": {"type": "string"},
            "description": "Pronouns whose antecedent is in THIS message, "
                           "mapped to the local cohort id they resolve to.",
        },
        "prior_context_referents": {
            "type": "object", "additionalProperties": {"type": "string"},
            "description": "References back to an earlier turn, mapped to "
                           "what they resolve to.",
        },
        "objectives": _array(
            "Every distinct thing the message asks for, in order.",
            {"type": "object", "additionalProperties": False,
             "required": ["objective_id", "description", "action"],
             "properties": {
                 "objective_id": {"type": "string"},
                 "description": {"type": "string"},
                 "action": {"type": "string", "enum": list(ob.ACTIONS)},
                 "measure_phrase": {"type": "string"},
                 "cohort_id": {"type": "string"},
             }}),
        "objective_coverage_plan": {
            "type": "object",
            "additionalProperties": {"type": "string",
                                     "enum": list(ob.STATUSES)},
            "description": "How each objective will be settled. Every "
                           "objective id must appear.",
        },
        "concepts": _array("Governed credit concepts, by their labels."),
        "ambiguities": _array("What the message leaves genuinely open."),
        "entities": _array(
            "Named things to filter or look up.",
            {"type": "object", "additionalProperties": False,
             "required": ["kind", "value"],
             "properties": {"kind": {"type": "string"},
                            "value": {"type": "string"}}}),
        "cohorts": _array(
            "Populations this message defines.",
            {"type": "object", "additionalProperties": False,
             "required": ["cohort_id", "definition"],
             "properties": {"cohort_id": {"type": "string"},
                            "definition": {"type": "string"},
                            "restricted": {"type": "boolean"}}}),
        "metrics": _array("The governed concepts that are the measures to "
                          "report."),
        "dimensions": _array("What to break the answer down by."),
        "filters": _array(
            "Governed restrictions.",
            {"type": "object", "additionalProperties": False,
             "required": ["field", "value"],
             "properties": {"field": {"type": "string"},
                            "op": {"type": "string"},
                            "value": {"type": "string"}}}),
        "period": {
            "type": "object", "additionalProperties": True,
            "description": "The period contract: the phrase, the basis, and "
                           "whether one date or two are needed.",
        },
        "grain": {"type": "string",
                  "description": "One row per what."},
        "population": {
            "type": "object", "additionalProperties": True,
            "description": "Which rows the analysis runs over, and whether "
                           "the population is matched across periods.",
        },
        "domains": _array("Governed data domains this needs."),
        "datasets": _array("Governed dataset names."),
        "relationships": _array("Declared relationships the plan traverses."),
        "joins": _array(
            "How the datasets are joined.",
            {"type": "object", "additionalProperties": True,
             "required": ["left", "right"],
             "properties": {"left": {"type": "string"},
                            "right": {"type": "string"},
                            "on": {"type": "string"},
                            "kind": {"type": "string"}}}),
        "operations": _array("The governed operations the plan performs."),
        "method": {
            "type": "object", "additionalProperties": True,
            "description": "The certified Analysis Studio method, where one "
                           "applies.",
        },
        "analytical_plan": {
            "type": "object", "additionalProperties": True,
            "description": "The plan skeleton. Never a compiled query.",
        },
        "invariants": _array("What a correct result must satisfy."),
        "visualization": {
            "type": "object", "additionalProperties": True,
            "description": "The chart the result's shape supports, or an "
                           "explicit refusal to chart it.",
        },
        "clarification": {
            "type": "object", "additionalProperties": True,
            "description": "The one question to ask, where the plan cannot "
                           "proceed without it.",
        },
        "risk_flags": _array("What about this plan needs watching.",
                             {"type": "string", "enum": list(RISK_FLAGS)}),
        "confidence_components": {
            "type": "object",
            "additionalProperties": {"type": "number",
                                     "minimum": 0, "maximum": 1},
            "description": "Confidence broken into its parts. One number "
                           "cannot be argued with.",
        },
        "teaching_case_ids_used": _array(
            "The ids of the teaching cases retrieved for this plan."),
    },
}


# ---------------------------------------------------------------- reading it

_TYPES: dict[str, type] = {
    f.name: (dict if f.name in ("same_turn_referents",
                                "prior_context_referents", "period",
                                "population", "method", "analytical_plan",
                                "visualization", "clarification",
                                "confidence_components",
                                "objective_coverage_plan")
             else str if f.name in ("capability", "conversation_action",
                                    "grain")
             else list)
    for f in dataclass_fields(Plan)
}


def read(raw: Any) -> tuple[Plan, list[Problem]]:
    """A planner reply as a document, and everything wrong with it.

    Never raises. A planner that returns something unusable is a routine
    event — the critic route (§27) exists for it — and an exception here would
    turn a repairable reply into a failed request.
    """
    problems: list[Problem] = []
    if not isinstance(raw, dict):
        return Plan(), [Problem("document", "the planner did not return an "
                                            "object")]

    unknown = sorted(set(raw) - set(FIELDS))
    for name in unknown:
        # A misspelled key is worse than a missing one: the field it was meant
        # to be is silently empty and the plan answers a different question.
        problems.append(Problem(name, "is not a field of the planner "
                                      "contract"))

    values: dict[str, Any] = {}
    for name in FIELDS:
        wanted = _TYPES[name]
        given = raw.get(name)
        if given is None:
            problems.append(Problem(name, "is missing"))
            continue
        if isinstance(given, str) and wanted is not str:
            # §20: do not parse free-form prose into execution logic. Splitting
            # "sector, segment" here is what makes "sector and segment where
            # stage is 2" survive the next release.
            problems.append(Problem(
                name, f"must be {'an object' if wanted is dict else 'a list'}, "
                      "not prose"))
            continue
        if not isinstance(given, wanted):
            problems.append(Problem(name, f"must be {wanted.__name__}"))
            continue
        values[name] = given

    plan = Plan(**values)
    problems += validate(plan)
    return plan, problems


def validate(plan: Plan) -> list[Problem]:
    """What a well-formed document still gets wrong."""
    problems: list[Problem] = []

    for name, allowed in ENUMS.items():
        value = getattr(plan, name)
        if value and value not in allowed:
            problems.append(Problem(name, f"{value!r} is not one of "
                                          f"{', '.join(allowed)}"))

    bad = [flag for flag in plan.risk_flags if flag not in RISK_FLAGS]
    if bad:
        problems.append(Problem("risk_flags", f"{', '.join(bad)} "
                                              "not governed flags"))

    unknown = [name for name in plan.confidence_components
               if name not in CONFIDENCE_COMPONENTS]
    if unknown:
        problems.append(Problem("confidence_components",
                                f"{', '.join(unknown)} is not a component"))
    for name, value in plan.confidence_components.items():
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            problems.append(Problem("confidence_components",
                                    f"{name} must be between 0 and 1"))

    ids = [str(o.get("objective_id") or "") for o in plan.objectives]
    if len(ids) != len(set(ids)):
        problems.append(Problem("objectives", "duplicate objective ids"))
    for objective in plan.objectives:
        action = objective.get("action")
        if action and action not in ob.ACTIONS:
            problems.append(Problem("objectives",
                                    f"{action!r} is not a governed action"))

    # §21: every objective needs a coverage plan. An objective with no planned
    # status is one nothing will ever report on, which is the silent omission
    # the whole validator exists to prevent.
    missing = [i for i in ids if i and i not in plan.objective_coverage_plan]
    if missing:
        problems.append(Problem("objective_coverage_plan",
                                f"{', '.join(missing)} has no planned "
                                "coverage"))
    stray = [i for i in plan.objective_coverage_plan if i not in ids]
    if stray:
        problems.append(Problem("objective_coverage_plan",
                                f"{', '.join(stray)} is not an objective"))
    for objective_id, status in plan.objective_coverage_plan.items():
        if status not in ob.STATUSES:
            problems.append(Problem("objective_coverage_plan",
                                    f"{objective_id}: {status!r} is not a "
                                    "coverage status"))

    if plan.capability == "ANALYSIS" and not plan.objectives:
        problems.append(Problem("objectives", "an analysis must say what it "
                                              "is computing"))
    if plan.conversation_action == "CLARIFY" and not plan.clarification:
        problems.append(Problem("clarification", "a clarifying plan must say "
                                                 "what it asks"))
    return problems


def usable(plan: Plan) -> bool:
    return not validate(plan)


# ------------------------------------------------------------- assembling it

def from_run(*, reading: Any = None, coverage: Any = None,
             retrieved: list[str] | None = None,
             analytical_plan: dict[str, Any] | None = None,
             method: dict[str, Any] | None = None,
             invariants: list[str] | None = None,
             visualization: dict[str, Any] | None = None,
             clarification: dict[str, Any] | None = None,
             risk_flags: list[str] | None = None,
             confidence: dict[str, float] | None = None) -> Plan:
    """The document, assembled from what a run actually produced.

    §20's schema is what a planner is ASKED for; this is what the run can
    honestly say it had. They are the same shape on purpose — the Trace (§45)
    and the Calculation Pack (§46) show one document whether the model filled
    it or the deterministic reader did, and a user comparing two runs is
    comparing like with like.
    """
    plan = Plan(
        analytical_plan=dict(analytical_plan or {}),
        method=dict(method or {}),
        invariants=list(invariants or []),
        visualization=dict(visualization or {}),
        clarification=dict(clarification or {}),
        risk_flags=[f for f in (risk_flags or []) if f in RISK_FLAGS],
        confidence_components={k: float(v) for k, v in (confidence or {}
                                                        ).items()
                               if k in CONFIDENCE_COMPONENTS},
        teaching_case_ids_used=list(retrieved or []),
    )

    if reading is not None:
        plan.capability = str(getattr(reading, "intent", "") or "")
        plan.conversation_action = str(
            getattr(reading, "conversation_action", "") or "")
        plan.concepts = list(getattr(reading, "concepts", ()) or ())
        plan.metrics = list(getattr(reading, "metrics", ()) or ())
        plan.dimensions = list(getattr(reading, "dimensions", ()) or ())
        plan.filters = [dict(f) for f in (getattr(reading, "filters", ())
                                          or ())]
        plan.entities = [dict(e) for e in (getattr(reading, "entities", ())
                                           or ())]
        plan.grain = str(getattr(reading, "grain", "") or "")
        plan.domains = list(getattr(reading, "candidate_domains", ()) or ())
        plan.datasets = list(getattr(reading, "datasets", ()) or ())
        operation = str(getattr(reading, "operation", "") or "")
        plan.operations = [operation] if operation and operation != "none" \
            else []
        periods = list(getattr(reading, "periods", ()) or ())
        requirement = str(getattr(reading, "period_requirement", "") or "")
        if periods or requirement:
            plan.period = {"phrases": periods, "requirement": requirement}
        plan.prior_context_referents = {
            str(r): "" for r in (getattr(reading, "entity_references", ())
                                 or ())}

    if coverage is not None:
        found = list(getattr(coverage, "objectives", ()) or ())
        plan.objectives = [{"objective_id": o.objective_id,
                            "description": o.description,
                            "action": o.action,
                            "measure_phrase": o.measure_phrase,
                            "cohort_id": o.cohort_id} for o in found]
        plan.objective_coverage_plan = {o.objective_id: o.status
                                        for o in found}
        if any(o.status == ob.PLANNED for o in found) and found:
            plan.risk_flags = sorted(set(plan.risk_flags))

    return plan


def coverage_flag(coverage: Any) -> list[str]:
    """The risk flag an incomplete coverage raises, if any.

    Separate from `from_run` because it is a judgment about a finished run and
    `from_run` is used before execution too.
    """
    unsettled = list(getattr(coverage, "unsettled", ()) or ())
    return ["OBJECTIVE_UNCOVERED"] if unsettled else []


__all__ = ["CONFIDENCE_COMPONENTS", "CONTRACT_VERSION", "ENUMS", "FIELDS",
           "RISK_FLAGS", "SCHEMA", "STRUCTURED", "Plan", "Problem",
           "coverage_flag", "from_run", "read", "usable", "validate"]
