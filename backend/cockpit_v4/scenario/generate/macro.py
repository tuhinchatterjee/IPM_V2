"""The twenty-factor registry, and the macro panel the books are built from.

Section 7.1 gives a candidate coverage dictionary of twenty macroeconomic
variables and is careful about what it is: *"not a claim that these are the
statistically established top twenty drivers or that every series is
present."* This module implements exactly that reading. Twenty candidates are
declared; each book carries the subset the release actually generates; the
rest are ABSENT with a reason, and an absent factor never becomes a zero
sensitivity.

**The paths are generated, not observed.** Every value here is SYNTHETIC_DEMO.
They are built from a shared latent cycle plus factor-specific loadings and
mean reversion, which gives them two properties the specification cares
about:

* they **co-move**, so section 7.3's warning that "co-movement among twenty
  MEVs must not produce spurious certainty about twenty independent effects"
  is a live condition in this data rather than a sentence in a document; and
* they have a **direction** that the risk parameters are then generated from,
  so a fitted sensitivity is recovering a relationship that is there.

**Native units are preserved.** A growth rate is a growth rate: MEV01 is
year-on-year real GDP growth in percent, and the quarter-to-quarter change in
that series is a change in a growth rate, not "quarterly growth". Section 7.2
makes that distinction and `native_unit` plus `shock_convention` are where it
is kept.

**Vintages are recorded.** Each observation carries `observation_status`,
`published_at` and `available_at`. A value published two months after the
period it describes was not available to a process running at the time, and
section 7.2 forbids treating a later revision as a known-at-the-time input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario.candidate_schema import SCENARIOS
from backend.cockpit_v4.scenario.generate import stable, unit_interval

#: Shock conventions, spelled the way section 5.1 spells them. A factor's
#: convention decides what "+20" means to it, and reading one as another is
#: the error the whole quantity algebra exists to stop.
PERCENTAGE_POINTS = "percentage_points"
BASIS_POINTS = "basis_points"
RELATIVE_PERCENT = "relative_percent"
INDEX_POINTS = "index_points"
NATIVE_UNITS = "native_units"


@dataclass(frozen=True)
class Factor:
    """One candidate macroeconomic variable."""

    factor_id: str
    name: str
    native_level: str
    shock_convention: str
    native_unit: str
    native_frequency: str
    #: Where the series sits in the long run, and how far it wanders.
    level: float
    amplitude: float
    #: How hard the shared cycle pulls this factor, and in which direction.
    #: A positive loading means the factor RISES when conditions worsen.
    loading: float
    #: How much of last period survives into this one.
    persistence: float
    #: Months between the period ending and the value being published.
    publication_lag_months: int
    #: How the series is reduced when a monthly book reads a quarterly
    #: series, or the reverse. Section 7.2 wants the rule recorded, not
    #: assumed.
    aggregation_rule: str


#: Section 7.1's twenty candidates, in its order. The levels and amplitudes
#: are chosen to be plausible for a Gulf economy and are not calibrated to
#: any real series; they are generator parameters, published here so that
#: anything fitted to them can be checked against what produced them.
FACTORS: tuple[Factor, ...] = (
    Factor("MEV01", "Real GDP growth",
           "year-on-year growth in real gross domestic product",
           PERCENTAGE_POINTS, "percent", "quarterly",
           level=3.2, amplitude=2.6, loading=-1.00, persistence=0.62,
           publication_lag_months=2, aggregation_rule="mean"),
    Factor("MEV02", "Non-oil real GDP growth",
           "year-on-year growth in real non-oil gross domestic product",
           PERCENTAGE_POINTS, "percent", "quarterly",
           level=4.1, amplitude=2.2, loading=-0.86, persistence=0.60,
           publication_lag_months=2, aggregation_rule="mean"),
    Factor("MEV03", "Unemployment rate",
           "unemployment as a percent of the labour force",
           PERCENTAGE_POINTS, "percent", "quarterly",
           level=6.0, amplitude=1.4, loading=0.95, persistence=0.78,
           publication_lag_months=1, aggregation_rule="period_end"),
    Factor("MEV04", "CPI inflation",
           "year-on-year change in the consumer price index",
           PERCENTAGE_POINTS, "percent", "monthly",
           level=2.4, amplitude=1.5, loading=0.42, persistence=0.70,
           publication_lag_months=1, aggregation_rule="mean"),
    Factor("MEV05", "Policy interest rate", "policy rate, percent per year",
           BASIS_POINTS, "percent", "monthly",
           level=5.25, amplitude=1.6, loading=0.55, persistence=0.88,
           publication_lag_months=0, aggregation_rule="period_end"),
    Factor("MEV06", "Three-month interbank rate",
           "three-month interbank offered rate, percent per year",
           BASIS_POINTS, "percent", "monthly",
           level=5.55, amplitude=1.7, loading=0.61, persistence=0.86,
           publication_lag_months=0, aggregation_rule="period_end"),
    Factor("MEV07", "Oil price", "benchmark crude, USD per barrel",
           RELATIVE_PERCENT, "index", "monthly",
           level=82.0, amplitude=19.0, loading=-0.92, persistence=0.74,
           publication_lag_months=0, aggregation_rule="mean"),
    Factor("MEV08", "Oil production", "crude production index, 2021 = 100",
           RELATIVE_PERCENT, "index", "monthly",
           level=100.0, amplitude=7.5, loading=-0.55, persistence=0.80,
           publication_lag_months=1, aggregation_rule="mean"),
    Factor("MEV09", "Residential property price index",
           "residential property prices, 2021 = 100",
           INDEX_POINTS, "index", "quarterly",
           level=112.0, amplitude=9.0, loading=-0.70, persistence=0.85,
           publication_lag_months=2, aggregation_rule="period_end"),
    Factor("MEV10", "Commercial property price index",
           "commercial property prices, 2021 = 100",
           INDEX_POINTS, "index", "quarterly",
           level=104.0, amplitude=11.0, loading=-0.81, persistence=0.83,
           publication_lag_months=2, aggregation_rule="period_end"),
    Factor("MEV11", "Equity market index", "main market index, 2021 = 100",
           RELATIVE_PERCENT, "index", "monthly",
           level=118.0, amplitude=16.0, loading=-0.78, persistence=0.66,
           publication_lag_months=0, aggregation_rule="period_end"),
    Factor("MEV12", "Nominal effective exchange rate",
           "nominal effective exchange rate, 2021 = 100; higher is stronger",
           INDEX_POINTS, "index", "monthly",
           level=100.0, amplitude=3.4, loading=0.30, persistence=0.75,
           publication_lag_months=0, aggregation_rule="mean"),
    Factor("MEV13", "Private-sector credit growth",
           "year-on-year growth in credit to the private sector",
           PERCENTAGE_POINTS, "percent", "monthly",
           level=7.8, amplitude=3.1, loading=-0.74, persistence=0.72,
           publication_lag_months=2, aggregation_rule="mean"),
    Factor("MEV14", "Household disposable-income growth",
           "year-on-year growth in nominal household disposable income",
           PERCENTAGE_POINTS, "percent", "quarterly",
           level=3.6, amplitude=2.0, loading=-0.88, persistence=0.64,
           publication_lag_months=3, aggregation_rule="mean"),
    Factor("MEV15", "Real wage growth",
           "year-on-year growth in real wages",
           PERCENTAGE_POINTS, "percent", "quarterly",
           level=1.9, amplitude=1.8, loading=-0.79, persistence=0.68,
           publication_lag_months=3, aggregation_rule="mean"),
    Factor("MEV16", "Retail sales growth",
           "year-on-year growth in retail sales value",
           PERCENTAGE_POINTS, "percent", "monthly",
           level=4.4, amplitude=3.3, loading=-0.83, persistence=0.58,
           publication_lag_months=1, aggregation_rule="sum"),
    Factor("MEV17", "Industrial production growth",
           "year-on-year growth in the industrial production index",
           PERCENTAGE_POINTS, "percent", "monthly",
           level=2.7, amplitude=3.6, loading=-0.80, persistence=0.60,
           publication_lag_months=2, aggregation_rule="mean"),
    Factor("MEV18", "Housing transaction activity",
           "housing transaction volume index, 2021 = 100",
           RELATIVE_PERCENT, "index", "monthly",
           level=100.0, amplitude=14.0, loading=-0.72, persistence=0.55,
           publication_lag_months=1, aggregation_rule="sum"),
    Factor("MEV19", "Business confidence (PMI)",
           "purchasing managers' index; 50 is the expansion threshold. An "
           "index, not a probability.",
           INDEX_POINTS, "index", "monthly",
           level=55.0, amplitude=4.5, loading=-0.90, persistence=0.52,
           publication_lag_months=0, aggregation_rule="mean"),
    Factor("MEV20", "Consumer confidence",
           "consumer confidence index, 2021 = 100",
           INDEX_POINTS, "index", "monthly",
           level=98.0, amplitude=8.0, loading=-0.87, persistence=0.57,
           publication_lag_months=0, aggregation_rule="mean"),
)

BY_ID: dict[str, Factor] = {f.factor_id: f for f in FACTORS}

#: Which factors each book's release actually generates a series for.
#:
#: Deliberately different, and deliberately not all twenty. A corporate book
#: that tracks oil production and industrial output does not necessarily
#: track household disposable income, and a retail book is the other way
#: round. Section 7.1: *"Map these candidates to actual series, record
#: unavailable entries."* Four absent in one book and six in the other is
#: what that instruction looks like when it is obeyed rather than quoted.
PRESENT: dict[str, frozenset[str]] = {
    dom.CORPORATE: frozenset({
        "MEV01", "MEV02", "MEV03", "MEV04", "MEV05", "MEV06", "MEV07",
        "MEV08", "MEV09", "MEV10", "MEV11", "MEV12", "MEV13", "MEV15",
        "MEV17", "MEV19"}),
    dom.RETAIL: frozenset({
        "MEV01", "MEV03", "MEV04", "MEV05", "MEV06", "MEV09", "MEV11",
        "MEV12", "MEV14", "MEV15", "MEV16", "MEV18", "MEV19", "MEV20"}),
}

#: Why a factor a book does not carry is absent. One sentence each, because
#: "UNAVAILABLE" with no reason is the same as a shrug.
ABSENT_REASON: dict[str, str] = {
    "MEV02": "This release publishes only the headline GDP series for the "
             "Retail book; the non-oil split is not generated for it.",
    "MEV07": "Oil is generated as a corporate-book driver. The Retail book "
             "has no series for it and none is imputed from the headline.",
    "MEV08": "Production volumes are generated for the corporate book only.",
    "MEV10": "Commercial property is a corporate-book series. Residential "
             "property (MEV09) is the Retail book's property factor and is "
             "not a substitute for it.",
    "MEV13": "Aggregate private-sector credit growth is generated for the "
             "corporate book only.",
    "MEV14": "Household income is generated as a retail-book driver and has "
             "no corporate series in this release.",
    "MEV16": "Retail sales are generated as a retail-book driver.",
    "MEV17": "Industrial production is generated as a corporate-book driver.",
    "MEV18": "Housing transaction activity is generated as a retail-book "
             "driver.",
    "MEV20": "Consumer confidence is generated as a retail-book driver. "
             "Business confidence (MEV19) is the corporate equivalent and "
             "measures something else.",
}

#: How the shared cycle differs by scenario. A downside is a worse cycle for
#: longer; an upside is a milder one. The three are the SAME generated path
#: under different amplitudes, which is why a scenario-weighted ECL is an
#: expectation over one economy rather than an average of three unrelated
#: ones.
SCENARIO_TILT: dict[str, float] = {
    "baseline": 0.0, "downside": 1.25, "upside": -0.60}

#: How far the latent cycle swings. Larger than any single factor's own
#: noise, so the factors move together.
CYCLE_AMPLITUDE = 1.0


def cycle(periods: tuple[str, ...], scenario: str, *, book: str) -> list[float]:
    """The shared latent cycle: one number per period, roughly in [-1, 1].

    A deterministic wave plus a repeatable wobble, tilted by the scenario.
    Positive means conditions are worsening, which is the sign convention
    every factor's `loading` is written against.
    """
    tilt = SCENARIO_TILT[scenario]
    out: list[float] = []
    previous = 0.0
    for index, period in enumerate(periods):
        wave = math.sin(2.0 * math.pi * index / max(len(periods) - 1, 1))
        wobble = (unit_interval(f"{book}|cycle|{period}") - 0.5) * 0.55
        value = 0.55 * previous + 0.45 * (wave + wobble)
        previous = value
        # The tilt grows through the window: a downside scenario is not a
        # level shift, it is a path that deteriorates.
        ramp = index / max(len(periods) - 1, 1)
        out.append(CYCLE_AMPLITUDE * value + tilt * (0.35 + 0.65 * ramp))
    return out


def path(factor: Factor, periods: tuple[str, ...], scenario: str, *,
         book: str) -> list[float]:
    """One factor's generated series, in its own native unit.

    The factor follows the cycle through its loading, keeps some of its own
    previous value through its persistence, and carries a small repeatable
    idiosyncratic term so that two factors with the same loading are not the
    same series.
    """
    shared = cycle(periods, scenario, book=book)
    out: list[float] = []
    previous = factor.level
    for index, period in enumerate(periods):
        idiosyncratic = (
            unit_interval(f"{book}|{factor.factor_id}|{scenario}|{period}")
            - 0.5) * factor.amplitude * 0.32
        pull = factor.level + factor.loading * factor.amplitude * shared[index]
        value = (factor.persistence * previous
                 + (1.0 - factor.persistence) * pull + idiosyncratic)
        previous = value
        out.append(round(value, 4))
    return out


def _published(period: str, lag_months: int, *, quarterly: bool) -> str:
    """When a value for this period was published, as a YYYY-MM string."""
    if quarterly:
        year, quarter = int(period[:4]), int(period[-1])
        month = quarter * 3  # the quarter's last month
    else:
        year, month = (int(p) for p in period.split("-"))
    total = year * 12 + (month - 1) + lag_months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def panel(domain_id: str, periods: tuple[str, ...]) -> list[dict[str, object]]:
    """Every generated observation for a book: factor x period x scenario.

    Only the factors this book carries. An absent factor produces no rows at
    all, rather than rows of zero -- section 7.1's *"Never present missing
    factors as zero"* is enforced by there being nothing to read.
    """
    domain_id = dom.parse(domain_id)
    quarterly = domain_id == dom.CORPORATE
    rows: list[dict[str, object]] = []
    for factor in FACTORS:
        if factor.factor_id not in PRESENT[domain_id]:
            continue
        for scenario_id, _name, _weight in SCENARIOS:
            values = path(factor, periods, scenario_id, book=domain_id)
            for period, value in zip(periods, values, strict=True):
                published = _published(period, factor.publication_lag_months,
                                       quarterly=quarterly)
                # The last two periods of a downside or upside path are a
                # projection, not an observation: a scenario's future is a
                # forecast and saying otherwise would make a generated path
                # look like history.
                forecast = (scenario_id != "baseline"
                            and period in periods[-2:])
                rows.append({
                    "factor_id": factor.factor_id,
                    "period": period,
                    "scenario_id": scenario_id,
                    "country_or_region": "SA",
                    "value": value,
                    "native_unit": factor.native_unit,
                    "native_frequency": factor.native_frequency,
                    "aggregation_rule": factor.aggregation_rule,
                    "observation_status": (
                        "FORECAST" if forecast else "ACTUAL"),
                    "forecast_vintage": (
                        f"{published}-v1" if forecast else ""),
                    "published_at": published,
                    "available_at": published,
                })
    return rows


def registry(domain_id: str) -> list[dict[str, object]]:
    """All twenty candidates, with this book's support status for each."""
    domain_id = dom.parse(domain_id)
    present = PRESENT[domain_id]
    out: list[dict[str, object]] = []
    for factor in FACTORS:
        carried = factor.factor_id in present
        out.append({
            "factor_id": factor.factor_id,
            "factor_name": factor.name,
            "native_level": factor.native_level,
            "shock_convention": factor.shock_convention,
            "native_unit": factor.native_unit,
            "geography": "SA",
            "native_frequency": factor.native_frequency,
            "series_id": (f"{domain_id}.{factor.factor_id}" if carried
                          else ""),
            "availability": "PRESENT" if carried else "ABSENT",
            "absent_reason": ("" if carried else ABSENT_REASON.get(
                factor.factor_id,
                "This release generates no series for this factor.")),
        })
    return out


