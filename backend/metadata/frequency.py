"""How often a dataset publishes, read from the periods it actually published.

Not declared, derived. A dataset that says it is monthly and has published four
quarters is quarterly, and the catalogue that believes the declaration will
offer a reader a month-on-month comparison that cannot be computed. The labels
in the lake are the only thing that knows.

Why it matters here rather than in a presentation layer
-------------------------------------------------------
Frequency changes what a sentence MEANS. "The latest period" is a quarter for
one dataset and a month for another; "over the latest year" steps back four
periods in the first and twelve in the second; and a month-on-month movement
over a quarterly book is a number with nothing behind it. Every one of those
is a wrong answer rather than a formatting choice, so the frequency has to be a
governed property of the dataset and not a guess made where it is displayed.
"""

from __future__ import annotations

import re

QUARTERLY = "quarterly"
MONTHLY = "monthly"
ANNUAL = "annual"
DAILY = "daily"
IRREGULAR = "irregular"
NONE = ""

#: How each frequency reads in a sentence, singular and plural.
UNIT: dict[str, tuple[str, str]] = {
    QUARTERLY: ("quarter", "quarters"),
    MONTHLY: ("month", "months"),
    ANNUAL: ("year", "years"),
    DAILY: ("day", "days"),
    IRREGULAR: ("period", "periods"),
    NONE: ("period", "periods"),
}

#: How many published periods make a year at each frequency. Read by anything
#: that has to turn "year on year" into a number of steps.
PERIODS_IN_A_YEAR: dict[str, int] = {
    QUARTERLY: 4, MONTHLY: 12, ANNUAL: 1, DAILY: 365,
}

_QUARTER = re.compile(r"^\s*Q([1-4])\s+(\d{4})\s*$", re.IGNORECASE)
_YEAR_QUARTER = re.compile(r"^\s*(\d{4})[-\s]?Q([1-4])\s*$", re.IGNORECASE)
_YEAR_MONTH = re.compile(r"^\s*(\d{4})[-/](\d{1,2})\s*$")
_MONTH_NAME = re.compile(
    r"^\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})"
    r"\s*$", re.IGNORECASE)
_YEAR = re.compile(r"^\s*(?:FY\s*)?(\d{4})\s*$", re.IGNORECASE)
_DATE = re.compile(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s*$")


def shape_of(label: str) -> str:
    """What one period label IS, from its own shape."""
    text = str(label or "")
    if _QUARTER.match(text) or _YEAR_QUARTER.match(text):
        return QUARTERLY
    if _DATE.match(text):
        return DAILY
    if _YEAR_MONTH.match(text) or _MONTH_NAME.match(text):
        return MONTHLY
    if _YEAR.match(text):
        return ANNUAL
    return IRREGULAR


def of(periods: tuple[str, ...] | list[str]) -> str:
    """The frequency a set of published periods is at.

    Empty for a dataset with no periods at all — a reference table has no
    frequency, and calling it "irregular" would suggest it publishes
    unpredictably rather than not at all.

    A dataset whose labels disagree is IRREGULAR rather than whichever shape
    happens to be commonest: a book that is half quarterly and half annual
    cannot answer "the latest quarter" and should not be asked to.
    """
    labels = [p for p in (periods or []) if str(p).strip()]
    if not labels:
        return NONE
    shapes = {shape_of(p) for p in labels}
    if len(shapes) == 1:
        return shapes.pop()
    return IRREGULAR


def unit(frequency: str, count: int = 1) -> str:
    """The word for one of this frequency's periods, singular or plural."""
    singular, plural = UNIT.get(frequency, UNIT[IRREGULAR])
    return singular if count == 1 else plural


def steps_for_a_year(frequency: str) -> int:
    """How many published periods a year is, or 0 where a year is meaningless."""
    return PERIODS_IN_A_YEAR.get(frequency, 0)


def coverage(periods: tuple[str, ...] | list[str]) -> str:
    """How far a dataset reaches, said the way its own frequency says it.

    "34 quarters from Q1 2018 to Q2 2026" rather than "34 periods": a reader
    deciding whether to ask a year-on-year question needs to know what a
    period IS here, and the number alone does not say.
    """
    labels = [p for p in (periods or []) if str(p).strip()]
    if not labels:
        return "No periods published."
    frequency = of(labels)
    word = unit(frequency, len(labels))
    if len(labels) == 1:
        return f"One {unit(frequency)} only: {labels[0]}."
    return f"{len(labels)} {word} from {labels[0]} to {labels[-1]}."


_MONTH_NUMBER = {m: n for n, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def sort_key(label: str) -> tuple[int, int, str]:
    """Where one period label sits in time.

    Period labels do not sort as text. "Q4 2025" is lexically after "Q2 2026"
    and chronologically before it, so a catalogue that took the string maximum
    reported the latest published period as one that had already passed.
    """
    text = str(label or "").strip()
    match = _QUARTER.match(text)
    if match:
        return (int(match.group(2)), int(match.group(1)) * 3, text)
    match = _YEAR_QUARTER.match(text)
    if match:
        return (int(match.group(1)), int(match.group(2)) * 3, text)
    match = _DATE.match(text)
    if match:
        return (int(match.group(1)),
                int(match.group(2)) * 100 + int(match.group(3)), text)
    match = _YEAR_MONTH.match(text)
    if match:
        return (int(match.group(1)), int(match.group(2)), text)
    match = _MONTH_NAME.match(text)
    if match:
        return (int(match.group(2)),
                _MONTH_NUMBER.get(match.group(1).lower()[:3], 0), text)
    match = _YEAR.match(text)
    if match:
        return (int(match.group(1)), 0, text)
    return (0, 0, text)


def latest_of(labels: list[str] | tuple[str, ...]) -> str:
    """The most recent of a set of period labels, chronologically."""
    real = [str(p) for p in (labels or []) if str(p).strip()]
    return max(real, key=sort_key) if real else ""


def earliest_of(labels: list[str] | tuple[str, ...]) -> str:
    real = [str(p) for p in (labels or []) if str(p).strip()]
    return min(real, key=sort_key) if real else ""


__all__ = ["QUARTERLY", "MONTHLY", "ANNUAL", "DAILY", "IRREGULAR", "NONE",
           "UNIT", "PERIODS_IN_A_YEAR", "shape_of", "of", "unit",
           "steps_for_a_year", "coverage", "sort_key", "latest_of",
           "earliest_of"]
