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
from backend.orchestration.clarification import needed_clarification
from backend.orchestration.interpreter import Narrative, build_narrative
from backend.orchestration.planner import get_planner, planner_mode
from backend.orchestration.schema import AnalysisPlan, PlanRejected, PlanStep
from backend.orchestration.validator import validate_plan
from backend.orchestration.vocabulary import get_vocabulary
from backend.trace.model import NodeStatus, NodeType, TraceGraph, TraceNode

logger = logging.getLogger(__name__)


# The stages shown to the user while an investigation runs. They are the real
# phases of this function, in the order they happen — not a decorative loader.
STAGES = [
    {"id": "understanding", "label": "Understanding the question"},
    {"id": "planning", "label": "Selecting IPM analyses"},
    {"id": "retrieving", "label": "Retrieving governed data"},
    {"id": "running", "label": "Running the IPM Engine"},
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
    #: Set when IPM stopped to ask rather than answering.
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
            "rule": "This node contains no figures. It records what IPM understood "
                    "the question to be asking, not what the answer is.",
        },
    ))
    graph.connect("question", "intent")

    graph.add_node(_interpretive_node(
        "plan", NodeType.PLAN,
        f"{len(steps)} IPM {'analysis' if len(steps) == 1 else 'analyses'} selected",
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
            # Interpreted: IPM's reading of those figures.
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


def run_investigation(question: str, *, user_id: int | None = None,
                      project_id: int | None = None, chat_id: int | None = None,
                      persist: bool = True,
                      period: tuple[str, str] | None = None) -> Investigation:
    """Answer one question end to end — or ask the one thing IPM needs to know.

    `period` is a comparison already chosen: from answering a clarification, or
    from refreshing a saved Investigation onto newer data.
    """
    started = time.perf_counter()
    planner = get_planner()
    vocab = get_vocabulary()

    plan = planner.plan(question, vocab, period=period)

    # Ask before running, never after. A clarification costs the user one click;
    # a confidently wrong comparison costs them a credit decision.
    clarification = needed_clarification(plan, vocab)
    if clarification is not None:
        narrative = build_narrative(question, plan.intent, [], plan=plan)
        asking = Investigation(
            question=question, plan=plan, steps=[], narrative=narrative,
            graph=build_reasoning_map(plan, [], narrative),
            node_hashes={}, duration_ms=int((time.perf_counter() - started) * 1000),
            status="needs_clarification", clarification=clarification,
            mode=planner_mode(),
        )
        asking.node_hashes = asking.graph.compute_hashes()
        return asking

    try:
        plan = validate_plan(plan, vocab)
    except PlanRejected as rejection:
        # A rejected plan is a real outcome, not an exception to swallow. It is
        # returned with its reasons so the user can see what IPM refused to do.
        empty = Investigation(
            question=question, plan=plan, steps=[],
            narrative=build_narrative(question, plan.intent, [], plan=plan),
            graph=build_reasoning_map(plan, [],
                                      build_narrative(question, plan.intent, [], plan=plan)),
            node_hashes={}, duration_ms=int((time.perf_counter() - started) * 1000),
            status="rejected", rejected=rejection.reasons, mode=planner_mode(),
        )
        empty.node_hashes = empty.graph.compute_hashes()
        return empty

    steps = execute_plan(plan, user_id=user_id)
    investigation = assemble(plan, steps,
                             duration_ms=int((time.perf_counter() - started) * 1000))
    if persist:
        persist_investigation(investigation, user_id=user_id, project_id=project_id,
                              chat_id=chat_id)
    return investigation


# ---------------------------------------------------------------- persistence


def persist_investigation(investigation: Investigation, *, user_id: int | None = None,
                          project_id: int | None = None, chat_id: int | None = None) -> int | None:
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
                chat_id=chat_id,
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
