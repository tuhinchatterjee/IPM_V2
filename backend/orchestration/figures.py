"""
One place that decides how a number is written down.

Why this module exists
----------------------
A credit officer read this in a CreditProbe answer:

    2.6246841182876173%
    12,260.522999999981
    73,391.774000000012

Every one of those figures is correct. Every one of them looks like a defect,
and a figure that looks like a defect is worse than a figure that is slightly
imprecise, because the reader now has to decide whether to trust the product.

The debris came from three different places writing numbers three different
ways: the table had a display contract, the deterministic narrative rounded by
hand, and the interpretation model was handed raw floats and quoted them back
verbatim. There is now one formatter, and everything that turns a number into
text goes through it.

Display precision is not calculation precision
----------------------------------------------
Nothing here rounds a stored value. `figures.percent(2.6246841182876173)` is a
string; the number it came from is untouched and every invariant, comparison and
threshold test still runs against the full-precision value. That separation is
the reason a share can be *displayed* as 2.62% and still be *checked* against a
covenant at 2.6246841182876173%.

Thresholds are the exception that proves it
-------------------------------------------
"Covenant headroom below 15%" is a question about a boundary, and 14.9996%
displayed as "15.00%" is a sentence that contradicts the answer it sits inside.
Where a caller knows the boundary, it says so, and the formatter adds decimals
until the written figure is still on the side of it that the underlying value
is on. That is the one case where display precision is allowed to be driven by
something other than readability.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

# Semantic kinds. These mirror the column semantics in `presentation`, which is
# where most callers get theirs from.
MONEY = "money"
PERCENT = "percent"
POINTS = "points"
RATIO = "ratio"
COUNT = "count"
DAYS = "days"
ORDINAL = "ordinal"
PLAIN = "plain"

#: A money figure at or above this reads in whole units. Two decimals on a
#: seventy-three-billion balance is noise wearing the costume of precision.
WHOLE_MONEY_ABOVE = 1000.0

#: Below this a money figure keeps one decimal — 321.8 says something 322 does
#: not when the next row is 318.4.
ONE_DECIMAL_MONEY_ABOVE = 1.0

#: How far a formatter will go chasing a threshold before it gives up and
#: writes the plain figure. Four decimals on a percentage is already past what
#: anybody reads; more than that and the boundary is not a display problem.
MAX_THRESHOLD_DECIMALS = 6

#: Anything with this many decimal places in prose is binary debris rather than
#: a considered precision. Nobody types 12,260.522999999981.
DEBRIS_DECIMALS = 4

_DEBRIS = re.compile(r"(?<![\w.])(-?\d[\d,]*\.\d{" + str(DEBRIS_DECIMALS) + r",})")


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    """How one figure should be written.

    Built from a column's semantics where there is a column, and by hand where
    there is not — a headline value, a figure in a sentence, a tooltip.
    """

    semantic: str = PLAIN
    unit: str = ""
    currency: str = ""
    #: The scale the stored figure is already in: "mn" for a book kept in
    #: millions. Never a scale the formatter applies — a scale it is told.
    scale: str = ""
    #: Force a precision. None means the semantic decides, which is normally
    #: what you want.
    decimals: int | None = None
    #: A boundary the written figure must stay on the correct side of.
    threshold: float | None = None
    #: Which side of the threshold the answer asserts: "below" or "above".
    side: str = ""

    @classmethod
    def from_column(cls, column: Any) -> Spec:
        """The spec implied by a presentation column contract."""
        spec = (column.to_dict() if hasattr(column, "to_dict")
                else dict(column or {}))
        semantic = str(spec.get("semantic") or PLAIN)
        unit = str(spec.get("unit") or "")
        if semantic == PERCENT and unit == "pp":
            semantic = POINTS
        semantic = semantic if semantic in _KNOWN else PLAIN

        # Money is the one semantic whose precision the column cannot decide.
        # 321.8 and 73,392 belong in the same column and want different
        # decimals, so the magnitude of the individual figure rules and the
        # column's hint is ignored.
        decimals = None if semantic == MONEY else spec.get("decimals")
        return cls(
            semantic=semantic,
            unit=unit,
            currency=str(spec.get("currency") or ""),
            scale=str(spec.get("scale") or ""),
            decimals=int(decimals) if decimals is not None else None,
        )


_KNOWN = frozenset({MONEY, PERCENT, POINTS, RATIO, COUNT, DAYS, ORDINAL, PLAIN})


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def text(value: Any, spec: Spec | dict[str, Any] | None = None) -> str:
    """One value, written the way its semantics say it should be.

    The single entry point. Everything else in this module is a convenience
    that builds a spec and calls this.
    """
    if isinstance(spec, dict):
        spec = Spec.from_column(spec)
    spec = spec or Spec()

    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if not isinstance(value, (int, float)):
        return str(value)

    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return "—"

    decimals = _decimals(number, spec)
    if spec.threshold is not None:
        decimals = _respecting(number, decimals, spec.threshold, spec.side)

    body = _grouped(number, decimals)
    return _with_unit(body, spec)


def _decimals(number: float, spec: Spec) -> int:
    if spec.decimals is not None:
        return max(0, int(spec.decimals))

    magnitude = abs(number)
    if spec.semantic in (COUNT, DAYS, ORDINAL):
        return 0
    if spec.semantic == MONEY:
        if magnitude >= WHOLE_MONEY_ABOVE:
            return 0
        if magnitude >= ONE_DECIMAL_MONEY_ABOVE:
            return 1
        return 2
    if spec.semantic in (PERCENT, POINTS):
        return 2
    if spec.semantic == RATIO:
        return 2

    # A plain number with no semantics behind it. Scale by magnitude, which is
    # the rule a person applies without thinking about it.
    if magnitude >= WHOLE_MONEY_ABOVE:
        return 0
    if magnitude >= 100:
        return 1
    return 2


def _respecting(number: float, decimals: int, threshold: float,
                side: str) -> int:
    """Enough decimals that the written figure keeps the answer's meaning.

    A population selected for headroom below 15% may contain 14.9996%. Written
    at two decimals that is "15.00%", which contradicts the sentence around it
    and looks exactly like the contradiction this product exists to make
    impossible. So the precision follows the boundary rather than the eye.
    """
    if number == threshold:
        return decimals

    strictly_below = number < threshold
    if side == "below" and not strictly_below:
        return decimals
    if side == "above" and strictly_below:
        return decimals

    while decimals <= MAX_THRESHOLD_DECIMALS:
        shown = round(number, decimals)
        if (shown < threshold) == strictly_below and shown != threshold:
            return decimals
        decimals += 1
    return MAX_THRESHOLD_DECIMALS


def _grouped(number: float, decimals: int) -> str:
    rendered = f"{number:,.{decimals}f}"
    # -0.00 is arithmetically true and reads as a mistake.
    if rendered.startswith("-") and float(rendered.replace(",", "")) == 0:
        rendered = rendered[1:]
    return rendered


def _with_unit(body: str, spec: Spec) -> str:
    if spec.semantic == PERCENT:
        return f"{body}%"
    if spec.semantic == POINTS:
        return f"{body} pp"
    if spec.semantic == RATIO:
        return f"{body}x"
    if spec.semantic == DAYS:
        return f"{body} days"
    if spec.semantic == MONEY:
        parts = [body]
        if spec.currency:
            parts.append(spec.currency)
        if spec.scale:
            parts.append(spec.scale)
        return " ".join(parts)
    if spec.unit and spec.unit not in ("%", "pp", "x", "days"):
        return f"{body} {spec.unit}"
    return body


# ---------------------------------------------------------------------------
# Named conveniences
# ---------------------------------------------------------------------------


def money(value: Any, *, currency: str = "", scale: str = "",
          decimals: int | None = None) -> str:
    """A balance, in the scale the book is already kept in."""
    return text(value, Spec(semantic=MONEY, currency=currency, scale=scale,
                            decimals=decimals))


def percent(value: Any, *, decimals: int | None = None,
            threshold: float | None = None, side: str = "") -> str:
    """A percentage. Two decimals unless a boundary needs more."""
    return text(value, Spec(semantic=PERCENT, unit="%", decimals=decimals,
                            threshold=threshold, side=side))


def points(value: Any, *, decimals: int | None = None) -> str:
    """A change expressed in percentage points: 0.04 pp, -4.64 pp."""
    return text(value, Spec(semantic=POINTS, unit="pp", decimals=decimals))


def ratio(value: Any, *, decimals: int | None = None) -> str:
    """A multiple: 1.42x."""
    return text(value, Spec(semantic=RATIO, unit="x", decimals=decimals))


def count(value: Any) -> str:
    """A whole number of things, with separators and no decimals."""
    return text(value, Spec(semantic=COUNT))


def days(value: Any) -> str:
    return text(value, Spec(semantic=DAYS, unit="days"))


def compact(value: Any, *, currency: str = "", scale: str = "mn") -> str:
    """A balance promoted to the next scale where that reads better.

    For a KPI card, where one figure stands alone and 12.3 USD bn is easier to
    hold in the head than 12,340 USD mn. Deliberately NOT used in tables or in
    prose: promoting one figure and not the one below it in the same column is
    how a comparison stops being a comparison.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return text(value)
    number = float(value)
    if scale == "mn" and abs(number) >= 1000:
        return text(number / 1000.0,
                    Spec(semantic=MONEY, currency=currency, scale="bn",
                         decimals=1))
    return money(number, currency=currency, scale=scale)


