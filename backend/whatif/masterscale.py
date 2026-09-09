"""
The governed rating masterscale, and what a notch is worth.

A rating downgrade is not a PD multiplier
-----------------------------------------
"What happens if these borrowers are downgraded one notch?" was, in every
version of this product before this one, answered by multiplying PD by some
number. That is not how a rating system works and it is not defensible in a
committee: the whole point of a masterscale is that a grade CARRIES a PD, and
moving a borrower down a notch moves it onto the PD the bank has assigned to
that grade.

So a notch is worth what the masterscale says it is worth, and the masterscale
here is the same one the book was graded on: `PERFORMING` with `RATING_BOUNDS`
as the PD band edges. This module reads that authority rather than restating it.

Within-grade calibration is preserved
-------------------------------------
Two BBB borrowers do not have the same PD. Snapping both to the grade's central
PD under a scenario would DESTROY information the bank has and would make the
answer worse than the question. So the shock is applied as the RATIO between
the two grades' masterscale PDs:

    stressed_pd = borrower_pd x (masterscale_pd(stressed_grade)
                                 / masterscale_pd(opening_grade))

A borrower at the strong end of BBB stays at the strong end of BBB-. The
masterscale decides how far the band moved; the borrower keeps its place inside
it. Both figures are reported, so a reader can see the mapping and the
borrower's own position separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import ratingscale
from backend.corporate.ratingscale import (
    ALL_STATES,
    DEFAULT_GRADE,
    PERFORMING_COUNT,
    RATING_BOUNDS,
)

MASTERSCALE_OWNER = "Credit Risk Analytics"
#: 3.0.0 is the governed nineteen-point PERFORMING scale, AAA to C, with
#: default a separate state rather than the scale's last grade, and a TTC PD
#: master calibrated on public corporate default evidence. Earlier scales are
#: gone rather than hidden underneath: there is no second computational grade
#: set, and a figure produced on an older one is not comparable with this.
MASTERSCALE_VERSION = "3.0.0"

PD_FLOOR_PCT = ratingscale.PD_FLOOR_PCT
PD_CEILING_PCT = ratingscale.PD_CEILING_PCT

#: Grade -> the THROUGH-THE-CYCLE twelve-month PD that grade carries, in
#: percent. Read straight from the governed master table rather than
#: reconstructed from the band edges: the masterscale is the definition, and a
#: geometric midpoint of its own bands would be a second opinion about it.
#:
#: D is NOT in this table. The masterscale is the table of performing grades,
#: and a defaulted exposure is measured at 100% by `ratingscale.applicable_pd`
#: rather than by looking a grade up here.
MASTERSCALE: dict[str, float] = dict(ratingscale.TTC_PD_PCT)

#: Index within `ALL_STATES`, so a defaulted name can still be located.
GRADE_INDEX: dict[str, int] = {grade: i for i, grade in enumerate(ALL_STATES)}

#: The performing grades, strongest first. A scenario never downgrades a
#: borrower INTO default: default is an event, not a grade a shock produces.
PERFORMING: tuple[str, ...] = ratingscale.PERFORMING

#: Broad bands, for questions phrased "all BBB borrowers" or "investment
#: grade". The governed table owns them; this is a view of it.
BANDS: dict[str, tuple[str, ...]] = {
    "AAA": ratingscale.BANDS["aaa"],
    "AA": ratingscale.BANDS["aa"],
    "A": ratingscale.BANDS["a"],
    "BBB": ratingscale.BANDS["bbb"],
    "BB": ratingscale.BANDS["bb"],
    "B": ratingscale.BANDS["b"],
    "CCC": ratingscale.BANDS["ccc"],
    "CC": ratingscale.BANDS["cc"],
    "C": ratingscale.BANDS["c"],
    "investment grade": ratingscale.INVESTMENT_GRADE,
    "sub-investment grade": ratingscale.SPECULATIVE_GRADE,
    "speculative grade": ratingscale.SPECULATIVE_GRADE,
    "high yield": ratingscale.SPECULATIVE_GRADE,
}


#: The bands indexed by their lower-cased name, so "BBB", "bbb" and "Bbb" all
#: resolve. Built once rather than lower-casing at every lookup.
_BAND_INDEX: dict[str, tuple[str, ...]] = {k.lower(): v for k, v in BANDS.items()}


@dataclass(frozen=True)
class Move:
    """One borrower's rating move under a scenario."""

    opening: str
    stressed: str
    notches: int
    opening_masterscale_pd: float
    stressed_masterscale_pd: float

    @property
    def factor(self) -> float:
        if self.opening_masterscale_pd <= 0:
            return 1.0
        return self.stressed_masterscale_pd / self.opening_masterscale_pd


