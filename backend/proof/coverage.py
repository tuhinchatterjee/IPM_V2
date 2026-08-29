"""
The Coverage Map. §19.

    §19: "Now wire actual signals into the collector."
    §19: "Do not mark missing signals PASS."

What a Coverage Map is for
----------------------------
Part F built ninety-five subcomponents and a collector that filled in the
handful the runtime happened to emit. That produced honest but low coverage,
and — more importantly — no way to tell WHY it was low. "Sixty-one checks did
not run" is not actionable; "sixty-one checks have no named source system"
is a work list.

So every subcomponent gets an entry naming, in §19's words: the source
system, the source field or event, when it is collected, what makes it
applicable, and what makes it PASS, FAIL, SKIPPED, NOT_APPLICABLE or
NOT_AVAILABLE. An entry with no `source` is `NOT_AVAILABLE` by construction —
which is the point. The map cannot flatter the product, because a
subcomponent nobody wired has nowhere to hide.

Why the map is data rather than code
--------------------------------------
Because it is checked against two things a comment cannot be checked against:
every subcomponent has exactly one entry (a test asserts the map and the
dimension catalogue agree), and every entry claiming to be instrumented is
one the collector actually emits (a second test runs the collector and
compares). A map that drifted from either would be a document about a
product that no longer exists.

The uncomfortable part, stated plainly
----------------------------------------
Many entries here are `PLANNED`. That is the truth about the product today,
and writing it down is what makes the next phase's work visible. The rule
that keeps it honest is that a `PLANNED` entry produces `NOT_AVAILABLE` at
runtime, and a critical `NOT_AVAILABLE` blocks. Nobody can improve the
coverage number by editing this file — only by wiring the signal and letting
the collector emit it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.assurance import dimensions as dm
from backend.assurance import record as rc

COVERAGE_VERSION = "1.0.0"

# ------------------------------------------------------------ the statuses

#: The signal is wired: the collector emits a judgement for this subcomponent.
WIRED = "WIRED"
#: The signal is identified and not yet wired. Produces NOT_AVAILABLE.
PLANNED = "PLANNED"
#: The subcomponent describes something outside what the backend can observe
#: — a browser behaviour, a person's action. Produces NOT_AVAILABLE in a
#: backend record rather than a false pass, and is covered elsewhere (a node
#: test, a browser script) where it is covered at all.
OUT_OF_BAND = "OUT_OF_BAND"

STATES: tuple[str, ...] = (WIRED, PLANNED, OUT_OF_BAND)


@dataclass(frozen=True)
class Entry:
    """§19's eleven fields for one subcomponent."""

    subcomponent: str
    state: str = PLANNED
    #: Which part of CreditProbe produces the evidence.
    source_system: str = ""
    #: The field, node or event on it.
    source_field: str = ""
    #: When it can be read.
    timing: str = ""
    #: When this check applies at all.
    applicability: str = ""
    passes_when: str = ""
    fails_when: str = ""
    skipped_when: str = ""
    not_applicable_when: str = ""
    #: Where a reader goes to see the evidence.
    evidence: str = ""
    owner: str = ""
    #: The test that proves the wiring.
    test: str = ""

    @property
    def dimension(self) -> str:
        return dm.dimension_of(self.subcomponent)

    @property
    def critical(self) -> bool:
        return self.subcomponent in dm.CRITICAL

    @property
    def mandatory(self) -> bool:
        return self.subcomponent in dm.MANDATORY

    @property
    def instrumented(self) -> bool:
        return self.state == WIRED

    @property
    def outcome_when_unwired(self) -> str:
        """What an unwired entry produces. Never PASS, never SKIPPED.

        SKIPPED would be a lie about a decision nobody made — it says
        execution chose not to run this check, when in fact no execution
        could.
        """
        return rc.NOT_AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "subcomponent": self.subcomponent,
            "dimension": self.dimension,
            "critical": self.critical,
            "mandatory": self.mandatory,
            "state": self.state,
            "source_system": self.source_system,
            "source_field": self.source_field,
            "timing": self.timing,
            "applicability": self.applicability,
            "passes_when": self.passes_when,
            "fails_when": self.fails_when,
            "skipped_when": self.skipped_when,
            "not_applicable_when": self.not_applicable_when,
            "evidence": self.evidence,
            "owner": self.owner,
            "test": self.test,
        }


def _e(name: str, **kwargs: Any) -> Entry:
    return Entry(subcomponent=name, **kwargs)


