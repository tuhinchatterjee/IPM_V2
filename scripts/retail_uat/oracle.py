"""
An independent ground-truth oracle for the retail UAT.

Revision 3's browser suites asserted what the product said against what the
product said. This does not: every figure here is computed with pandas directly
off the Parquet partitions, with no call into `backend.metrics`,
`backend.retail.ecl`, `backend.retail.whatif` or the governed runtime. If the
oracle and the product agree, two independent implementations agree. If they
disagree, one of them is wrong and the disagreement is the finding.

Deliberately naive
------------------
The arithmetic here is the obvious arithmetic — `groupby().sum()`, a boolean
mask, a sorted rank. It is not the efficient version and it is not the clever
version, because a clever oracle that shares a subtle assumption with the code
it is checking is not an oracle at all.

Three grain rules, applied everywhere
-------------------------------------
* An exposure or an allowance SUMS rows: one row is one facility-month.
* A customer count counts DISTINCT `customer_id`.
* A customer-level field — income, debt burden, disposable income — is repeated
  on every one of that customer's rows. It is never summed, and where it is
  averaged the oracle says over what.

The outcome window
------------------
`observed_default_within_window` is null until the twelve-month window closes.
Every outcome statistic here is computed on the latest month where it is not,
and records which month that was.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "retail" / "analytics" / "retail_facility_month"
OUT = ROOT / "docs" / "evidence" / "retail_overnight_uat" / "oracles"

PRODUCTS = {"PERSONAL_LOAN": "Personal Finance", "AUTO_LOAN": "Auto Finance",
            "HOME_LOAN": "Home Finance", "CREDIT_CARD": "Credit Card"}


def months() -> list[str]:
    return sorted(p.name.split("=", 1)[1] for p in LAKE.glob("reporting_month=*"))


def read(month: str, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(LAKE / f"reporting_month={month}" / "data.parquet",
                           columns=columns)


def latest() -> str:
    return months()[-1]


def latest_matured() -> str:
    """The most recent month whose twelve-month window has closed FOR EVERYONE.

    The trap this avoids, and it is a sharp one. `observed_default_within_window`
    is not null on 47 rows at 2026-07 — and every one of those 47 is a default.
    A facility that has already defaulted has a known outcome immediately; one
    that has not is unknown until the window closes. So "the latest month where
    the column is not null" selects the defaults and nothing else, and every
    statistic computed there is computed on a population with a 100% bad rate:
    the default rate reads 100%, and Gini is undefined because there are no
    goods to rank against.

    The honest test is whether the window has closed, which the book states on
    every row: `performance_window_complete_flag`. By that test the latest fully
    observed cohort is 2025-08, where all 17,509 rows are observed and 370 are
    defaults — a 2.11% rate rather than 100%.
    """
    for month in reversed(months()):
        frame = read(month, ["performance_window_complete_flag"])
        complete = frame["performance_window_complete_flag"].fillna(False).astype(bool)
        if complete.all() and len(frame):
            return month
    raise RuntimeError("no month has a fully closed outcome window")


def matured(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows whose outcome is genuinely observed, not merely non-null."""
    return frame.loc[
        frame["performance_window_complete_flag"].fillna(False).astype(bool)
        & frame["monitoring_eligible_flag"].fillna(False).astype(bool)]


# --------------------------------------------------------------- position


def book(month: str) -> dict[str, Any]:
    """The whole-book position: the figures every Cockpit answer opens with."""
    d = read(month, ["customer_id", "facility_id", "product_code",
                     "gross_carrying_amount_sar", "ecl_final_sar",
                     "ecl_weighted_sar", "management_overlay_sar",
                     "ead_base_sar", "ifrs9_stage", "dpd",
                     "undrawn_commitment_sar", "current_credit_limit_sar"])
    gca = float(d["gross_carrying_amount_sar"].sum())
    ecl = float(d["ecl_final_sar"].sum())
    return {
        "month": month,
        "facilities": int(len(d)),
        "customers": int(d["customer_id"].nunique()),
        "gross_carrying_amount_sar": round(gca, 2),
        "ead_sar": round(float(d["ead_base_sar"].sum()), 2),
        "ecl_final_sar": round(ecl, 2),
        "ecl_weighted_sar": round(float(d["ecl_weighted_sar"].sum()), 2),
        "overlay_sar": round(float(d["management_overlay_sar"].sum()), 2),
        "ecl_coverage_pct": round(100.0 * ecl / gca, 4),
        "undrawn_sar": round(float(d["undrawn_commitment_sar"].sum()), 2),
        "unit": "SAR",
    }


