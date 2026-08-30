"""The synthetic corporate universe. B1.

Sixteen quarters, Q3 2022 to Q2 2026, of a corporate book large enough to
demonstrate the whole of Borrower 360 and the relationship graph honestly:
3,800 distinct borrowers, never fewer than 3,000 active in any quarter,
with entries, exits and stable identifiers across the whole window.

Simulated, not sampled
----------------------
Random rows would give the graph nothing to find and hand-tuned rows would
give it exactly what somebody decided it should find. So every borrower
carries a latent credit quality that follows a persistent process driven by a
common macroeconomic factor and its sector's sensitivity to it, and every
observable - the rating, the leverage, the days past due, the covenant
headroom, the IFRS 9 stage - is a reading of that same latent state through a
different, noisy instrument.

Two consequences matter for what the rest of Part B claims:

* deterioration is genuinely *predictable* a quarter ahead, so an early
  warning is a finding rather than a coincidence; and
* a borrower's neighbours in the ownership graph share its parent's shocks,
  so a contagion measure computed over the graph is measuring something that
  was actually put there.

Determinism
-----------
One seed, no wall clock, no external call. The same universe on every
machine, so a figure quoted in a document is the figure a reader sees.

Origin
------
Every frame carries ``origin = SYNTHETIC_DEMO``. It describes no real
company, no real ownership structure and no real bank's book.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import NOT_CLIENT_DATA, ORIGIN

logger = logging.getLogger(__name__)

UNIVERSE_VERSION = "1.0.0"

#: One seed for the whole universe. Changing it changes every figure in every
#: document that quotes this data, which is why it is a constant and not an
#: argument with a default.
SEED = 20260830

# --------------------------------------------------------------- the window

FIRST_YEAR, FIRST_QUARTER = 2022, 3
QUARTER_COUNT = 16


def quarters(count: int = QUARTER_COUNT) -> list[str]:
    """`["Q3 2022", ... ]` - the same label format the rest of the book uses."""
    out: list[str] = []
    year, quarter = FIRST_YEAR, FIRST_QUARTER
    for _ in range(count):
        out.append(f"Q{quarter} {year}")
        quarter += 1
        if quarter == 5:
            quarter, year = 1, year + 1
    return out


QUARTERS: list[str] = quarters()


def quarter_end(period: str) -> str:
    """The last calendar day of a quarter label, as an ISO date."""
    quarter = int(period[1])
    year = int(period.split()[1])
    month, day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[quarter]
    return f"{year:04d}-{month:02d}-{day:02d}"


# --------------------------------------------------------------- population

#: 3,800 sits inside B1's 3,500-4,000 target and leaves room for ~300 exits
#: without any quarter falling below the 3,000 floor.
ENTITY_COUNT = 3_800
#: Present from the first quarter. The rest arrive over the window.
INITIAL_ACTIVE = 3_300


@dataclass(frozen=True)
class Sector:
    """A sector and how hard the cycle hits it.

    `beta` is sensitivity to the common factor, `vol` how much of a quarter's
    movement is the borrower's own rather than the cycle's, and `quality` the
    baseline the sector starts from. Contracting has a high beta AND high
    idiosyncratic volatility; Utilities has neither. That difference is the
    entire reason a sector breakdown is worth looking at.
    """

    name: str
    weight: float
    beta: float
    vol: float
    quality: float
    #: Typical revenue, in millions, for a borrower in this sector. Sets the
    #: scale of the financials and, through them, of the exposure.
    revenue_scale: float
    #: Typical EBITDA margin.
    margin: float


SECTORS: tuple[Sector, ...] = (
    Sector("Contracting", 0.12, 1.55, 0.62, -0.55, 420.0, 0.09),
    Sector("Real Estate", 0.10, 1.30, 0.50, -0.25, 380.0, 0.28),
    Sector("Petrochemicals", 0.08, 1.15, 0.38, 0.35, 1450.0, 0.22),
    Sector("Wholesale & Retail Trade", 0.10, 0.95, 0.44, -0.10, 520.0, 0.07),
    Sector("Manufacturing", 0.09, 1.00, 0.40, 0.05, 610.0, 0.14),
    Sector("Transport & Logistics", 0.07, 0.90, 0.38, 0.00, 340.0, 0.16),
    Sector("Hospitality & Tourism", 0.05, 1.35, 0.55, -0.35, 210.0, 0.19),
    Sector("Healthcare", 0.06, 0.45, 0.28, 0.40, 290.0, 0.21),
    Sector("Education", 0.04, 0.40, 0.26, 0.35, 160.0, 0.18),
    Sector("Utilities", 0.05, 0.30, 0.20, 0.75, 980.0, 0.31),
    Sector("Telecommunications", 0.04, 0.50, 0.24, 0.60, 1150.0, 0.34),
    Sector("Mining & Metals", 0.05, 1.20, 0.48, 0.05, 720.0, 0.24),
    Sector("Agriculture & Food", 0.05, 0.70, 0.36, 0.10, 300.0, 0.12),
    Sector("Financial Services", 0.05, 0.85, 0.34, 0.45, 640.0, 0.29),
    Sector("Government-Related Entities", 0.05, 0.25, 0.16, 1.05, 1900.0, 0.26),
)

#: A sub-sector per sector, so a cohort can be cut finer than the fifteen.
SUB_SECTORS: dict[str, tuple[str, ...]] = {
    "Contracting": ("Civil Works", "MEP Contracting", "Infrastructure",
                    "Fit-Out & Interiors"),
    "Real Estate": ("Commercial Leasing", "Residential Development",
                    "Retail Malls", "Industrial Parks"),
    "Petrochemicals": ("Basic Chemicals", "Polymers", "Fertilisers",
                       "Speciality Chemicals"),
    "Wholesale & Retail Trade": ("Food Distribution", "Consumer Electronics",
                                 "Building Materials", "Apparel"),
    "Manufacturing": ("Metal Fabrication", "Packaging", "Cement & Concrete",
                      "Automotive Components"),
    "Transport & Logistics": ("Freight Forwarding", "Shipping & Ports",
                              "Warehousing", "Land Transport"),
    "Hospitality & Tourism": ("Hotels", "Catering & Events",
                              "Travel Services", "Leisure & Entertainment"),
    "Healthcare": ("Hospitals", "Polyclinics", "Pharmaceutical Distribution",
                   "Medical Devices"),
    "Education": ("Private Schools", "Higher Education",
                  "Vocational Training", "Education Services"),
    "Utilities": ("Power Generation", "Water & Desalination",
                  "Waste Management", "District Cooling"),
    "Telecommunications": ("Mobile Operators", "Fixed & Fibre",
                           "Data Centres", "Managed IT Services"),
    "Mining & Metals": ("Aluminium", "Steel", "Industrial Minerals",
                        "Mining Services"),
    "Agriculture & Food": ("Poultry & Livestock", "Dairy",
                           "Grain & Milling", "Food Processing"),
    "Financial Services": ("Leasing Companies", "Insurance",
                           "Investment Firms", "Exchange Houses"),
    "Government-Related Entities": ("Sovereign-Linked Holding",
                                    "Municipal Services", "State Utility",
                                    "Development Fund"),
}

REGIONS: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("Riyadh", 0.30, ("Riyadh", "Al Kharj", "Diriyah")),
    ("Makkah", 0.17, ("Jeddah", "Makkah", "Taif")),
    ("Eastern Province", 0.19, ("Dammam", "Al Khobar", "Jubail", "Dhahran")),
    ("Madinah", 0.07, ("Madinah", "Yanbu")),
    ("Asir", 0.05, ("Abha", "Khamis Mushait")),
    ("Qassim", 0.05, ("Buraydah", "Unaizah")),
    ("Tabuk", 0.03, ("Tabuk", "Duba")),
    ("Ha'il", 0.03, ("Ha'il",)),
    ("Jazan", 0.03, ("Jazan",)),
    ("Najran", 0.02, ("Najran",)),
    ("Al Jouf", 0.02, ("Sakaka",)),
    ("Northern Borders", 0.02, ("Arar",)),
    ("Al Bahah", 0.02, ("Al Bahah",)),
)

SEGMENTS: tuple[tuple[str, float], ...] = (
    ("Large Corporate", 0.22), ("Mid Corporate", 0.34),
    ("Commercial", 0.30), ("Public Sector", 0.06), ("Financial Institution", 0.08),
)

SUB_SEGMENTS: dict[str, tuple[str, ...]] = {
    "Large Corporate": ("Top Tier", "Multinational Subsidiary", "Family Conglomerate"),
    "Mid Corporate": ("Established", "Growth", "Emerging"),
    "Commercial": ("Upper Commercial", "Core Commercial"),
    "Public Sector": ("Government Entity", "Government-Related Corporate"),
    "Financial Institution": ("Bank", "Non-Bank Financial"),
}

LEGAL_FORMS: tuple[tuple[str, float], ...] = (
    ("Limited Liability Company", 0.52), ("Joint Stock Company (Closed)", 0.22),
    ("Joint Stock Company (Listed)", 0.09), ("Establishment", 0.10),
    ("Branch of Foreign Company", 0.04), ("Government Entity", 0.03),
)

BUSINESS_UNITS: tuple[str, ...] = (
    "Corporate Banking - Central", "Corporate Banking - West",
    "Corporate Banking - East", "Commercial Banking",
    "Public Sector & Institutions", "Financial Institutions Group",
)

#: Name parts. Deliberately generic so no combination reads as a real company.
NAME_FIRST: tuple[str, ...] = (
    "Al Rajhi", "Al Faisal", "Al Nahda", "Al Maha", "Al Waha", "Al Rabia",
    "Arabian", "Gulf", "Peninsula", "Najd", "Hijaz", "Tihama", "Sahara",
    "Rawabi", "Marafiq", "Tamimi", "Bawadi", "Nakheel", "Qasr", "Shorouk",
    "Andalus", "Firdaus", "Yamama", "Salman", "Zahra", "Noor", "Safwa",
    "Riyada", "Mabani", "Takamul", "Ithmar", "Wafra", "Masar", "Tadawi",
)
NAME_SECOND: tuple[str, ...] = (
    "Holding", "Industrial", "Trading", "Development", "Investment",
    "Contracting", "Group", "Enterprises", "Services", "Logistics",
    "Manufacturing", "Projects", "Resources", "Ventures", "Partners",
)
#: A transliterated Arabic name, synthetic like everything else. Present so
#: B6's Arabic search and B7's name matching have something real to work on.
ARABIC_FIRST: tuple[str, ...] = (
    "الراجحي", "الفيصل", "النهضة", "المها", "الواحة", "الربيع", "العربية",
    "الخليج", "شبه الجزيرة", "نجد", "الحجاز", "تهامة", "الصحراء", "روابي",
    "مرافق", "التميمي", "بوادي", "النخيل", "قصر", "الشروق", "الأندلس",
    "الفردوس", "اليمامة", "سلمان", "الزهراء", "نور", "الصفوة", "ريادة",
    "مباني", "تكامل", "إثمار", "وفرة", "مسار", "تداوي",
)
ARABIC_SECOND: tuple[str, ...] = (
    "القابضة", "الصناعية", "للتجارة", "للتطوير", "للاستثمار", "للمقاولات",
    "المجموعة", "للمشاريع", "للخدمات", "للخدمات اللوجستية", "للتصنيع",
    "للمشروعات", "للموارد", "للمشاريع الاستثمارية", "شركاء",
)

RELATIONSHIP_MANAGERS: tuple[str, ...] = (
    "H. Al Otaibi", "N. Al Dossari", "S. Al Harbi", "M. Al Qahtani",
    "F. Al Zahrani", "A. Al Ghamdi", "R. Al Shehri", "K. Al Mutairi",
    "L. Al Anzi", "T. Al Subaie", "Y. Al Balawi", "D. Al Juhani",
)

# ------------------------------------------------------------ rating scale

#: A fourteen-point master scale. Numeric 1 (strongest) to 14, so
#: "rating_change_notches" is a plain subtraction and a downgrade is positive.
#:
#: Thirteen PERFORMING grades and D. D is assigned on the default event, never
#: by a PD band: a name can carry a 40% twelve-month PD and still be paying,
#: and a scale that grades it "D" makes the default rate unmeasurable because
#: the grade and the outcome stop being separate facts.
RATING_SCALE: tuple[str, ...] = (
    "AAA", "AA", "A", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
    "B+", "B", "CCC", "CC", "D",
)
#: Index of the default grade in RATING_SCALE.
DEFAULT_INDEX = len(RATING_SCALE) - 1
#: Upper PD bound, in percent, for each performing grade except the weakest.
RATING_BOUNDS: tuple[float, ...] = (
    0.04, 0.09, 0.18, 0.32, 0.55, 0.95, 1.60, 2.70, 4.50,
    7.50, 13.00, 26.00,
)
RATING_MODELS: tuple[str, ...] = (
    "Corporate Rating Model v4", "Financial Institutions Model v2",
    "Public Sector Model v1",
)
RATING_OUTLOOKS: tuple[str, ...] = ("Positive", "Stable", "Negative")

DEFAULT_GRADE = "D"
#: Quarterly hazard of default, as a share of the twelve-month PD. A twelve-
#: month probability spread over four quarters, with the shortfall left in
#: rather than solved out - a borrower that survives a quarter enters the next
#: one with its PD re-read from a quality that has itself moved.
QUARTERLY_HAZARD = 0.25
#: Quarters a defaulted borrower stays defaulted before it can cure.
DEFAULT_SEASONING = 3


#: Calibration of the quality-to-PD curve. Chosen so the median borrower is
#: BBB-/BB+ at the top of the cycle and BB-/B+ at the trough, and so the share
#: of the book below CCC moves from under 1% to a little over 4% across the
#: downturn. Those are the two properties every figure downstream inherits.
PD_OFFSET = 5.10


def pd_from_quality(z: np.ndarray) -> np.ndarray:
    """Twelve-month PD in percent from latent quality.

    Logistic: strong names cluster within a few basis points, weak ones climb
    steeply. Floored above zero because no rating system publishes a PD of
    exactly zero, and capped below 100 for the same reason.
    """
    return np.clip(100.0 / (1.0 + np.exp(2.10 * z + PD_OFFSET)), 0.02, 99.0)


def grade_from_pd(pd_pct: np.ndarray) -> np.ndarray:
    """Index into RATING_SCALE from the twelve-month PD, on fixed bands.

    Returns a PERFORMING grade only. D is never reached from a PD; it is set
    by the default event.
    """
    index = np.zeros_like(pd_pct, dtype=int)
    for edge in RATING_BOUNDS:
        index = index + (pd_pct > edge).astype(int)
    return np.clip(index, 0, DEFAULT_INDEX - 1)


# ------------------------------------------------------------------ helpers


def _choose(rng: np.random.Generator,
            options: tuple[tuple[str, float], ...] | list[tuple[str, float]],
            size: int) -> np.ndarray:
    labels = [o[0] for o in options]
    weights = np.array([o[1] for o in options], dtype=float)
    return rng.choice(labels, size=size, p=weights / weights.sum())


def _round(values: np.ndarray, places: int = 2) -> np.ndarray:
    return np.round(np.asarray(values, dtype=float), places)


@dataclass
class Universe:
    """Every frame the corporate universe produces, and what it is.

    Held together rather than written straight to disk so the whole thing can
    be built in a test, asserted on, and thrown away.
    """

    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    quarters: list[str] = field(default_factory=list)
    seed: int = SEED

    def __getitem__(self, name: str) -> pd.DataFrame:
        try:
            return self.frames[name]
        except KeyError:
            raise KeyError(
                f"'{name}' is not a corporate dataset. Built: "
                f"{', '.join(sorted(self.frames))}") from None

    def counts(self) -> dict[str, int]:
        return {name: len(frame) for name, frame in sorted(self.frames.items())}

    def to_dict(self) -> dict[str, Any]:
        master = self.frames.get("corporate_customer_master")
        per_quarter: dict[str, int] = {}
        if master is not None:
            per_quarter = {
                str(period): int(n) for period, n
                in master.groupby("period")["borrower_id"].nunique().items()}
        return {
            "universe_version": UNIVERSE_VERSION,
            "seed": self.seed,
            "origin": ORIGIN,
            "not_client_data": NOT_CLIENT_DATA,
            "quarters": list(self.quarters),
            "quarter_count": len(self.quarters),
            "distinct_borrowers": (
                int(master["borrower_id"].nunique()) if master is not None
                else 0),
            "active_per_quarter": per_quarter,
            "smallest_quarter": min(per_quarter.values()) if per_quarter else 0,
            "row_counts": self.counts(),
        }


# ------------------------------------------------------------- the entities


def build_entities(rng: np.random.Generator) -> pd.DataFrame:
    """The 3,800 borrowers, their fixed attributes, and when they are on book.

    Fixed attributes only. Anything that moves - the rating, the exposure, the
    stage - belongs to a quarter and is generated per quarter, because a
    borrower whose sector changes between quarters is a data-quality finding
    rather than a feature of the universe.
    """
    n = ENTITY_COUNT
    borrower_id = np.array([f"CORP-{100000 + i}" for i in range(n)])

    sector = _choose(rng, tuple((s.name, s.weight) for s in SECTORS), n)
    sub_sector = np.array([
        rng.choice(SUB_SECTORS[s]) for s in sector])

    region_names = tuple((r[0], r[1]) for r in REGIONS)
    region = _choose(rng, region_names, n)
    cities = {r[0]: r[2] for r in REGIONS}
    city = np.array([rng.choice(cities[r]) for r in region])

    segment = _choose(rng, SEGMENTS, n)
    sub_segment = np.array([rng.choice(SUB_SEGMENTS[s]) for s in segment])

    first = rng.integers(0, len(NAME_FIRST), n)
    second = rng.integers(0, len(NAME_SECOND), n)
    # A numeric suffix on collisions, so two borrowers never share a legal
    # name by accident - entity resolution has to be exercised by deliberate
    # near-duplicates (below), not by generator collisions.
    legal_name = np.array([
        f"{NAME_FIRST[a]} {NAME_SECOND[b]} Company" for a, b in zip(first, second, strict=True)])
    seen: dict[str, int] = {}
    unique: list[str] = []
    for name in legal_name:
        count = seen.get(name, 0)
        seen[name] = count + 1
        unique.append(name if count == 0 else f"{name} {count + 1}")
    legal_name = np.array(unique)
    display_name = np.array([
        n.replace(" Company", "").replace(" 2", "").replace(" 3", "")
        for n in legal_name])
    alias = np.array([
        f"{NAME_FIRST[a]} {NAME_SECOND[b][:4].upper()}"
        for a, b in zip(first, second, strict=True)])
    arabic_name = np.array([
        f"شركة {ARABIC_FIRST[a]} {ARABIC_SECOND[b]}"
        for a, b in zip(first, second, strict=True)])

    legal_form = _choose(rng, LEGAL_FORMS, n)
    incorporation_year = rng.integers(1978, 2021, n)
    incorporation_date = np.array([
        f"{y}-{m:02d}-{d:02d}" for y, m, d in zip(
            incorporation_year, rng.integers(1, 13, n), rng.integers(1, 28, n),
            strict=True)])
    relationship_year = np.maximum(incorporation_year + rng.integers(0, 12, n),
                                   2005)
    relationship_start = np.array([
        f"{min(int(y), 2022)}-{m:02d}-{d:02d}" for y, m, d in zip(
            relationship_year, rng.integers(1, 13, n), rng.integers(1, 28, n),
            strict=True)])

    #: Commercial-registration number. The strongest evidence entity
    #: resolution has (B7 precedence 1), so it is generated once per entity
    #: and never regenerated.
    cr_number = np.array([f"CR-{7000000 + int(i) * 7:07d}" for i in range(n)])

    relationship_manager = rng.choice(RELATIONSHIP_MANAGERS, n)
    business_unit = np.array([
        "Financial Institutions Group" if s == "Financial Institution"
        else "Public Sector & Institutions" if s == "Public Sector"
        else {"Riyadh": "Corporate Banking - Central",
              "Makkah": "Corporate Banking - West",
              "Madinah": "Corporate Banking - West",
              "Eastern Province": "Corporate Banking - East"}.get(
                  r, "Commercial Banking")
        for s, r in zip(segment, region, strict=True)])

    # ---- when each borrower is on book -----------------------------------
    #
    # INITIAL_ACTIVE are there from the first quarter; the rest arrive spread
    # over the window, so the book grows the way a book does. Exits are drawn
    # later, against latent quality, because a borrower that leaves should
    # mostly be one that was deteriorating or was refinanced away - not a
    # uniformly random name.
    entry_index = np.zeros(n, dtype=int)
    arriving = ENTITY_COUNT - INITIAL_ACTIVE
    entry_index[INITIAL_ACTIVE:] = np.sort(
        rng.integers(1, QUARTER_COUNT, arriving))

    quality = np.array([
        {s.name: s.quality for s in SECTORS}[s] for s in sector])
    beta = np.array([{s.name: s.beta for s in SECTORS}[s] for s in sector])
    vol = np.array([{s.name: s.vol for s in SECTORS}[s] for s in sector])
    revenue_scale = np.array([
        {s.name: s.revenue_scale for s in SECTORS}[s] for s in sector])
    margin = np.array([{s.name: s.margin for s in SECTORS}[s] for s in sector])

    #: Segment shifts the scale of the balance sheet, not its quality.
    size_factor = np.array([
        {"Large Corporate": 3.2, "Mid Corporate": 1.0, "Commercial": 0.35,
         "Public Sector": 2.4, "Financial Institution": 1.8}[s]
        for s in segment]) * np.exp(rng.normal(0.0, 0.45, n))

    return pd.DataFrame({
        "borrower_id": borrower_id,
        "cr_number": cr_number,
        "legal_name": legal_name,
        "display_name": display_name,
        "alias": alias,
        "arabic_name": arabic_name,
        "sector": sector,
        "sub_sector": sub_sector,
        "region": region,
        "city": city,
        "country": "Saudi Arabia",
        "segment": segment,
        "sub_segment": sub_segment,
        "legal_form": legal_form,
        "incorporation_date": incorporation_date,
        "relationship_start_date": relationship_start,
        "relationship_manager": relationship_manager,
        "business_unit": business_unit,
        "entry_index": entry_index,
        "sector_quality": quality,
        "sector_beta": beta,
        "sector_vol": vol,
        "revenue_scale": revenue_scale * size_factor,
        "sector_margin": margin,
        "size_factor": size_factor,
    })


def macro_factor(rng: np.random.Generator,
                 periods: list[str]) -> pd.DataFrame:
    """The common factor every borrower's quality is driven by.

    A cycle that turns: mildly positive through 2023, weakening across 2024,
    a trough in 2025 and a partial recovery. Written down as a path rather
    than drawn freely so the story a demonstration tells about "the 2025
    downturn" is the same story every time.
    """
    # Peak-to-trough of about 0.65 of a quality unit. Deeper than this and the
    # IFRS 9 relative SICR test - which compares a borrower's PD against its
    # ORIGINATION PD, not against last quarter's - puts a third of the book
    # into Stage 2 at the trough. That is arithmetically what the standard
    # says should happen in a recession of that size, so the honest fix is a
    # recession of a plausible size rather than a SICR threshold widened until
    # the stage mix looks comfortable.
    path = np.array([
        0.22, 0.18, 0.13, 0.07, 0.01, -0.03,
        -0.12, -0.19, -0.27, -0.35, -0.40, -0.37,
        -0.26, -0.14, -0.03, 0.07,
    ])[:len(periods)]
    noise = rng.normal(0.0, 0.05, len(path))
    factor = path + noise
    oil = 84.0 + 18.0 * factor + rng.normal(0.0, 2.0, len(path))
    gdp = 2.4 + 2.6 * factor + rng.normal(0.0, 0.25, len(path))
    rate = 5.6 - 1.1 * factor + rng.normal(0.0, 0.12, len(path))
    return pd.DataFrame({
        "period": periods,
        "period_end_date": [quarter_end(p) for p in periods],
        "credit_cycle_factor": _round(factor, 4),
        "oil_price_usd": _round(oil, 2),
        "real_gdp_growth_pct": _round(gdp, 2),
        "policy_rate_pct": _round(rate, 2),
        "origin": ORIGIN,
    })


#: How much of last quarter's quality carries into this one.
PERSISTENCE = 0.86
#: Damping on the sector volatilities. The sector table's `vol` figures set the
#: RELATIVE volatility of one sector against another, which is what a sector
#: breakdown is read for; this sets the absolute spread of the book, which is
#: what the rating distribution is read for. Keeping them as two numbers means
#: the second can be calibrated without flattening the first.
VOL_SCALE = 0.85


def simulate_quality(entities: pd.DataFrame, factor: np.ndarray,
                     rng: np.random.Generator) -> np.ndarray:
    """Latent credit quality, entity by quarter. Higher is stronger.

    An AR(1) around a sector baseline, shocked by the common factor through
    the sector's beta and by the borrower's own volatility. The starting draw
    is the stationary distribution, so the first quarter is not systematically
    different from the rest.
    """
    n, t = len(entities), len(factor)
    quality = entities["sector_quality"].to_numpy()
    beta = entities["sector_beta"].to_numpy()
    vol = entities["sector_vol"].to_numpy() * VOL_SCALE

    # The cycle is a LEVEL, not an innovation. Adding `beta * factor` to the
    # recursion the obvious way compounds it: with persistence 0.86 a factor
    # held at -0.5 moves quality by -0.5 * beta / (1 - 0.86), seven times the
    # intended shift, and the whole book defaults by the trough. So the mean
    # the process reverts to is `quality + beta * factor[t]`, and only the
    # DEVIATION from that mean persists.
    mean = quality[:, None] + np.outer(beta, factor)
    z = np.zeros((n, t))
    z[:, 0] = mean[:, 0] + rng.normal(
        0.0, vol / np.sqrt(1 - PERSISTENCE ** 2))
    for step in range(1, t):
        z[:, step] = (mean[:, step]
                      + PERSISTENCE * (z[:, step - 1] - mean[:, step - 1])
                      + rng.normal(0.0, vol))
    return z


# --------------------------------------------------------------- the spine


def simulate_state(entities: pd.DataFrame, z: np.ndarray,
                   rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Who is on book, who has defaulted, and who has left, quarter by quarter.

    Three states rather than two. A borrower that defaults does not vanish -
    it stays on book, in default, for at least DEFAULT_SEASONING quarters, and
    then either cures or is written off and exits. Collapsing default into
    exit would make the book look like it had no defaults at all, because
    every defaulted name would already be gone by the reporting date.

    Exits are drawn against quality, not uniformly: weak names leave through
    write-off, strong names leave through refinancing elsewhere, and the
    middle mostly stays. A uniformly random exit would make survivorship
    uninformative, which is the one thing a sixteen-quarter panel is for.
    """
    n, t = z.shape
    entry = entities["entry_index"].to_numpy()

    active = np.zeros((n, t), dtype=bool)
    defaulted = np.zeros((n, t), dtype=bool)
    exited = np.zeros(n, dtype=bool)
    exit_index = np.full(n, -1, dtype=int)
    default_age = np.zeros(n, dtype=int)

    pd_pct = pd_from_quality(z)

    for step in range(t):
        arrived = (entry <= step) & ~exited
        active[:, step] = arrived

        live = arrived & ~defaulted[:, step - 1] if step else arrived
        hazard = np.clip(pd_pct[:, step] / 100.0 * QUARTERLY_HAZARD, 0.0, 0.5)
        newly = live & (rng.random(n) < hazard)

        carried = defaulted[:, step - 1] & arrived if step else np.zeros(n, bool)
        defaulted[:, step] = carried | newly
        default_age = np.where(newly, 1,
                               np.where(defaulted[:, step], default_age + 1, 0))

        if step == t - 1:
            break

        # Write-off: a seasoned default that does not cure leaves the book.
        seasoned = defaulted[:, step] & (default_age >= DEFAULT_SEASONING)
        written_off = seasoned & (rng.random(n) < 0.34)
        # Cure: the rest of the seasoned defaults, if quality has recovered.
        cured = seasoned & ~written_off & (z[:, step] > -0.35)
        defaulted[cured, step] = defaulted[cured, step]  # state read below
        default_age = np.where(cured, 0, default_age)

        # Voluntary exit: refinanced away or relationship closed. Slightly
        # more likely for strong names, who have somewhere else to go.
        strength = np.clip((z[:, step] + 1.5) / 3.5, 0.0, 1.0)
        leaving = (arrived & ~defaulted[:, step]
                   & (rng.random(n) < 0.004 + 0.006 * strength))

        gone = written_off | leaving
        exited |= gone
        exit_index = np.where(gone & (exit_index < 0), step, exit_index)
        # A cure clears the default flag from the NEXT quarter onwards.
        defaulted[cured, step + 1:] = False

    return {
        "active": active,
        "defaulted": defaulted & active,
        "exit_index": exit_index,
        "pd_pct": pd_pct,
    }


