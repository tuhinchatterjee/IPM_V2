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

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.engine.runner import AnalysisRunResult, run_analysis
from backend.orchestration import multi
from backend.orchestration.dynamic import DynamicRequest, build_plan, read_question
from backend.orchestration.interpreter import Finding, Metric, Narrative, build_narrative
from backend.orchestration.planner import planner_mode
from backend.orchestration.schema import AnalysisPlan, PlanStep, Scope, StepRole
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
    #: How this turn was read: the conversation action, what it inherited, what
    #: the governed semantic guardrail made of the live reading, and whether the
    #: live path was available. Rendered on the Trace.
    conversation: dict[str, Any] = field(default_factory=dict)

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
            "conversation": self.conversation,
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
    """The governed relationship rows the planner may join on."""
    from backend.orchestration.context import relationship_rows

    return relationship_rows()


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
                      extra_filters: dict[str, Any] | None = None,
                      state: Any = None) -> Investigation:
    """Answer one question end to end — for callers that do not track state."""
    return answer_investigation(
        question, user_id=user_id, project_id=project_id,
        investigation_id=investigation_id, persist=persist, period=period,
        extra_filters=extra_filters, state=state)[0]


def answer_investigation(question: str, *, user_id: int | None = None,
                         project_id: int | None = None,
                         investigation_id: int | None = None,
                         persist: bool = True,
                         period: tuple[str, str] | None = None,
                         extra_filters: dict[str, Any] | None = None,
                         state: Any = None,
                         memory: Any = None
                         ) -> tuple[Investigation, Any]:
    """Answer one question end to end, and report how it was answered.

    Routing, in order:

      1. **Read the request** — the live model against the governed catalogue
         and the conversation so far, checked by the governed semantic reader.
      2. **Route by capability.** Only ANALYSIS reaches the runtime. A question
         about the catalogue, a join, a field or a method is answered from
         governed metadata, and nothing computes.
      3. **Compose and run.** The reading becomes an Analytical IR, which is
         validated against the catalogue and executed as parameterised SQL.

    There are exactly four outcomes, and no fifth:

      * an answer;
      * a clarification;
      * "CreditProbe does not hold data about that";
      * a stated failure.

    **There is no fallback to a registered analysis.** The previous version of
    this function rescued an unreadable question by running whichever certified
    analysis best matched its wording, and wrapped a failed composition in the
    old registry planner. Both produced confident, correct-looking answers to
    questions nobody had asked — "show me the five largest Real Estate
    customers" came back as a sector concentration reading 100% of a book
    already filtered to Real Estate. Answering a different question is worse
    than answering none, so this function no longer can.
    """
    from backend.orchestration import assembly, orchestrator

    started = time.perf_counter()
    try:
        answered = orchestrator.answer(question, state=state, memory=memory,
                                       period=period,
                                       extra_filters=extra_filters)
    except Exception as e:  # noqa: BLE001 - stated, never substituted
        logger.exception("The orchestrator raised on %r", question)
        return (_stated_failure(question, str(e), started), None)

    mode_now = orchestrator.mode()

    if answered.certified is not None:
        certified = _run_certified(question, answered, mode_now, started,
                                   user_id=user_id)
        if certified is not None:
            _record_conversation(certified, answered)
            if persist:
                persist_investigation(certified, user_id=user_id,
                                      project_id=project_id,
                                      investigation_id=investigation_id)
            return certified, answered
        # The certified analysis could not run. Compose instead — never a
        # different certified analysis.
        logger.info("The certified route failed for %r; composing instead.",
                    question)
        answered = orchestrator.answer(question, state=state, memory=memory,
                                       period=period,
                                       extra_filters=extra_filters,
                                       use_certified=False)

    if answered.unsupported:
        investigation = _unsupported(question, answered, mode_now, started)
    elif answered.clarification:
        investigation = _asking(question, answered, mode_now, started)
    elif answered.failure:
        investigation = _controlled_failure(question, answered, mode_now, started)
    elif answered.result is not None and answered.assessment is not None:
        # A question about the result already on the table, answered from it.
        # Routed before the metadata assembly because that one stamps every
        # answer with "no analytical engine ran and no figure was computed",
        # and both halves of that are wrong here.
        investigation = assembly.from_reuse(
            question, answered.reading, answered.result,
            cached=answered.cached, found=answered.assessment,
            provenance=answered.provenance,
            duration_ms=answered.duration_ms, mode=mode_now)
        _record_reuse(investigation, answered)
    elif answered.result is not None and answered.provenance is not None:
        # "Show it as a graph" — the previous result, drawn differently.
        investigation = assembly.from_redraw(
            question, answered.reading, answered.result,
            cached=answered.cached, provenance=answered.provenance,
            duration_ms=answered.duration_ms, mode=mode_now)
        _record_reuse(investigation, answered)
    elif answered.result is not None:
        investigation = assembly.from_handler(
            question, answered.reading, answered.result,
            duration_ms=answered.duration_ms, mode=mode_now)
    else:
        investigation = assembly.from_analysis(
            question, answered.reading, answered.build, answered.runtime,
            duration_ms=answered.duration_ms, mode=mode_now)
        _apply_interpretation(investigation, answered)
        _check_stated_thresholds(investigation, answered)
        _record_invariants(investigation, answered)
        _check_grounding(investigation, answered.runtime)

    _record_conversation(investigation, answered)
    _settle_caveats(investigation)
    if persist:
        persist_investigation(investigation, user_id=user_id,
                              project_id=project_id,
                              investigation_id=investigation_id)
    return investigation, answered


