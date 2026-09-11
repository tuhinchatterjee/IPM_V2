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
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst, RequireCommenter
from backend.config import settings
from backend.retail import DOMAIN_DISPLAY, DOMAIN_ID, SYNTHETIC_DISCLOSURE
from backend.retail import ecl as ecl_mod
from backend.retail import ews as ews_mod
from backend.retail import monitoring as mon
from backend.retail import whatif as wif
from backend.retail.config import load_config
from backend.retail.exports import json_safe, to_csv, to_json
from backend.retail.generate import PERIOD_FIELD
from backend.retail.models_registry import APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS
from backend.retail.movement import decompose
from backend.retail.profile import missing_seed_error
from backend.retail.taxonomy import PRODUCT_LABELS, resolve_product

#: Everything under /retail needs a signed-in user, and the endpoints that RUN
#: something need one who may run an analysis.
#:
#: The failure this prevents: the retail router carried no dependency at all,
#: so every endpoint under it — the portfolio, a named customer's whole
#: position, the Early Warning book — answered 200 to a request with no session
#: at all, on an installation where REQUIRE_LOGIN is on and every other router
#: refuses. The data is synthetic; the hole was not.
router = APIRouter(prefix="/retail", tags=["retail"],
                   dependencies=[RequireCommenter])

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


def _bureau(theirs: pd.DataFrame) -> dict[str, Any]:
    """The customer's bureau readings, as the book actually holds them."""
    scores = pd.to_numeric(theirs.get("bureau_score_current"),
                           errors="coerce").dropna()
    changes = pd.to_numeric(theirs.get("bureau_score_change_3m"),
                            errors="coerce").dropna()
    if scores.empty:
        return {"bureau_score_current": None, "bureau_score_change_3m": None,
                "bureau_score_low": None, "bureau_score_high": None,
                "bureau_observations": 0,
                "bureau_basis": "No bureau reading is published for this "
                                "customer at this month."}
    low, high = float(scores.min()), float(scores.max())
    return {
        # The LOWEST reading, named as such: a credit decision reads the worst
        # evidence it has, and an average of bureau observations is not a
        # bureau score.
        "bureau_score_current": low,
        "bureau_score_change_3m": (float(changes.min()) if not changes.empty
                                   else None),
        "bureau_score_low": low,
        "bureau_score_high": high,
        "bureau_observations": int(len(scores)),
        "bureau_basis": (
            f"{len(scores)} bureau observations are recorded against this "
            f"customer's facilities at this month-end"
            + (f", ranging {low:.0f} to {high:.0f}. The LOWEST is shown: a "
               "decision reads the worst evidence it holds, and an average of "
               "bureau observations is not a bureau score."
               if high > low else ". They agree.")),
    }


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
        # The bureau reading is recorded per FACILITY observation in this
        # synthetic book, and a customer with six facilities carries six of
        # them — 600 to 651 for one person at 2026-08. Reporting the first row's
        # value as "the customer's bureau score" would present one arbitrary
        # observation as a fact about the person, so the spread is reported and
        # the screen says what it is.
        **_bureau(theirs),
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
    # The month before this one, so affordability is measured against last
    # month rather than against origination. See RET-EWS-011.
    months = _months()
    at = months.index(m) if m in months else 0
    previous = _read(months[at - 1]) if at > 0 else None
    alerts = ews_mod.evaluate_snapshot(ews_mod.with_prior_month(frame, previous))
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
def run_whatif(payload: ScenarioIn, _: Principal = RequireAnalyst) -> dict:
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
def whatif_cutoff(cutoff: dict[str, float], month: str | None = Query(None),
                  _: Principal = RequireAnalyst) -> dict:
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


# --------------------------------------------------------------- What-If chat
#
# The conversational half of What-If. The engine above is exact and refuses
# what it does not implement; this is the part a person types at, and it keeps
# the same promises: a unit is never guessed, an instruction is never dropped,
# and nothing is normalised behind the reader's back.


class AskIn(BaseModel):
    question: str = Field("", max_length=2000)
    month: str | None = None
    #: The scenario the conversation is already holding, so "apply the same
    #: shock only to salary-transfer customers" narrows THAT scenario.
    carried: dict[str, Any] = Field(default_factory=dict)
    #: Set when the user answers a units clarification by clicking an option.
    chosen: dict[str, Any] | None = None
    #: The run already on the table, so "what changed, and why?" is answered
    #: about THAT run instead of being read as a scenario with no shocks.
    last_run: dict[str, Any] | None = None


class SaveIn(BaseModel):
    name: str = Field("", max_length=120)
    question: str = Field("", max_length=2000)
    month: str = Field("", max_length=16)
    run: dict[str, Any] = Field(default_factory=dict)


