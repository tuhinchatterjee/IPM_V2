"""The Saudi SME universe: what it promises, and whether the arithmetic agrees.

A synthetic universe for validating scorecards has one job beyond existing:
the weaknesses it claims to contain must be *discoverable by calculation*.
A demonstration where the finding is written into a fixture and read back
out teaches a reviewer that the findings are decorative, and a reviewer who
has learned that will not trust the ones that are real.

So every phenomenon in `synthetic.MANIFEST` is checked here by running the
governed kernels in `backend/scorecard/metrics.py` over the generated data
and asserting that the number comes out the way the manifest says it will.
If a phenomenon were removed from the generator, the corresponding test
would fail — which is the property that makes the manifest a description
rather than a claim.

Two of these tests were written before the data satisfied them, and both
found something:

* The bureau-proxy decay was ramped from cohort 12, but only cohorts 0-15
  have a realised outcome, so the decay barely started before the window
  closed and the univariate Gini came out non-monotonic. A phenomenon that
  lives where the outcome does not is a phenomenon nothing can find.

* The banked-sales drift was set to 0.34 and produced a CSI of 1.37. That
  is not a population shift; it is a column that changed meaning. It was
  moved to 0.20, which lands the index in the range where the conventional
  0.25 cut-off is the thing being crossed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.scorecard import metrics as M
from backend.scorecard.sme import build as sme_build
from backend.scorecard.sme import synthetic as S
from backend.scorecard.sme import variables as V

#: The engine's own vocabulary. Not "LOWER_IS_RISKIER" — `metrics.py` refuses
#: an unrecognised token rather than guessing, which is what stops a Gini
#: coming back with the sign inverted.
BETTER = "HIGHER_SCORE_IS_BETTER"

#: A conventional scorecard-practice cut-off, not a regulatory one. Used here
#: as a test threshold and labelled as such wherever it reaches a screen.
PSI_MATERIAL = 0.25


@pytest.fixture(scope="module")
def matured() -> pd.DataFrame:
    """Every cohort whose twelve-month window has closed."""
    return pd.concat([S.cohort(m) for m in S.matured_months()],
                     ignore_index=True)


# ================================================================ the calendar


class TestTheCalendarIsAnchoredNotWalked:

    def test_there_are_at_least_thirty_cohorts(self):
        assert len(S.COHORT_MONTHS) >= 30

    def test_at_least_fifteen_have_a_realised_outcome(self):
        assert len(S.matured_months()) >= 15

    def test_some_cohorts_are_deliberately_immature(self):
        """The refusal has to be reachable to be a control.

        A universe where every cohort happens to be matured leaves the
        "not yet matured" path implemented, unit-tested and unreachable: no
        screen ever shows it, and no report can demonstrate the difference
        between "no defaults" and "no outcome yet".
        """
        open_windows = [m for m in S.COHORT_MONTHS if not S.matured(m)]
        assert len(open_windows) >= 6

    def test_maturity_does_not_read_the_clock(self):
        """The whole of the midnight requirement, in one assertion.

        `matured` takes `data_end` as an argument with a constant default and
        never calls `date.today()`. A suite running either side of midnight
        gets the same answer because there is no clock in the path.
        """
        import inspect

        source = inspect.getsource(S)
        for forbidden in ("date.today", "datetime.now", "datetime.utcnow",
                          "time.time()"):
            assert forbidden not in source, (
                f"{forbidden} in the SME generator makes the universe depend "
                "on when it is built")

    def test_an_immature_cohort_carries_no_outcome_at_all(self):
        open_month = next(m for m in S.COHORT_MONTHS if not S.matured(m))
        frame = S.cohort(open_month)
        assert not bool(frame["is_matured"].iloc[0])
        assert frame["actual_default_12m"].isna().all(), (
            "an immature cohort has outcome values, which is how a zero that "
            "means 'not yet' becomes a zero that means 'none'")

    def test_the_window_close_month_is_on_every_row(self):
        frame = S.cohort(S.COHORT_MONTHS[0])
        assert frame["performance_window_end"].nunique() == 1
        assert frame["performance_horizon_months"].iloc[0] == 12

    def test_latest_matured_is_chronological_not_lexical(self):
        assert S.latest_matured() == S.matured_months()[-1]


# ============================================================== determinism


class TestTheUniverseIsDeterministic:

    def test_the_same_cohort_twice_is_the_same_cohort(self):
        assert S.cohort("2023-06").equals(S.cohort("2023-06"))

    def test_a_cohort_does_not_depend_on_what_was_generated_before_it(self):
        """Keyed per cohort, not per run.

        The failure this prevents is a partial rebuild producing a different
        universe from a full one, which is the kind of difference that shows
        up as a metric that moved when no code changed.
        """
        alone = S.cohort("2024-03")
        after = [S.cohort(m) for m in ("2023-01", "2023-02", "2024-03")][-1]
        assert alone.equals(after)


# ============================================================= the dictionary


class TestTheVariableDictionary:

    def test_there_are_more_than_thirty_meaningful_variables(self):
        assert len(V.SME) > 30

    def test_all_six_families_are_populated(self):
        for family in V.FAMILIES:
            assert V.BY_FAMILY[family], f"{family} has no variables"

    def test_every_proxy_field_says_so_in_its_name(self):
        """The honesty rule, enforced rather than documented.

        A field named for an external system's own output — a bureau score, a
        filing record, a certificate — carries `_proxy`. `simah_score` in a
        column header becomes "we have SIMAH" in a demonstration, and the
        distance between those two sentences is the whole of the claim.
        """
        unmarked = [n for n in V.proxies() if "_proxy" not in n]
        assert unmarked == [], (
            "these stand in for a system CreditProbe is not connected to and "
            f"do not say so: {unmarked}")

    def test_sensitive_fields_exist_and_cannot_score(self):
        assert V.sensitive(), (
            "nothing is monitoring-only, so fairness monitoring has nothing "
            "to monitor")
        for name in V.sensitive():
            assert name not in V.scoreable()

    def test_no_sensitive_field_is_in_either_model(self):
        for name in V.sensitive():
            assert name not in sme_build.CHALLENGER_VARIABLES


# ==================================== the phenomena, discovered by arithmetic


class TestTheSeededWeaknessesAreReal:

    def test_the_challenger_discriminates_better_than_the_champion(self, matured):
        champion = M.discrimination(
            matured, score="champion_score", target="actual_default_12m",
            score_direction=BETTER)
        challenger = M.discrimination(
            matured, score="challenger_score", target="actual_default_12m",
            score_direction=BETTER)
        assert challenger.auc > champion.auc, (
            f"challenger {challenger.auc:.4f} does not beat champion "
            f"{champion.auc:.4f}, so the champion/challenger conversation has "
            "nothing to be about")
        assert champion.auc > 0.60, (
            f"the champion's AUC is {champion.auc:.4f} — a model that weak "
            "makes every other finding moot")

    def test_the_champion_under_predicts_micro_and_the_portfolio_hides_it(
            self, matured):
        """The single most common way a scorecard is wrong in production.

        Both halves matter. Micro outside its limit is the finding; the
        portfolio inside its limit is why nobody noticed.
        """
        def over_expected(part: pd.DataFrame) -> float:
            return float(part["actual_default_12m"].mean()
                         / part["champion_pd_12m"].mean())

        micro = matured[matured.enterprise_size_class_proxy == "MICRO"]
        assert over_expected(micro) > 1.4, (
            "micro enterprises are not materially under-predicted")
        assert over_expected(matured) < 1.25, (
            "the portfolio O/E is outside a conventional limit too, so the "
            "aggregate no longer conceals the segment — which is a different "
            "and much less interesting finding")

    def test_medium_enterprises_are_over_predicted(self, matured):
        # The other side of a mis-segmented calibration. If everything were
        # under-predicted the model would simply be miscalibrated; opposite
        # errors either side of the split is what makes it a segmentation
        # problem.
        medium = matured[matured.enterprise_size_class_proxy == "MEDIUM"]
        ratio = float(medium["actual_default_12m"].mean()
                      / medium["champion_pd_12m"].mean())
        assert ratio < 0.9

    def test_rank_ordering_holds_for_the_portfolio(self, matured):
        rates = _bad_rate_by_band(matured)
        assert list(rates) == sorted(rates, reverse=True), (
            f"the portfolio does not rank risk monotonically: {rates}")

    def test_rank_ordering_breaks_in_government_contracting(self, matured):
        """A segment where the score genuinely does not work.

        Receivable cycles rather than credit quality drive the outcome here,
        and the score does not see it. Asserted as an inversion rather than
        as a named band, so the test survives a change to the band edges.
        """
        part = matured[matured.economic_sector == "CONTRACTING_GOVERNMENT"]
        rates = _bad_rate_by_band(part)
        assert list(rates) != sorted(rates, reverse=True), (
            f"contracting ranks as cleanly as the portfolio: {rates}")

    def test_upward_overrides_perform_worse_than_the_approvals_around_them(
            self, matured):
        overridden = matured[(matured.override_flag == 1)
                             & (matured.override_direction == "UPWARD")]
        ordinary = matured[(matured.approval_decision == "APPROVE")
                           & (matured.override_flag == 0)]
        assert len(overridden) > 200, "too few overrides to say anything"
        assert (overridden["actual_default_12m"].mean()
                > ordinary["actual_default_12m"].mean() * 1.3), (
            "overridden approvals perform like ordinary ones, so there is "
            "nothing for the override analysis to find")


def _bad_rate_by_band(frame: pd.DataFrame) -> list[float]:
    bands = pd.cut(frame["champion_score"],
                   [0, 540, 570, 600, 630, 660, 10_000])
    grouped = frame.groupby(bands, observed=True)["actual_default_12m"]
    return [float(v) for v in grouped.mean().tolist()]


# ============================== the drift phenomena, over the built partitions


@pytest.fixture(scope="module")
def built() -> dict[str, pd.DataFrame]:
    """The datasets as they are on the lake, with their approved bins.

    Read from Parquet rather than regenerated, because CSI is computed over
    the `_bin` columns and those are written by the build. Skipped rather
    than built here: a test that writes 54,000 rows to the lake as a side
    effect is a test that changes what the next one sees.
    """
    from pathlib import Path

    from backend.config import settings

    root = Path(settings.analytics_dir)
    if not (root / sme_build.MONTHLY).exists():
        pytest.skip("The SME universe has not been built on this machine. "
                    "Run `python -c 'from backend.scorecard.sme import build; "
                    "build.build()'`.")

    def load(dataset: str, months: tuple[str, ...]) -> pd.DataFrame:
        return pd.concat(
            [pd.read_parquet(root / dataset / f"cohort_month={m}")
             for m in months], ignore_index=True)

    return {
        "development": load(sme_build.DEVELOPMENT, S.DEVELOPMENT_MONTHS),
        "early": load(sme_build.MONTHLY, S.COHORT_MONTHS[:6]),
        "recent": load(sme_build.MONTHLY, S.COHORT_MONTHS[-6:]),
    }


class TestTheDriftPhenomena:

    def test_banked_sales_has_shifted_materially_and_says_which_variable(
            self, built):
        shift = M.csi(built["development"], built["recent"],
                      variable="bank_credits_to_declared_sales")
        assert shift.index > PSI_MATERIAL, (
            f"CSI is {shift.index:.4f}; nothing has drifted, so "
            "'which variable is causing the stability problem?' has no answer")
        assert shift.bins, "no per-bin contribution, so the answer is a number"

    def test_the_stable_variables_have_stayed_stable(self, built):
        """Without this the drift test proves nothing.

        A universe where everything drifts identifies no contributor. The
        finding is that *two* variables moved and six did not.
        """
        steady = [v for v in sme_build.BINNED_VARIABLES
                  if v not in ("bank_credits_to_declared_sales",
                               "commercial_bureau_score_proxy")]
        for name in steady:
            shift = M.csi(built["development"], built["recent"],
                          variable=name)
            assert shift.index < 0.10, (
                f"{name} has moved by {shift.index:.4f} too, so the drift is "
                "not attributable")

    def test_nothing_had_drifted_in_the_early_cohorts(self, built):
        # The drift is a ramp with a start, not a property of the dataset.
        for name in sme_build.BINNED_VARIABLES:
            shift = M.csi(built["development"], built["early"], variable=name)
            assert shift.index < 0.10, (
                f"{name} was already adrift at the start of the window")

    def test_the_bureau_proxy_loses_power_across_the_matured_window(self):
        """Falling univariate discrimination for one named variable.

        Measured in thirds rather than per cohort: a single month carries
        roughly 70 events, and a Gini on 70 events moves enough that a
        monotonic sequence of sixteen of them would be a coincidence rather
        than a trend.
        """
        months = S.matured_months()
        thirds = (months[:5], months[5:11], months[11:])
        ginis = []
        for part in thirds:
            frame = pd.concat([S.cohort(m) for m in part], ignore_index=True)
            binned = sme_build.spec().apply(
                frame, variables=["commercial_bureau_score_proxy"])
            made = M.variable_discrimination(
                binned, variable="commercial_bureau_score_proxy",
                target="actual_default_12m")
            ginis.append(float(made["gini"]))
        assert ginis == sorted(ginis, reverse=True), (
            f"the bureau proxy's power does not fall monotonically: {ginis}")
        assert ginis[0] - ginis[-1] > 0.05, (
            f"the decay is only {ginis[0] - ginis[-1]:.4f} of Gini, which is "
            "inside the noise for this sample size")


# ================================================================== the build


class TestTheBuild:

    def test_the_binning_is_fitted_once_and_out_of_time(self):
        spec = sme_build.spec()
        assert spec.spec_version == sme_build.SPEC_VERSION
        assert spec.development_population.startswith("2022-"), (
            "the binning was fitted on validation months, which makes every "
            "month look well-behaved by construction")
        assert sme_build.spec() is spec, "a second specification exists"

    def test_the_challenger_reads_variables_the_champion_does_not(self):
        extra = set(sme_build.CHALLENGER_VARIABLES) - set(
            sme_build.CHAMPION_VARIABLES)
        assert extra, "the two models read the same variables"
        assert "bank_credits_to_declared_sales" in extra

    def test_every_binned_variable_is_in_the_dictionary(self):
        for name in sme_build.BINNED_VARIABLES:
            assert V.get(name)

    def test_the_three_datasets_are_all_restricted(self):
        from backend.scorecard import domains

        for dataset in sme_build.DATASETS:
            assert domains.is_restricted(dataset), (
                f"{dataset} is readable by the general Cockpit")
            assert domains.domain_of(dataset) == domains.SCORECARD_SME

    def test_every_row_is_marked_generated(self):
        frame = S.cohort(S.COHORT_MONTHS[0])
        assert (frame["origin"] == S.ORIGIN).all()
