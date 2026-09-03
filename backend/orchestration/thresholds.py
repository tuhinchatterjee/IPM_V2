"""A number after a measure is a THRESHOLD. A number after a movement is not.

The defect
----------
    "Which customers have covenant headroom below 15%?"
        → the 10 largest customers BY covenant headroom

    "Which customers' covenant headroom fell below 15%?"
        → 2,682 customers whose headroom fell by MORE THAN 15 percentage points

Both wrong, and wrong in opposite directions.

The first question states a level test — headroom, as it stands now, under 15.
Nothing in the product read it. `read_conditions` only ever looked for movement
clauses, so the restriction was silently dropped and something downstream fell
back to ranking the measure. The answer that came back was a true sentence
about a different question, which is the worst shape a wrong answer can take:
1,209 customers qualify, and the reader was shown ten.

The second question states a CROSSING — it was at or above 15, it is now below.
The reader saw "fell", then saw "15", and had only one idea of what a number
after a movement word could mean: how big the movement was. So a threshold
became a magnitude, and the answer included borrowers whose headroom had gone
UP (0.02 → 10.85 is a rise of 10.83, which is "more than 15" in neither
direction) and borrowers who closed at 15.05, above the very threshold the
question asked about.

The rule
--------
Read the PREPOSITION, not just the number.

    below / under / less than / beneath      a bound, not a distance
    above / over / greater than / exceeding  a bound, not a distance
    by / at least / more than <n>%           a distance

and then read what the bound attaches to:

    "headroom below 15%"          LEVEL     one date. headroom < 15
    "headroom fell below 15%"     CROSSING  two dates. was >= 15, now < 15
    "headroom fell by 15%"        MOVEMENT  two dates. change <= -15

A crossing is genuinely two-period — it is a transition — but the value that
QUALIFIES a row is the closing one, and that is the value the answer must show.
Citing the opening figure as though it were the qualifying figure is how a
reader ends up with 15.05 in an answer about being under 15.

Which measures this covers
--------------------------
Every level-threshold measure, from one table: covenant headroom, DSCR,
interest coverage, utilisation, days past due, LGD, collateral coverage, PD,
ECL coverage, RAROC. The vocabulary is a property of the sentence rather than
of the measure, so a new measure needs an entry in the governed lexicon and
nothing here.
"""

from __future__ import annotations

import re
from typing import Any

from backend.orchestration.dynamic import Condition, _measure_for

THRESHOLDS_VERSION = "1.0.0"

#: What each bound word compares. Ordered longest-first where one phrase
#: contains another, because "at or below" must not be read as "below".
#:
#: "no more than" and "at most" are ceilings, not distances, which is the one
#: place this list overlaps `dynamic._MAGNITUDE` — there they qualify the SIZE
#: of a change, here they bound a LEVEL, and the difference is whether a
#: movement word came first.
_BOUNDS: tuple[tuple[str, str], ...] = (
    (r"at or below|no more than|at most|no higher than|up to", "lte"),
    (r"at or above|at least|no less than|no lower than", "gte"),
    (r"below|under|beneath|less than|lower than|fewer than", "lt"),
    (r"above|over|greater than|more than|exceeding|higher than|in excess of",
     "gt"),
)

#: A bound and the number it bounds. The unit is read and discarded: "1.2x",
#: "15%" and "30 days" all state the same governed field's own unit, and
#: re-deriving it from the word would be a second opinion about something the
#: catalogue already knows.
_BOUND_VALUE = re.compile(
    r"(?P<bound>" + "|".join(p for p, _ in _BOUNDS) + r")\s*"
    r"(?P<number>-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|per ?cent|percent|x|times|days?|bps|basis points)?",
    re.IGNORECASE,
)

#: "30+ DPD", "90+ days past due" — a bound written as a suffix.
_PLUS_SUFFIX = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*\+", re.IGNORECASE)

#: Movement words, narrowed to the ones that can precede a crossing. A measure
#: that "fell below" crossed downward; one that "rose above" crossed upward.
#: `became` and `went` are included because "became 30+ DPD" and "went above
#: 90%" are the two most common ways a credit officer says it.
_DOWNWARD = r"fell|fall\w*|declin\w*|drop\w*|slip\w*|sank|sunk|went|moved|dipped"
_UPWARD = r"ros\w*|rose|increas\w*|climb\w*|grew|jump\w*|went|moved|became|hit|reach\w*"