def _typed_state(answered: Any) -> dict[str, Any]:
    """The conversation's typed state as one readable block, or nothing."""
    from backend.orchestration import memory as wm

    found = getattr(answered, "memory", None)
    if found is None:
        return {}
    try:
        return wm.typed_state(found, getattr(answered, "state", None),
                              getattr(answered, "scope", None))
    except Exception as e:  # noqa: BLE001 - a Trace block must not lose an answer
        logger.warning("The typed state could not be assembled: %s", e)
        return {}


def _settle_caveats(investigation: Investigation) -> None:
    """One note per thing worth noting, in the order they were raised.

    Caveats are appended from a dozen places — the planner's warnings, the
    scope delta, the interpretation, the spelling correction — and a plan that
    hops through one dataset for two measures records the same aggregation note
    once per hop. Three identical sentences under a table read as three
    problems, and the reader stops trusting all of them.

    Run last, on every path, so no future appender has to remember.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for caveat in (investigation.narrative.caveats or []):
        text = str(caveat).strip()
        if text and text not in seen:
            seen.add(text)
            kept.append(text)
    investigation.narrative.caveats = kept


def _run_certified(question: str, answered: Any, mode_now: dict[str, Any],
                   started: float, *, user_id: int | None) -> Investigation | None:
    """Run the bank's approved analysis for a methodology asked for by name.

    Returns None if it will not run, and the caller composes instead. It never
    reaches for a *different* certified analysis: the whole reason this route is
    safe is that it only ever runs the one the request actually named.
    """
    found = answered.certified
    plan = AnalysisPlan(
        question=question,
        intent=f"{found.name} — the bank's certified methodology.",
        scope=Scope(focus=found.name, output="table",
                    period_requirement=str(found.period_requirement),
                    period_specified=bool(answered.certified_params)),
        steps=[PlanStep(analysis_id=found.analysis_id, title=found.name,
                        rationale=found.because,
                        params=dict(answered.certified_params),
                        role=StepRole.PRIMARY)],
        planner=answered.reading.source,
        model_name=answered.reading.model or None,
        notes=[found.because,
               f"Selected because the request matched {found.matched}."],
    )
    try:
        steps = execute_plan(plan, user_id=user_id)
    except Exception as e:  # noqa: BLE001 - compose instead, never substitute
        logger.info("Certified analysis %s did not run: %s",
                    found.analysis_id, e)
        return None
    if not steps or any(s.status != "succeeded" for s in steps):
        return None

    # The window the certified analysis actually used, back onto the scope, so
    # the answer and the Trace say which periods were read. A contract's own
    # governed default is the bank's decision and is often not the composer's,
    # and leaving the scope empty would hide which one applied.
    resolved = dict(steps[0].params or {})
    context = (steps[0].result or {}).get("context") or {}
    plan = dataclasses.replace(plan, scope=dataclasses.replace(
        plan.scope,
        from_period=(resolved.get("from_period")
                     or context.get("from_period") or None),
        to_period=(resolved.get("to_period") or resolved.get("period")
                   or context.get("period") or None),
        period_source=("read from the request" if answered.certified_params
                       else "the certified analysis's own governed default"),
    ))

    investigation = assemble(
        plan, steps, duration_ms=int((time.perf_counter() - started) * 1000),
        mode=mode_now)
    answered.written = _interpret_certified(question, found, steps[0])
    _apply_interpretation(investigation, answered)
    return investigation


class _CertifiedResult:
    """The shape `interpretation.write` reads, over a certified step's result.

    A thin adapter rather than a change to the interpreter: the interpreter's
    contract is "you are given the result and never the data", and a registered
    analysis's result satisfies that contract in a different shape.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        payload = payload or {}
        self.rows = list(payload.get("rows") or [])
        self.columns = list(payload.get("columns") or [])
        self.values = dict(payload.get("values") or {})
        self.warnings = list(payload.get("warnings") or [])
        self.row_count = len(self.rows)
        self.reconciliation = payload.get("reconciliation")


