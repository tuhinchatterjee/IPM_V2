"""Running a metric, and showing every step that produced the number.

The compilation is deliberately one query. A ratio whose numerator and
denominator are fetched separately is two chances to filter one side and not
the other, and the error shows up as a share nobody can reconcile rather than
as a failure. So every term becomes a conditional aggregate — `sum_where`,
`count_where` — over the same scan, which the analytical IR already supports
for exactly this reason, and the whole metric is one row of one result.

Everything after that row is arithmetic in Python, in the open: term values
combine into a numerator, the denominator likewise, and the final operation
divides and scales. That is what makes the verification workspace possible.
The trace is not a description of the calculation; it is the calculation, with
its intermediate values kept.

Row counts come back per term as well as values, because "the numerator is
zero" and "the numerator matched no rows" are different problems and only one
of them is a formula error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from backend.metrics.formula import Formula, FormulaError, Side, Term
from backend.runtime import ir

EXECUTION_VERSION = "1.0.0"

#: How many rows a verification sample may inspect. Enough to show somebody
#: the inclusion logic; not enough to be an export route.
SAMPLE_ROWS = 25


class MetricUnavailable(RuntimeError):
    """The metric is well formed but cannot be computed on this data."""


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def _predicate(term: Term) -> list[dict[str, Any]]:
    """The term's filter in the IR's own shape: a list of clauses, ANDed."""
    return [{"column": c.field, "op": c.op, "value": c.value}
            for c in term.where]


def _measure(term: Term) -> dict[str, Any]:
    """One term as an aggregate the compiler can write.

    A filtered term becomes a conditional aggregate rather than a filtered
    scan, so that all of a metric's terms — however differently filtered — are
    counted over one pass of the same rows.
    """
    where = _predicate(term)
    column = term.field or term.weight_field

    if term.aggregate == "count" and not term.field:
        return ({"function": "count_where", "as": term.id, "where": where}
                if where else {"function": "count", "as": term.id})
    if where and term.aggregate == "sum":
        return {"column": column, "function": "sum_where", "as": term.id,
                "where": where}
    if where and term.aggregate in ("count", "count_distinct"):
        return {"column": column, "function": "count_where", "as": term.id,
                "where": where}
    if where:
        # avg, min, max, median, stddev and weighted_avg have no conditional
        # form in the IR. Rather than approximate one, the term is refused with
        # the reason — an average computed over the wrong rows is worse than
        # no average.
        raise FormulaError(
            f"Term {term.id}: a filter on a {term.aggregate} is not something "
            "the engine can compute in one pass with the other terms. Use a "
            "sum or a count here, or make the filter part of the metric's own "
            "scope so it applies to every term.")

    spec: dict[str, Any] = {"column": column, "function": term.aggregate,
                            "as": term.id}
    if term.aggregate == "count" and not column:
        spec.pop("column", None)
    if term.aggregate == "weighted_avg":
        spec["column"] = term.field
        spec["weight"] = term.weight_field
    return spec


def compile_metric(formula: Formula, *, period: str = "",
                   scope: tuple[Any, ...] = ()) -> ir.AnalyticalPlan:
    """One plan, one scan, one row out.

    `scope` is the metric's own filter — the portfolio, the segment — applied
    to every term alike. It is a FILTER rather than a per-term condition
    because that is what "the whole metric is about the retail book" means.
    """
    datasets = formula.datasets
    if not datasets:
        raise FormulaError("This metric names no dataset to read.")
    dataset = datasets[0]

    steps: list[ir.Operation] = []
    scan_params: dict[str, Any] = {"dataset": dataset}
    if period:
        scan_params["period"] = period
    steps.append(ir.Operation(id="scan", op=ir.OpType.SCAN,
                              params=scan_params,
                              label=f"Read {dataset}"))
    source = "scan"

    if scope:
        steps.append(ir.Operation(
            id="scope", op=ir.OpType.FILTER, inputs=("scan",),
            params={"where": [{"column": c.field, "op": c.op, "value": c.value}
                              for c in scope]},
            label="Apply the metric's scope"))
        source = "scope"

    measures = [_measure(t) for t in formula.terms]
    # Every metric also reports how many rows it looked at. Without it, a
    # numerator of zero cannot be told apart from a population of zero.
    measures.append({"function": "count", "as": "_rows"})
    steps.append(ir.Operation(
        id="measure", op=ir.OpType.AGGREGATE, inputs=(source,),
        params={"measures": measures},
        label="Measure every term over the same rows"))

    return ir.AnalyticalPlan(
        objective=formula.describe(), operations=steps, output="measure",
        meta={"metric_formula": formula.to_dict(), "period": period})


# ---------------------------------------------------------------------------
# The trace
# ---------------------------------------------------------------------------


@dataclass
class TermValue:
    term: Term
    value: float | None
    rows: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.term.id, "label": self.term.label,
                "describes": self.term.describe(),
                "dataset": self.term.dataset,
                "aggregate": self.term.aggregate, "field": self.term.field,
                "filters": [c.describe() for c in self.term.where],
                "value": self.value, "rows": self.rows}


@dataclass
class SideValue:
    label: str
    terms: list[TermValue] = field(default_factory=list)
    combine: str = "add"
    value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "combine": self.combine,
                "value": self.value,
                "terms": [t.to_dict() for t in self.terms]}


@dataclass
class Calculation:
    """One computed metric, and everything that went into it."""

    value: float | None
    formula: Formula
    numerator: SideValue | None = None
    denominator: SideValue | None = None
    rows_considered: int = 0
    period: str = ""
    dataset: str = ""
    #: The SQL that produced it, for the audit-minded reader.
    sql: str = ""
    run_id: str = ""
    warnings: list[str] = field(default_factory=list)
    #: Why there is no value, when there is none.
    unavailable: str = ""

    @property
    def final_expression(self) -> str:
        if self.denominator is None or self.numerator is None:
            return f"{_fmt(self.value)}"
        top = _fmt(self.numerator.value)
        bottom = _fmt(self.denominator.value)
        tail = (f" × {self.formula.scale:g}" if self.formula.scale != 1 else "")
        return f"{top} / {bottom}{tail} = {_fmt(self.value)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "formula": self.formula.to_dict(),
            "numerator": self.numerator.to_dict() if self.numerator else None,
            "denominator": (self.denominator.to_dict()
                            if self.denominator else None),
            "final": self.final_expression,
            "rows_considered": self.rows_considered,
            "period": self.period, "dataset": self.dataset,
            "sql": self.sql, "run_id": self.run_id,
            "warnings": list(self.warnings),
            "unavailable": self.unavailable,
        }


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        return f"{value:,.0f}"
    if abs(value - round(value)) < 1e-9:
        return f"{value:,.0f}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _combine(values: list[float | None], how: str) -> float | None:
    """Fold a side's terms. A missing term makes the side missing.

    Treating a null term as zero is how a metric quietly reports a smaller
    numerator than it should when a filter matched nothing that ran.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None
    if how == "first":
        return present[0]
    if how == "add":
        return math.fsum(present)
    if how == "subtract":
        total = present[0]
        for value in present[1:]:
            total -= value
        return total
    if how == "multiply":
        total = present[0]
        for value in present[1:]:
            total *= value
        return total
    if how == "divide":
        if len(present) < 2 or present[1] == 0:
            return None
        return present[0] / present[1]
    return None


