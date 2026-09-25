"""The Retail candidate book: the same construction order, a different book.

`v4-whatif-retail-20m-s1`. Four accepted relations plus the eight candidate
ones, twenty months, macro first and measurement last — the reasoning is in
`corporate.py`'s header and applies unchanged.

What is different here, and why:

**Two scorecards, kept apart.** The behavioural score lives on the account
(it is in the accepted schema) and moves month to month with conditions. The
application score lives on `whatif_retail_profile`, is taken once at
origination and never moves again. Section 8 forbids substituting one for the
other, and a book where the two were the same number would make that rule
impossible to test. Their calibrations are separate rows of
`whatif_retail_score_map`, with separate support ranges and separate validity
windows.

**Employer sector is a real dimension.** Generated independently of product,
because section 3.3 says product is not a substitute for employer sector, and
a book where every Credit Card holder worked in the same industry would let a
sector question be answered by a product filter without anyone noticing.

**No CCF.** Retail exposure is the balance; the accepted book has no
conversion to recover and this one does not invent one. `whatif_retail_ifrs9`
therefore carries no CCF columns at all, rather than a column of zeros that
would read as "the conversion is nil".
"""

from __future__ import annotations

import math
import random
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.generate import month_range, months_between
from backend.cockpit_v4.generate.retail import BANDS, PRODUCTS, SUB_PRODUCTS
from backend.cockpit_v4.generate.totals import exact_total, whole_total
from backend.cockpit_v4.scenario import reference_ecl as ref
from backend.cockpit_v4.scenario.candidate_schema import ORIGIN, SCENARIOS
from backend.cockpit_v4.scenario.generate import (
    RETAIL_CUSTOMERS,
    RETAIL_SEED,
    signed,
    stable,
    unit_interval,
)
from backend.cockpit_v4.scenario.generate import macro as mv

SEGMENTS: tuple[str, ...] = ("Mass", "Affluent", "Private", "Payroll")
REGIONS: tuple[str, ...] = ("Riyadh", "Makkah", "Eastern Province", "Madinah",
                            "Qassim", "Asir", "Tabuk", "Hail")
EMPLOYMENT: tuple[str, ...] = ("Salaried-Government", "Salaried-Private",
                               "Self-employed", "Non-salaried")
CHANNELS: tuple[str, ...] = ("Branch", "Digital", "Partner")

#: The employer sector dimension the accepted Retail book does not carry.
#: Generated from the customer id alone -- independent of product, segment
#: and region -- so a sector question cannot be answered by a product filter.
EMPLOYER_SECTORS: tuple[str, ...] = (
    "Public Administration", "Healthcare", "Education", "Construction",
    "Retail Trade", "Oil and Gas", "Transport and Logistics",
    "Financial Services", "Hospitality", "Manufacturing")

#: Which broader group each employer sector rolls into. A hierarchy, because
#: section 8 asks sector discovery to return one.
SECTOR_GROUP: dict[str, str] = {
    "Public Administration": "Public Sector", "Healthcare": "Public Sector",
    "Education": "Public Sector", "Construction": "Cyclical",
    "Retail Trade": "Cyclical", "Hospitality": "Cyclical",
    "Transport and Logistics": "Cyclical", "Oil and Gas": "Resources",
    "Manufacturing": "Resources", "Financial Services": "Services"}

#: How hard each employer sector's PD responds to the cycle. Public-sector
#: employment barely moves; construction and hospitality move a lot. This is
#: the relationship a Retail sensitivity fit is trying to recover.
SECTOR_BETA: dict[str, float] = {
    "Public Administration": 0.10, "Healthcare": 0.16, "Education": 0.14,
    "Construction": 0.88, "Retail Trade": 0.61, "Oil and Gas": 0.44,
    "Transport and Logistics": 0.55, "Financial Services": 0.33,
    "Hospitality": 0.80, "Manufacturing": 0.49}

#: How each product's population responds on top of the employer effect.
PRODUCT_BETA: dict[str, float] = {
    "Mortgage": 0.42, "Personal Finance": 0.78, "Auto Finance": 0.58,
    "Credit Card": 0.95, "Buy Now Pay Later": 1.05}

PRODUCT_SPEC = {p[0]: {"secured": p[1], "share": p[2], "limit": p[3],
                       "lgd": p[4]} for p in PRODUCTS}
