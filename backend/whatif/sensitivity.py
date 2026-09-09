"""
The macro sensitivity matrix: what a macro shock does to a credit measure.

What this is, and what it is not
--------------------------------
This is a CONFIGURED management assumption set, owned and versioned, of the
form "a 100 basis point rise in policy rates raises corporate PD by 12% and
raises Shipping PD by 20%". It is what lets a credit officer ask "what happens
if rates rise 200 basis points" and get a number rather than a shrug.

It is NOT an econometric model and it is NOT a regulatory calibration. Nothing
here was estimated from historical default data, and the module says so in the
answer rather than in a footnote. Presenting a configured coefficient as an
empirical fact is the failure mode that discredits every honest figure beside
it, so each row carries its own basis.

Sector sensitivities are coherent rather than arbitrary
-------------------------------------------------------
Shipping is more exposed to trade volumes, fuel and working capital than Real
Estate is; Real Estate is more exposed to property values and rates than
Shipping is. The matrix reflects that, and where a sector has no distinct
sensitivity to a variable it inherits the portfolio-wide one rather than
carrying an invented number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MATRIX_OWNER = "Credit Risk Analytics"
MATRIX_VERSION = "1.0.0"
MATRIX_EFFECTIVE = "2026-01-01"

#: How each coefficient was arrived at. Every row carries one of these, and
#: none of them says "estimated from default data", because none of them was.
BASIS_MANAGEMENT = ("Management assumption, set by the threshold owner and "
                    "reviewed with the scenario. Not an econometric estimate.")
BASIS_STRUCTURAL = ("Structural: the transmission follows directly from how "
                    "the measure is defined, not from a fitted relationship.")


@dataclass(frozen=True)
class Variable:
    """One macro variable a scenario can shock."""

    key: str
    name: str
    unit: str
    #: The size of shock the coefficients below are quoted per.
    step: float
    step_label: str
    #: Relative change in 12-month PD per one `step` of shock, portfolio-wide.
    pd_effect: float
    #: Change in LGD, in percentage points, per one `step`.
    lgd_effect_pp: float = 0.0
    #: Relative change in the named financial measures per one `step`.
    financial_effects: dict[str, float] = field(default_factory=dict)
    #: Sector multipliers on the PD effect. A sector absent here is 1.0.
    sector_pd_multipliers: dict[str, float] = field(default_factory=dict)
    basis: str = BASIS_MANAGEMENT
    note: str = ""

    def pd_effect_for(self, sector: str) -> float:
        return self.pd_effect * self.sector_pd_multipliers.get(str(sector), 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "variable": self.name, "unit": self.unit,
            "shock_unit": self.step_label,
            "pd_effect_pct_per_step": round(self.pd_effect * 100, 2),
            "lgd_effect_pp_per_step": round(self.lgd_effect_pp, 3),
            "financial_effects": {k: round(v * 100, 2)
                                  for k, v in self.financial_effects.items()},
            "sector_sensitivity": {k: round(v, 2)
                                   for k, v in self.sector_pd_multipliers.items()},
            "basis": self.basis, "note": self.note,
            "owner": MATRIX_OWNER, "version": MATRIX_VERSION,
            "effective_date": MATRIX_EFFECTIVE,
        }


#: The configured matrix. Sector names must match the governed sector
#: vocabulary; a reconciliation test asserts they do.
VARIABLES: tuple[Variable, ...] = (
    Variable(
        key="rates", name="Policy interest rates", unit="basis points",
        step=100.0, step_label="per 100 bps",
        pd_effect=0.06, lgd_effect_pp=0.0,
        financial_effects={"interest_coverage": -0.055, "dscr": -0.050,
                           "free_cash_flow": -0.040},
        sector_pd_multipliers={
            "Real Estate": 1.9, "Contracting": 1.6,
            "Hospitality & Tourism": 1.4, "Transport & Logistics": 1.3,
            "Shipping": 1.3, "Wholesale & Retail Trade": 1.1,
            "Financial Services": 1.2, "Telecommunications": 1.1,
            "Utilities": 0.7, "Government-Related Entities": 0.5},
        note="Higher funding cost compresses debt-service capacity first and "
             "credit quality second. Leveraged and long-duration sectors feel "
             "it hardest."),
    Variable(
        key="gdp", name="Real GDP growth", unit="percentage points",
        step=-1.0, step_label="per 1pp fall",
        pd_effect=0.10,
        financial_effects={"revenue": -0.020, "ebitda": -0.035},
        sector_pd_multipliers={
            "Wholesale & Retail Trade": 1.5, "Contracting": 1.4,
            "Hospitality & Tourism": 1.4, "Manufacturing": 1.3,
            "Transport & Logistics": 1.3, "Shipping": 1.2,
            "Mining & Metals": 1.2, "Agriculture & Food": 0.8,
            "Healthcare": 0.6, "Education": 0.6, "Utilities": 0.5,
            "Government-Related Entities": 0.4},
        note="A demand shock reaches cyclical sectors first."),
    Variable(
        key="inflation", name="Inflation", unit="percentage points",
        step=1.0, step_label="per 1pp rise",
        pd_effect=0.035,
        financial_effects={"ebitda_margin": -0.030, "working_capital": 0.025},
        sector_pd_multipliers={
            "Wholesale & Retail Trade": 1.4, "Manufacturing": 1.3,
            "Contracting": 1.3, "Agriculture & Food": 1.3,
            "Hospitality & Tourism": 1.2, "Utilities": 0.8,
            "Government-Related Entities": 0.7},
        note="Input-cost pass-through is incomplete in contracted sectors, so "
             "margin absorbs it."),
    Variable(
        key="fx", name="Riyal-adverse FX move", unit="percent",
        step=10.0, step_label="per 10% adverse move",
        pd_effect=0.045,
        financial_effects={"ebitda": -0.030},
        sector_pd_multipliers={
            "Shipping": 1.6, "Transport & Logistics": 1.4,
            "Wholesale & Retail Trade": 1.3, "Manufacturing": 1.2,
            "Agriculture & Food": 1.2, "Real Estate": 0.6,
            "Government-Related Entities": 0.5},
        note="Import-dependent and foreign-currency-revenue sectors carry the "
             "exposure."),
    Variable(
        key="oil", name="Oil and commodity prices", unit="percent",
        step=-20.0, step_label="per 20% fall",
        pd_effect=0.07,
        financial_effects={"revenue": -0.030, "ebitda": -0.055},
        sector_pd_multipliers={
            "Oil & Gas": 2.4, "Petrochemicals": 2.1, "Mining & Metals": 1.9,
            "Government-Related Entities": 1.3, "Contracting": 1.2,
            "Manufacturing": 1.2, "Utilities": 0.8, "Healthcare": 0.5,
            "Education": 0.5},
        note="A price fall reaches producers directly and the wider economy "
             "through public spending."),
    Variable(
        key="property", name="Property and collateral values", unit="percent",
        step=-10.0, step_label="per 10% fall",
        pd_effect=0.03, lgd_effect_pp=3.5,
        financial_effects={},
        sector_pd_multipliers={
            "Real Estate": 2.2, "Contracting": 1.8,
            "Hospitality & Tourism": 1.4, "Wholesale & Retail Trade": 1.1},
        basis=BASIS_STRUCTURAL,
        note="The LGD effect is structural: a lower security value recovers "
             "less. The PD effect is a management assumption about the "
             "borrower's own balance sheet."),
    Variable(
        key="shipping_disruption", name="Shipping and logistics disruption",
        unit="severity index", step=1.0, step_label="per severity step",
        pd_effect=0.14,
        financial_effects={"revenue": -0.045, "ebitda": -0.070,
                           "working_capital": 0.060,
                           "cash_conversion_cycle_days": 0.080},
        sector_pd_multipliers={
            "Shipping": 2.5, "Transport & Logistics": 2.2,
            "Wholesale & Retail Trade": 1.5, "Manufacturing": 1.4,
            "Agriculture & Food": 1.3, "Contracting": 1.2,
            "Healthcare": 0.7, "Real Estate": 0.4,
            "Government-Related Entities": 0.6},
        note="Route closure and freight-rate volatility hit carriers and their "
             "working capital before anyone else's."),
    Variable(
        key="sector_stress", name="Sector-specific deterioration",
        unit="severity index", step=1.0, step_label="per severity step",
        pd_effect=0.12,
        financial_effects={"ebitda": -0.050},
        note="A general deterioration applied to a named sector, for scenarios "
             "that have a view on one industry rather than the macro."),
)

BY_KEY: dict[str, Variable] = {v.key: v for v in VARIABLES}


def variable(key: str) -> Variable | None:
    return BY_KEY.get(str(key or "").strip().lower())


def matrix_rows() -> list[dict[str, Any]]:
    """The whole matrix, one row per variable, for the configuration screen."""
    return [v.to_dict() for v in VARIABLES]


def sectors_named() -> tuple[str, ...]:
    """Every sector the matrix carries a coefficient for."""
    out: set[str] = set()
    for entry in VARIABLES:
        out.update(entry.sector_pd_multipliers)
    return tuple(sorted(out))


def describe() -> dict[str, Any]:
    return {
        "owner": MATRIX_OWNER,
        "version": MATRIX_VERSION,
        "effective_date": MATRIX_EFFECTIVE,
        "variables": matrix_rows(),
        "sectors": list(sectors_named()),
        "statement": (
            "These are configured management assumptions with an owner and a "
            "version, not econometric estimates and not a regulatory "
            "calibration. Each row states its own basis, and a scenario "
            "answer reports the version it used."),
    }


__all__ = [
    "BASIS_MANAGEMENT", "BASIS_STRUCTURAL", "BY_KEY", "MATRIX_EFFECTIVE",
    "MATRIX_OWNER", "MATRIX_VERSION", "VARIABLES", "Variable", "describe",
    "matrix_rows", "sectors_named", "variable",
]
