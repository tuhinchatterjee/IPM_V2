"""
Which way is bad, and which names measure a move.

Why this exists
---------------
A reading can quote a figure exactly and still say the wrong thing about it.
The packet holds a Contracting obligor at `ews_change_1m: -8.0` and another at
`+8.0`; "improved by 8.0" is true of one and false of the other, and the
figure alone cannot tell them apart.

So direction has to be decided from the FACT, not from the number. Two
questions, and this module owns both:

**Is this name a movement?** `ews_change_1m` is; `ews_score` is not. A score
of 3.31 is where something stands, and the verb near it belongs to whatever
moved, not to it.

**Which way is worse?** For the Early Warning score, up. That is the product's
own semantics — the score counts warning evidence — so a positive change is a
deterioration and a negative one an improvement. It is NOT a universal
convention, and this module does not assume it is: the field dictionary
declares `higher_is_worse` per field, a change column inherits it from the
level it measures, and a metric that declares neither is reported as unknown
rather than guessed at. An unknown metric's direction is simply not checked.
"""

from __future__ import annotations

import re
from typing import Any

#: A suffix that turns a level into a movement in it. `ews_score` is a level;
#: `ews_change_1m` is the move in it, and the base metric is what decides
#: which way is worse.
_WINDOW = re.compile(r"_(?:1m|3m|6m|12m|ytd|mom|qoq|yoy)$", re.I)
_MOVEMENT_SUFFIX = re.compile(
    r"_(?:change|delta|move|movement|shift|swing)$", re.I)

#: Names that ARE a movement without being spelled as one. Each is a figure
#: the runtime computes about a change, and each was invisible to a pattern
#: that only looked for the word "change" — which is how a packet holding
#: `largest_deterioration: +8.0` beside `ews_change_1m: -8.0` came to be read
#: as carrying only a fall.
_MOVEMENT_NAMES: frozenset[str] = frozenset({
    "points_contributed", "contribution", "weighted_contribution",
    "largest_improvement", "largest_deterioration", "change",
    "leading_layer_contribution", "ta_change", "score_change",
    "anchor_change", "notch_change", "net_change", "move", "movement",
})

#: How a movement name says which way it went, where the name itself says so.
#: `largest_deterioration` is a rise in the score whatever its sign convention
#: elsewhere, and `largest_improvement` a fall.
_NAMED_DIRECTION: dict[str, int] = {
    "largest_deterioration": +1,
    "largest_improvement": -1,
    "deterioration": +1,
    "improvement": -1,
}

#: The base metric a movement name measures, where it is not derivable by
#: stripping a suffix.
_BASE_OF: dict[str, str] = {
    "points_contributed": "ews_score",
    "contribution": "ews_score",
    "weighted_contribution": "ews_score",
    "leading_layer_contribution": "ews_score",
    "largest_improvement": "ews_score",
    "largest_deterioration": "ews_score",
    "ta_change": "ta_score",
    "score_change": "ews_score",
    "anchor_change": "anchor_score",
    "notch_change": "net_notches",
}

#: Where the dictionary is silent and the name is unmistakable. Kept short on
#: purpose: a metric this product cannot classify is one whose direction goes
#: unchecked, which is the safe answer.
_HIGHER_IS_WORSE: dict[str, bool] = {
    "ews_score": True, "ta_score": True, "classifier_score": True,
    "anchor_score": True, "net_notches": True, "notch_points": True,
    "l1_ta": True, "l2_ta": True, "l3_ta": True, "l4_ta": True,
    "l2_c": True, "l4_c": True,
    "high_plus_count": True, "high_plus_exposure": True,
    "days_past_due": True, "utilisation": True,
}

#: What a direction word in a structured claim means, as a sign on the change.
#: The two vocabularies the product uses — credit ("improved") and arithmetic
#: ("decreased") — because a reading writes in both.
DIRECTIONS: dict[str, int] = {
    "improved": -1, "decreased": -1, "down": -1, "fell": -1,
    "deteriorated": +1, "increased": +1, "up": +1, "rose": +1,
    "unchanged": 0, "held": 0, "flat": 0,
}


def leaf(name: str) -> str:
    """The field a dotted reference ends in."""
    return str(name or "").rsplit(".", 1)[-1].split("[")[0].strip()


