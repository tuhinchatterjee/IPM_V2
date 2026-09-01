"""
The six broad Intelligence Dimensions. §178, §179, §201.

    "Use exactly six top-level dimensions."
    "Do not delete the detailed checks."

Why six replaces the flat wall
--------------------------------
Ninety-odd individual checks displayed as one list is a wall nobody reads.
Every reader — a CRO, a Model Risk reviewer, a product owner — arrives with a
different question, and the wall answers none of them because it does not say
what any check is FOR. Six dimensions each answer a question a person actually
has: did it understand me, did it design the right analysis, did it calculate
correctly, did it say something useful, did the agents do their job, was it
reliable.

And the detailed checks stay. §179 is explicit, and the reason is that the
dimension is where you notice a problem and the subcomponent is where you fix
it. A dimension score with nothing under it is a colour with an opinion.

The subcomponents are the real content
----------------------------------------
Ninety-five of them across the six, each mapping to a check that already
exists somewhere in this product. Listing them here rather than deriving them
means the grouping is reviewable: somebody can disagree that "period
selection" belongs in Analytical Design rather than Computation, which is a
conversation worth having and impossible to have with a computed grouping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DIMENSIONS_VERSION = "1.0.0"

# ------------------------------------------------------------ §178's six
UNDERSTANDING = "UNDERSTANDING_AND_CONTEXT"
DESIGN = "ANALYTICAL_DESIGN"
COMPUTATION = "COMPUTATION_AND_EVIDENCE"
JUDGMENT = "JUDGMENT_AND_PRESENTATION"
AGENTIC = "AGENTIC_DELIVERY"
RELIABILITY = "RELIABILITY_AND_EXPERIENCE"

DIMENSIONS: tuple[str, ...] = (UNDERSTANDING, DESIGN, COMPUTATION, JUDGMENT,
                               AGENTIC, RELIABILITY)

LABELS: dict[str, str] = {
    UNDERSTANDING: "Understanding & context",
    DESIGN: "Analytical design",
    COMPUTATION: "Computation & evidence",
    JUDGMENT: "Judgment & presentation",
    AGENTIC: "Agentic delivery",
    RELIABILITY: "Reliability & experience",
}

#: §187's "six compact dimension indicators". A two-letter code so a row can
#: carry all six without becoming a paragraph, and a fixed order so a reader's
#: eye learns the positions rather than re-reading the headers each row.
SHORT: dict[str, str] = {
    UNDERSTANDING: "UC",
    DESIGN: "AD",
    COMPUTATION: "CE",
    JUDGMENT: "JP",
    AGENTIC: "AG",
    RELIABILITY: "RX",
}

#: The question each dimension answers, in the words §178 uses. Shown at the
#: top of the dimension, because a score with no question above it is a
#: number somebody has to guess the meaning of.
ANSWERS: dict[str, str] = {
    UNDERSTANDING: "Did CreditProbe understand the user, the conversation and "
                   "the requested scope?",
    DESIGN: "Did CreditProbe design the right analysis?",
    COMPUTATION: "Did CreditProbe calculate correctly and build trustworthy "
                 "evidence?",
    JUDGMENT: "Did CreditProbe turn the result into a strong, clear and "
              "appropriate credit-risk answer?",
    AGENTIC: "Did the governed agentic system coordinate and complete the "
             "work safely?",
    RELIABILITY: "Was the experience operationally reliable, efficient and "
                 "usable?",
}

#: §182's recommended starting weights. Versioned and configurable, and
#: deliberately not equal: Computation & Evidence carries the most because a
#: wrong number is the failure that cannot be recovered from downstream.
WEIGHTS: dict[str, int] = {
    UNDERSTANDING: 15,
    DESIGN: 20,
    COMPUTATION: 25,
    JUDGMENT: 20,
    AGENTIC: 10,
    RELIABILITY: 10,
}

WEIGHTS_VERSION = "1.0.0"

# ------------------------------------------------------- §178's subcomponents
SUBCOMPONENTS: dict[str, tuple[str, ...]] = {
    UNDERSTANDING: (
        "capability_intent", "same_turn_coreference", "multi_turn_context",
        "conversation_action", "objective_extraction", "ambiguity_detection",
        "clarification_quality", "language_locale_understanding",
        "corporate_retail_scope", "entity_cohort_resolution",
        "context_carry_forward", "new_topic_reset_detection",
    ),
    DESIGN: (
        "objective_coverage", "concept_selection", "method_blueprint_selection",
        "dataset_selection", "relationship_join_path", "period_selection",
        "grain_selection", "population_definition", "filter_definition",
        "cohort_construction", "plan_completeness", "task_dag",
        "model_route_escalation", "teaching_case_retrieval",
        "expected_output_visual_intent",
    ),
    COMPUTATION: (
        "analytical_ir", "generated_query", "approved_kernel_use", "execution",
        "data_quality", "join_reconciliation", "row_customer_reconciliation",
        "result_correctness", "business_invariants",
        "mathematical_invariants", "totals_reconciliation",
        "evidence_fact_graph", "entity_grounding", "figure_grounding",
        "period_unit_grounding", "cached_result_integrity", "scope_isolation",
        "permission_enforcement",
    ),
    JUDGMENT: (
        "materiality", "drivers_contributions", "breadth_concentration",
        "persistence_noise", "exception_detection",
        "contradictory_signal_diagnosis", "association_versus_causation",
        "direct_bottom_line", "analyst_interpretation", "limitations",
        "actionability", "concision_no_repetition", "visualization_validity",
        "number_formatting", "table_column_ordering", "trace_clarity",
        "follow_up_quality", "client_presentability",
    ),
    AGENTIC: (
        "officer_level_selection", "agent_selection", "orchestration_plan",
        "delegation", "task_execution", "handoffs",
        "challenge_conflict_resolution", "assurance_agent_checks",
        "budget_loop_safety", "worker_queue_execution", "proactive_review",
        "attention_case_creation", "case_deduplication",
        "human_approval_gates", "workflow_action_safety",
        "agentic_trace_consistency",
    ),
    RELIABILITY: (
        "controlled_error_handling", "no_unexplained_500",
        "provider_model_availability", "worker_scheduler_health", "latency",
        "token_cost_efficiency", "timeout_retry_behaviour",
        "stale_build_configuration_detection", "navigation_back_continuity",
        "download_export_reliability", "ui_responsiveness", "accessibility",
        "localization_rtl_readiness", "feedback_capture",
        "audit_completeness", "privacy_tenant_safety",
    ),
}

#: Which subcomponents are MANDATORY and CRITICAL. §182's gate reads this:
#: a failure in any one of them makes the whole record FAILED whatever the
#: weighted score says, because each is a case where the answer asserts
#: something untrue rather than being clumsy.
CRITICAL: frozenset[str] = frozenset({
    "result_correctness", "business_invariants", "mathematical_invariants",
    "figure_grounding", "entity_grounding", "period_unit_grounding",
    "scope_isolation", "permission_enforcement", "join_reconciliation",
    "totals_reconciliation", "objective_coverage", "population_definition",
    "period_selection", "agentic_trace_consistency", "trace_clarity",
    "visualization_validity", "privacy_tenant_safety",
})

#: Subcomponents that must be present for a record to have enough coverage to
#: claim anything. §182's coverage gate.
MANDATORY: frozenset[str] = CRITICAL | frozenset({
    "capability_intent", "objective_extraction", "concept_selection",
    "dataset_selection", "generated_query", "execution",
    "direct_bottom_line", "limitations", "controlled_error_handling",
})


def dimension_of(subcomponent: str) -> str:
    """Which dimension a subcomponent belongs to, or "" if unknown.

    Returns "" rather than guessing. A subcomponent nobody placed is a check
    that will not be counted, and reporting that honestly is better than
    filing it under whichever dimension sorts first.
    """
    for dimension, names in SUBCOMPONENTS.items():
        if subcomponent in names:
            return dimension
    return ""


def all_subcomponents() -> tuple[str, ...]:
    return tuple(name for names in SUBCOMPONENTS.values() for name in names)


@dataclass
class Weights:
    """§182's weights, versioned so a score can say which policy produced it."""

    version: str = WEIGHTS_VERSION
    weights: dict[str, int] = field(
        default_factory=lambda: dict(WEIGHTS))

    def __post_init__(self) -> None:
        missing = [d for d in DIMENSIONS if d not in self.weights]
        if missing:
            raise ValueError(
                f"a weighting policy must weight every dimension; missing "
                f"{', '.join(missing)}")
        total = sum(self.weights.values())
        if total != 100:
            raise ValueError(
                f"the weights sum to {total}, not 100. A policy whose weights "
                "do not sum to 100 produces a score nobody can compare with "
                "another one.")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "weights": dict(self.weights)}


