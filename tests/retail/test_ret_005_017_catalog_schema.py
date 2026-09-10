"""Gates RET-005 to RET-017 — catalogue, chronology, keys, schema, scores, determinism."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pandas as pd
import pytest

from backend.retail import taxonomy as tax
from backend.retail.config import load_config, month_end_series
from backend.retail.generate import PERIOD_FIELD, build
from backend.retail.models_registry import (
    APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS, all_scorecards,
)
from backend.retail.scorecards import FACTOR, OFFSET
from backend.retail.schema import EVALUATION_LABEL, spec_for


class TestRET005OneDomain:
    def test_catalogue_has_exactly_one_analytical_dataset(self, shipped_catalog):
        assert len(shipped_catalog["datasets"]) == 1

    def test_the_domain_is_cockpit_data(self, shipped_catalog):
        assert shipped_catalog["datasets"][0]["domain"] == "Cockpit Data"

    def test_exactly_25_monthly_members(self, shipped_catalog):
        assert len(shipped_catalog["monthly_members"]) == 25

    def test_lake_has_exactly_25_partitions(self, retail_book):
        assert len(retail_book.months()) == 25

    def test_catalogue_members_match_the_lake(self, shipped_catalog, retail_book):
        listed = [m["reporting_month"] for m in shipped_catalog["monthly_members"]]
        assert listed == retail_book.months()

    def test_no_second_domain_hides_in_the_catalogue(self, shipped_catalog):
        domains = {d["domain"] for d in shipped_catalog["datasets"]}
        assert domains == {"Cockpit Data"}


class TestRET006Chronology:
    def test_range_is_august_2024_to_august_2026(self, retail_book):
        months = retail_book.months()
        assert months[0] == "2024-08"
        assert months[-1] == "2026-08"

    def test_months_are_consecutive_with_no_duplicates(self, retail_book):
        months = retail_book.months()
        assert len(set(months)) == len(months)
        idx = [int(m[:4]) * 12 + int(m[5:]) for m in months]
        assert all(b - a == 1 for a, b in zip(idx, idx[1:]))

    def test_no_september_2026(self, retail_book):
        assert "2026-09" not in retail_book.months()

    def test_the_demo_date_is_explicit_and_manifest_versioned(self, retail_book):
        assert retail_book.manifest["demo_as_of_month"] == "2026-08"
        assert retail_book.manifest["config_version"]
        assert retail_book.manifest["manifest_hash"]

    def test_changing_the_demo_date_moves_the_whole_window(self):
        dates = month_end_series("2027-03", 25)
        assert len(dates) == 25
        assert dates[0].isoformat() == "2025-03-31"
        assert dates[-1].isoformat() == "2027-03-31"

    def test_a_month_count_other_than_25_is_refused(self):
        cfg = load_config()
        with pytest.raises(ValueError, match="exactly 25"):
            dataclasses.replace(cfg, months=24).validate()


class TestRET007Keys:
    def test_primary_key_unique_in_every_month(self, retail_book):
        for m in retail_book.months():
            frame = retail_book.month(m)
            assert not frame[["snapshot_date", "customer_id", "facility_id"]].duplicated().any(), m

    def test_facility_month_key_unique(self, retail_book):
        for m in retail_book.months():
            assert not retail_book.month(m)["facility_id"].duplicated().any(), m

    def test_multi_facility_customers_exist(self, retail_book):
        latest = retail_book.latest()
        counts = latest.groupby("customer_id")["facility_id"].nunique()
        assert (counts > 1).sum() > 0, "a retail book has customers with more than one facility"

    def test_customer_level_values_agree_across_a_customers_facilities(self, retail_book):
        latest = retail_book.latest()
        multi = latest.groupby("customer_id").filter(lambda g: len(g) > 1)
        for column in ("verified_total_monthly_income_sar", "employment_status",
                       "region", "employer_id", "debt_burden_ratio"):
            spread = multi.groupby("customer_id")[column].nunique(dropna=False)
            assert (spread <= 1).all(), (
                f"{column} is a customer-level field and disagrees between the same "
                "customer's facilities at one snapshot"
            )

    def test_each_facility_belongs_to_one_customer_throughout(self, retail_book):
        pairs = retail_book.all_months(["facility_id", "customer_id"]).drop_duplicates()
        assert pairs["facility_id"].duplicated().sum() == 0


class TestRET008ProductsAndSubsegments:
    def test_all_four_product_families(self, retail_book):
        assert set(retail_book.latest()["product_code"]) == set(tax.PRODUCT_CODES)

    def test_every_product_has_meaningful_representation(self, retail_book):
        share = retail_book.latest()["product_code"].value_counts(normalize=True)
        assert share.min() > 0.03, f"a product family is barely represented: {share.to_dict()}"

    @pytest.mark.parametrize("column", [
        "salary_transfer_flag", "new_to_bank_at_origination_flag", "employment_status",
        "employer_sector", "income_band", "indebtedness_band", "region", "city",
        "branch_id", "origination_channel", "residency_category",
    ])
    def test_saudi_subsegment_dimension_is_populated(self, retail_book, column):
        latest = retail_book.latest()
        assert column in latest.columns
        assert latest[column].notna().mean() > 0.9
        assert latest[column].nunique() > 1

    def test_card_auto_and_home_subsegments_exist_where_applicable(self, retail_book):
        latest = retail_book.latest()
        cards = latest[latest["product_code"] == tax.CREDIT_CARD]
        assert cards["card_behaviour_segment"].nunique() > 1
        autos = latest[latest["product_code"] == tax.AUTO_LOAN]
        assert autos["vehicle_new_used"].nunique() == 2
        assert autos["balloon_band"].nunique() > 1
        homes = latest[latest["product_code"] == tax.HOME_LOAN]
        assert homes["property_type"].nunique() > 1
        assert homes["housing_support_type"].nunique() > 1

    def test_no_financed_company_entity_appears(self, retail_book):
        latest = retail_book.latest()
        assert (latest["customer_scope"] == "NATURAL_PERSON_RETAIL").all()
        forbidden = {"obligor_group", "borrower_name", "sector_rating", "internal_rating",
                     "rating_grade", "ebitda", "dscr", "leverage_ratio", "covenant_breach_flag",
                     "balance_sheet_total", "revenue_sar"}
        assert not (forbidden & set(latest.columns))

    def test_employer_is_an_attribute_not_a_financed_customer(self, retail_book):
        latest = retail_book.latest()
        # Employer identifiers exist, but no employer appears as a customer.
        assert latest["employer_id"].notna().any()
        assert not set(latest["employer_id"].dropna()) & set(latest["customer_id"])


class TestRET009SchemaMetadata:
    REQUIRED_FAMILIES = {
        "identity": ["snapshot_date", "reporting_month", "dataset_version", "record_id",
                     "customer_id", "facility_id", "application_id", "product_code",
                     "origination_date", "months_on_book", "is_synthetic", "generator_version",
                     "data_quality_status", "customer_scope", "score_subject_grain"],
        "affordability": ["verified_monthly_salary_sar", "verified_total_monthly_income_sar",
                          "household_expenses_sar", "monthly_external_credit_obligations_sar",
                          "monthly_own_bank_credit_obligations_sar",
                          "monthly_total_credit_obligations_sar", "obligation_scope_definition",
                          "disposable_income_sar", "debt_burden_ratio", "income_band",
                          "indebtedness_band", "origination_income_sar",
                          "origination_debt_burden_ratio", "policy_version_at_origination",
                          "policy_exception_flag", "applied_score_cutoff",
                          "decision_at_origination"],
        "balances": ["original_finance_amount_sar", "current_credit_limit_sar",
                     "outstanding_principal_sar", "accrued_profit_interest_sar",
                     "gross_carrying_amount_sar", "undrawn_commitment_sar",
                     "scheduled_monthly_payment_sar", "actual_payment_received_sar",
                     "writeoff_amount_month_sar", "recovery_amount_month_sar",
                     "collateral_value_current_sar", "ltv_current_ratio",
                     "behavioural_expected_life_months", "ecl_expected_life_months"],
        "delinquency": ["dpd", "previous_month_dpd", "dpd_bucket", "overdue_amount_sar",
                        "oldest_unpaid_due_date", "missed_payment_count_3m",
                        "missed_payment_count_6m", "max_dpd_3m", "max_dpd_6m", "max_dpd_12m",
                        "current_default_flag", "first_default_date", "credit_impaired_flag",
                        "forbearance_flag", "cure_flag", "writeoff_flag", "collections_stage",
                        "payment_to_due_ratio_1m", "payment_to_due_ratio_3m",
                        "utilisation_ratio", "behaviour_history_months_available"],
        "bureau": ["bureau_score_at_origination", "bureau_score_current", "bureau_score_change_3m",
                   "bureau_score_scale_id", "bureau_enquiries_3m", "bureau_adverse_flag",
                   "bureau_thin_file_flag", "bureau_source_label", "salary_missed_cycle_count_3m",
                   "salary_change_3m_ratio", "income_volatility_6m", "balance_buffer_months",
                   "external_obligations_change_3m_sar"],
        "scores": ["application_score_at_origination", "application_score_band",
                   "application_predicted_pd_12m", "application_score_model_id",
                   "application_transform_version", "behavioural_score",
                   "behavioural_score_band", "behavioural_predicted_pd_12m",
                   "behavioural_score_previous_month", "behavioural_score_change_3m",
                   "score_input_missing_count", "score_input_stale_count",
                   "score_implementation_check_status", "score_evidence_ref"],
        "ifrs9": ["ifrs9_stage", "previous_month_stage", "stage_entry_date",
                  "staging_policy_version", "sicr_flag", "sicr_reason",
                  "sicr_quantitative_flag", "sicr_qualitative_flag", "sicr_dpd_backstop_flag",
                  "default_definition_id", "pd_ttc_12m", "pd_ttc_at_origination_12m",
                  "pd_origination_curve_remaining_life", "sicr_pd_ratio",
                  "pd_pit_12m_base", "pd_pit_lifetime_downturn", "lgd_base", "ead_base_sar",
                  "scenario_weight_base", "ecl_base_sar", "ecl_weighted_sar",
                  "management_overlay_sar", "ecl_final_sar", "ecl_coverage_ratio",
                  "ecl_horizon_type", "ecl_horizon_months", "scenario_set_id",
                  "calculation_run_id", "calculation_input_hash"],
        "monitoring": ["monitoring_as_of_date", "prediction_reference_date",
                       "score_target_definition_id", "performance_window_months",
                       "performance_window_start", "performance_window_end",
                       "observed_followup_months", "outcome_known_at",
                       "performance_window_complete_flag", "censoring_reason",
                       "observed_default_within_window", "observed_30plus_within_window",
                       "monitoring_eligible_flag", "monitoring_exclusion_reason",
                       "model_use_population"],
    }

    @pytest.mark.parametrize("family", sorted(REQUIRED_FAMILIES))
    def test_required_field_family_is_complete(self, retail_book, family):
        columns = set(retail_book.latest().columns)
        missing = sorted(set(self.REQUIRED_FAMILIES[family]) - columns)
        assert not missing, f"{family} family is missing: {missing}"

    def test_every_column_has_a_dictionary_entry(self, retail_book):
        for column in retail_book.latest().columns:
            spec = spec_for(column)
            assert spec.definition, f"{column} has no definition"
            assert spec.data_type
            assert spec.semantics

    def test_stock_and_flow_are_distinguished(self):
        assert spec_for("gross_carrying_amount_sar").semantics == "STOCK"
        assert spec_for("writeoff_amount_month_sar").semantics == "FLOW"
        assert "never summed" in spec_for("gross_carrying_amount_sar").definition.lower() or \
               "summing it across months" in spec_for("gross_carrying_amount_sar").definition

    def test_customer_grain_is_recorded_for_customer_fields(self):
        assert spec_for("verified_total_monthly_income_sar").grain == "CUSTOMER"
        assert spec_for("gross_carrying_amount_sar").grain == "FACILITY"

    def test_outcome_labels_are_marked_restricted(self):
        for column in ("observed_default_within_window", "outcome_known_at",
                       "monitoring_eligible_flag"):
            assert spec_for(column).semantics == EVALUATION_LABEL

    def test_data_contract_is_published(self, retail_book):
        from tests.retail.conftest import SHIPPED_METADATA
        contract = json.loads((SHIPPED_METADATA / "retail_data_contract.json").read_text())
        assert contract["primary_key"] == ["snapshot_date", "customer_id", "facility_id"]
        assert contract["is_synthetic"] is True
        assert contract["column_count"] == len(retail_book.latest().columns)
        assert contract["restricted_for_prediction"]


class TestRET010Chronology:
    def test_no_exposure_before_a_facility_exists(self, retail_book):
        for m in retail_book.months():
            frame = retail_book.month(m)
            assert (frame["months_on_book"] >= 0).all(), m
            assert (pd.to_datetime(frame["origination_date"])
                    <= pd.to_datetime(frame["snapshot_date"])).all(), m

    def test_months_on_book_increments_by_one(self, retail_book):
        months = retail_book.months()
        a = retail_book.month(months[10])[["facility_id", "months_on_book"]]
        b = retail_book.month(months[11])[["facility_id", "months_on_book"]]
        j = a.merge(b, on="facility_id", suffixes=("_a", "_b"))
        assert (j["months_on_book_b"] - j["months_on_book_a"] == 1).all()

    def test_remaining_tenor_declines(self, retail_book):
        months = retail_book.months()
        cols = ["facility_id", "remaining_contractual_tenor_months", "product_code"]
        a = retail_book.month(months[10])[cols]
        b = retail_book.month(months[11])[cols]
        j = a.merge(b, on="facility_id", suffixes=("_a", "_b"))
        j = j[j["product_code_a"] != tax.CREDIT_CARD]
        delta = (pd.to_numeric(j["remaining_contractual_tenor_months_b"])
                 - pd.to_numeric(j["remaining_contractual_tenor_months_a"]))
        assert (delta <= 0).all(), "remaining contractual tenor must not increase"

    def test_default_and_cure_dates_are_ordered(self, retail_book):
        latest = retail_book.latest()
        cured = latest[latest["cure_date"].notna() & latest["first_default_date"].notna()]
        if len(cured):
            assert (pd.to_datetime(cured["cure_date"])
                    >= pd.to_datetime(cured["first_default_date"])).all()

    def test_outcome_is_known_after_the_snapshot(self, retail_book):
        latest = retail_book.latest()
        assert (pd.to_datetime(latest["outcome_known_at"])
                > pd.to_datetime(latest["snapshot_date"])).all()


class TestRET011OriginationValuesAreFrozen:
    FROZEN = [
        "application_score_at_origination", "application_score_band",
        "application_predicted_pd_12m", "bureau_score_at_origination",
        "origination_income_sar", "origination_debt_burden_ratio",
        "origination_disposable_income_sar", "origination_employment_tenure_months",
        "origination_amount_to_income_ratio", "ltv_origination_ratio",
        "origination_bureau_enquiries_3m", "origination_salary_transfer_status",
        "app_income_raw", "app_dbr_transformed", "app_bureau_score_points",
    ]

    @pytest.mark.parametrize("column", FROZEN)
    def test_value_does_not_move_between_snapshots(self, retail_book, column):
        frames = [retail_book.month(m)[["facility_id", column]] for m in retail_book.months()]
        stacked = pd.concat(frames, ignore_index=True)
        spread = stacked.groupby("facility_id")[column].nunique(dropna=False)
        assert (spread <= 1).all(), (
            f"{column} is an origination value and changed on {int((spread > 1).sum())} "
            "facilities across the published months"
        )

    def test_current_income_does_move(self, retail_book):
        """The control: a current value is allowed to change, and does."""
        months = retail_book.months()
        a = retail_book.month(months[0])[["facility_id", "verified_total_monthly_income_sar"]]
        b = retail_book.month(months[-1])[["facility_id", "verified_total_monthly_income_sar"]]
        j = a.merge(b, on="facility_id", suffixes=("_a", "_b"))
        assert (j["verified_total_monthly_income_sar_a"]
                != j["verified_total_monthly_income_sar_b"]).any()


class TestRET012ModelFeatureCoverage:
    def test_every_model_feature_has_all_five_canonical_columns(self, retail_book):
        columns = set(retail_book.latest().columns)
        for sc in all_scorecards():
            for name in sc.column_names():
                assert name in columns, f"{sc.model_id} needs {name} and the dataset has no such column"

    def test_every_model_feature_has_its_raw_source_column(self, retail_book):
        columns = set(retail_book.latest().columns)
        for sc in all_scorecards():
            for f in sc.features:
                assert f.source in columns, (
                    f"{sc.model_id} reads '{f.source}' and the canonical dataset does not carry it"
                )

    def test_no_hidden_model_input(self, retail_book):
        """Every flattened column belongs to a declared feature — no orphans."""
        declared = {c for sc in all_scorecards() for c in sc.column_names()}
        present = {c for c in retail_book.latest().columns
                   if (c.startswith("app_") or c.startswith("beh_"))
                   and not c.startswith(("app_score_", "beh_score_"))
                   and c.endswith(("_raw", "_transformed", "_bin", "_missing_flag", "_points"))}
        assert present <= declared, f"undeclared score columns: {sorted(present - declared)}"

    def test_feature_counts_are_non_trivial(self):
        for sc in all_scorecards():
            assert len(sc.features) >= 10, f"{sc.model_id} has only {len(sc.features)} inputs"


class TestRET013ScoreReconstruction:
    def test_application_score_reconstructs_from_base_points_plus_points(self, retail_book):
        latest = retail_book.latest()
        for product, sc in APPLICATION_SCORECARDS.items():
            sub = latest[latest["product_code"] == product]
            if sub.empty:
                continue
            points = sum(pd.to_numeric(sub[f"app_{f.short}_points"]) for f in sc.features)
            rebuilt = sc.base_points + points
            actual = pd.to_numeric(sub["app_score_unclipped"])
            assert float((rebuilt - actual).abs().max()) < 1e-6, product

    def test_behavioural_score_reconstructs(self, retail_book):
        latest = retail_book.latest()
        for product, sc in BEHAVIOURAL_SCORECARDS.items():
            sub = latest[(latest["product_code"] == product) & latest["behavioural_score"].notna()]
            if sub.empty:
                continue
            points = sum(pd.to_numeric(sub[f"beh_{f.short}_points"]) for f in sc.features)
            rebuilt = sc.base_points + points
            actual = pd.to_numeric(sub["beh_score_unclipped"])
            assert float((rebuilt - actual).abs().max()) < 1e-6, product

    def test_score_reconstructs_end_to_end_from_raw_inputs(self, retail_book):
        """Raw -> transform -> points -> logit -> PD -> score, from the row itself."""
        latest = retail_book.latest()
        for product, sc in APPLICATION_SCORECARDS.items():
            sub = latest[latest["product_code"] == product]
            if sub.empty:
                continue
            row = sub.iloc[0]
            got = sc.reconstruct(row)
            assert abs(got["score"] - float(row["application_score_at_origination"])) < 1e-6
            assert abs(got["predicted_pd_12m"] - float(row["application_predicted_pd_12m"])) < 1e-9
            assert got["score_band"] == row["application_score_band"]
            assert len(got["contributions"]) == len(sc.features)

    def test_pd_and_score_agree_through_the_declared_scaling(self, retail_book):
        latest = retail_book.latest()
        p = pd.to_numeric(latest["application_predicted_pd_12m"]).to_numpy()
        logit = np.log(p / (1 - p))
        expected = OFFSET - FACTOR * logit
        actual = pd.to_numeric(latest["app_score_unclipped"]).to_numpy()
        assert float(np.abs(expected - actual).max()) < 1e-6

    def test_higher_score_means_lower_predicted_pd(self, retail_book):
        latest = retail_book.latest()
        corr = np.corrcoef(
            pd.to_numeric(latest["application_score_at_origination"]),
            pd.to_numeric(latest["application_predicted_pd_12m"]))[0, 1]
        assert corr < -0.9, f"score direction is wrong: correlation {corr}"

    def test_score_direction_is_recorded(self, retail_book):
        latest = retail_book.latest()
        assert (latest["application_score_direction"] == "HIGHER_IS_SAFER").all()
        assert (latest["behavioural_score_direction"] == "HIGHER_IS_SAFER").all()


class TestRET014RollingBehaviour:
    def test_rolling_windows_agree_with_the_observed_history(self, retail_book):
        months = retail_book.months()
        cols = ["facility_id", "dpd", "max_dpd_3m"]
        window = [retail_book.month(m)[cols] for m in months[-3:]]
        joined = window[0].merge(window[1], on="facility_id", suffixes=("_1", "_2"))
        joined = joined.merge(window[2].rename(columns={"dpd": "dpd_3", "max_dpd_3m": "max_dpd_3m_3"}),
                              on="facility_id")
        observed_max = joined[["dpd_1", "dpd_2", "dpd_3"]].max(axis=1)
        assert (pd.to_numeric(joined["max_dpd_3m_3"]) >= observed_max - 1e-9).all()

    def test_thin_history_is_an_honest_unavailable_state(self, retail_book):
        latest = retail_book.latest()
        thin = latest[latest["behaviour_history_months_available"] < 3]
        if len(thin):
            assert thin["behavioural_score"].isna().all(), (
                "a facility with under three months of history must not be scored"
            )
            assert (thin["behavioural_score_status"] == "NOT_SCORED_THIN_HISTORY").all()
            assert (thin["data_quality_status"] == "THIN_HISTORY").all()

    def test_thin_history_is_distinct_from_a_low_score(self, retail_book):
        latest = retail_book.latest()
        scored_low = latest[(latest["behavioural_score"].notna())
                            & (pd.to_numeric(latest["behavioural_score"]) < 540)]
        assert (scored_low["behavioural_score_status"] == "SCORED").all()

    def test_payment_ratio_is_bounded_and_defined(self, retail_book):
        latest = retail_book.latest()
        ratio = pd.to_numeric(latest["payment_to_due_ratio_3m"]).dropna()
        assert (ratio >= 0).all()
        assert np.isfinite(ratio).all()


class TestRET015BalancesAndApplicability:
    def test_balance_identity(self, retail_book):
        latest = retail_book.latest()
        gca = pd.to_numeric(latest["gross_carrying_amount_sar"])
        parts = (pd.to_numeric(latest["outstanding_principal_sar"])
                 + pd.to_numeric(latest["accrued_profit_interest_sar"]))
        assert float((gca - parts).abs().max()) < 0.02

    def test_no_negative_balances_or_probabilities(self, retail_book):
        latest = retail_book.latest()
        for column in ("outstanding_principal_sar", "gross_carrying_amount_sar",
                       "ecl_final_sar", "overdue_amount_sar"):
            assert (pd.to_numeric(latest[column]).fillna(0) >= -0.01).all(), column
        for column in ("pd_ttc_12m", "pd_pit_12m_base", "pd_pit_lifetime_base",
                       "lgd_base", "scenario_weight_base"):
            v = pd.to_numeric(latest[column]).dropna()
            assert (v >= 0).all() and (v <= 1).all(), column

    @pytest.mark.parametrize("column,product", [
        ("current_credit_limit_sar", tax.CREDIT_CARD),
        ("utilisation_ratio", tax.CREDIT_CARD),
        ("overlimit_days_3m", tax.CREDIT_CARD),
        ("cash_advance_share_3m", tax.CREDIT_CARD),
        ("vehicle_new_used", tax.AUTO_LOAN),
        ("dealer_id", tax.AUTO_LOAN),
        ("property_type", tax.HOME_LOAN),
        ("housing_support_type", tax.HOME_LOAN),
    ])
    def test_product_specific_field_is_null_elsewhere(self, retail_book, column, product):
        latest = retail_book.latest()
        others = latest[latest["product_code"] != product]
        assert others[column].isna().all(), (
            f"{column} applies to {product} only, and carries a value on another product. "
            "A non-applicable field is null with a reason, never a zero that reads like data."
        )

    def test_term_loans_do_not_carry_card_features(self, retail_book):
        latest = retail_book.latest()
        terms = latest[latest["product_code"] != tax.CREDIT_CARD]
        for column in ("utilisation_ratio", "minimum_payment_only_months_3m",
                       "undrawn_commitment_sar", "ccf_base"):
            assert terms[column].isna().all(), column

    def test_secured_products_carry_collateral_and_others_do_not(self, retail_book):
        latest = retail_book.latest()
        secured = latest[latest["secured_flag"].fillna(False)]
        unsecured = latest[~latest["secured_flag"].fillna(False)]
        assert secured["collateral_value_current_sar"].notna().all()
        assert unsecured["collateral_value_current_sar"].isna().all()


class TestRET016GrainSemantics:
    def test_customer_income_is_not_multiplied_by_facility_count(self, retail_book):
        latest = retail_book.latest()
        naive = float(pd.to_numeric(latest["verified_total_monthly_income_sar"]).sum())
        correct = float(latest.drop_duplicates("customer_id")
                        ["verified_total_monthly_income_sar"].astype(float).sum())
        assert naive > correct, "the test needs multi-facility customers to be meaningful"
        multi = latest.groupby("customer_id").size()
        expected_ratio = float(multi.mean())
        assert abs(naive / correct - expected_ratio) < 0.05

    def test_distinct_counts_are_distinct(self, retail_book):
        latest = retail_book.latest()
        assert latest["customer_id"].nunique() < len(latest)
        assert latest["facility_id"].nunique() == len(latest)

    def test_stocks_are_not_summed_across_months(self, retail_book):
        """Exposure at a date is one month's sum, never twenty-five months added up."""
        per_month = [float(retail_book.month(m)["gross_carrying_amount_sar"].sum())
                     for m in retail_book.months()]
        latest = per_month[-1]
        assert sum(per_month) > 20 * latest
        assert spec_for("gross_carrying_amount_sar").aggregation == "sum within one snapshot only"

    def test_flows_aggregate_across_months(self):
        assert spec_for("writeoff_amount_month_sar").aggregation == "sum across months in a period"

    def test_default_rate_denominator_excludes_already_defaulted(self, retail_book):
        frame = retail_book.month(retail_book.months()[0])
        eligible = frame[frame["monitoring_eligible_flag"].fillna(False)]
        assert not eligible["current_default_flag"].fillna(False).any(), (
            "a forward-default cohort must exclude facilities already in default"
        )


