"""
The executor — runs a validated plan and assembles one investigation.

What it does, in order:

    validate  ->  run each step through backend.engine.runner.run_analysis
              ->  stitch the step traces into one Analytical Reasoning Map
              ->  hand the structured results to the interpreter
              ->  persist the run, the plan and version 1 of the trace

Three things are worth being explicit about.

**Nothing here computes.** Every figure comes back from `run_analysis`, which is
the same entry point the API uses. The executor never touches a DataFrame.

**The map is emitted, not drawn.** Each step's trace was stamped by its own
execution. This module only prefixes the node ids so several steps can share one
canvas, and adds the interpretive nodes around them — the question, the reading
of it, the plan, and the narrative — so a reader can see exactly where judgement
stops and the engine starts.

**Unchanged steps are not re-run.** When a modification re-executes a plan, a
step whose analysis, parameters and filters are identical reuses its recorded
result and is marked as such on the map. That is what makes "exclude Real Estate"
take a second rather than a minute, and it is driven by the content hashes the
trace model already computes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.engine.runner import AnalysisRunResult, run_analysis
from backend.orchestration import multi
from backend.orchestration.clarification import needed_clarification
from backend.orchestration.comprehension import comprehend
from backend.orchestration.dynamic import DynamicRequest, build_plan, read_question
from backend.orchestration.interpreter import Finding, Metric, Narrative, build_narrative
from backend.orchestration.planner import DemoPlanner, planner_mode
from backend.orchestration.schema import AnalysisPlan, PlanRejected, PlanStep, Scope, StepRole
from backend.orchestration.validator import validate_plan
from backend.orchestration.vocabulary import get_vocabulary
from backend.trace.model import NodeStatus, NodeType, TraceGraph, TraceNode

logger = logging.getLogger(__name__)


# The stages shown to the user while an investigation runs. They are the real
# phases of this function, in the order they happen — not a decorative loader.
STAGES = [
    {"id": "understanding", "label": "Understanding the question"},
    {"id": "planning", "label": "Selecting CreditProbe analyses"},
    {"id": "retrieving", "label": "Retrieving governed data"},
    {"id": "running", "label": "Running the CreditProbe Engine"},
    {"id": "synthesising", "label": "Synthesising findings"},
]


def _resolved(analysis_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """A plan step's parameters with the contract's defaults filled in.

    An executed step records the *resolved* parameters, so a signature computed
    from the raw plan would never match one computed from a recorded step and
    nothing would ever be reused. Resolving both sides the same way is what makes
    "this step did not change" a fact rather than a coincidence.
    """
    from backend.engine.registry import get_registry

    try:
        return get_registry().contract(analysis_id).validate_params(params)
    except Exception:
        return dict(params)


@dataclass
class ExecutedStep:
    """One step of a plan, after it ran."""

    index: int
    analysis_id: str
    title: str
    rationale: str
    params: dict[str, Any]
    filters: dict[str, Any]
    period: str | None
    status: str
    certification: str
    analysis_version: str
    duration_ms: int
    result: dict[str, Any] | None
    error: str | None
    analysis_run_id: int | None = None
    trace: dict[str, Any] | None = None
    node_hashes: dict[str, str] = field(default_factory=dict)
    # True when this step reused a recorded result because nothing about it
    # changed. Displayed on the map, because "we did not re-run this" is a claim
    # a reviewer is entitled to see.
    reused: bool = False
    # PRIMARY when this step is the one that answers the question, SUPPORTING
    # when it is only there to help explain the primary result. Carried through
    # so the interface can lead with the answer instead of the longest table.
    role: str = "primary"

    @property
    def signature(self) -> str:
        """What makes this step's result valid. Two steps with the same
        signature must produce the same answer, so one can reuse the other."""
        import json

        return json.dumps(
            {"a": self.analysis_id, "p": self.params, "f": self.filters, "d": self.period},
            sort_keys=True, separators=(",", ":"), default=str,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "analysis_id": self.analysis_id,
            "title": self.title,
            "rationale": self.rationale,
            "params": self.params,
            "filters": self.filters,
            "period": self.period,
            "status": self.status,
            "certification": self.certification,
            "analysis_version": self.analysis_version,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
            "analysis_run_id": self.analysis_run_id,
            "trace": self.trace,
            "node_hashes": self.node_hashes,
            "reused": self.reused,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ExecutedStep:
        return cls(
            index=int(payload.get("index", 0)),
            analysis_id=str(payload.get("analysis_id", "")),
            title=str(payload.get("title", "")),
            rationale=str(payload.get("rationale", "")),
            params=dict(payload.get("params") or {}),
            filters=dict(payload.get("filters") or {}),
            period=payload.get("period"),
            status=str(payload.get("status", "succeeded")),
            certification=str(payload.get("certification", "")),
            analysis_version=str(payload.get("analysis_version", "")),
            duration_ms=int(payload.get("duration_ms") or 0),
            role=str(payload.get("role") or "primary"),
            result=payload.get("result"),
            error=payload.get("error"),
            analysis_run_id=payload.get("analysis_run_id"),
            trace=payload.get("trace"),
            node_hashes=dict(payload.get("node_hashes") or {}),
            reused=bool(payload.get("reused")),
        )


@dataclass
class Investigation:
    """One question, answered."""

    question: str
    plan: AnalysisPlan
    steps: list[ExecutedStep]
    narrative: Narrative
    graph: TraceGraph
    node_hashes: dict[str, str]
    duration_ms: int
    # succeeded | partial | failed | rejected | needs_clarification
    status: str = "succeeded"
    #: Set when CreditProbe stopped to ask rather than answering.
    clarification: Any = None
    analysis_run_id: int | None = None
    version: int = 1
    version_label: str = "Original"
    rejected: list[str] = field(default_factory=list)
    mode: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "plan": self.plan.to_dict(),
            "intent": self.plan.intent,
            "steps": [s.to_dict() for s in self.steps],
            "narrative": self.narrative.to_dict(),
            "follow_ups": self.plan.follow_ups,
            "notes": self.plan.notes,
            "unmatched": self.plan.unmatched,
            "trace": self.graph.to_dict(),
            "node_hashes": self.node_hashes,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "clarification": self.clarification.to_dict() if self.clarification else None,
            "analysis_run_id": self.analysis_run_id,
            "version": self.version,
            "version_label": self.version_label,
            "rejected": self.rejected,
            "mode": self.mode,
            "stages": STAGES,
        }


# ------------------------------------------------------------- the reasoning map


def _interpretive_node(node_id: str, node_type: NodeType, label: str,
                       config: dict[str, Any]) -> TraceNode:
    node = TraceNode(id=node_id, type=node_type, label=label, config=config)
    node.mark_started()
    node.mark_ok()
    return node


#: How each answer shape is drawn. One primary visual per answer — a question
#: gets the chart that fits its shape, never a gallery of every chart the data
#: could support.
_VISUALS: dict[str, dict[str, str]] = {
    "level": {"label": "Headline figures", "chart": "metrics",
              "why": "A position at a point in time reads as figures, not as a chart."},
    "movement": {"label": "Movement bridge", "chart": "waterfall",
                 "why": "A change between two periods is a bridge from opening to closing."},
    "ranking": {"label": "Ranked comparison", "chart": "bar",
                "why": "A ranking is read by length, so the bars are ordered and horizontal."},
    "distribution": {"label": "Composition", "chart": "stacked-bar",
                     "why": "A split of one total is read as parts of a whole."},
    "matrix": {"label": "Transition matrix", "chart": "matrix",
               "why": "A from/to grid is read as a matrix, shaded by concentration."},
    "trend": {"label": "Time series", "chart": "line",
              "why": "A path over many periods is read as a line."},
    "scenario": {"label": "Base against stressed", "chart": "comparison-bar",
                 "why": "A scenario is read by comparing two states of the same measure."},
    "list": {"label": "Ranked table", "chart": "table",
             "why": "Named exposures are read as a table, because the names matter."},
}


def build_reasoning_map(plan: AnalysisPlan, steps: list[ExecutedStep],
                        narrative: Narrative) -> TraceGraph:
    """Stitch the executed step traces into one graph.

    Layout is left to the client, which reads `layers()`. What matters here is
    that the shape is honest: the interpretive nodes (question, reading, plan,
    narrative) sit around the governed subgraphs, never inside them.
    """
    graph = TraceGraph()

    scope = plan.scope

    graph.add_node(_interpretive_node(
        "question", NodeType.USER_PROMPT, "Question asked",
        {"question": plan.question},
    ))
    graph.add_node(_interpretive_node(
        "intent", NodeType.LLM_INTENT, plan.intent or "Reading of the question",
        {
            # Which of the two interpretive moments this is. The question is read
            # BEFORE anything is computed; the findings are written AFTER. Both
            # are interpretation, but they are answerable to different things, so
            # the map names them separately.
            "stage": "question_interpretation",
            "stage_label": "Interpretation of the question",
            "intent": plan.intent,
            "planner": plan.planner,
            "model": plan.model_name,
            "unmatched": plan.unmatched,
            "notes": plan.notes,
            # How the question was read, field by field. This is the decision a
            # reviewer most often wants to challenge.
            "focus": scope.focus,
            "dimension": scope.dimension,
            "answer_shape": scope.output,
            "period_requirement": scope.period_requirement,
            "period_specified": scope.period_specified,
            "period": (
                f"{scope.from_period} to {scope.to_period}"
                if scope.from_period and scope.to_period else ""
            ),
            "period_source": scope.period_source,
            "filters": scope.filters,
            "rule": "This node contains no figures. It records what CreditProbe understood "
                    "the question to be asking, not what the answer is.",
        },
    ))
    graph.connect("question", "intent")

    graph.add_node(_interpretive_node(
        "plan", NodeType.PLAN,
        f"{len(steps)} CreditProbe {'analysis' if len(steps) == 1 else 'analyses'} selected",
        {"steps": [
            {"analysis_id": s.analysis_id, "title": s.title, "rationale": s.rationale,
             "params": s.params, "filters": s.filters}
            for s in steps
        ]},
    ))
    graph.connect("intent", "plan")

    leaves: list[str] = []
    for step in steps:
        prefix = f"s{step.index + 1}"
        step_graph = step.trace or {}
        id_map: dict[str, str] = {}

        for raw in step_graph.get("nodes") or []:
            original = str(raw.get("id"))
            new_id = f"{prefix}__{original}"
            id_map[original] = new_id
            node = TraceNode(
                id=new_id,
                type=NodeType(raw.get("type", "CALCULATION")),
                label=str(raw.get("label", "")),
                config=dict(raw.get("config") or {}),
                rows_in=raw.get("rows_in"),
                rows_out=raw.get("rows_out"),
                output_preview=raw.get("output_preview"),
                output_summary=dict(raw.get("output_summary") or {}),
                warnings=list(raw.get("warnings") or []),
                error=raw.get("error"),
                dataset=raw.get("dataset"),
                fields_used=list(raw.get("fields_used") or []),
                function_id=raw.get("function_id"),
                function_version=raw.get("function_version"),
                dataset_version=raw.get("dataset_version"),
            )
            node.duration_ms = raw.get("duration_ms")
            node.status = (
                NodeStatus.CACHED if step.reused
                else NodeStatus(raw.get("status", NodeStatus.OK.value))
            )
            # The step number is carried on the node so the canvas can group a
            # multi-step investigation into readable bands.
            node.config = {**node.config, "_step": step.index + 1,
                           "_step_title": step.title or step.analysis_id}
            graph.add_node(node)

        for edge in step_graph.get("edges") or []:
            source, target = id_map.get(str(edge.get("source"))), id_map.get(str(edge.get("target")))
            if source and target:
                graph.connect(source, target, edge.get("label"))

        roots = [id_map[n] for n in id_map if not any(
            e.get("target") == n for e in step_graph.get("edges") or []
        )]
        for root in roots:
            graph.connect("plan", root)

        step_leaves = [id_map[n] for n in id_map if not any(
            e.get("source") == n for e in step_graph.get("edges") or []
        )]
        leaves.extend(step_leaves or ([id_map[next(iter(id_map))]] if id_map else []))

    if not leaves:
        leaves = ["plan"]

    graph.add_node(_interpretive_node(
        "narrative", NodeType.LLM_EXPLANATION,
        "Findings written from the engine results",
        {
            "stage": "result_interpretation",
            "stage_label": "Interpretation of the result",
            # Calculated: quoted unchanged from a result node above.
            "direct_answer": narrative.direct_answer,
            "summary": narrative.summary,
            "finding_count": len(narrative.findings),
            # Interpreted: CreditProbe's reading of those figures.
            "interpretation": narrative.interpretation,
            "interpretation_points": list(narrative.interpretation_points),
            "rule": "Every figure quoted was returned by an engine analysis. "
                    "No figure on this node was calculated here, and no statement "
                    "here asserts a cause the engine did not establish.",
        },
    ))
    for leaf in leaves:
        graph.connect(leaf, "narrative")

    visual = _VISUALS.get(scope.output or "level", _VISUALS["level"])
    graph.add_node(_interpretive_node(
        "visual", NodeType.VISUALIZATION, visual["label"],
        {
            "answer_shape": scope.output,
            "chart": visual["chart"],
            "why": visual["why"],
            "rule": "The chart is chosen from the shape of the answer, not from the "
                    "figures in it.",
        },
    ))
    graph.connect("narrative", "visual")

    return graph


# ------------------------------------------------------------------ execution


def execute_plan(plan: AnalysisPlan, *, user_id: int | None = None,
                 previous: list[ExecutedStep] | None = None) -> list[ExecutedStep]:
    """Run every step, reusing any whose signature is unchanged.

    `previous` is the executed steps of the version being modified. A step whose
    analysis, parameters and filters are identical to one of them reuses that
    recorded result rather than recomputing it.
    """
    reusable = {step.signature: step for step in (previous or []) if step.status == "succeeded"}
    executed: list[ExecutedStep] = []

    for index, step in enumerate(plan.steps):
        candidate = ExecutedStep(
            index=index, analysis_id=step.analysis_id, title=step.title,
            rationale=step.rationale, params=_resolved(step.analysis_id, step.params),
            filters=dict(step.filters),
            period=step.period, status="pending", certification="", analysis_version="",
            duration_ms=0, result=None, error=None, role=str(step.role),
        )
        prior = reusable.get(candidate.signature)
        if prior is not None:
            executed.append(ExecutedStep(
                index=index, analysis_id=prior.analysis_id, title=step.title or prior.title,
                rationale=step.rationale or prior.rationale, params=prior.params,
                filters=prior.filters, period=prior.period, status=prior.status,
                certification=prior.certification, analysis_version=prior.analysis_version,
                duration_ms=prior.duration_ms, result=prior.result, error=prior.error,
                analysis_run_id=prior.analysis_run_id, trace=prior.trace,
                node_hashes=prior.node_hashes, reused=True, role=str(step.role),
            ))
            continue

        run: AnalysisRunResult = run_analysis(
            step.analysis_id,
            params=step.params,
            period=step.period,
            filters=step.filters,
            user_id=user_id,
        )
        payload = run.to_dict()
        executed.append(ExecutedStep(
            index=index,
            analysis_id=step.analysis_id,
            title=step.title,
            rationale=step.rationale,
            params=run.params,
            filters=dict(step.filters),
            period=step.period,
            status=run.status,
            certification=run.certification,
            analysis_version=run.analysis_version,
            duration_ms=run.duration_ms,
            result=payload.get("result"),
            error=run.error,
            trace=payload.get("trace"),
            node_hashes=run.node_hashes,
            role=str(step.role),
        ))
    return executed


def assemble(plan: AnalysisPlan, steps: list[ExecutedStep], *,
             duration_ms: int, mode: dict[str, Any] | None = None) -> Investigation:
    """Turn executed steps into a complete investigation."""
    narrative = build_narrative(plan.question, plan.intent,
                                [s.to_dict() for s in steps], plan=plan)
    graph = build_reasoning_map(plan, steps, narrative)
    hashes = graph.compute_hashes()
    failed = [s for s in steps if s.status != "succeeded"]
    status = "succeeded" if not failed else ("partial" if len(failed) < len(steps) else "failed")
    return Investigation(
        question=plan.question, plan=plan, steps=steps, narrative=narrative,
        graph=graph, node_hashes=hashes, duration_ms=duration_ms, status=status,
        mode=mode or planner_mode(),
    )



# ------------------------------------------------------ dynamic analysis


#: A question naming this many independent conditions is not answered by any one
#: certified analysis, however close an intent looks. Below it, the certified
#: library is preferred — a reviewed calculation beats a composed one whenever
#: both would answer the question.
DYNAMIC_CONDITION_THRESHOLD = 2


def dynamic_candidate(question: str, vocab: Any) -> DynamicRequest | None:
    """Whether this question should be composed rather than looked up.

    Returns the reading when the question is a multi-condition cohort question
    CreditProbe can compose, and None when it should go to the certified
    library. A reading that is not fully understood also returns None: the
    ordinary path's own refusal is better than a half-composed analysis.
    """
    try:
        request = read_question(question, periods=list(vocab.periods),
                               dimensions=dict(vocab.dimensions))
    except Exception as e:  # pragma: no cover - reading must never break a question
        logger.warning("Dynamic reading failed: %s", e)
        return None
    if not request.understood:
        return None
    if len(request.conditions) < DYNAMIC_CONDITION_THRESHOLD:
        return None
    return request


def _dynamic_plan(question: str, request: DynamicRequest) -> AnalysisPlan:
    """An AnalysisPlan describing the composition, for the map and the record.

    The step names `dynamic_analysis` rather than a registered id, and nothing
    downstream treats it as certified. What actually runs is the Analytical IR
    the request produced, through the same validator and compiler as everything
    else.
    """
    return AnalysisPlan(
        question=question,
        intent=request.summary,
        steps=[PlanStep(
            analysis_id="dynamic_analysis",
            title="Composed for this question",
            rationale=("No certified analysis answers this combination of "
                       "conditions, so CreditProbe composed one and ran it "
                       "through the governed runtime."),
            params={"grain": request.grain,
                    "opening_period": request.opening,
                    "closing_period": request.closing},
            filters={f: v for f, v in request.filters},
            role=StepRole.PRIMARY,
        )],
        scope=Scope(
            focus=f"{request.grain}s meeting every stated condition",
            output="ranking",
            period_requirement="period_over_period",
            period_specified=True,
            from_period=request.opening,
            to_period=request.closing,
            filters={f: v for f, v in request.filters},
            period_source="read from the question",
        ),
        planner="dynamic",
        follow_ups=[],
        notes=["This analysis was composed for this question. It is not a "
               "certified method and has not been reviewed."],
    )


def _dynamic_narrative(question: str, request: DynamicRequest,
                       result: Any) -> Narrative:
    """The answer, with the fact/reading boundary kept where it always is.

    Every figure here is `row_count` — a count of what the runtime returned. No
    figure is computed in this function, and the reading below asserts nothing
    the conditions did not already state.
    """
    grain = f"{request.grain}s" if result.row_count != 1 else request.grain
    where = ", ".join(v for _, v in request.filters)
    subject = f"{where} {grain}" if where else grain

    conditions = [c.describe() for c in request.conditions]
    findings = [Finding(
        text=(f"{result.row_count} {subject} meet every condition between "
              f"{request.opening} and {request.closing}."),
        tone="warning" if result.row_count else "neutral",
        evidence=[{"label": "Rows returned", "value": result.row_count}],
    )]

    return Narrative(
        direct_answer=(
            f"{result.row_count} {subject} meet all "
            f"{len(request.conditions)} conditions."),
        summary=f"{result.row_count} {subject} meet all "
                f"{len(request.conditions)} conditions.",
        findings=findings,
        interpretation=(
            "This analysis was composed for this question rather than selected "
            "from the certified library. The conditions applied were: "
            + "; ".join(conditions) + ". Read the analytical plan on the Trace "
            "before acting on the list — nobody has reviewed this calculation."),
        interpretation_points=[
            "Composed for this question, not a certified method.",
            f"Measured between {request.opening} and {request.closing}.",
            *conditions,
        ],
        metrics=[Metric(
            label=f"{request.grain.title()}s matching", value=result.row_count,
            unit="", direction="up-is-bad",
            hint="Every row satisfies every condition stated in the question.",
        )],
        caveats=(["The list was capped; narrow the question to see the rest."]
                 if result.truncated else []),
    )



def multi_candidate(question: str, vocab: Any) -> multi.MultiRequest | None:
    """Whether this question needs more than one governed dataset.

    Tried BEFORE the single-dataset reading, because a question mentioning ECL,
    a rating and exposure is not a facility-book question with extra words in
    it — answering it from the facility position alone would produce a correct
    figure about a narrower question, which is the failure this product exists
    to prevent.

    Returns None whenever the composed path should not run: one dataset is
    enough, the reading is incomplete, or nothing joins them. In every case the
    ordinary path's own refusal is better than a half-composed analysis.
    """
    from backend.data_access.catalog import get_catalog

    try:
        request = multi.read_question(
            question, catalogue=get_catalog(), periods=list(vocab.periods),
            dimensions=dict(vocab.dimensions),
            relationships=_active_relationships())
    except Exception as e:  # pragma: no cover - reading must never break a question
        logger.warning("Multi-dataset reading failed: %s", e)
        return None

    if not request.is_multi:
        return None
    if not request.understood:
        # Worth logging: a question that named several datasets and could not be
        # read is a gap in the reading, not a question nobody asked.
        logger.info("Multi-dataset question refused: %s", "; ".join(request.reasons))
        return None
    return request


def _active_relationships() -> list[dict[str, Any]]:
    """The governed relationship rows the planner may join on.

    Read through the service layer so there is one definition of "usable" —
    ACTIVE, confident enough, and not in an archived domain. Degrades to an
    empty graph rather than failing: with no relationships declared, a
    multi-dataset question is refused for want of a join, which is the honest
    outcome.
    """
    from backend.config import settings

    if not settings.has_database:
        return []
    try:
        from backend.db.engine import get_session
        from backend.services.relationships import active_relationships

        with get_session() as session:
            return active_relationships(session)
    except Exception as e:
        logger.warning("Could not read the relationship graph: %s", e)
        return []


def run_multi(question: str, request: multi.MultiRequest, *, started: float,
              user_id: int | None = None) -> Investigation:
    """Compose, validate, run and assemble one multi-dataset analysis."""
    from backend.data_access.catalog import get_catalog
    from backend.runtime.executor import ExecutionClass, execute

    build = multi.build_plan(request, catalogue=get_catalog())
    import dataclasses

    plan = dataclasses.replace(
        _dynamic_plan(question, _as_dynamic(request)),
        notes=["This analysis was composed for this question across "
               f"{len(request.datasets)} governed datasets, joined on the "
               "bank's own relationship model. It is not a certified method "
               "and has not been reviewed."])

    result = execute(build.plan, question=question, intent=request.summary,
                     certification=ExecutionClass.DYNAMIC)

    step = ExecutedStep(
        index=0, analysis_id="dynamic_analysis",
        title="Composed across several governed sources",
        rationale=(f"No certified analysis reads {', '.join(request.datasets)} "
                   "together, so CreditProbe composed one from the governed "
                   "relationship model."),
        params={"grain": request.grain, "shape": request.shape,
                "opening_period": request.opening,
                "closing_period": request.closing,
                "datasets": request.datasets},
        filters={f: v for f, v in request.filters},
        period=request.closing, status="succeeded",
        certification=ExecutionClass.DYNAMIC, analysis_version="",
        duration_ms=result.duration_ms,
        result={
            "values": {"matching": result.row_count,
                       "opening_period": request.opening,
                       "closing_period": request.closing},
            "units": {"matching": "count"},
            "input_row_count": result.row_count,
            "meta": {"execution": ExecutionClass.DYNAMIC,
                     "grain": request.grain, "shape": request.shape},
            "rows": result.rows,
            "columns": result.columns,
            "warnings": result.warnings,
            "chart": result.chart,
            "truncated": result.truncated,
            "certification": result.certification,
            "certification_label": result.certification_label,
            "reading": request.to_dict(),
            "plan": build.plan,
            "query": result.query.to_dict() if result.query else None,
            "joins": result.joins,
            "reconciliation": result.reconciliation,
            "fingerprint": result.fingerprint,
            "datasets": request.datasets,
            "explanation": multi.explain(request),
            "join_plan": (request.resolution.to_dict()
                          if request.resolution else None),
        },
        error=None,
        trace=result.graph.to_dict() if result.graph else None,
        node_hashes={}, role="primary",
    )

    narrative = _multi_narrative(question, request, result, build)
    graph = build_reasoning_map(plan, [step], narrative)
    investigation = Investigation(
        question=question, plan=plan, steps=[step], narrative=narrative,
        graph=graph, node_hashes=graph.compute_hashes(),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="succeeded",
        mode={**planner_mode(), "execution": ExecutionClass.DYNAMIC,
              "execution_label": ExecutionClass.LABELS[ExecutionClass.DYNAMIC],
              "datasets": request.datasets},
    )
    return investigation


def _as_dynamic(request: multi.MultiRequest) -> DynamicRequest:
    """A single-dataset-shaped view of the request, for the shared plan record.

    The AnalysisPlan and the reasoning map were built for the single-dataset
    path; rather than a second copy of both, the multi-dataset request is
    described in the same shape. Nothing downstream computes from this — it
    carries the reading, the periods and the filters onto the map.
    """
    shim = DynamicRequest(
        understood=True, dataset=request.base, grain=request.grain,
        key=request.key, opening=request.opening, closing=request.closing,
        filters=list(request.filters), summary=request.summary,
    )
    shim.conditions = [b.condition for b in request.bindings]
    return shim


def _multi_narrative(question: str, request: multi.MultiRequest, result: Any,
                     build: multi.PlanBuild) -> Narrative:
    """The answer, with the fact/reading boundary kept where it always is.

    Every figure here is a count of what came back or a figure the runtime
    returned. The reading states which governed sources were used and what the
    conditions were; it asserts no cause, and where the shape is an association
    it says co-movement in those words.
    """
    grain = multi._plural(request.grain) if result.row_count != 1 else request.grain
    where = ", ".join(v for _, v in request.filters)
    subject = f"{where} {grain}" if where else grain
    conditions = [b.condition.describe() for b in request.bindings]

    if request.shape == multi.ASSOCIATION and result.rows:
        row = result.rows[0]
        coefficient = row.get("coefficient")
        n = row.get("n")
        direct = (f"Across {n:,} {multi._plural(request.grain)}, the two "
                  f"measures moved together with a correlation of "
                  f"{coefficient:.3f}." if coefficient is not None else
                  "There were too few paired observations to measure an "
                  "association.")
        interpretation = (
            "This is co-movement, not cause. A correlation says the two "
            "measures moved together across the population; it does not "
            "establish that either one produced the other, and CreditProbe "
            "will not say that it does. The conditions read were: "
            + "; ".join(conditions) + ".")
        points = ["Composed across several governed sources, not a certified "
                  "method.",
                  "Co-movement across the population — not a causal claim.",
                  *conditions]
        metrics = [Metric(label="Correlation", value=coefficient, unit="",
                          direction="neutral",
                          hint="Between -1 and 1. Zero is no linear relationship.")]
        findings = [Finding(
            text=direct, tone="neutral",
            evidence=[{"label": "Observations", "value": n}])]
    else:
        direct = (f"{result.row_count} {subject} meet all "
                  f"{len(request.bindings)} conditions.")
        interpretation = (
            "This analysis was composed for this question across "
            + ", ".join(request.datasets)
            + ", joined on the bank's own governed relationships. The "
            "conditions applied were: " + "; ".join(conditions)
            + ". Read the join lineage on the Trace before acting on the list "
              "— nobody has reviewed this calculation.")
        points = [
            "Composed for this question, not a certified method.",
            f"Measured between {request.opening} and {request.closing}, "
            f"reported at {request.grain} level.",
            *conditions,
        ]
        metrics = [Metric(
            label=f"{request.grain.title()}s matching", value=result.row_count,
            unit="", direction="up-is-bad",
            hint="Every row satisfies every condition stated in the question.")]
        findings = [Finding(
            text=direct, tone="warning" if result.row_count else "neutral",
            evidence=[{"label": "Rows returned", "value": result.row_count}])]

    caveats = list(build.warnings)
    if result.reconciliation:
        first = result.reconciliation[0]
        last = result.reconciliation[-1]
        caveats.append(
            f"Population: {first['rows']:,} rows read, {last['rows']:,} in the "
            "final answer. The step-by-step reconciliation is on the Trace.")
    if result.truncated:
        caveats.append("The list was capped; narrow the question to see the rest.")

    return Narrative(
        direct_answer=direct, summary=direct, findings=findings,
        interpretation=interpretation, interpretation_points=points,
        metrics=metrics, caveats=caveats)


def run_dynamic(question: str, request: DynamicRequest, *,
                started: float, user_id: int | None = None) -> Investigation:
    """Compose, validate, run and assemble one dynamic analysis."""
    from backend.runtime.executor import ExecutionClass, execute

    plan = _dynamic_plan(question, request)
    ir = build_plan(request)

    result = execute(ir, question=question, intent=request.summary,
                     certification=ExecutionClass.DYNAMIC)

    step = ExecutedStep(
        index=0, analysis_id="dynamic_analysis",
        title="Composed for this question",
        rationale=plan.steps[0].rationale,
        params=dict(plan.steps[0].params), filters=dict(plan.steps[0].filters),
        period=request.closing, status="succeeded",
        certification=ExecutionClass.DYNAMIC, analysis_version="",
        duration_ms=result.duration_ms,
        result={
            "values": {"matching": result.row_count,
                       "opening_period": request.opening,
                       "closing_period": request.closing},
            # The full engine result shape, including the keys a composed
            # analysis has nothing to put in. Returning a partial shape makes
            # every consumer defensive, and the first one that is not breaks.
            "units": {"matching": "count"},
            "input_row_count": result.row_count,
            "meta": {"execution": ExecutionClass.DYNAMIC,
                     "grain": request.grain,
                     "dataset": request.dataset},
            "rows": result.rows,
            "columns": result.columns,
            "warnings": result.warnings,
            "chart": result.chart,
            "truncated": result.truncated,
            "certification": result.certification,
            "certification_label": result.certification_label,
            "reading": request.to_dict(),
            "plan": ir,
            "query": result.query.to_dict() if result.query else None,
        },
        error=None,
        trace=result.graph.to_dict() if result.graph else None,
        node_hashes={}, role="primary",
    )

    narrative = _dynamic_narrative(question, request, result)
    graph = build_reasoning_map(plan, [step], narrative)
    investigation = Investigation(
        question=question, plan=plan, steps=[step], narrative=narrative,
        graph=graph, node_hashes=graph.compute_hashes(),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="succeeded",
        mode={**planner_mode(), "execution": ExecutionClass.DYNAMIC,
              "execution_label": ExecutionClass.LABELS[ExecutionClass.DYNAMIC]},
    )
    return investigation


def run_investigation(question: str, *, user_id: int | None = None,
                      project_id: int | None = None,
                      investigation_id: int | None = None,
                      persist: bool = True,
                      period: tuple[str, str] | None = None,
                      extra_filters: dict[str, Any] | None = None) -> Investigation:
    """Answer one question end to end — or ask the one thing CreditProbe needs.

    Routing, in order:

      1. **Read the request.** A language model when one is configured, the
         deterministic semantic reader otherwise. It produces a structured
         reading: what kind of request, which governed concepts, which
         entities, how sure.
      2. **Route by capability.** Only ANALYSIS reaches the runtime. A question
         about the catalogue, a join, a field or a method is answered from
         governed metadata, and nothing computes.
      3. **Compose and run.** The reading becomes an Analytical IR, which is
         validated against the catalogue and executed as parameterised SQL.

    The legacy registry planner is reached only when the composition path
    fails — an emergency fallback, never the normal route, and the answer says
    so when it is used.
    """
    from backend.orchestration import assembly, orchestrator

    started = time.perf_counter()
    try:
        answered = orchestrator.answer(question, period=period,
                                       extra_filters=extra_filters)
        mode_now = orchestrator.mode()

        if answered.clarification:
            # Before asking, see whether a certified analysis already answers
            # this. "What deteriorated this period?" names no governed measure,
            # so the composer cannot read it — but the registry has an analysis
            # built for exactly that question, and asking the user to rephrase
            # something the product can already answer is worse service than
            # answering it and saying which route was taken.
            rescued = _registry_rescue(question, started, period=period,
                                       user_id=user_id)
            if rescued is not None:
                if persist:
                    persist_investigation(rescued, user_id=user_id,
                                          project_id=project_id,
                                          investigation_id=investigation_id)
                return rescued
            return _asking(question, answered, mode_now, started)

        if answered.result is not None:
            investigation = assembly.from_handler(
                question, answered.reading, answered.result,
                duration_ms=answered.duration_ms, mode=mode_now)
        else:
            investigation = assembly.from_analysis(
                question, answered.reading, answered.build, answered.runtime,
                duration_ms=answered.duration_ms, mode=mode_now)
            _check_grounding(investigation, answered.runtime)

        if persist:
            persist_investigation(investigation, user_id=user_id,
                                  project_id=project_id,
                                  investigation_id=investigation_id)
        return investigation
    except Exception as e:  # noqa: BLE001 - the fallback is the point
        logger.exception("The orchestrator failed on %r; falling back to the "
                         "registry planner.", question)
        fallback = _legacy_investigation(question, started, period=period,
                                          user_id=user_id, reason=str(e))
        if persist:
            persist_investigation(fallback, user_id=user_id,
                                  project_id=project_id,
                                  investigation_id=investigation_id)
        return fallback


def _about_a_period(clarification: str) -> bool:
    """Whether what is missing is the comparison window."""
    lowered = (clarification or "").lower()
    return ("over what period" in lowered or "which periods" in lowered
            or "span needs" in lowered)


#: How strongly the registry must recognise a question before it is allowed to
#: answer one the composer could not read.
#
#: Lower than it looks, because the registry is no longer what stands between a
#: question and a wrong answer. Capability routing is: a question about ratings
#: data or about a join never reaches this path at all, which is what stopped it
#: coming back as a Stage 2 distribution. What is left here is a question
#: already classified as an analysis whose measure the composer could not read,
#: and for those a labelled certified analysis beats a refusal.
_RESCUE_CONFIDENCE = 5


def _registry_rescue(question: str, started: float, *,
                     period: tuple[str, str] | None,
                     user_id: int | None) -> Investigation | None:
    """A certified analysis for a question the composer could not read.

    Returns None unless the registry recognises the question strongly and its
    plan validates. Emergency mode, and labelled as such on the answer.
    """
    try:
        vocab = get_vocabulary()
        plan = DemoPlanner().plan(question, vocab, period=period)
        if plan.unmatched or not plan.steps:
            return None
        if _registry_score(question) < _RESCUE_CONFIDENCE:
            return None
        if needed_clarification(plan, vocab) is not None:
            return None
        plan = validate_plan(plan, vocab)
        steps = execute_plan(plan, user_id=user_id)
        if not steps or any(s.status != "succeeded" for s in steps):
            return None
    except Exception as e:  # noqa: BLE001 - a failed rescue just means "ask"
        logger.info("No registry analysis rescued %r: %s", question, e)
        return None

    plan.notes.append(
        "CreditProbe could not compose an analysis for this question from the "
        "governed concepts, so it ran the certified analyses registered for it "
        "instead. Naming the figure you want will compose one directly.")
    investigation = assemble(
        plan, steps, duration_ms=int((time.perf_counter() - started) * 1000))
    investigation.mode = {**investigation.mode, "fallback": True,
                          "fallback_reason": "no governed measure was named"}
    return investigation


def _registry_score(question: str) -> int:
    """How strongly the registry's own patterns match this question."""
    import re

    from backend.orchestration.planner import INTENTS

    lowered = (question or "").lower()
    best = 0
    for intent in INTENTS:
        score = sum(weight for pattern, weight in intent.patterns
                    if re.search(pattern, lowered))
        best = max(best, score)
    return best