#: The bounds that state a POSITION rather than a distance.
#:
#: This is deliberately narrower than `_BOUNDS`, and the narrowing is the whole
#: safety of the crossing reading. After a movement word English uses the
#: comparatives for SIZE — "ECL rose more than 20%" is a twenty per cent rise,
#: not a crossing of the twenty line — while the positional prepositions keep
#: their positional sense: "fell below 15%" is a line that was crossed.
#:
#: So only the unambiguous positional words are admitted here. Anything else
#: after a movement word is left to the magnitude reader, which is the reading
#: it already had. A crossing is never invented out of a phrase that might have
#: meant a distance.
_POSITIONAL: tuple[tuple[str, str], ...] = (
    (r"to below|down below|below|beneath", "lt"),
    (r"to above|up above|above|past|through|beyond", "gt"),
)

#: A crossing: a movement word, then a POSITIONAL bound, then a number.
_CROSSING = re.compile(
    r"(?P<direction>" + _DOWNWARD + r"|" + _UPWARD + r")\s+"
    r"(?P<bound>" + "|".join(p for p, _ in _POSITIONAL) + r")\s*"
    r"(?P<number>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

#: "became 30+ DPD", "moved into 90+ days past due".
_CROSSING_PLUS = re.compile(
    r"(?P<direction>" + _UPWARD + r"|" + _DOWNWARD + r")\s+"
    r"(?:into\s+|to\s+)?(?P<number>\d+(?:\.\d+)?)\s*\+",
    re.IGNORECASE,
)


def _bound_op(word: str) -> str:
    """Which comparison a bound word states, positional or comparative."""
    lowered = word.lower().strip()
    for pattern, op in _POSITIONAL + _BOUNDS:
        if re.fullmatch(pattern, lowered, re.IGNORECASE):
            return op
    return "lt"


def _field_for(text: str, resolver: Any = None,
               whole: str = "") -> tuple[str, bool] | None:
    """The governed field a phrase names, through the caller's resolver.

    The resolver is what knows the live catalogue: the flat lexicon says
    "headroom" is `covenant_headroom_pct`, and the dataset actually in front of
    the question may spell it `covenant_tests_headroom_pct`. Falling back to
    the lexicon keeps this usable in a unit test with no catalogue loaded.

    Called `(phrase, whole_question)`, which is the convention `read_conditions`
    already uses: a qualifier anywhere in the sentence ("regulatory EAD") has to
    reach the resolver even when the phrase in hand is just "EAD".
    """
    if resolver is not None:
        try:
            found = resolver(text, whole or text)
        except TypeError:
            # A one-argument resolver, which some callers pass. Supported
            # rather than required: the alternative is every caller having to
            # know which arity this module expects.
            try:
                found = resolver(text)
            except Exception:  # pragma: no cover - a resolver is caller code
                found = None
        except Exception:  # pragma: no cover - a resolver is caller code
            found = None
        if found:
            return found
    return _measure_for(text)


def _measure_phrase(text: str, upto: int) -> str:
    """The words before a bound, which is where the measure is named.

    Cut at the bound rather than searched across the whole sentence: "Which
    borrowers have DSCR below 1.2x and utilisation above 90%" names two
    measures, and reading the sentence whole would attach both bounds to
    whichever measure the lexicon happened to match first.
    """
    return text[:upto]


def read_levels(text: str, *, resolver: Any = None, whole: str = ""
                ) -> tuple[list[Condition], list[str]]:
    """Level tests the sentence states, and the phrases it could not resolve.

    A level test restricts the population at ONE reporting date. It is the
    plain reading of "customers with headroom below 15%", and it is what makes
    that question a population rather than a ranking.
    """
    conditions: list[Condition] = []
    unread: list[str] = []
    seen: set[tuple[str, str]] = set()

    for match in _BOUND_VALUE.finditer(text):
        before = _measure_phrase(text, match.start())
        # A POSITIONAL bound immediately after a movement word is a CROSSING
        # and belongs to `read_crossings`. Reading it here as well would put a
        # one-date test on a two-date question.
        #
        # A comparative one is not: "ECL rose more than 20%" states a distance,
        # which neither reader here owns — it is the magnitude reader's, and
        # declining it silently is what leaves it to them.
        if re.search(r"(?:" + _DOWNWARD + r"|" + _UPWARD + r")\s*$",
                     before.rstrip(), re.IGNORECASE):
            continue
        found = _field_for(before, resolver, whole or text)
        if not found:
            unread.append(match.group(0).strip())
            continue
        field, higher_is_worse = found
        op = _bound_op(match.group("bound"))
        value = float(match.group("number"))
        key = (field, "level")
        if key in seen:
            continue
        seen.add(key)
        conditions.append(Condition(
            field=field, kind="level", op=op, value=value,
            phrase=match.group(0).strip(), higher_is_worse=higher_is_worse))

    # "more than 30 days past due" states the bound before the measure, which
    # the forward pattern above reads as a bound with no measure in front of
    # it. Try again with the tail.
    if not conditions:
        for match in _BOUND_VALUE.finditer(text):
            # From the bound onwards, NOT from after the number: "more than 30
            # days past due" carries its measure across the unit word, and
            # cutting after "30 days" leaves "past due", which the governed
            # lexicon spells "days past due" and so does not match.
            after = text[match.start():]
            found = _field_for(after, resolver, whole or text)
            if not found:
                continue
            field, higher_is_worse = found
            key = (field, "level")
            if key in seen:
                continue
            seen.add(key)
            conditions.append(Condition(
                field=field, kind="level", op=_bound_op(match.group("bound")),
                value=float(match.group("number")),
                phrase=match.group(0).strip(),
                higher_is_worse=higher_is_worse))
            unread = [u for u in unread if u != match.group(0).strip()]

    return conditions, unread


def read_crossings(text: str, *, resolver: Any = None, whole: str = ""
                   ) -> tuple[list[Condition], list[str]]:
    """Threshold crossings the sentence states.

    Each crossing yields TWO conditions, because a crossing is a statement
    about both dates: where the measure was, and where it now is. The closing
    one is what qualifies the row and what the answer must display; the opening
    one is what makes it a crossing rather than a level test that happens to be
    asked in the past tense.
    """
    conditions: list[Condition] = []
    unread: list[str] = []
    seen: set[str] = set()

    for pattern, has_bound in ((_CROSSING, True), (_CROSSING_PLUS, False)):
        for match in pattern.finditer(text):
            before = _measure_phrase(text, match.start())
            after = text[match.end():]
            found = (_field_for(before, resolver, whole or text)
                     or _field_for(after, resolver, whole or text))
            if not found:
                unread.append(match.group(0).strip())
                continue
            field, higher_is_worse = found
            if field in seen:
                continue
            value = float(match.group("number"))
            if has_bound:
                closing_op = _bound_op(match.group("bound"))
            else:
                # "became 30+ DPD" is a crossing UP to at-or-above the number.
                closing_op = "gte"
            # Where it must have been for this to be a crossing: on the other
            # side of the same line. Strictly the other side, so a row that sat
            # exactly on the threshold and has not moved is not reported as
            # having crossed it.
            opening_op = {"lt": "gte", "lte": "gt",
                          "gt": "lte", "gte": "lt"}[closing_op]
            seen.add(field)
            conditions.append(Condition(
                field=field, kind="level_open", op=opening_op, value=value,
                phrase=match.group(0).strip(),
                higher_is_worse=higher_is_worse))
            conditions.append(Condition(
                field=field, kind="level_close", op=closing_op, value=value,
                phrase=match.group(0).strip(),
                higher_is_worse=higher_is_worse))

    return conditions, unread


def read(text: str, *, resolver: Any = None, whole: str = ""
         ) -> tuple[list[Condition], list[str]]:
    """Every threshold the sentence states, level and crossing together.

    Crossings first: a crossing consumes its bound, and the level reader
    declines any bound that a movement word introduced, so the two cannot both
    claim the same phrase.
    """
    crossings, unread = read_crossings(text, resolver=resolver,
                                       whole=whole or text)
    levels, level_unread = read_levels(text, resolver=resolver,
                                       whole=whole or text)
    crossed = {c.field for c in crossings}
    levels = [c for c in levels if c.field not in crossed]
    return crossings + levels, unread + level_unread


def crossing_for(field: str, higher_is_worse: bool, phrase: str
                 ) -> list[Condition]:
    """The two halves of a crossing, if this movement phrase states one.

    Called with a movement that has already been read — the direction word and
    the number are known — and asked only whether the word BETWEEN them was
    positional. "fell below 15%" was; "fell more than 15%" was not, and stays a
    magnitude.

    This is the point the defect lived at. `semantics.condition_for` had the
    bound in its hand, treated it as a qualifier on the SIZE of the movement,
    and flipped it against the direction — so a question about crossing under
    fifteen became a question about falling by more than fifteen, and answered
    with borrowers whose headroom had risen.
    """
    if not phrase:
        return []
    match = _CROSSING.search(phrase) or _CROSSING_PLUS.search(phrase)
    if match is None:
        return []
    value = float(match.group("number"))
    try:
        closing_op = _bound_op(match.group("bound"))
    except IndexError:
        closing_op = "gte"          # the "30+" form crosses UP to at-or-above
    opening_op = {"lt": "gte", "lte": "gt", "gt": "lte", "gte": "lt"}[closing_op]
    said = match.group(0).strip()
    return [
        Condition(field=field, kind="level_open", op=opening_op, value=value,
                  phrase=said, higher_is_worse=higher_is_worse),
        Condition(field=field, kind="level_close", op=closing_op, value=value,
                  phrase=said, higher_is_worse=higher_is_worse),
    ]