def spine(entities: pd.DataFrame, state: dict[str, np.ndarray],
          z: np.ndarray, periods: list[str]) -> pd.DataFrame:
    """The borrower-quarter index every domain frame is built on.

    One row per borrower per quarter it is on book. Every other frame in this
    module joins to it, so a field that disagrees with the spine about whether
    a borrower existed in a quarter is a bug rather than a judgement call.
    """
    active = state["active"]
    rows, cols = np.nonzero(active)
    order = np.lexsort((rows, cols))
    rows, cols = rows[order], cols[order]

    return pd.DataFrame({
        "borrower_id": entities["borrower_id"].to_numpy()[rows],
        "period": np.array(periods)[cols],
        "period_end_date": np.array([quarter_end(p) for p in periods])[cols],
        "entity_index": rows,
        "quarter_index": cols,
        "quality": np.round(z[rows, cols], 4),
        "pd_pct": np.round(state["pd_pct"][rows, cols], 4),
        "default_flag": state["defaulted"][rows, cols],
    })


# ------------------------------------------------------------------ ratings


def build_ratings(entities: pd.DataFrame, spine_df: pd.DataFrame,
                  rng: np.random.Generator) -> pd.DataFrame:
    """The internal grade, its model, its override and its movement. B3.

    The grade is read from the PD, then a small share are OVERRIDDEN by a
    committee - up or down a notch, with the reason recorded. Overrides are
    generated rather than left out because "how often does the committee
    disagree with the model, and in which direction" is one of the questions
    the module exists to answer, and a book with no overrides answers it
    vacuously.
    """
    n = len(spine_df)
    index = spine_df["entity_index"].to_numpy()
    quarter = spine_df["quarter_index"].to_numpy()
    pd_pct = spine_df["pd_pct"].to_numpy()
    default_flag = spine_df["default_flag"].to_numpy()

    model_grade = grade_from_pd(pd_pct)

    # An override on roughly one name in fourteen, more often downwards: a
    # committee that overrides is usually adding a concern the model cannot
    # see rather than removing one it can.
    draw = rng.random(n)
    override = draw < 0.072
    direction = np.where(rng.random(n) < 0.62, 1, -1)
    grade_index = np.clip(model_grade + override * direction,
                          0, DEFAULT_INDEX - 1)
    grade_index = np.where(default_flag, DEFAULT_INDEX, grade_index)

    segment = entities["segment"].to_numpy()[index]
    model = np.where(
        segment == "Financial Institution", RATING_MODELS[1],
        np.where(segment == "Public Sector", RATING_MODELS[2], RATING_MODELS[0]))

    frame = pd.DataFrame({
        "borrower_id": spine_df["borrower_id"].to_numpy(),
        "period": spine_df["period"].to_numpy(),
        "period_end_date": spine_df["period_end_date"].to_numpy(),
        "internal_rating": np.array(RATING_SCALE)[grade_index],
        "internal_rating_numeric": grade_index + 1,
        "model_grade": np.array(RATING_SCALE)[model_grade],
        "rating_model": model,
        "rating_override_flag": override & ~default_flag,
        "rating_override_reason": np.where(
            override & ~default_flag,
            np.where(direction > 0,
                     "Committee: sector headwinds not in model inputs",
                     "Committee: parental support not in model inputs"),
            ""),
        "rating_date": spine_df["period_end_date"].to_numpy(),
        "external_rating": "",
        "rating_outlook": "",
        "_entity_index": index,
        "_quarter_index": quarter,
    })

    # Previous rating, per borrower, in period order. Left blank for the
    # quarter a borrower joins - there is no previous assessment, and a zero
    # there would be read as "no change".
    frame = frame.sort_values(["borrower_id", "_quarter_index"])
    previous = frame.groupby("borrower_id")["internal_rating_numeric"].shift(1)
    frame["previous_rating"] = np.where(
        previous.isna(), "",
        np.array(RATING_SCALE)[previous.fillna(1).astype(int) - 1])
    notches = frame["internal_rating_numeric"] - previous
    frame["rating_change_notches"] = notches.fillna(0).astype(int)
    frame["rating_direction"] = np.select(
        [previous.isna(), notches > 0, notches < 0],
        ["NEW", "DOWNGRADE", "UPGRADE"], default="STABLE")

    # An external rating on the names that would plausibly carry one.
    has_external = (
        np.isin(entities["segment"].to_numpy()[frame["_entity_index"]],
                ["Large Corporate", "Public Sector", "Financial Institution"])
        & (frame["internal_rating_numeric"] <= 9))
    external_index = np.clip(
        frame["internal_rating_numeric"].to_numpy() - 1
        + rng.integers(-1, 2, len(frame)), 0, DEFAULT_INDEX - 1)
    frame["external_rating"] = np.where(
        has_external, np.array(RATING_SCALE)[external_index], "")
    frame["rating_outlook"] = np.where(
        has_external,
        np.array(RATING_OUTLOOKS)[np.clip(
            1 + np.sign(frame["rating_change_notches"].to_numpy()), 0, 2)],
        "")

    frame["watchlist_flag"] = (
        (frame["internal_rating_numeric"] >= 11)
        | (frame["rating_change_notches"] >= 2))
    frame["origin"] = ORIGIN
    return frame.drop(columns=["_entity_index", "_quarter_index"]).reset_index(
        drop=True)


