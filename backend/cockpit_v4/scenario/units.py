"""What "increase PD by 20" actually means, typed so it cannot mean two things.

Section 5.1 of the What-If specification is a list of pairs that a reader
writes almost identically and that produce different books:

    increase PD by 20%              PD x 1.20          2.0% -> 2.40%
    increase PD by 20 basis points  PD + 0.0020        2.0% -> 2.20%
    increase PD by 2 percentage pts PD + 0.0200        2.0% -> 4.00%
    set PD to 20%                   PD  = 0.2000       2.0% -> 20.00%
    double PD                       PD x 2             2.0% -> 4.00%

Four of those five are "increase PD by 20", and they differ by a factor of ten
between neighbours. So the quantity a reader typed is never carried as a bare
number here. It is carried as an `Amount` -- a figure and the operation it
names -- and a bare number has no way into the engine at all.

THE STORAGE PROBLEM, which is the part that bites.

The published books do not store risk parameters in one convention. In
`corp_facility_quarter`, `pd_pit_12m` is a FRACTION in 0..1 and `lgd_pct` is a
PERCENT in 0..100. "Raise LGD by 10 percentage points" therefore adds 10 to one
column and 0.10 to the other, and a helper that did not know which would be
wrong half the time and plausible all of it.

Section 3.2 settles the internal convention -- "internally store probabilities
as decimal fractions; display percentages" -- so every operation here happens
in FRACTION space, and `to_fraction` / `from_fraction` carry a column in and
out of it. The field dictionary declares each column's storage; nothing is
inferred from a column's name.

EVERYTHING IS `Decimal`. `derivation.py` made this choice for published claims
and gives its reason at its own line 25; the same reason applies upstream. A
scenario that reconciles to the minor unit cannot get there through binary
floating point, and `0.1 + 0.2` is the shortest argument for that.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

# ---- how a reader can move a number -----------------------------------
#
# Deliberately not an enum of every phrase anyone might type. These are the
# distinct ARITHMETIC operations; mapping "double" and "by a factor of two"
# onto MULTIPLY is the analyst's job, and it happens before anything reaches
# this module.

#: x (1 + v/100). "Increase PD by 20%" -- the commonest reading, and the one
#: section 10.1's proportional Delta is built on.
RELATIVE = "relative_pct"

#: x v. "Double PD" is MULTIPLY 2; "reduce PD by half" is MULTIPLY 0.5. Kept
#: apart from RELATIVE because a reader who says "double" has not said "+100%"
#: and an audit record that claimed they had would be putting words in.
MULTIPLY = "multiply"

#: + v/100 in fraction space. "Increase PD by 2 percentage points."
ABSOLUTE_PP = "absolute_pp"

#: + v/10000 in fraction space. "Increase PD by 20 basis points."
BASIS_POINTS = "basis_points"

#: := v, in the FIELD'S OWN display unit. "Set PD to 3%" is SET_TO 3, and the
#: 3 is a percent because PD displays as a percent -- see `apply`.
SET_TO = "set_to"

#: + v currency units. For money fields only.
ABSOLUTE_AMOUNT = "absolute_amount"

#: + v steps along a published ordinal scale. "Downgrade one notch" is
#: NOTCHES +1 toward worse. The scale decides what the next grade is; this
#: module only carries the count. See `mappings.py`.
NOTCHES = "notches"

#: + v index points. "Reduce the score by 50 points" is POINTS -50, and
#: section 5.1 is explicit that it is not a 50% reduction.
POINTS = "points"

OPERATIONS: tuple[str, ...] = (
    RELATIVE, MULTIPLY, ABSOLUTE_PP, BASIS_POINTS, SET_TO,
    ABSOLUTE_AMOUNT, NOTCHES, POINTS,
)

#: The operations that scale a baseline rather than replace or offset it.
#: Proportional Delta (section 10.1) is defined over exactly these, because
#: only they have a factor to raise to an elasticity.
PROPORTIONAL_OPERATIONS: frozenset[str] = frozenset({RELATIVE, MULTIPLY})

#: Operations whose amount is a count of discrete steps, not a quantity. A
#: fractional notch is not a thing.
DISCRETE_OPERATIONS: frozenset[str] = frozenset({NOTCHES})


# ---- how a column stores what it holds ---------------------------------

#: 0..1. `pd_pit_12m`, `pd_lifetime`. The internal convention.
FRACTION = "fraction"

#: 0..100, the same quantity written differently. `lgd_pct`,
#: `utilisation_pct`, `ecl_coverage_pct`.
PERCENT = "percent"

#: SAR million. `ead_sar_mn`, `drawn_sar_mn`, `ecl_sar_mn`.
MONEY = "money"

#: A bare index with its own scale. `behaviour_score` runs 300..900 and means
#: nothing as a percentage of anything.
INDEX = "index"

#: A published ordered scale of labels. `rating_current`. Not a number, and
#: section 5.1 says so: "a corporate rating string is not inherently
#: numerically ordered."
ORDINAL = "ordinal"

STORAGE: tuple[str, ...] = (FRACTION, PERCENT, MONEY, INDEX, ORDINAL)

#: Which operations are meaningful against which storage. A percentage-point
#: move on a money column is a category error, and so is a basis-point move on
#: a credit score; both are refused rather than coerced.
ALLOWED: dict[str, frozenset[str]] = {
    FRACTION: frozenset({RELATIVE, MULTIPLY, ABSOLUTE_PP, BASIS_POINTS,
                         SET_TO}),
    PERCENT: frozenset({RELATIVE, MULTIPLY, ABSOLUTE_PP, BASIS_POINTS,
                        SET_TO}),
    MONEY: frozenset({RELATIVE, MULTIPLY, ABSOLUTE_AMOUNT, SET_TO}),
    INDEX: frozenset({RELATIVE, MULTIPLY, POINTS, SET_TO}),
    ORDINAL: frozenset({NOTCHES, SET_TO}),
}


class UnitError(ValueError):
    """A quantity that cannot mean what it was asked to mean.

    Raised rather than resolved. Section 5.1: an unqualified "increase by 20"
    is ambiguous and wants one concise clarification, not a house default.
    """


@dataclass(frozen=True)
class Amount:
    """A figure and the operation it names. The only quantity this engine has.

    `raw` is the reader's own wording, kept so an audit record can show what
    was typed beside what it was understood as. It is never parsed again.
    """

    value: Decimal
    operation: str
    raw: str = ""

    def __post_init__(self) -> None:
        if self.operation not in OPERATIONS:
            raise UnitError(
                f"{self.operation!r} is not an operation this engine has. "
                f"The operations are: {', '.join(OPERATIONS)}.")
        if not isinstance(self.value, Decimal):
            raise UnitError(
                f"{self.operation} carries {self.value!r}, which is "
                f"{type(self.value).__name__} and not Decimal. Every quantity "
                f"here is Decimal; see this module's header.")
        if self.operation in DISCRETE_OPERATIONS and self.value % 1 != 0:
            raise UnitError(
                f"{self.value} is not a whole number of steps. A rating moves "
                f"a notch at a time; there is no half-notch on a published "
                f"scale.")

    def describe(self) -> str:
        """One line, for the preview and the audit record."""
        v = _plain(self.value)
        return {
            RELATIVE: f"{v}% relative to baseline",
            MULTIPLY: f"multiplied by {v}",
            ABSOLUTE_PP: f"{_signed(v)} percentage points",
            BASIS_POINTS: f"{_signed(v)} basis points",
            SET_TO: f"set to {v}",
            ABSOLUTE_AMOUNT: f"{_signed(v)} SAR million",
            NOTCHES: f"{_signed(v)} notches",
            POINTS: f"{_signed(v)} points",
        }[self.operation]


def parse(value: Any, operation: str, raw: str = "") -> Amount:
    """Build an `Amount`, accepting the wire forms a JSON payload arrives in.

    A string is parsed as an exact decimal; a float is REFUSED rather than
    converted, because `Decimal(0.1)` is 0.1000000000000000055511151231257827
    and a tolerance that had to absorb that would have to be loose enough to
    absorb a real error too.
    """
    if isinstance(value, Amount):
        return value
    if isinstance(value, float):
        raise UnitError(
            f"{value!r} arrived as a float. Send the quantity as a string or "
            f"an int so it keeps the value that was typed: Decimal(0.1) is "
            f"not one tenth.")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise UnitError(f"{value!r} is not a number.") from exc
    if not amount.is_finite():
        raise UnitError(f"{value!r} is not a finite number.")
    return Amount(value=amount, operation=operation, raw=raw)


# ---- storage conversion ------------------------------------------------

_HUNDRED = Decimal(100)
_TEN_THOUSAND = Decimal(10_000)


def to_fraction(value: Decimal, storage: str) -> Decimal:
    """A stored value in the internal convention.

    FRACTION and PERCENT are the same quantity in different clothes and both
    become a fraction. MONEY, INDEX and ORDINAL are not rates at all and pass
    through untouched -- converting them would be asserting they were.
    """
    _require_storage(storage)
    if storage == PERCENT:
        return value / _HUNDRED
    return value


def from_fraction(value: Decimal, storage: str) -> Decimal:
    """Back to the column's own convention, for writing and for display."""
    _require_storage(storage)
    if storage == PERCENT:
        return value * _HUNDRED
    return value


