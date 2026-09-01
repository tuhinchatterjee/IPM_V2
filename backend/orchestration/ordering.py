"""
Which way round a ranking goes. One reading, used by everyone who needs it.

There were two readings of this before, and they disagreed in both directions.

The PLANNER scanned for low-end words before high-end ones, so the "lowest" in
"highest to lowest" won: the plan sorted ascending, `LIMIT 20` took the twenty
LOWEST probabilities of default, and the table was headed "highest".

The INVARIANT did not read the question at all - it asserted "largest first"
for every ranking. So the planner's correct ascending order for "the ten
borrowers with the LOWEST covenant headroom" was judged as a broken descending
one and the answer was withheld.

Between them, a question that named the high end was answered from the low end,
and a question that named the low end was refused. Both are the same defect:
two pieces of code reading one sentence separately. This module is the reading,
and it is the only one.

Note what is NOT here: nothing about tie-breaking, stability or SQL. Those live
in the compiler, which gives every result a total order. This module answers
one question - which end did the reader ask for - and answers it once.
"""

from __future__ import annotations

import re

#: Phrases that state the ORDER OF THE TABLE rather than which end of the
#: population to select. Each contains both superlatives by construction, so
#: they must be read whole, and read before the individual words.
ORDER_PHRASES: tuple[tuple[str, bool], ...] = (
    ("highest to lowest", True), ("largest to smallest", True),
    ("biggest to smallest", True), ("high to low", True),
    ("most to least", True), ("worst to best", True),
    ("greatest to least", True), ("greatest to smallest", True),
    ("in descending order", True), ("descending order", True),
    ("descending", True), ("desc order", True),
    ("lowest to highest", False), ("smallest to largest", False),
    ("smallest to biggest", False), ("low to high", False),
    ("least to most", False), ("best to worst", False),
    ("least to greatest", False),
    ("in ascending order", False), ("ascending order", False),
    ("ascending", False), ("asc order", False),
)

HIGH_END = re.compile(
    r"\b(?:largest|biggest|highest|top|most|worst|greatest|maximum|max|"
    r"riskiest|weakest\s+covered)\b", re.IGNORECASE)

LOW_END = re.compile(
    r"\b(?:smallest|lowest|bottom|least|weakest|minimum|min|thinnest|"
    r"tightest|narrowest)\b", re.IGNORECASE)

#: Words with which a question actually PROMISES an order at all. A plain
#: "show me X and Y" promises a list, and a list is not out of order.
RANKING_WORDS = re.compile(
    r"\b(top|bottom|rank(?:ed|ing)?|largest|biggest|smallest|highest|lowest|"
    r"worst|best|most|least|leading|tightest|narrowest|thinnest|"
    r"order(?:ed)?\s+by|sort(?:ed)?\s+by|greatest|first\s+\d+|last\s+\d+)\b",
    re.IGNORECASE)


def descending(text: str, *, default: bool = True) -> bool:
    """Whether the reader asked for the largest first.

    Three readings, in this order, and the order is the fix.

    1. An explicit ORDER phrase. "highest to lowest" says how to sort the
       table; it does not ask for the bottom of the book.
    2. When only one end is named, that end.
    3. When both are named and no phrase resolves them, the FIRST in the
       sentence - it is the one attached to the population being selected.
       "the 20 borrowers with the highest PD, shown lowest first" is a real
       if unusual request, and the selection is what a ranking is about.
    """
    lowered = " ".join(str(text or "").lower().split())
    for phrase, wants_descending in ORDER_PHRASES:
        if phrase in lowered:
            return wants_descending
    high, low = HIGH_END.search(lowered), LOW_END.search(lowered)
    if high and low:
        return high.start() < low.start()
    if low:
        return False
    if high:
        return True
    return default


def promises_an_order(text: str) -> bool:
    """Whether the reader asked for an order at all."""
    return bool(RANKING_WORDS.search(str(text or "")))


def claim(column: str, *, wants_descending: bool) -> str:
    """The sentence the invariant will hold the answer to."""
    readable = str(column or "").replace("_", " ").strip()
    return (f"ranked by {readable}, "
            + ("largest first" if wants_descending else "smallest first"))


__all__ = ["HIGH_END", "LOW_END", "ORDER_PHRASES", "RANKING_WORDS", "claim",
           "descending", "promises_an_order"]
