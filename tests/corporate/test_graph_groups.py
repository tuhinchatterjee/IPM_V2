"""Connected-counterparty candidate groups. Phase 2.6, 2.7, 2.8.

The rule under test is an ORDER, not a formula: control first, then weak
components over the CONTROL graph, then validated economic interdependence
merged in, with every member keeping the criterion that put it there.

The failure this guards against is percolation. Run weak connectivity over
raw OWNS and a common minority investor, a shared funder or the assessing
bank itself merges the entire portfolio into one "group" that is both useless
and confidently wrong.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.corporate import graphmath as gm


def graph(nodes, ownership, voting=None):
    owned = np.array(ownership, dtype=float)
    votes = np.array(voting if voting is not None else ownership, dtype=float)
    return gm.OwnershipGraph(tuple(nodes), owned, votes, "2026-06-30",
                             gm._components(owned))


class TestInterdependencePredicates:
    def test_every_framework_predicate_is_named(self):
        for name in ("RECEIPT_DEPENDENCE", "EXPENDITURE_DEPENDENCE",
                     "GUARANTEE_OF_EXPOSURE", "NON_SUBSTITUTABLE_OUTPUT",
                     "SAME_REPAYMENT_SOURCE", "DIFFICULTY_TRANSMISSION",
                     "JOINT_INSOLVENCY",
                     "SAME_NON_REPLACEABLE_FUNDING_SOURCE"):
            assert name in gm.PREDICATES

    def test_each_finding_records_its_test_not_just_its_verdict(
            self, universe):
        found = gm.interdependence_predicates(
            universe["corporate_supply_chain"],
            universe["corporate_guarantees"],
            universe["corporate_exposure_network"], "Q2 2026")
        assert len(found) > 100
        for column in ("predicate", "observed_value", "threshold", "inputs",
                       "evidence", "source", "effective_date", "verified_on",
                       "policy_version", "status"):
            assert column in found.columns
        assert (found["threshold"] >= 0).all()
        assert found["evidence"].str.len().min() > 10

    def test_a_non_binding_comfort_letter_is_a_candidate_not_a_finding(
            self, universe):
        """A comfort letter is not a guarantee and must not group anybody."""
        found = gm.interdependence_predicates(
            universe["corporate_supply_chain"],
            universe["corporate_guarantees"],
            universe["corporate_exposure_network"], "Q2 2026")
        guarantees = found[found["predicate"] == gm.GUARANTEE_OF_EXPOSURE]
        candidates = guarantees[
            guarantees["status"] == gm.PREDICATE_CANDIDATE]
        assert len(candidates) > 0
        assert all(not row["inputs"]["legally_binding"]
                   for _, row in candidates.iterrows())

    def test_a_candidate_predicate_does_not_form_a_group(self):
        closure = gm.control_closure(graph("AB", [[0, 0], [0, 0]]))
        pending = pd.DataFrame([{
            "from_node": "A", "to_node": "B",
            "predicate": gm.GUARANTEE_OF_EXPOSURE, "observed_value": 0.0,
            "threshold": 50.0, "inputs": {}, "evidence": "comfort letter",
            "status": gm.PREDICATE_CANDIDATE}])
        groups = gm.connected_groups(closure, pending, population=2)
        assert groups.group_of.get("A") != groups.group_of.get("B") or (
            groups.group_of.get("A") is None)

    def test_the_predicate_respects_the_as_of_predicate(self, universe):
        early = gm.interdependence_predicates(
            universe["corporate_supply_chain"],
            universe["corporate_guarantees"],
            universe["corporate_exposure_network"], "Q4 2023")
        late = gm.interdependence_predicates(
            universe["corporate_supply_chain"],
            universe["corporate_guarantees"],
            universe["corporate_exposure_network"], "Q2 2026")
        assert len(early) < len(late)


class TestGroupFormation:
    def test_control_forms_a_group(self):
        g = graph("ABC", [[0, .6, 0], [0, 0, .6], [0, 0, 0]])
        groups = gm.connected_groups(gm.control_closure(g), population=3)
        assert groups.group_of["A"] == groups.group_of["C"]

    def test_every_member_keeps_the_criterion_that_placed_it(self):
        g = graph("AB", [[0, .6], [0, 0]])
        groups = gm.connected_groups(gm.control_closure(g), population=2)
        assert gm.CRITERION_CONTROL in groups.criterion_hits["B"]

    def test_validated_interdependence_merges_across_ownership(self):
        """Two borrowers with no shareholder in common, joined by a guarantee."""
        g = graph("AB", [[0, 0], [0, 0]])
        validated = pd.DataFrame([{
            "from_node": "A", "to_node": "B",
            "predicate": gm.GUARANTEE_OF_EXPOSURE, "observed_value": 100.0,
            "threshold": 50.0, "inputs": {}, "evidence": "binding guarantee",
            "status": gm.PREDICATE_VALIDATED}])
        groups = gm.connected_groups(gm.control_closure(g), validated,
                                     population=2)
        assert groups.group_of["A"] == groups.group_of["B"]
        assert gm.CRITERION_INTERDEPENDENCE in groups.criterion_hits["B"]

    def test_the_evidence_answers_why_am_i_in_this_group(self):
        g = graph("AB", [[0, .6], [0, 0]])
        groups = gm.connected_groups(gm.control_closure(g), population=2)
        reasons = groups.evidence["B"]
        assert reasons
        assert reasons[0]["criterion"] == gm.CRITERION_CONTROL
        assert "controls" in reasons[0]["reason"]

    def test_a_group_is_declared_a_candidate_not_a_determination(self):
        g = graph("AB", [[0, .6], [0, 0]])
        groups = gm.connected_groups(gm.control_closure(g), population=2)
        caveat = groups.provenance()["caveat"]
        assert "not regulatory connectedness" in caveat
        assert "candidate" in caveat.lower()


class TestPercolationGuards:
    def test_raw_ownership_components_are_computed_only_for_comparison(
            self, universe):
        """A guard with nothing on the other side of it proves nothing."""
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        raw = gm.raw_ownership_components(g)
        assert "why_not_used" in raw
        assert "not a connected-counterparty rule" in raw["why_not_used"]

    def test_no_group_swallows_the_portfolio(self, universe):
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        closure = gm.control_closure(g)
        predicates = gm.interdependence_predicates(
            universe["corporate_supply_chain"],
            universe["corporate_guarantees"],
            universe["corporate_exposure_network"], "Q2 2026")
        groups = gm.connected_groups(closure, predicates, population=g.size)
        assert not groups.percolation_failed, (
            f"largest group holds {groups.largest_group} of "
            f"{groups.population} entities")
        assert groups.largest_group < g.size * gm.GIANT_COMPONENT_SHARE

    def test_a_large_group_is_routed_to_review(self):
        """Above the configured size a candidate group needs a human."""
        size = gm.REVIEW_GROUP_SIZE + 5
        matrix = np.zeros((size, size))
        matrix[0, 1:] = 0.6
        nodes = [f"E{i}" for i in range(size)]
        g = graph(nodes, matrix)
        groups = gm.connected_groups(gm.control_closure(g), population=size)
        assert groups.needs_review
        assert groups.provenance()["validation_status"] == "FLAG"

    def test_a_shared_minority_investor_does_not_group_the_book(self):
        """The percolation case, in miniature.

        One investor holds 5% of forty otherwise unrelated borrowers. Weak
        connectivity over raw OWNS makes that a single forty-one member
        group. Control-based grouping makes it none.
        """
        size = 41
        matrix = np.zeros((size, size))
        matrix[0, 1:] = 0.05
        nodes = [f"E{i}" for i in range(size)]
        g = graph(nodes, matrix)

        raw = gm.raw_ownership_components(g)
        assert raw["largest"] == size

        groups = gm.connected_groups(gm.control_closure(g), population=size)
        assert groups.largest_group == 0 or groups.largest_group < 3

    def test_a_shared_funder_does_not_group_the_book(self, universe):
        """FUNDED_BY is an observed edge and is never a grouping criterion."""
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        closure = gm.control_closure(g)
        groups = gm.connected_groups(closure, population=g.size)
        assert groups.largest_group < 100


class TestControlGroupingOnTheRealUniverse:
    def test_grouping_is_control_based_not_ownership_based(self, universe):
        """The two rules must give different answers, or one is unused."""
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        closure = gm.control_closure(g)
        predicates = gm.interdependence_predicates(
            universe["corporate_supply_chain"],
            universe["corporate_guarantees"],
            universe["corporate_exposure_network"], "Q2 2026")
        groups = gm.connected_groups(closure, predicates, population=g.size)
        raw = gm.raw_ownership_components(g)
        assert groups.largest_group != raw["largest"]

    def test_every_control_rule_fires_on_real_data(self, universe):
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        hits = gm.control_closure(g).rule_hits
        assert hits["majority_voting"] > 100
        assert hits["de_facto_voting"] > 10

    def test_the_closure_completes_in_reasonable_time(self, universe):
        """The first implementation did not finish inside ten minutes.

        Dense Warshall over every bloc, then an 87-million-iteration Python
        loop. Per-component closure gives the same answer in seconds.
        """
        import time

        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        started = time.time()
        gm.control_closure(g)
        assert time.time() - started < 60
