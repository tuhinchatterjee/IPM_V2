"""
Compiling a validated plan to parameterised DuckDB SQL.

The safety property
-------------------
Two kinds of thing appear in a query: *identifiers* (dataset and column names)
and *values* (thresholds, sector names, dates). They are handled completely
differently, and the difference is the whole security argument:

    identifiers  come only from the governed catalogue. Validation has already
                 confirmed every one exists. They are additionally checked
                 against a strict pattern here and double-quoted, so a catalogue
                 that somehow contained something odd still could not inject.

    values       NEVER appear in the SQL text. Every one becomes a `?` and
                 travels in the parameter list. There is no path by which a
                 value a user or a model supplied becomes part of the statement.

A reader can verify that claim by searching this file: no f-string ever
interpolates a value, only identifiers and structural keywords.

The shape of the output
-----------------------
One `WITH` chain, one CTE per operation, in dependency order. That is not the
smallest possible SQL, and it is not meant to be — DuckDB flattens it during
planning, and a query whose CTE names match the operation ids is a query a
reviewer can read next to the plan. "Which step produced this column?" is
answered by looking, not by inference.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.runtime.ir import (
    AnalyticalPlan,
    Expr,
    ExprType,
    Operation,
    OpType,
    PlanError,
)
from backend.runtime.validation import (
    DEFAULT_LIMITS,
    Limits,
    StepSchema,
    ValidationReport,
)

logger = logging.getLogger(__name__)

#: An identifier may be letters, digits and underscores. Nothing else reaches a
#: quoted name — belt and braces behind the catalogue check.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def ident(name: str) -> str:
    """Quote an identifier, refusing anything that is not plainly one."""
    plain = name.split(".")[-1]
    if not _IDENTIFIER.match(plain):
        raise PlanError(
            f"'{name}' is not a usable column name. Column names come from the "
            "governed dictionary, and this one is not shaped like one."
        )
    return f'"{plain}"'


def cte_name(op_id: str) -> str:
    """A CTE name derived from an operation id, safe and recognisable."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", op_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"step_{cleaned}"
    return f'"{cleaned}"'


@dataclass
class CompiledQuery:
    """The SQL, its parameters, and enough context to explain it."""

    sql: str
    params: list[Any] = field(default_factory=list)
    #: Operation id -> the CTE that holds its result.
    steps: dict[str, str] = field(default_factory=dict)
    #: Operations left for a kernel to run after the SQL returns.
    kernel_steps: list[Operation] = field(default_factory=list)
    #: Datasets read, for the Trace and the lineage panel.
    datasets: list[str] = field(default_factory=list)
    #: The WITH block on its own, so a second question can be asked of the same
    #: intermediate steps without recompiling or re-binding anything.
    cte_body: str = ""

    def population_sql(self, steps: list[str]) -> str:
        """One query counting the rows at each named step.

        Reuses the compiled CTEs verbatim, so the counts describe exactly the
        query that produced the answer rather than a re-derivation of it — and
        takes the same parameters in the same order, because the WITH block is
        unchanged.

        This is what makes "4,100 customers opened, 3,984 survived every join"
        a measured fact rather than a claim.
        """
        usable = [s for s in steps if s in self.steps.values()]
        if not usable or not self.cte_body:
            return ""
        counts = "\nUNION ALL\n".join(
            f"SELECT '{name}' AS step, COUNT(*) AS rows FROM {name}"
            for name in usable)
        return f"WITH {self.cte_body}\n{counts}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sql": self.sql,
            # The values, shown separately from the statement. That separation
            # IS the safety property, so the plan viewer shows it that way too.
            "parameters": list(self.params),
            "steps": dict(self.steps),
            "kernel_steps": [o.to_dict() for o in self.kernel_steps],
            "datasets": list(self.datasets),
        }



def _join_pairs(on: Any) -> list[tuple[str, str]]:
    """Join keys as (left, right) pairs, from any of the accepted spellings."""
    if isinstance(on, str):
        on = [on]
    pairs: list[tuple[str, str]] = []
    for entry in on or []:
        if isinstance(entry, str):
            pairs.append((entry, entry))
        elif isinstance(entry, dict):
            left_key = str(entry.get("left") or entry.get("left_column"))
            pairs.append((left_key, str(entry.get("right")
                                        or entry.get("right_column") or left_key)))
        else:
            pairs.append((str(entry[0]), str(entry[1])))
    return pairs


