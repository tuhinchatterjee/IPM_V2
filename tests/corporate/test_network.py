"""Network analytics: DebtRank, PageRank, betweenness, Louvain, NRS, similarity.

Every numeric expectation here is hand-computed on a graph small enough to
work through on paper, then checked against the implementation. Asserting
that a 3,800-node run "returns something" proves nothing; asserting that a
three-node cascade produces 0.375 proves the propagation rule.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.corporate import graphdata
from backend.corporate import network as net


def graph_of(edges: list[tuple[str, str, float]], *,
             extra: list[str] | None = None,
             as_of: str = "2026-06-30") -> net.DirectedGraph:
    """A DirectedGraph built directly, without going through the universe."""
    names = sorted({n for a, b, _ in edges for n in (a, b)} | set(extra or []))
    index = {name: i for i, name in enumerate(names)}
    weights = np.zeros((len(names), len(names)), dtype=float)
    for source, target, amount in edges:
        weights[index[source], index[target]] += amount
    return net.DirectedGraph(nodes=tuple(names), weights=weights, as_of=as_of)


# ---------------------------------------------------------------- DebtRank


class TestDebtRank:
    def test_a_two_step_chain_propagates_the_hand_computed_amount(self):
        """A exposed to B (50), B exposed to C (50), capital 100 each.

        W[A,B] = 50/100 = 0.5 and W[B,C] = 0.5. Shock C fully:
        B takes 1.0 * 0.5 = 0.5, then A takes 0.5 * 0.5 = 0.25.
        Impact is the mean over the two non-seed nodes: (0.5 + 0.25) / 2.
        """
        graph = graph_of([("A", "B", 50.0), ("B", "C", 50.0)])
        capital = {"A": 100.0, "B": 100.0, "C": 100.0}
        result = net.debtrank(graph, capital, "C")

        assert result.distress["B"] == pytest.approx(0.5)
        assert result.distress["A"] == pytest.approx(0.25)
        assert result.impact == pytest.approx(0.375)

    def test_the_seed_is_excluded_from_the_impact(self):
        graph = graph_of([("A", "B", 50.0)])
        capital = {"A": 100.0, "B": 100.0}
        result = net.debtrank(graph, capital, "B")
        # One other node, distressed to 0.5. The seed's own 1.0 is not in it.
        assert result.impact == pytest.approx(0.5)

    def test_a_node_propagates_exactly_once_so_a_cycle_terminates(self):
        """The rule that separates DebtRank from a naive cascade.

        A -> B -> A with full exposure. Without the propagate-once rule the
        two nodes would re-infect each other forever; with it the run ends
        and nothing exceeds 1.0.
        """
        graph = graph_of([("A", "B", 100.0), ("B", "A", 100.0)])
        capital = {"A": 100.0, "B": 100.0}
        result = net.debtrank(graph, capital, "A")

        assert result.converged is True
        assert result.iterations <= 3
        assert max(result.distress.values()) <= 1.0
        assert result.states["A"] == net.INACTIVE

    def test_distress_never_exceeds_one(self):
        """Three lenders all fully exposed to one borrower and to each other."""
        graph = graph_of([("A", "D", 400.0), ("B", "D", 400.0),
                          ("C", "D", 400.0), ("A", "B", 400.0),
                          ("B", "C", 400.0)])
        capital = dict.fromkeys("ABCD", 100.0)
        result = net.debtrank(graph, capital, "D")
        assert all(value <= 1.0 + 1e-12 for value in result.distress.values())

    def test_impact_matrix_caps_at_one(self):
        """Exposure of ten times capital is still a total loss, not ten."""
        graph = graph_of([("A", "B", 1_000.0)])
        weights = net.impact_matrix(graph, {"A": 100.0, "B": 100.0})
        assert weights[0, 1] == pytest.approx(1.0)

    def test_a_thin_balance_sheet_is_floored_not_divided_by_zero(self):
        graph = graph_of([("A", "B", 10.0)])
        weights = net.impact_matrix(graph, {"A": 0.0, "B": 0.0})
        assert np.isfinite(weights).all()
        assert weights[0, 1] == pytest.approx(1.0)

    def test_an_unknown_seed_returns_zero_impact_not_an_error(self):
        graph = graph_of([("A", "B", 50.0)])
        result = net.debtrank(graph, {"A": 100.0, "B": 100.0}, "NOT-A-NODE")
        assert result.impact == 0.0
        assert result.nodes_touched == 0

    def test_an_isolated_node_transmits_nothing(self):
        graph = graph_of([("A", "B", 50.0)], extra=["Z"])
        result = net.debtrank(graph, dict.fromkeys("ABZ", 100.0), "Z")
        assert result.impact == 0.0

    def test_the_result_carries_its_caveat_and_its_versions(self):
        graph = graph_of([("A", "B", 50.0)])
        payload = net.debtrank(graph, {"A": 100.0, "B": 100.0}, "B").to_dict()

        assert payload["caveat"] == net.DEBTRANK_CAVEAT
        assert "NOT an expected credit loss" in payload["caveat"]
        assert payload["method_version"] == net.NETWORK_VERSION
        assert payload["policy_version"] == net.POLICY_VERSION
        assert payload["as_of"] == "2026-06-30"
        assert payload["validation_status"] == "PASS"

    def test_two_runs_give_identical_numbers(self):
        graph = graph_of([("A", "B", 50.0), ("B", "C", 30.0),
                          ("C", "A", 70.0), ("A", "C", 20.0)])
        capital = dict.fromkeys("ABC", 100.0)
        first = net.debtrank(graph, capital, "C")
        second = net.debtrank(graph, capital, "C")
        assert first.distress == second.distress
        assert first.impact == second.impact

    def test_the_three_states_are_the_declared_ones(self):
        assert net.DEBTRANK_STATES == (net.UNDISTRESSED, net.DISTRESSED,
                                       net.INACTIVE)


# ---------------------------------------------------------------- PageRank


class TestPageRank:
    def test_forward_ranks_transmitters_and_reverse_ranks_the_exposed(self):
        """A star where everyone carries exposure to one hub.

        Forward, rank flows along the arrow and piles onto the hub: the hub is
        what everyone is exposed to. Reverse, the arrow is flipped and the
        hub becomes the thing that spreads, so the SPOKES score higher. The
        two must disagree; a measure where they agree has lost the direction.
        """
        graph = graph_of([(name, "HUB", 100.0) for name in ("A", "B", "C")])
        forward = net.pagerank(graph)
        reverse = net.pagerank(graph, reverse=True)

        assert forward["HUB"] > forward["A"]
        assert reverse["HUB"] < reverse["A"]

    def test_it_sums_to_one(self):
        graph = graph_of([("A", "B", 1.0), ("B", "C", 1.0), ("C", "A", 1.0),
                          ("A", "C", 3.0)])
        assert sum(net.pagerank(graph).values()) == pytest.approx(1.0)

    def test_a_dangling_node_does_not_leak_mass(self):
        """C has no outgoing edge. Its rank must be redistributed, not lost."""
        graph = graph_of([("A", "B", 1.0), ("B", "C", 1.0)])
        assert sum(net.pagerank(graph).values()) == pytest.approx(1.0)

    def test_personalisation_moves_rank_towards_the_seed(self):
        graph = graph_of([("A", "B", 1.0), ("B", "C", 1.0), ("C", "A", 1.0)])
        plain = net.pagerank(graph)
        seeded = net.pagerank(graph, personalisation={"A": 1.0})
        assert seeded["A"] > plain["A"]
        assert sum(seeded.values()) == pytest.approx(1.0)

    def test_a_symmetric_graph_gives_every_node_the_same_rank(self):
        graph = graph_of([("A", "B", 1.0), ("B", "A", 1.0),
                          ("B", "C", 1.0), ("C", "B", 1.0),
                          ("C", "A", 1.0), ("A", "C", 1.0)])
        ranks = list(net.pagerank(graph).values())
        assert max(ranks) - min(ranks) < 1e-9

    def test_two_runs_agree(self):
        graph = graph_of([("A", "B", 2.0), ("B", "C", 5.0), ("C", "A", 1.0)])
        assert net.pagerank(graph) == net.pagerank(graph)


# ------------------------------------------------------------- betweenness


class TestBetweenness:
    def test_the_middle_of_a_path_is_the_only_conduit(self):
        """L -> M -> R. M is on the single L-R path and nothing else is.

        Normalised over the 2 ordered pairs excluding M, M scores 1/2.
        """
        graph = graph_of([("L", "M", 1.0), ("M", "R", 1.0)])
        scores = net.betweenness(graph)
        assert scores["M"] == pytest.approx(0.5)
        assert scores["L"] == pytest.approx(0.0)
        assert scores["R"] == pytest.approx(0.0)

    def test_a_node_on_no_path_scores_zero(self):
        graph = graph_of([("A", "B", 1.0)], extra=["Z"])
        assert net.betweenness(graph)["Z"] == pytest.approx(0.0)

    def test_two_parallel_conduits_split_the_credit(self):
        """S -> M1 -> T and S -> M2 -> T. Each carries half the S-T flow."""
        graph = graph_of([("S", "M1", 1.0), ("M1", "T", 1.0),
                          ("S", "M2", 1.0), ("M2", "T", 1.0)])
        scores = net.betweenness(graph)
        assert scores["M1"] == pytest.approx(scores["M2"])
        assert scores["M1"] > 0.0

    def test_components_are_handled_independently(self):
        """Two disjoint paths. Neither middle is a conduit for the other."""
        graph = graph_of([("A", "B", 1.0), ("B", "C", 1.0),
                          ("X", "Y", 1.0), ("Y", "Z", 1.0)])
        scores = net.betweenness(graph)
        assert scores["B"] > 0.0
        assert scores["Y"] == pytest.approx(scores["B"])
        assert scores["A"] == pytest.approx(0.0)

    def test_two_runs_agree(self):
        graph = graph_of([("A", "B", 1.0), ("B", "C", 1.0), ("A", "C", 1.0),
                          ("C", "D", 1.0)])
        assert net.betweenness(graph) == net.betweenness(graph)


# ----------------------------------------------------------------- Louvain


class TestLouvain:
    def test_two_weakly_joined_triangles_split_into_two_communities(self):
        graph = graph_of([
            ("A", "B", 10.0), ("B", "C", 10.0), ("C", "A", 10.0),
            ("D", "E", 10.0), ("E", "F", 10.0), ("F", "D", 10.0),
            ("C", "D", 0.5),
        ])
        communities = net.louvain(graph)
        assert communities["A"] == communities["B"] == communities["C"]
        assert communities["D"] == communities["E"] == communities["F"]
        assert communities["A"] != communities["D"]

    def test_it_improves_modularity_over_one_community_per_node(self):
        graph = graph_of([
            ("A", "B", 10.0), ("B", "C", 10.0), ("C", "A", 10.0),
            ("D", "E", 10.0), ("E", "F", 10.0), ("F", "D", 10.0),
            ("C", "D", 0.5),
        ])
        singletons = {name: i for i, name in enumerate(graph.nodes)}
        found = net.louvain(graph)
        assert net.modularity(graph, found) > net.modularity(graph, singletons)

    def test_it_terminates_on_a_dense_graph(self):
        rng = np.random.default_rng(7)
        names = [f"N{i:02d}" for i in range(30)]
        edges = [(a, b, float(rng.integers(1, 9)))
                 for a in names for b in names if a < b and rng.random() < 0.4]
        graph = graph_of(edges)
        communities = net.louvain(graph)
        assert set(communities) == set(graph.nodes)

    def test_a_disconnected_node_gets_its_own_community(self):
        graph = graph_of([("A", "B", 5.0), ("B", "C", 5.0)], extra=["Z"])
        communities = net.louvain(graph)
        assert communities["Z"] not in {communities["A"], communities["B"],
                                        communities["C"]}

    def test_an_empty_graph_returns_an_empty_partition(self):
        graph = net.DirectedGraph(nodes=(), weights=np.zeros((0, 0)),
                                  as_of="2026-06-30")
        assert net.louvain(graph) == {}

    def test_two_runs_give_the_identical_partition(self):
        """Determinism is the property Louvain is least likely to have.

        The standard algorithm iterates over a set and breaks ties at random,
        so two runs on the same graph return different community ids and a
        report that names communities cannot be reproduced.
        """
        rng = np.random.default_rng(11)
        names = [f"N{i:02d}" for i in range(24)]
        edges = [(a, b, float(rng.integers(1, 6)))
                 for a in names for b in names if a < b and rng.random() < 0.3]
        graph = graph_of(edges)
        assert net.louvain(graph) == net.louvain(graph)


# ------------------------------------------------------ Network Risk Score


class TestNetworkRiskScore:
    def build(self) -> tuple[net.DirectedGraph, dict[str, float]]:
        graph = graph_of([
            ("A", "HUB", 80.0), ("B", "HUB", 60.0), ("C", "HUB", 40.0),
            ("HUB", "TAIL", 30.0), ("D", "E", 10.0),
        ])
        return graph, dict.fromkeys(graph.nodes, 100.0)

    def test_the_score_is_the_published_weighted_combination(self):
        graph, capital = self.build()
        result = net.network_risk_score(graph, capital)
        for name in graph.nodes:
            expected = 100.0 * sum(
                net.NRS_WEIGHTS[key] * result.normalised[key][name]
                for key in net.NRS_WEIGHTS)
            assert result.scores[name] == pytest.approx(expected)

    def test_the_weights_are_the_mandated_ones_and_sum_to_one(self):
        assert net.NRS_WEIGHTS == {"debtrank": 0.45,
                                   "forward_pagerank": 0.35,
                                   "betweenness": 0.20}
        assert sum(net.NRS_WEIGHTS.values()) == pytest.approx(1.0)

    def test_every_score_is_within_zero_and_one_hundred(self):
        graph, capital = self.build()
        result = net.network_risk_score(graph, capital)
        assert all(0.0 <= value <= 100.0 for value in result.scores.values())

    def test_the_components_are_kept_not_discarded(self):
        graph, capital = self.build()
        payload = net.network_risk_score(graph, capital).for_borrower("HUB")
        assert set(payload["components"]) == set(net.NRS_WEIGHTS)
        assert set(payload["normalised_components"]) == set(net.NRS_WEIGHTS)
        assert payload["weights"] == net.NRS_WEIGHTS

    def test_it_carries_the_mandated_label_everywhere_it_is_shown(self):
        graph, capital = self.build()
        result = net.network_risk_score(graph, capital)
        for name in ("HUB", "NOT-A-NODE"):
            label = result.for_borrower(name)["label"]
            for phrase in ("NETWORK RISK SCORE", "RELATIVE NETWORK RANKING",
                           "NOT A PROBABILITY", "NOT PD", "NOT A RATING",
                           "NOT IFRS 9 STAGE", "NOT ECL"):
                assert phrase in label

    def test_a_borrower_outside_the_network_is_not_available_not_zero(self):
        """Zero would read as "no network risk". It is "no network"."""
        graph, capital = self.build()
        payload = net.network_risk_score(graph, capital).for_borrower("GHOST")
        assert payload["status"] == "NOT_AVAILABLE"
        assert payload["network_risk_score"] is None

    def test_rank_one_is_the_highest_score(self):
        graph, capital = self.build()
        result = net.network_risk_score(graph, capital)
        top = max(result.scores, key=lambda n: (result.scores[n], n))
        assert result.rank(top) == 1

    def test_a_flat_population_normalises_to_zero_not_to_the_top(self):
        """Every borrower identical. Nobody is unusually central."""
        graph = graph_of([("A", "B", 10.0), ("B", "A", 10.0)])
        result = net.network_risk_score(graph, {"A": 100.0, "B": 100.0})
        assert all(value == pytest.approx(0.0)
                   for value in result.scores.values())

    def test_two_runs_agree(self):
        graph, capital = self.build()
        assert (net.network_risk_score(graph, capital).scores
                == net.network_risk_score(graph, capital).scores)


# -------------------------------------------------------------- similarity


def people_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    base = {"edge_id": "", "role": "", "ownership_pct": float("nan"),
            "voting_pct": float("nan"), "valid_from": "2020-01-01",
            "valid_to": "", "recorded_at": "2020-01-01",
            "source": "Commercial Registry filing", "confidence": 0.97,
            "origin": graphdata.ORIGIN}
    return pd.DataFrame([{**base, **row, "edge_id": f"E-{i:04d}"}
                         for i, row in enumerate(rows)])


class TestSimilarity:
    def test_jaccard_is_the_intersection_over_the_union(self):
        assert net.jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(0.5)

    def test_two_empty_evidence_sets_are_unknown_not_identical(self):
        """0/0 = 1 would rank the least documented borrowers as best matches."""
        assert net.jaccard(set(), set()) == 0.0

    def test_a_shared_director_and_address_makes_a_candidate(self):
        people = people_frame([
            {"edge_type": graphdata.DIRECTOR_OF, "from_node": "DIR-1",
             "to_node": "CORP-A"},
            {"edge_type": graphdata.DIRECTOR_OF, "from_node": "DIR-1",
             "to_node": "CORP-B"},
            {"edge_type": graphdata.REGISTERED_AT, "from_node": "CORP-A",
             "to_node": "ADDR-1"},
            {"edge_type": graphdata.REGISTERED_AT, "from_node": "CORP-B",
             "to_node": "ADDR-1"},
        ])
        found = net.similarity_candidates(people, "2026-06-30")
        assert len(found) == 1
        assert (found[0].left, found[0].right) == ("CORP-A", "CORP-B")
        assert found[0].score == pytest.approx(1.0)

    def test_borrowers_sharing_nothing_are_not_candidates(self):
        people = people_frame([
            {"edge_type": graphdata.DIRECTOR_OF, "from_node": "DIR-1",
             "to_node": "CORP-A"},
            {"edge_type": graphdata.DIRECTOR_OF, "from_node": "DIR-2",
             "to_node": "CORP-B"},
        ])
        assert net.similarity_candidates(people, "2026-06-30") == []

    def test_the_edge_never_creates_control_ubo_or_group_membership(self):
        """The three things a dotted line is explicitly not allowed to do."""
        candidate = net.SimilarityCandidate(
            left="CORP-A", right="CORP-B", score=0.9,
            shared=("DIR:DIR-1",), as_of="2026-06-30")
        edge = candidate.to_edge()
        assert edge["creates_control"] is False
        assert edge["creates_ubo"] is False
        assert edge["creates_group_membership"] is False

    def test_the_edge_is_labelled_and_drawn_as_a_candidate(self):
        candidate = net.SimilarityCandidate(
            left="CORP-A", right="CORP-B", score=0.9,
            shared=("DIR:DIR-1",), as_of="2026-06-30")
        edge = candidate.to_edge()
        assert edge["label"] == "HIDDEN RELATIONSHIP CANDIDATE"
        assert edge["presentation"] == "DOTTED"
        assert edge["edge_type"] == "SIMILAR_TO"
        assert "does NOT establish control" in edge["caveat"]

    def test_the_threshold_is_declared_unverified(self):
        assert "UNVERIFIED POLICY PARAMETER" in net.SIMILARITY_UNVERIFIED

    def test_the_evidence_is_recorded_so_a_reviewer_can_check_it(self):
        people = people_frame([
            {"edge_type": graphdata.DIRECTOR_OF, "from_node": "DIR-1",
             "to_node": "CORP-A"},
            {"edge_type": graphdata.DIRECTOR_OF, "from_node": "DIR-1",
             "to_node": "CORP-B"},
        ])
        found = net.similarity_candidates(people, "2026-06-30")
        assert found[0].shared == ("DIR:DIR-1",)

    def test_evidence_before_the_as_of_date_only(self):
        people = people_frame([
            {"edge_type": graphdata.DIRECTOR_OF, "from_node": "DIR-1",
             "to_node": "CORP-A", "recorded_at": "2020-01-01"},
            {"edge_type": graphdata.DIRECTOR_OF, "from_node": "DIR-1",
             "to_node": "CORP-B", "recorded_at": "2027-01-01"},
        ])
        assert net.similarity_candidates(people, "2026-06-30") == []

    def test_sector_is_not_evidence(self):
        """Every borrower has one. Including it would make everyone similar."""
        assert graphdata.IN_SECTOR not in net.SIMILARITY_EVIDENCE


# -------------------------------------------------------- graph confidence


class TestGraphConfidence:
    def test_confidence_is_the_weakest_link_not_the_average(self):
        path = [{"edge_id": "E1", "confidence": 0.97, "source": "Registry"},
                {"edge_id": "E2", "confidence": 0.58, "source": "RM note"},
                {"edge_id": "E3", "confidence": 0.97, "source": "Registry"}]
        found = net.path_confidence(path)
        assert found.value == pytest.approx(0.58)
        assert found.value != pytest.approx(
            sum(e["confidence"] for e in path) / 3)

    def test_it_names_the_weakest_edge_and_its_source(self):
        path = [{"edge_id": "E1", "confidence": 0.97, "source": "Registry"},
                {"edge_id": "E2", "confidence": 0.58, "source": "RM note"}]
        found = net.path_confidence(path)
        assert found.weakest_edge == "E2"
        assert found.weakest_source == "RM note"

    def test_length_alone_does_not_reduce_confidence(self):
        """The product rule would punish a long chain of certain steps."""
        short = net.path_confidence([{"edge_id": "A", "confidence": 0.9,
                                      "source": "s"}] * 2)
        long = net.path_confidence([{"edge_id": "A", "confidence": 0.9,
                                     "source": "s"}] * 8)
        assert short.value == pytest.approx(long.value)

    def test_no_evidence_is_zero_confidence_not_certainty(self):
        found = net.path_confidence([])
        assert found.value == 0.0
        assert found.band == "LOW"

    def test_the_bands_are_monotone(self):
        assert net.confidence_band(0.95) == "HIGH"
        assert net.confidence_band(0.80) == "MEDIUM"
        assert net.confidence_band(0.40) == "LOW"

    def test_a_path_referencing_a_missing_edge_is_broken_not_weak(self):
        edges = pd.DataFrame([{"edge_id": "E1", "confidence": 0.9,
                               "source": "Registry"}])
        found = net.chain_confidence(edges, ["E1", "E-GONE"])
        assert found.value == 0.0
        assert found.weakest_source == "EDGE NOT FOUND AS AT DATE"

    def test_the_rule_is_named_in_the_payload(self):
        payload = net.path_confidence(
            [{"edge_id": "E1", "confidence": 0.9, "source": "s"}]).to_dict()
        assert payload["rule"] == "WEAKEST_EVIDENCE_ON_PATH"


# --------------------------------------------- against the real universe


class TestAgainstTheUniverse:
    def test_the_exposure_graph_builds_and_carries_the_as_of_date(self, universe):
        frames = universe.frames
        graph = net.exposure_graph(frames["corporate_exposure_network"],
                                   frames["corporate_guarantees"],
                                   "2026-06-30")
        assert graph.size > 0
        assert graph.as_of == "2026-06-30"
        assert (graph.weights >= 0).all()

    def test_pagerank_over_the_real_graph_sums_to_one(self, universe):
        frames = universe.frames
        graph = net.exposure_graph(frames["corporate_exposure_network"],
                                   frames["corporate_guarantees"],
                                   "2026-06-30")
        assert sum(net.pagerank(graph).values()) == pytest.approx(1.0)

    def test_debtrank_over_the_real_graph_stays_bounded(self, universe):
        frames = universe.frames
        graph = net.exposure_graph(frames["corporate_exposure_network"],
                                   frames["corporate_guarantees"],
                                   "2026-06-30")
        capital = dict.fromkeys(graph.nodes, 100.0)
        for seed in list(graph.nodes)[:25]:
            result = net.debtrank(graph, capital, seed)
            assert 0.0 <= result.impact <= 1.0
            assert result.converged
            assert not math.isnan(result.impact)

    def test_similarity_finds_candidates_in_the_real_book(self, universe):
        found = net.similarity_candidates(
            universe.frames["corporate_ownership_edges"], "2026-06-30",
            limit=50)
        assert found, "the synthetic book is built to contain shared evidence"
        assert all(c.score >= net.SIMILARITY_THRESHOLD for c in found)