# --------------------------------------------------------------- financials

#: Fiscal years spread, so the latest available statement at a given quarter
#: is genuinely sometimes eighteen months old. Staleness is a finding the
#: module is meant to surface, so it has to exist in the data.
FISCAL_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)

#: Scheduled principal repaid in a year, as a share of total debt. A blend:
#: term debt amortises, revolvers and trade lines do not, so the book-wide
#: figure is well below the amortisation profile of any single term loan.
#: Set so the median borrower's debt-service cover lands near 1.3x, which is
#: where a mid-corporate book with four times leverage actually sits.
AMORTISATION_RATE = 0.065


def build_financials(entities: pd.DataFrame, z: np.ndarray,
                     rng: np.random.Generator) -> pd.DataFrame:
    """Spread statements, one row per borrower per fiscal year. B3, B4.

    At statement grain rather than quarterly, because that is the grain the
    data has: a company files once a year, and a Borrower 360 that shows a
    "Q2 2025 leverage" is showing the FY2024 statement with a label that hides
    how old it is. The snapshot picks the latest statement whose publication
    date has passed, and carries its age in days (B4) so the reader can see it.

    The statements are driven by the same latent quality as everything else,
    read one fiscal year behind - which is why a leverage ratio predicts a
    downgrade rather than merely accompanying one.
    """
    rows: list[pd.DataFrame] = []
    n = len(entities)
    revenue_scale = entities["revenue_scale"].to_numpy()
    margin = entities["sector_margin"].to_numpy()

    # Persistent idiosyncratic character, drawn ONCE per borrower.
    #
    # Drawing this noise fresh each fiscal year makes every company re-roll
    # its capital structure annually: leverage moves half a turn in a random
    # direction with no cause, and a covenant set with 30% headroom at
    # origination is breached by drift alone within three years. Real
    # companies are persistently more or less leveraged than their peers, so
    # the idiosyncratic part is a fixed trait and only a small innovation
    # moves year to year.
    trait = {
        name: rng.normal(0.0, sigma, n) for name, sigma in (
            ("leverage", 0.62), ("margin", 0.022), ("cash", 0.055),
            ("assets", 0.13), ("equity", 0.075), ("working_capital", 0.055),
            ("cfo", 0.11), ("current", 0.20), ("quick", 0.17),
            ("interest", 0.005), ("growth", 0.035),
        )}
    #: How much of the trait persists into the next statement. The rest is a
    #: fresh innovation, so a company can genuinely re-lever - just not by
    #: accident, every year, in both directions at once.
    drift = 0.30

    for offset, year in enumerate(FISCAL_YEARS):
        # FY2021 predates the window, so quality is read from the first
        # simulated quarter; later years step forward four quarters each.
        quarter = np.clip((offset - 1) * 4, 0, z.shape[1] - 1)
        quality = z[:, quarter]

        growth = np.clip(
            0.06 + 0.05 * quality + trait["growth"]
            + rng.normal(0, 0.06 * drift, n), -0.35, 0.55)
        revenue = revenue_scale * (1.0 + growth) ** offset
        ebitda_margin = np.clip(
            margin * (1.0 + 0.22 * quality) + trait["margin"]
            + rng.normal(0, 0.025 * drift, n), 0.01, 0.62)
        ebitda = revenue * ebitda_margin
        depreciation = revenue * np.clip(
            0.035 + rng.normal(0, 0.008, n), 0.005, 0.09)
        ebit = ebitda - depreciation

        leverage = np.clip(
            4.4 - 1.15 * quality + trait["leverage"]
            + rng.normal(0, 0.55 * drift, n), 0.2, 14.0)
        debt = ebitda * leverage
        cash = debt * np.clip(
            0.16 + 0.06 * quality + trait["cash"]
            + rng.normal(0, 0.05 * drift, n), 0.01, 0.75)
        net_debt = debt - cash
        interest = debt * np.clip(
            0.062 - 0.004 * quality + trait["interest"]
            + rng.normal(0, 0.005 * drift, n), 0.025, 0.13)
        net_income = np.maximum(ebit - interest, -0.9 * revenue) * 0.82

        total_assets = debt + revenue * np.clip(
            0.85 + 0.10 * quality + trait["assets"]
            + rng.normal(0, 0.12 * drift, n), 0.35, 2.4)
        book_equity = total_assets * np.clip(
            0.30 + 0.09 * quality + trait["equity"]
            + rng.normal(0, 0.07 * drift, n), 0.02, 0.78)
        total_liabilities = total_assets - book_equity
        working_capital = revenue * np.clip(
            0.13 + 0.04 * quality + trait["working_capital"]
            + rng.normal(0, 0.05 * drift, n), -0.12, 0.45)
        cfo = ebitda * np.clip(
            0.72 + 0.10 * quality + trait["cfo"]
            + rng.normal(0, 0.10 * drift, n), 0.05, 1.15)
        capex = revenue * np.clip(0.045 + rng.normal(0, 0.015, n), 0.004, 0.16)

        # Publication lag: most file within five months, some drag past a year.
        lag_days = np.clip(
            rng.normal(148, 46, n) + (quality < -0.5) * rng.normal(85, 40, n),
            75, 520).astype(int)
        statement_date = (pd.Timestamp(f"{year}-12-31")
                          + pd.to_timedelta(lag_days, unit="D"))

        rows.append(pd.DataFrame({
            "borrower_id": entities["borrower_id"].to_numpy(),
            "fiscal_year": year,
            "financial_statement_date": pd.Timestamp(
                f"{year}-12-31").strftime("%Y-%m-%d"),
            "statement_published_date": statement_date.strftime("%Y-%m-%d"),
            "statement_basis": np.where(
                entities["segment"].to_numpy() == "Large Corporate",
                "Audited consolidated", "Audited standalone"),
            "revenue": _round(revenue),
            "revenue_growth": _round(growth * 100, 2),
            "ebitda": _round(ebitda),
            "ebitda_margin": _round(ebitda_margin * 100, 2),
            "ebit": _round(ebit),
            "net_income": _round(net_income),
            "total_assets": _round(total_assets),
            "total_liabilities": _round(total_liabilities),
            "book_equity": _round(book_equity),
            "cash": _round(cash),
            "working_capital": _round(working_capital),
            "debt": _round(debt),
            "net_debt": _round(net_debt),
            "leverage": _round(np.where(ebitda > 0, debt / ebitda, 99.0), 2),
            "net_leverage": _round(
                np.where(ebitda > 0, net_debt / ebitda, 99.0), 2),
            "dscr": _round(np.where(
                interest > 0,
                cfo / np.maximum(interest + debt * AMORTISATION_RATE, 0.01),
                9.99), 2),
            "interest_coverage": _round(
                np.where(interest > 0, ebit / interest, 99.0), 2),
            "current_ratio": _round(np.clip(
                1.18 + 0.20 * quality + trait["current"]
                + rng.normal(0, 0.18 * drift, n), 0.25, 3.6), 2),
            "quick_ratio": _round(np.clip(
                0.86 + 0.18 * quality + trait["quick"]
                + rng.normal(0, 0.15 * drift, n), 0.10, 2.9), 2),
            "debt_to_equity": _round(
                np.where(book_equity > 0, debt / book_equity, 99.0), 2),
            "cash_flow_from_operations": _round(cfo),
            "free_cash_flow": _round(cfo - capex),
            "currency": "SAR",
            "unit": "millions",
            "origin": ORIGIN,
        }))

    return pd.concat(rows, ignore_index=True)


