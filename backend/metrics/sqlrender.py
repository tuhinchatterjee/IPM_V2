"""Writing a metric's SQL over governed dataset names.

Two SQL strings exist for every metric, and they are not the same statement:

``compiled``
    What DuckDB executes, from `backend.runtime.compiler`. It reads
    `read_parquet('data/analytics/portfolio_facility/…')` because that is where
    this deployment's Parquet layer actually is, and it is the truth about
    execution.

``rendered``
    What this module writes: the same calculation over the GOVERNED NAMES —
    `FROM portfolio_facility WHERE period = ?`. It is what a credit-risk
    professional reads to check the logic, and it is the shape a model is
    asked to write in, so the two can be reconciled term by term.

Why the second exists at all
-----------------------------
Because the first cannot be reviewed and must not be validated as if a person
or a model had written it. `sqlguard` refuses `read_parquet` — correctly, since
a model calling it is reaching for the filesystem — and the compiled statement
calls it on every metric. Feeding the compiled statement through the guard
would either fail every metric or require an exception that the guard's whole
value depends on not having.

So the artefact carries the rendered SQL as the code a person approves, the
compiled SQL beside it as the statement that will run, and says which is which.

This module never runs anything and never sees data. Values are `?`, exactly as
they are in the compiled statement, for exactly the same reason.
"""

from __future__ import annotations

from typing import Any

RENDER_VERSION = "3.0.0"

#: How each governed aggregation is written in SQL.
_AGGREGATE_SQL = {
    "sum": "SUM({column})",
    "count": "COUNT({column})",
    "count_distinct": "COUNT(DISTINCT {column})",
    "avg": "AVG({column})",
    "min": "MIN({column})",
    "max": "MAX({column})",
    "median": "MEDIAN({column})",
    "stddev": "STDDEV({column})",
}

_COMPARISON_SQL = {
    "=": "{f} = ?", "!=": "{f} <> ?", "<": "{f} < ?", "<=": "{f} <= ?",
    ">": "{f} > ?", ">=": "{f} >= ?",
    "in": "{f} IN ({placeholders})", "not_in": "{f} NOT IN ({placeholders})",
    "between": "{f} BETWEEN ? AND ?",
    "is_null": "{f} IS NULL", "is_not_null": "{f} IS NOT NULL",
    "contains": "{f} LIKE ?", "starts_with": "{f} LIKE ?",
    "ends_with": "{f} LIKE ?",
}

_COMBINE_SQL = {"add": " + ", "subtract": " - ", "multiply": " * ",
                "divide": " / "}


def _condition(condition: Any) -> str:
    template = _COMPARISON_SQL.get(condition.op)
    if template is None:
        return f"/* unsupported comparison {condition.op} */ TRUE"
    if condition.op in ("in", "not_in"):
        values = condition.value if isinstance(condition.value, (list, tuple)) else []
        placeholders = ", ".join("?" for _ in values) or "?"
        return template.format(f=condition.field, placeholders=placeholders)
    return template.format(f=condition.field)


def _term(term: Any) -> str:
    """One term as a conditional aggregate, exactly as the engine computes it."""
    column = term.field or term.weight_field or "*"
    if term.aggregate == "weighted_avg":
        body = (f"SUM({term.field} * {term.weight_field}) / "
                f"SUM({term.weight_field})")
    elif term.aggregate == "count" and not term.field:
        body = "COUNT(*)"
    else:
        body = _AGGREGATE_SQL.get(term.aggregate, "SUM({column})").format(
            column=column)
    if term.where:
        clauses = " AND ".join(_condition(c) for c in term.where)
        return f"{body} FILTER (WHERE {clauses})"
    return body


def _side(side: Any) -> str:
    if not side or not side.terms:
        return ""
    if len(side.terms) == 1 or side.combine == "first":
        return _term(side.terms[0])
    joiner = _COMBINE_SQL.get(side.combine, " + ")
    return "(" + joiner.join(_term(t) for t in side.terms) + ")"


def formula_sql(formula: Any, *, dataset: str = "", alias: str = "metric",
                period_placeholder: bool = True) -> str:
    """One single-dataset formula as a readable SELECT over governed names."""
    dataset = dataset or (formula.datasets[0] if formula.datasets else "")
    top = _side(formula.numerator)
    bottom = _side(formula.denominator) if formula.denominator else ""

    lines: list[str] = ["SELECT"]
    parts: list[str] = []
    for term in formula.terms:
        parts.append(f"  {_term(term)} AS {term.id}")
    if bottom:
        scale = ("" if formula.scale == 1
                 else f" * {formula.scale:g}")
        parts.append(f"  ({top}) / NULLIF({bottom}, 0){scale} AS {alias}")
    else:
        scale = "" if formula.scale == 1 else f" * {formula.scale:g}"
        parts.append(f"  ({top}){scale} AS {alias}")
    lines.append(",\n".join(parts))
    lines.append(f"FROM {dataset}")
    if period_placeholder:
        lines.append("WHERE period = ?")
    return "\n".join(lines)


def composite_sql(composite: Any, *, resolver: Any = None) -> str:
    """A composite as one readable statement: a CTE per side, then the
    arithmetic.

    A leg naming a governed metric is expanded through `resolver` so the
    statement shows the calculation rather than the metric's id — a person
    reviewing "watchlist exposure over total exposure" needs to see what
    watchlist exposure IS, not be told to look it up.
    """
    blocks: list[str] = []
    names: list[str] = []
    for leg, side in ((composite.numerator, "numerator"),
                      (composite.denominator, "denominator")):
        if leg is None:
            continue
        formula = leg.formula
        label = leg.label or leg.id
        if formula is None and leg.metric_id and resolver is not None:
            try:
                formula = resolver(leg.metric_id).formula
            except Exception:  # noqa: BLE001 - shown as a reference instead
                formula = None
        name = leg.id or side
        names.append(name)
        if formula is None:
            blocks.append(
                f"  -- {label}: the governed metric {leg.metric_id}\n"
                f"  {name} AS (SELECT NULL AS value)")
            continue
        at = (f"  -- {label}, {leg.period_offset} period(s) before the one "
              f"shown\n" if leg.period_offset else f"  -- {label}\n")
        body = formula_sql(formula, alias="value").replace("\n", "\n    ")
        blocks.append(f"{at}  {name} AS (\n    {body}\n  )")

    if not blocks:
        return ""
    head = "WITH\n" + ",\n".join(blocks)

    scale = "" if composite.scale == 1 else f" * {composite.scale:g}"
    if len(names) == 1:
        return f"{head}\nSELECT {names[0]}.value{scale} AS metric FROM {names[0]}"

    top, bottom = names[0], names[1]
    expression = {
        "ratio": f"{top}.value / NULLIF({bottom}.value, 0)",
        "growth": f"({top}.value / NULLIF({bottom}.value, 0)) - 1",
        "difference": f"{top}.value - {bottom}.value",
        "product": f"{top}.value * {bottom}.value",
    }.get(composite.operation, f"{top}.value / NULLIF({bottom}.value, 0)")
    return (f"{head}\nSELECT ({expression}){scale} AS metric\n"
            f"FROM {top} CROSS JOIN {bottom}")


def render(program: Any, *, resolver: Any = None) -> str:
    """The readable SQL for whichever kind of program this is."""
    if program is None:
        return ""
    if hasattr(program, "legs"):
        return composite_sql(program, resolver=resolver)
    return formula_sql(program)


__all__ = ["RENDER_VERSION", "composite_sql", "formula_sql", "render"]