def _asking(question: str, answered: Any, mode_now: dict[str, Any],
            started: float) -> Investigation:
    """CreditProbe stopping to ask rather than answering.

    A clarification is a real outcome with its own Trace: the question, how far
    the reading got, and what is missing. It is not an error and it is not an
    empty analysis.
    """
    from backend.orchestration.schema import Clarification

    reading = answered.reading

    # The comprehension module already knows how to ask well: it detects a
    # borrower nobody has heard of, distinguishes "no measure named" from "no
    # intent at all", and offers options resolved to things the engine can
    # actually do. Re-deriving a worse version of that here would be a second
    # way of asking, and the two would drift.
    typed = None
    try:
        vocab = get_vocabulary()
        registry_plan = DemoPlanner().plan(question, vocab)
        understanding = comprehend(question, registry_plan, vocab)
        if understanding.should_ask:
            typed = understanding.clarification
        elif _about_a_period(answered.clarification):
            # A missing comparison window has resolved options — "last quarter",
            # "last 12 months" — and answering by clicking one is a click rather
            # than a re-typed sentence. The clarification module already builds
            # them, so the composer's plainer version is only used when it does
            # not apply.
            typed = needed_clarification(registry_plan, vocab)
    except Exception as e:  # noqa: BLE001 - a worse question is better than none
        logger.info("Could not type the clarification for %r: %s", question, e)
    scope = Scope(focus=reading.label, output="level",
                  period_requirement=reading.period_requirement,
                  period_specified=bool(reading.periods))
    plan = AnalysisPlan(
        question=question, intent=reading.objective or question, scope=scope,
        steps=[], planner=reading.source, model_name=reading.model or None,
        unmatched=True,
        notes=["CreditProbe stopped to ask rather than answering a question it "
               "had not fully read."],
    )
    narrative = build_narrative(question, plan.intent, [], plan=plan)
    graph = TraceGraph()
    graph.add_node(TraceNode(id="question", type=NodeType.USER_PROMPT,
                             label="Question asked",
                             config={"question": question}))
    node = graph.add_node(TraceNode(
        id="intent", type=NodeType.CAPABILITY,
        label=f"Read as: {reading.label}",
        config={"intent": reading.intent, "confidence": reading.confidence,
                "concepts": list(reading.concepts), "read_by": reading.source,
                "clarification": answered.clarification,
                "rule": "Nothing was computed: CreditProbe asked instead."}))
    node.mark_ok()
    graph.connect("question", "intent")
    graph.compute_hashes()

    asking = Investigation(
        question=question, plan=plan, steps=[], narrative=narrative,
        graph=graph, node_hashes=graph.compute_hashes(),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="needs_clarification",
        clarification=typed or Clarification(
            kind="reading", question=answered.clarification,
            detail=reading.objective,
            because=reading.reasoning or "The request was not fully read.",
            options=[], allow_custom=True),
        mode=mode_now,
    )
    return asking


