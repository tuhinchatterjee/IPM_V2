"""The observed graph. B13, B15, B16, B17.

The centre of gravity here is B16's as-of predicate. Two of its three clauses
are memorable and the third is not, and a graph filtered on two of them fails
in the worst possible way: it returns MORE edges, never an error, so a
demonstration quietly acquires knowledge nobody had at the time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.corporate import graphdata as graph_mod
from backend.corporate import universe as universe_mod


@pytest.fixture(scope="module")
def edges(universe):
    return universe["corporate_ownership_edges"]


@pytest.fixture(scope="module")
def nodes(universe):
    return universe["corporate_graph_nodes"]


class TestNodeAndEdgeTypes:
    def test_b15_node_types_are_all_defined(self):
        for expected in ("Corporate", "NaturalPerson", "Address", "Director",
                         "Facility", "Guarantee", "FinancialStatement",
                         "Sector", "FundingSource", "ConnectedGroup",
                         "RegistryRecord", "AssessingInstitution"):
            assert expected in graph_mod.NODE_TYPES

    def test_b13_observed_edge_types_are_all_defined(self):
        for expected in ("OWNS", "CONTROLS", "DIRECTOR_OF", "PROVIDES",
                         "COVERS", "HOLDS", "LENT_TO", "SUPPLIES_TO",
                         "EXPOSED_TO", "FUNDED_BY", "IN_SECTOR",
                         "REGISTERED_AT"):
            assert expected in graph_mod.OBSERVED_EDGE_TYPES

    def test_guarantees_are_reified_nodes(self, nodes, universe):
        """B15: a guarantee is a node, not an edge.

        One guarantee can cover several facilities and be given by several
        guarantors jointly. As an edge that fact is duplicated once per
        facility, and the duplicates drift apart the first time one is
        amended.
        """
        guarantees = nodes[nodes["node_type"] == graph_mod.GUARANTEE]
        assert len(guarantees) > 0
        edges = universe["corporate_guarantees"]
        covers = edges[edges["edge_type"] == graph_mod.COVERS]
        multi = covers.groupby("guarantee_id").size()
        assert (multi > 1).any(), (
            "no guarantee covers more than one facility, so reifying it "
            "proves nothing")

    def test_every_edge_endpoint_is_a_known_node(self, edges, nodes):
        known = set(nodes["node_id"])
        unknown = (set(edges["from_node"]) | set(edges["to_node"])) - known
        assert unknown == set(), f"edges point at unknown nodes: {list(unknown)[:5]}"


class TestBitemporal:
    def test_every_edge_carries_all_five_required_columns(self, edges):
        for column in ("valid_from", "valid_to", "recorded_at", "source",
                       "confidence"):
            assert column in edges.columns

    def test_nothing_is_recorded_before_it_became_true(self, edges):
        assert (edges["recorded_at"] >= edges["valid_from"]).all()

    def test_recording_genuinely_lags(self, edges):
        """If recorded_at always equalled valid_from the third clause of B16
        would be untestable, because it could never exclude anything."""
        lag = (pd.to_datetime(edges["recorded_at"])
               - pd.to_datetime(edges["valid_from"])).dt.days
        assert lag.median() > 30
        assert lag.max() > 365

    def test_as_of_excludes_edges_that_had_not_started(self, edges):
        view = graph_mod.as_of(edges, "Q4 2023")
        assert (view["valid_from"] <= "2023-12-31").all()

    def test_as_of_excludes_edges_that_had_already_ended(self, edges):
        view = graph_mod.as_of(edges, "Q4 2023")
        closed = view[view["valid_to"] != ""]
        assert (closed["valid_to"] > "2023-12-31").all()

    def test_as_of_excludes_edges_recorded_later(self, edges):
        """B16's third clause. This is the leakage test.

        An edge valid from 2021 but only learned in 2025 must not appear in a
        2023 view, however true it was.
        """
        view = graph_mod.as_of(edges, "Q4 2023")
        assert (view["recorded_at"] <= "2023-12-31").all()

    def test_the_third_clause_actually_excludes_something(self, edges):
        """A guard that never fires is a guard nobody has tested.

        Filtering on validity alone and on all three clauses must give
        different answers, or the leakage test above is vacuous.
        """
        stamp = "2023-12-31"
        open_ended = edges["valid_to"].isna() | (edges["valid_to"] == "")
        validity_only = edges[
            (edges["valid_from"] <= stamp)
            & (open_ended | (edges["valid_to"] > stamp))]
        full = graph_mod.as_of(edges, "Q4 2023")
        assert len(full) < len(validity_only), (
            "the recorded_at clause excluded nothing, so a graph filtered "
            "without it would look identical and the leak would be invisible")

    def test_the_graph_grows_as_the_window_advances(self, edges):
        sizes = [len(graph_mod.as_of(edges, q))
                 for q in ("Q3 2022", "Q4 2023", "Q2 2026")]
        assert sizes[0] < sizes[1] < sizes[2]

    def test_a_quarter_label_and_its_date_give_the_same_view(self, edges):
        assert len(graph_mod.as_of(edges, "Q4 2023")) == len(
            graph_mod.as_of(edges, "2023-12-31"))


class TestOwnershipVersusVoting:
    def test_both_percentages_are_carried_separately(self, edges):
        owns = edges[edges["edge_type"] == graph_mod.OWNS]
        assert owns["ownership_pct"].notna().all()
        assert owns["voting_pct"].notna().all()

    def test_they_genuinely_diverge(self, edges):
        """B17. If voting always equalled ownership the column would be a
        copy, and every control question would silently be answered with an
        economic one."""
        owns = edges[edges["edge_type"] == graph_mod.OWNS]
        differ = (owns["voting_pct"] != owns["ownership_pct"]).mean()
        assert 0.05 < differ < 0.50, f"{differ:.1%} of holdings diverge"

    def test_voting_diverges_in_both_directions(self, edges):
        owns = edges[edges["edge_type"] == graph_mod.OWNS]
        gap = owns["voting_pct"] - owns["ownership_pct"]
        assert (gap > 0).any() and (gap < 0).any()

    def test_percentages_stay_inside_zero_to_one_hundred(self, edges):
        owns = edges[edges["edge_type"] == graph_mod.OWNS]
        for column in ("ownership_pct", "voting_pct"):
            assert owns[column].between(0, 100).all()


class TestStructure:
    def test_pyramids_exist(self, edges):
        """Effective ownership must need the whole chain somewhere."""
        owns = edges[edges["edge_type"] == graph_mod.OWNS]
        intermediate = owns[owns["to_node"].astype(str).str.endswith("-M")]
        assert len(intermediate) > 50

    def test_cross_holdings_exist(self, edges):
        """(I - A) has to be worth inverting rather than a chain worth
        multiplying."""
        owns = edges[edges["edge_type"] == graph_mod.OWNS]
        corporate_to_corporate = owns[
            owns["from_node"].astype(str).str.startswith("CORP-")
            & owns["to_node"].astype(str).str.startswith("CORP-")]
        assert len(corporate_to_corporate) > 20

    def test_the_graph_is_not_one_giant_blob(self, edges):
        """B22's guard needs something to guard.

        If every borrower were reachable from every other, connectedness would
        carry no information and the giant-component check could never be
        exercised on real structure.
        """
        owns = graph_mod.as_of(edges, "Q2 2026")
        owns = owns[owns["edge_type"] == graph_mod.OWNS]
        parent: dict[str, str] = {}

        def find(node: str) -> str:
            parent.setdefault(node, node)
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for a, b in zip(owns["from_node"], owns["to_node"], strict=True):
            ra, rb = find(str(a)), find(str(b))
            if ra != rb:
                parent[ra] = rb

        sizes: dict[str, int] = {}
        for node in list(parent):
            root = find(node)
            sizes[root] = sizes.get(root, 0) + 1
        largest = max(sizes.values())
        assert largest < len(parent) * 0.20, (
            f"largest ownership component holds {largest} of {len(parent)} "
            "nodes; the universe is one blob and connectedness means nothing")

    def test_directors_sit_on_more_than_one_board(self, universe):
        """B7 precedence 3 and hidden-relationship discovery both need this."""
        edges = universe["corporate_ownership_edges"]
        directors = edges[edges["edge_type"] == graph_mod.DIRECTOR_OF]
        seats = directors.groupby("from_node").size()
        assert (seats > 1).sum() > 500

    def test_addresses_are_shared(self, universe):
        edges = universe["corporate_ownership_edges"]
        registered = edges[edges["edge_type"] == graph_mod.REGISTERED_AT]
        occupants = registered.groupby("to_node").size()
        assert (occupants > 1).sum() > 100


class TestConfidence:
    def test_confidence_is_a_property_of_the_source(self, edges):
        owns = edges[edges["edge_type"] == graph_mod.OWNS]
        per_source = owns.groupby("source")["confidence"].nunique()
        assert (per_source == 1).all(), (
            "confidence varies within a source, so it is not the source's "
            "reliability but a number invented per edge")

    def test_a_registry_filing_outranks_a_relationship_manager_note(
            self, edges):
        owns = edges[edges["edge_type"] == graph_mod.OWNS]
        means = owns.groupby("source")["confidence"].first()
        assert (means["Commercial Registry filing"]
                > means["Relationship manager note"])

    def test_asserted_indirect_exposure_is_capped_below_a_booked_claim(
            self, universe):
        network = universe["corporate_exposure_network"]
        asserted = network[network["edge_type"] == graph_mod.EXPOSED_TO]
        booked = network[network["edge_type"] == graph_mod.LENT_TO]
        assert asserted["confidence"].max() <= booked["confidence"].min() + 1e-9


class TestSupplyChain:
    def test_dependence_is_directional(self, universe):
        supply = universe["corporate_supply_chain"]
        assert not np.allclose(supply["supplier_revenue_share_pct"],
                               supply["buyer_cost_share_pct"])

    def test_the_regulatory_caveat_is_on_every_row(self, universe):
        supply = universe["corporate_supply_chain"]
        assert supply["caveat"].str.contains("B21").all()

    def test_no_borrower_supplies_itself(self, universe):
        supply = universe["corporate_supply_chain"]
        assert (supply["from_node"] != supply["to_node"]).all()

    def test_sector_flows_are_plausible(self, universe):
        """A hospital does not buy cement."""
        supply = universe["corporate_supply_chain"]
        master = universe["corporate_customer_master"].drop_duplicates(
            "borrower_id").set_index("borrower_id")["sector"]
        buyers = supply["to_node"].map(master)
        suppliers = supply["from_node"].map(master)
        pairs = set(zip(buyers, suppliers, strict=True))
        assert ("Healthcare", "Mining & Metals") not in pairs


class TestPeriodsArgument:
    def test_a_short_build_produces_a_short_graph(self):
        short = universe_mod.build(periods=universe_mod.QUARTERS[:2])
        assert short["corporate_customer_master"]["period"].nunique() == 2
