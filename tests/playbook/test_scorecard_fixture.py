"""The demonstration's scorecard statistics are computed. PB-027.

§14 draws a line: a figure presented as computed must be computed from
synthetic inputs, and a figure that is a fixed illustrative assumption must say
so. These tests hold that line — a constant typed into the fixture and then
described as a model run would fail here.
"""

from __future__ import annotations

from backend.playbook.fixtures import scorecard as sc


class TestTheStatisticsAreDerivedNotDeclared:
    def test_changing_the_population_changes_every_statistic(self):
        """The proof that these are computed: move the inputs, and the outputs
        move with them. A hard-coded figure would not."""
        base = sc.development()
        shifted = sc._sample("shifted", seed=sc.SEED, good_mean=640,
                             bad_mean=620)
        assert sc.auc(shifted) < sc.auc(base)
        assert sc.gini(shifted) < sc.gini(base)
        assert sc.ks(shifted) < sc.ks(base)

    def test_gini_is_derived_from_auc(self):
        sample = sc.development()
        assert abs(sc.gini(sample) - (2 * sc.auc(sample) - 1)) < 1e-12

    def test_a_perfectly_separated_population_scores_one(self):
        perfect = sc.Sample("perfect", goods=(800, 810, 820), bads=(400, 410))
        assert sc.auc(perfect) == 1.0
        assert sc.gini(perfect) == 1.0

    def test_an_indistinguishable_population_scores_a_half(self):
        """Identical scores are all ties, and ties count a half."""
        flat = sc.Sample("flat", goods=(600, 600, 600), bads=(600, 600))
        assert sc.auc(flat) == 0.5
        assert sc.gini(flat) == 0.0

    def test_a_reversed_population_scores_below_a_half(self):
        reversed_sample = sc.Sample("reversed", goods=(400, 410), bads=(800, 810))
        assert sc.auc(reversed_sample) == 0.0


class TestTheFiguresAreCredible:
    def test_discrimination_is_in_the_range_a_scorecard_lives_in(self):
        dev = sc.development()
        assert 0.75 <= sc.auc(dev) <= 0.95
        assert 0.50 <= sc.gini(dev) <= 0.90

    def test_the_recent_sample_discriminates_slightly_less(self):
        """A validation report with no movement at all is not a useful
        demonstration of a validation report."""
        assert sc.auc(sc.recent()) < sc.auc(sc.development())

    def test_ks_is_a_proportion(self):
        assert 0.0 <= sc.ks(sc.development()) <= 1.0

    def test_psi_is_non_negative_and_stable_between_these_two_samples(self):
        value = sc.psi(sc.development(), sc.recent())
        assert value >= 0
        assert value < 0.10, "these two samples are meant to be stable"

    def test_psi_of_a_sample_against_itself_is_zero(self):
        dev = sc.development()
        assert sc.psi(dev, dev) < 1e-12


class TestItIsReproducible:
    def test_two_runs_produce_identical_figures(self):
        assert sc.headline() == sc.headline()

    def test_the_bands_partition_the_score_range_without_gaps(self):
        edges = [(low, high) for _, low, high in sc.BANDS]
        for (_, high), (low, _) in zip(edges[:-1], edges[1:], strict=True):
            assert high == low, "a score between two bands would be counted nowhere"

    def test_every_row_of_the_band_table_accounts_for_its_population(self):
        dev = sc.development()
        rows = sc.band_performance(dev)
        counted = sum(int(r[1]) for r in rows)
        assert counted == len(dev.goods) + len(dev.bads)

    def test_the_psi_table_sums_to_the_psi(self):
        """The table shows four decimal places, so its rows sum to the exact
        PSI only to that precision. Asserting more would be asserting that
        rounding does not happen."""
        dev, now = sc.development(), sc.recent()
        rows = sc.psi_table(dev, now)
        total = sum(float(r[3]) for r in rows)
        assert round(total, 3) == round(sc.psi(dev, now), 3)
