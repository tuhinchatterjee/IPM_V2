"""
Driver and contribution analysis. §72.

    "Every contribution must reconcile to the relevant total within tolerance.
     Do not calculate contribution for non-additive measures without a
     governed method."

Both sentences are refusals, and they are the module. Contribution analysis is
easy to compute and easy to compute wrongly, and the two wrong ways are:
attributing a change to parts that do not add back to it, and attributing a
change in a ratio as though a ratio had parts.

Reconciliation is not a check, it is the output
------------------------------------------------
`decompose` returns a Result carrying the residual, and the residual is
reported whether or not it is small. A contribution table that quietly absorbs
0.4% into rounding is a table somebody will later find does not tie, and by
then it will be in a board pack.

Non-additive measures
---------------------
A ratio has no parts. "ECL coverage rose 40bp, of which Contracting
contributed 12bp" is meaningless unless somebody has defined what contributing
to a ratio means — and there is a right answer (a weighted decomposition into
numerator and denominator effects), which is a governed METHOD, not something
to infer here. So `decompose` refuses a ratio and names the method that would
be needed.

Offsets are the interesting half
---------------------------------
§72 asks for "offsetting favorable/adverse effects", and it is the part most
contribution tables leave out. A total that moved 5 can be twenty entities
moving +30 and eighteen moving −25, and the sentence "ECL rose by 5" describes
that portfolio as badly as any sentence could.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

DRIVER_VERSION = "1.0.0"

#: How far a decomposition may miss its total before it is a defect rather
#: than arithmetic. Relative, because an absolute tolerance is either
#: meaningless on a large book or unreachable on a small one.
TOLERANCE = 1e-6

#: How much of the movement the top contributors have to explain before the
#: word "driven" is earned. Below it the answer is a distribution, not a
#: driver, and calling it one is the most common overstatement in a credit
#: narrative.
DRIVEN_AT = 0.5


class NotAdditive(ValueError):
    """A contribution was asked for on a measure that has no parts."""


@dataclass
class Contribution:
    """One entity's share of a movement."""

    entity_id: str
    entity_name: str = ""
    opening: float = 0.0
    closing: float = 0.0
    #: Absolute contribution to the change. Signed: a favourable mover has a
    #: negative contribution to a deterioration and that is the point.
    contribution: float = 0.0
    #: Share of the TOTAL MOVEMENT, which can exceed 1 and can be negative
    #: when offsets are present. Not clamped: clamping it would hide exactly
    #: the case the reader needs.
    share_of_change: float = 0.0
    #: Share of the opening level, so a large mover on a small base is
    #: distinguishable from a small mover on a large one.
    share_of_opening: float = 0.0
    #: True when the entity was absent at one of the two dates.
    entered: bool = False
    exited: bool = False

    @property
    def adverse(self) -> bool:
        return self.contribution > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id, "entity_name": self.entity_name,
            "opening": self.opening, "closing": self.closing,
            "contribution": self.contribution,
            "share_of_change": self.share_of_change,
            "share_of_opening": self.share_of_opening,
            "entered": self.entered, "exited": self.exited,
        }


@dataclass
class Result:
    """A decomposition, and everything a reader needs to trust it."""

    metric: str = ""
    opening_total: float = 0.0
    closing_total: float = 0.0
    contributions: list[Contribution] = field(default_factory=list)
    #: What the parts do not explain. Reported whether or not it is small.
    residual: float = 0.0
    tolerance: float = TOLERANCE
    limitations: list[str] = field(default_factory=list)

    @property
    def change(self) -> float:
        return self.closing_total - self.opening_total

    @property
    def reconciles(self) -> bool:
        scale = max(abs(self.change), abs(self.opening_total), 1.0)
        return abs(self.residual) <= self.tolerance * scale

    @property
    def adverse(self) -> list[Contribution]:
        return sorted((c for c in self.contributions if c.contribution > 0),
                      key=lambda c: -c.contribution)

    @property
    def favourable(self) -> list[Contribution]:
        return sorted((c for c in self.contributions if c.contribution < 0),
                      key=lambda c: c.contribution)

    @property
    def entered(self) -> list[Contribution]:
        return [c for c in self.contributions if c.entered]

    @property
    def exited(self) -> list[Contribution]:
        return [c for c in self.contributions if c.exited]

    def gross(self) -> tuple[float, float]:
        """Adverse and favourable movement, before they cancel.

        The number a net change hides. A total that moved 5 out of 30 adverse
        and 25 favourable is a different portfolio from one that moved 5 out
        of 5 adverse and 0 favourable, and only one of them is calm.
        """
        return (sum(c.contribution for c in self.adverse),
                sum(c.contribution for c in self.favourable))

    def top(self, n: int = 5) -> list[Contribution]:
        return sorted(self.contributions,
                      key=lambda c: -abs(c.contribution))[:n]

    def explained_by_top(self, n: int = 5) -> float:
        """How much of the MOVEMENT the largest n movers explain.

        Against the gross adverse movement rather than the net, because
        against a net of nearly zero every share is enormous and the number
        stops meaning anything.
        """
        adverse, favourable = self.gross()
        scale = max(abs(adverse), abs(favourable))
        if scale <= 0:
            return 0.0
        return sum(abs(c.contribution) for c in self.top(n)) / (
            abs(adverse) + abs(favourable))

    @property
    def driven(self) -> bool:
        """Whether "driven by" is an honest word for this.

        Below the threshold the answer is a distribution, and calling a
        distribution a driver is the most common overstatement in a credit
        narrative.
        """
        return self.explained_by_top(3) >= DRIVEN_AT

    def to_dict(self) -> dict[str, Any]:
        adverse, favourable = self.gross()
        return {
            "version": DRIVER_VERSION,
            "metric": self.metric,
            "opening_total": self.opening_total,
            "closing_total": self.closing_total,
            "change": self.change,
            "residual": self.residual,
            "reconciles": self.reconciles,
            "gross_adverse": adverse,
            "gross_favourable": favourable,
            "entered": [c.to_dict() for c in self.entered],
            "exited": [c.to_dict() for c in self.exited],
            "top": [c.to_dict() for c in self.top()],
            "explained_by_top_3": round(self.explained_by_top(3), 4),
            "explained_by_top_5": round(self.explained_by_top(5), 4),
            "driven": self.driven,
            "contributions": [c.to_dict() for c in self.contributions],
            "limitations": list(self.limitations),
        }