def series(domain_id: str, factor_id: str, periods: tuple[str, ...],
           scenario: str = "baseline") -> dict[str, float]:
    """One factor's baseline path as `{period: value}`, for a fitter.

    Raises for a factor this book does not carry, rather than returning
    zeros. A zero series fits a zero coefficient, and a zero coefficient
    reads as "no effect" rather than "no data" (section 7.1).
    """
    domain_id = dom.parse(domain_id)
    if factor_id not in PRESENT[domain_id]:
        raise KeyError(
            f"{factor_id} has no series in the {domain_id} candidate release. "
            f"{ABSENT_REASON.get(factor_id, '')} It is ABSENT, which is not "
            f"the same as a sensitivity of zero.")
    values = path(BY_ID[factor_id], periods, scenario, book=domain_id)
    return dict(zip(periods, values, strict=True))


def driver_index(domain_id: str, periods: tuple[str, ...],
                 scenario: str = "baseline") -> dict[str, float]:
    """The single number the books' risk parameters are generated from.

    This is the cycle itself, not a factor: the books are built so that
    conditions drive PD and LGD, and the twenty observable factors are
    different windows onto those conditions. A fitter that recovers a
    sensitivity to unemployment is recovering unemployment's share of this,
    which is exactly what a real sensitivity is and exactly why section 7.3
    says co-movement must not be read as twenty independent effects.
    """
    values = cycle(periods, scenario, book=dom.parse(domain_id))
    return dict(zip(periods, values, strict=True))


def factor_count(domain_id: str) -> tuple[int, int]:
    """(present, absent) for this book. Used by the registry's own tests."""
    present = len(PRESENT[dom.parse(domain_id)])
    return present, len(FACTORS) - present


def _unused_stable_guard() -> int:  # pragma: no cover - import-time contract
    """`stable` is imported for `unit_interval`; this keeps the link visible."""
    return stable("guard", 2)


__all__ = ["ABSENT_REASON", "BASIS_POINTS", "BY_ID", "CYCLE_AMPLITUDE",
           "FACTORS", "Factor", "INDEX_POINTS", "NATIVE_UNITS",
           "PERCENTAGE_POINTS", "PRESENT", "RELATIVE_PERCENT",
           "SCENARIO_TILT", "cycle", "driver_index", "factor_count", "panel",
           "path", "registry", "series"]