#: Shorthand for the common shape: a check read off the orchestration result
#: at the end of the turn, owned by the runtime team.
def _runtime(name: str, *, field_name: str, passes: str, fails: str,
             applicability: str = "Every turn.",
             system: str = "orchestration executor",
             timing: str = "after the answer is assembled, before the record "
                           "is sealed",
             skipped: str = "the signal is absent on this turn",
             not_applicable: str = "",
             evidence: str = "", test: str = "",
             state: str = WIRED) -> Entry:
    return Entry(
        subcomponent=name, state=state, source_system=system,
        source_field=field_name, timing=timing, applicability=applicability,
        passes_when=passes, fails_when=fails, skipped_when=skipped,
        not_applicable_when=not_applicable, evidence=evidence,
        owner="runtime", test=test)


# =========================================================== the map itself

_ENTRIES: tuple[Entry, ...] = (
    # ---------------------------------------- Understanding & context
    _runtime("capability_intent", field_name="reading.capability",
             passes="a capability was resolved before anything executed",
             fails="no capability could be resolved",
             evidence="Trace node `capability`",
             test="tests/proof/test_coverage_map.py"),
    _runtime("conversation_action", field_name="investigation.conversation.action",
             passes="the turn was classified into a conversation action",
             fails="no action was recorded",
             evidence="Trace node `conversation`"),
    _runtime("objective_extraction", field_name="reading.objectives",
             passes="at least one objective was extracted from the question",
             fails="the question produced no objective",
             evidence="Trace node `intent`"),
    _runtime("same_turn_coreference",
             field_name="investigation.conversation.same_turn_referents",
             passes="every same-turn referent resolved to a named entity",
             fails="a referent in this turn resolved to nothing",
             applicability="The question contains a same-turn referent.",
             not_applicable="the question contains no same-turn referent"),
    _runtime("multi_turn_context",
             field_name="investigation.conversation.inherited",
             passes="what was inherited from earlier turns is recorded",
             fails="context was used and not recorded",
             applicability="A second or later turn.",
             not_applicable="this is the first turn of the thread"),
    _runtime("context_carry_forward",
             field_name="investigation.conversation.carried",
             passes="the carried scope is recorded and matches the prior turn",
             fails="scope changed without a recorded reason",
             applicability="A second or later turn.",
             not_applicable="this is the first turn of the thread"),
    _runtime("new_topic_reset_detection",
             field_name="investigation.conversation.reset",
             passes="a topic change reset the inherited scope",
             fails="a new topic silently inherited the previous scope",
             applicability="A second or later turn.",
             not_applicable="this is the first turn of the thread"),
    _runtime("ambiguity_detection", field_name="investigation.status",
             passes="an ambiguous question produced a clarification",
             fails="an ambiguous question was answered by guessing",
             applicability="Always: the check is that a guess was NOT made."),
    _runtime("clarification_quality", field_name="investigation.clarification",
             passes="the clarification names the specific choice to be made",
             fails="the clarification is generic",
             applicability="The turn asked for clarification.",
             not_applicable="the turn did not ask for clarification"),
    _runtime("language_locale_understanding",
             field_name="investigation.conversation.language",
             passes="the language was resolved",
             fails="no language could be resolved"),
    _runtime("entity_cohort_resolution", field_name="reading.entities",
             passes="every named entity resolved to a governed identifier",
             fails="a named entity resolved to nothing",
             applicability="The question names an entity or cohort.",
             not_applicable="the question names no entity"),
    _e("corporate_retail_scope", state=PLANNED,
       source_system="semantic scope frame",
       source_field="scope.portfolio (corporate vs retail)",
       timing="at scope resolution",
       applicability="Requests where the corporate/retail split is meaningful.",
       passes_when="the resolved scope matches the requested portfolio",
       fails_when="a retail question was answered on corporate data",
       skipped_when="scope resolution did not run",
       not_applicable_when="the question is portfolio-agnostic",
       owner="semantics",
       evidence="Trace node `scope`"),

    # ---------------------------------------------- Analytical design
    _runtime("objective_coverage", field_name="answered.coverage",
             passes="every extracted objective was addressed",
             fails="an objective was not addressed",
             evidence="Trace node `objective_coverage`"),
    _runtime("concept_selection", field_name="build.measures",
             passes="every measure resolved to a governed concept",
             fails="a measure resolved to no concept",
             applicability="An analysis was planned.",
             not_applicable="no analysis was planned on this turn"),
    _runtime("dataset_selection", field_name="build.datasets",
             passes="every dataset is governed and authoritative for its "
                    "concept",
             fails="a non-authoritative dataset was selected",
             applicability="An analysis was planned.",
             not_applicable="no analysis was planned on this turn"),
    _runtime("period_selection", field_name="build.period",
             passes="the period matches what the question required",
             fails="the period does not match the requirement",
             applicability="An analysis was planned.",
             not_applicable="no analysis was planned on this turn"),
    _runtime("grain_selection", field_name="build.grain",
             passes="the output grain matches the question's subject",
             fails="the grain does not match",
             applicability="An analysis was planned.",
             not_applicable="no analysis was planned on this turn"),
    _runtime("population_definition", field_name="build.population",
             passes="the population is explicitly defined",
             fails="no population was defined",
             applicability="An analysis was planned.",
             not_applicable="no analysis was planned on this turn"),
    _runtime("filter_definition", field_name="build.filters",
             passes="every filter came from the question or a governed default",
             fails="a filter was invented",
             applicability="An analysis was planned.",
             not_applicable="no analysis was planned on this turn"),
    _runtime("plan_completeness", field_name="investigation.plan.steps",
             passes="the plan has at least one step and no unmatched clause",
             fails="the plan is empty or leaves a clause unmatched",
             applicability="An analysis was planned.",
             not_applicable="no analysis was planned on this turn"),
    _runtime("relationship_join_path", field_name="build.join_path",
             passes="the join path is a governed relationship",
             fails="the join is not a governed relationship",
             applicability="Two or more datasets were joined.",
             not_applicable="the analysis touched one dataset"),
    _runtime("method_blueprint_selection", field_name="build.method",
             passes="a governed method or blueprint was selected",
             fails="no method could be selected",
             applicability="An analysis was planned.",
             not_applicable="no analysis was planned on this turn"),
    _runtime("model_route_escalation", field_name="answered.decision",
             passes="the route matches the governed policy for this "
                    "complexity",
             fails="the route does not match the policy",
             evidence="Trace node `routing`"),
    _runtime("teaching_case_retrieval", field_name="answered.retrieved_cases",
             passes="every retrieved case is production-eligible",
             fails="a non-eligible case was retrieved",
             applicability="Retrieval ran.",
             not_applicable="no teaching pack was built for this turn"),
    _runtime("task_dag", field_name="outcome.plan",
             passes="the DAG terminated with every node in a terminal state",
             fails="a node never reached a terminal state",
             applicability="An orchestrated run.",
             not_applicable="no orchestration ran on this turn",
             system="agentic orchestrator"),
    _e("cohort_construction", state=PLANNED,
       source_system="analytical IR",
       source_field="ir.cohort definition",
       timing="at plan validation",
       applicability="The question defines a cohort.",
       passes_when="the cohort is defined by governed predicates only",
       fails_when="the cohort was constructed from ungoverned prose",
       skipped_when="cohort construction did not run",
       not_applicable_when="the question defines no cohort",
       owner="runtime"),
    _e("expected_output_visual_intent", state=WIRED,
       source_system="presentation contract",
       source_field="contract.visual_intent",
       timing="after the result shape is known",
       applicability="A result was returned.",
       passes_when="the requested output form was produced",
       fails_when="a chart was requested and a table was produced",
       skipped_when="no visual intent was expressed",
       not_applicable_when="the turn produced no result",
       owner="frontend/runtime"),

    # ------------------------------------------ Computation & evidence
    _runtime("analytical_ir", field_name="build.ir",
             passes="the IR validated against the governed metadata",
             fails="the IR failed validation",
             applicability="An analysis executed.",
             not_applicable="no analysis executed on this turn"),
    _runtime("generated_query", field_name="runtime.sql",
             passes="the query was compiled by the safe compiler and is "
                    "parameterised",
             fails="the query was not produced by the safe compiler",
             applicability="An analysis executed.",
             not_applicable="no analysis executed on this turn",
             evidence="Trace node `query`"),
    _runtime("approved_kernel_use", field_name="runtime.kernels",
             passes="every numerical step used an approved kernel",
             fails="a numerical step used an unapproved path",
             applicability="A numerical kernel ran.",
             not_applicable="no kernel ran on this turn"),
    _runtime("execution", field_name="answered.runtime",
             passes="the query executed and returned a result",
             fails="execution raised",
             applicability="An analysis executed.",
             not_applicable="no analysis executed on this turn"),
    _runtime("data_quality", field_name="runtime.quality",
             passes="no dataset read exceeded its governed null or drift "
                    "threshold",
             fails="a threshold was exceeded",
             applicability="An analysis executed.",
             not_applicable="no analysis executed on this turn"),
    _runtime("join_reconciliation", field_name="runtime.join_stats",
             passes="rows lost to the join are within the governed tolerance",
             fails="the join lost rows beyond tolerance",
             applicability="Two or more datasets were joined.",
             not_applicable="the analysis touched one dataset"),
    _runtime("row_customer_reconciliation", field_name="runtime.counts",
             passes="distinct subject counts reconcile before and after the "
                    "join",
             fails="the join amplified or dropped subjects",
             applicability="Two or more datasets were joined.",
             not_applicable="the analysis touched one dataset"),
    _runtime("result_correctness", field_name="answered.invariants",
             passes="the post-result invariants derived from the request held",
             fails="a post-result invariant did not hold",
             applicability="A result was returned.",
             not_applicable="no result was returned on this turn",
             evidence="Trace node `invariants`"),
    _runtime("business_invariants", field_name="answered.invariants.passed",
             passes="every business invariant held",
             fails="a business invariant did not hold",
             applicability="A result was returned.",
             not_applicable="no result was returned on this turn",
             evidence="Trace node `business_invariant`"),
    _runtime("mathematical_invariants", field_name="answered.invariants.maths",
             passes="components reconcile to totals within tolerance",
             fails="components do not reconcile",
             applicability="A result with components was returned.",
             not_applicable="the result has no decomposition"),
    _runtime("totals_reconciliation", field_name="answered.invariants",
             passes="the displayed total equals the sum of what is displayed",
             fails="the displayed total does not reconcile",
             applicability="A result with a total was returned.",
             not_applicable="the result has no total"),
    _runtime("evidence_fact_graph", field_name="judgment.facts",
             passes="at least one usable validated fact was registered",
             fails="no fact could be registered from the result",
             applicability="A result was returned.",
             not_applicable="no result was returned on this turn",
             evidence="Trace node `evidence`"),
    _runtime("entity_grounding", field_name="judgment.contract.entities",
             passes="every entity named in the prose exists in the result",
             fails="the prose named an entity the result does not contain",
             applicability="Prose was written.",
             not_applicable="no prose was written on this turn",
             evidence="Trace node `grounding`"),
    _runtime("figure_grounding", field_name="judgment.contract.grounded",
             passes="every figure in the prose traces to a validated fact",
             fails="a figure traces to no fact",
             applicability="Prose was written.",
             not_applicable="no prose was written on this turn",
             evidence="Trace node `grounding`"),
    _runtime("period_unit_grounding", field_name="judgment.contract.periods",
             passes="every period and unit in the prose matches the result",
             fails="a period or unit in the prose does not match",
             applicability="Prose was written.",
             not_applicable="no prose was written on this turn"),
    _runtime("cached_result_integrity", field_name="answered.cached",
             passes="the reused result's fingerprint matches the one recorded",
             fails="a reused result's fingerprint does not match",
             applicability="A previous result was reused.",
             not_applicable="no result was reused on this turn"),
    _runtime("scope_isolation", field_name="investigation.project_id",
             passes="every object read belongs to the requested scope",
             fails="an object outside the scope was read",
             system="orchestration executor + agentic scope"),
    _runtime("permission_enforcement", field_name="principal.role",
             passes="every read and write was permitted for the caller's role",
             fails="an operation exceeded the caller's role"),

    # ------------------------------------------ Judgment & presentation
    _runtime("materiality", field_name="judgment.rubric.materiality",
             passes="materiality came from the versioned policy",
             fails="a materiality claim was made with no policy behind it",
             applicability="A movement was described.",
             not_applicable="no movement was described"),
    _runtime("direct_bottom_line", field_name="judgment.rubric.direct",
             passes="the first sentence answers the question asked",
             fails="the first sentence does not answer the question"),
    _runtime("limitations", field_name="judgment.rubric.limitations",
             passes="material limitations are stated",
             fails="a known limitation was omitted"),
    _runtime("analyst_interpretation", field_name="judgment.contract",
             passes="the interpretation is bound to registered facts",
             fails="the interpretation asserts something unregistered",
             applicability="Prose was written.",
             not_applicable="no prose was written on this turn"),
    _runtime("number_formatting", field_name="judgment.rubric.formatting",
             passes="every figure follows the semantic format contract",
             fails="a figure is formatted against the contract",
             applicability="Figures were displayed.",
             not_applicable="no figures were displayed"),
    _runtime("concision_no_repetition", field_name="judgment.rubric.concise",
             passes="no statement is repeated",
             fails="the answer repeats itself"),
    _runtime("client_presentability", field_name="judgment.rubric.presentable",
             passes="the presentability rubric returned SHOW",
             fails="the rubric blocked or required a repair"),
    _runtime("visualization_validity", field_name="investigation.graph.visual",
             passes="the chosen chart is semantically valid for the result "
                    "shape",
             fails="the chart misrepresents the result",
             applicability="A chart was chosen.",
             not_applicable="no chart was chosen on this turn"),
    _runtime("trace_clarity", field_name="investigation.graph",
             passes="the Trace records every stage that ran",
             fails="a stage ran and left no Trace node"),
    _runtime("association_versus_causation",
             field_name="judgment.rubric.causal",
             passes="no causal claim was made from associational evidence",
             fails="a causal claim was made",
             applicability="Prose was written.",
             not_applicable="no prose was written on this turn"),
    _e("drivers_contributions", state=PLANNED,
       source_system="judgment drivers engine",
       source_field="drivers.decomposition",
       timing="after the result",
       applicability="A movement was decomposed.",
       passes_when="contributions reconcile to the total movement",
       fails_when="contributions do not reconcile",
       skipped_when="no decomposition ran",
       not_applicable_when="no movement was decomposed",
       owner="judgment"),
    _e("breadth_concentration", state=PLANNED,
       source_system="judgment breadth engine", source_field="breadth.verdict",
       timing="after the result", applicability="A distribution was described.",
       passes_when="the breadth claim came from the measure",
       fails_when="the breadth claim came from prose",
       skipped_when="the breadth engine did not run",
       not_applicable_when="no distribution was described", owner="judgment"),
    _e("persistence_noise", state=PLANNED,
       source_system="judgment persistence engine",
       source_field="persistence.verdict", timing="after the result",
       applicability="A trend was claimed.",
       passes_when="the required history was present and stated",
       fails_when="a trend was claimed on insufficient history",
       skipped_when="the persistence engine did not run",
       not_applicable_when="no trend was claimed", owner="judgment"),
    _e("exception_detection", state=PLANNED,
       source_system="judgment observations", source_field="observations",
       timing="after the result", applicability="A distribution was described.",
       passes_when="material exceptions were surfaced",
       fails_when="the largest exception was omitted",
       skipped_when="observation extraction did not run",
       not_applicable_when="the result has no exceptions", owner="judgment"),
    _e("contradictory_signal_diagnosis", state=PLANNED,
       source_system="judgment contradictions",
       source_field="contradictions.outcome", timing="after the result",
       applicability="Two signals disagreed.",
       passes_when="the disagreement was diagnosed or reported UNRESOLVED",
       fails_when="a disagreement was explained away",
       skipped_when="the contradiction engine did not run",
       not_applicable_when="no signals disagreed", owner="judgment"),
    _e("actionability", state=WIRED, source_system="judgment rubric",
       source_field="rubric.actionable", timing="after the prose",
       applicability="Prose was written.",
       passes_when="the answer names what to do or look at next",
       fails_when="the answer stops at a number",
       skipped_when="the rubric did not run",
       not_applicable_when="no prose was written", owner="judgment"),
    _e("table_column_ordering", state=WIRED,
       source_system="presentation contract", source_field="contract.columns",
       timing="after the result shape is known",
       applicability="A table was displayed.",
       passes_when="columns follow the governed order",
       fails_when="columns are in an arbitrary order",
       skipped_when="no contract was built",
       not_applicable_when="no table was displayed", owner="runtime"),
    _e("follow_up_quality", state=WIRED,
       source_system="suggestions service", source_field="suggestions",
       timing="after the answer",
       applicability="Suggestions were offered.",
       passes_when="every suggestion is answerable in the current scope",
       fails_when="a suggestion leaves the governed scope",
       skipped_when="no suggestions were offered",
       not_applicable_when="the turn offers no suggestions", owner="runtime"),

    # ------------------------------------------------- Agentic delivery
    _runtime("officer_level_selection", field_name="selection.level",
             passes="the selected officer matches the governed policy for the "
                    "recorded complexity and risk",
             fails="the officer does not match the policy",
             applicability="An agentic run exists.",
             not_applicable="no agentic run exists for this turn",
             system="agentic officers"),
    _runtime("agent_selection", field_name="outcome.plan.agents",
             passes="every selected specialist is justified by a concept in "
                    "the reading",
             fails="a specialist was selected with no concept behind it",
             applicability="An orchestrated run.",
             not_applicable="no orchestration ran on this turn",
             system="agentic registry"),
    _runtime("orchestration_plan", field_name="outcome.plan",
             passes="the plan is bounded and every task has an owner",
             fails="the plan is unbounded or a task has no owner",
             applicability="An orchestrated run.",
             not_applicable="no orchestration ran on this turn",
             system="agentic orchestrator"),
    _runtime("task_execution", field_name="outcome.plan.tasks",
             passes="every task reached a terminal state",
             fails="a task never terminated",
             applicability="An orchestrated run.",
             not_applicable="no orchestration ran on this turn",
             system="agentic orchestrator"),
    _runtime("challenge_conflict_resolution", field_name="outcome.conflicts",
             passes="every recorded conflict has a recorded resolution",
             fails="a conflict was left unresolved and unreported",
             applicability="An orchestrated run produced a conflict.",
             not_applicable="no conflict arose",
             system="agentic orchestrator"),
    _runtime("assurance_agent_checks", field_name="answered.assurance",
             passes="the assurance agent ran and recorded a verdict",
             fails="the assurance agent did not run on a coordinated review",
             applicability="A coordinated run.",
             not_applicable="the turn was not coordinated",
             system="agentic assurance"),
    _runtime("budget_loop_safety", field_name="outcome.budget",
             passes="the run stayed inside its task and call budget",
             fails="a budget was exceeded",
             applicability="An orchestrated run.",
             not_applicable="no orchestration ran on this turn",
             system="agentic orchestrator"),
    _runtime("agentic_trace_consistency", field_name="agentic.run_id",
             passes="the Agentic Trace lists exactly the tasks that ran",
             fails="the Agentic Trace disagrees with the task records",
             applicability="An agentic run exists.",
             not_applicable="no agentic run exists for this turn",
             system="agentic runs"),
    _e("delegation", state=PLANNED, source_system="agentic orchestrator",
       source_field="plan.delegations", timing="during orchestration",
       applicability="An orchestrated run with more than one specialist.",
       passes_when="each delegation names a registered agent and a bounded task",
       fails_when="a delegation names no agent or no bound",
       skipped_when="no delegation occurred",
       not_applicable_when="only one specialist ran", owner="agentic"),
    _e("handoffs", state=PLANNED, source_system="agentic orchestrator",
       source_field="plan.handoffs", timing="during orchestration",
       applicability="An orchestrated run with more than one specialist.",
       passes_when="every handoff carries structured findings, not prose",
       fails_when="a handoff passed unstructured text",
       skipped_when="no handoff occurred",
       not_applicable_when="only one specialist ran", owner="agentic"),
    _e("worker_queue_execution", state=PLANNED,
       source_system="agent worker + task queue",
       source_field="agent_jobs / agent_tasks", timing="during a queued run",
       applicability="A queued agentic run.",
       passes_when="every claimed task was completed or explicitly failed",
       fails_when="a task was claimed and abandoned",
       skipped_when="the run was synchronous",
       not_applicable_when="no queued run was involved", owner="agentic"),
    _e("proactive_review", state=PLANNED, source_system="agentic events",
       source_field="agent_runs.trigger", timing="on a review run",
       applicability="An event-driven review.",
       passes_when="the review ran deterministic pre-screening before any "
                   "model call",
       fails_when="a model was called over the whole book",
       skipped_when="no review ran",
       not_applicable_when="the turn was user-initiated", owner="agentic"),
    _e("attention_case_creation", state=PLANNED,
       source_system="risk cases", source_field="risk_cases",
       timing="after a review", applicability="A review produced signals.",
       passes_when="every created case carries validated evidence",
       fails_when="a case was created with no evidence",
       skipped_when="no cases were created",
       not_applicable_when="no review ran", owner="agentic"),
    _e("case_deduplication", state=PLANNED, source_system="risk cases",
       source_field="risk_cases.case_key", timing="at case creation",
       applicability="A review produced signals.",
       passes_when="a repeated signal updated a case rather than creating one",
       fails_when="an identical signal created a duplicate case",
       skipped_when="no cases were created",
       not_applicable_when="no review ran", owner="agentic"),
    _e("human_approval_gates", state=PLANNED,
       source_system="agent approvals", source_field="agent_approvals",
       timing="before any material action",
       applicability="A material action was proposed.",
       passes_when="every material action waited for a named approver",
       fails_when="a material action executed without approval",
       skipped_when="no material action was proposed",
       not_applicable_when="the turn proposed no action", owner="agentic"),
    _e("workflow_action_safety", state=PLANNED, source_system="workflow",
       source_field="workflow requests", timing="at action time",
       applicability="A workflow action was drafted.",
       passes_when="the action was drafted and not executed",
       fails_when="an action executed without a person",
       skipped_when="no workflow action was drafted",
       not_applicable_when="the turn drafted no action", owner="workflow"),

    # -------------------------------------- Reliability & experience
    _runtime("controlled_error_handling", field_name="investigation.status",
             passes="the turn ended in one of the four contracted outcomes",
             fails="the turn ended in an uncontracted state"),
    _runtime("no_unexplained_500", field_name="investigation.status",
             passes="no unexplained failure occurred",
             fails="the turn failed with no stated reason"),
    _runtime("latency", field_name="investigation.duration_ms",
             passes="the turn completed inside the configured target",
             fails="the turn exceeded the target",
             skipped="no duration was recorded"),
    _runtime("provider_model_availability", field_name="provider status",
             passes="the provider state was resolved before routing",
             fails="routing proceeded with an unknown provider state",
             system="llm telemetry"),
    _runtime("stale_build_configuration_detection",
             field_name="build_info + release ids",
             passes="the build and release the turn ran under were recorded",
             fails="the turn recorded no build or release",
             system="build info + releases"),
    _runtime("token_cost_efficiency", field_name="answered.calls",
             passes="the call count is within the configured envelope for the "
                    "route",
             fails="the call count exceeded the envelope",
             skipped="no calls were made on this turn"),
    _runtime("privacy_tenant_safety", field_name="principal.tenant",
             passes="every object read belongs to the caller's tenant",
             fails="an object from another tenant was read"),
    _runtime("audit_completeness", field_name="assurance record",
             passes="an assurance record was written for this turn",
             fails="no record was written"),
    _e("worker_scheduler_health", state=PLANNED,
       source_system="agent worker + scheduler",
       source_field="agent_workers.heartbeat, agent_schedules.next_run",
       timing="at the time of the run",
       applicability="A queued or scheduled agentic run.",
       passes_when="a worker heartbeat is current and the schedule is due or "
                   "idle as expected",
       fails_when="the worker is silent while work is queued",
       skipped_when="no queued or scheduled work was involved",
       not_applicable_when="the turn ran synchronously in the request",
       owner="agentic"),
    _e("timeout_retry_behaviour", state=PLANNED,
       source_system="llm provider + task queue",
       source_field="retry counters", timing="during execution",
       applicability="A call or task was retried.",
       passes_when="retries stayed within the configured limit and were "
                   "recorded",
       fails_when="retries exceeded the limit or went unrecorded",
       skipped_when="nothing was retried",
       not_applicable_when="no retryable operation ran", owner="runtime"),
    _e("feedback_capture", state=PLANNED, source_system="feedback service",
       source_field="feedback control availability", timing="at render",
       applicability="An answer was displayed.",
       passes_when="the answer carries a working GOOD/BAD control",
       fails_when="an answer was displayed with no feedback control",
       skipped_when="nothing was displayed",
       not_applicable_when="no answer was displayed", owner="frontend"),
    _e("navigation_back_continuity", state=OUT_OF_BAND,
       source_system="front end return-context", source_field="returnTo",
       timing="at navigation",
       applicability="The user navigated away and back.",
       passes_when="the exact prior position was restored",
       fails_when="the user landed at the top of the wrong screen",
       skipped_when="no navigation occurred",
       not_applicable_when="no navigation occurred",
       owner="frontend",
       test="frontend/src/lib/__tests__/return-context.test.ts"),
    _e("download_export_reliability", state=OUT_OF_BAND,
       source_system="exports service", source_field="export_records",
       timing="at export",
       applicability="An export was requested.",
       passes_when="the workbook was produced and reconciles to the result",
       fails_when="the workbook does not reconcile",
       skipped_when="no export was requested",
       not_applicable_when="no export was requested", owner="exports",
       test="tests/exports/"),
    _e("ui_responsiveness", state=OUT_OF_BAND, source_system="browser",
       source_field="viewport rendering", timing="at render",
       applicability="A screen was rendered.",
       passes_when="no horizontal overflow at the supported viewports",
       fails_when="content overflows",
       skipped_when="nothing was rendered",
       not_applicable_when="this is a backend-only turn", owner="frontend",
       test="scripts/browser_acceptance.py"),
    _e("accessibility", state=OUT_OF_BAND, source_system="browser",
       source_field="roles, labels, contrast", timing="at render",
       applicability="A screen was rendered.",
       passes_when="interactive elements carry roles and accessible names",
       fails_when="an interactive element has no accessible name",
       skipped_when="nothing was rendered",
       not_applicable_when="this is a backend-only turn", owner="frontend",
       test="scripts/browser_acceptance.py"),
    _e("localization_rtl_readiness", state=OUT_OF_BAND,
       source_system="front end", source_field="dir / locale",
       timing="at render", applicability="A screen was rendered.",
       passes_when="the layout mirrors correctly under RTL",
       fails_when="the layout breaks under RTL",
       skipped_when="nothing was rendered",
       not_applicable_when="this is a backend-only turn", owner="frontend"),
)

