"""
What a credit officer means by "worsening".

"Rating downgrade", "worsening leverage", "declining DSCR", "increase in ECL" —
four phrases, four different comparisons, and which comparison each one implies
is not a property of the phrase. It is a property of the **measure**:

  leverage    higher is worse   →  "worsening" means the number went UP
  DSCR        higher is better  →  "declining" means the number went DOWN
  rating      ordinal, 1 best   →  "downgrade" means the grade number went UP
  ECL         higher is worse   →  "increase" means the number went UP

The old Ask experience buried this in phrase tables, so it understood exactly
the sentences somebody had written down. Here the direction words are a small
closed vocabulary — English, not credit risk — and the *credit meaning* comes
from the governed concept's own `higher_is_worse` and `is_ordinal` metadata. Add
a concept to the catalogue and every one of these phrases works on it without
touching this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.orchestration.dynamic import Condition

# ---------------------------------------------------------------- direction
#
# Three families, because they mean different things:
#
#   WORSE / BETTER   evaluative — the direction depends on the measure
#   UP / DOWN        literal — the direction is stated outright
#   FLOOR            "did not fall" — a bound rather than a movement


@dataclass(frozen=True)
class Direction:
    """A movement word, and what it asserts."""

    id: str
    pattern: str
    #: worse | better | up | down | up_floor | down_floor
    kind: str


DIRECTIONS: tuple[Direction, ...] = (
    # Evaluative — resolved against the measure's own polarity.
    Direction("worse", r"worsen\w*|deteriorat\w*|weaken\w*|declin\w*|"
                       r"under ?perform\w*|slipp\w*|eroded?|erosion", "worse"),
    Direction("better", r"improv\w*|strengthen\w*|recover\w*|better", "better"),
    # Rating-specific, and still evaluative: a downgrade is a worse rating
    # whichever way the scale happens to be numbered.
    Direction("downgrade", r"downgrad\w*|notch(?:ed)? down|fell \w* notch", "worse"),
    Direction("upgrade", r"upgrad\w*|notch(?:ed)? up", "better"),
    # Literal — the user has named the direction of the number itself.
    Direction("up", r"increas\w*|ris\w*|rose|grew|grow\w*|higher|up\b|"
                    r"jump\w*|climb\w*|expand\w*", "up"),
    Direction("down", r"decreas\w*|fell|fall\w*|drop\w*|lower|down\b|"
                      r"shrank|shrink\w*|contract\w*|reduc\w*", "down"),
    # Bounds.
    Direction("no_fall", r"(?:did not|didn't|has not|hasn't|no|without)\s+"
                         r"(?:fall|decline|decrease|drop|reduc\w*)", "up_floor"),
    Direction("no_rise", r"(?:did not|didn't|has not|hasn't|no|without)\s+"
                         r"(?:rise|increase|grow|climb)", "down_floor"),
)

#: Numbers people write as words. "two notches" is as common as "2 notches",
#: and a magnitude reader that only sees digits silently drops the threshold —
#: which turns "deteriorated at least two notches" into "deteriorated at all"
#: and returns a much larger population than was asked for.
#: Deliberately no "a"/"an": as a magnitude they are almost always the article,
#: and "more than a rating downgrade" is not a threshold of one.
_WORD_NUMBERS: dict[str, float] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}

#: Words that quantify a movement. "more than 20%", "at least two notches".
_MAGNITUDE = re.compile(
    r"(?:(?P<bound>more than|greater than|at least|over|above|"
    r"less than|below|under|at most|no more than)\s+)?"
    r"\b(?P<value>\d+(?:\.\d+)?|"
    + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")\b\s*"
    r"(?P<unit>%|percent|percentage points?|notch(?:es)?|x\b|times)?",
    re.IGNORECASE,
)


def _magnitude_value(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        return _WORD_NUMBERS.get(raw.lower(), 0.0)

_STRICT = {"more than": "gt", "greater than": "gt", "over": "gt", "above": "gt",
           "less than": "lt", "below": "lt", "under": "lt"}
_INCLUSIVE = {"at least": "gte", "at most": "lte", "no more than": "lte"}


@dataclass(frozen=True)
class Movement:
    """A direction, with a magnitude where the question gave one."""

    direction: Direction
    value: float = 0.0
    #: pct | notches | absolute
    unit: str = "absolute"
    bound: str = ""
    phrase: str = ""


def find_movement(text: str) -> Movement | None:
    """The movement word in a fragment, and any number attached to it."""
    lowered = text.lower()
    best: tuple[int, Direction] | None = None
    for direction in DIRECTIONS:
        match = re.search(direction.pattern, lowered)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), direction)
    if best is None:
        return None

    direction = best[1]
    # The magnitude must come AFTER the movement word. "increased more than
    # 20%" and "deteriorated at least two notches" both do; "Stage 2 increased"
    # does not, and reading its 2 as a threshold turns "Stage 2 rose" into
    # "stage rose by more than two", which is a different and empty question.
    at = re.search(direction.pattern, lowered)
    tail = lowered[at.end():] if at else ""
    magnitude = _MAGNITUDE.search(tail)
    if not magnitude:
        return Movement(direction=direction, phrase=text.strip())

    raw_unit = (magnitude.group("unit") or "").lower()
    unit = ("pct" if raw_unit.startswith(("%", "percent")) else
            "notches" if raw_unit.startswith("notch") else "absolute")
    bound = (magnitude.group("bound") or "").lower().strip()
    return Movement(
        direction=direction,
        value=_magnitude_value(magnitude.group("value")),
        unit=unit,
        bound=_STRICT.get(bound) or _INCLUSIVE.get(bound, ""),
        phrase=text.strip(),
    )


# ------------------------------------------------------------- the resolution


def condition_for(match: Any, movement: Movement | None) -> Condition | None:
    """The comparison a movement implies, given what the measure IS.

    `match` is a resolved `ConceptMatch` — it knows the field, whether higher is
    worse, and whether the scale is ordinal. That metadata, not the wording, is
    what decides the direction of the test.
    """
    concept = match.concept
    if concept.is_categorical:
        # A category does not move. "sentiment is negative" is a level test, and
        # it is handled by the caller that knows the polarity vocabulary.
        return None

    if movement is None:
        # A concept named with no direction is not a condition. It is either the
        # measure the answer is ranked by or simply context, and inventing a
        # comparison for it would filter a population the user never asked to
        # narrow.
        return None

    kind = movement.direction.kind
    higher_is_worse = concept.higher_is_worse

    # Evaluative words resolve against the measure's polarity. This is the
    # whole point of the module: "worsening" on leverage and "worsening" on
    # DSCR are opposite tests, and neither is written down anywhere.
    if kind == "worse":
        rising = higher_is_worse
    elif kind == "better":
        rising = not higher_is_worse
    elif kind in {"up", "up_floor"}:
        rising = True
    elif kind in {"down", "down_floor"}:
        rising = False
    else:  # pragma: no cover - the enum above is closed
        return None

    floor = kind.endswith("_floor")
    if floor:
        # "did not fall" is >= 0, not > 0.
        op = "gte" if rising else "lte"
        threshold = 0.0
    elif movement.value:
        op = movement.bound or ("gte" if movement.direction.id in
                                {"downgrade", "upgrade"} else "gt")
        if not rising:
            op = {"gt": "lt", "gte": "lte", "lt": "gt", "lte": "gte"}.get(op, op)
        threshold = movement.value
    else:
        op = "gt" if rising else "lt"
        threshold = 0.0

    # An ordinal scale moves in notches; everything else moves in its own unit
    # or as a percentage, and a percentage change of a rating grade is
    # meaningless.
    if concept.is_ordinal:
        comparison = "change_abs"
        if not rising and threshold:
            threshold = -threshold
    elif movement.unit == "pct":
        comparison = "change_pct"
        if not rising and threshold:
            threshold = -threshold
    else:
        comparison = "change_abs"
        if not rising and threshold:
            threshold = -threshold

    return Condition(
        field=match.field, kind=comparison, op=op, value=threshold,
        phrase=movement.phrase or movement.direction.id,
        higher_is_worse=higher_is_worse,
    )


# ----------------------------------------------------------------- clauses
#
# Splitting a sentence into "one measure, one movement" fragments. This is
# ordinary English parsing, not credit knowledge: everything credit-specific
# happens in condition_for() above, against the governed concept.

_SPLIT = re.compile(
    r"\s*(?:,\s*(?:and|or|but)?\s*|\band\b|\bwhile\b|\balong ?with\b|"
    r"\btogether with\b|\bas well as\b|\bplus\b|;)\s*", re.IGNORECASE)


def clauses(question: str) -> list[str]:
    """The fragments of a question, each hopefully naming one measure.

    Deliberately crude. A fragment that names two measures is handled by the
    caller matching each concept's own phrase position, and a fragment that
    names none is skipped.
    """
    text = " ".join(str(question or "").split())
    parts = [p.strip(" .?!") for p in _SPLIT.split(text)]
    return [p for p in parts if p]


def movement_near(question: str, phrase: str, *,
                  window: int = 60) -> Movement | None:
    """The movement word attached to one concept's phrase.

    Looks in the clause containing the phrase first, then in a window around it
    — "rating downgrade" puts the direction after the measure while "declining
    DSCR" puts it before, and both are ordinary.
    """
    if not phrase:
        return None
    for clause in clauses(question):
        if phrase.lower() in clause.lower():
            found = find_movement(clause)
            if found is not None:
                return found

    text = str(question or "")
    at = text.lower().find(phrase.lower())
    if at < 0:
        return None
    start = max(0, at - window)
    end = min(len(text), at + len(phrase) + window)
    return find_movement(text[start:end])


__all__ = [
    "DIRECTIONS",
    "Direction",
    "Movement",
    "clauses",
    "condition_for",
    "find_movement",
    "movement_near",
]