class TestRET017Determinism:
    def test_identical_configuration_gives_identical_content(self, small_book, small_config, tmp_path):
        rebuilt = build(small_config, tmp_path / "again", log_progress=False)
        first = {m["reporting_month"]: m["content_hash"] for m in small_book.manifest["months"]}
        second = {m["reporting_month"]: m["content_hash"] for m in rebuilt["months"]}
        assert first == second, "the same seed and configuration must give the same book"

    def test_row_counts_and_totals_are_identical(self, small_book, small_config, tmp_path):
        rebuilt = build(small_config, tmp_path / "again2", log_progress=False)
        assert small_book.manifest["total_rows"] == rebuilt["total_rows"]
        for a, b in zip(small_book.manifest["months"], rebuilt["months"]):
            assert a["gross_carrying_amount_sar"] == pytest.approx(b["gross_carrying_amount_sar"])
            assert a["ecl_final_sar"] == pytest.approx(b["ecl_final_sar"])

    def test_reading_the_lake_does_not_regenerate_it(self, retail_book):
        before = {m: retail_book.month(m)["gross_carrying_amount_sar"].sum()
                  for m in retail_book.months()[:3]}
        retail_book._cache.clear()
        after = {m: retail_book.month(m)["gross_carrying_amount_sar"].sum()
                 for m in retail_book.months()[:3]}
        assert before == after
