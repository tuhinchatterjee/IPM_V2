"""
The Forward Risk Signal, pointed at the book this installation has.

What was on screen
------------------
`/early-warning` is a top-level navigation item. It described six families of
retail signal in detail —

    Repayment behaviour: days past due, missed payments, how much of what fell
    due was paid, and — on a card — utilisation, minimum-payment-only months
    and cash advances.

— and then said, three times, **"No model fitted for this transition yet. An
administrator can fit one in the Model Lab."** Pressing fit answered *"The
Forward Risk Signal needs at least three reporting periods"* on a book with
twenty-five months in it.

Only the DESCRIPTIONS had been converted. The fifteen factors under them were
covenant headroom, internal-grade notches, debt service coverage, news
sentiment and sector cycle beta, read from `portfolio_facility` — a corporate
dataset this installation does not hold, so the period list was empty and the
screen reported that as nobody having got round to fitting one.

Three more things were wrong with the same screen: the action beside each
target said "check the covenant package" on a personal-finance facility; the
exposure in each band was printed in millions on a book that publishes whole
SAR, out by a factor of a million; and the horizon was published as "one
reporting quarter" for a model fitted against the next month-end.
"""

from __future__ import annotations

import pytest

from backend.early_warning import factors as factor_set
from backend.early_warning import targets as target_set
from backend.retail import forward_signal, profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

#: Objects a retail book does not have. A factor reading one of these is a
#: factor with nothing behind it.
CORPORATE_COLUMNS = (
    "covenant_headroom_pct", "internal_grade", "prev_risk_rating", "dscr",
    "news_sentiment", "downgrade_prob_pct", "rollover_count", "pd_12m_pct",
    "lgd_pct", "utilisation_pct", "dpd_days", "collateral_value",
)


class TestTheFactorsAreThisBooksOwn:
    def test_no_factor_reads_a_corporate_column(self):
        for factor in factor_set.FACTORS:
            for column in factor.fields:
                assert column not in CORPORATE_COLUMNS, (
                    f"{factor.id} reads {column}, which belongs to the "
                    "corporate facility book")

    def test_every_factor_reads_a_published_column_of_this_book(self):
        from backend.data_access.catalog import Catalog

        try:
            held = set(Catalog.load().dataset(forward_signal.DATASET).fields)
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"the governed catalogue is not readable here: {e}")
        for factor in factor_set.FACTORS:
            for column in factor.fields:
                assert column in held, (
                    f"{factor.id} declares {column}, which "
                    f"{forward_signal.DATASET} does not carry")

    def test_the_families_the_screen_describes_are_all_filled(self):
        """A family blurb with no factor under it is the defect itself."""
        families = {f.family for f in factor_set.FACTORS}
        declared = {f.id for f in factor_set.FACTOR_FAMILIES}
        assert families == declared, (
            f"families with nothing behind them: {sorted(declared - families)}")

    def test_the_corporate_set_is_retained_rather_than_deleted(self):
        assert factor_set.CORPORATE_FACTORS
        assert any(f.id == "covenant_headroom"
                   for f in factor_set.CORPORATE_FACTORS)

    def test_the_read_fields_cover_every_factor(self):
        declared = set(forward_signal.READ_FIELDS)
        for factor in factor_set.FACTORS:
            for column in factor.fields:
                assert column in declared, (
                    f"{factor.id} reads {column}, which READ_FIELDS does not "
                    "ask the lake for")


class TestTheClaimsOnScreenAreTrueOfTheModel:
    def test_the_horizon_is_the_one_this_book_measures(self):
        """Fitted against the next MONTH-END. "Quarter" is a different claim."""
        for target in target_set.TARGETS:
            shown = target.to_dict()["horizon"]
            assert "month" in shown.lower(), shown
            assert "quarter" not in shown.lower(), shown

    def test_no_action_names_something_a_retail_book_does_not_have(self):
        forbidden = ("covenant", "annual review", "obligor", "rating notch")
        for target in target_set.TARGETS:
            action = target.to_dict()["action"].lower()
            for word in forbidden:
                assert word not in action, f"{target.id}: {action}"

    def test_every_target_still_has_an_action(self):
        for target in target_set.TARGETS:
            assert len(target.to_dict()["action"]) > 40


