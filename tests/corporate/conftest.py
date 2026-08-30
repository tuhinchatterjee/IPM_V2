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
