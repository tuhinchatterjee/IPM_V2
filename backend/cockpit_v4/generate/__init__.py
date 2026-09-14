"""V4-native synthetic book generators. One module per analytical domain."""

from __future__ import annotations

MONTHS = 20
LAST_MONTH = "2026-08"


def month_range(last: str = LAST_MONTH, count: int = MONTHS) -> tuple[str, ...]:
    """The `count` completed months ending at `last`, oldest first.

    Completed, deliberately. A part-month at the end of a book reads as a
    collapse in every month-on-month comparison drawn against it, and no
    amount of footnoting stops a reader seeing the cliff.
    """
    year, month = (int(p) for p in last.split("-"))
    out: list[str] = []
    for back in range(count - 1, -1, -1):
        total = year * 12 + (month - 1) - back
        out.append(f"{total // 12:04d}-{total % 12 + 1:02d}")
    return tuple(out)


def months_between(earlier: str, later: str) -> int:
    ey, em = (int(p) for p in earlier.split("-"))
    ly, lm = (int(p) for p in later.split("-"))
    return (ly * 12 + lm) - (ey * 12 + em)


__all__ = ["LAST_MONTH", "MONTHS", "month_range", "months_between"]