def masterscale_pd(grade: str) -> float:
    """The twelve-month PD a grade carries, in percent."""
    return MASTERSCALE.get(str(grade or "").strip().upper(), float("nan"))


def through_the_cycle(grades: Any) -> np.ndarray:
    """The through-the-cycle PD each grade carries, in percent.

    The lifetime PD reverts towards this, so a scenario that moves a grade has
    to move the anchor with it. Read from the governed scale rather than from
    the borrower, because that is the whole point of a masterscale: the level
    belongs to the grade.
    """
    return ratingscale.ttc_pd(
        pd.Series(grades).astype(str).str.strip().str.upper())


def shift(grade: str, notches: int) -> str:
    """Move a grade by `notches` (positive = worse), inside the scale.

    A downgrade stops at the weakest PERFORMING grade. Pushing a borrower into
    D would be asserting a default event that the scenario did not model, and a
    scenario that manufactures defaults out of arithmetic is one nobody should
    believe.
    """
    said = str(grade or "").strip().upper()
    if said not in GRADE_INDEX:
        return said
    if said == DEFAULT_GRADE:
        return said
    landed = GRADE_INDEX[said] + int(notches)
    return ALL_STATES[int(np.clip(landed, 0, PERFORMING_COUNT - 1))]


def move(grade: str, notches: int) -> Move:
    """One grade's move, with both masterscale PDs on it."""
    landed = shift(grade, notches)
    opening = masterscale_pd(grade)
    stressed = masterscale_pd(landed)
    actual = GRADE_INDEX.get(landed, 0) - GRADE_INDEX.get(str(grade or "").upper(), 0)
    return Move(opening=str(grade or "").upper(), stressed=landed,
                notches=int(actual),
                opening_masterscale_pd=opening, stressed_masterscale_pd=stressed)


def factors(grades: pd.Series, notches: int) -> pd.DataFrame:
    """The masterscale move for a column of grades.

    Returns the stressed grade, both masterscale PDs and the PD factor, so the
    answer table can show the mapping rather than assert it.
    """
    said = grades.astype(str).str.strip().str.upper()
    landed = said.map(lambda g: shift(g, notches))
    opening_pd = said.map(masterscale_pd)
    stressed_pd = landed.map(masterscale_pd)
    factor = (stressed_pd / opening_pd.replace(0, np.nan)).fillna(1.0)
    return pd.DataFrame({
        "opening_rating": said,
        "stressed_rating": landed,
        "opening_masterscale_pd": opening_pd,
        "stressed_masterscale_pd": stressed_pd,
        "rating_pd_factor": factor.clip(lower=0.01, upper=200.0),
        "notches_moved": landed.map(lambda g: GRADE_INDEX.get(g, 0))
                         - said.map(lambda g: GRADE_INDEX.get(g, 0)),
    })


def grades_in(band: str) -> tuple[str, ...]:
    """The grades a band names, or the grade itself if it is one.

    The BAND is checked first for the letter-only forms. "All BBB borrowers"
    means BBB+, BBB and BBB- to a credit officer — the crossover band — and
    reading it as the single middle notch answers a narrower question than
    the one asked. A modified grade (BBB+, BBB-) is unambiguous and resolves
    to itself.
    """
    said = str(band or "").strip()
    found = _BAND_INDEX.get(said.lower())
    if found:
        return found
    if said.upper() in GRADE_INDEX:
        return (said.upper(),)
    return ()


def table() -> list[dict[str, object]]:
    """The masterscale, as a reader can check it."""
    out = []
    for index, grade in enumerate(PERFORMING):
        lower = PD_FLOOR_PCT if index == 0 else RATING_BOUNDS[index - 1]
        upper = (PD_CEILING_PCT if index >= len(RATING_BOUNDS)
                 else RATING_BOUNDS[index])
        out.append({
            "grade": grade,
            "pd_floor_pct": round(lower, 4),
            "pd_ceiling_pct": round(upper, 4),
            "masterscale_pd_pct": round(MASTERSCALE[grade], 4),
        })
    return out


__all__ = [
    "BANDS", "GRADE_INDEX", "MASTERSCALE", "MASTERSCALE_OWNER",
    "MASTERSCALE_VERSION", "Move", "PERFORMING", "factors", "grades_in",
    "masterscale_pd", "move", "shift", "table",
]
