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

from backend.orchestration import temporal
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


#: "down" in an idiom that asks for a BREAKDOWN rather than a fall.
#:
#: The failure this prevents
#: -------------------------
#:     "Break ECL down by product"
#:
#: was answered "9,517 facilities where ecl final sar fell, between 2025-08 and
#: 2026-08. The 500 shown are ordered worst first." The literal DOWN direction
#: matches a bare "down", the concept "ECL" was masked out of the clause before
#: the scan, and what was left — "Break     down by product" — reads as an
#: assertion that something fell. The most ordinary way in English to ask for a
#: breakdown returned a deterioration cohort instead, computed correctly, under
#: a heading describing a question nobody asked.
#:
#: Masked rather than removed, so offsets a caller derived from the clause
#: still point where they did, and so a real movement elsewhere in the same
#: sentence survives: "break ECL down by product and say which fell" keeps its
#: "fell".
_BREAKDOWN_IDIOM = re.compile(
    r"\bbreak(?:s|ing)?\b[^.;?!]{0,40}?\b(?P<down>down)\b"
    r"|\bbroken\s+(?P<down2>down)\b"
    r"|\bdrill(?:s|ed|ing)?[\s\-]+(?P<down3>down)\b"
    r"|\btop[\s\-]?(?P<down4>down)\b"
    r"|\bdrill(?P<down5>down)\b",
    re.IGNORECASE,
)


def without_breakdown(text: str) -> str:
    """The text with a breakdown idiom's "down" blanked out, same length."""
    out = str(text or "")
    if "down" not in out.lower():
        return out
    for found in _BREAKDOWN_IDIOM.finditer(out):
        for group in ("down", "down2", "down3", "down4", "down5"):
            if found.group(group) is None:
                continue
            start, end = found.span(group)
            out = out[:start] + (" " * (end - start)) + out[end:]
    return out


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
    scanned = without_breakdown(text).lower()
    found: tuple[int, int] | None = None
    for direction in DIRECTIONS:
        at = re.search(direction.pattern, scanned)
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
    """The movement word in a fragment, and any number attached to it.

    Time is removed before the number is read. "ECL rose in Q1 2026" compiled
    to `total_ecl_change > 2026` and returned an empty population under a
    heading saying "ECL rose more than 2026" — a valid plan, a running query,
    passing invariants, and a finding a credit officer might believe. A period
    is a type, not a quantity, and the two must not share a parser.
    """
    lowered = without_breakdown(temporal.without_time(text)).lower()
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
    # The tail is taken from the time-free text for the same reason: a period
    # standing after the direction word is not the size of the movement.
    tail = lowered[at.end():] if at else ""
    magnitude = _MAGNITUDE.search(tail)
    if magnitude and _is_a_period(tail, magnitude):
        # "an increase in ECL over the latest 6 months" says WHEN, not HOW MUCH.
        # Reading the 6 as a threshold turned a question about a year into
        # "ECL rose by more than six", which is a different and much smaller
        # cohort — and nothing on screen said so.
        magnitude = None
    if magnitude and _is_a_label(tail, magnitude):
        # "What drove the increase in STAGE 2 exposure?" says WHICH, not HOW
        # MUCH. The 2 is the name of a stage, and reading it as a threshold
        # produced "IFRS 9 stage is 2 and IFRS 9 stage rose and EAD rose more
        # than 2" — three conditions from a sentence that states one, and two
        # facilities where the question was about a portfolio.
        #
        # Same shape as the period guard above and for the same reason: a
        # category label is a TYPE, not a quantity, and the two must not share
        # a parser.
        magnitude = None
    if magnitude and _is_a_bucket(tail, magnitude):
        # "90+ delinquency", "30+ DPD", "90 plus arrears" — a DELINQUENCY
        # BUCKET, and every retail book writes it that way. Read as the size
        # of a movement it produced "which subsegments' days past due rose by
        # more than 90", ranked by the summed day-change of the facilities
        # that qualified: a real number, in days, answering nothing anybody
        # asked. The bound belongs to the LEVEL, and the caller's threshold
        # reader picks it up there.
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