MAP: dict[str, Entry] = {e.subcomponent: e for e in _ENTRIES}


def entry(name: str) -> Entry | None:
    return MAP.get(name)


def unmapped() -> list[str]:
    """Subcomponents with no Coverage Map entry.

    A gap in the map itself, and the first thing a test asserts is empty:
    a subcomponent nobody described is one nobody owns.
    """
    return sorted(set(dm.all_subcomponents()) - set(MAP))


def orphans() -> list[str]:
    """Map entries naming a subcomponent that does not exist."""
    return sorted(set(MAP) - set(dm.all_subcomponents()))


def wired() -> set[str]:
    return {name for name, e in MAP.items() if e.instrumented}


def planned() -> set[str]:
    return {name for name, e in MAP.items() if e.state == PLANNED}


def out_of_band() -> set[str]:
    return {name for name, e in MAP.items() if e.state == OUT_OF_BAND}


def summary() -> dict[str, Any]:
    """The map, counted. What the Studio and the report both read."""
    by_dimension: dict[str, dict[str, Any]] = {}
    for dimension in dm.DIMENSIONS:
        names = set(dm.SUBCOMPONENTS[dimension])
        by_dimension[dimension] = {
            "dimension": dimension,
            "label": dm.LABELS[dimension],
            "subcomponents": len(names),
            "wired": len(names & wired()),
            "planned": len(names & planned()),
            "out_of_band": len(names & out_of_band()),
            "critical": len(names & set(dm.CRITICAL)),
            "critical_wired": len(names & set(dm.CRITICAL) & wired()),
        }
    total = len(dm.all_subcomponents())
    criticals = set(dm.CRITICAL)
    return {
        "version": COVERAGE_VERSION,
        "subcomponents": total,
        "mapped": len(MAP),
        "unmapped": unmapped(),
        "orphans": orphans(),
        "wired": len(wired()),
        "planned": len(planned()),
        "out_of_band": len(out_of_band()),
        "wired_pct": round(len(wired()) / total * 100.0, 1) if total else 0.0,
        "critical": len(criticals),
        "critical_wired": len(criticals & wired()),
        "critical_pct": (round(len(criticals & wired()) / len(criticals)
                               * 100.0, 1) if criticals else 0.0),
        "critical_gaps": sorted(criticals - wired()),
        "by_dimension": list(by_dimension.values()),
        "unwired_outcome": rc.NOT_AVAILABLE,
        "rule": ("A subcomponent with no wired signal reports NOT_AVAILABLE, "
                 "never PASS and never SKIPPED. Where it is critical, that "
                 "blocks. The coverage number cannot be improved by editing "
                 "this map — only by wiring the signal."),
    }


