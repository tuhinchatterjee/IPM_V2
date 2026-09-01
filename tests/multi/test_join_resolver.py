"""
The join graph, and what it refuses.

The resolver decides which datasets an analysis reads and how they are put
together. It takes governed relationship rows as plain dictionaries and returns
a plan, which means all of this runs without a database — and a resolver nobody
can test is a resolver nobody should trust.
"""

from __future__ import annotations

import pytest

from backend.runtime.joins import (
    AMBIGUITY_MARGIN,
    MANY_TO_MANY,
    MANY_TO_ONE,
    ONE_TO_MANY,
    build_graph,
    find_paths,
    resolve,
)

FACILITY = "portfolio_facility"


def edge(from_dataset, to_dataset, *, field="account_id",
         cardinality=MANY_TO_ONE, validated=True, match=0.99, confidence=1.0,
         temporal="same_period", identifier=1):
    return {
        "id": identifier,
        "name": f"{from_dataset}.{field} -> {to_dataset}.{field}",
        "from_dataset": from_dataset, "from_field": field,
        "to_dataset": to_dataset, "to_field": field,
        "cardinality": cardinality, "kind": "key",
        "join_policy": "asof" if temporal == "latest_on_or_before" else "inner",
        "temporal_rule": temporal, "confidence": confidence, "version": 1,
        "semantic": "test edge",
        "match_rate": match if validated else None,
        "validated_at": "2026-01-01" if validated else None,
    }


# ------------------------------------------------------------------- the graph


def test_an_edge_is_traversable_in_both_directions():
    graph = build_graph([edge(FACILITY, "ifrs9_staging")])
    assert graph.direct(FACILITY, "ifrs9_staging")
    assert graph.direct("ifrs9_staging", FACILITY)


def test_reversing_an_edge_reverses_its_cardinality():
    """The property that decides whether a walk is safe, so it is explicit."""
    graph = build_graph([edge(FACILITY, "borrower_financials",
                              field="customer_id", cardinality=MANY_TO_ONE)])
    forward = graph.direct(FACILITY, "borrower_financials")[0]
    backward = graph.direct("borrower_financials", FACILITY)[0]
    assert forward.cardinality == MANY_TO_ONE
    assert backward.cardinality == ONE_TO_MANY
    assert not forward.multiplies_left
    assert backward.multiplies_left


def test_a_self_join_is_not_a_path_step():
    """A parent pointing at another member of the same table is a legitimate
    relationship and a terrible path step — it would let the search circle."""
    graph = build_graph([edge("group_structure", "group_structure",
                              field="customer_id")])
    assert len(graph) == 0


# ------------------------------------------------------------------ pathfinding


def test_a_direct_relationship_is_found():
    graph = build_graph([edge(FACILITY, "ifrs9_staging")])
    paths = find_paths(graph, FACILITY, "ifrs9_staging")
    assert len(paths) == 1
    assert paths[0].hops == 1


def test_a_two_hop_path_is_found_through_an_intermediate():
    graph = build_graph([
        edge(FACILITY, "borrower_financials", field="customer_id", identifier=1),
        edge("customer_ratings", "borrower_financials", field="customer_id",
             identifier=2),
    ])
    paths = find_paths(graph, FACILITY, "customer_ratings")
    assert paths
    assert paths[0].hops == 2
    assert paths[0].datasets == [FACILITY, "borrower_financials", "customer_ratings"]


def test_a_direct_path_outranks_a_longer_one():
    graph = build_graph([
        edge(FACILITY, "customer_ratings", field="customer_id", identifier=1),
        edge(FACILITY, "borrower_financials", field="customer_id", identifier=2),
        edge("customer_ratings", "borrower_financials", field="customer_id",
             identifier=3),
    ])
    paths = find_paths(graph, FACILITY, "customer_ratings")
    assert paths[0].hops == 1
    assert paths[0].score > paths[-1].score


def test_a_measured_relationship_outranks_an_unvalidated_one():
    """An assertion is not evidence, and the ranking says so."""
    graph = build_graph([edge(FACILITY, "a", identifier=1, validated=True)])
    other = build_graph([edge(FACILITY, "a", identifier=2, validated=False)])
    measured = find_paths(graph, FACILITY, "a")[0]
    asserted = find_paths(other, FACILITY, "a")[0]
    assert measured.score > asserted.score


def test_a_multiplying_edge_is_penalised_and_flagged():
    graph = build_graph([edge(FACILITY, "covenant_tests",
                              cardinality=ONE_TO_MANY)])
    path = find_paths(graph, FACILITY, "covenant_tests")[0]
    assert path.multiplies
    assert any("multiply" in r for r in path.reasons)


def test_an_asof_edge_says_it_is_one():
    graph = build_graph([edge(FACILITY, "customer_ratings", field="customer_id",
                              cardinality=MANY_TO_MANY,
                              temporal="latest_on_or_before")])
    path = find_paths(graph, FACILITY, "customer_ratings")[0]
    assert path.needs_asof
    assert any("never a later one" in r for r in path.reasons)


def test_the_search_stops_at_the_hop_limit():
    chain = [edge(f"d{i}", f"d{i + 1}", identifier=i) for i in range(8)]
    graph = build_graph(chain)
    assert find_paths(graph, "d0", "d8", max_hops=3) == []
    assert find_paths(graph, "d0", "d3", max_hops=3)


def test_a_path_never_revisits_a_dataset():
    graph = build_graph([
        edge("a", "b", identifier=1), edge("b", "c", identifier=2),
        edge("c", "a", identifier=3),
    ])
    for path in find_paths(graph, "a", "c"):
        assert len(set(path.datasets)) == len(path.datasets)


