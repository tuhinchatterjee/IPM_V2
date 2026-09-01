"""
Shared plumbing: getting one borrower's rows out of a governed dataset.

Every reader needs the same three things - the periods a dataset holds, the
rows for one borrower at one of them, and the row before - and each of them
has a way to be subtly wrong. Doing it once means being wrong once, and being
fixed once.

The period sort is the example. Reporting-period labels look sortable and are
not: "Q4 2025" sorts after "Q2 2026" alphabetically, which puts the latest
period a year and two quarters in the past and compares it against the wrong
prior one. Every figure downstream is then correct and about the wrong dates,
which is the hardest kind of wrong to notice.
"""

from __future__ import annotations

import re
from typing import Any

_QUARTER = re.compile(r"\s*Q([1-4])\s+(\d{4})")
_YEAR_FIRST = re.compile(r"\s*(\d{4})[-/]?Q?([1-4])?")


def period_key(period: str) -> tuple[int, int]:
    """A reporting-period label as something that sorts chronologically."""
    found = _QUARTER.match(str(period))
    if found:
        return (int(found.group(2)), int(found.group(1)))
    found = _YEAR_FIRST.match(str(period))
    if found:
        return (int(found.group(1)), int(found.group(2) or 0))
    return (0, 0)


def load(dataset: str) -> Any:
    """The dataset, or None when this deployment does not carry it.

    Returning None rather than raising is deliberate: a missing dataset is a
    thing a reading REPORTS (§7), not a failure that takes a screen down.
    """
    try:
        from backend.corporate import service as corporate

        return corporate._load(dataset)
    except Exception:  # noqa: BLE001 - reported by the reader as missing
        return None


def periods_of(frame: Any) -> list[str]:
    if frame is None or "period" not in getattr(frame, "columns", []):
        return []
    return sorted((str(p) for p in frame["period"].unique()), key=period_key)


def resolve(frame: Any, period: str = "") -> tuple[str, str]:
    """The period to read and the one before it.

    An unrecognised period resolves to nothing rather than to the latest.
    Quietly answering about a different quarter is the worst failure available
    here: every figure is right and every one is about the wrong date.
    """
    periods = periods_of(frame)
    if not periods:
        return ("", "")
    chosen = period or periods[-1]
    if chosen not in periods:
        return ("", "")
    index = periods.index(chosen)
    return (chosen, periods[index - 1] if index else "")


def rows_for(frame: Any, borrower_id: str, period: str,
             key: str = "borrower_id") -> list[dict[str, Any]]:
    if frame is None or not period:
        return []
    if key not in getattr(frame, "columns", []):
        return []
    found = frame[(frame[key] == borrower_id) & (frame["period"] == period)]
    return found.to_dict("records")


__all__ = ["load", "period_key", "periods_of", "resolve", "rows_for"]
