"""
Running a plan, and recording exactly what ran.

The order of operations here is the governance argument, and it is deliberate:

    parse -> validate -> compile -> execute -> trace

Nothing is compiled that did not validate, and nothing executes that was not
compiled from a validated plan. There is no branch in this module where a plan
reaches DuckDB without passing through `validate`, which is what lets the
product claim the language model cannot run arbitrary queries: the model's
output is data until this file turns it into SQL, and this file will not do that
for a plan the catalogue rejected.

The Trace is emitted as execution happens, one node per operation, carrying what
that step actually did — the query, the parameters kept separate from it, the
rows in and out, how long it took, and a hash. It is evidence rather than a
description, because a description is written by whoever is describing.

Hybrid execution
----------------
SQL first, kernels after. DuckDB does the reading, joining, filtering and
aggregating — the part that touches millions of rows and has an optimiser — and
an allowlisted Python kernel runs on the small result that comes back. The Trace
shows both runtimes, so "which engine produced this figure" is answered by
looking.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.runtime.compiler import CompiledQuery, compile_plan
from backend.runtime.ir import AnalyticalPlan, Operation, OpType, PlanError
from backend.runtime.kernels import kernel_for, run_kernel
from backend.runtime.validation import (
    DEFAULT_LIMITS,
    Limits,
    PlanRejected,
    ValidationReport,
    validate,
)
from backend.trace.model import NodeType, TraceGraph, TraceNode

logger = logging.getLogger(__name__)

#: How many rows travel back with the result for the preview grid. The full
#: result stays server-side; anything larger is an export.
PREVIEW_ROWS = 200


# ------------------------------------------------------------ the certification


class ExecutionClass:
    """How much a result may claim for itself.

    The distinction is the point of having both. A certified method has an
    explicit methodology, tested implementation and golden cases behind it, and
    earns the double tick. A composed plan is governed — every dataset and field
    was checked, every value bound — but nobody has validated *this particular
    composition*, and saying otherwise would make the tick meaningless.
    """

    CERTIFIED = "certified"
    DYNAMIC = "dynamic"

    LABELS = {
        CERTIFIED: "CreditProbe Certified",
        DYNAMIC: "Dynamic Analysis · Governed Runtime",
    }


# ----------------------------------------------------------------- the result


@dataclass
class RuntimeResult:
    """What every execution returns, whatever ran underneath it."""

    run_id: str
    plan: AnalyticalPlan
    columns: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    certification: str = ExecutionClass.DYNAMIC
    #: The certified methods this run used, if any.
    methods: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    query: CompiledQuery | None = None
    graph: TraceGraph | None = None
    duration_ms: int = 0
    chart: dict[str, Any] = field(default_factory=dict)

    @property
    def certification_label(self) -> str:
        return ExecutionClass.LABELS.get(self.certification, self.certification)

    def to_dict(self, *, include_sql: bool = True) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "plan": self.plan.to_dict(),
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "summary": self.summary,
            "warnings": self.warnings,
            "certification": self.certification,
            "certification_label": self.certification_label,
            "methods": self.methods,
            "datasets": self.datasets,
            "duration_ms": self.duration_ms,
            "chart": self.chart,
            "query": self.query.to_dict() if (self.query and include_sql) else None,
            "trace": self.graph.to_dict() if self.graph else None,
        }


class ExecutionError(PlanError):
    """A validated plan that failed while running."""


# ------------------------------------------------------------------ the runner


def execute(plan: AnalyticalPlan | dict[str, Any], *,
            limits: Limits = DEFAULT_LIMITS,
            certification: str = ExecutionClass.DYNAMIC,
            question: str = "",
            intent: str = "",
            source: Any = None) -> RuntimeResult:
    """Validate, compile and run one plan.

    The single entry point. Every caller — Ask CreditProbe, a saved method, a
    Trace modification, a test — comes through here, so the checks cannot be
    bypassed by adding a caller.
    """
    started = time.perf_counter()
    run_id = uuid.uuid4().hex[:16]

    if isinstance(plan, dict):
        plan = AnalyticalPlan.from_dict(plan)

    report = validate(plan, limits=limits).raise_if_bad()
    query = compile_plan(plan, report, limits=limits, source=source)

    graph = TraceGraph()
    cursor = _trace_preamble(graph, plan, question, intent, report)

    frame, sql_node = _run_sql(graph, cursor, plan, query, limits)
    cursor = sql_node

    for operation in query.kernel_steps:
        frame, cursor = _run_kernel_step(graph, cursor, operation, frame)

    duration_ms = int((time.perf_counter() - started) * 1000)
    result = _shape(run_id, plan, frame, query, report, certification, duration_ms)

    _trace_result(graph, cursor, result)
    graph.compute_hashes()
    result.graph = graph
    return result


# ------------------------------------------------------------------- tracing


def _trace_preamble(graph: TraceGraph, plan: AnalyticalPlan, question: str,
                    intent: str, report: ValidationReport) -> str:
    """The nodes above the query: question, intent, plan, domains, datasets.

    Emitted before anything runs, because they describe what was decided rather
    than what happened — and because a plan that fails should still show a
    reader what it was going to do.
    """
    from backend.data_access.catalog import get_catalog

    previous = ""
    if question:
        graph.add_node(TraceNode(id="question", type=NodeType.USER_PROMPT,
                                 label="Question asked",
                                 config={"question": question}))
        previous = "question"

    if intent:
        graph.add_node(TraceNode(id="intent", type=NodeType.LLM_INTENT,
                                 label="Reading of the question",
                                 config={"intent": intent}))
        if previous:
            graph.connect(previous, "intent")
        previous = "intent"

    graph.add_node(TraceNode(
        id="plan", type=NodeType.PLAN,
        label=f"Analytical plan · {len(plan.operations)} steps",
        config={
            "objective": plan.objective,
            "operations": [o.to_dict() for o in plan.ordered()],
            "fingerprint": plan.fingerprint(),
            "warnings": report.warnings,
        },
    ))
    if previous:
        graph.connect(previous, "plan")
    previous = "plan"

    catalog = get_catalog()
    seen_domains: set[str] = set()
    for name in plan.datasets():
        try:
            spec = catalog.dataset(name)
        except Exception:  # pragma: no cover - validation already refused it
            continue

        if spec.domain not in seen_domains:
            seen_domains.add(spec.domain)
            domain_id = f"domain_{len(seen_domains)}"
            graph.add_node(TraceNode(id=domain_id, type=NodeType.DATA_DOMAIN,
                                     label=spec.domain,
                                     config={"domain": spec.domain}))
            graph.connect(previous, domain_id)

        family_id = f"family_{spec.family}"
        if family_id not in graph.nodes:
            graph.add_node(TraceNode(
                id=family_id, type=NodeType.DATASET_FAMILY, label=spec.family,
                config={"family": spec.family, "grain": spec.grain,
                        "primary_keys": list(spec.primary_keys)},
            ))
            graph.connect(previous, family_id)

        periods = sorted({
            str(o.params.get("period")) for o in plan.operations
            if o.op is OpType.SCAN and o.params.get("dataset") == name
            and o.params.get("period")
        })
        dataset_id = f"dataset_{name}"
        if dataset_id not in graph.nodes:
            fields = sorted(report.schemas.get(
                next(o.id for o in plan.operations
                     if o.op is OpType.SCAN and o.params.get("dataset") == name),
                None,
            ).columns) if report.schemas else []
            node = graph.add_node(TraceNode(
                id=dataset_id, type=NodeType.DATASET,
                label=f"{spec.business_name or name}"
                      + (f" · {', '.join(periods)}" if periods else ""),
                config={
                    "dataset": name, "domain": spec.domain, "family": spec.family,
                    "periods": periods, "origin": spec.origin,
                    "is_synthetic": spec.is_synthetic, "version": spec.version,
                    "grain": spec.grain,
                },
                dataset=name, fields_used=fields,
            ))
            node.mark_ok()
            graph.connect(family_id, dataset_id)
            previous = dataset_id

    return previous


def _step_node_type(op: Operation) -> NodeType:
    return {
        OpType.FILTER: NodeType.FILTER,
        OpType.JOIN: NodeType.JOIN,
        OpType.DERIVE: NodeType.DERIVED_VARIABLE,
        OpType.RATIO: NodeType.DERIVED_VARIABLE,
        OpType.DELTA: NodeType.DERIVED_VARIABLE,
        OpType.GROWTH: NodeType.DERIVED_VARIABLE,
        OpType.BUCKET: NodeType.DERIVED_VARIABLE,
        OpType.GROUP: NodeType.AGGREGATION,
        OpType.AGGREGATE: NodeType.AGGREGATION,
        OpType.DISTINCT_COUNT: NodeType.AGGREGATION,
        OpType.PERCENTILE: NodeType.AGGREGATION,
        OpType.WINDOW: NodeType.WINDOW,
        OpType.LAG: NodeType.WINDOW,
        OpType.LEAD: NodeType.WINDOW,
        OpType.RANK: NodeType.WINDOW,
        OpType.ROLLING: NodeType.WINDOW,
        OpType.MOVING_AVERAGE: NodeType.WINDOW,
        OpType.METHOD: NodeType.CERTIFIED_METHOD,
        OpType.VISUALIZE: NodeType.VISUALIZATION,
    }.get(op.op, NodeType.TRANSFORMATION)


def _describe(op: Operation) -> str:
    """A short line for the Trace box, built from the parameters themselves.

    Not a label the model wrote: a model-supplied caption on a governed node is
    a place for a description to drift from what ran.
    """
    p = op.params
    if op.op is OpType.FILTER:
        conditions = p.get("where") or p.get("conditions") or []
        if isinstance(conditions, dict):
            conditions = [conditions]
        if conditions:
            first = conditions[0]
            more = f" (+{len(conditions) - 1} more)" if len(conditions) > 1 else ""
            return (f"Keep where {first.get('column')} "
                    f"{first.get('op', '=')} {first.get('value')}{more}")
        return "Filter"
    if op.op is OpType.JOIN:
        return f"{str(p.get('kind') or 'inner').title()} join on " + ", ".join(
            str(k if isinstance(k, str) else k.get("left")) for k in (p.get("on") or [])
        )
    if op.op in (OpType.GROUP, OpType.AGGREGATE):
        by = ", ".join(str(k) for k in (p.get("by") or p.get("group_by") or []))
        measures = p.get("aggregates") or p.get("measures") or []
        return (f"Aggregate by {by}" if by else "Aggregate") + f" · {len(measures)} measures"
    if op.op is OpType.DERIVE:
        columns = p.get("columns") or p.get("derive") or []
        names = [str(c.get("as") or c.get("name")) for c in columns
                 if isinstance(c, dict)]
        return "Derive " + ", ".join(names)
    if op.op in (OpType.TOP_N, OpType.BOTTOM_N):
        return f"{'Top' if op.op is OpType.TOP_N else 'Bottom'} {p.get('n')} by {p.get('by')}"
    if op.op is OpType.RATIO:
        return f"{p.get('as') or 'ratio'} = {p.get('numerator')} / {p.get('denominator')}"
    if op.op is OpType.SORT:
        return "Sort"
    if op.op is OpType.LIMIT:
        return f"First {p.get('n')}"
    return str(op.op).replace("_", " ").title()


def _run_sql(graph: TraceGraph, parent: str, plan: AnalyticalPlan,
             query: CompiledQuery, limits: Limits) -> tuple[pd.DataFrame, str]:
    """Execute the compiled statement and record it.

    One node per plan operation, so the Trace reads like the plan, plus one
    SQL_QUERY node carrying the statement actually sent. The per-operation
    nodes are configuration; the query node is the evidence.
    """
    from backend.data_access.duckdb_source import DuckDBSource

    # One node per operation, in the order the CTEs were emitted, so the Trace
    # reads like the plan rather than like the SQL.
    previous = parent
    for op_id in query.steps:
        operation = plan.by_id(op_id)
        if operation.op is OpType.SCAN:
            # Already on the graph as a DATASET node, with its periods and
            # provenance. A second box saying the same thing is clutter.
            continue
        node = graph.add_node(TraceNode(
            id=f"op_{op_id}", type=_step_node_type(operation),
            label=operation.label or _describe(operation),
            config={"operation": str(operation.op), "id": op_id,
                    **operation.to_dict()["params"]},
        ))
        node.mark_ok()
        if previous:
            graph.connect(previous, f"op_{op_id}")
        previous = f"op_{op_id}"

    node = graph.add_node(TraceNode(
        id="sql", type=NodeType.SQL_QUERY,
        label="DuckDB query",
        config={
            "engine": "duckdb",
            "sql": query.sql,
            # Kept apart from the statement on purpose. A reader can see that no
            # value was ever spliced into the text.
            "parameters": list(query.params),
            "parameter_count": len(query.params),
            "datasets": list(query.datasets),
        },
    ))
    if previous:
        graph.connect(previous, "sql")
    node.mark_started()

    started = time.perf_counter()
    try:
        source = DuckDBSource()
        with source._lock:  # the same guard every governed read uses
            connection = source._conn
            # DuckDB has no statement timeout, so the guard is a watchdog that
            # interrupts the connection. Without one, a plan that turns out to
            # be a cartesian product takes the process rather than the request.
            watchdog = threading.Timer(
                float(limits.timeout_seconds), connection.interrupt)
            watchdog.daemon = True
            watchdog.start()
            try:
                frame = connection.execute(query.sql, query.params).fetch_df()
            finally:
                watchdog.cancel()
    except Exception as e:
        node.mark_failed(str(e))
        raise ExecutionError(
            "The analysis could not be completed against the governed data. "
            f"{_readable(e)}"
        ) from e

    node.rows_out = int(len(frame))
    node.output_summary = {
        "columns": list(frame.columns),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    node.mark_ok(rows_out=int(len(frame)))
    return frame, "sql"


def _run_kernel_step(graph: TraceGraph, parent: str, op: Operation,
                     frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Run one allowlisted numerical operation on the query's result."""
    kernel = kernel_for(op)
    node = graph.add_node(TraceNode(
        id=f"kernel_{op.id}", type=NodeType.KERNEL,
        label=f"{kernel.name} · {op.label or op.id}",
        config={
            "engine": "python",
            "kernel": kernel.name,
            "summary": kernel.summary,
            "parameters": op.to_dict()["params"],
            "limitations": kernel.limitations,
        },
        function_id=kernel.name,
    ))
    graph.connect(parent, f"kernel_{op.id}")
    node.rows_in = int(len(frame))
    node.mark_started()

    try:
        out = run_kernel(kernel, frame, op.params)
    except PlanError as e:
        node.mark_failed(str(e))
        raise

    node.output_summary = {"columns": list(out.columns), "kernel": kernel.name}
    node.mark_ok(rows_out=int(len(out)))
    if kernel.limitations:
        node.warnings.append(kernel.limitations)
    return out, f"kernel_{op.id}"