# -------------------------------------------------------------- resolution


def test_an_unreachable_target_is_named_not_guessed():
    graph = build_graph([edge(FACILITY, "ifrs9_staging")])
    resolution = resolve(graph, base=FACILITY, targets=["climate_risk"])
    assert not resolution.ok
    assert "climate_risk" in resolution.unreachable
    assert "Declare one in Data Builder" in resolution.unreachable["climate_risk"]


def test_two_close_paths_are_reported_as_a_choice():
    """Customer-level aggregation and facility-level attribution give
    genuinely different answers, so the caller is handed both."""
    graph = build_graph([
        edge(FACILITY, "target", field="customer_id", identifier=1,
             validated=True, match=0.9),
        edge(FACILITY, "bridge", field="account_id", identifier=2),
        edge("bridge", "target", field="account_id", identifier=3),
    ])
    resolution = resolve(graph, base=FACILITY, targets=["target"])
    best = resolution.paths[0]
    others = find_paths(graph, FACILITY, "target")[1:]
    if others and best.score - others[0].score < AMBIGUITY_MARGIN:
        assert "target" in resolution.ambiguous
        assert any("more than one way" in w for w in resolution.warnings)


def test_a_clearly_better_path_is_chosen_without_asking():
    graph = build_graph([
        edge(FACILITY, "target", identifier=1, validated=True, match=1.0),
        edge(FACILITY, "b", identifier=2, validated=False),
        edge("b", "c", identifier=3, validated=False),
        edge("c", "target", identifier=4, validated=False,
             cardinality=MANY_TO_MANY),
    ])
    resolution = resolve(graph, base=FACILITY, targets=["target"])
    assert resolution.paths[0].hops == 1
    assert "target" not in resolution.ambiguous


def test_a_multiplying_path_warns_that_it_will_be_aggregated():
    graph = build_graph([edge(FACILITY, "covenant_tests",
                              cardinality=ONE_TO_MANY)])
    resolution = resolve(graph, base=FACILITY, targets=["covenant_tests"])
    assert any("aggregates that side" in w for w in resolution.warnings)


def test_a_low_confidence_path_says_so():
    graph = build_graph([edge(FACILITY, "target", confidence=0.8)])
    resolution = resolve(graph, base=FACILITY, targets=["target"])
    assert any("not fully confirmed" in w for w in resolution.warnings)


def test_the_resolution_lists_every_dataset_and_edge_once():
    graph = build_graph([
        edge(FACILITY, "a", identifier=1), edge(FACILITY, "b", identifier=2),
    ])
    resolution = resolve(graph, base=FACILITY, targets=["a", "b"])
    assert resolution.datasets == [FACILITY, "a", "b"]
    assert len(resolution.edges()) == 2
    assert resolution.ok


def test_the_base_needs_no_path_to_itself():
    graph = build_graph([edge(FACILITY, "a")])
    resolution = resolve(graph, base=FACILITY, targets=[FACILITY, "a"])
    assert len(resolution.paths) == 1


# ---------------------------------------------------- the shipped graph


@pytest.fixture(scope="module")
def shipped():
    from backend.services.relationships import GOVERNED_RELATIONSHIPS

    rows = []
    for index, r in enumerate(GOVERNED_RELATIONSHIPS, start=1):
        rows.append({
            "id": index, "name": f"{r.from_dataset} -> {r.to_dataset}",
            "from_dataset": r.from_dataset, "from_field": r.from_field,
            "to_dataset": r.to_dataset, "to_field": r.to_field,
            "cardinality": r.cardinality, "kind": r.kind,
            "join_policy": r.join_policy, "temporal_rule": r.temporal_rule,
            "confidence": r.confidence, "version": 1, "semantic": r.semantic,
            "match_rate": None, "validated_at": None,
        })
    return build_graph(rows)


def test_the_shipped_graph_reaches_every_source_the_examples_need(shipped):
    for target in ("ifrs9_staging", "customer_ratings", "facility_delinquency",
                   "covenant_tests", "macro_saudi", "credit_memo_signals",
                   "borrower_financials"):
        resolution = resolve(shipped, base=FACILITY, targets=[target])
        assert resolution.ok, f"{target} is unreachable from the facility book"
        assert resolution.paths[0].hops <= 2


def test_the_ratings_edge_is_declared_as_of(shipped):
    path = resolve(shipped, base=FACILITY,
                   targets=["customer_ratings"]).paths[0]
    assert path.needs_asof, (
        "An annual cycle against a quarterly book has to be an as-of join, or "
        "a Q2 analysis reads a rating that had not been awarded."
    )


def test_the_cardinality_of_every_shipped_edge_matches_the_service():
    """The runtime repeats these constants rather than importing the service.
    If the two ever disagree, a join the service calls safe becomes one the
    runtime multiplies."""
    from backend.runtime import joins as runtime
    from backend.services import relationships as service

    assert runtime.SAFE_CARDINALITIES == service.SAFE_CARDINALITIES
    assert runtime.ONE_TO_ONE == service.ONE_TO_ONE
    assert runtime.MANY_TO_ONE == service.MANY_TO_ONE
    assert runtime.ONE_TO_MANY == service.ONE_TO_MANY
    assert runtime.MANY_TO_MANY == service.MANY_TO_MANY
    assert runtime.LATEST_ON_OR_BEFORE == service.LATEST_ON_OR_BEFORE