def _side(side: Side, row: dict[str, Any], label: str) -> SideValue:
    out = SideValue(label=label, combine=side.combine)
    for term in side.terms:
        raw = row.get(term.id)
        value = None if raw is None else float(raw)
        out.terms.append(TermValue(term=term, value=value))
    out.value = _combine([t.value for t in out.terms], side.combine)
    return out


def evaluate(formula: Formula, row: dict[str, Any], *,
             rows_considered: int = 0) -> Calculation:
    """Arithmetic over one result row, in the open.

    Separated from execution so it can be tested against a dictionary, and so
    the verification workspace can re-run the arithmetic without re-running
    the query.
    """
    top = _side(formula.numerator, row, "Numerator") if (
        formula.numerator.terms) else None
    bottom = (_side(formula.denominator, row, "Denominator")
              if formula.denominator and formula.denominator.terms else None)

    calculation = Calculation(
        value=None, formula=formula, numerator=top, denominator=bottom,
        rows_considered=rows_considered,
        dataset=formula.datasets[0] if formula.datasets else "")

    if top is None or top.value is None:
        calculation.unavailable = (
            "The numerator could not be computed: no rows matched its terms.")
        return calculation

    if bottom is None:
        calculation.value = top.value * formula.scale if (
            formula.scale != 1) else top.value
        return calculation

    if bottom.value is None:
        calculation.unavailable = (
            "The denominator could not be computed: no rows matched its "
            "terms.")
        return calculation
    if bottom.value == 0:
        # Not an error and not zero. A share of nothing has no value, and
        # reporting 0% would be a claim the data does not support.
        calculation.unavailable = (
            "The denominator is zero for this period, so the metric has no "
            "value. That is a fact about the population, not a failure.")
        return calculation

    calculation.value = (top.value / bottom.value) * formula.scale
    return calculation


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def run(formula: Formula, *, period: str = "",
        scope: tuple[Any, ...] = (), question: str = "") -> Calculation:
    """Compile, validate, execute, and show the working.

    Goes through `runtime.executor.execute`, which is the single entry point
    every other analysis in CreditProbe uses. A metric that ran its own SQL
    would be a second path with its own bugs and its own permissions.
    """
    from backend.runtime.executor import execute

    plan = compile_metric(formula, period=period, scope=scope)
    result = execute(plan, question=question or formula.describe(),
                     intent="metric")
    if not result.rows:
        calculation = Calculation(
            value=None, formula=formula, period=period,
            dataset=formula.datasets[0] if formula.datasets else "")
        calculation.unavailable = (
            "The query returned no rows at all, which usually means the "
            "dataset has nothing for this period.")
        return calculation

    row = dict(result.rows[0])
    calculation = evaluate(formula, row,
                           rows_considered=int(row.get("_rows") or 0))
    calculation.period = period
    calculation.run_id = result.run_id
    calculation.sql = result.query.sql if result.query else ""
    calculation.warnings = list(result.warnings)
    return calculation