# ---------------------------------------------------------------------------
# The safety net
# ---------------------------------------------------------------------------


def scrub(prose: str, *, keep: object = ()) -> str:
    """Rewrite binary floating-point debris found in a finished sentence.

    The typed path above is the real fix: rows are formatted before anything
    reads them, so a model quoting "the figures exactly as they appear" quotes
    formatted ones. This is what stands behind it, for prose that arrived from
    somewhere the typed path does not reach.

    It only ever touches a number written to four or more decimal places, which
    is a precision no person chooses and every float64 subtraction produces. A
    figure written to three is left exactly as it is, on the assumption that
    whoever wrote it meant it.

    `keep` is how a caller protects deliberate precision. A covenant answer
    writes 14.9996% on purpose — rounding it to 15.00% would contradict the
    sentence it sits in — so the caller passes the figures it formatted and
    this leaves them exactly as they are. Anything not in that set was not
    produced by the formatter and is debris by construction.
    """
    if not prose:
        return prose
    protected = {str(k).strip() for k in (keep or ())}

    def rewrite(match: re.Match[str]) -> str:
        raw = match.group(1)
        if raw in protected:
            return raw
        try:
            number = float(raw.replace(",", ""))
        except ValueError:
            return raw
        magnitude = abs(number)
        if magnitude >= WHOLE_MONEY_ABOVE:
            decimals = 0
        elif magnitude >= 100:
            decimals = 1
        else:
            decimals = 2
        return _grouped(number, decimals)

    return _DEBRIS.sub(rewrite, prose)


def has_debris(prose: str) -> bool:
    """Whether a sentence carries a figure no person would have written."""
    return bool(_DEBRIS.search(prose or ""))


__all__ = [
    "COUNT",
    "DAYS",
    "DEBRIS_DECIMALS",
    "MAX_THRESHOLD_DECIMALS",
    "MONEY",
    "ONE_DECIMAL_MONEY_ABOVE",
    "ORDINAL",
    "PERCENT",
    "PLAIN",
    "POINTS",
    "RATIO",
    "Spec",
    "WHOLE_MONEY_ABOVE",
    "compact",
    "count",
    "days",
    "has_debris",
    "money",
    "percent",
    "points",
    "ratio",
    "scrub",
    "text",
]