#: Nouns whose following number NAMES a category rather than sizing a change.
#: "stage 2", "grade 7", "bucket 3", "band 4" are all the identity of a class.
#: Notches are deliberately absent: "deteriorated two notches" IS a magnitude.
_LABEL_NOUN = re.compile(
    r"(?:stages?|grades?|buckets?|bands?|tiers?|categor(?:y|ies)|classes|"
    r"class|levels?|rating grades?)\s*$", re.I)


def _is_a_label(tail: str, magnitude: Any) -> bool:
    """Whether the number after a movement word names a category."""
    return bool(_LABEL_NOUN.search(tail[:magnitude.start()]))


#: "90+", "30 plus" — a number written with a trailing plus is the NAME of a
#: delinquency band, not a quantity a measure moved by.
_A_BUCKET = re.compile(r"\s*(?:\+|plus\b)", re.IGNORECASE)


def _is_a_bucket(tail: str, magnitude: Any) -> bool:
    """Whether the number after a movement word names a delinquency band."""
    return bool(_A_BUCKET.match(tail[magnitude.end():]))


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
    # A comma INSIDE a number is a thousands separator, not a clause boundary.
    # "a credit limit of 100,000 or more" was cut into "a credit limit of 100"
    # and "000 or more": the bound was left in a clause with no measure, the
    # condition was dropped, and the answer was a population nobody asked for.
    r"\s*(?:(?<!\d),(?!\d{3}\b)\s*(?:and|or|but)?\s*"
    r"|,(?=\s)\s*(?:and|or|but)?\s*"
    r"|\band\b|\bor\b|\bbut\b|\bwhile\b|"
    r"\balong ?with\b|\btogether with\b|\bas well as\b|\bplus\b|;)\s*",
    re.IGNORECASE)


def clauses(question: str) -> list[str]:
    """The fragments of a question, each hopefully naming one measure.

    Deliberately crude. A fragment that names two measures is handled by the
    caller matching each concept's own phrase position, and a fragment that
    names none is skipped.
    """
    # A suffix bound is rewritten BEFORE the split, because the split reads
    # "or" as a conjunction: "90 or more days past due" became the two clauses
    # "how many customers are 90" and "more days past due", neither of which
    # states a bound. The condition was dropped and the whole book returned.
    text = _forward_bounds(" ".join(str(question or "").split()))
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
    # A thousands separator is part of the number. "a credit limit of 100,000
    # or more" stated no bound the reader could see: the comma ended the
    # match, the condition was dropped, and the answer was every facility on
    # the book — 19,745 where 28 qualify.
    r"(?P<value>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?"
    r"|zero|nil|nought)\s*"
    r"(?P<unit>%|percent|percentage points?|"
    r"pp|x|times|notch(?:es)?|days?|bps)?", re.I)

#: Zero, written out. "disposable income BELOW ZERO" stated a bound the reader
#: could not see, because the value had to be digits — so the condition was
#: dropped and the question answered over the whole book.
_WRITTEN = {"zero": 0.0, "nil": 0.0, "nought": 0.0}


def _bound_value(said: str) -> float:
    text = (said or "").strip().lower().replace(",", "")
    return _WRITTEN[text] if text in _WRITTEN else float(text)


#: A bound stated as a SIGN rather than as a number: "negative disposable
#: income", "customers whose affordability buffer is negative".
#:
#: "How many customers have negative disposable income?" carried no bound word
#: and no digit, so nothing read it: the condition was dropped silently and the
#: answer was a ranking of the HIGHEST POSITIVE values, under a question asking
#: for the negative ones. Both directions are read, because "positive" is the
#: same claim the other way and reading one of them alone is worse than
#: reading neither.
_SIGN_BOUND = re.compile(
    r"\b(?P<sign>negative|positive)\b|"
    r"\b(?:is|are|was|were)\s+(?P<sign2>negative|positive)\b", re.I)

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



#: A bound written AFTER its number, which is how people say it out loud.
#:
#: `_THRESHOLD_OPS` already lists "or more" and "or less"; `_THRESHOLD`
#: requires the bound word BEFORE the value, so neither could ever match. "How
#: many customers are 90 OR MORE days past due?" therefore stated no bound at
#: all, the condition was dropped, and the answer was **14,251 customers** —
#: the whole book — where the true figure is 96. Worse than a silent drop: a
#: caveat said a condition had not been applied, and the figure was given
#: anyway.
_SUFFIX_TO_PREFIX: tuple[tuple[str, str], ...] = (
    (r"or\s+(?:more|greater|higher|above|over|worse|older|longer|later)",
     "at least"),
    (r"or\s+(?:less|fewer|lower|below|under|better|younger|shorter|earlier)",
     "at most"),
)

