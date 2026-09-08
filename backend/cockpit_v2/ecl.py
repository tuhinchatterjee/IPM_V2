"""
The governed ECL calculator. Brief §4.3.

This module is the only place in Cockpit V2 that turns credit parameters into
an expected credit loss. Every figure the Cockpit reports, and every factor
contribution it attributes, is produced by calling into here — including the
attribution engine, which evaluates opening/closing parameter combinations
through this same code rather than through a parallel approximation. That is
what makes a factor bridge reconcile by construction instead of by a plug.

The measurement, stated plainly
-------------------------------
A facility is measured over a window of future periods on a quarterly grid.
For each period ``t`` in that window and each scenario ``s``:

* ``h[t]``  is the CONDITIONAL default hazard — the probability of defaulting
  in period ``t`` given survival to the end of period ``t-1``;
* ``S[t] = S[t-1] * (1 - h[t])`` is survival, with ``S[0] = 1``;
* ``m[t] = S[t-1] * h[t]`` is the MARGINAL default probability;
* ``ead[t]`` is exposure at default were default to occur in ``t``;
* ``lgd[t]`` is loss severity given default in ``t`` — already net of expected
  recoveries and of the cost and timing of realising them;
* ``df[t]`` discounts the loss back to the reporting date at the effective
  interest rate.

Then

    scenario_ecl = sum over t of  m[t] * ead[t] * lgd[t] * df[t]
    weighted_model_ecl = sum over s of  weight[s] * scenario_ecl[s]
    reported_ecl = weighted_model_ecl + separately_identified_overlay

Three things this deliberately does NOT do
------------------------------------------
* It does not multiply an annual PD by a number of years to get a lifetime PD.
  A cumulative PD is a sum of marginals over the window, and the marginals come
  from the survival recursion above.
* It does not discount recoveries twice. ``lgd[t]`` is a severity expressed at
  the default date, and the only discounting applied to it is ``df[t]``, from
  the default date back to the reporting date. Where a recovery is expected to
  arrive later than the default, that lag is carried inside the severity by
  ``severity_from_recovery`` below, which says so.
* It does not reuse the performing formula for a credit-impaired account. A
  Stage 3 facility is measured by ``impaired_measurement``, which is the cash
  shortfall on an account that has already defaulted, and it is labelled
  ``METHOD_IMPAIRED_CASH_SHORTFALL`` wherever it is reported.

Twelve-month versus lifetime is a restriction on the DEFAULT WINDOW, not on the
recovery cash flows: a default that happens in month nine may still be recovered
in year three, and ``lgd``/``df`` carry that.

Limitations, stated rather than implied
---------------------------------------
This is a general-approach demonstration implementation. It does NOT cover
purchased or originated credit-impaired assets (POCI), the simplified approach
for trade receivables, modification and derecognition accounting, or any
instrument-specific treatment. It is not IFRS 9 compliant, has not been
validated, and no parameter in it is calibrated to anything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from backend.cockpit_v2 import MODEL_VERSION

#: Periods per year on the measurement grid. Quarterly, because the demo data
#: is quarterly and a twelve-month window then falls exactly on a boundary.
PERIODS_PER_YEAR = 4

#: The twelve-month measurement window, in periods of the grid above.
TWELVE_MONTH_PERIODS = PERIODS_PER_YEAR

#: The longest lifetime window measured, in periods. A cap rather than a
#: modelling claim: it keeps a thirty-year facility from making the attribution
#: engine quadratic, and it is reported as a limitation when it binds.
MAX_LIFETIME_PERIODS = 40

#: How close a set of scenario weights must come to one.
WEIGHT_TOLERANCE = 1e-9

#: Reconciliation tolerance for the attribution bridge, in currency units.
RECONCILIATION_TOLERANCE = 1e-6

METHOD_PERFORMING = "METHOD_PERFORMING_COMPONENT"
METHOD_IMPAIRED = "METHOD_IMPAIRED_CASH_SHORTFALL"

STAGE_1 = 1
STAGE_2 = 2
STAGE_3 = 3


class EclInputError(ValueError):
    """An input the calculator refuses rather than silently repairs."""


# ------------------------------------------------------------------ helpers


def survival_and_marginals(
    hazard: Sequence[float], periods: int
) -> tuple[list[float], list[float]]:
    """Survival and marginal default probability over the first `periods`.

    Returns ``(survival, marginal)`` where ``survival[t]`` is the probability
    of not having defaulted by the END of period ``t`` and ``marginal[t]`` is
    the probability of defaulting IN period ``t``.

    This is the identity the whole module rests on, so it is a function with a
    name rather than three lines repeated in four places.
    """
    periods = max(0, min(int(periods), len(hazard)))
    survival: list[float] = []
    marginal: list[float] = []
    alive = 1.0
    for t in range(periods):
        h = float(hazard[t])
        if not 0.0 <= h <= 1.0:
            raise EclInputError(
                f"a conditional default hazard must lie in [0, 1]; period "
                f"{t + 1} carries {h!r}")
        marginal.append(alive * h)
        alive *= 1.0 - h
        survival.append(alive)
    return survival, marginal


def cumulative_pd(hazard: Sequence[float], periods: int) -> float:
    """Cumulative probability of default over the window. Never `pd * years`."""
    _, marginal = survival_and_marginals(hazard, periods)
    return float(sum(marginal))


def annual_pd_to_hazard(annual_pd: float,
                        periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """The constant per-period hazard implied by a twelve-month PD.

    ``1 - (1 - pd)**(1/n)``. Inverting the survival identity rather than
    dividing the PD by four, which would understate the hazard and would not
    reproduce the twelve-month PD when compounded back up.
    """
    p = float(annual_pd)
    if not 0.0 <= p < 1.0:
        raise EclInputError(
            f"a twelve-month PD must lie in [0, 1); got {p!r}")
    return 1.0 - (1.0 - p) ** (1.0 / float(periods_per_year))


def discount_factors(effective_rate: float, periods: int,
                     periods_per_year: int = PERIODS_PER_YEAR) -> list[float]:
    """Discount factors to the MIDPOINT of each period.

    The midpoint rather than the end, because a default is not concentrated on
    the last day of the quarter it happens in. Stated here because a reader
    reconciling the arithmetic by hand needs to know which convention is used.
    """
    r = float(effective_rate)
    if r <= -1.0:
        raise EclInputError(f"an effective rate must exceed -100%; got {r!r}")
    out: list[float] = []
    for t in range(int(periods)):
        years = (t + 0.5) / float(periods_per_year)
        out.append(1.0 / ((1.0 + r) ** years))
    return out


def severity_from_recovery(*, unsecured_lgd: float, secured_lgd: float,
                           collateral_coverage: float,
                           recovery_lag_years: float = 0.0,
                           effective_rate: float = 0.0) -> float:
    """Effective loss severity from the secured/unsecured split.

    ``collateral_coverage`` is the fraction of exposure covered by recognised
    collateral AFTER haircuts and AFTER allocation across the facilities that
    share the asset — it is computed in ``generate``/``attribution`` and passed
    in here, so this function can never double-count a shared asset or deduct a
    haircut twice.

    ``recovery_lag_years`` carries the delay between default and realisation.
    It is applied ONCE, to the secured leg only, and the caller must not then
    discount the resulting severity again for the same lag: the discounting in
    ``scenario_ecl`` runs from the DEFAULT date to the reporting date and this
    lag runs from realisation back to the default date. The two windows do not
    overlap.
    """
    cover = min(max(float(collateral_coverage), 0.0), 1.0)
    lag = max(float(recovery_lag_years), 0.0)
    drag = 1.0 / ((1.0 + float(effective_rate)) ** lag) if lag else 1.0
    # A lag makes the SECURED recovery worth less, so it raises severity on the
    # secured leg towards the unsecured one; it never lowers it.
    secured_component = 1.0 - (1.0 - float(secured_lgd)) * drag
    severity = cover * secured_component + (1.0 - cover) * float(unsecured_lgd)
    return min(max(severity, 0.0), 1.0)


def check_weights(weights: Iterable[float],
                  tolerance: float = WEIGHT_TOLERANCE) -> float:
    """Scenario weights must sum to one within a stated tolerance."""
    total = float(sum(weights))
    if abs(total - 1.0) > tolerance:
        raise EclInputError(
            f"scenario weights must sum to 1 within {tolerance}; they sum to "
            f"{total!r}")
    return total


# ------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class ScenarioInput:
    """Everything one scenario contributes to one facility's measurement.

    The four paths are per-period and are what the factor groups switch between
    when the attribution engine evaluates an opening/closing combination. Each
    is a separate field precisely so that a PD change and an EAD change are
    different objects rather than two readings of one blended number.
    """

    scenario_id: str
    weight: float
    #: Conditional default hazard per period. Brief §4.3's ``h_t``.
    hazard: tuple[float, ...]
    #: Loss severity given default in the period. Net of expected recoveries.
    lgd: tuple[float, ...]
    #: Exposure at default were default to occur in the period.
    ead: tuple[float, ...]
    #: Discount factor from the period back to the reporting date.
    discount: tuple[float, ...]

    def __post_init__(self) -> None:
        n = len(self.hazard)
        if not (len(self.lgd) == len(self.ead) == len(self.discount) == n):
            raise EclInputError(
                f"scenario {self.scenario_id!r}: hazard, lgd, ead and discount "
                f"must be the same length; got "
                f"{n}, {len(self.lgd)}, {len(self.ead)}, {len(self.discount)}")
        if n == 0:
            raise EclInputError(
                f"scenario {self.scenario_id!r} carries no periods")

    @property
    def periods(self) -> int:
        return len(self.hazard)


@dataclass(frozen=True)
class FacilityMeasurement:
    """One facility at one reporting date, ready to be measured."""

    facility_id: str
    borrower_id: str
    reporting_date: str
    stage: int
    #: The measurement window in periods. Twelve months for Stage 1; remaining
    #: life for Stage 2 and Stage 3. Set by the staging policy, never here.
    horizon_periods: int
    scenarios: tuple[ScenarioInput, ...]
    #: Separately identified, never blended into a parameter. Brief §4.3.
    overlay: float = 0.0
    currency: str = "INR"
    #: Rate to the reporting currency at the reporting date. 1.0 when the
    #: facility already reports in it.
    fx_rate: float = 1.0
    method: str = METHOD_PERFORMING
    model_version: str = MODEL_VERSION
    #: Free-form, surfaced verbatim wherever this facility's ECL is reported.
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.scenarios:
            raise EclInputError(
                f"facility {self.facility_id!r} carries no scenarios")
        check_weights(s.weight for s in self.scenarios)
        if self.horizon_periods < 1:
            raise EclInputError(
                f"facility {self.facility_id!r}: the measurement window must "
                f"be at least one period; got {self.horizon_periods}")


# ------------------------------------------------------------------ results


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    weight: float
    ecl: float
    cumulative_pd: float
    twelve_month_pd: float
    exposure_weighted_lgd: float
    ead_at_reporting_date: float
    marginal_pd: tuple[float, ...]
    survival: tuple[float, ...]
    periods_measured: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "weight": self.weight,
            "scenario_ecl": self.ecl,
            "cumulative_pd": self.cumulative_pd,
            "twelve_month_pd": self.twelve_month_pd,
            "exposure_weighted_lgd": self.exposure_weighted_lgd,
            "ead_at_reporting_date": self.ead_at_reporting_date,
            "periods_measured": self.periods_measured,
        }


@dataclass(frozen=True)
class EclResult:
    """What the calculator returns for one facility at one date."""

    facility_id: str
    borrower_id: str
    reporting_date: str
    stage: int
    method: str
    model_version: str
    horizon_periods: int
    scenarios: tuple[ScenarioResult, ...]
    weighted_model_ecl: float
    overlay: float
    reported_ecl: float
    #: Descriptive scenario-weighted parameter summaries. Useful to read; NOT a
    #: route back to `weighted_model_ecl`. `weighted_pd * weighted_lgd * ead`
    #: does not reproduce it and the demo proves that on its own data.
    weighted_twelve_month_pd: float
    weighted_lifetime_pd: float
    weighted_lgd: float
    weighted_ead: float
    limitations: tuple[str, ...] = ()

    @property
    def naive_parameter_product(self) -> float:
        """`weighted PD x weighted LGD x weighted EAD`. Deliberately exposed.

        Not an alternative computation of the weighted ECL. It is carried so
        the Cockpit can SHOW the gap when a user asks whether the shortcut
        works, rather than asserting that it does not.
        """
        return (self.weighted_twelve_month_pd * self.weighted_lgd
                * self.weighted_ead)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facility_id": self.facility_id,
            "borrower_id": self.borrower_id,
            "reporting_date": self.reporting_date,
            "stage": self.stage,
            "method": self.method,
            "model_version": self.model_version,
            "horizon_periods": self.horizon_periods,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "weighted_model_ecl": self.weighted_model_ecl,
            "overlay": self.overlay,
            "reported_ecl": self.reported_ecl,
            "weighted_twelve_month_pd": self.weighted_twelve_month_pd,
            "weighted_lifetime_pd": self.weighted_lifetime_pd,
            "weighted_lgd": self.weighted_lgd,
            "weighted_ead": self.weighted_ead,
            "naive_parameter_product": self.naive_parameter_product,
            "limitations": list(self.limitations),
        }


# ---------------------------------------------------------------- the engine


def scenario_ecl(scenario: ScenarioInput, horizon_periods: int) -> ScenarioResult:
    """One scenario's ECL for one facility. The component method of §4.3."""
    periods = max(1, min(int(horizon_periods), scenario.periods))
    survival, marginal = survival_and_marginals(scenario.hazard, periods)

    total = 0.0
    severity_weight = 0.0
    severity_value = 0.0
    for t in range(periods):
        loss = marginal[t] * scenario.ead[t] * scenario.lgd[t] * scenario.discount[t]
        total += loss
        severity_weight += marginal[t] * scenario.ead[t]
        severity_value += marginal[t] * scenario.ead[t] * scenario.lgd[t]

    twelve = cumulative_pd(scenario.hazard,
                           min(TWELVE_MONTH_PERIODS, scenario.periods))
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        weight=scenario.weight,
        ecl=total,
        cumulative_pd=float(sum(marginal)),
        twelve_month_pd=twelve,
        # Weighted by where default actually happens, so a severity that rises
        # late in a life is not averaged as if it applied from day one. With no
        # default mass at all the severity is the first period's, not zero.
        exposure_weighted_lgd=(severity_value / severity_weight
                               if severity_weight > 0 else scenario.lgd[0]),
        ead_at_reporting_date=scenario.ead[0],
        marginal_pd=tuple(marginal),
        survival=tuple(survival),
        periods_measured=periods,
    )


