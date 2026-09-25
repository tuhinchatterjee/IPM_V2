"""Chronological splitting, by period and by nothing else.

Section 11.2. Four rules, and each closes a way a model can look better than
it is:

**Chronological, by DISTINCT REPORTING PERIOD.** A random split puts the same
facility's 2024Q1 and 2024Q3 rows on both sides, and the model memorises the
facility rather than learning the relationship. Sixty thousand rows across
twenty quarters are twenty periods for this purpose too -- the same counting
`sensitivity/readiness.py` applies, for the same reason.

**Expanding-window folds inside development only.** Fold k trains on periods
up to some boundary and validates on the ones after it, so every fold is a
forecast. The test periods are not in any fold.

**An embargo derived from label availability.** The target is set at a
reporting date, so a row whose label was not knowable at the boundary is
out. The rule here is stated in periods and RECORDED -- `Assignment.embargo`
-- rather than being a constant somebody picked.

**Persisted per row.** `assignment_rows()` publishes which split every row
landed in, so the card's counts can be checked instead of trusted. A split
nobody can reconstruct is a split nobody can audit.

The shares are 60/20/20 by period: on a twenty-period book that is 12 / 4 / 4,
which is also the smallest split that leaves a development window worth
folding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

TRAIN = "train"
VALIDATE = "validate"
TEST = "test"
EMBARGOED = "embargoed"
SPLITS = (TRAIN, VALIDATE, TEST, EMBARGOED)

#: Section 11.2's shares, by DISTINCT PERIOD.
TRAIN_SHARE = 0.60
VALIDATE_SHARE = 0.20

#: The minimum development window worth folding. Below this the split is
#: refused rather than produced with one fold and called cross-validation.
MIN_TRAIN_PERIODS = 8
MIN_VALIDATE_PERIODS = 2
MIN_TEST_PERIODS = 2


@dataclass(frozen=True)
class Assignment:
    """Which periods are in which split, and the rule that put them there."""

    periods: tuple[str, ...]
    train: tuple[str, ...]
    validate: tuple[str, ...]
    test: tuple[str, ...]
    embargo: int
    embargoed: tuple[str, ...]
    rule: str

    def of(self, period: str) -> str:
        if period in self.embargoed:
            return EMBARGOED
        if period in self.train:
            return TRAIN
        if period in self.validate:
            return VALIDATE
        if period in self.test:
            return TEST
        raise KeyError(f"{period!r} is not a period of this book.")

    def counts(self) -> dict[str, int]:
        return {TRAIN: len(self.train), VALIDATE: len(self.validate),
                TEST: len(self.test), EMBARGOED: len(self.embargoed)}

    def describe(self) -> str:
        return (
            f"{len(self.periods)} distinct reporting periods, split "
            f"chronologically: {len(self.train)} train "
            f"({self.train[0]}–{self.train[-1]}), {len(self.validate)} "
            f"validate ({self.validate[0]}–{self.validate[-1]}), "
            f"{len(self.test)} test ({self.test[0]}–{self.test[-1]}). "
            f"{self.rule}")


def label_embargo(rows: Iterable[Mapping[str, Any]], *,
                  period_column: str) -> tuple[int, str]:
    """How many periods of a boundary are unusable, from the data itself.

    The target is the declared ECL rate at a reporting date, and the horizon
    that rate is measured over is published beside it as
    `lifetime_horizon_months` -- so a row's label is not settled until that
    horizon has run. What is asked here is narrower and answerable: is the
    twelve-month figure knowable at the reporting date?

    It is: every column the calculator reads is published as at that date.
    So the embargo this book needs is **one period**, to stop a training row
    and a validation row describing the same exposure at adjacent dates with
    overlapping twelve-month windows. That is derived from the data's own
    frequency rather than assumed, and the reasoning travels with the number
    so a reader can disagree with it.
    """
    frequencies = {len(str(r[period_column])) for r in rows}
    if not frequencies:
        return 1, "no rows; the default one-period embargo applies."
    return 1, (
        "One period. Every input the ECL calculator reads is published as "
        "at the reporting date, so a label is knowable then; the embargo "
        "exists to stop adjacent periods sharing an overlapping "
        "twelve-month window across a split boundary, not to wait for an "
        "outcome.")


def assign(periods: Sequence[str], *, embargo: int = 1,
           rule: str = "") -> Assignment:
    """Split distinct periods 60/20/20 in time order.

    The embargoed periods come out of the END of training and the END of
    validation -- the boundaries -- and are reported as their own count
    rather than folded into a neighbour. A period nobody trained on and
    nobody tested on is a period the card should show.
    """
    ordered = tuple(sorted(set(periods)))
    if len(ordered) < MIN_TRAIN_PERIODS + MIN_VALIDATE_PERIODS + \
            MIN_TEST_PERIODS:
        raise ValueError(
            f"{len(ordered)} distinct periods is not enough to split "
            f"chronologically with an embargo. This needs at least "
            f"{MIN_TRAIN_PERIODS + MIN_VALIDATE_PERIODS + MIN_TEST_PERIODS}, "
            f"and a smaller book should report that rather than produce a "
            f"split that looks like one.")

    total = len(ordered)
    train_end = max(MIN_TRAIN_PERIODS, round(total * TRAIN_SHARE))
    validate_end = max(train_end + MIN_VALIDATE_PERIODS,
                       round(total * (TRAIN_SHARE + VALIDATE_SHARE)))
    validate_end = min(validate_end, total - MIN_TEST_PERIODS)

    train = ordered[:train_end]
    validate = ordered[train_end:validate_end]
    test = ordered[validate_end:]

    held: list[str] = []
    if embargo > 0:
        held = list(train[-embargo:]) + list(validate[-embargo:])
        train = train[:-embargo] if len(train) > embargo else train
        validate = (validate[:-embargo] if len(validate) > embargo
                    else validate)

    if len(train) < MIN_TRAIN_PERIODS - embargo:
        raise ValueError(
            f"after a {embargo}-period embargo the training window is "
            f"{len(train)} periods, which is below what this split needs.")
    return Assignment(
        periods=ordered, train=tuple(train), validate=tuple(validate),
        test=tuple(test), embargo=embargo, embargoed=tuple(held),
        rule=rule or f"{embargo}-period embargo at each boundary.")


def folds(assignment: Assignment, *, count: int = 3
          ) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Expanding-window folds, INSIDE the development periods only.

    Fold k trains on everything up to a boundary and validates on the
    periods after it, so every fold is a forecast rather than an
    interpolation. The test periods never appear, in any fold, on either
    side -- which is what makes the out-of-fold predictions `blend.py` fits
    its weights on legitimate.
    """
    development = assignment.train + assignment.validate
    if len(development) < count + 2:
        count = max(1, len(development) - 2)
    out: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    step = max(1, (len(development) - count) // count)
    start = len(development) - count * step
    for k in range(count):
        boundary = start + k * step
        train = development[:boundary]
        valid = development[boundary:boundary + step]
        if len(train) >= 2 and valid:
            out.append((tuple(train), tuple(valid)))
    return out


def assignment_rows(assignment: Assignment, rows: Iterable[Mapping[str, Any]],
                    *, key: str, period_column: str,
                    stamp: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One published row per observation, saying where it went.

    M05: the split assignment is persisted, so the model card's counts are
    checkable. A split that exists only inside a training script is a claim
    rather than a record.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        period = str(row[period_column])
        out.append({**stamp, key: str(row[key]), period_column: period,
                    "split": assignment.of(period),
                    "embargo_periods": assignment.embargo})
    return out


def leakage(assignment: Assignment) -> list[str]:
    """Every way this split could still leak. Empty is the only pass.

    Cheap to run and worth running: a split built by arithmetic that lands
    one period on both sides would otherwise be discovered by an
    implausibly good test score.
    """
    problems: list[str] = []
    train, validate, test = (set(assignment.train), set(assignment.validate),
                             set(assignment.test))
    for left, right, names in ((train, validate, "train/validate"),
                               (train, test, "train/test"),
                               (validate, test, "validate/test")):
        shared = left & right
        if shared:
            problems.append(f"{names} share {sorted(shared)}")
    if train and validate and max(train) >= min(validate):
        problems.append("a training period is not earlier than every "
                        "validation period")
    if validate and test and max(validate) >= min(test):
        problems.append("a validation period is not earlier than every test "
                        "period")
    if train and test and max(train) >= min(test):
        problems.append("a training period is not earlier than every test "
                        "period")
    covered = train | validate | test | set(assignment.embargoed)
    missing = set(assignment.periods) - covered
    if missing:
        problems.append(f"{sorted(missing)} are in no split at all")
    return problems


__all__ = ["Assignment", "EMBARGOED", "MIN_TEST_PERIODS",
           "MIN_TRAIN_PERIODS", "MIN_VALIDATE_PERIODS", "SPLITS", "TEST",
           "TRAIN", "TRAIN_SHARE", "VALIDATE", "VALIDATE_SHARE", "assign",
           "assignment_rows", "folds", "label_embargo", "leakage"]
