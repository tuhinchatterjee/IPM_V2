"""The arrears roll-forward, on its own.

R2 §24 asked for the "extreme delinquency (repeated 450-day values)" to be
looked at. It was not extreme, it was mechanical: the loop aged a delinquent
facility by thirty days per QUARTER and clipped the result, so a facility that
fell late early and never cured climbed one rung per quarter and came to rest
on exactly 450 — fifteen quarters times thirty — where it stayed. Forty-eight
facilities shared that value, more than any other number above ninety.

Two things were wrong and both are structural, so both are tested here rather
than asserted about the built lake: a quarter is about ninety days, not thirty,
and a book resolves its deep arrears rather than carrying them forever.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _generator():
    """Import the generator script by path; it is not a package module."""
    name = "generate_saudi_universe"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _generator()


def run(gen, quarters, stress_level, seed=7, n=4000):
    """Roll a book of identical borrowers forward, and keep every snapshot."""
    rng = np.random.default_rng(seed)
    dpd = np.zeros(n, dtype=int)
    stress = np.full(n, stress_level)
    history = []
    for _ in range(quarters):
        dpd = gen.age_delinquency(dpd, stress, 0.0, rng)
        history.append(dpd.copy())
    return history


class TestAgeing:
    def test_a_delinquent_facility_ages_by_a_quarter(self, gen):
        """Not by a month. This is the whole 450 artefact in one line."""
        rng = np.random.default_rng(1)
        aged = gen.age_delinquency(np.full(500, 120), np.full(500, -4.0), 0.0,
                                   rng)
        moved = aged[aged > 0]
        assert moved.size, "a book this healthy should not cure every case"
        assert set(np.unique(moved)) == {120 + gen.QUARTER_DAYS}

    def test_a_current_facility_that_falls_late_starts_inside_a_bucket(
            self, gen):
        rng = np.random.default_rng(2)
        aged = gen.age_delinquency(np.zeros(4000, dtype=int),
                                   np.full(4000, 3.5), 0.0, rng)
        late = set(np.unique(aged[aged > 0]))
        assert late <= {30, 60}, late
        assert late == {30, 60}, "both entry points should occur"

    def test_nothing_survives_past_the_workout_horizon(self, gen):
        history = run(gen, quarters=20, stress_level=3.0)
        worst = max(int(snapshot.max()) for snapshot in history)
        assert worst <= gen.WORKOUT_HORIZON_DAYS, worst

    def test_no_single_arrears_value_dominates_the_tail(self, gen):
        """The artefact, stated as a property.

        A ladder that ends at a clip puts a pile on the top rung. A book that
        resolves its cases does not: the deep tail should thin out.
        """
        final = run(gen, quarters=20, stress_level=2.4)[-1]
        deep = final[final >= 180]
        assert deep.size >= 30, "need a tail to say anything about its shape"
        counts = np.bincount(deep)
        assert counts.max() / deep.size < 0.65, (
            f"one arrears value holds {counts.max()}/{deep.size} of the deep "
            f"tail")

    def test_the_tail_is_thinner_than_the_shoulder(self, gen):
        """Monotone decay, which a clipped ladder does not have."""
        final = run(gen, quarters=20, stress_level=2.4)[-1]
        shoulder = int(((final >= 90) & (final < 210)).sum())
        tail = int((final >= 300).sum())
        assert shoulder > tail, (shoulder, tail)

    def test_a_healthy_book_stays_almost_entirely_current(self, gen):
        final = run(gen, quarters=20, stress_level=-1.5)[-1]
        assert (final > 0).mean() < 0.05

    def test_a_stressed_book_is_not_entirely_delinquent(self, gen):
        """Curing and resolution both keep the level down."""
        final = run(gen, quarters=20, stress_level=2.4)[-1]
        assert 0.02 < (final > 0).mean() < 0.60

    def test_the_roll_forward_is_deterministic_for_a_seed(self, gen):
        first = run(gen, quarters=8, stress_level=1.0, seed=11)[-1]
        again = run(gen, quarters=8, stress_level=1.0, seed=11)[-1]
        assert np.array_equal(first, again)

    def test_arrears_are_never_negative(self, gen):
        for level in (-2.0, 0.0, 2.0, 4.0):
            final = run(gen, quarters=12, stress_level=level)[-1]
            assert (final >= 0).all()
