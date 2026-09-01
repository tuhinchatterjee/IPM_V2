"""Performance regressions for the graph derivation. Phase 2.19.

Every bound here is at least three times the measured cost, because a
performance test that fails on a slow CI runner gets deleted rather than
investigated. They exist to catch the class of regression that took control
closure from 2.5 seconds to over ten minutes: an algorithm that was quietly
replaced by one with a worse complexity, not a machine that was 20% slower.

Each bound records what it is protecting against.
"""

from __future__ import annotations

import time

import pytest

from backend.corporate import graphmath as gm
from backend.corporate import graphquality as gq
from backend.corporate import graphsummary as gs
from backend.corporate import network as net

AS_OF = "2026-06-30"


@pytest.fixture(scope="module")
def ownership(universe):
    return gm.build_ownership_graph(
        universe["corporate_ownership_edges"], AS_OF)


@pytest.fixture(scope="module")
def exposure(universe):
    return net.exposure_graph(universe["corporate_exposure_network"],
                              universe["corporate_guarantees"], AS_OF)


def elapsed(work) -> tuple[object, float]:
    started = time.perf_counter()
    result = work()
    return result, time.perf_counter() - started


class TestOwnershipMathematics:
    def test_the_ownership_graph_builds_in_seconds(self, universe):
        """9,333 nodes. A per-edge Python loop over a dense matrix would not."""
        _, seconds = elapsed(lambda: gm.build_ownership_graph(
            universe["corporate_ownership_edges"], AS_OF))
        assert seconds < 30, f"ownership graph took {seconds:.1f}s"

    def test_effective_ownership_solves_per_component(self, ownership):
        """A single dense solve over 9,333 nodes is a 9,333 x 9,333 inverse.

        Per component it is a few thousand small solves. If this ever creeps
        past the bound, the block-diagonal decomposition has been lost.
        """
        _, seconds = elapsed(lambda: gm.effective_ownership(ownership))
        assert seconds < 30, f"effective ownership took {seconds:.1f}s"

    def test_control_closure_stays_per_component(self, ownership):
        """The regression that matters most in this file.

        A dense Warshall over ~9,000 blocs is 87 million Python iterations and
        took over ten minutes. Per component it is 2.5 seconds and gives
        identical answers. A change that reintroduces the dense form will not
        look wrong in review; it will just be slow, and only this catches it.
        """
        _, seconds = elapsed(lambda: gm.control_closure(ownership))
        assert seconds < 60, f"control closure took {seconds:.1f}s"

    def test_connected_groups_are_cheap_once_control_is_known(
            self, universe, ownership):
        closure = gm.control_closure(ownership)
        interdependence = gm.interdependence_predicates(
            universe["corporate_supply_chain"],
            universe["corporate_guarantees"],
            universe["corporate_exposure_network"], AS_OF)
        _, seconds = elapsed(lambda: gm.connected_groups(
            closure, interdependence, population=3_800))
        assert seconds < 15, f"connected groups took {seconds:.1f}s"


class TestNetworkAnalytics:
    def test_the_all_seeds_debtrank_sweep_shares_one_impact_matrix(
            self, exposure, universe):
        """2,960 seeds over a 2,960 x 2,960 matrix.

        Rebuilding the matrix per seed made this the entire cost of the
        derivation and none of it was arithmetic anyone needed. The bound is
        set low enough that the per-seed rebuild cannot pass it.
        """
        capital = dict.fromkeys(exposure.nodes, 100.0)
        _, seconds = elapsed(lambda: net.debtrank_all(exposure, capital))
        assert seconds < 45, f"DebtRank sweep took {seconds:.1f}s"

    def test_centrality_over_the_real_graph(self, exposure):
        def run():
            net.pagerank(exposure)
            net.pagerank(exposure, reverse=True)
            net.betweenness(exposure)
            net.louvain(exposure)

        _, seconds = elapsed(run)
        assert seconds < 30, f"centrality took {seconds:.1f}s"

    def test_similarity_uses_an_inverted_index(self, universe):
        """All-pairs over 3,800 borrowers is 7.2 million comparisons for a
        result that is almost entirely zeros. Two borrowers with no shared
        token cannot have a non-zero Jaccard, so only sharers are compared."""
        _, seconds = elapsed(lambda: net.similarity_candidates(
            universe["corporate_ownership_edges"], AS_OF, limit=500))
        assert seconds < 20, f"similarity took {seconds:.1f}s"


class TestTheGateAndTheWholeDerivation:
    def test_the_quality_gate_is_cheap_enough_to_run_every_time(
            self, universe):
        """A gate people are tempted to skip for speed is a gate that gets
        skipped. Fifteen checks over 43,000 edges take about a second."""
        _, seconds = elapsed(lambda: gq.run(universe.frames, AS_OF))
        assert seconds < 15, f"quality gate took {seconds:.1f}s"

    def test_one_quarter_of_the_whole_derivation(self, universe):
        """End to end: gate, ownership, control, groups, network, summary.

        Measured at about 18 seconds for 3,253 borrowers. The bound is three
        times that, so all sixteen quarters stay inside a five-minute build.
        """
        master = universe["corporate_customer_master"]
        period = universe.quarters[-1]
        block = master[master["period"] == period]
        borrowers = sorted(block["borrower_id"].astype(str).unique())

        result, seconds = elapsed(lambda: gs.derive(
            universe.frames, period, AS_OF, borrowers))
        assert seconds < 90, f"one quarter took {seconds:.1f}s"
        assert len(result.rows) == len(borrowers)

        # The stage timings are recorded, so a future regression can be
        # attributed rather than guessed at.
        assert set(result.timings) >= {
            "quality", "ownership_graph", "effective_ownership",
            "control_closure", "connected_groups"}
        assert all(value >= 0 for value in result.timings.values())
