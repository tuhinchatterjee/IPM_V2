"""
The small deterministic ECL oracle. Playbook §14.

A tiny, self-contained scenario-weighted ECL fixture, deliberately separate from
the real and demonstration portfolios, whose only job is to be the single place
a cross-file reconciliation test can point at. Six figures are DECLARED here —
the exposures, the three scenario ECLs and the scenario weights. Everything
else, including the weighted ECL, its movement, the percentage change and the
coverage ratios, is DERIVED by `backend.playbook.calc`.

Why nothing derived is written down
-----------------------------------
The specification's failure mode is a demonstration in which the chat says
+8.95%, the Word file says +8.9%, the deck rounds to +9% and the workbook still
carries last week's +7.4% — four numbers, four hand-maintained copies, and no
way to tell which one somebody forgot. Deriving them all from one fixture in
code means the four artefacts cannot disagree, because there is only one figure.

The scenario ordering is economically coherent on purpose: upturn below base
below downturn, in both periods. That matters because the discrepancy detector
is supposed to flag an ordering that is not, and a fixture that quietly violated
it would make the detector look broken.

This is synthetic. It is not a portfolio, it is an arithmetic test case.
"""

from __future__ import annotations

from decimal import Decimal

from backend.playbook import calc
from backend.playbook.calc import Calculation, Input

FIXTURE_ID = "playbook-ecl-oracle"
FIXTURE_VERSION = "1.0.0"

CURRENCY = "SAR"
SCALE = "million"

PRIOR_PERIOD = "Q1 2026"
CURRENT_PERIOD = "Q2 2026"

#: The declared inputs. Everything else in this module is computed from these.
DECLARED: dict[str, dict[str, str]] = {
    "exposure": {"prior": "1000.00", "current": "1050.00"},
    "base_ecl": {"prior": "18.00", "current": "19.20"},
    "upturn_ecl": {"prior": "14.00", "current": "15.00"},
    "downturn_ecl": {"prior": "32.00", "current": "36.00"},
}

#: Scenario weights, unchanged between the two periods. Declared as a mapping so
#: the weighted calculation reads in the same order it is documented in.
WEIGHTS: dict[str, str] = {"base": "0.60", "upturn": "0.15", "downturn": "0.25"}

_LOCATOR = f"fixture://{FIXTURE_ID}@{FIXTURE_VERSION}"


def _money(name: str, value: str, period: str) -> Input:
    return Input(
        name=f"{name} ({period})",
        value=Decimal(value),
        unit=calc.CURRENCY,
        scale=SCALE,
        locator=f"{_LOCATOR}#{name}.{period}",
        origin="methodology",
    )


def _weight(scenario: str) -> Input:
    return Input(
        name=f"{scenario} weight",
        value=Decimal(WEIGHTS[scenario]),
        unit=calc.RATIO,
        locator=f"{_LOCATOR}#weight.{scenario}",
        origin="methodology",
    )


def exposure(period: str) -> Input:
    return _money("exposure", DECLARED["exposure"][period], period)


def scenario_ecl(scenario: str, period: str) -> Input:
    return _money(f"{scenario}_ecl", DECLARED[f"{scenario}_ecl"][period], period)


def weights() -> list[Input]:
    return [_weight("base"), _weight("upturn"), _weight("downturn")]


def weighted_ecl(period: str) -> Calculation:
    """Probability-weighted ECL for one period, recomputed from the fixture.

    `calc.weighted` refuses a weight set that does not sum to one, so this is
    also the test that the declared weights are complete.
    """
    components = [scenario_ecl(s, period) for s in ("base", "upturn", "downturn")]
    return calc.weighted(
        components, weights(), name=f"weighted ECL ({period})", dp=2
    )


def coverage_ratio(period: str) -> Calculation:
    """Weighted ECL over exposure, as a percentage, with its denominator named."""
    w = weighted_ecl(period)
    return calc.ratio(
        Input(
            name=w.name,
            value=w.value,
            unit=calc.CURRENCY,
            scale=SCALE,
            locator=f"{_LOCATOR}#weighted_ecl.{period}",
            origin="derived",
        ),
        exposure(period),
        name=f"coverage ratio ({period})",
        dp=2,
    )


def _as_input(c: Calculation, locator_suffix: str) -> Input:
    return Input(
        name=c.name,
        value=c.value,
        unit=c.unit,
        scale=c.scale,
        locator=f"{_LOCATOR}#{locator_suffix}",
        origin="derived",
    )


def weighted_ecl_movement() -> Calculation:
    """Absolute movement in weighted ECL, in SAR million."""
    return calc.delta(
        _as_input(weighted_ecl("prior"), "weighted_ecl.prior"),
        _as_input(weighted_ecl("current"), "weighted_ecl.current"),
        name="weighted ECL movement",
    )


def weighted_ecl_percent_change() -> Calculation:
    """Relative movement in weighted ECL, as a percent of the prior period."""
    return calc.percent_change(
        _as_input(weighted_ecl("prior"), "weighted_ecl.prior"),
        _as_input(weighted_ecl("current"), "weighted_ecl.current"),
        name="weighted ECL change",
    )


def coverage_movement_bps() -> Calculation:
    """Coverage movement in basis points — not percent, and not the same number."""
    return calc.bps_change(
        _as_input(coverage_ratio("prior"), "coverage.prior"),
        _as_input(coverage_ratio("current"), "coverage.current"),
        name="coverage movement",
    )


def exposure_movement() -> Calculation:
    return calc.delta(
        exposure("prior"), exposure("current"), name="exposure movement"
    )


def headline() -> dict[str, Calculation]:
    """Every derived figure the demonstration is allowed to quote.

    Chat, Word, PDF, PowerPoint and the workbook all read this one mapping, so
    the four artefacts cannot disagree with each other or with the analysis.
    """
    return {
        "weighted_ecl_prior": weighted_ecl("prior"),
        "weighted_ecl_current": weighted_ecl("current"),
        "weighted_ecl_movement": weighted_ecl_movement(),
        "weighted_ecl_percent_change": weighted_ecl_percent_change(),
        "coverage_prior": coverage_ratio("prior"),
        "coverage_current": coverage_ratio("current"),
        "coverage_movement_bps": coverage_movement_bps(),
        "exposure_movement": exposure_movement(),
    }


def scenario_ordering_is_coherent(period: str) -> bool:
    """Upturn ≤ base ≤ downturn, which the authoritative fixture must satisfy.

    Exposed so the discrepancy detector can be tested against a fixture that is
    coherent and a separate one that deliberately is not.
    """
    up = scenario_ecl("upturn", period).value
    base = scenario_ecl("base", period).value
    down = scenario_ecl("downturn", period).value
    return up <= base <= down
