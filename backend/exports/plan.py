"""
Reading a persisted Analytical IR as an audit trail.

The IR is the plan the runtime actually executed: a list of named operations,
each with its inputs and its parameters. It is precise and it is not English.
An Internal Audit reviewer opening the calculation pack needs both — the exact
operation, so the pack is checkable, and a sentence saying what it did, so the
pack is readable.

This module turns one stored plan into the records the workbook's sheets are
made of: what was read, what was joined and on which keys, what was filtered
out, what was derived, and what each step meant. It reads; it never plans and
never executes. Where the IR does not say something — a relationship version
that was not stamped, a cardinality nobody recorded — the field is left empty
rather than inferred, because a plausible guess in an audit pack is worse than
a blank.

Certified engine analyses have no IR. `read()` returns an empty view for those
and the workbook says the analysis ran a registered method instead, which is
the truth and is more useful than twenty blank sheets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Operations that shape rows without combining tables or aggregating them.
#: These become the TRANSFORMATIONS sheet.
TRANSFORMS = {
    "DERIVE", "CAST", "NORMALIZE", "DEDUPLICATE", "SELECT", "SEGMENT",
    "BUCKET", "COHORT", "VINTAGE", "PIVOT", "UNPIVOT", "CROSSTAB",
    "RATIO", "DELTA", "GROWTH", "CONTRIBUTION", "LAG", "LEAD", "ROLLING",
    "MOVING_AVERAGE", "RANK", "WINDOW", "PERCENTILE", "QUANTILE",
}

#: Operations that reduce many rows to fewer.
AGGREGATIONS = {"GROUP", "AGGREGATE", "DISTINCT_COUNT", "AGGREGATE_BEFORE_JOIN"}

#: Operations that combine two tables.
COMBINES = {"JOIN", "ASOF_JOIN", "UNION", "APPEND", "COMPARE"}

#: Operations that order or cut the result.
ORDERING = {"SORT", "LIMIT", "TOP_N", "BOTTOM_N"}


@dataclass
class Scan:
    """One governed dataset read, and the columns read from it."""

    id: str = ""
    dataset: str = ""
    period: str = ""
    alias: str = ""
    fields: list[str] = field(default_factory=list)


@dataclass
class Join:
    """One governed join, as the plan recorded it."""

    id: str = ""
    kind: str = "JOIN"
    label: str = ""
    left: str = ""
    right: str = ""
    left_keys: list[str] = field(default_factory=list)
    right_keys: list[str] = field(default_factory=list)
    how: str = ""
    cardinality: str = ""
    relationship: str = ""
    relationship_version: str = ""
    as_of: str = ""
    meaning: str = ""
    authoritative: str = ""

    @property
    def keys(self) -> str:
        pairs = list(zip(self.left_keys, self.right_keys, strict=False))
        if pairs:
            return ", ".join(f"{a} = {b}" for a, b in pairs)
        return ", ".join(self.left_keys or self.right_keys)


@dataclass
class Condition:
    """One filter or exclusion, in the words a reviewer would use."""

    id: str = ""
    sequence: int = 0
    field_name: str = ""
    operator: str = ""
    value: str = ""
    meaning: str = ""
    origin: str = ""


@dataclass
class Step:
    """One operation in the plan, described twice: exactly, and in English."""

    id: str = ""
    op: str = ""
    label: str = ""
    inputs: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    meaning: str = ""
    formula: str = ""
    outputs: list[str] = field(default_factory=list)
    unit: str = ""
    kernel: str = ""

    @property
    def is_kernel(self) -> bool:
        return bool(self.kernel)


@dataclass
class PlanView:
    """A persisted plan, decomposed into the shapes the workbook needs."""

    steps: list[Step] = field(default_factory=list)
    scans: list[Scan] = field(default_factory=list)
    joins: list[Join] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    grain: str = ""
    period: str = ""
    top_n: int = 0
    explanation: str = ""

    @property
    def empty(self) -> bool:
        return not self.steps

    def fields_for(self, dataset: str) -> list[str]:
        """Every column read from one dataset, in plan order and deduplicated."""
        seen: list[str] = []
        for scan in self.scans:
            if scan.dataset != dataset:
                continue
            for name in scan.fields:
                if name not in seen:
                    seen.append(name)
        return seen

    def transformations(self) -> list[Step]:
        return [s for s in self.steps if s.op in TRANSFORMS]

    def by_id(self, step_id: str) -> Step | None:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None


# ------------------------------------------------------------------ reading


def read(ir: dict[str, Any], *, kernel_steps: list[dict[str, Any]] | None = None) -> PlanView:
    """Decompose one stored Analytical IR.

    `kernel_steps` is the executor's record of which operations ran in an
    approved numerical kernel rather than in SQL. It is carried through so the
    pack can say which is which — "computed in SQL over the governed data" and
    "computed by the approved trend kernel over the SQL result" are different
    claims and a model-risk reviewer needs to see which one applies.
    """
    view = PlanView()
    if not ir:
        return view

    meta = dict(ir.get("meta") or {})
    view.grain = str(meta.get("grain") or "")
    view.period = str(meta.get("period") or "")
    view.top_n = int(meta.get("top_n") or 0)
    view.explanation = str(meta.get("explanation") or "")

    kernels = {
        str(entry.get("id") or entry.get("op") or ""): str(entry.get("kernel") or "")
        for entry in (kernel_steps or [])
        if isinstance(entry, dict)
    }

    sequence = 0
    for raw in ir.get("operations") or []:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "").upper()
        params = dict(raw.get("params") or {})
        step = Step(
            id=str(raw.get("id") or ""),
            op=op,
            label=str(raw.get("label") or ""),
            inputs=[str(i) for i in (raw.get("inputs") or [])],
            params=params,
            meaning=meaning(op, params),
            formula=formula(op, params),
            outputs=outputs(op, params),
            unit=str(params.get("unit") or ""),
            kernel=kernels.get(str(raw.get("id") or ""), ""),
        )
        view.steps.append(step)

        if op == "SCAN":
            view.scans.append(Scan(
                id=step.id,
                dataset=str(params.get("dataset") or ""),
                period=str(params.get("period") or ""),
                alias=str(params.get("alias") or ""),
                fields=[str(f) for f in (params.get("fields") or [])],
            ))
        elif op in {"JOIN", "ASOF_JOIN"}:
            view.joins.append(_join(step, meta))
        elif op == "FILTER":
            for condition in _conditions(step, meta):
                sequence += 1
                condition.sequence = sequence
                view.conditions.append(condition)

    _fill_join_sides(view)
    return view


def _join(step: Step, meta: dict[str, Any]) -> Join:
    """One join, preferring what the planner recorded about the relationship.

    The operation's own parameters say how the join was executed; the plan's
    `join_path` says which governed relationship authorised it, at which
    version, with what cardinality and what it means in the business. An audit
    pack needs the second, so the path entry wins wherever it has an opinion.
    """
    params = step.params
    path = _path_entry(meta, step.id)
    left_keys, right_keys = _keys(params, path)
    return Join(
        id=step.id,
        kind=step.op,
        label=step.label,
        left=str(path.get("from") or (step.inputs[0] if step.inputs else "")),
        right=str(path.get("to") or (step.inputs[1] if len(step.inputs) > 1 else "")),
        left_keys=left_keys,
        right_keys=right_keys,
        how=str(params.get("kind") or params.get("how") or path.get("policy") or ""),
        cardinality=str(path.get("cardinality") or params.get("cardinality") or ""),
        relationship=str(path.get("relationship_name") or params.get("relationship") or ""),
        relationship_version=str(
            path.get("relationship_version") or params.get("relationship_version") or ""
        ),
        as_of=str(path.get("temporal_rule") or params.get("direction") or ""),
        meaning=str(path.get("semantic") or params.get("means") or step.label),
        authoritative=("aggregated before joining" if path.get("aggregated_first")
                       else ""),
    )


def _keys(params: dict[str, Any], path: dict[str, Any]) -> tuple[list[str], list[str]]:
    """The join keys as two aligned lists.

    `on` is written as a list of {left, right} pairs; a plan that wrote a bare
    column name or a single pair is read the same way rather than rejected.
    """
    left: list[str] = []
    right: list[str] = []
    on = params.get("on")
    if isinstance(on, dict):
        on = [on]
    for entry in on or []:
        if isinstance(entry, dict):
            left.append(str(entry.get("left") or entry.get("column") or ""))
            right.append(str(entry.get("right") or entry.get("column") or ""))
        else:
            left.append(str(entry))
            right.append(str(entry))
    if not left:
        left = [str(k) for k in (params.get("left_on") or [])]
        right = [str(k) for k in (params.get("right_on") or [])]
    if not left:
        keys = [str(k) for k in (path.get("keys") or [])]
        if len(keys) == 2:
            left, right = [keys[0]], [keys[1]]
        else:
            left = right = keys
    return [k for k in left if k], [k for k in right if k]


def _path_entry(meta: dict[str, Any], step_id: str) -> dict[str, Any]:
    """The governed relationship the planner chose for this join, if it stamped one."""
    for entry in meta.get("join_path") or []:
        if isinstance(entry, dict) and str(entry.get("step") or "") == step_id:
            return entry
    return {}


def _fill_join_sides(view: PlanView) -> None:
    """Name each join's sides by dataset rather than by step id where possible.

    "portfolio_facility joined to customer_ratings" is a sentence a credit
    officer can check. "source joined to right_1" is not.
    """
    dataset_of = {scan.id: scan.dataset for scan in view.scans}
    produced: dict[str, str] = dict(dataset_of)
    for step in view.steps:
        if step.id in produced:
            continue
        upstream = [produced.get(i, "") for i in step.inputs]
        named = [u for u in upstream if u]
        if named:
            produced[step.id] = named[0] if len(set(named)) == 1 else " + ".join(
                dict.fromkeys(named)
            )
    for join in view.joins:
        join.left = produced.get(join.left, join.left)
        join.right = produced.get(join.right, join.right)


def _conditions(step: Step, meta: dict[str, Any]) -> list[Condition]:
    """One FILTER operation as one row per predicate.

    A FILTER carries a list of predicates; the sheet wants a row each, because
    "Stage in {2,3}" and "sector = Real Estate" remove different populations and
    a reviewer asks about them separately.
    """
    stated = {
        str(entry.get("field") or ""): entry
        for entry in meta.get("filters") or []
        if isinstance(entry, dict)
    }
    out: list[Condition] = []
    predicates = (step.params.get("where") or step.params.get("predicates")
                  or step.params.get("conditions") or [])
    if isinstance(predicates, dict):
        predicates = [predicates]
    for predicate in predicates:
        if not isinstance(predicate, dict):
            continue
        name = str(predicate.get("field") or predicate.get("column") or "")
        known = stated.get(name, {})
        out.append(Condition(
            id=step.id,
            field_name=name,
            operator=str(predicate.get("op") or predicate.get("operator") or "="),
            value=_value(predicate.get("value")),
            meaning=str(predicate.get("means") or known.get("means") or step.label),
            origin=str(predicate.get("origin") or known.get("origin") or "requested"),
        ))
    if not out and step.label:
        out.append(Condition(id=step.id, operator="", value="",
                             meaning=step.label, origin="requested"))
    return out


def _value(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    if value is None:
        return ""
    return str(value)


# ------------------------------------------------------ English for one step


def meaning(op: str, params: dict[str, Any]) -> str:
    """What this operation did, in a sentence a credit officer would check.

    Written from the parameters rather than from the planner's label, so a step
    whose label was authored by the model is still described by what it
    actually asked the runtime to do.
    """
    p = params
    if op == "SCAN":
        fields = ", ".join(str(f) for f in (p.get("fields") or []))
        where = f" at {p.get('period')}" if p.get("period") else ""
        return (f"Read {p.get('dataset', 'the dataset')}{where}"
                + (f", taking {fields}." if fields else "."))
    if op == "METHOD":
        return (f"Ran the certified method {p.get('method', '')}"
                + (f" version {p.get('version')}" if p.get("version") else "") + ".")
    if op == "FILTER":
        return "Kept only the rows matching the stated conditions."
    if op == "SELECT":
        return "Kept only the columns needed downstream."
    if op == "DERIVE":
        return f"Added {_named(p, 'as')} from the columns already present."
    if op == "CAST":
        return f"Changed the type of {_named(p, 'column')} to {p.get('to', '')}."
    if op == "NORMALIZE":
        return f"Rescaled {_named(p, 'column')} using {p.get('method', 'a scaling rule')}."
    if op == "DEDUPLICATE":
        return f"Reduced to one row per {_list(p.get('by'))}."
    if op == "GROUP":
        return (f"Grouped by {_list(p.get('by')) or 'the whole population'} and "
                f"{_aggregates(p)} within each group.")
    if op == "AGGREGATE":
        return f"Reduced the whole table to one row, {_aggregates(p)}."
    if op == "DISTINCT_COUNT":
        return f"Counted the distinct values of {_named(p, 'column')}."
    if op == "AGGREGATE_BEFORE_JOIN":
        return (f"Rolled the table up to one row per {_list(p.get('by'))} BEFORE "
                "joining, so the join could not multiply rows.")
    if op == "RECONCILE_GRAIN":
        return f"Brought this side to {p.get('grain', 'the output grain')}."
    if op == "TEMPORAL_ALIGN":
        return ("Mapped the reporting period onto the source's own cycle using "
                f"the rule {p.get('rule', 'as recorded')}, so a period the "
                "source had not yet published is not read as missing.")
    if op == "RELATIONSHIP_PATH":
        return "Recorded the governed path between the datasets. Computes nothing."
    if op == "JOIN":
        left, right = _keys(p, {})
        pairs = ", ".join(f"{a} = {b}" for a, b in zip(left, right, strict=False))
        return f"Joined on {pairs or 'the governed keys'} ({p.get('kind') or p.get('how') or 'inner'})."
    if op == "ASOF_JOIN":
        return ("Matched each row to the latest right-hand row on or before the "
                "reporting date, so no future data was used.")
    if op in {"UNION", "APPEND"}:
        return ("Stacked the two results." if op == "APPEND"
                else "Combined the two results and removed duplicates.")
    if op == "WINDOW":
        return f"Computed {p.get('function', 'a window function')} across the population."
    if op == "RATIO":
        return f"Divided {_named(p, 'numerator')} by {_named(p, 'denominator')}, guarding zero."
    if op == "DELTA":
        return f"Took the absolute change in {_named(p, 'column')}."
    if op == "GROWTH":
        return f"Took the percentage change in {_named(p, 'column')}."
    if op == "CONTRIBUTION":
        return f"Took each row's share of the total movement in {_named(p, 'column')}."
    if op == "RECONCILE":
        return "Asserted that the parts sum to the whole."
    if op == "SORT":
        return f"Ordered by {_sort(p)}."
    if op in {"LIMIT", "TOP_N", "BOTTOM_N"}:
        end = "smallest" if op == "BOTTOM_N" else "largest"
        return f"Kept {p.get('n') or p.get('limit') or ''} rows, {end} first."
    if op == "RANK":
        return f"Ranked rows by {_named(p, 'column')}."
    if op in {"LAG", "LEAD"}:
        return f"Took the {'previous' if op == 'LAG' else 'next'} period's {_named(p, 'column')}."
    if op in {"ROLLING", "MOVING_AVERAGE"}:
        return f"Averaged {_named(p, 'column')} over {p.get('window', 'a moving window')}."
    if op in {"SEGMENT", "BUCKET", "COHORT", "VINTAGE"}:
        return f"Labelled each row by {_named(p, 'by') or _named(p, 'column')}."
    if op == "COMPARE":
        return "Placed the two periods side by side on the shared key."
    if op == "FLOW":
        return "Traced the movement from the opening position to the closing position."
    if op in {"DISTRIBUTION", "PERCENTILE", "QUANTILE"}:
        return f"Described the distribution of {_named(p, 'column')}."
    if op == "TREND":
        return f"Fitted the trend in {_named(p, 'column')} across the periods."
    if op == "CORRELATION":
        return (f"Measured the association between {_named(p, 'x')} and "
                f"{_named(p, 'y')}. Association, not cause.")
    if op == "OUTLIER":
        return f"Identified rows where {_named(p, 'column')} sits outside the expected range."
    if op == "VISUALIZE":
        return "Declared the intended chart. Computes nothing."
    return ""


def formula(op: str, params: dict[str, Any]) -> str:
    """The step's arithmetic, where it has any that can be written down."""
    p = params
    if op == "RATIO":
        return (f"{p.get('numerator', 'numerator')} ÷ "
                f"NULLIF({p.get('denominator', 'denominator')}, 0)"
                + (" × 100" if p.get("as_percent") or str(p.get("as", "")).endswith("_pct")
                   else ""))
    if op == "DERIVE":
        return str(p.get("expression") or p.get("formula") or "")
    if op == "GROUP":
        return "; ".join(
            f"{a.get('as', a.get('column'))} = {str(a.get('function', '')).upper()}"
            f"({a.get('column')})"
            for a in (p.get("aggregates") or []) if isinstance(a, dict)
        )
    if op == "AGGREGATE":
        return "; ".join(
            f"{a.get('as', a.get('column'))} = {str(a.get('function', '')).upper()}"
            f"({a.get('column')})"
            for a in (p.get("aggregates") or []) if isinstance(a, dict)
        )
    if op == "WINDOW":
        return (f"{p.get('as', 'value')} = {str(p.get('function', '')).upper()}"
                f"({p.get('column')}) OVER ()")
    if op == "DELTA":
        return f"{p.get('as', 'change')} = closing {p.get('column')} − opening {p.get('column')}"
    if op == "GROWTH":
        return (f"{p.get('as', 'growth')} = (closing {p.get('column')} − opening "
                f"{p.get('column')}) ÷ NULLIF(opening {p.get('column')}, 0) × 100")
    if op == "NORMALIZE":
        return str(p.get("method") or "")
    return ""


