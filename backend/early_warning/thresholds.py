"""Numeric band boundaries for the classifiers that have a real source field
in `corporate_borrower_360` today, transcribed from the same Tab 2 cells
`classifiers_v2.py` uses — this module is the numeric-cutoff counterpart to
the descriptive band text already in `CLASSIFIER_DEFINITIONS`.

Not every classifier has a real source field yet (spec Section 6's lineage
gap): supplier/buyer concentration, project dependency, guarantor relative
strength, and the upstream-supply-chain classifiers have no CreditProbe
dataset today. Those are declared `UNSOURCED_DEFAULT_BAND` here rather than
fabricated — consistent with the existing taxonomy module's own principle
that "an absent measure is a stated absence" — and score at a neutral
MEDIUM band so they contribute their configured weight without asserting a
risk reading this deployment cannot support.
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


def rating_band(internal_rating_numeric: float) -> str:
    """Tab 2 #1: masterscale grade groups 1-3/4-5/6-7/8-9/10+."""
    if internal_rating_numeric <= 3:
        return "VERY_LOW"
    if internal_rating_numeric <= 5:
        return "LOW"
    if internal_rating_numeric <= 7:
        return "MEDIUM"
    if internal_rating_numeric <= 9:
        return "HIGH"
    return "VERY_HIGH"


def stage_band(stage: int, dpd: float) -> str:
    """Tab 2 #4. Cannot distinguish "Stage 1 low-risk exemption" from
    "Stage 1 on watch" without a source field for the exemption flag, so
    Stage 1 defaults to LOW (the more conservative of the two Stage-1 bands)."""
    if stage >= 3:
        return "VERY_HIGH"
    if stage == 2 and dpd >= 30:
        return "HIGH"
    if stage == 2:
        return "MEDIUM"
    return "LOW"


def segment_band(segment: str) -> str:
    """Tab 2 #24, proxied against this deployment's actual segment labels
    (Large Corporate / Mid Corporate / Financial Institution / Commercial /
    Public Sector) rather than the workbook's own wording (Large corporate /
    Corporate / Mid corporate / SME / Micro), since the two vocabularies
    don't line up 1:1. Financial Institution and Public Sector are treated
    as institutionally-backed (lower band) rather than guessed at as SME."""
    mapping = {
        "Large Corporate": "VERY_LOW",
        "Financial Institution": "LOW",
        "Public Sector": "LOW",
        "Mid Corporate": "MEDIUM",
        "Commercial": "HIGH",
    }
    return mapping.get(segment, UNSOURCED_DEFAULT_BAND)


def country_band(country: str) -> str:
    """Tab 2 #26. This deployment's universe is single-jurisdiction (Saudi
    Arabia); a real sovereign-rating source would be needed to differentiate
    a multi-jurisdiction book. Defaulted LOW (AA-/A range) rather than
    VERY_LOW, since no sovereign rating feed actually backs this reading."""
    return "LOW"


@dataclass(frozen=True)
class ClassifierSource:
    """How to compute one classifier's band this period, or that it cannot
    be computed from any real field this deployment has."""

    fields: tuple[str, ...]
    compute: Callable[..., str] | None  # None means UNSOURCED_DEFAULT_BAND


# ---------------------------------------------------------------------------
# One entry per classifier key (classifiers_v2.CLASSIFIER_DEFINITIONS).
# Fields not listed here score UNSOURCED_DEFAULT_BAND.
# ---------------------------------------------------------------------------

