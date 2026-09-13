"""
How a number is written for a reader. One policy, in one place.

The defect this exists for
--------------------------
Formatting was scattered. The prompt told the analyst what a credit paper
looks like, the validator decided what precision it would accept, the
frontend rendered whatever string arrived, and none of the three was the
authority. So a correct figure could be refused for being written the way a
credit officer writes it, and a run that had already executed its SQL spent
another model call to remove two decimal places.

This module is the authority. It answers three questions and nothing else:

    WHAT KIND of quantity is this?    -- from the declared unit, never the name
    HOW MANY decimals does it show?   -- from the kind
    HOW IS IT WRITTEN?                -- from the kind, the scale and the
                                         currency the release declared

Semantic class, not spelling
----------------------------
A class is read from a unit, and units come from two vocabularies that both
have to work. The CATALOGUE declares a field's unit in the release's own
terms -- `RCY`, `probability_0_1`, `fraction`, `times`, `days` -- and that is
the authoritative one, because it is a property of the data rather than of
whoever is describing it. An ANSWER declares a unit in a reader's terms --
`SAR million`, `percent`, `percentage points`. Both map here.

What is never used is the claim's NAME. `total_ead` and `ead_share` are told
apart by their units. A policy that reads names would classify `ecl_pct_of_ead`
as money because it starts with a measure.

Fraction or percent is a fact, not a convention
-----------------------------------------------
The catalogue says `pd_pit_12m` is `probability_0_1` and `lgd_pit` is
`fraction_0_1`, so a canonical PD of 0.043276 is a fraction, and 4.33% is the
same number written for a reader. The display scale is therefore part of the
class -- PROBABILITY and PERCENTAGE are different classes precisely because
one is multiplied by a hundred on the way to the page and the other is not.
Nothing here infers which from the magnitude of the value: 0.04 is a
perfectly ordinary figure in percent as well as in fractions, and guessing
between them is how a PD gets published two orders of magnitude wrong.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

#: Business rounding, stated once. Decimal's default is ROUND_HALF_EVEN,
#: which sends 0.125 to 0.12 -- right for statistics, wrong for a figure in
#: a credit paper, where half goes up.
ROUNDING = ROUND_HALF_UP

# ---- the classes -------------------------------------------------------

MONETARY_AMOUNT = "MONETARY_AMOUNT"
PERCENTAGE = "PERCENTAGE"
PROBABILITY = "PROBABILITY"
PERCENTAGE_POINT = "PERCENTAGE_POINT"
RATIO = "RATIO"
COUNT = "COUNT"
INTEGER = "INTEGER"
RATING = "RATING"
IFRS_STAGE = "IFRS_STAGE"
PERIOD = "PERIOD"
UNKNOWN = "UNKNOWN"

#: Decimal places each class shows. §14. Money is ZERO: a portfolio exposure
#: of SAR 40,599 million is how the figure appears in a credit paper, and the
#: two decimal places it used to carry were three-hundredths of a riyal on a
#: forty-billion book.
DECIMALS: dict[str, int] = {
    MONETARY_AMOUNT: 0,
    PERCENTAGE: 2,
    PROBABILITY: 2,
    PERCENTAGE_POINT: 2,
    RATIO: 2,
    COUNT: 0,
    INTEGER: 0,
    RATING: 0,
    IFRS_STAGE: 0,
    PERIOD: 0,
    UNKNOWN: 2,
}

#: What a class may declare instead of its default, when a figure genuinely
#: needs it -- a coverage ratio quoted to three places, a small movement. A
#: class not listed here permits only its default, because there is no such
#: thing as a borrower count to two decimal places.
PERMITTED: dict[str, tuple[int, ...]] = {
    MONETARY_AMOUNT: (0, 1, 2, 3),
    PERCENTAGE: (2, 0, 1, 3),
    PROBABILITY: (2, 0, 1, 3),
    PERCENTAGE_POINT: (2, 0, 1, 3),
    RATIO: (2, 3, 4, 1),
    COUNT: (0,),
    INTEGER: (0,),
    RATING: (0,),
    IFRS_STAGE: (0,),
    PERIOD: (0,),
    UNKNOWN: (2, 0, 1, 3, 4),
}

#: Classes whose canonical value is a fraction and whose display is a
#: percentage. The factor is part of the class, never inferred from the
#: value: 0.04 is an ordinary figure in both vocabularies.
DISPLAY_FACTOR: dict[str, Decimal] = {PROBABILITY: Decimal(100)}

#: Classes that are not numbers at all. A stage is 2, not 2.00, and a rating
#: is a grade.
CATEGORICAL: frozenset[str] = frozenset({RATING, IFRS_STAGE, PERIOD})

# ---- reading a class off a unit ----------------------------------------

#: The CATALOGUE's vocabulary: what the release says a field holds. This is
#: the authoritative mapping, because it describes the data rather than the
#: description.
CATALOG_UNITS: dict[str, str] = {
    "rcy": MONETARY_AMOUNT,
    "reporting_currency": MONETARY_AMOUNT,
    "amount": MONETARY_AMOUNT,
    "probability_0_1": PROBABILITY,
    "fraction_0_1": PROBABILITY,
    "fraction": PROBABILITY,
    "share": PROBABILITY,
    "rate_0_1": PROBABILITY,
    "percent": PERCENTAGE,
    "percentage": PERCENTAGE,
    "pct": PERCENTAGE,
    "times": RATIO,
    "ratio": RATIO,
    "multiple": RATIO,
    "x": RATIO,
    "days": COUNT,
    "months": COUNT,
    "years": COUNT,
    "count": COUNT,
    "notches": COUNT,
    "rank": INTEGER,
    "index": INTEGER,
}

#: An ANSWER's vocabulary: how a reader names the unit.
ANSWER_UNITS: dict[str, str] = {
    "%": PERCENTAGE,
    "percent": PERCENTAGE,
    "percentage": PERCENTAGE,
    "pct": PERCENTAGE,
    "percentage point": PERCENTAGE_POINT,
    "percentage points": PERCENTAGE_POINT,
    "pp": PERCENTAGE_POINT,
    "ppt": PERCENTAGE_POINT,
    "basis point": PERCENTAGE_POINT,
    "basis points": PERCENTAGE_POINT,
    "bps": PERCENTAGE_POINT,
    "probability": PROBABILITY,
    "fraction": PROBABILITY,
    "share": PROBABILITY,
    "proportion": PROBABILITY,
    "ratio": RATIO,
    "times": RATIO,
    "multiple": RATIO,
    "x": RATIO,
    "count": COUNT,
    "borrowers": COUNT,
    "facilities": COUNT,
    "obligors": COUNT,
    "accounts": COUNT,
    "names": COUNT,
    "rows": COUNT,
    "days": COUNT,
    "notches": COUNT,
    "amount": MONETARY_AMOUNT,
    "stage": IFRS_STAGE,
    "ifrs9 stage": IFRS_STAGE,
    "ifrs 9 stage": IFRS_STAGE,
    "rating": RATING,
    "grade": RATING,
    "quarter": PERIOD,
    "period": PERIOD,
    "date": PERIOD,
}

#: "SAR million", "USD bn", or a bare "SAR". A three-letter currency code
#: and, after a space, whatever word the release uses for its scale.
#:
#: The scale word is deliberately OPEN rather than an enumeration. Listing
#: the scale words a policy accepts means listing the ones it does not, and
#: a release denominated in a scale nobody enumerated would quietly fall to
#: the loosest precision rule instead of being read. The SPACE is what keeps
#: this honest: "notional" is one word and does not become a currency.
_MONEY = re.compile(
    r"^(?P<currency>[A-Za-z]{3})(?:\s+(?P<scale>[A-Za-z]{1,12}))?$")

_SCALE_WORD = {"m": "million", "mn": "million", "b": "billion",
               "bn": "billion", "k": "thousand"}

#: What a scale word means relative to one MILLION of the currency. Used to
#: catch a thousandfold restatement: a figure in millions presented in
#: billions is a real error if the number is not also divided, so the pair is
#: checked together. A scale this table does not know is still a valid scale
#: -- it simply cannot be compared against another one.
MONEY_SCALES: dict[str, Decimal] = {
    "": Decimal(1),
    "million": Decimal(1), "mn": Decimal(1), "m": Decimal(1),
    "billion": Decimal(1000), "bn": Decimal(1000), "b": Decimal(1000),
    "thousand": Decimal("0.001"), "k": Decimal("0.001"),
}


def classify(unit: str) -> str:
    """The semantic class of a unit. Read from the unit and nothing else."""
    raw = str(unit or "").strip().lower()
    if not raw:
        return UNKNOWN
    if raw in CATALOG_UNITS:
        return CATALOG_UNITS[raw]
    if raw in ANSWER_UNITS:
        return ANSWER_UNITS[raw]
    if _MONEY.match(raw):
        return MONETARY_AMOUNT
    return UNKNOWN


def decimals(unit: str) -> int:
    return DECIMALS[classify(unit)]


def permitted(unit: str) -> tuple[int, ...]:
    return PERMITTED[classify(unit)]


def quantize(value: Decimal, places: int) -> Decimal:
    """The display form of a canonical value. Deterministic, half up.

    Negative zero is normalised away: a movement of -0.001 rounds to -0.00,
    and "SAR -0 million" on a credit paper reads as a loss too small to name
    rather than as nothing, which is worse than either.
    """
    shown = value.quantize(Decimal(1).scaleb(-places), rounding=ROUNDING)
    return shown + Decimal(0) if shown == 0 else shown


def plain(value: Decimal) -> Decimal:
    """The same number, never in exponent notation."""
    return Decimal(format(value, "f"))


def display_value(canonical: Decimal, unit: str,
                  places: int | None = None) -> Decimal:
    """The canonical value on the reader's scale, at display precision.

    This is where a fraction becomes a percentage. `places` applies AFTER the
    scale change, so a PD at two places is 4.33% and not 0.04 turned into
    4.32760%.
    """
    kind = classify(unit)
    shown = plain(canonical) * DISPLAY_FACTOR.get(kind, Decimal(1))
    return plain(quantize(shown, DECIMALS[kind] if places is None else places))


def format_value(canonical: Decimal, unit: str,
                 places: int | None = None) -> str:
    """How the number reads once it is published."""
    kind = classify(unit)
    places = DECIMALS[kind] if places is None else places
    shown = display_value(canonical, unit, places)
    body = f"{shown:,}"

    if kind == MONETARY_AMOUNT:
        match = _MONEY.match(str(unit or "").strip().lower())
        if not match:
            # The unit says "an amount" without saying of what. Publishing a
            # bare number is honest; inventing a currency is not.
            return body
        currency = match.group("currency").upper()
        scale = (match.group("scale") or "").lower()
        return f"{currency} {body} {_SCALE_WORD.get(scale, scale)}".strip()
    if kind in (PERCENTAGE, PROBABILITY):
        return f"{body}%"
    if kind == PERCENTAGE_POINT:
        return f"{body} pp"
    if kind == RATIO:
        return f"{body}x"
    if kind in (COUNT, INTEGER):
        word = str(unit or "").strip()
        return f"{body} {word}" if word.lower() not in ("count", "") else body
    if kind in CATEGORICAL:
        return body
    word = str(unit or "").strip()
    return f"{body} {word}".strip()


def format_unitless(value: Decimal) -> str:
    """A number whose unit nothing could name, written for a person anyway.

    Declining to name a unit is honest. Printing 1.5690646127781567 at a
    credit officer is not -- it is machine precision reaching a reader, and
    it is a defect whether or not we know what the number measures.

    So: no unit is asserted, ever, and no currency is implied. A value that
    is whole is written whole, because that is a fact about the value rather
    than a guess about its kind; anything else gets two decimal places,
    which is what a general figure carries when nobody has said otherwise.
    """
    shown = plain(value)
    if shown == shown.to_integral_value():
        return f"{shown.to_integral_value():,}"
    return f"{quantize(shown, DECIMALS[UNKNOWN]):,}"


def money_unit(catalog: Any) -> str:
    """The money unit of ONE release, e.g. "SAR million".

    Empty when the release does not say. An empty unit is honest; a guessed
    one is not, and a caller can render a bare number rather than assert a
    currency the release never claimed.
    """
    currency = str(getattr(catalog, "reporting_currency", "") or "").strip()
    scale = str(getattr(catalog, "amount_scale", "") or "").strip()
    return f"{currency} {scale}".strip()


def unit_for_field(catalog: Any, relation: str, column: str) -> str:
    """The unit an ANSWER should use for a catalogue field.

    `RCY` means "the reporting currency", which is not something a reader can
    be shown; it resolves to the release's own denomination. Everything else
    is already in terms this policy understands.
    """
    try:
        spec = catalog.resolve(relation, column)
    except Exception:  # noqa: BLE001
        return ""
    raw = str(getattr(spec, "unit", "") or "").strip()
    if raw.lower() in ("rcy", "reporting_currency"):
        return money_unit(catalog)
    return raw


__all__ = ["CATALOG_UNITS", "CATEGORICAL", "COUNT", "DECIMALS",
           "MONEY_SCALES",
           "DISPLAY_FACTOR", "IFRS_STAGE", "INTEGER", "MONETARY_AMOUNT",
           "PERCENTAGE", "PERCENTAGE_POINT", "PERIOD", "PERMITTED",
           "PROBABILITY", "RATING", "RATIO", "ROUNDING", "UNKNOWN",
           "classify", "decimals", "display_value", "format_unitless",
           "format_value",
           "money_unit", "permitted", "plain", "quantize", "unit_for_field"]
