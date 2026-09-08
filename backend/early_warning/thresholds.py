"""Numeric band boundaries for the classifiers that have a real source
field in `corporate_borrower_360` (or a real, governed derivation from the
corporate graph domains) today — the numeric-cutoff counterpart to the
descriptive band text already in `classifiers_v2.CLASSIFIER_DEFINITIONS`.

23 classifiers now (Tab 03 of the corrected workbook), down from 35 in the
earlier, incorrect draft. Several previously-unsourced classifiers were
dropped for collinearity in the correction and no longer need a source at
all; a few genuinely have no real field anywhere in this deployment and are
declared `UNSOURCED_DEFAULT_BAND` here rather than fabricated — consistent
with the platform's own principle that an absent measure is a stated
absence, never a guessed one:

  - `bank_share_of_obligor_debt` — needs a credit-bureau feed of the
    obligor's total external debt; this deployment has none.
  - `sector_vulnerability_grade` — needs an internal sector scorecard;
    inventing a 1-5 grade with no analytical basis would be a fabrication,
    not a proxy, so it is left unsourced rather than guessed.
  - `supplier_replaceability` — needs an alternate-supplier count and
    switching-time field; not tracked anywhere in this deployment.
  - `guarantor_capacity` — needs the GUARANTOR's own rating to compare
    against the obligor's; `corporate_borrower_360` has guarantee exposure
    and links, but not a guarantor entity rating to compare with.

Two classifiers are genuinely computed, not merely looked up:

  - `supplier_concentration` and `receivable_concentration_by_counterparty`
    are derived from the real (if synthetic-demonstration) `corporate_supply_chain`
    graph edges — `buyer_cost_share_pct` summed over a borrower's top-3
    suppliers, and the largest single buyer's `supplier_revenue_share_pct`
    of a borrower's own revenue, respectively. Tab 03 marks both "Annual"
    update frequency, so they are computed once from the currently-active
    edges and held constant across the 15-month build, exactly as a real
    annual refresh cadence would behave.
  - `ebitda_margin_vs_sector` needs a cross-sectional sector median that
    isn't a per-row field — the build script computes it once per sector
    per period and merges it in as `sector_median_ebitda_margin` before
    this module bands the relative position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

UNSOURCED_DEFAULT_BAND = "MEDIUM"


def coerce(value, default: float | None = None) -> float | None:
    """Several corporate_borrower_360 fields carry an explicit
    "NOT_AVAILABLE" string sentinel (a declared absence, not a missing
    column) alongside genuine numeric rows — coerced to `default` rather
    than raising, so a real but sparsely-populated field still scores the
    rows it does have."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def banded(value: float, cutoffs: tuple[float, float, float, float], higher_is_worse: bool) -> str:
    """Map a numeric value to one of the five bands given four cutoffs
    (the boundaries between VERY_LOW/LOW, LOW/MEDIUM, MEDIUM/HIGH,
    HIGH/VERY_HIGH), in the direction the classifier actually runs."""
    c1, c2, c3, c4 = cutoffs
    if higher_is_worse:
        if value < c1:
            return "VERY_LOW"
        if value < c2:
            return "LOW"
        if value < c3:
            return "MEDIUM"
        if value < c4:
            return "HIGH"
        return "VERY_HIGH"
    else:
        if value > c1:
            return "VERY_LOW"
        if value > c2:
            return "LOW"
        if value > c3:
            return "MEDIUM"
        if value > c4:
            return "HIGH"
        return "VERY_HIGH"


def stage_band(stage: int, dpd: float) -> str:
    """Tab 03 #2. Cannot distinguish "Stage 1 low-risk" from "Stage 1 on
    watch" without a source field for the watch flag, so Stage 1 defaults
    to LOW (the more conservative of the two Stage-1 bands)."""
    if stage >= 3:
        return "VERY_HIGH"
    if stage == 2 and dpd >= 30:
        return "HIGH"
    if stage == 2:
        return "MEDIUM"
    return "LOW"


def country_band(country: str) -> str:
    """Tab 03 #17. This deployment's universe is single-jurisdiction (Saudi
    Arabia); a real sovereign-rating source would be needed to differentiate
    a multi-jurisdiction book. Defaulted LOW (AA-/A range) rather than
    VERY_LOW, since no sovereign rating feed actually backs this reading."""
    return "LOW"


def ebitda_margin_relative_band(margin_pct: float, sector_median_pct: float) -> str:
    """Tab 03 #8: bands are relative to the sector median, not absolute.
    Expressed as a ratio to the median so a thin-margin sector and a
    fat-margin sector are read the same way; a non-positive median falls
    back to a flat +/-10 percentage-point comparison since a ratio is not
    meaningful there."""
    if sector_median_pct is None or abs(sector_median_pct) < 0.5:
        diff = margin_pct - (sector_median_pct or 0.0)
        return banded(-diff, (25.0, 10.0, -10.0, -25.0), True)
    ratio = margin_pct / sector_median_pct
    return banded(-ratio, (-1.25, -1.10, -0.90, -0.75), True)


