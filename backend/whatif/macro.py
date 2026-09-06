"""
The ten macroeconomic variables a What-If scenario can move, and what each is
assumed to do to PD and LGD.

These are ASSUMPTIONS, and they say so
--------------------------------------
Every number in this module is a CreditProbe What-If reference sensitivity set
by the threshold owner. None of it is an IFRS 9 requirement, and none of it is
an econometric estimate fitted to this book. A screen that showed "unemployment
+1pp raises PD by 12%" without saying where that came from would be inviting a
credit committee to believe a coefficient nobody measured.

So each variable carries its owner, its version, its effective date and the
basis on which it was set, and `describe()` hands all of that to the screen.

Why they are not fitted
-----------------------
They could not honestly be fitted from this book. The synthetic macro series
are generated from a single latent cycle factor:

    oil  = 84.0 + 18.0 * factor + noise
    gdp  =  2.4 +  2.6 * factor + noise
    rate =  5.6 -  1.1 * factor + noise

so oil, GDP and the policy rate are collinear by construction — one degree of
freedom observed sixteen times, not three variables observed fifty-two thousand
times. A regression on that data would recover the generator's own arithmetic
and present it as an empirical finding. Stating the sensitivities as declared
assumptions is the honest form, and it is also the form a bank's own scenario
committee actually uses.

Scaling
-------
    PD_new  = PD_old x multiplier ** units
    LGD_new = LGD_old + lgd_change_pp * units

where `units` is how many ADVERSE units of that variable the scenario applied.
A favourable move is a negative unit count and works in the opposite direction
because the same arithmetic runs with a negative exponent. Both are capped into
a range a probability and a loss rate can actually occupy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

MACRO_OWNER = "Credit Risk Analytics"
MACRO_VERSION = "1.0.0"
MACRO_EFFECTIVE = "2026-01-01"

BASIS = ("A CreditProbe What-If reference sensitivity, set by the threshold "
         "owner and reviewed with the scenario. It is not an IFRS 9 "
         "coefficient and it is not an econometric estimate fitted to this "
         "book.")

#: PD may not leave the range a probability occupies, and a rate of exactly
#: zero is not something any rating system publishes.
PD_FLOOR_PCT = 0.001
PD_CEILING_PCT = 100.0
LGD_FLOOR_PCT = 0.0
LGD_CEILING_PCT = 100.0

#: How a magnitude was expressed, which decides how many adverse units it is.
RELATIVE = "relative_pct"
ABSOLUTE_PP = "absolute_pp"
BASIS_POINTS = "basis_points"


class MacroError(ValueError):
    """A macro instruction that cannot be applied, stated rather than guessed."""


@dataclass(frozen=True)
class Variable:
    """One macro variable and its declared What-If sensitivity."""

    key: str
    name: str
    #: What the variable is measured in, for the screen.
    unit: str
    #: The size of one ADVERSE unit, in that measure. Negative where an adverse
    #: move is a fall (GDP, oil, equities, house prices).
    adverse_unit: float
    #: How to say one adverse unit in a sentence.
    adverse_label: str
    #: PD multiplier per adverse unit.
    pd_multiplier: float
    #: LGD change, in percentage points, per adverse unit.
    lgd_change_pp: float
    #: The dataset column carrying the observed level, where one exists.
    column: str = ""
    note: str = ""

    @property
    def falls_when_adverse(self) -> bool:
        return self.adverse_unit < 0

    def units_for(self, magnitude: float, unit: str, *,
                  level: float | None = None) -> float:
        """How many ADVERSE units a stated magnitude amounts to.

        A relative magnitude needs the current level to become an absolute
        move: "increase unemployment by 30%" against a level of 5% is +1.5
        percentage points, never +30 percentage points. Where the variable is
        itself quoted in percent (oil, equities, house prices, FX) a relative
        magnitude IS the move and no level is needed.
        """
        said = float(magnitude)
        if unit == BASIS_POINTS:
            absolute = said / 100.0
        elif unit == ABSOLUTE_PP:
            absolute = said
        elif unit == RELATIVE:
            if self.unit == "percent":
                absolute = said
            elif level is None:
                raise MacroError(
                    f"'{self.name}' is quoted in {self.unit}, so a relative "
                    f"move of {said:g}% needs the current level to become an "
                    "absolute change. The level was not available.")
            else:
                absolute = float(level) * (said / 100.0)
        else:
            raise MacroError(f"'{unit}' is not a magnitude this engine reads.")
        if self.adverse_unit == 0:
            raise MacroError(f"'{self.name}' has no adverse unit defined.")
        return absolute / self.adverse_unit

    def pd_factor(self, units: float) -> float:
        """The PD multiplier this many adverse units implies."""
        return float(self.pd_multiplier ** float(units))

    def lgd_delta(self, units: float) -> float:
        """The LGD change, in percentage points, this many adverse units implies."""
        return float(self.lgd_change_pp * float(units))

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "unit": self.unit,
                "adverse_unit": self.adverse_unit,
                "adverse_label": self.adverse_label,
                "pd_multiplier": self.pd_multiplier,
                "lgd_change_pp": self.lgd_change_pp,
                "column": self.column, "basis": BASIS, "note": self.note,
                "direction": "falls" if self.falls_when_adverse else "rises"}


#: The ten CreditProbe V1 macro variables, in the order a screen shows them.
VARIABLES: tuple[Variable, ...] = (
    Variable("gdp_growth", "GDP Growth Rate", "percentage points",
             -1.0, "per 1pp fall", 1.10, 0.75, column="real_gdp_growth_pct",
             note="A slowdown raises default rates broadly and weakens "
                  "recoveries a little."),
    Variable("unemployment", "Unemployment Rate", "percentage points",
             1.0, "per 1pp rise", 1.12, 1.00,
             note="The strongest single PD sensitivity in the V1 set: "
                  "unemployment moves both corporate demand and the "
                  "household side of a borrower's own book."),
    Variable("house_price_index", "House Price Index", "percent",
             -10.0, "per 10% fall", 1.06, 2.50,
             note="Modest PD effect, large LGD effect: property is the "
                  "collateral, so a fall is felt in recovery rather than in "
                  "whether the borrower pays."),
    Variable("inflation", "Inflation Rate", "percentage points",
             2.0, "per 2pp rise", 1.05, 0.50,
             note="Margin compression and working-capital absorption."),
    Variable("current_account", "Current Account Balance / Deficit",
             "percentage points of GDP",
             2.0, "per 2pp deterioration", 1.03, 0.25,
             note="The weakest PD sensitivity in the set: an external "
                  "imbalance reaches a corporate book slowly."),
    Variable("equity_index", "Stock Market Index", "percent",
             -20.0, "per 20% fall", 1.05, 0.50,
             note="A confidence and collateral channel rather than a "
                  "cash-flow one."),
    Variable("policy_rate", "Policy Interest Rate", "basis points",
             200.0, "per 200 bps rise", 1.08, 0.50,
             column="policy_rate_pct",
             note="Debt service first: coverage and DSCR move before PD does."),
    Variable("fx_depreciation", "Domestic Currency / FX Depreciation", "percent",
             10.0, "per 10% depreciation", 1.05, 0.25,
             note="Reaches unhedged foreign-currency borrowers hardest."),
    Variable("oil_price", "Oil Price", "percent",
             -20.0, "per 20% fall", 1.05, 0.50, column="oil_price_usd",
             note="Sector-concentrated in reality; the V1 sensitivity is a "
                  "book-wide average and does not vary by sector."),
    Variable("credit_spread", "Corporate Credit Spread", "basis points",
             100.0, "per 100 bps widening", 1.08, 0.50,
             note="Refinancing risk: the price of rolling debt, not the "
                  "ability to service it."),
)

BY_KEY: dict[str, Variable] = {v.key: v for v in VARIABLES}

#: Spoken names a person is likely to use, mapped to the variable key.
ALIASES: dict[str, str] = {
    "gdp": "gdp_growth", "gdp growth": "gdp_growth", "growth": "gdp_growth",
    "real gdp": "gdp_growth", "recession": "gdp_growth",
    "unemployment": "unemployment", "jobless": "unemployment",
    "joblessness": "unemployment", "employment": "unemployment",
    "house prices": "house_price_index", "house price": "house_price_index",
    "hpi": "house_price_index", "property prices": "house_price_index",
    "property price": "house_price_index", "housing": "house_price_index",
    "real estate prices": "house_price_index",
    "inflation": "inflation", "cpi": "inflation", "prices": "inflation",
    "current account": "current_account", "current account deficit": "current_account",
    "external balance": "current_account", "trade balance": "current_account",
    "stock market": "equity_index", "equities": "equity_index",
    "equity": "equity_index", "equity index": "equity_index",
    "share prices": "equity_index", "tadawul": "equity_index",
    "policy rate": "policy_rate", "interest rate": "policy_rate",
    "interest rates": "policy_rate", "rates": "policy_rate",
    "base rate": "policy_rate", "saibor": "policy_rate",
    "fx": "fx_depreciation", "currency": "fx_depreciation",
    "exchange rate": "fx_depreciation", "depreciation": "fx_depreciation",
    "riyal": "fx_depreciation",
    "oil": "oil_price", "oil price": "oil_price", "crude": "oil_price",
    "brent": "oil_price", "commodity": "oil_price", "commodities": "oil_price",
    "credit spread": "credit_spread", "credit spreads": "credit_spread",
    "spread": "credit_spread", "spreads": "credit_spread",
    "corporate spread": "credit_spread",
}


def variable(key: str) -> Variable | None:
    """The variable a key or spoken name refers to."""
    said = str(key or "").strip().lower()
    if said in BY_KEY:
        return BY_KEY[said]
    aliased = ALIASES.get(said)
    return BY_KEY.get(aliased) if aliased else None


def resolve(name: str) -> Variable:
    """The variable, or a refusal that names what this engine does carry."""
    found = variable(name)
    if found is None:
        raise MacroError(
            f"'{name}' is not one of the macroeconomic variables this What-If "
            "engine carries. They are: "
            + ", ".join(v.name for v in VARIABLES) + ".")
    return found


def apply_pd(pd_pct: pd.Series | np.ndarray, factor: float) -> np.ndarray:
    """A PD series moved by a macro factor, capped into a probability."""
    values = pd.to_numeric(pd.Series(pd_pct), errors="coerce").fillna(0.0).to_numpy()
    return np.clip(values * float(factor), PD_FLOOR_PCT, PD_CEILING_PCT)


def apply_lgd(lgd_pct: pd.Series | np.ndarray, delta_pp: float) -> np.ndarray:
    """An LGD series moved by a macro change, capped into a loss rate."""
    values = pd.to_numeric(pd.Series(lgd_pct), errors="coerce").fillna(0.0).to_numpy()
    return np.clip(values + float(delta_pp), LGD_FLOOR_PCT, LGD_CEILING_PCT)


@dataclass(frozen=True)
class Applied:
    """One macro variable, moved, with the arithmetic a reader can check."""

    variable: Variable
    magnitude: float
    unit: str
    units: float
    pd_factor: float
    lgd_delta_pp: float
    level: float | None = None

    def describe(self) -> str:
        direction = "adverse" if self.units >= 0 else "favourable"
        return (f"{self.variable.name} {self.magnitude:+g}"
                f"{'%' if self.unit == RELATIVE else ''} "
                f"({self.units:+.2f} {direction} units of "
                f"{self.variable.adverse_label.replace('per ', '')}): "
                f"PD x{self.pd_factor:.4f}, LGD {self.lgd_delta_pp:+.2f}pp")

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.variable.key, "name": self.variable.name,
                "magnitude": self.magnitude, "unit": self.unit,
                "adverse_units": round(self.units, 4),
                "pd_factor": round(self.pd_factor, 6),
                "lgd_delta_pp": round(self.lgd_delta_pp, 4),
                "observed_level": self.level,
                "rule": self.variable.adverse_label,
                "basis": BASIS, "description": self.describe()}


def applied(name: str, magnitude: float, unit: str = ABSOLUTE_PP, *,
            level: float | None = None) -> Applied:
    """Work out what one macro instruction does, without touching a book."""
    found = resolve(name)
    units = found.units_for(magnitude, unit, level=level)
    return Applied(variable=found, magnitude=float(magnitude), unit=unit,
                   units=units, pd_factor=found.pd_factor(units),
                   lgd_delta_pp=found.lgd_delta(units), level=level)


def combined(shocks: list[Applied]) -> tuple[float, float]:
    """The joint PD factor and LGD change of several macro moves.

    PD factors multiply and LGD changes add, which is the same composition rule
    the rest of the engine uses, so a macro shock and a direct PD shock compose
    the same way whichever order they arrive in.
    """
    factor = 1.0
    delta = 0.0
    for shock in shocks:
        factor *= shock.pd_factor
        delta += shock.lgd_delta_pp
    return factor, delta


def levels(macro: pd.DataFrame | None, period: str = "") -> dict[str, float]:
    """The observed level of each variable, where the book publishes one.

    Only three of the ten are carried by `corporate_macro`. The rest have no
    observed level in this installation, and the screen says so rather than
    inventing a number to put under a heading.
    """
    if macro is None or macro.empty:
        return {}
    frame = macro
    if period and "period" in frame.columns:
        chosen = frame[frame["period"].astype(str) == str(period)]
        frame = chosen if not chosen.empty else frame.tail(1)
    else:
        frame = frame.tail(1)
    row = frame.iloc[-1]
    out: dict[str, float] = {}
    for found in VARIABLES:
        if found.column and found.column in frame.columns:
            try:
                out[found.key] = float(row[found.column])
            except (TypeError, ValueError):
                continue
    return out


def history(macro: pd.DataFrame | None) -> dict[str, list[dict[str, Any]]]:
    """The recent path of each variable the book publishes, for a mini chart."""
    if macro is None or macro.empty or "period" in macro.columns is False:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for found in VARIABLES:
        if not found.column or found.column not in macro.columns:
            continue
        rows = []
        for _, row in macro.iterrows():
            try:
                rows.append({"period": str(row["period"]),
                             "value": float(row[found.column])})
            except (TypeError, ValueError, KeyError):
                continue
        if rows:
            out[found.key] = rows
    return out


def describe(macro: pd.DataFrame | None = None, period: str = "") -> dict[str, Any]:
    """The macro matrix as a reader can check it."""
    observed = levels(macro, period)
    paths = history(macro)
    return {
        "owner": MACRO_OWNER,
        "version": MACRO_VERSION,
        "effective": MACRO_EFFECTIVE,
        "basis": BASIS,
        "count": len(VARIABLES),
        "observed_period": period,
        "limitation": (
            "The observed macro series in this installation are generated from "
            "a single latent cycle factor, so oil, GDP growth and the policy "
            "rate move together by construction. The sensitivities below are "
            "declared assumptions, not relationships estimated from that data."),
        "variables": [
            {**v.to_dict(),
             "observed_level": observed.get(v.key),
             "has_observed_level": v.key in observed,
             "history": paths.get(v.key, [])}
            for v in VARIABLES],
    }


__all__ = [
    "ABSOLUTE_PP", "ALIASES", "Applied", "BASIS", "BASIS_POINTS", "BY_KEY",
    "LGD_CEILING_PCT", "LGD_FLOOR_PCT", "MACRO_EFFECTIVE", "MACRO_OWNER",
    "MACRO_VERSION", "MacroError", "PD_CEILING_PCT", "PD_FLOOR_PCT",
    "RELATIVE", "VARIABLES", "Variable", "applied", "apply_lgd", "apply_pd",
    "combined", "describe", "history", "levels", "resolve", "variable",
]
