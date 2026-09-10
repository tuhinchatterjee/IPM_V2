"""
The synthetic Saudi retail portfolio generator.

This is a longitudinal SIMULATION, not twenty-five spreadsheets of random
numbers. Customers persist. A facility originated in March 2025 has the same
origination amount, the same application score and the same bureau score at
origination in every later month, its months on book increase by one each time,
and its balance moves only because a payment, a drawdown, an accrual or a
write-off moved it.

That matters for the product's central claim. A behavioural score can only be
shown to *predict* default if the thing it is built from and the thing it
predicts come out of the same underlying state. So every customer carries a
latent stress process driven by a common cycle; salary interruption, rising
utilisation, missed payments, bureau deterioration and eventual default are all
noisy readings of that one state. The signal is genuinely there, it is nobody's
hand-placed answer, and it is imperfect enough that a model finding it has found
something rather than been told it.

Everything written here is SYNTHETIC. No real customer, employer, bureau feed or
bank policy is described.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from backend.retail import ecl as ecl_mod
from backend.retail.config import RetailDemoConfig
from backend.retail.models_registry import (
    APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS,
    application_columns, behavioural_columns,
)
from backend.retail.policy import (
    AFFORDABILITY_POLICY, CUTOFF_POLICY, DEFAULT_DEFINITION_ID, RECOVERY_POLICY,
    STAGING_POLICY,
)
from backend.retail import taxonomy as tax

logger = logging.getLogger(__name__)

HISTORY_MONTHS = 12  # ring-buffer depth for rolling features

# --------------------------------------------------------------------------
# Delinquency calibration.
#
# These constants set how often a synthetic customer misses a payment and how
# often they catch up, and therefore what the book's 12-month default rate
# comes out at. They are tuned to land a demonstration book in the low single
# digits, which is where a Saudi retail portfolio of this mix plausibly sits.
# They are a DEMO CALIBRATION CHOICE, not an observed default rate for ANB or
# for the Saudi market.
# --------------------------------------------------------------------------
MISS_INTERCEPT: dict[str, float] = {
    "CREDIT_CARD": -4.15, "PERSONAL_LOAN": -4.45, "AUTO_LOAN": -4.75, "HOME_LOAN": -5.15,
}
MISS_STRESS_BETA = 0.74
MISS_DBR_BETA = 1.05
MISS_SALARY_BETA = 0.70
CATCH_UP_INTERCEPT = 0.95
CATCH_UP_STRESS_BETA = 0.80
UTP_INTERCEPT = -8.6
WRITE_OFF_AFTER_DEFAULT_MONTHS = 15
#: The column the canonical dataset is partitioned by, and the `period_field`
#: its catalogue entry declares. Both must agree or a month can be listed and
#: then not opened.
PERIOD_FIELD = "reporting_month"
BUREAU_SCALE_ID = "SYNTH_BUREAU_PROXY_300_900"
BUREAU_SOURCE_LABEL = "Synthetic bureau proxy"


def _months_between(a: date, b: date) -> int:
    return (b.year * 12 + b.month) - (a.year * 12 + a.month)


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    y, m = idx // 12, idx % 12 + 1
    if m == 12:
        return date(y, 12, 31)
    return date.fromordinal(date(y, m + 1, 1).toordinal() - 1)


# ==========================================================================
# Customers
# ==========================================================================

@dataclass
class Customers:
    n: int
    customer_id: np.ndarray
    region: np.ndarray
    city: np.ndarray
    branch_id: np.ndarray
    residency: np.ndarray
    age_band: np.ndarray
    dependants_band: np.ndarray
    employment_status: np.ndarray
    employer_id: np.ndarray
    employer_sector: np.ndarray
    employment_tenure_months_at_start: np.ndarray
    salary_transfer: np.ndarray
    base_salary_sar: np.ndarray
    other_income_sar: np.ndarray
    household_expenses_sar: np.ndarray
    external_obligations_sar: np.ndarray
    segment: np.ndarray
    relationship_start_month_index: np.ndarray
    latent_quality: np.ndarray      # persistent credit quality, higher = safer
    cycle_beta: np.ndarray          # sensitivity to the common cycle
    salary_shock_group: np.ndarray  # story: employer-linked salary disruption


def _build_customers(rng: np.random.Generator, cfg: RetailDemoConfig, n: int) -> Customers:
    regions = np.array(list(tax.REGION_WEIGHTS))
    rweights = np.array([tax.REGION_WEIGHTS[r] for r in regions], dtype="float64")
    rweights = rweights / rweights.sum()
    region = rng.choice(regions, size=n, p=rweights)
    city = np.array([
        tax.SAUDI_REGIONS[r][rng.integers(0, len(tax.SAUDI_REGIONS[r]))] for r in region
    ], dtype=object)
    branch_id = np.array([f"BR-{r[:3]}-{rng.integers(1, 25):03d}" for r in region], dtype=object)

    residency = rng.choice(np.array(tax.RESIDENCY_CATEGORIES), size=n, p=[0.72, 0.28])
    age_band = rng.choice(np.array(tax.AGE_BANDS), size=n, p=[0.19, 0.31, 0.26, 0.16, 0.08])
    dependants_band = rng.choice(np.array(tax.DEPENDANTS_BANDS), size=n, p=[0.22, 0.38, 0.28, 0.12])

    employment_status = rng.choice(
        np.array(tax.EMPLOYMENT_STATUS), size=n, p=[0.27, 0.09, 0.48, 0.11, 0.05])
    emp_ids = np.array([e[0] for e in tax.EMPLOYER_GROUPS])
    emp_sectors = {e[0]: e[2] for e in tax.EMPLOYER_GROUPS}
    public_ids = np.array([e[0] for e in tax.EMPLOYER_GROUPS if e[2] == "PUBLIC_ADMINISTRATION"])
    employer_id = np.empty(n, dtype=object)
    is_public = np.isin(employment_status, ["GOVERNMENT", "GOVERNMENT_RELATED"])
    employer_id[is_public] = rng.choice(public_ids, size=int(is_public.sum()))
    employer_id[~is_public] = rng.choice(emp_ids, size=int((~is_public).sum()))
    self_emp = employment_status == "SELF_EMPLOYED"
    employer_id[self_emp] = None
    employer_sector = np.array(
        [emp_sectors.get(e) if e is not None else "OTHER_SERVICES" for e in employer_id],
        dtype=object)

    # Income: lognormal by employment status, floored so a booked retail
    # facility always has an income that could have supported it.
    mu = np.select(
        [employment_status == "GOVERNMENT", employment_status == "GOVERNMENT_RELATED",
         employment_status == "PRIVATE_SECTOR", employment_status == "SELF_EMPLOYED",
         employment_status == "RETIRED"],
        [9.32, 9.45, 9.18, 9.25, 8.72], default=9.20)
    base_salary = np.round(np.exp(rng.normal(mu, 0.52, size=n)) / 100.0) * 100.0
    base_salary = np.clip(base_salary, 3_500.0, 400_000.0)
    other_income = np.where(rng.random(n) < 0.22,
                            np.round(base_salary * rng.uniform(0.04, 0.30, size=n) / 100) * 100,
                            0.0)
    total_income = base_salary + other_income
    household_expenses = np.round(
        total_income * rng.uniform(0.22, 0.45, size=n) / 100.0) * 100.0
    external_obligations = np.where(
        rng.random(n) < 0.58,
        np.round(total_income * rng.uniform(0.03, 0.28, size=n) / 100.0) * 100.0,
        0.0)

    segment = np.select(
        [total_income >= 60_000, total_income >= 25_000, total_income >= 12_000],
        ["PRIVATE", "AFFLUENT", "MASS_AFFLUENT"], default="MASS").astype(object)

    salary_transfer = rng.random(n) < np.where(is_public, 0.86, 0.58)
    employment_tenure = np.clip(
        rng.gamma(2.4, 26.0, size=n).astype("int64"), 1, 420)
    relationship_start = -rng.integers(0, 160, size=n)  # months before the window

    latent_quality = rng.normal(0.0, 1.0, size=n)
    cycle_beta = np.clip(rng.normal(1.0, 0.35, size=n), 0.15, 2.2)

    # Seeded investigation story: two synthetic construction employers run a
    # salary-disruption episode during the window. Discoverable from the data,
    # never from a hard-coded answer.
    salary_shock_group = np.isin(employer_id, ["EMP-G007", "EMP-G008"])

    return Customers(
        n=n,
        customer_id=np.array([f"RC-{i:07d}" for i in range(1, n + 1)], dtype=object),
        region=region, city=city, branch_id=branch_id, residency=residency,
        age_band=age_band, dependants_band=dependants_band,
        employment_status=employment_status, employer_id=employer_id,
        employer_sector=employer_sector,
        employment_tenure_months_at_start=employment_tenure,
        salary_transfer=salary_transfer, base_salary_sar=base_salary,
        other_income_sar=other_income, household_expenses_sar=household_expenses,
        external_obligations_sar=external_obligations, segment=segment,
        relationship_start_month_index=relationship_start,
        latent_quality=latent_quality, cycle_beta=cycle_beta,
        salary_shock_group=salary_shock_group,
    )


# ==========================================================================
# Facilities
# ==========================================================================

@dataclass
class Facilities:
    n: int
    facility_id: np.ndarray
    application_id: np.ndarray
    customer_index: np.ndarray
    product_code: np.ndarray
    origination_month_index: np.ndarray   # relative to the first simulated month
    original_tenor_months: np.ndarray     # 0 for revolving
    original_amount: np.ndarray           # finance amount, or card limit
    original_limit: np.ndarray            # card limit, else 0
    nominal_rate: np.ndarray
    contract_structure: np.ndarray
    rate_type: np.ndarray
    channel: np.ndarray
    purpose: np.ndarray
    collateral_value_origination: np.ndarray
    vehicle_new_used: np.ndarray
    vehicle_age_months: np.ndarray
    dealer_id: np.ndarray
    down_payment: np.ndarray
    balloon_payment: np.ndarray
    property_type: np.ndarray
    housing_support: np.ndarray
    new_to_bank: np.ndarray


def _annuity_payment(principal: np.ndarray, monthly_rate: np.ndarray, n: np.ndarray) -> np.ndarray:
    n_safe = np.maximum(n, 1)
    r = np.where(monthly_rate <= 0, 1e-9, monthly_rate)
    factor = np.power(1.0 + r, n_safe)
    return principal * r * factor / (factor - 1.0)


def _build_facilities(
    rng: np.random.Generator, cfg: RetailDemoConfig, cust: Customers, n_months: int,
) -> Facilities:
    target_latest = int(cfg.portfolio["target_active_facilities_latest_month"])
    return _build_facilities_sized(rng, cfg, cust, n_months, int(round(target_latest * 1.34)))


def _build_facilities_sized(
    rng: np.random.Generator, cfg: RetailDemoConfig, cust: Customers, n_months: int,
    n_applications: int, product_weights: dict[str, float] | None = None,
) -> Facilities:
    """One row per APPLICATION, with everything fixed at origination.

    Applications, not facilities: the cutoff has not been applied yet. What
    survives it becomes the booked book.
    """
    mix = product_weights or cfg.portfolio["product_mix_latest_month"]
    products = np.array(list(mix))
    p = np.array([mix[k] for k in products], dtype="float64")
    p = p / p.sum()

    n_fac = int(n_applications)

    customer_index = rng.integers(0, cust.n, size=n_fac)
    product_code = rng.choice(products, size=n_fac, p=p)

    income = cust.base_salary_sar[customer_index] + cust.other_income_sar[customer_index]

    tenor = np.zeros(n_fac, dtype="int64")
    amount = np.zeros(n_fac, dtype="float64")
    limit = np.zeros(n_fac, dtype="float64")
    rate = np.zeros(n_fac, dtype="float64")

    is_card = product_code == tax.CREDIT_CARD
    is_pl = product_code == tax.PERSONAL_LOAN
    is_auto = product_code == tax.AUTO_LOAN
    is_home = product_code == tax.HOME_LOAN

    # Credit card: limit as a multiple of monthly income, capped.
    limit_raw = income * rng.uniform(0.8, 3.2, size=n_fac)
    limit = np.where(is_card, np.clip(np.round(limit_raw / 500.0) * 500.0, 3_000.0, 250_000.0), 0.0)
    amount = np.where(is_card, limit, amount)
    rate = np.where(is_card, rng.uniform(0.22, 0.34, size=n_fac), rate)

    pl_amt = np.clip(np.round(income * rng.uniform(3.0, 14.0, size=n_fac) / 1000.0) * 1000.0,
                     10_000.0, 1_500_000.0)
    pl_tenor = rng.choice(np.array([12, 24, 36, 48, 60]), size=n_fac, p=[0.06, 0.18, 0.30, 0.22, 0.24])
    amount = np.where(is_pl, pl_amt, amount)
    tenor = np.where(is_pl, pl_tenor, tenor)
    rate = np.where(is_pl, rng.uniform(0.055, 0.115, size=n_fac), rate)

    auto_amt = np.clip(np.round(income * rng.uniform(4.0, 16.0, size=n_fac) / 1000.0) * 1000.0,
                       25_000.0, 900_000.0)
    auto_tenor = rng.choice(np.array([24, 36, 48, 60]), size=n_fac, p=[0.10, 0.31, 0.29, 0.30])
    amount = np.where(is_auto, auto_amt, amount)
    tenor = np.where(is_auto, auto_tenor, tenor)
    rate = np.where(is_auto, rng.uniform(0.045, 0.089, size=n_fac), rate)

    home_amt = np.clip(np.round(income * rng.uniform(28.0, 90.0, size=n_fac) / 5000.0) * 5000.0,
                       250_000.0, 6_000_000.0)
    home_tenor = rng.choice(np.array([120, 180, 240, 300]), size=n_fac, p=[0.12, 0.26, 0.36, 0.26])
    amount = np.where(is_home, home_amt, amount)
    tenor = np.where(is_home, home_tenor, tenor)
    rate = np.where(is_home, rng.uniform(0.038, 0.072, size=n_fac), rate)

    # Origination spread: most facilities pre-date the window (a continuing
    # book), the rest originate inside it so vintages are observable.
    #
    # The pre-window age is bounded by the contract's own tenor. Without that,
    # a 24-month personal finance drawn 90 months ago matures before the first
    # published month and quietly vanishes, and the book that arrives on screen
    # is nothing like the product mix that was configured.
    u = rng.random(n_fac)
    pre_window = u < 0.55
    max_age = np.where(tenor > 0, np.maximum((tenor * 0.85).astype("int64"), 2), 96)
    max_age = np.minimum(max_age, 96)
    pre_age = 1 + (rng.random(n_fac) * (max_age - 1)).astype("int64")
    # New business is tilted towards the later months so the book grows gently
    # rather than running off. A shrinking demo book would still be coherent,
    # but a growing one is what a retail portfolio under monitoring looks like,
    # and it gives the vintage questions something to compare.
    in_window = np.minimum(
        (n_months * np.power(rng.random(n_fac), 0.68)).astype("int64"), n_months - 1)
    orig_idx = np.where(pre_window, -pre_age, in_window)


    # Collateral, down payment, balloon
    collateral = np.zeros(n_fac, dtype="float64")
    auto_ltv = np.clip(rng.normal(0.76, 0.09, size=n_fac), 0.35, 0.85)
    home_ltv = np.clip(rng.normal(0.78, 0.09, size=n_fac), 0.40, 0.90)
    collateral = np.where(is_auto, amount / auto_ltv, collateral)
    collateral = np.where(is_home, amount / home_ltv, collateral)
    collateral = np.round(collateral / 1000.0) * 1000.0

    down_payment = np.where(is_auto, np.maximum(collateral - amount, 0.0), np.nan)
    has_balloon = is_auto & (rng.random(n_fac) < 0.34)
    balloon = np.where(has_balloon,
                       np.round(amount * rng.uniform(0.12, 0.38, size=n_fac) / 500.0) * 500.0,
                       np.where(is_auto, 0.0, np.nan))

    channel = np.array([
        tax.CHANNEL_BY_PRODUCT[pc][rng.integers(0, len(tax.CHANNEL_BY_PRODUCT[pc]))]
        for pc in product_code
    ], dtype=object)
    # Seeded story: a personal-finance origination-mix shift toward DIGITAL in
    # the later part of the window.
    shift = is_pl & (orig_idx >= n_months - 14) & (rng.random(n_fac) < 0.45)
    channel = np.where(shift, "DIGITAL", channel)

    purpose = np.full(n_fac, None, dtype=object)
    purpose = np.where(is_pl,
                       rng.choice(np.array(tax.PERSONAL_LOAN_PURPOSES), size=n_fac,
                                  p=[0.62, 0.24, 0.14]),
                       purpose)
    purpose = np.where(is_home,
                       rng.choice(np.array(tax.HOME_PURPOSES), size=n_fac, p=[0.66, 0.22, 0.12]),
                       purpose)

    structure = np.where(is_home, rng.choice(np.array(["IJARA", "MURABAHA"]), size=n_fac, p=[0.55, 0.45]),
                np.where(is_auto, rng.choice(np.array(["IJARA", "MURABAHA"]), size=n_fac, p=[0.62, 0.38]),
                np.where(is_pl, rng.choice(np.array(["TAWARRUQ", "MURABAHA"]), size=n_fac, p=[0.7, 0.3]),
                         "MURABAHA"))).astype(object)
    rate_type = np.where(is_home, rng.choice(np.array(["FIXED", "FLOATING"]), size=n_fac, p=[0.42, 0.58]),
                         "FIXED").astype(object)

    vehicle_new_used = np.where(is_auto,
                                rng.choice(np.array(tax.VEHICLE_CONDITIONS), size=n_fac, p=[0.58, 0.42]),
                                None)
    vehicle_age = np.where(is_auto & (vehicle_new_used == "USED"),
                           rng.integers(12, 84, size=n_fac).astype("float64"),
                           np.where(is_auto, 0.0, np.nan))
    dealer_id = np.where(is_auto,
                         np.array([f"DLR-{rng.integers(1, 60):03d}" for _ in range(n_fac)], dtype=object),
                         None)

    property_type = np.where(is_home,
                             rng.choice(np.array(tax.PROPERTY_TYPES), size=n_fac,
                                        p=[0.44, 0.33, 0.15, 0.08]),
                             None)
    housing_support = np.where(is_home & (rng.random(n_fac) < 0.31),
                               "SYNTHETIC_SUPPORTED_PROGRAMME",
                               np.where(is_home, "NONE", None))

    rel_start = cust.relationship_start_month_index[customer_index]
    new_to_bank = (orig_idx - rel_start) <= 1

    return Facilities(
        n=n_fac,
        facility_id=np.array([f"RF-{i:08d}" for i in range(1, n_fac + 1)], dtype=object),
        application_id=np.array([f"APP-{i:08d}" for i in range(1, n_fac + 1)], dtype=object),
        customer_index=customer_index, product_code=product_code,
        origination_month_index=orig_idx, original_tenor_months=tenor,
        original_amount=amount, original_limit=limit, nominal_rate=rate,
        contract_structure=structure, rate_type=rate_type, channel=channel,
        purpose=purpose, collateral_value_origination=collateral,
        vehicle_new_used=vehicle_new_used, vehicle_age_months=vehicle_age,
        dealer_id=dealer_id, down_payment=down_payment, balloon_payment=balloon,
        property_type=property_type, housing_support=housing_support,
        new_to_bank=new_to_bank,
    )


def _subset_facilities(fac: Facilities, mask: np.ndarray) -> Facilities:
    """The booked subset, every array filtered the same way."""
    keep = np.asarray(mask, dtype=bool)
    return Facilities(
        n=int(keep.sum()),
        **{
            name: getattr(fac, name)[keep]
            for name in (
                "facility_id", "application_id", "customer_index", "product_code",
                "origination_month_index", "original_tenor_months", "original_amount",
                "original_limit", "nominal_rate", "contract_structure", "rate_type",
                "channel", "purpose", "collateral_value_origination", "vehicle_new_used",
                "vehicle_age_months", "dealer_id", "down_payment", "balloon_payment",
                "property_type", "housing_support", "new_to_bank",
            )
        },
    )


# ==========================================================================
# The monthly simulation
# ==========================================================================

def _cycle_path(n_months: int) -> np.ndarray:
    """The common credit cycle the whole book is exposed to.

    A synthetic path: a mild improvement through the middle of the window and a
    deterioration towards the end, so that ECL, stage mix and delinquency have
    something real to move with and a month-on-month question has an answer that
    is not noise.
    """
    t = np.arange(n_months, dtype="float64")
    return 0.55 * np.sin(2.0 * np.pi * (t - 6.0) / 31.0) + 0.30 * (t / max(n_months - 1, 1))


@dataclass
class _State:
    active: np.ndarray
    balance: np.ndarray
    accrued: np.ndarray
    limit: np.ndarray
    scheduled_payment: np.ndarray
    arrears_months: np.ndarray
    day_offset: np.ndarray
    overdue: np.ndarray
    default_flag: np.ndarray
    first_default_idx: np.ndarray
    latest_default_idx: np.ndarray
    default_episode: np.ndarray
    months_in_default: np.ndarray
    cure_counter: np.ndarray
    cure_flag: np.ndarray
    cure_idx: np.ndarray
    forbearance_flag: np.ndarray
    forbearance_idx: np.ndarray
    restructured_flag: np.ndarray
    writeoff_flag: np.ndarray
    writeoff_idx: np.ndarray
    cumulative_writeoff: np.ndarray
    writeoff_month_amount: np.ndarray
    recovery_month_amount: np.ndarray
    collections_stage: np.ndarray
    closed_idx: np.ndarray
    closure_reason: np.ndarray
    collateral_current: np.ndarray
    bureau_score: np.ndarray
    utilisation: np.ndarray
    stage: np.ndarray
    stage_prev: np.ndarray
    stage_entry_idx: np.ndarray
    behavioural_score_prev: np.ndarray
    contact_attempts: np.ndarray
    promise_flag: np.ndarray
    broken_promises: np.ndarray
    autopay_failures: np.ndarray
    external_obligations: np.ndarray


def _ring(n: int) -> np.ndarray:
    return np.full((n, HISTORY_MONTHS), np.nan, dtype="float64")


def _push(buf: np.ndarray, values: np.ndarray) -> np.ndarray:
    buf[:, :-1] = buf[:, 1:]
    buf[:, -1] = values
    return buf


def _tail(buf: np.ndarray, k: int) -> np.ndarray:
    return buf[:, -k:]


def _nan_count_ge(buf: np.ndarray, k: int, threshold: float) -> np.ndarray:
    w = _tail(buf, k)
    return np.nansum((w >= threshold) & ~np.isnan(w), axis=1)


def _history_depth(buf: np.ndarray) -> np.ndarray:
    return (~np.isnan(buf)).sum(axis=1)


# ==========================================================================
# Origination: everything measured once, on the application date, and frozen
# ==========================================================================

INCOME_GROWTH_MONTHLY = 0.0021
SCORE_TO_IFRS9_PD_MAPPING_VERSION = "retail-score-to-ifrs9-pd-1.0.0"
#: The versioned link from a behavioural model PD to a through-the-cycle IFRS 9
#: PD. Two different questions, joined by a stated mapping rather than by
#: assuming they are the same number.
IFRS9_PD_MAP_A, IFRS9_PD_MAP_B = -0.15, 0.94
#: How strongly the point-in-time PD responds to the cycle. A demo coefficient.
PIT_CYCLE_KAPPA = 0.55


def _logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(q / (1.0 - q))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _origination_frame(
    rng: np.random.Generator, cust: Customers, fac: Facilities,
) -> pd.DataFrame:
    """The application-date view of every facility, computed once.

    Every column here is fixed at origination and repeated unchanged on every
    later snapshot. A current-income shock must not reach any of them.
    """
    ci = fac.customer_index
    oi = fac.origination_month_index.astype("float64")

    growth = np.power(1.0 + INCOME_GROWTH_MONTHLY, oi)
    salary_orig = np.round(cust.base_salary_sar[ci] * growth / 10.0) * 10.0
    other_orig = np.round(cust.other_income_sar[ci] * growth / 10.0) * 10.0
    income_orig = salary_orig + other_orig
    expenses_orig = np.round(cust.household_expenses_sar[ci] * growth / 10.0) * 10.0
    external_orig = np.round(cust.external_obligations_sar[ci] * growth / 10.0) * 10.0

    mrate = fac.nominal_rate / 12.0
    is_card = fac.product_code == tax.CREDIT_CARD
    instalment = np.where(
        is_card,
        np.maximum(fac.original_limit * 0.05, 200.0),   # card minimum payment
        _annuity_payment(fac.original_amount, mrate, np.maximum(fac.original_tenor_months, 1)),
    )
    instalment = np.round(instalment, 2)

    # Own-bank obligations already running when this facility was applied for:
    # the sum of the instalments of the SAME customer's earlier facilities.
    # Counted once, and this facility's own instalment is added exactly once on
    # top of it — the commonest affordability double count, avoided explicitly.
    order = pd.DataFrame({"c": ci, "o": fac.origination_month_index, "i": instalment})
    order["seq"] = np.arange(len(order))
    order = order.sort_values(["c", "o", "seq"])
    prior = order.groupby("c")["i"].cumsum() - order["i"]
    prior_own = prior.sort_index().to_numpy()

    own_bank_obligations = prior_own + instalment
    total_obligations = own_bank_obligations + external_orig
    dbr = np.where(income_orig > 0, total_obligations / income_orig, np.nan)
    disposable = income_orig - expenses_orig - total_obligations

    emp_tenure_orig = np.clip(cust.employment_tenure_months_at_start[ci] + oi, 1, 500).astype("int64")
    cust_tenure_orig = np.clip(oi - cust.relationship_start_month_index[ci], 0, 500).astype("int64")

    # Synthetic bureau proxy at origination: a noisy reading of latent quality.
    q = cust.latent_quality[ci]
    bureau = np.clip(np.round(650.0 + 58.0 * q + rng.normal(0, 34.0, size=fac.n)), 300, 900)
    thin_file = (cust_tenure_orig < 6) & (rng.random(fac.n) < 0.55)
    bureau = np.where(thin_file, np.nan, bureau)

    enquiries = rng.poisson(np.clip(1.6 - 0.45 * q, 0.15, 6.0)).astype("float64")
    ext_dpd = np.where(rng.random(fac.n) < _sigmoid(-1.9 - 0.8 * q),
                       rng.choice(np.array([5.0, 20.0, 45.0, 75.0, 120.0]), size=fac.n,
                                  p=[0.42, 0.26, 0.16, 0.10, 0.06]), 0.0)
    ext_facilities = rng.poisson(np.clip(2.3 - 0.35 * q, 0.2, 9.0)).astype("float64")

    amount_to_income = np.where(income_orig > 0, fac.original_amount / income_orig, np.nan)
    instalment_to_income = np.where(income_orig > 0, instalment / income_orig, np.nan)

    is_auto = fac.product_code == tax.AUTO_LOAN
    is_home = fac.product_code == tax.HOME_LOAN
    secured = is_auto | is_home
    ltv_orig = np.where(secured & (fac.collateral_value_origination > 0),
                        fac.original_amount / np.where(fac.collateral_value_origination > 0,
                                                       fac.collateral_value_origination, 1.0),
                        np.nan)
    balloon_ratio = np.where(is_auto & (fac.original_amount > 0),
                             np.nan_to_num(fac.balloon_payment, nan=0.0) / fac.original_amount,
                             np.nan)

    # Income stability needs pre-application salary history. A brand-new
    # customer does not have it, and the column says so rather than guessing.
    has_history = cust_tenure_orig >= 6
    stability = np.where(
        has_history,
        np.clip(rng.normal(0.94, 0.055, size=fac.n) - 0.045 * np.clip(-q, 0, None), 0.30, 1.0),
        np.nan,
    )

    df = pd.DataFrame({
        "facility_id": fac.facility_id,
        "application_id": fac.application_id,
        "origination_income_sar": income_orig,
        "origination_salary_sar": salary_orig,
        "origination_household_expenses_sar": expenses_orig,
        "origination_external_obligations_sar": external_orig,
        "origination_own_bank_obligations_sar": own_bank_obligations,
        "origination_total_obligations_sar": total_obligations,
        "origination_debt_burden_ratio": dbr,
        "origination_disposable_income_sar": disposable,
        "origination_employment_tenure_months": emp_tenure_orig,
        "origination_customer_tenure_months": cust_tenure_orig,
        "origination_salary_transfer_status": np.where(
            cust.salary_transfer[ci], "YES", "NO").astype(object),
        "bureau_score_at_origination": bureau,
        "origination_bureau_enquiries_3m": enquiries,
        "origination_bureau_external_dpd_max": ext_dpd,
        "origination_bureau_active_facilities": ext_facilities,
        "origination_amount_to_income_ratio": amount_to_income,
        "origination_instalment_to_income_ratio": instalment_to_income,
        "original_tenor_months": np.where(fac.original_tenor_months > 0,
                                          fac.original_tenor_months, np.nan),
        "ltv_origination_ratio": ltv_orig,
        "origination_balloon_ratio": balloon_ratio,
        "origination_income_stability_ratio": stability,
        "scheduled_monthly_payment_sar": instalment,
        "bureau_thin_file_flag": thin_file,
    })
    return df


def _score_at_origination(orig: pd.DataFrame, fac: Facilities) -> pd.DataFrame:
    """Application score per facility, from its product's configured model.

    Scored per product and reassembled, so a card facility carries null in the
    columns of a feature only the mortgage model uses rather than a zero that
    would read like an observation.
    """
    pieces: list[pd.DataFrame] = []
    for product, sc in APPLICATION_SCORECARDS.items():
        mask = (fac.product_code == product)
        if not mask.any():
            continue
        sub = sc.score_frame(orig.loc[mask])
        sub["app_model_id"] = sc.model_id
        sub["app_model_version"] = sc.model_version
        sub["app_transform_version"] = sc.transform_version
        sub["app_target_definition_id"] = sc.target_definition_id
        pieces.append(sub)
    out = pd.concat(pieces, axis=0).reindex(orig.index)
    for c in application_columns():
        if c not in out.columns:
            out[c] = np.nan
    return out


def _amortised_balance(
    principal: np.ndarray, monthly_rate: np.ndarray, tenor: np.ndarray, k: np.ndarray,
) -> np.ndarray:
    """Outstanding principal after `k` scheduled payments of an annuity."""
    r = np.where(monthly_rate <= 0, 1e-9, monthly_rate)
    n = np.maximum(tenor, 1).astype("float64")
    kk = np.clip(k.astype("float64"), 0, n)
    num = np.power(1.0 + r, n) - np.power(1.0 + r, kk)
    den = np.power(1.0 + r, n) - 1.0
    return np.maximum(principal * num / np.where(den == 0, 1e-9, den), 0.0)


def _alive_at_end(fac: Facilities, n_months: int) -> np.ndarray:
    """Whether a facility's contract still runs at the last simulated month.

    Contractual only — it ignores default, write-off and early settlement — but
    it is enough to see that a 24-month personal finance and a revolving card
    do not survive a 37-month window at the same rate, which is the whole
    reason the application mix has to differ from the book mix.
    """
    is_card = fac.product_code == tax.CREDIT_CARD
    return is_card | ((fac.origination_month_index + fac.original_tenor_months) > (n_months - 1))


def calibrate_product_weights(
    cfg: RetailDemoConfig, cust: Customers, n_months: int, n_applications: int,
    *, iterations: int = 3,
) -> tuple[dict[str, float], float]:
    """Application-mix weights that land the LAST month on the configured book mix.

    `product_mix_latest_month` says what the book should look like in August
    2026. Applications are not the book: cards revolve for years while a
    two-year personal finance matures inside the window, so booking the target
    mix as applications produces a card-heavy book and a personal-finance
    rump. This measures each product's survival and booking rate on a
    throwaway pass and inverts them. Deterministic: its own seeded generator,
    no wall clock.
    """
    target = cfg.portfolio["product_mix_latest_month"]
    weights = {k: float(v) for k, v in target.items()}
    survivor_rate = 1.0
    for it in range(iterations):
        rng = np.random.default_rng(cfg.seed + 9_000 + it)
        fac = _build_facilities_sized(rng, cfg, cust, n_months, n_applications, weights)
        orig = _origination_frame(rng, cust, fac)
        app = _score_at_origination(orig, fac)
        score = pd.to_numeric(app["app_score_value"]).to_numpy(dtype="float64")
        cutoff = np.array([CUTOFF_POLICY.cutoff_for(p) for p in fac.product_code])
        booked = (score >= cutoff) | ((score < cutoff) & (rng.random(fac.n) < CUTOFF_POLICY.exception_rate))
        survivors = booked & _alive_at_end(fac, n_months)
        if not survivors.any():
            break
        survivor_rate = float(survivors.mean())
        realised = pd.Series(fac.product_code[survivors]).value_counts(normalize=True).to_dict()
        new: dict[str, float] = {}
        for prod, want in target.items():
            got = realised.get(prod, 1e-6)
            new[prod] = max(weights[prod] * (want / got), 1e-6)
        total = sum(new.values())
        weights = {k: v / total for k, v in new.items()}
    return weights, survivor_rate


class RetailSimulation:
    """The month-by-month state machine behind the published book."""

    def __init__(self, cfg: RetailDemoConfig, rng: np.random.Generator):
        self.cfg = cfg
        self.rng = rng
        self.n_all = len(cfg.all_dates)
        self.n_published = cfg.months
        self.first_published_index = len(cfg.warmup_dates)
        self.dates = cfg.all_dates
        self.cycle = _cycle_path(self.n_all)

    # -- setup -------------------------------------------------------------

    def prepare(self) -> None:
        cfg, rng = self.cfg, self.rng
        target = int(cfg.portfolio["target_active_facilities_latest_month"])
        per_customer = float(cfg.portfolio["facilities_per_customer_mean"])
        n_applications = int(round(target * 1.85))
        n_customers = max(int(round(n_applications / per_customer)), 100)

        self.cust = _build_customers(rng, cfg, n_customers)

        # Two things stand between an application and a row in August 2026: the
        # cutoff, and the contract running out. Both are measured rather than
        # guessed at, so the published book lands on the configured size and mix
        # instead of near them.
        self.product_weights, survivor_rate = calibrate_product_weights(
            cfg, self.cust, self.n_all, n_applications)
        #: Defaults, write-offs and early settlements remove a further slice
        #: that the contractual survival estimate cannot see.
        lifecycle_attrition = 0.93
        n_applications = int(round(target / max(survivor_rate * lifecycle_attrition, 0.05)))
        n_customers = max(int(round(n_applications / per_customer)), 100)
        self.cust = _build_customers(np.random.default_rng(cfg.seed), cfg, n_customers)
        self.calibrated_survivor_rate = survivor_rate

        fac_all = _build_facilities_sized(
            rng, cfg, self.cust, self.n_all, n_applications, self.product_weights)
        orig_all = _origination_frame(rng, self.cust, fac_all)
        app_all = _score_at_origination(orig_all, fac_all)

        # --- the cutoff, applied for real -------------------------------
        # Everything below the product's cutoff is declined, except a small
        # documented exception share. That is what makes the canonical table a
        # BOOKED book, and what gives §13.4's retrospective cutoff replay a
        # real population to work on.
        score = pd.to_numeric(app_all["app_score_value"]).to_numpy(dtype="float64")
        cutoff = np.array([CUTOFF_POLICY.cutoff_for(p) for p in fac_all.product_code])
        above = score >= cutoff
        exception = (~above) & (rng.random(fac_all.n) < CUTOFF_POLICY.exception_rate)
        booked = above | exception

        self.fac = _subset_facilities(fac_all, booked)
        self.orig = orig_all.loc[booked].reset_index(drop=True)
        self.app = app_all.loc[booked].reset_index(drop=True)
        self.applied_cutoff = cutoff[booked]
        self.policy_exception = exception[booked]
        self.declined_count = int((~booked).sum())
        self.application_count = int(fac_all.n)

        n = self.fac.n
        self.state = _State(
            active=np.zeros(n, dtype=bool), balance=np.zeros(n), accrued=np.zeros(n),
            limit=np.zeros(n),
            scheduled_payment=self.orig["scheduled_monthly_payment_sar"].to_numpy(dtype="float64"),
            arrears_months=np.zeros(n, dtype="int64"),
            day_offset=rng.integers(1, 31, size=n).astype("int64"),
            overdue=np.zeros(n),
            default_flag=np.zeros(n, dtype=bool),
            first_default_idx=np.full(n, -1, dtype="int64"),
            latest_default_idx=np.full(n, -1, dtype="int64"),
            default_episode=np.zeros(n, dtype="int64"),
            months_in_default=np.zeros(n, dtype="int64"),
            cure_counter=np.zeros(n, dtype="int64"),
            cure_flag=np.zeros(n, dtype=bool), cure_idx=np.full(n, -1, dtype="int64"),
            forbearance_flag=np.zeros(n, dtype=bool),
            forbearance_idx=np.full(n, -1, dtype="int64"),
            restructured_flag=np.zeros(n, dtype=bool),
            writeoff_flag=np.zeros(n, dtype=bool), writeoff_idx=np.full(n, -1, dtype="int64"),
            cumulative_writeoff=np.zeros(n), writeoff_month_amount=np.zeros(n),
            recovery_month_amount=np.zeros(n),
            collections_stage=np.zeros(n, dtype="int64"),
            closed_idx=np.full(n, -1, dtype="int64"),
            closure_reason=np.full(n, None, dtype=object),
            collateral_current=self.fac.collateral_value_origination.astype("float64").copy(),
            bureau_score=self.orig["bureau_score_at_origination"].to_numpy(dtype="float64").copy(),
            utilisation=np.zeros(n),
            stage=np.ones(n, dtype="int64"), stage_prev=np.ones(n, dtype="int64"),
            stage_entry_idx=np.full(n, -1, dtype="int64"),
            behavioural_score_prev=np.full(n, np.nan),
            contact_attempts=np.zeros(n, dtype="int64"),
            promise_flag=np.zeros(n, dtype=bool),
            broken_promises=np.zeros(n, dtype="int64"),
            autopay_failures=np.zeros(n, dtype="int64"),
            external_obligations=self.orig["origination_external_obligations_sar"].to_numpy(
                dtype="float64").copy(),
        )

        # Rolling history, facility level
        self.h_dpd = _ring(n)
        self.h_missed = _ring(n)
        self.h_due = _ring(n)
        self.h_paid = _ring(n)
        self.h_util = _ring(n)
        self.h_minpay = _ring(n)
        self.h_overlimit = _ring(n)
        self.h_cashadv = _ring(n)
        self.h_bureau = _ring(n)
        self.h_extoblig = _ring(n)
        self.h_broken = _ring(n)
        self.h_autopay = _ring(n)
        self.h_balance = _ring(n)
        self.h_enquiries = _ring(n)
        self.h_behscore = _ring(n)

        # Rolling history, customer level
        m = self.cust.n
        self.h_salary = _ring(m)
        self.h_salary_missed = _ring(m)
        self.h_avg_balance = _ring(m)
        self.cust_stress = np.zeros(m)
        self.cust_ar = np.zeros(m)
        self.cust_bank_balance = np.maximum(
            self.cust.base_salary_sar * rng.uniform(0.2, 2.5, size=m), 200.0)
        self.employment_change = np.zeros(m, dtype=bool)
        self.job_loss_reported = np.zeros(m, dtype=bool)
        # External credit obligations belong to the PERSON, not to one of their
        # facilities. Held per customer so a customer with three loans has one
        # obligation figure, one debt burden ratio and one disposable income,
        # rather than three that disagree.
        self.cust_external_obligations = self.cust.external_obligations_sar.astype("float64").copy()

        # Seeded story: persistent-revolver card cohort.
        self.story_revolver = (
            (self.fac.product_code == tax.CREDIT_CARD)
            & (rng.random(n) < 0.11)
        )

        # Event matrices for outcome labelling. Small, and the only way to
        # build a forward-looking label without letting the generator write
        # future knowledge into an operational row.
        self.ev_new_default = np.zeros((n, self.n_all), dtype=bool)
        self.ev_dpd30 = np.zeros((n, self.n_all), dtype=bool)
        self.ev_dpd60 = np.zeros((n, self.n_all), dtype=bool)
        self.ev_active = np.zeros((n, self.n_all), dtype=bool)
        self.ev_in_default = np.zeros((n, self.n_all), dtype=bool)

    # -- one month ---------------------------------------------------------

    def _customer_month(self, t: int) -> None:
        """Advance every customer's latent state, salary and personal account."""
        rng, c = self.rng, self.cust
        m = c.n
        cyc = self.cycle[t]

        self.cust_ar = 0.86 * self.cust_ar + rng.normal(0.0, 0.48, size=m)
        stress = -c.latent_quality + c.cycle_beta * cyc + self.cust_ar
        self.cust_stress = stress

        growth = (1.0 + INCOME_GROWTH_MONTHLY) ** t
        expected = c.base_salary_sar * growth

        # Employment change is rare, persistent and observable only through its
        # consequences. It is never used as proof of job loss on its own.
        newly_changed = (~self.employment_change) & (rng.random(m) < _sigmoid(-6.4 + 0.55 * stress))
        self.employment_change |= newly_changed

        # Seeded story: two synthetic construction employers run a payroll
        # disruption episode in the middle of the published window.
        published_t = t - self.first_published_index
        in_episode = c.salary_shock_group & (10 <= published_t) & (published_t <= 21)
        p_missed = _sigmoid(-4.35 + 0.62 * stress) + np.where(in_episode, 0.20, 0.0)
        p_missed = np.where(self.employment_change, p_missed + 0.10, p_missed)
        missed = rng.random(m) < np.clip(p_missed, 0.0, 0.97)

        amount = np.where(
            missed, 0.0,
            np.round(expected * np.clip(rng.normal(1.0, 0.055, size=m), 0.45, 1.9) / 10.0) * 10.0,
        )
        # A reported job loss is a separate, rarer, explicitly-sourced signal.
        self.job_loss_reported |= (
            self.employment_change & missed & (rng.random(m) < 0.05)
        )

        self.cust_external_obligations = np.maximum(
            self.cust_external_obligations * (1.0 + INCOME_GROWTH_MONTHLY)
            + np.where(rng.random(m) < 0.05, rng.uniform(150, 2_400, size=m), 0.0)
            - np.where(rng.random(m) < 0.035, rng.uniform(100, 1_200, size=m), 0.0),
            0.0)
        obligations = self.cust_external_obligations
        outflow = (c.household_expenses_sar * growth) + obligations
        self.cust_bank_balance = np.maximum(
            self.cust_bank_balance * 0.55 + amount - outflow * rng.uniform(0.75, 1.05, size=m),
            0.0,
        )

        _push(self.h_salary, amount)
        _push(self.h_salary_missed, missed.astype("float64"))
        _push(self.h_avg_balance, self.cust_bank_balance)

    def _activate(self, t: int) -> None:
        """Bring facilities on to the book on their origination month."""
        st, fac = self.state, self.fac
        due_now = (fac.origination_month_index == t) & ~st.active & (st.closed_idx < 0)
        # Facilities originated before the simulation start join at t = 0 with
        # the balance their age implies, not at their full original amount.
        if t == 0:
            due_now |= (fac.origination_month_index < 0) & ~st.active
        if not due_now.any():
            return

        idx = np.where(due_now)[0]
        elapsed = np.maximum(t - fac.origination_month_index[idx], 0)
        is_card = fac.product_code[idx] == tax.CREDIT_CARD
        tenor = fac.original_tenor_months[idx]
        matured = (~is_card) & (elapsed >= tenor)

        keep = ~matured
        idx = idx[keep]
        if idx.size == 0:
            return
        elapsed = elapsed[keep]
        is_card = is_card[keep]

        mrate = fac.nominal_rate[idx] / 12.0
        bal = np.where(
            is_card,
            fac.original_limit[idx] * np.clip(self.rng.normal(0.36, 0.24, size=idx.size), 0.0, 1.0),
            _amortised_balance(fac.original_amount[idx], mrate,
                               fac.original_tenor_months[idx], elapsed),
        )
        st.balance[idx] = np.round(bal, 2)
        st.limit[idx] = np.where(is_card, fac.original_limit[idx], 0.0)
        st.utilisation[idx] = np.where(
            is_card & (fac.original_limit[idx] > 0),
            st.balance[idx] / np.where(fac.original_limit[idx] > 0, fac.original_limit[idx], 1.0),
            np.nan,
        )
        st.active[idx] = True
        st.stage_entry_idx[idx] = t

    def _facility_month(self, t: int) -> None:
        """Payments, arrears, balances, default, cure, write-off and closure."""
        rng, st, fac = self.rng, self.state, self.fac
        n = fac.n
        ci = fac.customer_index
        stress = self.cust_stress[ci]
        active = st.active

        is_card = fac.product_code == tax.CREDIT_CARD
        is_auto = fac.product_code == tax.AUTO_LOAN
        is_home = fac.product_code == tax.HOME_LOAN
        mrate = fac.nominal_rate / 12.0

        months_on_book = np.maximum(t - fac.origination_month_index, 0)

        # --- card utilisation: mean-reverting, pushed up by stress ---------
        target_util = np.clip(
            0.34 + 0.11 * stress + np.where(self.story_revolver, 0.22, 0.0)
            + rng.normal(0.0, 0.07, size=n),
            0.0, 1.18,
        )
        new_util = np.where(np.isnan(st.utilisation), target_util,
                            0.72 * st.utilisation + 0.28 * target_util)
        new_util = np.clip(new_util + rng.normal(0.0, 0.035, size=n), 0.0, 1.22)
        card_balance = np.round(new_util * st.limit, 2)

        # --- what is due this month ---------------------------------------
        due = np.where(
            is_card,
            np.maximum(card_balance * 0.05, np.minimum(200.0, np.maximum(card_balance, 0.0))),
            st.scheduled_payment,
        )
        due = np.where(active, due, 0.0)

        # --- balloon pressure for auto -------------------------------------
        balloon = np.nan_to_num(fac.balloon_payment, nan=0.0)
        months_to_balloon = np.where(
            is_auto & (balloon > 0),
            fac.original_tenor_months - months_on_book,
            np.nan,
        )
        balloon_pressure = np.where(
            np.isnan(months_to_balloon), 0.0,
            np.clip((9.0 - np.nan_to_num(months_to_balloon, nan=99.0)) / 9.0, 0.0, 1.0)
            * np.clip(balloon / np.maximum(fac.original_amount, 1.0), 0.0, 1.0) * 2.4,
        )

        # --- miss / pay ----------------------------------------------------
        alpha = np.select(
            [is_card, fac.product_code == tax.PERSONAL_LOAN, is_auto, is_home],
            [MISS_INTERCEPT["CREDIT_CARD"], MISS_INTERCEPT["PERSONAL_LOAN"],
             MISS_INTERCEPT["AUTO_LOAN"], MISS_INTERCEPT["HOME_LOAN"]],
            default=MISS_INTERCEPT["PERSONAL_LOAN"],
        )
        salary_missed_now = self.h_salary_missed[ci, -1] > 0
        dbr_pressure = np.clip(
            pd.to_numeric(self.orig["origination_debt_burden_ratio"]).to_numpy() - 0.35, -0.4, 0.6)
        p_miss = _sigmoid(
            alpha + MISS_STRESS_BETA * stress + MISS_DBR_BETA * dbr_pressure
            + MISS_SALARY_BETA * salary_missed_now.astype("float64")
            + 0.75 * np.where(is_card, np.clip(new_util - 0.55, 0, None) * 2.0, 0.0)
            + balloon_pressure
        )
        p_catch_up = _sigmoid(
            CATCH_UP_INTERCEPT - CATCH_UP_STRESS_BETA * stress - 0.55 * balloon_pressure)

        r = rng.random(n)
        in_arrears = st.arrears_months > 0
        missed = np.where(in_arrears, r > p_catch_up, r < p_miss)
        missed = missed & active & ~st.writeoff_flag

        # --- arrears and DPD ------------------------------------------------
        st.arrears_months = np.where(
            active,
            np.where(missed, st.arrears_months + 1, 0),
            st.arrears_months,
        )
        dpd = np.where(
            st.arrears_months > 0,
            (st.arrears_months - 1) * 30 + st.day_offset,
            0,
        ).astype("int64")
        dpd = np.where(active, dpd, 0)

        # --- payment received ------------------------------------------------
        min_only = is_card & ~missed & (rng.random(n) < _sigmoid(-0.35 + 0.75 * stress
                                                                + np.where(self.story_revolver, 1.5, 0.0)))
        paid = np.where(
            missed, 0.0,
            np.where(
                is_card,
                np.where(min_only, due, np.minimum(card_balance, due * rng.uniform(1.5, 9.0, size=n))),
                due,
            ),
        )
        paid = np.where(active, np.round(paid, 2), 0.0)

        # --- balances ---------------------------------------------------------
        interest = np.round(st.balance * mrate, 2)
        principal_repaid = np.where(
            is_card, np.maximum(paid - interest, 0.0),
            np.where(missed, 0.0, np.maximum(paid - interest, 0.0)),
        )
        new_drawdown = np.where(
            is_card, np.maximum(card_balance - (st.balance - principal_repaid), 0.0), 0.0)

        term_balance = np.maximum(st.balance - principal_repaid, 0.0)
        st.balance = np.where(active, np.round(np.where(is_card, card_balance, term_balance), 2),
                              st.balance)
        st.accrued = np.where(
            active,
            np.round(np.where(missed, st.accrued + interest, np.maximum(st.accrued - paid, 0.0) * 0.0), 2),
            st.accrued,
        )
        st.overdue = np.where(active, np.round(np.where(missed, st.overdue + due, 0.0), 2), st.overdue)
        st.utilisation = np.where(is_card & active, new_util, np.nan)

        # --- default, cure, write-off ----------------------------------------
        utp = active & ~st.default_flag & (rng.random(n) < _sigmoid(UTP_INTERCEPT + 0.85 * stress))
        newly_default = active & ~st.default_flag & ((dpd >= STAGING_POLICY.stage3_dpd_backstop) | utp)
        st.default_flag |= newly_default
        st.first_default_idx = np.where(
            newly_default & (st.first_default_idx < 0), t, st.first_default_idx)
        st.latest_default_idx = np.where(newly_default, t, st.latest_default_idx)
        st.default_episode = np.where(newly_default, st.default_episode + 1, st.default_episode)
        self.ev_new_default[:, t] = newly_default
        self.utp_now = utp & newly_default

        st.months_in_default = np.where(st.default_flag, st.months_in_default + 1, 0)

        cured = st.default_flag & ~missed & (st.arrears_months == 0)
        st.cure_counter = np.where(cured, st.cure_counter + 1, 0)
        cure_now = st.cure_counter >= STAGING_POLICY.cure_probation_months
        st.default_flag = np.where(cure_now, False, st.default_flag)
        st.cure_flag |= cure_now
        st.cure_idx = np.where(cure_now, t, st.cure_idx)
        st.months_in_default = np.where(cure_now, 0, st.months_in_default)

        # Forbearance: granted to a minority of stressed-but-not-defaulted cases.
        grant = (active & ~st.forbearance_flag & ~st.default_flag
                 & (st.arrears_months >= 1) & (rng.random(n) < 0.055))
        st.forbearance_flag |= grant
        st.forbearance_idx = np.where(grant, t, st.forbearance_idx)
        st.restructured_flag |= grant

        write_now = (st.default_flag & (st.months_in_default >= WRITE_OFF_AFTER_DEFAULT_MONTHS)
                     & ~st.writeoff_flag)
        st.writeoff_month_amount = np.where(write_now, st.balance, 0.0)
        recovery_rate = np.where(
            is_auto | is_home,
            np.clip(st.collateral_current * 0.72 / np.maximum(st.balance, 1.0), 0.0, 0.95),
            rng.uniform(0.05, 0.30, size=n),
        )
        st.recovery_month_amount = np.where(write_now, np.round(st.balance * recovery_rate, 2), 0.0)
        st.cumulative_writeoff = st.cumulative_writeoff + st.writeoff_month_amount
        st.writeoff_flag |= write_now
        st.writeoff_idx = np.where(write_now, t, st.writeoff_idx)

        st.collections_stage = np.select(
            [st.writeoff_flag, st.default_flag & (st.months_in_default >= 6),
             st.default_flag, dpd >= 30, dpd >= 1],
            [5, 4, 3, 2, 1], default=0,
        ).astype("int64")
        st.contact_attempts = np.where(dpd >= 1, np.minimum(st.contact_attempts + 1, 12), 0)
        promise = (dpd >= 30) & (rng.random(n) < 0.45)
        broke = promise & (rng.random(n) < _sigmoid(-0.4 + 0.7 * stress))
        st.promise_flag = promise
        st.broken_promises = np.where(broke, 1, 0)
        st.autopay_failures = np.where(missed & (rng.random(n) < 0.55), 1, 0)

        # --- collateral --------------------------------------------------------
        depreciation = np.where(is_auto, 0.9865, 1.0)
        home_move = 1.0 + (0.0016 - 0.0042 * np.clip(self.cycle[t], 0, None))
        st.collateral_current = np.where(
            is_auto, st.collateral_current * depreciation,
            np.where(is_home, st.collateral_current * home_move, st.collateral_current),
        )

        # --- closure ------------------------------------------------------------
        matured = active & ~is_card & (months_on_book >= fac.original_tenor_months)
        settled = (active & ~st.default_flag & ~matured
                   & (rng.random(n) < float(self.cfg.portfolio["monthly_voluntary_closure_rate"])))
        closing = matured | settled | write_now
        st.closure_reason = np.where(
            closing & (st.closure_reason == None),  # noqa: E711
            np.where(write_now, "WRITTEN_OFF", np.where(matured, "MATURED", "SETTLED_EARLY")),
            st.closure_reason,
        )
        st.closed_idx = np.where(closing & (st.closed_idx < 0), t, st.closed_idx)

        self.dpd_now = dpd
        self.due_now = due
        self.paid_now = paid
        self.missed_now = missed
        self.min_only_now = min_only
        self.interest_now = interest
        self.principal_repaid_now = principal_repaid
        self.new_drawdown_now = new_drawdown
        self.months_on_book_now = months_on_book
        self.months_to_balloon_now = months_to_balloon
        self.active_now = active.copy()

        self.ev_active[:, t] = active
        self.ev_dpd30[:, t] = active & (dpd >= 30)
        self.ev_dpd60[:, t] = active & (dpd >= 60)
        self.ev_in_default[:, t] = active & st.default_flag

        # Facilities close AFTER this month's row is recorded, so a closure is
        # observable rather than a row that silently vanishes.
        st.active = np.where(closing, False, st.active)

    # -- observable signals, rolling windows, scores -----------------------

    def _push_history(self, t: int) -> None:
        """Record this month's observations, then derive the rolling windows.

        Pushed before the rolling features are read, so a 3-month window ending
        at this snapshot includes this snapshot. Nothing here can see month
        t + 1: that is what keeps the behavioural score honest.
        """
        rng, st, fac = self.rng, self.state, self.fac
        n = fac.n
        ci = fac.customer_index
        stress = self.cust_stress[ci]
        is_card = fac.product_code == tax.CREDIT_CARD

        # Synthetic bureau proxy: a noisy monthly reading of latent quality,
        # dragged down by observed delinquency.
        q = self.cust.latent_quality[ci]
        target_bureau = np.clip(
            650.0 + 58.0 * q - 1.25 * np.minimum(self.dpd_now, 180)
            - 22.0 * np.clip(stress, 0, None) + rng.normal(0, 12.0, size=n),
            300.0, 900.0)
        prev = self.state.bureau_score
        st.bureau_score = np.where(np.isnan(prev), target_bureau, 0.78 * prev + 0.22 * target_bureau)
        st.bureau_score = np.where(self.active_now, np.round(st.bureau_score, 0), st.bureau_score)

        st.external_obligations = self.cust_external_obligations[ci]

        overlimit_days = np.where(
            is_card & (self.state.utilisation > 1.0),
            np.round(30.0 * np.clip((self.state.utilisation - 1.0) * 5.0, 0.0, 1.0)), 0.0)
        cash_adv = np.where(
            is_card,
            np.round(np.maximum(rng.normal(0.04 + 0.05 * np.clip(stress, 0, None), 0.05, size=n), 0.0), 4),
            np.nan)
        enquiries = np.where(rng.random(n) < _sigmoid(-2.2 + 0.45 * stress),
                             rng.integers(1, 4, size=n).astype("float64"), 0.0)

        _push(self.h_dpd, np.where(self.active_now, self.dpd_now, np.nan))
        _push(self.h_missed, np.where(self.active_now, self.missed_now.astype("float64"), np.nan))
        _push(self.h_due, np.where(self.active_now, self.due_now, np.nan))
        _push(self.h_paid, np.where(self.active_now, self.paid_now, np.nan))
        _push(self.h_util, np.where(self.active_now & is_card, self.state.utilisation, np.nan))
        _push(self.h_minpay, np.where(self.active_now & is_card,
                                      self.min_only_now.astype("float64"), np.nan))
        _push(self.h_overlimit, np.where(self.active_now & is_card, overlimit_days, np.nan))
        _push(self.h_cashadv, np.where(self.active_now & is_card, cash_adv, np.nan))
        _push(self.h_bureau, np.where(self.active_now, st.bureau_score, np.nan))
        _push(self.h_extoblig, np.where(self.active_now, st.external_obligations, np.nan))
        _push(self.h_broken, np.where(self.active_now, st.broken_promises.astype("float64"), np.nan))
        _push(self.h_autopay, np.where(self.active_now, st.autopay_failures.astype("float64"), np.nan))
        _push(self.h_balance, np.where(self.active_now, st.balance, np.nan))
        _push(self.h_enquiries, np.where(self.active_now, enquiries, np.nan))

    def _behavioural_sources(self, t: int) -> pd.DataFrame:
        """Every raw input the behavioural models read, computed from history."""
        st, fac = self.state, self.fac
        n = fac.n
        ci = fac.customer_index
        is_card = fac.product_code == tax.CREDIT_CARD
        is_auto = fac.product_code == tax.AUTO_LOAN
        secured = np.isin(fac.product_code, list(tax.SECURED_PRODUCTS))

        depth = _history_depth(self.h_dpd)
        thin = depth < 3

        def _win_sum(buf: np.ndarray, k: int) -> np.ndarray:
            w = _tail(buf, k)
            out = np.nansum(w, axis=1)
            return np.where((~np.isnan(w)).sum(axis=1) == 0, np.nan, out)

        def _win_max(buf: np.ndarray, k: int) -> np.ndarray:
            w = _tail(buf, k)
            allnan = (~np.isnan(w)).sum(axis=1) == 0
            with np.errstate(all="ignore"):
                out = np.where(allnan, np.nan, np.nanmax(np.where(np.isnan(w), -np.inf, w), axis=1))
            return out

        def _win_mean(buf: np.ndarray, k: int) -> np.ndarray:
            w = _tail(buf, k)
            counts = (~np.isnan(w)).sum(axis=1)
            totals = np.nansum(w, axis=1)
            return np.where(counts == 0, np.nan, totals / np.where(counts == 0, 1, counts))

        due_3m = _win_sum(self.h_due, 3)
        paid_3m = _win_sum(self.h_paid, 3)
        due_1m = self.h_due[:, -1]
        paid_1m = self.h_paid[:, -1]

        util_now = np.where(is_card, st.utilisation, np.nan)
        util_3m_ago = np.where(is_card, self.h_util[:, -4] if HISTORY_MONTHS >= 4 else np.nan, np.nan)

        sal = self.h_salary[ci]
        sal_missed = self.h_salary_missed[ci]
        sal_1m = sal[:, -1]
        def _safe_mean(block: np.ndarray) -> np.ndarray:
            counts = (~np.isnan(block)).sum(axis=1)
            totals = np.nansum(block, axis=1)
            return np.where(counts == 0, np.nan, totals / np.where(counts == 0, 1, counts))

        sal_prev3 = _safe_mean(sal[:, -4:-1]) if HISTORY_MONTHS >= 4 else np.full(n, np.nan)
        sal_avg3 = _safe_mean(sal[:, -3:])
        sal_avg6 = _safe_mean(sal[:, -6:])
        sal6 = sal[:, -6:]
        sal6_mean = _safe_mean(sal6)
        sal6_counts = (~np.isnan(sal6)).sum(axis=1)
        sal6_var = np.where(
            sal6_counts == 0, np.nan,
            np.nansum((sal6 - sal6_mean[:, None]) ** 2, axis=1)
            / np.where(sal6_counts == 0, 1, sal6_counts))
        vol = np.where(sal6_mean > 0, np.sqrt(sal6_var) / np.where(sal6_mean > 0, sal6_mean, 1.0), np.nan)

        obligations_monthly = np.maximum(
            st.external_obligations + st.scheduled_payment, 1.0)
        buffer_months = self.h_avg_balance[ci][:, -3:].mean(axis=1) / obligations_monthly

        bureau_now = st.bureau_score
        bureau_3m = self.h_bureau[:, -4] if HISTORY_MONTHS >= 4 else np.full(n, np.nan)
        ext_now = self.h_extoblig[:, -1]
        ext_3m = self.h_extoblig[:, -4] if HISTORY_MONTHS >= 4 else np.full(n, np.nan)

        gca = st.balance + st.accrued
        ltv_current = np.where(secured & (st.collateral_current > 0),
                               gca / np.where(st.collateral_current > 0, st.collateral_current, 1.0),
                               np.nan)

        # External delinquency reported by the synthetic bureau proxy.
        ext_dpd = np.where(
            np.isnan(bureau_now), np.nan,
            np.where(bureau_now < 520, 60.0, np.where(bureau_now < 580, 20.0, 0.0)))

        df = pd.DataFrame({
            "dpd": np.where(self.active_now, self.dpd_now, np.nan),
            "max_dpd_3m": _win_max(self.h_dpd, 3),
            "max_dpd_6m": _win_max(self.h_dpd, 6),
            "max_dpd_12m": _win_max(self.h_dpd, 12),
            "missed_payment_count_3m": _win_sum(self.h_missed, 3),
            "missed_payment_count_6m": _win_sum(self.h_missed, 6),
            "payment_to_due_ratio_1m": np.where(due_1m > 0, paid_1m / np.where(due_1m > 0, due_1m, 1.0), np.nan),
            "payment_to_due_ratio_3m": np.where(due_3m > 0, paid_3m / np.where(due_3m > 0, due_3m, 1.0), np.nan),
            "utilisation_ratio": util_now,
            "utilisation_avg_3m": _win_mean(self.h_util, 3),
            "utilisation_change_3m_pp": np.where(
                np.isnan(util_now) | np.isnan(util_3m_ago), np.nan,
                (util_now - util_3m_ago) * 100.0),
            "minimum_payment_only_months_3m": _win_sum(self.h_minpay, 3),
            "overlimit_days_3m": _win_sum(self.h_overlimit, 3),
            "cash_advance_share_3m": _win_mean(self.h_cashadv, 3),
            "salary_credit_amount_1m_sar": sal_1m,
            "salary_credit_average_3m_sar": sal_avg3,
            "salary_credit_average_6m_sar": sal_avg6,
            "salary_change_3m_ratio": np.where(
                (sal_prev3 > 0) & ~np.isnan(sal_1m), sal_1m / np.where(sal_prev3 > 0, sal_prev3, 1.0), np.nan),
            "salary_missed_cycle_count_3m": np.nansum(sal_missed[:, -3:], axis=1),
            "income_volatility_6m": vol,
            "balance_buffer_months": buffer_months,
            "account_average_balance_3m_sar": self.h_avg_balance[ci][:, -3:].mean(axis=1),
            "bureau_score_current": bureau_now,
            "bureau_score_change_3m": np.where(np.isnan(bureau_3m), np.nan, bureau_now - bureau_3m),
            "bureau_external_dpd_max": ext_dpd,
            "external_obligations_change_3m_sar": np.where(
                np.isnan(ext_3m), np.nan, np.maximum(ext_now - ext_3m, 0.0)),
            "bureau_enquiries_3m": _win_sum(self.h_enquiries, 3),
            "bureau_enquiries_6m": _win_sum(self.h_enquiries, 6),
            "broken_promise_count_3m": _win_sum(self.h_broken, 3),
            "autopay_failure_count_3m": _win_sum(self.h_autopay, 3),
            "months_on_book": self.months_on_book_now.astype("float64"),
            "months_to_balloon": self.months_to_balloon_now,
            "ltv_current_ratio": ltv_current,
            "behaviour_history_months_available": depth.astype("float64"),
        })
        self.thin_history = thin
        return df

    def _behavioural_scores(self, sources: pd.DataFrame) -> pd.DataFrame:
        """Behavioural score per facility, from its product's configured model.

        A facility with fewer than three months of observed behaviour is NOT
        scored. Thin history is a distinct state from a low score, and the row
        says which one it is.
        """
        pieces: list[pd.DataFrame] = []
        for product, sc in BEHAVIOURAL_SCORECARDS.items():
            mask = (self.fac.product_code == product) & self.active_now & ~self.thin_history
            if not mask.any():
                continue
            sub = sc.score_frame(sources.loc[mask])
            sub["beh_model_id"] = sc.model_id
            sub["beh_model_version"] = sc.model_version
            sub["beh_transform_version"] = sc.transform_version
            sub["beh_target_definition_id"] = sc.target_definition_id
            pieces.append(sub)
        if not pieces:
            return pd.DataFrame(index=sources.index)
        out = pd.concat(pieces, axis=0).reindex(sources.index)
        for c in behavioural_columns():
            if c not in out.columns:
                out[c] = np.nan
        return out

    # -- IFRS 9 -------------------------------------------------------------

    def _risk_and_ecl(self, t: int, sources: pd.DataFrame, beh: pd.DataFrame) -> pd.DataFrame:
        """PD term structures, staging and scenario ECL for this month."""
        cfg, st, fac = self.cfg, self.state, self.fac
        n = fac.n
        is_card = fac.product_code == tax.CREDIT_CARD
        secured = np.isin(fac.product_code, list(tax.SECURED_PRODUCTS))
        cyc = self.cycle[t]

        gca = np.round(st.balance + st.accrued, 2)
        mrate = ecl_mod.monthly_rate(fac.nominal_rate)

        # --- which model PD feeds IFRS 9, through a stated mapping ---------
        pd_beh = pd.to_numeric(beh.get("beh_predicted_pd_12m", pd.Series(np.nan, index=sources.index))
                               ).to_numpy(dtype="float64")
        pd_app = pd.to_numeric(self.app["app_predicted_pd_12m"]).to_numpy(dtype="float64")
        pd_source = np.where(np.isnan(pd_beh), pd_app, pd_beh)
        pd_source_label = np.where(np.isnan(pd_beh), "APPLICATION_MODEL", "BEHAVIOURAL_MODEL")

        logit_ttc = IFRS9_PD_MAP_A + IFRS9_PD_MAP_B * _logit(pd_source)
        pd_ttc_12m = _sigmoid(logit_ttc)
        pd_pit_12m_base_raw = _sigmoid(logit_ttc + PIT_CYCLE_KAPPA * cyc)

        logit_ttc_orig = IFRS9_PD_MAP_A + IFRS9_PD_MAP_B * _logit(pd_app)
        pd_ttc_orig_12m = _sigmoid(logit_ttc_orig)
        pd_pit_orig_12m = _sigmoid(logit_ttc_orig)

        # --- horizons -------------------------------------------------------
        revolving_life = int(cfg.ecl["revolving_behavioural_life_months"])
        contractual_remaining = np.maximum(
            fac.original_tenor_months - self.months_on_book_now, 1)
        remaining_life = np.where(is_card, revolving_life, contractual_remaining)
        remaining_life = np.clip(remaining_life, 1, ecl_mod.LIFETIME_HORIZON_CAP_MONTHS)
        n_months = int(remaining_life.max()) if n else 1
        n_months = max(n_months, 12)

        # --- EAD path -------------------------------------------------------
        k = np.arange(1, n_months + 1)[None, :].astype("float64")
        undrawn = np.where(is_card, np.maximum(st.limit - st.balance, 0.0), 0.0)
        ccf_base = np.where(is_card, 0.45, np.nan)
        amort_path = _amortised_balance(
            gca[:, None] * np.ones((1, n_months)),
            mrate[:, None] * np.ones((1, n_months)),
            np.maximum(contractual_remaining, 1)[:, None] * np.ones((1, n_months)),
            k * np.ones((n, 1)),
        )
        card_path = (st.balance + np.nan_to_num(ccf_base, nan=0.0) * undrawn)[:, None] * np.ones((1, n_months))
        ead_path_base = np.where(is_card[:, None], card_path, amort_path)

        # --- hazard ---------------------------------------------------------
        hazard_base = ecl_mod.seasoned_hazard_path(
            pd_pit_12m_base_raw, self.months_on_book_now.astype("float64"), n_months)

        # --- LGD from recovery inputs ---------------------------------------
        sale_cost = np.where(
            fac.product_code == tax.AUTO_LOAN, RECOVERY_POLICY.expected_sale_cost_ratio[tax.AUTO_LOAN],
            np.where(fac.product_code == tax.HOME_LOAN,
                     RECOVERY_POLICY.expected_sale_cost_ratio[tax.HOME_LOAN], np.nan))
        delay = np.select(
            [fac.product_code == tax.AUTO_LOAN, fac.product_code == tax.HOME_LOAN],
            [RECOVERY_POLICY.recovery_delay_months[tax.AUTO_LOAN],
             RECOVERY_POLICY.recovery_delay_months[tax.HOME_LOAN]],
            default=8,
        ).astype("float64")
        rr_secured = np.clip(
            st.collateral_current * (1.0 - np.nan_to_num(sale_cost, nan=0.1))
            / np.maximum(gca, 1.0), 0.0, 1.0)
        rr_unsecured = np.where(is_card, 1.0 - RECOVERY_POLICY.unsecured_lgd[tax.CREDIT_CARD],
                                1.0 - RECOVERY_POLICY.unsecured_lgd[tax.PERSONAL_LOAN])
        recovery_rate_nominal = np.where(secured, rr_secured, rr_unsecured)

        # --- staging, computed from the base scenario ------------------------
        _, marg_base = ecl_mod.survival_and_marginal(hazard_base)
        pd_life_base = ecl_mod.cumulative_pd(marg_base, remaining_life)
        pd12_base = ecl_mod.cumulative_pd(marg_base, np.minimum(remaining_life, 12))

        hazard_orig = ecl_mod.seasoned_hazard_path(
            pd_pit_orig_12m, np.zeros(n), n_months)
        _, marg_orig = ecl_mod.survival_and_marginal(hazard_orig)
        pd_orig_remaining = ecl_mod.cumulative_pd(marg_orig, remaining_life)

        sicr_ratio = np.where(pd_orig_remaining > 0,
                              pd_life_base / np.where(pd_orig_remaining > 0, pd_orig_remaining, 1.0),
                              np.nan)
        sicr_abs = pd_life_base - pd_orig_remaining

        beh_score = pd.to_numeric(beh.get("beh_score_value", pd.Series(np.nan, index=sources.index))
                                  ).to_numpy(dtype="float64")
        beh_drop = np.where(np.isnan(st.behavioural_score_prev) | np.isnan(beh_score), np.nan,
                            st.behavioural_score_prev - beh_score)
        missed_6m = pd.to_numeric(sources["missed_payment_count_6m"]).fillna(0).to_numpy()
        watch = (self.dpd_now >= 1) | (
            pd.to_numeric(sources["salary_missed_cycle_count_3m"]).fillna(0).to_numpy() >= 1)

        sicr_quant = (
            ((~np.isnan(sicr_ratio)) & (sicr_ratio >= STAGING_POLICY.sicr_pd_ratio_threshold))
            | (sicr_abs >= STAGING_POLICY.sicr_pd_absolute_threshold)
        )
        sicr_qual = (
            (st.forbearance_flag & STAGING_POLICY.forbearance_is_sicr)
            | (missed_6m >= STAGING_POLICY.missed_payments_6m_sicr_threshold)
            | ((~np.isnan(beh_drop)) & (beh_drop >= STAGING_POLICY.behavioural_drop_sicr_threshold) & watch)
        )
        sicr_backstop = self.dpd_now >= STAGING_POLICY.stage2_dpd_backstop
        sicr = sicr_quant | sicr_qual | sicr_backstop

        stage = np.where(st.default_flag, 3, np.where(sicr, 2, 1)).astype("int64")

        sicr_reason = np.select(
            [st.default_flag, sicr_backstop, sicr_quant, st.forbearance_flag,
             missed_6m >= STAGING_POLICY.missed_payments_6m_sicr_threshold, sicr_qual],
            ["Credit-impaired: 90+ DPD or recorded unlikeliness to pay",
             f"DPD backstop at {STAGING_POLICY.stage2_dpd_backstop} days",
             "Quantitative SICR against the origination remaining-life PD reference",
             "Qualitative SICR: forbearance granted",
             "Qualitative SICR: repeated missed payments in six months",
             "Qualitative SICR: behavioural deterioration with a watch condition"],
            default=None,
        ).astype(object)

        # --- ECL per scenario ------------------------------------------------
        scen = cfg.scenarios
        results: dict[str, ecl_mod.EclResult] = {}
        pd12_s: dict[str, np.ndarray] = {}
        pdlife_s: dict[str, np.ndarray] = {}
        lgd_s: dict[str, np.ndarray] = {}
        ead_s: dict[str, np.ndarray] = {}
        ccf_s: dict[str, np.ndarray] = {}

        base_lgd = ecl_mod.lgd_from_recovery(
            recovery_rate_nominal, delay, mrate,
            floor=RECOVERY_POLICY.lgd_floor, cap=RECOVERY_POLICY.lgd_cap)

        for s in ecl_mod.SCENARIOS:
            hz = np.clip(hazard_base * scen.hazard_multiplier[s], 0.0, 1.0)
            lgd = np.clip(base_lgd * scen.lgd_multiplier[s],
                          RECOVERY_POLICY.lgd_floor, RECOVERY_POLICY.lgd_cap)
            ead_path = ead_path_base * scen.ead_multiplier[s]
            s3_delay = np.maximum(delay + scen.recovery_delay_add_months[s], 0.0)
            res = ecl_mod.compute_ecl(ecl_mod.EclInputs(
                stage=stage, ead_path=ead_path, hazard_path=hz, lgd=lgd,
                monthly_discount_rate=mrate, remaining_life_months=remaining_life,
                gross_carrying_amount=gca,
                stage3_recovery_rate_nominal=recovery_rate_nominal,
                stage3_delay_months=s3_delay,
            ))
            results[s] = res
            pd12_s[s] = res.pd_12m
            pdlife_s[s] = res.pd_lifetime
            lgd_s[s] = res.lgd
            ead_s[s] = res.ead
            ccf_s[s] = np.where(is_card, 0.45 * scen.ead_multiplier[s], np.nan)

        # Round each scenario ECL to the halala FIRST, then weight the rounded
        # values. Weighting the unrounded ones and rounding the answer would
        # leave the published identity — weight * each published scenario ECL —
        # failing by a fraction of a halala on every row, and by a real number of
        # riyals once twenty thousand rows are added up. The identity a reader
        # can check must hold on the numbers they can see.
        # Precision, stated once. Each SCENARIO ECL is published rounded to the
        # halala, because that is the figure a reader quotes. The weighted and
        # final allowance are then the exact weighted combination OF THOSE
        # PUBLISHED VALUES, carried at full precision and rounded only for
        # display — so the identity a reader can check on screen holds exactly
        # rather than to within a rounding error that becomes real riyals once
        # twenty thousand rows are added up.
        ecl_by_scen = {s: np.round(results[s].ecl, 2) for s in ecl_mod.SCENARIOS}
        weighted = ecl_mod.weighted_ecl(ecl_by_scen, scen.weights)
        overlay = np.full(n, float(cfg.ecl["management_overlay_sar"]))
        final = ecl_mod.final_ecl(weighted, overlay)

        self.behavioural_score_previous_month = st.behavioural_score_prev.copy()
        st.behavioural_score_prev = np.where(np.isnan(beh_score), st.behavioural_score_prev, beh_score)
        _push(self.h_behscore, np.where(self.active_now, beh_score, np.nan))
        st.stage_entry_idx = np.where(stage != st.stage_prev, t, st.stage_entry_idx)
        self.stage_now = stage

        out = pd.DataFrame({
            "gross_carrying_amount_sar": gca,
            "ifrs9_stage": stage,
            "previous_month_stage": st.stage_prev,
            "staging_policy_version": STAGING_POLICY.version,
            "sicr_flag": sicr,
            "sicr_reason": sicr_reason,
            "sicr_quantitative_flag": sicr_quant,
            "sicr_qualitative_flag": sicr_qual,
            "sicr_dpd_backstop_flag": sicr_backstop,
            "stage_override_flag": False,
            "stage_override_reason": None,
            "default_definition_id": DEFAULT_DEFINITION_ID,
            "credit_risk_model_id": "RETAIL_IFRS9_DEMO",
            "pd_model_version": ecl_mod.PD_MODEL_VERSION,
            "lgd_model_version": ecl_mod.LGD_MODEL_VERSION,
            "ead_model_version": ecl_mod.EAD_MODEL_VERSION,
            "ecl_model_version": ecl_mod.ECL_MODEL_VERSION,
            "ifrs9_pd_source_model": pd_source_label,
            "ifrs9_pd_mapping_version": SCORE_TO_IFRS9_PD_MAPPING_VERSION,
            "pd_ttc_12m": pd_ttc_12m,
            # The hazard ANCHOR: the 12-month PIT probability the monthly hazard
            # path was built from, before seasoning. Stored so What-If can
            # rebuild the identical curve and reproduce the baseline exactly,
            # rather than approximating it from a cumulative result.
            "pd_pit_12m_anchor": pd_pit_12m_base_raw,
            "monthly_discount_rate": mrate,
            "ecl_remaining_life_months": remaining_life,
            "ecl_contractual_remaining_months": contractual_remaining,
            "ecl_undrawn_commitment_sar": undrawn,
            "ecl_drawn_balance_sar": st.balance,
            "pd_ttc_at_origination_12m": pd_ttc_orig_12m,
            "pd_pit_at_origination_12m": pd_pit_orig_12m,
            "pd_origination_curve_remaining_life": pd_orig_remaining,
            "sicr_pd_ratio": sicr_ratio,
            "sicr_pd_absolute_change": sicr_abs,
            "pd_pit_12m_base": pd12_s["base"],
            "pd_pit_12m_upturn": pd12_s["upturn"],
            "pd_pit_12m_downturn": pd12_s["downturn"],
            "pd_pit_lifetime_base": pdlife_s["base"],
            "pd_pit_lifetime_upturn": pdlife_s["upturn"],
            "pd_pit_lifetime_downturn": pdlife_s["downturn"],
            "lgd_base": lgd_s["base"],
            "lgd_upturn": lgd_s["upturn"],
            "lgd_downturn": lgd_s["downturn"],
            "ead_base_sar": ead_s["base"],
            "ead_upturn_sar": ead_s["upturn"],
            "ead_downturn_sar": ead_s["downturn"],
            "ccf_base": ccf_s["base"],
            "ccf_upturn": ccf_s["upturn"],
            "ccf_downturn": ccf_s["downturn"],
            "scenario_weight_base": scen.weights["base"],
            "scenario_weight_upturn": scen.weights["upturn"],
            "scenario_weight_downturn": scen.weights["downturn"],
            "ecl_base_sar": ecl_by_scen["base"],
            "ecl_upturn_sar": ecl_by_scen["upturn"],
            "ecl_downturn_sar": ecl_by_scen["downturn"],
            "ecl_weighted_sar": weighted,
            "management_overlay_sar": overlay,
            "ecl_final_sar": final,
            "ecl_coverage_ratio": ecl_mod.coverage_ratio(final, gca),
            "allowance_scope": "FACILITY_LEVEL_LOSS_ALLOWANCE",
            "ecl_horizon_type": results["base"].horizon_type,
            "ecl_horizon_months": results["base"].horizon_months,
            "ecl_expected_life_months": remaining_life,
            "behavioural_expected_life_months": np.where(is_card, revolving_life, np.nan),
            "recovery_rate_nominal": recovery_rate_nominal,
            "recovery_delay_months": delay,
            "expected_sale_cost_ratio": sale_cost,
            "scenario_set_id": scen.scenario_set_id,
            "scenario_set_version": scen.scenario_set_version,
            "pd_curve_id": f"RETAIL_PD_CURVE_{ecl_mod.PD_MODEL_VERSION}",
            "lgd_curve_id": f"RETAIL_LGD_{ecl_mod.LGD_MODEL_VERSION}",
            "ead_curve_id": f"RETAIL_EAD_{ecl_mod.EAD_MODEL_VERSION}",
            "recovery_cashflow_ref": RECOVERY_POLICY.version,
            "discount_method": str(cfg.ecl["discount_method"]),
            "effective_annual_interest_rate": fac.nominal_rate,
            "calculation_method_label": (
                "Transparent monthly-hazard demonstration engine; not an approved "
                "accounting model"
            ),
        }, index=sources.index)
        return out

    # -- the canonical row --------------------------------------------------

    def _month_frame(
        self, t: int, sources: pd.DataFrame, beh: pd.DataFrame, risk: pd.DataFrame,
        dataset_version: str,
    ) -> pd.DataFrame:
        """One wide, joined row per live facility for this month-end."""
        cfg, st, fac, cust = self.cfg, self.state, self.fac, self.cust
        snap = self.dates[t]
        ci = fac.customer_index
        n = fac.n
        is_card = fac.product_code == tax.CREDIT_CARD
        is_auto = fac.product_code == tax.AUTO_LOAN
        is_home = fac.product_code == tax.HOME_LOAN
        secured = np.isin(fac.product_code, list(tax.SECURED_PRODUCTS))
        amortising = ~is_card

        growth = (1.0 + INCOME_GROWTH_MONTHLY) ** t
        salary = np.round(cust.base_salary_sar[ci] * growth, 2)
        other = np.round(cust.other_income_sar[ci] * growth, 2)
        income = salary + other
        expenses = np.round(cust.household_expenses_sar[ci] * growth, 2)
        external_ob = np.round(self.cust_external_obligations[ci], 2)

        # Own-bank obligations: this customer's live scheduled instalments,
        # summed once across their facilities.
        own_bank = pd.Series(np.where(self.active_now, st.scheduled_payment, 0.0)).groupby(
            pd.Series(ci)).transform("sum").to_numpy()
        total_ob = np.round(own_bank + external_ob, 2)
        disposable = np.round(income - expenses - total_ob, 2)
        dbr = np.where(income > 0, total_ob / np.where(income > 0, income, 1.0), np.nan)

        orig_month_index = fac.origination_month_index
        orig_date = np.array([
            _add_months(self.dates[0], int(m)) if m >= 0 else _add_months(self.dates[0], int(m))
            for m in orig_month_index
        ], dtype=object)
        maturity = np.array([
            _add_months(od, int(tn)) if tn > 0 else None
            for od, tn in zip(orig_date, fac.original_tenor_months)
        ], dtype=object)

        gca = risk["gross_carrying_amount_sar"].to_numpy()
        undrawn = np.where(is_card, np.maximum(st.limit - st.balance, 0.0), np.nan)

        oldest_unpaid = np.array([
            _add_months(snap, -int(a)) if a > 0 else None for a in st.arrears_months
        ], dtype=object)

        first_default_date = np.array([
            self.dates[i] if i >= 0 else None for i in st.first_default_idx], dtype=object)
        latest_default_date = np.array([
            self.dates[i] if i >= 0 else None for i in st.latest_default_idx], dtype=object)
        cure_date = np.array([
            self.dates[i] if i >= 0 else None for i in st.cure_idx], dtype=object)
        forb_date = np.array([
            self.dates[i] if i >= 0 else None for i in st.forbearance_idx], dtype=object)
        closure_date = np.array([
            self.dates[i] if 0 <= i <= t else None for i in st.closed_idx], dtype=object)

        util = st.utilisation
        base = pd.DataFrame({
            # --- identity, provenance, lifecycle -------------------------
            "snapshot_date": snap,
            "reporting_month": f"{snap.year:04d}-{snap.month:02d}",
            "dataset_version": dataset_version,
            "record_id": [f"{snap.isoformat()}|{f}" for f in fac.facility_id],
            "customer_id": cust.customer_id[ci],
            "facility_id": fac.facility_id,
            "application_id": fac.application_id,
            "product_code": fac.product_code,
            "product_label": np.array([tax.PRODUCT_LABELS[p] for p in fac.product_code], dtype=object),
            "product_subsegment": np.where(
                is_card, "CARD", np.where(fac.purpose != None, fac.purpose,  # noqa: E711
                                          np.where(is_auto, fac.vehicle_new_used, "STANDARD"))),
            "portfolio_country": cfg.portfolio_country,
            "currency": cfg.currency,
            "customer_relationship_start_date": np.array([
                _add_months(self.dates[0], int(m)) for m in cust.relationship_start_month_index[ci]
            ], dtype=object),
            "customer_tenure_months": (t - cust.relationship_start_month_index[ci]).astype("int64"),
            "application_date": np.array([_add_months(d, -1) for d in orig_date], dtype=object),
            "approval_date": orig_date,
            "origination_date": orig_date,
            "origination_vintage": np.array([f"{d.year:04d}-{d.month:02d}" for d in orig_date],
                                            dtype=object),
            "contractual_maturity_date": maturity,
            "original_tenor_months": np.where(amortising, fac.original_tenor_months, np.nan),
            "remaining_contractual_tenor_months": np.where(
                amortising, np.maximum(fac.original_tenor_months - self.months_on_book_now, 0), np.nan),
            "months_on_book": self.months_on_book_now.astype("int64"),
            "facility_status": np.where(st.closed_idx == t, "CLOSED", "OPEN"),
            "closure_date": closure_date,
            "closure_reason": st.closure_reason,
            "refinanced_from_facility_id": None,
            "restructured_flag": st.restructured_flag,
            "restructure_date": forb_date,
            "source_system": "RETAIL_SYNTHETIC_GENERATOR",
            "source_record_id": [f"GEN|{f}|{snap.isoformat()}" for f in fac.facility_id],
            "source_available_at": snap,
            "is_synthetic": True,
            "generator_version": cfg.generator_version,
            "data_quality_status": np.where(self.thin_history, "THIN_HISTORY", "OK"),
            "customer_scope": "NATURAL_PERSON_RETAIL",
            "score_subject_grain": "FACILITY",

            # --- customer, employment, affordability ----------------------
            "region": cust.region[ci],
            "region_label": np.array([tax.REGION_LABELS[r] for r in cust.region[ci]], dtype=object),
            "city": cust.city[ci],
            "branch_id": cust.branch_id[ci],
            "origination_channel": fac.channel,
            "customer_segment": cust.segment[ci],
            "new_to_bank_at_origination_flag": fac.new_to_bank,
            "residency_category": cust.residency[ci],
            "age_band": cust.age_band[ci],
            "dependants_band": cust.dependants_band[ci],
            "employment_status": cust.employment_status[ci],
            "employer_id": cust.employer_id[ci],
            "employer_sector": cust.employer_sector[ci],
            "employment_tenure_months": np.clip(
                cust.employment_tenure_months_at_start[ci] + t, 1, 600).astype("int64"),
            "salary_transfer_flag": cust.salary_transfer[ci],
            "salary_verification_status": np.where(cust.salary_transfer[ci], "VERIFIED_TRANSFER",
                                                   "DECLARED_DOCUMENTED"),
            "verified_monthly_salary_sar": salary,
            "verified_other_monthly_income_sar": other,
            "verified_total_monthly_income_sar": income,
            "household_expenses_sar": expenses,
            "monthly_external_credit_obligations_sar": external_ob,
            "monthly_own_bank_credit_obligations_sar": np.round(own_bank, 2),
            "monthly_total_credit_obligations_sar": total_ob,
            "obligation_scope_definition": AFFORDABILITY_POLICY.obligation_scope_definition,
            "disposable_income_sar": disposable,
            "debt_burden_ratio": dbr,
            "affordability_buffer_sar": np.round(disposable, 2),
            "income_band": np.array([tax.INCOME_BAND_SPEC.band_of(v) for v in income], dtype=object),
            "indebtedness_band": np.array([tax.INDEBTEDNESS_BAND_SPEC.band_of(v) for v in dbr],
                                          dtype=object),
            "policy_version_at_origination": CUTOFF_POLICY.version,
            "policy_exception_flag": self.policy_exception,
            "policy_exception_reason": np.where(
                self.policy_exception, "Booked below the application-score cutoff on a documented "
                                       "synthetic demo exception", None),
            "score_override_flag": self.policy_exception,
            "score_override_direction": np.where(self.policy_exception, "UP", None),
            "score_override_reason": np.where(
                self.policy_exception, "Documented synthetic demo exception at origination", None),
            "applied_score_cutoff": self.applied_cutoff,
            "decision_at_origination": "APPROVED",
            "employment_change_flag": self.employment_change[ci],
            "job_loss_reported_flag": self.job_loss_reported[ci],
            "job_loss_signal_source": np.where(
                self.job_loss_reported[ci], "SYNTHETIC_CUSTOMER_DECLARATION", None),

            # --- balances, terms, collateral -------------------------------
            "original_finance_amount_sar": np.where(amortising, fac.original_amount, np.nan),
            "original_credit_limit_sar": np.where(is_card, fac.original_limit, np.nan),
            "current_credit_limit_sar": np.where(is_card, st.limit, np.nan),
            "outstanding_principal_sar": np.round(st.balance, 2),
            "accrued_profit_interest_sar": np.round(st.accrued, 2),
            "undrawn_commitment_sar": undrawn,
            "available_limit_sar": undrawn,
            "scheduled_monthly_payment_sar": np.where(amortising, st.scheduled_payment, np.nan),
            "scheduled_payment_due_sar": np.round(self.due_now, 2),
            "actual_payment_received_sar": np.round(self.paid_now, 2),
            "principal_repayment_sar": np.round(self.principal_repaid_now, 2),
            "new_drawdown_sar": np.round(self.new_drawdown_now, 2),
            "accrued_charges_sar": np.round(self.interest_now, 2),
            "capitalised_amount_sar": 0.0,
            "writeoff_amount_month_sar": np.round(st.writeoff_month_amount, 2),
            "recovery_amount_month_sar": np.round(st.recovery_month_amount, 2),
            "other_balance_adjustment_sar": 0.0,
            "nominal_annual_profit_interest_rate": fac.nominal_rate,
            "rate_type": fac.rate_type,
            "contract_structure": fac.contract_structure,
            "secured_flag": secured,
            "collateral_type": np.where(is_auto, "VEHICLE", np.where(is_home, "RESIDENTIAL_PROPERTY", None)),
            "collateral_value_origination_sar": np.where(secured, fac.collateral_value_origination, np.nan),
            "collateral_value_current_sar": np.where(secured, np.round(st.collateral_current, 2), np.nan),
            "collateral_valuation_date": np.where(secured, snap, None),
            "vehicle_new_used": fac.vehicle_new_used,
            "vehicle_age_months": np.where(is_auto, fac.vehicle_age_months + self.months_on_book_now, np.nan),
            "dealer_id": fac.dealer_id,
            "down_payment_sar": fac.down_payment,
            "balloon_payment_sar": fac.balloon_payment,
            "balloon_due_date": np.where(is_auto & (np.nan_to_num(fac.balloon_payment) > 0), maturity, None),
            "housing_support_flag": np.where(is_home, fac.housing_support == "SYNTHETIC_SUPPORTED_PROGRAMME", None),
            "housing_support_type": fac.housing_support,
            "property_type": fac.property_type,
            "home_purpose": np.where(is_home, fac.purpose, None),
            "auto_structure": np.where(is_auto, fac.contract_structure, None),

            # --- delinquency and collections --------------------------------
            "previous_month_dpd": np.where(np.isnan(self.h_dpd[:, -2]), np.nan, self.h_dpd[:, -2]),
            "dpd_bucket": np.array([tax.DPD_BUCKET_SPEC.band_of(v) for v in self.dpd_now], dtype=object),
            "overdue_amount_sar": np.round(st.overdue, 2),
            "oldest_unpaid_due_date": oldest_unpaid,
            "current_default_flag": st.default_flag,
            "first_default_date": first_default_date,
            "latest_default_date": latest_default_date,
            "default_reason": np.where(
                st.default_flag,
                np.where(self.dpd_now >= STAGING_POLICY.stage3_dpd_backstop,
                         "NINETY_DAYS_PAST_DUE", "UNLIKELINESS_TO_PAY"), None),
            "default_episode_id": np.where(st.default_episode > 0,
                                           np.array([f"DEF-{f}-{e}" for f, e
                                                     in zip(fac.facility_id, st.default_episode)],
                                                    dtype=object), None),
            "credit_impaired_flag": st.default_flag,
            "unlikeliness_to_pay_flag": st.default_flag & (self.dpd_now < STAGING_POLICY.stage3_dpd_backstop),
            "forbearance_flag": st.forbearance_flag,
            "forbearance_start_date": forb_date,
            "cure_flag": st.cure_flag,
            "cure_date": cure_date,
            "cure_probation_months": STAGING_POLICY.cure_probation_months,
            "writeoff_flag": st.writeoff_flag,
            "cumulative_writeoff_sar": np.round(st.cumulative_writeoff, 2),
            "collections_stage": np.array([tax.COLLECTIONS_STAGES[i] for i in st.collections_stage],
                                          dtype=object),
            "contact_attempts_3m": np.minimum(st.contact_attempts, 12).astype("int64"),
            "promise_to_pay_flag": st.promise_flag,
            "promise_to_pay_due_date": np.where(st.promise_flag, _add_months(snap, 1), None),
            "days_30plus_count_12m": _nan_count_ge(self.h_dpd, 12, 30).astype("float64"),
            "months_30plus_count_12m": _nan_count_ge(self.h_dpd, 12, 30).astype("float64"),
            "full_payment_months_6m": np.nansum(
                (_tail(self.h_paid, 6) >= _tail(self.h_due, 6)) & ~np.isnan(_tail(self.h_due, 6)), axis=1
            ).astype("float64"),
            "card_behaviour_segment": np.where(
                ~is_card, None,
                np.where(np.nan_to_num(util, nan=0.0) < 0.02, "INACTIVE",
                         np.where(np.nan_to_num(
                             pd.to_numeric(sources["minimum_payment_only_months_3m"]).fillna(0).to_numpy()
                         ) >= 2, "REVOLVER", "TRANSACTOR"))),
            "utilisation_band": np.array(
                [tax.UTILISATION_BAND_SPEC.band_of(v) if v == v else None for v in util], dtype=object),
            "ltv_band": np.array(
                [tax.LTV_BAND_SPEC.band_of(v) for v in
                 pd.to_numeric(sources["ltv_current_ratio"]).to_numpy()], dtype=object),
            "down_payment_band": np.where(
                is_auto, np.array([
                    tax.BandSpec("d", tax.DOWN_PAYMENT_BANDS, (0.10, 0.20, 0.30)).band_of(v)
                    for v in np.where(fac.collateral_value_origination > 0,
                                      np.nan_to_num(fac.down_payment, nan=0.0)
                                      / np.maximum(fac.collateral_value_origination, 1.0), np.nan)
                ], dtype=object), None),
            "balloon_band": np.where(
                is_auto, np.array([
                    "NONE" if (v == 0) else tax.BandSpec("b", tax.BALLOON_BANDS[1:], (0.20, 0.35)).band_of(v)
                    for v in np.nan_to_num(
                        pd.to_numeric(self.orig["origination_balloon_ratio"]).to_numpy(), nan=0.0)
                ], dtype=object), None),

            # --- bureau -------------------------------------------------------
            "bureau_score_origination_date": orig_date,
            "bureau_score_current_date": snap,
            "bureau_score_scale_id": BUREAU_SCALE_ID,
            "bureau_active_facilities_count": pd.to_numeric(
                self.orig["origination_bureau_active_facilities"]).to_numpy(),
            "bureau_total_exposure_sar": np.round(external_ob * 24.0, 2),
            "bureau_adverse_flag": pd.to_numeric(sources["bureau_external_dpd_max"]).fillna(0).to_numpy() >= 30,
            "bureau_thin_file_flag": self.orig["bureau_thin_file_flag"].to_numpy(),
            "bureau_data_available_flag": ~np.isnan(st.bureau_score),
            "bureau_source_label": BUREAU_SOURCE_LABEL,
            "bureau_data_freshness_days": 15,
            "salary_credit_last_date": np.array([
                snap if v > 0 else None for v in np.nan_to_num(self.h_salary[ci][:, -1], nan=0.0)
            ], dtype=object),
            "expected_salary_credit_date": snap,
            "salary_delay_days": np.where(self.h_salary_missed[ci][:, -1] > 0, 30, 0),
            "account_inflows_1m_sar": np.round(self.h_salary[ci][:, -1], 2),
            "account_outflows_1m_sar": np.round(expenses + total_ob, 2),

            # --- score status -----------------------------------------------
            "application_score_date": orig_date,
            "application_score_direction": "HIGHER_IS_SAFER",
            "application_score_status": "SCORED_AT_ORIGINATION",
            "application_score_reconciled_flag": True,
            "behavioural_score_date": snap,
            "behavioural_score_direction": "HIGHER_IS_SAFER",
            "behavioural_score_status": np.where(self.thin_history, "NOT_SCORED_THIN_HISTORY", "SCORED"),
            "behavioural_score_reconciled_flag": ~self.thin_history,
            "score_implementation_check_status": "PASS",
            "score_evidence_ref": [f"SCORE|{f}|{snap.isoformat()}" for f in fac.facility_id],
            "calculation_run_id": f"RETAIL-RUN-{dataset_version}-{snap.isoformat()}",
            "calculation_available_at": snap,
        }, index=sources.index)

        beh_score = pd.to_numeric(
            beh.get("beh_score_value", pd.Series(np.nan, index=sources.index)),
            errors="coerce").to_numpy(dtype="float64")
        beh_prev = getattr(self, "behavioural_score_previous_month", np.full(n, np.nan))
        beh_3m_ago = self.h_behscore[:, -4] if HISTORY_MONTHS >= 4 else np.full(n, np.nan)

        # The specification names several fields that the scoring engine emits
        # under its own prefixed names. Both are kept: the prefixed columns are
        # the model's own output, and these are the canonical dictionary names
        # every module, blueprint and export reads.
        aliases = pd.DataFrame({
            "application_score_at_origination": pd.to_numeric(
                self.app["app_score_value"], errors="coerce").to_numpy(),
            "application_score_model_id": self.app.get("app_model_id"),
            "application_score_model_version": self.app.get("app_model_version"),
            "application_score_band": self.app.get("app_score_band_value"),
            "application_predicted_pd_12m": pd.to_numeric(
                self.app["app_predicted_pd_12m"], errors="coerce").to_numpy(),
            "application_transform_version": self.app.get("app_transform_version"),
            "behavioural_score": beh_score,
            "behavioural_score_model_id": beh.get("beh_model_id"),
            "behavioural_score_model_version": beh.get("beh_model_version"),
            "behavioural_score_band": beh.get("beh_score_band_value"),
            "behavioural_predicted_pd_12m": pd.to_numeric(
                beh.get("beh_predicted_pd_12m", pd.Series(np.nan, index=sources.index)),
                errors="coerce").to_numpy(),
            "behavioural_transform_version": beh.get("beh_transform_version"),
            "behavioural_score_previous_month": beh_prev,
            "behavioural_score_change_3m": np.where(
                np.isnan(beh_3m_ago) | np.isnan(beh_score), np.nan, beh_score - beh_3m_ago),
            "score_input_missing_count": (
                pd.to_numeric(self.app.get("app_input_missing_count"), errors="coerce").fillna(0).to_numpy()
                + pd.to_numeric(beh.get("beh_input_missing_count", pd.Series(0, index=sources.index)),
                                errors="coerce").fillna(0).to_numpy()),
            "score_input_stale_count": np.where(self.thin_history, 1, 0),
            "returned_payment_count_3m": pd.to_numeric(
                sources["autopay_failure_count_3m"], errors="coerce").to_numpy(),
            "stage_entry_date": np.array([
                self.dates[i] if i >= 0 else None for i in st.stage_entry_idx], dtype=object),
            "calculation_input_hash": [
                hashlib.sha256(f"{fid}|{snap.isoformat()}|{dataset_version}".encode()).hexdigest()[:32]
                for fid in fac.facility_id
            ],
        }, index=sources.index)

        frame = pd.concat([base, sources, self.app, beh, aliases, self.orig.drop(
            columns=["facility_id", "application_id", "scheduled_monthly_payment_sar",
                     "bureau_thin_file_flag"]), risk], axis=1)
        frame = frame.loc[:, ~frame.columns.duplicated()]
        return frame.loc[self.active_now].reset_index(drop=True)

    # -- the run ------------------------------------------------------------

    def run(self, dataset_version: str) -> Iterator[tuple[int, date, pd.DataFrame]]:
        """Advance the whole book, yielding only the published month-ends."""
        self.prepare()
        for t in range(self.n_all):
            self._customer_month(t)
            self._activate(t)
            self._facility_month(t)
            self._push_history(t)
            sources = self._behavioural_sources(t)
            beh = self._behavioural_scores(sources)
            risk = self._risk_and_ecl(t, sources, beh)
            if t >= self.first_published_index:
                frame = self._month_frame(t, sources, beh, risk, dataset_version)
                frame = pd.concat(
                    [frame, pd.DataFrame({"_facility_row": np.where(self.active_now)[0]},
                                         index=frame.index)],
                    axis=1)
                yield t, self.dates[t], frame
            self.state.stage_prev = self.stage_now