NEW_PRODUCT = "Buy Now Pay Later"
NEW_PRODUCT_FROM = "2026-03"

BEHAVIOURAL_VERSION = "whatif-behaviour-scorecard-3.1"
APPLICATION_VERSION = "whatif-application-scorecard-2.0"

#: Score scales. The two scorecards are on DIFFERENT scales on purpose: an
#: application score of 700 and a behavioural score of 700 are not the same
#: statement, and a book where they shared a scale would make substituting
#: one for the other look harmless.
BEHAVIOUR_RANGE = (300, 900)
APPLICATION_RANGE = (200, 800)

BASE_LOGIT = -3.75
CYCLE_TO_LOGIT = 0.70
SCORE_TO_LOGIT = -3.10

BASE_LGD_SHIFT = 0.0
LGD_CYCLE = 0.070

#: Overlays, held on the unsecured products a retail committee would hold
#: them on and fixed under a parameter stress.
OVERLAY_PRODUCTS: frozenset[str] = frozenset({"Credit Card", NEW_PRODUCT})
OVERLAY_RATE = 0.09

MODEL_VERSION = ref.VERSION


def _logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def band_of(score: float) -> str:
    """The published behavioural band. The accepted book's own boundaries."""
    if score >= 780:
        return "A"
    if score >= 700:
        return "B"
    if score >= 620:
        return "C"
    if score >= 540:
        return "D"
    return "E"


def customers(rng: random.Random) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index in range(RETAIL_CUSTOMERS):
        customer_id = f"WRC{index + 1:06d}"
        sector = EMPLOYER_SECTORS[stable(customer_id + "|sector",
                                         len(EMPLOYER_SECTORS))]
        out.append({
            "customer_id": customer_id,
            "customer_segment": SEGMENTS[index % len(SEGMENTS)],
            "employment_type": EMPLOYMENT[stable(customer_id + "|emp",
                                                 len(EMPLOYMENT))],
            "employer_sector": sector,
            "region": REGIONS[stable(customer_id + "|region", len(REGIONS))],
            "quality": rng.uniform(0.0, 1.0),
            "tenure_months": 6 + stable(customer_id + "|tenure", 180),
            # Taken once, at origination, and never moved again.
            "application_score": APPLICATION_RANGE[0] + stable(
                customer_id + "|app",
                APPLICATION_RANGE[1] - APPLICATION_RANGE[0]),
            "eir": round(0.055 + 0.085 * rng.random(), 4),
        })
    return out


def accounts_of(people: list[dict[str, Any]],
                rng: random.Random) -> list[dict[str, Any]]:
    names = [p[0] for p in PRODUCTS if p[0] != NEW_PRODUCT]
    weights = [p[2] for p in PRODUCTS if p[0] != NEW_PRODUCT]
    out: list[dict[str, Any]] = []
    for person in people:
        count = 1 + stable(person["customer_id"] + "|n", 2)
        for slot in range(count):
            account_id = f"{person['customer_id']}A{slot + 1}"
            # A tenth of customers get the product that did not exist at the
            # start of the window, so a "which product is new" question has
            # an answer.
            new_one = stable(account_id + "|new", 10) == 0 and slot == 0
            product = (NEW_PRODUCT if new_one
                       else rng.choices(names, weights=weights, k=1)[0])
            subs = SUB_PRODUCTS[product]
            spec = PRODUCT_SPEC[product]
            out.append({
                "account_id": account_id,
                "customer_id": person["customer_id"],
                "product": product,
                "sub_product": subs[stable(account_id + "|sub",
                                           len(subs))][0],
                "secured_flag": spec["secured"],
                "base_limit": round(spec["limit"]
                                    * (0.4 + 1.4 * unit_interval(
                                        account_id + "|limit")), 6),
                "base_lgd": spec["lgd"],
                "base_utilisation": 0.20 + 0.70 * unit_interval(
                    account_id + "|util"),
                "channel": CHANNELS[stable(account_id + "|ch",
                                           len(CHANNELS))],
                "maturity_months": 12 + stable(account_id + "|mat", 49),
                "new_product": new_one,
            })
    return out