def by_product(month: str) -> dict[str, Any]:
    """Exposure, ECL, facilities and customers per product. CP-CHAT-01."""
    d = read(month, ["customer_id", "product_code", "product_label",
                     "gross_carrying_amount_sar", "ecl_final_sar",
                     "ifrs9_stage", "dpd"])
    rows = []
    for code, group in d.groupby("product_code"):
        gca = float(group["gross_carrying_amount_sar"].sum())
        ecl = float(group["ecl_final_sar"].sum())
        rows.append({
            "product_code": str(code),
            "product_label": PRODUCTS.get(str(code), str(code)),
            "facilities": int(len(group)),
            "customers": int(group["customer_id"].nunique()),
            "gross_carrying_amount_sar": round(gca, 2),
            "ecl_final_sar": round(ecl, 2),
            "ecl_coverage_pct": round(100.0 * ecl / gca, 4) if gca else None,
        })
    rows.sort(key=lambda r: -r["gross_carrying_amount_sar"])
    return {"month": month, "rows": rows,
            "total_gca_sar": round(float(d["gross_carrying_amount_sar"].sum()), 2),
            "total_ecl_sar": round(float(d["ecl_final_sar"].sum()), 2),
            "ranking_by_exposure": [r["product_label"] for r in rows],
            "unit": "SAR",
            "note": "One row per facility; customers counted distinct."}


def by_stage(month: str, product: str | None = None) -> dict[str, Any]:
    """Exposure and ECL by IFRS 9 stage, with the disproportion CP-CHAT-02 asks for."""
    d = read(month, ["product_code", "ifrs9_stage",
                     "gross_carrying_amount_sar", "ecl_final_sar"])
    if product:
        d = d[d["product_code"] == product]
    gca_all = float(d["gross_carrying_amount_sar"].sum())
    ecl_all = float(d["ecl_final_sar"].sum())
    rows = []
    for stage, group in d.groupby("ifrs9_stage"):
        gca = float(group["gross_carrying_amount_sar"].sum())
        ecl = float(group["ecl_final_sar"].sum())
        rows.append({
            "stage": int(stage), "facilities": int(len(group)),
            "gross_carrying_amount_sar": round(gca, 2),
            "ecl_final_sar": round(ecl, 2),
            "exposure_share_pct": round(100.0 * gca / gca_all, 4) if gca_all else None,
            "ecl_share_pct": round(100.0 * ecl / ecl_all, 4) if ecl_all else None,
            "coverage_pct": round(100.0 * ecl / gca, 4) if gca else None,
        })
    rows.sort(key=lambda r: r["stage"])
    worst = max(rows, key=lambda r: (r["ecl_share_pct"] or 0)
                - (r["exposure_share_pct"] or 0))
    return {"month": month, "product": product, "rows": rows,
            "most_disproportionate_stage": worst["stage"],
            "note": ("A stage contributes disproportionately when its share of "
                     "ECL exceeds its share of exposure.")}


def movement(prior: str, month: str, product: str | None = None) -> dict[str, Any]:
    """The ECL movement between two months, with entrants and exits separated.

    CP-CHAT-04 and CP-CHAT-05. A facility present in only one of the two months
    is an entrant or an exit, not a movement, and conflating them is the single
    most common way an ECL bridge lies.
    """
    cols = ["facility_id", "product_code", "gross_carrying_amount_sar",
            "ecl_final_sar", "ifrs9_stage"]
    a, b = read(prior, cols), read(month, cols)
    if product:
        a, b = a[a["product_code"] == product], b[b["product_code"] == product]
    a = a.set_index("facility_id")
    b = b.set_index("facility_id")
    common = a.index.intersection(b.index)
    entrants = b.index.difference(a.index)
    exits = a.index.difference(b.index)
    return {
        "prior_month": prior, "month": month, "product": product,
        "ecl_prior_sar": round(float(a["ecl_final_sar"].sum()), 2),
        "ecl_now_sar": round(float(b["ecl_final_sar"].sum()), 2),
        "ecl_change_sar": round(float(b["ecl_final_sar"].sum()
                                      - a["ecl_final_sar"].sum()), 2),
        "ecl_change_pct": round(100.0 * (float(b["ecl_final_sar"].sum())
                                         / float(a["ecl_final_sar"].sum()) - 1), 4),
        "facilities_prior": int(len(a)), "facilities_now": int(len(b)),
        "continuing": int(len(common)),
        "entrants": int(len(entrants)),
        "exits": int(len(exits)),
        "ecl_from_continuing_sar": round(float(
            b.loc[common, "ecl_final_sar"].sum()
            - a.loc[common, "ecl_final_sar"].sum()), 2),
        "ecl_from_entrants_sar": round(float(b.loc[entrants, "ecl_final_sar"].sum()), 2),
        "ecl_from_exits_sar": round(-float(a.loc[exits, "ecl_final_sar"].sum()), 2),
        "note": ("continuing + entrants + exits reconciles to the total change; "
                 "an entrant is new business, not deterioration."),
    }