_SUFFIX_BOUND = re.compile(
    r"(?P<value>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent|per cent|percentage points?|pp|x|times|"
    r"notch(?:es)?|days?|bps)?\s*"
    r"(?P<word>" + "|".join(p for p, _ in _SUFFIX_TO_PREFIX) + r")\b",
    re.IGNORECASE)


def _forward_bounds(said: str) -> str:
    """"90 or more days" rewritten as "at least 90 days".

    A rewrite rather than a second pattern, so one bound vocabulary keeps
    deciding what a bound means and there is no second opinion to drift.
    """
    def swap(match: re.Match[str]) -> str:
        word = match.group("word").lower()
        for pattern, phrase in _SUFFIX_TO_PREFIX:
            if re.fullmatch(pattern, word, re.IGNORECASE):
                unit = match.group("unit") or ""
                return (f"{phrase} {match.group('value')}"
                        + (f" {unit}" if unit else ""))
        return match.group(0)

    return _SUFFIX_BOUND.sub(swap, str(said or ""))

def find_threshold(text: str) -> Threshold | None:
    """The level test in a fragment, if it states one.

    Time removed first, as in `find_movement`: "covenant headroom below 15% in
    Q1 2026" states one threshold, not two, and "ECL above 2026" states none.
    """
    said = _forward_bounds(temporal.without_time(text or ""))
    match = _THRESHOLD.search(said)
    if match is None:
        plus = _PLUS_BOUND.search(said)
        if plus is not None:
            return Threshold(op="gte", value=float(plus.group("value")),
                             unit=(plus.group("unit") or "").lower().strip(),
                             phrase=plus.group(0).strip())
        # A sign is a bound at zero. Read only where the clause states no
        # numeric bound at all, so a sentence that says both keeps the one it
        # wrote down.
        sign = _SIGN_BOUND.search(said)
        if sign is not None:
            which = (sign.group("sign") or sign.group("sign2") or "").lower()
            return Threshold(op="lt" if which == "negative" else "gt",
                             value=0.0, unit="",
                             phrase=sign.group(0).strip())
        return None
    op = _threshold_op(match.group("word"))
    if not op:
        return None
    return Threshold(op=op, value=_bound_value(match.group("value")),
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


#: Units the catalogue holds as a DECIMAL fraction: 0.598, not 59.8.
_DECIMAL_UNITS = frozenset({"ratio", "probability", "x"})

#: How a reader writes a percentage.
_PERCENT_SAID = frozenset({"%", "percent", "per cent"})


def _to_field_scale(match: Any, threshold: Threshold) -> tuple[float, str]:
    """The bound in the units the COLUMN is held in, and what was converted.

    The unit was read and discarded, on the reasoning that "1.2x", "15%" and
    "30 days" all state the governed field's own unit. They do not. A retail
    book holds `debt_burden_ratio` as a DECIMAL — 0.598, not 59.8 — so

        "customers with a debt burden ratio above 50 percent"

    compiled to `debt_burden_ratio > 50`, which no row in the book satisfies.
    The answer was empty, and nothing said the bound had been read on a
    different scale from the column.

    Converted rather than refused, because the reader's phrasing is the
    conventional one and the catalogue knows both scales. Stated on the
    answer, because a silently rescaled bound is a silently different
    question.
    """
    unit = str(getattr(threshold, "unit", "") or "").strip().lower()
    field_unit = str(getattr(match.concept, "unit", "") or "").strip().lower()
    if unit in _PERCENT_SAID and field_unit in _DECIMAL_UNITS:
        return threshold.value / 100.0, (
            f"{threshold.phrase} was read as "
            f"{threshold.value / 100.0:g} because "
            f"{match.label} is held as a decimal fraction in this book")
    return threshold.value, ""


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
    value, rescaled = _to_field_scale(match, threshold)
    return Condition(
        field=match.field, kind="level", op=threshold.op,
        value=value,
        phrase=threshold.phrase + (f" ({rescaled})" if rescaled else ""),
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
    "without_breakdown",
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
