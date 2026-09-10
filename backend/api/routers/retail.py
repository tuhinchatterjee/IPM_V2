"""
The retail product's own API surface.

One domain, one canonical table, and the endpoints the retail screens actually
read: the published manifest, a portfolio view for a month, a customer's whole
position, the Early Warning book, the ECL movement bridge, scorecard monitoring
and What-If.

Every response carries the dataset version and the snapshot it was computed
from, so a figure on a screen can be traced to the exact published data that
produced it. Every response also carries the synthetic disclosure, because a
figure that travels without it eventually gets quoted as if it were the bank's.

Reads are projected: a screen asking for a portfolio total does not pull five
hundred columns across nineteen thousand rows into memory to add up one of them.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.config import settings
from backend.retail import DOMAIN_DISPLAY, DOMAIN_ID, SYNTHETIC_DISCLOSURE
from backend.retail import ecl as ecl_mod
from backend.retail import ews as ews_mod
from backend.retail import monitoring as mon
from backend.retail import whatif as wif
from backend.retail.config import load_config
from backend.retail.exports import json_safe
from backend.retail.generate import PERIOD_FIELD
from backend.retail.models_registry import APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS
from backend.retail.movement import decompose
from backend.retail.profile import missing_seed_error
from backend.retail.taxonomy import PRODUCT_LABELS, resolve_product

router = APIRouter(prefix="/retail", tags=["retail"])

DATASET = "retail_facility_month"


def _dataset_dir() -> Path:
    return Path(settings.analytics_dir) / DATASET


def _months() -> list[str]:
    directory = _dataset_dir()
    if not directory.exists():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(missing_seed_error()))
    months = sorted(p.name.split("=", 1)[1] for p in directory.glob(f"{PERIOD_FIELD}=*"))
    if not months:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(missing_seed_error()))
    return months


def _resolve_month(month: str | None) -> str:
    months = _months()
    if month is None or month == "latest":
        return months[-1]
    if month not in months:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"'{month}' is not a published month. Cockpit Data holds "
            f"{months[0]} to {months[-1]}, {len(months)} months in all.",
        )
    return month


def _read(month: str, columns: list[str] | None = None) -> pd.DataFrame:
    path = _dataset_dir() / f"{PERIOD_FIELD}={month}" / "data.parquet"
    try:
        return pd.read_parquet(path, columns=columns)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"No published data for {month}.") from None


@functools.lru_cache(maxsize=1)
def _manifest() -> dict[str, Any]:
    import json
    path = Path(settings.metadata_dir) / "retail_dataset_manifest.json"
    if not path.exists():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(missing_seed_error()))
    return json.loads(path.read_text())


def _envelope(month: str, **extra: Any) -> dict[str, Any]:
    return {
        "domain_id": DOMAIN_ID,
        "domain_display": DOMAIN_DISPLAY,
        "dataset": DATASET,
        "dataset_version": _manifest()["dataset_version"],
        "snapshot_month": month,
        "is_synthetic": True,
        "disclosure": SYNTHETIC_DISCLOSURE,
        **extra,
    }


# --------------------------------------------------------------------------
# The published book
# --------------------------------------------------------------------------

@router.get("/manifest", summary="The published retail domain and its months")
def manifest() -> dict:
    m = _manifest()
    return json_safe({
        **_envelope(m["last_snapshot"][:7]),
        "months": [
            {
                "reporting_month": x["reporting_month"],
                "snapshot_date": x["snapshot_date"],
                "rows": x["rows"],
                "distinct_customers": x["distinct_customers"],
                "distinct_facilities": x["distinct_facilities"],
                "products": x["products"],
                "validation_status": x["validation_status"],
                "content_hash": x["content_hash"][:16],
            }
            for x in m["months"]
        ],
        "month_count": len(m["months"]),
        "first_snapshot": m["first_snapshot"],
        "last_snapshot": m["last_snapshot"],
        "total_rows": m["total_rows"],
        "generator_version": m["generator_version"],
        "seed": m["seed"],
        "manifest_hash": m["manifest_hash"][:16],
        "scenario_weights": m["scenario_weights"],
    })


@router.get("/portfolio", summary="The retail book at one month, by product")
def portfolio(month: str | None = Query(None), product: str | None = Query(None)) -> dict:
    m = _resolve_month(month)
    columns = ["customer_id", "facility_id", "product_code", "ifrs9_stage",
               "gross_carrying_amount_sar", "ecl_final_sar", "ecl_base_sar",
               "ecl_upturn_sar", "ecl_downturn_sar", "ecl_weighted_sar",
               "management_overlay_sar", "dpd"]
    frame = _read(m, columns)
    if product:
        code = resolve_product(product)
        if code is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"'{product}' is not a retail product family. Available: "
                + ", ".join(f"{k} ({v})" for k, v in PRODUCT_LABELS.items()))
        frame = frame[frame["product_code"] == code]

    def _rows(group: pd.DataFrame) -> dict[str, Any]:
        gca = float(group["gross_carrying_amount_sar"].sum())
        ecl = float(group["ecl_final_sar"].sum())
        return {
            "customers": int(group["customer_id"].nunique()),
            "facilities": int(group["facility_id"].nunique()),
            "gross_carrying_amount_sar": round(gca, 2),
            "ecl_final_sar": round(ecl, 2),
            "ecl_base_sar": round(float(group["ecl_base_sar"].sum()), 2),
            "ecl_upturn_sar": round(float(group["ecl_upturn_sar"].sum()), 2),
            "ecl_downturn_sar": round(float(group["ecl_downturn_sar"].sum()), 2),
            "coverage_ratio": round(ecl / gca, 6) if gca > 0 else None,
            "stage_facilities": {int(k): int(v) for k, v in
                                 group["ifrs9_stage"].value_counts().sort_index().items()},
            "dpd_30_plus_facilities": int((group["dpd"] >= 30).sum()),
            "dpd_90_plus_facilities": int((group["dpd"] >= 90).sum()),
        }

    by_product = {
        str(code): {"label": PRODUCT_LABELS.get(str(code), str(code)), **_rows(group)}
        for code, group in frame.groupby("product_code", sort=True)
    }
    return json_safe({
        **_envelope(m),
        "total": _rows(frame),
        "by_product": by_product,
        "notes": [
            "Exposure and the loss allowance are month-end STOCKS. They are the "
            "position on this date, not a sum across the published months.",
            "Customers are counted distinctly: a customer with three facilities "
            "is one customer.",
        ],
    })


@router.get("/customers", summary="Find a retail customer")
def customers(q: str = Query("", max_length=64), month: str | None = Query(None),
              limit: int = Query(20, ge=1, le=100)) -> dict:
    m = _resolve_month(month)
    frame = _read(m, ["customer_id", "facility_id", "region_label", "employment_status",
                      "customer_segment", "gross_carrying_amount_sar", "ifrs9_stage"])
    if q:
        frame = frame[frame["customer_id"].str.contains(q, case=False, na=False)]
    grouped = frame.groupby("customer_id", sort=True).agg(
        facilities=("facility_id", "nunique"),
        exposure_sar=("gross_carrying_amount_sar", "sum"),
        worst_stage=("ifrs9_stage", "max"),
        region=("region_label", "first"),
        employment=("employment_status", "first"),
        segment=("customer_segment", "first"),
    ).reset_index().head(limit)
    return json_safe({**_envelope(m),
                      "count": int(len(grouped)),
                      "customers": grouped.to_dict("records")})


@router.get("/customer/{customer_id}", summary="One retail customer, in full")
def customer(customer_id: str, month: str | None = Query(None)) -> dict:
    """Everything the book knows about one natural person at one month-end.

    Customer-level figures — income, obligations, debt burden, disposable
    income — are reported ONCE, taken from the first of their facility rows
    where they are by definition identical. Summing them across the rows would
    report one person's income as many times as they hold facilities.
    """
    m = _resolve_month(month)
    frame = _read(m)
    theirs = frame[frame["customer_id"] == customer_id]
    if theirs.empty:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No retail customer '{customer_id}' at {m}. This installation holds "
            "Saudi retail customers only.")

    head = theirs.iloc[0]
    customer_level = {
        "customer_id": customer_id,
        "region": head.get("region_label"),
        "city": head.get("city"),
        "branch_id": head.get("branch_id"),
        "customer_segment": head.get("customer_segment"),
        "residency_category": head.get("residency_category"),
        "age_band": head.get("age_band"),
        "dependants_band": head.get("dependants_band"),
        "employment_status": head.get("employment_status"),
        "employer_id": head.get("employer_id"),
        "employer_sector": head.get("employer_sector"),
        "employment_tenure_months": head.get("employment_tenure_months"),
        "salary_transfer_flag": bool(head.get("salary_transfer_flag")),
        "customer_tenure_months": head.get("customer_tenure_months"),
        "verified_monthly_salary_sar": head.get("verified_monthly_salary_sar"),
        "verified_total_monthly_income_sar": head.get("verified_total_monthly_income_sar"),
        "household_expenses_sar": head.get("household_expenses_sar"),
        "monthly_external_credit_obligations_sar":
            head.get("monthly_external_credit_obligations_sar"),
        "monthly_own_bank_credit_obligations_sar":
            head.get("monthly_own_bank_credit_obligations_sar"),
        "monthly_total_credit_obligations_sar": head.get("monthly_total_credit_obligations_sar"),
        "obligation_scope_definition": head.get("obligation_scope_definition"),
        "disposable_income_sar": head.get("disposable_income_sar"),
        "debt_burden_ratio": head.get("debt_burden_ratio"),
        "income_band": head.get("income_band"),
        "indebtedness_band": head.get("indebtedness_band"),
        "bureau_score_current": head.get("bureau_score_current"),
        "bureau_score_change_3m": head.get("bureau_score_change_3m"),
        "bureau_source_label": head.get("bureau_source_label"),
        "bureau_scale_id": head.get("bureau_score_scale_id"),
        "salary_missed_cycle_count_3m": head.get("salary_missed_cycle_count_3m"),
        "balance_buffer_months": head.get("balance_buffer_months"),
        "employment_change_flag": bool(head.get("employment_change_flag")),
        "job_loss_reported_flag": bool(head.get("job_loss_reported_flag")),
    }

    facility_columns = [
        "facility_id", "product_code", "product_label", "product_subsegment",
        "origination_date", "origination_vintage", "months_on_book",
        "contractual_maturity_date", "remaining_contractual_tenor_months",
        "original_finance_amount_sar", "current_credit_limit_sar",
        "outstanding_principal_sar", "gross_carrying_amount_sar",
        "undrawn_commitment_sar", "utilisation_ratio", "scheduled_monthly_payment_sar",
        "dpd", "dpd_bucket", "current_default_flag", "forbearance_flag", "cure_flag",
        "collections_stage", "ifrs9_stage", "previous_month_stage", "sicr_reason",
        "pd_pit_12m_base", "pd_pit_lifetime_base", "lgd_base", "ead_base_sar",
        "ecl_base_sar", "ecl_upturn_sar", "ecl_downturn_sar", "ecl_weighted_sar",
        "ecl_final_sar", "ecl_coverage_ratio", "ecl_horizon_type", "ecl_horizon_months",
        "application_score_at_origination", "application_score_band",
        "application_predicted_pd_12m", "application_score_model_id",
        "behavioural_score", "behavioural_score_band", "behavioural_predicted_pd_12m",
        "behavioural_score_status", "behavioural_score_change_3m",
        "bureau_score_at_origination", "ltv_current_ratio", "collateral_value_current_sar",
        "secured_flag",
    ]
    facilities = theirs[[c for c in facility_columns if c in theirs.columns]]

    # The customer's own history: one row per published month they were live.
    history: list[dict[str, Any]] = []
    for hm in _months():
        slim = _read(hm, ["customer_id", "gross_carrying_amount_sar", "ecl_final_sar",
                          "dpd", "ifrs9_stage", "behavioural_score",
                          "salary_credit_amount_1m_sar", "utilisation_ratio"])
        rows = slim[slim["customer_id"] == customer_id]
        if rows.empty:
            continue
        history.append({
            "reporting_month": hm,
            "facilities": int(len(rows)),
            "gross_carrying_amount_sar": round(float(rows["gross_carrying_amount_sar"].sum()), 2),
            "ecl_final_sar": round(float(rows["ecl_final_sar"].sum()), 2),
            "max_dpd": int(pd.to_numeric(rows["dpd"]).max()),
            "worst_stage": int(rows["ifrs9_stage"].max()),
            "behavioural_score": (None if rows["behavioural_score"].isna().all()
                                  else round(float(pd.to_numeric(
                                      rows["behavioural_score"]).mean()), 1)),
            "salary_credit_sar": round(float(
                pd.to_numeric(rows["salary_credit_amount_1m_sar"]).iloc[0] or 0.0), 2),
        })

    alerts = ews_mod.evaluate_snapshot(frame)
    theirs_alerts = alerts[alerts["customer_id"] == customer_id]

    return json_safe({
        **_envelope(m),
        "customer": customer_level,
        "facility_count": int(len(facilities)),
        "exposure_sar": round(float(theirs["gross_carrying_amount_sar"].sum()), 2),
        "ecl_final_sar": round(float(theirs["ecl_final_sar"].sum()), 2),
        "facilities": facilities.to_dict("records"),
        "history": history,
        "alerts": theirs_alerts.to_dict("records"),
        "notes": [
            "Income, obligations, debt burden and disposable income are CUSTOMER "
            "values. They are reported once here, not once per facility.",
            "Exposure and the loss allowance are summed across this customer's "
            "facilities at this month-end, each facility counted once.",
        ],
    })


@router.get("/facility/{facility_id}/score", summary="Reconstruct a facility's scores")
def facility_score(facility_id: str, month: str | None = Query(None)) -> dict:
    """Raw input, transformation, bin and points, adding to the score exactly."""
    m = _resolve_month(month)
    frame = _read(m)
    rows = frame[frame["facility_id"] == facility_id]
    if rows.empty:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"No retail facility '{facility_id}' at {m}.")
    row = rows.iloc[0]
    product = str(row["product_code"])
    out: dict[str, Any] = {**_envelope(m), "facility_id": facility_id,
                           "product_code": product,
                           "product_label": PRODUCT_LABELS.get(product, product)}

    app_card = APPLICATION_SCORECARDS[product]
    out["application"] = app_card.reconstruct(row)
    out["application"]["as_at"] = str(row.get("application_score_date"))
    out["application"]["note"] = (
        "Scored once, on the application date, and frozen on every later "
        "snapshot. A change in current income does not move it."
    )

    if pd.isna(row.get("behavioural_score")):
        out["behavioural"] = {
            "status": row.get("behavioural_score_status"),
            "detail": (
                f"Not scored: {row.get('behaviour_history_months_available')} months of "
                "observed behaviour are available and the model needs three. Thin "
                "history is a different state from a low score."
            ),
        }
    else:
        beh_card = BEHAVIOURAL_SCORECARDS[product]
        out["behavioural"] = beh_card.reconstruct(row)
        out["behavioural"]["as_at"] = str(row.get("behavioural_score_date"))
    return json_safe(out)


# --------------------------------------------------------------------------
# Early Warning
# --------------------------------------------------------------------------

@router.get("/early-warning", summary="Retail warnings at one month")
def early_warning(month: str | None = Query(None),
                  severity: str | None = Query(None),
                  limit: int = Query(200, ge=1, le=2000)) -> dict:
    m = _resolve_month(month)
    frame = _read(m)
    alerts = ews_mod.evaluate_snapshot(frame)
    if severity:
        alerts = alerts[alerts["severity"].str.upper() == severity.upper()]
    exposure = ews_mod.affected_exposure(alerts)
    by_rule = (alerts.groupby(["rule_id", "rule_name", "severity"], sort=True)
               .size().reset_index(name="alerts").to_dict("records")) if len(alerts) else []
    return json_safe({
        **_envelope(m),
        "rulebook_version": ews_mod.RULEBOOK_VERSION,
        "alert_count": int(len(alerts)),
        "distinct_customers": int(alerts["customer_id"].nunique()) if len(alerts) else 0,
        "affected_exposure_sar": exposure,
        "portfolio_exposure_sar": round(float(frame["gross_carrying_amount_sar"].sum()), 2),
        "by_rule": by_rule,
        "alerts": alerts.head(limit).to_dict("records"),
        "notes": [
            "Affected exposure counts each facility once, even where two rules "
            "cover it and even where a customer-level rule attaches several.",
            "Recommended actions are reviews. Nothing here changes a limit or "
            "contacts a customer.",
        ],
    })


@router.get("/early-warning/rulebook", summary="The retail rule library")
def rulebook() -> dict:
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **ews_mod.rulebook()})


# --------------------------------------------------------------------------
# ECL movement
# --------------------------------------------------------------------------

@router.get("/movement", summary="The ECL bridge between two months")
def movement(from_month: str = Query(..., alias="from"),
             to_month: str = Query(..., alias="to")) -> dict:
    a, b = _resolve_month(from_month), _resolve_month(to_month)
    if a >= b:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"'{from_month}' must be earlier than '{to_month}'.")
    bridge = decompose(_read(a), _read(b))
    return json_safe({**_envelope(b), "opening_month": a, **bridge})


# --------------------------------------------------------------------------
# Scorecard monitoring
# --------------------------------------------------------------------------

@router.get("/monitoring/application", summary="Application scorecard discrimination")
def application_monitoring(product: str = Query("PERSONAL_LOAN")) -> dict:
    code = resolve_product(product) or product.upper()
    if code not in APPLICATION_SCORECARDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"'{product}' is not a retail product family.")
    columns = ["months_on_book", "monitoring_eligible_flag",
               "performance_window_complete_flag", "application_id", "product_code",
               "application_score_at_origination", "application_score_band",
               "application_predicted_pd_12m", "observed_default_within_window",
               "customer_id", "reporting_month"]
    frames = [_read(m, columns) for m in _months()]
    everything = pd.concat(frames, ignore_index=True)
    cohort = mon.application_cohort(everything)
    cohort = cohort[cohort["product_code"] == code]

    metrics = [
        mon.auc(cohort["application_score_at_origination"],
                cohort["observed_default_within_window"],
                customer_ids=cohort["customer_id"]),
        mon.gini(cohort["application_score_at_origination"],
                 cohort["observed_default_within_window"],
                 customer_ids=cohort["customer_id"]),
        mon.ks(cohort["application_score_at_origination"],
               cohort["observed_default_within_window"]),
    ]
    ci = mon.bootstrap_ci(cohort["application_score_at_origination"],
                          cohort["observed_default_within_window"],
                          statistic="gini", draws=200)
    if ci:
        metrics[1].uncertainty = ci

    card = APPLICATION_SCORECARDS[code]
    envelope = mon.evidence_envelope(
        question=f"How does the {PRODUCT_LABELS[code]} application scorecard discriminate?",
        model_id=card.model_id, model_version=card.model_version,
        target=card.target_event, horizon_months=card.horizon_months,
        evaluation_as_of=_months()[-1],
        cohort_dates=sorted(cohort["reporting_month"].unique()) if len(cohort) else [],
        metrics=metrics,
        exclusions={
            "not_at_origination": int((everything["months_on_book"] != 0).sum()),
            "window_not_complete": int(
                (~everything["performance_window_complete_flag"].fillna(False)).sum()),
            "already_in_default": int(
                (~everything["monitoring_eligible_flag"].fillna(False)).sum()),
        },
        reference_definition="Origination cohorts with a fully observed 12-month window",
        dataset_hashes=[_manifest()["manifest_hash"][:16]],
        findings=[],
        limitations=[
            "Each application is counted once, at origination. An application "
            "score repeated across monthly snapshots is one observation.",
            "Cohorts whose twelve-month window has not fully elapsed are excluded "
            "and counted, not treated as good.",
        ])
    bands = mon.band_table(cohort["application_score_at_origination"],
                           cohort["observed_default_within_window"],
                           cohort["application_score_band"])
    calibration = mon.calibration(cohort["application_predicted_pd_12m"],
                                  cohort["observed_default_within_window"])
    return json_safe({
        **_envelope(_months()[-1]),
        "product_code": code,
        "evidence": envelope,
        "band_table": bands.to_dict("records"),
        "calibration": calibration,
    })


# --------------------------------------------------------------------------
# What-If
# --------------------------------------------------------------------------

class ScenarioIn(BaseModel):
    name: str = Field("Scenario", max_length=120)
    month: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    shocks: dict[str, Any] = Field(default_factory=dict)
    staging_mode: str = wif.FROZEN_STAGE
    scenario_weights: dict[str, float] | None = None


@router.get("/whatif/methodologies", summary="What the retail What-If supports")
def methodologies() -> dict:
    return {
        "methodology_version": wif.METHODOLOGY_VERSION,
        "supported": wif.SUPPORTED_METHODOLOGIES,
        "staging_modes": [wif.FROZEN_STAGE, wif.REEVALUATE_STAGE],
        "disclosure": SYNTHETIC_DISCLOSURE,
    }


@router.post("/whatif", summary="Run a retail What-If scenario")
def run_whatif(payload: ScenarioIn) -> dict:
    m = _resolve_month(payload.month)
    frame = _read(m)
    scenario = wif.Scenario(
        name=payload.name,
        dataset_version=_manifest()["dataset_version"],
        snapshot_date=str(frame["snapshot_date"].iloc[0]),
        filters=payload.filters, shocks=payload.shocks,
        staging_mode=payload.staging_mode,
        scenario_weights=payload.scenario_weights)
    try:
        scenario.validate()
    except wif.UnsupportedShock as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    try:
        result = wif.run(frame, scenario, load_config())
    except KeyError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e).strip('"')) from e
    return json_safe({**_envelope(m), **result})


@router.post("/whatif/cutoff", summary="Replay a different application cutoff")
def whatif_cutoff(cutoff: dict[str, float], month: str | None = Query(None)) -> dict:
    m = _resolve_month(month)
    unknown = sorted(set(cutoff) - set(PRODUCT_LABELS))
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown product family: {', '.join(unknown)}. Valid: "
            + ", ".join(PRODUCT_LABELS))
    frame = _read(m, ["facility_id", "product_code",
                      "application_score_at_origination",
                      "gross_carrying_amount_sar", "observed_default_within_window"])
    return json_safe({**_envelope(m), **wif.cutoff_replay(frame, cutoff)})