# ------------------------------------------------------------- delinquency


def delinquency(month: str, by: str = "product_code") -> dict[str, Any]:
    """30/60/90+ DPD by exposure AND by count, which are different numbers."""
    d = read(month, [by, "gross_carrying_amount_sar", "dpd"])
    out = []
    for key, group in d.groupby(by):
        gca = float(group["gross_carrying_amount_sar"].sum())
        row: dict[str, Any] = {by: str(key), "facilities": int(len(group)),
                               "gross_carrying_amount_sar": round(gca, 2)}
        for days in (30, 60, 90):
            late = group[group["dpd"] >= days]
            row[f"dpd{days}_exposure_pct"] = (
                round(100.0 * float(late["gross_carrying_amount_sar"].sum()) / gca, 4)
                if gca else None)
            row[f"dpd{days}_count_pct"] = (
                round(100.0 * len(late) / len(group), 4) if len(group) else None)
        out.append(row)
    out.sort(key=lambda r: -(r["dpd30_exposure_pct"] or 0))
    return {"month": month, "by": by, "rows": out,
            "highest_dpd30_by_exposure": out[0][by] if out else None,
            "note": "By exposure and by count are different measures."}


def trend(measure: str, product: str | None = None) -> dict[str, Any]:
    """A measure across every published month, in calendar order. CP-CHAT-09."""
    points = []
    for m in months():
        d = read(m, ["product_code", measure])
        if product:
            d = d[d["product_code"] == product]
        points.append({"month": m, "value": round(float(d[measure].sum()), 2)})
    return {"measure": measure, "product": product,
            "months": len(points), "points": points,
            "first_month": points[0]["month"], "last_month": points[-1]["month"],
            "note": "Every published month, in calendar order, none omitted."}


def deterioration(window: int = 3, by: str = "product_subsegment",
                  top: int = 10) -> dict[str, Any]:
    """Which segments deteriorated most on 30+ DPD over a window. CP-CHAT-10."""
    ms = months()
    now, then = ms[-1], ms[-1 - window]
    rows = []
    for label, frame in (("now", read(now, [by, "gross_carrying_amount_sar", "dpd"])),
                         ("then", read(then, [by, "gross_carrying_amount_sar", "dpd"]))):
        for key, group in frame.groupby(by):
            gca = float(group["gross_carrying_amount_sar"].sum())
            rate = (100.0 * float(group.loc[group["dpd"] >= 30,
                                            "gross_carrying_amount_sar"].sum()) / gca
                    if gca else None)
            rows.append({"segment": str(key), "when": label, "rate": rate,
                         "gca": gca})
    now_by = {r["segment"]: r for r in rows if r["when"] == "now"}
    then_by = {r["segment"]: r for r in rows if r["when"] == "then"}
    moved = []
    for segment, a in now_by.items():
        b = then_by.get(segment)
        if not b or a["rate"] is None or b["rate"] is None:
            continue
        moved.append({"segment": segment,
                      "dpd30_now_pct": round(a["rate"], 4),
                      "dpd30_then_pct": round(b["rate"], 4),
                      "change_pp": round(a["rate"] - b["rate"], 4),
                      "exposure_now_sar": round(a["gca"], 2)})
    moved.sort(key=lambda r: -r["change_pp"])
    return {"from_month": then, "to_month": now, "by": by,
            "rows": moved[:top],
            "ranking": [r["segment"] for r in moved[:top]],
            "note": "Percentage-POINT change in the 30+ DPD exposure rate."}


# --------------------------------------------------------------- scorecard


