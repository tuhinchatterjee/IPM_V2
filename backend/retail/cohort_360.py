"""The imported cohort, as Borrower 360 shows it. U06.

The defect this exists for
--------------------------
Borrower 360 knows how to show one customer. An investigation hands it eleven
hundred, and the naive rendering of that is a table of averages — one PD, one
LGD, one score per customer — which is wrong for any customer holding more than
one facility. A personal loan at 4% and a mortgage at 0.4% do not average into
a customer who is at 2.2%; there is no such customer.

So a customer row carries what is true at CUSTOMER grain (identity, the exact
issue, the Early Warning band, the count of included facilities) and the
facility rows underneath carry what is true at FACILITY grain (stage, days past
due, probability of default, loss given default, exposure, expected loss).
Where a customer aggregate is shown at all, its basis is named and the facility
values are one expansion away.

What is included, and what is only context
------------------------------------------
By default the cohort holds the FLAGGED facilities — the ones the case is
about. A customer's other facilities are shown as context and are NOT in the
financial baseline, because adding them would quietly change the totals the
investigation has been carrying. Switching to all of a customer's authorised
facilities is an explicit act that writes a new cohort snapshot with recomputed
counts.

Everything read here is SYNTHETIC demonstration data.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from backend.retail import episode_measures as em
from backend.retail import episodes as ep
from backend.retail import metrics_contract as mc

logger = logging.getLogger(__name__)

VERSION = "retail-cohort-360-1.0.0"

#: How many month-ends of Early Warning history a customer row carries.
EWS_WINDOWS = 6


def _numeric(rows: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(rows.get(column), errors="coerce")


def _facility_row(row: pd.Series, *, flagged: bool) -> dict[str, Any]:
    def number(column: str, digits: int = 2) -> float | None:
        value = pd.to_numeric(row.get(column), errors="coerce")
        return None if pd.isna(value) else round(float(value), digits)

    return {
        "facility_id": str(row.get("facility_id") or ""),
        "product": str(row.get("product_code") or ""),
        "subproduct": str(row.get("product_subsegment") or ""),
        "included": flagged,
        "included_because": (
            "meets the case rule at the reporting date" if flagged
            else "another authorised facility of this customer, shown as "
                 "context and NOT in the financial baseline"),
        "stage": number("ifrs9_stage", 0),
        "dpd": number("dpd", 0),
        "gca_sar": number("gross_carrying_amount_sar"),
        "ead_sar": number("ead_base_sar"),
        "ecl_sar": number("ecl_weighted_sar"),
        "pd_12m": number("pd_pit_12m_base", 6),
        "pd_lifetime": number("pd_pit_lifetime_base", 6),
        "lgd": number("lgd_base", 6),
        "behavioural_score": number("behavioural_score", 1),
        "application_score": number("app_score_value", 1),
        "application_score_band": str(row.get("application_score_band") or ""),
        "credit_impaired": bool(row.get("credit_impaired_flag") or False),
    }


def _ews_history(customer_id: str, product: str, months: list[str],
                 cache: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """The Early Warning series for one customer-product, with its coverage.

    A month with no observation is reported as a gap, not as a zero. A flat
    line drawn through missing months is the specific way a coverage problem
    becomes a statement that nothing was wrong.
    """
    series: list[dict[str, Any]] = []
    missing = 0
    for month in months:
        panel = cache.get(month)
        if panel is None or panel.empty:
            missing += 1
            series.append({"month": month, "score": None, "band": "",
                           "state": mc.UNAVAILABLE})
            continue
        found = panel[(panel["customer_id"].astype(str) == customer_id)
                      & (panel["product_code"].astype(str) == product)]
        if found.empty:
            missing += 1
            series.append({"month": month, "score": None, "band": "",
                           "state": mc.UNAVAILABLE})
            continue
        row = found.iloc[0]
        score = pd.to_numeric(row.get("ews_score"), errors="coerce")
        series.append({
            "month": month,
            "score": None if pd.isna(score) else round(float(score), 2),
            "band": str(row.get("ews_severity") or row.get("ews_band") or ""),
            "state": mc.COVERED,
        })
    return {
        "series": series,
        "coverage": mc.coverage(covered=len(months) - missing,
                                eligible=len(months),
                                missing={mc.UNAVAILABLE: missing}),
        "definition": mc.definition("ews_band"),
    }


def _panels(months: list[str]) -> dict[str, pd.DataFrame]:
    """The Early Warning panel for each month, read once."""
    import glob

    from backend.config import settings

    out: dict[str, pd.DataFrame] = {}
    for month in months:
        parts = sorted(glob.glob(
            f"{settings.analytics_dir}/retail_ews_panel/"
            f"reporting_month={month}/*.parquet"))
        if not parts:
            out[month] = pd.DataFrame()
            continue
        frames = []
        for part in parts:
            try:
                frames.append(pd.read_parquet(part, columns=[
                    "customer_id", "product_code", "ews_score",
                    "ews_severity"]))
            except (KeyError, ValueError):
                frames.append(pd.read_parquet(part))
        out[month] = pd.concat(frames, ignore_index=True) if frames \
            else pd.DataFrame()
    return out


def customers(snapshot: Any, *, offset: int = 0, limit: int = 50,
              with_context_facilities: bool = True) -> dict[str, Any]:
    """The customer list for one cohort snapshot, page by page.

    Paginated for the screen and NOT for the population: the counts, the
    totals and the export all read the snapshot's own identifier list, so a
    default page size can never redefine who the investigation is about.
    """
    at = snapshot.source_as_of
    data = em.frame(at)
    if data.empty:
        return {"available": False, "because": f"no published book at {at}"}

    wanted_customers = [str(c) for c in (snapshot.customer_ids or [])]
    wanted_facilities = {str(f) for f in (snapshot.facility_ids or [])}
    page = wanted_customers[offset:offset + limit]
    if not page:
        return {"available": True, "rows": [], "offset": offset,
                "limit": limit, "total": len(wanted_customers)}

    rows = data[data["customer_id"].astype(str).isin(set(page))]
    months = [m for m in em.months() if m <= at][-EWS_WINDOWS:]
    panels = _panels(months)
    episode = ep.by_id(snapshot.case_id)
    issue = episode.card_measure if episode else snapshot.case_id

    out: list[dict[str, Any]] = []
    for customer_id in page:
        held = rows[rows["customer_id"].astype(str) == customer_id]
        if held.empty:
            out.append({
                "customer_id": customer_id,
                "issue": issue,
                "state": mc.UNAVAILABLE,
                "because": ("this customer is in the saved cohort but has no "
                            "row in the book at this date"),
                "facilities": [],
            })
            continue
        included = held[held["facility_id"].astype(str).isin(wanted_facilities)]
        context = held[~held["facility_id"].astype(str).isin(wanted_facilities)]
        product = str(included["product_code"].iloc[0]) if not included.empty \
            else str(held["product_code"].iloc[0])

        facilities = [_facility_row(r, flagged=True)
                      for _i, r in included.iterrows()]
        if with_context_facilities:
            facilities += [_facility_row(r, flagged=False)
                           for _i, r in context.iterrows()]

        mixed = included["product_code"].nunique() > 1
        out.append({
            "customer_id": customer_id,
            "issue": issue,
            "segment": str(included["episode_pocket_label"].iloc[0]
                           if "episode_pocket_label" in included
                           and not included.empty else ""),
            "included_facilities": int(len(included)),
            "context_facilities": int(len(context)),
            "gca_sar": round(float(_numeric(
                included, "gross_carrying_amount_sar").sum()), 2),
            "ead_sar": round(float(_numeric(included, "ead_base_sar").sum()), 2),
            "ecl_sar": round(float(_numeric(
                included, "ecl_weighted_sar").sum()), 2),
            "worst_stage": int(_numeric(included, "ifrs9_stage").max() or 1),
            "max_dpd": int(_numeric(included, "dpd").max() or 0),
            "behavioural_score": (
                None if included.empty else
                round(float(_numeric(included, "behavioural_score")
                            .median()), 1)),
            "application_score": (
                None if included.empty else
                round(float(_numeric(included, "app_score_value")
                            .median()), 1)),
            # An aggregate whose basis is named, or none at all.
            "pd_12m_basis": (
                "exposure-weighted across this customer's included facilities"
                if not mixed else
                "not shown: this customer's included facilities are different "
                "products, and one probability across them describes nobody"),
            "pd_12m": (
                None if mixed or included.empty else
                round(float((_numeric(included, "pd_pit_12m_base")
                             * _numeric(included, "ead_base_sar")).sum()
                            / max(float(_numeric(included, "ead_base_sar")
                                        .sum()), 1e-9)), 6)),
            "ews": _ews_history(customer_id, product, months, panels),
            "facilities": facilities,
            "state": mc.COVERED,
        })

    return {
        "available": True,
        "snapshot_id": snapshot.snapshot_id,
        "case_id": snapshot.case_id,
        "as_of": at,
        "issue": issue,
        "rows": out,
        "offset": offset,
        "limit": limit,
        "total": len(wanted_customers),
        "facility_total": len(wanted_facilities),
        "pagination_note": (
            "This page is a rendering limit, not the population. The counts, "
            "the totals, the export and the What-If handoff all read the "
            "snapshot's own identifier list."),
    }


def totals(snapshot: Any) -> dict[str, Any]:
    """The cohort's financial baseline, from the included facilities only."""
    at = snapshot.source_as_of
    data = em.frame(at)
    if data.empty:
        return {"available": False, "because": f"no published book at {at}"}
    wanted = {str(f) for f in (snapshot.facility_ids or [])}
    rows = data[data["facility_id"].astype(str).isin(wanted)]
    stage = rows["ifrs9_stage"].value_counts().to_dict()
    return {
        "available": True,
        "snapshot_id": snapshot.snapshot_id,
        "as_of": at,
        "customers": int(rows["customer_id"].nunique()),
        "facilities": int(len(rows)),
        "missing_facilities": len(wanted) - int(len(rows)),
        "gca_sar": round(float(_numeric(
            rows, "gross_carrying_amount_sar").sum()), 2),
        "ead_sar": round(float(_numeric(rows, "ead_base_sar").sum()), 2),
        "ecl_sar": round(float(_numeric(rows, "ecl_weighted_sar").sum()), 2),
        "stage": {f"stage_{int(k)}": int(v) for k, v in sorted(stage.items())},
        "basis": "the included facilities only; context facilities are excluded",
    }
