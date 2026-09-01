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
    # No movement at all, which is a condition and not the absence of one.
    # "Unchanged ratings but materially rising PD" asks for borrowers whose
    # rating held while their PD moved — a divergence, and the whole point of
    # the question. Read as no condition it becomes "rising PD", which is a
    # much larger population and a different finding.
    Direction("unchanged", r"unchanged|\bflat\b|stable|steady|no change|"
                           r"(?:did not|didn't|has not|hasn't) (?:move|change)|"
                           r"held steady|stayed the same", "flat"),
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


#: Words that carry no measure between a name and the movement asserted of it.
#: "was downgraded", "a downgrade", "the increase in" — stripping these is what
#: lets the reader see that nothing but a movement word is left.
_FILLER = re.compile(
    r"\b(?:a|an|the|is|are|was|were|be|been|has|have|had|its|their|this|that|"
    r"in|of|on|to|by|and)\b|[^\w%]+", re.IGNORECASE)


def phrase_asserts_movement(phrase: str) -> Movement | None:
    """The movement a concept's OWN phrase asserts, where it asserts one.

    This is the other half of the masking rule below, and leaving it out was a
    release-blocking defect. "Which customers were downgraded and had expected
    credit loss rise?" resolves "downgraded" to the internal rating — the word
    is how the rating concept is named in that sentence — and the mask then
    blanked it out before looking for a movement. Nothing was left to find, no
    condition was built, no filter reached the plan, and the answer returned
    every customer whose ECL rose whether or not they had been downgraded. The
    heading said both conditions; the rows honoured one.

    The distinction is whether the movement word is the WHOLE phrase or only a
    part of it. "probability of credit deterioration" is the NAME of a measure
    and asserts nothing; "downgraded" is an assertion and names nothing. So the
    movement has to account for the entire phrase once ordinary filler is
    removed — which "deterioration" inside a five-word noun phrase does not.
    """
    text = str(phrase or "").strip()
    if not text:
        return None
    found: tuple[int, int] | None = None
    for direction in DIRECTIONS:
        at = re.search(direction.pattern, text.lower())
        if at and (found is None or at.start() < found[0]):
            found = (at.start(), at.end())
    if found is None:
        return None
    remainder = text[:found[0]] + " " + text[found[1]:]
    if _FILLER.sub(" ", remainder).strip():
        # Something other than the movement word is in the phrase, so the
        # phrase names a measure and the word is part of the name.
        return None
    return find_movement(text)


def _mask(clause: str, phrase: str) -> str:
    """The clause with the concept's own phrase blanked out.

    Same length, so any offset a caller derived from the clause still points
    where it did.
    """
    at = _where(clause, phrase)
    if at < 0:
        return clause
    return clause[:at] + (" " * len(phrase)) + clause[at + len(phrase):]


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
    if magnitude and _is_a_period(tail, magnitude):
        # "an increase in ECL over the latest 6 months" says WHEN, not HOW MUCH.
        # Reading the 6 as a threshold turned a question about a year into
        # "ECL rose by more than six", which is a different and much smaller
        # cohort — and nothing on screen said so.
        magnitude = None
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


#: Units that make a number a span of time rather than a size of movement.
#: A length of time, allowing one adjective between the number and the unit.
#:
#: "over the last four REPORTING periods" slipped past the bare version: the
#: guard looked for a time unit immediately after the number, found the word
#: "reporting", and concluded the 4 was a threshold. Every condition in the
#: sentence then acquired one — "leverage rose more than 4", "covenant
#: headroom fell more than 4%", "DSCR fell more than 4x" — and a question
#: about four quarters of history became a question about a magnitude nobody
#: named. "calendar quarters", "fiscal years" and "trading days" are the same
#: shape.
_TIME_UNIT = re.compile(
    r"^\s*(?:(?:reporting|calendar|fiscal|financial|trading|business|"
    r"consecutive|full)\s+)?"
    r"(?:months?|quarters?|years?|weeks?|days?|periods?)\b", re.I)


def _is_a_period(tail: str, magnitude: Any) -> bool:
    """Whether the number after a movement word is a length of time."""
    return bool(_TIME_UNIT.match(tail[magnitude.end():]))


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
    elif kind == "flat":
        # Neither direction: the measure is asserted not to have moved.
        comparison = "change_abs"
        return Condition(
            field=match.field, kind=comparison, op="eq", value=0.0,
            phrase=movement.phrase or movement.direction.id,
            higher_is_worse=higher_is_worse)
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
    r"\s*(?:,\s*(?:and|or|but)?\s*|\band\b|\bor\b|\bbut\b|\bwhile\b|"
    r"\balong ?with\b|\btogether with\b|\bas well as\b|\bplus\b|;)\s*",
    re.IGNORECASE)


