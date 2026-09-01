"""The Trace a compound request leaves behind. §39.

§39 lists ten stages, and the reason it lists them rather than saying "trace
the compound request" is that each one is a place a multi-question answer can
go wrong invisibly:

    USER MESSAGE            what was actually typed
    OBJECTIVE DECOMPOSITION what it was read as asking - where a third
                            question gets dropped
    SHARED SCOPE            the population every clause is about - where two
                            clauses end up on two different books
    TASK DAG                what depended on what - where a decomposition
                            runs before the comparison it decomposes
    ANALYSIS PORTFOLIO      what was considered and rejected - the part a
                            reader otherwise has to take on trust
    SPECIALIST ANALYSES     what each one found
    VALIDATION              what was checked
    COMPARISON              how the analyses were reconciled
    SYNTHESIS               the paragraph that ties them together
    OBJECTIVE COVERAGE      what the reader asked for against what they got

The last line of §39 is "No hidden chain-of-thought", and this module obeys
it structurally rather than by intention: every node it builds is assembled
from a recorded decision - a parse, a score, a graph, a count - and there is
no field for a model's reasoning to be written into. The one interpretive
node, SYNTHESIS, carries the prose the reader was already shown.
"""

from __future__ import annotations

from typing import Any

from backend.orchestration import objectives as obj
from backend.trace.model import NodeStatus, NodeType, TraceGraph, TraceNode

COMPOUND_TRACE_VERSION = "1.0.0"

#: §39's per-objective vocabulary. The Trace says ANSWERED where the internal
#: status is COMPLETE, because "complete" is a word about the machinery and
#: "answered" is a word about the reader's question.
OBJECTIVE_LABEL: dict[str, str] = {
    obj.COMPLETE: "ANSWERED",
    obj.PARTIAL: "PARTIALLY ANSWERED",
    obj.NEEDS_CLARIFICATION: "CLARIFICATION NEEDED",
    obj.UNAVAILABLE: "UNSUPPORTED",
    obj.FAILED: "FAILED",
    obj.PLANNED: "NOT ANSWERED",
}

#: The stages, in order, with the node type each becomes. Kept as data so a
#: stage cannot be dropped by an edit without the count changing.
STAGES: tuple[tuple[str, NodeType], ...] = (
    ("USER MESSAGE", NodeType.USER_PROMPT),
    ("OBJECTIVE DECOMPOSITION", NodeType.OBJECTIVE_DECOMPOSITION),
    ("SHARED SCOPE", NodeType.SHARED_SCOPE),
    ("TASK DAG", NodeType.TASK_DAG),
    ("ANALYSIS PORTFOLIO", NodeType.ANALYSIS_PORTFOLIO),
    ("SPECIALIST ANALYSES", NodeType.ENGINE_FUNCTION),
    ("VALIDATION", NodeType.BUSINESS_INVARIANT),
    ("COMPARISON", NodeType.COMPARISON),
    ("SYNTHESIS", NodeType.SYNTHESIS),
    ("OBJECTIVE COVERAGE", NodeType.OBJECTIVE_COVERAGE),
)


def _node(node_id: str, node_type: NodeType, label: str,
          config: dict[str, Any], *, done: bool = True) -> TraceNode:
    return TraceNode(
        id=node_id, type=node_type, label=label, config=config,
        status=NodeStatus.OK if done else NodeStatus.PENDING)


