#!/usr/bin/env python
"""
Generate CreditProbe's Saudi demonstration universe.

    python scripts/generate_saudi_universe.py

What this is
------------
A synthetic Saudi corporate and commercial loan book, large enough and long
enough to demonstrate the whole product honestly:

    portfolio_facility   15 quarters, Q4 2022 to Q2 2026, ~15,000 facilities each
    ifrs9_staging        the same 15 quarters, one row per facility, staging detail
    customer_ratings     8 annual rating cycles, 2018 to 2025, every customer
    borrower_financials  one row per customer, latest two fiscal years
    macro_saudi          34 quarters of Saudi macroeconomic series, 2018 to 2026

Every row is marked SYNTHETIC. None of it describes a real borrower, a real
bank, or a real economy. It exists so that a demonstration of an early-warning
model is a demonstration of a model rather than a slideshow.

Why it is generated rather than sampled
---------------------------------------
The product's central claim is that a forward risk signal can be built from
observable factors. That claim can only be shown on data where deterioration is
genuinely *predictable* — where a facility that migrates from Stage 1 to Stage 2
next quarter was, this quarter, already showing it in its utilisation, its
covenant headroom, its days past due and its sector's exposure to the cycle.

Randomly generated rows would give a model nothing to find, and hand-tuned rows
would give it exactly what somebody decided it should find. So the universe is
SIMULATED instead: every customer carries a latent credit quality that follows a
persistent process driven by a common macroeconomic factor and its sector's
sensitivity to it, and every observable field is a noisy reading of that latent
state. Migrations then fall out of IFRS 9 staging rules applied to the result.
The signal is real, it is nobody's opinion, and a model that finds it has found
something that was actually there.

Determinism
-----------
One seed, no wall-clock, no external calls. The same universe every time, on
every machine, so a figure quoted in a document is the figure a reader sees.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402

SEED = 20260824

#: The reporting periods in the portfolio book.
FIRST_YEAR, FIRST_QUARTER = 2022, 4
N_QUARTERS = 15

#: The annual rating cycles.
RATING_YEARS = list(range(2018, 2026))

#: Macro history, which starts earlier than the book so the rating years have
#: an economic context of their own.
MACRO_FIRST_YEAR = 2018

N_CUSTOMERS = 4_100

DEMO_NOTE = "SYNTHETIC — CreditProbe demonstration data. Not a real portfolio."


def log(msg: str) -> None:
    print(f"  {msg}")


# ============================================================ the periods


def quarters(first_year: int, first_quarter: int, count: int) -> list[str]:
    """["Q4 2022", "Q1 2023", ...] — the label format the rest of the product uses."""
    out, year, quarter = [], first_year, first_quarter
    for _ in range(count):
        out.append(f"Q{quarter} {year}")
        quarter += 1
        if quarter == 5:
            quarter, year = 1, year + 1
    return out


def quarter_end(period: str) -> str:
    """The last day of a reporting quarter, as an ISO date."""
    q, year = int(period[1]), int(period.split()[1])
    month, day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[q]
    return f"{year}-{month:02d}-{day:02d}"


PERIODS = quarters(FIRST_YEAR, FIRST_QUARTER, N_QUARTERS)
MACRO_PERIODS = quarters(
    MACRO_FIRST_YEAR, 1, (2026 - MACRO_FIRST_YEAR) * 4 + 2
)


# ============================================================= the economy


@dataclass(frozen=True)
class Sector:
    """A sector, and how much the cycle moves it.

    `beta` is sensitivity to the common macroeconomic factor; `vol` is how much
    of a borrower's quarter-to-quarter movement is its own rather than the
    cycle's. Contracting has a high beta and high idiosyncratic volatility;
    Utilities has neither. That difference is the whole reason a sector
    breakdown is worth looking at.
    """

    name: str
    weight: float
    beta: float
    vol: float
    #: Baseline credit quality. Positive is stronger.
    quality: float


SECTORS: list[Sector] = [
    Sector("Contracting", 0.13, 1.55, 0.62, -0.55),
    Sector("Real Estate", 0.11, 1.30, 0.50, -0.25),
    Sector("Petrochemicals", 0.09, 1.15, 0.38, 0.35),
    Sector("Wholesale & Retail Trade", 0.10, 0.95, 0.44, -0.10),
    Sector("Manufacturing", 0.09, 1.00, 0.40, 0.05),
    Sector("Transport & Logistics", 0.07, 0.90, 0.38, 0.00),
    Sector("Hospitality & Tourism", 0.06, 1.35, 0.55, -0.35),
    Sector("Healthcare", 0.06, 0.45, 0.28, 0.40),
    Sector("Education", 0.04, 0.40, 0.26, 0.35),
    Sector("Utilities", 0.05, 0.30, 0.20, 0.75),
    Sector("Telecommunications", 0.04, 0.50, 0.24, 0.60),
    Sector("Mining & Metals", 0.05, 1.20, 0.48, 0.05),
    Sector("Agriculture & Food", 0.05, 0.70, 0.36, 0.10),
    Sector("Financial Services", 0.03, 0.85, 0.34, 0.45),
    Sector("Government-Related Entities", 0.03, 0.25, 0.16, 1.05),
]

REGIONS = [
    ("Riyadh", 0.30), ("Makkah", 0.17), ("Eastern Province", 0.19),
    ("Madinah", 0.07), ("Asir", 0.05), ("Qassim", 0.05), ("Tabuk", 0.03),
    ("Ha'il", 0.03), ("Jazan", 0.03), ("Najran", 0.02), ("Al Jouf", 0.02),
    ("Northern Borders", 0.02), ("Al Bahah", 0.02),
]

SEGMENTS = [("Corporate", 0.30), ("Commercial", 0.34), ("SME", 0.32), ("Public Sector", 0.04)]

PRODUCTS = [
    ("Term Loan", 0.30), ("Revolving Credit Facility", 0.20),
    ("Working Capital Facility", 0.16), ("Project Finance", 0.10),
    ("Trade Finance", 0.10), ("Letter of Guarantee", 0.08),
    ("Ijara", 0.04), ("Murabaha", 0.02),
]

COLLATERAL = [
    ("Real Estate Mortgage", 0.30), ("Cash Collateral", 0.08),
    ("Corporate Guarantee", 0.20), ("Assignment of Receivables", 0.14),
    ("Plant & Machinery", 0.10), ("Sovereign Guarantee", 0.04), ("Unsecured", 0.14),
]


def macro_series(rng: np.random.Generator) -> pd.DataFrame:
    """A plausible Saudi macroeconomic path, and the common factor it implies.

    The series are shaped so the book has something to react to: an oil-driven
    strong 2022, a softer 2023 as production cuts bite, a non-oil recovery
    through 2024-25, and a mild late slowdown. The `credit_cycle_factor` is the
    single number the borrower simulation actually uses — positive is a
    supportive quarter, negative is a hostile one.
    """
    n = len(MACRO_PERIODS)
    t = np.arange(n)

    # A cycle with a long wave, a shorter wave and a little noise. Nothing here
    # forecasts anything; it is a shape with turning points to model against.
    cycle = (
        0.95 * np.sin(2 * math.pi * (t - 3) / 21)
        + 0.35 * np.sin(2 * math.pi * (t + 5) / 9)
        + rng.normal(0, 0.16, n)
    )
    cycle = np.clip(cycle, -2.1, 2.1)

    brent = np.clip(76 + 21 * cycle + rng.normal(0, 3.4, n), 34, 128)
    policy_rate = np.clip(3.4 + 1.9 * np.sin(2 * math.pi * (t - 8) / 24) + t * 0.018, 1.0, 6.5)
    non_oil_growth = np.clip(3.6 + 1.5 * cycle + rng.normal(0, 0.35, n), -1.5, 8.0)
    oil_growth = np.clip(1.2 + 3.4 * cycle + rng.normal(0, 1.1, n), -11.0, 12.0)
    real_gdp_growth = 0.42 * oil_growth + 0.58 * non_oil_growth
    inflation = np.clip(2.2 + 0.55 * np.sin(2 * math.pi * (t - 2) / 15) + rng.normal(0, 0.22, n), 0.2, 5.5)
    pmi = np.clip(53.5 + 2.7 * cycle + rng.normal(0, 0.7, n), 44.0, 61.0)
    unemployment = np.clip(9.2 - 0.85 * cycle + rng.normal(0, 0.2, n) - t * 0.035, 3.2, 12.5)
    real_estate_index = 100 * np.cumprod(1 + (0.006 + 0.011 * cycle / 2 + rng.normal(0, 0.004, n)))

    # What the borrowers feel. Credit conditions lag activity by about a
    # quarter, and a high policy rate is a headwind in its own right.
    lagged = np.concatenate([[cycle[0]], cycle[:-1]])
    rate_drag = -(policy_rate - policy_rate.mean()) / 2.6
    factor = 0.62 * lagged + 0.24 * cycle + 0.30 * rate_drag

    return pd.DataFrame({
        "period": MACRO_PERIODS,
        "period_end_date": [quarter_end(p) for p in MACRO_PERIODS],
        "real_gdp_growth_pct": np.round(real_gdp_growth, 2),
        "non_oil_gdp_growth_pct": np.round(non_oil_growth, 2),
        "oil_gdp_growth_pct": np.round(oil_growth, 2),
        "brent_usd_bbl": np.round(brent, 2),
        "sama_policy_rate_pct": np.round(policy_rate, 2),
        "inflation_pct": np.round(inflation, 2),
        "pmi_index": np.round(pmi, 1),
        "unemployment_pct": np.round(unemployment, 2),
        "real_estate_price_index": np.round(real_estate_index, 1),
        "credit_cycle_factor": np.round(factor, 4),
        "data_origin": DEMO_NOTE,
    })


# ============================================================ the customers

FIRST_WORDS = [
    "Al Faisaliah", "Najd", "Rawabi", "Tihama", "Yanbu", "Jubail", "Hail",
    "Qassim", "Sharqiyah", "Madinah", "Taif", "Dammam", "Khobar", "Jazan",
    "Riyadh", "Makkah", "Tabuk", "Buraidah", "Unaizah", "Abha", "Sakaka",
    "Arar", "Dhahran", "Hofuf", "Kharj", "Majmaah", "Zulfi", "Wadi",
    "Nafud", "Rub Al Khali", "Asir", "Baha", "Layla", "Aflaj", "Ghat",
    "Sudair", "Diriyah", "Ushaiqer", "Turaif", "Duba", "Wajh", "Qatif",
    "Safwa", "Anak", "Rahima", "Ras Tanura", "Khafji", "Sabya", "Farasan",
]
SECOND_WORDS = [
    "Holding", "Group", "Industries", "Trading", "Contracting", "Development",
    "Projects", "Enterprises", "Company", "Corporation", "Partners", "Ventures",
    "Works", "Systems", "Services", "Logistics", "Investments", "Resources",
]

INTERNAL_RATINGS = [
    "CP-1", "CP-2", "CP-3", "CP-4", "CP-5",
    "CP-6", "CP-7", "CP-8", "CP-9", "CP-10",
]
RATING_BUCKETS = {
    "CP-1": "Investment grade", "CP-2": "Investment grade", "CP-3": "Investment grade",
    "CP-4": "Investment grade", "CP-5": "Sub-investment grade",
    "CP-6": "Sub-investment grade", "CP-7": "Watch",
    "CP-8": "Watch", "CP-9": "Impaired", "CP-10": "Impaired",
}
GRADE_BANDS = {
    1: "Very low risk", 2: "Very low risk", 3: "Low risk", 4: "Low risk",
    5: "Moderate risk", 6: "Moderate risk", 7: "Elevated risk",
    8: "High risk", 9: "Default", 10: "Default",
}
EXTERNAL_RATINGS = ["A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+"]


def choose(rng: np.random.Generator, options: list[tuple[str, float]], size: int) -> np.ndarray:
    labels = [o[0] for o in options]
    weights = np.array([o[1] for o in options], dtype=float)
    return rng.choice(labels, size=size, p=weights / weights.sum())


def build_customers(rng: np.random.Generator) -> pd.DataFrame:
    """The borrowers: who they are, and how exposed they are to the cycle."""
    sector_names = [s.name for s in SECTORS]
    sector_weights = np.array([s.weight for s in SECTORS])
    sector_weights = sector_weights / sector_weights.sum()
    sectors = rng.choice(sector_names, size=N_CUSTOMERS, p=sector_weights)
    by_name = {s.name: s for s in SECTORS}

    names, seen = [], set()
    for i in range(N_CUSTOMERS):
        for _ in range(40):
            candidate = (
                f"{FIRST_WORDS[rng.integers(len(FIRST_WORDS))]} "
                f"{SECOND_WORDS[rng.integers(len(SECOND_WORDS))]}"
            )
            if candidate not in seen:
                break
        if candidate in seen:
            candidate = f"{candidate} {i}"
        seen.add(candidate)
        names.append(candidate)

    segments = choose(rng, SEGMENTS, N_CUSTOMERS)
    # Size in USD mn of total exposure, log-normal and segment-dependent.
    scale = np.where(segments == "Corporate", 4.1,
                     np.where(segments == "Commercial", 2.9,
                              np.where(segments == "SME", 1.7, 4.6)))
    size = np.exp(rng.normal(scale, 0.62)) + 0.4

    quality = np.array([by_name[s].quality for s in sectors])
    beta = np.array([by_name[s].beta for s in sectors])
    vol = np.array([by_name[s].vol for s in sectors])
    # Bigger borrowers are, on the whole, stronger; a public-sector obligor more
    # so again. Neither relationship is deterministic.
    quality = (
        quality
        + 0.22 * np.log1p(size) / 2.0
        + np.where(segments == "Public Sector", 0.9, 0.0)
        + np.where(segments == "SME", -0.30, 0.0)
        + rng.normal(0, 0.55, N_CUSTOMERS)
    )

    return pd.DataFrame({
        "customer_id": [f"SA-{100000 + i}" for i in range(N_CUSTOMERS)],
        "borrower_name": names,
        "sector": sectors,
        "region": choose(rng, REGIONS, N_CUSTOMERS),
        "country": "Saudi Arabia",
        "segment": segments,
        "obligor_group": [
            f"GRP-{1000 + (i // 3)}" if i % 5 < 2 else "" for i in range(N_CUSTOMERS)
        ],
        "owner_analyst": [f"Analyst {1 + (i % 24):02d}" for i in range(N_CUSTOMERS)],
        "size_usd_mn": size,
        "base_quality": quality,
        "beta": beta,
        "vol": vol,
    })


# ============================================================ the simulation


def simulate_quality(customers: pd.DataFrame, factor: np.ndarray,
                     rng: np.random.Generator) -> np.ndarray:
    """Latent credit quality, per customer per quarter.

    An AR(1) around each borrower's own baseline, pushed by the cycle in
    proportion to its sector's beta. Persistence is what makes the data
    predictable at all: a borrower that weakened last quarter is more likely to
    be weak this quarter, which is exactly the regularity a forward risk signal
    is supposed to detect.
    """
    n, t = len(customers), N_QUARTERS
    rho = 0.86
    base = customers["base_quality"].to_numpy()
    beta = customers["beta"].to_numpy()
    vol = customers["vol"].to_numpy()

    z = np.zeros((n, t))
    # Start each borrower already somewhere, not all at their baseline.
    z[:, 0] = base + beta * factor[0] * 0.5 + rng.normal(0, vol * 0.9)
    for q in range(1, t):
        drift = base + beta * factor[q] * 0.55
        z[:, q] = rho * z[:, q - 1] + (1 - rho) * drift + rng.normal(0, vol * 0.42)
    return z


def pd_from_quality(z: np.ndarray) -> np.ndarray:
    """Twelve-month PD in percent, from latent quality.

    A logistic curve: strong borrowers cluster at a few basis points, weak ones
    rise steeply. The floor stops a PD of exactly zero, which no real rating
    system publishes.
    """
    return np.clip(100.0 / (1.0 + np.exp(2.05 * z + 2.55)), 0.03, 99.0)


def grade_from_pd(pd_pct: np.ndarray) -> np.ndarray:
    """Internal grade 1-10 from the 12-month PD, on fixed published bands."""
    bounds = [0.10, 0.22, 0.45, 0.90, 1.80, 3.60, 7.00, 14.0, 30.0]
    grade = np.ones_like(pd_pct, dtype=int)
    for edge in bounds:
        grade = grade + (pd_pct > edge).astype(int)
    return np.clip(grade, 1, 10)


# ================================================================== staging


#: Relative PD increase that counts as a significant increase in credit risk.
SICR_PD_RATIO = 2.0
#: And the absolute increase it must also clear, so a move from 0.03% to 0.07%
#: does not trip a trigger on its own.
SICR_PD_ABSOLUTE = 0.55
#: Quarters of clean behaviour before a Stage 2 facility may return to Stage 1.
CURE_QUARTERS = 2


def build_book(customers: pd.DataFrame, z: np.ndarray, macro: pd.DataFrame,
               rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every facility, every quarter — and the IFRS 9 staging beside it.

    Facilities belong to customers and inherit their credit quality; everything
    that varies within a customer (utilisation, collateral, product) varies at
    the facility level. Staging is then applied per facility under the rules
    above, with days past due and cure periods carried forward properly, so a
    migration is the consequence of a history rather than a coin toss.
    """
    n_customers = len(customers)
    # Two to six facilities each, so ~15,000 rows a quarter.
    counts = rng.integers(2, 7, n_customers)
    customer_index = np.repeat(np.arange(n_customers), counts)
    n_facilities = len(customer_index)

    facility_ids = np.array([f"SA-ACC-{500000 + i}" for i in range(n_facilities)])
    products = choose(rng, PRODUCTS, n_facilities)
    collateral_types = choose(rng, COLLATERAL, n_facilities)

    # Split each customer's exposure across its facilities.
    share = rng.gamma(2.4, 1.0, n_facilities)
    share = share / np.bincount(customer_index, weights=share)[customer_index]
    limits = customers["size_usd_mn"].to_numpy()[customer_index] * share
    limits = np.clip(limits, 0.15, None)

    # Facility-level quirks that persist: some facilities simply run hotter.
    util_bias = rng.normal(0, 0.11, n_facilities)
    lgd_base = np.where(
        collateral_types == "Cash Collateral", 0.10,
        np.where(collateral_types == "Sovereign Guarantee", 0.14,
                 np.where(collateral_types == "Real Estate Mortgage", 0.32,
                          np.where(collateral_types == "Unsecured", 0.58, 0.42))))
    lgd_base = np.clip(lgd_base + rng.normal(0, 0.05, n_facilities), 0.05, 0.85)
    eir = np.clip(rng.normal(6.4, 1.5, n_facilities), 2.2, 13.5)

    factor = macro.set_index("period").loc[PERIODS, "credit_cycle_factor"].to_numpy()

    # State carried between quarters. This is what makes the book longitudinal
    # rather than fifteen unrelated snapshots.
    dpd = np.zeros(n_facilities, dtype=int)
    stage = np.ones(n_facilities, dtype=int)
    clean_quarters = np.full(n_facilities, CURE_QUARTERS, dtype=int)
    utilisation = np.clip(rng.beta(5.0, 2.6, n_facilities) + util_bias, 0.05, 1.0)
    rollovers = rng.poisson(0.4, n_facilities)

    z_fac = z[customer_index]
    pd_origination = pd_from_quality(z_fac[:, 0] + rng.normal(0.35, 0.25, n_facilities))
    grade_origination = grade_from_pd(pd_origination)

    facility_frames: list[pd.DataFrame] = []
    staging_frames: list[pd.DataFrame] = []
    previous_grade = grade_origination.copy()
    previous_util = utilisation.copy()

    for q, period in enumerate(PERIODS):
        quality = z_fac[:, q]
        pd_12m = pd_from_quality(quality)
        grade = grade_from_pd(pd_12m)
        # Lifetime PD exceeds the 12-month PD by more for weaker borrowers.
        pd_life = np.clip(pd_12m * (1.55 + 0.055 * grade), pd_12m, 99.5)

        # --- behaviour, driven by quality with real persistence -------------
        stress = np.clip(-quality, -3.0, 4.0)
        utilisation = np.clip(
            0.72 * utilisation + 0.28 * (0.55 + 0.085 * stress + util_bias)
            + rng.normal(0, 0.035, n_facilities),
            0.02, 1.05,
        )
        # Delinquency: a hazard that rises steeply with stress, then accumulates.
        hazard = 1.0 / (1.0 + np.exp(-(1.30 * stress - 3.55 - 0.25 * factor[q])))
        newly_late = (rng.random(n_facilities) < hazard) & (dpd == 0)
        dpd = np.where(newly_late, 30, np.where(dpd > 0, dpd + 30, 0))
        # Cure: healthier borrowers get current again.
        cured = (dpd > 0) & (rng.random(n_facilities) < 1.0 / (1.0 + np.exp(1.15 * stress)))
        dpd = np.where(cured, 0, dpd)
        dpd = np.clip(dpd, 0, 720)

        dscr = np.clip(1.85 - 0.30 * stress + rng.normal(0, 0.22, n_facilities), 0.15, 5.5)
        headroom = np.clip(28.0 - 9.5 * stress + rng.normal(0, 5.5, n_facilities), -45.0, 85.0)
        sentiment = np.clip(-0.16 * stress + rng.normal(0, 0.30, n_facilities), -1.0, 1.0)
        rollovers = rollovers + (rng.random(n_facilities) < np.clip(0.05 + 0.07 * stress, 0, 0.55))
        downgrade_prob = np.clip(
            100.0 / (1.0 + np.exp(-(0.95 * stress - 1.85))) + rng.normal(0, 3.0, n_facilities),
            0.2, 99.0,
        )
        ai_score = np.clip(0.5 + 0.16 * stress + rng.normal(0, 0.06, n_facilities), 0.0, 1.0)

        # --- staging --------------------------------------------------------
        pd_ratio = pd_12m / np.maximum(pd_origination, 0.01)
        notches = grade - grade_origination

        trigger_pd = (pd_ratio >= SICR_PD_RATIO) & (pd_12m - pd_origination >= SICR_PD_ABSOLUTE)
        trigger_dpd = dpd >= 30
        trigger_covenant = headroom < 0
        trigger_notch = notches >= 3
        trigger_watchlist = (grade >= 7) & (downgrade_prob > 55)

        # Default is a delinquency fact, or a grade-10 borrower who is also
        # visibly distressed. A borrower cannot jump from a clean Stage 1
        # straight to impaired on a rating move alone — in a real book that
        # migration goes through Stage 2 first, and a model trained on data
        # where it does not would learn a transition that does not happen.
        defaulted = (dpd >= 90) | ((grade == 10) & ((dpd >= 30) | (headroom < 0)))
        sicr = trigger_pd | trigger_dpd | trigger_covenant | trigger_notch | trigger_watchlist

        clean_quarters = np.where(sicr | defaulted, 0, clean_quarters + 1)
        # Once impaired, a facility only leaves Stage 3 by curing fully and
        # serving out the probation, which is why so few of them do.
        was_three = stage == 3
        new_stage = np.where(
            defaulted, 3,
            np.where(sicr, 2,
                     np.where(clean_quarters >= CURE_QUARTERS, 1, np.maximum(stage, 2))))
        new_stage = np.where(was_three & ~defaulted & (clean_quarters < CURE_QUARTERS + 2),
                             3, new_stage)
        previous_stage = stage
        stage = new_stage

        # --- exposure and loss ---------------------------------------------
        ccf = np.where(products == "Term Loan", 1.0,
                       np.clip(0.42 + 0.25 * utilisation, 0.2, 1.0))
        exposure = limits * utilisation
        undrawn = np.clip(limits - exposure, 0, None)
        ead = exposure + undrawn * ccf
        collateral = np.clip(limits * np.where(collateral_types == "Unsecured", 0.0,
                                               rng.uniform(0.25, 0.95, n_facilities)), 0, None)
        lgd = np.clip(lgd_base * (1.0 + 0.05 * stress), 0.03, 0.95)

        horizon_pd = np.where(stage == 1, pd_12m, np.where(stage == 3, 100.0, pd_life))
        model_ecl = ead * lgd * horizon_pd / 100.0
        # The overlay is management's view of what the model has not caught yet,
        # and it is larger when the cycle is against the book.
        overlay = model_ecl * np.clip(0.10 - 0.05 * factor[q], 0.0, 0.35)
        total_ecl = model_ecl + overlay
        coverage = np.where(ead > 0, 100.0 * total_ecl / ead, 0.0)
        raroc = np.clip(eir - coverage * 0.9 - 2.6 + rng.normal(0, 1.1, n_facilities), -22, 34)

        ratings = np.array(INTERNAL_RATINGS)[grade - 1]
        prev_ratings = np.array(INTERNAL_RATINGS)[previous_grade - 1]

        severity = np.where(stage == 3, "Critical",
                            np.where(stage == 2, np.where(dpd >= 30, "High", "Medium"), "Low"))
        trigger_name = np.where(
            defaulted, "Default / 90+ DPD",
            np.where(trigger_dpd, "Days past due",
                     np.where(trigger_covenant, "Covenant breach",
                              np.where(trigger_pd, "PD deterioration",
                                       np.where(trigger_notch, "Rating downgrade",
                                                np.where(trigger_watchlist, "Watchlist",
                                                         "None"))))))
        action = np.where(stage == 3, "Refer to Remedial Management",
                          np.where(stage == 2, "Enhanced monitoring and covenant review",
                                   np.where(grade >= 6, "Annual review brought forward",
                                            "Standard monitoring")))
        trend = np.where(grade > previous_grade, "Deteriorating",
                         np.where(grade < previous_grade, "Improving", "Stable"))

        facility_frames.append(pd.DataFrame({
            "snapshot_date": quarter_end(period),
            "period": period,
            "customer_id": customers["customer_id"].to_numpy()[customer_index],
            "account_id": facility_ids,
            "borrower_name": customers["borrower_name"].to_numpy()[customer_index],
            "obligor_group": customers["obligor_group"].to_numpy()[customer_index],
            "segment": customers["segment"].to_numpy()[customer_index],
            "sector": customers["sector"].to_numpy()[customer_index],
            "region": customers["region"].to_numpy()[customer_index],
            "country": customers["country"].to_numpy()[customer_index],
            "product_type": products,
            "owner_analyst": customers["owner_analyst"].to_numpy()[customer_index],
            "limit_amount": np.round(limits, 3),
            "exposure": np.round(exposure, 3),
            "undrawn": np.round(undrawn, 3),
            "ccf_pct": np.round(ccf * 100, 2),
            "ead": np.round(ead, 3),
            "utilisation_pct": np.round(utilisation * 100, 2),
            "prev_utilisation_pct": np.round(previous_util * 100, 2),
            "collateral_value": np.round(collateral, 3),
            "collateral_type": collateral_types,
            "internal_grade": grade,
            "risk_rating": ratings,
            "prev_risk_rating": prev_ratings,
            "rating_bucket": [RATING_BUCKETS[r] for r in ratings],
            "grade_band": [GRADE_BANDS[g] for g in grade],
            "ifrs9_stage": stage,
            "exposure_grade": np.where(ead > 50, "Large", np.where(ead > 10, "Medium", "Small")),
            "dpd_days": dpd,
            "pd_12m_pct": np.round(pd_12m, 4),
            "pd_lifetime_pct": np.round(pd_life, 4),
            "lgd_pct": np.round(lgd * 100, 2),
            "model_ecl": np.round(model_ecl, 4),
            "macro_overlay": np.round(overlay, 4),
            "total_ecl": np.round(total_ecl, 4),
            "ecl_coverage_pct": np.round(coverage, 3),
            "eir_pct": np.round(eir, 2),
            "raroc_pct": np.round(raroc, 2),
            "ai_risk_score": np.round(ai_score, 3),
            "severity": severity,
            "trigger_type": trigger_name,
            "reason_code": np.where(trigger_name == "None", "RC-000", "RC-" + np.char.zfill(
                (grade * 7 % 40 + 1).astype(str), 3)),
            "recommended_action": action,
            "trend": trend,
            "sicr_trigger": sicr,
            "dscr": np.round(dscr, 2),
            "covenant_headroom_pct": np.round(headroom, 2),
            "downgrade_prob_pct": np.round(downgrade_prob, 2),
            "news_sentiment": np.round(sentiment, 3),
            "rollover_count": rollovers.astype(int),
            "watchlist": (grade >= 7) | (stage >= 2),
            "npl": stage == 3,
            "appetite_breach": (ead > 85) & (grade >= 6),
        }))

        staging_frames.append(pd.DataFrame({
            "period": period,
            "period_end_date": quarter_end(period),
            "account_id": facility_ids,
            "customer_id": customers["customer_id"].to_numpy()[customer_index],
            "sector": customers["sector"].to_numpy()[customer_index],
            "segment": customers["segment"].to_numpy()[customer_index],
            "ifrs9_stage": stage,
            "prior_stage": previous_stage,
            "stage_moved": stage != previous_stage,
            "ead": np.round(ead, 3),
            "pd_at_origination_pct": np.round(pd_origination, 4),
            "pd_12m_pct": np.round(pd_12m, 4),
            "pd_lifetime_pct": np.round(pd_life, 4),
            "pd_ratio_to_origination": np.round(pd_ratio, 3),
            "notches_since_origination": notches,
            "lgd_pct": np.round(lgd * 100, 2),
            "dpd_days": dpd,
            "sicr_pd_trigger": trigger_pd,
            "sicr_dpd_trigger": trigger_dpd,
            "sicr_covenant_trigger": trigger_covenant,
            "sicr_rating_trigger": trigger_notch,
            "sicr_watchlist_trigger": trigger_watchlist,
            "sicr_any_trigger": sicr,
            "quarters_clean": clean_quarters,
            "model_ecl": np.round(model_ecl, 4),
            "macro_overlay": np.round(overlay, 4),
            "total_ecl": np.round(total_ecl, 4),
            "ecl_coverage_pct": np.round(coverage, 3),
            "data_origin": DEMO_NOTE,
        }))

        previous_grade = grade.copy()
        previous_util = utilisation.copy()

    return (
        pd.concat(facility_frames, ignore_index=True),
        pd.concat(staging_frames, ignore_index=True),
    )


