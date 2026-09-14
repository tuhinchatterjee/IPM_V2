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

#: The book is not twenty names.
#:
#: It was, and the consequence showed in every answer: thirteen sectors over
#: twenty borrowers meant "EAD by sector" returned thirteen rows of which
#: most held a single obligor, so "sector" and "borrower" were the same
#: dimension wearing two names, and every month-on-month movement was one
#: company's news. A wholesale book a credit officer would recognise has
#: several names in each sector, a spread of sizes, and enough of them that a
#: sector aggregate says something about the sector.
#:
#: The twenty above are the authored anchors and keep their stories. The tail
#: below is composed deterministically from Saudi place and trade words, so
#: it is reproducible byte for byte and no real institution is described.
_TAIL_PREFIXES: tuple[str, ...] = (
    "Al Faisaliah", "Najd", "Hijaz", "Tuwaiq", "Dhahran", "Qassim",
    "Al Khobar", "Unayzah", "Al Jouf", "Wadi Hanifah", "Rabigh", "Al Ahsa",
    "Sudair", "Al Kharj", "Buraydah", "Taif", "Najran", "Jazan",
)

#: sector -> (sub-sectors, trade words, home regions)
_TAIL_SECTORS: dict[str, tuple[tuple[str, ...], tuple[str, ...],
                               tuple[str, ...]]] = {
    "Construction": (("Civil Infrastructure", "Building Contracting",
                      "Roads and Bridges", "Marine Works"),
                     ("Contracting", "Engineering", "Civil Works"),
                     ("Riyadh", "Makkah", "Eastern Province", "Qassim")),
    "Real Estate": (("Commercial Property", "Mixed Use", "Residential",
                     "Industrial Parks"),
                    ("Properties", "Estates", "Development"),
                    ("Riyadh", "Makkah", "Madinah", "Eastern Province")),
    "Hospitality": (("Hotels", "Serviced Apartments", "Catering"),
                    ("Hospitality", "Hotels", "Resorts"),
                    ("Makkah", "Madinah", "Riyadh", "Tabuk")),
    "Retail Trade": (("Department Stores", "Grocery", "Specialty Retail"),
                     ("Retail", "Stores", "Markets"),
                     ("Riyadh", "Hail", "Asir", "Eastern Province")),
    "Transport and Logistics": (("Freight", "Land Transport", "Warehousing",
                                 "Port Services"),
                                ("Logistics", "Transport", "Shipping"),
                                ("Makkah", "Madinah", "Eastern Province",
                                 "Riyadh")),
    "Manufacturing": (("Industrial Products", "Metal Fabrication",
                       "Packaging", "Building Materials"),
                      ("Industries", "Manufacturing", "Works"),
                      ("Qassim", "Eastern Province", "Riyadh", "Asir")),
    "Wholesale Trade": (("General Trading", "Food Distribution",
                         "Equipment Distribution"),
                        ("Trading", "Distribution", "Supplies"),
                        ("Riyadh", "Eastern Province", "Makkah")),
    "Agriculture and Agri-processing": (("Food Processing", "Dairy",
                                         "Poultry", "Grain Handling"),
                                        ("Agri", "Farms", "Foods"),
                                        ("Asir", "Qassim", "Hail",
                                         "Northern Borders")),
    "Metals and Mining": (("Mining", "Smelting", "Aggregates"),
                          ("Minerals", "Metals", "Mining"),
                          ("Northern Borders", "Eastern Province", "Hail")),
    "Healthcare": (("Hospitals", "Clinics", "Pharmaceuticals"),
                   ("Medical", "Healthcare", "Care"),
                   ("Riyadh", "Makkah", "Eastern Province")),
    "Chemicals": (("Petrochemicals", "Specialty Chemicals", "Fertilisers"),
                  ("Chemicals", "Petrochemicals", "Industries"),
                  ("Eastern Province", "Madinah", "Riyadh")),
    "Information Technology": (("IT Services", "Software", "Data Centres"),
                               ("Technologies", "Digital", "Systems"),
                               ("Riyadh", "Eastern Province", "Makkah")),
    "Power and Utilities": (("Generation", "Renewables", "Water"),
                            ("Energy", "Power", "Utilities"),
                            ("Madinah", "Tabuk", "Eastern Province",
                             "Najran")),
}

#: Extra names per sector. Weighted so the sectors with an authored story
#: carry enough obligors for that story to be a SECTOR finding rather than
#: one company's news.
_TAIL_COUNTS: dict[str, int] = {
    "Construction": 9, "Real Estate": 8, "Hospitality": 6,
    "Retail Trade": 6, "Transport and Logistics": 6, "Manufacturing": 7,
    "Wholesale Trade": 5, "Agriculture and Agri-processing": 5,
    "Metals and Mining": 4, "Healthcare": 5, "Chemicals": 6,
    "Information Technology": 5, "Power and Utilities": 5,
}