# --------------------------------------------------------- facility & exposure

PRODUCTS: tuple[tuple[str, float, bool, bool], ...] = (
    # name, weight, funded, revolving
    ("Term Loan", 0.24, True, False),
    ("Revolving Credit Facility", 0.17, True, True),
    ("Working Capital Facility", 0.15, True, True),
    ("Project Finance", 0.07, True, False),
    ("Trade Finance - Letters of Credit", 0.11, False, True),
    ("Letter of Guarantee", 0.10, False, True),
    ("Overdraft", 0.06, True, True),
    ("Ijara", 0.05, True, False),
    ("Murabaha", 0.05, True, False),
)

CURRENCIES: tuple[tuple[str, float], ...] = (
    ("SAR", 0.78), ("USD", 0.17), ("EUR", 0.035), ("AED", 0.015),
)


def build_facilities(entities: pd.DataFrame, spine_df: pd.DataFrame,
                     rng: np.random.Generator) -> pd.DataFrame:
    """Every facility at every quarter end. B3.

    Facility count and size come from the borrower's scale, and utilisation
    from its quality: a name under pressure draws its revolver, which is one
    of the earliest observable signals there is and the reason utilisation is
    modelled against quality rather than drawn freely.
    """
    n_entities = len(entities)
    size = entities["size_factor"].to_numpy()

    facility_count = np.clip(
        (1 + rng.poisson(2.2, n_entities) + (size > 1.5).astype(int)), 1, 9)
    offsets = np.concatenate([[0], np.cumsum(facility_count)])

    facility_id: list[str] = []
    owner_index: list[int] = []
    for i, count in enumerate(facility_count):
        for k in range(int(count)):
            facility_id.append(f"CFAC-{offsets[i] + k + 1:06d}")
            owner_index.append(i)
    facility_id_arr = np.array(facility_id)
    owner = np.array(owner_index)
    total_facilities = len(facility_id_arr)

    product_names = tuple((p[0], p[1]) for p in PRODUCTS)
    product = _choose(rng, product_names, total_facilities)
    funded = np.isin(product, [p[0] for p in PRODUCTS if p[2]])
    revolving = np.isin(product, [p[0] for p in PRODUCTS if p[3]])
    currency = _choose(rng, CURRENCIES, total_facilities)

    #: A facility's share of its borrower's total limit. Normalised per
    #: borrower so the shares sum to one and the largest facility is a real
    #: concentration rather than an artefact of independent draws.
    share = rng.gamma(2.2, 1.0, total_facilities)
    share = share / np.bincount(owner, share, minlength=n_entities)[owner]

    borrower_limit = entities["revenue_scale"].to_numpy() * np.clip(
        rng.normal(0.55, 0.18, n_entities), 0.12, 1.4)
    limit = borrower_limit[owner] * share

    secured = rng.random(total_facilities) < 0.58
    # Most facilities predate the window. Drawing origination from the window
    # alone would give the first quarter a book a third the size of the last,
    # and every "growth since Q3 2022" figure would be measuring the
    # generator's start date rather than the book.
    origination_quarter = rng.integers(-40, QUARTER_COUNT - 1,
                                       total_facilities)
    tenor_quarters = rng.integers(20, 80, total_facilities)

    # Expand to quarters. Only facilities that exist in a quarter, for
    # borrowers that are on book in it.
    entity_period = {
        (int(e), str(p)) for e, p in
        zip(spine_df["entity_index"], spine_df["period"], strict=True)}
    quality_lookup = {
        (int(e), str(p)): q for e, p, q in
        zip(spine_df["entity_index"], spine_df["period"], spine_df["quality"],
            strict=True)}

    frames: list[pd.DataFrame] = []
    for step, period in enumerate(QUARTERS):
        live = (origination_quarter <= step) & (
            origination_quarter + tenor_quarters > step)
        on_book = np.array([(int(o), period) in entity_period for o in owner])
        keep = live & on_book
        if not keep.any():
            continue
        idx = np.nonzero(keep)[0]
        owners = owner[idx]
        quality = np.array([quality_lookup[(int(o), period)] for o in owners])

        # Utilisation rises as quality falls; a term loan is drawn in full.
        base = np.where(revolving[idx],
                        np.clip(0.52 - 0.13 * quality
                                + rng.normal(0, 0.14, len(idx)), 0.02, 1.0),
                        np.clip(0.94 + rng.normal(0, 0.05, len(idx)),
                                0.35, 1.0))
        drawn = limit[idx] * base
        undrawn = np.maximum(limit[idx] - drawn, 0.0)
        # Credit conversion on the undrawn commitment, by product.
        ccf = np.where(revolving[idx], 0.40, 0.20)

        frames.append(pd.DataFrame({
            "facility_id": facility_id_arr[idx],
            "borrower_id": entities["borrower_id"].to_numpy()[owners],
            "period": period,
            "period_end_date": quarter_end(period),
            "product_type": product[idx],
            "currency": currency[idx],
            "limit_amount": _round(limit[idx]),
            "drawn_exposure": _round(drawn),
            "undrawn_commitment": _round(undrawn),
            "utilisation_pct": _round(
                np.where(limit[idx] > 0, drawn / limit[idx] * 100, 0.0), 2),
            "funded_exposure": _round(np.where(funded[idx], drawn, 0.0)),
            "unfunded_exposure": _round(np.where(funded[idx], 0.0, drawn)),
            "trade_finance_exposure": _round(np.where(
                product[idx] == "Trade Finance - Letters of Credit",
                drawn, 0.0)),
            "guarantee_exposure": _round(np.where(
                product[idx] == "Letter of Guarantee", drawn, 0.0)),
            "ifrs9_ead": _round(drawn + undrawn * ccf),
            "credit_conversion_factor": ccf,
            "is_revolving": revolving[idx],
            "is_secured": secured[idx],
            "secured_exposure": _round(np.where(secured[idx], drawn, 0.0)),
            "unsecured_exposure": _round(np.where(secured[idx], 0.0, drawn)),
            "origination_quarter_index": origination_quarter[idx],
            "maturity_quarter_index": (
                origination_quarter[idx] + tenor_quarters[idx]),
            "origin": ORIGIN,
        }))

    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------------- IFRS 9