class TestAPeriodLabelOfEitherShapeSorts:
    """The IndexError the Model Lab showed as "something went wrong"."""

    def test_a_monthly_label_sorts_chronologically(self):
        from backend.early_warning.service import _period_key

        months = ["2026-01", "2025-12", "2024-08", "2026-10", "2026-09"]
        assert sorted(months, key=_period_key) == [
            "2024-08", "2025-12", "2026-01", "2026-09", "2026-10"]

    def test_a_quarterly_label_still_sorts(self):
        from backend.early_warning.service import _period_key

        quarters = ["Q1 2026", "Q4 2025", "Q2 2026"]
        assert sorted(quarters, key=_period_key) == [
            "Q4 2025", "Q1 2026", "Q2 2026"]

    def test_an_unreadable_label_does_not_raise(self):
        from backend.early_warning.service import _period_key

        assert _period_key("") == (0, 0)
        assert _period_key("not a period") == (0, 0)


class TestTheSignalFitsAndScores:
    """The gate that would have caught this: it has to RUN on the real book."""

    @pytest.fixture(scope="class")
    def panel(self, retail_book):
        from backend.early_warning.service import build_panel

        return build_panel(target_set.target("stage1_to_stage2"))

    def test_the_panel_is_built_from_more_than_one_period(self, panel):
        assert len(set(panel.periods)) >= 4
        assert len(panel.factors) > 1000

    def test_the_outcome_is_a_real_migration_rate(self, panel):
        rate = float(panel.outcome.mean())
        assert 0.0001 < rate < 0.2, (
            f"a Stage 1 to Stage 2 rate of {rate:.4%} is not a retail book")

    def test_every_factor_column_is_populated(self, panel):
        for factor in factor_set.FACTORS:
            column = panel.factors[factor.id]
            assert column.notna().all(), f"{factor.id} has gaps"
            assert column.std() > 0, (
                f"{factor.id} is constant, so it carries no information")


class TestTheTriageListCanBeNarrowed:
    """§13 asks for a product filter, a customer search and an ordering."""

    @pytest.mark.parametrize("sort,first_key", [
        ("severity", "severity"),
        ("exposure", "exposure"),
        ("rule", "rule"),
        ("customer", "customer"),
    ])
    def test_every_ordering_is_accepted(self, sort, first_key):
        from backend.api.routers.retail import _SORTS

        assert _SORTS[sort] == first_key

    def test_severity_is_ordered_by_meaning_not_by_spelling(self):
        from backend.api.routers.retail import _SEVERITY_ORDER

        assert (_SEVERITY_ORDER["CRITICAL"] < _SEVERITY_ORDER["HIGH"]
                < _SEVERITY_ORDER["MEDIUM"] < _SEVERITY_ORDER["LOW"]), (
            "sorted as text, MEDIUM comes before the two that matter")

    def test_the_sort_puts_the_worst_first(self):
        pytest.importorskip("pandas")
        import pandas as pd

        from backend.api.routers.retail import _sorted_alerts

        alerts = pd.DataFrame([
            {"severity": "MEDIUM", "affected_exposure_sar": 10.0,
             "rule_id": "B", "customer_id": "RC-2"},
            {"severity": "CRITICAL", "affected_exposure_sar": 1.0,
             "rule_id": "A", "customer_id": "RC-1"},
            {"severity": "HIGH", "affected_exposure_sar": 5.0,
             "rule_id": "C", "customer_id": "RC-3"},
        ])
        ordered = _sorted_alerts(alerts, "severity")
        assert list(ordered["severity"]) == ["CRITICAL", "HIGH", "MEDIUM"]
        by_money = _sorted_alerts(alerts, "exposure")
        assert list(by_money["affected_exposure_sar"]) == [10.0, 5.0, 1.0]
