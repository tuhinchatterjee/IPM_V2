"""
The deterministic calculator. Playbook §7.

Every number a Playbook document states must be traceable to something that is
not a language model. This module is that something: a small set of credit-risk
arithmetic operations, each returning not just a value but the formula, the
inputs, their locators, the rounding convention and — where a ratio is involved
— the denominator, because "coverage rose 8 basis points" is unreviewable
without knowing what it was divided by.

Why the unit vocabulary is closed
---------------------------------
The single most common way a credit report becomes wrong is a unit slip:
a percentage-point change reported as a percentage change, a basis-point move
described as a percent, a SAR million figure printed as SAR. These are not
rounding disagreements — they are order-of-magnitude errors that survive review
because both numbers look plausible.

So a unit here is a value, not a label. `PERCENT` and `PERCENTAGE_POINT` are
different units and no operation silently converts one into the other;
`pp_change` and `percent_change` are different functions because they answer
different questions, and asking for the wrong one is a mistake a reviewer can
see rather than one buried in prose.

Nothing in this module imports a provider, and nothing in it is reachable from
one. The model may read a Calculation; it may not produce one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

#: A pure count.
COUNT = "count"
#: An amount of money. `scale` carries "million" and friends.
CURRENCY = "currency"
#: A proportion expressed out of 100. 2.09 means 2.09%.
PERCENT = "percent"
#: A DIFFERENCE between two percentages. 0.08 pp is not 0.08%.
PERCENTAGE_POINT = "percentage_point"
#: One hundredth of a percentage point. 7.86 bps is 0.0786 pp.
BASIS_POINT = "basis_point"
#: A dimensionless multiplier, e.g. a scenario weight.
RATIO = "ratio"

UNITS = (COUNT, CURRENCY, PERCENT, PERCENTAGE_POINT, BASIS_POINT, RATIO)


class CalculationError(ValueError):
    """The arithmetic could not be performed on the values supplied.

    Raised rather than returned, because every caller does the same thing with
    it — records that the figure is unavailable and says so in the document
    instead of printing something plausible.
    """


@dataclass(frozen=True)
class Input:
    """One value entering a calculation, and where it came from.

    `locator` is what makes a figure reviewable: `xlsx://ECL!B12`,
    `export://41/rev/2#table.ecl_by_scenario`, `docx://para/17`. A value with no
    locator is permitted only for a weight or constant supplied by the
    methodology itself, and then `origin` says so.
    """

    name: str
    value: Decimal
    unit: str
    locator: str = ""
    #: "source" | "export" | "methodology" | "derived"
    origin: str = "source"
    scale: str = ""

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise CalculationError(f"unknown unit {self.unit!r}")


@dataclass(frozen=True)
class Calculation:
    """A number, and everything needed to defend it.

    This is what gets persisted alongside a change item and what the grounding
    check reconciles drafted prose against. `formula` is written for a human
    reviewer, not for evaluation.
    """

    name: str
    value: Decimal
    unit: str
    formula: str
    inputs: tuple[Input, ...] = ()
    scale: str = ""
    #: Decimal places the value should be PRESENTED with. Kept separate from the
    #: value, so rounding is a display decision and never silently compounds
    #: through a chain of calculations.
    dp: int = 2
    #: For any ratio: what it was divided by. A coverage ratio whose denominator
    #: is unstated is a number nobody can check.
    denominator: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def rounded(self) -> Decimal:
        return _round(self.value, self.dp)

    def as_dict(self) -> dict:
        """The persisted form. Decimals become strings, never floats — a float
        here would reintroduce exactly the drift this module exists to remove.
        """
        return {
            "name": self.name,
            "value": str(self.value),
            "rounded": str(self.rounded),
            "unit": self.unit,
            "scale": self.scale,
            "dp": self.dp,
            "formula": self.formula,
            "denominator": self.denominator,
            "notes": list(self.notes),
            "inputs": [
                {
                    "name": i.name,
                    "value": str(i.value),
                    "unit": i.unit,
                    "scale": i.scale,
                    "locator": i.locator,
                    "origin": i.origin,
                }
                for i in self.inputs
            ],
        }


def dec(value: object) -> Decimal:
    """Coerce to Decimal, refusing what cannot be trusted as a number.

    A spreadsheet cell holding the formula string "=B4*C4" with no cached value
    is not a result, and neither is "n/a" or an empty cell. Those arrive here as
    strings and are refused, rather than becoming 0.0 and quietly reducing a
    total.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise CalculationError("a boolean is not a credit-risk figure")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # str() of a float is its shortest round-tripping form, which keeps
        # 19.2 as 19.2 rather than 19.199999999999999.
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace(" ", "")
        if text.startswith("="):
            raise CalculationError(
                "a formula string is not a computed value — read the cached "
                "result or report the figure as unavailable"
            )
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise CalculationError(f"{value!r} is not a number") from exc
    raise CalculationError(f"cannot read {type(value).__name__} as a number")


def _round(value: Decimal, dp: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-dp))