def _tail() -> tuple[tuple[str, str, str, str], ...]:
    """The generated part of the book. A pure function of the tables above."""
    taken = {name for name, *_ in BORROWERS}
    out: list[tuple[str, str, str, str]] = []
    for sector in sorted(_TAIL_COUNTS):
        subs, words, regions = _TAIL_SECTORS[sector]
        for index in range(_TAIL_COUNTS[sector]):
            seed = _stable(f"{sector}|{index}", 10_000)
            prefix = _TAIL_PREFIXES[(seed + index) % len(_TAIL_PREFIXES)]
            word = words[(seed // 7 + index) % len(words)]
            name = f"{prefix} {word}"
            bump = 0
            while name in taken:
                bump += 1
                prefix = _TAIL_PREFIXES[(seed + index + bump)
                                        % len(_TAIL_PREFIXES)]
                name = f"{prefix} {word}"
                if bump > len(_TAIL_PREFIXES):
                    name = f"{prefix} {word} {bump}"
            taken.add(name)
            out.append((name, sector, subs[(seed // 3 + index) % len(subs)],
                        regions[(seed // 11 + index) % len(regions)]))
    return tuple(out)


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

#: The through-the-cycle PD of each grade, as a master scale.
#:
#: Calibrated rather than convenient. The first version of this generator
#: priced the whole book off `0.004 * exp(grade / 3.4)`, which put the
#: AVERAGE Stage 1 twelve-month PD at nine and a half per cent -- a CCC
#: number applied to a performing investment-grade book, and a Stage 1
#: coverage ratio of four and a half per cent that no credit reader would
#: accept. The curve below is the shape a rating master scale actually has:
#: roughly a doubling every grade and a half, from one basis point at AAA to
#: the high teens at C.
PD_ANCHOR = 0.00012
PD_DECAY = 2.55

#: How hard the sector stories push. Tuned against the book they produce:
#: at 1.0 the three stressed sectors finished with every single obligor on
#: the watch list and forty-five per cent of the book in Stage 2, which is a
#: portfolio in resolution rather than one under pressure, and a book where
#: "which names deteriorated?" has no answer because all of them did.
STRESS_SCALE = 0.62

#: The grade at which the book treats an exposure as weak enough to watch as
#: a backstop, and the grade at which it is credit-impaired. The primary
#: trigger is RELATIVE -- a downgrade since origination -- because that is
#: what a significant increase in credit risk means.
WATCH_GRADE = RATINGS.index("CCC")
IMPAIRED_GRADE = RATINGS.index("CC")

#: Notches of downgrade since origination that trigger a significant
#: increase in credit risk on their own. Two is the common policy.
SICR_NOTCHES = 2

#: How the book was written: the grade distribution at origination.
#:
#: It used to be `4 + (index * 3) % 11`, which spans A+ to B and nothing
#: else. A wholesale book with no name weaker than B has no watch list on
#: day one, and the generated book duly reported exactly zero Stage 2
#: exposure for the first fifteen months of the window and no impaired
#: exposure at all. A real book is written across the scale, with most of it
#: around BBB/BB and a short tail either side.
ORIGINATION_GRADES: tuple[int, ...] = tuple(range(2, 18))
ORIGINATION_WEIGHTS: tuple[int, ...] = (
    1, 2, 3, 5, 8, 11, 13, 13, 12, 10, 8, 6, 4, 3, 2, 1)

#: Debt service coverage below which a borrower starts missing payments, and
#: above which arrears cure. Between the two the arrears freeze: a borrower
#: that has stopped deteriorating has not yet repaid.
ARREARS_DSCR = 1.00
CURE_DSCR = 1.20


def grade_pd(grade: int) -> float:
    """Twelve-month PD for a rating grade, from the master scale."""
    return _clamp(PD_ANCHOR * math.exp(grade / PD_DECAY), 0.0001, 0.40)

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


def _jitter(key: str, month: str, spread: float) -> float:
    """A per-(entity, month) wobble that is stable across builds.

    Hashed rather than drawn, so it is a pure function of who and when: two
    builds fingerprint identically and adding a borrower does not reshuffle
    everyone else's history.
    """
    digest = hashlib.sha256(f"corp|{key}|{month}".encode("utf-8")).digest()
    unit = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return (unit - 0.5) * 2 * spread


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

    release_id = release_id or dom.DEFAULT_RELEASES[dom.CORPORATE]
    months = month_range()
    rng = random.Random(SEED)

    borrowers: list[dict[str, Any]] = []
    facilities: list[dict[str, Any]] = []
    book = BORROWERS + _tail()
    for index, (name, sector, sub_sector, region) in enumerate(book):
        borrower_id = f"CB{index + 1:04d}"
        borrowers.append({
            "borrower_id": borrower_id, "borrower_name": name,
            "group_id": f"CG{_stable(GROUPS.get(sector, name), 9000) + 1000}",
            "group_name": GROUPS.get(sector, f"{name} Holding"),
            "sector": sector, "sub_sector": sub_sector, "region": region,
            "relationship_tier": TIERS[index % len(TIERS)],
            "base_rating": rng.choices(ORIGINATION_GRADES,
                                       weights=ORIGINATION_WEIGHTS, k=1)[0],
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
    #: Days past due carried forward per facility, driven by the borrower's
    #: own debt service coverage rather than by a threshold on a stress
    #: index. "Why is this facility in arrears?" is then a question the book
    #: can answer from a column it publishes.
    arrears: dict[str, int] = {}

    for m_index, month in enumerate(months):
        ramp = _ramp(m_index, len(months))
        season = math.sin((m_index % 12) / 12 * 2 * math.pi)
        #: What the borrower loop worked out, for the facility loop to read.
        #: It used to recompute `stress` and `personal` itself, which meant
        #: the facility's risk and the borrower's financials could drift
        #: apart silently the moment either formula changed.
        state: dict[str, dict[str, Any]] = {}

        for borrower in borrowers:
            bid = borrower["borrower_id"]
            stress = (SECTOR_STRESS.get(borrower["sector"], 0.0) * ramp
                      * STRESS_SCALE)
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

            # Unevenly, and stickily.
            #
            # Unevenly because a sector whose obligors all downgrade together
            # is a sector where "which names moved?" has no answer: every
            # borrower carries a permanent idiosyncratic offset, so the weak
            # names go first, some hold on, and a healthy sector still has a
            # name or two on the watch list.
            #
            # Stickily because a rating is a decision, not a reading. Letting
            # it follow a monthly wobble put names into Stage 2 and out again
            # month after month, which is not a credit cycle and would make
            # every "what changed?" answer noise. A downgrade lands at once;
            # a recovery takes a notch a month.
            idiosyncratic = _jitter(bid, "origination", 1.7)
            notches = max(0, int(round(4.2 * personal + idiosyncratic
                                       + _jitter(bid, month, 0.3))))
            target = min(len(RATINGS) - 1,
                         borrower["base_rating"] + notches)
            prior = previous_rating.get(bid, target)
            grade = max(target, prior - 1)
            previous_rating[bid] = grade
            moved = prior - grade  # negative is a downgrade

            state[bid] = {
                "personal": personal, "grade": grade, "dscr": dscr,
                "notches_from_origination": grade - borrower["base_rating"],
            }

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
                "pd_ttc_12m": round(grade_pd(grade), 6),
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
            here = state[bid]
            personal = here["personal"]
            grade = here["grade"]

            limit = facility["base_limit"] * (1 + 0.004 * m_index)
            util = _clamp(facility["base_util"] + 0.12 * personal
                          + 0.02 * season + facility["wobble"], 0.05, 1.0)
            drawn = limit * util
            undrawn = max(0.0, limit - drawn)
            ead = drawn + undrawn * facility["ccf"]

            # Arrears follow debt service, not a threshold on a stress
            # index. A borrower that cannot cover its debt service starts
            # missing payments and rolls thirty days deeper each month; one
            # that recovers cures; one in between is frozen where it is.
            prior_dpd = arrears.get(facility["facility_id"], 0)
            dscr = here["dscr"]
            if dscr < ARREARS_DSCR:
                dpd = min(360, prior_dpd + 30 if prior_dpd else 12)
            elif dscr < CURE_DSCR and prior_dpd:
                dpd = prior_dpd
            else:
                dpd = 0
            arrears[facility["facility_id"]] = dpd

            # Staging from what the book OBSERVES: arrears, the grade
            # itself, and the downgrade since origination. Reading it off
            # the stress index instead left the first nine months of the
            # window with exactly zero Stage 2 exposure -- a book with a
            # switch in it rather than a credit cycle.
            if dpd >= 90 or grade >= IMPAIRED_GRADE:
                stage = 3
            elif (dpd >= 30 or grade >= WATCH_GRADE
                  or here["notches_from_origination"] >= SICR_NOTCHES):
                stage = 2
            else:
                stage = 1
            sicr = 1 if stage >= 2 else 0
            default_flag = 1 if stage == 3 else 0

            lgd = _clamp(facility["lgd"] + 0.09 * personal, 0.12, 0.85)
            if stage == 3:
                # A defaulted exposure has already defaulted. Publishing a
                # point-in-time PD of eight per cent against it, as this
                # book once did, is not a calibration choice -- it is a
                # contradiction of the flag in the next column.
                pd_pit = pd_life = 1.0
                ecl_12m = ecl_life = ead * lgd
            else:
                pd_pit = _clamp(grade_pd(grade) * (1 + 0.35 * personal),
                                0.0001, 0.45)
                pd_life = _clamp(pd_pit * (2.4 + 1.6 * personal), pd_pit,
                                 0.97)
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


__all__ = ["BORROWERS", "RATINGS", "SECTOR_STRESS", "build",
           "grade_pd", "obligors"]


def obligors() -> tuple[tuple[str, str, str, str], ...]:
    """Every name in the book: the authored anchors and the generated tail."""
    return BORROWERS + _tail()