# =============================================================== the ratings


def build_ratings(customers: pd.DataFrame, macro: pd.DataFrame,
                  rng: np.random.Generator) -> pd.DataFrame:
    """Eight annual rating cycles, one row per customer per year.

    The same latent process as the book, run annually and further back, so the
    rating history is consistent with the portfolio it later becomes rather than
    an unrelated table that happens to share customer identifiers.
    """
    n = len(customers)
    base = customers["base_quality"].to_numpy()
    beta = customers["beta"].to_numpy()
    vol = customers["vol"].to_numpy()

    annual_factor = (
        macro.assign(year=[int(p.split()[1]) for p in macro["period"]])
        .groupby("year")["credit_cycle_factor"].mean()
    )

    rows = []
    z = base + rng.normal(0, vol * 0.8)
    for year in RATING_YEARS:
        drift = base + beta * float(annual_factor.get(year, 0.0)) * 0.6
        z = 0.78 * z + 0.22 * drift + rng.normal(0, vol * 0.55)
        pd_12m = pd_from_quality(z)
        grade = grade_from_pd(pd_12m)
        ratings = np.array(INTERNAL_RATINGS)[grade - 1]
        external_index = np.clip(
            (grade * 1.25 + rng.normal(0, 1.1, n)).astype(int), 0, len(EXTERNAL_RATINGS) - 1
        )

        leverage = np.clip(2.4 - 0.42 * z + rng.normal(0, 0.55, n), 0.1, 12.0)
        coverage_ratio = np.clip(4.2 + 0.85 * z + rng.normal(0, 0.9, n), 0.15, 18.0)
        current_ratio = np.clip(1.35 + 0.16 * z + rng.normal(0, 0.28, n), 0.25, 4.5)
        margin = np.clip(11.5 + 2.6 * z + rng.normal(0, 2.6, n), -18.0, 38.0)
        revenue = customers["size_usd_mn"].to_numpy() * np.clip(
            rng.normal(2.4, 0.5, n), 0.6, 6.0
        )

        rows.append(pd.DataFrame({
            "period": str(year),
            "rating_year": year,
            "customer_id": customers["customer_id"],
            "borrower_name": customers["borrower_name"],
            "sector": customers["sector"],
            "region": customers["region"],
            "segment": customers["segment"],
            "internal_grade": grade,
            "risk_rating": ratings,
            "rating_bucket": [RATING_BUCKETS[r] for r in ratings],
            "pd_12m_pct": np.round(pd_12m, 4),
            "external_rating": np.array(EXTERNAL_RATINGS)[external_index],
            "revenue_usd_mn": np.round(revenue, 2),
            "net_leverage": np.round(leverage, 2),
            "interest_coverage": np.round(coverage_ratio, 2),
            "current_ratio": np.round(current_ratio, 2),
            "ebitda_margin_pct": np.round(margin, 2),
            "rating_action": "",
            "data_origin": DEMO_NOTE,
        }))

    ratings_df = pd.concat(rows, ignore_index=True)
    # The action is the year-on-year move, computed once the whole history
    # exists rather than guessed at each step.
    ratings_df = ratings_df.sort_values(["customer_id", "rating_year"])
    previous = ratings_df.groupby("customer_id")["internal_grade"].shift(1)
    ratings_df["prior_internal_grade"] = previous.fillna(ratings_df["internal_grade"]).astype(int)
    move = ratings_df["internal_grade"] - ratings_df["prior_internal_grade"]
    ratings_df["rating_action"] = np.where(
        previous.isna(), "Initial rating",
        np.where(move > 0, "Downgrade", np.where(move < 0, "Upgrade", "Affirmed")),
    )
    ratings_df["notches_moved"] = move.astype(int)
    return ratings_df.reset_index(drop=True)