def _owner_of(principal: Principal | None) -> int | None:
    """Who is asking. The store scopes every read and write to this."""
    return getattr(principal, "user_id", None)


@router.get("/whatif/landing", summary="Everything the retail What-If screen shows")
def whatif_landing(principal: Principal = RequireCommenter) -> dict:
    from backend.retail import profile as prof
    from backend.retail import whatif_store as store

    months = _months()
    saved: list[dict[str, Any]] = []
    persistence = "Saved What-Ifs are stored for you and reopened as they ran."
    try:
        saved = [s.card() for s in store.listing(owner=_owner_of(principal))]
    except store.Unavailable as e:
        persistence = str(e)
    return json_safe({
        "heading": "What-If",
        "domain": DOMAIN_DISPLAY,
        "dataset": DATASET,
        "months": months,
        "latest_month": months[-1] if months else None,
        "methodology_version": wif.METHODOLOGY_VERSION,
        "supported": wif.SUPPORTED_METHODOLOGIES,
        "staging_modes": [wif.FROZEN_STAGE, wif.REEVALUATE_STAGE],
        "starters": list(prof.SCENARIO_STARTERS),
        "saved": saved,
        "persistence": persistence,
        "disclosure": SYNTHETIC_DISCLOSURE,
    })


@router.post("/whatif/ask", summary="Type a retail scenario in words")
def whatif_ask(payload: AskIn,
               principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_language as lang

    months = _months()
    ask = lang.read(payload.question, months, payload.carried or {})
    if payload.chosen:
        # A clarification answered by clicking. The chosen reading REPLACES the
        # ambiguous one; it is not merged with a guess taken in the meantime.
        ask.question = ""
        ask.options = []
        ask.shocks.update(dict(payload.chosen.get("shocks") or {}))
        for column, value in (payload.carried.get("filters") or {}).items():
            ask.filters.setdefault(column, value)
        ask.shocks.update({k: v for k, v in (payload.carried.get("shocks") or {}).items()
                           if k not in ask.shocks})

    month = _resolve_month(payload.month or ask.month or None)

    if lang.wants_explanation(payload.question) and not payload.chosen:
        return _explain(payload, month)

    if ask.needs_clarification:
        return json_safe({
            **_envelope(month),
            "kind": "clarification",
            "question": ask.question,
            "options": ask.options,
            "read_as": ask.read_as,
            "scenario_so_far": ask.to_dict(),
        })

    if ask.unsupported and not ask.shocks and ask.scenario_weights is None:
        return json_safe({
            **_envelope(month),
            "kind": "refusal",
            "question": payload.question,
            "unsupported": ask.unsupported,
            "supported": wif.SUPPORTED_METHODOLOGIES,
            "message": (
                "CreditProbe will not run part of a scenario and call it the "
                "scenario. It reads: " + "; ".join(ask.unsupported)
                + ". What this retail engine implements: "
                + lang.supported_sentence() + "."),
        })

    frame = _read(month)
    scenario = wif.Scenario(
        name=ask.name or (payload.question[:80] or "Scenario"),
        dataset_version=_manifest()["dataset_version"],
        snapshot_date=str(frame["snapshot_date"].iloc[0]),
        filters=ask.filters, shocks=ask.shocks,
        staging_mode=ask.staging_mode,
        scenario_weights=ask.scenario_weights)
    try:
        scenario.validate()
        result = wif.run(frame, scenario, load_config())
    except wif.UnsupportedShock as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except (ValueError, KeyError) as e:
        # A validation refusal is an ANSWER, not a server error: the weights
        # that do not sum to one are the thing the reader needs to see.
        return json_safe({
            **_envelope(month),
            "kind": "invalid",
            "question": payload.question,
            "message": str(e).strip('"'),
            "read_as": ask.read_as,
            "scenario_so_far": ask.to_dict(),
        })
    return json_safe({
        **_envelope(month),
        "kind": "result",
        "question": payload.question,
        "read_as": ask.read_as,
        "neutral": ask.is_neutral,
        "unsupported": ask.unsupported,
        **result,
    })


def _explain(payload: "AskIn", month: str) -> dict:
    """Explain the run already on the table, from that run's own figures.

    Nothing is recomputed and nothing is invented: every number in the answer
    is read out of the run the reader is looking at, and the assumptions and
    limitations are the ones that run carried.
    """
    run = payload.last_run or {}
    scenario = run.get("scenario") or {}
    baseline = run.get("baseline") or {}
    result = run.get("scenario_result") or {}
    delta = run.get("delta") or {}
    if not scenario:
        return json_safe({
            **_envelope(month),
            "kind": "explanation",
            "question": payload.question,
            "message": ("There is no scenario on the table yet. Describe a "
                        "change and CreditProbe will run it, then explain it."),
            "lines": [],
        })

    shocks = scenario.get("shocks") or {}
    change = float(delta.get("ecl_final_sar") or 0.0)
    pct = delta.get("ecl_final_pct")
    direction = "rose" if change > 0 else ("fell" if change < 0 else "did not move")
    lines = [
        f"Expected credit loss {direction} from SAR "
        f"{baseline.get('ecl_final_sar', 0):,.0f} to SAR "
        f"{result.get('ecl_final_sar', 0):,.0f}"
        + (f" — a change of SAR {change:,.0f}"
           f" ({pct * 100:+.2f}%)." if isinstance(pct, (int, float)) else "."),
        "The population is "
        + (_pairs(scenario.get("filters") or {}) if scenario.get("filters")
           else "the whole retail book")
        + f", {baseline.get('facilities', 0):,} facilities held by "
          f"{baseline.get('customers', 0):,} customers at {month}.",
        ("Nothing was shocked: this is the published book."
         if not shocks else
         "What moved it: " + _pairs(shocks)
         + f", with staging {scenario.get('staging_mode', '')}."),
    ]
    drivers = sorted((run.get("drivers") or []),
                     key=lambda d: abs(float(d.get("delta_sar") or 0.0)),
                     reverse=True)[:3]
    if drivers:
        lines.append(
            "Largest contributions: "
            + "; ".join(f"{d.get('product_code')} SAR "
                        f"{float(d.get('delta_sar') or 0.0):,.0f}"
                        for d in drivers) + ".")
    return json_safe({
        **_envelope(month),
        "kind": "explanation",
        "question": payload.question,
        "lines": lines,
        "assumptions": run.get("assumptions") or [],
        "limitations": run.get("limitations") or [],
        "run_id": scenario.get("run_id", ""),
        "methodology_version": scenario.get("methodology_version", ""),
    })


@router.post("/whatif/save", summary="Keep a What-If run")
def whatif_save(payload: SaveIn,
                principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_store as store

    if not payload.run:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "There is no run to save.")
    try:
        saved = store.save(name=payload.name, question=payload.question,
                           month=payload.month, run=payload.run,
                           owner=_owner_of(principal))
    except store.Unavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return json_safe({"saved": saved.card()})


@router.get("/whatif/saved", summary="What-Ifs you have kept")
def whatif_saved(principal: Principal = RequireCommenter) -> dict:
    from backend.retail import whatif_store as store

    try:
        rows = store.listing(owner=_owner_of(principal))
    except store.Unavailable as e:
        return json_safe({"saved": [], "persistence": str(e)})
    return json_safe({"saved": [r.card() for r in rows]})


@router.get("/whatif/saved/{scenario_id}", summary="Reopen a saved What-If")
def whatif_reopen(scenario_id: int,
                  principal: Principal = RequireCommenter) -> dict:
    from backend.retail import whatif_store as store

    try:
        row = store.get(scenario_id, owner=_owner_of(principal))
    except store.Unavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e).strip('"')) from e
    # Exactly as it ran, on the snapshot it read. Never recomputed on open: a
    # saved scenario that quietly re-ran itself against a newer month would
    # show different figures under the name somebody saved.
    return json_safe({"saved": row.card(), **row.body})


