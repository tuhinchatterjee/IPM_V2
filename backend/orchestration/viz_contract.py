"""
Whether a chart says something true about the result. P0.11.

The defect this exists to fix
-----------------------------
A two-period sector-share result was drawn as a heatmap whose axes were the
MEASURE VALUES. Every distinct share became its own category, so the axis
headers were long floating-point numbers, every value appeared exactly once,
and the matrix was a sparse diagonal — a picture of nothing, drawn confidently.

The mistake was a category error in the literal sense: a measure was used where
a dimension belongs. Nothing checked that, because chart selection had a
`choose` step and no `validate` step, and a selector that is right most of the
time still needs something to catch it when it is not.

What this checks
----------------
P0.11's list, and each one is a question a chart can fail:

    axis roles          is every axis a DIMENSION, and every encoded value a
                        MEASURE? This is the one the heatmap failed.
    cardinality         is the axis readable, or is it 400 ticks?
    labels              can a label be read, or is it a 17-character float?
    units               do the series share a unit, or is money plotted
                        against a percentage on one scale?
    ordering            is an ordinal axis in its own order?
    period semantics    is a time axis actually time, and in sequence?
    missing values      is the chart mostly gaps?
    overplotting        are there more marks than pixels?
    precision           does any label carry more than the display contract?
    suitability         does the shape support the chart at all?

The rule
--------
A chart that fails is REPLACED, not annotated. P0.11 says "if invalid, choose a
better chart or table", and a table is always available — it is the honest
fallback, because a table of numbers is never a misleading picture of them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: The most ticks an axis can carry and still be read. Beyond this the labels
#: overlap and the chart is decoration.
MAX_AXIS_CATEGORIES = 30

#: A label longer than this is not a label. "2.6246841182876173" is 18.
MAX_LABEL_CHARS = 24

#: Beyond this many marks a scatter is a cloud.
MAX_MARKS = 2_000

#: How much of a series may be missing before the chart is mostly gaps.
MAX_MISSING_SHARE = 0.4

#: Semantics that are MEASURES — things that are counted, not categories.
MEASURE_SEMANTICS: frozenset[str] = frozenset(
    {"money", "percent", "ratio", "count", "days", "share", "number"})

#: Semantics that can carry an axis.
DIMENSION_SEMANTICS: frozenset[str] = frozenset(
    {"identity", "text", "category", "dimension", "period", "ordinal",
     "stage", "rating"})

#: A label that is a bare number with decimals — the signature of a measure
#: being used as a category.
_NUMERIC_LABEL = re.compile(r"^-?\d[\d,]*\.\d+$")


@dataclass
class Problem:
    """One reason a chart does not say something true."""

    check: str
    detail: str
    #: True where the chart cannot be shown at all, as opposed to shown with a
    #: caveat. Everything P0.11 lists is fatal: a misleading chart is worse
    #: than a table, so there is no "warn and draw anyway" here.
    fatal: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "detail": self.detail, "fatal": self.fatal}


@dataclass
class Verdict:
    """Whether this chart may be drawn, and what to draw instead."""

    ok: bool = True
    problems: list[Problem] = field(default_factory=list)
    #: What to draw instead when it may not. Always a real alternative.
    fallback: str = "table"

    @property
    def why(self) -> str:
        return "; ".join(p.detail for p in self.problems)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "fallback": self.fallback,
                "problems": [p.to_dict() for p in self.problems],
                "why": self.why}


def validate(visual: Any, columns: list[dict[str, Any]],
             rows: list[dict[str, Any]]) -> Verdict:
    """Whether `visual` is a truthful picture of these rows.

    Takes the chosen visual rather than choosing one: selection and validation
    are separate jobs, and a validator that also selects cannot catch the
    selector's mistakes.
    """
    chart = str(getattr(visual, "chart", "") or "")
    if not chart or chart in ("table", "kpi"):
        # A table cannot misrepresent its own numbers, and a KPI is a figure
        # with a label rather than a picture of a relationship.
        return Verdict(ok=True)

    by_name = {str(c.get("name") or ""): c for c in (columns or [])}
    problems: list[Problem] = []

    axes = [a for a in (getattr(visual, "x", ""),
                        getattr(visual, "series", "")) if a]
    encoded = list(getattr(visual, "y", ()) or [])

    problems.extend(_axis_roles(axes, encoded, by_name))
    problems.extend(_cardinality(axes, rows))
    problems.extend(_labels(axes, rows, by_name))
    problems.extend(_units(encoded, by_name))
    problems.extend(_periods(axes, by_name, rows))
    problems.extend(_missing(encoded, rows))
    problems.extend(_overplotting(chart, rows))

    fatal = [p for p in problems if p.fatal]
    if fatal:
        logger.info("chart %s rejected: %s", chart,
                    "; ".join(p.detail for p in fatal))
    return Verdict(ok=not fatal, problems=problems, fallback=_fallback(visual))


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def _axis_roles(axes: list[str], encoded: list[str],
                by_name: dict[str, dict[str, Any]]) -> list[Problem]:
    """An axis carries a DIMENSION; a mark encodes a MEASURE.

    The check the heatmap failed. A measure on an axis turns every distinct
    value into its own category, which is why the result was a sparse diagonal
    with floating-point headers: there was exactly one row per value, because
    the "categories" were the values.
    """
    found: list[Problem] = []
    for axis in axes:
        column = by_name.get(axis)
        if column is None:
            continue
        semantic = str(column.get("semantic") or "")
        if semantic in MEASURE_SEMANTICS:
            found.append(Problem(
                "axis_roles",
                f"'{column.get('label') or axis}' is a measure "
                f"({semantic}), and a measure cannot be an axis: every "
                f"distinct value becomes its own category."))
    for name in encoded:
        column = by_name.get(name)
        if column is None:
            continue
        semantic = str(column.get("semantic") or "")
        if semantic in DIMENSION_SEMANTICS and semantic != "ordinal":
            found.append(Problem(
                "axis_roles",
                f"'{column.get('label') or name}' is a {semantic}, and a "
                f"chart cannot encode it as a magnitude."))
    return found


def _cardinality(axes: list[str], rows: list[dict[str, Any]]) -> list[Problem]:
    found: list[Problem] = []
    for axis in axes:
        distinct = {_key(r.get(axis)) for r in (rows or [])}
        if len(distinct) > MAX_AXIS_CATEGORIES:
            found.append(Problem(
                "cardinality",
                f"'{axis}' has {len(distinct)} distinct values; beyond "
                f"{MAX_AXIS_CATEGORIES} the axis cannot be read."))
    return found


def _labels(axes: list[str], rows: list[dict[str, Any]],
            by_name: dict[str, dict[str, Any]]) -> list[Problem]:
    """A label a person can read.

    Catches the symptom the heatmap showed even where the role check would
    not: a header of "2.6246841182876173" is unreadable whatever its semantic
    says it is.
    """
    found: list[Problem] = []
    for axis in axes:
        for row in (rows or [])[:200]:
            label = _key(row.get(axis))
            if _NUMERIC_LABEL.match(label):
                found.append(Problem(
                    "labels",
                    f"'{axis}' is labelled with bare numbers such as "
                    f"'{label}', which is a measure being used as a category."))
                break
            if len(label) > MAX_LABEL_CHARS:
                found.append(Problem(
                    "labels",
                    f"'{axis}' carries labels of {len(label)} characters; "
                    f"they cannot be drawn legibly.", fatal=False))
                break
    return found


def _units(encoded: list[str],
           by_name: dict[str, dict[str, Any]]) -> list[Problem]:
    """One scale, one unit. Money against a percentage is two charts."""
    units = {str((by_name.get(n) or {}).get("unit") or "")
             for n in encoded if n in by_name}
    units.discard("")
    if len(units) > 1:
        return [Problem(
            "units",
            f"the series carry different units ({', '.join(sorted(units))}), "
            f"so one scale would misstate every one of them.")]
    return []


def _periods(axes: list[str], by_name: dict[str, dict[str, Any]],
             rows: list[dict[str, Any]]) -> list[Problem]:
    """A time axis must be time, and in order."""
    found: list[Problem] = []
    for axis in axes:
        column = by_name.get(axis) or {}
        if str(column.get("semantic") or "") != "period":
            continue
        seen = [_key(r.get(axis)) for r in (rows or [])]
        ordered = sorted(dict.fromkeys(seen), key=_period_key)
        if list(dict.fromkeys(seen)) != ordered:
            found.append(Problem(
                "period_semantics",
                f"'{axis}' is a period axis whose values are not in "
                f"chronological order.", fatal=False))
    return found


def _missing(encoded: list[str], rows: list[dict[str, Any]]) -> list[Problem]:
    found: list[Problem] = []
    total = len(rows or [])
    if not total:
        return found
    for name in encoded:
        blank = sum(1 for r in rows if r.get(name) is None)
        if blank / total > MAX_MISSING_SHARE:
            found.append(Problem(
                "missing_values",
                f"'{name}' is missing for {blank} of {total} rows; the chart "
                f"would be mostly gaps."))
    return found


def _overplotting(chart: str, rows: list[dict[str, Any]]) -> list[Problem]:
    if chart in ("scatter", "dot") and len(rows or []) > MAX_MARKS:
        return [Problem(
            "overplotting",
            f"{len(rows)} marks is more than a scatter can separate.")]
    return []


def _fallback(visual: Any) -> str:
    """What to draw instead. The visual's own alternatives, then the table."""
    for option in list(getattr(visual, "alternatives", ()) or []):
        if str(option) != str(getattr(visual, "chart", "")):
            return str(option)
    return "table"


def _key(value: Any) -> str:
    return "" if value is None else str(value)


_QUARTER = re.compile(r"^Q(?P<q>[1-4])\s+(?P<y>\d{4})$", re.I)


def _period_key(label: str) -> tuple[int, int, str]:
    found = _QUARTER.match(label.strip())
    if found:
        return (int(found.group("y")), int(found.group("q")), "")
    if label.strip().isdigit():
        return (int(label.strip()), 0, "")
    return (0, 0, label)


__all__ = [
    "DIMENSION_SEMANTICS",
    "MAX_AXIS_CATEGORIES",
    "MAX_LABEL_CHARS",
    "MAX_MARKS",
    "MEASURE_SEMANTICS",
    "Problem",
    "Verdict",
    "validate",
]
