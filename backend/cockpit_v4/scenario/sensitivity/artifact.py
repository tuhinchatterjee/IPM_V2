"""The stored sensitivity artifact: written once offline, read in every turn.

Section 7.1: *"A chat question retrieves the stored artifact and its
calculation details. Training work is never an unannounced side effect of
asking a question."* This module is the retrieval half, and it imports
nothing from `estimate.py` — deliberately, so that reading a sensitivity
cannot reach the code that fits one.

Three jobs:

**`rows()`** turns fitted slopes into the columns
`whatif_*_sensitivity` declares, at build time.

**`translate()`** is what a scenario actually uses. Given a factor move in
native units it returns the parameter's baseline, its new value and the
change, all three, because section 5.1 requires all three and a reader shown
only the new value cannot tell a relative move from a percentage-point one.

**`aggregate()`** applies several factors at once, through section 7.2's
declared linear form:

    change_in_parameter = SUM over factors and lags of
                          native_sensitivity x change_in_macro_at_that_lag

with the nonlinear alternative offered by name rather than substituted for
it: *"Do not silently replace the user's linear sensitivity-times-change
interpretation with a nonlinear formula."*

A slope whose readiness is not `SUPPORTED_ESTIMATE` is refused here rather
than applied quietly. That is section 7.3's *"Factors not supportably
estimable remain unavailable for automatic translation unless the user
supplies an explicit assumption."*
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.cockpit_v4.generate.totals import exact_total
from backend.cockpit_v4.scenario.candidate_schema import ORIGIN
from backend.cockpit_v4.scenario.errors import (
    SENSITIVITY_NOT_SUPPORTED,
    raise_for,
)
from backend.cockpit_v4.scenario.sensitivity import readiness as rd

ARTIFACT_VERSION = "1.0.0"

#: What one native unit means, per shock convention, spelled out for the
#: `native_derivative_unit` column. A number without this sentence beside it
#: is the ambiguity section 5.1 is about.
UNIT_SENTENCE: dict[str, str] = {
    "percentage_points": (
        "percentage points of the parameter per one percentage point of the "
        "factor"),
    "basis_points": (
        "percentage points of the parameter per one percentage point of the "
        "factor; a basis-point shock is a hundredth of that"),
    "relative_percent": (
        "percentage points of the parameter per one native unit of the "
        "factor; a relative shock is converted to native units first"),
    "index_points": (
        "percentage points of the parameter per one index point of the "
        "factor"),
    "native_units": (
        "percentage points of the parameter per one native unit of the "
        "factor"),
}


@dataclass(frozen=True)
class Slope:
    """One stored sensitivity, as read back from the release."""

    parameter: str
    factor_id: str
    lag: int
    native_derivative: float
    native_derivative_unit: str
    reference_parameter_value: float
    reference_factor_value: float
    coefficient: float
    readiness: str
    limitation: str
    support_low: float
    support_high: float
    ci_low: float
    ci_high: float
    artifact_version: str
    source_fingerprint: str

    @property
    def supported(self) -> bool:
        return self.readiness == rd.SUPPORTED_ESTIMATE

    def in_support(self, factor_value: float) -> bool:
        """Was this factor value inside the training window's range?

        Section 11.4's extrapolation rule, applied to sensitivities too: a
        shock outside the range the slope was fitted over carries a warning
        rather than being silently evaluated.
        """
        return self.support_low <= factor_value <= self.support_high


@dataclass(frozen=True)
class Translation:
    """A factor move turned into a parameter move. All three numbers."""

    parameter: str
    factor_id: str
    lag: int
    factor_baseline: float
    factor_scenario: float
    factor_change: float
    parameter_baseline: float
    parameter_scenario: float
    parameter_change_pp: float
    method: str
    warnings: tuple[str, ...] = ()

    def describe(self) -> str:
        return (
            f"{self.factor_id} {self.factor_baseline:g} to "
            f"{self.factor_scenario:g} ({self.factor_change:+g}) moves "
            f"{self.parameter} from {self.parameter_baseline * 100:.2f}% to "
            f"{self.parameter_scenario * 100:.2f}%, a change of "
            f"{self.parameter_change_pp:+.2f} percentage points")


#: The two translations section 7.2 names, offered by name rather than one
#: being substituted for the other.
LINEAR = "linear_sensitivity_times_change"
NONLINEAR = "fitted_link_finite_difference"


def rows(fits: Iterable[Any], *, domain_id: str, period: str,
         period_column: str, release_id: str, fingerprint: str,
         tenant_id: str, conventions: dict[str, str],
         method: str, fitted_at: str,
         unavailable: Iterable[tuple[str, str]] = ()) -> list[dict[str, Any]]:
    """Published rows for one book's artifact, fitted and unavailable alike.

    `unavailable` carries `(factor_id, reason)` for the factors this book has
    no series for. They get rows too: section 7.1 wants a twenty-entry
    availability table, and a registry with four silent gaps is not one.
    """
    out: list[dict[str, Any]] = []
    stamp = {"tenant_id": tenant_id, "dataset_release_id": release_id,
             "domain_id": domain_id, "reporting_currency": "SAR",
             "origin": ORIGIN}
    for fit in fits:
        convention = conventions.get(fit.factor_id, "native_units")
        out.append({
            **stamp,
            "artifact_id": f"{domain_id}-sensitivity-{ARTIFACT_VERSION}",
            "artifact_version": ARTIFACT_VERSION,
            period_column: period,
            "parameter": fit.parameter,
            "factor_id": fit.factor_id,
            "lag": int(fit.lag),
            "transformation": "first difference in native units",
            "coefficient": round(fit.coefficient, 8),
            "native_derivative": round(fit.native_derivative, 8),
            "native_derivative_unit": UNIT_SENTENCE.get(
                convention, UNIT_SENTENCE["native_units"]),
            "reference_parameter_value": round(fit.reference_parameter, 8),
            "reference_factor_value": round(fit.reference_factor, 6),
            "standardised_response": round(fit.standardised_response, 8),
            "std_error": round(fit.std_error, 8),
            "ci_low": round(fit.ci_low, 8),
            "ci_high": round(fit.ci_high, 8),
            "sign_stability": round(fit.sign_stability, 4),
            "training_periods": int(fit.training_periods),
            "validation_periods": int(fit.validation_periods),
            "train_start": fit.train_start,
            "train_end": fit.train_end,
            "effective_df": round(fit.effective_df, 4),
            "max_df_allowed": rd.max_effective_df(fit.training_periods),
            "collinearity": round(fit.collinearity, 4),
            "fit_error": round(fit.fit_error, 8),
            "validation_error": round(fit.validation_error, 8),
            "readiness": fit.verdict.status,
            "limitation": fit.verdict.limitation,
            "support_low": round(fit.support_low, 6),
            "support_high": round(fit.support_high, 6),
            "method": method,
            "source_release_id": release_id,
            "source_fingerprint": fingerprint,
        })
    for factor_id, reason in unavailable:
        for parameter in ("pd_pit_12m", "pd_lifetime", "lgd_pct"):
            out.append({
                **stamp,
                "artifact_id": f"{domain_id}-sensitivity-{ARTIFACT_VERSION}",
                "artifact_version": ARTIFACT_VERSION,
                period_column: period,
                "parameter": parameter, "factor_id": factor_id, "lag": 0,
                "transformation": "", "coefficient": 0.0,
                "native_derivative": 0.0,
                "native_derivative_unit": "",
                "reference_parameter_value": 0.0,
                "reference_factor_value": 0.0,
                "standardised_response": 0.0, "std_error": 0.0,
                "ci_low": 0.0, "ci_high": 0.0, "sign_stability": 0.0,
                "training_periods": 0, "validation_periods": 0,
                "train_start": "", "train_end": "", "effective_df": 0.0,
                "max_df_allowed": 0.0, "collinearity": 0.0,
                "fit_error": 0.0, "validation_error": 0.0,
                "readiness": rd.UNAVAILABLE,
                "limitation": reason,
                "support_low": 0.0, "support_high": 0.0, "method": "",
                "source_release_id": release_id,
                "source_fingerprint": fingerprint,
            })
    return out


def from_row(row: dict[str, Any]) -> Slope:
    """One published row, back as a `Slope`."""
    return Slope(
        parameter=str(row["parameter"]), factor_id=str(row["factor_id"]),
        lag=int(row["lag"]),
        native_derivative=float(row["native_derivative"]),
        native_derivative_unit=str(row["native_derivative_unit"]),
        reference_parameter_value=float(row["reference_parameter_value"]),
        reference_factor_value=float(row["reference_factor_value"]),
        coefficient=float(row["coefficient"]),
        readiness=str(row["readiness"]), limitation=str(row["limitation"]),
        support_low=float(row["support_low"]),
        support_high=float(row["support_high"]),
        ci_low=float(row["ci_low"]), ci_high=float(row["ci_high"]),
        artifact_version=str(row["artifact_version"]),
        source_fingerprint=str(row["source_fingerprint"]))


def require_usable(slope: Slope, *, in_use_fingerprint: str = "") -> None:
    """Refuse a slope a scenario may not translate through.

    Two refusals, both section 7.3's: a readiness below
    `SUPPORTED_ESTIMATE`, and an artifact fitted against a different release
    (S16). Neither is a warning -- applying either anyway would put a number
    in front of a reader that the artifact itself says is not fit to use.
    """
    if not slope.supported:
        raise_for(SENSITIVITY_NOT_SUPPORTED,
                  f"{slope.factor_id} has no supported sensitivity for "
                  f"{slope.parameter} in this book: {slope.limitation} "
                  f"State the parameter change you want to assume, and it "
                  f"will be applied as your assumption rather than as an "
                  f"estimate.",
                  field_path=f"sensitivity.{slope.factor_id}",
                  readiness=slope.readiness, parameter=slope.parameter)
    if rd.is_stale(slope.source_fingerprint, in_use_fingerprint):
        raise_for(SENSITIVITY_NOT_SUPPORTED,
                  f"This sensitivity was fitted against release bytes "
                  f"{slope.source_fingerprint[:12]} and the book in use is "
                  f"{in_use_fingerprint[:12]}. A fit against different bytes "
                  f"describes a different book; refit before using it.",
                  field_path=f"sensitivity.{slope.factor_id}",
                  readiness=rd.STALE)


def translate(slope: Slope, *, factor_baseline: float,
              factor_scenario: float, parameter_baseline: float | None = None,
              method: str = LINEAR,
              in_use_fingerprint: str = "") -> Translation:
    """A factor move, through one slope, into a parameter move.

    Section 7.4's worked example is the contract: unemployment 6.0% to 5.4%
    is **−0.6 percentage points**, and at +0.20 PD points per unemployment
    point a baseline PD of 3.00% becomes **2.88%**. Never `−10` because the
    reader said "10%", and never a ten-point move.

    `method` picks between the two translations section 7.2 names. The
    linear one is the reader's own reading of "sensitivity times change";
    the nonlinear one adds the fitted linear-predictor change to the observed
    baseline logit and inverts, so its zero-shock output is the observed
    baseline exactly (S09). They give different answers and the preview shows
    which was used.
    """
    require_usable(slope, in_use_fingerprint=in_use_fingerprint)
    baseline = (slope.reference_parameter_value if parameter_baseline is None
                else parameter_baseline)
    change = factor_scenario - factor_baseline

    warnings: list[str] = []
    if not slope.in_support(factor_scenario):
        warnings.append(
            f"{factor_scenario:g} is outside the {slope.support_low:g} to "
            f"{slope.support_high:g} range this slope was fitted over. The "
            f"translation is an extrapolation.")

    if method == LINEAR:
        moved_pp = slope.native_derivative * change
        scenario = baseline + moved_pp / 100.0
    elif method == NONLINEAR:
        bounded = min(max(baseline, 1e-9), 1.0 - 1e-9)
        logit = math.log(bounded / (1.0 - bounded))
        scenario = 1.0 / (1.0 + math.exp(-(logit + slope.coefficient
                                           * change)))
        moved_pp = (scenario - baseline) * 100.0
    else:
        raise_for(SENSITIVITY_NOT_SUPPORTED,
                  f"{method!r} is not a translation this engine has. They "
                  f"are {LINEAR} and {NONLINEAR}, and they give different "
                  f"answers, which is why neither is substituted for the "
                  f"other.",
                  field_path="sensitivity.method")
        raise AssertionError("unreachable")  # pragma: no cover

    if scenario < 0.0:
        warnings.append(
            f"The linear translation puts {slope.parameter} below zero. A "
            f"probability cannot be negative; the fitted-link translation "
            f"stays inside (0, 1) and is the alternative here.")
    return Translation(
        parameter=slope.parameter, factor_id=slope.factor_id, lag=slope.lag,
        factor_baseline=factor_baseline, factor_scenario=factor_scenario,
        factor_change=change, parameter_baseline=baseline,
        parameter_scenario=scenario, parameter_change_pp=moved_pp,
        method=method, warnings=tuple(warnings))


def aggregate(moves: Sequence[tuple[Slope, float, float]], *,
              parameter_baseline: float,
              in_use_fingerprint: str = "") -> Translation:
    """Several factors at once, through section 7.2's declared linear sum.

        change_in_parameter = SUM over j,l of
            native_sensitivity[j,l] x change_in_macro[j, at lag l]

    Only the linear form: summing nonlinear translations would not be a sum
    of anything. Every slope must be for the same parameter, because adding a
    PD response to an LGD response would be adding two different quantities.
    """
    if not moves:
        raise ValueError("an aggregate of no factors is not a translation.")
    parameters = {slope.parameter for slope, _b, _s in moves}
    if len(parameters) > 1:
        raise ValueError(
            f"these slopes are for {sorted(parameters)}. A PD response and "
            f"an LGD response are different quantities and do not add.")

    warnings: list[str] = []
    contributions: list[float] = []
    for slope, factor_baseline, factor_scenario in moves:
        one = translate(slope, factor_baseline=factor_baseline,
                        factor_scenario=factor_scenario,
                        parameter_baseline=parameter_baseline, method=LINEAR,
                        in_use_fingerprint=in_use_fingerprint)
        contributions.append(one.parameter_change_pp)
        warnings.extend(one.warnings)

    total_pp = exact_total(contributions)
    return Translation(
        parameter=next(iter(parameters)),
        factor_id=", ".join(s.factor_id for s, _b, _sc in moves),
        lag=max(s.lag for s, _b, _sc in moves),
        factor_baseline=float("nan"), factor_scenario=float("nan"),
        factor_change=float("nan"),
        parameter_baseline=parameter_baseline,
        parameter_scenario=parameter_baseline + total_pp / 100.0,
        parameter_change_pp=total_pp, method=LINEAR,
        warnings=tuple(warnings) + (
            "Summed marginal sensitivities. Section 7.3: correlated "
            "univariate slopes are not a jointly estimated model, and the "
            "total may overstate a joint move.",))


def rank(slopes: Iterable[Slope],
         responses: dict[tuple[str, str], float]) -> list[Slope]:
    """Factors ordered by their standardised response, largest first.

    Section 7.4 asks for a stated training-only ranking measure and for the
    native-unit slopes to be shown beside it. The measure is the parameter's
    response to one training-period standard deviation of the factor --
    stated here, not inferred from the ordering -- and magnitude is not
    evidence of causal importance.
    """
    return sorted(
        slopes,
        key=lambda s: -abs(responses.get((s.parameter, s.factor_id), 0.0)))


__all__ = ["ARTIFACT_VERSION", "LINEAR", "NONLINEAR", "Slope", "Translation",
           "UNIT_SENTENCE", "aggregate", "from_row", "rank", "require_usable",
           "rows", "translate"]
