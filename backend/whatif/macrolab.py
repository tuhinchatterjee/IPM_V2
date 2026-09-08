"""
What the macro variable and the book have actually done together, and what a
person may put in place of the configured assumption.

Two different things live here, and keeping them apart is the point
-------------------------------------------------------------------
**The CreditProbe reference sensitivity** is a declared assumption. It says a
one-point rise in unemployment multiplies PD by 1.12 and adds a point to LGD,
because somebody decided that, wrote it down and versioned it. It is not
estimated from this data and it never claims to be.

**The empirical relationship** is what the sixteen quarters in this
installation actually show. It is measured, it is reported with its
uncertainty, and — with sixteen observations — it is DIRECTIONAL EVIDENCE and
nothing stronger. Sixteen quarterly points cannot calibrate an econometric
relationship, and a screen that presented an R-squared from them as a
calibration would be lying with statistics.

**A user-defined sensitivity** is neither. It is what this person wants to
assume for this thread, and it is labelled as theirs. It never silently
replaces the reference, it is carried on the result and into the workbook, and
it is never described as required, regulatory, approved or empirical unless it
actually is.

The macro series in this installation
--------------------------------------
Generated from a single latent cycle factor, so GDP growth, the oil price and
the policy rate move together by construction. There are effectively sixteen
independent macro observations, not fifty thousand. Every function here says
so where it matters, because the alternative is a scatter plot that looks like
a finding.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MACROLAB_VERSION = "1.0.0"

#: Where a sensitivity came from. The label is carried everywhere the number
#: is, because "PD ×1.12 per 1pp" means three different things depending on
#: which of these produced it.
REFERENCE = "reference"
EMPIRICAL = "empirical"
USER = "user"
SOURCES: tuple[str, ...] = (REFERENCE, EMPIRICAL, USER)

SOURCE_LABELS: dict[str, str] = {
    REFERENCE: "CreditProbe Reference Sensitivity",
    EMPIRICAL: "Estimated from this installation's history",
    USER: "User-Defined Sensitivity",
}

#: How a response is expressed.
MULTIPLIER = "multiplier"      # PD is multiplied
ABSOLUTE_PP = "absolute_pp"    # LGD moves by points
RESPONSE_KINDS: tuple[str, ...] = (MULTIPLIER, ABSOLUTE_PP)

#: Below this many usable observations the relationship is not reported as a
#: relationship at all. Sixteen quarters gives fifteen changes; a cut that
#: leaves fewer than eight is noise with a line through it.
MINIMUM_POINTS = 8

#: However good the fit looks, this many observations does not calibrate
#: anything. Stated on every estimate.
SMALL_SAMPLE = (
    "This installation carries sixteen quarterly observations, so fifteen "
    "changes at most. That is enough to see whether the relationship runs in "
    "the direction the configured sensitivity assumes, and how strongly. It is "
    "NOT an econometric calibration: no confidence interval from fifteen "
    "points would mean what a reader would take it to mean, and the observed "
    "macro series here move together by construction.")


class MacroLabError(ValueError):
    """A relationship that cannot be estimated or stored, said rather than faked."""


# ----------------------------------------------------- the empirical work


@dataclass
class Fit:
    """One estimated relationship, with everything needed to distrust it."""

    variable: str
    variable_name: str
    unit: str
    #: Change in the borrower-weighted PIT 12-month PD, in PERCENT of itself,
    #: per one unit of the variable's own adverse move.
    slope_pct_per_unit: float = 0.0
    intercept_pct: float = 0.0
    correlation: float = 0.0
    r_squared: float = 0.0
    points: int = 0
    #: The implied PD multiplier for one ADVERSE unit, so it can be put beside
    #: the configured one and compared without arithmetic.
    implied_pd_multiplier: float = 1.0
    configured_pd_multiplier: float = 1.0
    direction_agrees: bool = True
    strength: str = "none"
    series: list[dict[str, Any]] = field(default_factory=list)
    scatter: list[dict[str, Any]] = field(default_factory=list)
    cuts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable, "variable_name": self.variable_name,
            "unit": self.unit,
            "slope_pct_per_unit": round(self.slope_pct_per_unit, 4),
            "intercept_pct": round(self.intercept_pct, 4),
            "correlation": round(self.correlation, 4),
            "r_squared": round(self.r_squared, 4),
            "points": self.points,
            "implied_pd_multiplier": round(self.implied_pd_multiplier, 4),
            "configured_pd_multiplier": round(self.configured_pd_multiplier, 4),
            "direction_agrees": self.direction_agrees,
            "strength": self.strength,
            "series": self.series, "scatter": self.scatter, "cuts": self.cuts,
            "note": self.note,
            "small_sample": SMALL_SAMPLE,
            "source": EMPIRICAL,
            "source_label": SOURCE_LABELS[EMPIRICAL],
        }


def _strength(r_squared: float, points: int) -> str:
    """How much the fit is worth, said in words rather than in a p-value."""
    if points < MINIMUM_POINTS:
        return "insufficient"
    if r_squared >= 0.60:
        return "strong in this window"
    if r_squared >= 0.30:
        return "moderate in this window"
    if r_squared >= 0.10:
        return "weak in this window"
    return "no visible relationship in this window"


def _least_squares(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Slope, intercept and correlation. Fifteen points needs no library."""
    if len(x) < 2:
        return 0.0, 0.0, 0.0
    mx, my = float(np.mean(x)), float(np.mean(y))
    dx, dy = x - mx, y - my
    sxx = float(np.dot(dx, dx))
    if sxx <= 1e-12:
        return 0.0, my, 0.0
    slope = float(np.dot(dx, dy) / sxx)
    syy = float(np.dot(dy, dy))
    correlation = (float(np.dot(dx, dy) / math.sqrt(sxx * syy))
                   if syy > 1e-12 else 0.0)
    return slope, my - slope * mx, correlation