def _trace_result(graph: TraceGraph, parent: str, result: RuntimeResult) -> None:
    node = graph.add_node(TraceNode(
        id="result", type=NodeType.RESULT,
        label=f"Result · {result.row_count:,} rows",
        config={
            "columns": [c["name"] for c in result.columns],
            "row_count": result.row_count,
            "truncated": result.truncated,
            "certification": result.certification,
            "certification_label": result.certification_label,
        },
        output_preview=result.rows[:5],
        output_summary=result.summary,
    ))
    node.mark_ok(rows_out=result.row_count)
    graph.connect(parent, "result")


# ------------------------------------------------------------------- shaping


def _shape(run_id: str, plan: AnalyticalPlan, frame: pd.DataFrame,
           query: CompiledQuery, report: ValidationReport,
           certification: str, duration_ms: int) -> RuntimeResult:
    """Turn the final frame into the Result contract."""
    truncated = len(frame) > PREVIEW_ROWS
    preview = frame.head(PREVIEW_ROWS)

    columns = []
    for name in frame.columns:
        series = frame[name]
        columns.append({
            "name": str(name),
            "type": _column_type(series),
            "origin": report.schemas.get(plan.output_id, None).columns.get(str(name), "")
            if report.schemas.get(plan.output_id) else "",
            "null_count": int(series.isna().sum()),
        })

    summary: dict[str, Any] = {"rows": int(len(frame))}
    for name in frame.columns:
        series = pd.to_numeric(frame[name], errors="coerce")
        if series.notna().sum() and series.notna().sum() >= 0.9 * len(frame):
            summary[str(name)] = {
                "sum": _finite(series.sum()),
                "mean": _finite(series.mean()),
                "min": _finite(series.min()),
                "max": _finite(series.max()),
            }

    return RuntimeResult(
        run_id=run_id,
        plan=plan,
        columns=columns,
        rows=[
            {k: _jsonable(v) for k, v in record.items()}
            for record in preview.to_dict(orient="records")
        ],
        row_count=int(len(frame)),
        truncated=truncated,
        summary=summary,
        warnings=list(report.warnings),
        certification=certification,
        methods=plan.methods(),
        datasets=list(query.datasets),
        query=query,
        duration_ms=duration_ms,
        chart=suggest_chart(plan, frame),
    )