def clauses(question: str) -> list[str]:
    """The fragments of a question, each hopefully naming one measure.

    Deliberately crude. A fragment that names two measures is handled by the
    caller matching each concept's own phrase position, and a fragment that
    names none is skipped.
    """
    text = " ".join(str(question or "").split())
    parts = [p.strip(" .?!") for p in _SPLIT.split(text)]
    return [p for p in parts if p]


def _pattern_for(phrase: str) -> re.Pattern[str]:
    """A phrase matched on WORD BOUNDARIES, with flexible internal spacing.

    Substring matching was a real defect and a subtle one. "EAD" occurs inside
    "h-EAD-room", so in

        "... worsening DPD and declining covenant headroom over the latest
         year? Rank them by EAD."

    the concept EAD was found in the covenant clause, inherited that clause's
    "declining", and became a fifth cohort condition — "EAD rose" — on a
    question that only asked for the answer to be ordered by it. The cohort was
    silently narrower than the one requested. Any short measure abbreviation
    can collide this way; the boundary is what makes it impossible.
    """
    spaced = re.escape(" ".join(str(phrase).split())).replace(r"\ ", r"\s+")
    # \b does not fire next to a digit-adjacent boundary like "IFRS 9", so the
    # boundaries are asserted as "not a word character" lookarounds instead.
    return re.compile(rf"(?<!\w){spaced}(?!\w)", re.I)


def _mentions(text: str, phrase: str) -> bool:
    """Whether `text` names this concept, as a word rather than as letters."""
    if not phrase:
        return False
    return bool(_pattern_for(phrase).search(str(text or "")))


def _where(text: str, phrase: str) -> int:
    """Where `text` names this concept, or -1."""
    if not phrase:
        return -1
    found = _pattern_for(phrase).search(str(text or ""))
    return found.start() if found else -1


def movement_near(question: str, phrase: str, *,
                  window: int = 60) -> Movement | None:
    """The movement word attached to one concept's phrase.

    Looks in the clause containing the phrase first, then in a window around it
    — "rating downgrade" puts the direction after the measure while "declining
    DSCR" puts it before, and both are ordinary.
    """
    if not phrase:
        return None
    # A phrase that IS a movement word asserts it. Checked before the clause
    # walk because the mask below would otherwise erase the only evidence.
    asserted = phrase_asserts_movement(phrase)
    if asserted is not None:
        return asserted
    for clause in clauses(question):
        if _mentions(clause, phrase):
            # A movement word INSIDE the concept's own phrase is part of the
            # measure's NAME, not an assertion about how the measure moved.
            #
            # "the 10 borrowers with the highest probability of credit
            # deterioration over the next 12 months" resolves to twelve-month
            # PD, and the word "deterioration" that made it resolve was then
            # read a second time as "PD deteriorated". A request for a ranking
            # became a cohort of everyone whose PD rose - five hundred rows
            # where ten were asked for, under a heading that did not say so.
            #
            # Masked rather than skipped: the rest of the clause is still
            # read, so "ECL deterioration fell this quarter" keeps its "fell".
            clause = _mask(clause, phrase)
            # The clause the phrase sits in is FINAL, including when its
            # verdict is "no movement". Falling through to a window search
            # here let a neighbouring clause lend its verb: in "…a rating
            # downgrade and covenant headroom below 15%", headroom borrowed
            # "downgrade" and the 15 with it, and a threshold test became
            # "headroom fell more than 15%" — which returned borrowers at
            # 16.17% headroom under a heading that promised below 15%.
            return find_movement(clause)

    text = str(question or "")
    at = _where(text, phrase)
    if at < 0:
        return None
    start = max(0, at - window)
    end = min(len(text), at + len(phrase) + window)
    return find_movement(text[start:end])


# ---------------------------------------------------------------- thresholds
#
# A level test, as distinct from a movement. "covenant headroom below 15%" says
# nothing about how headroom moved; it names a line and asks who is the wrong
# side of it. Reading it as a movement is not a near miss — it returns a
# different population, under a heading that describes the one you asked for.

#: Comparison words, and the operator each asserts about the measure.
_THRESHOLD_OPS: tuple[tuple[str, str], ...] = (
    (r"(?:strictly\s+)?(?:below|under|less than|lower than|beneath|"
     r"smaller than|worse than)", "lt"),
    (r"(?:strictly\s+)?(?:above|over|more than|greater than|higher than|"
     r"exceed(?:s|ing)?|better than)", "gt"),
    (r"(?:at most|no more than|not more than|up to|or less|or lower|or below)",
     "lte"),
    (r"(?:at least|no less than|not less than|or more|or higher|or above)",
     "gte"),
    (r"(?:equal to|exactly|equals?|is)", "eq"),
)

_THRESHOLD = re.compile(
    r"\b(?P<word>" + "|".join(p for p, _ in _THRESHOLD_OPS) + r")\s+"
    r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|percent|percentage points?|"
    r"pp|x|times|notch(?:es)?|days?|bps)?", re.I)