def _interpret_certified(question: str, found: Any, step: ExecutedStep) -> Any:
    from backend.orchestration import interpretation

    return interpretation.write(
        question, f"{found.name}: {found.when_to_use or found.because}",
        _CertifiedResult(step.result or {}),
        plan_note=("This is the bank's CERTIFIED methodology, run as approved. "
                   "Do not describe it as a composed or dynamic analysis."))


def _record_conversation(investigation: Investigation, answered: Any) -> None:
    """Put how this turn was read onto the answer, for the Trace and the UI.

    Recorded on every turn, including the ones where everything agreed. A field
    that only appears when something went wrong teaches users that its presence
    is bad news, which makes the good news invisible.
    """
    investigation.conversation = {
        "action": answered.continuation.action,
        "certified": (answered.certified.to_dict()
                      if answered.certified is not None else None),
        "continuation": answered.continuation.to_dict(),
        "guardrail": answered.verdict.to_dict(),
        "reading": answered.reading.to_dict(),
        "model_calls": answered.calls,
        "degraded_reason": answered.degraded_reason,
        "interpretation": (answered.written.to_dict()
                           if answered.written is not None else None),
        "invariants": (answered.invariants.to_dict()
                       if getattr(answered, "invariants", None) is not None
                       else None),
        "routing": (answered.decision.to_dict()
                    if getattr(answered, "decision", None) is not None
                    else None),
        "scope": (answered.scope.to_dict()
                  if getattr(answered, "scope", None) is not None else None),
        "investigation": dict(getattr(answered, "investigation", {}) or {}),
        "compound": dict(getattr(answered, "compound", {}) or {}),
        "association": dict(getattr(answered, "association", {}) or {}),
        # Every typed slot the conversation carries, in one place. The state is
        # split between what the last TURN produced and what the last ANALYSIS
        # settled — right, and hard to see. This is the view of it.
        "memory": _typed_state(answered),
    }
    if answered.degraded_reason:
        investigation.narrative.caveats.append(
            "A provider key is configured but the live model could not be "
            "reached for this answer, so the request was read by CreditProbe's "
            "governed semantic reader. Every figure was still computed by the "
            "governed runtime.")
    if answered.verdict.rejected:
        investigation.narrative.caveats.append(
            "The live model's reading of this request was rejected by the "
            "governed semantic guardrail and CreditProbe used its own reading "
            "of the same question instead.")


def _apply_interpretation(investigation: Investigation, answered: Any) -> None:
    """Put the model's reading of the result into the narrative.

    Only when it survived grounding. A discarded interpretation leaves the
    deterministic narrative in place and says so, rather than leaving a gap the
    reader has to interpret.
    """
    written = answered.written
    if written is None:
        return
    if written.live:
        if written.headline:
            investigation.narrative.direct_answer = written.headline
        investigation.narrative.interpretation = written.interpretation
        if written.notable:
            investigation.narrative.interpretation_points = list(written.notable)
        investigation.narrative.caveats.extend(written.caveats)
    elif written.unavailable:
        investigation.narrative.caveats.append(written.unavailable)