def _check_grounding(investigation: Investigation, runtime: Any) -> None:
    """Refuse to ship prose containing a figure the result does not carry.

    Logged rather than raised: an ungrounded figure is a defect in how the
    narrative was assembled, and taking the whole answer away from the user
    because one sentence rounded badly would be worse than showing it. The
    test suite asserts this list is empty.
    """
    from backend.orchestration import assembly

    step = investigation.steps[0] if investigation.steps else None
    allowed = assembly.grounded_values(
        runtime, (step.result or {}).get("values") if step else None)
    for text in (investigation.narrative.direct_answer,
                 investigation.narrative.interpretation,
                 *[f.text for f in investigation.narrative.findings]):
        loose = assembly.ungrounded(text, allowed)
        if loose:
            logger.error("Ungrounded figure(s) %s in: %s", loose, text)
            investigation.narrative.caveats.append(
                "One figure in this reading could not be traced to the result "
                "and has been flagged for review.")
            return


def _legacy_investigation(question: str, started: float, *,
                          period: tuple[str, str] | None,
                          user_id: int | None, reason: str) -> Investigation:
    """The registry planner, as an emergency fallback only.

    This is the path the whole product used to take. It is kept because a
    composition that will not run is not a reason to return nothing, but the
    answer says plainly that it is a fallback — presenting it as the normal
    route is what made six questions in a row come back confidently wrong.
    """
    vocab = get_vocabulary()
    plan = DemoPlanner().plan(question, vocab, period=period)
    plan.notes.append(
        "CreditProbe could not compose an analysis for this question and fell "
        "back to its registered analyses. The answer may be narrower than what "
        "was asked.")

    reading = comprehend(question, plan, vocab)
    if reading.should_ask:
        narrative = build_narrative(question, plan.intent, [], plan=plan)
        asking = Investigation(
            question=question, plan=plan, steps=[], narrative=narrative,
            graph=build_reasoning_map(plan, [], narrative),
            node_hashes={}, duration_ms=int((time.perf_counter() - started) * 1000),
            status="needs_clarification", clarification=reading.clarification,
            mode={**planner_mode(), "fallback": True, "fallback_reason": reason},
        )
        asking.node_hashes = asking.graph.compute_hashes()
        return asking

    clarification = needed_clarification(plan, vocab)
    if clarification is not None:
        narrative = build_narrative(question, plan.intent, [], plan=plan)
        asking = Investigation(
            question=question, plan=plan, steps=[], narrative=narrative,
            graph=build_reasoning_map(plan, [], narrative),
            node_hashes={}, duration_ms=int((time.perf_counter() - started) * 1000),
            status="needs_clarification", clarification=clarification,
            mode={**planner_mode(), "fallback": True, "fallback_reason": reason},
        )
        asking.node_hashes = asking.graph.compute_hashes()
        return asking

    try:
        plan = validate_plan(plan, vocab)
    except PlanRejected as rejection:
        empty = Investigation(
            question=question, plan=plan, steps=[],
            narrative=build_narrative(question, plan.intent, [], plan=plan),
            graph=build_reasoning_map(plan, [],
                                      build_narrative(question, plan.intent, [], plan=plan)),
            node_hashes={}, duration_ms=int((time.perf_counter() - started) * 1000),
            status="rejected", rejected=rejection.reasons,
            mode={**planner_mode(), "fallback": True, "fallback_reason": reason},
        )
        empty.node_hashes = empty.graph.compute_hashes()
        return empty

    steps = execute_plan(plan, user_id=user_id)
    investigation = assemble(plan, steps,
                             duration_ms=int((time.perf_counter() - started) * 1000))
    investigation.mode = {**investigation.mode, "fallback": True,
                          "fallback_reason": reason}
    return investigation


