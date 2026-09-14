"""
A Saudi corporate credit book, twenty months of it, with things to find.

What this is not
----------------
It is not noise. A synthetic book whose every metric wanders randomly is
useless for the thing it exists to support: an analyst asking "what is
deteriorating and why" and getting an answer that holds together. So the
dynamics here are authored -- a few sectors under real stress, a downgrade
cluster that shows up in ratings before it shows up in stage, covenant
headroom eroding where leverage is rising, collateral values softening in
one sector and firming in another -- and the rest of the book is stable or
quietly improving, because a portfolio where everything worsens at once is
its own kind of unbelievable.

Determinism
-----------
Every number comes from a seeded generator and a pure function of
(entity, month). Two builds of the same release id produce byte-identical
parquet and therefore the same fingerprint, which is what makes the
fingerprint worth checking.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.generate import month_range, months_between

SEED = 20260801

#: Fictional Saudi and GCC-style names. No real institution is described.
BORROWERS: tuple[tuple[str, str, str, str], ...] = (
    # (name, sector, sub_sector, region)
    ("Al Noor Infrastructure", "Construction", "Civil Infrastructure", "Riyadh"),
    ("Tuwaiq Construction", "Construction", "Building Contracting", "Riyadh"),
    ("Najd Manufacturing", "Manufacturing", "Industrial Products", "Qassim"),
    ("Rawabi Industrial Works", "Manufacturing", "Metal Fabrication", "Eastern Province"),
    ("Eastern Petrochemicals", "Chemicals", "Petrochemicals", "Eastern Province"),
    ("Jubail Specialty Chemicals", "Chemicals", "Specialty Chemicals", "Eastern Province"),
    ("Red Sea Logistics", "Transport and Logistics", "Freight", "Makkah"),
    ("Hijaz Freight Services", "Transport and Logistics", "Land Transport", "Madinah"),
    ("Gulf Horizon Trading", "Wholesale Trade", "General Trading", "Riyadh"),
    ("Al Waha Healthcare", "Healthcare", "Hospitals", "Riyadh"),
    ("Kingdom Technology Services", "Information Technology", "IT Services", "Riyadh"),
    ("Sadara Digital Systems", "Information Technology", "Software", "Eastern Province"),
    ("Asir Agri Processing", "Agriculture and Agri-processing", "Food Processing", "Asir"),
    ("Yanbu Power Partners", "Power and Utilities", "Generation", "Madinah"),
    ("Tabuk Renewables", "Power and Utilities", "Renewables", "Tabuk"),
    ("Al Rawdah Real Estate", "Real Estate", "Commercial Property", "Riyadh"),
    ("Jeddah Waterfront Development", "Real Estate", "Mixed Use", "Makkah"),
    ("Hail Retail Group", "Retail Trade", "Department Stores", "Hail"),
    ("Arabian Metals and Mining", "Metals and Mining", "Mining", "Northern Borders"),
    ("Al Fanar Hospitality", "Hospitality", "Hotels", "Makkah"),
)

GROUPS: dict[str, str] = {
    "Construction": "Tuwaiq Holding",
    "Chemicals": "Eastern Industrial Group",
    "Transport and Logistics": "Red Sea Holding",
    "Information Technology": "Kingdom Digital Group",
    "Power and Utilities": "Arabian Energy Group",
    "Real Estate": "Al Rawdah Group",
}

#: Nineteen grades, best to worst, then the default state.
RATINGS: tuple[str, ...] = (
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C")
DEFAULT_GRADE = "D"

FACILITY_TYPES = ("Term Loan", "Revolving Credit", "Working Capital",
                  "Trade Finance", "Project Finance")
COLLATERAL_TYPES = ("Real Estate", "Plant and Equipment", "Receivables",
                    "Cash Deposit", "Corporate Guarantee")
COVENANT_TYPES = ("Leverage", "DSCR", "Interest Cover", "Current Ratio",
                  "Minimum EBITDA")
TIERS = ("Strategic", "Core", "Transactional")

#: The authored stories. A sector's stress builds over the window; a
#: negative figure is an improving sector, and the book has both.
SECTOR_STRESS: dict[str, float] = {
    "Construction": 1.00,
    "Real Estate": 0.85,
    "Hospitality": 0.55,
    "Retail Trade": 0.40,
    "Transport and Logistics": 0.20,
    "Manufacturing": 0.15,
    "Wholesale Trade": 0.10,
    "Agriculture and Agri-processing": 0.05,
    "Metals and Mining": 0.00,
    "Healthcare": -0.10,
    "Chemicals": -0.20,
    "Information Technology": -0.30,
    "Power and Utilities": -0.35,
}

#: Collateral values follow their own cycle. Real estate softens through the
#: window while industrial security firms up -- so "coverage fell" and "ECL
#: rose" are separable findings rather than the same finding twice.
COLLATERAL_DRIFT: dict[str, float] = {
    "Real Estate": -0.18, "Plant and Equipment": 0.06,
    "Receivables": -0.04, "Cash Deposit": 0.0,
    "Corporate Guarantee": -0.02,
}


def _stable(text: str, modulus: int) -> int:
    """A repeatable integer from a string.

    NOT `hash()`. Python randomises string hashing per process, so a build on
    Monday and a build on Tuesday produced different group ids and different
    waiver months from the same inputs -- and therefore different parquet
    bytes and a different fingerprint. A fingerprint that changes when
    nothing changed is a fingerprint nobody can check anything against.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulus


