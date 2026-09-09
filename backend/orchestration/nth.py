"""«the second one» — a reference to one row of the answer already on screen.

The defect
----------
    "Which of those have rising 12-month PD?"   → 23 Shipping borrowers
    "Why does the second one worry you?"        → the whole 25-row ranking

The second sentence points at exactly one borrower. Nothing read it, so the
turn was planned from the words alone: "worry" resolved to the composite credit
concern signals, the ranking was recomputed over the whole population, and the
answer came back describing twenty-five names when the reader had asked about
one. Arithmetically correct, and about a different subject.

What this reads
---------------
An **ordinal reference into the previous result** — "the second one", "the
third", "#4", "the last one", "the worst of those". Not a ranking request: "the
second largest customer" names its own ordering and is a fresh question.

The rule it enforces
--------------------
**An ordinal binds to the stored order, and nothing is re-ranked.** "The second
one" is `ordered_result_ids[1]` of the result the previous turn published — the
row the reader is looking at — not the second row of a ranking recomputed now.
Recomputing could return a different second row for reasons the reader cannot
see, and the sentence promises the one on their screen.

And when it cannot bind — no previous population, or an index past the end —
the turn says so. It never widens back to the whole population, because an
answer about everything under a sentence that says "the second one" is the
failure this module exists to prevent, arriving by the polite route.

`worse` and `better` are read against the stored order
------------------------------------------------------
"The worst one" is the top of a ranking of concern and the bottom of a ranking
of interest cover. So it is resolved from the ORDER the previous plan recorded
— which column it sorted on, in which direction, and whether a higher value of
that column is the worse one — and where that is not recorded it does not
resolve at all rather than guessing which end the reader meant.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.orchestration.ordinal import DIRECTION

logger = logging.getLogger(__name__)

NTH_VERSION = "1.0.0"

#: The ordinal as it is written, and the zero-based position it names.
WORDS: dict[str, int] = {
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4,
    "sixth": 5, "6th": 5,
    "seventh": 6, "7th": 6,
    "eighth": 7, "8th": 7,
    "ninth": 8, "9th": 8,
    "tenth": 9, "10th": 9,
    "eleventh": 10, "twelfth": 11,
}

#: The head noun an ordinal may be attached to. A row of a credit answer is a
#: borrower, a name, a line — never a measure, which is what keeps "the second
#: highest exposure" out of here.
#: Singular on purpose: "the worst names" is a cohort, not a position, and
#: reading it as one would answer about a single borrower.
_ROW = (r"one|row|name|borrower|customer|client|obligor|company|"
        r"entity|entry|item|line|account|facility|sector|group|record")

#: A word that means the sentence is asking for its OWN ranking rather than
#: pointing at a stored one. "The second largest customer" is a new question.
_RANKS = (r"largest|biggest|smallest|highest|lowest|worst|best|top|bottom|"
          r"weakest|strongest|riskiest|safest|most|least|\d")

_ORDINAL_WORDS = "|".join(sorted(WORDS, key=len, reverse=True))

#: "the second one", "the second borrower", "the second?" — the ordinal must
#: be attached to a ROW of the previous answer or end the clause. Without that
#: anchor "the first quarter of 2025" and "the last year" read as references to
#: rows, and a question about a period became a question about a borrower.
_NAMED = re.compile(
    rf"\bthe\s+({_ORDINAL_WORDS})\b(?:\s+({_ROW})\b|(?=\s*[?.,!;]|\s*$))",
    re.IGNORECASE)

#: "the 2nd", "#3", "number 4", "row 5".
_NUMBERED = re.compile(
    r"(?:#\s*|\brow\s+)(\d{1,3})\b"
    r"|(?:\bthe\s+)?(?:\bnumber\s+|\bno\.\s*)(\d{1,3})\b"
    r"(?=\s*[?.,!;]|\s*$)", re.IGNORECASE)

#: The ends of the stored order, named without counting.
_LAST = re.compile(
    rf"\bthe\s+(?:last|final|bottom|lowest)\s+(?:{_ROW})\b"
    rf"|\bthe\s+(?:last|final)\s+of\s+(?:those|these|them)\b"
    rf"|\bthe\s+(?:last|final)(?=\s*[?.,!;]|\s*$)", re.IGNORECASE)
_TOP = re.compile(
    rf"\bthe\s+top\s+(?:{_ROW})\b|\bthe\s+(?:one|name)\s+at\s+the\s+top\b",
    re.IGNORECASE)

#: "the worst of those", "the best one" — resolved against the stored order.
_EXTREME = re.compile(
    rf"\bthe\s+(worst|best)\s+(?:{_ROW}|of\s+(?:those|these|them))\b",
    re.IGNORECASE)

#: A count that follows an ordinal makes it a slice, not a position: "the first
#: five" is a population reference and `referents` already reads it as one.
_COUNT_AFTER = re.compile(
    r"^\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|"
    r"fifty|hundred)\b", re.IGNORECASE)
_RANK_AFTER = re.compile(rf"^\s*(?:{_RANKS})\b", re.IGNORECASE)


@dataclass(frozen=True)
class Nth:
    """One position in the previous result, as the sentence named it."""

    #: Zero-based position from the start, or -1 for "the last one".
    index: int = 0
    #: The words that asked for it, for the Trace and for a clarification.
    phrase: str = ""
    #: "worst" / "best" when the end has to be chosen from the stored order.
    extreme: str = ""

    @property
    def from_the_end(self) -> bool:
        return self.index < 0


@dataclass(frozen=True)
class Bound:
    """The one identity an ordinal reference resolved to."""

    entity_key: str = ""
    entity_id: str = ""
    label: str = ""
    position: int = 0            # 1-based, as a person counts
    of: int = 0                  # how many rows the stored order held
    phrase: str = ""
    because: str = ""

    @property
    def resolved(self) -> bool:
        return bool(self.entity_key and self.entity_id)


def read(question: str) -> Nth | None:
    """The ordinal reference this sentence makes, or None for none.

    State is deliberately not consulted. Whether a reference CAN be resolved is
    a separate question from whether one was MADE, and answering the first in
    place of the second is how "the second one" became a portfolio ranking.
    """
    text = " " + " ".join(str(question or "").split()) + " "

    match = _EXTREME.search(text)
    if match:
        return Nth(index=0, phrase=match.group(0).strip(),
                   extreme=match.group(1).lower())

    match = _LAST.search(text)
    if match:
        return Nth(index=-1, phrase=match.group(0).strip())

    match = _TOP.search(text)
    if match:
        return Nth(index=0, phrase=match.group(0).strip())

    match = _NAMED.search(text)
    if match:
        after = text[match.end():]
        # "the first five", "the second largest" — a slice or a fresh ranking.
        if not match.group(2) and (_COUNT_AFTER.match(after)
                                   or _RANK_AFTER.match(after)):
            return None
        return Nth(index=WORDS[match.group(1).lower()],
                   phrase=match.group(0).strip())

    match = _NUMBERED.search(text)
    if match:
        position = int(match.group(1) or match.group(2))
        if position >= 1:
            return Nth(index=position - 1, phrase=match.group(0).strip())
    return None


def _ordering(ir: dict[str, Any]) -> tuple[str, str]:
    """The column and direction the previous plan sorted on, if it sorted."""
    for operation in reversed(list((ir or {}).get("operations") or [])):
        if str(operation.get("op") or "").upper() != "SORT":
            continue
        by = (operation.get("params") or {}).get("by") or []
        if by:
            first = by[0]
            return (str(first.get("column") or ""),
                    str(first.get("direction") or "asc").lower())
    return ("", "")


def _end_for(extreme: str, ir: dict[str, Any]) -> int | None:
    """Which end of the STORED order "the worst one" names, or None.

    Never guessed. A ranking whose ordering was not recorded, or whose measure
    has no governed direction, leaves this unresolved — and an unresolved
    reference is asked about rather than answered from the wrong end.
    """
    column, direction = _ordering(ir)
    if not column or column not in DIRECTION:
        return None
    higher_is_worse = DIRECTION[column]
    # The worst row sits at the top when the sort puts the worst value first.
    worst_first = (direction == "desc") == higher_is_worse
    if extreme == "worst":
        return 0 if worst_first else -1
    return -1 if worst_first else 0


def resolve(reference: Nth, state: Any) -> Bound:
    """Bind an ordinal reference to exactly one identity of the stored result.

    Nothing is recomputed and nothing is re-ranked: the position is read out of
    the order the previous turn published. An index past the end of that order
    is reported as unresolved, because answering the last row instead of the
    seventh would be a different borrower under the same sentence.
    """
    result = getattr(state, "result", None)
    ids = list(getattr(result, "entity_ids", []) or []) if result else []
    key = str(getattr(result, "entity_key", "") or "") if result else ""
    if not ids or not key:
        return Bound(phrase=reference.phrase,
                     because="no previous answer in this investigation "
                             "published an ordered set of rows")

    index = reference.index
    if reference.extreme:
        end = _end_for(reference.extreme, dict(getattr(state, "ir", {}) or {}))
        if end is None:
            return Bound(phrase=reference.phrase,
                         because="the previous answer's ordering does not say "
                                 f"which end {reference.phrase!r} names")
        index = end

    if index < 0:
        index = len(ids) + index
    if not 0 <= index < len(ids):
        return Bound(phrase=reference.phrase,
                     because=f"the previous answer returned {len(ids)} rows, "
                             f"which does not reach {reference.phrase!r}")

    entity_id = ids[index]
    labels = dict(getattr(result, "entity_labels", {}) or {})
    return Bound(
        entity_key=key, entity_id=entity_id,
        label=str(labels.get(entity_id) or entity_id),
        position=index + 1, of=len(ids), phrase=reference.phrase,
        because=(f"{reference.phrase!r} is row {index + 1} of the "
                 f"{len(ids)} the previous answer returned"))


def clarification(bound: Bound) -> str:
    """What to ask when an ordinal pointed at a row that is not there.

    Written as a colleague would ask it. The reader knows what they meant; what
    they need is to be told which part CreditProbe could not follow.
    """
    return (f"Which row do you mean by {bound.phrase or 'that'}? "
            f"{bound.because[0].upper() + bound.because[1:]}. Ask the question "
            "that produces the list, or name the borrower, and I will take it "
            "from there.")


__all__ = ["Bound", "NTH_VERSION", "Nth", "WORDS", "clarification", "read",
           "resolve"]