def _weighted_pd(frame: pd.DataFrame) -> float:
    """The book's exposure-weighted point-in-time twelve-month PD."""
    pd_12m = pd.to_numeric(frame.get("pd_12m"), errors="coerce").fillna(0.0)
    ead = pd.to_numeric(frame.get("ead"), errors="coerce").fillna(0.0)
    total = float(ead.sum())
    return float((pd_12m * ead).sum() / total) if total > 0 else float(pd_12m.mean())


def _population(frame: pd.DataFrame, population: Any) -> pd.DataFrame:
    """The rows a scenario's population would select, for the history too.

    A relationship estimated on the whole book and then applied to Contracting
    is a relationship about a different portfolio.
    """
    if population is None:
        return frame
    work = frame
    sectors = tuple(getattr(population, "sectors", ()) or ())
    if sectors and "sector" in work.columns:
        wanted = {s.strip().lower() for s in sectors}
        work = work[work["sector"].astype(str).str.strip().str.lower().isin(wanted)]
    stages = tuple(getattr(population, "stages", ()) or ())
    if stages and "stage" in work.columns:
        work = work[pd.to_numeric(work["stage"], errors="coerce").isin(stages)]
    return work


def estimate(variable: str, *, population: Any = None,
             source: Any = None) -> Fit:
    """Align the variable's history to the book's PD and measure the two.

    Changes against changes, not levels against levels. Two series that both
    trend produce a correlation of 0.9 and mean nothing; the question is
    whether a MOVE in the variable comes with a MOVE in the book.
    """
    from backend.whatif import domain as dm
    from backend.whatif import macro as mc

    found = mc.variable(variable)
    if found is None:
        raise MacroLabError(
            f"'{variable}' is not one of the ten governed macro variables. "
            "They are: " + ", ".join(v.name for v in mc.VARIABLES) + ".")

    body = Fit(variable=found.key, variable_name=found.name, unit=found.unit,
               configured_pd_multiplier=found.pd_multiplier)

    series = mc.history(dm.macro(source))
    path = series.get(found.key) or []
    if not path:
        body.note = (
            f"No observed time series is loaded for {found.name} in this "
            "installation, so there is nothing to estimate against. The "
            "configured reference sensitivity still applies, and you can "
            "define your own.")
        body.strength = "insufficient"
        return body

    levels: dict[str, float] = {}
    for period in dm.periods(source):
        try:
            frame, _ = dm.book(period, source=source)
        except Exception:  # noqa: BLE001 - a quarter that will not read is skipped
            continue
        part = _population(frame, population)
        if part.empty:
            continue
        levels[period] = _weighted_pd(part)

    observed = {str(point["period"]): float(point["value"])
                for point in path if point.get("value") is not None}
    shared = [p for p in dm.periods(source)
              if p in levels and p in observed]
    if len(shared) < 3:
        body.note = ("The macro series and the book do not overlap in enough "
                     "quarters to compare.")
        body.strength = "insufficient"
        return body

    body.series = [{"period": p, "macro": round(observed[p], 4),
                    "weighted_pd_pct": round(levels[p], 4)} for p in shared]

    # Changes, and the macro change expressed in ADVERSE units so the slope is
    # directly comparable with the configured multiplier.
    adverse = float(found.adverse_unit) or 1.0
    xs, ys, scatter = [], [], []
    for before, after in zip(shared, shared[1:], strict=False):
        # The column and the declared unit do not always agree — an index
        # level against a percentage move, a rate in percent against an
        # adverse unit in basis points. The variable reconciles them; doing it
        # here would be the second unit convention that caused the problem.
        try:
            macro_move = found.observed_move(observed[before],
                                             observed[after]) / adverse
        except mc.MacroError:
            continue
        pd_before, pd_after = levels[before], levels[after]
        if pd_before <= 1e-9:
            continue
        pd_move = (pd_after / pd_before - 1.0) * 100.0
        xs.append(macro_move)
        ys.append(pd_move)
        scatter.append({"from": before, "to": after,
                        "macro_adverse_units": round(macro_move, 4),
                        "pd_change_pct": round(pd_move, 4)})
    body.scatter = scatter
    body.points = len(xs)
    if body.points < 3:
        body.note = "Too few consecutive quarters to fit anything."
        body.strength = "insufficient"
        return body

    slope, intercept, correlation = _least_squares(np.array(xs), np.array(ys))
    body.slope_pct_per_unit = slope
    body.intercept_pct = intercept
    body.correlation = correlation
    body.r_squared = correlation ** 2
    body.strength = _strength(body.r_squared, body.points)
    body.implied_pd_multiplier = max(0.01, 1.0 + slope / 100.0)
    body.direction_agrees = (
        (body.implied_pd_multiplier - 1.0) * (found.pd_multiplier - 1.0) >= 0)

    direction = ("consistent with" if body.direction_agrees
                 else "opposite to")
    comparison = ("weaker than" if abs(body.implied_pd_multiplier - 1.0)
                  < abs(found.pd_multiplier - 1.0) else "stronger than")
    body.note = (
        f"Over {body.points} quarterly changes, one adverse unit of "
        f"{found.name} came with a {slope:+.2f}% move in the "
        f"exposure-weighted twelve-month PD — an implied multiplier of "
        f"{body.implied_pd_multiplier:.3f} against the configured "
        f"{found.pd_multiplier:.3f}. The direction is {direction} the "
        f"configured sensitivity and the magnitude is {comparison} it. "
        f"The fit is {body.strength} (R² {body.r_squared:.2f}).")
    return body


