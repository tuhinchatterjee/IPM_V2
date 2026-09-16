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
from backend.retail import ews_layers
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
                  product: str | None = Query(
                      None, description="One retail product, or empty for all"),
                  customer: str | None = Query(
                      None, description="A customer or facility id, whole or "
                                        "partial"),
                  rule: str | None = Query(
                      None, description="One rule id, e.g. RET-EWS-001"),
                  family: str | None = Query(
                      None, description="One rulebook family, e.g. REPAYMENT"),
                  layer: str | None = Query(
                      None, description="One methodology layer key, e.g. "
                                        "repayment"),
                  sort: str = Query(
                      "severity",
                      description="severity | exposure | rule | customer"),
                  limit: int = Query(200, ge=1, le=2000)) -> dict:
    m = _resolve_month(month)
    frame = _read(m)
    # The month before this one, so affordability is measured against last
    # month rather than against origination. See RET-EWS-011.
    months = _months()
    at = months.index(m) if m in months else 0
    previous = _read(months[at - 1]) if at > 0 else None
    alerts = ews_mod.evaluate_snapshot(ews_mod.with_prior_month(frame, previous))
    # The chip decks are counted HERE, before any chip is applied.
    #
    # Counting them after would empty the screen the moment a reader clicked
    # one: pick CRITICAL and the severity deck would show CRITICAL alone, with
    # no way back to HIGH except the Clear button. The decks say what the month
    # raised; the headline says what the current filters match; the active chip
    # says which of them is on.
    universe = alerts
    if severity:
        alerts = alerts[alerts["severity"].str.upper() == severity.upper()]
    # A triage list nobody can narrow to a product is a triage list nobody
    # uses: 5,952 alerts across four products, and the person reading it owns
    # one of them this morning.
    if product:
        code = resolve_product(product) or product.upper()
        alerts = alerts[alerts["product_code"] == code]
    if customer:
        wanted = str(customer).strip().upper()
        if wanted:
            keys = (alerts["customer_id"].fillna("").str.upper()
                    + "|" + alerts["facility_id"].fillna("").str.upper())
            alerts = alerts[keys.str.contains(wanted, regex=False)]
    # §13: every chip on the screen is a filter. A rule chip that reads
    # "RET-EWS-001 · 348" and does nothing when clicked is a label; clicking
    # it has to narrow the list to those 348, and narrow the COUNT with it,
    # which means narrowing here rather than in the browser over a capped page.
    if rule:
        alerts = alerts[alerts["rule_id"].str.upper() == str(rule).strip().upper()]
    # Filtered here rather than in the browser for the same reason as the rule
    # chip: the browser only ever holds the capped page, so a family list built
    # from it offered five of the eleven families the month actually raised.
    if family:
        alerts = alerts[alerts["rule_family"].str.upper()
                        == str(family).strip().upper()]
    if layer:
        key = str(layer).strip().lower()
        wanted_families = {f for f in alerts["rule_family"].unique()
                           if ews_layers.layer_of(f) == key}
        alerts = alerts[alerts["rule_family"].isin(wanted_families)]
    alerts = _sorted_alerts(alerts, sort)
    exposure = ews_mod.affected_exposure(alerts)
    by_rule = _by_rule(universe)
    by_severity = [
        {"severity": name,
         "alerts": int(sum(r["alerts"] for r in by_rule if r["severity"] == name))}
        for name in reversed(ews_mod.SEVERITY_ORDER)
        if any(r["severity"] == name for r in by_rule)]
    by_family = [
        {"family": name,
         "alerts": int(sum(r["alerts"] for r in by_rule if r["rule_family"] == name))}
        for name in sorted({r["rule_family"] for r in by_rule})]
    by_layer = []
    for one in ews_layers.LAYERS:
        n = int(sum(r["alerts"] for r in by_rule if r["layer"] == one.key))
        if n:
            by_layer.append({"layer": one.key, "layer_name": one.name,
                             "alerts": n})
    unlayered = int(sum(r["alerts"] for r in by_rule if not r["layer"]))
    if unlayered:
        by_layer.append({"layer": "", "layer_name": "Data quality — not a risk layer",
                         "alerts": unlayered})
    by_product = []
    if len(universe):
        counted = (universe["product_code"].fillna("").replace("", "ALL PRODUCTS")
                   .value_counts())
        for code, n in counted.items():
            by_product.append({
                "product_code": "" if code == "ALL PRODUCTS" else str(code),
                "product_label": ("Raised against the customer, not one product"
                                  if code == "ALL PRODUCTS"
                                  else dict(PRODUCT_LABELS).get(str(code), str(code))),
                "alerts": int(n)})
    return json_safe({
        **_envelope(m),
        "rulebook_version": ews_mod.RULEBOOK_VERSION,
        "alert_count": int(len(alerts)),
        "distinct_customers": int(alerts["customer_id"].nunique()) if len(alerts) else 0,
        "affected_exposure_sar": exposure,
        "portfolio_exposure_sar": round(float(frame["gross_carrying_amount_sar"].sum()), 2),
        "by_rule": by_rule,
        # Every deck below counts the month, not the current filter. See the
        # note where `universe` is taken.
        "deck_total": int(len(universe)),
        "by_severity": by_severity,
        "by_family": by_family,
        "by_layer": by_layer,
        "by_product": by_product,
        # What the reader is actually looking at, said out loud. The screen
        # printed "ALERTS 500" while the rule chips under it added to 5,952:
        # 500 was the page size, not a finding.
        "returned": int(min(limit, len(alerts))),
        "capped": bool(len(alerts) > limit),
        "alerts": alerts.head(limit).to_dict("records"),
        # The severities this RULEBOOK uses, worst first. The screen offered a
        # hard-coded ALL/HIGH/MEDIUM/LOW: CRITICAL — the 232 alerts a Head of
        # Retail Risk opens the screen for — could not be selected at all, and
        # LOW was an option no rule could ever fill.
        "severities": [s for s in reversed(ews_mod.SEVERITY_ORDER)
                       if any(r["severity"] == s for r in by_rule)],
        "filters": {"severity": (severity or "").upper(),
                    "product": (resolve_product(product) or "").upper()
                    if product else "",
                    "customer": (customer or "").strip(),
                    "rule": (rule or "").strip().upper(),
                    "family": (family or "").strip().upper(),
                    "layer": (layer or "").strip().lower(),
                    "sort": _SORTS.get(sort, "severity")},
        "notes": [
            "Affected exposure counts each facility once, even where two rules "
            "cover it and even where a customer-level rule attaches several.",
            "Recommended actions are reviews. Nothing here changes a limit or "
            "contacts a customer.",
        ],
    })


def _by_rule(alerts: Any) -> list[dict]:
    """One row per rule, with the layer it rolls up into."""
    if not len(alerts):
        return []
    rows = (alerts.groupby(["rule_id", "rule_name", "severity", "rule_family"],
                           sort=True)
            .size().reset_index(name="alerts").to_dict("records"))
    for row in rows:
        row["layer"] = ews_layers.layer_of(row["rule_family"])
        found = ews_layers.get(row["layer"])
        row["layer_name"] = found.name if found else "Not a risk layer"
    return rows


