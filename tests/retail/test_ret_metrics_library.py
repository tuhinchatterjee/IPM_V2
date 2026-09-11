"""
The retail metric library, and the empty dashboard it replaces.

RFD-37: every one of the sixty-one metrics in `backend/metrics/library.py`
reads a dataset this deployment does not have — the two scorecard-validation
extracts, the corporate facility position, the corporate staging table. Nothing
raised. Metrics, Lenses and the Playbook rendered perfectly and put a dash in
every box, because a metric whose dataset is absent comes back *unavailable*
rather than failing. A tile that cannot be calculated is worse than a tile that
is not there: it looks like a number that happens to be missing today.

These gates hold three things:

* every served metric reads the one governed retail dataset and computes a
  value against the real book;
* every tile on every served lens computes, and one lens shows one period;
* the maturity rule is the one the book states, not "the outcome column is not
  null" — which at 2026-07 selects 47 rows of which 47 are defaults.
"""

from __future__ import annotations

import pytest

from backend.metrics import lenses as shipped
from backend.metrics import library as lib
from backend.metrics import retail_library as rl
from backend.metrics.catalogue import PERIOD_LATEST_MATURED
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

LATEST = "2026-08"
MATURED = "2025-08"


class TestTheServedLibraryIsTheRetailOne:
    def test_the_profile_serves_the_retail_metrics(self):
        assert lib.ALL == rl.ALL
        assert len(lib.ALL) >= 40

    def test_the_corporate_definitions_are_retained(self):
        """Retired, not deleted: a corporate profile serves all sixty-one."""
        assert len(lib.DEFINED) == 61
        assert any(m.metric_id.startswith("corporate.") for m in lib.DEFINED)

    def test_every_served_metric_reads_the_governed_retail_book(self):
        for metric in lib.ALL:
            for dataset in metric.formula.datasets:
                assert dataset == rl.BOOK, (
                    f"{metric.metric_id} reads {dataset}, which this "
                    "installation does not hold")

    def test_the_library_declares_no_problem_of_its_own(self):
        assert rl.check() == []

    def test_no_metric_id_is_defined_twice(self):
        ids = [m.metric_id for m in rl.ALL]
        assert len(ids) == len(set(ids))

    def test_every_metric_names_a_domain_and_a_unit(self):
        for metric in rl.ALL:
            assert metric.domain, f"{metric.metric_id} has no domain"
            assert metric.unit, f"{metric.metric_id} has no unit"
            assert metric.definition, f"{metric.metric_id} has no definition"


class TestTheMaturityRuleIsTheOneTheBookStates:
    """The sharpest trap in this dataset.

    A facility that has already defaulted has a known outcome immediately; one
    that has not is unknown until its twelve-month window closes. So on any
    immature month the non-null outcomes are the defaults AND NOTHING ELSE.
    """

    def test_the_outcome_column_is_all_defaults_on_an_immature_month(
            self, retail_book):
        frame = retail_book.month(
            "2026-07", columns=["observed_default_within_window"])
        known = frame["observed_default_within_window"].dropna()
        assert len(known) > 0, "this gate is about a month with SOME outcomes"
        assert bool(known.astype(bool).all()), (
            "2026-07 is expected to carry only already-defaulted outcomes; if "
            "that has changed, the trap this gate guards has moved")

    def test_the_matured_scope_uses_the_window_flag_not_the_outcome(self):
        fields = {c.field for c in rl._MATURED}
        assert "performance_window_complete_flag" in fields
        assert "observed_default_within_window" not in fields, (
            "scoping on a non-null outcome selects the defaults and nothing "
            "else on every immature month")

    def test_the_window_flag_separates_the_months_cleanly(self, retail_book):
        for month, expected in ((MATURED, True), ("2025-09", False),
                                (LATEST, False)):
            frame = retail_book.month(
                month, columns=["performance_window_complete_flag"])
            complete = frame["performance_window_complete_flag"].fillna(
                False).astype(bool)
            assert bool(complete.all()) is expected, month

    def test_an_outcome_metric_resolves_to_the_fully_observed_month(self):
        from backend.metrics import service as svc

        for metric in rl.ALL:
            if metric.period_rule != PERIOD_LATEST_MATURED:
                continue
            assert svc.latest_matured_period(metric) == MATURED, (
                f"{metric.metric_id} resolved to a month whose window has not "
                "closed for everyone")

    def test_the_observed_default_rate_is_not_a_hundred_percent(self):
        """What the naive rule would have produced."""
        from backend.metrics import execution as ex

        metric = next(m for m in rl.ALL
                      if m.metric_id == "retail.observed_default_rate")
        value = ex.run(metric.formula, period=MATURED, scope=metric.scope).value
        assert value is not None
        assert 0.5 < value < 10.0, (
            f"an observed default rate of {value}% is not a retail book; a "
            "value near 100 means the cohort is the defaults only")