def _require_storage(storage: str) -> None:
    if storage not in STORAGE:
        raise UnitError(
            f"{storage!r} is not a storage convention this engine knows. "
            f"They are: {', '.join(STORAGE)}.")


# ---- the one place a number moves --------------------------------------

def apply(baseline: Decimal, amount: Amount, *, storage: str) -> Decimal:
    """The baseline moved by the amount, in the column's own convention.

    In and out in the column's storage; the arithmetic in between happens in
    fraction space for rate-like columns, so a percentage-point move means the
    same thing whether the book wrote 0.04 or 4.0.

    This function does NOT clamp. Section 5.1: "Do not silently clamp an
    invalid request" -- a result outside a field's valid range is the caller's
    to surface, with the unclipped value, the clipped value and the affected
    count all visible. `bounds.py` owns that, and it owns it separately so
    that a cap is a declared policy with a named effect rather than something
    that quietly happened here.
    """
    _require_storage(storage)
    if amount.operation not in ALLOWED[storage]:
        raise UnitError(
            f"{amount.operation} does not apply to a {storage} field. "
            f"A {storage} field accepts: "
            f"{', '.join(sorted(ALLOWED[storage]))}.")

    if amount.operation == SET_TO:
        # SET_TO names the value in the field's DISPLAY unit, which is how a
        # reader says it: "set PD to 3%" is three, not 0.03, and the field
        # knows that PD displays as a percent. A percent-stored field displays
        # in the unit it stores, so only FRACTION needs the conversion.
        if storage == FRACTION:
            return amount.value / _HUNDRED
        return amount.value

    if amount.operation == RELATIVE:
        return baseline * (Decimal(1) + amount.value / _HUNDRED)
    if amount.operation == MULTIPLY:
        return baseline * amount.value
    if amount.operation == ABSOLUTE_AMOUNT:
        return baseline + amount.value
    if amount.operation == POINTS:
        return baseline + amount.value

    # The two that need fraction space.
    as_fraction = to_fraction(baseline, storage)
    if amount.operation == ABSOLUTE_PP:
        moved = as_fraction + amount.value / _HUNDRED
    else:  # BASIS_POINTS
        moved = as_fraction + amount.value / _TEN_THOUSAND
    return from_fraction(moved, storage)