@dataclass
class Gap:
    """One thing to wire, with everything needed to wire it."""

    entry: Entry
    why_it_matters: str = ""
    blocking_flows: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {**self.entry.to_dict(),
                "why_it_matters": self.why_it_matters,
                "blocking_flows": list(self.blocking_flows)}


def work_list() -> list[dict[str, Any]]:
    """What is left to instrument, worst first.

    Critical gaps first because they block; then mandatory; then the rest.
    Out-of-band entries are excluded — they are not backend work, and a work
    list that mixed "wire the drivers engine" with "check contrast in a
    browser" would be ignored by both owners.
    """
    from backend.proof import flows as fl

    gaps: list[Gap] = []
    for name in sorted(planned()):
        found = MAP[name]
        blocking = [flow for flow in fl.FLOWS
                    if name in fl.critical_for(flow)]
        gaps.append(Gap(
            entry=found,
            why_it_matters=(
                "Critical: a flow that needs this cannot be scored until it "
                "is wired." if found.critical else
                "Mandatory: leaves the record in NEEDS_REVIEW."
                if found.mandatory else
                "Non-critical: costs coverage only."),
            blocking_flows=blocking))
    gaps.sort(key=lambda g: (not g.entry.critical, not g.entry.mandatory,
                             g.entry.subcomponent))
    return [g.to_dict() for g in gaps]