#: How a triage list may be ordered, and what each ordering is FOR.
_SORTS: dict[str, str] = {
    "severity": "severity",
    "exposure": "exposure",
    "rule": "rule",
    "customer": "customer",
}

#: Worst first. An alphabetical severity sort puts CRITICAL after MEDIUM.
_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _sorted_alerts(alerts: Any, sort: str) -> Any:
    """The triage list in the order the reader asked for.

    Severity is ordered by what it MEANS rather than by its spelling: sorted
    as text, CRITICAL sorts before HIGH by luck and MEDIUM before them both
    the moment somebody adds a LOW.
    """
    if not len(alerts):
        return alerts
    wanted = _SORTS.get(str(sort or "").lower(), "severity")
    if wanted == "exposure":
        return alerts.sort_values("affected_exposure_sar", ascending=False)
    if wanted == "rule":
        return alerts.sort_values(["rule_id", "customer_id"])
    if wanted == "customer":
        return alerts.sort_values(["customer_id", "rule_id"])
    ranked = alerts.assign(
        _rank=alerts["severity"].str.upper().map(_SEVERITY_ORDER).fillna(9))
    return (ranked.sort_values(["_rank", "affected_exposure_sar"],
                               ascending=[True, False])
            .drop(columns=["_rank"]))


@router.get("/early-warning/rulebook", summary="The retail rule library")
def rulebook() -> dict:
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **ews_mod.rulebook()})


# --------------------------------------------------------------------------
# Early warning, as a portfolio
# --------------------------------------------------------------------------
#
# The screens above answer "which alerts fired?". These answer the question a
# Head of Retail Risk actually opens Early Warning to ask — where is the book
# going wrong, how badly, and who is it — down the hierarchy
#
#     portfolio -> product -> subsegment -> customer -> facility / signal
#
# Everything is served from the precomputed panel in
# `backend.retail.ews_portfolio`, which is built once at bootstrap. The
# rulebook is untouched and remains the signal layer underneath.

@router.get("/early-warning/portfolio",
            summary="The retail book through early warning, at one month")
def ews_portfolio_view(month: str | None = Query(None),
                       product: str | None = Query(
                           None, description="One retail product, or empty "
                                             "for the whole book"),
                       trend_months: int = Query(25, ge=2, le=60)) -> dict:
    from backend.retail import ews_portfolio as ewp

    code = (resolve_product(product) or "") if product else ""
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      **ewp.portfolio(month or "", product=code,
                                      trend_months=trend_months)})


@router.get("/early-warning/portfolio/products",
            summary="One card per retail product")
def ews_products(month: str | None = Query(None),
                 trend_months: int = Query(25, ge=2, le=60)) -> dict:
    from backend.retail import ews_portfolio as ewp

    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      "month": month or "",
                      "products": ewp.products(month or "",
                                               trend_months=trend_months)})


@router.get("/early-warning/portfolio/subsegments",
            summary="One product, broken into the pockets its data supports")
def ews_subsegments(product: str = Query(...),
                    month: str | None = Query(None),
                    dimension: str = Query(""),
                    trend_months: int = Query(25, ge=2, le=60)) -> dict:
    from backend.retail import ews_portfolio as ewp

    return json_safe({
        "disclosure": SYNTHETIC_DISCLOSURE,
        **ewp.subsegments(product, month or "", dimension=dimension,
                          trend_months=trend_months)})


@router.get("/early-warning/portfolio/customers",
            summary="The early-warning customer list")
def ews_customers(month: str | None = Query(None),
                  product: str = Query(""),
                  dimension: str = Query(""),
                  value: str = Query(""),
                  cohort: str = Query("all"),
                  limit: int = Query(200, ge=1, le=2000),
                  offset: int = Query(0, ge=0)) -> dict:
    from backend.retail import ews_portfolio as ewp

    return json_safe({
        "disclosure": SYNTHETIC_DISCLOSURE,
        **ewp.customers(month or "", product=product, dimension=dimension,
                        value=value, cohort=cohort, limit=limit,
                        offset=offset)})


@router.get("/early-warning/portfolio/customers/{customer_id}",
            summary="One customer, across every month scored")
def ews_customer(customer_id: str, month: str | None = Query(None),
                 trend_months: int = Query(25, ge=2, le=60)) -> dict:
    from backend.retail import ews_portfolio as ewp

    found = ewp.customer(customer_id, month or "", trend_months=trend_months)
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            found.get("because")
                            or f"{customer_id} is not in the panel.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


@router.get("/early-warning/portfolio/story",
            summary="The prebuilt product story: already bad, and next")
def ews_story(month: str | None = Query(None),
              product: str = Query("CREDIT_CARD")) -> dict:
    from backend.retail import ews_portfolio as ewp

    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      **ewp.story(month or "", product=product)})


@router.get("/early-warning/methodology-detail",
            summary="The current early-warning methodology, in full")
def ews_methodology() -> dict:
    from backend.retail import ews_portfolio as ewp

    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **ewp.methodology()})


@router.get("/early-warning/rules/{rule_id}",
            summary="One rule, and what it did to the book this month")
def ews_rule(rule_id: str, month: str | None = Query(None)) -> dict:
    from backend.retail import ews_portfolio as ewp

    found = ewp.rule_detail(rule_id, month or "")
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, found.get("because")
                            or f"{rule_id} is not a governed rule.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


# --------------------------------------------------------------------------
# The Early Warning Score workspace
#
# One domain — `retail_ews_score`, twenty monthly snapshots at
# customer-facility-month grain — read through `backend.retail.ews_views`.
# Every figure the workspace shows comes through here, so a number on a screen
# and the same number in the chat cannot come from different places.
# --------------------------------------------------------------------------

@router.get("/ews/portfolio", summary="Total retail, and the four products")
def ews_portfolio_view(month: str | None = Query(None)) -> dict:
    from backend.retail import ews_views as views

    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      **views.portfolio(month or "")})


@router.get("/ews/product/{product_code}",
            summary="One product, and its sub-portfolios")
def ews_product_view(product_code: str,
                     month: str | None = Query(None)) -> dict:
    from backend.retail import ews_views as views

    found = views.product(product_code, month or "")
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            found.get("because") or f"{product_code} is not a "
                                                    "retail product.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


@router.get("/ews/product/{product_code}/classification/{code}",
            summary="Salaried or Non-Salaried inside one product")
def ews_classification_view(product_code: str, code: str,
                            month: str | None = Query(None)) -> dict:
    from backend.retail import ews_views as views

    found = views.classification(product_code, code, month or "")
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            found.get("because") or "Not a governed "
                                                    "classification.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


@router.get("/ews/interpretation",
            summary="What the Early Warning figures mean, at any level")