def _check_stated_thresholds(investigation: Investigation,
                             answered: Any) -> None:
    """Test the question's own thresholds against what the answer SAYS.

    The row checks pass and the sentence contradicts them. That happened: a
    screen for covenant headroom below 15% returned rows that all satisfied it,
    and the prose above the table named a borrower at 16.17%. Every figure was
    real, every row was correct, and the answer contradicted its own heading —
    the single most damaging thing this product can produce, because the
    sentence is what a credit officer quotes into a paper.

    Where the offending text is the model's interpretation, the interpretation
    is discarded and the deterministic reading stands. Where it is the direct
    answer or a finding — CreditProbe's own arithmetic — the answer is not
    shown at all. A contradictory headline is not something to annotate.
    """
    from backend.orchestration import invariants as inv

    report = getattr(answered, "invariants", None)
    narrative = investigation.narrative
    if report is None or not report.checks or narrative is None:
        return

    step = investigation.steps[0] if investigation.steps else None
    columns = ((step.result or {}).get("columns") or []) if step else []
    labels = {str(c.get("name")): str(c.get("label") or "") for c in columns}
    units = {str(c.get("name")): str(c.get("unit") or "") for c in columns}

    def failing(texts: list[str]) -> list[Any]:
        return inv.check_prose([c for c in report.checks if c.claim],
                               [t for t in texts if t],
                               labels=labels, units=units)

    written = failing([narrative.interpretation,
                       *(narrative.interpretation_points or [])])
    if written:
        logger.error("Discarding an interpretation that contradicts the "
                     "question's threshold: %s", written[0].detail)
        narrative.interpretation = ""
        narrative.interpretation_points = []
        narrative.caveats.append(
            "CreditProbe withheld the written interpretation of this result: "
            + written[0].detail
            + " The figures below are unaffected — they were computed by the "
              "governed runtime and every row satisfies the threshold.")

    computed = failing([narrative.direct_answer,
                        *[f.text for f in (narrative.findings or [])]])
    if computed:
        logger.error("Blocking an answer that contradicts its own heading: %s",
                     computed[0].detail)
        investigation.status = "failed"
        investigation.rejected.append(
            "CreditProbe computed an answer and then found that what it said "
            "about the result contradicted the question. "
            + computed[0].detail
            + " Rather than show a heading its own rows disprove, CreditProbe "
              "has stopped.")


def _unsupported(question: str, answered: Any, mode_now: dict[str, Any],
                 started: float) -> Investigation:
    """CreditProbe saying it does not hold data about this, and stopping.

    Deliberately not a clarification. A clarification offers a menu, and a menu
    offered to somebody asking about CEO resignations invites them to accept an
    answer about exposure instead — which is the substitution this whole layer
    exists to prevent. There is no menu here, because no choice on it would make
    the question answerable.
    """
    reading = answered.reading
    coverage = dict(answered.coverage or {})

    plan = AnalysisPlan(
        question=question, intent=reading.objective or question,
        scope=Scope(focus=reading.label, output="level"),
        steps=[], planner=reading.source, model_name=reading.model or None,
        unmatched=True,
        notes=["No analysis was composed and no figure was computed: the "
               "governed data holds nothing about what was asked."],
    )
    narrative = build_narrative(question, plan.intent, [], plan=plan)
    narrative.direct_answer = answered.unsupported
    narrative.interpretation = ""
    narrative.caveats = []

    graph = TraceGraph()
    graph.add_node(TraceNode(id="question", type=NodeType.USER_PROMPT,
                             label="Question asked",
                             config={"question": question}))
    node = graph.add_node(TraceNode(
        id="coverage", type=NodeType.CAPABILITY,
        label="Outside the governed data",
        config={"subject": coverage.get("subject", ""),
                "recognised": coverage.get("known_terms", []),
                "not_recognised": coverage.get("unknown_terms", []),
                "read_by": reading.source,
                "rule": ("CreditProbe answers only from published, "
                         "authoritative datasets. Nothing was substituted.")}))
    node.mark_ok()
    graph.connect("question", "coverage")
    graph.compute_hashes()

    return Investigation(
        question=question, plan=plan, steps=[], narrative=narrative,
        graph=graph, node_hashes=graph.compute_hashes(),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="unsupported", mode=mode_now,
    )


