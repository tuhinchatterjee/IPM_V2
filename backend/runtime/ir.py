"""
The CreditProbe Analytical IR.

What this is
------------
A plan is a directed acyclic graph of operations. Each operation names its type,
its inputs by id, and its parameters. Nothing in it is executable text: there is
no SQL string, no Python expression, no path. A plan is data, and data can be
validated, hashed, stored, diffed, shown to a reviewer and replayed nine months
later.

That is the whole reason the language model emits IR rather than SQL. A model
that writes SQL has to be trusted; a model that writes IR is checked. Every
dataset name, field name, operator and function in a plan is looked up in the
governed catalogue before anything runs, and anything not found stops the plan
rather than reaching the database.

Why a graph rather than a pipeline
----------------------------------
Real analytical questions branch. "How did ECL move against last year" reads the
same dataset at two periods and joins them; a contribution analysis needs the
total and the parts. A linear list of steps cannot express that without
inventing temporary names, so operations reference their inputs explicitly and
the plan is topologically ordered when it is compiled.

Expressions
-----------
Derived measures need arithmetic, and arithmetic is where an IR usually gives up
and accepts a string. This one does not: an expression is a small tree of
literals, column references and named functions, all of which are checked. It
covers what a bank analyst writes in a spreadsheet — arithmetic, comparison,
CASE, coalesce, date parts, ratios — and deliberately covers nothing else.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PlanError(ValueError):
    """A plan that cannot be read, validated or compiled.

    Always carries a message written for the person who asked the question, not
    for the developer — a refusal nobody can act on is only half a refusal.
    """


# ===========================================================  operations


class OpType(StrEnum):
    """Every operation the runtime can perform.

    Grouped by what they do to a table rather than alphabetically, because the
    grouping is how somebody reads a plan.
    """

    # ---- sources
    SCAN = "SCAN"                    # read a governed dataset
    METHOD = "METHOD"                # run a certified Analysis Studio method

    # ---- row shaping
    SELECT = "SELECT"                # choose columns
    FILTER = "FILTER"                # keep rows matching a predicate
    DERIVE = "DERIVE"                # add computed columns
    CAST = "CAST"                    # change a column's type
    NORMALIZE = "NORMALIZE"          # scale a column (z-score, min-max, share)
    DEDUPLICATE = "DEDUPLICATE"      # one row per key
    SORT = "SORT"
    LIMIT = "LIMIT"
    TOP_N = "TOP_N"
    BOTTOM_N = "BOTTOM_N"

    # ---- combining
    JOIN = "JOIN"                    # inner/left/right/full, direction in params
    ASOF_JOIN = "ASOF_JOIN"          # latest right-hand row on or before the left
    UNION = "UNION"                  # set union, deduplicated
    APPEND = "APPEND"                # stack rows, keeping duplicates

    # ---- multi-dataset composition
    #
    # These carry the governance of a composed join. Each one computes
    # something the plan could express with the operations above; naming them
    # separately is what lets the Trace say WHY a step is there — "rolled the
    # covenant table up to facility level so the join could not multiply it" is
    # a different statement from "grouped by account_id", and only the first
    # one is reviewable.
    AGGREGATE_BEFORE_JOIN = "AGGREGATE_BEFORE_JOIN"  # roll up the many side first
    RECONCILE_GRAIN = "RECONCILE_GRAIN"              # bring a side to the output grain
    TEMPORAL_ALIGN = "TEMPORAL_ALIGN"                # map one frequency onto another
    RELATIONSHIP_PATH = "RELATIONSHIP_PATH"          # records the path; computes nothing

    # ---- grouping and aggregation
    GROUP = "GROUP"                  # group + aggregate in one step
    AGGREGATE = "AGGREGATE"          # aggregate the whole table to one row
    DISTINCT_COUNT = "DISTINCT_COUNT"

    # ---- ordered analytics
    WINDOW = "WINDOW"                # generic window function
    LAG = "LAG"
    LEAD = "LEAD"
    ROLLING = "ROLLING"              # moving window aggregate
    MOVING_AVERAGE = "MOVING_AVERAGE"
    RANK = "RANK"

    # ---- reshaping
    PIVOT = "PIVOT"
    UNPIVOT = "UNPIVOT"
    CROSSTAB = "CROSSTAB"

    # ---- credit-risk shapes
    SEGMENT = "SEGMENT"              # label rows by a dimension
    BUCKET = "BUCKET"                # band a numeric column
    COHORT = "COHORT"                # assign an origination cohort
    VINTAGE = "VINTAGE"              # cohort x months-on-book
    COMPARE = "COMPARE"              # two periods side by side
    DELTA = "DELTA"                  # absolute change
    GROWTH = "GROWTH"                # percentage change
    CONTRIBUTION = "CONTRIBUTION"    # share of a total movement
    RECONCILE = "RECONCILE"          # assert parts sum to a whole
    FLOW = "FLOW"                    # opening -> closing movement
    WATERFALL = "WATERFALL"          # ordered decomposition
    MATRIX = "MATRIX"                # from-state x to-state
    RATIO = "RATIO"                  # numerator / denominator with guards

    # ---- distribution and statistics
    DISTRIBUTION = "DISTRIBUTION"
    PERCENTILE = "PERCENTILE"
    QUANTILE = "QUANTILE"
    OUTLIER = "OUTLIER"
    TREND = "TREND"
    CORRELATION = "CORRELATION"
    STAT_TEST = "STAT_TEST"
    REGRESSION = "REGRESSION"
    SCENARIO = "SCENARIO"

    # ---- output
    VISUALIZE = "VISUALIZE"          # declare the intended chart, computes nothing


#: Operations executed by a numerical kernel rather than compiled to SQL. They
#: run on the result of the SQL that precedes them, which is why every one of
#: them is an aggregate: a kernel never sees the raw book.
KERNEL_OPS = frozenset({
    OpType.CORRELATION,
    OpType.STAT_TEST,
    OpType.REGRESSION,
    OpType.OUTLIER,
    OpType.TREND,
    OpType.SCENARIO,
})

#: Operations that read from no input — the roots of a plan.
SOURCE_OPS = frozenset({OpType.SCAN, OpType.METHOD})

#: Operations taking exactly two inputs.
BINARY_OPS = frozenset({OpType.JOIN, OpType.UNION, OpType.APPEND, OpType.COMPARE})


#: How rows from two tables are matched. Named rather than free text so a plan
#: cannot ask for a join the compiler has not been taught to write safely.
JOIN_KINDS = frozenset({"inner", "left", "right", "full", "anti", "semi"})

#: Aggregate functions. The compiler maps each to SQL itself — the plan never
#: supplies a function name that reaches the database.
AGG_FUNCTIONS = frozenset({
    "sum", "avg", "min", "max", "count", "count_distinct", "median",
    "stddev", "variance", "first", "last", "any_value",
    "weighted_avg", "quantile",
})

#: Window functions.
WINDOW_FUNCTIONS = frozenset({
    "row_number", "rank", "dense_rank", "percent_rank", "ntile",
    "lag", "lead", "first_value", "last_value",
    "sum", "avg", "min", "max", "count",
})

#: Comparison operators usable in a filter.
COMPARISONS = frozenset({
    "=", "!=", "<", "<=", ">", ">=",
    "in", "not_in", "between", "is_null", "is_not_null",
    "contains", "starts_with", "ends_with",
})


# ===========================================================  expressions


class ExprType(StrEnum):
    """The shapes a derived value can take."""

    LITERAL = "literal"
    COLUMN = "column"
    FUNCTION = "function"
    CASE = "case"


#: Scalar functions a derived column may use. Every one is mapped to SQL by the
#: compiler; a name outside this set is refused rather than passed through.
SCALAR_FUNCTIONS = frozenset({
    # arithmetic
    "add", "subtract", "multiply", "divide", "negate", "abs", "round",
    "floor", "ceil", "power", "sqrt", "log", "ln", "exp", "mod",
    "safe_divide",          # divide, but null rather than an error on zero
    "pct_change",           # (new - old) / old, guarded
    "least", "greatest",
    # comparison and logic — usable inside CASE conditions
    "eq", "ne", "lt", "lte", "gt", "gte",
    "and", "or", "not",
    "is_null", "is_not_null", "coalesce", "nullif",
    "in_list",
    # text
    "lower", "upper", "trim", "concat", "substring", "length", "like",
    # dates and periods
    "year", "quarter", "month", "day", "date_diff", "date_add",
    "period_offset",        # "Q1 2026" shifted by N quarters
    "period_year", "period_quarter",
    # typing
    "cast_number", "cast_text", "cast_date", "cast_boolean",
})


@dataclass(frozen=True)
class Expr:
    """One node of a derived-value tree.

    Deliberately not a string. A string expression has to be parsed, and a
    parser is a place where "1+1" and "1; DROP TABLE" are separated by how good
    the parser is. A tree of typed nodes has no such seam: a literal is a bound
    parameter, a column is looked up in the catalogue, and a function must be
    one the compiler knows how to write.
    """

    type: ExprType
    #: LITERAL — the value. Reaches DuckDB as a bound parameter, never as text.
    value: Any = None
    #: COLUMN — the column name, optionally qualified "input_id.column".
    name: str = ""
    #: FUNCTION — the function, from SCALAR_FUNCTIONS.
    function: str = ""
    #: FUNCTION / CASE — the arguments, in order.
    args: tuple[Expr, ...] = ()
    #: CASE — (condition, result) pairs, evaluated in order.
    whens: tuple[tuple[Expr, Expr], ...] = ()
    #: CASE — the fallback.
    otherwise: Expr | None = None

    # ---- constructors, so callers do not build dataclasses by hand ----------

    @staticmethod
    def lit(value: Any) -> Expr:
        return Expr(ExprType.LITERAL, value=value)

    @staticmethod
    def col(name: str) -> Expr:
        return Expr(ExprType.COLUMN, name=name)

    @staticmethod
    def fn(function: str, *args: Expr) -> Expr:
        return Expr(ExprType.FUNCTION, function=function, args=tuple(args))

    @staticmethod
    def case(whens: list[tuple[Expr, Expr]], otherwise: Expr | None = None) -> Expr:
        return Expr(ExprType.CASE,
                    whens=tuple((c, r) for c, r in whens), otherwise=otherwise)

    # ---- traversal ---------------------------------------------------------

    def columns(self) -> set[str]:
        """Every column this expression reads, at any depth.

        Used by validation to check them all against the catalogue, and by the
        compiler to work out what has to be selected.
        """
        found: set[str] = set()
        if self.type is ExprType.COLUMN and self.name:
            found.add(self.name)
        for arg in self.args:
            found |= arg.columns()
        for condition, result in self.whens:
            found |= condition.columns() | result.columns()
        if self.otherwise is not None:
            found |= self.otherwise.columns()
        return found

    def functions(self) -> set[str]:
        """Every function named, at any depth."""
        found: set[str] = set()
        if self.type is ExprType.FUNCTION and self.function:
            found.add(self.function)
        for arg in self.args:
            found |= arg.functions()
        for condition, result in self.whens:
            found |= condition.functions() | result.functions()
        if self.otherwise is not None:
            found |= self.otherwise.functions()
        return found

    def depth(self) -> int:
        """How deeply nested. A guard against a plan that is a denial of service."""
        children = [a.depth() for a in self.args]
        children += [max(c.depth(), r.depth()) for c, r in self.whens]
        if self.otherwise is not None:
            children.append(self.otherwise.depth())
        return 1 + max(children, default=0)

    # ---- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": str(self.type)}
        if self.type is ExprType.LITERAL:
            out["value"] = self.value
        elif self.type is ExprType.COLUMN:
            out["name"] = self.name
        elif self.type is ExprType.FUNCTION:
            out["function"] = self.function
            out["args"] = [a.to_dict() for a in self.args]
        elif self.type is ExprType.CASE:
            out["whens"] = [[c.to_dict(), r.to_dict()] for c, r in self.whens]
            if self.otherwise is not None:
                out["otherwise"] = self.otherwise.to_dict()
        return out

    @staticmethod
    def from_dict(raw: Any) -> Expr:
        """Read an expression an LLM produced. Refuses anything malformed.

        Tolerant of the two shorthands a model reliably reaches for — a bare
        scalar meaning a literal, and a bare string meaning a column — because
        rejecting those costs a round trip and teaches nothing.
        """
        if raw is None or isinstance(raw, (int, float, bool)):
            return Expr.lit(raw)
        if isinstance(raw, str):
            return Expr.col(raw)
        if not isinstance(raw, dict):
            raise PlanError(f"An expression must be an object, not {type(raw).__name__}.")

        kind = str(raw.get("type") or "").lower()
        if kind in ("literal", "value", "const"):
            return Expr.lit(raw.get("value"))
        if kind in ("column", "col", "field"):
            name = str(raw.get("name") or raw.get("column") or "")
            if not name:
                raise PlanError("A column expression needs a name.")
            return Expr.col(name)
        if kind in ("function", "fn", "call"):
            function = str(raw.get("function") or raw.get("fn") or "")
            if not function:
                raise PlanError("A function expression needs a function name.")
            args = tuple(Expr.from_dict(a) for a in (raw.get("args") or []))
            return Expr(ExprType.FUNCTION, function=function.lower(), args=args)
        if kind == "case":
            whens: list[tuple[Expr, Expr]] = []
            for pair in raw.get("whens") or []:
                if isinstance(pair, dict):
                    whens.append((Expr.from_dict(pair.get("when")),
                                  Expr.from_dict(pair.get("then"))))
                elif isinstance(pair, (list, tuple)) and len(pair) == 2:
                    whens.append((Expr.from_dict(pair[0]), Expr.from_dict(pair[1])))
                else:
                    raise PlanError("A CASE branch must be a [when, then] pair.")
            otherwise = (Expr.from_dict(raw["otherwise"])
                         if raw.get("otherwise") is not None else None)
            return Expr(ExprType.CASE, whens=tuple(whens), otherwise=otherwise)

        raise PlanError(
            f"'{kind or '(missing)'}' is not an expression type. "
            "Use literal, column, function or case."
        )


# ===========================================================  the operation


@dataclass(frozen=True)
class Operation:
    """One step of a plan.

    `params` is deliberately a plain dict rather than a per-type dataclass. The
    shapes differ a great deal between a JOIN and a REGRESSION, the set grows,
    and validation reads them by name anyway — a class hierarchy here would be
    fifty classes for no additional safety, because the safety comes from
    validation and not from the type.
    """

    id: str
    op: OpType
    #: Ids of the operations feeding this one, in order. Empty for a source.
    inputs: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    #: One line for the reader, shown on the Trace node. Not used for anything
    #: computational, and never a substitute for the parameters.
    label: str = ""

    @property
    def is_source(self) -> bool:
        return self.op in SOURCE_OPS

    @property
    def is_kernel(self) -> bool:
        return self.op in KERNEL_OPS

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "op": str(self.op),
            "inputs": list(self.inputs),
            "params": _plain(self.params),
            "label": self.label,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> Operation:
        if not isinstance(raw, dict):
            raise PlanError(f"An operation must be an object, not {type(raw).__name__}.")

        op_name = str(raw.get("op") or raw.get("type") or "").upper()
        if not op_name:
            raise PlanError("Every operation needs an 'op'.")
        try:
            op = OpType(op_name)
        except ValueError:
            raise PlanError(
                f"'{op_name}' is not an operation CreditProbe can perform. "
                f"Available: {', '.join(sorted(o.value for o in OpType))}"
            ) from None

        op_id = str(raw.get("id") or "").strip()
        if not op_id:
            raise PlanError(f"The {op_name} operation needs an 'id'.")

        raw_inputs = raw.get("inputs") or raw.get("input") or []
        if isinstance(raw_inputs, str):
            raw_inputs = [raw_inputs]
        inputs = tuple(str(i) for i in raw_inputs)

        params = raw.get("params")
        if params is None:
            # A model that puts parameters at the top level rather than under
            # "params" has understood the operation and mis-typed the envelope.
            params = {k: v for k, v in raw.items()
                      if k not in {"id", "op", "type", "inputs", "input", "label"}}
        if not isinstance(params, dict):
            raise PlanError(f"Parameters for {op_id} must be an object.")

        return Operation(id=op_id, op=op, inputs=inputs, params=dict(params),
                         label=str(raw.get("label") or ""))


# ===========================================================  the plan


@dataclass
class AnalyticalPlan:
    """A whole analysis, as data.

    Mutable, unlike the operations in it, because a plan is edited: a Trace
    modification adds a filter, a method builder swaps a threshold. Each edit
    produces a new plan with a new hash, and the old one stays readable.
    """

    #: What the analysis is for, in the user's terms. Shown at the top of the
    #: plan view and carried onto the Trace.
    objective: str = ""
    operations: list[Operation] = field(default_factory=list)
    #: The operation whose result is the answer. Defaults to the last one.
    output: str = ""
    #: Free-form provenance: the question, the planner, the method it came from.
    meta: dict[str, Any] = field(default_factory=dict)

    # ---- structure ---------------------------------------------------------

    def by_id(self, op_id: str) -> Operation:
        for operation in self.operations:
            if operation.id == op_id:
                return operation
        raise PlanError(f"The plan has no operation called '{op_id}'.")

    @property
    def output_id(self) -> str:
        if self.output:
            return self.output
        if not self.operations:
            raise PlanError("An empty plan has no result.")
        return self.operations[-1].id

    def sources(self) -> list[Operation]:
        return [o for o in self.operations if o.is_source]

    def datasets(self) -> list[str]:
        """Every governed dataset this plan reads, in plan order."""
        seen: list[str] = []
        for operation in self.operations:
            if operation.op is OpType.SCAN:
                name = str(operation.params.get("dataset") or "")
                if name and name not in seen:
                    seen.append(name)
        return seen

    def methods(self) -> list[str]:
        """Every certified method this plan invokes."""
        seen: list[str] = []
        for operation in self.operations:
            if operation.op is OpType.METHOD:
                name = str(operation.params.get("method") or "")
                if name and name not in seen:
                    seen.append(name)
        return seen

    def ordered(self) -> list[Operation]:
        """Operations in dependency order.

        Raises on a cycle rather than looping. A plan that refers to itself is
        not a plan, and finding out during execution would mean finding out with
        a half-built temporary table.
        """
        remaining = {o.id: o for o in self.operations}
        done: set[str] = set()
        out: list[Operation] = []

        while remaining:
            ready = [o for o in remaining.values()
                     if all(i in done for i in o.inputs)]
            if not ready:
                stuck = ", ".join(sorted(remaining))
                raise PlanError(
                    f"These operations depend on each other in a loop, so there "
                    f"is no order to run them in: {stuck}."
                )
            # Stable: plan order among the ready set, so the same plan always
            # compiles to the same SQL and therefore the same hash.
            ready.sort(key=lambda o: [x.id for x in self.operations].index(o.id))
            for operation in ready:
                out.append(operation)
                done.add(operation.id)
                del remaining[operation.id]
        return out

    # ---- identity ----------------------------------------------------------

    def fingerprint(self) -> str:
        """A stable hash of what this plan computes.

        Excludes labels and meta — a re-worded label is the same computation,
        and two plans that differ only in prose should reconcile to the same
        number and say so.
        """
        payload = json.dumps(
            [
                {"id": o.id, "op": str(o.op), "inputs": list(o.inputs),
                 "params": _plain(o.params)}
                for o in self.ordered()
            ] + [{"output": self.output_id}],
            sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    # ---- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "operations": [o.to_dict() for o in self.operations],
            "output": self.output_id if self.operations else "",
            "meta": _plain(self.meta),
            "datasets": self.datasets(),
            "methods": self.methods(),
            "fingerprint": self.fingerprint() if self.operations else "",
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> AnalyticalPlan:
        if not isinstance(raw, dict):
            raise PlanError(f"A plan must be an object, not {type(raw).__name__}.")

        raw_ops = raw.get("operations") or raw.get("steps") or []
        if not isinstance(raw_ops, list):
            raise PlanError("'operations' must be a list.")
        if not raw_ops:
            raise PlanError("A plan with no operations computes nothing.")

        operations = [Operation.from_dict(o) for o in raw_ops]

        ids = [o.id for o in operations]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise PlanError(
                f"Two operations share an id, so references to them are "
                f"ambiguous: {', '.join(sorted(duplicates))}."
            )

        return AnalyticalPlan(
            objective=str(raw.get("objective") or ""),
            operations=operations,
            output=str(raw.get("output") or ""),
            meta=dict(raw.get("meta") or {}),
        )

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def _plain(value: Any) -> Any:
    """Make a params dict JSON-safe, keeping expression trees inspectable."""
    if isinstance(value, Expr):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, StrEnum):
        return str(value)
    return value


__all__ = [
    "AGG_FUNCTIONS",
    "BINARY_OPS",
    "COMPARISONS",
    "JOIN_KINDS",
    "KERNEL_OPS",
    "SCALAR_FUNCTIONS",
    "SOURCE_OPS",
    "WINDOW_FUNCTIONS",
    "AnalyticalPlan",
    "Expr",
    "ExprType",
    "OpType",
    "Operation",
    "PlanError",
]
