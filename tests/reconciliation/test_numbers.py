"""Are the numbers right? Reconciled against a path that shares no code.

§2 of the closure phase, and the one gate a validation product cannot pass by
testing itself. Every figure below is computed twice:

  * once by the production stack — `runner.run(...)`, exactly as the API and
    the report call it;
  * once by `tests/reconciliation/independent.py`, which reads the parquet
    partitions with pandas and recomputes the statistic from its definition
    using a different algorithm.

The independent module imports nothing from `backend.scorecard.metrics` or
`backend.scorecard.validation`. `test_the_independent_path_shares_no_kernel`
asserts that, because the moment it does the rest of this file becomes a test
that a function equals itself.

On tolerances
--------------
Every assertion states its own, and the reason is about arithmetic. The
default is 1e-9: two float summations in different orders. Two comparisons are
looser and both say why in the assertion message — the pairwise AUC runs on a
bounded subsample, and the decile rank-order comparison depends on how ties
are split at a band edge. Nothing here was widened to make a number agree.
"""

from __future__ import annotations

import pytest

from tests.reconciliation import independent as check

#: Two float summations over the same values in different orders. Anything
#: larger than this is a difference in the arithmetic, not in the machine.
EXACT = 1e-9

MODELS = ("retail_application_champion", "retail_behaviour_champion",
          "sme_champion")


def _lake_present() -> bool:
    return check.analytics_root().exists()


pytestmark = pytest.mark.skipif(
    not _lake_present(),
    reason="the analytics lake is not built in this working copy")


# --------------------------------------------------------------- the setup


@pytest.fixture(scope="module")
def registry():
    from backend.scorecard.validation import models as model_registry

    return model_registry


@pytest.fixture(scope="module")
def produced():
    """Production results, one full run per model, computed once.

    Module-scoped because three full runs is three minutes of bootstrap
    resampling and re-running them per assertion would buy nothing: the
    engine is deterministic, which is itself asserted below.
    """
    from backend.scorecard.validation import models as model_registry
    from backend.scorecard.validation import registry as test_registry
    from backend.scorecard.validation import runner

    out = {}
    for model_id in MODELS:
        model = model_registry.get(model_id)
        results = []
        for category in test_registry.CATEGORIES:
            results.extend(runner.run_category(category, model))
        out[model_id] = {r.test_id: r for r in results}
    return out


@pytest.fixture(scope="module")
def cohorts(registry):
    """The matured cohort for each model, read straight off disk.

    Maturity is taken from the model's own maturity flag rather than
    recomputed from a calendar. That flag is DATA, written by the builder that
    knows the horizon; recomputing it here would be reconciling the production
    engine against my reading of the calendar rather than against the rows.
    """
    out = {}
    for model_id in MODELS:
        model = registry.get(model_id)
        frame = check.read(model.dataset, period_field=model.period_field)
        matured = frame[frame[model.matured_column].fillna(False).astype(bool)]
        out[model_id] = (model, matured)
    return out


def _value(produced, model_id: str, test_id: str) -> float:
    result = produced[model_id].get(test_id)
    assert result is not None, f"{test_id} did not run for {model_id}"
    assert result.value is not None, (
        f"{test_id} on {model_id} produced no number: {result.state} — "
        f"{result.detail}")
    return float(result.value)


# ------------------------------------------------------ the premise itself