def _asking(question: str, answered: Any, mode_now: dict[str, Any],
            started: float) -> Investigation:
    """CreditProbe stopping to ask rather than answering.

    A clarification is a real outcome with its own Trace: the question, how far
    the reading got, and what is missing. It is not an error and it is not an
    empty analysis.

    What it is NOT, any more, is an invitation to pick from the engine's list of
    registered analyses. That menu was written when the engine could only answer
    twenty-four questions; offering it now describes a product that no longer
    exists, and it sent users away from the question they actually had.
    """
    from backend.orchestration.schema import Clarification

    reading = answered.reading
    typed = (_ambiguity_clarification(answered)
             or _period_clarification(question, answered)
             or _reading_clarification(question, answered))

    scope = Scope(focus=reading.label, output="level",
                  period_requirement=reading.period_requirement,
                  period_specified=bool(reading.periods))
    plan = AnalysisPlan(
        question=question, intent=reading.objective or question, scope=scope,
        steps=[], planner=reading.source, model_name=reading.model or None,
        unmatched=True,
        notes=["CreditProbe stopped to ask rather than answering a question it "
               "had not fully read. No analysis was run and no figure was "
               "computed."],
    )
    narrative = build_narrative(question, plan.intent, [], plan=plan)
    # Nothing ran, so the default "the analyses ran but returned no figures"
    # is not merely unhelpful, it is untrue — and it sends a user looking for a
    # data problem when the product is waiting for an answer from them.
    narrative.direct_answer = str(
        (typed.question if typed else "") or answered.clarification
        or "CreditProbe needs one more thing before it can answer that.")
    narrative.summary = narrative.direct_answer
    narrative.interpretation = ""

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
                "conversation_action": answered.continuation.action,
                "rule": "Nothing was computed: CreditProbe asked instead."}))
    node.mark_ok()
    graph.connect("question", "intent")
    graph.compute_hashes()

    return Investigation(
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


#: What a clarification offers when the thing that is missing is the figure.
#:
#: Built from governed CONCEPTS rather than from the analysis registry. The old
#: refusal offered a menu of the twenty-four analyses the engine had been given,
#: under the sentence "I can only answer with analyses the engine has
#: registered" — which stopped being true when the composer was built, and which
#: sent people away from the question they actually had. Every option below is a
#: question the composer can genuinely answer, generated from the catalogue, so
#: the list cannot drift out of date either.
#: `(concept id, option label, question)`. The concept is named rather than
#: taken positionally, because pairing "the largest exposures" with whichever
#: concept happened to be third in the catalogue produced offers that read as
#: nonsense to anybody who knows the vocabulary.
_OFFER_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    ("ead", "{label} by sector", "What is total {label} by sector in {period}?"),
    ("ead", "The largest exposures",
     "Show me the ten largest customers by {label}."),
    ("ecl", "How {label} moved", "How has {label} changed over the latest year?"),
)


def _ambiguity_clarification(answered: Any) -> Any:
    """One word, several governed figures — asked with the figures on offer.

    Distinct from the generic "which figure?" menu, which lists what the
    composer *can* answer. This lists what the user's own word could have
    meant, so answering is picking a definition rather than rephrasing a
    question that was perfectly clear apart from one term.
    """
    from backend.orchestration.schema import Clarification

    found = dict(getattr(answered, "ambiguity", None) or {})
    options = found.get("options") or []
    if not options:
        return None

    return Clarification(
        kind="ambiguity",
        question=str(found.get("question") or ""),
        detail=str(found.get("definition") or ""),
        because=(f"'{found.get('business_name') or found.get('concept')}' is "
                 f"governed as {len(options)} different measures, and they are "
                 "materially different amounts."),
        options=[{"label": o.get("label", ""),
                  "field": o.get("field", ""),
                  "detail": o.get("note", ""),
                  "question": _restated(answered.question, o.get("label", ""))}
                 for o in options],
        allow_custom=True,
    )


def _restated(question: str, label: str) -> str:
    """The user's own question with the ambiguous word replaced by a choice.

    So the option is a question that can be asked rather than a value that has
    to be posted back through a different endpoint.
    """
    import re as _re

    if not label:
        return question
    swapped = _re.sub(r"(?i)\bexposures?\b", label.lower(), question, count=1)
    if swapped != question:
        return swapped
    return f"{question.rstrip('.?! ')} — using {label.lower()}."


