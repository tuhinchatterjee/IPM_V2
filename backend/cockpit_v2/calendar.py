"""
Quarters, reporting dates and availability dates. Brief §3.1, §3.2.

Small on purpose. Every module that reasons about "the latest completed
quarter" or "which statement was knowable at this date" goes through here, so
the one rule that matters — later information never leaks into an earlier
snapshot — is enforced in a single place rather than re-derived per caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

#: The eight completed quarters the demo publishes. Brief §3.1's initial target.
QUARTERS: tuple[str, ...] = (
    "2024Q3", "2024Q4", "2025Q1", "2025Q2",
    "2025Q3", "2025Q4", "2026Q1", "2026Q2",
)

#: The compact two-quarter pilot built and proven before the full demo.
PILOT_QUARTERS: tuple[str, ...] = ("2026Q1", "2026Q2")

#: Calendar quarters, stated. Not fiscal, not rolling.
QUARTER_SEMANTICS = (
    "Calendar quarters. 2026Q2 means the three months ending 30 June 2026, and "
    "the snapshot is as at that date. Every published quarter is a COMPLETED "
    "reporting period; no partial quarter is published as an actual.")

_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_MONTH_END_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


@dataclass(frozen=True)
class Quarter:
    label: str
    year: int
    quarter: int

    @property
    def end_date(self) -> date:
        month = _QUARTER_END_MONTH[self.quarter]
        return date(self.year, month, _MONTH_END_DAY[month])

    @property
    def start_date(self) -> date:
        month = _QUARTER_END_MONTH[self.quarter] - 2
        return date(self.year, month, 1)

    @property
    def index(self) -> int:
        """Quarters since 2000Q1. Handy for arithmetic across year ends."""
        return (self.year - 2000) * 4 + (self.quarter - 1)

    def shift(self, quarters: int) -> Quarter:
        i = self.index + int(quarters)
        return Quarter(f"{2000 + i // 4}Q{i % 4 + 1}", 2000 + i // 4, i % 4 + 1)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.label


def parse(label: str) -> Quarter:
    """`2026Q2`, `2026-Q2`, `Q2 2026` and `Cockpit_2026_Q2` all mean one thing."""
    text = str(label).strip().replace("-", "").replace("_", "").replace(" ", "")
    text = text.upper()
    if text.startswith("COCKPIT"):
        text = text[len("COCKPIT"):]
    if "Q" not in text:
        raise ValueError(f"{label!r} is not a quarter label")
    left, right = text.split("Q", 1)
    if left and left.isdigit() and len(left) == 4:
        year, quarter = int(left), int(right[:1])
    else:  # "Q22026"
        quarter, year = int(right[:1]), int(right[1:5])
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"{label!r} does not name a quarter of the year")
    return Quarter(f"{year}Q{quarter}", year, quarter)


def reporting_date(label: str) -> date:
    return parse(label).end_date


def iso(label: str) -> str:
    return reporting_date(label).isoformat()


def previous(label: str) -> str | None:
    """The published quarter before this one, or None when there is none.

    Returning None rather than the earliest quarter is the point: brief §3.1
    says that if a prior comparison period is absent the Cockpit must say so
    instead of comparing an arbitrary dataset.
    """
    i = QUARTERS.index(label) if label in QUARTERS else -1
    return QUARTERS[i - 1] if i > 0 else None


def latest() -> str:
    """The latest COMPLETED quarter the demo publishes."""
    return QUARTERS[-1]


def display(label: str) -> str:
    q = parse(label)
    return f"Q{q.quarter} {q.year}"


def dataset_name(label: str) -> str:
    """The governed dataset name of one quarterly package."""
    q = parse(label)
    return f"cockpit_{q.year}_q{q.quarter}"


def business_name(label: str) -> str:
    """The name the user sees in Data Builder — brief §3.1's `Cockpit_2026_Q2`."""
    q = parse(label)
    return f"Cockpit_{q.year}_Q{q.quarter}"


#: Days after a period end before an audited annual statement is available.
ANNUAL_AVAILABILITY_LAG_DAYS = 120
#: The same for a management interim statement.
INTERIM_AVAILABILITY_LAG_DAYS = 55


def available_by(period_end: date, *, audited: bool) -> date:
    lag = (ANNUAL_AVAILABILITY_LAG_DAYS if audited
           else INTERIM_AVAILABILITY_LAG_DAYS)
    return period_end + timedelta(days=lag)


def knowable(available_date: date, as_at: date) -> bool:
    """Whether a fact was knowable at a reporting date. The leak guard."""
    return available_date <= as_at


__all__ = ["ANNUAL_AVAILABILITY_LAG_DAYS", "INTERIM_AVAILABILITY_LAG_DAYS",
           "PILOT_QUARTERS", "QUARTERS", "QUARTER_SEMANTICS", "Quarter",
           "available_by", "business_name", "dataset_name", "display", "iso",
           "knowable", "latest", "parse", "previous", "reporting_date"]