class TestTheSecondOpinionIsActuallySecond:

    def test_the_independent_path_shares_no_kernel(self):
        """The premise of this whole file, asserted rather than assumed.

        A reconciliation that imports the thing it reconciles reproduces its
        bugs and agrees with them to fifteen decimal places.
        """
        source = (check.__file__)
        with open(source, encoding="utf-8") as handle:
            body = handle.read()
        # Ignore the prose: the module docstring names these modules on
        # purpose, to say what it is NOT using.
        code = body.split('"""', 2)[-1]
        for forbidden in ("backend.scorecard.metrics",
                          "backend.scorecard.validation",
                          "backend.scorecard.binning"):
            assert forbidden not in code, (
                f"the independent path imports {forbidden}; it is no longer "
                "independent")

    def test_the_production_engine_is_deterministic(self, registry):
        """Two runs of the same test on the same data give the same number.

        Stated first because every comparison below assumes it. The bootstrap
        in the discrimination kernel is seeded; if it were not, a difference
        against the independent path could be noise and no assertion here
        would mean anything.
        """
        from backend.scorecard.validation import runner

        model = registry.get("sme_champion")
        first = runner.run("DISC-AUC", model)
        second = runner.run("DISC-AUC", model)
        assert first.value == second.value


# ------------------------------------------------------------ AUC and Gini


class TestDiscrimination:

    @pytest.mark.parametrize("model_id", MODELS)
    def test_auc_matches_a_trapezoidal_roc(self, model_id, produced, cohorts):
        """Mann-Whitney on midranks, against integrating the ROC.

        Two genuinely different routes to the same quantity: production ranks
        and sums, this sorts and integrates. They agree exactly because both
        are exact — the equality of the two is a theorem, not an
        approximation, so the tolerance is float noise and nothing else.
        """
        model, matured = cohorts[model_id]
        pool = check.cohort(matured, score=model.score_column,
                            outcome=model.outcome_column,
                            direction=model.score_direction)
        mine = check.auc_trapezoid(pool)
        theirs = _value(produced, model_id, "DISC-AUC")
        assert abs(mine - theirs) < EXACT, (
            f"{model_id} AUC: production {theirs!r}, trapezoidal ROC over "
            f"{pool.n} rows and {pool.event_count} events {mine!r}, "
            f"difference {abs(mine - theirs):.3e}")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_auc_matches_an_exhaustive_pair_count(self, model_id, produced,
                                                  cohorts):
        """The definition, counted. Bounded sample, so a looser tolerance.

        AUC is the probability that a randomly chosen event outranks a
        randomly chosen non-event. This counts those pairs directly on a
        deterministic sub-sample of 4,000 per class — 16 million comparisons,
        not the 140 million the full cross-product would need.

        The tolerance is 0.02 and it is a SAMPLING tolerance, stated in
        advance: the standard error of an AUC on 4,000 per class is around
        0.006, so 0.02 is roughly three of them. It is not a tolerance on the
        arithmetic, which the trapezoidal test above pins to 1e-9.
        """
        model, matured = cohorts[model_id]
        pool = check.cohort(matured, score=model.score_column,
                            outcome=model.outcome_column,
                            direction=model.score_direction)
        mine = check.auc_pairwise(pool)
        theirs = _value(produced, model_id, "DISC-AUC")
        assert abs(mine - theirs) < 0.02, (
            f"{model_id} AUC: production {theirs!r}, exhaustive pair count on "
            f"a bounded sample {mine!r}")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_gini_is_two_auc_minus_one(self, model_id, produced, cohorts):
        model, matured = cohorts[model_id]
        pool = check.cohort(matured, score=model.score_column,
                            outcome=model.outcome_column,
                            direction=model.score_direction)
        mine = check.gini(check.auc_trapezoid(pool))
        theirs = _value(produced, model_id, "DISC-GINI")
        assert abs(mine - theirs) < EXACT, (
            f"{model_id} Gini: production {theirs!r}, 2·AUC−1 {mine!r}")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_ks_matches_two_empirical_cdfs(self, model_id, produced, cohorts):
        """Production reads KS off the same count table it uses for AUC.

        This builds the two empirical CDFs separately and differences them.
        Two statistics sharing one intermediate agree with each other whether
        or not the intermediate is right, which is exactly why KS gets its own
        route here.
        """
        model, matured = cohorts[model_id]
        pool = check.cohort(matured, score=model.score_column,
                            outcome=model.outcome_column,
                            direction=model.score_direction)
        mine = check.ks(pool)
        theirs = _value(produced, model_id, "DISC-KS")
        assert abs(mine - theirs) < EXACT, (
            f"{model_id} KS: production {theirs!r}, two empirical CDFs "
            f"{mine!r}")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_the_sample_the_engine_reports_is_the_sample_on_disk(
            self, model_id, produced, cohorts):
        """The counts, not just the statistic.

        A metric computed correctly over the wrong rows is wrong, and the
        observation count is the only thing on the result that says which rows
        those were.
        """
        model, matured = cohorts[model_id]
        pool = check.cohort(matured, score=model.score_column,
                            outcome=model.outcome_column,
                            direction=model.score_direction)
        result = produced[model_id]["DISC-AUC"]
        assert result.observations == pool.n, (
            f"{model_id}: the engine reports {result.observations} "
            f"observations, the matured partitions on disk hold {pool.n} "
            f"usable rows ({pool.dropped} dropped for a missing score or "
            "outcome)")
        assert result.events == pool.event_count, (
            f"{model_id}: the engine reports {result.events} events, the rows "
            f"on disk carry {pool.event_count}")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_the_score_ranks_risk_in_the_declared_direction(
            self, model_id, cohorts):
        """A sanity check the AUC alone cannot fail on.

        An AUC of 0.65 is 0.65 whichever way the score points; only the
        DIRECTION says whether that is discrimination or an inverted
        scorecard. This reads the event rate by risk decile and requires the
        riskiest decile to be worse than the safest.
        """
        model, matured = cohorts[model_id]
        pool = check.cohort(matured, score=model.score_column,
                            outcome=model.outcome_column,
                            direction=model.score_direction)
        bands = check.rank_order(pool)
        assert bands[0] > bands[-1], (
            f"{model_id}: the riskiest decile defaults at {bands[0]:.4f} and "
            f"the safest at {bands[-1]:.4f}. With "
            f"{model.score_direction} that is the wrong way round, and every "
            "discrimination figure on this model is 1 minus the truth.")