def decompose(metric: str, opening: dict[str, float],
              closing: dict[str, float], *, names: dict[str, str] | None = None,
              additive: bool = True,
              governed_method: str = "",
              tolerance: float = TOLERANCE) -> Result:
    """Attribute a movement to the entities that made it. §72.

    `additive` is the caller's statement about the MEASURE, not about the
    numbers. A sum of exposures is additive; a coverage ratio is not, whatever
    its parts happen to add to. Passing additive=False without a governed
    method raises, because the alternative is a plausible table nobody can
    defend.
    """
    if not additive and not governed_method:
        raise NotAdditive(
            f"{metric!r} is not additive, so it has no contributions. A ratio "
            "moves through its numerator and its denominator, and attributing "
            "that to entities needs a governed method — name one, or "
            "decompose the numerator and denominator separately.")

    known = dict(names or {})
    entities = sorted(set(opening) | set(closing))
    opening_total = sum(opening.values())
    closing_total = sum(closing.values())
    change = closing_total - opening_total

    contributions: list[Contribution] = []
    for entity in entities:
        before = float(opening.get(entity, 0.0))
        after = float(closing.get(entity, 0.0))
        moved = after - before
        contributions.append(Contribution(
            entity_id=entity,
            entity_name=known.get(entity, entity),
            opening=before, closing=after, contribution=moved,
            share_of_change=(moved / change) if change else 0.0,
            share_of_opening=(moved / before) if before else 0.0,
            entered=entity not in opening,
            exited=entity not in closing,
        ))

    result = Result(metric=metric, opening_total=opening_total,
                    closing_total=closing_total, contributions=contributions,
                    residual=change - sum(c.contribution
                                          for c in contributions),
                    tolerance=tolerance)
    if governed_method:
        result.limitations.append(
            f"Contributions computed by the governed method "
            f"{governed_method}.")
    if result.entered or result.exited:
        result.limitations.append(
            f"{len(result.entered)} entities entered and "
            f"{len(result.exited)} left between the two dates; their "
            "contribution is a population change, not a movement in the "
            "entities that were there throughout.")
    return result


def matched(opening: dict[str, float],
            closing: dict[str, float]) -> tuple[dict[str, float],
                                                dict[str, float]]:
    """The two sides restricted to entities present in both.

    §71's challenge asks whether new or exited customers drove a movement, and
    the honest way to answer it is to compute the movement twice: once over
    everything and once over the matched population. The difference between
    the two answers IS the population effect.
    """
    both = set(opening) & set(closing)
    return ({k: v for k, v in opening.items() if k in both},
            {k: v for k, v in closing.items() if k in both})


def population_effect(metric: str, opening: dict[str, float],
                      closing: dict[str, float]) -> dict[str, Any]:
    """How much of a movement is the population changing rather than moving."""
    everything = decompose(metric, opening, closing)
    left, right = matched(opening, closing)
    like_for_like = decompose(metric, left, right)
    return {
        "total_change": everything.change,
        "matched_change": like_for_like.change,
        "population_change": everything.change - like_for_like.change,
        "entered": len(everything.entered),
        "exited": len(everything.exited),
        "matched_entities": len(left),
        "share_from_population": (
            (everything.change - like_for_like.change) / everything.change
            if everything.change else 0.0),
    }


def offsets(result: Result) -> dict[str, Any]:
    """§72's "offsetting favorable/adverse effects", as a statement.

    Returned as its own object because a narrative that mentions only the net
    is describing the portfolio badly, and the sentence that fixes it needs
    both gross numbers and the ratio between them.
    """
    adverse, favourable = result.gross()
    net = result.change
    hidden = min(abs(adverse), abs(favourable))
    return {
        "gross_adverse": adverse,
        "gross_favourable": favourable,
        "net": net,
        "offset": hidden,
        #: How much movement the net number conceals, as a multiple of itself.
        #: Large where a calm total hides a churning book.
        "offset_ratio": (hidden / abs(net)) if abs(net) > 1e-12 else
                        (math.inf if hidden else 0.0),
        "material_offset": bool(hidden) and (
            abs(net) < 1e-12 or hidden / abs(net) >= 0.25),
    }


__all__ = ["Contribution", "DRIVEN_AT", "DRIVER_VERSION", "NotAdditive",
           "Result", "TOLERANCE", "decompose", "matched", "offsets",
           "population_effect"]