def measure(facility: FacilityMeasurement) -> EclResult:
    """Measure one facility. Every Cockpit V2 ECL figure comes through here."""
    results = tuple(scenario_ecl(s, facility.horizon_periods)
                    for s in facility.scenarios)

    weighted = sum(r.weight * r.ecl for r in results)
    w_twelve = sum(r.weight * r.twelve_month_pd for r in results)
    w_life = sum(r.weight * r.cumulative_pd for r in results)
    w_lgd = sum(r.weight * r.exposure_weighted_lgd for r in results)
    w_ead = sum(r.weight * r.ead_at_reporting_date for r in results)

    limitations = list(facility.limitations)
    if facility.horizon_periods >= MAX_LIFETIME_PERIODS:
        limitations.append(
            f"The lifetime window is capped at {MAX_LIFETIME_PERIODS} quarters "
            f"({MAX_LIFETIME_PERIODS // PERIODS_PER_YEAR} years); any remaining "
            f"term beyond that is not measured.")

    return EclResult(
        facility_id=facility.facility_id,
        borrower_id=facility.borrower_id,
        reporting_date=facility.reporting_date,
        stage=facility.stage,
        method=facility.method,
        model_version=facility.model_version,
        horizon_periods=facility.horizon_periods,
        scenarios=results,
        weighted_model_ecl=weighted,
        overlay=facility.overlay,
        reported_ecl=weighted + facility.overlay,
        weighted_twelve_month_pd=w_twelve,
        weighted_lifetime_pd=w_life,
        weighted_lgd=w_lgd,
        weighted_ead=w_ead,
        limitations=tuple(limitations),
    )


