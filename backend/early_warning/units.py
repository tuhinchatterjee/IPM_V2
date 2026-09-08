"""
How an Early Warning figure is written down, in one place.

Why this is its own module
--------------------------
It started in the composer, which was fine until the escalation note needed
it too — and `compose` imports `escalation`, so the note could not reach it
and wrote its own `SAR {x:,.0f}m` instead. That is how a convention becomes
four conventions: the acceptance run found a KPI tile reading `15,470` above
prose reading "SAR 15.5bn" above a report narrative reading
"SAR 117991.0 million", all three the same exposure.

So the writer sits below everything that writes, and nothing formats a
riyal figure by hand. `tests/early_warning/test_money_convention.py` reads
the source of the modules that write and fails if any of them does.

The convention
--------------
The book is kept in millions of riyals. A credit officer says "fifteen point
five billion", never "fifteen thousand four hundred and seventy million", so
a figure at or above a thousand millions is written in billions to one
decimal. Below that it stays in millions, also to one decimal, because a
facility at 321.8 rounded to 322 has lost the precision the reader is
checking the figure for. A live residual under a hundred thousand riyals
keeps a second decimal rather than rounding to "SAR 0.0m", which reads as no
exposure at all.

Mirrored character for character by `money()` in
frontend/src/lib/early-warning-format.ts. The same exposure appears on a KPI
tile, in the sentence beneath it, and in the report generated from both, and
the two sides carry the same expected strings in their own tests so neither
can drift alone.

Tables are the deliberate exception. A column of twenty-five rows each
repeating "SAR" is twenty-four repetitions of the one fact that does not
change, so a table names its unit once in the header — `(SAR mn)` in a
report, `(SAR m)` on screen — and keeps bare numbers in the cells.
"""

from __future__ import annotations

#: What a money column says in its header, once, in a generated report.
MONEY_COLUMN_UNIT = "SAR mn"


def money(value: float) -> str:
    """A monetary figure, written the one way Early Warning writes it."""
    if abs(value) >= 1000:
        return f"SAR {value / 1000:,.1f}bn"
    if 0 < abs(value) < 0.1:
        return f"SAR {value:,.2f}m"
    return f"SAR {value:,.1f}m"


def money_cell(value: float | None) -> str:
    """A money value for a table cell, bare, under a `(SAR mn)` header.

    Deliberately not scaled. A column where one cell reads 15.5 and the next
    reads 840.0 under a single header is a column stating two different
    units, and the reader has no way to tell which row is which.
    """
    if value is None:
        return "—"
    return f"{value:,.1f}"


__all__ = ["MONEY_COLUMN_UNIT", "money", "money_cell"]