def build_borrower_financials(customers: pd.DataFrame,
                              ratings: pd.DataFrame) -> pd.DataFrame:
    """One row per borrower, in the governed shape the existing analyses expect.

    The two fiscal years are the last two rating years, so this table and the
    rating history cannot disagree.
    """
    years = sorted(ratings["rating_year"].unique())
    fy_previous, fy_latest = years[-2], years[-1]
    previous = ratings[ratings["rating_year"] == fy_previous].set_index("customer_id")
    latest = ratings[ratings["rating_year"] == fy_latest].set_index("customer_id")
    order = customers["customer_id"]

    return pd.DataFrame({
        "customer_id": order,
        "borrower_name": customers["borrower_name"].to_numpy(),
        "net_leverage_fy24": previous.loc[order, "net_leverage"].to_numpy(),
        "net_leverage_fy25": latest.loc[order, "net_leverage"].to_numpy(),
        "interest_coverage_fy24": previous.loc[order, "interest_coverage"].to_numpy(),
        "interest_coverage_fy25": latest.loc[order, "interest_coverage"].to_numpy(),
        "current_ratio_fy24": previous.loc[order, "current_ratio"].to_numpy(),
        "current_ratio_fy25": latest.loc[order, "current_ratio"].to_numpy(),
        "external_rating": latest.loc[order, "external_rating"].to_numpy(),
        "external_rating_as_of": f"{fy_latest}-12-31",
        "rating_notch_gap": (
            latest.loc[order, "internal_grade"].to_numpy()
            - previous.loc[order, "internal_grade"].to_numpy()
        ),
        "last_collateral_valuation_date": f"{fy_latest}-06-30",
    })


