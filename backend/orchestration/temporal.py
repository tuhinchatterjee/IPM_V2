"""
When a question says a time, that is a TIME — never a number.

The failure this exists to prevent
----------------------------------
    "Which customers were downgraded and had expected credit loss rise
     in Q1 2026?"

compiled to

    total_ecl_change > 2026.0

and came back as "None of customers in the book match internal rating was
downgraded and ECL rose more than 2026". The magnitude reader looked at the
words after the direction word "rise", found the digits `2026`, and read them
as the size of the movement. Nobody has ever asked for an ECL that rose by more
than two thousand and twenty-six million; the question named a quarter.

The result is worse than a crash. The plan is valid, the query runs, the
invariants pass — the population is simply empty, and an empty population reads
as a finding. "No borrower deteriorated that way this quarter" is a sentence a
credit officer might well believe.

The rule
--------
A temporal expression is masked out of the text BEFORE any numeric threshold is
read from it. Masked rather than deleted: the mask is the same length as what
it replaced, so every offset a caller already computed still points where it
did.

This is a type distinction, not a heuristic about plausible magnitudes. A
threshold of 2026 is perfectly plausible for an exposure in thousands; what
makes `2026` a period here is that it is written as one. Guessing from the size
of the number would fail on "ECL rose more than 2026" meaning exactly that, and
would fail differently every year.

What counts as time
-------------------
Quarters (`Q1 2026`), years (`2026`, `FY2026`, `CY 2026`), months
(`March 2026`, `2026-03`), half years, spans (`between Q1 2026 and Q2 2026`,
`from 2024 to 2026`), relative windows (`last quarter`, `the previous four
quarters`, `year on year`, `latest year`, `this quarter`) and the horizons a
credit question names (`over the next 12 months`).

A bare four-digit number in the range a reporting calendar occupies is a year.
That is the one judgement call in the module, and it is bounded: outside
`_YEAR_FLOOR`..`_YEAR_CEILING` a number is a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: The window in which a bare four-digit integer is read as a calendar year
#: rather than as a quantity. Deliberately generous at the top — a book may
#: carry forward-looking periods — and deliberately closed, so an exposure of
#: 1,500 or a limit of 3,000 is never mistaken for a date.
_YEAR_FLOOR = 1990
_YEAR_CEILING = 2100

_MONTH_NAMES = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
                r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
                r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")

#: Every shape a reporting period takes in a question. Ordered longest-first,
#: because "Q1 2026" must be consumed whole before the bare-year rule can see
#: the 2026 inside it.
_SHAPES: tuple[tuple[str, str], ...] = (
    # A named span, taken whole so neither endpoint is left loose.
    ("span", r"\b(?:between|from)\s+(?:q[1-4]\s*)?(?:fy|cy)?\s*\d{4}\s+"
             r"(?:and|to|through|until|-)\s+(?:q[1-4]\s*)?(?:fy|cy)?\s*\d{4}\b"),
    ("span", r"\bbetween\s+q[1-4]\s+\d{4}\s+and\s+q[1-4]\s+\d{4}\b"),
    # Quarters and halves.
    ("quarter", r"\bq[1-4]\s*[-/ ]?\s*(?:fy|cy)?\s*\d{4}\b"),
    ("quarter", r"\b\d{4}\s*[-/]\s*q[1-4]\b"),
    ("half", r"\bh[12]\s*(?:fy|cy)?\s*\d{4}\b"),
    # Months.
    ("month", rf"\b(?:{_MONTH_NAMES})\s+\d{{4}}\b"),
    ("month", r"\b\d{4}-(?:0[1-9]|1[0-2])\b"),
    # Fiscal and calendar years, and a bare year introduced by a preposition.
    ("year", r"\b(?:fy|cy)\s*\d{4}\b"),
    ("year", r"\b(?:in|during|for|as at|as of|at)\s+\d{4}\b"),
    # Relative windows. These carry no digits of their own except a count of
    # periods, which is a length of time and not a magnitude either.
    #
    # The "over the …" form comes first so the whole phrase is taken as one
    # span rather than leaving a loose "over" for a threshold reader to find.
    ("relative", r"\b(?:over|during|across|within|throughout|for)\s+the\s+"
                 r"(?:next|last|past|previous|coming|latest|trailing)\s+"
                 r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
                 r"twelve)?\s*"
                 r"(?:reporting|calendar|fiscal|financial|trading|business|"
                 r"consecutive|full)?\s*"
                 r"(?:months?|quarters?|years?|weeks?|days?|periods?)\b"),
    ("relative", r"\b(?:the\s+)?(?:latest|last|previous|prior|preceding|"
                 r"trailing|past|next|coming|following)\s+"
                 r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
                 r"twelve)?\s*"
                 r"(?:reporting|calendar|fiscal|financial|trading|business|"
                 r"consecutive|full)?\s*"
                 r"(?:quarters?|years?|months?|weeks?|days?|periods?|"
                 r"cycles?|halves|half)\b"),
    ("relative", r"\b(?:this|the current|the latest)\s+"
                 r"(?:quarter|year|month|period|cycle|reporting period)\b"),
    ("relative", r"\b(?:year[ -]on[ -]year|quarter[ -]on[ -]quarter|"
                 r"year[ -]over[ -]year|q[- ]?o[- ]?q|y[- ]?o[- ]?y|"
                 r"month[ -]on[ -]month)\b"),
    ("relative", r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
                 r"twelve)[- ](?:month|quarter|year|week|day)\s+"
                 r"(?:horizon|window|period|window|view|lookback|look-back)\b"),
    ("relative", r"\b(?:since|until|till)\s+(?:q[1-4]\s+)?\d{4}\b"),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.IGNORECASE)) for kind, pattern in _SHAPES)

#: A bare four-digit number that no other shape claimed. Checked last, and only
#: inside the calendar window.
_BARE_YEAR = re.compile(r"(?<![\w.%])(\d{4})(?![\w.%])")

#: Digits that belong to a measure rather than to a calendar, whatever they
#: look like. "12-month PD" is the NAME of a measure; masking its 12 would be
#: harmless here but would break the concept resolver downstream, and a module
#: that quietly edits a measure's name is worse than the defect it fixes.
_MEASURE_NAMES = re.compile(
    r"\b(?:12|twelve)[- ]month\s+(?:pd|probability)"
    r"|\blifetime\s+pd\b"
    r"|\b(?:ifrs\s*9|ifrs9)\b"
    r"|\bstage\s*[123]\b"
    r"|\bbasel\s*(?:ii|iii|\d)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Span:
    """One temporal expression, and where it sits in the text."""

    kind: str
    text: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text,
                "start": self.start, "end": self.end}


@dataclass(frozen=True)
class Reading:
    """What a question says about time, kept apart from what it says about size."""

    spans: tuple[Span, ...] = field(default_factory=tuple)

    @property
    def any(self) -> bool:
        return bool(self.spans)

    def texts(self) -> tuple[str, ...]:
        return tuple(s.text for s in self.spans)

    def to_dict(self) -> dict[str, Any]:
        return {"spans": [s.to_dict() for s in self.spans]}


def _overlaps(start: int, end: int, taken: list[tuple[int, int]]) -> bool:
    return any(start < b and a < end for a, b in taken)


def read(text: str) -> Reading:
    """Every temporal expression in a fragment, longest shape first."""
    said = str(text or "")
    if not said:
        return Reading()

    taken: list[tuple[int, int]] = []
    # Measure names are reserved first, so their digits can never be claimed as
    # a date by a later, greedier shape.
    for found in _MEASURE_NAMES.finditer(said):
        taken.append((found.start(), found.end()))

    spans: list[Span] = []
    for kind, pattern in _COMPILED:
        for found in pattern.finditer(said):
            if _overlaps(found.start(), found.end(), taken):
                continue
            taken.append((found.start(), found.end()))
            spans.append(Span(kind=kind, text=found.group(0),
                              start=found.start(), end=found.end()))

    for found in _BARE_YEAR.finditer(said):
        if _overlaps(found.start(), found.end(), taken):
            continue
        year = int(found.group(1))
        if not _YEAR_FLOOR <= year <= _YEAR_CEILING:
            continue
        taken.append((found.start(), found.end()))
        spans.append(Span(kind="year", text=found.group(0),
                          start=found.start(), end=found.end()))

    spans.sort(key=lambda s: s.start)
    return Reading(spans=tuple(spans))


def without_time(text: str) -> str:
    """The fragment with every temporal expression blanked out.

    Same length as the input, so an offset a caller already holds still points
    at the same word. This is what every numeric threshold reader must be given
    instead of the raw text.
    """
    said = str(text or "")
    found = read(said)
    if not found.any:
        return said
    out = list(said)
    for span in found.spans:
        for index in range(span.start, span.end):
            out[index] = " "
    return "".join(out)


def is_temporal(fragment: str) -> bool:
    """Whether a fragment is ENTIRELY a time expression.

    Used where a caller has already isolated something and needs to know
    whether it is a date rather than where the dates are.
    """
    said = " ".join(str(fragment or "").split())
    if not said:
        return False
    return not without_time(said).strip()


__all__ = ["Reading", "Span", "is_temporal", "read", "without_time"]
