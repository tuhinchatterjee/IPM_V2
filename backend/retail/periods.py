"""Which months a question is about, and which of them can still be answered.

The failure this exists for
---------------------------
"Compare the latest complete quarter with the previous quarter" was answered
by looking at the computer's clock. On a machine whose date had rolled into
September the answer named a Q3 that the book does not contain, and a project
seeded the same way is still on screen titled "Retail Portfolio Review — Q3
2026" over a book whose last month is August.

The published chronology is a property of the DATA. It is read from the
manifest of scored months, never from `date.today()`.

Two separate ideas that get confused
------------------------------------
**Completeness** is about the calendar: a quarter is complete when the book
holds all three of its months. With August as the latest month, the latest
COMPLETE quarter is Q2 2026 (Apr-Jun) and the comparison is Q1 2026. July and
August are a quarter-to-date of two months, which may be compared only with
another two-month window that is named as such.

**Maturity** is about outcomes: a twelve-month outcome for an observation made
in August 2026 has not happened yet. Asking whether those customers defaulted
returns a rate near zero, not because they are safe but because the window is
open. A matured twelve-month assessment observes no later than August 2025.

Both are needed at once, and they answer different questions: "what does the
book look like now" uses the latest month; "how did the model do" uses the
latest matured cutoff; and a screen that shows one while labelling it the
other is the defect this module exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Version of the period rules themselves, so an analysis can record which set
#: of conventions produced its dates.
PERIOD_POLICY_VERSION = "retail-period-policy-1.0.0"

#: Months in an outcome window. Twelve is the horizon the retail PD models are
#: fitted on; changing it is a model decision, not a display one.
OUTCOME_HORIZON_MONTHS = 12


def _index(month: str) -> int:
    year, part = month.split("-")
    return int(year) * 12 + int(part) - 1


def _month(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def shift(month: str, by: int) -> str:
    """`by` months later (negative for earlier), as YYYY-MM."""
    return _month(_index(month) + by)


def span(first: str, last: str) -> list[str]:
    """Every month from `first` to `last` inclusive, oldest first."""
    return [_month(i) for i in range(_index(first), _index(last) + 1)]


def quarter_of(month: str) -> tuple[int, int]:
    year, part = (int(one) for one in month.split("-"))
    return year, (part - 1) // 3 + 1


def quarter_months(year: int, quarter: int) -> list[str]:
    start = (quarter - 1) * 3 + 1
    return [f"{year:04d}-{start + n:02d}" for n in range(3)]


def quarter_label(year: int, quarter: int) -> str:
    return f"Q{quarter} {year}"


@dataclass(frozen=True)
class Window:
    """A named stretch of months, and what it is honest to call it."""

    label: str
    months: list[str]
    complete: bool
    kind: str  # "quarter" | "quarter_to_date" | "month" | "custom"

    @property
    def first(self) -> str:
        return self.months[0]

    @property
    def last(self) -> str:
        return self.months[-1]

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "months": list(self.months),
                "first": self.first, "last": self.last,
                "complete": self.complete, "kind": self.kind}


@dataclass(frozen=True)
class Comparison:
    """Two windows a reader may legitimately put side by side."""

    current: Window
    prior: Window
    basis: str
    note: str = ""
    policy_version: str = PERIOD_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"current": self.current.to_dict(), "prior": self.prior.to_dict(),
                "basis": self.basis, "note": self.note,
                "policy_version": self.policy_version}


def latest_complete_quarter(available: list[str]) -> Window | None:
    """The most recent quarter for which the book holds all three months."""
    if not available:
        return None
    held = set(available)
    year, quarter = quarter_of(max(available))
    for _ in range(12):
        months = quarter_months(year, quarter)
        if all(one in held for one in months):
            return Window(quarter_label(year, quarter), months, True, "quarter")
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return None


def previous_quarter(window: Window) -> Window:
    year, quarter = quarter_of(window.first)
    quarter -= 1
    if quarter == 0:
        year, quarter = year - 1, 4
    return Window(quarter_label(year, quarter),
                  quarter_months(year, quarter), True, "quarter")


def quarter_to_date(available: list[str]) -> Window | None:
    """The months of the current quarter the book actually holds.

    None when the latest month completes its quarter — there is no
    quarter-to-date distinct from the quarter itself.
    """
    if not available:
        return None
    last = max(available)
    year, quarter = quarter_of(last)
    wanted = quarter_months(year, quarter)
    held = [one for one in wanted if one in set(available)]
    if len(held) == len(wanted):
        return None
    return Window(f"{quarter_label(year, quarter)} to date "
                  f"({held[0]}–{held[-1]})", held, False, "quarter_to_date")


def comparable_window(window: Window, available: list[str]) -> Window | None:
    """A window of the same length, immediately before `window`.

    A two-month quarter-to-date compared against a three-month quarter is not
    a comparison; it is two different questions with one label.
    """
    held = set(available)
    n = len(window.months)
    end = shift(window.first, -1)
    months = span(shift(end, -(n - 1)), end)
    if not all(one in held for one in months):
        return None
    return Window(f"the {n} months to {months[-1]}", months, True, "custom")


def default_comparison(available: list[str]) -> Comparison | None:
    """What "the latest complete quarter versus the previous one" resolves to.

    The default the contract asks for, computed from the data rather than
    asserted: with August 2026 as the latest month this is Q2 2026 against
    Q1 2026, and July-August is offered separately as a quarter-to-date.
    """
    current = latest_complete_quarter(available)
    if current is None:
        return None
    prior = previous_quarter(current)
    if not all(one in set(available) for one in prior.months):
        return None
    qtd = quarter_to_date(available)
    note = ""
    if qtd is not None:
        note = (f"{qtd.label} is available as a separate mode, compared with "
                f"the same number of months immediately before it. It is not "
                f"a quarter and is not labelled as one.")
    return Comparison(current, prior, "latest complete quarter", note)


def qtd_comparison(available: list[str]) -> Comparison | None:
    """Quarter-to-date against an equally long window, both named."""
    current = quarter_to_date(available)
    if current is None:
        return None
    prior = comparable_window(current, available)
    if prior is None:
        return None
    return Comparison(current, prior, "quarter to date",
                      f"{len(current.months)} months against the "
                      f"{len(prior.months)} immediately before them. Neither "
                      f"window is a complete quarter.")


def month_on_month(available: list[str]) -> Comparison | None:
    """The latest month against the one before it."""
    if len(available) < 2:
        return None
    ordered = sorted(available)
    last, before = ordered[-1], ordered[-2]
    return Comparison(Window(last, [last], True, "month"),
                      Window(before, [before], True, "month"),
                      "month on month")


@dataclass(frozen=True)
class Maturity:
    """Where the observable outcome window ends, and what that forbids."""

    latest_month: str
    horizon_months: int
    observation_cutoff: str
    #: Months whose outcome window is open at `latest_month`.
    censored: list[str] = field(default_factory=list)

    def matured(self, month: str) -> bool:
        return _index(month) <= _index(self.observation_cutoff)

    def to_dict(self) -> dict[str, Any]:
        return {"latest_month": self.latest_month,
                "horizon_months": self.horizon_months,
                "observation_cutoff": self.observation_cutoff,
                "censored_months": list(self.censored),
                "policy_version": PERIOD_POLICY_VERSION,
                "statement": (
                    f"A {self.horizon_months}-month outcome can only be "
                    f"observed for observations made on or before "
                    f"{self.observation_cutoff}. The "
                    f"{len(self.censored)} month(s) after it are censored: "
                    f"their outcome windows are still open, so a low measured "
                    f"default rate there is an artefact of the window, not a "
                    f"finding about the customers.")}


def maturity(available: list[str],
             horizon: int = OUTCOME_HORIZON_MONTHS) -> Maturity | None:
    """The latest observation month whose `horizon` outcome is fully seen."""
    if not available:
        return None
    last = max(available)
    cutoff = shift(last, -horizon)
    censored = [one for one in sorted(available) if _index(one) > _index(cutoff)]
    return Maturity(last, horizon, cutoff, censored)