def _ramp(index: int, total: int) -> float:
    """0 at the start of the window, 1 at the end, easing in the middle."""
    if total <= 1:
        return 1.0
    x = index / (total - 1)
    return x * x * (3 - 2 * x)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build(release_id: str = "",
          tenant_id: str = lake.DEFAULT_TENANT) -> lake.Build:
    import pandas as pd

    release_id = release_id or dom.DEFAULT_RELEASES[dom.CORPORATE]
    months = month_range()
    rng = random.Random(SEED)

    borrowers: list[dict[str, Any]] = []
    facilities: list[dict[str, Any]] = []
    for index, (name, sector, sub_sector, region) in enumerate(BORROWERS):
        borrower_id = f"CB{index + 1:04d}"
        borrowers.append({
            "borrower_id": borrower_id, "borrower_name": name,
            "group_id": f"CG{_stable(GROUPS.get(sector, name), 9000) + 1000}",
            "group_name": GROUPS.get(sector, f"{name} Holding"),
            "sector": sector, "sub_sector": sub_sector, "region": region,
            "relationship_tier": TIERS[index % len(TIERS)],
            "base_rating": 4 + (index * 3) % 11,
            "base_revenue": round(rng.uniform(900, 7200), 1),
            "base_margin": rng.uniform(0.09, 0.28),
            "base_leverage": rng.uniform(1.4, 4.2),
            "quality": rng.uniform(0.0, 1.0),
        })
        for slot in range(2 + index % 3):
            facilities.append({
                "facility_id": f"CF{index + 1:04d}{slot + 1}",
                "borrower_id": borrower_id,
                "facility_type": FACILITY_TYPES[(index + slot)
                                                % len(FACILITY_TYPES)],
                "base_limit": round(rng.uniform(140, 1450), 1),
                "base_util": rng.uniform(0.42, 0.93),
                "ccf": rng.uniform(0.2, 0.5),
                "lgd": rng.uniform(0.28, 0.55),
                "collateral_type": COLLATERAL_TYPES[(index + slot)
                                                    % len(COLLATERAL_TYPES)],
                "base_collateral": rng.uniform(0.55, 1.35),
                "covenant_type": COVENANT_TYPES[(index + slot * 2)
                                                % len(COVENANT_TYPES)],
                "wobble": rng.uniform(-0.03, 0.03),
            })

    by_id = {b["borrower_id"]: b for b in borrowers}
    gov = {"tenant_id": tenant_id, "dataset_release_id": release_id,
           "domain_id": dom.CORPORATE, "reporting_currency": lake.CURRENCY}

    borrower_rows: list[dict[str, Any]] = []
    facility_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    covenant_rows: list[dict[str, Any]] = []
    previous_rating: dict[str, int] = {}
    stage_since: dict[str, tuple[int, int]] = {}

    for m_index, month in enumerate(months):
        ramp = _ramp(m_index, len(months))
        season = math.sin((m_index % 12) / 12 * 2 * math.pi)

        for borrower in borrowers:
            bid = borrower["borrower_id"]
            stress = SECTOR_STRESS.get(borrower["sector"], 0.0) * ramp
            # A borrower's own quality softens or sharpens its sector's story.
            personal = stress * (0.55 + 0.9 * (1 - borrower["quality"]))

            revenue = borrower["base_revenue"] * (
                1 + 0.035 * season - 0.16 * personal + 0.012 * m_index / 12)
            margin = _clamp(borrower["base_margin"] - 0.05 * personal,
                            0.01, 0.42)
            ebitda = revenue * margin
            debt = borrower["base_revenue"] * borrower["base_leverage"] * 0.38
            debt *= 1 + 0.10 * personal
            cash = max(8.0, ebitda * (0.42 - 0.18 * personal))
            net_debt = max(0.0, debt - cash)
            leverage = net_debt / max(ebitda, 1.0)
            dscr = _clamp(2.35 - 0.95 * personal - 0.05 * leverage, 0.55, 4.2)
            interest_cover = _clamp(5.4 - 2.2 * personal - 0.22 * leverage,
                                    0.7, 12.0)

            notches = int(round(3.1 * personal))
            grade = min(len(RATINGS) - 1, borrower["base_rating"] + notches)
            prior = previous_rating.get(bid, grade)
            previous_rating[bid] = grade
            moved = prior - grade  # negative is a downgrade

            borrower_rows.append({
                **gov,
                "borrower_id": bid, "borrower_name": borrower["borrower_name"],
                "group_id": borrower["group_id"],
                "group_name": borrower["group_name"],
                "reporting_month": month, "sector": borrower["sector"],
                "sub_sector": borrower["sub_sector"],
                "region": borrower["region"],
                "relationship_tier": borrower["relationship_tier"],
                "rating_current": RATINGS[grade],
                "rating_previous": RATINGS[prior],
                "rating_notches_moved": moved,
                "rating_outlook": ("Negative" if personal > 0.35
                                   else "Positive" if personal < -0.12
                                   else "Stable"),
                "pd_ttc_12m": round(_clamp(0.0035 * math.exp(grade / 3.6),
                                           0.0002, 0.65), 6),
                "revenue_sar_mn": round(revenue, 1),
                "ebitda_sar_mn": round(ebitda, 1),
                "total_debt_sar_mn": round(debt, 1),
                "cash_sar_mn": round(cash, 1),
                "net_debt_sar_mn": round(net_debt, 1),
                "leverage_x": round(leverage, 3),
                "dscr_x": round(dscr, 3),
                "interest_cover_x": round(interest_cover, 3),
                "current_ratio_x": round(_clamp(1.65 - 0.5 * personal,
                                                0.55, 3.1), 3),
                "ebitda_margin_pct": round(margin * 100, 3),
                "qualitative_score": round(
                    _clamp(78 - 34 * personal + 4 * season, 12, 97), 2),
            })

        for facility in facilities:
            borrower = by_id[facility["borrower_id"]]
            bid = borrower["borrower_id"]
            stress = SECTOR_STRESS.get(borrower["sector"], 0.0) * ramp
            personal = stress * (0.55 + 0.9 * (1 - borrower["quality"]))

            limit = facility["base_limit"] * (1 + 0.004 * m_index)
            util = _clamp(facility["base_util"] + 0.12 * personal
                          + 0.02 * season + facility["wobble"], 0.05, 1.0)
            drawn = limit * util
            undrawn = max(0.0, limit - drawn)
            ead = drawn + undrawn * facility["ccf"]

            pd_pit = _clamp(0.004 * math.exp(
                (borrower["base_rating"] + 3.1 * personal) / 3.4)
                + 0.004 * personal, 0.0003, 0.85)
            dpd = int(max(0, round((personal - 0.42) * 165))) if personal > 0.42 else 0
            if personal > 0.80:
                stage = 3
            elif personal > 0.34 or dpd >= 30:
                stage = 2
            else:
                stage = 1
            sicr = 1 if stage >= 2 else 0
            default_flag = 1 if stage == 3 else 0
            pd_life = _clamp(pd_pit * (2.4 + 1.6 * personal), pd_pit, 0.97)
            lgd = _clamp(facility["lgd"] + 0.09 * personal, 0.12, 0.85)

            ecl_12m = ead * pd_pit * lgd
            ecl_life = ead * pd_life * lgd
            ecl = ecl_12m if stage == 1 else ecl_life

            seen, since = stage_since.get(facility["facility_id"], (stage, 0))
            since = since + 1 if seen == stage else 1
            stage_since[facility["facility_id"]] = (stage, since)

            facility_rows.append({
                **gov,
                "facility_id": facility["facility_id"], "borrower_id": bid,
                "reporting_month": month,
                "facility_type": facility["facility_type"],
                "sector": borrower["sector"], "region": borrower["region"],
                "limit_sar_mn": round(limit, 2),
                "drawn_sar_mn": round(drawn, 2),
                "undrawn_sar_mn": round(undrawn, 2),
                "utilisation_pct": round(util * 100, 3),
                "ead_sar_mn": round(ead, 2),
                "stage": stage, "sicr_flag": sicr,
                "default_flag": default_flag, "dpd_days": dpd,
                "pd_pit_12m": round(pd_pit, 6),
                "pd_lifetime": round(pd_life, 6),
                "lgd_pct": round(lgd * 100, 3),
                "ecl_12m_sar_mn": round(ecl_12m, 4),
                "ecl_lifetime_sar_mn": round(ecl_life, 4),
                "ecl_sar_mn": round(ecl, 4),
                "past_due_flag": 1 if dpd > 0 else 0,
                "months_in_stage": since,
            })

            drift = COLLATERAL_DRIFT.get(facility["collateral_type"], 0.0)
            market = (ead * facility["base_collateral"]
                      * (1 + drift * ramp + 0.015 * season))
            haircut = {"Real Estate": 0.25, "Plant and Equipment": 0.35,
                       "Receivables": 0.30, "Cash Deposit": 0.0,
                       "Corporate Guarantee": 0.40}[facility["collateral_type"]]
            allocated = market * (1 - haircut)
            collateral_rows.append({
                **gov,
                "collateral_id": f"CC{facility['facility_id'][2:]}",
                "facility_id": facility["facility_id"], "borrower_id": bid,
                "reporting_month": month,
                "collateral_type": facility["collateral_type"],
                "market_value_sar_mn": round(market, 2),
                "haircut_pct": round(haircut * 100, 2),
                "allocated_value_sar_mn": round(allocated, 2),
                "coverage_pct": round(allocated / max(ead, 0.01) * 100, 3),
                "ltv_pct": round(ead / max(market, 0.01) * 100, 3),
                "valuation_age_months": (m_index % 12) + 1,
            })

            kind = facility["covenant_type"]
            observed, threshold = {
                "Leverage": (round(
                    (net_debt := max(0.0, borrower["base_revenue"]
                                     * borrower["base_leverage"] * 0.38
                                     * (1 + 0.10 * personal))) /
                    max(borrower["base_revenue"] * borrower["base_margin"], 1.0),
                    3), 4.00),
                "DSCR": (round(_clamp(2.35 - 0.95 * personal, 0.55, 4.2), 3),
                         1.25),
                "Interest Cover": (round(_clamp(5.4 - 2.2 * personal, 0.7,
                                                12.0), 3), 2.50),
                "Current Ratio": (round(_clamp(1.65 - 0.5 * personal, 0.55,
                                               3.1), 3), 1.10),
                "Minimum EBITDA": (round(borrower["base_revenue"]
                                         * borrower["base_margin"]
                                         * (1 - 0.30 * personal), 2),
                                   round(borrower["base_revenue"]
                                         * borrower["base_margin"] * 0.70, 2)),
            }[kind]
            # Leverage is a ceiling; everything else here is a floor.
            if kind == "Leverage":
                headroom = (threshold - observed) / max(threshold, 0.01) * 100
            else:
                headroom = (observed - threshold) / max(threshold, 0.01) * 100
            breach = 1 if headroom < 0 else 0
            status = "BREACH" if breach else ("WATCH" if headroom < 10
                                              else "PASS")
            waiver = 1 if breach and (m_index + _stable(kind, 97)) % 3 == 0 else 0
            covenant_rows.append({
                **gov,
                "covenant_id": f"CV{facility['facility_id'][2:]}",
                "facility_id": facility["facility_id"], "borrower_id": bid,
                "reporting_month": month, "covenant_type": kind,
                "threshold_value": round(float(threshold), 3),
                "observed_value": round(float(observed), 3),
                "headroom_pct": round(headroom, 3),
                "test_status": status, "breach_flag": breach,
                "waiver_flag": waiver,
                "waiver_month": month if waiver else "",
            })

    frames = {
        "corp_borrower_month": pd.DataFrame(borrower_rows),
        "corp_facility_month": pd.DataFrame(facility_rows),
        "corp_collateral_month": pd.DataFrame(collateral_rows),
        "corp_covenant_month": pd.DataFrame(covenant_rows),
    }
    return lake.Build(
        domain_id=dom.CORPORATE, release_id=release_id, periods=months,
        frames=frames,
        counts={"borrowers": len(borrowers), "facilities": len(facilities),
                "groups": len({b["group_name"] for b in borrowers}),
                "sectors": len({b["sector"] for b in borrowers})},
        notes={"rating_scale": list(RATINGS) + [DEFAULT_GRADE],
               "stressed_sectors": [s for s, v in SECTOR_STRESS.items()
                                    if v > 0.3],
               "improving_sectors": [s for s, v in SECTOR_STRESS.items()
                                     if v < 0]})


__all__ = ["BORROWERS", "RATINGS", "SECTOR_STRESS", "build"]