def measure_many(facilities: Iterable[FacilityMeasurement]) -> list[EclResult]:
    return [measure(f) for f in facilities]


# ------------------------------------------------------------- constructors


def performing_measurement(
    *, facility_id: str, borrower_id: str, reporting_date: str, stage: int,
    remaining_periods: int, effective_rate: float,
    scenario_parameters: Sequence[dict[str, Any]],
    ead_path_factor: Sequence[float] | None = None,
    overlay: float = 0.0, currency: str = "INR", fx_rate: float = 1.0,
    limitations: Sequence[str] = (),
) -> FacilityMeasurement:
    """Build a Stage 1 / Stage 2 measurement from readable parameters.

    ``scenario_parameters`` entries carry ``scenario_id``, ``weight``,
    ``twelve_month_pd``, ``hazard_shape`` (a per-period multiplier on the
    constant hazard, so a term structure is an explicit input rather than an
    accident), ``lgd`` and ``ead``.

    The measurement window follows the stage, per brief §4.3: twelve months for
    Stage 1, remaining life for Stage 2. Nothing here decides the stage — the
    staging policy does, and it is applied before this is called.
    """
    if stage not in (STAGE_1, STAGE_2):
        raise EclInputError(
            f"performing_measurement covers Stage 1 and Stage 2; got stage "
            f"{stage!r}. Use impaired_measurement for Stage 3.")

    life = max(1, min(int(remaining_periods), MAX_LIFETIME_PERIODS))
    horizon = TWELVE_MONTH_PERIODS if stage == STAGE_1 else life
    horizon = max(1, min(horizon, life))

    df = discount_factors(effective_rate, life)
    shape_default = [1.0] * life

    scenarios: list[ScenarioInput] = []
    for raw in scenario_parameters:
        base_hazard = annual_pd_to_hazard(float(raw["twelve_month_pd"]))
        shape = list(raw.get("hazard_shape") or shape_default)
        shape = (shape + [shape[-1]] * life)[:life] if shape else shape_default
        hazard = [min(max(base_hazard * float(k), 0.0), 1.0) for k in shape]

        lgd_in = raw["lgd"]
        lgd = ([float(x) for x in lgd_in][:life] if isinstance(lgd_in, (list, tuple))
               else [float(lgd_in)] * life)
        lgd = (lgd + [lgd[-1]] * life)[:life]

        ead_in = raw["ead"]
        if isinstance(ead_in, (list, tuple)):
            ead = ([float(x) for x in ead_in] + [float(ead_in[-1])] * life)[:life]
        else:
            factors = list(ead_path_factor or [1.0] * life)
            factors = (factors + [factors[-1]] * life)[:life]
            ead = [float(ead_in) * float(k) for k in factors]

        scenarios.append(ScenarioInput(
            scenario_id=str(raw["scenario_id"]), weight=float(raw["weight"]),
            hazard=tuple(hazard), lgd=tuple(lgd), ead=tuple(ead),
            discount=tuple(df)))

    return FacilityMeasurement(
        facility_id=facility_id, borrower_id=borrower_id,
        reporting_date=reporting_date, stage=stage, horizon_periods=horizon,
        scenarios=tuple(scenarios), overlay=overlay, currency=currency,
        fx_rate=fx_rate, method=METHOD_PERFORMING,
        limitations=tuple(limitations))


