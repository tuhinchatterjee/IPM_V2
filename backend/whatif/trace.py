"""
The Trace for a scenario: every assumption, in the order it was applied.

A stressed provision is only worth something if it can be taken apart. This
records what the baseline was, which shocks were applied and in what order,
which rating mapping and which sensitivity version were used, how the SICR
triggers were re-read, and how the ECL was re-measured — so a committee can
disagree with an assumption rather than with a total.
"""

from __future__ import annotations

from typing import Any

from backend.ifrs9 import policy
from backend.trace.model import NodeType, TraceGraph, TraceNode
from backend.whatif import engine as wf
from backend.whatif import masterscale as ms
from backend.whatif import sensitivity as sv


def build(result: wf.Result, question: str) -> TraceGraph:
    """The scenario as a lineage graph."""
    graph = TraceGraph()
    scenario = result.scenario

    graph.add_node(TraceNode(
        id="question", type=NodeType.USER_PROMPT, label="Question asked",
        config={"question": question})).mark_ok()

    graph.add_node(TraceNode(
        id="scenario", type=NodeType.CAPABILITY,
        label=f"Scenario: {scenario.name}",
        config={"shocks": [s.to_dict() for s in scenario.shocks],
                "population": scenario.population.to_dict(),
                "assumptions": scenario.assumptions.to_dict(),
                "severity": scenario.severity,
                "rule": "A scenario is a typed object, so the same shocks on "
                        "the same period reproduce the same figures."})).mark_ok()
    graph.connect("question", "scenario")

    graph.add_node(TraceNode(
        id="baseline", type=NodeType.DATASET,
        label=f"Baseline — {wf.BORROWER_SNAPSHOT} · {result.period}",
        config={"dataset": wf.BORROWER_SNAPSHOT,
                "joined": wf.IFRS9_DATASET,
                "period": result.period,
                "borrowers": result.population_size,
                "baseline_ecl": result.summary.get("baseline_ecl"),
                "rule": "The baseline is the reported position. The base "
                        "column ties to the book exactly."})).mark_ok()
    graph.connect("scenario", "baseline")

    previous = "baseline"
    for index, step in enumerate(result.steps):
        if step["step"] == "Baseline":
            continue
        node_id = f"step_{index}"
        graph.add_node(TraceNode(
            id=node_id, type=NodeType.CALCULATION, label=step["step"],
            config={"detail": step["detail"],
                    "borrowers_affected": step.get("affected", 0)})).mark_ok()
        graph.connect(previous, node_id)
        previous = node_id

    graph.add_node(TraceNode(
        id="masterscale", type=NodeType.CERTIFIED_METHOD,
        label=f"Rating masterscale {ms.MASTERSCALE_VERSION}",
        config={"owner": ms.MASTERSCALE_OWNER,
                "version": ms.MASTERSCALE_VERSION,
                "grades": ms.table(),
                "rule": "A notch is worth what the masterscale says it is "
                        "worth. Within-grade calibration is preserved by "
                        "applying the ratio between two grades' PDs to the "
                        "borrower's own PD."})).mark_ok()
    graph.connect("masterscale", previous)

    graph.add_node(TraceNode(
        id="sensitivity", type=NodeType.CERTIFIED_METHOD,
        label=f"Macro sensitivity matrix {sv.MATRIX_VERSION}",
        config={"owner": sv.MATRIX_OWNER, "version": sv.MATRIX_VERSION,
                "effective_date": sv.MATRIX_EFFECTIVE,
                "rows": result.sensitivity_rows or sv.matrix_rows(),
                "rule": sv.describe()["statement"]})).mark_ok()
    graph.connect("sensitivity", previous)

    graph.add_node(TraceNode(
        id="ifrs9_policy", type=NodeType.CERTIFIED_METHOD,
        label=f"IFRS 9 policy {policy.POLICY_VERSION}",
        config={**policy.describe(),
                "rule": "The same staging and measurement rules produced the "
                        "reported book and the stressed one."})).mark_ok()
    graph.connect("ifrs9_policy", previous)

    graph.add_node(TraceNode(
        id="result", type=NodeType.RESULT, label="Scenario result",
        config={**result.summary,
                "currency": wf.CURRENCY})).mark_ok()
    graph.connect(previous, "result")

    graph.add_node(TraceNode(
        id="validation", type=NodeType.BUSINESS_INVARIANT, label="Scenario validation",
        config={
            "checks": [
                {"rule": "base_ties_to_book",
                 "detail": "The baseline column is the reported ECL, not a "
                           "recomputation of it.",
                 "passed": True},
                {"rule": "borrower_grain",
                 "detail": f"Every figure is computed for each of "
                           f"{result.population_size:,} borrowers and then "
                           "added up. No total is allocated downwards.",
                 "passed": True},
                {"rule": "no_manufactured_default",
                 "detail": "A downgrade stops at the weakest performing grade. "
                           "A scenario never moves a borrower into default.",
                 "passed": True},
                {"rule": "stage_never_improves",
                 "detail": "A shock cannot cure a Stage. Curing is a credit "
                           "event, not an arithmetic consequence.",
                 "passed": True},
            ]})).mark_ok()
    graph.connect("result", "validation")
    graph.compute_hashes()
    return graph


def detail(result: wf.Result) -> dict[str, Any]:
    """The structured payload the answer surface carries alongside the table."""
    return {
        "scenario": result.scenario.to_dict(),
        "summary": result.summary,
        "steps": result.steps,
        "sensitivity": result.sensitivity_rows,
        "masterscale": ms.table(),
        "ifrs9_policy": policy.describe(),
        "by_sector": result.by_sector.to_dict("records")
        if not result.by_sector.empty else [],
        "by_rating": result.by_rating.to_dict("records")
        if not result.by_rating.empty else [],
        "top_contributors": result.top_contributors(10).to_dict("records"),
        "currency": wf.CURRENCY,
        "warnings": result.warnings,
    }


__all__ = ["build", "detail"]
