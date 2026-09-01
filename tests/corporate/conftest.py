"""One universe, built once, shared by the whole corporate suite.

Building it costs six seconds and assembling the snapshot another seven. Doing
that per test would put two minutes of generation into a suite that is
otherwise instant, and every test here asserts on the SAME universe by design:
the generator is deterministic, so a property that holds for one build holds
for all of them.
"""

from __future__ import annotations

import pytest

from backend.corporate import snapshot as snapshot_mod
from backend.corporate import universe as universe_mod


@pytest.fixture(scope="session")
def universe():
    return universe_mod.build()


@pytest.fixture(scope="session")
def snapshot(universe):
    return snapshot_mod.assemble(universe)


@pytest.fixture(scope="session")
def graph_period(universe):
    """The one quarter the suite derives the graph for."""
    return universe.quarters[-1]


@pytest.fixture(scope="session")
def graph_frames(universe, graph_period):
    """The derived graph, for ONE quarter.

    A full sixteen-quarter derivation is about five minutes. Deriving one
    quarter costs eighteen seconds and exercises exactly the same code path,
    and the tests that matter here are about what the derivation produces, not
    about how many quarters it produced it for. The one test that cares about
    the multi-quarter behaviour - that an underived quarter keeps its sentinel
    rather than inheriting a derived one - gets that for free from this
    fixture, because fifteen quarters are underived.
    """
    from backend.corporate import graphsummary as graphsummary_mod
    return graphsummary_mod.build(universe, periods=[graph_period])


@pytest.fixture(scope="session")
def graph_snapshot(universe, graph_frames):
    from backend.corporate import graphsummary as graphsummary_mod
    return snapshot_mod.assemble(
        universe, graph=graph_frames[graphsummary_mod.GROUPS_DATASET])