# ==========================================================================
# Outcome labelling — evaluation labels, never predictors
# ==========================================================================

def _outcome_columns(
    sim: RetailSimulation, t: int, rows: np.ndarray, monitoring_as_of: date,
) -> pd.DataFrame:
    """Forward-looking labels for a snapshot, with their maturity stated.

    These are EVALUATION labels. They carry `outcome_known_at`, and the
    operational prediction views exclude them, because a feature that knows how
    the next year turned out is not a feature.
    """
    n_all = sim.n_all
    horizon = 12
    window_start = t + 1
    window_end = min(t + horizon, n_all - 1)
    observed_followup = max(window_end - t, 0)
    complete = observed_followup >= horizon

    def _seen(matrix: np.ndarray) -> np.ndarray:
        if window_start > window_end:
            return np.zeros(len(rows), dtype=bool)
        return matrix[rows, window_start:window_end + 1].any(axis=1)

    default_seen = _seen(sim.ev_new_default)
    d30_seen = _seen(sim.ev_dpd30)
    d60_seen = _seen(sim.ev_dpd60)

    def _label(seen: np.ndarray) -> np.ndarray:
        # A positive observed inside an incomplete window is still a positive.
        # A negative is only a negative once the whole window has been observed;
        # otherwise it is unknown, and unknown is not "good".
        return np.where(seen, True, np.where(complete, False, None)).astype(object)

    already_default = sim.ev_in_default[rows, t]
    eligible = ~already_default

    return pd.DataFrame({
        "monitoring_as_of_date": monitoring_as_of,
        "prediction_reference_date": sim.dates[t],
        "score_target_definition_id": "retail-first-default-12m-1.0.0",
        "performance_window_months": horizon,
        "performance_window_start": _add_months(sim.dates[t], 1),
        "performance_window_end": _add_months(sim.dates[t], horizon),
        "observed_followup_months": observed_followup,
        "outcome_known_at": _add_months(sim.dates[t], horizon),
        "performance_window_complete_flag": complete,
        "censoring_reason": None if complete else (
            f"Only {observed_followup} of {horizon} follow-up months are observable in this "
            f"25-month history; the window ends after the last published snapshot."
        ),
        "observed_default_within_window": _label(default_seen),
        "observed_30plus_within_window": _label(d30_seen),
        "observed_60plus_within_window": _label(d60_seen),
        "monitoring_eligible_flag": eligible,
        "monitoring_exclusion_reason": np.where(
            already_default, "Already in default at the prediction date", None),
        "monitoring_reference_id": f"MON-{sim.dates[t].isoformat()}",
        "monitoring_reference_type": "MONTHLY_LANDMARK_COHORT",
        "model_use_population": np.where(
            already_default, "DEFAULTED_EXCLUDED_FROM_FORWARD_DEFAULT_MODELS",
            "PERFORMING_ELIGIBLE"),
    })