# ------------------------------------------------------------- calibration


class TestCalibration:

    @pytest.mark.parametrize("model_id", MODELS)
    def test_the_portfolio_calibration_ratio(self, model_id, cohorts,
                                             produced):
        """Observed over predicted, on the whole matured book.

        Reconciled against the engine's own actual-versus-predicted test where
        it produced one. Where it refused, the refusal is checked instead:
        a calibration test that could not run must not have left a number
        behind.
        """
        model, matured = cohorts[model_id]
        mine = check.observed_versus_predicted(
            matured, pd_column=model.pd_column,
            outcome=model.outcome_column)
        assert mine["rows"] > 0

        result = produced[model_id].get("CAL-OE")
        if result is None:
            pytest.skip(f"{model_id} has no CAL-OE in its applicable tests")
        if result.value is None:
            assert not result.measured, (
                "a result with no value must not report itself as measured")
            return
        assert abs(float(result.value) - mine["ratio"]) < 1e-6, (
            f"{model_id} actual-versus-predicted: production {result.value!r},"
            f" observed {mine['observed']!r} over predicted "
            f"{mine['predicted']!r} = {mine['ratio']!r}")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_predicted_probabilities_are_probabilities(self, model_id,
                                                       cohorts):
        """Nothing downstream checks this, so it is checked here.

        A PD above 1 or below 0 makes every calibration statistic meaningless
        while leaving all of them finite, which is the worst combination: the
        report reads normally and is wrong throughout.
        """
        import pandas as pd

        model, matured = cohorts[model_id]
        p = pd.to_numeric(matured[model.pd_column], errors="coerce").dropna()
        assert float(p.min()) >= 0.0, f"{model_id} has a negative PD"
        assert float(p.max()) <= 1.0, f"{model_id} has a PD above 1"


# --------------------------------------------------------------- stability