#: Relative PD increase that counts as a significant increase in credit risk.
SICR_PD_RATIO = 2.0
#: And the absolute increase it must also clear, so a move from 0.03% to 0.07%
#: does not trip a trigger on its own.
SICR_PD_ABSOLUTE = 0.75
#: A twelve-month PD this high is a significant increase on its own, whatever
#: the borrower was graded at origination. Roughly the CCC band.
SICR_ABSOLUTE_PD = 13.0
#: Days past due at which a facility is presumed to have suffered a SICR.
SICR_DPD_DAYS = 30
#: Days past due at which default is presumed.
DEFAULT_DPD_DAYS = 90

SCENARIOS: tuple[tuple[str, float], ...] = (
    ("Base", 0.50), ("Upside", 0.20), ("Downside", 0.30),
)


def build_ifrs9(entities: pd.DataFrame, spine_df: pd.DataFrame,
                facilities: pd.DataFrame, delinquency: pd.DataFrame,
                rng: np.random.Generator) -> pd.DataFrame:
    """Staging and expected credit loss, at obligor grain. B3, B4.

    Staged at OBLIGOR level, not facility level: for corporate exposures a
    significant increase in credit risk is assessed on the counterparty, and a
    book that stages one facility of a borrower differently from another is
    describing a bank that does not exist. The grain is stated in the domain
    metadata so nobody has to infer it from the row count.

    All three IFRS 9 triggers are evaluated separately and recorded
    separately, so a Stage 2 borrower can be asked WHY it is Stage 2 rather
    than only THAT it is.
    """
    frame = spine_df[["borrower_id", "period", "period_end_date",
                      "entity_index", "quarter_index", "pd_pct",
                      "default_flag"]].copy()

    ead = (facilities.groupby(["borrower_id", "period"])["ifrs9_ead"]
           .sum().rename("ead"))
    frame = frame.merge(ead, on=["borrower_id", "period"], how="left")
    frame["ead"] = frame["ead"].fillna(0.0)

    dpd = delinquency.set_index(["borrower_id", "period"])["current_dpd"]
    frame["current_dpd"] = frame.set_index(
        ["borrower_id", "period"]).index.map(dpd).fillna(0).astype(int)

    frame = frame.sort_values(["borrower_id", "quarter_index"])

    # PD at origination is the PD when the exposure was first recognised, and
    # for most of this book that predates the window: the facilities data has
    # three quarters of every four originating before Q3 2022. Taking the
    # borrower's PD in its FIRST OBSERVED quarter instead would anchor every
    # comparison to the top of the cycle, and by the 2025 trough almost every
    # borrower's PD would have doubled against it - putting half the book in
    # Stage 2 as an artefact of where the generator starts, not of what the
    # borrower did. So origination PD is read from the borrower's own
    # through-the-cycle quality, which is stable and is what a bank's
    # origination-grade record actually holds.
    origination_quality = (
        entities["sector_quality"].to_numpy()
        + rng.normal(0.0, 0.55, len(entities)))
    origination_pd = pd_from_quality(origination_quality)
    frame["pd_at_origination_pct"] = _round(
        origination_pd[frame["entity_index"].to_numpy()], 4)

    ratio = frame["pd_pct"] / frame["pd_at_origination_pct"].replace(0, np.nan)
    absolute = frame["pd_pct"] - frame["pd_at_origination_pct"]
    frame["sicr_trigger_pd"] = (
        (ratio >= SICR_PD_RATIO) & (absolute >= SICR_PD_ABSOLUTE)).fillna(False)
    frame["sicr_trigger_dpd"] = frame["current_dpd"] >= SICR_DPD_DAYS
    frame["sicr_trigger_watchlist"] = frame["pd_pct"] >= SICR_ABSOLUTE_PD
    frame["sicr_flag"] = (frame["sicr_trigger_pd"]
                          | frame["sicr_trigger_dpd"]
                          | frame["sicr_trigger_watchlist"])

    frame["stage"] = np.where(
        frame["default_flag"] | (frame["current_dpd"] >= DEFAULT_DPD_DAYS), 3,
        np.where(frame["sicr_flag"], 2, 1))
    frame["prior_stage"] = (frame.groupby("borrower_id")["stage"]
                            .shift(1).fillna(frame["stage"]).astype(int))
    frame["stage_moved"] = frame["stage"] - frame["prior_stage"]

    n = len(frame)
    pd_12m = frame["pd_pct"].to_numpy() / 100.0
    # Lifetime PD over a five-year horizon, floored at the twelve-month rate.
    pd_lifetime = np.clip(1.0 - (1.0 - pd_12m) ** 4.2, pd_12m, 0.999)
    secured_share = np.clip(rng.normal(0.55, 0.20, n), 0.0, 0.95)
    lgd = np.clip(0.62 - 0.38 * secured_share + rng.normal(0, 0.05, n),
                  0.08, 0.90)
    lgd = np.where(frame["stage"] == 3,
                   np.clip(lgd + 0.06, 0.10, 0.95), lgd)

    ead_v = frame["ead"].to_numpy()
    ecl_12m = pd_12m * lgd * ead_v
    ecl_lifetime = pd_lifetime * lgd * ead_v
    # Scenario weighting: the reported ECL is the probability-weighted one.
    weighted = (0.50 * 1.00 + 0.20 * 0.72 + 0.30 * 1.46)
    base_ecl = np.where(frame["stage"] == 1, ecl_12m, ecl_lifetime) * weighted
    overlay = np.where(rng.random(n) < 0.06,
                       base_ecl * rng.uniform(0.05, 0.25, n), 0.0)

    frame["pd_12m"] = _round(pd_12m * 100, 4)
    frame["pd_lifetime"] = _round(pd_lifetime * 100, 4)
    frame["lgd"] = _round(lgd * 100, 2)
    frame["ecl_12m"] = _round(ecl_12m * weighted, 4)
    frame["ecl_lifetime"] = _round(ecl_lifetime * weighted, 4)
    frame["management_overlay"] = _round(overlay, 4)
    frame["final_ecl"] = _round(base_ecl + overlay, 4)
    # Guarded denominator rather than np.where over the raw division: both
    # branches of np.where are evaluated, so the division warns on the zero-
    # exposure rows even though their result is discarded.
    safe_ead = np.where(ead_v > 0, ead_v, 1.0)
    frame["ecl_coverage"] = _round(
        np.where(ead_v > 0, (base_ecl + overlay) / safe_ead * 100, 0.0), 4)
    frame["scenario_weight_base"] = 0.50
    frame["scenario_weight_upside"] = 0.20
    frame["scenario_weight_downside"] = 0.30
    frame["ead"] = _round(ead_v)
    frame["origin"] = ORIGIN

    return frame.drop(columns=["entity_index", "quarter_index", "pd_pct"]
                      ).reset_index(drop=True)


# -------------------------------------------------------------- delinquency

DELINQUENCY_BUCKETS: tuple[tuple[int, str], ...] = (
    (0, "Current"), (30, "1-30 days"), (60, "31-60 days"),
    (90, "61-90 days"), (180, "91-180 days"), (10_000, "180+ days"),
)


