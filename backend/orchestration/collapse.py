"""A comparison that cannot come out non-zero. Part 12.

The defect
----------
    "Which borrowers had a PD increase and were downgraded in Q2 2026?"

runs. Every condition reaches the FILTER. The query succeeds. The plan is
faithful to the question. It returns **no borrowers**, and a reader takes that
as a finding: nothing on this book both deteriorated and was downgraded.

That is not what happened. `customer_ratings` is an ANNUAL dataset whose latest
completed cycle is 2025. Q1 2026 and Q2 2026 both resolve, correctly and by
design, to that same 2025 cycle — so the internal grade on both sides of the
quarter-on-quarter comparison is *the same row*, the difference is identically
zero for every borrower on the book, and a condition asking for a change in it
can never hold. The empty result is a fact about the calendar, not about the
book.

The compiler already knows this can happen; its own comment on
`completed_year_of_quarter` says the alignment stops a quarter reading a cycle
that has not finished, at the cost of "no error and no movement, because both
ends of a year-on-year comparison land on the same cycle". What was missing is
anybody saying so on the way out.

What this does
--------------
Reads the finished plan and reports which movement columns are structurally
incapable of being non-zero: a change derived from a field that reaches the
plan through an as-of join whose temporal alignment maps BOTH endpoints of the
comparison onto the same source cycle.

It computes nothing about the borrowers. It is a statement about the plan, made
before the plan runs, so an empty answer can say why it is empty.

Not a defect to be fixed by widening the comparison
----------------------------------------------------
The obvious "fix" — let the quarter read the 2026 cycle — is look-ahead: it
would answer a Q2 2026 question with a rating cycle that had not finished at
Q2 2026, which is worse than saying nothing. The other obvious fix — compare
across a year instead of a quarter — silently answers a different question.
So this says what it can and cannot do, and names the field that DOES record
the movement where the catalogue publishes one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

COLLAPSE_VERSION = "1.0.0"

#: The alignment rules that map a fine period onto a coarser cycle. `identity`
#: does not, so it cannot collapse anything.
_COARSENING = {"year_of_quarter", "completed_year_of_quarter"}

#: The year at the end of a governed period label — "Q2 2026" -> 2026.
_YEAR = re.compile(r"(\d{4})\s*$")


def _aligned(period: str, rule: str) -> str:
    """Which source cycle this period reads under this rule.

    The same arithmetic the compiler does, in Python, so the check and the
    query cannot disagree about which cycle a quarter lands on.
    """
    found = _YEAR.search(str(period or ""))
    if not found:
        return str(period or "")
    year = int(found.group(1))
    if rule == "completed_year_of_quarter":
        return str(year - 1)
    if rule == "year_of_quarter":
        return str(year)
    return str(period)


@dataclass(frozen=True)
class Collapsed:
    """One movement the plan cannot measure, and why."""

    #: The derived column: `customer_ratings_internal_grade_change`.
    column: str
    #: The dataset the underlying field came from.
    dataset: str
    #: The two periods asked for, and the one cycle they both read.
    opening: str
    closing: str
    cycle: str
    #: A field on the same dataset that DOES record the movement, when the
    #: catalogue publishes one. Empty when it does not.
    instead: str = ""

    @property
    def says(self) -> str:
        said = (
            f"{self.dataset} is published once a cycle, and both {self.opening} "
            f"and {self.closing} read the {self.cycle} cycle — the same rows on "
            "both sides of the comparison. A change measured across them is "
            "zero for every borrower by construction, so this condition cannot "
            "be tested between these two dates.")
        if self.instead:
            said += (f" The {self.dataset} cycle does record the movement "
                     f"itself, in {self.instead}; asking for that reads what "
                     "actually happened rather than a difference that cannot "
                     "exist.")
        return said

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "dataset": self.dataset,
                "opening": self.opening, "closing": self.closing,
                "cycle": self.cycle, "instead": self.instead,
                "says": self.says}


@dataclass
class Finding:
    """Every collapsed comparison in one plan."""

    collapsed: list[Collapsed] = field(default_factory=list)
    version: str = COLLAPSE_VERSION

    @property
    def any(self) -> bool:
        return bool(self.collapsed)

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(entry.column for entry in self.collapsed)

    def sentence(self) -> str:
        if not self.collapsed:
            return ""
        return " ".join(entry.says for entry in self.collapsed)

    def to_dict(self) -> dict[str, Any]:
        return {"collapsed": [c.to_dict() for c in self.collapsed],
                "sentence": self.sentence(), "version": self.version}


# ------------------------------------------------------------ reading a plan


def _operations(plan: Any) -> list[dict[str, Any]]:
    if isinstance(plan, dict):
        return list(plan.get("operations") or [])
    return list(getattr(plan, "operations", None) or [])


def _params(op: Any) -> dict[str, Any]:
    if isinstance(op, dict):
        return dict(op.get("params") or {})
    return dict(getattr(op, "params", None) or {})


def _get(op: Any, name: str, default: Any = None) -> Any:
    if isinstance(op, dict):
        return op.get(name, default)
    return getattr(op, name, default)


def _prefixed_columns(plan: Any) -> dict[str, tuple[str, str]]:
    """Column prefix -> (dataset, alignment rule) for every as-of join.

    An as-of join renames the right-hand columns with a prefix, so a derived
    change on `customer_ratings_internal_grade` can be traced back to the
    `customer_ratings` scan it came from and the alignment that placed it.
    """
    scans: dict[str, str] = {}
    rules: dict[str, str] = {}
    found: dict[str, tuple[str, str]] = {}
    for op in _operations(plan):
        kind = str(_get(op, "op", ""))
        params = _params(op)
        if kind == "SCAN":
            scans[str(_get(op, "id", ""))] = str(params.get("dataset") or "")
        elif kind == "TEMPORAL_ALIGN":
            rules[str(_get(op, "id", ""))] = str(params.get("rule") or "")
        elif kind == "ASOF_JOIN":
            inputs = list(_get(op, "inputs", []) or [])
            prefix = str(params.get("right_prefix") or "")
            if not prefix or len(inputs) < 2:
                continue
            rule = rules.get(str(inputs[0]), "")
            dataset = scans.get(str(inputs[1]), "")
            if rule in _COARSENING and dataset:
                found[prefix] = (dataset, rule)
    return found


def _changes(plan: Any) -> dict[str, tuple[str, str]]:
    """Derived change column -> the two columns it subtracts."""
    out: dict[str, tuple[str, str]] = {}
    for op in _operations(plan):
        if str(_get(op, "op", "")) != "DERIVE":
            continue
        for column in _params(op).get("columns") or []:
            expression = column.get("expression") or {}
            if expression.get("function") != "subtract":
                continue
            args = list(expression.get("args") or [])
            if len(args) == 2 and all(isinstance(a, str) for a in args):
                out[str(column.get("as") or "")] = (str(args[0]), str(args[1]))
    return out


def _movement_periods(plan: Any) -> tuple[str, str]:
    """The two reporting periods the plan is comparing.

    Read from the SCANs rather than from the request, because the plan is what
    actually ran and a period the request carried but the plan ignored would
    make this check answer about the wrong pair of dates.
    """
    opening = closing = ""
    for op in _operations(plan):
        if str(_get(op, "op", "")) != "SCAN":
            continue
        period = str(_params(op).get("period") or "")
        if not period:
            continue
        node = str(_get(op, "id", ""))
        if node.startswith("opening") and not opening:
            opening = period
        elif node.startswith("closing") and not closing:
            closing = period
    return opening, closing


#: Fields that record a movement AS A FACT on the cycle, rather than as a
#: difference between two of them. Named per dataset so the suggestion is a
#: column the catalogue actually publishes rather than a guess.
_RECORDS_MOVEMENT: dict[str, tuple[str, ...]] = {
    "customer_ratings": ("notches_moved", "rating_action",
                         "prior_internal_grade"),
}


def _instead(dataset: str, columns: set[str]) -> str:
    for candidate in _RECORDS_MOVEMENT.get(dataset, ()):
        if not columns or candidate in columns:
            return candidate
    return ""


def _published(dataset: str) -> set[str]:
    """What the catalogue publishes for this dataset, when it can be read."""
    try:
        from backend.data_access import get_catalog

        found = get_catalog().dataset(dataset)
    except Exception:  # noqa: BLE001 - a suggestion is not worth an error
        return set()
    fields = getattr(found, "fields", None) or getattr(found, "columns", None)
    if not fields:
        return set()
    return {str(getattr(f, "name", f)) for f in fields}


def inspect(plan: Any) -> Finding:
    """Which movements in this plan cannot come out non-zero, and why.

    Reads the plan only. Nothing here touches the book, so it can be called
    before the query runs — which is the point: an empty answer should be able
    to say why it is empty rather than leaving the reader to conclude that
    nothing happened.
    """
    found = Finding()
    prefixes = _prefixed_columns(plan)
    if not prefixes:
        return found
    opening, closing = _movement_periods(plan)
    if not opening or not closing or opening == closing:
        # No movement to collapse, or the plan is not comparing two dates.
        return found

    for column, (left, right) in _changes(plan).items():
        for prefix, (dataset, rule) in prefixes.items():
            # The closing side carries its own prefix on top of the join's, so
            # match on the underlying column that both sides share.
            if prefix not in left and prefix not in right:
                continue
            if _aligned(opening, rule) != _aligned(closing, rule):
                continue
            found.collapsed.append(Collapsed(
                column=column, dataset=dataset,
                opening=opening, closing=closing,
                cycle=_aligned(closing, rule),
                instead=_instead(dataset, _published(dataset))))
            break
    return found


__all__ = ["COLLAPSE_VERSION", "Collapsed", "Finding", "inspect"]
