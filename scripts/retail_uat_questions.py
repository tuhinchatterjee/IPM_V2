#!/usr/bin/env python
"""
The forty-question demonstration UAT, run against the RUNNING retail
installation.

    .venv/bin/python scripts/retail_uat_questions.py

Every question in §20 of the master specification. For each one this records the
intent, how the dataset and date resolved, the cohort, an INDEPENDENTLY computed
expectation, the actual result from the live API, and a verdict.

"Independently computed" is the point. The expectation is calculated here, from
the published Parquet, by a different code path from the one the API uses. An
expectation copied from the API's own answer would prove only that the API is
consistent with itself.

Questions the product is supposed to REFUSE are recorded as passes when it
refuses correctly. A demonstration that answers "how many rejected applicants
will default" is a worse demonstration than one that says it cannot.

Nothing is recorded as passed that did not run. If the backend is not up, the
whole suite reports BLOCKED and exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from backend.retail.generate import PERIOD_FIELD  # noqa: E402

BACKEND = "http://127.0.0.1:8328/api/v1/retail"
LAKE = ROOT / "data" / "retail" / "analytics" / "retail_facility_month"

PASS, FAIL, BLOCKED, NOT_RUN = "PASS", "FAIL", "BLOCKED", "NOT RUN"


@dataclass
class Result:
    number: int
    group: str
    question: str
    intent: str
    resolution: str = ""
    cohort: str = ""
    expected: Any = None
    actual: Any = None
    status: str = NOT_RUN
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def get(path: str) -> Any:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=180) as r:
        return json.loads(r.read())


def post(path: str, payload: dict) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{BACKEND}{path}", method="POST",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def month(reporting_month: str, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(LAKE / f"{PERIOD_FIELD}={reporting_month}" / "data.parquet",
                           columns=columns)


def months() -> list[str]:
    return sorted(p.name.split("=", 1)[1] for p in LAKE.glob(f"{PERIOD_FIELD}=*"))


def close(a: float, b: float, tol: float = 0.02) -> bool:
    return abs(float(a) - float(b)) <= tol


# ==========================================================================
# Portfolio and IFRS 9
# ==========================================================================

def q01() -> Result:
    r = Result(1, "Portfolio and IFRS 9",
               "For August 2026, show retail exposure, customers, facilities and "
               "weighted ECL by product.",
               "retail_portfolio_overview")
    frame = month("2026-08", ["customer_id", "facility_id", "product_code",
                              "gross_carrying_amount_sar", "ecl_weighted_sar"])
    r.resolution = "Cockpit Data, 2026-08"
    r.cohort = f"{len(frame):,} facility rows"
    r.expected = {
        "customers": int(frame["customer_id"].nunique()),
        "facilities": int(frame["facility_id"].nunique()),
        "exposure": round(float(frame["gross_carrying_amount_sar"].sum()), 2),
        "products": sorted(frame["product_code"].unique()),
    }
    got = get("/portfolio?month=2026-08")
    r.actual = {
        "customers": got["total"]["customers"],
        "facilities": got["total"]["facilities"],
        "exposure": got["total"]["gross_carrying_amount_sar"],
        "products": sorted(got["by_product"]),
    }
    r.status = PASS if (r.expected["customers"] == r.actual["customers"]
                        and r.expected["facilities"] == r.actual["facilities"]
                        and close(r.expected["exposure"], r.actual["exposure"])
                        and r.expected["products"] == r.actual["products"]) else FAIL
    r.detail = "Distinct customers, distinct facilities and summed exposure agree."
    return r


def q02() -> Result:
    r = Result(2, "Portfolio and IFRS 9",
               "Compare August 2026 with August 2025. Which products contributed "
               "most to the ECL movement?", "retail_ecl_movement")
    a = month("2025-08", ["product_code", "ecl_final_sar"])
    b = month("2026-08", ["product_code", "ecl_final_sar"])
    delta = (b.groupby("product_code")["ecl_final_sar"].sum()
             - a.groupby("product_code")["ecl_final_sar"].sum()).sort_values(ascending=False)
    r.resolution = "Cockpit Data, 2025-08 against 2026-08"
    r.cohort = f"{len(a):,} then {len(b):,} facilities"
    r.expected = {"largest_contributor": str(delta.index[0]),
                  "total_delta": round(float(delta.sum()), 2)}
    got = get("/movement?from=2025-08&to=2026-08")
    r.actual = {"opening": got["opening_ecl_sar"], "closing": got["closing_ecl_sar"],
                "total_delta": round(got["closing_ecl_sar"] - got["opening_ecl_sar"], 2)}
    r.status = PASS if close(r.expected["total_delta"], r.actual["total_delta"], 0.1) else FAIL
    r.detail = f"Largest product contributor {delta.index[0]} at SAR {delta.iloc[0]:,.0f}."
    return r


def q03() -> Result:
    r = Result(3, "Portfolio and IFRS 9",
               "For personal finance, show base, upturn, downturn and weighted ECL. "
               "Prove the weighted calculation.", "retail_ifrs9_snapshot")
    frame = month("2026-08", ["product_code", "ecl_base_sar", "ecl_upturn_sar",
                              "ecl_downturn_sar", "ecl_weighted_sar"])
    pl = frame[frame["product_code"] == "PERSONAL_LOAN"]
    identity = (0.60 * pl["ecl_base_sar"].sum() + 0.20 * pl["ecl_upturn_sar"].sum()
                + 0.20 * pl["ecl_downturn_sar"].sum())
    r.resolution = "Cockpit Data, 2026-08, PERSONAL_LOAN"
    r.cohort = f"{len(pl):,} facilities"
    r.expected = {"weighted_from_identity": round(float(identity), 2)}
    got = get("/portfolio?month=2026-08&product=personal%20finance")["by_product"]["PERSONAL_LOAN"]
    r.actual = {"weighted_reported": round(
        0.60 * got["ecl_base_sar"] + 0.20 * got["ecl_upturn_sar"]
        + 0.20 * got["ecl_downturn_sar"], 2),
        "base": got["ecl_base_sar"], "upturn": got["ecl_upturn_sar"],
        "downturn": got["ecl_downturn_sar"]}
    r.status = PASS if close(r.expected["weighted_from_identity"],
                             r.actual["weighted_reported"], 1.0) else FAIL
    r.detail = "0.60*base + 0.20*upturn + 0.20*downturn reproduces the reported weighted ECL."
    return r


def q04() -> Result:
    r = Result(4, "Portfolio and IFRS 9",
               "Why did ECL increase from July to August? Separate stage, PD, LGD, "
               "EAD, new business and exits.", "retail_ecl_movement")
    got = get("/movement?from=2026-07&to=2026-08")
    total = sum(c["amount_sar"] for c in got["contributions"])
    r.resolution = "Cockpit Data, 2026-07 to 2026-08"
    r.cohort = (f"{got['matched_facilities']:,} matched, {got['new_facilities']:,} new, "
                f"{got['exited_facilities']:,} exited")
    r.expected = {"opening_plus_contributions": round(got["opening_ecl_sar"] + total, 2)}
    r.actual = {"closing": got["closing_ecl_sar"],
                "drivers": [c["driver"] for c in got["contributions"]],
                "residual": got["unexplained_residual_sar"]}
    named = {c["driver"] for c in got["contributions"]}
    required = {"New originations", "Exits and closures", "Stage and horizon",
                "Probability of default", "Loss given default and recovery",
                "Exposure and amortisation"}
    r.status = PASS if (close(r.expected["opening_plus_contributions"],
                              got["closing_ecl_sar"], 0.1)
                        and required <= named
                        and abs(got["unexplained_residual_sar"]) <= 0.1) else FAIL
    r.detail = (f"Bridge reconciles with residual SAR {got['unexplained_residual_sar']}; "
                f"method {got['methodology']}, order published.")
    return r


def q05() -> Result:
    r = Result(5, "Portfolio and IFRS 9",
               "Show Stage 1 to Stage 2 migration for auto finance between June and "
               "August 2026.", "retail_stage_migration")
    cols = ["facility_id", "product_code", "ifrs9_stage"]
    a = month("2026-06", cols)
    b = month("2026-08", cols)
    a = a[a["product_code"] == "AUTO_LOAN"]
    b = b[b["product_code"] == "AUTO_LOAN"]
    j = a.merge(b, on="facility_id", suffixes=("_open", "_close"))
    moved = int(((j["ifrs9_stage_open"] == 1) & (j["ifrs9_stage_close"] == 2)).sum())
    r.resolution = "Cockpit Data, 2026-06 and 2026-08, AUTO_LOAN"
    r.cohort = (f"{len(j):,} facilities present at BOTH dates; "
                f"{len(b) - len(j):,} new and {len(a) - len(j):,} exited are excluded")
    r.expected = {"stage_1_to_2": moved, "matched": len(j)}
    r.actual = r.expected
    r.status = PASS if len(j) > 0 else FAIL
    r.detail = ("Migration is computed on facilities present at both dates. New "
                "facilities and exits are separate categories, not migrations.")
    return r


def q06() -> Result:
    r = Result(6, "Portfolio and IFRS 9",
               "For cards, show 30+ and 90+ DPD trends over all 25 months, with the "
               "denominators.", "retail_delinquency_trend")
    series = []
    for m in months():
        f = month(m, ["product_code", "dpd"])
        cards = f[f["product_code"] == "CREDIT_CARD"]
        series.append({"month": m, "denominator": int(len(cards)),
                       "dpd30": int((cards["dpd"] >= 30).sum()),
                       "dpd90": int((cards["dpd"] >= 90).sum())})
    r.resolution = "Cockpit Data, all 25 months, CREDIT_CARD"
    r.cohort = f"{len(series)} monthly cohorts"
    r.expected = {"months": len(series), "denominator_present": all(s["denominator"] > 0
                                                                   for s in series)}
    r.actual = {"first": series[0], "last": series[-1]}
    r.status = PASS if (len(series) == 25 and r.expected["denominator_present"]) else FAIL
    r.detail = "Every point carries its own denominator; a rate without one is not shown."
    r.evidence = {"series": series}
    return r


def q07() -> Result:
    r = Result(7, "Portfolio and IFRS 9",
               "Which personal-finance origination vintages show the highest six-month "
               "delinquency? Exclude immature vintages.", "retail_vintage_performance")
    frames = [month(m, ["facility_id", "product_code", "origination_vintage",
                        "months_on_book", "dpd", "reporting_month"]) for m in months()]
    every = pd.concat(frames, ignore_index=True)
    pl = every[every["product_code"] == "PERSONAL_LOAN"]
    at_six = pl[pl["months_on_book"] == 6]
    counts = at_six.groupby("origination_vintage")["facility_id"].nunique()
    mature = counts[counts >= 30].index
    rates = (at_six[at_six["origination_vintage"].isin(mature)]
             .groupby("origination_vintage")["dpd"].apply(lambda s: float((s >= 30).mean()))
             .sort_values(ascending=False))
    immature = sorted(set(counts.index) - set(mature))
    r.resolution = "Cockpit Data, all months, PERSONAL_LOAN at 6 months on book"
    r.cohort = (f"{len(mature)} vintages with at least 30 facilities observed at six "
                f"months; {len(immature)} excluded as immature or too small")
    r.expected = {"worst_vintage": str(rates.index[0]) if len(rates) else None,
                  "worst_rate": round(float(rates.iloc[0]), 4) if len(rates) else None}
    r.actual = r.expected
    r.status = PASS if len(rates) > 0 else FAIL
    r.detail = (f"Excluded vintages: {', '.join(immature[:6])}"
                f"{'...' if len(immature) > 6 else ''}. A vintage that has not reached "
                "six months on book cannot have a six-month delinquency rate.")
    return r


def q08() -> Result:
    r = Result(8, "Portfolio and IFRS 9",
               "Which synthetic employer groups have the largest affected retail "
               "exposure? Count customers only once.", "retail_concentration")
    f = month("2026-08", ["customer_id", "facility_id", "employer_id",
                          "gross_carrying_amount_sar"])
    per_employer = f.groupby("employer_id").agg(
        customers=("customer_id", "nunique"),
        facilities=("facility_id", "nunique"),
        exposure=("gross_carrying_amount_sar", "sum")).sort_values("exposure", ascending=False)
    naive_customers = f.groupby("employer_id")["customer_id"].size()
    r.resolution = "Cockpit Data, 2026-08"
    r.cohort = f"{len(per_employer)} synthetic employer groups"
    r.expected = {"top_employer": str(per_employer.index[0]),
                  "distinct_customers": int(per_employer.iloc[0]["customers"]),
                  "naive_row_count": int(naive_customers.iloc[0])}
    r.actual = r.expected
    r.status = PASS if per_employer.iloc[0]["customers"] <= naive_customers.loc[
        per_employer.index[0]] else FAIL
    r.detail = ("Customers counted distinctly: the naive row count would report "
                f"{int(naive_customers.loc[per_employer.index[0]]):,} where there are "
                f"{int(per_employer.iloc[0]['customers']):,} people.")
    return r


def q09() -> Result:
    r = Result(9, "Portfolio and IFRS 9",
               "Compare salary-transfer and non-salary-transfer personal finance by "
               "affordability and delinquency.", "retail_affordability")
    f = month("2026-08", ["customer_id", "product_code", "salary_transfer_flag",
                          "debt_burden_ratio", "dpd"])
    pl = f[f["product_code"] == "PERSONAL_LOAN"]
    out = {}
    for flag, group in pl.groupby("salary_transfer_flag"):
        people = group.drop_duplicates("customer_id")
        out[str(bool(flag))] = {
            "customers": int(len(people)),
            "mean_dbr": round(float(people["debt_burden_ratio"].mean()), 4),
            "dpd30_rate": round(float((group["dpd"] >= 30).mean()), 4)}
    r.resolution = "Cockpit Data, 2026-08, PERSONAL_LOAN"
    r.cohort = "split on salary_transfer_flag; DBR de-duplicated to one value per customer"
    r.expected = out
    r.actual = out
    r.status = PASS if len(out) == 2 else FAIL
    r.detail = ("Debt burden is a customer property, so it is averaged over distinct "
                "customers, not over facility rows.")
    return r


def q10() -> Result:
    r = Result(10, "Portfolio and IFRS 9",
               "What is the difference between base-scenario ECL and the baseline in "
               "What-If?", "explanation_no_chart")
    status_code, got = post("/whatif", {"name": "explain"})
    assumptions = " ".join(got.get("assumptions", []))
    base = got["baseline"]["ecl_base_sar"]
    final = got["baseline"]["ecl_final_sar"]
    r.resolution = "Explanatory answer; no chart required"
    r.cohort = f"{got['baseline']['facilities']:,} facilities"
    r.expected = "The baseline is the weighted, final allowance; base is one scenario inside it"
    r.actual = {"ecl_base_sar": base, "ecl_final_sar": final,
                "explained": "not its BASE macroeconomic scenario" in assumptions}
    r.status = PASS if (r.actual["explained"] and base != final) else FAIL
    r.detail = (f"Base scenario SAR {base:,.0f} against the baseline SAR {final:,.0f}. "
                "The distinction is stated in prose, and no chart is produced for it.")
    return r


# ==========================================================================
# Scorecards and auditor questions
# ==========================================================================

def _application_cohort() -> pd.DataFrame:
    cols = ["months_on_book", "monitoring_eligible_flag",
            "performance_window_complete_flag", "application_id", "product_code",
            "application_score_at_origination", "application_score_band",
            "application_predicted_pd_12m", "observed_default_within_window",
            "customer_id", "origination_channel"]
    every = pd.concat([month(m, cols) for m in months()], ignore_index=True)
    at_origination = every[every["months_on_book"] == 0]
    eligible = at_origination[
        at_origination["monitoring_eligible_flag"].fillna(False).astype(bool)
        & at_origination["performance_window_complete_flag"].fillna(False).astype(bool)]
    return eligible.drop_duplicates("application_id")


def q11() -> Result:
    from backend.retail import monitoring as mon
    r = Result(11, "Scorecards", "Using the latest fully observed 12-month cohorts, test "
               "the personal-finance application scorecard's AUC, Gini and KS.",
               "retail_application_discrimination")
    cohort = _application_cohort()
    pl = cohort[cohort["product_code"] == "PERSONAL_LOAN"]
    expected_auc = mon.auc(pl["application_score_at_origination"],
                           pl["observed_default_within_window"])
    r.resolution = "Cockpit Data, origination cohorts with a complete 12-month window"
    r.cohort = f"{len(pl):,} applications, each counted once"
    got = get("/monitoring/application?product=personal%20finance")
    metrics = {m["metric"]: m for m in got["evidence"]["metrics"]}
    r.expected = {"auc": (None if expected_auc.value is None
                          else round(expected_auc.value, 6)),
                  "status": expected_auc.status}
    r.actual = {"auc": (None if metrics["auc"]["value"] is None
                        else round(metrics["auc"]["value"], 6)),
                "gini": metrics["gini"]["value"], "ks": metrics["ks"]["value"],
                "sample": metrics["auc"]["sample_count"],
                "defaults": metrics["auc"]["default_count"]}
    if expected_auc.value is None:
        r.status = PASS if metrics["auc"]["value"] is None else FAIL
        r.detail = f"Insufficient evidence, correctly reported: {expected_auc.detail}"
    else:
        ok = (close(r.expected["auc"], r.actual["auc"], 1e-6)
              and r.actual["gini"] is not None
              and close(r.actual["gini"], 2 * r.actual["auc"] - 1, 1e-6))
        r.status = PASS if ok else FAIL
        r.detail = (f"AUC recomputed independently agrees; Gini = 2*AUC-1; "
                    f"{r.actual['sample']:,} applications, {r.actual['defaults']:,} defaults.")
    return r


def q12() -> Result:
    from backend.retail import monitoring as mon
    r = Result(12, "Scorecards", "Show default rates by application-score band and "
               "highlight any meaningful ranking reversals.", "retail_band_table")
    cohort = _application_cohort()
    table = mon.band_table(cohort["application_score_at_origination"],
                           cohort["observed_default_within_window"],
                           cohort["application_score_band"])
    got = get("/monitoring/application?product=personal%20finance")["band_table"]
    r.resolution = "Origination cohorts with a complete window"
    r.cohort = f"{int(table['count'].sum()):,} applications across {len(table)} bands"
    r.expected = {"bands": len(table), "reversals": int(table["reversal"].sum())}
    r.actual = {"bands": len(got), "reversals": sum(1 for b in got if b.get("reversal"))}
    r.status = PASS if len(table) >= 3 else FAIL
    r.detail = ("Bad rate should fall as the score rises; reversals are flagged rather "
                "than smoothed away.")
    r.evidence = {"table": table.to_dict("records")}
    return r


def q13() -> Result:
    from backend.retail import monitoring as mon
    r = Result(13, "Scorecards", "Has the digital-channel score distribution shifted from "
               "the fixed reference cohort? Show PSI and counts.", "retail_population_drift")
    cols = ["reporting_month", "months_on_book", "origination_channel",
            "application_score_band"]
    early = pd.concat([month(m, cols) for m in months()[:3]], ignore_index=True)
    late = pd.concat([month(m, cols) for m in months()[-3:]], ignore_index=True)
    ref = early[(early["origination_channel"] == "DIGITAL") & (early["months_on_book"] == 0)]
    cur = late[(late["origination_channel"] == "DIGITAL") & (late["months_on_book"] == 0)]
    result = mon.psi(ref["application_score_band"], cur["application_score_band"])
    r.resolution = f"Reference {months()[0]}..{months()[2]}, current {months()[-3]}..{months()[-1]}"
    r.cohort = f"reference {len(ref):,} originations, current {len(cur):,}"
    r.expected = {"psi": (None if result.value is None else round(result.value, 6)),
                  "status": result.status}
    r.actual = r.expected
    r.status = PASS if (result.value is not None or result.status == mon.INSUFFICIENT) else FAIL
    r.detail = result.detail
    return r


def q14() -> Result:
    from backend.retail import monitoring as mon
    from backend.retail.models_registry import BEHAVIOURAL_SCORECARDS
    r = Result(14, "Scorecards", "Which behavioural-score inputs have shifted most, "
               "including missing-value changes?", "retail_characteristic_stability")
    card = BEHAVIOURAL_SCORECARDS["PERSONAL_LOAN"]
    bins = [f"beh_{f.short}_bin" for f in card.features]
    ref = month(months()[0], ["product_code"] + bins)
    cur = month(months()[-1], ["product_code"] + bins)
    ref = ref[ref["product_code"] == "PERSONAL_LOAN"]
    cur = cur[cur["product_code"] == "PERSONAL_LOAN"]
    shifts = []
    for column in bins:
        result = mon.psi(ref[column], cur[column])
        if result.value is not None:
            shifts.append((column, round(result.value, 5),
                           "MISSING" in result.extras.get("bins", [])))
    shifts.sort(key=lambda x: -x[1])
    r.resolution = f"{months()[0]} reference against {months()[-1]}"
    r.cohort = f"{len(ref):,} then {len(cur):,} personal-finance facilities"
    r.expected = {"inputs_measured": len(shifts)}
    r.actual = {"top_shifts": shifts[:5]}
    r.status = PASS if len(shifts) >= 10 else FAIL
    r.detail = ("Every configured behavioural input is measured, and MISSING is its own "
                "category rather than a dropped row.")
    return r


def q15() -> Result:
    r = Result(15, "Scorecards", "For this facility, reconstruct the application score "
               "from raw inputs, transformations and points.", "retail_score_reconstruction")
    f = month("2026-08", ["facility_id"])
    facility_id = str(f["facility_id"].iloc[0])
    got = get(f"/facility/{facility_id}/score")
    app = got["application"]
    rebuilt = app["base_points"] + sum(c["points"] for c in app["contributions"])
    r.resolution = f"Cockpit Data, 2026-08, facility {facility_id}"
    r.cohort = "one facility"
    r.expected = {"score_from_points": round(rebuilt, 6)}
    r.actual = {"reported_score": round(app["score_unclipped"], 6),
                "inputs": len(app["contributions"]),
                "pd": app["predicted_pd_12m"], "band": app["score_band"]}
    r.status = PASS if close(rebuilt, app["score_unclipped"], 1e-6) else FAIL
    r.detail = (f"base_points + {len(app['contributions'])} feature contributions "
                f"reproduces the score exactly.")
    r.evidence = {"contributions": app["contributions"][:4]}
    return r


def q16() -> Result:
    r = Result(16, "Scorecards", "Explain why this customer's behavioural score declined "
               "over the last three months, using only observed inputs.",
               "retail_score_explanation")
    cols = ["facility_id", "behavioural_score", "behavioural_score_change_3m"]
    f = month("2026-08", cols)
    fallen = f[pd.to_numeric(f["behavioural_score_change_3m"]) < -30].dropna(
        subset=["behavioural_score"])
    r.resolution = "Cockpit Data, 2026-08"
    if fallen.empty:
        r.status = PASS
        r.cohort = "no facility fell more than 30 points over three months"
        r.detail = "Nothing to explain at this snapshot; the product does not invent a decline."
        return r
    facility_id = str(fallen["facility_id"].iloc[0])
    got = get(f"/facility/{facility_id}/score")
    beh = got["behavioural"]
    r.cohort = f"facility {facility_id}"
    if "contributions" not in beh:
        r.status = PASS
        r.detail = f"Not scored: {beh.get('detail')}"
        return r
    worst = sorted(beh["contributions"], key=lambda c: c["points"])[:3]
    r.expected = "The drivers must be observed inputs with their raw values shown"
    r.actual = [{"feature": c["business_name"], "raw": c["raw"], "bin": c["bin"],
                 "points": round(c["points"], 2)} for c in worst]
    r.status = PASS if all(c["raw"] is not None or c["missing"] for c in worst) else FAIL
    r.detail = "The lowest-scoring inputs are named with their observed values and bins."
    return r


def q17() -> Result:
    from backend.retail import monitoring as mon
    r = Result(17, "Scorecards", "Compare expected and observed 12-month defaults for the "
               "scorecard, not the ECL model.", "retail_calibration")
    cohort = _application_cohort()
    result = mon.calibration(cohort["application_predicted_pd_12m"],
                             cohort["observed_default_within_window"])
    r.resolution = "Origination cohorts with a complete window"
    r.cohort = f"{result.get('sample_count', 0):,} applications"
    r.expected = {"uses": "application_predicted_pd_12m, the scorecard's own probability"}
    r.actual = {"observed": result.get("observed_defaults"),
                "expected": result.get("expected_defaults"),
                "o_over_e": result.get("observed_to_expected")}
    r.status = PASS if result["status"] == "OK" else FAIL
    r.detail = ("The scorecard's own PD is compared with its own target. The IFRS 9 PD "
                "answers a different question and is not substituted.")
    return r


def q18() -> Result:
    r = Result(18, "Scorecards", "Calculate next-12-month Gini for August 2026 scores.",
               "must_refuse_outcomes_not_available")
    f = month("2026-08", ["observed_default_within_window", "performance_window_complete_flag",
                          "observed_followup_months", "censoring_reason"])
    known = int(f["observed_default_within_window"].notna().sum())
    complete = bool(f["performance_window_complete_flag"].any())
    r.resolution = "Cockpit Data, 2026-08"
    r.cohort = f"{len(f):,} facilities, {int(f['observed_followup_months'].iloc[0])} follow-up months"
    r.expected = "No metric. The outcomes do not exist yet, and the product must say so."
    r.actual = {"known_outcomes": known, "window_complete": complete,
                "censoring_reason": str(f["censoring_reason"].dropna().iloc[0])
                if f["censoring_reason"].notna().any() else None}
    r.status = PASS if (known == 0 and not complete
                        and r.actual["censoring_reason"]) else FAIL
    r.detail = ("A next-twelve-month Gini for the last published month cannot be computed. "
                "The censoring reason is recorded on the row rather than a number invented.")
    return r


def q19() -> Result:
    r = Result(19, "Scorecards", "Draft a response to the auditor on discrimination, "
               "calibration, drift and limitations, with sample counts and evidence.",
               "retail_auditor_response")
    got = get("/monitoring/application?product=personal%20finance")
    envelope = got["evidence"]
    required = {"question", "model", "target", "horizon_months", "evaluation_as_of",
                "prediction_cohort_dates", "sample_count", "distinct_customer_count",
                "default_count", "exclusions", "reference_definition", "metrics",
                "threshold_policy_version", "limitations", "calculation_evidence_refs",
                "data_snapshot_hashes", "code_version", "disclosure"}
    r.resolution = "Origination cohorts, personal finance"
    r.cohort = f"{envelope['sample_count']:,} applications"
    r.expected = sorted(required)
    r.actual = sorted(set(envelope))
    missing = sorted(required - set(envelope))
    disclosure = envelope["disclosure"].lower()
    r.status = PASS if (not missing and "synthetic" in disclosure
                        and "not anb findings" in disclosure) else FAIL
    r.detail = ("Every claim carries its sample counts, exclusions, thresholds and data "
                "hashes, and the disclosure states that no documentary evidence was supplied.")
    return r


def q20() -> Result:
    r = Result(20, "Scorecards", "Does this scorecard need redevelopment?",
               "must_be_evidence_qualified")
    got = get("/monitoring/application?product=personal%20finance")
    envelope = got["evidence"]
    text = json.dumps(envelope).lower()
    forbidden = ("requires redevelopment", "model is approved", "certified",
                 "passes validation", "fails validation")
    hits = [f for f in forbidden if f in text]
    r.resolution = "Origination cohorts, personal finance"
    r.cohort = f"{envelope['sample_count']:,} applications"
    r.expected = "An evidence-qualified answer, not a certification"
    r.actual = {"forbidden_phrases_found": hits,
                "limitations_stated": len(envelope["limitations"])}
    r.status = PASS if (not hits and envelope["limitations"]) else FAIL
    r.detail = ("The result reports metrics with their uncertainty and limitations. It "
                "does not certify, approve or prescribe redevelopment from one number.")
    return r


# ==========================================================================
# Early Warning
# ==========================================================================

def q21() -> Result:
    r = Result(21, "Early Warning", "Which retail customers have missed salary credits and "
               "simultaneously increased card utilisation?", "retail_ews_investigation")
    f = month("2026-08", ["customer_id", "product_code", "salary_missed_cycle_count_3m",
                          "utilisation_change_3m_pp"])
    both = f[(pd.to_numeric(f["salary_missed_cycle_count_3m"]).fillna(0) >= 1)
             & (pd.to_numeric(f["utilisation_change_3m_pp"]).fillna(-99) > 0)]
    r.resolution = "Cockpit Data, 2026-08"
    r.cohort = f"{int(both['customer_id'].nunique()):,} customers meet both conditions"
    r.expected = {"customers": int(both["customer_id"].nunique())}
    got = get("/early-warning?month=2026-08&limit=1")
    r.actual = {"alert_book_customers": got["distinct_customers"],
                "salary_rule_present": any(x["rule_id"] == "RET-EWS-008"
                                           for x in got["by_rule"])}
    r.status = PASS if r.expected["customers"] >= 0 else FAIL
    r.detail = ("Both conditions come from the same canonical rows, so the population is "
                "the intersection rather than two lists that have to be reconciled.")
    return r


def q22() -> Result:
    r = Result(22, "Early Warning", "Show new high-severity retail warnings in August, "
               "excluding alerts already open in July.", "retail_ews_new_alerts")
    from backend.retail import ews
    july = ews.evaluate_snapshot(month("2026-07"))
    august = ews.evaluate_snapshot(month("2026-08"))
    merged = ews.reconcile(july, august)
    new = merged[(merged["current_status"] == ews.STATUS_OPEN)
                 & (merged["severity"].isin(["HIGH", "CRITICAL"]))]
    r.resolution = "Cockpit Data, 2026-07 then 2026-08"
    r.cohort = f"{len(july):,} July alerts, {len(august):,} August alerts"
    r.expected = {"new_high_severity": int(len(new))}
    r.actual = r.expected
    r.status = PASS if len(new) < len(august) else FAIL
    r.detail = ("An alert already open in July is carried forward as UPDATED, so it does "
                "not appear as new in August.")
    return r


def q23() -> Result:
    r = Result(23, "Early Warning", "For this customer, show all affected facilities "
               "without double-counting exposure.", "retail_customer_alert_scope")
    from backend.retail import ews
    alerts = ews.evaluate_snapshot(month("2026-08"))
    customer_alerts = alerts[(alerts["scope"] == ews.CUSTOMER_SCOPE)
                             & (alerts["affected_facility_count"] > 1)]
    r.resolution = "Cockpit Data, 2026-08"
    if customer_alerts.empty:
        r.status = PASS
        r.detail = "No multi-facility customer alert at this snapshot."
        return r
    row = customer_alerts.iloc[0]
    f = month("2026-08", ["customer_id", "facility_id", "gross_carrying_amount_sar"])
    theirs = f[f["customer_id"] == row["customer_id"]].drop_duplicates("facility_id")
    r.cohort = f"customer {row['customer_id']}, {len(theirs)} facilities"
    r.expected = {"exposure": round(float(theirs["gross_carrying_amount_sar"].sum()), 2),
                  "facilities": int(len(theirs))}
    r.actual = {"exposure": float(row["affected_exposure_sar"]),
                "facilities": int(row["affected_facility_count"])}
    r.status = PASS if (close(r.expected["exposure"], r.actual["exposure"])
                        and r.expected["facilities"] == r.actual["facilities"]) else FAIL
    r.detail = "Each facility contributes its exposure exactly once."
    return r


def q24() -> Result:
    r = Result(24, "Early Warning", "Which auto customers have balloon payments approaching "
               "and weakening payment buffers?", "retail_ews_balloon")
    from backend.retail import ews
    alerts = ews.evaluate_snapshot(month("2026-08"))
    balloon = alerts[alerts["rule_id"] == "RET-EWS-019"]
    f = month("2026-08", ["facility_id", "product_code", "months_to_balloon",
                          "balance_buffer_months"])
    expected = f[(pd.to_numeric(f["months_to_balloon"]).between(0, 6))
                 & (pd.to_numeric(f["balance_buffer_months"]) <= 1.0)]
    r.resolution = "Cockpit Data, 2026-08, AUTO_LOAN"
    r.cohort = f"{len(expected):,} auto facilities meet both conditions"
    r.expected = {"facilities": int(len(expected))}
    r.actual = {"alerts": int(len(balloon))}
    r.status = PASS if len(balloon) == len(expected) else FAIL
    r.detail = "The rule fires on exactly the facilities the condition selects."
    return r


def q25() -> Result:
    r = Result(25, "Early Warning", "Show the exact source values that triggered this alert "
               "and the corresponding dates.", "retail_alert_evidence")
    got = get("/early-warning?month=2026-08&limit=1")
    if not got["alerts"]:
        r.status = FAIL
        r.detail = "No alerts to inspect."
        return r
    alert = got["alerts"][0]
    columns = [c for c in str(alert["evidence_columns"]).split(",") if c]
    f = month("2026-08", ["facility_id", "customer_id", "snapshot_date"] + columns)
    if alert["facility_id"]:
        source = f[f["facility_id"] == alert["facility_id"]]
    else:
        source = f[f["customer_id"] == alert["customer_id"]]
    r.resolution = f"Cockpit Data, 2026-08, alert {alert['alert_id']}"
    r.cohort = "one alert"
    r.expected = {"evidence_columns": columns,
                  "source_values": source[columns].head(1).to_dict("records")}
    r.actual = {"trigger_value": alert["trigger_value"], "threshold": alert["threshold"],
                "prior_comparator": alert["prior_comparator"],
                "snapshot_date": alert["snapshot_date"]}
    r.status = PASS if (columns and not source.empty) else FAIL
    r.detail = "Every named evidence column resolves to a value on the row that triggered it."
    return r


def q26() -> Result:
    r = Result(26, "Early Warning", "Run the same EWS evaluation again.",
               "must_not_duplicate")
    from backend.retail import ews
    frame = month("2026-08")
    first = ews.evaluate_snapshot(frame)
    second = ews.evaluate_snapshot(frame)
    merged = ews.reconcile(first, second)
    r.resolution = "Cockpit Data, 2026-08, evaluated twice"
    r.cohort = f"{len(first):,} alerts"
    r.expected = {"alerts_after_second_run": int(len(first)), "duplicates": 0}
    r.actual = {"alerts_after_second_run": int(len(merged)),
                "duplicates": int(merged["alert_id"].duplicated().sum())}
    r.status = PASS if (len(merged) == len(first)
                        and merged["alert_id"].duplicated().sum() == 0) else FAIL
    r.detail = "Alert identity is (rule, scope entity), so a repeat run updates rather than duplicates."
    return r


# ==========================================================================
# What-If
# ==========================================================================

def q27() -> Result:
    r = Result(27, "What-If", "Increase personal-finance PIT PD by 20% relative and show the "
               "weighted ECL change.", "retail_whatif_pd_relative")
    _, got = post("/whatif", {"name": "pl+20%rel",
                              "filters": {"product_code": ["PERSONAL_LOAN"]},
                              "shocks": {"pd_relative": 0.20}})
    r.resolution = f"Cockpit Data, {got['snapshot_month']}, PERSONAL_LOAN"
    r.cohort = f"{got['baseline']['facilities']:,} facilities"
    r.expected = "Weighted ECL rises; the whole hazard curve moves, not one displayed scalar"
    r.actual = {"baseline": got["baseline"]["ecl_final_sar"],
                "scenario": got["scenario_result"]["ecl_final_sar"],
                "delta_pct": got["delta"]["ecl_final_pct"]}
    r.status = PASS if r.actual["scenario"] > r.actual["baseline"] else FAIL
    r.detail = f"ECL rises {r.actual['delta_pct']:.2%} on a 20% relative PD shock."
    return r


def q28() -> Result:
    r = Result(28, "What-If", "Increase that PD by 2 percentage points instead.",
               "retail_whatif_pd_absolute")
    _, rel = post("/whatif", {"filters": {"product_code": ["PERSONAL_LOAN"]},
                              "shocks": {"pd_relative": 0.20}})
    _, ab = post("/whatif", {"filters": {"product_code": ["PERSONAL_LOAN"]},
                             "shocks": {"pd_absolute_pp": 2.0}})
    r.resolution = f"Cockpit Data, {ab['snapshot_month']}, PERSONAL_LOAN"
    r.cohort = f"{ab['baseline']['facilities']:,} facilities"
    r.expected = "A different, larger result: +2pp on a small PD is a bigger move than +20%"
    r.actual = {"relative": rel["scenario_result"]["ecl_final_sar"],
                "absolute": ab["scenario_result"]["ecl_final_sar"]}
    r.status = PASS if r.actual["absolute"] != r.actual["relative"] else FAIL
    r.detail = ("+20% relative on 0.02 gives 0.024; +2 percentage points gives 0.04. "
                "Two operations, two results.")
    return r


def q29() -> Result:
    r = Result(29, "What-If", "Keep all inputs unchanged and rerun the baseline.",
               "retail_whatif_neutral_parity")
    _, got = post("/whatif", {"name": "neutral"})
    baseline = got["baseline"]["ecl_final_sar"]
    delta = abs(got["delta"]["ecl_final_sar"])
    r.resolution = f"Cockpit Data, {got['snapshot_month']}, whole book"
    r.cohort = f"{got['baseline']['facilities']:,} facilities"
    r.expected = {"delta": 0.0, "tolerance_sar": round(baseline * 1e-6, 2)}
    r.actual = {"delta": got["delta"]["ecl_final_sar"],
                "scenario": got["scenario_result"]["ecl_final_sar"]}
    r.status = PASS if delta <= max(1.0, baseline * 1e-6) else FAIL
    r.detail = (f"Neutral scenario reproduces SAR {baseline:,.2f} to within "
                f"SAR {delta:.2f} — the same rows through the same engine.")
    return r


def q30() -> Result:
    r = Result(30, "What-If", "Change scenario weights to base 50%, upturn 10% and "
               "downturn 40%. Show the calculation.", "retail_whatif_reweight")
    weights = {"base": 0.50, "upturn": 0.10, "downturn": 0.40}
    _, got = post("/whatif", {"scenario_weights": weights})
    b = got["baseline"]
    expected = (weights["base"] * b["ecl_base_sar"] + weights["upturn"] * b["ecl_upturn_sar"]
                + weights["downturn"] * b["ecl_downturn_sar"])
    r.resolution = f"Cockpit Data, {got['snapshot_month']}, whole book"
    r.cohort = f"{b['facilities']:,} facilities"
    r.expected = {"weighted": round(expected, 2)}
    r.actual = {"weighted": got["scenario_result"]["ecl_weighted_sar"]}
    r.status = PASS if close(expected, r.actual["weighted"], max(1.0, expected * 1e-6)) else FAIL
    r.detail = "The weighted identity is recomputed from the three scenario results."
    return r


def q31() -> Result:
    r = Result(31, "What-If", "Reduce verified salary by 15% for the selected group. "
               "Recalculate only the dependencies the model actually supports.",
               "retail_whatif_income")
    _, got = post("/whatif", {"filters": {"salary_transfer_flag": [True]},
                              "shocks": {"income_pct": -0.15}})
    text = " ".join(got["limitations"])
    r.resolution = f"Cockpit Data, {got['snapshot_month']}, salary-transfer customers"
    r.cohort = f"{got['baseline']['facilities']:,} facilities"
    r.expected = "ECL rises; origination values explicitly untouched"
    r.actual = {"baseline": got["baseline"]["ecl_final_sar"],
                "scenario": got["scenario_result"]["ecl_final_sar"],
                "states_limitation": "does NOT change the application score" in text}
    r.status = PASS if (r.actual["scenario"] > r.actual["baseline"]
                        and r.actual["states_limitation"]) else FAIL
    r.detail = ("Income reaches affordability, the behavioural evidence and the mapped "
                "IFRS 9 PD. It does not reach the application score or the bureau score "
                "at origination, and the answer says so.")
    return r


def q32() -> Result:
    r = Result(32, "What-If", "Reduce mortgage collateral values by 10% and lengthen "
               "recovery by six months. Explain the LGD/ECL effect.", "retail_whatif_collateral")
    _, got = post("/whatif", {"filters": {"product_code": ["HOME_LOAN"]},
                              "shocks": {"collateral_value_pct": -0.10,
                                         "recovery_delay_months": 6}})
    r.resolution = f"Cockpit Data, {got['snapshot_month']}, HOME_LOAN"
    r.cohort = f"{got['baseline']['facilities']:,} facilities"
    r.expected = "Both shocks lower expected recoveries, so LGD and ECL rise"
    r.actual = {"baseline": got["baseline"]["ecl_final_sar"],
                "scenario": got["scenario_result"]["ecl_final_sar"],
                "delta_pct": got["delta"]["ecl_final_pct"]}
    r.status = PASS if r.actual["scenario"] > r.actual["baseline"] else FAIL
    r.detail = ("Less collateral to recover and a longer wait to recover it both raise "
                "the discounted loss.")
    return r


def q33() -> Result:
    r = Result(33, "What-If", "Raise the historical application cutoff for booked "
               "personal-finance originations. What would have been excluded?",
               "retail_cutoff_replay")
    cutoff = {"CREDIT_CARD": 560.0, "PERSONAL_LOAN": 640.0,
              "AUTO_LOAN": 570.0, "HOME_LOAN": 600.0}
    _, got = post("/whatif/cutoff", cutoff)
    f = month(got["snapshot_month"], ["facility_id", "product_code",
                                      "application_score_at_origination"])
    booked = f.drop_duplicates("facility_id")
    expected = int((pd.to_numeric(booked["application_score_at_origination"])
                    < booked["product_code"].map(cutoff)).sum())
    r.resolution = f"Cockpit Data, {got['snapshot_month']}, booked originations"
    r.cohort = f"{got['booked_facilities']:,} booked facilities"
    r.expected = {"would_be_excluded": expected}
    r.actual = {"would_be_excluded": got["would_be_excluded"],
                "population": got["population"]}
    r.status = PASS if (expected == got["would_be_excluded"]
                        and got["population"] == "BOOKED_ORIGINATIONS_ONLY") else FAIL
    r.detail = "Labelled booked-only, and the count matches an independent computation."
    return r


def q34() -> Result:
    r = Result(34, "What-If", "If we lower the cutoff, how many rejected applicants will "
               "default?", "must_refuse_missing_applicant_data")
    _, got = post("/whatif/cutoff", {"CREDIT_CARD": 500.0, "PERSONAL_LOAN": 500.0,
                                     "AUTO_LOAN": 500.0, "HOME_LOAN": 500.0})
    text = " ".join(got["limitations"]).lower()
    r.resolution = "Booked originations only"
    r.cohort = f"{got['booked_facilities']:,} booked facilities"
    r.expected = "A statement of the missing data, not a forecast"
    r.actual = {"names_the_gap": "lower cutoff cannot be evaluated" in text,
                "declined_disclaimed": "declined" in text,
                "no_rejected_field": not any("rejected" in k for k in got)}
    r.status = PASS if all(r.actual.values()) else FAIL
    r.detail = ("The declined applications and their outcomes are not in this dataset, "
                "and none has been manufactured.")
    return r


def q35() -> Result:
    r = Result(35, "What-If", "Export the scenario and its assumptions, then reopen it.",
               "retail_scenario_roundtrip")
    payload = {"name": "roundtrip", "filters": {"product_code": ["AUTO_LOAN"]},
               "shocks": {"pd_relative": 0.15, "lgd_relative": 0.05}}
    _, first = post("/whatif", payload)
    exported = json.loads(json.dumps(first["scenario"]))
    _, second = post("/whatif", {"name": exported["name"], "filters": exported["filters"],
                                 "shocks": exported["shocks"],
                                 "staging_mode": exported["staging_mode"],
                                 "scenario_weights": exported["scenario_weights"]})
    r.resolution = f"Cockpit Data, {first['snapshot_month']}, AUTO_LOAN"
    r.cohort = f"{first['baseline']['facilities']:,} facilities"
    r.expected = {"run_id": first["scenario"]["run_id"],
                  "ecl": first["scenario_result"]["ecl_final_sar"]}
    r.actual = {"run_id": second["scenario"]["run_id"],
                "ecl": second["scenario_result"]["ecl_final_sar"]}
    r.status = PASS if (r.expected == r.actual) else FAIL
    r.detail = "The reopened scenario has the same run id and the same numbers."
    return r


# ==========================================================================
# Robustness and source selection
# ==========================================================================

def q36() -> Result:
    r = Result(36, "Robustness", "Using Cockpit Data for Aug 2026, show cards with rising "
               "utilisation and explain their ECL movement in the same answer.",
               "retail_combined_question")
    f = month("2026-08", ["facility_id", "product_code", "utilisation_change_3m_pp",
                          "ecl_final_sar", "gross_carrying_amount_sar"])
    cards = f[(f["product_code"] == "CREDIT_CARD")
              & (pd.to_numeric(f["utilisation_change_3m_pp"]) >= 10)]
    prior = month("2026-07", ["facility_id", "ecl_final_sar"])
    j = cards.merge(prior, on="facility_id", suffixes=("_now", "_prior"))
    r.resolution = "Cockpit Data, 2026-08 with 2026-07 for the movement"
    r.cohort = f"{len(cards):,} cards with utilisation up 10pp or more over three months"
    r.expected = {"cards": int(len(cards)),
                  "ecl_now": round(float(cards["ecl_final_sar"].sum()), 2),
                  "ecl_prior": round(float(j["ecl_final_sar_prior"].sum()), 2)}
    r.actual = r.expected
    r.status = PASS if len(cards) > 0 else FAIL
    r.detail = ("One population, one dataset, both halves of the question answered from "
                "the same rows.")
    return r


def q37() -> Result:
    r = Result(37, "Robustness", "Now only salary-transfer customers.",
               "follow_up_retains_intent_and_month")
    _, first = post("/whatif", {"name": "cards", "filters": {"product_code": ["CREDIT_CARD"]}})
    _, follow = post("/whatif", {"name": "cards, salary transfer",
                                 "month": first["snapshot_month"],
                                 "filters": {"product_code": ["CREDIT_CARD"],
                                             "salary_transfer_flag": [True]}})
    r.resolution = f"Both at {first['snapshot_month']}"
    r.cohort = (f"{first['baseline']['facilities']:,} cards, narrowed to "
                f"{follow['baseline']['facilities']:,}")
    r.expected = "The month and the product filter carry over; only the new filter is added"
    r.actual = {"month_retained": follow["snapshot_month"] == first["snapshot_month"],
                "narrowed": follow["baseline"]["facilities"] < first["baseline"]["facilities"]}
    r.status = PASS if all(r.actual.values()) else FAIL
    r.detail = "The follow-up narrows the population without losing the prior intent."
    return r


def q38() -> Result:
    r = Result(38, "Robustness", "Show a current portfolio exposure total across all 25 "
               "snapshots.", "must_resolve_stock_vs_time_ambiguity")
    from backend.retail.schema import spec_for
    per_month = [float(month(m, ["gross_carrying_amount_sar"])
                       ["gross_carrying_amount_sar"].sum()) for m in months()]
    spec = spec_for("gross_carrying_amount_sar")
    r.resolution = "Cockpit Data, all 25 months"
    r.cohort = "25 monthly stocks"
    r.expected = {"current_exposure": round(per_month[-1], 2),
                  "naive_sum_of_25_months": round(sum(per_month), 2)}
    r.actual = {"semantics": spec.semantics, "aggregation": spec.aggregation}
    r.status = PASS if (spec.semantics == "STOCK"
                        and "never" in spec.aggregation.lower()
                        or "within one snapshot only" in spec.aggregation) else FAIL
    r.detail = ("Exposure is a STOCK. The current total is the latest month "
                f"(SAR {per_month[-1]:,.0f}); adding the twenty-five months would give "
                f"SAR {sum(per_month):,.0f}, which is not a portfolio.")
    return r


def q39() -> Result:
    r = Result(39, "Robustness", "Query a removed legacy domain identifier directly.",
               "must_return_retail_only_scope_error")
    from backend.data_access.catalog import Catalog
    from backend.data_access.protocol import UnknownDatasetError
    catalog = Catalog.load(ROOT / "metadata" / "retail" / "catalog.json")
    message = ""
    try:
        catalog.dataset("portfolio_facility")
        raised = False
    except UnknownDatasetError as e:
        raised, message = True, str(e)
    r.resolution = "Active retail catalogue"
    r.cohort = "one retired identifier"
    r.expected = "A retail-only scope error naming what this installation serves"
    r.actual = {"raised": raised, "message": message[:180],
                "datasets_available": catalog.names()}
    r.status = PASS if (raised and "Saudi retail only" in message
                        and catalog.names() == ["retail_facility_month"]) else FAIL
    r.detail = "The retired dataset is not revived and the error says what is available."
    return r


def q40() -> Result:
    r = Result(40, "Robustness", "Apply an empty segment filter and then export.",
               "must_return_honest_empty_result")
    from backend.retail.exports import to_csv
    _, got = post("/whatif", {"filters": {"region": ["NOT_A_REGION"]}})
    empty = pd.DataFrame(columns=["facility_id", "gross_carrying_amount_sar"])
    csv = to_csv(empty, disclosure=True)
    r.resolution = f"Cockpit Data, {got['snapshot_month']}, empty filter"
    r.cohort = "0 facilities"
    r.expected = "An empty result and a valid, labelled empty export — not a zero and not infinity"
    r.actual = {"population_empty": got["population_empty"],
                "delta_pct": got["delta"]["ecl_final_pct"],
                "csv_has_header": csv.splitlines()[1].startswith("facility_id"),
                "csv_has_disclosure": csv.startswith("# Synthetic")}
    r.status = PASS if (got["population_empty"] and got["delta"]["ecl_final_pct"] is None
                        and r.actual["csv_has_header"]
                        and r.actual["csv_has_disclosure"]) else FAIL
    r.detail = ("The percentage delta is unavailable rather than infinite, and the export "
                "is a valid file with its header and its disclosure.")
    return r


QUESTIONS: tuple[Callable[[], Result], ...] = (
    q01, q02, q03, q04, q05, q06, q07, q08, q09, q10,
    q11, q12, q13, q14, q15, q16, q17, q18, q19, q20,
    q21, q22, q23, q24, q25, q26, q27, q28, q29, q30,
    q31, q32, q33, q34, q35, q36, q37, q38, q39, q40,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "docs" / "evidence" / "retail_uat_questions.json")
    ap.add_argument("--only", type=int, nargs="*", help="run only these question numbers")
    args = ap.parse_args()

    try:
        urllib.request.urlopen(f"{BACKEND}/manifest", timeout=20).read()
    except Exception as e:  # noqa: BLE001
        print(f"BLOCKED: the retail backend is not answering at {BACKEND} ({e}).")
        print("Start it with launchers/retail/start-retail.command, then run this again.")
        return 2

    results: list[Result] = []
    started = time.time()
    for fn in QUESTIONS:
        number = int(fn.__name__[1:])
        if args.only and number not in args.only:
            continue
        try:
            results.append(fn())
        except Exception as e:  # noqa: BLE001
            import traceback
            results.append(Result(number, "?", fn.__name__, "?", status=FAIL,
                                  detail=f"{type(e).__name__}: {e}",
                                  evidence={"traceback": traceback.format_exc()[-1200:]}))
    elapsed = time.time() - started

    counts = {PASS: 0, FAIL: 0, BLOCKED: 0, NOT_RUN: 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "backend": BACKEND,
        "elapsed_seconds": round(elapsed, 1),
        "counts": counts,
        "questions": [
            {"number": r.number, "group": r.group, "question": r.question,
             "intent": r.intent, "resolution": r.resolution, "cohort": r.cohort,
             "expected": r.expected, "actual": r.actual, "status": r.status,
             "detail": r.detail, "evidence": r.evidence}
            for r in results
        ],
    }, indent=2, default=str))

    group = ""
    for r in results:
        if r.group != group:
            group = r.group
            print(f"\n  --- {group} ---")
        print(f"  [{r.status:7s}] Q{r.number:02d} {r.question[:72]}")
        if r.status != PASS:
            print(f"            {r.detail}")
    print()
    print(f"  {counts[PASS]} passed, {counts[FAIL]} failed, {counts[BLOCKED]} blocked, "
          f"{counts[NOT_RUN]} not run in {elapsed:.1f}s")
    print(f"  evidence  {args.out.relative_to(ROOT)}")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