def is_a_movement(name: str) -> bool:
    """Whether this name measures a change rather than a level."""
    end = leaf(name)
    if not end:
        return False
    if end in _MOVEMENT_NAMES or end in _NAMED_DIRECTION:
        return True
    stem = _WINDOW.sub("", end)
    if _MOVEMENT_SUFFIX.search(stem) or stem in _MOVEMENT_NAMES:
        return True
    # A bare `change` under a name that says which way: the census publishes
    # `movement_census.largest_deterioration.change`, and the leaf on its own
    # says nothing.
    return bool(named_direction(name))


def base_metric(name: str) -> str:
    """The level a movement measures, or the name itself for a level."""
    end = leaf(name)
    stem = _WINDOW.sub("", end)
    if stem in _BASE_OF:
        return _BASE_OF[stem]
    if end in _BASE_OF:
        return _BASE_OF[end]
    without = _MOVEMENT_SUFFIX.sub("", stem)
    if without != stem:
        for candidate in (f"{without}_score", without):
            if candidate in _HIGHER_IS_WORSE or _declared(candidate) is not None:
                return candidate
    return stem


def _declared(name: str) -> bool | None:
    """`higher_is_worse` as the field dictionary states it, or None."""
    try:
        from backend.early_warning import dictionary as dic

        described = dic.describe(name) or {}
    except Exception:  # noqa: BLE001 - an unreadable dictionary declares nothing
        return None
    value = described.get("higher_is_worse")
    return bool(value) if isinstance(value, bool) else None


def worse_when_positive(name: str) -> int:
    """+1 where a rise is bad, -1 where a rise is good, 0 where nobody says.

    The dictionary first, because it is the governed description of the
    product's own fields; then this module's short list; then unknown. A
    metric nobody has classified is not guessed at — its direction simply
    goes unchecked, which is the difference between a control and a hazard.
    """
    if not is_a_movement(name):
        return 0
    end = leaf(name)
    stem = _WINDOW.sub("", end)
    if stem in _NAMED_DIRECTION or end in _NAMED_DIRECTION:
        # The name says it outright. `largest_deterioration` is a
        # deterioration however the underlying metric is oriented.
        return 1
    base = base_metric(name)
    declared = _declared(base)
    if declared is None:
        declared = _HIGHER_IS_WORSE.get(base)
    if declared is None:
        return 0
    return 1 if declared else -1


def named_direction(name: str) -> int:
    """The direction a name asserts on its own, or 0.

    `largest_deterioration: 8.0` is a RISE of eight even though eight is
    positive and the field says nothing about sign; `largest_improvement:
    -10.0` is a fall. Without this the census read as a fall and a true
    sentence about a deterioration was refused.

    Every segment of the path, not only the last: the census publishes
    `movement_census.largest_deterioration.change`, and the segment that says
    which way it went is the middle one.
    """
    for segment in reversed(str(name or "").replace("[", ".").split(".")):
        stem = _WINDOW.sub("", segment.strip())
        said = _NAMED_DIRECTION.get(stem) or _NAMED_DIRECTION.get(segment)
        if said:
            return said
    return 0


def movement_sign(name: str, value: float) -> int:
    """Which way this fact moved: +1 worse, -1 better, 0 flat or unknown.

    Not the sign of the number — the sign of the CONDITION. A change of -8.0
    in a score where higher is worse is an improvement; the same -8.0 in a
    metric where higher is better would be the opposite, and a metric nobody
    has classified returns 0 and is left alone.
    """
    if not value:
        return 0
    asserted = named_direction(name)
    if asserted:
        return asserted
    orientation = worse_when_positive(name)
    if not orientation:
        return 0
    return orientation if value > 0 else -orientation


def direction_word(word: str) -> int | None:
    """A direction word as a sign, or None where it is not one."""
    return DIRECTIONS.get(str(word or "").strip().lower())


def describes(name: str, value: float) -> str:
    """How the product would say which way this fact went."""
    sign = movement_sign(name, value)
    return {1: "deteriorated", -1: "improved"}.get(sign, "unchanged")


__all__ = ["DIRECTIONS", "base_metric", "describes", "direction_word",
           "is_a_movement", "leaf", "movement_sign", "named_direction",
           "worse_when_positive"]