def catalogue() -> dict[str, Any]:
    """The whole structure, for the Studio and for a reviewer.

    Every dimension with its question, its weight and its subcomponents —
    so somebody can disagree that "period selection" belongs in Analytical
    Design rather than Computation, which is a conversation worth having and
    impossible to have with a computed grouping.
    """
    return {
        "version": DIMENSIONS_VERSION,
        "weights_version": WEIGHTS_VERSION,
        "dimensions": [
            {"id": d, "label": LABELS[d], "answers": ANSWERS[d],
             "weight": WEIGHTS[d],
             "subcomponents": [
                 {"id": s, "critical": s in CRITICAL,
                  "mandatory": s in MANDATORY}
                 for s in SUBCOMPONENTS[d]]}
            for d in DIMENSIONS],
        "subcomponent_count": len(all_subcomponents()),
        "critical_count": len(CRITICAL),
        "note": ("The detailed checks are not deleted. The dimension is where "
                 "you notice a problem; the subcomponent is where you fix "
                 "it."),
    }


__all__ = ["AGENTIC", "ANSWERS", "COMPUTATION", "CRITICAL", "DESIGN",
           "DIMENSIONS", "DIMENSIONS_VERSION", "JUDGMENT", "LABELS",
           "SHORT",
           "MANDATORY", "RELIABILITY", "SUBCOMPONENTS", "UNDERSTANDING",
           "WEIGHTS", "WEIGHTS_VERSION", "Weights", "all_subcomponents",
           "catalogue", "dimension_of"]
