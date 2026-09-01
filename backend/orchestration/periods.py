"""
Reporting periods: what the data actually has, and what to offer the user.

Two jobs.

**Reading a period out of the question.** "Which sectors deteriorated this
quarter?" specifies a comparison; "which sectors deteriorated?" does not. The
difference decides whether CreditProbe answers or asks, so it is worked out here rather
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
    Frequency.QUARTERLY: {"3 months": 1, "6 months": 2, "12 months": 4,
                          "2 years": 8, "3 years": 12},
    Frequency.MONTHLY: {"3 months": 3, "6 months": 6, "12 months": 12,
                        "2 years": 24, "3 years": 36},
    Frequency.ANNUAL: {"12 months": 1, "2 years": 2, "3 years": 3},
}

#: Which spans are offered as clarification choices. The longer spans exist so a
#: question can resolve them, but a menu of six options is a menu nobody reads.
_OFFERED_SPANS = ("3 months", "6 months", "12 months")

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
        if span not in _OFFERED_SPANS or steps <= 1 or steps >= len(periods):
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

#: The words a credit officer uses for "the most recent one". Treated as
#: synonyms on purpose: a product that resolved "over the LAST year" and asked a
#: clarifying question about "over the LATEST year" is not reading English, it is
#: pattern-matching, and the difference was visible to every user who hit it.
_RECENT = r"(?:last|latest|past|previous|prior|current|trailing|most recent|this)"

#: Phrases that pin a comparison without naming a period. Each maps to the
#: number of reporting steps back from the latest period.
#:
#: Ordered longest-match-first within each span so "the last three years" is not
#: consumed by the plain "last year" rule.
_RELATIVE_SPANS: list[tuple[str, str]] = [
    # ---- three years
    (rf"\b(?:over|in|across|for)?\s*(?:the\s+)?{_RECENT}\s+(?:3|three)\s+years?\b",
     "3 years"),
    (r"\b(?:3|three)[- ]year\b", "3 years"),
    (r"\b(?:12|twelve)\s+quarters\b", "3 years"),

    # ---- two years
    (rf"\b(?:over|in|across|for)?\s*(?:the\s+)?{_RECENT}\s+(?:2|two)\s+years?\b",
     "2 years"),
    (r"\b(?:2|two)[- ]year\b", "2 years"),
    (r"\b(?:8|eight)\s+quarters\b", "2 years"),

    # ---- a year
    (rf"\b(?:over|in|across|for|during|since)?\s*(?:the\s+)?{_RECENT}\s+year\b",
     "12 months"),
    (rf"\b{_RECENT}\s+(?:12|twelve)\s+months\b", "12 months"),
    (r"\b(?:12|twelve)[- ]months?\b", "12 months"),
    (r"\byear[- ]on[- ]year\b|\byear[- ]over[- ]year\b|\byoy\b", "12 months"),
    (r"\b(?:4|four)\s+quarters\b", "12 months"),
    (r"\bannual (?:change|movement|comparison)\b", "12 months"),

    # ---- six months
    (rf"\b{_RECENT}\s+(?:6|six)\s+months\b", "6 months"),
    (r"\b(?:6|six)[- ]months?\b", "6 months"),
    (r"\b(?:2|two)\s+quarters\b", "6 months"),

    # ---- a quarter
    (rf"\b{_RECENT}\s+(?:period|quarter|month)\b", "previous"),
    (rf"\bsince\s+{_RECENT}\s+(?:period|quarter|month)\b", "previous"),
    (rf"\bvs\.?\s+(?:the\s+)?{_RECENT}\s+(?:period|quarter|month)\b",
     "previous"),
    (rf"\bagainst\s+(?:the\s+)?{_RECENT}\s+(?:period|quarter|month)\b",
     "previous"),
    (r"\bquarter[- ]on[- ]quarter\b|\bqoq\b", "previous"),
    (rf"\b{_RECENT}\s+(?:3|three)\s+months\b", "3 months"),
    (r"\bsequential(?:ly)?\b", "previous"),

    # ---- everything
    (r"\bsince the start\b", "full history"),
    (r"\ball (?:available )?(?:periods|history)\b", "full history"),
    (r"\bover time\b|\bfull history\b|\bwhole history\b", "full history"),
    (r"\bevery (?:quarter|period|year)\b", "full history"),
]

#: The comparison a two-period question means when it does not say. A year, and
#: it is stated on the answer rather than assumed silently — see
#: `governed_default`.
DEFAULT_SPAN = "12 months"


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


#: A reporting period as people write one. Matched against the question so a
#: period the data does NOT have can be told apart from no period at all.
#:
#: `(pattern, exact)` — `exact` means the whole phrase has to be a period the
#: data holds; otherwise it is enough that the data covers the year.
_PERIOD_SHAPED: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(r"\bq[1-4]\s+(\d{4})\b", re.I), True),
    (re.compile(r"\b(?:fy|cy)\s*(\d{4})\b", re.I), False),
    (re.compile(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
                r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
                r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{4})\b",
     re.I), False),
    (re.compile(r"\b(?:in|during|for)\s+(\d{4})\b", re.I), False),
)


def unavailable(question: str, periods: list[str]) -> str:
    """A period the question names outright that the data does not hold.

    The failure this prevents
    -------------------------
        "What was total exposure at default in Q1 2015?"

    came back as a confident portfolio figure — for Q2 2026. The period reader
    matches against the periods that EXIST, so one that does not exist did not
    register as a period at all, and the request fell through to the governed
    default as though no date had been mentioned. A credit officer reading a
    2015 question above a 2026 answer has nothing on the screen to tell them
    which quarter they are looking at.

    Returns the period as the question wrote it, or "" when everything it names
    is available. It never proposes a near miss: offering Q1 2023 to somebody
    who asked for Q1 2015 invites them to accept a different question.
    """
    if not periods:
        return ""
    known = {_normalise(p) for p in periods}
    years = {p.strip()[-4:] for p in periods}

    for pattern, exact in _PERIOD_SHAPED:
        for match in pattern.finditer(str(question or "")):
            if match.group(1) in years and not exact:
                continue
            if exact and _normalise(match.group(0)) in known:
                continue
            if exact and match.group(1) not in years:
                return match.group(0).strip()
            if exact:
                return match.group(0).strip()
            return match.group(1)
    return ""


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


def governed_default(periods: list[str]) -> PeriodIntent:
    """The comparison window to use when a movement question named none.

    The product used to stop and ask. That is the right instinct applied to the
    wrong case: a period genuinely IS ambiguous when two readings would give
    different answers, and "which customers were downgraded?" is not one of
    those — every credit officer asking it means over the review cycle, which is
    a year.

    So the default is taken, and the answer says which two periods it used. An
    unnecessary question costs a round trip and makes the product look unsure;
    an unstated assumption would be worse than either, which is why the source
    string is written to be shown rather than logged.
    """
    if len(periods) < 2:
        return PeriodIntent(False, source="there is only one published period")

    steps = _STEPS_PER_SPAN.get(detect_frequency(periods), {}).get(DEFAULT_SPAN)
    if not steps or steps >= len(periods):
        # Not enough history for a year. The full span is the honest answer,
        # and saying so is better than refusing.
        return PeriodIntent(
            True, periods[0], periods[-1],
            f"the question did not name a window, so CreditProbe used the full "
            f"published history, {periods[0]} to {periods[-1]}")

    opening, closing = periods[-1 - steps], periods[-1]
    return PeriodIntent(
        True, opening, closing,
        f"the question did not name a window, so CreditProbe used the governed "
        f"default of the latest year: {opening} to {closing}")


__all__ = [
    "unavailable",
    "DEFAULT_SPAN",
    "Frequency",
    "PeriodChoice",
    "PeriodIntent",
    "comparison_choices",
    "detect_frequency",
    "governed_default",
    "read_period_intent",
]
