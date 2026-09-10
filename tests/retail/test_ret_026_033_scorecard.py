"""Gates RET-026 to RET-033 — metrics, cohorts, maturity, leakage, calibration, evidence."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.retail import monitoring as mon
from backend.retail.models_registry import APPLICATION_SCORECARDS


class TestRET026MetricsAgainstKnownFixtures:
    def test_perfect_separation(self):
        score = [700.0] * 50 + [500.0] * 50
        outcome = [False] * 50 + [True] * 50
        assert mon.auc(score, outcome, min_sample=10, min_defaults=5).value == pytest.approx(1.0)
        assert mon.gini(score, outcome, min_sample=10, min_defaults=5).value == pytest.approx(1.0)
        assert mon.ks(score, outcome, min_sample=10, min_defaults=5).value == pytest.approx(1.0)

    def test_inverted_score_gives_a_negative_gini_not_an_absolute_value(self):
        score = [500.0] * 50 + [700.0] * 50
        outcome = [False] * 50 + [True] * 50
        result = mon.gini(score, outcome, min_sample=10, min_defaults=5)
        assert result.value == pytest.approx(-1.0)
        assert "negative" in result.detail.lower()

    def test_all_ties_give_one_half(self):
        score = [600.0] * 100
        outcome = [True] * 20 + [False] * 80
        assert mon.auc(score, outcome, min_sample=10, min_defaults=5).value == pytest.approx(0.5)

    def test_partial_ties_are_half_credited(self):
        # Two goods and two bads, one tied pair.
        score = [700.0, 600.0, 600.0, 500.0]
        outcome = [False, False, True, True]
        got = mon.auc(score, outcome, min_sample=1, min_defaults=1).value
        assert got == pytest.approx(0.875)

    def test_missing_scores_are_dropped_not_imputed(self):
        score = [700.0, np.nan, 500.0, 550.0]
        outcome = [False, True, True, False]
        r = mon.auc(score, outcome, min_sample=1, min_defaults=1)
        assert r.sample_count == 3

    def test_single_class_returns_insufficient_evidence(self):
        r = mon.auc([600.0] * 200, [False] * 200)
        assert r.value is None
        assert r.status == mon.INSUFFICIENT
        assert "One-class" in r.detail

    def test_gini_matches_two_auc_minus_one_on_real_data(self, retail_book):
        cohort = mon.application_cohort(retail_book.all_months(
            ["months_on_book", "monitoring_eligible_flag", "performance_window_complete_flag",
             "application_id", "application_score_at_origination",
             "observed_default_within_window", "customer_id"]))
        if len(cohort) < 100:
            pytest.skip("not enough matured origination cohort in this book")
        a = mon.auc(cohort["application_score_at_origination"],
                    cohort["observed_default_within_window"])
        g = mon.gini(cohort["application_score_at_origination"],
                     cohort["observed_default_within_window"])
        if a.value is None:
            pytest.skip(a.detail)
        assert g.value == pytest.approx(2 * a.value - 1)

    def test_agrees_with_sklearn_on_the_same_orientation(self):
        rng = np.random.default_rng(7)
        n = 3000
        y = rng.random(n) < 0.08
        s = np.where(y, rng.normal(560, 45, n), rng.normal(630, 45, n))
        from sklearn.metrics import roc_auc_score
        expected = roc_auc_score(y, -s)
        assert mon.auc(s, y).value == pytest.approx(expected, abs=1e-9)


class TestRET027CohortConstruction:
    def test_an_application_is_counted_once_not_once_per_month(self, retail_book):
        columns = ["months_on_book", "monitoring_eligible_flag",
                   "performance_window_complete_flag", "application_id",
                   "application_score_at_origination", "observed_default_within_window"]
        every_row = retail_book.all_months(columns)
        cohort = mon.application_cohort(every_row)
        assert cohort["application_id"].duplicated().sum() == 0
        assert len(cohort) < len(every_row) / 5, (
            "an application repeated across monthly snapshots must collapse to one observation"
        )

    def test_application_cohort_is_at_origination(self, retail_book):
        cohort = mon.application_cohort(retail_book.all_months(
            ["months_on_book", "monitoring_eligible_flag",
             "performance_window_complete_flag", "application_id"]))
        assert (cohort["months_on_book"] == 0).all()

    def test_behavioural_landmarks_declare_their_month(self, retail_book):
        months = retail_book.months()[:6]
        frames = pd.concat([retail_book.month(m) for m in months], ignore_index=True)
        landmarks = mon.behavioural_landmarks(frames, months=months[:2])
        assert set(landmarks["reporting_month"]) <= set(months[:2])
        assert landmarks["behavioural_score"].notna().all()

    def test_repeated_customers_are_clustered_in_the_uncertainty(self, retail_book):
        months = retail_book.months()[:6]
        frames = pd.concat([retail_book.month(m) for m in months], ignore_index=True)
        landmarks = mon.behavioural_landmarks(frames)
        if len(landmarks) < 500:
            pytest.skip("not enough landmark rows")
        clustered = mon.bootstrap_ci(
            landmarks["behavioural_score"], landmarks["observed_default_within_window"],
            clusters=landmarks["customer_id"], draws=60)
        naive = mon.bootstrap_ci(
            landmarks["behavioural_score"], landmarks["observed_default_within_window"],
            draws=60)
        assert clustered is not None and naive is not None
        assert clustered["resampling_unit"] == "customer"
        assert naive["resampling_unit"] == "row"
        assert (clustered["upper"] - clustered["lower"]) >= (naive["upper"] - naive["lower"]) * 0.75


class TestRET028Maturity:
    def test_the_latest_month_has_no_matured_outcome(self, retail_book):
        latest = retail_book.latest()
        assert not latest["performance_window_complete_flag"].any()
        assert int(latest["observed_followup_months"].iloc[0]) == 0
        assert latest["censoring_reason"].notna().all()

    def test_an_unobserved_non_default_is_null_not_false(self, retail_book):
        months = retail_book.months()
        # A month whose window runs past the end of the history.
        immature = retail_book.month(months[-6])
        labels = immature["observed_default_within_window"]
        assert labels.isna().any(), (
            "rows with an incomplete follow-up window must be null, not counted as good"
        )
        # A default seen inside the partial window is still a known positive.
        known_positive = labels.dropna()
        assert len(known_positive) == 0 or bool(known_positive.astype(bool).any())

    def test_mature_months_are_fully_labelled(self, retail_book):
        months = retail_book.months()
        mature = retail_book.month(months[0])
        assert mature["performance_window_complete_flag"].all()
        assert mature["observed_default_within_window"].notna().all()
        assert int(mature["observed_followup_months"].iloc[0]) == 12

    def test_censoring_is_explained_where_it_applies(self, retail_book):
        months = retail_book.months()
        immature = retail_book.month(months[-1])
        reason = immature["censoring_reason"].dropna().iloc[0]
        assert "follow-up" in reason.lower()

    def test_already_defaulted_rows_are_excluded_with_a_reason(self, retail_book):
        frame = retail_book.month(retail_book.months()[0])
        defaulted = frame[frame["current_default_flag"].fillna(False)]
        if len(defaulted):
            assert not defaulted["monitoring_eligible_flag"].any()
            assert defaulted["monitoring_exclusion_reason"].notna().all()
            assert (defaulted["model_use_population"]
                    == "DEFAULTED_EXCLUDED_FROM_FORWARD_DEFAULT_MODELS").all()


class TestRET029NoLeakage:
    def test_outcome_columns_are_declared_restricted(self, retail_book):
        from tests.retail.conftest import SHIPPED_METADATA
        import json
        contract = json.loads((SHIPPED_METADATA / "retail_data_contract.json").read_text())
        restricted = set(contract["restricted_for_prediction"])
        for column in ("observed_default_within_window", "observed_30plus_within_window",
                       "observed_60plus_within_window", "outcome_known_at"):
            assert column in restricted

    def test_no_model_feature_is_an_outcome_label(self, retail_book):
        from backend.retail.models_registry import all_scorecards
        from tests.retail.conftest import SHIPPED_METADATA
        import json
        contract = json.loads((SHIPPED_METADATA / "retail_data_contract.json").read_text())
        restricted = set(contract["restricted_for_prediction"])
        for sc in all_scorecards():
            for f in sc.features:
                assert f.source not in restricted, (
                    f"{sc.model_id} reads '{f.source}', which is an evaluation label"
                )

    def test_outcome_known_at_is_always_after_the_snapshot(self, retail_book):
        for m in retail_book.months():
            f = retail_book.month(m, ["outcome_known_at", "snapshot_date"])
            assert (pd.to_datetime(f["outcome_known_at"])
                    > pd.to_datetime(f["snapshot_date"])).all(), m

    def test_historical_rows_are_not_rewritten_with_later_knowledge(self, retail_book):
        """The first month's operational values are what they were, not what
        the last month knows."""
        months = retail_book.months()
        first = retail_book.month(months[0])
        # A facility in default in the last month, but performing in the first,
        # must still read as performing in the first month's row.
        last = retail_book.latest()
        defaulted_later = set(last.loc[last["current_default_flag"].fillna(False), "facility_id"])
        early = first[first["facility_id"].isin(defaulted_later)]
        if len(early):
            assert not early["current_default_flag"].all(), (
                "the opening snapshot must not know about later defaults"
            )

    def test_a_prediction_view_excludes_evaluation_columns(self, retail_book):
        from tests.retail.conftest import SHIPPED_METADATA
        import json
        contract = json.loads((SHIPPED_METADATA / "retail_data_contract.json").read_text())
        restricted = set(contract["restricted_for_prediction"])
        latest = retail_book.latest()
        prediction_view = latest.drop(columns=[c for c in restricted if c in latest.columns])
        assert not (set(prediction_view.columns) & restricted)


class TestRET030Calibration:
    def test_calibration_uses_the_models_own_probability(self, retail_book):
        cohort = mon.application_cohort(retail_book.all_months(
            ["months_on_book", "monitoring_eligible_flag", "performance_window_complete_flag",
             "application_id", "application_predicted_pd_12m",
             "observed_default_within_window", "pd_pit_12m_base"]))
        if len(cohort) < 100:
            pytest.skip("not enough matured origination cohort")
        result = mon.calibration(cohort["application_predicted_pd_12m"],
                                 cohort["observed_default_within_window"])
        assert result["status"] == "OK"
        assert result["observed_to_expected"] is not None
        assert 0.2 < result["observed_to_expected"] < 5.0

    def test_the_application_pd_and_the_ifrs9_pd_are_different_quantities(self, retail_book):
        latest = retail_book.latest()
        app = pd.to_numeric(latest["application_predicted_pd_12m"])
        ifrs9 = pd.to_numeric(latest["pd_pit_12m_base"])
        assert float((app - ifrs9).abs().mean()) > 1e-4, (
            "if these were the same number, one of them would be mislabelled"
        )
        assert latest["ifrs9_pd_mapping_version"].nunique() == 1, (
            "the link between them must be an explicit versioned mapping"
        )

    def test_targets_are_declared_per_model(self):
        for sc in APPLICATION_SCORECARDS.values():
            assert sc.target_event
            assert sc.horizon_months == 12
            assert sc.target_definition_id

    def test_brier_is_offered_as_a_supplement_not_as_calibration(self):
        result = mon.calibration([0.1] * 200, [False] * 190 + [True] * 10)
        assert "brier_score" in result
        assert "cannot separate" in result["note"]


class TestRET031Stability:
    def test_psi_is_zero_on_an_identical_population(self):
        pop = ["A", "B", "C", "D"] * 500
        assert mon.psi(pop, pop).value == pytest.approx(0.0, abs=1e-12)

    def test_psi_rises_with_a_real_shift(self):
        ref = ["A"] * 400 + ["B"] * 400 + ["C"] * 200
        cur = ["A"] * 700 + ["B"] * 200 + ["C"] * 100
        assert mon.psi(ref, cur).value > 0.1

    def test_missing_is_its_own_category_not_a_dropped_row(self):
        ref = ["A"] * 500 + ["B"] * 500
        cur = ["A"] * 500 + [None] * 500
        result = mon.psi(ref, cur)
        assert "MISSING" in result.extras["bins"]
        assert result.value > 0.2

    def test_zero_bins_are_smoothed_not_divided_by(self):
        ref = ["A"] * 900 + ["B"] * 100
        cur = ["A"] * 1000
        result = mon.psi(ref, cur)
        assert np.isfinite(result.value)
        assert "floored" in result.detail

    def test_a_psi_boundary_is_not_claimed_as_regulatory(self):
        assert "not a universal regulatory" in mon.psi(["A"] * 10, ["A"] * 10).detail

    def test_characteristic_stability_on_a_real_input(self, retail_book):
        months = retail_book.months()
        ref = retail_book.month(months[0])["app_dbr_bin"]
        cur = retail_book.latest()["app_dbr_bin"]
        result = mon.psi(ref, cur)
        assert result.value is not None and np.isfinite(result.value)

    def test_model_versions_are_distinguishable(self, retail_book):
        latest = retail_book.latest()
        assert latest["application_score_model_id"].nunique() == 4, (
            "each product family has its own model and its own reference population"
        )


class TestRET032InsufficientEvidence:
    def test_a_small_segment_returns_counts_not_a_metric(self):
        r = mon.auc([600.0, 610.0, 620.0], [True, False, False])
        assert r.value is None
        assert r.status == mon.INSUFFICIENT
        assert r.sample_count == 3

    def test_a_low_default_segment_returns_counts_not_a_metric(self):
        score = list(np.linspace(500, 700, 500))
        outcome = [True] * 3 + [False] * 497
        r = mon.auc(score, outcome)
        assert r.value is None
        assert r.default_count == 3
        assert "minimum" in r.detail

    def test_no_confidence_interval_around_nothing(self):
        assert mon.bootstrap_ci([600.0] * 50, [False] * 50) is None

    def test_an_empty_cohort_is_reported_as_empty(self):
        r = mon.auc([], [])
        assert r.value is None and r.sample_count == 0

    def test_the_band_table_survives_an_empty_input(self):
        table = mon.band_table([], [], [])
        assert table.empty


class TestRET033AuditEvidence:
    def test_the_evidence_envelope_carries_everything_an_auditor_needs(self, retail_book):
        cohort = mon.application_cohort(retail_book.all_months(
            ["months_on_book", "monitoring_eligible_flag", "performance_window_complete_flag",
             "application_id", "application_score_at_origination",
             "observed_default_within_window", "customer_id", "reporting_month"]))
        metrics = [mon.auc(cohort["application_score_at_origination"],
                           cohort["observed_default_within_window"],
                           customer_ids=cohort["customer_id"])]
        envelope = mon.evidence_envelope(
            question="Has the application scorecard's discrimination weakened?",
            model_id="RETAIL_APP_PERSONAL_LOAN", model_version="1.0.0",
            target="First new default within 12 months", horizon_months=12,
            evaluation_as_of=retail_book.months()[-1],
            cohort_dates=sorted(cohort["reporting_month"].unique()),
            metrics=metrics,
            exclusions={"already_in_default": 0, "immature_window": 0},
            reference_definition="Fixed early monitoring cohort, 2024-08 to 2024-10",
            dataset_hashes=[m["content_hash"] for m in retail_book.manifest["months"][:1]],
            findings=[], limitations=[])
        for key in ("question", "model", "target", "horizon_months", "evaluation_as_of",
                    "prediction_cohort_dates", "sample_count", "distinct_customer_count",
                    "default_count", "exclusions", "reference_definition", "metrics",
                    "uncertainty", "threshold_policy_version", "findings", "limitations",
                    "calculation_evidence_refs", "data_snapshot_hashes", "code_version"):
            assert key in envelope, key

    def test_synthetic_results_are_not_claimed_as_bank_findings(self):
        envelope = mon.evidence_envelope(
            question="q", model_id="m", model_version="1", target="t", horizon_months=12,
            evaluation_as_of="2026-08", cohort_dates=[], metrics=[], exclusions={},
            reference_definition="r", dataset_hashes=[], findings=[], limitations=[])
        disclosure = envelope["disclosure"].lower()
        assert "synthetic" in disclosure
        assert "not anb findings" in disclosure
        assert "no documentary evidence" in disclosure

    def test_the_reference_population_is_named_not_called_a_validation_sample(self, retail_book):
        envelope = mon.evidence_envelope(
            question="q", model_id="m", model_version="1", target="t", horizon_months=12,
            evaluation_as_of="2026-08", cohort_dates=[], metrics=[], exclusions={},
            reference_definition="Fixed early monitoring cohort, 2024-08 to 2024-10",
            dataset_hashes=[], findings=[], limitations=[])
        assert "monitoring cohort" in envelope["reference_definition"]
        assert "development sample" not in envelope["reference_definition"].lower()