# ==========================================================================
# Build
# ==========================================================================

def _content_hash(df: pd.DataFrame) -> str:
    """A stable hash of a month's business content, for the manifest."""
    cols = sorted(c for c in df.columns if not c.startswith("_"))
    h = hashlib.sha256()
    for c in cols:
        h.update(c.encode())
        s = df[c]
        if pd.api.types.is_float_dtype(s):
            h.update(np.round(s.to_numpy(dtype="float64"), 6).tobytes())
        else:
            h.update(pd.util.hash_pandas_object(s.astype(str), index=False).to_numpy().tobytes())
    return h.hexdigest()


def build(
    cfg: RetailDemoConfig,
    analytics_dir: Path,
    *,
    dataset_name: str = "retail_facility_month",
    log_progress: bool = True,
) -> dict[str, Any]:
    """Generate the whole book and publish it atomically.

    Writes to a staging directory and swaps it in only once every month has
    passed its checks, so a failed build cannot leave a half-published
    portfolio behind (RET-053).
    """
    cfg.validate()
    rng = np.random.default_rng(cfg.seed)
    dataset_version = f"{cfg.generator_version}+cfg{cfg.config_version}+seed{cfg.seed}"

    target = Path(analytics_dir) / dataset_name
    staging = Path(analytics_dir) / f".{dataset_name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    sim = RetailSimulation(cfg, rng)

    # Two passes, so peak memory is one month rather than twenty-five. The
    # first writes each month as it is simulated; the second adds the forward
    # outcome labels, which cannot exist until the whole history has run.
    staged: list[tuple[int, date, Path]] = []
    for t, snap, frame in sim.run(dataset_version):
        part = staging / f"{PERIOD_FIELD}={snap.year:04d}-{snap.month:02d}"
        part.mkdir(parents=True, exist_ok=True)
        path = part / "data.parquet"
        frame.to_parquet(path, index=False)
        staged.append((t, snap, path))
        if log_progress:
            logger.info("simulated %s: %d live facilities", snap.isoformat(), len(frame))

    monitoring_as_of = cfg.last_snapshot
    months: list[dict[str, Any]] = []
    total_rows = 0
    customers_seen: set[str] = set()
    facilities_seen: set[str] = set()
    column_count = 0

    for t, snap, path in staged:
        frame = pd.read_parquet(path)
        rows = frame.pop("_facility_row").to_numpy()
        outcomes = _outcome_columns(sim, t, rows, monitoring_as_of)
        outcomes.index = frame.index
        frame = pd.concat([frame, outcomes], axis=1)
        frame = frame.loc[:, ~frame.columns.duplicated()]

        _validate_month(frame, snap)
        frame.to_parquet(path, index=False)
        column_count = len(frame.columns)

        total_rows += len(frame)
        customers_seen.update(frame["customer_id"].tolist())
        facilities_seen.update(frame["facility_id"].tolist())
        months.append({
            "reporting_month": f"{snap.year:04d}-{snap.month:02d}",
            "snapshot_date": snap.isoformat(),
            "rows": int(len(frame)),
            "distinct_customers": int(frame["customer_id"].nunique()),
            "distinct_facilities": int(frame["facility_id"].nunique()),
            "products": sorted(frame["product_code"].unique().tolist()),
            "gross_carrying_amount_sar": float(frame["gross_carrying_amount_sar"].sum()),
            "ecl_final_sar": float(frame["ecl_final_sar"].sum()),
            "content_hash": _content_hash(frame),
            "validation_status": "PASSED",
        })
        del frame

    if len(months) != cfg.months:
        raise RuntimeError(
            f"generated {len(months)} months, expected exactly {cfg.months}; "
            "nothing has been published"
        )

    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)

    manifest = {
        **cfg.to_manifest(),
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "column_count": int(column_count),
        "total_rows": total_rows,
        "distinct_customers_all_months": len(customers_seen),
        "distinct_facilities_all_months": len(facilities_seen),
        "applications_generated": sim.application_count,
        "applications_declined_at_cutoff": sim.declined_count,
        "months": months,
        "policy": {
            "staging_policy_version": STAGING_POLICY.version,
            "cutoff_policy_version": CUTOFF_POLICY.version,
            "recovery_policy_version": RECOVERY_POLICY.version,
            "affordability_policy_version": AFFORDABILITY_POLICY.version,
        },
        "lifetime_horizon_cap_months": ecl_mod.LIFETIME_HORIZON_CAP_MONTHS,
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, default=str).encode()).hexdigest()
    return manifest


def _validate_month(frame: pd.DataFrame, snap: date) -> None:
    """Checks that must pass before a month is allowed into the publication."""
    if frame.empty:
        raise RuntimeError(f"{snap}: no rows generated")
    if frame["facility_id"].duplicated().any():
        raise RuntimeError(f"{snap}: duplicate facility_id within one snapshot")
    if frame[["snapshot_date", "customer_id", "facility_id"]].duplicated().any():
        raise RuntimeError(f"{snap}: duplicate primary key")
    numeric = frame.select_dtypes(include=[np.floating])
    bad = numeric.columns[np.isinf(numeric.to_numpy(dtype="float64", na_value=0.0)).any(axis=0)]
    if len(bad):
        raise RuntimeError(f"{snap}: non-finite values in {list(bad)}")
    if (frame["months_on_book"] < 0).any():
        raise RuntimeError(f"{snap}: negative months on book")
    if (frame["gross_carrying_amount_sar"] < 0).any():
        raise RuntimeError(f"{snap}: negative gross carrying amount")
