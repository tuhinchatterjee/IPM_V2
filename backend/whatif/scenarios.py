"""
A scenario is an object, not a sentence.

"What happens if EBITDA falls 15% and rates rise 200 basis points?" is two
shocks with a population, a period and a set of assumptions. Holding that as a
typed object rather than as free text is what makes the answer reproducible,
comparable against another scenario, saveable, and arguable in a committee —
somebody can disagree with the SHOCK rather than with the sentence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.whatif import sensitivity as sv

# ------------------------------------------------------------- shock kinds

RATING = "rating"
PD = "pd"
LGD = "lgd"
EAD = "ead"
FINANCIAL = "financial"
COLLATERAL = "collateral"
MACRO = "macro"

#: How a magnitude is expressed. Kept explicit because "PD up 25" is ambiguous
#: and every ambiguity here becomes a number somebody cannot reconcile.
RELATIVE = "relative_pct"
ABSOLUTE_PP = "absolute_pp"
BASIS_POINTS = "basis_points"
NOTCHES = "notches"
STEPS = "steps"


@dataclass(frozen=True)
class Shock:
    """One movement, applied to one measure."""

    kind: str
    magnitude: float
    unit: str
    #: For MACRO, the sensitivity-matrix variable key. For FINANCIAL, the
    #: financial measure. Unused elsewhere.
    target: str = ""
    label: str = ""

    def describe(self) -> str:
        if self.label:
            return self.label
        if self.kind == RATING:
            direction = "downgraded" if self.magnitude > 0 else "upgraded"
            count = abs(int(self.magnitude))
            return f"{direction} by {count} notch{'es' if count != 1 else ''}"
        if self.kind == MACRO:
            found = sv.variable(self.target)
            name = found.name if found else self.target
            return f"{name} shocked by {self.magnitude:g} {found.unit if found else ''}".strip()
        if self.unit == RELATIVE:
            return f"{self.target or self.kind} {'up' if self.magnitude > 0 else 'down'} {abs(self.magnitude):g}%"
        if self.unit == ABSOLUTE_PP:
            return f"{self.target or self.kind} {'up' if self.magnitude > 0 else 'down'} {abs(self.magnitude):g}pp"
        if self.unit == BASIS_POINTS:
            return f"{self.target or self.kind} {'up' if self.magnitude > 0 else 'down'} {abs(self.magnitude):g} bps"
        return f"{self.target or self.kind} {self.magnitude:g}"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "magnitude": self.magnitude,
                "unit": self.unit, "target": self.target,
                "description": self.describe()}


@dataclass(frozen=True)
class Population:
    """Who the scenario is applied to. Empty means the whole book."""

    sectors: tuple[str, ...] = ()
    rating_bands: tuple[str, ...] = ()
    stages: tuple[int, ...] = ()
    borrower_ids: tuple[str, ...] = ()
    watchlist_only: bool = False

    @property
    def is_whole_book(self) -> bool:
        return not (self.sectors or self.rating_bands or self.stages
                    or self.borrower_ids or self.watchlist_only)

    def describe(self) -> str:
        if self.is_whole_book:
            return "the whole corporate book"
        parts = []
        if self.rating_bands:
            parts.append(f"{', '.join(self.rating_bands)} borrowers")
        if self.sectors:
            parts.append(f"in {', '.join(self.sectors)}")
        if self.stages:
            parts.append(f"in Stage {', '.join(str(s) for s in self.stages)}")
        if self.borrower_ids:
            parts.append(f"{len(self.borrower_ids)} named borrowers")
        if self.watchlist_only:
            parts.append("on the watchlist")
        return " ".join(parts) or "the whole corporate book"

    def to_dict(self) -> dict[str, Any]:
        return {"sectors": list(self.sectors),
                "rating_bands": list(self.rating_bands),
                "stages": list(self.stages),
                "borrower_ids": list(self.borrower_ids),
                "watchlist_only": self.watchlist_only,
                "description": self.describe()}


@dataclass(frozen=True)
class Assumptions:
    """The judgement calls a scenario makes, stated rather than buried."""

    #: Re-evaluate the governed SICR triggers against the stressed PD. On by
    #: default: a scenario that moves PD and leaves every Stage where it was is
    #: not a scenario, it is a multiplication.
    reevaluate_sicr: bool = True
    #: Move a borrower into Stage 2 on a rating deterioration alone, even where
    #: the PD triggers do not fire. OFF by default, because a notch is not a
    #: governed SICR trigger in this policy and turning it on is a decision
    #: somebody has to make.
    rating_deterioration_sicr: bool = False
    #: How many notches of deterioration that assumption needs.
    rating_sicr_notches: int = 2
    #: Let collateral shocks flow into LGD.
    collateral_to_lgd: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "reevaluate_sicr": self.reevaluate_sicr,
            "rating_deterioration_sicr": self.rating_deterioration_sicr,
            "rating_sicr_notches": self.rating_sicr_notches,
            "collateral_to_lgd": self.collateral_to_lgd,
        }


@dataclass(frozen=True)
class Scenario:
    """A named, versioned, reproducible set of shocks."""

    key: str
    name: str
    shocks: tuple[Shock, ...] = ()
    population: Population = field(default_factory=Population)
    assumptions: Assumptions = field(default_factory=Assumptions)
    severity: str = "custom"
    rationale: str = ""
    period: str = ""

    def describe(self) -> str:
        if not self.shocks:
            return "no shock (the reported position)"
        return "; ".join(shock.describe() for shock in self.shocks)

    def shocks_of(self, kind: str) -> tuple[Shock, ...]:
        return tuple(s for s in self.shocks if s.kind == kind)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "severity": self.severity,
                "rationale": self.rationale, "period": self.period,
                "shocks": [s.to_dict() for s in self.shocks],
                "population": self.population.to_dict(),
                "assumptions": self.assumptions.to_dict(),
                "description": self.describe()}


# ------------------------------------------------------- preconfigured set
#
# Twelve scenarios a committee would recognise. Each one runs against the live
# book and produces real figures; none of them is a placeholder.

def _s(key: str, name: str, severity: str, rationale: str,
       shocks: tuple[Shock, ...], population: Population | None = None,
       assumptions: Assumptions | None = None) -> Scenario:
    return Scenario(key=key, name=name, severity=severity, rationale=rationale,
                    shocks=shocks, population=population or Population(),
                    assumptions=assumptions or Assumptions())


PRECONFIGURED: tuple[Scenario, ...] = (
    _s("base", "Base — reported position", "base",
       "The book as reported, for comparison. Every other scenario is measured "
       "against this.", ()),
    _s("downgrade_one_notch", "One-notch corporate downgrade", "mild",
       "A broad deterioration in credit quality across the corporate book, "
       "without a specific macro cause.",
       (Shock(RATING, 1, NOTCHES),)),
    _s("downgrade_bbb_two", "Two-notch BBB downgrade", "moderate",
       "The crossover band deteriorates. BBB is where a downgrade starts "
       "moving names towards sub-investment grade and towards Stage 2.",
       (Shock(RATING, 2, NOTCHES),),
       Population(rating_bands=("BBB",))),
    _s("pd_up_25", "12-month PD up 25%", "mild",
       "A model or calibration shift raising PD across the book by a quarter.",
       (Shock(PD, 25.0, RELATIVE),)),
    _s("pd_up_50", "12-month PD up 50%", "moderate",
       "A sharper PD deterioration, at the level where SICR triggers begin to "
       "fire on their own.",
       (Shock(PD, 50.0, RELATIVE),)),
    _s("rates_200bp", "Policy rates up 200 bps", "moderate",
       "A tightening cycle. Debt-service capacity compresses first, and the "
       "leveraged and long-duration sectors carry it.",
       (Shock(MACRO, 200.0, BASIS_POINTS, target="rates"),)),
    _s("ebitda_rates", "EBITDA down 15% with rates up 200 bps", "severe",
       "Earnings compression and a tightening cycle together — the combination "
       "that moves interest coverage and DSCR at the same time.",
       (Shock(FINANCIAL, -15.0, RELATIVE, target="ebitda"),
        Shock(MACRO, 200.0, BASIS_POINTS, target="rates"))),
    _s("collateral_down_20", "Collateral values down 20%", "moderate",
       "A property and security-value correction. The loss given default rises "
       "even where the borrower's own position is unchanged.",
       (Shock(COLLATERAL, -20.0, RELATIVE),)),
    _s("shipping_disruption", "Shipping and logistics disruption", "severe",
       "Route closure and freight-rate volatility, with the working-capital "
       "consequences that follow for carriers and their customers.",
       (Shock(MACRO, 2.0, STEPS, target="shipping_disruption"),)),
    _s("oil_downside", "Oil and commodity downside", "severe",
       "A 40% fall in hydrocarbon prices, reaching producers directly and the "
       "wider economy through public spending.",
       (Shock(MACRO, -40.0, RELATIVE, target="oil"),)),
    _s("severe_combined", "Severe combined corporate stress", "severe",
       "The board-level downside: a downgrade cycle, a demand shock, a "
       "tightening cycle and a collateral correction at once.",
       (Shock(RATING, 1, NOTCHES),
        Shock(MACRO, -2.0, ABSOLUTE_PP, target="gdp"),
        Shock(MACRO, 200.0, BASIS_POINTS, target="rates"),
        Shock(COLLATERAL, -15.0, RELATIVE)),
       None,
       Assumptions(rating_deterioration_sicr=True, rating_sicr_notches=1)),
    _s("stage2_sensitivity", "Stage 2 migration sensitivity", "moderate",
       "How much PD deterioration the Stage 1 book absorbs before the governed "
       "SICR triggers move it. Applied to Stage 1 only.",
       (Shock(PD, 75.0, RELATIVE),),
       Population(stages=(1,))),
    _s("utilisation_drawdown", "High-utilisation drawdown stress", "moderate",
       "Committed but undrawn limits are drawn as liquidity tightens, raising "
       "exposure at default without any change in credit quality.",
       (Shock(EAD, 15.0, RELATIVE),)),
)

BY_KEY: dict[str, Scenario] = {s.key: s for s in PRECONFIGURED}


def scenario(key: str) -> Scenario | None:
    return BY_KEY.get(str(key or "").strip().lower())


def catalogue() -> list[dict[str, Any]]:
    return [s.to_dict() for s in PRECONFIGURED]


__all__ = [
    "ABSOLUTE_PP", "Assumptions", "BASIS_POINTS", "BY_KEY", "COLLATERAL",
    "EAD", "FINANCIAL", "LGD", "MACRO", "NOTCHES", "PD", "PRECONFIGURED",
    "RATING", "RELATIVE", "STEPS", "Population", "Scenario", "Shock",
    "catalogue", "scenario",
]