# ---------------------------------------------------------- delinquency


#: The arrears buckets a collections team works in. Ordered, because "worse
#: than 60 days" is a question somebody asks and an alphabetical bucket list
#: cannot answer it.
DPD_BUCKETS: list[tuple[str, int, int]] = [
    ("Current", 0, 0),
    ("1-29 days", 1, 29),
    ("30-59 days", 30, 59),
    ("60-89 days", 60, 89),
    ("90-179 days", 90, 179),
    ("180+ days", 180, 10_000),
]

COLLECTIONS_STAGES = [
    "None", "Soft reminder", "Formal demand", "Collections", "Legal recovery",
]

FORBEARANCE_TYPES = [
    "None", "Payment holiday", "Term extension", "Interest capitalisation",
    "Covenant waiver", "Restructured facility",
]


def bucket_for(dpd: np.ndarray) -> np.ndarray:
    """The arrears bucket each days-past-due figure falls in."""
    out = np.full(len(dpd), DPD_BUCKETS[0][0], dtype=object)
    for label, low, high in DPD_BUCKETS:
        out[(dpd >= low) & (dpd <= high)] = label
    return out


def build_delinquency(facility: pd.DataFrame,
                      rng: np.random.Generator) -> pd.DataFrame:
    """Arrears and collections, one row per facility per quarter.

    Derived from the facility book's own `dpd_days` rather than simulated
    separately. That is the whole point: an analyst who reads 90 days past due
    here and a Stage 1 classification in the impairment table has found a
    contradiction in the demonstration data, not an insight, and the fastest way
    to destroy confidence in a demonstration is to let it disagree with itself.

    What this dataset adds is everything the facility snapshot does not carry:
    which bucket the arrears fall in, how much is actually overdue, how many
    instalments were missed, when the borrower last paid, whether they have been
    forborne, and where collections has got to.
    """
    frame = facility[[
        "period", "account_id", "customer_id", "borrower_name", "sector",
        "region", "segment", "product_type", "dpd_days", "exposure", "ead",
        "ifrs9_stage", "npl", "watchlist",
    ]].copy()
    frame = frame.sort_values(["account_id", "period"], kind="mergesort")

    dpd = frame["dpd_days"].to_numpy()
    n = len(frame)

    # Amount overdue: roughly one quarterly instalment per 30 days in arrears,
    # capped at the exposure. Nobody can be more overdue than they owe.
    exposure = frame["exposure"].to_numpy()
    instalment = exposure / 20.0
    missed = np.ceil(dpd / 30.0).astype(int)
    arrears = np.minimum(instalment * missed * rng.uniform(0.7, 1.3, n), exposure)
    arrears = np.where(dpd > 0, np.round(arrears, 3), 0.0)

    # A borrower 45 days down last paid about 45 days ago, give or take. One
    # who is current paid at some point in the quarter.
    since_payment = np.where(
        dpd > 0,
        dpd + rng.integers(0, 20, n),
        rng.integers(1, 92, n),
    )
    period_end = pd.to_datetime([quarter_end(p) for p in frame["period"]])
    last_payment = period_end - pd.to_timedelta(since_payment, unit="D")

    # Cured this quarter: in arrears last quarter, current now. Computed by
    # shifting within each account, so it is a real transition rather than a
    # coin flip.
    previous_dpd = frame.groupby("account_id", observed=True)["dpd_days"].shift(1)
    cured = (previous_dpd.fillna(0).to_numpy() > 0) & (dpd == 0)
    newly_delinquent = (previous_dpd.fillna(0).to_numpy() == 0) & (dpd > 0)

    # Forbearance concentrates where the arrears are, but is not implied by
    # them: a bank forbears some borrowers and pursues others.
    forborne_odds = np.clip(dpd / 400.0, 0.0, 0.45)
    forborne = rng.random(n) < forborne_odds
    forbearance = np.where(
        forborne,
        rng.choice(FORBEARANCE_TYPES[1:], size=n),
        FORBEARANCE_TYPES[0],
    )

    # Collections escalates with the bucket, which is how a collections
    # function actually works.
    stage_index = np.digitize(dpd, [1, 30, 90, 180])
    collections = np.array(COLLECTIONS_STAGES, dtype=object)[
        np.clip(stage_index, 0, len(COLLECTIONS_STAGES) - 1)
    ]

    out = pd.DataFrame({
        "period": frame["period"].to_numpy(),
        "period_end_date": [quarter_end(p) for p in frame["period"]],
        "account_id": frame["account_id"].to_numpy(),
        "customer_id": frame["customer_id"].to_numpy(),
        "borrower_name": frame["borrower_name"].to_numpy(),
        "sector": frame["sector"].to_numpy(),
        "region": frame["region"].to_numpy(),
        "segment": frame["segment"].to_numpy(),
        "product_type": frame["product_type"].to_numpy(),
        "days_past_due": dpd,
        "dpd_bucket": bucket_for(dpd),
        "arrears_amount": arrears,
        "instalments_missed": np.where(dpd > 0, missed, 0),
        "last_payment_date": last_payment.strftime("%Y-%m-%d"),
        "days_since_last_payment": since_payment,
        "forbearance_type": forbearance,
        "restructured_flag": forbearance == "Restructured facility",
        "collections_stage": collections,
        "cured_this_period": cured,
        "newly_delinquent": newly_delinquent,
        "exposure_at_risk": np.where(dpd >= 90, np.round(frame["ead"], 3), 0.0),
        "ifrs9_stage": frame["ifrs9_stage"].to_numpy(),
        "npl": frame["npl"].to_numpy(),
        "watchlist": frame["watchlist"].to_numpy(),
    })
    return out.sort_values(["period", "account_id"], kind="mergesort").reset_index(drop=True)