@router.delete("/whatif/saved/{scenario_id}", summary="Delete a saved What-If")
def whatif_delete(scenario_id: int,
                  principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_store as store

    try:
        store.delete(scenario_id, owner=_owner_of(principal))
    except store.Unavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e).strip('"')) from e
    return {"deleted": scenario_id}


@router.get("/whatif/saved/{scenario_id}/export",
            summary="Download a saved What-If")
def whatif_export(scenario_id: int, fmt: str = Query("csv", pattern="^(csv|json)$"),
                  principal: Principal = RequireCommenter) -> Response:
    """The saved run as a file, carrying everything needed to check it.

    Not a picture of the screen: the file names the run, the snapshot, the
    methodology and its version, the population, every shock and every figure
    — so somebody who opens it a month later can reconcile it against the
    published book rather than take the number on trust.
    """
    from fastapi.responses import Response as FileResponse

    from backend.retail import whatif_store as store

    try:
        row = store.get(scenario_id, owner=_owner_of(principal))
    except store.Unavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e).strip('"')) from e

    run = row.body.get("run") or {}
    scenario = run.get("scenario") or {}
    baseline = run.get("baseline") or {}
    result = run.get("scenario_result") or {}
    delta = run.get("delta") or {}
    stem = _safe_filename(row.name)

    if fmt == "json":
        payload = {
            "disclosure": SYNTHETIC_DISCLOSURE,
            "saved": row.card(),
            "run": run,
        }
        return FileResponse(
            content=to_json(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition":
                     f'attachment; filename="{stem}.json"'})

    rows = [
        {"field": "Saved as", "value": row.name},
        {"field": "Question", "value": row.body.get("question", "")},
        {"field": "Reporting month", "value": row.body.get("month", "")},
        {"field": "Run id", "value": scenario.get("run_id", "")},
        {"field": "Dataset version", "value": scenario.get("dataset_version", "")},
        {"field": "Snapshot date", "value": scenario.get("snapshot_date", "")},
        {"field": "Methodology", "value": scenario.get("methodology_version", "")},
        {"field": "Staging mode", "value": scenario.get("staging_mode", "")},
        {"field": "Population filters",
         "value": _pairs(scenario.get("filters") or {})},
        {"field": "Shocks", "value": _pairs(scenario.get("shocks") or {})},
        {"field": "Scenario weights",
         "value": _pairs(scenario.get("scenario_weights") or {})},
        {"field": "Facilities", "value": baseline.get("facilities")},
        {"field": "Customers", "value": baseline.get("customers")},
        {"field": "Baseline ECL (SAR)", "value": baseline.get("ecl_final_sar")},
        {"field": "What-If ECL (SAR)", "value": result.get("ecl_final_sar")},
        {"field": "Change (SAR)", "value": delta.get("ecl_final_sar")},
        {"field": "Change (fraction of baseline)",
         "value": delta.get("ecl_final_pct")},
    ]
    for driver in (run.get("drivers") or []):
        rows.append({"field": f"Driver — {driver.get('product_code')} (SAR)",
                     "value": driver.get("delta_sar")})
    for line in (run.get("assumptions") or []) + (run.get("limitations") or []):
        rows.append({"field": "Assumption or limitation", "value": line})

    csv = to_csv(pd.DataFrame(rows), disclosure=True)
    return FileResponse(
        content=csv, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'})


def _pairs(mapping: dict[str, Any]) -> str:
    return "; ".join(f"{k}={v}" for k, v in sorted(mapping.items())) or "none"


def _safe_filename(name: str) -> str:
    """A filename a browser will accept and a header cannot be broken with."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "whatif")).strip("._")
    return (cleaned or "whatif")[:60]


@router.get("/whatif/compare", summary="Compare two saved What-Ifs")
def whatif_compare(left: int = Query(...), right: int = Query(...),
                   principal: Principal = RequireCommenter) -> dict:
    """Two saved runs side by side, with what differs between them named.

    The comparison is of the SELECTED runs, read back from the store, never of
    whatever happened to be in memory. Where the two do not share a month, a
    population or a methodology the difference is stated rather than papered
    over: two ECL figures from different books are not a movement.
    """
    from backend.retail import whatif_store as store

    owner = _owner_of(principal)
    try:
        rows = [store.get(left, owner=owner), store.get(right, owner=owner)]
    except store.Unavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e).strip('"')) from e

    cards = [row.card() for row in rows]
    differences: list[str] = []
    if cards[0]["month"] != cards[1]["month"]:
        differences.append(
            f"Different reporting months: {cards[0]['month']} and "
            f"{cards[1]['month']}. The two baselines are different books, so "
            "the gap between the results is not a scenario effect.")
    if cards[0]["filters"] != cards[1]["filters"]:
        differences.append(
            f"Different populations: {_pairs(cards[0]['filters'])} against "
            f"{_pairs(cards[1]['filters'])}.")
    if cards[0]["methodology_version"] != cards[1]["methodology_version"]:
        differences.append(
            "Different methodology versions: "
            f"{cards[0]['methodology_version']} and "
            f"{cards[1]['methodology_version']}.")
    if cards[0]["dataset_version"] != cards[1]["dataset_version"]:
        differences.append(
            "Different dataset versions: the two runs read different "
            "publications of the book.")

    comparable = not differences
    left_ecl = cards[0]["whatif_ecl"]
    right_ecl = cards[1]["whatif_ecl"]
    gap = (None if left_ecl is None or right_ecl is None
           else round(float(right_ecl) - float(left_ecl), 2))
    return json_safe({
        "left": cards[0],
        "right": cards[1],
        "comparable": comparable,
        "differences": differences,
        "ecl_gap_sar": gap,
        "note": ("Both runs are on the same book, so the difference between "
                 "them is the difference between the two scenarios."
                 if comparable else
                 "These runs do not share a baseline. The figures are shown "
                 "side by side and the difference is NOT reported as a "
                 "scenario effect."),
        "disclosure": SYNTHETIC_DISCLOSURE,
    })
