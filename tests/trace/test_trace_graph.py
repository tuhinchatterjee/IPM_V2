"""
Trace graph tests.

The behaviour that matters most is content hashing: it is what makes Trace
modification fast (re-run only what changed) and honest (the UI can show exactly
which nodes a change affected, as a computed fact rather than a guess).

The graph under test mirrors the branching example in docs/PRODUCT_SPEC.md §4.2.
"""

from __future__ import annotations

import pytest

from backend.trace.model import (
    NodeStatus,
    NodeType,
    TraceGraph,
    TraceGraphError,
    TraceNode,
)


def node(node_id: str, node_type: NodeType, **kw) -> TraceNode:
    return TraceNode(id=node_id, type=node_type, label=kw.pop("label", node_id), **kw)


@pytest.fixture()
def graph() -> TraceGraph:
    """A branching analysis: two datasets feeding an aggregation, an engine
    function, a result, then a chart and a narrative."""
    g = TraceGraph()
    g.add_node(node("prompt", NodeType.USER_PROMPT, config={"text": "Why has Stage 2 increased?"}))
    g.add_node(node("intent", NodeType.LLM_INTENT, config={"intent": "explain_stage_movement"}))
    g.add_node(node("plan", NodeType.PLAN, config={"steps": 2}))
    g.add_node(node("ds_portfolio", NodeType.DATASET, dataset="portfolio_facility",
                    fields_used=["ead", "ifrs9_stage"], dataset_version=1))
    g.add_node(node("ds_ecl", NodeType.DATASET, dataset="portfolio_facility",
                    fields_used=["total_ecl"], dataset_version=1))
    g.add_node(node("filter_sector", NodeType.FILTER, config={"field": "sector", "value": "Real Estate"}))
    g.add_node(node("agg", NodeType.AGGREGATION, config={"group_by": ["ifrs9_stage"], "measure": "ead"}))
    g.add_node(node("fn_migration", NodeType.ENGINE_FUNCTION,
                    function_id="stage_migration", function_version="1.0.0"))
    g.add_node(node("result", NodeType.RESULT))
    g.add_node(node("explain", NodeType.LLM_EXPLANATION))
    g.add_node(node("chart", NodeType.VISUALIZATION, config={"type": "stacked_bar"}))

    g.connect("prompt", "intent")
    g.connect("intent", "plan")
    g.connect("plan", "ds_portfolio")
    g.connect("plan", "ds_ecl")
    g.connect("ds_portfolio", "filter_sector")
    g.connect("filter_sector", "agg")
    g.connect("ds_ecl", "agg")
    g.connect("agg", "fn_migration")
    g.connect("fn_migration", "result")
    g.connect("result", "explain")
    g.connect("result", "chart")
    return g


# ------------------------------------------------------------------ structure


def test_graph_shape(graph):
    assert len(graph.nodes) == 11
    assert graph.roots() == ["prompt"]
    assert set(graph.leaves()) == {"explain", "chart"}


def test_branch_and_rejoin_is_supported(graph):
    """A real analysis branches and re-joins; a straight chain is a simplification."""
    assert sorted(graph.children("plan")) == ["ds_ecl", "ds_portfolio"]
    assert sorted(graph.parents("agg")) == ["ds_ecl", "filter_sector"]


def test_governed_and_interpretive_nodes_are_distinguishable(graph):
    """A reader must see at a glance where the AI's judgement ends and the
    deterministic engine begins."""
    assert graph.nodes["fn_migration"].is_governed
    assert graph.nodes["explain"].is_interpretive
    assert not graph.nodes["explain"].is_governed
    stats = graph.to_dict()["stats"]
    assert stats["governed_nodes"] == 6
    assert stats["interpretive_nodes"] == 4


def test_duplicate_node_id_is_rejected(graph):
    with pytest.raises(TraceGraphError, match="Duplicate"):
        graph.add_node(node("result", NodeType.RESULT))


def test_connecting_an_unknown_node_is_rejected(graph):
    with pytest.raises(TraceGraphError, match="unknown node"):
        graph.connect("result", "nowhere")


# ------------------------------------------------------------------ ordering


def test_topological_order_respects_dependencies(graph):
    order = graph.topological_order()
    assert len(order) == len(graph.nodes)
    for edge in graph.edges:
        assert order.index(edge.source) < order.index(edge.target)