# ---------------------------------------------------------------- persistence


def persist_investigation(investigation: Investigation, *, user_id: int | None = None,
                          project_id: int | None = None,
                          investigation_id: int | None = None) -> int | None:
    """Store the investigation and version 1 of its trace.

    Best-effort: a database problem must not lose an answer the user is already
    reading. The id is set on the investigation when it succeeds, which is what
    puts a working Trace button on the result.
    """
    from backend.config import settings

    if not settings.has_database:
        return None
    try:
        from backend.db.engine import get_session
        from backend.models.platform import AnalysisRun, TraceVersionRow

        with get_session() as session:
            record = AnalysisRun(
                project_id=project_id,
                investigation_id=investigation_id,
                user_id=user_id,
                question=investigation.question,
                intent={"intent": investigation.plan.intent,
                        "planner": investigation.plan.planner,
                        "unmatched": investigation.plan.unmatched,
                        "analysis_id": investigation.steps[0].analysis_id
                        if investigation.steps else None,
                        "source": "ask"},
                plan=investigation.plan.to_dict(),
                context={"period": "latest",
                         "filters": investigation.steps[0].filters
                         if investigation.steps else {}},
                status=investigation.status,
                rejection_reason="; ".join(investigation.rejected) or None,
                result={"steps": [s.to_dict() for s in investigation.steps]},
                narrative=investigation.narrative.summary,
                follow_ups=investigation.plan.follow_ups,
                function_versions={s.analysis_id: s.analysis_version
                                   for s in investigation.steps},
                model_provider=investigation.mode.get("planner"),
                model_name=investigation.mode.get("model_name"),
                duration_ms=investigation.duration_ms,
            )
            session.add(record)
            session.flush()

            session.add(TraceVersionRow(
                analysis_run_id=record.id,
                version_number=1,
                label="Original",
                graph=investigation.graph.to_dict(),
                node_hashes=investigation.node_hashes,
                result={"steps": [s.to_dict() for s in investigation.steps],
                        "narrative": investigation.narrative.to_dict(),
                        "plan": investigation.plan.to_dict()},
                created_by=user_id,
            ))
            session.flush()
            investigation.analysis_run_id = record.id
            return record.id
    except Exception as e:
        logger.warning("Could not persist investigation %r: %s", investigation.question, e)
        return None


__all__ = [
    "STAGES",
    "ExecutedStep",
    "Investigation",
    "PlanStep",
    "assemble",
    "build_reasoning_map",
    "execute_plan",
    "persist_investigation",
    "run_investigation",
]
