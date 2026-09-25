"""The masterscale, in its own published order.

Section 8: *"A rating change moves along the published scale. Do not
increment a grade string, do not sort grades lexically, and do not translate
a notch into a multiplier on PD."*

All three are real mistakes and each produces a plausible-looking answer.

* **Incrementing the string.** `AA` + 1 notch is not `AB`. There is no `AB`
  on this scale, and a book that accepted one would carry a grade nothing
  maps to.
* **Sorting lexically.** Sorted as text, this release's scale reads
  `A, AA, B, B+, BB, BB-, BB+, BBB, BBB+, BBB-, CCC, D` — so a one-notch
  downgrade from `AA` lands on `B`, eight grades past where it belongs, and
  `BB-` sorts before `BB+`. The published `grade_rank` is the order, and it
  is the only order.
* **Turning a notch into a multiplier.** The PD step between grades is not
  constant: on this release `AA` to `A` is a factor of 2.0 and `B` to `CCC`
  is 2.5. One notch is one row of the map, and its PD is the PD that row
  publishes.

Three boundary cases get answers rather than clamps, because each is a
different thing and a reader shown a single silent result cannot tell which
happened:

* **Off the top or bottom of the scale.** The move is applied as far as the
  scale goes and the result SAYS it stopped, with how many notches were
  requested and how many were applied.
* **A grade the scale does not carry.** Refused. An unrated obligor has no
  position to step from, and putting one at the middle of the scale would be
  inventing a rating.
* **The default grade.** Refused for a move in either direction. A defaulted
  obligor carries PD 1.0 by the staging rule rather than by a rating, so
  stepping off `D` is a cure decision, not a notch.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario.errors import (
    MAPPING_UNAVAILABLE,
    PARAMETER_OUT_OF_RANGE,
    raise_for,
)

#: The horizons a published map can carry, and the column each lives in.
HORIZONS: dict[str, str] = {"12m": "pd_12m", "lifetime": "pd_lifetime"}


@dataclass(frozen=True)
class Grade:
    """One row of the published masterscale."""

    grade: str
    rank: int
    pd_12m: Decimal
    pd_lifetime: Decimal
    horizon_months: float
    is_default: bool
    is_investment_grade: bool
    mapping_version: str

    def pd(self, horizon: str = "12m") -> Decimal:
        if horizon not in HORIZONS:
            raise_for(MAPPING_UNAVAILABLE,
                      f"{horizon!r} is not a horizon this map publishes. It "
                      f"has {', '.join(sorted(HORIZONS))}.",
                      field_path="rating.horizon")
        return self.pd_12m if horizon == "12m" else self.pd_lifetime


@dataclass(frozen=True)
class Move:
    """A notch move, and what actually happened to it.

    `requested` and `applied` are separate numbers on purpose. They differ
    only at a scale boundary, and that is exactly the case a reader has to be
    told about: three notches asked for and one applied is not three notches.
    """

    from_grade: Grade
    to_grade: Grade
    requested_notches: int
    applied_notches: int
    stopped_at_boundary: bool
    note: str

    @property
    def pd_change(self) -> Decimal:
        return self.to_grade.pd_12m - self.from_grade.pd_12m

    def describe(self) -> str:
        direction = "downgrade" if self.requested_notches > 0 else "upgrade"
        body = (f"{self.from_grade.grade} {direction} "
                f"{abs(self.requested_notches)} notch"
                f"{'' if abs(self.requested_notches) == 1 else 'es'} to "
                f"{self.to_grade.grade}: PD "
                f"{self.from_grade.pd_12m * 100:.2f}% to "
                f"{self.to_grade.pd_12m * 100:.2f}%")
        return f"{body}. {self.note}" if self.note else body


@dataclass(frozen=True)
class Scale:
    """A published masterscale, in rank order."""

    mapping_version: str
    grades: tuple[Grade, ...]

    @property
    def order(self) -> tuple[str, ...]:
        """The scale as published. A reader can compare this with the book."""
        return tuple(g.grade for g in self.grades)

    @property
    def default_grade(self) -> Grade | None:
        for grade in self.grades:
            if grade.is_default:
                return grade
        return None

    def of(self, grade: str) -> Grade:
        """One grade, or a refusal naming the scale it is not on."""
        for candidate in self.grades:
            if candidate.grade == grade:
                return candidate
        raise_for(MAPPING_UNAVAILABLE,
                  f"{grade!r} is not on the {self.mapping_version} scale, "
                  f"which is {' '.join(self.order)}. An exposure carrying it "
                  f"is unrated as far as this map is concerned, and there is "
                  f"no position on the scale to step from. State the PD you "
                  f"want to assume for it instead.",
                  field_path="rating.grade", scale=list(self.order))
        raise AssertionError("unreachable")  # pragma: no cover

    def notch(self, grade: str, steps: int) -> Move:
        """Step the published order. Positive is a DOWNGRADE.

        The sign convention is stated rather than inferred: ranks run from 1
        at the strongest grade, so a downgrade increases the rank and a
        downgrade is what a stress scenario asks for.
        """
        if int(steps) != steps:
            raise_for(PARAMETER_OUT_OF_RANGE,
                      f"{steps} is not a whole number of notches. A rating "
                      f"moves a grade at a time; there is no half-notch on a "
                      f"published scale.",
                      field_path="rating.notches")
        start = self.of(grade)
        if start.is_default:
            raise_for(PARAMETER_OUT_OF_RANGE,
                      f"{grade!r} is this scale's default grade. A defaulted "
                      f"obligor carries PD 1.0 because it has defaulted, not "
                      f"because of where it sits on a scale, so there is no "
                      f"notch to move. Curing it is a stage decision and "
                      f"needs to be asked for as one.",
                      field_path="rating.grade", is_default_grade=True)
        if steps == 0:
            return Move(start, start, 0, 0, False, "")

        index = self.grades.index(start)
        wanted = index + int(steps)
        landed = max(0, min(len(self.grades) - 1, wanted))
        stopped = landed != wanted
        note = ""
        if stopped:
            edge = "strongest" if wanted < 0 else "weakest"
            note = (
                f"The scale stops at {self.grades[landed].grade}, its "
                f"{edge} grade, so {abs(int(steps))} notches were asked for "
                f"and {abs(landed - index)} were applied. The rest has no "
                f"grade to land on and was not applied as a PD change "
                f"either.")
        return Move(start, self.grades[landed], int(steps), landed - index,
                    stopped, note)

    def pd_for(self, grade: str, horizon: str = "12m") -> Decimal:
        return self.of(grade).pd(horizon)

    def rank_of(self, grade: str) -> int:
        return self.of(grade).rank


def scale(rows: Iterable[Mapping[str, Any]],
          mapping_version: str = "") -> Scale:
    """Build a `Scale` from published `whatif_*_rating_map` rows.

    One mapping version at a time. A map with two versions in it is two maps,
    and merging them would produce a scale that never existed: section 8 asks
    for the mapping version in force to be named, and this is where that is
    made true rather than documented.
    """
    collected = [dict(r) for r in rows]
    versions = {str(r.get("mapping_version") or "") for r in collected}
    if mapping_version:
        collected = [r for r in collected
                     if str(r.get("mapping_version")) == mapping_version]
        versions = {mapping_version}
    if not collected:
        raise_for(MAPPING_UNAVAILABLE,
                  f"no rating map rows for version "
                  f"{mapping_version or '(any)'!r}. A rating change needs a "
                  f"published scale; there is no default one.",
                  field_path="rating.mapping_version")
    if len(versions) > 1:
        raise_for(MAPPING_UNAVAILABLE,
                  f"these rows carry {len(versions)} mapping versions "
                  f"({', '.join(sorted(versions))}). Two versions are two "
                  f"scales and merging them would produce an order that "
                  f"never existed. Name the one in force.",
                  field_path="rating.mapping_version",
                  versions=sorted(versions))

    grades = tuple(sorted(
        (Grade(grade=str(r["rating_grade"]), rank=int(r["grade_rank"]),
                pd_12m=Decimal(str(r["pd_12m"])),
                pd_lifetime=Decimal(str(r["pd_lifetime"])),
                horizon_months=float(r["horizon_months"]),
                is_default=bool(int(r.get("is_default_grade") or 0)),
                is_investment_grade=bool(
                    int(r.get("is_investment_grade") or 0)),
                mapping_version=str(r["mapping_version"]))
         for r in collected),
        key=lambda g: g.rank))

    ranks = [g.rank for g in grades]
    if len(set(ranks)) != len(ranks):
        raise_for(MAPPING_UNAVAILABLE,
                  "this scale publishes two grades at the same rank, so "
                  "'one notch' has no single answer. The order is the map's "
                  "to state.",
                  field_path="rating.grade_rank")
    return Scale(mapping_version=next(iter(versions)), grades=grades)


__all__ = ["Grade", "HORIZONS", "Move", "Scale", "scale"]