class TestEveryServedMetricComputesAgainstTheRealBook:
    @pytest.mark.parametrize("metric_id", [m.metric_id for m in rl.ALL])
    def test_it_returns_a_value(self, metric_id, retail_book):
        from backend.metrics import execution as ex
        from backend.metrics import service as svc

        metric = next(m for m in rl.ALL if m.metric_id == metric_id)
        period = (svc.latest_matured_period(metric)
                  if metric.period_rule == PERIOD_LATEST_MATURED else LATEST)
        result = ex.run(metric.formula, period=period, scope=metric.scope)
        assert result.value is not None, (
            f"{metric_id} computed nothing: {result.unavailable}")
        assert result.rows_considered, f"{metric_id} read no rows"


@pytest.fixture(scope="module")
def latest(retail_book):
    """The published month, read straight off the Parquet."""
    return retail_book.month(LATEST)


class TestTheMetricsAgreeWithAnIndependentAggregation:
    """Two implementations, one answer. Computed here with pandas, straight off
    the Parquet, with no call into the metric engine."""

    def _value(self, metric_id, period=LATEST):
        from backend.metrics import execution as ex

        metric = next(m for m in rl.ALL if m.metric_id == metric_id)
        return ex.run(metric.formula, period=period, scope=metric.scope).value

    def test_exposure(self, latest):
        assert self._value("retail.gross_carrying_amount") == pytest.approx(
            float(latest["gross_carrying_amount_sar"].sum()), rel=1e-9)

    def test_allowance(self, latest):
        assert self._value("retail.ecl") == pytest.approx(
            float(latest["ecl_final_sar"].sum()), rel=1e-9)

    def test_customers_are_counted_distinct_not_by_row(self, latest):
        """The book has more facilities than customers; conflating them is the
        commonest way a retail figure is overstated."""
        assert self._value("retail.customers") == pytest.approx(
            float(latest["customer_id"].nunique()))
        assert self._value("retail.facilities") == pytest.approx(float(len(latest)))
        assert self._value("retail.customers") < self._value("retail.facilities")

    def test_coverage_is_a_ratio_of_totals_not_an_average_of_ratios(self, latest):
        ratio_of_totals = 100.0 * (float(latest["ecl_final_sar"].sum())
                                   / float(latest["gross_carrying_amount_sar"].sum()))
        average_of_ratios = 100.0 * float(latest["ecl_coverage_ratio"].mean())
        assert self._value("retail.ecl_coverage") == pytest.approx(
            ratio_of_totals, rel=1e-9)
        assert abs(ratio_of_totals - average_of_ratios) > 1e-6, (
            "this gate needs the two to differ to mean anything")

    @pytest.mark.parametrize("stage", [1, 2, 3])
    def test_stage_exposure_and_coverage(self, latest, stage):
        rows = latest[latest["ifrs9_stage"] == stage]
        gca = float(rows["gross_carrying_amount_sar"].sum())
        ecl = float(rows["ecl_final_sar"].sum())
        assert self._value(f"retail.stage{stage}.exposure") == pytest.approx(
            gca, rel=1e-9)
        assert self._value(f"retail.stage{stage}.share") == pytest.approx(
            100.0 * gca / float(latest["gross_carrying_amount_sar"].sum()),
            rel=1e-9)

    @pytest.mark.parametrize("days", [30, 60, 90])
    def test_delinquency_by_exposure(self, latest, days):
        late = latest[latest["dpd"] >= days]
        expected = 100.0 * (float(late["gross_carrying_amount_sar"].sum())
                            / float(latest["gross_carrying_amount_sar"].sum()))
        assert self._value(f"retail.dpd{days}_rate") == pytest.approx(
            expected, rel=1e-9)

    def test_delinquency_by_count_is_a_different_number(self, latest):
        by_exposure = self._value("retail.dpd30_rate")
        by_count = self._value("retail.dpd30_count_rate")
        assert by_count == pytest.approx(
            100.0 * float((latest["dpd"] >= 30).mean()), rel=1e-9)
        assert by_exposure != pytest.approx(by_count, rel=1e-6), (
            "if these were the same number one of them would be redundant")

    def test_card_utilisation_is_weighted_by_limit(self, latest):
        cards = latest[latest["product_code"] == "CREDIT_CARD"]
        expected = 100.0 * (float(cards["gross_carrying_amount_sar"].sum())
                            / float(cards["current_credit_limit_sar"].sum()))
        assert self._value("retail.card_utilisation") == pytest.approx(
            expected, rel=1e-9)

    def test_application_gini_matches_an_independent_rank_sum(self, retail_book):
        """AUC by the rank-sum identity, computed here, against the governed
        kernel's answer."""
        import numpy as np
        import pandas as pd

        frame = retail_book.month(MATURED, columns=[
            "application_score_at_origination", "observed_default_within_window",
            "performance_window_complete_flag", "monitoring_eligible_flag"])
        frame = frame[
            frame["performance_window_complete_flag"].fillna(False).astype(bool)
            & frame["monitoring_eligible_flag"].fillna(False).astype(bool)]
        frame = frame[frame["application_score_at_origination"].notna()]
        bad = frame["observed_default_within_window"].astype(bool).to_numpy()
        rank = frame["application_score_at_origination"].rank(
            method="average").to_numpy()
        n_bad = float(bad.sum())
        n_good = float(len(bad) - n_bad)
        auc = ((rank[~bad].sum() - n_good * (n_good + 1) / 2)
               / (n_good * n_bad))
        expected = 2 * auc - 1
        assert self._value("retail.application.gini", MATURED) == pytest.approx(
            expected, abs=1e-6)