def ews_interpretation_view(level: str = Query("portfolio"),
                            product: str | None = Query(None),
                            classification: str | None = Query(None),
                            sub_product: str | None = Query(None),
                            month: str | None = Query(None)) -> dict:
    """The management reading of a level, written from its own served figures.

    Deterministic: the same figures give the same paragraph, and no external
    model is called.
    """
    from backend.retail import ews_interpretation as reader
    from backend.retail import ews_views as views

    at = month or ""
    which = (level or "portfolio").lower()
    if which == "portfolio":
        found = reader.portfolio(views.portfolio(at))
    elif which == "product":
        found = reader.product(views.product(product or "", at))
    elif which == "classification":
        found = reader.classification(
            views.classification(product or "", classification or "", at))
    elif which == "sub_product":
        found = reader.sub_product(
            views.classification(product or "", classification or "", at)
            if classification else views.product(product or "", at),
            sub_product or "")
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{level!r} is not a level this reads.")
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            found.get("because") or "Nothing to interpret.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


@router.get("/ews/customers", summary="The Early Warning customer list")
def ews_customers_view(
        month: str | None = Query(None),
        product: str | None = Query(None),
        classification: str | None = Query(None),
        sub_product: str | None = Query(None),
        cohort: str = Query("all"),
        reason: str | None = Query(None),
        layer: str | None = Query(None),
        dpd_bucket: str | None = Query(None),
        stage: str | None = Query(None),
        score_min: float | None = Query(None, ge=0, le=100),
        score_max: float | None = Query(None, ge=0, le=100),
        behavioural_min: float | None = Query(None),
        behavioural_max: float | None = Query(None),
        search: str | None = Query(None, max_length=64),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0)) -> dict:
    from backend.retail import ews_views as views

    return json_safe({
        "disclosure": SYNTHETIC_DISCLOSURE,
        **views.customers(
            month or "", product=product or "",
            classification=classification or "",
            sub_product=sub_product or "",
            cohort=cohort, reason=reason or "", layer=layer or "",
            dpd_bucket=dpd_bucket or "", stage=stage or "",
            score_min=score_min, score_max=score_max,
            behavioural_min=behavioural_min, behavioural_max=behavioural_max,
            search=search or "", limit=limit, offset=offset)})


@router.get("/ews/customers/{customer_id}",
            summary="One customer: four layers, sublayers, triggers")
def ews_customer_view(customer_id: str,
                      month: str | None = Query(None)) -> dict:
    from backend.retail import ews_views as views

    found = views.customer(customer_id, month or "")
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            found.get("because")
                            or f"{customer_id} is not in the domain.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


@router.get("/ews/signals", summary="Every trigger, and what it caught")
def ews_signals_view(month: str | None = Query(None),
                     product: str | None = Query(None),
                     classification: str | None = Query(None),
                     sub_product: str | None = Query(None),
                     layer: str | None = Query(None),
                     severity: str | None = Query(None),
                     reason: str | None = Query(None),
                     limit: int = Query(500, ge=1, le=500)) -> dict:
    from backend.retail import ews_views as views

    return json_safe({
        "disclosure": SYNTHETIC_DISCLOSURE,
        **views.signals(month or "", product=product or "",
                        classification=classification or "",
                        sub_product=sub_product or "", layer=layer or "",
                        severity=severity or "", reason=reason or "",
                        limit=limit)})


@router.get("/ews/signals/{key}", summary="One trigger, with its history")
def ews_signal_view(key: str, month: str | None = Query(None)) -> dict:
    from backend.retail import ews_views as views

    found = views.signal(key, month or "")
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            found.get("because") or f"No trigger {key!r}.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


@router.get("/ews/model", summary="The model tree, with live hit counts")
def ews_model_view(month: str | None = Query(None)) -> dict:
    from backend.retail import ews_views as views

    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      **views.model(month or "")})


@router.get("/ews/model-log", summary="Every Early Warning model version")
def ews_model_log() -> dict:
    from backend.retail import ews_registry as registry

    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **registry.log()})


@router.get("/ews/model-log/{model_version}",
            summary="One model version, in full")
def ews_model_version(model_version: str) -> dict:
    from backend.retail import ews_registry as registry

    found = registry.record(model_version)
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            found.get("because") or "Unknown model version.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


@router.get("/ews/model-log/{model_version}/compare",
            summary="What changed between two model versions")
def ews_model_compare(model_version: str,
                      against: str | None = Query(None)) -> dict:
    from backend.retail import ews_registry as registry

    # No `against` means "what changed at this version", which is this
    # version against the one it replaced. The registry resolves that; an
    # explicit `against` compares any two.
    found = registry.compare(model_version, against or "")
    if not found.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            found.get("because") or "Cannot compare.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE, **found})


@router.get("/ews/model-log/{model_version}/report.docx",
            summary="The model development report, as a Word document")
def ews_model_report(model_version: str) -> Response:
    """Generated on request from the published panel, not from a stored file.

    A report that could disagree with the screen it was downloaded from would
    be worse than no report, so it is computed when it is asked for.
    """
    from backend.retail import ews_report

    try:
        data, name = ews_report.build(model_version)
    except ValueError as problem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(problem)) from problem
    return Response(
        content=data,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"),
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


class EwsExportIn(BaseModel):
    """What a card knows about itself when a reader exports it."""

    month: str | None = None
    level: str = "product"
    product: str | None = None
    classification: str | None = None
    sub_product: str | None = None
    customer_id: str | None = None
    cohort: str | None = None
    severity: str | None = None
    reason: str | None = None
    layer: str | None = None
    score_min: float | None = None
    score_max: float | None = None
    dpd_bucket: str | None = None
    stage: str | None = None
    route: str | None = None
    label: str | None = None


class CohortScenarioIn(BaseModel):
    selection_id: str
    shocks: dict[str, Any] = Field(default_factory=dict)
    #: A typed sentence, read by the governed parser. Given this, `shocks` is
    #: what the parser produced rather than what the caller assembled — the
    #: browser held its own short reader and understood five shocks where the
    #: parser understands the whole vocabulary.
    said: str = ""
    name: str = ""
    method: str = "delta"
    staging_mode: str = "frozen_stage"
    within: dict[str, Any] = Field(default_factory=dict)
    scenario_weights: dict[str, float] | None = None


@router.post("/ews/export-to-whatif",
             summary="Hand the selected Early Warning cohort to What-If")
def ews_export_to_whatif(payload: EwsExportIn,
                         principal: Principal = RequireAnalyst) -> dict:
    """Write the selection set for exactly what is on screen, §7 and §8.

    The canonical book is not touched: what is written is membership, with
    the source card, the filters and the counts at the moment of export.
    """
    from backend.retail import whatif_selection as selection

    try:
        made = selection.create(
            month=payload.month or "", level=payload.level,
            product=payload.product or "",
            classification=payload.classification or "",
            sub_product=payload.sub_product or "",
            customer_id=payload.customer_id or "",
            cohort=payload.cohort or "", severity=payload.severity or "",
            reason=payload.reason or "", layer=payload.layer or "",
            score_min=payload.score_min, score_max=payload.score_max,
            dpd_bucket=payload.dpd_bucket or "", stage=payload.stage or "",
            route=payload.route or "", label=payload.label or "",
            created_by=getattr(principal, "username", "") or "")
    except ValueError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem)) from problem
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      "selection_id": made.selection_id,
                      "selection": made.to_dict()})