def impaired_measurement(
    *, facility_id: str, borrower_id: str, reporting_date: str,
    gross_carrying_amount: float, effective_rate: float,
    scenario_parameters: Sequence[dict[str, Any]],
    overlay: float = 0.0, currency: str = "INR", fx_rate: float = 1.0,
    limitations: Sequence[str] = (),
) -> FacilityMeasurement:
    """A Stage 3, credit-impaired measurement. Brief §4.3.

    Default has already occurred, so there is no hazard to model: the loss is
    the shortfall between the gross carrying amount and the present value of
    the recoveries expected on it. That is expressed on the same grid as the
    performing method — hazard 1.0 in the first period, exposure equal to the
    gross carrying amount, severity equal to ``1 - recovery_rate``, discounted
    over the expected time to realisation — so the factor engine can evaluate
    it without a second code path, and it is labelled
    ``METHOD_IMPAIRED_CASH_SHORTFALL`` everywhere it is reported.

    ``scenario_parameters`` entries carry ``scenario_id``, ``weight``,
    ``recovery_rate`` and ``recovery_lag_years``.
    """
    scenarios: list[ScenarioInput] = []
    for raw in scenario_parameters:
        recovery = min(max(float(raw["recovery_rate"]), 0.0), 1.0)
        lag = max(float(raw.get("recovery_lag_years", 0.0)), 0.0)
        df = 1.0 / ((1.0 + float(effective_rate)) ** lag)
        scenarios.append(ScenarioInput(
            scenario_id=str(raw["scenario_id"]), weight=float(raw["weight"]),
            hazard=(1.0,), lgd=(1.0 - recovery * df,),
            ead=(float(gross_carrying_amount),), discount=(1.0,)))

    return FacilityMeasurement(
        facility_id=facility_id, borrower_id=borrower_id,
        reporting_date=reporting_date, stage=STAGE_3, horizon_periods=1,
        scenarios=tuple(scenarios), overlay=overlay, currency=currency,
        fx_rate=fx_rate, method=METHOD_IMPAIRED,
        limitations=tuple(limitations) + (
            "Stage 3 is measured as the cash shortfall on an account that has "
            "already defaulted, not by the performing-loan formula. Expected "
            "recoveries are discounted once, over the expected time to "
            "realisation.",))