def factor(baseline: Decimal, scenario: Decimal) -> Decimal | None:
    """`scenario / baseline`, or None when the ratio does not exist.

    Section 10.3, and oracle O11. A zero baseline going to a positive value
    has no ratio, and inventing one through an epsilon denominator would turn
    a contractual PD of zero into an arbitrary large number that then
    multiplies an ECL. Zero to zero is a neutral 1: nothing moved.

    Returning None rather than raising is deliberate -- an unsupported row is
    a reason-coded coverage fact the run reports, not an exception that ends
    it (section 9.1).
    """
    if baseline == 0:
        return Decimal(1) if scenario == 0 else None
    return scenario / baseline


# ---- presentation ------------------------------------------------------

def _plain(value: Decimal) -> str:
    """A Decimal without exponent notation or trailing zero noise."""
    text = format(value.normalize(), "f")
    return text


def _signed(text: str) -> str:
    return text if text.startswith("-") else f"+{text}"


def three_values(baseline: Decimal, amount: Amount, *,
                 storage: str) -> dict[str, str]:
    """Baseline, new value and the move, all three, as section 5.1 requires.

    "Reduce unemployment by 10%" means 6.0% becomes 5.4%, a change of -0.6
    percentage points, and the specification says to display all three --
    because a reader who meant percentage points and got a relative change has
    no way to tell from the new value alone.
    """
    moved = apply(baseline, amount, storage=storage)
    out = {
        "baseline": _plain(baseline),
        "scenario": _plain(moved),
        "change": _signed(_plain(moved - baseline)),
        "operation": amount.describe(),
    }
    if storage in (FRACTION, PERCENT):
        pp = from_fraction(to_fraction(moved, storage)
                           - to_fraction(baseline, storage), PERCENT)
        out["change_percentage_points"] = _signed(_plain(pp))
    ratio = factor(baseline, moved)
    out["change_relative_pct"] = (
        _signed(_plain((ratio - 1) * _HUNDRED)) if ratio is not None else
        "not defined from a zero baseline")
    return out


__all__ = [
    "ABSOLUTE_AMOUNT", "ABSOLUTE_PP", "ALLOWED", "Amount", "BASIS_POINTS",
    "DISCRETE_OPERATIONS", "FRACTION", "INDEX", "MONEY", "MULTIPLY",
    "NOTCHES", "OPERATIONS", "ORDINAL", "PERCENT",
    "PROPORTIONAL_OPERATIONS", "RELATIVE", "SET_TO", "STORAGE", "POINTS",
    "UnitError", "apply", "factor", "from_fraction", "parse", "three_values",
    "to_fraction",
]
