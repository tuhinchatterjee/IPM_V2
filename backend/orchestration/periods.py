"""
Reporting periods: what the data actually has, and what to offer the user.

Two jobs.

**Reading a period out of the question.** "Which sectors deteriorated this
quarter?" specifies a comparison; "which sectors deteriorated?" does not. The
difference decides whether IPM answers or asks, so it is worked out here rather
than guessed at the point of use.

**Offering choices that exist.** If the book is quarterly, "last 3 months" is a
nonsense option — it is one quarter, or none. Every option this module returns
is built from the real period list and resolves to two real period labels, so
answering a clarification is a click rather than a typing exercise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Frequency(StrEnum):
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"
    ANNUAL = "annual"
    UNKNOWN = "unknown"


QUARTER = re.compile(r"^Q([1-4])\s+(\d{4})$", re.I)
MONTH_NAMES = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
MONTH = re.compile(rf"^({MONTH_NAMES})[a-z]*\s+(\d{{4}})$", re.I)
ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
YEAR = re.compile(r"^(FY\s*)?(\d{4})$", re.I)


def detect_frequency(periods: list[str]) -> Frequency:
    """How often the book is reported, read from the period labels themselves."""
    if not periods:
        return Frequency.UNKNOWN
    sample = periods[: min(len(periods), 8)]
    if all(QUARTER.match(p) for p in sample):
        return Frequency.QUARTERLY
    if all(MONTH.match(p) or ISO_MONTH.match(p) for p in sample):
        return Frequency.MONTHLY
    if all(YEAR.match(p) for p in sample):
        return Frequency.ANNUAL
    return Frequency.UNKNOWN


#: How many reporting periods make up a span, per frequency. A span the data
#: cannot express is simply not offered.
_STEPS_PER_SPAN: dict[Frequency, dict[str, int]] = {
    Frequency.QUARTERLY: {"3 months": 1, "6 months": 2, "12 months": 4},
    Frequency.MONTHLY: {"3 months": 3, "6 months": 6, "12 months": 12},
    Frequency.ANNUAL: {"12 months": 1, "3 years": 3},
}

_UNIT_LABEL: dict[Frequency, str] = {
    Frequency.QUARTERLY: "quarter",
    Frequency.MONTHLY: "month",
    Frequency.ANNUAL: "year",
    Frequency.UNKNOWN: "period",
}


@dataclass(frozen=True)
class PeriodChoice:
    """One quick option on a clarification, already resolved to real periods."""

    id: str
    label: str
    from_period: str
    to_period: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "from_period": self.from_period,
            "to_period": self.to_period,
            "detail": self.detail,
        }


def comparison_choices(periods: list[str], limit: int = 5) -> list[PeriodChoice]:
    """The comparison spans this dataset can actually support.

    Ordered from the most commonly wanted to the broadest. Spans longer than the
    history are dropped rather than clamped: offering "last 12 months" on nine
    months of data would produce an answer to a different question.
    """
    if len(periods) < 2:
        return []

    frequency = detect_frequency(periods)
    unit = _UNIT_LABEL[frequency]
    latest = periods[-1]
    choices = [
        PeriodChoice(
            id="previous",
            label=f"Latest vs previous {unit}",
            from_period=periods[-2],
            to_period=latest,
            detail=f"{periods[-2]} to {latest}",
        )
    ]

    for span, steps in _STEPS_PER_SPAN.get(frequency, {}).items():
        if steps <= 1 or steps >= len(periods):
            continue
        start = periods[-1 - steps]
        choices.append(PeriodChoice(
            id=span.replace(" ", "_"),
            label=f"Last {span}",
            from_period=start,
            to_period=latest,
            detail=f"{start} to {latest}",
        ))

    if len(periods) > 2:
        choices.append(PeriodChoice(
            id="full_history",
            label="Full history",
            from_period=periods[0],
            to_period=latest,
            detail=f"{periods[0]} to {latest}",
        ))

    # Drop duplicates that collapse onto the same pair of periods.
    seen: set[tuple[str, str]] = set()
    unique: list[PeriodChoice] = []
    for choice in choices:
        key = (choice.from_period, choice.to_period)
        if key in seen:
            continue
        seen.add(key)
        unique.append(choice)
    return unique[:limit]


# ---------------------------------------------------------------------------
# Reading a period out of a question
# ---------------------------------------------------------------------------

#: Phrases that pin a comparison without naming a period. Each maps to the
#: number of reporting steps back from the latest period.
_RELATIVE_SPANS: list[tuple[str, str]] = [
    (r"\bthis (period|quarter|month)\b", "previous"),
    (r"\bsince last (period|quarter|month)\b", "previous"),
    (r"\bvs\.? (the )?(previous|prior|last) (period|quarter|month)\b", "previous"),
    (r"\bagainst (the )?(previous|prior|last) (period|quarter|month)\b", "previous"),
    (r"\blast quarter\b", "previous"),
    (r"\bquarter[- ]on[- ]quarter\b", "previous"),
    (r"\blast (3|three) months\b", "3 months"),
    (r"\blast (6|six) months\b", "6 months"),
    (r"\blast (12|twelve) months\b", "12 months"),
    (r"\bover the (last|past) year\b", "12 months"),
    (r"\byear[- ]on[- ]year\b", "12 months"),
    (r"\bsince the start\b", "full history"),
    (r"\ball (available )?(periods|history)\b", "full history"),
    (r"\bover time\b", "full history"),
]


@dataclass(frozen=True)
class PeriodIntent:
    """What the question said about time."""

    specified: bool
    from_period: str | None = None
    to_period: str | None = None
    #: How it was read — shown on the Trace's interpretation node.
    source: str = ""
    named_periods: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "specified": self.specified,
            "from_period": self.from_period,
            "to_period": self.to_period,
            "source": self.source,
            "named_periods": list(self.named_periods),
        }


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def read_period_intent(question: str, periods: list[str]) -> PeriodIntent:
    """Work out whether the question already settled the comparison period."""
    if not periods:
        return PeriodIntent(specified=False, source="no periods available")

    lowered = " " + _normalise(question) + " "

    # 1. Periods named outright, e.g. "Q1 2026 vs Q4 2025".
    named = [p for p in periods if f" {_normalise(p)} " in lowered]
    if len(named) >= 2:
        ordered = [p for p in periods if p in named]
        return PeriodIntent(True, ordered[0], ordered[-1],
                            "two reporting periods named in the question", ordered)
    if len(named) == 1:
        only = named[0]
        index = periods.index(only)
        # "since Q2 2025" and "from Q2 2025" open a window that runs to the
        # latest period. Without this they would read as "the quarter ending
        # Q2 2025", which is the opposite of what was asked.
        if re.search(rf"\b(since|from|after)\s+{re.escape(_normalise(only))}\b", lowered):
            if only != periods[-1]:
                return PeriodIntent(True, only, periods[-1],
                                    f"the question asked for the period since {only}", named)
        if index == 0:
            return PeriodIntent(True, only, periods[-1],
                                "one period named; compared to the latest", named)
        return PeriodIntent(True, periods[index - 1], only,
                            "one period named; compared to the period before it", named)

    # 2. Relative phrases, resolved against the real period list.
    for pattern, span in _RELATIVE_SPANS:
        if not re.search(pattern, lowered):
            continue
        if span == "previous":
            return PeriodIntent(True, periods[-2], periods[-1],
                                "the question asked about the current period")
        if span == "full history":
            return PeriodIntent(True, periods[0], periods[-1],
                                "the question asked about the whole history")
        steps = _STEPS_PER_SPAN.get(detect_frequency(periods), {}).get(span)
        if steps and steps < len(periods):
            return PeriodIntent(True, periods[-1 - steps], periods[-1],
                                f"the question asked for the last {span}")

    return PeriodIntent(False, source="the question did not say which periods to compare")


__all__ = [
    "Frequency",
    "PeriodChoice",
    "PeriodIntent",
    "comparison_choices",
    "detect_frequency",
    "read_period_intent",
]