def build(release_id: str = "", tenant_id: str = lake.DEFAULT_TENANT,
          artifacts: dict[str, Any] | None = None) -> lake.Build:
    """The Retail candidate release, in memory."""
    import pandas as pd

    from backend.cockpit_v4.scenario import candidate_schema as cs
    from backend.cockpit_v4.scenario.generate.corporate import (
        pending_artifact_rows,
    )

    release_id = release_id or cs.RELEASES[dom.RETAIL]
    months = month_range()
    rng = random.Random(RETAIL_SEED)
    people = customers(rng)
    accounts = accounts_of(people, rng)
    by_customer = {p["customer_id"]: p for p in people}

    drivers = {s: mv.driver_index(dom.RETAIL, months, s)
               for s, _n, _w in SCENARIOS}
    property_index = {s: mv.series(dom.RETAIL, "MEV09", months, s)
                      for s, _n, _w in SCENARIOS}
    weights = {s: w for s, _n, w in SCENARIOS}
    profile = ref.profile("retail")

    gov = {"tenant_id": tenant_id, "dataset_release_id": release_id,
           "domain_id": dom.RETAIL, "reporting_currency": "SAR"}
    stamp = dict(gov, origin=ORIGIN)

    customer_rows: list[dict[str, Any]] = []
    account_rows: list[dict[str, Any]] = []
    behaviour_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    ifrs9_rows: list[dict[str, Any]] = []
    term_rows: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []

    previous_score: dict[str, float] = {}

    for index, month in enumerate(months):
        previous_month = months[max(index - 1, 0)]
        driver = {s: drivers[s][previous_month] for s in drivers}
        prop = {s: (property_index[s][previous_month] - 112.0) / 9.0
                for s in property_index}

        month_start = len(account_rows)
        month_scores: dict[str, float] = {}
        for person in people:
            beta = SECTOR_BETA[person["employer_sector"]]
            # The behavioural score moves with conditions and with the
            # customer's own standing. It is a CURRENT measure -- which is
            # the whole reason it is not the application score.
            score = _clamp(
                760.0
                - 210.0 * person["quality"]
                - 46.0 * beta * driver["baseline"]
                + signed(f"{person['customer_id']}|{month}|score") * 22.0,
                float(BEHAVIOUR_RANGE[0]), float(BEHAVIOUR_RANGE[1]))
            month_scores[person["customer_id"]] = round(score, 2)

        for account in accounts:
            person = by_customer[account["customer_id"]]
            if account["new_product"] and month < NEW_PRODUCT_FROM:
                continue
            origination = (NEW_PRODUCT_FROM if account["new_product"]
                           else months[0])
            score = month_scores[person["customer_id"]]
            standardised = (score - 600.0) / 150.0
            beta = (SECTOR_BETA[person["employer_sector"]]
                    * PRODUCT_BETA[account["product"]])

            per_scenario: dict[str, dict[str, float]] = {}
            for scenario_id, _name, _weight in SCENARIOS:
                logit = (BASE_LOGIT
                         + SCORE_TO_LOGIT * standardised
                         + CYCLE_TO_LOGIT * beta * driver[scenario_id]
                         + signed(f"{account['account_id']}|{month}|pd")
                         * 0.20)
                pd_12m = _clamp(_logistic(logit), 0.0004, 0.70)
                lgd = _clamp(
                    account["base_lgd"]
                    + LGD_CYCLE * (0.4 * beta) * prop[scenario_id]
                    - (0.17 if account["secured_flag"] else 0.0)
                    + signed(f"{account['account_id']}|{month}|lgd") * 0.04,
                    0.05, 0.92)
                per_scenario[scenario_id] = {"pd": pd_12m, "lgd": lgd}

            base = per_scenario["baseline"]
            utilisation = _clamp(
                account["base_utilisation"] + 0.09 * driver["baseline"],
                0.02, 1.0)
            limit = account["base_limit"]
            balance = round(limit * utilisation, 6)
            ead = balance

            pressure = (base["pd"] * 7.0
                        + 0.34 * max(driver["baseline"], 0.0)
                        + unit_interval(
                            f"{account['account_id']}|{month}|dpd") * 0.45)
            if pressure > 1.50:
                dpd = 90 + stable(f"{account['account_id']}|{month}|d3", 180)
            elif pressure > 1.02:
                dpd = 31 + stable(f"{account['account_id']}|{month}|d2", 58)
            elif pressure > 0.76:
                dpd = 1 + stable(f"{account['account_id']}|{month}|d1", 29)
            else:
                dpd = 0
            defaulted = dpd >= 90
            sicr = dpd >= 30 or base["pd"] > 0.12
            stage = 3 if defaulted else (2 if sicr else 1)

            buckets = {
                s: ref.term_structure(
                    pd_12m=per_scenario[s]["pd"], lgd=per_scenario[s]["lgd"],
                    ead=ead, eir=person["eir"],
                    remaining_maturity_months=float(
                        account["maturity_months"]),
                    defaulted=defaulted, **profile)
                for s, _n, _w in SCENARIOS}
            overlay = round(
                OVERLAY_RATE * ead * 0.01
                if account["product"] in OVERLAY_PRODUCTS else 0.0, 6)
            measured = ref.measure(per_scenario=buckets, weights=weights,
                                   stage=stage, overlay=overlay)
            ecl_12m = round(measured.ecl_12m + overlay, 6)
            ecl_life = round(measured.ecl_lifetime + overlay, 6)
            ecl = ecl_12m if stage == 1 else ecl_life

            write_off = round(ead * 0.30, 6) if dpd > 180 else 0.0
            recovery = round(write_off * (0.34 if account["secured_flag"]
                                          else 0.12), 6)
            if write_off > 0:
                # The write-off floor the accepted Retail book also carries:
                # once an amount is written off, the loss is at least what
                # was lost net of recovery, whatever the model says.
                ecl = max(ecl, round(write_off - recovery, 6))
                ecl_life = max(ecl_life, ecl)
                if stage == 1:
                    ecl_12m = ecl

            previous = previous_score.get(person["customer_id"], score)
            previous_score[person["customer_id"]] = score

            account_rows.append({
                **gov,
                "account_id": account["account_id"],
                "customer_id": person["customer_id"],
                "reporting_month": month,
                "product": account["product"],
                "sub_product": account["sub_product"],
                "secured_flag": account["secured_flag"],
                "origination_month": origination,
                "origination_channel": account["channel"],
                "vintage_year": int(origination[:4]),
                "months_on_book": int(months_between(origination, month)) + 1,
                "customer_segment": person["customer_segment"],
                "employment_type": person["employment_type"],
                "region": person["region"],
                "limit_sar_mn": limit,
                "balance_sar_mn": balance,
                "ead_sar_mn": ead,
                "utilisation_pct": round(utilisation * 100, 4),
                "stage": stage,
                "sicr_flag": int(sicr),
                "default_flag": int(defaulted),
                "dpd_days": int(dpd),
                "delinquency_bucket": (
                    "Current" if dpd == 0 else "1-30" if dpd <= 30
                    else "31-60" if dpd <= 60 else "61-90" if dpd <= 90
                    else "90+"),
                "delinquency_bucket_fine": (
                    "Current" if dpd == 0 else "1-15" if dpd <= 15
                    else "16-30" if dpd <= 30 else "31-60" if dpd <= 60
                    else "61-90" if dpd <= 90 else "91-180" if dpd <= 180
                    else "180+"),
                "pd_pit_12m": round(1.0 if defaulted else base["pd"], 6),
                "pd_lifetime": round(
                    1.0 if defaulted
                    else _clamp(base["pd"] * 2.4, base["pd"], 0.98), 6),
                "lgd_pct": round(base["lgd"] * 100, 4),
                "ecl_12m_sar_mn": ecl_12m,
                "ecl_lifetime_sar_mn": ecl_life,
                "ecl_sar_mn": ecl,
                "write_off_sar_mn": write_off,
                "recovery_sar_mn": recovery,
                "cure_flag": int(stage == 1 and dpd == 0 and previous < score),
                "behaviour_score": score,
                "score_band": band_of(score),
            })

            behaviour_rows.append({
                **gov,
                "account_id": account["account_id"],
                "customer_id": person["customer_id"],
                "reporting_month": month,
                "product": account["product"],
                "sub_product": account["sub_product"],
                "utilisation_pct": round(utilisation * 100, 4),
                "utilisation_change_pp": round(
                    9.0 * driver["baseline"], 4),
                "payment_ratio_pct": round(
                    _clamp(42.0 - 16.0 * driver["baseline"]
                           - 18.0 * person["quality"], 1.0, 100.0), 4),
                "missed_payments_12m": int(min(dpd // 30, 6)),
                "delinquency_streak_months": int(min(dpd // 30, 6)),
                "balance_growth_pct": round(6.0 * driver["baseline"], 4),
                "cash_advance_ratio_pct": round(
                    _clamp(7.0 + 9.0 * driver["baseline"], 0.0, 60.0), 4),
                "overlimit_flag": int(utilisation > 0.97),
                "inflow_change_pct": round(-7.0 * driver["baseline"], 4),
                "bureau_inquiries_6m": int(stable(
                    f"{account['account_id']}|{month}|inq", 6)),
                "repayment_behaviour_score": round(
                    _clamp(score - 40.0 + 25.0 * (1 - person["quality"]),
                           300.0, 900.0), 2),
            })

            if account["secured_flag"]:
                value = round(ead * (1.25 + 0.55 * unit_interval(
                    account["account_id"] + "|coll")), 6)
                collateral_rows.append({
                    **gov,
                    "account_id": account["account_id"],
                    "customer_id": person["customer_id"],
                    "reporting_month": month,
                    "product": account["product"],
                    "collateral_type": (
                        "Residential Property"
                        if account["product"] == "Mortgage" else "Vehicle"),
                    "collateral_value_sar_mn": value,
                    "ltv_pct": round(ead / max(value, 0.000001) * 100, 4),
                    "collateral_coverage_pct": round(
                        value / max(ead, 0.000001) * 100, 4),
                    "valuation_age_months": int(stable(
                        f"{account['account_id']}|{month}|age", 24)),
                })

            denominator = max(ead, 0.000001)
            ifrs9_rows.append({
                **stamp,
                "account_id": account["account_id"],
                "reporting_month": month,
                "ecl_modelled_sar_mn": round(measured.ecl_recognised, 6),
                "ecl_overlay_sar_mn": overlay,
                "overlay_reason": (
                    "Unsecured product overlay held by the retail credit "
                    "committee" if overlay else ""),
                "ecl_denominator": "ead_sar_mn",
                "ecl_rate": round(min(ecl / denominator, 1.0), 8),
                "effective_interest_rate": person["eir"],
                "remaining_maturity_months": float(
                    account["maturity_months"]),
                "lifetime_horizon_months": float(sum(ref.RETAIL_BUCKETS)),
                "ifrs9_model_version": MODEL_VERSION,
            })

            for scenario_id, scenario_name, weight in SCENARIOS:
                for bucket in buckets[scenario_id]:
                    term_rows.append({
                        **stamp,
                        "account_id": account["account_id"],
                        "reporting_month": month,
                        "scenario_id": scenario_id,
                        "scenario_name": scenario_name,
                        "scenario_weight": weight,
                        "horizon_index": bucket.index,
                        "horizon_end_period": months[min(
                            index + int(bucket.end_month), len(months) - 1)],
                        "horizon_months": round(bucket.months, 4),
                        "pd_marginal": round(bucket.pd_marginal, 8),
                        "pd_cumulative": round(bucket.pd_cumulative, 8),
                        "survival": round(bucket.survival, 8),
                        "lgd": round(bucket.lgd, 6),
                        "ead_sar_mn": round(bucket.ead, 6),
                        "discount_factor": round(bucket.discount_factor, 8),
                        "expected_shortfall_sar_mn": round(
                            bucket.expected_shortfall, 8),
                    })

        # Indexed as the month's rows were appended, rather than filtered out
        # of the whole book per customer. The filter version was quadratic in
        # the account count and took the Retail build from under a minute to
        # longer than anyone would wait for it.
        this_month: dict[str, list[dict[str, Any]]] = {}
        for row in account_rows[month_start:]:
            this_month.setdefault(row["customer_id"], []).append(row)
        for person in people:
            own = this_month.get(person["customer_id"])
            if not own:
                continue
            score = month_scores[person["customer_id"]]
            prior = (month_scores[person["customer_id"]] if index == 0
                     else _clamp(score + signed(
                         f"{person['customer_id']}|{previous_month}|d") * 9.0,
                         float(BEHAVIOUR_RANGE[0]),
                         float(BEHAVIOUR_RANGE[1])))
            customer_rows.append({
                **gov,
                "customer_id": person["customer_id"],
                "reporting_month": month,
                "customer_segment": person["customer_segment"],
                "employment_type": person["employment_type"],
                "region": person["region"],
                "tenure_months": int(person["tenure_months"] + index),
                "accounts_held": len(own),
                "behaviour_score": score,
                "behaviour_score_previous": round(prior, 2),
                "behaviour_score_change": round(score - prior, 2),
                "score_band": band_of(score),
                "score_band_previous": band_of(prior),
                "score_migration": (
                    "Improved" if band_of(score) < band_of(prior)
                    else "Deteriorated" if band_of(score) > band_of(prior)
                    else "Stable"),
                "total_ead_sar_mn": round(
                    exact_total(r["ead_sar_mn"] for r in own), 6),
                "total_ecl_sar_mn": round(
                    exact_total(r["ecl_sar_mn"] for r in own), 6),
                "worst_stage": max((r["stage"] for r in own), default=1),
                "worst_dpd_days": max((r["dpd_days"] for r in own),
                                      default=0),
            })
            profile_rows.append({
                **stamp,
                "customer_id": person["customer_id"],
                "reporting_month": month,
                "employer_sector": person["employer_sector"],
                "employer_sector_group": SECTOR_GROUP[
                    person["employer_sector"]],
                "application_score": int(person["application_score"]),
                "application_score_version": APPLICATION_VERSION,
                "application_scored_at": months[0],
                "behaviour_score_version": BEHAVIOURAL_VERSION,
            })

    latest = months[-1]
    macro_rows = [
        {**stamp, "factor_id": r["factor_id"],
         "reporting_month": r["period"], "scenario_id": r["scenario_id"],
         "country_or_region": r["country_or_region"], "value": r["value"],
         "native_unit": r["native_unit"],
         "native_frequency": r["native_frequency"],
         "aggregation_rule": r["aggregation_rule"],
         "observation_status": r["observation_status"],
         "forecast_vintage": r["forecast_vintage"],
         "published_at": r["published_at"], "available_at": r["available_at"]}
        for r in mv.panel(dom.RETAIL, months)]
    registry_rows = [{**stamp, "reporting_month": latest, **r}
                     for r in mv.registry(dom.RETAIL)]
    score_rows = _score_map(stamp, months)

    frames = {
        "retail_customer_month": pd.DataFrame(customer_rows),
        "retail_account_month": pd.DataFrame(account_rows),
        "retail_behaviour_month": pd.DataFrame(behaviour_rows),
        "retail_collateral_month": pd.DataFrame(collateral_rows),
        "whatif_retail_macro_month": pd.DataFrame(macro_rows),
        "whatif_retail_mev_registry": pd.DataFrame(registry_rows),
        "whatif_retail_score_map": pd.DataFrame(score_rows),
        "whatif_retail_term_structure": pd.DataFrame(term_rows),
        "whatif_retail_ifrs9": pd.DataFrame(ifrs9_rows),
        "whatif_retail_profile": pd.DataFrame(profile_rows),
    }
    supplied = artifacts or {}
    sensitivity = pending_artifact_rows(stamp, latest, sensitivity=True)
    for row in sensitivity:
        row["reporting_month"] = row.pop("reporting_quarter")
    metric = pending_artifact_rows(stamp, latest, sensitivity=False)
    for row in metric:
        row["reporting_month"] = row.pop("reporting_quarter")
    frames["whatif_retail_sensitivity"] = supplied.get(
        "whatif_retail_sensitivity", pd.DataFrame(sensitivity))
    frames["whatif_retail_model_metric"] = supplied.get(
        "whatif_retail_model_metric", pd.DataFrame(metric))

    present, absent = mv.factor_count(dom.RETAIL)
    return lake.Build(
        domain_id=dom.RETAIL, release_id=release_id, periods=months,
        frames=frames,
        counts={"customers": len(people), "accounts": len(accounts),
                "products": len(PRODUCTS),
                "sub_products": whole_total(
                    len(v) for v in SUB_PRODUCTS.values()),
                "employment_types": len(EMPLOYMENT),
                "employer_sectors": len(EMPLOYER_SECTORS),
                "regions": len(REGIONS),
                "macro_factors_present": present,
                "macro_factors_absent": absent,
                "economic_scenarios": len(SCENARIOS)},
        notes={
            "origin": ORIGIN,
            "not_a_bank_engine": (
                "ECL here is measured by reference_ecl.py, a calculator "
                "written for this demonstration. It is not a bank engine and "
                "its output is not an accounting figure."),
            "macro_is_generated": (
                "The macroeconomic panel is generated, not observed. It is "
                "not economic history."),
            "score_bands": list(BANDS),
            "behavioural_scorecard": BEHAVIOURAL_VERSION,
            "application_scorecard": APPLICATION_VERSION,
            "scorecards_are_distinct": (
                "The behavioural score is current and moves monthly; the "
                "application score is taken once at origination. They are on "
                "different scales and neither substitutes for the other."),
            "employer_sectors": list(EMPLOYER_SECTORS),
            "employer_sector_betas": dict(SECTOR_BETA),
            "product_betas": dict(PRODUCT_BETA),
            "true_cycle_coefficient": CYCLE_TO_LOGIT,
            "ecl_denominator": "ead_sar_mn",
            "reference_calculator": MODEL_VERSION,
            "product_launched_in_window": {NEW_PRODUCT: NEW_PRODUCT_FROM},
            "scenario_weights": {s: w for s, _n, w in SCENARIOS},
            "total_ecl_sar_mn": round(exact_total(
                r["ecl_sar_mn"] for r in account_rows), 6),
        })


def _score_map(stamp: dict[str, Any],
               months: tuple[str, ...]) -> list[dict[str, Any]]:
    """Both calibrations, as separate rows on separate scales.

    The behavioural calibration covers 300-900 and is published per product.
    The application calibration covers 200-800 and is published once. They
    are never merged, and `score_type` is the column that keeps them apart.
    """
    latest = months[-1]
    out: list[dict[str, Any]] = []
    for low in range(BEHAVIOUR_RANGE[0], BEHAVIOUR_RANGE[1], 60):
        high = min(low + 59, BEHAVIOUR_RANGE[1])
        midpoint = (low + high) / 2.0
        pd_12m = _clamp(_logistic(BASE_LOGIT + SCORE_TO_LOGIT
                                  * ((midpoint - 600.0) / 150.0)),
                        0.0004, 0.70)
        for product in [p[0] for p in PRODUCTS]:
            out.append({
                **stamp, "score_type": "BEHAVIOURAL",
                "scorecard_version": BEHAVIOURAL_VERSION,
                "product": product, "band_low": low,
                "reporting_month": latest, "band_high": high,
                "band_label": band_of(midpoint),
                "pd_12m": round(
                    _clamp(pd_12m * PRODUCT_BETA[product], 0.0002, 0.85), 6),
                "horizon_months": 12.0,
                "direction": "HIGHER_IS_SAFER",
                "support_low": BEHAVIOUR_RANGE[0],
                "support_high": BEHAVIOUR_RANGE[1],
                "effective_from": months[0], "effective_to": "",
                "source": ("Fitted on this release's behavioural score and "
                           "twelve-month default outcome."),
            })
    for low in range(APPLICATION_RANGE[0], APPLICATION_RANGE[1], 60):
        high = min(low + 59, APPLICATION_RANGE[1])
        midpoint = (low + high) / 2.0
        out.append({
            **stamp, "score_type": "APPLICATION",
            "scorecard_version": APPLICATION_VERSION,
            "product": "ALL", "band_low": low,
            "reporting_month": latest, "band_high": high,
            "band_label": f"App {low}-{high}",
            "pd_12m": round(_clamp(_logistic(
                BASE_LOGIT + 0.6 + SCORE_TO_LOGIT
                * ((midpoint - 500.0) / 130.0)), 0.0004, 0.80), 6),
            "horizon_months": 12.0,
            "direction": "HIGHER_IS_SAFER",
            "support_low": APPLICATION_RANGE[0],
            "support_high": APPLICATION_RANGE[1],
            "effective_from": months[0], "effective_to": "",
            "source": ("Fitted at origination on this release's application "
                       "score. NOT a current-score calibration."),
        })
    return out


__all__ = ["APPLICATION_RANGE", "APPLICATION_VERSION", "BEHAVIOURAL_VERSION",
           "BEHAVIOUR_RANGE", "CHANNELS", "CYCLE_TO_LOGIT", "EMPLOYER_SECTORS",
           "EMPLOYMENT", "NEW_PRODUCT", "NEW_PRODUCT_FROM", "PRODUCT_BETA",
           "REGIONS", "SECTOR_BETA", "SECTOR_GROUP", "SEGMENTS",
           "accounts_of", "band_of", "build", "customers"]