def build(question: str, reading: obj.Reading, *,
          portfolio: Any = None,
          scope: obj.SharedScope | None = None,
          analyses: list[dict[str, Any]] | None = None,
          validation: dict[str, Any] | None = None,
          comparison: dict[str, Any] | None = None,
          synthesis: str = "",
          length_decision: Any = None) -> TraceGraph:
    """The ten stages, as a graph.

    Stages with nothing behind them are recorded as PENDING rather than
    omitted. An absent stage looks like a stage that did not apply; a pending
    one says it did apply and did not happen, and those are different things
    for a reader deciding how much of the answer to trust.
    """
    graph = TraceGraph()
    scope = scope if scope is not None else obj.shared_scope(reading)
    coverage = obj.coverage(reading)

    graph.add_node(_node(
        "compound_message", NodeType.USER_PROMPT, "User message",
        {"question": question,
         "clauses": [c.text for c in reading.discourse.clauses]}))

    graph.add_node(_node(
        "compound_objectives", NodeType.OBJECTIVE_DECOMPOSITION,
        f"{len(reading.objectives)} objective(s)",
        {"objectives": [
            {**o.to_dict(), "reported_as": OBJECTIVE_LABEL.get(o.status,
                                                               o.status)}
            for o in reading.objectives]}))
    graph.connect("compound_message", "compound_objectives",
                  "read as asking")

    graph.add_node(_node(
        "compound_scope", NodeType.SHARED_SCOPE,
        (f"Shared: {scope.population}" if scope.shared
         else "No single shared population"),
        {**scope.to_dict(),
         "note": ("every objective is about this population"
                  if scope.shared else
                  "the objectives are about different populations, so their "
                  "figures are not directly comparable and the answer has to "
                  "say so")}))
    graph.connect("compound_objectives", "compound_scope", "scoped to")

    dag = (portfolio.dependency_graph() if portfolio is not None else {})
    layers = (portfolio.layers() if portfolio is not None else [])
    graph.add_node(_node(
        "compound_dag", NodeType.TASK_DAG,
        (f"{len(dag)} task(s), {len(layers)} round(s)" if dag
         else "No task graph"),
        {"dependencies": dag, "rounds": layers,
         "parallelism": (portfolio.parallelism if portfolio is not None
                         else 0)},
        done=bool(dag)))
    graph.connect("compound_scope", "compound_dag", "planned as")

    graph.add_node(_node(
        "compound_portfolio", NodeType.ANALYSIS_PORTFOLIO,
        (f"{len(portfolio.selected)} of {len(portfolio.candidates)} analyses"
         if portfolio is not None else "No portfolio"),
        (portfolio.to_dict() if portfolio is not None else {}),
        done=portfolio is not None))
    graph.connect("compound_dag", "compound_portfolio", "selected from")

    ran = analyses or []
    graph.add_node(_node(
        "compound_analyses", NodeType.ENGINE_FUNCTION,
        f"{len(ran)} specialist analysis(es)",
        {"analyses": ran}, done=bool(ran)))
    graph.connect("compound_portfolio", "compound_analyses", "executed")

    graph.add_node(_node(
        "compound_validation", NodeType.BUSINESS_INVARIANT,
        ("Validation" if validation else "Not validated"),
        validation or {}, done=bool(validation)))
    graph.connect("compound_analyses", "compound_validation", "checked by")

    graph.add_node(_node(
        "compound_comparison", NodeType.COMPARISON,
        ("Comparison" if comparison else
         "Nothing to compare" if len(ran) < 2 else "Not compared"),
        comparison or {"note": (
            "a single analysis has nothing to be reconciled against"
            if len(ran) < 2 else
            "several analyses ran and were not reconciled against each "
            "other, so a disagreement between them would not have been "
            "noticed")},
        done=bool(comparison) or len(ran) < 2))
    graph.connect("compound_validation", "compound_comparison", "reconciled")

    graph.add_node(_node(
        "compound_synthesis", NodeType.SYNTHESIS,
        ("Synthesis" if synthesis else "Not synthesised"),
        {"text": synthesis,
         "length_policy": (length_decision.to_dict()
                           if length_decision is not None else {})},
        done=bool(synthesis)))
    graph.connect("compound_comparison", "compound_synthesis", "written as")

    graph.add_node(_node(
        "compound_coverage", NodeType.OBJECTIVE_COVERAGE,
        coverage.headline() or "No objectives",
        {**coverage.to_dict(),
         "reported": [
             {"objective_id": o.objective_id,
              "description": o.description,
              "status": OBJECTIVE_LABEL.get(o.status, o.status),
              "note": o.note}
             for o in reading.objectives],
         "presentable": coverage.presentable}))
    graph.connect("compound_synthesis", "compound_coverage", "covers")

    return graph


def stages(graph: TraceGraph) -> list[dict[str, Any]]:
    """The ten stages as the Trace view renders them, in §39's order."""
    order = [
        ("USER MESSAGE", "compound_message"),
        ("OBJECTIVE DECOMPOSITION", "compound_objectives"),
        ("SHARED SCOPE", "compound_scope"),
        ("TASK DAG", "compound_dag"),
        ("ANALYSIS PORTFOLIO", "compound_portfolio"),
        ("SPECIALIST ANALYSES", "compound_analyses"),
        ("VALIDATION", "compound_validation"),
        ("COMPARISON", "compound_comparison"),
        ("SYNTHESIS", "compound_synthesis"),
        ("OBJECTIVE COVERAGE", "compound_coverage"),
    ]
    out: list[dict[str, Any]] = []
    for title, node_id in order:
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        out.append({
            "stage": title,
            "node_id": node_id,
            "type": node.type.value,
            "label": node.label,
            "governed": node.is_governed,
            "status": node.status.value,
            "config": node.config,
        })
    return out


def applies(reading: obj.Reading, portfolio: Any = None) -> bool:
    """Whether this turn earns a compound Trace.

    One objective answered by one analysis is not a compound request, and
    wrapping it in ten stages would bury the two that matter.
    """
    analyses = len(portfolio.selected) if portfolio is not None else 0
    return len(reading.objectives) > 1 or analyses > 1