def obligor_profile_band(segment: str, tenure_years: float, restructure_flag: bool) -> str:
    """Tab 03 #18, merged in version 2 from borrower size/segment and
    relationship tenure — proxied against this deployment's actual segment
    labels (Large Corporate / Corporate-equivalent Mid Corporate / Financial
    Institution / Public Sector / Commercial), since the workbook's own
    wording (Large corporate / Corporate / Mid corporate / SME / Micro)
    doesn't map 1:1 onto them."""
    if restructure_flag:
        return "VERY_HIGH"
    base = {
        "Large Corporate": "VERY_LOW", "Financial Institution": "LOW",
        "Public Sector": "LOW", "Mid Corporate": "MEDIUM", "Commercial": "HIGH",
    }.get(segment, UNSOURCED_DEFAULT_BAND)
    if tenure_years is not None and tenure_years < 1.0:
        # A short relationship worsens by one band, floored at HIGH.
        order = ["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
        idx = min(order.index(base) + 1, order.index("HIGH"))
        return order[idx]
    return base


@dataclass(frozen=True)
class ClassifierSource:
    """How to compute one classifier's band this period, or that it cannot
    be computed from any real field this deployment has."""

    fields: tuple[str, ...]
    compute: Callable[..., str] | None  # None means UNSOURCED_DEFAULT_BAND


# ---------------------------------------------------------------------------
# One entry per classifier key (classifiers_v2.CLASSIFIER_DEFINITIONS).
# Keys not listed here score UNSOURCED_DEFAULT_BAND. `supplier_concentration`
# and `receivable_concentration_by_counterparty` read precomputed columns
# (`supplier_concentration_pct`, `receivable_concentration_pct`) that
# scripts/build_early_warning_v2.py merges in from the graph edges;
# `ebitda_margin_vs_sector` reads a precomputed `sector_median_ebitda_margin`.
# ---------------------------------------------------------------------------

SOURCES: dict[str, ClassifierSource] = {
    "pd_12m": ClassifierSource(
        ("pd_12m",), lambda v: banded(v, (0.15, 0.60, 3.0, 10.0), True)),
    "ifrs9_stage": ClassifierSource(
        ("stage", "current_dpd"), lambda s, d: stage_band(s, d)),
    "dpd_current": ClassifierSource(
        ("current_dpd",), lambda v: banded(v, (0.5, 7.5, 29.5, 89.5), True)),
    "dscr": ClassifierSource(
        ("dscr",), lambda v: banded(v, (2.00, 1.50, 1.25, 1.00), False)),
    "leverage_net_debt_ebitda": ClassifierSource(
        ("net_leverage",), lambda v: banded(v, (1.5, 3.0, 4.5, 6.0), True)),
    "quick_ratio": ClassifierSource(
        ("quick_ratio",), lambda v: banded(v, (1.50, 1.20, 0.90, 0.70), False)),
    "cash_conversion_cycle": ClassifierSource(
        ("cash_conversion_cycle_days",), lambda v: banded(v, (30, 60, 90, 150), True)),
    "ebitda_margin_vs_sector": ClassifierSource(
        ("ebitda_margin", "sector_median_ebitda_margin"),
        lambda m, s: ebitda_margin_relative_band(m, s)),
    "revenue_trend_3y_cagr": ClassifierSource(
        # Proxy: single-period revenue growth, not a true 3-year CAGR — no
        # multi-year revenue series exists in this snapshot to compute one.
        ("revenue_growth",), lambda v: banded(v, (10.0, 0.0, -5.0, -15.0), False)),
    "collateral_coverage_or_ltv": ClassifierSource(
        ("collateral_coverage_pct",), lambda v: banded(v, (150.0, 125.0, 100.0, 70.0), False)),
    "covenant_headroom": ClassifierSource(
        ("minimum_headroom_pct",),
        lambda v: banded(max(-100.0, min(200.0, v)), (30.0, 15.0, 5.0, 0.0), False)),
    "facility_utilisation_12m_avg": ClassifierSource(
        ("drawn_exposure", "total_limit"),
        lambda d, t: banded(100.0 * d / t if t else 0.0, (40.0, 60.0, 80.0, 95.0), True)),
    "connected_group_exposure_pct_tier1": ClassifierSource(
        ("group_utilisation_pct",),
        lambda v: banded(coerce(v, 0.0), (5.0, 10.0, 15.0, 20.0), True)),
    "financial_statement_quality_and_age": ClassifierSource(
        # Proxy: statement age only — auditor identity/opinion type is not a
        # field this snapshot carries.
        ("financial_statement_age_days",), lambda v: banded(v, (182, 365, 546, 730), True)),
    "country_jurisdiction_risk": ClassifierSource(
        ("country",), lambda c: country_band(c)),
    "obligor_profile": ClassifierSource(
        ("segment", "relationship_tenure_years", "restructure_flag"),
        lambda seg, ten, restr: obligor_profile_band(seg, ten, restr)),
    "supplier_concentration": ClassifierSource(
        ("supplier_concentration_pct",),
        lambda v: banded(coerce(v, 0.0), (20.0, 35.0, 50.0, 70.0), True)),
    "receivable_concentration_by_counterparty": ClassifierSource(
        ("receivable_concentration_pct",),
        lambda v: banded(coerce(v, 0.0), (10.0, 20.0, 35.0, 50.0), True)),
    "relationship_edge_confidence": ClassifierSource(
        ("graph_confidence",),
        # Inverted: HIGHER confidence is BETTER (lower risk band).
        lambda v: banded(coerce(v, 0.5), (0.90, 0.75, 0.50, 0.25), False)),
}

def negative_equity_flag(book_equity: float | None) -> bool:
    """Tab 03 Section C: gearing was dropped for collinearity in Tab 02;
    negative equity is retained as a Classifier-dimension override
    (`classifiers_v2.score_classifiers`'s `negative_equity` flag) rather
    than a per-classifier band, since gearing itself is no longer scored."""
    return book_equity is not None and book_equity < 0