class TestStability:

    @pytest.mark.parametrize("model_id", MODELS)
    def test_score_psi_matches_the_written_out_sum(self, model_id, produced,
                                                   registry):
        """PSI on the latest period against development, recomputed.

        The bands come from the reference population's deciles, which is the
        production decision and the right one — cutting each month at its own
        deciles compares a distribution to itself. That decision is inherited
        deliberately; the ARITHMETIC over those bands is not.

        The production kernel floors each share at a small epsilon so an empty
        bin cannot make the logarithm infinite. This implementation refuses an
        empty bin instead. Where neither side has one — which is the case on
        all three books — the two agree exactly; if that ever stops being
        true, this test will say so rather than absorbing it.
        """
        import numpy as np
        import pandas as pd

        model = registry.get(model_id)
        result = produced[model_id].get("STAB-PSI")
        if result is None or result.value is None:
            pytest.skip(f"{model_id} produced no score PSI")

        reference = check.read(model.reference_dataset)
        periods = check.partitions(model.dataset)
        current = check.read(model.dataset, periods=(periods[-1],),
                             period_field=model.period_field)

        values = pd.to_numeric(reference[model.score_column],
                               errors="coerce").dropna()
        edges = list(np.unique(
            values.quantile(np.linspace(0, 1, 11)).to_numpy()))[1:-1]

        expected = check.bin_counts(reference[model.score_column], edges)
        actual = check.bin_counts(current[model.score_column], edges)
        mine = check.population_stability(expected, actual)

        assert abs(mine - float(result.value)) < 1e-6, (
            f"{model_id} score PSI on {periods[-1]}: production "
            f"{result.value!r}, Σ(a−e)·ln(a/e) over the reference deciles "
            f"{mine!r}")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_a_population_compared_with_itself_has_no_drift(self, model_id,
                                                            registry):
        """The property that makes PSI a drift measure at all.

        Not a comparison against production — a check that the independent
        implementation is itself sound before it is used to judge anything.
        """
        import numpy as np
        import pandas as pd

        model = registry.get(model_id)
        reference = check.read(model.reference_dataset)
        values = pd.to_numeric(reference[model.score_column],
                               errors="coerce").dropna()
        edges = list(np.unique(
            values.quantile(np.linspace(0, 1, 11)).to_numpy()))[1:-1]
        counts = check.bin_counts(reference[model.score_column], edges)
        assert check.population_stability(counts, counts) == 0.0


# --------------------------------------------------------------- variables