@router.get("/ews/whatif-selection/{selection_id}",
            summary="One exported cohort, with its baseline")
def ews_selection(selection_id: str, membership: bool = Query(False)) -> dict:
    from backend.retail import whatif_cohort as cohort
    from backend.retail import whatif_selection as selection

    found = selection.get(selection_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{selection_id} is not a known selection.")
    shaped = found.to_dict()
    if not membership:
        shaped.pop("selected_customer_ids", None)
        shaped.pop("selected_facility_ids", None)
    return json_safe({
        "disclosure": SYNTHETIC_DISCLOSURE,
        "selection": shaped,
        "baseline": selection.baseline(found),
        "prompts": selection.prompts(found),
        "methodologies": cohort.methodologies(),
    })


@router.get("/ews/whatif-selection/{selection_id}/customers",
            summary="The customers in an exported cohort")
def ews_selection_customers(selection_id: str,
                            limit: int = Query(100, ge=1, le=1000)) -> dict:
    from backend.retail import whatif_selection as selection

    found = selection.get(selection_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{selection_id} is not a known selection.")
    rows = selection.build_rows(found.source_month, **{
        k: v for k, v in found.source_filters.items()
        if k in ("product", "classification", "sub_product", "customer_id",
                 "cohort", "severity", "reason", "layer", "score_min",
                 "score_max", "dpd_bucket", "stage")})
    held = rows[rows["facility_id"].astype(str).isin(
        set(found.selected_facility_ids))]
    columns = ["customer_id", "customer_name", "facility_id", "product_label",
               "classification_label", "sub_product_label", "ews_score",
               "ews_severity", "dpd", "ifrs9_stage",
               "gross_carrying_amount_sar", "current_bad_flag",
               "forward_risk_flag"]
    have = [one for one in columns if one in held.columns]
    return json_safe({
        "disclosure": SYNTHETIC_DISCLOSURE,
        "selection_id": found.selection_id,
        "total": int(len(held)),
        "customers": held[have].head(limit).to_dict("records"),
    })


@router.post("/ews/whatif-selection/run",
             summary="Run a scenario on an exported cohort")
def ews_cohort_scenario(payload: CohortScenarioIn,
                        _: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_cohort as cohort

    from backend.retail import whatif_selection as selection_store

    shocks = dict(payload.shocks)
    within = dict(payload.within)
    staging = payload.staging_mode
    weights = payload.scenario_weights
    reading: dict[str, Any] = {}

    if payload.said and not shocks:
        found = selection_store.get(payload.selection_id)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"{payload.selection_id} is not a known selection.")
        reading = cohort.read(payload.said, found)
        if not reading.get("understood"):
            # Not an error: the thread asks the reader a question back, which
            # is the whole point of refusing to guess a unit or a cohort.
            return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                              "available": False, "needs_clarification": True,
                              **reading})
        shocks = reading["shocks"]
        within = {**reading.get("within", {}), **within}
        staging = reading.get("staging_mode") or staging
        weights = reading.get("scenario_weights") or weights

    try:
        out = cohort.run(payload.selection_id, shocks=shocks,
                         name=payload.name or payload.said,
                         method=payload.method,
                         staging_mode=staging, within=within,
                         scenario_weights=weights)
    except wif.UnsupportedShock as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem)) from problem
    except ValueError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem)) from problem
    if not out.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            out.get("because") or "Nothing to run.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      "reading": reading or None, **out})


class CohortWorkbookIn(BaseModel):
    selection_id: str
    shocks: dict[str, Any] = Field(default_factory=dict)
    said: str = ""
    method: str = "delta"
    staging_mode: str = "frozen_stage"
    within: dict[str, Any] = Field(default_factory=dict)
    scenario_weights: dict[str, float] | None = None


@router.post("/ews/whatif-selection/workbook.xlsx",
             summary="The scenario result, as a workbook")
