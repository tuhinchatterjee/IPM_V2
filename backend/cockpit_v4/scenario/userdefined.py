"""Method 3: the reader supplies the impact, and the engine makes it add up.

Section 12 allows five ways of stating an impact, and no sixth:

* **relative** -- "assume ECL rises 15%";
* **absolute** -- "add 250 SAR million of ECL";
* **target amount** -- "ECL becomes 22,000 SAR million";
* **target rate** -- "coverage becomes 3.2% of EAD";
* **elasticity** -- "ECL rises 1.4% for every 1% PD rise".

**Why there is no expression evaluator here.** The specification asks for a
restricted typed evaluator with no `eval` and no raw SQL. Five declared forms
are stricter than a restricted language and need no parser at all: there is
nothing to sandbox, nothing to escape from, and a reader's statement either
matches one of the five or is refused with the five named. This is the same
choice `derivation.py` made with its closed twelve operations, and it is the
one the accepted architecture already lives by.

**The allocation is the hard part.** A reader who says "ECL becomes 22,000"
has stated a total, and the answer has to show that total spread over the
cohort so a record-level table sums to it. Proportional shares almost never
land on whole currency units, and rounding each one independently leaves the
sum a few halalas off the number the reader just typed -- which is exactly
the failure section 13.1 forbids, because the table and the headline then
disagree. `allocate()` uses largest-remainder: floor every share to the
currency quantum, then hand the leftover quanta out one at a time to the rows
with the largest discarded fractions. The sum is the target EXACTLY, by
construction, and no row is moved by more than one quantum from its
proportional share.

Rows with a zero baseline receive nothing. There is no proportional share of
a zero, and inventing one would put ECL on a facility the book says has none
-- section 10.3's rule again, in a different costume.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Any

from backend.cockpit_v4.scenario.errors import (
    PARAMETER_OUT_OF_RANGE,
    UNIT_AMBIGUOUS,
    raise_for,
)

# ---- the five forms, and nothing else ----------------------------------

#: "ECL rises 15%" -- a percentage of the baseline total.
RELATIVE = "relative"

#: "add 250 SAR million" -- an amount, in the book's own money unit.
ABSOLUTE = "absolute"

#: "ECL becomes 22,000" -- the total itself.
TARGET_AMOUNT = "target_amount"

#: "coverage becomes 3.2%" -- a rate on baseline EAD.
TARGET_RATE = "target_rate"

#: "ECL rises 1.4% per 1% of PD" -- a ratio applied to a stated driver move.
ELASTICITY = "elasticity"

FORMS: tuple[str, ...] = (RELATIVE, ABSOLUTE, TARGET_AMOUNT, TARGET_RATE,
                          ELASTICITY)

#: Currency precision for a SAR-million figure. The allocation reconciles
#: exactly AT this quantum, which is the only sense in which an exact
#: reconciliation of a proportional split can be promised.
QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class Assumption:
    """One reader-supplied impact, typed, with their own words kept.

    `value` means something different in each form, which is the point of
    the form being explicit: 15 is a percentage in RELATIVE, 250 SAR million
    in ABSOLUTE, a total in TARGET_AMOUNT, a coverage percentage in
    TARGET_RATE, and a ratio in ELASTICITY.
    """

    form: str
    value: Decimal
    #: ELASTICITY only: the driver's own move, as a percentage.
    driver_move_pct: Decimal = Decimal(0)
    driver_field: str = ""
    #: The reader's statement, verbatim, for the audit record.
    stated_as: str = ""

    def __post_init__(self) -> None:
        if self.form not in FORMS:
            raise_for(UNIT_AMBIGUOUS,
                      f"{self.form!r} is not one of the five ways an impact "
                      f"can be stated. They are: {', '.join(FORMS)}.",
                      field_path="user_assumption.form")
        for name in ("value", "driver_move_pct"):
            if not isinstance(getattr(self, name), Decimal):
                raise_for(UNIT_AMBIGUOUS,
                          f"{name} must be Decimal; a float would make the "
                          f"reconciliation inexact for a reason that has "
                          f"nothing to do with the scenario.",
                          field_path=f"user_assumption.{name}")
        if self.form == ELASTICITY and self.driver_move_pct == 0:
            raise_for(UNIT_AMBIGUOUS,
                      "an elasticity needs a driver move to act on: a "
                      "sensitivity of 1.4 says nothing until something has "
                      "moved by a stated amount.",
                      field_path="user_assumption.driver_move_pct")

    def describe(self) -> str:
        v = format(self.value.normalize(), "f")
        return {
            RELATIVE: f"ECL moves {v}% against baseline",
            ABSOLUTE: f"ECL moves by {v} SAR million",
            TARGET_AMOUNT: f"ECL becomes {v} SAR million",
            TARGET_RATE: f"coverage becomes {v}% of baseline EAD",
            ELASTICITY: (
                f"ECL moves {v}% for each 1% of "
                f"{self.driver_field or 'the driver'}, which moves "
                f"{format(self.driver_move_pct.normalize(), 'f')}%"),
        }[self.form]

    def canonical(self) -> dict[str, Any]:
        """The part of the assumption that could change a number."""
        return {"form": self.form, "value": str(self.value),
                "driver_move_pct": str(self.driver_move_pct),
                "driver_field": self.driver_field}


def target_total(assumption: Assumption, *, baseline_ecl: Decimal,
                 baseline_ead: Decimal) -> Decimal:
    """The scenario total the reader's statement implies.

    Quantised to the currency precision, because that is the number the
    allocation has to reconcile to exactly, and a target carrying more
    precision than the currency does cannot be reconciled to at all.
    """
    if assumption.form == RELATIVE:
        raw = baseline_ecl * (Decimal(1) + assumption.value / 100)
    elif assumption.form == ABSOLUTE:
        raw = baseline_ecl + assumption.value
    elif assumption.form == TARGET_AMOUNT:
        raw = assumption.value
    elif assumption.form == TARGET_RATE:
        if baseline_ead == 0:
            raise_for(PARAMETER_OUT_OF_RANGE,
                      "a coverage target is a rate on exposure, and this "
                      "cohort's baseline EAD is zero. State the ECL total "
                      "itself instead.",
                      field_path="user_assumption.value")
        raw = baseline_ead * assumption.value / 100
    else:  # ELASTICITY
        # Both numbers are already percentages: an elasticity of 1.4 means
        # 1.4% of ECL per 1% of the driver, so the product IS the percentage
        # ECL moves by and there is exactly one division by a hundred. Two
        # of them turn a 28% stress into a 0.28% one, which is a plausible
        # enough number that nothing downstream would flag it.
        moved_pct = assumption.value * assumption.driver_move_pct
        raw = baseline_ecl * (Decimal(1) + moved_pct / 100)

    if raw < 0:
        raise_for(PARAMETER_OUT_OF_RANGE,
                  f"that assumption puts the cohort's ECL at {raw}, and an "
                  f"expected credit loss cannot be negative. State what the "
                  f"total should be.",
                  field_path="user_assumption.value", implied_total=str(raw))
    return raw.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)


def allocate(target: Decimal, baselines: list[Decimal], *,
             keys: list[str] | None = None,
             quantum: Decimal = QUANTUM) -> list[Decimal]:
    """Spread a target total over rows in proportion to their baselines.

    Largest-remainder, so the returned list sums to `target` EXACTLY and no
    row sits more than one quantum from its proportional share. Section 13.1:
    the record-level table and the headline are the same number, not two
    numbers that nearly agree.

    A zero baseline receives zero: there is no proportional share of nothing,
    and allocating one would report ECL on a row the book says carries none.
    """
    total = sum(baselines, Decimal(0))
    if total == 0:
        if target == 0:
            return [Decimal(0) for _ in baselines]
        raise_for(PARAMETER_OUT_OF_RANGE,
                  f"every row in this cohort carries a baseline ECL of zero, "
                  f"so there is no proportion to spread {target} over. A "
                  f"total has to land somewhere, and nothing here can carry "
                  f"it.",
                  field_path="user_assumption.value")

    shares = [(b / total) * target if b else Decimal(0) for b in baselines]
    floored = [s.quantize(quantum, rounding=ROUND_FLOOR) for s in shares]
    leftover = target - sum(floored, Decimal(0))
    quanta = int((leftover / quantum).to_integral_value(
        rounding=ROUND_HALF_EVEN))

    # Largest discarded fraction first. Ties break on the entity's own id,
    # so two rows with identical baselines get the same answer however the
    # cohort happened to arrive -- section 17.1's O10: "reordering input rows
    # must not change the assignment when stable entity IDs break ties."
    # Falling back to position when no ids are given keeps the function
    # deterministic, but it is position-dependent, so `rows()` passes ids.
    def tiebreak(index: int) -> tuple[Decimal, str, int]:
        key = keys[index] if keys else ""
        return (-(shares[index] - floored[index]), key, index)

    order = sorted((i for i, b in enumerate(baselines) if b), key=tiebreak)
    # Each floor discards strictly less than one quantum, so the leftover is
    # strictly fewer quanta than there are rows carrying a share. No row can
    # need two, and a state where one did would mean the shares did not sum
    # to the target -- which is the bug this function exists to prevent, so
    # it is raised rather than papered over with a second pass.
    if quanta > len(order):  # pragma: no cover - guards an impossible state
        raise AssertionError(
            f"{quanta} leftover quanta over {len(order)} rows: the shares do "
            f"not sum to the target and the allocation would be wrong.")
    out = list(floored)
    for index in order[:quanta]:
        out[index] += quantum
    return out


def reconciles(allocated: list[Decimal], target: Decimal) -> bool:
    """The property the allocation exists to have. Cheap enough to assert."""
    return sum(allocated, Decimal(0)) == target


def rows(assumption: Assumption, baselines: list[Decimal], *,
         baseline_ead: Decimal, keys: list[str] | None = None,
         quantum: Decimal = QUANTUM) -> list[Decimal]:
    """The scenario ECL per row, for a reader-supplied impact."""
    baseline_ecl = sum(baselines, Decimal(0))
    target = target_total(assumption, baseline_ecl=baseline_ecl,
                          baseline_ead=baseline_ead)
    return allocate(target, baselines, keys=keys, quantum=quantum)


def from_payload(body: dict[str, Any]) -> Assumption:
    """Build an assumption from the JSON an analyst authored.

    Numbers arrive as strings for the reason `units.parse` gives: a float
    that looks like 0.1 is not one tenth, and a reconciliation loose enough
    to absorb that is loose enough to absorb a real error.
    """
    for key in ("value", "driver_move_pct"):
        if isinstance(body.get(key), float):
            raise_for(UNIT_AMBIGUOUS,
                      f"{key} arrived as a float. Send it as a string so it "
                      f"keeps the value that was typed.",
                      field_path=f"user_assumption.{key}")
    return Assumption(
        form=str(body.get("form", "")),
        value=Decimal(str(body.get("value", "0"))),
        driver_move_pct=Decimal(str(body.get("driver_move_pct", "0"))),
        driver_field=str(body.get("driver_field", "")),
        stated_as=str(body.get("stated_as", "")))


__all__ = [
    "ABSOLUTE", "ELASTICITY", "FORMS", "QUANTUM", "RELATIVE", "TARGET_AMOUNT",
    "TARGET_RATE", "Assumption", "allocate", "from_payload", "reconciles",
    "rows", "target_total",
]
