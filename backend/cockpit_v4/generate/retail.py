"""
A Saudi retail credit book, twenty months of it, at a real retail grain.

Retail is not corporate with different words
--------------------------------------------
A corporate facility is one large exposure to one obligor, watched
individually. A retail account is one of thousands, watched as a population:
what matters is how a PRODUCT, a SCORE BAND, a DELINQUENCY BUCKET or a
VINTAGE is moving, and the individual account matters when it falls out of
one of those. So the grain here is customer x account x month, the
behavioural score and the variables behind it are first-class, and the
segmentation is product and score band rather than sector.

The authored stories
--------------------
Credit Card utilisation and delinquency build through the window while
Mortgage stays sound; the 2024 Personal Finance vintage deteriorates well
ahead of the 2025 one; score band D thins as its accounts fall into E; and a
cohort of Auto Finance accounts cures and improves. Not everything worsens,
because a book where it does teaches an analyst nothing about telling signal
from level.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.generate import month_range, months_between

SEED = 20260802

#: A retail book is a POPULATION. At nine hundred customers the portfolio
#: came to six million riyals of ECL and the attention cards read "up SAR 0
#: million" -- arithmetically true and useless, because the book was too
#: small for the unit it is denominated in. A mass-market book is tens of
#: thousands of accounts; this is the smallest number that makes the figures
#: read like a portfolio rather than a branch.
CUSTOMERS = 9000

PRODUCTS: tuple[tuple[str, int, float, float, float], ...] = (
    # (product, secured, share, base limit SAR mn, base LGD)
    ("Mortgage", 1, 0.22, 1.35, 0.18),
    ("Personal Finance", 0, 0.31, 0.22, 0.62),
    ("Auto Finance", 1, 0.19, 0.16, 0.42),
    ("Credit Card", 0, 0.28, 0.055, 0.78),
)

SEGMENTS = ("Mass", "Affluent", "Private", "Payroll")
REGIONS = ("Riyadh", "Makkah", "Eastern Province", "Madinah", "Qassim",
           "Asir", "Tabuk", "Hail")
BANDS = ("A", "B", "C", "D", "E")

#: How hard each product's population is pushed over the window.
PRODUCT_STRESS: dict[str, float] = {
    "Credit Card": 1.00,
    "Personal Finance": 0.62,
    "Auto Finance": -0.25,
    "Mortgage": 0.08,
}

#: What the composite pressure is worth in absolute terms.
#:
#: Tuned against the book it produces, not chosen first. At 1.0 the stressed
#: products came out with ninety-seven per cent of card accounts in Stage 2 --
#: arithmetically consistent and not a portfolio any bank would recognise, so
#: every question asked of it would have a silly answer. The deterioration is
#: meant to be findable, not total.
STRESS_SCALE = 0.27

#: Monthly probability that a CURRENT account misses a payment, before the
#: account's own fragility and the product's stress are applied.
#:
#: Delinquency is not a threshold on a smooth stress index. Modelled that
#: way -- which is how this generator began -- the worst account in the book
#: reached eighty days past due and SEVEN accounts out of twelve thousand
#: ever defaulted, because a smooth index has no tail. A retail book without
#: a tail has no non-performing population, so every question about arrears,
#: Stage 3, write-offs, cures or coverage answers "approximately nothing" and
#: means nothing.
#:
#: So arrears are a ROLL-RATE process: an account enters at a hazard, then
#: each month either cures or rolls thirty days deeper, and one deep enough
#: is charged off and leaves the book. Stress raises the entry hazard and
#: slows the cure; it does not decide the outcome.
ENTRY_HAZARD: dict[str, float] = {
    "Credit Card": 0.022,
    "Personal Finance": 0.015,
    "Auto Finance": 0.008,
    "Mortgage": 0.0035,
}

#: Monthly probability that a delinquent account cures, before depth,
#: fragility and stress. Cure gets materially harder the deeper the arrears:
#: a bucket an account has sat in for four months is not one it walks out of
#: at the same rate as the first missed payment.
CURE_RATE: dict[str, float] = {
    "Credit Card": 0.30,
    "Personal Finance": 0.27,
    "Auto Finance": 0.34,
    "Mortgage": 0.40,
}

#: Days past due at which the account is charged off, written down and
#: leaves the book. Saudi retail practice and IFRS 9 both put the
#: write-off point well past the ninety-day default marker.
CHARGE_OFF_DPD = 210

#: How much of the exposure is written off at charge-off, and how much of
#: THAT comes back. Secured products recover more, which is what the security
#: is for.
WRITE_OFF_FRACTION = 0.82
RECOVERY_OF_WRITE_OFF = {0: 0.14, 1: 0.46}

#: Older vintages carry more of the stress. A 2024 book has been through more
#: than a 2026 one and it should show.
VINTAGE_STRESS: dict[int, float] = {2021: 0.15, 2022: 0.30, 2023: 0.55,
                                    2024: 0.95, 2025: 0.45, 2026: 0.10}


def _band(score: float) -> str:
    if score >= 780:
        return "A"
    if score >= 700:
        return "B"
    if score >= 620:
        return "C"
    if score >= 540:
        return "D"
    return "E"


def _bucket(dpd: int) -> str:
    if dpd <= 0:
        return "Current"
    if dpd < 30:
        return "1-29"
    if dpd < 60:
        return "30-59"
    if dpd < 90:
        return "60-89"
    return "90+"


def _unit(key: str, month: str) -> float:
    """A stable uniform draw in [0, 1) for one entity in one month.

    Hashed rather than drawn from a stream, so the roll-rate process is a
    pure function of who and when: two builds produce the same arrears, and
    adding a customer does not reshuffle everyone else's.
    """
    digest = hashlib.sha256(f"roll|{key}|{month}".encode("utf-8")).digest()
    return int.from_bytes(digest[:6], "big") / float(1 << 48)


def _jitter(key: str, month: str, spread: float) -> float:
    """A per-(entity, month) wobble that is stable across builds.

    Without it every account drifts the same way every month and the book
    reads as a metronome: eight hundred customers "DETERIORATED" and fifteen
    "IMPROVED", which tells an analyst nothing because it is true of
    everyone. Real months are mixed even inside a deteriorating trend, and a
    score that only ever falls is not a score anybody would act on.

    Hashed rather than drawn, so it is a pure function of who and when and
    two builds fingerprint identically.
    """
    digest = hashlib.sha256(f"{key}|{month}".encode("utf-8")).digest()
    unit = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return (unit - 0.5) * 2 * spread


def _ramp(index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    x = index / (total - 1)
    # Eases in and keeps going. Smoothstep was the first shape here and its
    # slope falls to zero at BOTH ends, so the last few months of the window
    # barely moved -- which made every month-on-month attention card tiny and
    # left the feed with two findings on a book that had plainly changed. A
    # book whose story stops before its last month is a book nobody can ask
    # "what moved this month".
    return x ** 1.55


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build(release_id: str = "",
          tenant_id: str = lake.DEFAULT_TENANT) -> lake.Build:
    import pandas as pd

    release_id = release_id or dom.DEFAULT_RELEASES[dom.RETAIL]
    months = month_range()
    rng = random.Random(SEED)

    weights = [p[2] for p in PRODUCTS]
    customers: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    for index in range(CUSTOMERS):
        customer_id = f"RC{index + 1:06d}"
        segment = SEGMENTS[index % len(SEGMENTS)]
        customers.append({
            "customer_id": customer_id,
            "customer_segment": segment,
            "region": REGIONS[(index * 3) % len(REGIONS)],
            "base_tenure": rng.randint(6, 168),
            "base_score": rng.uniform(520, 860),
            "quality": rng.uniform(0.0, 1.0),
        })
        for slot in range(1 if index % 3 else 2):
            product, secured, _, base_limit, base_lgd = rng.choices(
                PRODUCTS, weights=weights, k=1)[0]
            # Origination is spread back before the window so vintages differ.
            origin_year = rng.choices([2021, 2022, 2023, 2024, 2025, 2026],
                                      weights=[5, 9, 16, 26, 30, 14], k=1)[0]
            origin_month = rng.randint(1, 12)
            if origin_year == 2026:
                origin_month = min(origin_month, 8)
            accounts.append({
                "account_id": f"RA{index + 1:06d}{slot}",
                "customer_id": customer_id,
                "product": product, "secured_flag": secured,
                "origination_month": f"{origin_year:04d}-{origin_month:02d}",
                "vintage_year": origin_year,
                "base_limit": round(base_limit * rng.uniform(0.5, 2.4), 4),
                "base_util": rng.uniform(0.18, 0.94),
                "base_lgd": base_lgd,
                "wobble": rng.uniform(-0.04, 0.04),
                "cure_cohort": rng.random() < 0.08,
                # Heavy-tailed on purpose: most accounts are near zero and a
                # few are genuinely fragile. A uniform draw here would give
                # every account the same modest chance of arrears and
                # produce a book with no tail, which is the defect this
                # replaces.
                "fragility": round(rng.random() ** 3.0, 6),
            })

    by_id = {c["customer_id"]: c for c in customers}
    gov = {"tenant_id": tenant_id, "dataset_release_id": release_id,
           "domain_id": dom.RETAIL, "reporting_currency": lake.CURRENCY}

    account_rows: list[dict[str, Any]] = []
    behaviour_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    customer_rows: list[dict[str, Any]] = []
    previous_score: dict[str, float] = {}
    previous_util: dict[str, float] = {}
    previous_balance: dict[str, float] = {}
    streak: dict[str, int] = {}
    #: Days past due carried into the next month, and the accounts that have
    #: been charged off and no longer report.
    arrears: dict[str, int] = {}
    charged_off: set[str] = set()

    for m_index, month in enumerate(months):
        ramp = _ramp(m_index, len(months))
        season = math.sin((m_index % 12) / 12 * 2 * math.pi)
        per_customer: dict[str, list[dict[str, Any]]] = {}

        for account in accounts:
            if months_between(account["origination_month"], month) < 0:
                continue  # not opened yet: no row rather than a zero row
            if account["account_id"] in charged_off:
                continue  # written off and closed: no row rather than zeros
            customer = by_id[account["customer_id"]]
            on_book = months_between(account["origination_month"], month)

            stress = PRODUCT_STRESS.get(account["product"], 0.0) * ramp
            stress *= 0.6 + 0.9 * VINTAGE_STRESS.get(account["vintage_year"],
                                                     0.4)
            personal = (stress * STRESS_SCALE
                        * (0.5 + 1.0 * (1 - customer["quality"])))
            personal += _jitter(account["account_id"] + "p", month, 0.07)
            if account["cure_cohort"] and m_index > len(months) // 2:
                # A cohort that works its way back. Real books have these and
                # a book without them reads as a one-way slide.
                personal -= 0.35 * _ramp(m_index - len(months) // 2,
                                         len(months) // 2)

            limit = account["base_limit"] * (1 + 0.002 * on_book)
            util = _clamp(account["base_util"] + 0.20 * personal
                          + 0.03 * season + account["wobble"]
                          + _jitter(account["account_id"], month, 0.05),
                          0.01, 1.22)
            balance = limit * min(util, 1.15)
            ead = balance if account["product"] != "Credit Card" else (
                balance + max(0.0, limit - balance) * 0.45)

            score = _clamp(customer["base_score"] - 190 * personal
                           + 9 * season
                           + _jitter(account["customer_id"], month, 26.0),
                           300, 900)
            band = _band(score)
            prior_score = previous_score.get(account["customer_id"], score)

            # The roll-rate process. Entry, then cure or roll, then
            # charge-off. Stress moves the rates; it does not set the state.
            account_id = account["account_id"]
            prior_dpd = arrears.get(account_id, 0)
            pressure = max(0.0, personal)
            draw = _unit(account_id, month)
            fragility = account["fragility"]
            if prior_dpd <= 0:
                hazard = (ENTRY_HAZARD[account["product"]]
                          * (0.25 + 3.1 * fragility)
                          * (1.0 + 2.6 * pressure))
                dpd = (4 + int(24 * _unit(account_id + "entry", month))
                       if draw < hazard else 0)
            else:
                depth = min(1.0, prior_dpd / float(CHARGE_OFF_DPD))
                cure = (CURE_RATE[account["product"]]
                        * (1.25 - 0.85 * fragility)
                        * (1.0 - 0.72 * depth)
                        / (1.0 + 1.4 * pressure))
                dpd = 0 if draw < cure else prior_dpd + 30
            was = streak.get(account_id, 0)
            streak[account_id] = was + 1 if dpd > 0 else 0
            arrears[account_id] = dpd

            # Staging from OBSERVABLE triggers, not from the stress index.
            #
            # Reading Stage 2 off a smooth index put forty-eight per cent of
            # the card book in Stage 2 while five per cent of it was actually
            # in arrears -- a book no bank would recognise, and one where
            # "what drove the Stage 2 increase?" has no answer an analyst
            # could act on. The triggers below are the ones a retail SICR
            # policy actually uses: thirty days past due, an absolute score
            # floor below the lowest band boundary, and a material fall from
            # the score the account was written at.
            score_fall = customer["base_score"] - score
            if dpd >= 90:
                stage = 3
            elif dpd >= 30 or score < 520 or score_fall > 105:
                stage = 2
            else:
                stage = 1
            lgd = _clamp(account["base_lgd"] + 0.10 * personal
                         - (0.12 if account["secured_flag"] else 0.0),
                         0.05, 0.92)
            if stage == 3:
                # An account ninety days past due has defaulted. Pricing it
                # off a score-driven PD of a few per cent put the Stage 3
                # coverage of this book at twelve per cent, which says the
                # bank expects to collect eighty-eight per cent of its
                # non-performing retail book. It does not.
                pd_pit = pd_life = 1.0
                ecl_12m = ecl_life = ead * lgd
            else:
                pd_pit = _clamp(0.006 * math.exp((900 - score) / 150)
                                + 0.02 * personal, 0.0004, 0.92)
                pd_life = _clamp(pd_pit * (2.2 + 1.8 * personal), pd_pit,
                                 0.98)
                ecl_12m = ead * pd_pit * lgd
                ecl_life = ead * pd_life * lgd
            ecl = ecl_12m if stage == 1 else ecl_life
            # Charge-off: the account is written down in THIS month's row and
            # reports no month after it. The write-off is a flow and the row
            # that carries it is the last one the account has.
            wrote_off = 0.0
            recovered = 0.0
            if dpd >= CHARGE_OFF_DPD:
                wrote_off = ead * WRITE_OFF_FRACTION
                recovered = wrote_off * RECOVERY_OF_WRITE_OFF[
                    account["secured_flag"]]
                charged_off.add(account_id)
                # A charged-off account is fully provided at the point it
                # leaves: carrying a lifetime ECL below the amount written
                # off would say the book expected to keep it.
                ecl = max(ecl, wrote_off - recovered)
                ecl_life = max(ecl_life, ecl)
            cured = 1 if (was > 0 and dpd == 0) else 0

            row = {
                **gov,
                "account_id": account["account_id"],
                "customer_id": account["customer_id"],
                "reporting_month": month, "product": account["product"],
                "secured_flag": account["secured_flag"],
                "origination_month": account["origination_month"],
                "vintage_year": account["vintage_year"],
                "months_on_book": on_book,
                "customer_segment": customer["customer_segment"],
                "region": customer["region"],
                "limit_sar_mn": round(limit, 5),
                "balance_sar_mn": round(balance, 5),
                "ead_sar_mn": round(ead, 5),
                "utilisation_pct": round(util * 100, 3),
                "stage": stage, "sicr_flag": 1 if stage >= 2 else 0,
                "default_flag": 1 if stage == 3 else 0,
                "dpd_days": dpd, "delinquency_bucket": _bucket(dpd),
                "pd_pit_12m": round(pd_pit, 6),
                "pd_lifetime": round(pd_life, 6),
                "lgd_pct": round(lgd * 100, 3),
                "ecl_12m_sar_mn": round(ecl_12m, 6),
                "ecl_lifetime_sar_mn": round(ecl_life, 6),
                "ecl_sar_mn": round(ecl, 6),
                "write_off_sar_mn": round(wrote_off, 6),
                "recovery_sar_mn": round(recovered, 6),
                "cure_flag": cured,
                "behaviour_score": round(score, 2), "score_band": band,
            }
            account_rows.append(row)
            per_customer.setdefault(account["customer_id"], []).append(row)

            prior_util = previous_util.get(account["account_id"], util)
            prior_balance = previous_balance.get(account["account_id"],
                                                 balance)
            previous_util[account["account_id"]] = util
            previous_balance[account["account_id"]] = balance
            behaviour_rows.append({
                **gov,
                "account_id": account["account_id"],
                "customer_id": account["customer_id"],
                "reporting_month": month, "product": account["product"],
                "utilisation_pct": round(util * 100, 3),
                "utilisation_change_pp": round((util - prior_util) * 100, 3),
                "payment_ratio_pct": round(
                    _clamp(38 - 26 * personal + 4 * season, 0.0, 100.0), 3),
                "missed_payments_12m": int(max(0, round(personal * 5.2))),
                "delinquency_streak_months": streak[account["account_id"]],
                "balance_growth_pct": round(
                    (balance - prior_balance) / max(prior_balance, 1e-6)
                    * 100, 3),
                "cash_advance_ratio_pct": round(
                    _clamp(3 + 22 * personal, 0.0, 60.0), 3)
                if account["product"] == "Credit Card" else 0.0,
                "overlimit_flag": 1 if util > 1.0 else 0,
                "inflow_change_pct": round(-9.5 * personal + 2.5 * season, 3),
                "bureau_inquiries_6m": int(max(0, round(personal * 4.4))),
                "repayment_behaviour_score": round(
                    _clamp(82 - 55 * personal, 2, 99), 2),
            })

            if account["secured_flag"]:
                drift = -0.10 if account["product"] == "Mortgage" else -0.22
                value = (limit * (1.32 if account["product"] == "Mortgage"
                                  else 1.18)
                         * (1 + drift * (on_book / 60.0)))
                collateral_rows.append({
                    **gov,
                    "account_id": account["account_id"],
                    "customer_id": account["customer_id"],
                    "reporting_month": month, "product": account["product"],
                    "collateral_type": ("Residential Property"
                                        if account["product"] == "Mortgage"
                                        else "Motor Vehicle"),
                    "collateral_value_sar_mn": round(value, 5),
                    "ltv_pct": round(balance / max(value, 1e-6) * 100, 3),
                    "collateral_coverage_pct": round(
                        value / max(ead, 1e-6) * 100, 3),
                    "valuation_age_months": (on_book % 18) + 1,
                })

        for customer_id, rows in per_customer.items():
            customer = by_id[customer_id]
            score = sum(r["behaviour_score"] for r in rows) / len(rows)
            prior = previous_score.get(customer_id, score)
            previous_score[customer_id] = score
            band, prior_band = _band(score), _band(prior)
            customer_rows.append({
                **gov,
                "customer_id": customer_id, "reporting_month": month,
                "customer_segment": customer["customer_segment"],
                "region": customer["region"],
                "tenure_months": customer["base_tenure"] + m_index,
                "accounts_held": len(rows),
                "behaviour_score": round(score, 2),
                "behaviour_score_previous": round(prior, 2),
                "behaviour_score_change": round(score - prior, 2),
                "score_band": band, "score_band_previous": prior_band,
                "score_migration": ("DETERIORATED" if score < prior - 2
                                    else "IMPROVED" if score > prior + 2
                                    else "STABLE"),
                "total_ead_sar_mn": round(
                    sum(r["ead_sar_mn"] for r in rows), 5),
                "total_ecl_sar_mn": round(
                    sum(r["ecl_sar_mn"] for r in rows), 6),
                "worst_stage": max(r["stage"] for r in rows),
                "worst_dpd_days": max(r["dpd_days"] for r in rows),
            })

    frames = {
        "retail_customer_month": pd.DataFrame(customer_rows),
        "retail_account_month": pd.DataFrame(account_rows),
        "retail_behaviour_month": pd.DataFrame(behaviour_rows),
        "retail_collateral_month": pd.DataFrame(collateral_rows),
    }
    return lake.Build(
        domain_id=dom.RETAIL, release_id=release_id, periods=months,
        frames=frames,
        counts={"customers": len(customers), "accounts": len(accounts),
                "products": len(PRODUCTS), "regions": len(REGIONS)},
        notes={"score_bands": list(BANDS),
               "stressed_products": [p for p, v in PRODUCT_STRESS.items()
                                     if v > 0.3],
               "improving_products": [p for p, v in PRODUCT_STRESS.items()
                                      if v < 0]})


__all__ = ["BANDS", "CUSTOMERS", "PRODUCTS", "PRODUCT_STRESS", "build"]