def _same_unit(a: Input, b: Input, op: str) -> None:
    if a.unit != b.unit:
        raise CalculationError(
            f"cannot {op} {a.unit} and {b.unit} — these are different units"
        )
    if a.scale != b.scale:
        raise CalculationError(
            f"cannot {op} values at different scales ({a.scale or 'unscaled'} "
            f"vs {b.scale or 'unscaled'})"
        )


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


def weighted(components: list[Input], weights: list[Input], *, name: str,
             dp: int = 2) -> Calculation:
    """A probability-weighted figure, e.g. scenario-weighted ECL.

    The weights are checked to sum to one. A scenario set whose weights sum to
    0.95 is a methodology error, and computing a confident weighted average over
    it would hide the error inside a number that looks fine.
    """
    if len(components) != len(weights):
        raise CalculationError(
            f"{len(components)} components but {len(weights)} weights"
        )
    if not components:
        raise CalculationError("no components to weight")

    total_weight = sum((w.value for w in weights), Decimal(0))
    if _round(total_weight, 6) != Decimal("1.000000"):
        raise CalculationError(
            f"scenario weights sum to {total_weight}, not 1 — refusing to "
            "report a weighted figure over an incomplete scenario set"
        )
    unit, scale = components[0].unit, components[0].scale
    for c in components[1:]:
        _same_unit(components[0], c, "weight together")

    value = sum(
        (c.value * w.value for c, w in zip(components, weights, strict=True)),
        Decimal(0),
    )
    terms = " + ".join(
        f"{w.name} × {c.name}" for c, w in zip(components, weights, strict=True)
    )
    return Calculation(
        name=name,
        value=value,
        unit=unit,
        scale=scale,
        dp=dp,
        formula=terms,
        inputs=tuple(components) + tuple(weights),
    )


def delta(prior: Input, current: Input, *, name: str, dp: int = 2) -> Calculation:
    """Absolute movement, in the unit of the inputs."""
    _same_unit(prior, current, "difference")
    return Calculation(
        name=name,
        value=current.value - prior.value,
        unit=current.unit,
        scale=current.scale,
        dp=dp,
        formula=f"{current.name} − {prior.name}",
        inputs=(prior, current),
    )


def percent_change(prior: Input, current: Input, *, name: str,
                   dp: int = 2) -> Calculation:
    """Relative movement, as a PERCENT of the prior value.

    Returns PERCENT, never PERCENTAGE_POINT. If the inputs are themselves
    percentages, this is the percent change *of* a percentage — which is a
    different statement from the percentage-point change and is why `pp_change`
    exists separately.
    """
    _same_unit(prior, current, "compare")
    if prior.value == 0:
        raise CalculationError(
            f"{prior.name} is zero — a percentage change from zero is undefined"
        )
    value = (current.value - prior.value) / prior.value * Decimal(100)
    return Calculation(
        name=name,
        value=value,
        unit=PERCENT,
        dp=dp,
        formula=f"({current.name} − {prior.name}) ÷ {prior.name} × 100",
        inputs=(prior, current),
        denominator=prior.name,
    )


def pp_change(prior: Input, current: Input, *, name: str,
              dp: int = 2) -> Calculation:
    """Movement between two percentages, in PERCENTAGE POINTS."""
    for i in (prior, current):
        if i.unit != PERCENT:
            raise CalculationError(
                f"{i.name} is {i.unit}; a percentage-point change is only "
                "defined between two percentages"
            )
    return Calculation(
        name=name,
        value=current.value - prior.value,
        unit=PERCENTAGE_POINT,
        dp=dp,
        formula=f"{current.name} − {prior.name}",
        inputs=(prior, current),
    )


def bps_change(prior: Input, current: Input, *, name: str,
               dp: int = 1) -> Calculation:
    """The same movement as `pp_change`, expressed in basis points."""
    pp = pp_change(prior, current, name=name, dp=dp)
    return Calculation(
        name=name,
        value=pp.value * Decimal(100),
        unit=BASIS_POINT,
        dp=dp,
        formula=f"({current.name} − {prior.name}) × 100",
        inputs=(prior, current),
    )


def ratio(numerator: Input, denominator: Input, *, name: str,
          dp: int = 2, as_percent: bool = True) -> Calculation:
    """A ratio such as a coverage ratio, with its denominator recorded."""
    if denominator.value == 0:
        raise CalculationError(f"{denominator.name} is zero — ratio undefined")
    if numerator.scale != denominator.scale:
        raise CalculationError(
            f"cannot divide {numerator.scale or 'unscaled'} by "
            f"{denominator.scale or 'unscaled'} without a stated conversion"
        )
    raw = numerator.value / denominator.value
    return Calculation(
        name=name,
        value=raw * Decimal(100) if as_percent else raw,
        unit=PERCENT if as_percent else RATIO,
        dp=dp,
        formula=(
            f"{numerator.name} ÷ {denominator.name}"
            + (" × 100" if as_percent else "")
        ),
        inputs=(numerator, denominator),
        denominator=denominator.name,
    )
