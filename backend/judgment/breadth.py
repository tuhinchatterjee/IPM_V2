"""
Breadth versus concentration. §73.

    "Do not let the LLM decide broad versus concentrated from prose alone."

The distinction matters more than almost anything else in a credit narrative,
because it decides what somebody does next. "Contracting deteriorated" leads to
a segment review; "Contracting deteriorated because two names blew up" leads to
two phone calls. Getting it backwards wastes a quarter either way.

Why four verdicts and not two
------------------------------
BROAD and CONCENTRATED are the answers people want. MIXED and UNDETERMINED are
the answers the data frequently supports, and a two-valued engine forces one of
the first two onto evidence that does not carry it. MIXED is a real finding —
a handful of large movers on top of a general drift is a different portfolio
from either alone. UNDETERMINED means too few entities to tell, and saying so
is better than a confident answer computed over four borrowers.

The measures, and what each one catches alone
----------------------------------------------
Top-n share catches the obvious case and misses a hundred-name drift with one
outlier. Affected count catches the drift and misses that the drift is
immaterial. Herfindahl catches the shape of the distribution and says nothing
about how much moved. Threshold crossings catch what a credit officer actually
watches. So the verdict reads several and states which ones drove it, and where
they disagree the verdict is MIXED rather than whichever fired first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.judgment import drivers as dr

BREADTH_VERSION = "1.0.0"

BROAD = "BROAD"
CONCENTRATED = "CONCENTRATED"
MIXED = "MIXED"
UNDETERMINED = "UNDETERMINED"

VERDICTS: tuple[str, ...] = (BROAD, CONCENTRATED, MIXED, UNDETERMINED)

#: Below this many moving entities there is nothing to be broad across. Four
#: borrowers cannot show a segment-wide pattern, and a confident verdict over
#: four is a verdict about noise.
MIN_ENTITIES = 8

#: The top three explaining this much of the movement is concentration.
CONCENTRATED_AT = 0.60
#: No entity explaining more than this, with most of the population moving the
#: same way, is breadth.
BROAD_TOP_AT = 0.25
#: The share of entities that must move adversely before "across the segment"
#: is an honest phrase.
BROAD_PARTICIPATION_AT = 0.50

#: Herfindahl above this is a concentrated contribution distribution whatever
#: the top-n share says. Computed over contribution shares, not exposures.
HHI_CONCENTRATED_AT = 0.18


@dataclass
class Verdict:
    """How a movement is distributed, and what said so."""

    verdict: str = UNDETERMINED
    #: Every measure that was computed, so a reader can disagree with the one
    #: they think is wrong rather than with the conclusion.
    measures: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    #: The entities the verdict is about, most significant first.
    leaders: list[str] = field(default_factory=list)

    @property
    def determined(self) -> bool:
        return self.verdict != UNDETERMINED

    def sentence(self) -> str:
        """The clause a narrative may use. Never stronger than the verdict."""
        return {
            BROAD: "The movement is broad across the population.",
            CONCENTRATED: "The movement is concentrated in a few names.",
            MIXED: "A few large movers sit on top of a wider drift.",
            UNDETERMINED: "There are too few moving entities to say whether "
                          "this is broad or concentrated.",
        }[self.verdict]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": BREADTH_VERSION,
            "verdict": self.verdict,
            "sentence": self.sentence(),
            "measures": dict(self.measures),
            "reasons": list(self.reasons),
            "leaders": list(self.leaders),
        }


def herfindahl(shares: list[float]) -> float:
    """The Herfindahl index of a set of shares.

    Computed over ABSOLUTE contribution shares so offsetting movers do not
    cancel into a spuriously diffuse index: a book where one name moved +50
    and another −50 is concentrated, and a signed index would call it empty.
    """
    total = sum(abs(s) for s in shares)
    if total <= 0:
        return 0.0
    return sum((abs(s) / total) ** 2 for s in shares)


def assess(result: dr.Result, *,
           threshold_crossings: int = 0,
           population: int = 0) -> Verdict:
    """§73's decision, from §73's measures.

    `threshold_crossings` is what a credit officer actually watches — names
    that crossed a covenant, a stage boundary, a DPD bucket — and it is passed
    in because it is not derivable from a contribution table.
    """
    moving = [c for c in result.contributions
              if abs(c.contribution) > 0]
    adverse = result.adverse
    total = population or len(result.contributions)

    measures: dict[str, Any] = {
        "entities": len(result.contributions),
        "moving": len(moving),
        "adverse": len(adverse),
        "population": total,
        "participation": (len(adverse) / total) if total else 0.0,
        "top_1": result.explained_by_top(1),
        "top_3": result.explained_by_top(3),
        "top_5": result.explained_by_top(5),
        "hhi": herfindahl([c.contribution for c in result.contributions]),
        "threshold_crossings": threshold_crossings,
        "offsets": dr.offsets(result),
    }

    if len(moving) < MIN_ENTITIES:
        return Verdict(
            verdict=UNDETERMINED, measures=measures,
            reasons=[f"only {len(moving)} entities moved; at least "
                     f"{MIN_ENTITIES} are needed before breadth means "
                     "anything"],
            leaders=[c.entity_id for c in result.top(3)])

    reasons: list[str] = []
    concentrated = False
    broad = False

    if measures["top_3"] >= CONCENTRATED_AT:
        concentrated = True
        reasons.append(f"the three largest movers explain "
                       f"{measures['top_3']:.0%} of the movement")
    if measures["hhi"] >= HHI_CONCENTRATED_AT:
        concentrated = True
        reasons.append(f"the contribution distribution is concentrated "
                       f"(Herfindahl {measures['hhi']:.2f})")

    if measures["top_1"] <= BROAD_TOP_AT and \
            measures["participation"] >= BROAD_PARTICIPATION_AT:
        broad = True
        reasons.append(
            f"{measures['participation']:.0%} of the population moved "
            f"adversely and no single name explains more than "
            f"{measures['top_1']:.0%}")
    if threshold_crossings and total and \
            threshold_crossings / total >= BROAD_PARTICIPATION_AT:
        broad = True
        reasons.append(f"{threshold_crossings} of {total} entities crossed a "
                       "governed threshold")

    if concentrated and broad:
        # Both fired. That is a real portfolio shape, not an error: a handful
        # of large movers on top of a general drift. Reporting either half
        # alone would be wrong in a way somebody acts on.
        verdict = MIXED
    elif concentrated:
        verdict = CONCENTRATED
    elif broad:
        verdict = BROAD
    else:
        verdict = MIXED
        reasons.append("no measure reached a threshold in either direction")

    return Verdict(verdict=verdict, measures=measures, reasons=reasons,
                   leaders=[c.entity_id for c in result.top(5)])


__all__ = ["BREADTH_VERSION", "BROAD", "BROAD_PARTICIPATION_AT",
           "BROAD_TOP_AT", "CONCENTRATED", "CONCENTRATED_AT",
           "HHI_CONCENTRATED_AT", "MIN_ENTITIES", "MIXED", "UNDETERMINED",
           "VERDICTS", "Verdict", "assess", "herfindahl"]