def _column_type(series: pd.Series) -> str:
    kind = str(series.dtype)
    if kind.startswith(("int", "uint")):
        return "integer"
    if kind.startswith("float"):
        return "number"
    if kind.startswith("bool"):
        return "boolean"
    if "datetime" in kind:
        return "date"
    return "text"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number or number in (float("inf"), float("-inf")) else round(number, 6)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if value != value else value
    if pd.isna(value):
        return None
    return str(value)


def _readable(error: Exception) -> str:
    """Turn a database error into something a person can act on."""
    text = str(error)
    if "Out of Memory" in text or "memory" in text.lower():
        return ("The query needed more memory than the runtime allows. Narrow "
                "the period, add a filter, or aggregate earlier.")
    if any(w in text.lower() for w in ("timeout", "interrupt", "cancelled")):
        return ("The query took longer than the runtime allows. Narrow the "
                "period or aggregate before joining.")
    if "No files found" in text or "IO Error" in text:
        return ("The data for that period is not on disk. Check the period in "
                "Data Builder.")
    return text.split("\n")[0][:300]


# ------------------------------------------------------------ chart suggestion


def suggest_chart(plan: AnalyticalPlan, frame: pd.DataFrame) -> dict[str, Any]:
    """Pick a chart from the SHAPE of the result, never from its values.

    The distinction matters: the language model may say "draw this as a line",
    and that is a preference about presentation. It may not supply the points.
    Everything here reads column names, types and counts — never a number.
    """
    for operation in reversed(plan.operations):
        if operation.op is OpType.VISUALIZE:
            declared = dict(operation.params)
            declared.setdefault("chart", "table")
            declared["source"] = "declared in the plan"
            return declared

    if frame.empty:
        return {"chart": "table", "source": "no rows to draw"}

    numeric = [c for c in frame.columns
               if pd.api.types.is_numeric_dtype(frame[c])]
    categorical = [c for c in frame.columns if c not in numeric]
    rows = len(frame)

    period_like = [c for c in frame.columns
                   if str(c).lower() in ("period", "period_end_date", "date",
                                         "month", "quarter", "year", "reporting_period")]

    if period_like and numeric:
        return {"chart": "line", "x": period_like[0], "y": numeric[:3],
                "source": "a measure over an ordered period axis"}
    if rows == 1:
        return {"chart": "kpi", "value": numeric[:4],
                "source": "a single row of measures"}
    if {"from_state", "to_state"} <= set(frame.columns):
        return {"chart": "matrix", "x": "to_state", "y": "from_state",
                "value": "value", "source": "a from/to transition"}
    if {"bucket", "count"} <= set(frame.columns):
        return {"chart": "histogram", "x": "bucket", "y": "count",
                "source": "a distribution across buckets"}
    if categorical and numeric and rows <= 30:
        return {"chart": "bar", "x": categorical[0], "y": numeric[0],
                "source": "a small number of ranked categories"}
    if len(numeric) >= 2 and rows > 30:
        return {"chart": "scatter", "x": numeric[0], "y": numeric[1],
                "source": "two measures across many rows"}
    return {"chart": "table", "source": "no shape that a chart would clarify"}


__all__ = [
    "PREVIEW_ROWS",
    "ExecutionClass",
    "ExecutionError",
    "PlanRejected",
    "RuntimeResult",
    "execute",
    "suggest_chart",
]