_OP_BY_WORD: dict[str, str] = {}


def _threshold_op(word: str) -> str:
    if not _OP_BY_WORD:
        for pattern, op in _THRESHOLD_OPS:
            _OP_BY_WORD[pattern] = op
    lowered = (word or "").strip().lower()
    for pattern, op in _THRESHOLD_OPS:
        if re.fullmatch(pattern, lowered, re.I):
            return op
    return ""


@dataclass(frozen=True)
class Threshold:
    """A line the measure has to be on one side of."""

    op: str
    value: float
    unit: str = ""
    phrase: str = ""


#: "90+ DPD", "30+ days past due". The plus sign IS the comparison, and a
#: reader that only knew the word "above" dropped the condition from every
#: question written the way a collections book writes it.
_PLUS_BOUND = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*\+\s*"
    r"(?P<unit>%|percent|days?|dpd|bps|notch(?:es)?)?", re.I)


def find_threshold(text: str) -> Threshold | None:
    """The level test in a fragment, if it states one."""
    match = _THRESHOLD.search(text or "")
    if match is None:
        plus = _PLUS_BOUND.search(text or "")
        if plus is not None:
            return Threshold(op="gte", value=float(plus.group("value")),
                             unit=(plus.group("unit") or "").lower().strip(),
                             phrase=plus.group(0).strip())
        return None
    op = _threshold_op(match.group("word"))
    if not op:
        return None
    return Threshold(op=op, value=float(match.group("value")),
                     unit=(match.group("unit") or "").lower().strip(),
                     phrase=match.group(0).strip())


def threshold_near(question: str, phrase: str) -> Threshold | None:
    """The level test attached to one concept's phrase.

    Clause-local only, and deliberately so. A threshold that had to be found
    across a clause boundary is a threshold on a different measure, and
    borrowing it is how a covenant question ended up filtering ECL.
    """
    if not phrase:
        return None
    for clause in clauses(question):
        if _mentions(clause, phrase):
            return find_threshold(clause)
    return None


def threshold_condition(match: Any, threshold: Threshold | None) -> Any:
    """The level Condition a threshold implies for this concept."""
    from backend.orchestration.dynamic import Condition

    if threshold is None:
        return None
    concept = match.concept
    if concept.is_categorical:
        return None
    if getattr(concept, "is_state", False):
        # A state has no scale, so a number standing near it in the sentence
        # belongs to something else. "Covenant breach or 90+ DPD" produced
        # `breached >= 90` — a comparison between a boolean and a number that
        # the database refuses at the point the answer is due, and that would
        # have been worse if it had silently succeeded.
        return None
    return Condition(
        field=match.field, kind="level", op=threshold.op,
        value=threshold.value, phrase=threshold.phrase,
        higher_is_worse=concept.higher_is_worse)


#: A state named as something to REPORT rather than to require. "Watchlist
#: borrowers by sector" wants a breakdown; "borrowers on the watchlist" wants
#: the watchlist. Only the first of those is not a condition, so the guard is
#: narrow: the state has to be introduced by a grouping or reporting word.
_REPORTED = (r"\b(?:by|per|across|grouped by|broken down by|for each|"
             r"for every)\s+{phrase}\b"
             r"|\b{phrase}\s+(?:breakdown|split|distribution|status|mix)\b")


def state_condition(match: Any, question: str = "") -> Any:
    """The Condition a governed STATE implies when a question names it.

    A state is not a measure and not a category: it is a thing a borrower is
    either in or not. Naming one asserts it, which is why it needs neither a
    direction nor a threshold to become a condition — and why a reader that
    demanded one dropped "on watchlist" and "in covenant breach" from every
    question that used them.

    The negative reading is NOT handled here. "Not on watchlist" is the same
    predicate with the sentence's Boolean structure around it, and putting the
    negation in the leaf would negate it twice on the paths that also read the
    structure.
    """
    from backend.orchestration.dynamic import Condition

    concept = getattr(match, "concept", None)
    if concept is None or not getattr(concept, "is_state", False):
        return None
    phrase = str(getattr(match, "phrase", "") or "")
    if question and phrase:
        spelling = re.escape(phrase).replace(r"\ ", r"\s+")
        if re.search(_REPORTED.format(phrase=spelling), question, re.I):
            return None
    return Condition(
        field=match.field, kind="level", op="eq", value=True,
        phrase=phrase, higher_is_worse=True)


__all__ = [
    "DIRECTIONS",
    "Direction",
    "Movement",
    "Threshold",
    "clauses",
    "condition_for",
    "find_movement",
    "find_threshold",
    "movement_near",
    "phrase_asserts_movement",
    "state_condition",
    "threshold_condition",
    "threshold_near",
]