def simple_measurement(
    *, facility_id: str, borrower_id: str = "", reporting_date: str = "",
    ead: float, scenario_parameters: Sequence[dict[str, Any]],
    overlay: float = 0.0,
) -> FacilityMeasurement:
    """A single-period `PD x LGD x EAD` measurement with a unit discount factor.

    Explicitly simplified, and used only where the brief asks for exactly this
    shape: the independent arithmetic oracle of §6.1 and the anti-canned-answer
    perturbations built on it. It is NOT how the demo book is measured, and the
    integrity gates assert that no generated facility uses it.
    """
    scenarios = tuple(
        ScenarioInput(scenario_id=str(raw["scenario_id"]),
                      weight=float(raw["weight"]),
                      hazard=(float(raw["pd"]),), lgd=(float(raw["lgd"]),),
                      ead=(float(ead),), discount=(1.0,))
        for raw in scenario_parameters)
    return FacilityMeasurement(
        facility_id=facility_id, borrower_id=borrower_id or facility_id,
        reporting_date=reporting_date, stage=STAGE_1, horizon_periods=1,
        scenarios=scenarios, overlay=overlay, method=METHOD_PERFORMING,
        limitations=("Deliberately simplified single-period fixture: one "
                     "period, unit discount factor, no term structure.",))


def portfolio_total(results: Iterable[EclResult]) -> dict[str, float]:
    """Reported and model ECL over a set of facilities, plus the overlay."""
    model = overlay = reported = 0.0
    for r in results:
        model += r.weighted_model_ecl
        overlay += r.overlay
        reported += r.reported_ecl
    return {"weighted_model_ecl": model, "overlay": overlay,
            "reported_ecl": reported}


def close_enough(a: float, b: float,
                 tolerance: float = RECONCILIATION_TOLERANCE) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance)


__all__ = [
    "EclInputError", "EclResult", "FacilityMeasurement", "MAX_LIFETIME_PERIODS",
    "METHOD_IMPAIRED", "METHOD_PERFORMING", "PERIODS_PER_YEAR",
    "RECONCILIATION_TOLERANCE", "STAGE_1", "STAGE_2", "STAGE_3",
    "ScenarioInput", "ScenarioResult", "TWELVE_MONTH_PERIODS",
    "annual_pd_to_hazard", "check_weights", "close_enough", "cumulative_pd",
    "discount_factors", "impaired_measurement", "measure", "measure_many",
    "performing_measurement", "portfolio_total", "scenario_ecl",
    "severity_from_recovery", "simple_measurement", "survival_and_marginals",
]
