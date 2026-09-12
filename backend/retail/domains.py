"""The four governed retail domains, as views of one canonical book.

The Saudi retail installation holds one analytical universe:
`retail_facility_month`, twenty-five month-ends at facility-month grain. A Head
of Retail Risk, a model validator, an early-warning analyst and somebody
building a stress scenario all read that same book — but they do not read the
same five hundred and forty-six columns, and putting all of them on one screen
means none of the four can find their own.

So there are four domains and one book. Each derived domain is a COLUMN VIEW of
the canonical rows: the same facility, the same month, the same exposure, with
the fields that domain is about and nothing else. They are built from the
canonical parquet and never generated independently, which is what makes the
reconciliation in `reconcile()` a tautology rather than a hope — the row counts,
the customer counts and the exposure totals agree because they are the same
rows.

What this is not
----------------
It is not four universes. Nothing here invents a figure, re-derives an exposure
or re-scores a model. Every column in a derived domain is carried across
unchanged from the canonical book, and a column the book does not hold is
absent from the view rather than computed into it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CANONICAL = "retail_facility_month"

#: Bumped when a view's column list changes.
RETAIL_DOMAINS_VERSION = "1.0.0"

#: Carried by every view, because every view is still the same book.
KEYS: tuple[str, ...] = (
    "record_id", "reporting_month", "customer_id", "facility_id",
    "product_code", "product_label", "product_subsegment",
)


@dataclass(frozen=True)
class DomainView:
    """One governed derived domain, and the columns it carries."""

    dataset: str
    business_name: str
    domain: str
    purpose: str
    grain: str
    owner: str
    #: Columns beyond `KEYS`. A name the canonical book does not hold is
    #: skipped with a note rather than fabricated.
    columns: tuple[str, ...] = ()
    authoritative_for: tuple[str, ...] = ()

    def wanted(self) -> list[str]:
        return list(dict.fromkeys(KEYS + self.columns))


# --------------------------------------------------------- Early Warning Data

EARLY_WARNING = DomainView(
    dataset="retail_early_warning",
    business_name="Retail early warning",
    domain="Early Warning Data",
    purpose=(
        "Where the book is going wrong before it is written off: current "
        "delinquency and stage beside the behavioural signals that move first, "
        "the exposure at stake, and the layer inputs the Forward Risk Signal "
        "is scored from."),
    grain="One row per facility per month-end, for the retail book.",
    owner="Retail Early Warning",
    columns=(
        # Where it is now.
        "dpd", "dpd_bucket", "previous_month_dpd", "ifrs9_stage",
        "previous_month_stage", "sicr_flag", "sicr_reason",
        "current_default_flag", "credit_impaired_flag", "collections_stage",
        "forbearance_flag", "restructured_flag", "unlikeliness_to_pay_flag",
        "promise_to_pay_flag", "broken_promise_count_3m",
        # What it is worth.
        "gross_carrying_amount_sar", "ead_base_sar", "ecl_final_sar",
        "current_credit_limit_sar", "undrawn_commitment_sar",
        # Repayment behaviour.
        "missed_payment_count_3m", "missed_payment_count_6m",
        "max_dpd_3m", "max_dpd_6m", "max_dpd_12m",
        "payment_to_due_ratio_1m", "payment_to_due_ratio_3m",
        "returned_payment_count_3m", "autopay_failure_count_3m",
        "minimum_payment_only_months_3m", "full_payment_months_6m",
        # Affordability and income.
        "salary_transfer_flag", "salary_missed_cycle_count_3m",
        "salary_delay_days", "salary_change_3m_ratio",
        "verified_total_monthly_income_sar", "debt_burden_ratio",
        "disposable_income_sar", "affordability_buffer_sar",
        "income_volatility_6m", "external_obligations_change_3m_sar",
        "employment_change_flag", "job_loss_reported_flag",
        # Score dynamics.
        "behavioural_score", "behavioural_score_band",
        "behavioural_score_previous_month", "behavioural_score_change_3m",
        "application_score_at_origination", "application_score_band",
        "behavioural_predicted_pd_12m",
        # Facility structure.
        "utilisation_ratio", "utilisation_band", "utilisation_change_3m_pp",
        "utilisation_avg_3m", "overlimit_days_3m", "cash_advance_share_3m",
        "card_behaviour_segment", "months_on_book", "ltv_current_ratio",
        "ltv_band", "collateral_value_current_sar", "secured_flag",
        "months_to_balloon", "balloon_payment_sar",
        # Bureau and external.
        "bureau_score_current", "bureau_score_change_3m",
        "bureau_external_dpd_max", "bureau_enquiries_3m",
        "bureau_active_facilities_count", "bureau_adverse_flag",
        "bureau_thin_file_flag", "bureau_data_available_flag",
        # Who and where.
        "customer_segment", "region_label", "city", "origination_channel",
        "new_to_bank_at_origination_flag", "employment_status",
    ),
    authoritative_for=("retail_early_warning_position",),
)


# ------------------------------------------------------ Credit Scorecard Data

CREDIT_SCORECARD = DomainView(
    dataset="retail_credit_scorecard",
    business_name="Retail credit scorecard",
    domain="Credit Scorecard Data",
    purpose=(
        "Both scorecards as they were actually applied: the model and version "
        "that scored each facility, every configured input raw, transformed "
        "and in points, the total score, the band, the mapped PD, and the "
        "outcome where the performance window has closed."),
    grain="One row per facility per month-end, for the retail book.",
    owner="Retail Model Validation",
    columns=(
        # Application scorecard: identity and result.
        "app_model_id", "app_model_version", "application_score_model_id",
        "application_score_model_version", "application_score_direction",
        "application_score_at_origination", "application_score_band",
        "app_score_value", "app_score_band_value", "app_score_points_total",
        "app_score_base_points", "app_score_logit", "app_score_unclipped",
        "app_predicted_pd_12m", "application_predicted_pd_12m",
        "app_target_definition_id", "app_transform_version",
        "application_score_status", "application_score_reconciled_flag",
        "application_score_date", "applied_score_cutoff",
        "decision_at_origination", "policy_exception_flag",
        "policy_exception_reason", "score_override_flag",
        "score_override_direction", "score_override_reason",
        # Application inputs, raw / transformed / points.
        "app_income_raw", "app_income_transformed", "app_income_points",
        "app_income_bin", "app_dbr_raw", "app_dbr_transformed",
        "app_dbr_points", "app_dbr_bin", "app_emp_tenure_raw",
        "app_emp_tenure_transformed", "app_emp_tenure_points",
        "app_emp_tenure_bin", "app_cust_tenure_raw",
        "app_cust_tenure_transformed", "app_cust_tenure_points",
        "app_cust_tenure_bin", "app_bureau_score_raw",
        "app_bureau_score_transformed", "app_bureau_score_points",
        "app_bureau_score_bin", "app_bureau_dpd_raw",
        "app_bureau_dpd_transformed", "app_bureau_dpd_points",
        "app_bureau_dpd_bin", "app_bureau_enquiries_raw",
        "app_bureau_enquiries_transformed", "app_bureau_enquiries_points",
        "app_bureau_enquiries_bin", "app_ltv_raw", "app_ltv_transformed",
        "app_ltv_points", "app_ltv_bin", "app_salary_transfer_raw",
        "app_salary_transfer_transformed", "app_salary_transfer_points",
        "app_salary_transfer_bin", "app_disposable_raw",
        "app_disposable_transformed", "app_disposable_points",
        "app_disposable_bin", "app_input_missing_count",
        # Behavioural scorecard: identity and result.
        "beh_model_id", "beh_model_version", "behavioural_score_model_id",
        "behavioural_score_model_version", "behavioural_score_direction",
        "behavioural_score", "behavioural_score_band", "beh_score_value",
        "beh_score_band_value", "beh_score_points_total",
        "beh_score_base_points", "beh_score_logit", "beh_score_unclipped",
        "beh_predicted_pd_12m", "behavioural_predicted_pd_12m",
        "beh_target_definition_id", "beh_transform_version",
        "behavioural_score_status", "behavioural_score_reconciled_flag",
        "behavioural_score_date", "behavioural_score_previous_month",
        "behavioural_score_change_3m",
        # Behavioural inputs, raw / transformed / points.
        "beh_utilisation_raw", "beh_utilisation_transformed",
        "beh_utilisation_points", "beh_utilisation_bin",
        "beh_util_change_raw", "beh_util_change_transformed",
        "beh_util_change_points", "beh_util_change_bin", "beh_dpd_raw",
        "beh_dpd_transformed", "beh_dpd_points", "beh_dpd_bin",
        "beh_max_dpd_6m_raw", "beh_max_dpd_6m_transformed",
        "beh_max_dpd_6m_points", "beh_max_dpd_6m_bin", "beh_missed_6m_raw",
        "beh_missed_6m_transformed", "beh_missed_6m_points",
        "beh_missed_6m_bin", "beh_min_pay_raw", "beh_min_pay_transformed",
        "beh_min_pay_points", "beh_min_pay_bin", "beh_pay_ratio_3m_raw",
        "beh_pay_ratio_3m_transformed", "beh_pay_ratio_3m_points",
        "beh_pay_ratio_3m_bin", "beh_salary_missed_raw",
        "beh_salary_missed_transformed", "beh_salary_missed_points",
        "beh_salary_missed_bin", "beh_bureau_dpd_raw",
        "beh_bureau_dpd_transformed", "beh_bureau_dpd_points",
        "beh_bureau_dpd_bin", "beh_mob_raw", "beh_mob_transformed",
        "beh_mob_points", "beh_mob_bin", "beh_input_missing_count",
        # Monitoring and outcome.
        "monitoring_eligible_flag", "monitoring_exclusion_reason",
        "monitoring_as_of_date", "monitoring_reference_id",
        "monitoring_reference_type", "model_use_population",
        "performance_window_start", "performance_window_end",
        "performance_window_months", "performance_window_complete_flag",
        "observed_default_within_window", "observed_30plus_within_window",
        "observed_60plus_within_window", "observed_followup_months",
        "outcome_known_at", "censoring_reason", "score_subject_grain",
        "score_implementation_check_status", "score_input_missing_count",
        "score_input_stale_count",
        # Context a validator needs.
        "customer_segment", "origination_channel", "origination_vintage",
        "months_on_book", "current_default_flag", "dpd", "ifrs9_stage",
        "gross_carrying_amount_sar",
    ),
    authoritative_for=("retail_scorecard_position",),
)


# ----------------------------------------------------- What-If Analysis Data

WHATIF = DomainView(
    dataset="retail_whatif",
    business_name="Retail what-if analysis",
    domain="What-If Analysis Data",
    purpose=(
        "Everything a scenario moves and everything it lands on: the IFRS 9 "
        "risk parameters under each scenario, the staging inputs, the "
        "collateral and recovery assumptions, the score variables a stress "
        "can be applied to, and the weighted ECL the book currently carries."),
    grain="One row per facility per month-end, for the retail book.",
    owner="Retail IFRS 9",
    columns=(
        # What the scenario lands on.
        "ecl_final_sar", "ecl_weighted_sar", "ecl_base_sar", "ecl_upturn_sar",
        "ecl_downturn_sar", "management_overlay_sar", "ecl_coverage_ratio",
        "gross_carrying_amount_sar", "outstanding_principal_sar",
        "ecl_drawn_balance_sar", "ecl_undrawn_commitment_sar",
        # Risk parameters, by scenario.
        "pd_pit_12m_base", "pd_pit_12m_upturn", "pd_pit_12m_downturn",
        "pd_pit_lifetime_base", "pd_pit_lifetime_upturn",
        "pd_pit_lifetime_downturn", "pd_ttc_12m", "pd_pit_12m_anchor",
        "lgd_base", "lgd_upturn", "lgd_downturn",
        "ead_base_sar", "ead_upturn_sar", "ead_downturn_sar",
        "ccf_base", "ccf_upturn", "ccf_downturn",
        "pd_model_version", "lgd_model_version", "ead_model_version",
        "ecl_model_version", "ifrs9_pd_mapping_version",
        "ifrs9_pd_source_model",
        # Scenario weights and horizon.
        "scenario_weight_base", "scenario_weight_upturn",
        "scenario_weight_downturn", "scenario_set_id", "scenario_set_version",
        "ecl_horizon_type", "ecl_horizon_months", "ecl_expected_life_months",
        "ecl_remaining_life_months", "monthly_discount_rate",
        "discount_method",
        # Recovery and collateral.
        "recovery_rate_nominal", "recovery_delay_months",
        "recovery_amount_month_sar", "expected_sale_cost_ratio",
        "collateral_value_current_sar", "collateral_value_origination_sar",
        "collateral_type", "secured_flag", "ltv_current_ratio", "ltv_band",
        # Staging inputs.
        "ifrs9_stage", "previous_month_stage", "sicr_flag",
        "sicr_quantitative_flag", "sicr_qualitative_flag",
        "sicr_dpd_backstop_flag", "sicr_pd_ratio", "sicr_pd_absolute_change",
        "sicr_reason", "staging_policy_version", "stage_override_flag",
        "dpd", "dpd_bucket", "credit_impaired_flag", "current_default_flag",
        "forbearance_flag", "restructured_flag", "cure_flag",
        # Stressable score variables.
        "behavioural_score", "behavioural_score_band",
        "behavioural_predicted_pd_12m", "application_score_at_origination",
        "application_score_band", "utilisation_ratio", "utilisation_band",
        "debt_burden_ratio", "verified_total_monthly_income_sar",
        "salary_transfer_flag", "card_behaviour_segment",
        # Context.
        "customer_segment", "region_label", "current_credit_limit_sar",
        "undrawn_commitment_sar", "months_on_book",
    ),
    authoritative_for=("retail_whatif_position",),
)


DERIVED: tuple[DomainView, ...] = (EARLY_WARNING, CREDIT_SCORECARD, WHATIF)

#: Every Data Builder heading a retail installation offers.
RETAIL_DOMAIN_NAMES: tuple[str, ...] = (
    "Cockpit Data", "Early Warning Data", "Credit Scorecard Data",
    "What-If Analysis Data",
)


# ------------------------------------------------------------------ building

@dataclass
class Built:
    """What one build produced."""

    written: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        made = ", ".join(f"{k} ({n} months)"
                         for k, n in sorted(self.written.items()))
        return made or "nothing written"


def build(*, analytics_dir: str | Path | None = None,
          replace: bool = False) -> Built:
    """Write the three derived domains from the canonical book.

    Idempotent: a month already written is left alone unless `replace` is set.
    Reading the canonical parquet and selecting columns, nothing else — there
    is no arithmetic here at all, which is the point.
    """
    import pandas as pd

    from backend.config import settings
    from backend.retail import guard

    root = Path(analytics_dir or settings.analytics_dir)
    guard.require_retail_directory(root, what="the retail domain builder")

    source = root / CANONICAL
    if not source.exists():
        raise FileNotFoundError(
            f"{source} does not exist. The canonical retail book has to be "
            "published before its governed views can be built.")

    months = sorted(p.name for p in source.iterdir()
                    if p.is_dir() and p.name.startswith("reporting_month="))
    out = Built()
    if not months:
        out.notes.append("the canonical book holds no months")
        return out

    # The column list is checked once, against the first month, so a view that
    # names a column the book has stopped holding says so rather than failing
    # twenty-five times.
    first = _read_one(source / months[0])
    held = set(first.columns)
    for view in DERIVED:
        wanted = [c for c in view.wanted() if c in held]
        absent = [c for c in view.wanted() if c not in held]
        if absent:
            out.notes.append(
                f"{view.dataset}: {len(absent)} column(s) the book does not "
                f"hold were left out — {', '.join(sorted(absent)[:6])}"
                + (" …" if len(absent) > 6 else ""))
        target = root / view.dataset
        written = 0
        for month in months:
            destination = target / month
            marker = destination / "part-0.parquet"
            if marker.exists() and not replace:
                continue
            frame = _read_one(source / month)
            destination.mkdir(parents=True, exist_ok=True)
            frame[[c for c in wanted if c in frame.columns]].to_parquet(
                marker, index=False)
            written += 1
        if written:
            out.written[view.dataset] = written
        else:
            out.skipped.append(view.dataset)
    return out


def _read_one(directory: Path) -> Any:
    import pandas as pd

    parts = sorted(directory.glob("*.parquet"))
    if not parts:
        raise FileNotFoundError(f"{directory} holds no parquet")
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True) \
        if len(parts) > 1 else pd.read_parquet(parts[0])


# ------------------------------------------------------------ reconciliation

def reconcile(*, analytics_dir: str | Path | None = None,
              period: str = "") -> list[str]:
    """Prove each view is the canonical book. Empty means it is.

    Checked rather than asserted in a docstring: a view is only trustworthy
    while it is still derived, and a builder that silently stopped running
    would leave three domains quietly describing last quarter.
    """
    import pandas as pd

    from backend.config import settings

    root = Path(analytics_dir or settings.analytics_dir)
    source = root / CANONICAL
    months = sorted(p.name for p in source.iterdir()
                    if p.is_dir() and p.name.startswith("reporting_month="))
    if not months:
        return ["the canonical book holds no months"]
    at = f"reporting_month={period}" if period else months[-1]
    if at not in months:
        return [f"the canonical book has no {at}"]

    truth = _read_one(source / at)
    problems: list[str] = []
    for view in DERIVED:
        directory = root / view.dataset
        if not directory.exists():
            problems.append(f"{view.dataset}: not built")
            continue
        their_months = sorted(p.name for p in directory.iterdir() if p.is_dir())
        if len(their_months) != len(months):
            problems.append(
                f"{view.dataset}: {len(their_months)} months against "
                f"{len(months)} in the canonical book")
        if at not in their_months:
            problems.append(f"{view.dataset}: no {at}")
            continue
        frame = _read_one(directory / at)
        if len(frame) != len(truth):
            problems.append(
                f"{view.dataset}: {len(frame):,} rows against "
                f"{len(truth):,} in the canonical book at {at}")
        for column in ("customer_id", "facility_id"):
            if column in frame and column in truth:
                mine, theirs = frame[column].nunique(), truth[column].nunique()
                if mine != theirs:
                    problems.append(
                        f"{view.dataset}: {mine:,} distinct {column} against "
                        f"{theirs:,}")
        for column in ("gross_carrying_amount_sar", "ead_base_sar",
                       "ecl_final_sar"):
            if column in frame and column in truth:
                mine = float(frame[column].sum())
                theirs = float(truth[column].sum())
                if abs(mine - theirs) > max(abs(theirs) * 1e-9, 0.01):
                    problems.append(
                        f"{view.dataset}: {column} totals {mine:,.2f} against "
                        f"{theirs:,.2f}")
    return problems


# ------------------------------------------------------------- registration

def register(*, metadata_dir: str | Path | None = None) -> list[str]:
    """Put the three views in the governed catalogue, idempotently.

    Each view's field definitions are COPIED from the canonical book's own
    entries, so a column means the same thing in a view as it does in the
    book. Writing fresh definitions here would create a second place for a
    definition to drift, and the first thing to drift would be the sentence a
    reader trusts.
    """
    import json

    from backend.config import settings
    from backend.retail import guard

    root = Path(metadata_dir or settings.metadata_dir)
    guard.require_retail_directory(root, what="the retail domain registration")
    path = root / "catalog.json"
    payload = json.loads(path.read_text())
    datasets = payload.get("datasets") or []
    canonical = next((d for d in datasets if d.get("name") == CANONICAL), None)
    if canonical is None:
        raise LookupError(
            f"{CANONICAL} is not in {path}; its views cannot be registered "
            "against a book the catalogue does not hold.")

    by_name = {str(f.get("name")): f for f in (canonical.get("fields") or [])}
    present = {str(d.get("name")) for d in datasets}
    added: list[str] = []
    for view in DERIVED:
        if view.dataset in present:
            continue
        fields = [dict(by_name[c]) for c in view.wanted() if c in by_name]
        datasets.append({
            "name": view.dataset,
            "domain": view.domain,
            "business_name": view.business_name,
            "purpose": view.purpose,
            "grain": view.grain,
            "primary_keys": ["reporting_month", "customer_id", "facility_id"],
            "period_field": "reporting_month",
            "owner": view.owner,
            "status": canonical.get("status", "active"),
            "version": canonical.get("version", "1.0.0"),
            "is_synthetic": True,
            "origin": canonical.get("origin", "demo"),
            "dataset_family": view.dataset,
            "authoritative_for": list(view.authoritative_for),
            "portfolio_scope": canonical.get("portfolio_scope", "RETAIL_BOOK"),
            "fields": fields,
        })
        added.append(view.dataset)
    if added:
        payload["datasets"] = datasets
        path.write_text(json.dumps(payload, indent=2))
    return added