# ------------------------------------------------- what a person may define


@dataclass(frozen=True)
class Sensitivity:
    """One macro relationship, and where it came from.

    Frozen, because a sensitivity that could be edited after a result was
    computed on it would make the result unreproducible.
    """

    variable: str
    source: str = REFERENCE
    #: Per one adverse unit of the variable's own move.
    pd_response_kind: str = MULTIPLIER
    pd_response: float = 1.0
    lgd_response_kind: str = ABSOLUTE_PP
    lgd_response: float = 0.0
    #: Where it applies. Empty means the whole book.
    sectors: tuple[str, ...] = ()
    segments: tuple[str, ...] = ()
    rating_bands: tuple[str, ...] = ()
    stages: tuple[int, ...] = ()
    #: What it will not do, whatever the shock.
    pd_ceiling_pct: float = 99.0
    lgd_ceiling_pct: float = 95.0
    name: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise MacroLabError(
                f"'{self.source}' is not a sensitivity source. They are: "
                + ", ".join(SOURCES) + ".")
        for kind, what in ((self.pd_response_kind, "PD"),
                           (self.lgd_response_kind, "LGD")):
            if kind not in RESPONSE_KINDS:
                raise MacroLabError(
                    f"'{kind}' is not a {what} response kind. They are: "
                    + ", ".join(RESPONSE_KINDS) + ".")
        if self.pd_response_kind == MULTIPLIER and self.pd_response <= 0:
            raise MacroLabError(
                "A PD multiplier must be positive. A multiplier of zero or "
                "less says a shock removes every borrower's risk.")

    @property
    def scoped(self) -> bool:
        return bool(self.sectors or self.segments or self.rating_bands
                    or self.stages)

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    def describe(self) -> str:
        pd_part = (f"PD ×{self.pd_response:g}"
                   if self.pd_response_kind == MULTIPLIER
                   else f"PD {self.pd_response:+g}pp")
        lgd_part = (f"LGD ×{self.lgd_response:g}"
                    if self.lgd_response_kind == MULTIPLIER
                    else f"LGD {self.lgd_response:+g}pp")
        where = ""
        if self.scoped:
            parts = []
            if self.sectors:
                parts.append("in " + ", ".join(self.sectors))
            if self.segments:
                parts.append("in " + ", ".join(self.segments))
            if self.rating_bands:
                parts.append("rated " + ", ".join(self.rating_bands))
            if self.stages:
                parts.append("in Stage " + ", ".join(str(s) for s in self.stages))
            where = ", " + " and ".join(parts)
        return f"{pd_part}, {lgd_part} per adverse unit{where} ({self.label})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable, "source": self.source,
            "source_label": self.label, "name": self.name,
            "pd_response_kind": self.pd_response_kind,
            "pd_response": self.pd_response,
            "lgd_response_kind": self.lgd_response_kind,
            "lgd_response": self.lgd_response,
            "sectors": list(self.sectors), "segments": list(self.segments),
            "rating_bands": list(self.rating_bands),
            "stages": list(self.stages), "scoped": self.scoped,
            "pd_ceiling_pct": self.pd_ceiling_pct,
            "lgd_ceiling_pct": self.lgd_ceiling_pct,
            "description": self.describe(), "note": self.note,
        }

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> Sensitivity:
        return cls(
            variable=str(body.get("variable", "")),
            source=str(body.get("source") or REFERENCE),
            pd_response_kind=str(body.get("pd_response_kind") or MULTIPLIER),
            pd_response=float(body.get("pd_response", 1.0)),
            lgd_response_kind=str(body.get("lgd_response_kind") or ABSOLUTE_PP),
            lgd_response=float(body.get("lgd_response", 0.0)),
            sectors=tuple(body.get("sectors") or ()),
            segments=tuple(body.get("segments") or ()),
            rating_bands=tuple(body.get("rating_bands") or ()),
            stages=tuple(int(s) for s in (body.get("stages") or ())),
            pd_ceiling_pct=float(body.get("pd_ceiling_pct", 99.0)),
            lgd_ceiling_pct=float(body.get("lgd_ceiling_pct", 95.0)),
            name=str(body.get("name") or ""),
            note=str(body.get("note") or ""))