# ------------------------------------------------------- credit memo signals


MEMO_TYPES = [
    "Annual review", "Interim review", "Covenant waiver request",
    "Site visit note", "Watchlist escalation", "Credit committee paper",
]

MEMO_AUTHORS = [
    "Relationship Manager", "Credit Analyst", "Sector Specialist",
    "Portfolio Manager", "Credit Officer",
]

RECOMMENDATIONS = [
    "Maintain limits", "Reduce exposure", "Hold and monitor",
    "Escalate to watchlist", "Seek additional security", "Exit facility",
]

#: Every synthetic extract carries this prefix, without exception. Natural
#: wording is fine and makes the demonstration better; wording that could be
#: mistaken for real client information is not. The marker is what keeps the
#: second from happening once a row has been exported to a CSV, pasted into a
#: deck, and read by somebody who never saw the screen it came from.
SYNTHETIC_MARKER = "SYNTHETIC EXTRACT — "

#: Sentences a credit file actually contains, one per concern. Assembled from a
#: fixed bank rather than generated, so the same six concerns always read the
#: same way and the text can be checked by eye.
_CONCERN_SENTENCES = {
    "covenant_breach": "Net leverage covenant was breached at the last test date.",
    "liquidity_concern": "Headroom on committed facilities is under three months of cover.",
    "management_change": "The finance director left during the period and has not been replaced.",
    "sector_headwind": "Sector demand has softened and margins are compressing.",
    "going_concern": "The auditor has drawn attention to a material uncertainty over going concern.",
    "receivables_stretch": "Debtor days have extended materially against the prior year.",
}

_POSITIVE_SENTENCES = [
    "Trading is ahead of budget and the order book has lengthened.",
    "The shareholder injected equity during the period.",
    "Leverage has reduced following the disposal of a non-core asset.",
    "Collateral was revalued upward at the last inspection.",
]