class TestTheLensesShowSomething:
    def test_the_shipped_lenses_are_well_formed(self):
        assert shipped.check() == []

    def test_a_served_lens_fits_inside_the_tile_limit(self):
        """A lens is a view. The limit is a product constraint and the fix for
        breaching it is fewer tiles, not a bigger limit."""
        from backend.services.lenses import MAX_PANELS, MAX_TILES

        for spec in shipped.served():
            assert len(spec.tiles) <= MAX_TILES, (
                f"{spec.slug} has {len(spec.tiles)} tiles")
            assert len(spec.sections) <= MAX_PANELS, spec.slug

    def test_every_served_lens_reads_only_retail_metrics(self):
        served = {m.metric_id for m in lib.ALL}
        for spec in shipped.served():
            for tile in spec.tiles:
                assert tile.metric_id in served, (
                    f"{spec.slug} shows {tile.metric_id}, which this "
                    "installation does not serve")

    @pytest.mark.parametrize("slug", [s.slug for s in shipped.served()])
    def test_no_tile_on_it_is_empty(self, slug, retail_book):
        from backend.metrics import service as svc

        spec = next(s for s in shipped.served() if s.slug == slug)
        empty = []
        for tile in spec.tiles:
            result = svc.value(tile.metric_id)
            if result.get("value") is None:
                empty.append((tile.metric_id, result.get("unavailable")))
        assert not empty, f"{slug} has empty tiles: {empty}"

    def test_the_current_book_lens_shows_one_period(self):
        """A figure from a year ago on a screen headed 'this month' is how a
        dashboard misleads without saying anything false."""
        from backend.metrics import service as svc

        periods = {svc.value(t.metric_id)["period"]
                   for t in shipped.RETAIL_RISK.tiles}
        assert periods == {LATEST}, (
            f"the Retail Credit Risk lens mixes periods: {sorted(periods)}")