def ews_cohort_workbook(payload: CohortWorkbookIn,
                        _: Principal = RequireAnalyst) -> Response:
    """Built from the result the screen showed, never recomputed differently.

    The scenario is re-run here because a browser cannot post a megabyte of
    result back, but it is the SAME call with the same inputs, so the figures
    in the workbook are the figures on the page.
    """
    from backend.retail import whatif_cohort as cohort
    from backend.retail import whatif_selection as selection_store
    from backend.retail import whatif_workbook as book

    found = selection_store.get(payload.selection_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{payload.selection_id} is not a known selection.")

    shocks, within = dict(payload.shocks), dict(payload.within)
    staging, weights = payload.staging_mode, payload.scenario_weights
    if payload.said and not shocks:
        reading = cohort.read(payload.said, found)
        if not reading.get("understood"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                reading.get("question") or "Unreadable scenario.")
        shocks = reading["shocks"]
        within = {**reading.get("within", {}), **within}
        staging = reading.get("staging_mode") or staging
        weights = reading.get("scenario_weights") or weights

    try:
        out = cohort.run(payload.selection_id, shocks=shocks,
                         name=payload.said, method=payload.method,
                         staging_mode=staging, within=within,
                         scenario_weights=weights)
    except (wif.UnsupportedShock, ValueError) as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem)) from problem
    if not out.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            out.get("because") or "Nothing to run.")

    facilities = _cohort_facility_detail(found, shocks, staging, weights)
    # The customer sheet used to be raw book rows — all 498 columns of them.
    # It is a CURATED summary rolled up from the same facility recomputation
    # the totals came from, so the sheet's rows and the workbook's totals are
    # the same arithmetic rather than two reads of the book.
    customers = _cohort_customer_detail(found, facilities)
    payload_bytes, filename = book.build(
        out, selection=found.to_dict(), customers=customers,
        facilities=facilities)
    return Response(
        content=payload_bytes,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _cohort_customer_detail(selection: Any,
                            facilities: list[dict]) -> list[dict]:
    """One row per customer, rolled up from the facility recomputation.

    A customer with three cards is ONE customer. Summing income or counting
    them three times is the multiplication §4.1 forbids, so only the
    additive quantities — exposure, ECL — are summed, and the rest are taken
    from the customer's worst facility.
    """
    import pandas as pd

    from backend.retail import ews_score as scored

    if not facilities:
        return []
    try:
        frame = pd.DataFrame(facilities)
        book = scored.read(selection.source_month)
        keep = [c for c in ("facility_id", "customer_name",
                            "sub_product_code", "classification",
                            "dpd_bucket", "behavioural_score",
                            "behavioural_score_band")
                if c in book.columns]
        # Eight columns of a 498-column panel, and narrowed BEFORE the rows
        # are copied. Taking the slice after the copy made this the second
        # most expensive step in a workbook download, for context that fits
        # in a handful of columns.
        frame["facility_id"] = frame["facility_id"].astype(str)
        wanted = set(frame["facility_id"])
        context = book.loc[book["facility_id"].astype(str).isin(wanted), keep]
        context = context.copy()
        context["facility_id"] = context["facility_id"].astype(str)
        joined = frame.merge(context, on="facility_id", how="left")
        # Sorted once, so each group's first row IS its worst facility and the
        # per-group sort inside the loop disappears. On 4,630 customers that
        # was 4,630 sorts of a two-row frame.
        # Sorted once so each customer's first row IS their worst facility,
        # then aggregated by pandas rather than by a Python loop. The loop
        # built 4,630 dictionaries and sorted a two-row frame inside each one.
        joined = joined.sort_values("ecl_change_sar", ascending=False)
        joined["customer_id"] = joined["customer_id"].astype(str)
        grouped = joined.groupby("customer_id", sort=False)
        summed = grouped[["exposure_sar", "ecl_weighted_sar_before",
                          "ecl_weighted_sar_after", "ecl_change_sar"]].sum()
        counted = grouped.size().rename("facilities")
        worst = grouped.head(1).set_index("customer_id")
        out = summed.join(counted).join(
            worst[[c for c in ("customer_name", "product_code",
                               "sub_product_code", "classification",
                               "dpd_after", "dpd_bucket", "stage_after",
                               "behavioural_score", "behavioural_score_band",
                               "pd_pit_12m_before", "pd_pit_12m_after",
                               "lgd_before", "lgd_after")
                   if c in worst.columns]])
        out = out.reset_index()
        label = _maybe_text(selection.source_label)
        rolled = [{
            "customer_id": row["customer_id"],
            "customer_name": (_maybe_text(row.get("customer_name"))
                              or scored.display_name(row["customer_id"])),
            "product_code": _maybe_text(row.get("product_code")),
            "sub_product_code": _maybe_text(row.get("sub_product_code")),
            "classification": _maybe_text(row.get("classification")),
            "facilities": int(row["facilities"]),
            "exposure_sar": round(float(row["exposure_sar"]), 2),
            "dpd": _maybe_int(row.get("dpd_after")),
            "dpd_bucket": _maybe_text(row.get("dpd_bucket")),
            "ifrs9_stage": _maybe_int(row.get("stage_after")),
            "behavioural_score": _maybe_float(row.get("behavioural_score")),
            "behavioural_score_band": _maybe_text(
                row.get("behavioural_score_band")),
            "pd_pit_12m_before": _maybe_float(row.get("pd_pit_12m_before")),
            "pd_pit_12m_after": _maybe_float(row.get("pd_pit_12m_after")),
            "lgd_before": _maybe_float(row.get("lgd_before")),
            "lgd_after": _maybe_float(row.get("lgd_after")),
            "ecl_before_sar": round(float(row["ecl_weighted_sar_before"]), 2),
            "ecl_after_sar": round(float(row["ecl_weighted_sar_after"]), 2),
            "ecl_change_sar": round(float(row["ecl_change_sar"]), 2),
            "changed": "Yes" if abs(row["ecl_change_sar"]) >= 0.005 else "No",
            "reason": label,
        } for row in out.to_dict("records")]
        rolled.sort(key=lambda one: -abs(one["ecl_change_sar"]))
        return rolled[:5000]
    except Exception:  # noqa: BLE001 - the workbook still ships without it
        return []


def _maybe_text(value: Any) -> str:
    """A string, or empty — never the WORD "nan".

    `str(value or "")` looks safe and is not: a float nan is truthy, so `or`
    never fires and `str` turns it into the three characters n, a, n. The
    score-band column carried them into a downloaded workbook.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none", "nat", "<na>") else text


def _maybe_int(value: Any) -> int | None:
    try:
        import math

        got = float(value)
        return None if math.isnan(got) else int(got)
    except (TypeError, ValueError):
        return None


def _maybe_float(value: Any) -> float | None:
    try:
        import math

        got = float(value)
        return None if math.isnan(got) else got
    except (TypeError, ValueError):
        return None


def _cohort_facility_detail(selection: Any, shocks: dict[str, Any],
                            staging: str,
                            weights: dict[str, float] | None) -> list[dict]:
    """Facility by facility, as the engine scored it before and after.

    Read off the same recomputation the result came from, so the workbook's
    rows add up to the workbook's totals.
    """
    import pandas as pd

    from backend.retail import ecl as ecl_mod
    from backend.retail import ews_score as scored
    from backend.retail import whatif_cohort as cohort
    from backend.retail.config import load_config

    try:
        book = scored._read_book(selection.source_month)
        stressed, _ = cohort.narrow(selection, {})
        rows = book[book["facility_id"].astype(str).isin(set(stressed))]
        if not len(rows):
            return []
        config = load_config()
        share = {s: float((weights or config.scenarios.weights)[s])
                 for s in ecl_mod.SCENARIOS}
        scenario = wif.Scenario(
            name="workbook", dataset_version="",
            snapshot_date=str(rows["snapshot_date"].iloc[0]),
            filters={}, shocks=dict(shocks), staging_mode=staging,
            scenario_weights=weights)
        after = wif._recompute(rows, scenario, share)
        out = pd.DataFrame({
            "customer_id": rows["customer_id"].to_numpy(),
            "facility_id": rows["facility_id"].to_numpy(),
            "product_code": rows["product_code"].to_numpy(),
            "dpd_before": pd.to_numeric(rows["dpd"], errors="coerce").to_numpy(),
            "dpd_after": after["dpd"],
            "stage_before": rows["ifrs9_stage"].to_numpy(),
            "stage_after": after["stage"],
            "pd_pit_12m_before": pd.to_numeric(
                rows["pd_pit_12m_base"], errors="coerce").to_numpy(),
            "pd_pit_12m_after": after["pd_anchor"],
            "lgd_before": pd.to_numeric(
                rows["lgd_base"], errors="coerce").to_numpy(),
            "lgd_after": after["lgd"],
            "exposure_sar": pd.to_numeric(
                rows["gross_carrying_amount_sar"], errors="coerce").to_numpy(),
            "ecl_weighted_sar_before": pd.to_numeric(
                rows["ecl_weighted_sar"], errors="coerce").to_numpy(),
            "ecl_weighted_sar_after": after["ecl_weighted"],
        })
        out["ecl_change_sar"] = (out["ecl_weighted_sar_after"]
                                 - out["ecl_weighted_sar_before"]).round(2)
        return out.sort_values("ecl_change_sar",
                               ascending=False).head(5000).to_dict("records")
    except Exception:  # noqa: BLE001 - the workbook still ships without it
        return []


@router.get("/ews/whatif-selections", summary="Recent exported cohorts")
def ews_selections(limit: int = Query(25, ge=1, le=100)) -> dict:
    from backend.retail import whatif_selection as selection

    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      "selections": selection.listing(limit)})


@router.get("/ews/domain", summary="What the Early Warning Score domain holds")
def ews_domain_view() -> dict:
    from backend.retail import ews_score as score
    from backend.retail import ews_views as views

    return json_safe({
        "disclosure": SYNTHETIC_DISCLOSURE,
        **views.field_contract(),
        "problems": score.check(),
        "months_expected": score.MONTHS_KEPT,
        "source_dataset": score.BOOK,
    })


class EwsAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    month: str | None = Field(default=None, max_length=16)
    product: str | None = Field(default=None, max_length=32)
    sub_product: str | None = Field(default=None, max_length=32)
    customer: str | None = Field(default=None, max_length=32)


@router.post("/ews/ask", summary="Ask the Early Warning Score domain")
def ews_ask(payload: EwsAskIn) -> dict:
    """Answer one question, from the Early Warning Score domain only.

    The scope is structural: `backend.retail.ews_chat` imports the model
    configuration and the Early Warning views, and holds no other dataset
    name, no catalogue and no planner. A question about expected credit loss,
    a scenario or a corporate book is answered with a scope notice naming the
    module that owns it, rather than from the wrong data.
    """
    from backend.retail import ews_chat as chat

    return json_safe({
        "disclosure": SYNTHETIC_DISCLOSURE,
        "question": payload.question,
        **chat.ask(payload.question, month=payload.month or "",
                   product=payload.product or "",
                   sub_product=payload.sub_product or "",
                   customer=payload.customer or "")})


@router.get("/ews/prompts", summary="The chat's seeded questions")
def ews_prompts(level: str = Query("portfolio")) -> dict:
    from backend.retail import ews_chat as chat

    return json_safe({"level": level, "prompts": chat.chips(level),
                      "scope": list(chat.SCOPE),
                      "scope_note": chat.OUT_OF_SCOPE_NOTE})


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
        # A chosen option may BE a reweighting rather than a shock. Without
        # this, clicking "Severe downturn tilt" applied no weights at all and
        # ran the neutral scenario the clarification existed to prevent.
        chosen_weights = payload.chosen.get("scenario_weights")
        if chosen_weights:
            ask.scenario_weights = {name: float(value)
                                    for name, value in chosen_weights.items()}
        for column, value in (payload.carried.get("filters") or {}).items():
            ask.filters.setdefault(column, value)
        # Family-aware, so answering a units question with "percentage points"
        # does not leave the carried relative PD increase sitting under it.
        lang.carry_shocks(ask, dict(payload.carried.get("shocks") or {}))
        # A scenario assembled from a CLICK has to describe itself. The button
        # label is not a sentence this parser can read, so without this the
        # result card captioned a two-percentage-point shock on personal
        # finance as "an unchanged scenario over the whole retail book".
        ask.read_as = lang.describe_scenario(ask)

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

    if ask.cutoff is not None:
        # Two analyses, not one. A cutoff replay COUNTS booked originations
        # against a threshold; a shock REBUILDS expected credit loss on the
        # book as it stands. They read different populations and answer
        # different questions, so a sentence asking for both is answered with
        # that fact rather than with whichever half ran first.
        if ask.shocks or ask.scenario_weights is not None:
            return json_safe({
                **_envelope(month),
                "kind": "invalid",
                "question": payload.question,
                "message": (
                    "That sentence asks for two different analyses at once. A "
                    "cutoff replay counts the originations that WERE booked "
                    "against a score threshold; an ECL shock rebuilds the book "
                    "as it stands today. They run over different populations "
                    "and neither is a step in the other, so CreditProbe will "
                    "not combine them. Ask for one, then the other."),
                "read_as": ask.read_as,
                "scenario_so_far": ask.to_dict(),
            })
        cutoff_frame = _read(month, ["facility_id", "product_code",
                                     "application_score_at_origination",
                                     "gross_carrying_amount_sar",
                                     "observed_default_within_window"])
        return json_safe({
            **_envelope(month),
            "kind": "cutoff",
            "question": payload.question,
            "read_as": ask.read_as,
            **wif.cutoff_replay(cutoff_frame, ask.cutoff),
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


# ==================== one What-If thread, however it was opened =============
#
# §8 of the demo completion contract. The standalone page and an Early Warning
# export were two implementations over two API families: one had a method
# choice and a waterfall and a workbook, the other ran a scenario inline under
# the guided cards and exposed `pd_relative` to the reader. Different entry
# context is legitimate; reduced functionality is not.
#
# So both entries now open a THREAD over a SELECTION, and everything after
# that is the same code. The cohort a guided card describes is selected the
# same way an exported one is, carries the same membership record, and reaches
# the same engine, result and workbook.


class ThreadOpenIn(BaseModel):
    """Open a thread. Either on an existing selection, or on a new cohort."""

    selection_id: str = ""
    title: str = ""
    opened_from: str = "standalone"
    month: str = ""
    # The cohort, when there is no selection yet. These are the seven guided
    # cards' filters and the standalone page's scope chips.
    product: str = ""
    classification: str = ""
    sub_product: str = ""
    customer_id: str = ""
    cohort: str = ""
    dpd_bucket: str = ""
    stage: str = ""
    behavioural_band: str = ""
    severity: str = ""
    method: str = ""
    staging_mode: str = ""


class ThreadAskIn(BaseModel):
    said: str = ""
    shocks: dict[str, Any] = Field(default_factory=dict)
    method: str = ""
    staging_mode: str = ""
    within: dict[str, Any] = Field(default_factory=dict)
    scenario_weights: dict[str, float] | None = None
    name: str = ""


def _thread_view(thread: Any) -> dict:
    from backend.retail import whatif_selection as selection_store

    body = thread.to_dict()
    found = selection_store.get(thread.selection_id)
    if found is not None:
        body["selection"] = {
            k: v for k, v in found.to_dict().items()
            if k not in ("selected_customer_ids", "selected_facility_ids")}
        body["baseline"] = selection_store.baseline(found)
        body["prompts"] = selection_store.prompts(found)
    return body


@router.post("/whatif/threads", summary="Open a What-If thread")
def whatif_thread_open(payload: ThreadOpenIn,
                       principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_selection as selection_store
    from backend.retail import whatif_thread as threads

    selection_id = payload.selection_id
    if not selection_id:
        source = (selection_store.SOURCE_GUIDED
                  if payload.opened_from == threads.FROM_GUIDED
                  else selection_store.SOURCE_STANDALONE)
        try:
            made = selection_store.create(
                month=payload.month, level="cohort", route="/what-if",
                product=payload.product, classification=payload.classification,
                sub_product=payload.sub_product,
                customer_id=payload.customer_id, cohort=payload.cohort,
                dpd_bucket=payload.dpd_bucket, stage=payload.stage,
                behavioural_band=payload.behavioural_band,
                severity=payload.severity, source_module=source,
                label=payload.title, created_by=str(principal.user_id or ""))
        except ValueError as problem:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                str(problem)) from problem
        selection_id = made.selection_id

    found = selection_store.get(selection_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{selection_id} is not a known selection.")
    try:
        thread = threads.create(
            title=payload.title or found.source_label or "What-If",
            selection_id=selection_id, month=found.source_month,
            opened_from=payload.opened_from, method=payload.method,
            staging_mode=payload.staging_mode, owner=principal.user_id)
    except Exception as problem:  # noqa: BLE001 - said, never faked
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"The thread could not be saved: {problem}"
                            ) from problem
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      **_thread_view(thread)})


@router.get("/whatif/threads", summary="Recent What-If threads")
def whatif_thread_list(limit: int = 25,
                       principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_thread as threads

    try:
        rows = threads.listing(owner=principal.user_id, limit=limit)
    except Exception:  # noqa: BLE001 - an empty list, never a 500
        rows = []
    return json_safe({"threads": [one.to_dict() for one in rows]})


@router.get("/whatif/threads/{thread_id}", summary="Reopen a What-If thread")
def whatif_thread_get(thread_id: str,
                      principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_thread as threads

    thread = threads.get(thread_id, owner=principal.user_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{thread_id} is not a thread you can open.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      **_thread_view(thread)})


@router.post("/whatif/threads/{thread_id}/method",
             summary="Choose Delta, XGBoost or both")
def whatif_thread_method(thread_id: str, payload: ThreadAskIn,
                         principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_thread as threads

    thread = threads.set_method(thread_id, method=payload.method,
                                staging_mode=payload.staging_mode,
                                owner=principal.user_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{thread_id} is not a thread you can open.")
    return json_safe(thread.to_dict())


@router.post("/whatif/threads/{thread_id}/undo",
             summary="Remove the last exchange")
def whatif_thread_undo(thread_id: str,
                       principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import whatif_thread as threads

    thread = threads.remove_last_result(thread_id, owner=principal.user_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{thread_id} is not a thread you can open.")
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      **_thread_view(thread)})


@router.post("/whatif/threads/{thread_id}/ask",
             summary="Ask this thread for a scenario")
def whatif_thread_ask(thread_id: str, payload: ThreadAskIn,
                      principal: Principal = RequireAnalyst) -> dict:
    """One turn: read it, require a method, run it, and persist all of it.

    The method is REQUIRED before the first run. Defaulting to Delta while
    presenting it as the reader's choice is the specific dishonesty §8.3
    names, so an unchosen method returns the cards rather than a result.
    """
    from backend.retail import whatif_cohort as cohort
    from backend.retail import whatif_selection as selection_store
    from backend.retail import whatif_thread as threads

    thread = threads.get(thread_id, owner=principal.user_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{thread_id} is not a thread you can open.")
    found = selection_store.get(thread.selection_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{thread.selection_id} is no longer available.")

    shocks = dict(payload.shocks)
    within = dict(payload.within)
    staging = payload.staging_mode or thread.staging_mode or wif.FROZEN_STAGE
    weights = payload.scenario_weights
    reading: dict[str, Any] = {}

    # Answering the method prompt is not asking again. Without this the
    # transcript showed the same question twice — once for the turn that was
    # told to choose a method, once for the turn that supplied it — which
    # reads as a duplicate rather than as a choice.
    answering = bool(
        payload.method and thread.turns
        and thread.turns[-1].get("kind") == threads.INTERPRETED
        and thread.turns[-1].get("needs_method")
        and any(one.get("kind") == threads.SAID
                and one.get("text") == payload.said
                for one in thread.turns[-3:]))
    if payload.said and not answering:
        threads.append(thread_id, {"kind": threads.SAID, "text": payload.said},
                       owner=principal.user_id)
    if payload.said and not shocks:
        reading = cohort.read(payload.said, found)
        if not reading.get("understood"):
            threads.append(thread_id,
                           {"kind": threads.CLARIFICATION, **reading},
                           owner=principal.user_id)
            return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                              "available": False, "needs_clarification": True,
                              "thread_id": thread_id, **reading})
        shocks = reading["shocks"]
        within = {**reading.get("within", {}), **within}
        staging = reading.get("staging_mode") or staging
        weights = reading.get("scenario_weights") or weights

    method = payload.method or thread.method
    if not method:
        # The interpreted scope and shock FIRST, then the cards — so the
        # reader is choosing a method for a scenario they can already see.
        asked = {"kind": threads.INTERPRETED, "shocks": shocks,
                 "reading": reading or None,
                 "needs_method": True}
        threads.append(thread_id, asked, owner=principal.user_id)
        return json_safe({
            "disclosure": SYNTHETIC_DISCLOSURE, "available": False,
            "needs_method": True, "thread_id": thread_id,
            "shocks": shocks, "reading": reading or None,
            "described": cohort._describe(shocks) if shocks else "",
            "methods": [
                {**one, "key": key} for key, one in cohort.METHODS.items()],
            "because": ("Choose Delta, XGBoost or both. CreditProbe will not "
                        "run one and present it as your choice."),
        })

    try:
        out = cohort.run(thread.selection_id, shocks=shocks,
                         name=payload.name or payload.said,
                         method=method, staging_mode=staging,
                         within=within, scenario_weights=weights)
    except wif.UnsupportedShock as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem)) from problem
    except ValueError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem)) from problem
    if not out.get("available"):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            out.get("because") or "Nothing to run.")

    threads.set_method(thread_id, method=method, staging_mode=staging,
                       owner=principal.user_id)
    # The RESULT is stored with the turn, not a pointer to a recomputation:
    # reopening has to show the figures that were on screen, not what the
    # engine would say today about a book that has moved since.
    threads.append(thread_id, {
        "kind": threads.RESULT, "method": method, "shocks": shocks,
        "staging_mode": staging, "within": within,
        "said": payload.said, "reading": reading or None,
        "result": json_safe(out),
    }, owner=principal.user_id)
    return json_safe({"disclosure": SYNTHETIC_DISCLOSURE,
                      "thread_id": thread_id,
                      "reading": reading or None, **out})


# ================================ §13: the shared report service ===========


class ReportIn(BaseModel):
    """Ask for one of the report families the service writes."""

    family: str = "investigation"
    product: str = ""
    classification: str = ""
    sub_product: str = ""
    month: str = ""
    prior: str = ""
    question: str = ""
    mode: str = "quarter"
    comments: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    #: Validation reports only: which scorecard, and an analyst's conclusion.
    model_id: str = ""
    run_key: str = ""
    conclusion: str = ""


def _validation_run(payload: "ReportIn") -> dict[str, Any] | None:
    """The stored validation run this report describes.

    By run key when one is given, otherwise the newest recorded run for the
    model. Never a fresh execution: a full validation is minutes of work, and
    re-running it here would produce a document that disagrees with the
    screen it was downloaded from.
    """
    from backend.db.engine import get_session
    from backend.scorecard.validation import store as run_store

    with get_session() as session:
        stored = None
        if payload.run_key:
            stored = run_store.get(session, payload.run_key)
        elif payload.model_id:
            held = run_store.history(session, model_id=payload.model_id,
                                     limit=1)
            stored = held[0] if held else None
        if stored is None:
            return None
        return run_store.run_body(stored)


@router.post("/reports/{family}.docx", summary="A Word report from an analysis")
def retail_report(family: str, payload: ReportIn,
                  principal: Principal = RequireAnalyst) -> Response:
    """Build one report, or fail as an error rather than as a file.

    §13 opens by naming the failure to avoid: "Never download an HTML
    error/login page with a .docx extension." A caller that cannot build a
    report gets a status code and a JSON body; it never gets a document whose
    contents are an apology, because that file opens and the reader believes
    they have the report.
    """
    from backend.retail import report_service as reports

    if family not in (reports.INVESTIGATION, reports.TRAITS,
                      reports.VALIDATION):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{family!r} is not a report this service writes.")
    try:
        if family == reports.INVESTIGATION:
            from backend.retail import analysis_delinquency as analysis

            out = analysis.run(month=payload.month, prior=payload.prior,
                               product=payload.product,
                               classification=payload.classification,
                               sub_product=payload.sub_product,
                               question=payload.question)
            bundle = reports.investigation_bundle(
                out, prepared_by=str(principal.user_id or ""),
                comments=payload.comments, actions=payload.actions)
        elif family == reports.VALIDATION:
            # Read from a STORED run, never from a fresh one. A full
            # validation is minutes of work, and re-running it here would
            # produce a report that disagrees with the screen it was
            # downloaded from.
            held = _validation_run(payload)
            if held is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "No validation run is stored for that model. Run the "
                    "validation first; this report is written from its "
                    "result, not from a new run.")
            bundle = reports.validation_bundle(
                held, prepared_by=str(principal.user_id or ""),
                comments=payload.comments, actions=payload.actions,
                conclusion=payload.conclusion)
        else:
            from backend.retail import analysis_traits as analysis

            out = analysis.run(month=payload.month, product=payload.product,
                               classification=payload.classification,
                               sub_product=payload.sub_product,
                               question=payload.question, mode=payload.mode)
            bundle = reports.traits_bundle(
                out, prepared_by=str(principal.user_id or ""),
                comments=payload.comments, actions=payload.actions)
        content, filename = reports.render(family, bundle)
    except reports.ReportUnavailable as problem:
        raise HTTPException(status.HTTP_409_CONFLICT, str(problem)) from problem
    except ValueError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            str(problem)) from problem
    return Response(
        content=content,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# --------------------------------------------------------------------------
# The presenter story (§22) and the prompt bank (§23).
#
# Both are read-only descriptions of intent. The story resolves its artifact
# ids against this installation on every request rather than caching them,
# because a reseed changes them and a cached breadcrumb sends a presenter to
# a dead link in front of a client. The bank is static by design: it is the
# contract the chips and the automated suite share, so a chip cannot drift
# from what is tested.
# --------------------------------------------------------------------------


@router.get("/demo/story", summary="The guided presenter story")
def demo_story(_: Principal = RequireCommenter) -> dict:
    from backend.db.engine import get_session
    from backend.retail import demo_story as story_mod

    with get_session() as session:
        out = story_mod.story(session)
    out["disclosure"] = SYNTHETIC_DISCLOSURE
    return out


@router.get("/demo/prompts", summary="The versioned prompt bank")
def demo_prompts(surface: str | None = Query(None),
                 _: Principal = RequireCommenter) -> dict:
    from backend.retail import prompt_bank

    out = prompt_bank.catalogue()
    if surface:
        held = out["by_surface"].get(surface)
        if held is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"No prompts are banked for the {surface!r} surface. "
                f"Known surfaces: {', '.join(sorted(out['by_surface']))}.")
        out["by_surface"] = {surface: held}
        out["prompts"] = len(held)
    return out


# --------------------------------------------------------------------------
# The What-If challenger's model page (§10.2).
#
# The route the frontend model page used to read is the CORPORATE registry,
# which in a retail installation answers "Corporate IFRS 9 publishes no
# periods to train on" — a model card with no versions, for a model that
# cannot exist here, while the challenger that actually runs retail scenarios
# had no page at all.
# --------------------------------------------------------------------------


@router.get("/whatif/models/challenger",
            summary="The stored What-If challenger, and what it was fitted on")
def challenger_card(_: Principal = RequireCommenter) -> dict:
    from backend.retail import challenger_registry as registry
    from backend.retail import whatif_cohort as cohort

    held = registry.held()
    body: dict[str, Any] = {
        **cohort.METHODS[cohort.CHALLENGER],
        "has_artifact": held is not None,
        "stale": registry.stale(),
        "disclosure": SYNTHETIC_DISCLOSURE,
    }
    if held is None:
        body["because"] = (
            "No challenger has been fitted on this installation yet. The "
            "bootstrap fits one; until then a scenario asking for the "
            "challenger fits it on the spot.")
        return body
    body["card"] = held.to_dict()
    if registry.stale():
        body["because"] = (
            "The stored challenger was fitted on a different book than the "
            "one published now. It will be refitted on the next scenario "
            "that asks for it rather than served.")
    return body


@router.post("/whatif/models/challenger/rebuild",
             summary="Refit the What-If challenger on the published book")
def challenger_rebuild(principal: Principal = RequireAnalyst) -> dict:
    from backend.retail import challenger_registry as registry

    try:
        _, card = registry.build()
    except registry.ChallengerUnavailable as problem:
        raise HTTPException(status.HTTP_409_CONFLICT, str(problem)) from problem
    return {"card": card.to_dict(),
            "says": (f"Refitted on {card.rows_fitted:,} facilities of the "
                     f"book published at {card.month}, held back "
                     f"{card.rows_held_back:,} to measure on.")}


@router.get("/whatif/models/challenger/parity",
            summary="Whether the stored artifact scores as the fitted model did")
def challenger_parity(principal: Principal = RequireAnalyst) -> dict:
    """§10.2's save/load parity, run rather than asserted."""
    from backend.retail import challenger_registry as registry

    try:
        return registry.parity()
    except registry.ChallengerUnavailable as problem:
        raise HTTPException(status.HTTP_409_CONFLICT, str(problem)) from problem


@router.get("/whatif/models/challenger/example",
            summary="Real facilities, scored by the challenger")
def challenger_example(rows: int = Query(8, ge=1, le=50),
                       _: Principal = RequireCommenter) -> dict:
    from backend.retail import challenger_registry as registry

    try:
        return registry.example(rows=rows)
    except registry.ChallengerUnavailable as problem:
        raise HTTPException(status.HTTP_409_CONFLICT, str(problem)) from problem