def _gini(score: np.ndarray, bad: np.ndarray) -> float:
    """AUC by the rank-sum identity, then Gini = 2·AUC − 1.

    Written from the definition rather than borrowed, and deliberately not the
    trapezoid-over-a-sampled-ROC version: ties are handled by average ranks,
    which is where a hand-rolled ROC usually goes wrong.
    """
    order = pd.Series(score).rank(method="average").to_numpy()
    n_bad = float(bad.sum())
    n_good = float(len(bad) - n_bad)
    if n_bad == 0 or n_good == 0:
        return float("nan")
    # Higher score is better, so a defaulter should rank LOW.
    auc_good_above_bad = ((order[bad == 0].sum() - n_good * (n_good + 1) / 2)
                          / (n_good * n_bad))
    return float(2 * auc_good_above_bad - 1)


def _ks(score: np.ndarray, bad: np.ndarray) -> float:
    frame = pd.DataFrame({"s": score, "b": bad}).sort_values("s")
    cum_bad = (frame["b"] == 1).cumsum() / max((frame["b"] == 1).sum(), 1)
    cum_good = (frame["b"] == 0).cumsum() / max((frame["b"] == 0).sum(), 1)
    return float((cum_bad - cum_good).abs().max())


def discrimination(score_field: str, product: str | None = None,
                   month: str | None = None) -> dict[str, Any]:
    """AUC, Gini and KS on the matured population. SC-02, SC-03, SC-10."""
    m = month or latest_matured()
    d = read(m, ["facility_id", "product_code", score_field,
                 "observed_default_within_window", "salary_transfer_flag",
                 "performance_window_complete_flag", "monitoring_eligible_flag"])
    d = matured(d)
    d = d[d["observed_default_within_window"].notna()]
    if product:
        d = d[d["product_code"] == product]
    d = d[d[score_field].notna()]
    bad = d["observed_default_within_window"].astype(bool).to_numpy().astype(int)
    score = pd.to_numeric(d[score_field], errors="coerce").to_numpy()
    gini = _gini(score, bad)
    return {
        "month": m, "score_field": score_field, "product": product,
        "population": int(len(d)),
        "defaults": int(bad.sum()),
        "default_rate_pct": round(100.0 * bad.mean(), 4) if len(bad) else None,
        "auc": round((gini + 1) / 2, 6),
        "gini": round(gini, 6),
        "ks": round(_ks(score, bad), 6),
        "note": ("Matured rows only — the outcome window has closed. Higher "
                 "score is better, so a defaulter should rank low."),
        "limitations": [
            "Discrimination is the ability to RANK. It says nothing about "
            "whether the predicted PD level is right — that is calibration.",
            "A cohort with few defaults gives an unstable statistic.",
        ],
    }


def score_band_outcome(product: str = "PERSONAL_LOAN",
                       band_field: str = "application_score_band",
                       month: str | None = None) -> dict[str, Any]:
    """Observed default rate by score band. SC-05, CP-CHAT-13."""
    m = month or latest_matured()
    d = read(m, ["product_code", band_field, "pd_pit_12m_base",
                 "observed_default_within_window",
                 "performance_window_complete_flag", "monitoring_eligible_flag"])
    d = matured(d)
    d = d[(d["observed_default_within_window"].notna())
          & (d["product_code"] == product)]
    rows = []
    for band, group in d.groupby(band_field):
        bad = group["observed_default_within_window"].astype(bool)
        rows.append({
            "band": str(band), "facilities": int(len(group)),
            "defaults": int(bad.sum()),
            "observed_default_pct": round(100.0 * float(bad.mean()), 4),
            "predicted_pd_pct": round(100.0 * float(
                pd.to_numeric(group["pd_pit_12m_base"],
                              errors="coerce").mean()), 4),
        })
    rows.sort(key=lambda r: r["band"])
    rates = [r["observed_default_pct"] for r in rows]
    return {"month": m, "product": product, "band_field": band_field,
            "rows": rows,
            "monotonic_decreasing": all(a >= b for a, b in zip(rates, rates[1:])),
            "monotonic_increasing": all(a <= b for a, b in zip(rates, rates[1:])),
            "note": ("Observed against predicted on the same matured "
                     "population — this is calibration, not discrimination.")}


