"""
Flow classes and their coverage targets. §21.

    §21: "Do not set one meaningless global target."

Why one number would be meaningless
-------------------------------------
"Assurance coverage is 78%" is a statement about nothing. A metadata question
has no result to reconcile and no invariants to check; a coordinated portfolio
review has agents, budgets and approvals that a metadata question does not.
Averaged together, the metadata questions — which are easy and numerous —
carry the number, and the coordinated reviews where coverage actually matters
disappear into it.

So coverage is measured per FLOW CLASS, and each class declares which
subcomponents are applicable to it. A subcomponent outside a flow's applicable
set is not counted against it, and a subcomponent INSIDE that set which has no
signal is `NOT_AVAILABLE` — which blocks if it is critical, rather than
quietly lowering an average.

How a flow is classified
-------------------------
Deterministically, from the record itself: the answer type, whether an
analysis executed, how many datasets were touched, whether an agentic run
exists, whether the turn came from a proactive event, and whether it was
Project-scoped. Never from the question's wording — a classifier that read
the prose would put "review the portfolio" and "review the portfolio's
spelling" in the same class.

The gate this phase must meet
-------------------------------
Per §21: 100% of applicable CRITICAL subcomponents instrumented, no critical
`NOT_AVAILABLE`, no mandatory `SKIPPED`, and at least 90% overall applicable
coverage. A flow that misses any of those stays `UNVERIFIED` with no score.
Thresholds are not lowered to pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.assurance import dimensions as dm

FLOWS_VERSION = "1.0.0"

# ------------------------------------------------------------- the classes

METADATA = "METADATA_DISCOVERY"
SIMPLE = "SIMPLE_ANALYSIS"
MULTI_DOMAIN = "MULTI_DOMAIN_ANALYSIS"
COORDINATED = "AGENTIC_COORDINATED_REVIEW"
PROACTIVE = "PROACTIVE_REVIEW"
PROJECT = "PROJECT_AGENTIC_FLOW"
#: Not one of §21's six. A turn that asked rather than answered, or declined,
#: has a genuinely different applicable set — and folding it into SIMPLE
#: would report every clarification as a simple analysis missing its result
#: checks, which is a false failure rather than a real gap.
CONVERSATIONAL = "CONVERSATIONAL_NO_ANALYSIS"

FLOWS: tuple[str, ...] = (METADATA, SIMPLE, MULTI_DOMAIN, COORDINATED,
                          PROACTIVE, PROJECT, CONVERSATIONAL)

LABELS: dict[str, str] = {
    METADATA: "Metadata / discovery",
    SIMPLE: "Simple analysis",
    MULTI_DOMAIN: "Multi-domain analysis",
    COORDINATED: "Agentic coordinated review",
    PROACTIVE: "Proactive review",
    PROJECT: "Project agentic flow",
    CONVERSATIONAL: "Conversational (no analysis ran)",
}

MEANS: dict[str, str] = {
    METADATA: "A question about what data exists, answered from the "
              "catalogue. No result to reconcile and no invariants to check.",
    SIMPLE: "One measure over one domain. Data, plan, result, invariants and "
            "grounding all apply.",
    MULTI_DOMAIN: "Two or more governed domains joined. Adds relationship, "
                  "grain, period and join reconciliation.",
    COORDINATED: "An orchestrated run with specialists. Adds officer, agent, "
                 "task, tool, budget and approval checks.",
    PROACTIVE: "An event-driven review. Adds idempotency, pre-screening, case "
               "deduplication and severity.",
    PROJECT: "A Project-scoped agentic run. Adds scope isolation, return "
             "context, workflow and approval.",
    CONVERSATIONAL: "A clarification, an unsupported answer or a controlled "
                    "failure. No analysis ran, so the result checks are not "
                    "applicable — established from the record, not assumed.",
}

# ------------------------------------------------- what applies to each flow

#: The checks every flow carries, whatever it did. These are about the turn
#: itself rather than about an analysis, so nothing exempts them.
_ALWAYS: frozenset[str] = frozenset({
    "capability_intent", "conversation_action", "objective_extraction",
    "language_locale_understanding",
    "trace_clarity", "direct_bottom_line", "limitations",
    "controlled_error_handling", "no_unexplained_500", "latency",
    "audit_completeness", "privacy_tenant_safety", "permission_enforcement",
    "scope_isolation", "feedback_capture",
    "stale_build_configuration_detection", "provider_model_availability",
    "token_cost_efficiency",
})

#: The analysis spine: everything from choosing data to proving the number.
_ANALYSIS: frozenset[str] = frozenset({
    "objective_coverage", "concept_selection", "method_blueprint_selection",
    "dataset_selection", "period_selection", "grain_selection",
    "population_definition", "filter_definition", "plan_completeness",
    "expected_output_visual_intent",
    "analytical_ir", "generated_query", "execution", "data_quality",
    "result_correctness", "business_invariants", "mathematical_invariants",
    "totals_reconciliation", "evidence_fact_graph", "entity_grounding",
    "figure_grounding", "period_unit_grounding",
    "materiality", "analyst_interpretation", "actionability",
    "association_versus_causation", "visualization_validity",
    "number_formatting", "table_column_ordering", "concision_no_repetition",
    "client_presentability", "follow_up_quality",
})

#: What a second governed domain adds.
_MULTI: frozenset[str] = frozenset({
    "relationship_join_path", "join_reconciliation",
    "row_customer_reconciliation", "cohort_construction",
    "drivers_contributions", "breadth_concentration",
})

#: What orchestration adds.
_AGENTIC: frozenset[str] = frozenset({
    "officer_level_selection", "agent_selection", "orchestration_plan",
    "delegation", "task_execution", "handoffs",
    "challenge_conflict_resolution", "assurance_agent_checks",
    "budget_loop_safety", "agentic_trace_consistency",
    "model_route_escalation", "task_dag",
})

#: What an event-driven review adds on top of orchestration.
_PROACTIVE: frozenset[str] = frozenset({
    "worker_queue_execution", "proactive_review", "attention_case_creation",
    "case_deduplication", "human_approval_gates", "workflow_action_safety",
})

#: What a Project adds. Scope isolation is already in _ALWAYS because it is
#: never optional; these are the Project-specific ones.
_PROJECT: frozenset[str] = frozenset({
    "navigation_back_continuity", "human_approval_gates",
    "workflow_action_safety", "context_carry_forward",
})

#: What a multi-turn conversation adds.
_CONVERSATION: frozenset[str] = frozenset({
    "same_turn_coreference", "multi_turn_context", "context_carry_forward",
    "new_topic_reset_detection", "entity_cohort_resolution",
})

APPLICABLE: dict[str, frozenset[str]] = {
    METADATA: _ALWAYS | {"dataset_selection", "concept_selection",
                         "data_quality", "ambiguity_detection"},
    CONVERSATIONAL: _ALWAYS | _CONVERSATION | {"ambiguity_detection",
                                               "clarification_quality"},
    SIMPLE: _ALWAYS | _ANALYSIS | _CONVERSATION,
    MULTI_DOMAIN: _ALWAYS | _ANALYSIS | _MULTI | _CONVERSATION,
    COORDINATED: (_ALWAYS | _ANALYSIS | _MULTI | _AGENTIC | _CONVERSATION
                  | {"exception_detection", "persistence_noise",
                     "contradictory_signal_diagnosis"}),
    PROACTIVE: (_ALWAYS | _ANALYSIS | _MULTI | _AGENTIC | _PROACTIVE
                | {"exception_detection", "persistence_noise"}),
    PROJECT: (_ALWAYS | _ANALYSIS | _AGENTIC | _PROJECT | _CONVERSATION),
}


def applicable(flow: str) -> frozenset[str]:
    """The subcomponents that apply to a flow.

    An unknown flow gets the widest set rather than the narrowest. Coverage
    should be harder to claim for something nobody classified, not easier.
    """
    known = APPLICABLE.get(flow)
    if known is not None:
        return known
    return frozenset().union(*APPLICABLE.values())


def critical_for(flow: str) -> frozenset[str]:
    return applicable(flow) & frozenset(dm.CRITICAL)


def mandatory_for(flow: str) -> frozenset[str]:
    return applicable(flow) & frozenset(dm.MANDATORY)


# ----------------------------------------------------------- classification


def classify(*, answer_type: str = "", executed: bool = False,
             datasets: int = 0, agentic_run: bool = False,
             specialists: int = 0, proactive: bool = False,
             project_id: str = "") -> str:
    """Which flow a turn belongs to, from the record rather than the prose.

    Order matters and is deliberate: proactive beats project beats
    coordinated beats multi-domain beats simple. A proactive review inside a
    Project is judged as a proactive review, because its idempotency and
    deduplication checks are the ones most likely to be the reason it went
    wrong.
    """
    if proactive:
        return PROACTIVE
    if not executed:
        # Nothing computed. Metadata answered from the catalogue is a real
        # answer; a clarification or a refusal is a different thing again.
        if answer_type in ("metadata", "discovery", "succeeded") and datasets:
            return METADATA
        return CONVERSATIONAL
    if project_id:
        return PROJECT
    if agentic_run and specialists >= 2:
        return COORDINATED
    if datasets >= 2:
        return MULTI_DOMAIN
    return SIMPLE


# ------------------------------------------------------------- the targets


@dataclass(frozen=True)
class Target:
    """§21's gate for one flow.

    `critical_pct` is 100 and not configurable downward. The other two are
    fields so a flow can be held to a HIGHER standard than the default, never
    a lower one — `Target.__post_init__` refuses a weaker gate outright,
    because "do not lower thresholds merely to pass" has to be enforced
    somewhere and a constant nobody can edit is the wrong place (a real flow
    may genuinely deserve more).
    """

    flow: str
    critical_pct: float = 100.0
    overall_pct: float = 90.0
    allow_critical_not_available: bool = False
    allow_mandatory_skipped: bool = False

    def __post_init__(self) -> None:
        if self.critical_pct < 100.0:
            raise ValueError(
                f"{self.flow}: applicable critical coverage must be 100%. "
                "§21 does not permit a lower critical gate.")
        if self.overall_pct < 90.0:
            raise ValueError(
                f"{self.flow}: overall applicable coverage must be at least "
                "90%. Do not lower thresholds merely to pass.")
        if self.allow_critical_not_available or self.allow_mandatory_skipped:
            raise ValueError(
                f"{self.flow}: a critical NOT_AVAILABLE or a mandatory "
                "SKIPPED blocks. Neither may be permitted per flow.")


TARGETS: dict[str, Target] = {flow: Target(flow=flow) for flow in FLOWS}


@dataclass
class FlowCoverage:
    """How one flow actually did, measured against its target."""

    flow: str
    instrumented: set[str] = field(default_factory=set)
    not_available: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    not_applicable: set[str] = field(default_factory=set)

    @property
    def target(self) -> Target:
        return TARGETS.get(self.flow, Target(flow=self.flow))

    @property
    def applicable_set(self) -> frozenset[str]:
        return applicable(self.flow) - self.not_applicable

    @property
    def critical_set(self) -> frozenset[str]:
        return critical_for(self.flow) - self.not_applicable

    @property
    def critical_instrumented(self) -> set[str]:
        return self.critical_set & self.instrumented

    @property
    def critical_missing(self) -> set[str]:
        return self.critical_set - self.instrumented

    @property
    def critical_pct(self) -> float:
        total = len(self.critical_set)
        return (len(self.critical_instrumented) / total * 100.0
                if total else 0.0)

    @property
    def overall_pct(self) -> float:
        total = len(self.applicable_set)
        return (len(self.applicable_set & self.instrumented) / total * 100.0
                if total else 0.0)

    @property
    def mandatory_skipped(self) -> set[str]:
        return mandatory_for(self.flow) & (self.skipped | self.not_available)

    @property
    def blocking(self) -> list[str]:
        """Every reason this flow may not be scored. §21's gate."""
        reasons: list[str] = []
        if self.critical_missing:
            reasons.append(
                f"{len(self.critical_missing)} applicable critical "
                f"subcomponent(s) are not instrumented: "
                f"{', '.join(sorted(self.critical_missing)[:5])}")
        blocked = self.critical_set & self.not_available
        if blocked:
            reasons.append(
                f"{len(blocked)} critical subcomponent(s) report "
                f"NOT_AVAILABLE: {', '.join(sorted(blocked)[:5])}")
        if self.mandatory_skipped:
            reasons.append(
                f"{len(self.mandatory_skipped)} mandatory subcomponent(s) did "
                f"not run: {', '.join(sorted(self.mandatory_skipped)[:5])}")
        if self.overall_pct < self.target.overall_pct:
            reasons.append(
                f"overall applicable coverage {self.overall_pct:.1f}% is "
                f"below the {self.target.overall_pct:.0f}% gate")
        return reasons

    @property
    def meets_gate(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow": self.flow,
            "label": LABELS.get(self.flow, self.flow),
            "means": MEANS.get(self.flow, ""),
            "applicable": len(self.applicable_set),
            "instrumented": len(self.applicable_set & self.instrumented),
            "overall_pct": round(self.overall_pct, 1),
            "overall_gate": self.target.overall_pct,
            "critical_applicable": len(self.critical_set),
            "critical_instrumented": len(self.critical_instrumented),
            "critical_pct": round(self.critical_pct, 1),
            "critical_gate": self.target.critical_pct,
            "critical_missing": sorted(self.critical_missing),
            "critical_not_available": sorted(self.critical_set
                                             & self.not_available),
            "mandatory_skipped": sorted(self.mandatory_skipped),
            "not_applicable": sorted(self.not_applicable),
            "meets_gate": self.meets_gate,
            "blocking": self.blocking,
        }