def sample(formula: Formula, *, period: str = "",
           scope: tuple[Any, ...] = (), limit: int = SAMPLE_ROWS
           ) -> dict[str, Any]:
    """A handful of underlying rows, with the inclusion logic worked out.

    §10.4's record-level proxy. What makes it useful is not the rows — it is
    the columns beside them saying, for each term, whether this row was
    counted. That is how somebody checks the filter means what they meant.
    """
    from backend.runtime.executor import execute

    datasets = formula.datasets
    if not datasets:
        raise FormulaError("This metric names no dataset to read.")

    wanted: list[str] = []
    for term in formula.terms:
        for name in (term.field, term.weight_field):
            if name and name not in wanted:
                wanted.append(name)
        for condition in term.where:
            if condition.field and condition.field not in wanted:
                wanted.append(condition.field)

    steps: list[ir.Operation] = []
    scan: dict[str, Any] = {"dataset": datasets[0]}
    if period:
        scan["period"] = period
    steps.append(ir.Operation(id="scan", op=ir.OpType.SCAN, params=scan))
    source = "scan"
    if scope:
        steps.append(ir.Operation(
            id="scope", op=ir.OpType.FILTER, inputs=("scan",),
            params={"where": [{"column": c.field, "op": c.op, "value": c.value}
                              for c in scope]}))
        source = "scope"
    if wanted:
        steps.append(ir.Operation(
            id="pick", op=ir.OpType.SELECT, inputs=(source,),
            params={"columns": wanted}))
        source = "pick"
    steps.append(ir.Operation(
        id="few", op=ir.OpType.LIMIT, inputs=(source,),
        params={"limit": int(limit)}))

    plan = ir.AnalyticalPlan(objective="A sample of the rows behind the metric",
                             operations=steps, output="few")
    result = execute(plan, question="metric sample", intent="metric_sample")

    rows: list[dict[str, Any]] = []
    for raw in result.rows:
        row = dict(raw)
        row["_included"] = {t.id: _matches(t, row) for t in formula.terms}
        rows.append(row)
    return {"columns": wanted, "rows": rows, "period": period,
            "dataset": datasets[0], "limit": int(limit)}


def _matches(term: Term, row: dict[str, Any]) -> bool:
    """Whether one row is counted by one term. The same rules the SQL used.

    Recomputed here rather than read back from the database on purpose: if the
    two ever disagree, the sample is showing somebody a lie about which rows
    were counted, and a test can catch that by comparing the count of included
    rows against the term's own row count.
    """
    for condition in term.where:
        value = row.get(condition.field)
        wanted = condition.value
        op = condition.op
        try:
            if op == "=" and value != wanted:
                return False
            if op == "!=" and value == wanted:
                return False
            if op == "<" and not (value is not None and value < wanted):
                return False
            if op == "<=" and not (value is not None and value <= wanted):
                return False
            if op == ">" and not (value is not None and value > wanted):
                return False
            if op == ">=" and not (value is not None and value >= wanted):
                return False
            if op == "in" and value not in (wanted or []):
                return False
            if op == "not_in" and value in (wanted or []):
                return False
            if op == "between" and not (
                    value is not None and wanted[0] <= value <= wanted[1]):
                return False
            if op == "is_null" and value is not None:
                return False
            if op == "is_not_null" and value is None:
                return False
            if op == "contains" and str(wanted) not in str(value or ""):
                return False
            if op == "starts_with" and not str(value or "").startswith(
                    str(wanted)):
                return False
            if op == "ends_with" and not str(value or "").endswith(str(wanted)):
                return False
        except TypeError:
            # A comparison the types do not support means this row is not in
            # the population, which is what the database would decide too.
            return False
    return True


__all__ = [
    "EXECUTION_VERSION", "SAMPLE_ROWS", "MetricUnavailable",
    "TermValue", "SideValue", "Calculation",
    "compile_metric", "evaluate", "run", "sample",
]