def calibration(product: str | None = None,
                month: str | None = None) -> dict[str, Any]:
    """Observed-to-expected default ratio. SC-06."""
    m = month or latest_matured()
    d = read(m, ["product_code", "pd_pit_12m_base",
                 "observed_default_within_window",
                 "performance_window_complete_flag", "monitoring_eligible_flag"])
    d = matured(d)
    d = d[d["observed_default_within_window"].notna()]
    if product:
        d = d[d["product_code"] == product]
    observed = float(d["observed_default_within_window"].astype(bool).mean())
    expected = float(pd.to_numeric(d["pd_pit_12m_base"], errors="coerce").mean())
    return {"month": m, "product": product, "population": int(len(d)),
            "observed_default_pct": round(100.0 * observed, 4),
            "predicted_pd_pct": round(100.0 * expected, 4),
            "observed_to_expected": round(observed / expected, 4) if expected else None,
            "note": ("Above 1.0 means the book defaulted more than the model "
                     "expected on this cohort.")}


def psi(score_field: str = "application_score_at_origination",
        reference_month: str | None = None,
        month: str | None = None, bins: int = 10) -> dict[str, Any]:
    """Population stability index against a reference month. SC-07."""
    now = month or latest()
    ref = reference_month or months()[0]
    a = pd.to_numeric(read(ref, [score_field])[score_field],
                      errors="coerce").dropna()
    b = pd.to_numeric(read(now, [score_field])[score_field],
                      errors="coerce").dropna()
    edges = np.unique(np.quantile(a, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    pa = np.histogram(a, bins=edges)[0] / len(a)
    pb = np.histogram(b, bins=edges)[0] / len(b)
    safe = 1e-6
    contributions = (pb - pa) * np.log(np.maximum(pb, safe) / np.maximum(pa, safe))
    return {"score_field": score_field, "reference_month": ref, "month": now,
            "bins": int(len(pa)), "psi": round(float(contributions.sum()), 6),
            "reference_population": int(len(a)), "population": int(len(b)),
            "note": ("PSI on quantile bins of the reference month. The 0.10 / "
                     "0.25 bands are a common convention, not a regulation.")}


# ----------------------------------------------------------------- what-if


def whatif_pd_relative(shock: float, product: str | None = None,
                       salary_transfer: bool | None = None,
                       month: str | None = None) -> dict[str, Any]:
    """A relative PD shock, reconstructed independently for the AGGREGATE.

    A full independent rebuild of the hazard curve is the engine's job; what
    this checks is the population, the baseline, and that the direction and
    rough magnitude of the movement are right. The exact reconciliation of the
    engine to the published book is the neutral-parity gate, which is separate.
    """
    m = month or latest()
    d = read(m, ["facility_id", "customer_id", "product_code",
                 "salary_transfer_flag", "gross_carrying_amount_sar",
                 "ecl_final_sar", "pd_pit_12m_base", "ifrs9_stage"])
    if product:
        d = d[d["product_code"] == product]
    if salary_transfer is not None:
        d = d[d["salary_transfer_flag"] == salary_transfer]
    return {"month": m, "product": product, "salary_transfer": salary_transfer,
            "shock_relative": shock,
            "facilities": int(len(d)),
            "customers": int(d["customer_id"].nunique()),
            "baseline_ecl_sar": round(float(d["ecl_final_sar"].sum()), 3),
            "baseline_gca_sar": round(float(d["gross_carrying_amount_sar"].sum()), 2),
            "average_pd": round(float(pd.to_numeric(
                d["pd_pit_12m_base"], errors="coerce").mean()), 6),
            "stage_counts": {int(k): int(v) for k, v in
                             d["ifrs9_stage"].value_counts().sort_index().items()},
            "note": ("Baseline and population only. The stressed figure is the "
                     "engine's; this fixes what it must be computed over.")}


def cutoff_replay(cutoff: float, product: str = "PERSONAL_LOAN",
                  month: str | None = None) -> dict[str, Any]:
    """The application-cutoff replay, counted independently. SC-15, WI-CHAT-07."""
    m = month or latest()
    d = read(m, ["facility_id", "product_code",
                 "application_score_at_origination",
                 "gross_carrying_amount_sar",
                 "observed_default_within_window"])
    d = d.drop_duplicates("facility_id")
    d = d[d["product_code"] == product]
    score = pd.to_numeric(d["application_score_at_origination"], errors="coerce")
    excluded = score < cutoff
    known = d["observed_default_within_window"].notna()
    out: dict[str, Any] = {
        "month": m, "product": product, "cutoff": cutoff,
        "booked_facilities": int(len(d)),
        "would_be_excluded": int(excluded.sum()),
        "would_be_excluded_pct": round(100.0 * float(excluded.mean()), 4),
        "excluded_exposure_sar": round(float(
            d.loc[excluded, "gross_carrying_amount_sar"].sum()), 2),
        "lowest_booked_score": round(float(score.min()), 4),
        "outcomes_available": bool(known.any()),
    }
    if known.any():
        out["excluded_default_pct"] = round(100.0 * float(
            d.loc[excluded & known, "observed_default_within_window"]
            .astype(bool).mean()), 4)
        out["retained_default_pct"] = round(100.0 * float(
            d.loc[~excluded & known, "observed_default_within_window"]
            .astype(bool).mean()), 4)
    out["note"] = ("Booked originations only, and only the product asked "
                   "about. It says nothing about declined applicants.")
    return out


# ------------------------------------------------------------------ build


def build() -> dict[str, Any]:
    now, matured_month = latest(), latest_matured()
    prior = months()[-2]
    oracle: dict[str, Any] = {
        "generated_from": str(LAKE.relative_to(ROOT)),
        "months_published": months(),
        "latest_month": now,
        "latest_matured_month": matured_month,
        "book": book(now),
        "by_product": by_product(now),
        "by_stage": by_stage(now),
        "by_stage_personal_finance": by_stage(now, "PERSONAL_LOAN"),
        "movement_whole_book": movement(prior, now),
        "movement_personal_finance": movement(prior, now, "PERSONAL_LOAN"),
        "delinquency_by_product": delinquency(now),
        "trend_ecl_credit_card": trend("ecl_final_sar", "CREDIT_CARD"),
        "trend_ecl_whole_book": trend("ecl_final_sar"),
        "deterioration_3m": deterioration(),
        "application_discrimination_personal": discrimination(
            "application_score_at_origination", "PERSONAL_LOAN"),
        "application_discrimination_all": discrimination(
            "application_score_at_origination"),
        "behavioural_discrimination_all": discrimination("behavioural_score"),
        "bureau_discrimination_all": discrimination("bureau_score_current"),
        "score_band_outcome_personal": score_band_outcome(),
        "calibration_personal": calibration("PERSONAL_LOAN"),
        "calibration_all": calibration(),
        "psi_application_score": psi(),
        "whatif_pd20_personal": whatif_pd_relative(0.20, "PERSONAL_LOAN"),
        "whatif_pd20_personal_salary": whatif_pd_relative(
            0.20, "PERSONAL_LOAN", salary_transfer=True),
        "cutoff_620_personal_latest": cutoff_replay(620.0),
        "cutoff_620_personal_matured": cutoff_replay(620.0, month=matured_month),
    }
    # Discrimination by salary transfer, for SC-10.
    for flag, name in ((True, "salary_transfer"), (False, "non_salary_transfer")):
        d = read(matured_month, ["product_code", "salary_transfer_flag",
                                 "application_score_at_origination",
                                 "observed_default_within_window",
                                 "performance_window_complete_flag",
                                 "monitoring_eligible_flag"])
        d = matured(d)
        d = d[(d["observed_default_within_window"].notna())
              & (d["product_code"] == "PERSONAL_LOAN")
              & (d["salary_transfer_flag"] == flag)]
        bad = d["observed_default_within_window"].astype(bool).to_numpy().astype(int)
        score = pd.to_numeric(d["application_score_at_origination"],
                              errors="coerce").to_numpy()
        oracle[f"application_discrimination_{name}"] = {
            "month": matured_month, "population": int(len(d)),
            "defaults": int(bad.sum()),
            "gini": round(_gini(score, bad), 6) if bad.sum() else None,
            "note": "Too few defaults makes this unstable; the count is stated.",
        }
    return oracle


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    oracle = build()
    path = OUT / "retail_oracle.json"
    path.write_text(json.dumps(oracle, indent=2, default=str))

    b = oracle["book"]
    print(f"  Book at {b['month']}: {b['facilities']:,} facilities, "
          f"{b['customers']:,} customers")
    print(f"    GCA  SAR {b['gross_carrying_amount_sar']:,.2f}")
    print(f"    ECL  SAR {b['ecl_final_sar']:,.2f}  "
          f"({b['ecl_coverage_pct']:.4f}% coverage)")
    print(f"  Matured month: {oracle['latest_matured_month']}")
    a = oracle["application_discrimination_personal"]
    print(f"    Application Gini (personal finance): {a['gini']} "
          f"on {a['population']:,} rows, {a['defaults']} defaults")
    print(f"  Written to {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