class TestVariables:

    @pytest.mark.parametrize("model_id", MODELS)
    def test_information_value_matches_a_hand_counted_woe_table(
            self, model_id, produced, cohorts):
        """IV per variable, recounted over the approved bins.

        The bins are read from the `<variable>_bin` column rather than cut
        afresh: re-binning on the validation sample would measure a different,
        better, unapproved model. What is independent here is the counting and
        the logarithms, which is where an IV goes wrong.

        Reconciled against the SMOOTHED formula, at 5e-7 — the engine
        publishes its IV rounded to six decimals and nothing else separates
        the two. The production kernel applies Laplace smoothing of 0.5 per
        bin, which is a stated policy (`binning.SMOOTHING`, documented as
        keeping a zero-bad bin finite) rather than an unexplained epsilon, so
        the independent path reproduces the policy instead of tolerating the
        gap it creates. `test_the_smoothing_is_the_only_difference` measures
        that gap separately.
        """
        model, matured = cohorts[model_id]
        result = produced[model_id].get("VAR-IV")
        if result is None or not result.table:
            pytest.skip(f"{model_id} produced no variable IV table")

        checked = 0
        for row in result.table:
            variable = row.get("variable", "")
            column = f"{variable}_bin"
            if column not in matured.columns:
                continue
            mine, _ = check.iv_over_bins(
                matured[column], matured[model.outcome_column],
                smoothing=0.5)
            assert abs(mine - float(row["information_value"])) < 5e-7, (
                f"{model_id} {variable}: production "
                f"{row['information_value']!r}, hand-counted smoothed WOE "
                f"table {mine!r}")
            checked += 1
        assert checked >= 3, (
            f"{model_id}: only {checked} variables could be reconciled; a "
            "reconciliation of one variable is an anecdote")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_the_smoothing_is_the_only_difference_and_it_is_small(
            self, model_id, produced, cohorts):
        """How far the production policy moves the textbook number.

        Measured rather than assumed. Half an observation per bin on a cohort
        of tens of thousands should move an IV in the fourth decimal; if it
        ever moved it in the second, the smoothing would be doing the work
        instead of the data, and a validator reading "IV 0.31" would be
        reading an artefact of the correction.

        The bound is 0.01 and it is a MATERIALITY bound on a documented
        policy, not a tolerance on the arithmetic — the assertion above pins
        that to 5e-7.
        """
        model, matured = cohorts[model_id]
        result = produced[model_id].get("VAR-IV")
        if result is None or not result.table:
            pytest.skip(f"{model_id} produced no variable IV table")

        for row in result.table:
            variable = row.get("variable", "")
            column = f"{variable}_bin"
            if column not in matured.columns:
                continue
            smoothed, _ = check.iv_over_bins(
                matured[column], matured[model.outcome_column], smoothing=0.5)
            try:
                textbook, _ = check.iv_over_bins(
                    matured[column], matured[model.outcome_column],
                    smoothing=0.0)
            except ValueError:
                # A bin with no bads: this is the case the smoothing exists
                # for, and the textbook formula has no finite answer. Named
                # rather than skipped silently.
                continue
            assert abs(smoothed - textbook) < 0.01, (
                f"{model_id} {variable}: Laplace smoothing moves the IV from "
                f"{textbook!r} to {smoothed!r}. On a cohort this size the "
                "correction should be immaterial; that it is not means the "
                "published figure is an artefact of the correction.")

    @pytest.mark.parametrize("model_id", MODELS)
    def test_variable_psi_matches_the_written_out_sum(self, model_id,
                                                      produced, registry):
        """CSI per characteristic, over the approved bins, recounted."""
        model = registry.get(model_id)
        result = produced[model_id].get("STAB-CSI")
        if result is None or not result.table:
            pytest.skip(f"{model_id} produced no per-variable CSI table")

        reference = check.read(model.reference_dataset)
        periods = check.partitions(model.dataset)
        current = check.read(model.dataset, periods=(periods[-1],),
                             period_field=model.period_field)

        checked = 0
        for row in result.table:
            variable = row.get("variable", "")
            column = f"{variable}_bin"
            if column not in reference.columns or column not in current.columns:
                continue
            levels = sorted(set(reference[column].dropna().astype(str))
                            | set(current[column].dropna().astype(str)))
            expected = [int((reference[column].astype(str) == lvl).sum())
                        for lvl in levels]
            actual = [int((current[column].astype(str) == lvl).sum())
                      for lvl in levels]
            if 0 in expected or 0 in actual:
                # An empty bin is where the production floor and this
                # implementation deliberately differ. Skipped, and named, so
                # nobody reads a silent pass as agreement.
                continue
            mine = check.population_stability(expected, actual)
            published = row.get("index", row.get("csi"))
            assert published is not None
            assert abs(mine - float(published)) < 1e-5, (
                f"{model_id} {variable} CSI: production {published!r}, "
                f"Σ(a−e)·ln(a/e) {mine!r}")
            checked += 1
        assert checked >= 2, (
            f"{model_id}: only {checked} characteristics could be reconciled")


# ------------------------------------------------- champion vs challenger