def configured(variable: str) -> Sensitivity:
    """The CreditProbe reference sensitivity, as a Sensitivity."""
    from backend.whatif import macro as mc

    found = mc.variable(variable)
    if found is None:
        raise MacroLabError(f"'{variable}' is not a governed macro variable.")
    return Sensitivity(
        variable=found.key, source=REFERENCE,
        pd_response_kind=MULTIPLIER, pd_response=found.pd_multiplier,
        lgd_response_kind=ABSOLUTE_PP, lgd_response=found.lgd_change_pp,
        pd_ceiling_pct=mc.PD_CEILING_PCT, lgd_ceiling_pct=mc.LGD_CEILING_PCT,
        name=found.name, note=found.note)


def from_fit(body: Fit) -> Sensitivity:
    """The estimated relationship, expressed as something the engine can apply.

    The LGD leg is NOT estimated: nothing in this book relates a macro variable
    to loss severity independently of default, so the configured LGD response
    is carried across and said so. Estimating it from the same fifteen points
    would be manufacturing a second number from the first one's noise.
    """
    reference = configured(body.variable)
    return Sensitivity(
        variable=body.variable, source=EMPIRICAL,
        pd_response_kind=MULTIPLIER,
        pd_response=body.implied_pd_multiplier,
        lgd_response_kind=ABSOLUTE_PP,
        lgd_response=reference.lgd_response,
        pd_ceiling_pct=reference.pd_ceiling_pct,
        lgd_ceiling_pct=reference.lgd_ceiling_pct,
        name=f"{body.variable_name} — estimated",
        note=(body.note + " The LGD response is the configured one: nothing in "
              "this book relates a macro variable to loss severity "
              "independently of default."))