def build_credit_memos(customers: pd.DataFrame, facility: pd.DataFrame,
                       rng: np.random.Generator) -> pd.DataFrame:
    """Credit file notes, as structured signals rather than free prose.

    Real credit memos are documents. What an analytical product can actually
    use from them is what they SAY — a covenant breach mentioned, a finance
    director gone, a going-concern paragraph — so this dataset carries those as
    flags with a short extract attached, rather than pretending to hold the
    document.

    The signals are anchored to the borrower's condition in the same quarter, so
    a memo raising liquidity concern belongs to a borrower whose numbers were in
    fact deteriorating. A memo dataset uncorrelated with the book would teach
    the product that unstructured signals predict nothing.

    Every extract is assembled from a fixed sentence bank. It is deliberately
    obvious that these are templates: a plausible-looking paragraph of credit
    opinion about a named company is exactly the thing nobody should be able to
    mistake for a real one.
    """
    # One memo per borrower per quarter for the deteriorating half of the book,
    # and an annual review for everybody else — which is roughly the cadence a
    # real credit function runs at.
    rows: list[dict] = []
    by_period = facility.groupby("period", observed=True)

    for period, chunk in by_period:
        worst = (
            chunk.sort_values(["ifrs9_stage", "pd_12m_pct"], ascending=False)
            .drop_duplicates("customer_id")
        )
        # Everyone in stage 2 or 3, plus a rotating slice of the rest, so the
        # performing book is reviewed once a year rather than never.
        watched = worst[worst["ifrs9_stage"] >= 2]
        performing = worst[worst["ifrs9_stage"] == 1]
        rotation = performing.iloc[
            rng.integers(0, max(1, len(performing)), size=max(1, len(performing) // 4))
        ]
        subjects = pd.concat([watched, rotation]).drop_duplicates("customer_id")

        n = len(subjects)
        if n == 0:
            continue

        stage = subjects["ifrs9_stage"].to_numpy()
        pd_pct = subjects["pd_12m_pct"].to_numpy()
        # Concern probability rises with the borrower's own condition.
        pressure = np.clip((stage - 1) * 0.3 + pd_pct / 25.0, 0.02, 0.92)

        flags = {
            key: rng.random(n) < pressure * weight
            for key, weight in (
                ("covenant_breach", 0.75),
                ("liquidity_concern", 0.65),
                ("management_change", 0.30),
                ("sector_headwind", 0.55),
                ("going_concern", 0.20),
                ("receivables_stretch", 0.45),
            )
        }
        raised = np.sum(list(flags.values()), axis=0)

        # Sentiment follows what was actually flagged, not a separate die roll.
        sentiment = np.where(raised >= 2, "negative",
                             np.where(raised == 1, "mixed", "positive"))

        extracts = []
        for i in range(n):
            said = [_CONCERN_SENTENCES[key] for key, series in flags.items()
                    if series[i]]
            if not said:
                said = [_POSITIVE_SENTENCES[int(rng.integers(0, len(_POSITIVE_SENTENCES)))]]
            extracts.append(SYNTHETIC_MARKER + " ".join(said))

        rows.append(pd.DataFrame({
            "period": period,
            "period_end_date": quarter_end(str(period)),
            "memo_id": [f"MEMO-{period.replace(' ', '')}-{i:05d}" for i in range(n)],
            "customer_id": subjects["customer_id"].to_numpy(),
            "borrower_name": subjects["borrower_name"].to_numpy(),
            "sector": subjects["sector"].to_numpy(),
            "region": subjects["region"].to_numpy(),
            "memo_type": rng.choice(MEMO_TYPES, size=n),
            "author_role": rng.choice(MEMO_AUTHORS, size=n),
            "sentiment": sentiment,
            "concerns_raised": raised.astype(int),
            "signal_strength_pct": np.round(100.0 * np.clip(raised / 6.0, 0, 1), 1),
            "recommendation": rng.choice(RECOMMENDATIONS, size=n),
            "extract": extracts,
            "is_synthetic_text": True,
            **{f"{key}_mentioned": series for key, series in flags.items()},
        }))

    memos = pd.concat(rows, ignore_index=True)
    return memos.sort_values(["period", "memo_id"], kind="mergesort").reset_index(drop=True)


# ================================================================= writing


def write_partitioned(df: pd.DataFrame, directory: Path, period_field: str | None) -> int:
    """One folder per period, matching the layout the Data Access Layer reads."""
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if period_field is None:
        df.to_parquet(directory / "data.parquet", index=False)
        return 1
    written = 0
    for period, chunk in df.groupby(period_field, observed=True):
        part = directory / f"{period_field}={period}"
        part.mkdir(parents=True, exist_ok=True)
        chunk.to_parquet(part / "data.parquet", index=False)
        written += 1
    return written


def field(name: str, business: str, definition: str, data_type: str,
          unit: str | None = None, sensitivity: str = "internal") -> dict:
    return {
        "name": name,
        "source_column": name,
        "business_name": business,
        "definition": definition,
        "data_type": data_type,
        "unit": unit,
        "sensitivity": sensitivity,
        "nullable": True,
    }


def infer_fields(df: pd.DataFrame, described: dict[str, dict]) -> list[dict]:
    """Catalogue entries for a generated dataset.

    Every column gets an entry. Columns this script has described by hand use
    that description; anything else gets an honest placeholder rather than being
    left out of the dictionary, because a field the catalogue does not know
    about is a field the Data Access Layer will refuse to serve.
    """
    out = []
    for column in df.columns:
        if column in described:
            out.append(described[column])
            continue
        dtype = df[column].dtype
        data_type = (
            "boolean" if pd.api.types.is_bool_dtype(dtype)
            else "integer" if pd.api.types.is_integer_dtype(dtype)
            else "number" if pd.api.types.is_numeric_dtype(dtype)
            else "string"
        )
        out.append(field(column, column.replace("_", " ").title(),
                         f"{column.replace('_', ' ').capitalize()} as generated.",
                         data_type))
    return out


# The columns worth describing properly. The generated datasets are new, so
# nothing else in the product knows what these mean unless it is written down.
DELINQUENCY_FIELDS = {
    "period": field("period", "Reporting period", "Reporting quarter, e.g. Q1 2026.",
                    "string"),
    "period_end_date": field("period_end_date", "Period end date",
                             "Last calendar day of the reporting quarter.", "date"),
    "account_id": field("account_id", "Account ID", "Facility identifier.", "string",
                        sensitivity="confidential"),
    "customer_id": field("customer_id", "Customer ID", "Borrower identifier.",
                         "string", sensitivity="confidential"),
    "borrower_name": field("borrower_name", "Borrower", "Registered borrower name.",
                           "string", sensitivity="confidential"),
    "days_past_due": field("days_past_due", "Days past due",
                           "Days the oldest unpaid amount has been outstanding at "
                           "period end. The same figure the facility snapshot "
                           "carries — the two cannot disagree.", "integer", "days"),
    "dpd_bucket": field("dpd_bucket", "Arrears bucket",
                        "Current, 1-29, 30-59, 60-89, 90-179 or 180+ days.", "string"),
    "arrears_amount": field("arrears_amount", "Amount overdue",
                            "Contractual amount past due at period end.", "number",
                            "USD mn"),
    "instalments_missed": field("instalments_missed", "Instalments missed",
                                "Scheduled payments not made.", "integer"),
    "last_payment_date": field("last_payment_date", "Last payment",
                               "Date of the most recent payment received.", "date"),
    "days_since_last_payment": field("days_since_last_payment", "Days since payment",
                                     "Days between the last payment and period end.",
                                     "integer", "days"),
    "forbearance_type": field("forbearance_type", "Forbearance",
                              "Concession granted, if any: payment holiday, term "
                              "extension, interest capitalisation, covenant waiver "
                              "or a restructured facility.", "string"),
    "restructured_flag": field("restructured_flag", "Restructured",
                               "The facility has been restructured.", "boolean"),
    "collections_stage": field("collections_stage", "Collections stage",
                               "How far recovery action has gone: none, soft "
                               "reminder, formal demand, collections, or legal "
                               "recovery.", "string"),
    "cured_this_period": field("cured_this_period", "Cured this period",
                               "In arrears at the previous quarter end and current "
                               "at this one.", "boolean"),
    "newly_delinquent": field("newly_delinquent", "Newly delinquent",
                              "Current at the previous quarter end and in arrears "
                              "at this one.", "boolean"),
    "exposure_at_risk": field("exposure_at_risk", "Exposure at risk",
                              "Exposure at default on facilities 90 or more days "
                              "past due; zero otherwise.", "number", "USD mn"),
}


MEMO_FIELDS = {
    "period": field("period", "Reporting period", "Reporting quarter the memo "
                    "belongs to, e.g. Q1 2026.", "string"),
    "period_end_date": field("period_end_date", "Period end date",
                             "Last calendar day of the reporting quarter.", "date"),
    "memo_id": field("memo_id", "Memo ID", "Credit file note identifier.", "string"),
    "customer_id": field("customer_id", "Customer ID", "Borrower identifier.",
                         "string", sensitivity="confidential"),
    "borrower_name": field("borrower_name", "Borrower", "Registered borrower name.",
                           "string", sensitivity="confidential"),
    "memo_type": field("memo_type", "Memo type",
                       "Annual or interim review, covenant waiver request, site "
                       "visit note, watchlist escalation or committee paper.",
                       "string"),
    "author_role": field("author_role", "Author role",
                         "The role that wrote the note.", "string"),
    "sentiment": field("sentiment", "Sentiment",
                       "Positive, mixed or negative — derived from what the note "
                       "actually raised, not scored separately.", "string"),
    "concerns_raised": field("concerns_raised", "Concerns raised",
                             "How many of the six tracked concerns the note "
                             "mentions.", "integer"),
    "signal_strength_pct": field("signal_strength_pct", "Signal strength",
                                 "Concerns raised as a share of the six tracked.",
                                 "number", "%"),
    "recommendation": field("recommendation", "Recommendation",
                            "The action the author proposed.", "string"),
    "extract": field("extract", "Extract",
                     "A short quotation from the note. Every value begins "
                     "'SYNTHETIC EXTRACT —': assembled from a fixed sentence "
                     "bank, never a real credit opinion about a real company. "
                     "The marker travels with the row into exports, so it "
                     "cannot be mistaken for client information later.",
                     "string", sensitivity="confidential"),
    "is_synthetic_text": field("is_synthetic_text", "Synthetic text",
                               "Always true. The extract is generated, not "
                               "written.", "boolean"),
    "covenant_breach_mentioned": field("covenant_breach_mentioned",
                                       "Covenant breach mentioned",
                                       "The note refers to a covenant breach.",
                                       "boolean"),
    "liquidity_concern_mentioned": field("liquidity_concern_mentioned",
                                         "Liquidity concern mentioned",
                                         "The note refers to constrained liquidity.",
                                         "boolean"),
    "management_change_mentioned": field("management_change_mentioned",
                                         "Management change mentioned",
                                         "The note refers to a change of key "
                                         "management.", "boolean"),
    "sector_headwind_mentioned": field("sector_headwind_mentioned",
                                       "Sector headwind mentioned",
                                       "The note refers to sector conditions "
                                       "worsening.", "boolean"),
    "going_concern_mentioned": field("going_concern_mentioned",
                                     "Going concern mentioned",
                                     "The note refers to a going-concern "
                                     "qualification or material uncertainty.",
                                     "boolean"),
    "receivables_stretch_mentioned": field("receivables_stretch_mentioned",
                                           "Receivables stretch mentioned",
                                           "The note refers to lengthening debtor "
                                           "days.", "boolean"),
}


STAGING_FIELDS = {
    "period": field("period", "Reporting period", "Reporting quarter, e.g. Q1 2026.", "string"),
    "period_end_date": field("period_end_date", "Period end date",
                             "Last calendar day of the reporting quarter.", "date"),
    "account_id": field("account_id", "Account ID", "Facility identifier.", "string",
                        sensitivity="confidential"),
    "customer_id": field("customer_id", "Customer ID", "Borrower identifier.", "string",
                         sensitivity="confidential"),
    "ifrs9_stage": field("ifrs9_stage", "IFRS 9 stage",
                         "Impairment stage at the reporting date: 1 performing, "
                         "2 significant increase in credit risk, 3 credit-impaired.",
                         "integer", "stage"),
    "prior_stage": field("prior_stage", "Prior stage",
                         "The stage this facility carried at the previous reporting date.",
                         "integer", "stage"),
    "stage_moved": field("stage_moved", "Stage moved",
                         "True when the stage differs from the previous reporting date.",
                         "boolean"),
    "pd_at_origination_pct": field(
        "pd_at_origination_pct", "PD at origination",
        "Twelve-month probability of default recorded when the facility was "
        "originated. The comparison point for the IFRS 9 SICR assessment.",
        "number", "%"),
    "pd_ratio_to_origination": field(
        "pd_ratio_to_origination", "PD ratio to origination",
        "Current twelve-month PD divided by the PD at origination.", "number", "x"),
    "notches_since_origination": field(
        "notches_since_origination", "Notches since origination",
        "Internal grades moved since origination. Positive is deterioration.",
        "integer", "notches"),
    "sicr_pd_trigger": field("sicr_pd_trigger", "SICR: PD deterioration",
                             "PD has at least doubled since origination and risen by "
                             "at least 0.55 percentage points.", "boolean"),
    "sicr_dpd_trigger": field("sicr_dpd_trigger", "SICR: days past due",
                              "Thirty or more days past due at the reporting date.",
                              "boolean"),
    "sicr_covenant_trigger": field("sicr_covenant_trigger", "SICR: covenant breach",
                                   "Covenant headroom is negative.", "boolean"),
    "sicr_rating_trigger": field("sicr_rating_trigger", "SICR: rating downgrade",
                                 "Three or more internal grades worse than at "
                                 "origination.", "boolean"),
    "sicr_watchlist_trigger": field("sicr_watchlist_trigger", "SICR: watchlist",
                                    "On the watchlist with an elevated downgrade "
                                    "probability.", "boolean"),
    "sicr_any_trigger": field("sicr_any_trigger", "SICR triggered",
                              "Any significant-increase-in-credit-risk trigger is "
                              "active.", "boolean"),
    "quarters_clean": field("quarters_clean", "Quarters clean",
                            "Consecutive quarters with no active trigger. Two are "
                            "required before a facility may return to Stage 1.",
                            "integer", "count"),
    "data_origin": field("data_origin", "Data origin",
                         "Provenance marker carried on every synthetic row.", "string"),
}

RATINGS_FIELDS = {
    "period": field("period", "Rating year", "The annual rating cycle, e.g. 2025.", "string"),
    "rating_year": field("rating_year", "Rating year",
                         "Calendar year of the rating cycle.", "integer"),
    "customer_id": field("customer_id", "Customer ID", "Borrower identifier.", "string",
                         sensitivity="confidential"),
    "borrower_name": field("borrower_name", "Borrower", "Borrower legal name.", "string",
                           sensitivity="confidential"),
    "internal_grade": field("internal_grade", "Internal grade",
                            "CreditProbe internal grade, 1 (strongest) to 10 (default).",
                            "integer", "grade"),
    "risk_rating": field("risk_rating", "Risk rating",
                         "CreditProbe internal rating symbol, CP-1 to CP-10.", "string"),
    "external_rating": field("external_rating", "External rating",
                             "Agency-style external rating held at the cycle date.",
                             "string"),
    "revenue_usd_mn": field("revenue_usd_mn", "Revenue",
                            "Annual revenue at the rating date.", "number", "USD mn"),
    "net_leverage": field("net_leverage", "Net leverage",
                          "Net debt divided by EBITDA at the rating date.", "number", "x"),
    "interest_coverage": field("interest_coverage", "Interest coverage",
                               "EBITDA divided by interest expense.", "number", "x"),
    "current_ratio": field("current_ratio", "Current ratio",
                           "Current assets divided by current liabilities.", "number", "x"),
    "ebitda_margin_pct": field("ebitda_margin_pct", "EBITDA margin",
                               "EBITDA as a percentage of revenue.", "number", "%"),
    "rating_action": field("rating_action", "Rating action",
                           "Upgrade, Downgrade, Affirmed, or Initial rating.", "string"),
    "prior_internal_grade": field("prior_internal_grade", "Prior internal grade",
                                  "Internal grade at the previous annual cycle.",
                                  "integer", "grade"),
    "notches_moved": field("notches_moved", "Notches moved",
                           "Grades moved since the previous cycle. Positive is a "
                           "downgrade.", "integer", "notches"),
    "data_origin": field("data_origin", "Data origin",
                         "Provenance marker carried on every synthetic row.", "string"),
}

MACRO_FIELDS = {
    "period": field("period", "Reporting period", "Calendar quarter, e.g. Q1 2026.", "string"),
    "period_end_date": field("period_end_date", "Period end date",
                             "Last calendar day of the quarter.", "date"),
    "real_gdp_growth_pct": field("real_gdp_growth_pct", "Real GDP growth",
                                 "Year-on-year real GDP growth.", "number", "%"),
    "non_oil_gdp_growth_pct": field("non_oil_gdp_growth_pct", "Non-oil GDP growth",
                                    "Year-on-year growth in non-oil real GDP.",
                                    "number", "%"),
    "oil_gdp_growth_pct": field("oil_gdp_growth_pct", "Oil GDP growth",
                                "Year-on-year growth in oil real GDP.", "number", "%"),
    "brent_usd_bbl": field("brent_usd_bbl", "Brent crude",
                           "Average Brent crude price over the quarter.",
                           "number", "USD/bbl"),
    "sama_policy_rate_pct": field("sama_policy_rate_pct", "Policy rate",
                                  "Central bank policy rate at the quarter end.",
                                  "number", "%"),
    "inflation_pct": field("inflation_pct", "Inflation",
                           "Year-on-year consumer price inflation.", "number", "%"),
    "pmi_index": field("pmi_index", "PMI", "Purchasing managers' index. Above 50 is "
                       "expansion.", "number", "index"),
    "unemployment_pct": field("unemployment_pct", "Unemployment",
                              "National unemployment rate.", "number", "%"),
    "real_estate_price_index": field("real_estate_price_index", "Real estate price index",
                                     "Composite real estate price index, first quarter "
                                     "of the series = 100.", "number", "index"),
    "credit_cycle_factor": field(
        "credit_cycle_factor", "Credit cycle factor",
        "The single systematic factor the borrower simulation responds to. "
        "Positive is a supportive quarter for credit quality; negative is a "
        "hostile one. Derived from the series above, not observed.",
        "number", "z"),
    "data_origin": field("data_origin", "Data origin",
                         "Provenance marker carried on every synthetic row.", "string"),
}


def main() -> int:
    from scripts.build_data_lake import (  # noqa: PLC0415 - optional reuse
        BORROWER_FIELDS,
        FACILITY_FIELDS,
        build_field_defs,
        read_source_dictionary,
    )

    print("Generating the CreditProbe Saudi demonstration universe")
    print()
    rng = np.random.default_rng(SEED)

    log(f"Seed {SEED} — the same universe on every machine, every time.")
    macro = macro_series(rng)
    log(f"macro_saudi: {len(macro)} quarters ({MACRO_PERIODS[0]} to {MACRO_PERIODS[-1]})")

    customers = build_customers(rng)
    log(f"Customers: {len(customers):,} across {len(SECTORS)} sectors and "
        f"{len(REGIONS)} regions")

    factor = macro.set_index("period").loc[PERIODS, "credit_cycle_factor"].to_numpy()
    z = simulate_quality(customers, factor, rng)
    facility, staging = build_book(customers, z, macro, rng)
    per_quarter = len(facility) // N_QUARTERS
    log(f"portfolio_facility: {len(facility):,} rows over {N_QUARTERS} quarters "
        f"({per_quarter:,} facilities a quarter)")

    moves = staging[staging["stage_moved"]]
    log(f"ifrs9_staging: {len(staging):,} rows, {len(moves):,} stage migrations")
    for target, label in (
        ((staging["prior_stage"] == 1) & (staging["ifrs9_stage"] == 2), "Stage 1 to 2"),
        ((staging["prior_stage"] == 1) & (staging["ifrs9_stage"] == 3), "Stage 1 to 3"),
        ((staging["prior_stage"] == 2) & (staging["ifrs9_stage"] == 3), "Stage 2 to 3"),
    ):
        log(f"    {label}: {int(target.sum()):,}")

    ratings = build_ratings(customers, macro, rng)
    log(f"customer_ratings: {len(ratings):,} rows over {len(RATING_YEARS)} annual cycles "
        f"({RATING_YEARS[0]} to {RATING_YEARS[-1]})")

    financials = build_borrower_financials(customers, ratings)
    log(f"borrower_financials: {len(financials):,} rows")

    delinquency = build_delinquency(facility, rng)
    in_arrears = int((delinquency["days_past_due"] > 0).sum())
    log(f"facility_delinquency: {len(delinquency):,} rows, {in_arrears:,} in arrears "
        f"({100.0 * in_arrears / len(delinquency):.1f}% of facility-quarters)")
    for label in ("30-59 days", "60-89 days", "90-179 days", "180+ days"):
        count = int((delinquency["dpd_bucket"] == label).sum())
        log(f"    {label}: {count:,}")

    memos = build_credit_memos(customers, facility, rng)
    negative = int((memos["sentiment"] == "negative").sum())
    log(f"credit_memo_signals: {len(memos):,} notes, {negative:,} negative "
        f"({100.0 * negative / len(memos):.1f}%)")

    print()
    print("ANALYTICS layer — Parquet, partitioned by period")
    parts = write_partitioned(facility, settings.analytics_dir / "portfolio_facility", "period")
    log(f"portfolio_facility: {parts} period partitions")
    parts = write_partitioned(staging, settings.analytics_dir / "ifrs9_staging", "period")
    log(f"ifrs9_staging: {parts} period partitions")
    parts = write_partitioned(ratings, settings.analytics_dir / "customer_ratings", "period")
    log(f"customer_ratings: {parts} annual partitions")
    parts = write_partitioned(macro, settings.analytics_dir / "macro_saudi", "period")
    log(f"macro_saudi: {parts} period partitions")
    parts = write_partitioned(
        delinquency, settings.analytics_dir / "facility_delinquency", "period")
    log(f"facility_delinquency: {parts} period partitions")
    parts = write_partitioned(
        memos, settings.analytics_dir / "credit_memo_signals", "period")
    log(f"credit_memo_signals: {parts} period partitions")
    write_partitioned(financials, settings.analytics_dir / "borrower_financials", None)
    log("borrower_financials: 1 file (no period dimension)")

    settings.curated_dir.mkdir(parents=True, exist_ok=True)
    facility.to_parquet(settings.curated_dir / "portfolio_facility.parquet", index=False)
    financials.to_parquet(settings.curated_dir / "borrower_financials.parquet", index=False)

    # ------------------------------------------------------------- catalogue
    print()
    print("METADATA — governed catalogue")
    source = settings.raw_dir / "Portfolio_Monitoring_Dataset.xlsx"
    if source.exists():
        with pd.ExcelFile(source) as xl:
            dictionary = read_source_dictionary(xl)
    else:  # pragma: no cover - the workbook ships with the repository
        dictionary = {}

    # The facility and borrower field definitions are the published ones, so a
    # governed name means the same thing here as it did before.
    reverse = {governed: src for src, governed in FACILITY_FIELDS.items()}
    facility_fields = build_field_defs(
        {reverse[c]: c for c in facility.columns if c in reverse},
        dictionary,
        set(reverse[c] for c in facility.columns if c in reverse),
    )
    reverse_b = {governed: src for src, governed in BORROWER_FIELDS.items()}
    borrower_fields = build_field_defs(
        {reverse_b[c]: c for c in financials.columns if c in reverse_b},
        dictionary,
        set(reverse_b[c] for c in financials.columns if c in reverse_b),
    )

    catalog = {
        "version": "2.0.0",
        "generated_from": "scripts/generate_saudi_universe.py",
        "datasets": [
            {
                "name": "portfolio_facility",
                "domain": "Core Portfolio / Facility",
                "business_name": "Portfolio Facility Snapshot",
                "purpose": (
                    "Quarter-end position of every credit facility: exposure, limits, "
                    "collateral, rating, IFRS 9 staging, PD/LGD/ECL and early-warning "
                    "signals."
                ),
                "grain": "One row per facility (account) per reporting period.",
                "primary_keys": ["period", "account_id"],
                "period_field": "period",
                "owner": "Credit Risk Analytics",
                "status": "active",
                "version": "2.0.0",
                "is_synthetic": True,
                "origin": "demo",
                "dataset_family": "portfolio_facility",
                "authoritative_for": ["credit_facility_position"],
                "fields": facility_fields,
            },
            {
                "name": "ifrs9_staging",
                "domain": "IFRS 9 Impairment",
                "business_name": "IFRS 9 Staging and SICR Assessment",
                "purpose": (
                    "The staging decision behind every facility: the PD at "
                    "origination it is measured against, each SICR trigger "
                    "separately, the stage before and after, and the resulting ECL."
                ),
                "grain": "One row per facility per reporting period.",
                "primary_keys": ["period", "account_id"],
                "period_field": "period",
                "owner": "Credit Risk Analytics",
                "status": "active",
                "version": "1.0.0",
                "is_synthetic": True,
                "origin": "demo",
                "dataset_family": "ifrs9_staging",
                "authoritative_for": ["ifrs9_impairment_staging"],
                "fields": infer_fields(staging, STAGING_FIELDS),
            },
            {
                "name": "facility_delinquency",
                "domain": "Arrears and Collections",
                "business_name": "Facility Arrears and Collections",
                "purpose": (
                    "Days past due, the arrears bucket, the amount overdue, "
                    "forbearance granted and how far collections has escalated, "
                    "for every facility at every quarter end."
                ),
                "grain": "One row per facility (account) per reporting period.",
                "primary_keys": ["period", "account_id"],
                "period_field": "period",
                "owner": "Credit Risk Operations",
                "status": "active",
                "version": "1.0.0",
                "is_synthetic": True,
                "origin": "demo",
                "dataset_family": "facility_delinquency",
                "authoritative_for": ["facility_delinquency"],
                "fields": infer_fields(delinquency, DELINQUENCY_FIELDS),
            },
            {
                "name": "credit_memo_signals",
                "domain": "Credit File and Commentary",
                "business_name": "Credit Memo Signals",
                "purpose": (
                    "What the credit file says, as structured signals: covenant "
                    "breaches, liquidity concerns, management changes, sector "
                    "headwinds and going-concern language, with the extract that "
                    "raised each one."
                ),
                "grain": "One row per credit file note.",
                "primary_keys": ["memo_id"],
                "period_field": "period",
                "owner": "Credit Risk Analytics",
                "status": "active",
                "version": "1.0.0",
                "is_synthetic": True,
                "origin": "demo",
                "dataset_family": "credit_memo_signals",
                "authoritative_for": ["credit_file_commentary"],
                "fields": infer_fields(memos, MEMO_FIELDS),
            },
            {
                "name": "customer_ratings",
                "domain": "Corporate Ratings",
                "business_name": "Annual Customer Rating History",
                "purpose": (
                    "Eight annual rating cycles for every customer: the internal "
                    "grade awarded, the financials behind it, and the action taken "
                    "against the previous year."
                ),
                "grain": "One row per customer per rating year.",
                "primary_keys": ["period", "customer_id"],
                "period_field": "period",
                "owner": "Credit Risk Analytics",
                "status": "active",
                "version": "1.0.0",
                "is_synthetic": True,
                "origin": "demo",
                "dataset_family": "customer_ratings",
                "authoritative_for": ["customer_rating_history"],
                "fields": infer_fields(ratings, RATINGS_FIELDS),
            },
            {
                "name": "borrower_financials",
                "domain": "Corporate Ratings",
                "business_name": "Borrower Financials & External Ratings",
                "purpose": (
                    "Borrower-level financial ratios across two fiscal years plus the "
                    "external rating and its gap to the internal rating."
                ),
                "grain": "One row per borrower (customer).",
                "primary_keys": ["customer_id"],
                "period_field": "",
                "owner": "Credit Risk Analytics",
                "status": "active",
                "version": "2.0.0",
                "is_synthetic": True,
                "origin": "demo",
                "dataset_family": "borrower_financials",
                "authoritative_for": ["borrower_financials"],
                "fields": borrower_fields,
            },
            {
                "name": "macro_saudi",
                "domain": "Macroeconomic",
                "business_name": "Saudi Macroeconomic Series",
                "purpose": (
                    "Quarterly macroeconomic series and the single credit cycle "
                    "factor derived from them, which is what the portfolio simulation "
                    "actually responds to."
                ),
                "grain": "One row per calendar quarter.",
                "primary_keys": ["period"],
                "period_field": "period",
                "owner": "Credit Risk Analytics",
                "status": "active",
                "version": "1.0.0",
                "is_synthetic": True,
                "origin": "demo",
                "dataset_family": "macro_saudi",
                "authoritative_for": ["macroeconomic_series"],
                "fields": infer_fields(macro, MACRO_FIELDS),
            },
        ],
        "quality_findings": [],
        "lineage": [
            {"step": "raw", "detail":
                "None. This universe is simulated by scripts/generate_saudi_universe.py "
                f"from seed {SEED}; there is no source file, and re-running reproduces "
                "it exactly."},
            {"step": "curated", "detail":
                "Governed field names, declared types and published units applied at "
                "generation; percentages are true percentages throughout."},
            {"step": "analytics", "detail":
                "Parquet partitioned by reporting period; read by DuckDB through the "
                "Data Access Layer."},
        ],
        "synthetic_notice": DEMO_NOTE,
    }

    settings.metadata_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = settings.metadata_dir / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    log(f"{catalog_path} — {len(catalog['datasets'])} governed datasets")

    print()
    print("Done. Every row is marked SYNTHETIC and describes no real borrower.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