def _reading_clarification(question: str, answered: Any) -> Any:
    """"Which figure?" — with figures the composer can actually compose.

    Returns None rather than an empty menu when the catalogue cannot be read: a
    clarification with nothing to click is still a better answer than a
    confident number about something else, which is what this replaced.
    """
    from backend.orchestration.schema import Clarification

    try:
        from backend.orchestration import concepts as cx
        from backend.orchestration.vocabulary import get_vocabulary

        vocab = get_vocabulary()
        period = vocab.periods[-1] if vocab.periods else "the latest quarter"
        by_id = {c.id: c.label for c in cx.CONCEPTS}
        spare = [c.label for c in cx.CONCEPTS
                 if not c.is_categorical and not c.is_ordinal]
    except Exception as e:  # noqa: BLE001
        logger.info("Could not offer governed concepts for %r: %s", question, e)
        return None
    if not by_id:
        return None

    options = []
    for index, (concept_id, option_label, template) in enumerate(_OFFER_TEMPLATES):
        label = by_id.get(concept_id) or (spare[index] if index < len(spare) else "")
        if not label:
            continue
        options.append({
            "id": f"concept-{index}",
            "label": option_label.format(label=label),
            "question": template.format(label=label, period=period)})
    options.append({"id": "catalogue", "label": "What data is available",
                    "question": "What data do you have?"})

    return Clarification(
        kind="reading",
        question=answered.clarification or "Which figure should CreditProbe measure?",
        detail=("CreditProbe composes an analysis from the governed concepts in "
                "the catalogue. Name the figure you want and it will build it — "
                "or start from one of these."),
        options=options,
        because=(answered.reading.reasoning
                 or "The request did not name a governed measure."),
        allow_custom=True,
    )


def _period_clarification(question: str, answered: Any) -> Any:
    """The one clarification that still has clickable options: a period.

    A comparison window has real alternatives — last quarter, the latest year —
    and answering by clicking one is a click rather than a re-typed sentence.
    Every other clarification is a sentence, because the thing that is missing
    is a figure or a name and a menu cannot offer those.
    """
    lowered = (answered.clarification or "").lower()
    if not any(phrase in lowered for phrase in
               ("what period", "which periods", "span needs",
                "nothing to compare")):
        return None
    try:
        from backend.orchestration.periods import comparison_choices
        from backend.orchestration.schema import Clarification
        from backend.orchestration.vocabulary import get_vocabulary

        choices = comparison_choices(list(get_vocabulary().periods))
        if not choices:
            return None
        return Clarification(
            kind="period",
            question="Over what period should CreditProbe measure this?",
            detail=answered.clarification,
            options=[{"id": c.id, "label": c.label, "detail": c.detail,
                      "from_period": c.from_period, "to_period": c.to_period}
                     for c in choices],
            because="The book is reported quarterly, so the window changes the "
                    "answer.",
            allow_custom=True,
        )
    except Exception as e:  # noqa: BLE001 - a plainer question is still a question
        logger.info("Could not offer period options for %r: %s", question, e)
        return None


def _controlled_failure(question: str, answered: Any,
                        mode_now: dict[str, Any],
                        started: float) -> Investigation:
    """CreditProbe saying it could not do this, and stopping.

    The important word is *stopping*. This is the branch that used to run the
    registry planner, and the whole value of the change is that a user who sees
    this message knows they have not been given an answer — rather than being
    given a real, certified, reconciled figure for a question they did not ask.
    """
    reading = answered.reading
    scope = Scope(focus=reading.label, output="level",
                  period_requirement=reading.period_requirement,
                  period_specified=bool(reading.periods))
    plan = AnalysisPlan(
        question=question, intent=reading.objective or question, scope=scope,
        steps=[], planner=reading.source, model_name=reading.model or None,
        unmatched=True,
        notes=["CreditProbe could not complete this request and has not "
               "substituted a different analysis."],
    )
    narrative = Narrative(
        direct_answer="CreditProbe could not complete that request.",
        summary=answered.failure,
        findings=[], interpretation="", interpretation_points=[],
        caveats=[answered.failure],
    )
    graph = TraceGraph()
    graph.add_node(TraceNode(id="question", type=NodeType.USER_PROMPT,
                             label="Question asked",
                             config={"question": question}))
    node = graph.add_node(TraceNode(
        id="failure", type=NodeType.CAPABILITY,
        label="Could not complete",
        config={"intent": reading.intent, "kind": answered.failure_kind,
                "detail": answered.failure,
                "rule": "No substitute analysis was run."}))
    node.mark_failed(answered.failure)
    graph.connect("question", "failure")
    graph.compute_hashes()

    return Investigation(
        question=question, plan=plan, steps=[], narrative=narrative,
        graph=graph, node_hashes=graph.compute_hashes(),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="failed", rejected=[answered.failure], mode=mode_now,
    )