def bucket_for(dpd: np.ndarray) -> np.ndarray:
    out = np.full(len(dpd), DELINQUENCY_BUCKETS[-1][1], dtype=object)
    assigned = np.zeros(len(dpd), dtype=bool)
    for edge, label in DELINQUENCY_BUCKETS:
        hit = (~assigned) & (dpd <= edge if edge else dpd <= 0)
        out[hit] = label
        assigned |= hit
    return out


def build_delinquency(entities: pd.DataFrame, spine_df: pd.DataFrame,
                      facilities: pd.DataFrame,
                      rng: np.random.Generator) -> pd.DataFrame:
    """Days past due, arrears and collections. B3, B4.

    Days past due is drawn from the same latent quality as the rating, which
    is what makes the two agree often enough to be credible and disagree often
    enough to be worth investigating. A borrower in default is always past due;
    a strong borrower occasionally is, because operational late payment
    happens to good companies and a book without it teaches the wrong lesson.
    """
    n = len(spine_df)
    quality = spine_df["quality"].to_numpy()
    default_flag = spine_df["default_flag"].to_numpy()

    # Probability of being past due at all, then the severity if so.
    p_late = np.clip(0.10 - 0.085 * quality, 0.015, 0.75)
    late = (rng.random(n) < p_late) | default_flag
    severity = np.clip(rng.gamma(1.6, 22.0, n) * np.exp(-0.30 * quality),
                       1, 640)
    dpd = np.where(late, severity, 0.0)
    dpd = np.where(default_flag, np.maximum(dpd, 91), dpd).astype(int)

    exposure = (facilities.groupby(["borrower_id", "period"])["drawn_exposure"]
                .sum())
    drawn = spine_df.set_index(["borrower_id", "period"]).index.map(
        exposure).to_numpy()
    drawn = np.nan_to_num(np.asarray(drawn, dtype=float))

    arrears = np.where(dpd > 0,
                       drawn * np.clip(rng.uniform(0.01, 0.12, n)
                                       * (1 + dpd / 180.0), 0.0, 0.95), 0.0)
    missed = np.clip((dpd // 30) + (rng.random(n) < 0.25).astype(int), 0, 12)

    frame = pd.DataFrame({
        "borrower_id": spine_df["borrower_id"].to_numpy(),
        "period": spine_df["period"].to_numpy(),
        "period_end_date": spine_df["period_end_date"].to_numpy(),
        "current_dpd": dpd,
        "delinquency_bucket": bucket_for(dpd),
        "arrears_amount": _round(arrears),
        "days_since_last_payment": np.where(
            dpd > 0, dpd + rng.integers(0, 22, n), rng.integers(1, 62, n)),
        "number_of_missed_payments_12m": missed,
        "collections_flag": dpd >= 60,
        "collections_stage": np.select(
            [dpd >= 180, dpd >= 90, dpd >= 60, dpd >= 30],
            ["Legal recovery", "Formal demand", "Collections engaged",
             "First reminder"], default="None"),
        "quarter_index": spine_df["quarter_index"].to_numpy(),
        "origin": ORIGIN,
    })

    # Rolling maxima, per borrower, in period order.
    frame = frame.sort_values(["borrower_id", "quarter_index"])
    grouped = frame.groupby("borrower_id")["current_dpd"]
    frame["max_dpd_3m"] = frame["current_dpd"]
    frame["max_dpd_12m"] = (grouped.rolling(4, min_periods=1).max()
                            .reset_index(level=0, drop=True).astype(int))
    return frame.drop(columns=["quarter_index"]).reset_index(drop=True)


# ---------------------------------------------------------------- covenants

COVENANTS: tuple[tuple[str, str, str, float], ...] = (
    # name, tested measure, direction, threshold
    ("Net leverage", "net_leverage", "MAXIMUM", 4.50),
    ("Interest cover", "interest_coverage", "MINIMUM", 2.50),
    ("Debt service cover", "dscr", "MINIMUM", 1.20),
    ("Current ratio", "current_ratio", "MINIMUM", 1.05),
    ("Debt to equity", "debt_to_equity", "MAXIMUM", 2.20),
    ("Minimum tangible net worth", "book_equity", "MINIMUM", 0.0),
)


def build_covenants(entities: pd.DataFrame, spine_df: pd.DataFrame,
                    financials: pd.DataFrame,
                    rng: np.random.Generator) -> pd.DataFrame:
    """One row per covenant test. B3, B4.

    Tested against the LATEST AVAILABLE statement, not against a figure
    invented for the quarter. That is what makes a covenant breach a
    consequence of the financials rather than a second, unrelated opinion
    about the borrower - and it is why a breach on a stale statement can be
    recognised as a breach on a stale statement.

    Thresholds are set at ORIGINATION, with headroom, and then held fixed.
    Setting them at a market-standard absolute instead - four and a half times
    leverage for everybody - breaches a quarter of the book on day one, because
    the standard is a starting point for a negotiation and not a level every
    borrower actually sits inside. Anchoring on the borrower's own earliest
    statement and adding a cushion reproduces what a credit agreement does:
    everyone complies when it is signed, and a breach afterwards means
    something changed.

    Headroom is signed and expressed as a percentage of the threshold, so a
    maximum and a minimum covenant sit in the same column and compare:
    positive is compliant, negative is breached, in both directions.
    """
    latest = latest_statement(spine_df, financials)
    n_borrowers = len(entities)

    #: Which covenants a borrower is subject to. Not every facility carries
    #: every covenant, and a book where everyone is tested on everything makes
    #: "covenants tested" a constant rather than a fact.
    subject = rng.random((n_borrowers, len(COVENANTS))) < np.array(
        [0.72, 0.68, 0.55, 0.40, 0.45, 0.30])
    #: Headroom granted at origination, as a multiple of the borrower's own
    #: level. Drawn per borrower per covenant, so a tightly covenanted name is
    #: tight across the board and a loosely covenanted one is loose.
    #: 30% to 75%. A credit committee sets a covenant to catch a material
    #: deterioration, not a normal year: this book's quality falls by about
    #: two thirds of a unit peak to trough, which moves leverage by roughly a
    #: fifth, so a cushion narrower than that breaches most of the book at the
    #: trough on arithmetic alone.
    cushion = rng.uniform(0.30, 0.75, (n_borrowers, len(COVENANTS)))

    # The anchor is each borrower's earliest spread statement - what the
    # credit committee would have had in front of it.
    earliest = (financials.sort_values("fiscal_year")
                .groupby("borrower_id", as_index=False).first())
    anchor = earliest.set_index("borrower_id")

    rows: list[pd.DataFrame] = []
    entity_index = latest["entity_index"].to_numpy()
    for position, (name, measure, direction, floor) in enumerate(COVENANTS):
        keep = subject[entity_index, position]
        if not keep.any():
            continue
        part = latest.loc[keep]
        observed = part[measure].to_numpy()
        base = anchor.loc[part["borrower_id"].to_numpy(), measure].to_numpy()
        cush = cushion[part["entity_index"].to_numpy(), position]

        if direction == "MAXIMUM":
            threshold = np.abs(base) * (1.0 + cush)
            # Never looser than the market standard where one exists.
            if floor > 0:
                threshold = np.minimum(threshold, floor * (1.0 + cush))
            headroom = (threshold - observed) / np.maximum(
                np.abs(threshold), 1e-9) * 100
        else:
            threshold = np.abs(base) * (1.0 - cush * 0.75)
            if floor > 0:
                threshold = np.maximum(threshold, floor * (1.0 - cush * 0.75))
            headroom = (observed - threshold) / np.maximum(
                np.abs(threshold), 1e-9) * 100

        rows.append(pd.DataFrame({
            "borrower_id": part["borrower_id"].to_numpy(),
            "period": part["period"].to_numpy(),
            "period_end_date": part["period_end_date"].to_numpy(),
            "covenant_id": f"COV-{position + 1:02d}",
            "covenant_name": name,
            "tested_measure": measure,
            "direction": direction,
            "threshold": _round(threshold, 3),
            "observed_value": _round(observed, 3),
            "headroom_pct": _round(headroom, 2),
            "breach_flag": headroom < 0,
            "tested_on_statement_date": part[
                "financial_statement_date"].to_numpy(),
            "statement_age_days": part[
                "financial_statement_age_days"].to_numpy(),
            "next_test_date": part["next_test_date"].to_numpy(),
            "waiver_granted": False,
            "origin": ORIGIN,
        }))

    frame = pd.concat(rows, ignore_index=True)
    # A waiver on roughly a fifth of breaches. Recorded rather than netted off,
    # so "how many covenants breached" and "how many breaches were waived"
    # stay two different numbers.
    breached = frame["breach_flag"].to_numpy()
    frame["waiver_granted"] = breached & (rng.random(len(frame)) < 0.21)
    return frame


def latest_statement(spine_df: pd.DataFrame,
                     financials: pd.DataFrame) -> pd.DataFrame:
    """The most recent statement PUBLISHED by each quarter end, and its age.

    An as-of join, not a fiscal-year join. A borrower's FY2024 statement is
    not available in Q1 2025 if it was published in May; using it there would
    give the demonstration foresight it does not have, and would make every
    covenant test and every ratio silently forward-looking.
    """
    left = spine_df[["borrower_id", "period", "period_end_date",
                     "entity_index", "quarter_index"]].copy()
    left["as_of"] = pd.to_datetime(left["period_end_date"])

    right = financials.copy()
    right["published"] = pd.to_datetime(right["statement_published_date"])
    right = right.sort_values("published")

    merged = pd.merge_asof(
        left.sort_values("as_of"), right,
        left_on="as_of", right_on="published", by="borrower_id",
        direction="backward")

    merged["financial_statement_age_days"] = (
        merged["as_of"] - pd.to_datetime(merged["financial_statement_date"])
    ).dt.days
    merged["next_test_date"] = (
        merged["as_of"] + pd.Timedelta(days=91)).dt.strftime("%Y-%m-%d")
    return merged.dropna(subset=["fiscal_year"]).reset_index(drop=True)


# --------------------------------------------------------------- collateral

COLLATERAL_TYPES: tuple[tuple[str, float, float, int], ...] = (
    # type, weight, eligible haircut, typical revaluation interval in days
    ("Real Estate Mortgage", 0.31, 0.30, 730),
    ("Cash Collateral", 0.08, 0.00, 90),
    ("Assignment of Receivables", 0.16, 0.35, 180),
    ("Plant & Machinery", 0.12, 0.50, 730),
    ("Listed Securities", 0.06, 0.25, 90),
    ("Inventory", 0.09, 0.55, 365),
    ("Corporate Guarantee", 0.13, 0.40, 365),
    ("Sovereign Guarantee", 0.05, 0.10, 1095),
)


def build_collateral(entities: pd.DataFrame, spine_df: pd.DataFrame,
                     facilities: pd.DataFrame,
                     rng: np.random.Generator) -> pd.DataFrame:
    """One row per collateral item per quarter. B3, B4.

    Market value moves with the cycle - property and inventory hardest,
    cash not at all - and the ELIGIBLE value is market value after the
    regulatory haircut for the type. The two are kept as separate columns
    because a coverage ratio computed on market value and one computed on
    eligible value differ by a third, and a screen that shows one of them
    labelled "collateral coverage" without saying which is unreadable.

    Valuation age is real: a property revalued every two years is, on
    average, a year out of date, and that is a fact about the security a
    credit officer needs rather than an inconvenience to be smoothed away.
    """
    secured = facilities[facilities["is_secured"]]
    if secured.empty:  # pragma: no cover - the generator always secures some
        return pd.DataFrame()

    # One collateral item per secured facility, occasionally two.
    keys = secured[["facility_id", "borrower_id", "period", "period_end_date",
                    "drawn_exposure"]].reset_index(drop=True)
    extra = keys.loc[rng.random(len(keys)) < 0.22].copy()
    extra["_second"] = True
    keys["_second"] = False
    items = pd.concat([keys, extra], ignore_index=True)

    n = len(items)
    kind = _choose(rng, tuple((c[0], c[1]) for c in COLLATERAL_TYPES), n)
    haircut = np.array([{c[0]: c[2] for c in COLLATERAL_TYPES}[k]
                        for k in kind])
    interval = np.array([{c[0]: c[3] for c in COLLATERAL_TYPES}[k]
                         for k in kind])

    quarter_index = np.array([QUARTERS.index(p) for p in items["period"]])
    cycle = macro_factor(np.random.default_rng(SEED), QUARTERS)[
        "credit_cycle_factor"].to_numpy()
    sensitivity = np.where(
        np.isin(kind, ["Real Estate Mortgage", "Inventory",
                       "Listed Securities"]), 0.22,
        np.where(kind == "Cash Collateral", 0.0, 0.09))

    cover = np.clip(rng.gamma(3.0, 0.42, n), 0.15, 3.2)
    market_value = (items["drawn_exposure"].to_numpy() * cover
                    * (1.0 + sensitivity * cycle[quarter_index]))
    market_value = np.where(items["_second"].to_numpy(),
                            market_value * 0.35, market_value)
    eligible = market_value * (1.0 - haircut)

    # Age as a MULTIPLE of the revaluation interval, not a uniform draw
    # inside it. A uniform draw inside the interval makes an overdue valuation
    # arithmetically impossible, which would hide the one collateral finding a
    # credit officer most needs: security whose stated value nobody has
    # checked since before the borrower deteriorated. Revaluation slips, so a
    # sixth of this book's security is past its own interval.
    age = np.clip(
        (interval * np.clip(rng.gamma(2.4, 0.30, n), 0.02, 2.6)).astype(int),
        0, 1825)
    as_of = pd.to_datetime(items["period_end_date"])
    valuation_date = (as_of - pd.to_timedelta(age, unit="D"))

    return pd.DataFrame({
        "collateral_id": [f"COLL-{i + 1:07d}" for i in range(n)],
        "facility_id": items["facility_id"].to_numpy(),
        "borrower_id": items["borrower_id"].to_numpy(),
        "period": items["period"].to_numpy(),
        "period_end_date": items["period_end_date"].to_numpy(),
        "collateral_type": kind,
        "collateral_market_value": _round(market_value),
        "regulatory_haircut_pct": _round(haircut * 100, 1),
        "collateral_eligible_value": _round(eligible),
        "last_valuation_date": valuation_date.dt.strftime("%Y-%m-%d"),
        "valuation_age_days": age,
        "revaluation_interval_days": interval,
        "valuation_overdue": age > interval,
        "origin": ORIGIN,
    })


# ------------------------------------------------------ limits & large exposure

#: A demonstration eligible-capital reference, in millions. §B55: this is NOT
#: a verified regulatory figure for any institution. It exists so utilisation
#: percentages have a denominator and so the large-exposure screen has
#: something to compute; any real limit must come from the client's own
#: capital position.
ELIGIBLE_CAPITAL_REFERENCE = 42_000.0
#: Likewise demonstration thresholds, expressed against that reference.
SINGLE_NAME_LIMIT_PCT = 15.0
GROUP_LIMIT_PCT = 25.0
INVESTIGATION_TRIGGER_PCT = 10.0
UNVERIFIED_REGULATORY_PARAMETER = (
    "UNVERIFIED REGULATORY PARAMETER: the eligible capital reference and the "
    "single-name, group and investigation thresholds here are demonstration "
    "values. They are not a verified statement of any binding limit under any "
    "regulation, and must be replaced with the institution's own before any "
    "figure derived from them is relied on."
)


def build_limits(entities: pd.DataFrame, spine_df: pd.DataFrame,
                 facilities: pd.DataFrame,
                 rng: np.random.Generator) -> pd.DataFrame:
    """Single-name utilisation against the capital reference. B3, B4.

    Group utilisation is left EMPTY here and filled in by the graph module,
    because "the group" is a derived answer that depends on how connectedness
    was defined - and writing a number into this domain now would make the
    limits domain quietly authoritative over a question the graph has not been
    asked yet.
    """
    exposure = (facilities.groupby(["borrower_id", "period"])
                .agg(total_limit=("limit_amount", "sum"),
                     total_outstanding=("drawn_exposure", "sum"),
                     ifrs9_ead=("ifrs9_ead", "sum"),
                     facility_count=("facility_id", "size"),
                     largest_facility=("limit_amount", "max"))
                .reset_index())

    frame = spine_df[["borrower_id", "period", "period_end_date"]].merge(
        exposure, on=["borrower_id", "period"], how="left")
    for column in ("total_limit", "total_outstanding", "ifrs9_ead",
                   "largest_facility"):
        frame[column] = frame[column].fillna(0.0)
    frame["facility_count"] = frame["facility_count"].fillna(0).astype(int)

    utilisation = (frame["ifrs9_ead"] / ELIGIBLE_CAPITAL_REFERENCE * 100)
    frame["eligible_capital_reference"] = ELIGIBLE_CAPITAL_REFERENCE
    frame["single_name_utilisation_pct"] = _round(utilisation, 4)
    frame["single_name_limit_pct"] = SINGLE_NAME_LIMIT_PCT
    frame["limit_status"] = np.select(
        [utilisation >= SINGLE_NAME_LIMIT_PCT,
         utilisation >= INVESTIGATION_TRIGGER_PCT],
        ["BREACH", "INVESTIGATE"], default="WITHIN LIMIT")
    frame["investigation_trigger"] = utilisation >= INVESTIGATION_TRIGGER_PCT
    frame["group_utilisation_pct"] = np.nan
    frame["group_limit_pct"] = GROUP_LIMIT_PCT
    frame["group_utilisation_status"] = "NOT YET COMPUTED"
    frame["parameter_caveat"] = UNVERIFIED_REGULATORY_PARAMETER
    frame["origin"] = ORIGIN
    return frame


# ---------------------------------------------------------------- watchlist

WATCHLIST_SIGNALS: tuple[tuple[str, str, float], ...] = (
    # signal, severity, relative likelihood
    ("Covenant breach reported", "HIGH", 0.16),
    ("Liquidity pressure observed", "HIGH", 0.13),
    ("Delayed submission of audited financials", "MEDIUM", 0.14),
    ("Key management departure", "MEDIUM", 0.08),
    ("Sector headwinds", "MEDIUM", 0.12),
    ("Loss of a major customer", "HIGH", 0.07),
    ("Adverse press coverage", "LOW", 0.08),
    ("Litigation disclosed", "MEDIUM", 0.06),
    ("Going-concern language in audit opinion", "HIGH", 0.05),
    ("Related-party exposure concentration", "MEDIUM", 0.06),
    ("Group affiliate under stress", "MEDIUM", 0.05),
)

WATCHLIST_GRADES: tuple[str, ...] = (
    "Not listed", "Monitor", "Watch", "Substandard", "Special mention",
)


def build_watchlist(entities: pd.DataFrame, spine_df: pd.DataFrame,
                    rng: np.random.Generator) -> pd.DataFrame:
    """Qualitative concerns, one row per signal raised. B3.

    Deliberately NOT one row per borrower-quarter with a flag. A borrower can
    carry three concerns at once and they can be raised by three different
    people on three different dates, and collapsing them to a boolean throws
    away the only part a credit officer reads.
    """
    quality = spine_df["quality"].to_numpy()
    n = len(spine_df)
    # Expected number of open signals rises sharply as quality falls.
    intensity = np.clip(0.06 + np.exp(-1.5 * quality) * 0.10, 0.02, 1.6)
    count = rng.poisson(intensity)

    rows: list[dict[str, Any]] = []
    weights = np.array([s[2] for s in WATCHLIST_SIGNALS])
    weights = weights / weights.sum()
    borrower = spine_df["borrower_id"].to_numpy()
    period = spine_df["period"].to_numpy()
    period_end = spine_df["period_end_date"].to_numpy()

    picks = rng.choice(len(WATCHLIST_SIGNALS), size=int(count.sum()), p=weights)
    raisers = rng.choice(RELATIONSHIP_MANAGERS, size=int(count.sum()))
    cursor = 0
    for row in range(n):
        for _ in range(int(count[row])):
            signal, severity, _ = WATCHLIST_SIGNALS[picks[cursor]]
            rows.append({
                "borrower_id": borrower[row],
                "period": period[row],
                "period_end_date": period_end[row],
                "signal": signal,
                "severity": severity,
                "raised_by": raisers[cursor],
                "raised_date": period_end[row],
                "origin": ORIGIN,
            })
            cursor += 1

    frame = pd.DataFrame(rows)
    if frame.empty:  # pragma: no cover - the generator always raises some
        return frame

    # The watchlist GRADE is a per-borrower-quarter conclusion drawn from the
    # signals, so it is derived here rather than drawn independently: a grade
    # that disagrees with its own evidence is the defect this avoids.
    severity_rank = frame["severity"].map(
        {"LOW": 1, "MEDIUM": 2, "HIGH": 3})
    summary = (frame.assign(rank=severity_rank)
               .groupby(["borrower_id", "period"])
               .agg(worst=("rank", "max"), signals=("signal", "size")))
    grade = np.select(
        [(summary["worst"] == 3) & (summary["signals"] >= 3),
         summary["worst"] == 3,
         summary["worst"] == 2],
        [WATCHLIST_GRADES[4], WATCHLIST_GRADES[3], WATCHLIST_GRADES[2]],
        default=WATCHLIST_GRADES[1])
    lookup = pd.Series(grade, index=summary.index)
    frame["watchlist_grade"] = frame.set_index(
        ["borrower_id", "period"]).index.map(lookup)
    return frame


# ------------------------------------------------------------ restructuring

CONCESSION_TYPES: tuple[str, ...] = (
    "Payment holiday", "Interest-only period", "Maturity extension",
    "Covenant reset", "Interest rate reduction", "Debt rescheduling",
    "Partial debt forgiveness",
)
#: Quarters of performing behaviour before a forborne exposure may exit
#: forbearance. A demonstration value, not a verified regulatory probation
#: period - B55.
FORBEARANCE_PROBATION_QUARTERS = 8


def build_restructuring(entities: pd.DataFrame, spine_df: pd.DataFrame,
                        rng: np.random.Generator) -> pd.DataFrame:
    """Concessions granted for credit reasons. B3.

    A concession is only forbearance if it was granted BECAUSE the borrower
    was in difficulty; the same maturity extension granted to a strong
    borrower for commercial reasons is not. Both are generated, and the
    distinction is carried in `granted_for_credit_reasons` rather than
    inferred, because inferring it from the borrower's grade is exactly the
    circular reasoning the classification exists to prevent.
    """
    quality = spine_df["quality"].to_numpy()
    n = len(spine_df)
    hazard = np.clip(0.004 + np.exp(-1.9 * quality) * 0.010, 0.001, 0.16)
    granted = rng.random(n) < hazard
    if not granted.any():  # pragma: no cover
        return pd.DataFrame()

    part = spine_df.loc[granted].reset_index(drop=True)
    m = len(part)
    credit_reasons = part["quality"].to_numpy() < 0.15
    # Some strong borrowers restructure commercially; some weak ones do too.
    credit_reasons = np.where(rng.random(m) < 0.12, ~credit_reasons,
                              credit_reasons)

    return pd.DataFrame({
        "restructuring_id": [f"RST-{i + 1:06d}" for i in range(m)],
        "borrower_id": part["borrower_id"].to_numpy(),
        "period": part["period"].to_numpy(),
        "period_end_date": part["period_end_date"].to_numpy(),
        "concession_type": rng.choice(CONCESSION_TYPES, m),
        "granted_date": part["period_end_date"].to_numpy(),
        "granted_for_credit_reasons": credit_reasons,
        "forbearance_flag": credit_reasons,
        "probation_quarters": np.where(
            credit_reasons, FORBEARANCE_PROBATION_QUARTERS, 0),
        "probation_ends_quarter_index": np.where(
            credit_reasons,
            part["quarter_index"].to_numpy() + FORBEARANCE_PROBATION_QUARTERS,
            part["quarter_index"].to_numpy()),
        "restructure_flag": True,
        "parameter_caveat": (
            "The probation period is a demonstration value, not a verified "
            "regulatory requirement - B55."),
        "origin": ORIGIN,
    })


# ------------------------------------------------------------- profitability

#: Demonstration capital and hurdle parameters. B55: not verified regulatory
#: or institutional figures.
CAPITAL_RATIO = 0.105
RISK_WEIGHT_BY_STAGE: dict[int, float] = {1: 0.75, 2: 1.20, 3: 1.50}
HURDLE_RATE_PCT = 12.0


def build_profitability(entities: pd.DataFrame, spine_df: pd.DataFrame,
                        facilities: pd.DataFrame, ifrs9: pd.DataFrame,
                        rng: np.random.Generator) -> pd.DataFrame:
    """Revenue, cost of risk, capital consumed and the return on it. B3.

    RAROC here is a demonstration construction, not the institution's own
    methodology: net revenue less expected loss and operating cost, over
    regulatory capital at a stage-dependent risk weight. It is labelled as
    such wherever it is shown, because a return figure computed on somebody
    else's assumptions and presented without them is worse than no figure.
    """
    exposure = (facilities.groupby(["borrower_id", "period"])
                .agg(drawn=("drawn_exposure", "sum"),
                     undrawn=("undrawn_commitment", "sum"),
                     ead=("ifrs9_ead", "sum")).reset_index())
    frame = spine_df[["borrower_id", "period", "period_end_date"]].merge(
        exposure, on=["borrower_id", "period"], how="left").fillna(
        {"drawn": 0.0, "undrawn": 0.0, "ead": 0.0})

    stage = ifrs9.set_index(["borrower_id", "period"])["stage"]
    ecl = ifrs9.set_index(["borrower_id", "period"])["final_ecl"]
    keys = frame.set_index(["borrower_id", "period"]).index
    frame["stage"] = keys.map(stage).fillna(1).astype(int)
    expected_loss = np.nan_to_num(np.asarray(keys.map(ecl), dtype=float))

    n = len(frame)
    margin = np.clip(rng.normal(0.031, 0.009, n), 0.008, 0.075)
    fee_rate = np.clip(rng.normal(0.0055, 0.0022, n), 0.0, 0.02)
    net_interest = frame["drawn"].to_numpy() * margin
    fees = (frame["drawn"].to_numpy() + frame["undrawn"].to_numpy()) * fee_rate
    revenue = net_interest + fees
    operating_cost = revenue * np.clip(rng.normal(0.30, 0.07, n), 0.10, 0.62)

    risk_weight = frame["stage"].map(RISK_WEIGHT_BY_STAGE).to_numpy()
    rwa = frame["ead"].to_numpy() * risk_weight
    capital = rwa * CAPITAL_RATIO
    profit = revenue - operating_cost - expected_loss
    raroc = np.where(capital > 0, profit / np.maximum(capital, 1e-9) * 100,
                     np.nan)

    return pd.DataFrame({
        "borrower_id": frame["borrower_id"],
        "period": frame["period"],
        "period_end_date": frame["period_end_date"],
        "net_interest_income": _round(net_interest, 4),
        "fee_income": _round(fees, 4),
        "total_revenue": _round(revenue, 4),
        "operating_cost": _round(operating_cost, 4),
        "expected_loss": _round(expected_loss, 4),
        "risk_weighted_assets": _round(rwa),
        "risk_weight_applied": _round(risk_weight, 3),
        "regulatory_capital": _round(capital, 4),
        "net_profit": _round(profit, 4),
        "raroc_pct": _round(raroc, 2),
        "hurdle_rate_pct": HURDLE_RATE_PCT,
        "above_hurdle": raroc >= HURDLE_RATE_PCT,
        "methodology": (
            "Demonstration RAROC: (revenue - operating cost - expected loss) "
            "over regulatory capital at a stage-dependent risk weight. Not "
            "the institution's own methodology - B55."),
        "origin": ORIGIN,
    })


# ---------------------------------------------------------------- assembly


def build(*, periods: list[str] | None = None, seed: int = SEED) -> Universe:
    """The whole corporate universe, in dependency order. B1.

    One generator, one seed, one pass. The order matters and is not arbitrary:
    delinquency is built before IFRS 9 because staging reads days past due,
    and profitability after IFRS 9 because cost of risk is the expected credit
    loss. Building them in any other order would need a second pass to
    reconcile them, and a reconciliation pass is where two versions of the
    same number come from.
    """
    from backend.corporate import graphdata, resolution

    quarters_ = periods or QUARTERS
    rng = np.random.default_rng(seed)

    entities = build_entities(rng)
    macro = macro_factor(rng, quarters_)
    z = simulate_quality(entities, macro["credit_cycle_factor"].to_numpy(), rng)
    state = simulate_state(entities, z, rng)
    spine_df = spine(entities, state, z, quarters_)

    financials = build_financials(entities, z, rng)
    facilities = build_facilities(entities, spine_df, rng)
    delinquency = build_delinquency(entities, spine_df, facilities, rng)
    ifrs9 = build_ifrs9(entities, spine_df, facilities, delinquency, rng)
    covenants = build_covenants(entities, spine_df, financials, rng)
    collateral = build_collateral(entities, spine_df, facilities, rng)
    limits = build_limits(entities, spine_df, facilities, rng)
    watchlist = build_watchlist(entities, spine_df, rng)
    restructuring = build_restructuring(entities, spine_df, rng)
    profitability = build_profitability(
        entities, spine_df, facilities, ifrs9, rng)

    ratings = build_ratings(entities, spine_df, rng)

    graph = graphdata.build_graph(entities, rng)
    people = graphdata.build_people_edges(entities, graph["_nodes"], rng)
    supply = graphdata.build_supply_chain(entities, rng)
    exposure = graphdata.build_exposure_network(entities, graph, rng)
    guarantee_nodes, provides, covers = graphdata.build_guarantees(
        entities, facilities, graph, rng)
    entity_resolution = resolution.build(entities, people, rng)

    nodes = pd.concat(
        [graph["_nodes"], people.attrs["director_nodes"], guarantee_nodes],
        ignore_index=True)
    nodes["origin"] = ORIGIN

    ownership_edges = pd.concat(
        [graph["_ownership"], people], ignore_index=True)
    guarantees = pd.concat([provides, covers], ignore_index=True)

    master = build_customer_master(entities, spine_df, ratings)

    return Universe(
        quarters=list(quarters_),
        seed=seed,
        frames={
            "corporate_macro": macro,
            "corporate_customer_master": master,
            "corporate_ratings": ratings,
            "corporate_financials": financials,
            "corporate_facilities": facilities,
            "corporate_ifrs9": ifrs9,
            "corporate_delinquency": delinquency,
            "corporate_covenants": covenants,
            "corporate_collateral": collateral,
            "corporate_limits": limits,
            "corporate_watchlist": watchlist,
            "corporate_restructuring": restructuring,
            "corporate_profitability": profitability,
            "corporate_graph_nodes": nodes,
            "corporate_ownership_edges": ownership_edges,
            "corporate_supply_chain": supply,
            "corporate_exposure_network": exposure,
            "corporate_guarantees": guarantees,
            "corporate_entity_resolution": entity_resolution,
        })


def build_customer_master(entities: pd.DataFrame, spine_df: pd.DataFrame,
                          ratings: pd.DataFrame) -> pd.DataFrame:
    """Identity, as at each quarter. B3, B4.

    Quarterly rather than a single slowly-changing record, because the
    Borrower 360 snapshot is a quarterly object and a relationship manager who
    changed in Q2 2025 must show as the manager of record in Q2 2025 and not
    retrospectively in Q3 2022. `status` is the field that moves: everything
    else about a borrower's identity is stable by construction, and a sector
    that changed between quarters would be a data-quality finding.
    """
    frame = spine_df[["borrower_id", "period", "period_end_date",
                      "entity_index", "quarter_index"]].merge(
        entities.drop(columns=[
            "entry_index", "sector_quality", "sector_beta", "sector_vol",
            "revenue_scale", "sector_margin", "size_factor"]),
        on="borrower_id", how="left")

    watch = ratings.set_index(["borrower_id", "period"])["watchlist_flag"]
    keys = frame.set_index(["borrower_id", "period"]).index
    on_watch = pd.Series(keys.map(watch)).fillna(False).to_numpy()

    first = frame.groupby("borrower_id")["quarter_index"].transform("min")
    last = frame.groupby("borrower_id")["quarter_index"].transform("max")
    frame["status"] = np.select(
        [frame["quarter_index"] == first,
         frame["quarter_index"] == last, on_watch],
        ["NEW RELATIONSHIP", "LAST OBSERVED QUARTER", "ACTIVE - WATCHLIST"],
        default="ACTIVE")
    frame["customer_number"] = frame["borrower_id"].str.replace(
        "CORP-", "CN", regex=False)
    frame["group_id"] = ""
    frame["group_name"] = ""
    frame["origin"] = ORIGIN
    return frame.drop(columns=["entity_index", "quarter_index"])