def test_topological_order_is_deterministic(graph):
    """A layout that reshuffles on every open reads as unreliable."""
    assert graph.topological_order() == graph.topological_order()


def test_cycle_is_detected(graph):
    graph.connect("explain", "plan")
    with pytest.raises(TraceGraphError, match="cycle"):
        graph.topological_order()


def test_layers_place_each_node_below_its_parents(graph):
    layers = graph.layers()
    depth = {n: i for i, layer in enumerate(layers) for n in layer}
    assert depth["prompt"] == 0
    for edge in graph.edges:
        assert depth[edge.source] < depth[edge.target]


# ------------------------------------------------------------------- hashing


def test_every_node_gets_a_hash(graph):
    hashes = graph.compute_hashes()
    assert len(hashes) == len(graph.nodes)
    assert all(h for h in hashes.values())


def test_hashing_is_stable_across_runs(graph):
    first = graph.compute_hashes()
    second = graph.compute_hashes()
    assert first == second


def test_execution_evidence_does_not_change_the_hash(graph):
    """Timings and row counts are the *result* of running, not an input to it.
    If they fed the hash, every re-run would invalidate the whole graph and
    selective re-execution would never reuse anything."""
    before = graph.compute_hashes()
    n = graph.nodes["agg"]
    n.mark_started()
    n.mark_ok(rows_out=42)
    n.rows_in = 673
    n.warnings.append("small sample")
    after = graph.compute_hashes()
    assert before == after
    assert n.status is NodeStatus.OK


def test_changing_a_filter_changes_only_that_node_and_its_descendants(graph):
    """This is the mechanism behind 'Exclude Real Estate' re-running in a second
    rather than a minute."""
    before = graph.compute_hashes()
    graph.nodes["filter_sector"].config["value"] = "Energy"
    graph.compute_hashes()
    diff = graph.diff_hashes(before)

    assert set(diff["changed"]) == {"filter_sector", "agg", "fn_migration", "result",
                                    "explain", "chart"}
    # The prompt, the plan and the untouched ECL branch must be reusable.
    for untouched in ("prompt", "intent", "plan", "ds_portfolio", "ds_ecl"):
        assert untouched in diff["unchanged"]


def test_changing_a_function_version_invalidates_downstream(graph):
    """A recalibrated function must not silently reuse results computed by the
    previous version."""
    before = graph.compute_hashes()
    graph.nodes["fn_migration"].function_version = "1.1.0"
    graph.compute_hashes()
    diff = graph.diff_hashes(before)
    assert set(diff["changed"]) == {"fn_migration", "result", "explain", "chart"}


def test_changing_the_dataset_version_invalidates_downstream(graph):
    before = graph.compute_hashes()
    graph.nodes["ds_portfolio"].dataset_version = 2
    graph.compute_hashes()
    diff = graph.diff_hashes(before)
    assert "ds_portfolio" in diff["changed"]
    assert "result" in diff["changed"]
    assert "ds_ecl" in diff["unchanged"]


def test_affected_by_returns_the_node_plus_everything_downstream(graph):
    affected = graph.affected_by(["filter_sector"])
    assert affected == {"filter_sector", "agg", "fn_migration", "result", "explain", "chart"}


def test_descendants_of_a_leaf_is_empty(graph):
    assert graph.descendants("chart") == set()


def test_diff_reports_added_and_removed_nodes(graph):
    before = graph.compute_hashes()
    graph.add_node(node("table", NodeType.VISUALIZATION, config={"type": "table"}))
    graph.connect("result", "table")
    graph.compute_hashes()
    diff = graph.diff_hashes(before)
    assert diff["added"] == ["table"]
    assert diff["removed"] == []


# --------------------------------------------------------------- serialisation


def test_to_dict_is_json_shaped_for_the_frontend(graph):
    graph.compute_hashes()
    payload = graph.to_dict()
    assert {"nodes", "edges", "layers", "stats"} <= set(payload)
    first = payload["nodes"][0]
    assert first["id"] == "prompt"
    for key in ("type", "label", "config", "status", "is_governed", "content_hash"):
        assert key in first


def test_failed_node_records_its_error(graph):
    n = graph.nodes["fn_migration"]
    n.mark_started()
    n.mark_failed("Dataset unavailable for Q1 2026")
    assert n.status is NodeStatus.FAILED
    assert "unavailable" in (n.error or "")
    assert n.duration_ms is not None