def recommend(body: Fit) -> dict[str, Any]:
    """Which sensitivity to use, and why — evidence, never preference.

    A recommendation, never a substitution. Whatever this says, the configured
    sensitivity stays in force until a person chooses otherwise.
    """
    if body.strength == "insufficient":
        return {
            "recommends": REFERENCE,
            "because": (
                "There is not enough overlapping history to estimate a "
                "relationship, so there is nothing to weigh against the "
                "configured sensitivity."),
            "options": [REFERENCE, USER],
        }
    if not body.direction_agrees:
        return {
            "recommends": REFERENCE,
            "because": (
                f"The estimated relationship runs OPPOSITE to the configured "
                f"one — an implied multiplier of {body.implied_pd_multiplier:.3f} "
                f"against {body.configured_pd_multiplier:.3f}. Over "
                f"{body.points} observations, from series that move together "
                "by construction, that is more likely to be an artefact of "
                "this installation's data than a finding about credit. I would "
                "keep the configured sensitivity and treat the estimate as "
                "something to explain rather than to use."),
            "options": [REFERENCE, EMPIRICAL, USER],
        }
    weaker = (abs(body.implied_pd_multiplier - 1.0)
              < abs(body.configured_pd_multiplier - 1.0))
    return {
        "recommends": REFERENCE,
        "because": (
            f"The historical relationship is directionally consistent with the "
            f"configured sensitivity but "
            f"{'weaker' if weaker else 'stronger'} — "
            f"{body.implied_pd_multiplier:.3f} against "
            f"{body.configured_pd_multiplier:.3f}, on {body.points} "
            f"observations with an R² of {body.r_squared:.2f}. Given the "
            "limited window I would retain the configured sensitivity for the "
            "primary What-If and run the estimated one as a comparison."),
        "options": [REFERENCE, EMPIRICAL, USER],
    }


def describe() -> dict[str, Any]:
    """What a macro relationship can be, for the configuration screen."""
    return {
        "version": MACROLAB_VERSION,
        "sources": [{"source": key, "label": label} for key, label
                    in SOURCE_LABELS.items()],
        "response_kinds": [
            {"kind": MULTIPLIER, "means": "the parameter is multiplied"},
            {"kind": ABSOLUTE_PP, "means": "the parameter moves by points"}],
        "small_sample": SMALL_SAMPLE,
        "statement": (
            "A CreditProbe reference sensitivity is a declared assumption. An "
            "estimated one is what this installation's sixteen quarters "
            "actually show. A user-defined one is what you want to assume. All "
            "three are labelled wherever the number appears, and a user-defined "
            "sensitivity is never called required, regulatory, approved or "
            "empirical."),
    }


__all__ = [
    "ABSOLUTE_PP", "EMPIRICAL", "Fit", "MACROLAB_VERSION", "MINIMUM_POINTS",
    "MULTIPLIER", "MacroLabError", "REFERENCE", "RESPONSE_KINDS", "SMALL_SAMPLE",
    "SOURCES", "SOURCE_LABELS", "Sensitivity", "USER", "configured",
    "describe", "estimate", "from_fit", "recommend",
]