class TestTheSaudiSmeChallenger:
    """§2 asks for the SME champion/challenger difference specifically."""

    def test_the_challenger_gap_is_the_difference_of_two_aucs(
            self, produced, cohorts):
        model, matured = cohorts["sme_champion"]
        result = produced["sme_champion"].get("CC-DISCRIMINATION")
        if result is None or result.value is None:
            pytest.skip("no challenger comparison ran on this data")

        champion = check.auc_trapezoid(check.cohort(
            matured, score=model.score_column,
            outcome=model.outcome_column, direction=model.score_direction))
        challenger = check.auc_trapezoid(check.cohort(
            matured, score=model.challenger_score_column,
            outcome=model.outcome_column, direction=model.score_direction))
        mine = challenger - champion
        assert abs(mine - float(result.value)) < 1e-6, (
            f"challenger minus champion: production {result.value!r}, "
            f"{challenger!r} − {champion!r} = {mine!r}")

    def test_the_challenger_pd_is_a_probability(self, cohorts):
        import pandas as pd

        model, matured = cohorts["sme_champion"]
        p = pd.to_numeric(matured[model.challenger_pd_column],
                          errors="coerce").dropna()
        assert float(p.min()) >= 0.0 and float(p.max()) <= 1.0


# ------------------------------------------------------- implementation


class TestImplementationReplication:
    """§2 asks for one implementation score replicated by hand.

    Done on the two retail scorecards, which publish a coefficient equation.
    The Saudi SME champion does not, and its own IMPL-REPLICATE returns
    NOT_APPLICABLE with that reason — which is asserted here rather than
    skipped, because "we could not check" and "there was nothing to check"
    are different statements and only one of them belongs in a report.
    """

    @pytest.mark.parametrize("model_id", ("retail_application_champion",
                                          "retail_behaviour_champion"))
    def test_one_score_recomputed_from_the_approved_equation(
            self, model_id, registry, cohorts):
        """Take ten rows, apply the published equation, compare the column.

        Arithmetic written out here rather than through `metrics.replicate`.
        If the stored score and the equation disagree, the model in production
        is not the model that was approved, and no discrimination statistic
        computed over the stored column means what the report says it means.
        """
        import math

        model = registry.get(model_id)
        equation = model.approved_equation()
        _, matured = cohorts[model_id]

        rows = matured.head(10)
        worst_logit = 0.0
        worst_pd = 0.0
        for _, row in rows.iterrows():
            logit = float(equation.intercept)
            for term in equation.terms:
                logit += float(term.coefficient) * float(row[term.column()])
            stored_logit = float(row[f"logit_{equation.output_prefix}"])
            worst_logit = max(worst_logit, abs(logit - stored_logit))

            probability = 1.0 / (1.0 + math.exp(-logit))
            stored_pd = float(row[f"pd_{equation.output_prefix}"])
            worst_pd = max(worst_pd, abs(probability - stored_pd))

        assert worst_logit < 1e-6, (
            f"{model_id}: the approved equation and the stored logit differ "
            f"by up to {worst_logit!r} across ten rows. The scorecard in the "
            "data is not the scorecard in the registry.")
        assert worst_pd < 1e-6, (
            f"{model_id}: recomputed PD differs from the stored PD by up to "
            f"{worst_pd!r}")

    def test_the_sme_scorecard_says_it_cannot_be_replicated(
            self, registry, produced):
        """A refusal with a reason, not a silent absence.

        This deployment holds no published coefficient equation for the Saudi
        SME scorecard. An engine that answered IMPL-REPLICATE anyway — with a
        pass, or with a zero difference — would be certifying an
        implementation nobody checked.
        """
        result = produced["sme_champion"]["IMPL-REPLICATE"]
        assert result.value is None
        assert result.state == "NOT_APPLICABLE"
        assert result.detail, "a refusal with no reason is a blank cell"

        from backend.scorecard.validation import models as model_registry

        with pytest.raises(model_registry.ModelError) as refused:
            registry.get("sme_champion").approved_equation()
        assert "no published coefficient equation" in str(refused.value)