class Compiler:
    """Turns one validated plan into one parameterised statement."""

    def __init__(self, plan: AnalyticalPlan, report: ValidationReport, *,
                 limits: Limits = DEFAULT_LIMITS, source: Any = None) -> None:
        if not report.ok:
            raise PlanError(
                "A plan that failed validation is never compiled. "
                + " ".join(report.reasons)
            )
        self.plan = plan
        self.report = report
        self.limits = limits
        self._params: list[Any] = []
        self._ctes: list[str] = []
        self._steps: dict[str, str] = {}
        self._kernels: list[Operation] = []

        from backend.data_access.duckdb_source import DuckDBSource

        self._source = source or DuckDBSource()

    # ---- values ------------------------------------------------------------

    def bind(self, value: Any) -> str:
        """Add a value to the parameter list and return its placeholder.

        The only way a value enters a query. Every literal in the plan goes
        through here.
        """
        self._params.append(value)
        return "?"

    # ---- entry point -------------------------------------------------------

    def compile(self) -> CompiledQuery:
        ordered = self.plan.ordered()

        # Kernel operations run after the SQL. Everything up to the first one
        # compiles; the rest is handed to the executor with the frame.
        sql_ops: list[Operation] = []
        for operation in ordered:
            if operation.is_kernel or self._kernels:
                self._kernels.append(operation)
            else:
                sql_ops.append(operation)

        if not sql_ops:
            raise PlanError(
                "This plan starts with a statistical operation, but a statistic "
                "needs a population. Read and shape the data first."
            )

        for operation in sql_ops:
            self._emit(operation)

        final = self._steps[sql_ops[-1].id]
        body = ",\n".join(self._ctes)
        # A hard cap on what comes back, regardless of what the plan asked for.
        # The plan's own LIMIT is usually smaller; this one is the backstop.
        sql = (
            f"WITH {body}\nSELECT * FROM {final}\n"
            f"LIMIT {int(self.limits.max_output_rows)}"
        )

        return CompiledQuery(
            sql=sql,
            params=list(self._params),
            steps=dict(self._steps),
            kernel_steps=list(self._kernels),
            datasets=self.plan.datasets(),
            cte_body=body,
        )

    # ---- emitting ----------------------------------------------------------

    def _emit(self, op: Operation) -> None:
        handler = getattr(self, f"_op_{str(op.op).lower()}", None)
        if handler is None:
            raise PlanError(
                f"{op.id}: {op.op} has no SQL implementation. It may be a "
                "statistical operation, which runs after the query."
            )
        body = handler(op)
        name = cte_name(op.id)
        self._ctes.append(f"{name} AS (\n{_indent(body)}\n)")
        self._steps[op.id] = name

    def _input(self, op: Operation, index: int = 0) -> str:
        return self._steps[op.inputs[index]]

    def _schema(self, op_id: str) -> StepSchema:
        return self.report.schemas.get(op_id, StepSchema())

    # ---- expressions -------------------------------------------------------

    def expr(self, raw: Any) -> str:
        """Compile an expression tree. Values bind; columns quote."""
        node = raw if isinstance(raw, Expr) else Expr.from_dict(raw)

        if node.type is ExprType.LITERAL:
            return self.bind(node.value)
        if node.type is ExprType.COLUMN:
            return ident(node.name)
        if node.type is ExprType.CASE:
            parts = ["CASE"]
            for condition, result in node.whens:
                parts.append(f"WHEN {self.expr(condition)} THEN {self.expr(result)}")
            if node.otherwise is not None:
                parts.append(f"ELSE {self.expr(node.otherwise)}")
            parts.append("END")
            return "(" + " ".join(parts) + ")"

        args = [self.expr(a) for a in node.args]
        return _scalar_sql(node.function, args, self)

    # ---- sources -----------------------------------------------------------

    def _op_scan(self, op: Operation) -> str:
        dataset = str(op.params["dataset"])
        period = op.params.get("period")
        pattern = self._source._require_files(dataset, str(period) if period else None)

        schema = self._schema(op.id)
        columns = ", ".join(ident(c) for c in schema.columns) or "*"
        # The path is a catalogue-derived location, not user input; it is bound
        # as a parameter regardless, because read_parquet accepts one.
        return f"SELECT {columns}\nFROM read_parquet({self.bind(pattern)})"

    def _op_method(self, op: Operation) -> str:
        raise PlanError(
            f"{op.id}: a certified method is executed by the engine rather than "
            "compiled into a query. Run it as its own step."
        )

    # ---- row shaping -------------------------------------------------------

    def _op_select(self, op: Operation) -> str:
        columns = ", ".join(ident(str(c)) for c in
                            (op.params.get("columns") or op.params.get("fields")))
        return f"SELECT {columns}\nFROM {self._input(op)}"

    def _op_filter(self, op: Operation) -> str:
        clauses: list[str] = []
        predicates = op.params.get("where") or op.params.get("conditions") or []
        if isinstance(predicates, dict):
            predicates = [predicates]
        for predicate in predicates:
            clauses.append(self._predicate(predicate))
        if op.params.get("expression") or op.params.get("expr"):
            clauses.append(self.expr(op.params.get("expression") or op.params["expr"]))

        joiner = " OR " if str(op.params.get("combine") or "and").lower() == "or" else " AND "
        where = joiner.join(f"({c})" for c in clauses) or "TRUE"
        return f"SELECT *\nFROM {self._input(op)}\nWHERE {where}"

    def _predicate(self, predicate: dict[str, Any]) -> str:
        column = ident(str(predicate.get("column") or predicate.get("field")))
        comparison = str(predicate.get("op") or predicate.get("operator") or "=").lower()
        value = predicate.get("value", predicate.get("values"))

        if comparison == "is_null":
            return f"{column} IS NULL"
        if comparison == "is_not_null":
            return f"{column} IS NOT NULL"
        if comparison in ("in", "not_in"):
            values = value if isinstance(value, list) else [value]
            if not values:
                # An empty IN list is a contradiction in SQL and a mistake in a
                # plan. Say so rather than silently returning nothing.
                raise PlanError(
                    f"A '{comparison}' filter on {predicate.get('column')} has no "
                    "values, so it would match nothing."
                )
            placeholders = ", ".join(self.bind(v) for v in values)
            keyword = "IN" if comparison == "in" else "NOT IN"
            return f"{column} {keyword} ({placeholders})"
        if comparison == "between":
            low, high = value
            return f"{column} BETWEEN {self.bind(low)} AND {self.bind(high)}"
        if comparison in ("contains", "starts_with", "ends_with"):
            text = str(value)
            pattern = {"contains": f"%{text}%", "starts_with": f"{text}%",
                       "ends_with": f"%{text}"}[comparison]
            # LIKE with a bound pattern: the wildcards are ours, the text is not.
            return f"CAST({column} AS VARCHAR) ILIKE {self.bind(pattern)}"

        operator = {"=": "=", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}[comparison]
        return f"{column} {operator} {self.bind(value)}"

    def _op_derive(self, op: Operation) -> str:
        entries = op.params.get("columns") or op.params.get("derive") or []
        if isinstance(entries, dict):
            entries = [{"as": k, "expression": v} for k, v in entries.items()]

        source = self._schema(op.inputs[0])
        replaced = {str(e.get("as") or e.get("name")) for e in entries}
        kept = [ident(c) for c in source.columns if c not in replaced]
        added = [
            f"{self.expr(e.get('expression') or e.get('expr'))} AS "
            f"{ident(str(e.get('as') or e.get('name')))}"
            for e in entries
        ]
        return f"SELECT {', '.join([*kept, *added])}\nFROM {self._input(op)}"

    def _op_cast(self, op: Operation) -> str:
        column = str(op.params["column"])
        to = str(op.params.get("to") or op.params.get("type")).lower()
        sql_type = {"number": "DOUBLE", "integer": "BIGINT", "text": "VARCHAR",
                    "date": "DATE", "boolean": "BOOLEAN"}[to]
        source = self._schema(op.inputs[0])
        columns = [
            (f"TRY_CAST({ident(c)} AS {sql_type}) AS {ident(c)}"
             if c == column else ident(c))
            for c in source.columns
        ]
        return f"SELECT {', '.join(columns)}\nFROM {self._input(op)}"

    def _op_normalize(self, op: Operation) -> str:
        column = ident(str(op.params["column"]))
        method = str(op.params.get("method") or "share").lower()
        partition = [str(c) for c in
                     (op.params.get("by") or op.params.get("partition_by") or [])]
        over = (f" OVER (PARTITION BY {', '.join(ident(c) for c in partition)})"
                if partition else " OVER ()")
        name = ident(str(op.params.get("as") or f"{op.params['column']}_{method}"))

        formula = {
            "share": f"({column} * 100.0) / NULLIF(SUM({column}){over}, 0)",
            "zscore": f"({column} - AVG({column}){over}) / NULLIF(STDDEV({column}){over}, 0)",
            "minmax": (f"({column} - MIN({column}){over}) / "
                       f"NULLIF(MAX({column}){over} - MIN({column}){over}, 0)"),
            "index": f"({column} * 100.0) / NULLIF(FIRST_VALUE({column}){over}, 0)",
        }[method]
        return f"SELECT *, {formula} AS {name}\nFROM {self._input(op)}"

    def _op_deduplicate(self, op: Operation) -> str:
        keys = [str(k) for k in (op.params.get("keys") or op.params.get("by") or [])]
        if not keys:
            return f"SELECT DISTINCT *\nFROM {self._input(op)}"
        order = self._order_clause(op.params.get("order_by") or []) or "1"
        partition = ", ".join(ident(k) for k in keys)
        return (
            f"SELECT * EXCLUDE (_cp_rn) FROM (\n"
            f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition} "
            f"ORDER BY {order}) AS _cp_rn\n"
            f"  FROM {self._input(op)}\n"
            f") WHERE _cp_rn = 1"
        )

    def _order_clause(self, entries: Any) -> str:
        if isinstance(entries, (str, dict)):
            entries = [entries]
        parts: list[str] = []
        for entry in entries or []:
            if isinstance(entry, dict):
                name = str(entry.get("column") or entry.get("field"))
                descending = bool(entry.get("desc") or entry.get("descending")
                                  or str(entry.get("direction") or "").lower() == "desc")
            else:
                name, descending = str(entry), False
            # NULLS LAST on both directions: a null sorting to the top of a
            # "largest exposures" table is a bug that looks like data.
            parts.append(f"{ident(name)} {'DESC' if descending else 'ASC'} NULLS LAST")
        return ", ".join(parts)

    def _op_sort(self, op: Operation) -> str:
        order = self._order_clause(op.params.get("by") or op.params.get("columns")
                                   or op.params.get("order_by"))
        return f"SELECT *\nFROM {self._input(op)}\nORDER BY {order}"

    def _op_limit(self, op: Operation) -> str:
        count = int(op.params.get("n") or op.params.get("count") or op.params.get("limit"))
        order = self._order_clause(op.params.get("order_by") or [])
        clause = f"\nORDER BY {order}" if order else ""
        # A literal integer, already bounds-checked by validation. DuckDB does
        # not accept a parameter in LIMIT.
        return f"SELECT *\nFROM {self._input(op)}{clause}\nLIMIT {count}"

    def _op_top_n(self, op: Operation, descending: bool = True) -> str:
        measure = str(op.params.get("by") or op.params.get("column")
                      or op.params.get("measure"))
        count = int(op.params.get("n") or op.params.get("count") or op.params.get("limit"))
        within = [str(c) for c in
                  (op.params.get("within") or op.params.get("partition_by") or [])]
        direction = "DESC" if descending else "ASC"

        if not within:
            return (f"SELECT *\nFROM {self._input(op)}\n"
                    f"ORDER BY {ident(measure)} {direction} NULLS LAST\nLIMIT {count}")

        partition = ", ".join(ident(c) for c in within)
        return (
            f"SELECT * EXCLUDE (_cp_rank) FROM (\n"
            f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition} "
            f"ORDER BY {ident(measure)} {direction} NULLS LAST) AS _cp_rank\n"
            f"  FROM {self._input(op)}\n"
            f") WHERE _cp_rank <= {count}"
        )

    def _op_bottom_n(self, op: Operation) -> str:
        return self._op_top_n(op, descending=False)

    # ---- combining ---------------------------------------------------------

    def _op_join(self, op: Operation) -> str:
        left_cte, right_cte = self._input(op, 0), self._input(op, 1)
        left_schema = self._schema(op.inputs[0])
        right_schema = self._schema(op.inputs[1])

        kind = str(op.params.get("kind") or op.params.get("how") or "inner").lower()
        kind = {"left_join": "left", "inner_join": "inner", "outer": "full"}.get(kind, kind)

        pairs = _join_pairs(op.params.get("on") or op.params.get("keys") or [])

        condition = " AND ".join(
            f"L.{ident(left_key)} = R.{ident(right_key)}" for left_key, right_key in pairs
        )

        if kind in ("semi", "anti"):
            keyword = "SEMI" if kind == "semi" else "ANTI"
            return (f"SELECT L.*\nFROM {left_cte} L\n"
                    f"{keyword} JOIN {right_cte} R ON {condition}")

        keyword = {"inner": "INNER JOIN", "left": "LEFT JOIN",
                   "right": "RIGHT JOIN", "full": "FULL OUTER JOIN"}[kind]

        right_keys = {p[1] for p in pairs}
        prefix = str(op.params.get("right_prefix") or "")
        selected = [f"L.{ident(c)} AS {ident(c)}" for c in left_schema.columns]
        for column in right_schema.columns:
            if column in right_keys and column in left_schema.columns:
                continue  # the key is already carried by the left side
            alias = f"{prefix}{column}" if prefix else column
            if alias in left_schema.columns:
                alias = f"right_{column}"
            selected.append(f"R.{ident(column)} AS {ident(alias)}")

        return (f"SELECT {', '.join(selected)}\nFROM {left_cte} L\n"
                f"{keyword} {right_cte} R ON {condition}")


    def _op_asof_join(self, op: Operation) -> str:
        """The latest right-hand row dated on or before each left-hand row.

        This is the join that makes an annual rating usable against a quarterly
        book, and the one place where getting the comparison backwards would
        silently read the future. The ordering column is compared with `<=`
        and never `<`, because a rating dated exactly at the reporting date IS
        available at that date — and never with `>=`, which is how look-ahead
        gets in.

        Compiled as a windowed pick rather than DuckDB's ASOF JOIN so the
        tie-breaking is explicit and identical on every engine: partition by the
        join keys, order by the right-hand date descending, take the first.
        """
        left_cte, right_cte = self._input(op, 0), self._input(op, 1)
        left_schema = self._schema(op.inputs[0])
        right_schema = self._schema(op.inputs[1])

        pairs = _join_pairs(op.params.get("on") or op.params.get("keys") or [])
        if not pairs:
            raise PlanError(f"{op.id}: an as-of join needs at least one key.")

        left_order = str(op.params.get("left_order")
                         or op.params.get("left_time") or "")
        right_order = str(op.params.get("right_order")
                          or op.params.get("right_time") or "")
        if not left_order or not right_order:
            raise PlanError(
                f"{op.id}: an as-of join needs the ordering column on both "
                "sides — without it there is nothing to be 'as of'.")

        direction = str(op.params.get("direction") or "backward").lower()
        if direction != "backward":
            raise PlanError(
                f"{op.id}: only a backward as-of join is permitted. A forward "
                "one reads an observation that had not happened at the "
                "analysis date.")

        # Both sides are cast to the same type before they are compared. A
        # governed period is a LABEL — "2025", "Q2 2026" — and one side
        # arriving as an integer from a Hive partition while the other is text
        # is a type error at best and an arbitrary ordering at worst. The plan
        # says which comparison it means; text is the default because that is
        # what a period label is.
        compare_as = str(op.params.get("order_as") or "text").lower()
        cast_type = {"text": "VARCHAR", "number": "DOUBLE"}.get(compare_as)
        if cast_type is None:
            raise PlanError(
                f"{op.id}: '{compare_as}' is not a comparison an as-of join "
                "performs. Use 'text' for period labels or 'number'.")

        def ordered(alias: str, column: str) -> str:
            qualified = f"{alias}.{ident(column)}" if alias else ident(column)
            return f"CAST({qualified} AS {cast_type})"

        condition = " AND ".join(
            f"L.{ident(left_key)} = R.{ident(right_key)}"
            for left_key, right_key in pairs)

        prefix = str(op.params.get("right_prefix") or "")
        right_keys = {p[1] for p in pairs}
        selected = [f"L.{ident(c)} AS {ident(c)}" for c in left_schema.columns]
        for column in right_schema.columns:
            if column in right_keys and column in left_schema.columns:
                continue
            alias = f"{prefix}{column}" if prefix else column
            if alias in left_schema.columns:
                alias = f"right_{column}"
            selected.append(f"R.{ident(column)} AS {ident(alias)}")

        # LEFT JOIN on purpose: a left-hand row with no observation on or before
        # its date has no as-of match, and dropping it silently would shrink the
        # population without saying so. The plan filters it explicitly if it
        # means to.
        return (
            f"SELECT {', '.join(selected)}\n"
            f"FROM {left_cte} L\n"
            f"LEFT JOIN (\n"
            f"  SELECT *, ROW_NUMBER() OVER (\n"
            f"    PARTITION BY {', '.join(ident(p[1]) for p in pairs)}, "
            f"_cp_asof_left\n"
            f"    ORDER BY {ordered('', right_order)} DESC\n"
            f"  ) AS _cp_asof_rank FROM (\n"
            f"    SELECT R2.*, {ordered('L2', left_order)} AS _cp_asof_left\n"
            f"    FROM {right_cte} R2\n"
            f"    JOIN (SELECT DISTINCT {ident(left_order)} FROM {left_cte}) L2\n"
            f"      ON {ordered('R2', right_order)} <= {ordered('L2', left_order)}\n"
            f"  )\n"
            f") R ON {condition} AND R._cp_asof_left = "
            f"{ordered('L', left_order)} AND R._cp_asof_rank = 1"
        )

    def _op_aggregate_before_join(self, op: Operation) -> str:
        """Roll the many-side up to the grain it will be joined at.

        Identical SQL to GROUP. It exists as its own operation so the Trace can
        say WHY the step is there — "rolled the covenant table up to facility
        level so the join could not multiply it" is reviewable and "grouped by
        account_id" is not.
        """
        return self._op_group(op)

    def _op_reconcile_grain(self, op: Operation) -> str:
        """Bring one side to the analysis output grain."""
        return self._op_group(op)

    def _op_temporal_align(self, op: Operation) -> str:
        """Map one reporting frequency onto another, as a derived column.

        Computes the period a row belongs to on the OTHER side's calendar —
        the rating year behind a quarter, say — so the join afterwards is an
        equality on a governed column rather than an inequality nobody checked.
        """
        source = str(op.params.get("column") or op.params["source"])
        target = str(op.params.get("as") or "aligned_period")
        rule = str(op.params.get("rule") or "year_of_quarter")

        schema = self._schema(op.inputs[0])
        kept = [ident(c) for c in schema.columns if c != target]

        # Cast to text before matching. A governed period is usually a label
        # ("Q2 2026") but an annual dataset stores the bare year as an integer,
        # and regexp_extract on a BIGINT is a binder error that loses the whole
        # answer to a message about argument types.
        year = (f"CAST(regexp_extract(CAST({ident(source)} AS VARCHAR), "
                f"'(\\d{{4}})$', 1) AS INTEGER)")

        if rule == "year_of_quarter":
            # "Q3 2026" -> "2026". The year is the last whitespace-separated
            # token, taken from the string rather than parsed as a date,
            # because the governed period IS a label.
            expression = f"CAST({year} AS VARCHAR)"
        elif rule == "completed_year_of_quarter":
            # "Q2 2026" -> "2025". An annual cycle labelled 2026 is not
            # complete until the end of 2026, so it is not available to an
            # analysis run in Q2 of that year. Aligning to the year label
            # itself would let a quarter read a cycle that had not finished —
            # look-ahead that produces no error and no movement, because both
            # ends of a year-on-year comparison land on the same cycle.
            expression = f"CAST(({year} - 1) AS VARCHAR)"
        elif rule == "identity":
            expression = ident(source)
        else:
            raise PlanError(
                f"{op.id}: '{rule}' is not a governed temporal alignment rule.")

        return (f"SELECT {', '.join([*kept, f'{expression} AS {ident(target)}'])}\n"
                f"FROM {self._input(op)}")

    def _op_relationship_path(self, op: Operation) -> str:
        """Records which governed relationships the plan used. Computes nothing.

        A pass-through so the path appears on the Trace as a step rather than as
        a footnote, and so the compiled SQL still reads in the order the
        analysis was reasoned about.
        """
        return f"SELECT *\nFROM {self._input(op)}"

    def _op_union(self, op: Operation) -> str:
        schema = self._schema(op.inputs[0])
        columns = ", ".join(ident(c) for c in schema.columns)
        parts = [f"SELECT {columns} FROM {self._steps[i]}" for i in op.inputs]
        return "\nUNION\n".join(parts)

    def _op_append(self, op: Operation) -> str:
        schema = self._schema(op.inputs[0])
        columns = ", ".join(ident(c) for c in schema.columns)
        parts = [f"SELECT {columns} FROM {self._steps[i]}" for i in op.inputs]
        return "\nUNION ALL\n".join(parts)

    # ---- aggregation -------------------------------------------------------

    def _aggregate_sql(self, entry: dict[str, Any]) -> str:
        function = str(entry.get("function") or entry.get("agg")).lower()
        column = entry.get("column") or entry.get("field")
        quoted = ident(str(column)) if column else None

        if function == "count":
            inner = f"COUNT({quoted})" if quoted else "COUNT(*)"
        elif function == "count_distinct":
            inner = f"COUNT(DISTINCT {quoted})"
        elif function == "weighted_avg":
            weight = ident(str(entry.get("weight") or entry.get("weight_by")))
            # Weighted mean, written out so a reviewer can check it: sum of
            # value times weight, over the sum of the weights that had a value.
            inner = (f"SUM({quoted} * {weight}) / "
                     f"NULLIF(SUM(CASE WHEN {quoted} IS NULL THEN 0 ELSE {weight} END), 0)")
        elif function == "quantile":
            q = float(entry.get("q") or entry.get("quantile"))
            inner = f"QUANTILE_CONT({quoted}, {self.bind(q)})"
        elif function == "any_value":
            inner = f"ANY_VALUE({quoted})"
        else:
            sql_function = {
                "sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX",
                "median": "MEDIAN", "stddev": "STDDEV", "variance": "VARIANCE",
                "first": "FIRST", "last": "LAST",
            }[function]
            inner = f"{sql_function}({quoted})"

        name = str(entry.get("as") or entry.get("name")
                   or (f"{function}_{column}" if column else function))
        return f"{inner} AS {ident(name)}"

    def _aggregate_entries(self, op: Operation) -> list[dict[str, Any]]:
        entries = op.params.get("aggregates") or op.params.get("measures") or []
        if isinstance(entries, dict):
            entries = [{"as": k, **v} if isinstance(v, dict) else {"as": k, "function": v}
                       for k, v in entries.items()]
        return list(entries)

    def _op_group(self, op: Operation) -> str:
        keys = op.params.get("by") or op.params.get("group_by") or []
        if isinstance(keys, str):
            keys = [keys]
        grouped = [ident(str(k)) for k in keys]
        measures = [self._aggregate_sql(e) for e in self._aggregate_entries(op)]
        selected = ", ".join([*grouped, *measures])
        group_by = f"\nGROUP BY {', '.join(grouped)}" if grouped else ""
        return f"SELECT {selected}\nFROM {self._input(op)}{group_by}"

    def _op_aggregate(self, op: Operation) -> str:
        measures = ", ".join(self._aggregate_sql(e) for e in self._aggregate_entries(op))
        return f"SELECT {measures}\nFROM {self._input(op)}"

    def _op_distinct_count(self, op: Operation) -> str:
        column = ident(str(op.params["column"]))
        keys = [ident(str(k)) for k in (op.params.get("by") or [])]
        name = ident(str(op.params.get("as") or f"distinct_{op.params['column']}"))
        selected = ", ".join([*keys, f"COUNT(DISTINCT {column}) AS {name}"])
        group_by = f"\nGROUP BY {', '.join(keys)}" if keys else ""
        return f"SELECT {selected}\nFROM {self._input(op)}{group_by}"

    # ---- windows -----------------------------------------------------------

    def _op_window(self, op: Operation) -> str:
        function = str(op.params.get("function") or op.params.get("fn") or "").lower()
        if op.op is OpType.LAG:
            function = "lag"
        elif op.op is OpType.LEAD:
            function = "lead"
        elif op.op is OpType.RANK:
            function = function or "rank"
        elif op.op in (OpType.ROLLING, OpType.MOVING_AVERAGE):
            function = function or "avg"

        column = op.params.get("column") or op.params.get("field")
        quoted = ident(str(column)) if column else None

        partition = [ident(str(c)) for c in
                     (op.params.get("partition_by") or op.params.get("by") or [])]
        order = self._order_clause(op.params.get("order_by") or [])

        over = []
        if partition:
            over.append(f"PARTITION BY {', '.join(partition)}")
        if order:
            over.append(f"ORDER BY {order}")

        if op.op in (OpType.ROLLING, OpType.MOVING_AVERAGE):
            window = int(op.params.get("window") or op.params.get("periods") or 3)
            if window < 1:
                raise PlanError(f"{op.id}: a rolling window must cover at least one period.")
            over.append(f"ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW")

        offset = int(op.params.get("offset") or op.params.get("periods") or 1)
        call = {
            "row_number": "ROW_NUMBER()", "rank": "RANK()",
            "dense_rank": "DENSE_RANK()", "percent_rank": "PERCENT_RANK()",
            "ntile": f"NTILE({int(op.params.get('buckets') or 4)})",
            "lag": f"LAG({quoted}, {offset})", "lead": f"LEAD({quoted}, {offset})",
            "first_value": f"FIRST_VALUE({quoted})", "last_value": f"LAST_VALUE({quoted})",
            "sum": f"SUM({quoted})", "avg": f"AVG({quoted})",
            "min": f"MIN({quoted})", "max": f"MAX({quoted})",
            "count": f"COUNT({quoted})" if quoted else "COUNT(*)",
        }[function]

        default_name = f"{function}_{column}" if column else function
        name = ident(str(op.params.get("as") or default_name))
        return (f"SELECT *, {call} OVER ({' '.join(over)}) AS {name}\n"
                f"FROM {self._input(op)}")

    _op_lag = _op_lead = _op_rolling = _op_moving_average = _op_rank = _op_window

    # ---- reshaping ---------------------------------------------------------

    def _op_pivot(self, op: Operation) -> str:
        on = ident(str(op.params.get("on") or op.params.get("column")
                       or op.params.get("pivot_on")))
        value = ident(str(op.params.get("value") or op.params.get("values")
                          or op.params.get("measure")))
        index = [ident(str(c)) for c in
                 (op.params.get("by") or op.params.get("index") or [])]
        function = str(op.params.get("function") or "sum").upper()
        using = {"SUM": "SUM", "AVG": "AVG", "MIN": "MIN", "MAX": "MAX",
                 "COUNT": "COUNT", "MEDIAN": "MEDIAN"}.get(function, "SUM")
        group_by = f"\nGROUP BY {', '.join(index)}" if index else ""
        # DuckDB's PIVOT resolves the columns from the data at execution.
        return (f"PIVOT {self._input(op)}\nON {on}\n"
                f"USING {using}({value}){group_by}")

    _op_crosstab = _op_pivot

    def _op_unpivot(self, op: Operation) -> str:
        columns = [ident(str(c)) for c in
                   (op.params.get("columns") or op.params.get("measures"))]
        name_as = ident(str(op.params.get("name_as") or "measure"))
        value_as = ident(str(op.params.get("value_as") or "value"))
        return (f"UNPIVOT {self._input(op)}\n"
                f"ON {', '.join(columns)}\n"
                f"INTO NAME {name_as} VALUE {value_as}")

    # ---- credit-risk shapes ------------------------------------------------

    def _op_bucket(self, op: Operation) -> str:
        column = ident(str(op.params["column"]))
        edges = [float(e) for e in (op.params.get("edges") or op.params.get("bounds"))]
        labels = op.params.get("labels")
        name = ident(str(op.params.get("as") or f"{op.params['column']}_bucket"))

        branches = []
        for index, edge in enumerate(edges):
            label = (str(labels[index]) if labels and index < len(labels)
                     else f"< {edge:g}")
            branches.append(f"WHEN {column} < {self.bind(edge)} THEN {self.bind(label)}")
        final = (str(labels[len(edges)]) if labels and len(labels) > len(edges)
                 else f">= {edges[-1]:g}")
        case = ("CASE " + " ".join(branches) + f" ELSE {self.bind(final)} END")
        return f"SELECT *, {case} AS {name}\nFROM {self._input(op)}"

    def _op_segment(self, op: Operation) -> str:
        column = ident(str(op.params.get("column") or op.params.get("by")))
        name = ident(str(op.params.get("as") or "segment"))
        return f"SELECT *, {column} AS {name}\nFROM {self._input(op)}"

    def _op_ratio(self, op: Operation) -> str:
        numerator = ident(str(op.params["numerator"]))
        denominator = ident(str(op.params["denominator"]))
        name = ident(str(op.params.get("as") or "ratio"))
        scale = " * 100.0" if op.params.get("as_percent", True) else ""
        # NULLIF, not a CASE: division by zero is undefined, and reporting it as
        # zero would put a 0% next to a denominator that does not exist.
        return (f"SELECT *, ({numerator}{scale}) / NULLIF({denominator}, 0) AS {name}\n"
                f"FROM {self._input(op)}")

    def _op_delta(self, op: Operation) -> str:
        return self._two_column_measure(op, "-", "delta")

    def _op_growth(self, op: Operation) -> str:
        opening = ident(str(op.params.get("from") or op.params.get("opening")))
        closing = ident(str(op.params.get("to") or op.params.get("closing")))
        name = ident(str(op.params.get("as") or "growth_pct"))
        return (f"SELECT *, (({closing} - {opening}) * 100.0) / "
                f"NULLIF(ABS({opening}), 0) AS {name}\nFROM {self._input(op)}")

    def _two_column_measure(self, op: Operation, operator: str, default: str) -> str:
        opening = ident(str(op.params.get("from") or op.params.get("opening")))
        closing = ident(str(op.params.get("to") or op.params.get("closing")))
        name = ident(str(op.params.get("as") or default))
        return (f"SELECT *, ({closing} {operator} {opening}) AS {name}\n"
                f"FROM {self._input(op)}")

    def _op_contribution(self, op: Operation) -> str:
        column = ident(str(op.params.get("column") or op.params.get("of")))
        partition = [ident(str(c)) for c in (op.params.get("by") or [])]
        over = (f" OVER (PARTITION BY {', '.join(partition)})" if partition else " OVER ()")
        name = ident(str(op.params.get("as") or "contribution_pct"))
        return (f"SELECT *, ({column} * 100.0) / NULLIF(SUM({column}){over}, 0) AS {name}\n"
                f"FROM {self._input(op)}")

    def _op_reconcile(self, op: Operation) -> str:
        parts = [ident(str(p)) for p in op.params["parts"]]
        whole = ident(str(op.params.get("whole") or op.params.get("total")))
        tolerance = float(op.params.get("tolerance") or 0.01)
        total = " + ".join(f"COALESCE({p}, 0)" for p in parts)
        return (
            f"SELECT *, ({total}) - {whole} AS \"difference\", "
            f"ABS(({total}) - {whole}) <= {self.bind(tolerance)} AS \"reconciles\"\n"
            f"FROM {self._input(op)}"
        )

    def _op_matrix(self, op: Operation) -> str:
        from_column = ident(str(op.params.get("from") or op.params.get("from_column")))
        to_column = ident(str(op.params.get("to") or op.params.get("to_column")))
        measure = op.params.get("measure") or op.params.get("value")
        value = f"SUM({ident(str(measure))})" if measure else "COUNT(*)"
        return (
            f"SELECT {from_column} AS \"from_state\", {to_column} AS \"to_state\",\n"
            f"       {value} AS \"value\",\n"
            f"       ({value} * 100.0) / NULLIF(SUM({value}) OVER "
            f"(PARTITION BY {from_column}), 0) AS \"share_pct\"\n"
            f"FROM {self._input(op)}\nGROUP BY {from_column}, {to_column}"
        )

    def _op_compare(self, op: Operation) -> str:
        left, right = self._input(op, 0), self._input(op, 1)
        keys = op.params.get("on") or op.params.get("keys")
        if isinstance(keys, str):
            keys = [keys]
        measures = [str(m) for m in
                    (op.params.get("measures") or op.params.get("columns"))]

        condition = " AND ".join(f"O.{ident(k)} = C.{ident(k)}" for k in keys)
        selected = [f"COALESCE(O.{ident(k)}, C.{ident(k)}) AS {ident(k)}" for k in keys]
        for measure in measures:
            quoted = ident(measure)
            selected += [
                f"O.{quoted} AS {ident(measure + '_opening')}",
                f"C.{quoted} AS {ident(measure + '_closing')}",
                f"(C.{quoted} - O.{quoted}) AS {ident(measure + '_change')}",
                f"((C.{quoted} - O.{quoted}) * 100.0) / NULLIF(ABS(O.{quoted}), 0) "
                f"AS {ident(measure + '_change_pct')}",
            ]
        # FULL OUTER: something present in only one period is a real finding —
        # an inner join here would silently drop every entry and every exit.
        return (f"SELECT {', '.join(selected)}\nFROM {left} O\n"
                f"FULL OUTER JOIN {right} C ON {condition}")

    def _op_flow(self, op: Operation) -> str:
        return self._two_column_measure(op, "-", "flow")

    def _op_waterfall(self, op: Operation) -> str:
        column = ident(str(op.params.get("column") or op.params.get("of")))
        order = self._order_clause(op.params.get("order_by") or [])
        over = f" OVER (ORDER BY {order})" if order else " OVER ()"
        name = ident(str(op.params.get("as") or "step_value"))
        return (f"SELECT *, {column} AS {name}, "
                f"SUM({column}){over} AS \"cumulative\"\nFROM {self._input(op)}")

    def _op_cohort(self, op: Operation) -> str:
        column = ident(str(op.params.get("column") or op.params.get("of")))
        name = ident(str(op.params.get("as") or "cohort"))
        return f"SELECT *, {column} AS {name}\nFROM {self._input(op)}"

    def _op_vintage(self, op: Operation) -> str:
        opened = ident(str(op.params.get("opened") or op.params.get("from")))
        observed = ident(str(op.params.get("observed") or op.params.get("to")))
        name = ident(str(op.params.get("as") or "months_on_book"))
        return (f"SELECT *, DATE_DIFF('month', CAST({opened} AS DATE), "
                f"CAST({observed} AS DATE)) AS {name}\nFROM {self._input(op)}")

    def _op_distribution(self, op: Operation) -> str:
        column = ident(str(op.params["column"]))
        buckets = int(op.params.get("buckets") or 10)
        return (
            f"SELECT CAST(FLOOR({column} / NULLIF(_cp_width, 0)) AS BIGINT) "
            f"AS \"bucket\",\n"
            f"       COUNT(*) AS \"count\",\n"
            f"       (COUNT(*) * 100.0) / SUM(COUNT(*)) OVER () AS \"share_pct\"\n"
            f"FROM (SELECT *, (MAX({column}) OVER () - MIN({column}) OVER ()) "
            f"/ {buckets}.0 AS _cp_width FROM {self._input(op)})\n"
            f"GROUP BY 1\nORDER BY 1"
        )

    def _op_percentile(self, op: Operation) -> str:
        column = ident(str(op.params["column"]))
        quantiles = [float(q) for q in
                     (op.params.get("quantiles") or op.params.get("q") or [0.25, 0.5, 0.75])]
        keys = [ident(str(k)) for k in (op.params.get("by") or [])]
        measures = [
            f"QUANTILE_CONT({column}, {self.bind(q)}) AS \"p{int(q * 100)}\""
            for q in quantiles
        ]
        selected = ", ".join([*keys, *measures])
        group_by = f"\nGROUP BY {', '.join(keys)}" if keys else ""
        return f"SELECT {selected}\nFROM {self._input(op)}{group_by}"

    _op_quantile = _op_percentile

    def _op_visualize(self, op: Operation) -> str:
        # Declares a chart; changes no number. Passing rows straight through is
        # what makes that guarantee structural rather than a promise.
        return f"SELECT *\nFROM {self._input(op)}"