def outputs(op: str, params: dict[str, Any]) -> list[str]:
    """The columns this step added, where it adds named columns."""
    named: list[str] = []
    for key in ("as", "output", "column_out"):
        if params.get(key):
            named.append(str(params[key]))
    for entry in params.get("aggregates") or []:
        if isinstance(entry, dict):
            named.append(str(entry.get("as") or entry.get("column") or ""))
    if op == "GROUP":
        named = [str(b) for b in (params.get("by") or [])] + named
    return [n for n in named if n]


def _named(params: dict[str, Any], key: str) -> str:
    return str(params.get(key) or "")


def _list(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    return str(value or "")


def _sort(params: dict[str, Any]) -> str:
    """A SORT's key list as words. Each key carries its own direction."""
    parts: list[str] = []
    for entry in params.get("by") or []:
        if isinstance(entry, dict):
            column = str(entry.get("column") or "")
            down = str(entry.get("direction") or "desc").lower().startswith("desc")
            parts.append(f"{column} {'largest first' if down else 'smallest first'}")
        else:
            parts.append(str(entry))
    return ", ".join(parts) or "the natural order"


def _aggregates(params: dict[str, Any]) -> str:
    parts: list[str] = []
    for entry in params.get("aggregates") or []:
        if not isinstance(entry, dict):
            continue
        function = str(entry.get("function") or "").lower()
        column = str(entry.get("column") or "")
        word = {"sum": "summed", "avg": "averaged", "mean": "averaged",
                "min": "took the minimum of", "max": "took the maximum of",
                "count": "counted", "nunique": "counted the distinct"}.get(
                    function, f"applied {function} to")
        parts.append(f"{word} {column}")
    return "; ".join(parts) or "aggregated the measures"