def _stated_failure(question: str, reason: str,
                    started: float) -> Investigation:
    """The last resort: something threw where nothing should have.

    Still not a fallback analysis. An unexpected exception means CreditProbe
    does not know what happened, and the one thing it must not do when it does
    not know what happened is produce a number.
    """
    logger.error("Unhandled failure answering %r: %s", question, reason)
    scope = Scope(focus="Could not complete", output="level",
                  period_requirement="none", period_specified=False)
    plan = AnalysisPlan(
        question=question, intent=question, scope=scope, steps=[],
        planner="none", unmatched=True,
        notes=["CreditProbe could not complete this request and has not "
               "substituted a different analysis."],
    )
    detail = ("CreditProbe could not complete that request. "
              f"The orchestration failed: {reason}")
    graph = TraceGraph()
    graph.add_node(TraceNode(id="question", type=NodeType.USER_PROMPT,
                             label="Question asked",
                             config={"question": question}))
    node = graph.add_node(TraceNode(id="failure", type=NodeType.CAPABILITY,
                                    label="Could not complete",
                                    config={"detail": detail}))
    node.mark_failed(reason)
    graph.connect("question", "failure")
    graph.compute_hashes()
    return Investigation(
        question=question, plan=plan, steps=[],
        narrative=Narrative(
            direct_answer="CreditProbe could not complete that request.",
            summary=detail, findings=[], interpretation="",
            interpretation_points=[], caveats=[detail]),
        graph=graph, node_hashes=graph.compute_hashes(),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="failed", rejected=[detail],
    )


def _record_corrections(investigation: Investigation, answered: Any) -> None:
    """Say so when the question answered is not quite the question typed.

    A silent correction is a good answer to a question the user did not ask.
    Shown as a caveat rather than buried on the Trace, because the one person
    who can tell whether `Estste` meant `estate` is the person who typed it.
    """
    changes = list(getattr(answered, "corrections", None) or [])
    if not changes:
        return
    pairs = ", ".join(f"\u2018{was}\u2019 as \u2018{now}\u2019"
                      for was, now in changes)
    investigation.narrative.caveats.append(
        f"CreditProbe read {pairs}. Rephrase if that is not what you meant.")


def _record_invariants(investigation: Investigation, answered: Any) -> None:
    """Put what was checked on the Trace, whether or not anything failed.

    Recorded on every answer, including the ones where everything held. A node
    that only appears when something went wrong teaches users that its presence
    is bad news, which makes its absence invisible — and the absence is the
    thing they would need to notice.
    """
    _record_routing(investigation, answered)
    _record_scope(investigation, answered)
    _record_evidence(investigation, answered)
    _record_corrections(investigation, answered)

    report = getattr(answered, "invariants", None)
    if report is None or not report.checks:
        return

    graph = investigation.graph
    if graph is None:
        return
    try:
        node = graph.add_node(TraceNode(
            id="invariants", type=NodeType.BUSINESS_INVARIANT,
            label=(f"{len(report.checks) - len(report.failures)} of "
                   f"{len(report.checks)} checks held"),
            config={
                "checked": [c.claim for c in report.checks],
                "failed": [f.to_dict() for f in report.failures],
                "skipped": list(report.skipped),
                "rule": ("Every promise the question made is tested against "
                         "the rows themselves. A failure blocks the answer "
                         "rather than annotating it."),
            }))
        if report.ok:
            node.mark_ok()
        else:
            node.mark_failed(report.sentence())
        for leaf in ("result", "run__result"):
            if leaf in graph.nodes:
                graph.connect(leaf, "invariants")
                break
        investigation.node_hashes = graph.compute_hashes()
    except Exception as e:  # noqa: BLE001 - a Trace node must not lose an answer
        logger.warning("Could not record the invariant node: %s", e)