def _scalar_sql(function: str, args: list[str], compiler: Compiler) -> str:
    """SQL for one scalar function. Every mapping is written here, by hand."""
    def arg(index: int) -> str:
        try:
            return args[index]
        except IndexError:
            raise PlanError(
                f"'{function}' was given {len(args)} arguments and needs more."
            ) from None

    binary = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/",
              "mod": "%", "eq": "=", "ne": "<>", "lt": "<", "lte": "<=",
              "gt": ">", "gte": ">=", "and": "AND", "or": "OR"}
    if function in binary:
        return "(" + f" {binary[function]} ".join(args) + ")"

    simple = {"abs": "ABS", "floor": "FLOOR", "ceil": "CEIL", "sqrt": "SQRT",
              "exp": "EXP", "ln": "LN", "lower": "LOWER", "upper": "UPPER",
              "trim": "TRIM", "length": "LENGTH", "year": "YEAR",
              "quarter": "QUARTER", "month": "MONTH", "day": "DAY",
              "least": "LEAST", "greatest": "GREATEST", "coalesce": "COALESCE",
              "nullif": "NULLIF", "concat": "CONCAT", "round": "ROUND",
              "power": "POWER", "log": "LOG"}
    if function in simple:
        return f"{simple[function]}({', '.join(args)})"

    if function == "negate":
        return f"(-{arg(0)})"
    if function == "not":
        return f"(NOT {arg(0)})"
    if function == "is_null":
        return f"({arg(0)} IS NULL)"
    if function == "is_not_null":
        return f"({arg(0)} IS NOT NULL)"
    if function in ("safe_divide", "pct_change"):
        if function == "safe_divide":
            return f"({arg(0)} / NULLIF({arg(1)}, 0))"
        # (new - old) / |old|, as a percentage, undefined when old is zero.
        return f"((({arg(1)} - {arg(0)}) * 100.0) / NULLIF(ABS({arg(0)}), 0))"
    if function == "in_list":
        return f"({arg(0)} IN ({', '.join(args[1:])}))"
    if function == "like":
        return f"(CAST({arg(0)} AS VARCHAR) ILIKE {arg(1)})"
    if function == "substring":
        return f"SUBSTRING({arg(0)}, {arg(1)}, {arg(2)})"
    if function == "date_diff":
        # unit, start, end — the unit is a bound value, not spliced text.
        return f"DATE_DIFF({arg(0)}, CAST({arg(1)} AS DATE), CAST({arg(2)} AS DATE))"
    if function == "date_add":
        return f"(CAST({arg(0)} AS DATE) + INTERVAL ({arg(1)}) DAY)"
    if function == "period_year":
        # "Q1 2026" -> 2026. The period label format is governed, so this is a
        # property of the data model rather than a guess about strings.
        return f"CAST(RIGHT(CAST({arg(0)} AS VARCHAR), 4) AS INTEGER)"
    if function == "period_quarter":
        return f"CAST(SUBSTRING(CAST({arg(0)} AS VARCHAR), 2, 1) AS INTEGER)"
    if function == "period_offset":
        raise PlanError(
            "'period_offset' is not available inside an expression. Scan the "
            "period you want and compare the two."
        )
    if function.startswith("cast_"):
        sql_type = {"cast_number": "DOUBLE", "cast_text": "VARCHAR",
                    "cast_date": "DATE", "cast_boolean": "BOOLEAN"}[function]
        return f"TRY_CAST({arg(0)} AS {sql_type})"

    raise PlanError(f"'{function}' has no SQL implementation in the runtime.")


def _indent(text: str) -> str:
    return "\n".join("  " + line for line in text.splitlines())


def compile_plan(plan: AnalyticalPlan, report: ValidationReport, *,
                 limits: Limits = DEFAULT_LIMITS, source: Any = None) -> CompiledQuery:
    """Compile a validated plan. The only entry point callers should use."""
    return Compiler(plan, report, limits=limits, source=source).compile()


__all__ = ["CompiledQuery", "Compiler", "compile_plan", "ident"]
