"""
The canonical value, the display value, and who is allowed to choose.

The defect this exists for
--------------------------
A live run computed exposure at default by sector, correctly, and then had
its answer refused:

    asserted  40599.17
    canonical 40599.1736630513815

The analyst did the right thing. `40,599.17` is how a credit officer writes
that number, and `40,599.1736630513815` is not. What refused it was a
validator that compared the two at a relative tolerance of 1e-9 -- a bound
written to "absorb a decimal string the analyst rounded", which it does not:
rounding a five-digit figure to two places moves it by about 9e-8 relative,
nearly a hundred times that bound. The comment was wrong and the number
proved it.

The fix is not a wider tolerance. A wider tolerance buys presentation at the
cost of arithmetic, and at 1e-6 a genuinely wrong figure starts to pass.
What is needed is the distinction the old contract never drew:

    CANONICAL   the full-precision value CreditProbe computed from the
                executed evidence. It is the truth and it is never rounded
                away -- it is what gets stored and recomputed against.

    DISPLAY     the value a person reads. It is the canonical value
                quantized to a precision this module allows, by a rounding
                mode this module fixes.

An asserted figure is valid when it is one of exactly two things: the
canonical value, or the canonical value correctly rounded for display.
Anything else -- including a number that happens to round to the right
answer, like 40599.1699 -- is refused, because "rounds to something correct"
is not the same as "is correct".

Who owns precision
------------------
CreditProbe does. The analyst declares what it INTENDS, and this module says
whether that intent is permitted for the unit in question. A claim cannot
widen its own tolerance by declaring a coarser precision, and precision is
never inferred from a claim's name -- `total_ead` and `ead_share` are told
apart by their units, not by their spelling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

#: Business rounding, stated once. Decimal's default is ROUND_HALF_EVEN,
#: which rounds 0.125 to 0.12 -- correct for statistics and wrong for a
#: figure in a credit paper, where half goes up.
ROUNDING = ROUND_HALF_UP

# ---- unit classes ------------------------------------------------------

MONEY = "money"
PERCENT = "percent"
PERCENTAGE_POINT = "percentage_point"
RATIO = "ratio"
COUNT = "count"
CATEGORICAL = "categorical"
UNKNOWN = "unknown"

#: The reporting currency of the V4 demonstration book. A Saudi corporate
#: portfolio, quoted the way a Saudi credit paper quotes one.
CURRENCY = "SAR"
AMOUNT_SCALE = "million"

#: How an amount is written. One style, used everywhere.
MONEY_UNIT = "SAR million"

#: Scale words that are legitimate for money, and the multiplier each
#: implies relative to the canonical scale. A figure in SAR million
#: presented as SAR billion is a thousand-fold error if the number is not
#: also divided, so the pair is checked together and never assumed.
MONEY_SCALES: dict[str, Decimal] = {
    "": Decimal(1),
    "million": Decimal(1), "mn": Decimal(1), "m": Decimal(1),
    "billion": Decimal(1000), "bn": Decimal(1000), "b": Decimal(1000),
    "thousand": Decimal("0.001"), "k": Decimal("0.001"),
}

_MONEY = re.compile(
    r"^(?P<currency>[A-Za-z]{3})\s*(?P<scale>million|mn|m|billion|bn|b|"
    r"thousand|k)?$", re.I)

_PERCENT_WORDS = {"percent", "%", "pct", "percentage"}
_POINT_WORDS = {"percentage point", "percentage points", "pp", "ppt",
                "basis point", "basis points", "bps"}
_RATIO_WORDS = {"ratio", "fraction", "share", "proportion", "x", "times",
                "multiple"}
_COUNT_WORDS = {"count", "borrowers", "facilities", "obligors", "accounts",
                "names", "rows", "notches"}
_CATEGORICAL_WORDS = {"stage", "ifrs9 stage", "rating", "grade", "category"}

#: Permitted display precisions per class. The first is the default. A
#: claim may declare any of them; anything else is refused with this list.
ALLOWED: dict[str, tuple[int, ...]] = {
    MONEY: (2, 0, 1, 3),
    PERCENT: (2, 0, 1, 3),
    PERCENTAGE_POINT: (2, 0, 1, 3),
    RATIO: (2, 3, 4),
    COUNT: (0,),
    CATEGORICAL: (0,),
    UNKNOWN: (2, 0, 1, 3, 4),
}


@dataclass(frozen=True)
class Unit:
    """A parsed unit: what kind of quantity, and at what scale."""

    raw: str
    kind: str
    currency: str = ""
    scale: str = ""

    @property
    def is_money(self) -> bool:
        return self.kind == MONEY

    def describe(self) -> str:
        return self.raw or self.kind


def classify(unit: str) -> Unit:
    """What kind of number is this, read from the unit and nothing else."""
    raw = str(unit or "").strip()
    lowered = raw.lower()
    if not lowered:
        return Unit(raw, UNKNOWN)
    if lowered in _PERCENT_WORDS:
        return Unit(raw, PERCENT)
    if lowered in _POINT_WORDS:
        return Unit(raw, PERCENTAGE_POINT)
    if lowered in _RATIO_WORDS:
        return Unit(raw, RATIO)
    if lowered in _COUNT_WORDS:
        return Unit(raw, COUNT)
    if lowered in _CATEGORICAL_WORDS:
        return Unit(raw, CATEGORICAL)
    match = _MONEY.match(lowered)
    if match:
        return Unit(raw, MONEY, currency=match.group("currency").upper(),
                    scale=(match.group("scale") or "").lower())
    return Unit(raw, UNKNOWN)


def allowed_precisions(unit: str) -> tuple[int, ...]:
    return ALLOWED[classify(unit).kind]


def default_precision(unit: str) -> int:
    return allowed_precisions(unit)[0]


def quantize(value: Decimal, places: int) -> Decimal:
    """The display form of a canonical value. Deterministic, half up.

    Negative zero is normalised away. A movement of -0.001 rounds to -0.00
    in IEEE and in Decimal, and "SAR -0.00 million" on a credit paper reads
    as a loss too small to name rather than as nothing -- which is worse
    than either. Zero is zero.
    """
    shown = value.quantize(Decimal(1).scaleb(-places), rounding=ROUNDING)
    return shown + Decimal(0) if shown == 0 else shown


def plain(value: Decimal) -> Decimal:
    """The same number, never in exponent notation."""
    return Decimal(format(value, "f"))


@dataclass(frozen=True)
class Verdict:
    ok: bool
    problem: str = ""
    canonical: Decimal = Decimal(0)
    display: Decimal = Decimal(0)
    precision: int = 2


def check(asserted: str, canonical: Decimal, *, unit: str,
          declared_precision: int, label: str) -> Verdict:
    """Is `asserted` this canonical value, written for a reader?

    Valid in exactly two forms: the canonical value itself, or the canonical
    value quantized to a permitted precision. A third number that merely
    rounds to the right answer is not one of them.
    """
    kind = classify(unit).kind
    permitted = ALLOWED[kind]
    if declared_precision not in permitted:
        return Verdict(
            False,
            f"{label} declares {declared_precision} decimal place"
            f"{'s' if declared_precision != 1 else ''} for a value in "
            f"{unit!r}. CreditProbe allows "
            f"{', '.join(str(p) for p in permitted)} for a "
            f"{kind.replace('_', ' ')}.")
    try:
        given = Decimal(asserted)
    except (InvalidOperation, ValueError):
        return Verdict(False, f"{label} asserts {asserted!r}, which is not a "
                              f"decimal.")

    canonical = plain(canonical)
    display = plain(quantize(canonical, declared_precision))
    if given == canonical or given == display:
        return Verdict(True, canonical=canonical, display=display,
                       precision=declared_precision)

    rounds_right = quantize(given, declared_precision) == display
    detail = (
        f" It rounds to the right figure, which is not the same as being it: "
        f"send the value CreditProbe computed, or that value rounded."
        if rounds_right else "")
    return Verdict(
        False,
        f"{label} asserts {given} and the evidence gives {canonical}, which "
        f"displays at {declared_precision}dp as {display}.{detail}",
        canonical=canonical, display=display,
        precision=declared_precision)


def format_value(value: Decimal, unit: str, places: int) -> str:
    """How the number reads once it is published."""
    parsed = classify(unit)
    shown = quantize(value, places)
    body = f"{shown:,}"
    if parsed.is_money:
        scale = parsed.scale or AMOUNT_SCALE
        pretty = {"m": "million", "mn": "million", "b": "billion",
                  "bn": "billion", "k": "thousand"}.get(scale, scale)
        return f"{parsed.currency} {body} {pretty}".strip()
    if parsed.kind == PERCENT:
        return f"{body}%"
    if parsed.kind == COUNT:
        return f"{body} {parsed.raw}".strip() if parsed.raw.lower() not in (
            "count",) else body
    return f"{body} {parsed.raw}".strip()


__all__ = ["ALLOWED", "AMOUNT_SCALE", "CATEGORICAL", "COUNT", "CURRENCY",
           "MONEY", "MONEY_SCALES", "MONEY_UNIT", "PERCENT",
           "PERCENTAGE_POINT", "RATIO", "ROUNDING", "UNKNOWN", "Unit",
           "Verdict", "allowed_precisions", "check", "classify",
           "default_precision", "format_value", "plain", "quantize"]