SOURCES: dict[str, ClassifierSource] = {
    "internal_rating_level": ClassifierSource(
        ("internal_rating_numeric",), lambda r: rating_band(r)),
    "pd_12m_level": ClassifierSource(
        ("pd_12m",), lambda v: banded(v, (0.15, 0.60, 3.0, 10.0), True)),
    "ifrs9_stage": ClassifierSource(
        ("stage", "current_dpd"), lambda s, d: stage_band(s, d)),
    "ecl_coverage": ClassifierSource(
        ("ecl_coverage",), lambda v: banded(v, (0.25, 1.0, 5.0, 20.0), True)),
    "days_past_due_current": ClassifierSource(
        ("current_dpd",), lambda v: banded(v, (0.5, 7.5, 29.5, 89.5), True)),
    "dscr": ClassifierSource(
        ("dscr",), lambda v: banded(v, (2.00, 1.50, 1.25, 1.00), False)),
    "interest_coverage_ebit_interest": ClassifierSource(
        ("interest_coverage",), lambda v: banded(v, (6.50, 4.25, 2.50, 1.50), False)),
    "leverage_net_debt_ebitda": ClassifierSource(
        ("net_leverage",), lambda v: banded(v, (1.5, 3.0, 4.5, 6.0), True)),
    "gearing_total_debt_equity": ClassifierSource(
        ("debt_to_equity",), lambda v: banded(v, (0.50, 1.00, 2.00, 3.00), True)),
    "current_ratio": ClassifierSource(
        ("current_ratio",), lambda v: banded(v, (2.00, 1.50, 1.20, 1.00), False)),
    "quick_ratio": ClassifierSource(
        ("quick_ratio",), lambda v: banded(v, (1.50, 1.20, 0.90, 0.70), False)),
    "cash_conversion_cycle": ClassifierSource(
        ("cash_conversion_cycle_days",), lambda v: banded(v, (30, 60, 90, 150), True)),
    "revenue_trend_3y_cagr": ClassifierSource(
        # Proxy: single-period revenue growth, not a true 3-year CAGR — no
        # multi-year revenue series exists in this snapshot to compute one.
        ("revenue_growth",), lambda v: banded(v, (10.0, 0.0, -5.0, -15.0), False)),
    "collateral_coverage": ClassifierSource(
        ("collateral_coverage_pct",), lambda v: banded(v, (150.0, 125.0, 100.0, 70.0), False)),
    "covenant_headroom": ClassifierSource(
        ("minimum_headroom_pct",),
        lambda v: banded(max(-100.0, min(200.0, v)), (30.0, 15.0, 5.0, 0.0), False)),
    "facility_utilisation_12m_avg": ClassifierSource(
        ("drawn_exposure", "total_limit"),
        lambda d, t: banded(100.0 * d / t if t else 0.0, (40.0, 60.0, 80.0, 95.0), True)),
    "unsecured_share_of_exposure": ClassifierSource(
        ("collateral_eligible_value", "drawn_exposure"),
        lambda c, d: banded(100.0 * max(0.0, 1.0 - (c / d if d else 0.0)),
                             (10.0, 30.0, 50.0, 75.0), True)),
    "single_name_exposure_pct_tier1": ClassifierSource(
        ("single_name_utilisation_pct",), lambda v: banded(v, (2.5, 5.0, 10.0, 15.0), True)),
    "group_connected_exposure_pct_tier1": ClassifierSource(
        ("group_utilisation_pct",),
        lambda v: banded(coerce(v, 0.0), (5.0, 10.0, 15.0, 20.0), True)),
    "borrower_size_segment": ClassifierSource(
        ("segment",), lambda s: segment_band(s)),
    "financial_statement_quality": ClassifierSource(
        # Proxy: statement age only — auditor identity/opinion type is not a
        # field this snapshot carries.
        ("financial_statement_age_days",), lambda v: banded(v, (182, 365, 546, 730), True)),
    "country_jurisdiction_risk": ClassifierSource(
        ("country",), lambda c: country_band(c)),
    "relationship_edge_confidence": ClassifierSource(
        ("graph_confidence",),
        # Inverted: HIGHER confidence is BETTER (lower risk band).
        lambda v: banded(coerce(v, 0.5), (0.90, 0.75, 0.50, 0.25), False)),
}

#: Overrides evaluated on top of the band computed above (Tab 2 Section C).
#: Returns the forced/floored band, or None if the override does not apply.
def classifier_overrides(row: dict) -> dict[str, str]:
    forced: dict[str, str] = {}
    if row.get("book_equity", 1.0) is not None and row.get("book_equity", 1.0) < 0:
        forced["gearing_total_debt_equity"] = "VERY_HIGH"
    return forced