def _record_evidence(investigation: Investigation, answered: Any) -> None:
    """The boundary the written interpretation had to stay inside.

    On the Trace whether the prose was kept or discarded. A reader asking
    "could it have said that?" is answered by the package rather than by
    trusting that something checked.
    """
    written = getattr(answered, "written", None)
    graph = investigation.graph
    if written is None or graph is None or "interpretation" not in graph.nodes:
        return
    package = dict(getattr(written, "evidence", {}) or {})
    grounding = dict(getattr(written, "grounding", {}) or {})
    if not package and not grounding:
        return
    try:
        node = graph.add_node(TraceNode(
            id="evidence", type=NodeType.RECONCILIATION,
            label=(f"{package.get('fact_count', 0)} facts the answer could "
                   "quote" if package else "Interpretation withheld"),
            config={
                "package": package,
                "grounding": grounding,
                "rule": ("The written interpretation may assert only what "
                         "this result establishes. Prose that asserts more is "
                         "discarded rather than annotated."),
            }))
        if grounding:
            node.mark_failed("; ".join(grounding.get("problems") or []))
        else:
            node.mark_ok()
        graph.connect("interpretation", "evidence")
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not record the evidence node: %s", e)


def _record_reuse(investigation: Investigation, answered: Any) -> None:
    """The reuse facts onto the investigation, where the API can read them.

    Duplicated deliberately onto `mode` as well as onto the step: the answer
    surface reads `mode`, the audit reads the step, and a claim this specific
    should be visible from both without either having to know about the other.
    """
    provenance = getattr(answered, "provenance", None)
    if provenance is None:
        return
    investigation.mode.update({
        "reused_result": True,
        "data_rescan": False,
        "derived_from_run_id": provenance.derived_from_run_id,
        "derived_from_result_fingerprint":
            provenance.derived_from_result_fingerprint,
        "reuse": provenance.to_dict(),
    })


def _record_scope(investigation: Investigation, answered: Any) -> None:
    """The active scope on the answer and on the Trace.

    The line goes on the narrative, not just into a payload nobody opens.
    "5 customers carried from the previous answer · Q2 2026 · exposure at
    default" above a table is what stops somebody reading a five-name figure
    as a portfolio one.
    """
    delta = getattr(answered, "scope", None)
    if delta is None:
        return

    line = delta.after.line()
    if line:
        investigation.narrative.scope = line
    if delta.widening_note:
        investigation.narrative.caveats.append(delta.widening_note)

    graph = investigation.graph
    if graph is None or "intent" not in graph.nodes:
        return
    try:
        node = graph.add_node(TraceNode(
            id="scope", type=NodeType.PRIOR_CONTEXT,
            label=f"Scope — {delta.kind.replace('_', ' ').lower()}",
            config={
                **delta.to_dict(),
                "rule": ("Every figure below covers exactly this population, "
                         "period and set of filters."),
            }))
        node.mark_ok()
        graph.connect("intent", "scope")
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not record the scope node: %s", e)


def _record_routing(investigation: Investigation, answered: Any) -> None:
    """Which route and model answered this turn, on the Trace.

    Recorded even when the route was "no model at all" — especially then. A
    user asking why an answer is trustworthy is best served by seeing that the
    catalogue answered it directly and nothing was inferred.
    """
    decision = getattr(answered, "decision", None)
    graph = investigation.graph
    if decision is None or graph is None or "intent" not in graph.nodes:
        return
    try:
        node = graph.add_node(TraceNode(
            id="routing", type=NodeType.MODEL_ROUTING,
            label=decision.to_dict().get("label", decision.route),
            config={
                **decision.to_dict(),
                "rule": ("The route is decided from structural signals before "
                         "any model is called, so it costs nothing and is the "
                         "same for the same request."),
            }))
        node.mark_ok()
        graph.connect("intent", "routing")
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not record the routing node: %s", e)


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
        runtime, (step.result or {}).get("values") if step else None,
        asked=investigation.question)
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
    "answer_investigation",
    "run_investigation",
]
