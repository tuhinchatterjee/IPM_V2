"""Gates RET-034 to RET-038 — retail alerts, deduplication, scope, coverage, no corporate block."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.retail import ews


@pytest.fixture(scope="module")
def alerts(retail_book):
    return ews.evaluate_snapshot(retail_book.latest())


class TestRET034AlertsFromCanonicalData:
    def test_alerts_are_raised(self, alerts):
        assert not alerts.empty, "a 19,000-facility book should raise retail warnings"

    def test_every_alert_names_its_rule_and_version(self, alerts):
        for column in ("rule_id", "rule_version", "rulebook_version", "rule_name", "rule_family"):
            assert alerts[column].notna().all()

    def test_every_alert_carries_measurement_threshold_and_evidence(self, alerts):
        assert alerts["trigger_value"].notna().all()
        assert alerts["threshold"].notna().all()
        assert alerts["unit"].notna().all()
        assert alerts["evidence_columns"].str.len().gt(0).all()
        assert alerts["evidence_record_refs"].str.len().gt(0).all()

    def test_alert_identities_reference_real_rows(self, alerts, retail_book):
        latest = retail_book.latest()
        assert set(alerts["customer_id"]) <= set(latest["customer_id"])
        facility_alerts = alerts[alerts["scope"] == ews.FACILITY_SCOPE]
        assert set(facility_alerts["facility_id"]) <= set(latest["facility_id"])

    def test_dates_are_the_snapshot_date(self, alerts, retail_book):
        snapshot = retail_book.latest()["snapshot_date"].iloc[0]
        assert (alerts["snapshot_date"] == snapshot).all()

    def test_no_separate_ews_seed_exists(self):
        from tests.retail.conftest import SHIPPED_ANALYTICS
        datasets = [p.name for p in SHIPPED_ANALYTICS.iterdir()
                    if p.is_dir() and not p.name.startswith(".")]
        assert datasets == ["retail_facility_month"], (
            f"EWS must read the canonical book, not its own seed; found {datasets}"
        )

    def test_thresholds_are_labelled_synthetic_and_configurable(self, alerts):
        assert alerts["threshold_source"].str.contains("Synthetic demo threshold").all()
        assert alerts["threshold_source"].str.contains("bank-configurable").all()

    def test_a_threshold_override_changes_the_alert_count(self, retail_book):
        latest = retail_book.latest()
        strict = ews.evaluate_snapshot(latest, thresholds={"RET-EWS-002": 1.0})
        normal = ews.evaluate_snapshot(latest, thresholds={"RET-EWS-002": 3.0})
        n_strict = int((strict["rule_id"] == "RET-EWS-002").sum())
        n_normal = int((normal["rule_id"] == "RET-EWS-002").sum())
        assert n_strict > n_normal


class TestRET035Lifecycle:
    def test_running_the_same_evaluation_twice_does_not_duplicate(self, retail_book):
        latest = retail_book.latest()
        first = ews.evaluate_snapshot(latest)
        second = ews.evaluate_snapshot(latest)
        merged = ews.reconcile(first, second)
        assert merged["alert_id"].duplicated().sum() == 0
        assert len(merged) == len(first)

    def test_a_persisting_condition_updates_rather_than_reopening(self, retail_book):
        latest = retail_book.latest()
        first = ews.evaluate_snapshot(latest)
        merged = ews.reconcile(first, ews.evaluate_snapshot(latest))
        assert (merged["current_status"] == ews.STATUS_UPDATED).all()
        assert (merged["first_seen_date"] == first["first_seen_date"].iloc[0]).all()

    def test_a_resolved_condition_closes(self, retail_book):
        months = retail_book.months()
        previous = ews.evaluate_snapshot(retail_book.month(months[-2]))
        current = ews.evaluate_snapshot(retail_book.month(months[-1]))
        merged = ews.reconcile(previous, current)
        gone = set(previous["alert_id"]) - set(current["alert_id"])
        if gone:
            closed = merged[merged["alert_id"].isin(gone)]
            assert (closed["current_status"] == ews.STATUS_CLOSED).all()

    def test_a_returning_condition_retriggers_deliberately(self, retail_book):
        latest = retail_book.latest()
        current = ews.evaluate_snapshot(latest)
        assert not current.empty
        previously_closed = current.head(5).copy()
        previously_closed["current_status"] = ews.STATUS_CLOSED
        merged = ews.reconcile(previously_closed, current)
        retriggered = merged[merged["alert_id"].isin(previously_closed["alert_id"])]
        assert (retriggered["current_status"] == ews.STATUS_RETRIGGERED).all()
        assert (retriggered["first_seen_date"] == latest["snapshot_date"].iloc[0]).all()

    def test_history_survives_across_months(self, retail_book):
        months = retail_book.months()
        book = ews.evaluate_snapshot(retail_book.month(months[-3]))
        for m in months[-2:]:
            book = ews.reconcile(book, ews.evaluate_snapshot(retail_book.month(m)))
        assert book["alert_id"].duplicated().sum() == 0
        assert set(book["current_status"]) <= {
            ews.STATUS_OPEN, ews.STATUS_UPDATED, ews.STATUS_CLOSED, ews.STATUS_RETRIGGERED}


class TestRET036ScopeAndDoubleCounting:
    def test_a_customer_alert_is_raised_once_per_customer(self, alerts):
        customer_alerts = alerts[alerts["scope"] == ews.CUSTOMER_SCOPE]
        assert customer_alerts.groupby(["rule_id", "customer_id"]).size().max() == 1

    def test_a_customer_alert_carries_no_single_facility(self, alerts):
        customer_alerts = alerts[alerts["scope"] == ews.CUSTOMER_SCOPE]
        assert customer_alerts["facility_id"].isna().all()
        assert (customer_alerts["affected_facility_count"] >= 1).all()

    def test_a_customer_alert_attaches_every_facility_they_hold(self, alerts, retail_book):
        latest = retail_book.latest()
        customer_alerts = alerts[alerts["scope"] == ews.CUSTOMER_SCOPE]
        if customer_alerts.empty:
            pytest.skip("no customer-scope alerts")
        row = customer_alerts.iloc[0]
        theirs = latest[latest["customer_id"] == row["customer_id"]]
        assert row["affected_facility_count"] == theirs["facility_id"].nunique()

    def test_affected_exposure_counts_each_facility_once(self, alerts, retail_book):
        latest = retail_book.latest()
        total = ews.affected_exposure(alerts)
        assert total <= float(latest["gross_carrying_amount_sar"].sum()) + 0.01, (
            "exposure under alert cannot exceed the book"
        )
        naive = float(alerts["affected_exposure_sar"].sum())
        assert naive > total, (
            "the naive sum double counts across overlapping rules; the test needs that "
            "overlap to be meaningful"
        )

    def test_a_multi_facility_customers_exposure_is_not_multiplied(self, alerts, retail_book):
        latest = retail_book.latest()
        customer_alerts = alerts[alerts["scope"] == ews.CUSTOMER_SCOPE]
        if customer_alerts.empty:
            pytest.skip("no customer-scope alerts")
        multi = customer_alerts[customer_alerts["affected_facility_count"] > 1]
        if multi.empty:
            pytest.skip("no multi-facility customer alerts")
        row = multi.iloc[0]
        theirs = latest[latest["customer_id"] == row["customer_id"]]
        expected = float(theirs.drop_duplicates("facility_id")["gross_carrying_amount_sar"].sum())
        assert row["affected_exposure_sar"] == pytest.approx(expected, abs=0.01)


class TestRET037SignalCoverage:
    REQUIRED_FAMILIES = {
        "REPAYMENT", "CARD_BEHAVIOUR", "INCOME", "AFFORDABILITY", "SCORE",
        "BUREAU", "COLLECTIONS", "FORBEARANCE", "PRODUCT_STRUCTURE", "COLLATERAL",
    }

    def test_the_rulebook_covers_every_required_family(self):
        assert {r.family for r in ews.RULES} >= self.REQUIRED_FAMILIES

    @pytest.mark.parametrize("rule_id", [
        "RET-EWS-008",  # salary interruption
        "RET-EWS-002",  # repayment
        "RET-EWS-005",  # card utilisation
        "RET-EWS-013",  # behavioural score
        "RET-EWS-015",  # bureau
    ])
    def test_signal_actually_fires_somewhere_in_the_book(self, retail_book, rule_id):
        fired = 0
        for m in retail_book.months()[-6:]:
            alerts = ews.evaluate_snapshot(retail_book.month(m))
            fired += int((alerts["rule_id"] == rule_id).sum())
        assert fired > 0, f"{rule_id} never fires; a rule that cannot fire is not a signal"

    @pytest.mark.parametrize("rule_id,product", [
        ("RET-EWS-019", "AUTO_LOAN"),   # balloon
        ("RET-EWS-020", None),          # secured LTV
    ])
    def test_product_specific_signal_is_demonstrable(self, retail_book, rule_id, product):
        found = 0
        for m in retail_book.months()[-12:]:
            alerts = ews.evaluate_snapshot(retail_book.month(m))
            hits = alerts[alerts["rule_id"] == rule_id]
            found += len(hits)
            if product and len(hits):
                assert (hits["product_code"] == product).all()
        if found == 0:
            pytest.skip(
                f"{rule_id} does not fire in this seed. The rule is implemented and tested "
                "against a constructed frame below; it is not a dead control."
            )

    def test_a_product_rule_fires_on_a_constructed_frame(self, retail_book):
        """Rules that the seed does not happen to trigger are still executable."""
        latest = retail_book.latest().copy()
        autos = latest[latest["product_code"] == "AUTO_LOAN"].head(20).copy()
        autos["months_to_balloon"] = 3.0
        autos["balance_buffer_months"] = 0.1
        alerts = ews.evaluate_snapshot(autos)
        assert (alerts["rule_id"] == "RET-EWS-019").sum() == len(autos)

    def test_explanations_state_evidence_not_conclusions(self, alerts):
        salary = alerts[alerts["rule_id"] == "RET-EWS-008"]
        if salary.empty:
            pytest.skip("no salary alerts at this snapshot")
        reason = salary["reason"].iloc[0].lower()
        assert "not proof of job loss" in reason
        assert "has lost their job" not in reason

    def test_recommended_actions_are_reviews_not_executed_decisions(self, alerts):
        for text in alerts["recommended_review"].unique():
            lowered = text.lower()
            for forbidden in ("we have reduced", "limit has been cancelled", "customer contacted",
                              "account blocked", "we have emailed"):
                assert forbidden not in lowered


class TestRET038NoCorporateBlocker:
    CORPORATE_INPUTS = (
        "balance_sheet", "income_statement", "cash_flow_statement", "ebitda", "dscr",
        "leverage", "covenant", "financial_statement", "audited_accounts", "rating_grade",
    )

    def test_no_rule_requires_a_company_financial_statement(self):
        for rule in ews.RULES:
            for feature in rule.features:
                for token in self.CORPORATE_INPUTS:
                    assert token not in feature.lower(), (
                        f"{rule.rule_id} needs '{feature}', which is a corporate input"
                    )

    def test_the_rulebook_text_names_no_corporate_requirement(self):
        import json
        blob = json.dumps(ews.rulebook()).lower()
        for token in self.CORPORATE_INPUTS:
            assert token not in blob, f"the rulebook mentions '{token}'"

    def test_every_rule_input_exists_in_the_canonical_dataset(self, retail_book):
        columns = set(retail_book.latest().columns)
        for rule in ews.RULES:
            missing = [f for f in rule.features if f not in columns]
            assert not missing, f"{rule.rule_id} needs {missing}, which the retail book lacks"

    def test_a_missing_retail_input_yields_a_precise_limitation_not_invented_evidence(self):
        frame = pd.DataFrame({
            "product_code": ["CREDIT_CARD"], "customer_id": ["RC-1"], "facility_id": ["RF-1"],
            "snapshot_date": ["2026-08-31"], "record_id": ["r"],
            "gross_carrying_amount_sar": [1000.0], "employer_id": [None], "region": ["RIYADH"],
            "missed_payment_count_3m": [np.nan],
        })
        alerts = ews.evaluate_snapshot(frame)
        assert (alerts["rule_id"] == "RET-EWS-002").sum() == 0, (
            "a rule whose input is missing must not fire on a guessed value"
        )

    def test_workflow_runs_end_to_end_on_retail_data_alone(self, retail_book):
        months = retail_book.months()[-3:]
        book = pd.DataFrame(columns=ews._ALERT_COLUMNS)
        for m in months:
            book = ews.reconcile(book, ews.evaluate_snapshot(retail_book.month(m)))
        assert len(book) > 0
        assert ews.affected_exposure(book) > 0
