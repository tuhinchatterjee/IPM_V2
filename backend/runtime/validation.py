"""
Whether a plan may run.

This module is the security boundary of the whole pivot. Everything upstream of
it — the language model, the planner, a method definition somebody typed — is
untrusted input. Everything downstream compiles and executes. So every rule the
product depends on lives here, stated once:

    every dataset named is in the governed catalogue
    every column named exists on the input it is read from
    every function named is one the compiler can write
    every operator is from a fixed set
    every literal stays a bound parameter and never becomes SQL text
    every join is on real columns, with a kind the compiler knows
    nothing reads a dataset in an archived domain
    nothing is unbounded, unordered-but-limited, or shaped like a bomb

A refusal is a message somebody can act on. "Unknown field 'ecl'" with the five
nearest governed names beats "validation failed", because the second teaches
nobody anything and the first is often self-service.

Why the column checks are structural
------------------------------------
Validation walks the plan in dependency order and carries a *schema* — the set
of columns available at each step — exactly as the compiler will. A GROUP drops
everything not grouped or aggregated; a JOIN unions two schemas; a DERIVE adds
one name. Checking a column against "some dataset somewhere has this" would pass
plans that then fail in the database, which is the failure mode that makes an
analytical product feel unreliable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

from backend.runtime.ir import (
    AGG_FUNCTIONS,
    COMPARISONS,
    JOIN_KINDS,
    SCALAR_FUNCTIONS,
    WINDOW_FUNCTIONS,
    AnalyticalPlan,
    Expr,
    Operation,
    OpType,
    PlanError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- the limits


@dataclass(frozen=True)
class Limits:
    """What the runtime refuses on grounds of cost rather than governance.

    These are not arbitrary. Each one corresponds to a way a plan can be
    expensive without being wrong, and a product that lets one person's
    exploratory question take the database down is not usable by a team.
    """

    #: Operations in one plan. A legitimate analysis is tens, not hundreds.
    max_operations: int = 60
    #: Datasets scanned. More than this is a data model problem, not a question.
    max_scans: int = 12
    #: Joins. Each one multiplies the risk of an accidental explosion.
    max_joins: int = 10
    #: Rows a result may carry back. Beyond this it is an export, not an answer.
    max_output_rows: int = 50_000
    #: Nesting inside one derived expression.
    max_expression_depth: int = 12
    #: Grouping keys. A group-by wider than this returns one row per row.
    max_group_keys: int = 12
    #: Seconds a single execution may take.
    timeout_seconds: int = 60


DEFAULT_LIMITS = Limits()


class PlanRejected(PlanError):
    """A plan that will not run, with every reason rather than the first.

    All the reasons, because a caller fixing them one round trip at a time is
    a caller who gives up on the third.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__(" ".join(reasons) if reasons else "The plan was refused.")


# ------------------------------------------------------------ the schema walk


@dataclass
class StepSchema:
    """What one operation produces: the columns, and where each came from."""

    columns: dict[str, str] = field(default_factory=dict)   # name -> origin
    dataset: str = ""            # set when the step is still one dataset
    period: str | None = None    # the period pinned on the scan, if any

    def names(self) -> set[str]:
        return set(self.columns)


@dataclass
class ValidationReport:
    """The outcome, with everything a caller or a reviewer needs."""

    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Schema at each operation, for the compiler and the plan viewer.
    schemas: dict[str, StepSchema] = field(default_factory=dict)
    datasets: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)

    def raise_if_bad(self) -> ValidationReport:
        if not self.ok:
            raise PlanRejected(self.reasons)
        return self


def validate(plan: AnalyticalPlan, *, catalog: Any = None,
             limits: Limits = DEFAULT_LIMITS,
             archived_domains: frozenset[str] | None = None) -> ValidationReport:
    """Check a plan against the governed catalogue and the cost limits."""
    from backend.data_access.catalog import get_catalog

    catalog = catalog or get_catalog()
    if archived_domains is None:
        from backend.data_access.authority import archived_domains as retired
        archived_domains = retired()

    reasons: list[str] = []
    warnings: list[str] = []
    schemas: dict[str, StepSchema] = {}

    # ---- shape and cost, before anything is looked up ----------------------
    if not plan.operations:
        return ValidationReport(False, ["The plan has no operations."])

    if len(plan.operations) > limits.max_operations:
        reasons.append(
            f"The plan has {len(plan.operations)} operations, and the runtime "
            f"allows {limits.max_operations}. Ask a narrower question, or save "
            "part of this as a method and build on it."
        )

    scans = [o for o in plan.operations if o.op is OpType.SCAN]
    joins = [o for o in plan.operations if o.op is OpType.JOIN]
    if len(scans) > limits.max_scans:
        reasons.append(
            f"The plan reads {len(scans)} datasets; the runtime allows "
            f"{limits.max_scans}."
        )
    if len(joins) > limits.max_joins:
        reasons.append(
            f"The plan joins {len(joins)} times; the runtime allows "
            f"{limits.max_joins}. Each join multiplies the risk of an "
            "accidental row explosion."
        )

    try:
        ordered = plan.ordered()
    except PlanError as e:
        return ValidationReport(False, [str(e)])

    known_ids = {o.id for o in plan.operations}
    if plan.output and plan.output not in known_ids:
        reasons.append(
            f"The plan's result is '{plan.output}', which is not one of its "
            "operations."
        )

    # ---- operation by operation, carrying the schema forward ---------------
    for operation in ordered:
        for input_id in operation.inputs:
            if input_id not in known_ids:
                reasons.append(
                    f"{operation.id} reads from '{input_id}', which the plan "
                    "does not define."
                )
        if any(i not in schemas for i in operation.inputs):
            continue  # its input already failed; a second complaint adds nothing

        try:
            schemas[operation.id] = _check(
                operation, schemas, catalog, limits, archived_domains, warnings,
            )
        except PlanError as e:
            reasons.append(str(e))
            # Keep an empty schema so downstream steps report their own problems
            # against something, rather than cascading "unknown input".
            schemas[operation.id] = StepSchema()

    return ValidationReport(
        ok=not reasons,
        reasons=reasons,
        warnings=warnings,
        schemas=schemas,
        datasets=plan.datasets(),
        methods=plan.methods(),
    )


# ------------------------------------------------------- per-operation checks


def _check(op: Operation, schemas: dict[str, StepSchema], catalog: Any,
           limits: Limits, archived: frozenset[str],
           warnings: list[str]) -> StepSchema:
    """Validate one operation and return the schema it produces."""
    inputs = [schemas[i] for i in op.inputs]

    if op.op in (OpType.SCAN, OpType.METHOD):
        if inputs:
            raise PlanError(f"{op.id} is a source and cannot read from another step.")
    elif not inputs:
        raise PlanError(f"{op.id} is a {op.op} and needs an input.")

    handler = _HANDLERS.get(op.op)
    if handler is None:
        raise PlanError(
            f"{op.id}: the runtime has no implementation for {op.op} yet."
        )
    return handler(op, inputs, catalog, limits, archived, warnings)


def _require(op: Operation, key: str, *aliases: str) -> Any:
    for name in (key, *aliases):
        if name in op.params and op.params[name] is not None:
            return op.params[name]
    raise PlanError(f"{op.id} ({op.op}) needs a '{key}' parameter.")


def _column(op: Operation, name: str, schema: StepSchema, what: str = "column") -> str:
    """Check a column exists where it is read. Suggests, rather than only refusing."""
    plain = name.split(".")[-1] if "." in name else name
    if name in schema.columns:
        return name
    if plain in schema.columns:
        return plain
    near = get_close_matches(plain, sorted(schema.columns), n=4, cutoff=0.6)
    hint = f" Did you mean {', '.join(near)}?" if near else ""
    available = ", ".join(sorted(schema.columns)[:12]) or "(nothing)"
    raise PlanError(
        f"{op.id}: '{name}' is not a {what} available at this step.{hint} "
        f"Available here: {available}"
        f"{' …' if len(schema.columns) > 12 else ''}"
    )


def _expr(op: Operation, raw: Any, schema: StepSchema, limits: Limits) -> Expr:
    """Validate a derived expression: its depth, its functions and its columns."""
    expression = raw if isinstance(raw, Expr) else Expr.from_dict(raw)

    if expression.depth() > limits.max_expression_depth:
        raise PlanError(
            f"{op.id}: an expression is nested {expression.depth()} deep and the "
            f"runtime allows {limits.max_expression_depth}."
        )

    unknown = sorted(expression.functions() - SCALAR_FUNCTIONS)
    if unknown:
        near = get_close_matches(unknown[0], sorted(SCALAR_FUNCTIONS), n=3, cutoff=0.5)
        hint = f" Did you mean {', '.join(near)}?" if near else ""
        raise PlanError(
            f"{op.id}: '{unknown[0]}' is not a function the runtime provides.{hint}"
        )

    for column in sorted(expression.columns()):
        _column(op, column, schema)
    return expression


# ---- sources ---------------------------------------------------------------


def _scan(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
          archived: frozenset[str], warnings: list[str]) -> StepSchema:
    name = str(_require(op, "dataset"))
    try:
        spec = catalog.dataset(name)
    except Exception:
        available = sorted(d.name for d in catalog.all())
        near = get_close_matches(name, available, n=4, cutoff=0.5)
        hint = f" Did you mean {', '.join(near)}?" if near else ""
        raise PlanError(
            f"{op.id}: '{name}' is not a governed dataset.{hint} CreditProbe can "
            "only read datasets published in Data Builder."
        ) from None

    if spec.domain in archived:
        raise PlanError(
            f"{op.id}: '{name}' is in '{spec.domain}', which has been archived. "
            "Its data is still viewable in Data Builder, but the engine no "
            "longer reads it. Restore the domain, or use the dataset that "
            "replaced it."
        )

    wanted = op.params.get("fields") or op.params.get("columns")
    if wanted:
        if not isinstance(wanted, list):
            raise PlanError(f"{op.id}: 'fields' must be a list.")
        chosen: dict[str, str] = {}
        for column in wanted:
            column = str(column)
            if column not in spec.fields:
                near = get_close_matches(column, sorted(spec.fields), n=4, cutoff=0.6)
                hint = f" Did you mean {', '.join(near)}?" if near else ""
                raise PlanError(
                    f"{op.id}: '{column}' is not a field of {name}.{hint}"
                )
            chosen[column] = name
    else:
        chosen = dict.fromkeys(spec.fields, name)

    period = op.params.get("period")
    if period is not None:
        period = str(period)

    return StepSchema(columns=chosen, dataset=name, period=period)


def _method(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
            archived: frozenset[str], warnings: list[str]) -> StepSchema:
    """A certified Analysis Studio method used as a source.

    The method's own contract decides what it returns, so validation here checks
    only that it exists and is runnable — the registry is the authority on the
    rest, exactly as it is when the method is run on its own.
    """
    from backend.engine.registry import get_registry

    method = str(_require(op, "method", "analysis", "analysis_id"))
    registry = get_registry()
    try:
        contract = registry.require_runnable(method).contract
    except Exception as e:
        raise PlanError(f"{op.id}: {e}") from None

    columns = {str(o.name): method for o in getattr(contract, "outputs", [])}
    return StepSchema(columns=columns or {"value": method}, dataset="")


# ---- row shaping -----------------------------------------------------------


def _select(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
            archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    wanted = _require(op, "columns", "fields")
    if not isinstance(wanted, list) or not wanted:
        raise PlanError(f"{op.id}: 'columns' must be a non-empty list.")
    return StepSchema(
        columns={_column(op, str(c), source): source.columns.get(str(c), "") for c in wanted},
        dataset=source.dataset, period=source.period,
    )


def _filter(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
            archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    predicates = op.params.get("where") or op.params.get("conditions") or []
    expression = op.params.get("expression") or op.params.get("expr")

    if not predicates and expression is None:
        raise PlanError(f"{op.id}: a FILTER needs 'where' or 'expression'.")

    if expression is not None:
        _expr(op, expression, source, limits)

    if predicates and not isinstance(predicates, list):
        predicates = [predicates]
    for predicate in predicates:
        if not isinstance(predicate, dict):
            raise PlanError(f"{op.id}: each condition must be an object.")
        column = str(predicate.get("column") or predicate.get("field") or "")
        if not column:
            raise PlanError(f"{op.id}: a condition needs a 'column'.")
        _column(op, column, source)

        comparison = str(predicate.get("op") or predicate.get("operator") or "=").lower()
        if comparison not in COMPARISONS:
            raise PlanError(
                f"{op.id}: '{comparison}' is not a comparison the runtime offers. "
                f"Use one of: {', '.join(sorted(COMPARISONS))}."
            )
        if comparison in ("in", "not_in") and not isinstance(
            predicate.get("value") or predicate.get("values"), list
        ):
            raise PlanError(f"{op.id}: '{comparison}' needs a list of values.")
        if comparison == "between":
            bounds = predicate.get("value") or predicate.get("values")
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise PlanError(f"{op.id}: 'between' needs exactly two values.")

    return StepSchema(dict(source.columns), source.dataset, source.period)


def _derive(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
            archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    columns = op.params.get("columns") or op.params.get("derive") or []
    if isinstance(columns, dict):
        columns = [{"as": k, "expression": v} for k, v in columns.items()]
    if not isinstance(columns, list) or not columns:
        raise PlanError(f"{op.id}: a DERIVE needs 'columns'.")

    out = dict(source.columns)
    for entry in columns:
        if not isinstance(entry, dict):
            raise PlanError(f"{op.id}: each derived column must be an object.")
        name = str(entry.get("as") or entry.get("name") or "")
        if not name:
            raise PlanError(f"{op.id}: a derived column needs an 'as' name.")
        if name in source.columns:
            warnings.append(
                f"{op.id} replaces the existing column '{name}'. The original is "
                "no longer available after this step."
            )
        # Validated against the schema BEFORE this column is added, so a
        # derived column cannot silently refer to itself.
        _expr(op, entry.get("expression") or entry.get("expr"), source, limits)
        out[name] = f"derived:{op.id}"

    return StepSchema(out, source.dataset, source.period)


def _cast(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
          archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    column = str(_require(op, "column"))
    _column(op, column, source)
    to = str(_require(op, "to", "type")).lower()
    if to not in {"number", "integer", "text", "date", "boolean"}:
        raise PlanError(
            f"{op.id}: cannot cast to '{to}'. Use number, integer, text, date "
            "or boolean."
        )
    return StepSchema(dict(source.columns), source.dataset, source.period)


def _normalize(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
               archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    column = str(_require(op, "column"))
    _column(op, column, source)
    method = str(op.params.get("method") or "share").lower()
    if method not in {"share", "zscore", "minmax", "index"}:
        raise PlanError(
            f"{op.id}: '{method}' is not a normalisation. Use share, zscore, "
            "minmax or index."
        )
    for key in ("by", "partition_by"):
        for column_name in op.params.get(key) or []:
            _column(op, str(column_name), source)
    out = dict(source.columns)
    out[str(op.params.get("as") or f"{column}_{method}")] = f"derived:{op.id}"
    return StepSchema(out, source.dataset, source.period)


def _deduplicate(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
                 archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    for column in op.params.get("keys") or op.params.get("by") or []:
        _column(op, str(column), source)
    order = op.params.get("order_by") or []
    for entry in order:
        _column(op, str(entry.get("column") if isinstance(entry, dict) else entry), source)
    return StepSchema(dict(source.columns), source.dataset, source.period)


def _sort(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
          archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    entries = _require(op, "by", "columns", "order_by")
    if isinstance(entries, (str, dict)):
        entries = [entries]
    for entry in entries:
        name = entry.get("column") if isinstance(entry, dict) else entry
        _column(op, str(name), source)
    return StepSchema(dict(source.columns), source.dataset, source.period)


def _limit(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
           archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    count = op.params.get("n") or op.params.get("count") or op.params.get("limit")
    if count is None:
        raise PlanError(f"{op.id}: a LIMIT needs 'n'.")
    try:
        count = int(count)
    except (TypeError, ValueError):
        raise PlanError(f"{op.id}: 'n' must be a whole number.") from None
    if count <= 0:
        raise PlanError(f"{op.id}: 'n' must be greater than zero.")
    if count > limits.max_output_rows:
        raise PlanError(
            f"{op.id}: asks for {count:,} rows and the runtime returns at most "
            f"{limits.max_output_rows:,}. Use the governed export for a larger "
            "extract."
        )
    return StepSchema(dict(source.columns), source.dataset, source.period)


def _top_n(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
           archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    _column(op, str(_require(op, "by", "column", "measure")), source)
    for column in op.params.get("within") or op.params.get("partition_by") or []:
        _column(op, str(column), source)
    _limit(op, inputs, catalog, limits, archived, warnings)
    return StepSchema(dict(source.columns), source.dataset, source.period)


# ---- combining -------------------------------------------------------------



#: The temporal mappings a plan may use to align two reporting frequencies.
TEMPORAL_RULES = frozenset({"year_of_quarter",
                            "completed_year_of_quarter", "identity"})


def _pairs(op: Operation, on: Any) -> list[tuple[str, str]]:
    """Join keys as (left, right) pairs, refusing anything malformed."""
    if isinstance(on, str):
        on = [on]
    pairs: list[tuple[str, str]] = []
    for entry in on or []:
        if isinstance(entry, str):
            pairs.append((entry, entry))
        elif isinstance(entry, dict):
            left_key = str(entry.get("left") or entry.get("left_column") or "")
            right_key = str(entry.get("right") or entry.get("right_column") or left_key)
            if not left_key:
                raise PlanError(f"{op.id}: a join key needs a 'left' column.")
            pairs.append((left_key, right_key))
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            pairs.append((str(entry[0]), str(entry[1])))
        else:
            raise PlanError(f"{op.id}: a join key must be a name or a left/right pair.")
    return pairs


def _join(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
          archived: frozenset[str], warnings: list[str]) -> StepSchema:
    if len(inputs) != 2:
        raise PlanError(f"{op.id}: a JOIN needs exactly two inputs.")
    left, right = inputs

    kind = str(op.params.get("kind") or op.params.get("how") or "inner").lower()
    kind = {"left_join": "left", "inner_join": "inner", "outer": "full"}.get(kind, kind)
    if kind not in JOIN_KINDS:
        raise PlanError(
            f"{op.id}: '{kind}' is not a join the runtime performs. Use one of: "
            f"{', '.join(sorted(JOIN_KINDS))}."
        )

    on = op.params.get("on") or op.params.get("keys") or []
    if isinstance(on, str):
        on = [on]
    if not on:
        raise PlanError(
            f"{op.id}: a JOIN needs join keys. A join with no keys pairs every "
            "row with every row, which the runtime refuses."
        )

    pairs = _pairs(op, on)

    for left_key, right_key in pairs:
        _column(op, left_key, left, "join key on the left")
        _column(op, right_key, right, "join key on the right")

    # A join whose keys are on neither side's declared grain will fan out. It is
    # a warning rather than a refusal: sometimes fanning out is the point.
    if kind in ("inner", "left", "right", "full") and len(pairs) == 1:
        warnings.append(
            f"{op.id} joins on a single key. If it is not unique on at least one "
            "side, the result will have more rows than either input."
        )

    if kind in ("anti", "semi"):
        return StepSchema(dict(left.columns), left.dataset, left.period)

    # Mirrors the compiler exactly. A schema that disagrees with the SQL is
    # worse than no schema: validation passes and the database refuses, which
    # is the failure mode that makes a plan look non-deterministic.
    out = dict(left.columns)
    prefix = str(op.params.get("right_prefix") or "")
    right_keys = {p[1] for p in pairs}
    for name, origin in right.columns.items():
        if name in right_keys and name in left.columns:
            continue  # the key is already carried by the left side
        alias = f"{prefix}{name}" if prefix else name
        if alias in left.columns:
            # Both sides carry it. Keep the left and expose the right renamed,
            # rather than silently choosing one — a silently dropped column is
            # how a join quietly answers a different question.
            alias = f"right_{name}"
        out[alias] = origin
    return StepSchema(out, "", left.period or right.period)



def _asof_join(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
               archived: frozenset[str], warnings: list[str]) -> StepSchema:
    """An as-of join, and the two ways it can read the future.

    Both are refused here rather than caught in review:

      * a forward direction, which pairs a row with an observation dated AFTER
        it — the definition of look-ahead;
      * a missing ordering column, which leaves nothing for "as of" to mean and
        would compile to an ordinary join that silently takes an arbitrary row.
    """
    if len(inputs) != 2:
        raise PlanError(f"{op.id}: an as-of join needs exactly two inputs.")
    left, right = inputs

    direction = str(op.params.get("direction") or "backward").lower()
    if direction != "backward":
        raise PlanError(
            f"{op.id}: '{direction}' is not permitted. An as-of join reads the "
            "latest observation on or before the analysis date; a forward one "
            "reads data that had not happened yet.")

    left_order = str(op.params.get("left_order") or op.params.get("left_time") or "")
    right_order = str(op.params.get("right_order") or op.params.get("right_time") or "")
    if not left_order or not right_order:
        raise PlanError(
            f"{op.id}: an as-of join needs an ordering column on both sides. "
            "Without one there is nothing for 'as of' to be measured against.")
    _column(op, left_order, left, "as-of ordering column on the left")
    _column(op, right_order, right, "as-of ordering column on the right")

    pairs = _pairs(op, op.params.get("on") or op.params.get("keys") or [])
    if not pairs:
        raise PlanError(
            f"{op.id}: an as-of join needs join keys. Without them every "
            "left-hand row would take the latest right-hand row in the whole "
            "table.")
    for left_key, right_key in pairs:
        _column(op, left_key, left, "join key on the left")
        _column(op, right_key, right, "join key on the right")

    warnings.append(
        f"{op.id} is an as-of join: each row takes the latest "
        f"{right.dataset or 'right-hand'} observation dated on or before its "
        "own period. Rows with no earlier observation carry nulls rather than "
        "being dropped.")

    # Mirrors the compiler, including the reserved columns the window adds and
    # then discards.
    out = dict(left.columns)
    prefix = str(op.params.get("right_prefix") or "")
    right_keys = {p[1] for p in pairs}
    for name, origin in right.columns.items():
        if name in right_keys and name in left.columns:
            continue
        alias = f"{prefix}{name}" if prefix else name
        if alias in left.columns:
            alias = f"right_{name}"
        out[alias] = origin
    return StepSchema(out, "", left.period or right.period)


def _aggregate_before_join(op: Operation, inputs: list[StepSchema], catalog: Any,
                           limits: Limits, archived: frozenset[str],
                           warnings: list[str]) -> StepSchema:
    """Same shape as GROUP, kept separate so the Trace can say why it is here."""
    return _group(op, inputs, catalog, limits, archived, warnings)


def _temporal_align(op: Operation, inputs: list[StepSchema], catalog: Any,
                    limits: Limits, archived: frozenset[str],
                    warnings: list[str]) -> StepSchema:
    schema = inputs[0]
    source = str(op.params.get("column") or op.params.get("source") or "")
    if not source:
        raise PlanError(f"{op.id}: TEMPORAL_ALIGN needs the period column to map.")
    _column(op, source, schema, "period column")

    rule = str(op.params.get("rule") or "year_of_quarter")
    if rule not in TEMPORAL_RULES:
        raise PlanError(
            f"{op.id}: '{rule}' is not a governed temporal alignment. Use one "
            f"of: {', '.join(sorted(TEMPORAL_RULES))}.")

    target = str(op.params.get("as") or "aligned_period")
    out = dict(schema.columns)
    out[target] = schema.dataset or ""
    return StepSchema(out, schema.dataset, schema.period)


def _relationship_path(op: Operation, inputs: list[StepSchema], catalog: Any,
                       limits: Limits, archived: frozenset[str],
                       warnings: list[str]) -> StepSchema:
    """Records the governed relationships used. Changes nothing about the rows.

    The path is checked for shape only — it is metadata the planner wrote, and
    the joins it describes were each validated as their own operation.
    """
    path = op.params.get("path") or []
    if not isinstance(path, list):
        raise PlanError(f"{op.id}: a relationship path is a list of hops.")
    for hop in path:
        if not isinstance(hop, dict) or not hop.get("relationship_id"):
            raise PlanError(
                f"{op.id}: every hop must name the governed relationship it "
                "used. A join path with an anonymous hop cannot be audited.")
    return inputs[0]


def _union(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
           archived: frozenset[str], warnings: list[str]) -> StepSchema:
    if len(inputs) < 2:
        raise PlanError(f"{op.id}: a {op.op} needs at least two inputs.")
    first = inputs[0]
    for other in inputs[1:]:
        missing = first.names() - other.names()
        extra = other.names() - first.names()
        if missing or extra:
            raise PlanError(
                f"{op.id}: the inputs do not have the same columns, so they "
                f"cannot be stacked. Only on the first: "
                f"{', '.join(sorted(missing)) or '(none)'}. Only on the other: "
                f"{', '.join(sorted(extra)) or '(none)'}. Add a SELECT to make "
                "them match."
            )
    return StepSchema(dict(first.columns), "", first.period)


# ---- grouping --------------------------------------------------------------


def _aggregates(op: Operation, source: StepSchema, limits: Limits) -> dict[str, str]:
    entries = op.params.get("aggregates") or op.params.get("measures") or []
    if isinstance(entries, dict):
        entries = [{"as": k, **v} if isinstance(v, dict) else {"as": k, "function": v}
                   for k, v in entries.items()]
    if not isinstance(entries, list):
        raise PlanError(f"{op.id}: 'aggregates' must be a list.")

    out: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise PlanError(f"{op.id}: each aggregate must be an object.")
        function = str(entry.get("function") or entry.get("agg") or "").lower()
        if function not in AGG_FUNCTIONS:
            near = get_close_matches(function, sorted(AGG_FUNCTIONS), n=3, cutoff=0.5)
            hint = f" Did you mean {', '.join(near)}?" if near else ""
            raise PlanError(
                f"{op.id}: '{function or '(missing)'}' is not an aggregate the "
                f"runtime provides.{hint} Available: "
                f"{', '.join(sorted(AGG_FUNCTIONS))}."
            )
        column = entry.get("column") or entry.get("field")
        if function not in ("count", "count_where") and not column:
            raise PlanError(f"{op.id}: '{function}' needs a column.")
        if function in ("sum_where", "count_where"):
            predicate = entry.get("where") or entry.get("when")
            clauses = predicate if isinstance(predicate, list) else [predicate]
            if not clauses or not all(isinstance(c, dict) and c.get("column")
                                      for c in clauses):
                raise PlanError(
                    f"{op.id}: a '{function}' aggregate needs a `where` with a "
                    "column, saying which rows it counts.")
            for clause in clauses:
                _column(op, str(clause["column"]), source)
        if column:
            _column(op, str(column), source)
        if function == "weighted_avg":
            weight = entry.get("weight") or entry.get("weight_by")
            if not weight:
                raise PlanError(
                    f"{op.id}: a weighted average needs a 'weight' column — an "
                    "unweighted mean treats a small facility and a very large "
                    "one as equally important."
                )
            _column(op, str(weight), source)
        if function == "quantile":
            q = entry.get("q") or entry.get("quantile")
            if q is None or not (0 <= float(q) <= 1):
                raise PlanError(f"{op.id}: 'quantile' needs a q between 0 and 1.")

        name = str(entry.get("as") or entry.get("name")
                   or (f"{function}_{column}" if column else function))
        out[name] = f"aggregate:{op.id}"
    return out


def _group(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
           archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    keys = op.params.get("by") or op.params.get("group_by") or []
    if isinstance(keys, str):
        keys = [keys]
    if len(keys) > limits.max_group_keys:
        raise PlanError(
            f"{op.id}: groups by {len(keys)} columns and the runtime allows "
            f"{limits.max_group_keys}. Grouping by that many usually returns "
            "one row per row, which is the input rather than a summary."
        )

    out: dict[str, str] = {}
    for key in keys:
        resolved = _column(op, str(key), source)
        out[resolved] = source.columns.get(resolved, "")

    aggregates = _aggregates(op, source, limits)
    if not aggregates:
        raise PlanError(
            f"{op.id}: a GROUP needs at least one aggregate. Grouping without "
            "aggregating is a DEDUPLICATE."
        )
    out.update(aggregates)
    return StepSchema(out, source.dataset, source.period)


def _aggregate(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
               archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    aggregates = _aggregates(op, source, limits)
    if not aggregates:
        raise PlanError(f"{op.id}: an AGGREGATE needs at least one measure.")
    return StepSchema(aggregates, source.dataset, source.period)


def _distinct_count(op: Operation, inputs: list[StepSchema], catalog: Any,
                    limits: Limits, archived: frozenset[str],
                    warnings: list[str]) -> StepSchema:
    source = inputs[0]
    column = str(_require(op, "column"))
    _column(op, column, source)
    keys = op.params.get("by") or []
    out = {str(k): source.columns.get(str(k), "") for k in keys}
    for key in keys:
        _column(op, str(key), source)
    out[str(op.params.get("as") or f"distinct_{column}")] = f"aggregate:{op.id}"
    return StepSchema(out, source.dataset, source.period)


# ---- ordered analytics -----------------------------------------------------


def _window(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
            archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    function = str(op.params.get("function") or op.params.get("fn") or "").lower()
    if op.op is OpType.LAG:
        function = "lag"
    elif op.op is OpType.LEAD:
        function = "lead"
    elif op.op is OpType.RANK:
        function = function or "rank"
    elif op.op in (OpType.ROLLING, OpType.MOVING_AVERAGE):
        function = function or "avg"

    if function not in WINDOW_FUNCTIONS:
        raise PlanError(
            f"{op.id}: '{function or '(missing)'}' is not a window function the "
            f"runtime provides. Available: {', '.join(sorted(WINDOW_FUNCTIONS))}."
        )

    column = op.params.get("column") or op.params.get("field")
    if function not in ("row_number", "rank", "dense_rank", "percent_rank", "count"):
        if not column:
            raise PlanError(f"{op.id}: '{function}' needs a column.")
    if column:
        _column(op, str(column), source)

    for key in op.params.get("partition_by") or op.params.get("by") or []:
        _column(op, str(key), source)

    order = op.params.get("order_by") or []
    if isinstance(order, (str, dict)):
        order = [order]
    for entry in order:
        name = entry.get("column") if isinstance(entry, dict) else entry
        _column(op, str(name), source)

    if function in ("lag", "lead", "rank", "dense_rank", "row_number",
                    "first_value", "last_value") and not order:
        raise PlanError(
            f"{op.id}: '{function}' depends on row order, so it needs "
            "'order_by'. Without it the answer would change between runs."
        )

    out = dict(source.columns)
    default_name = f"{function}_{column}" if column else function
    out[str(op.params.get("as") or default_name)] = f"window:{op.id}"
    return StepSchema(out, source.dataset, source.period)


# ---- reshaping and credit-risk shapes --------------------------------------


def _pivot(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
           archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    on = str(_require(op, "on", "column", "pivot_on"))
    _column(op, on, source)
    value = str(_require(op, "value", "values", "measure"))
    _column(op, value, source)
    for key in op.params.get("by") or op.params.get("index") or []:
        _column(op, str(key), source)
    function = str(op.params.get("function") or "sum").lower()
    if function not in AGG_FUNCTIONS:
        raise PlanError(f"{op.id}: '{function}' is not an aggregate for a pivot.")
    # Columns are data-dependent, so the schema is open after a pivot. The
    # compiler resolves them at execution and the Trace records what appeared.
    out = {str(k): source.columns.get(str(k), "")
           for k in (op.params.get("by") or op.params.get("index") or [])}
    return StepSchema(out, source.dataset, source.period)


def _unpivot(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
             archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    columns = _require(op, "columns", "measures")
    if not isinstance(columns, list) or not columns:
        raise PlanError(f"{op.id}: an UNPIVOT needs 'columns'.")
    for column in columns:
        _column(op, str(column), source)
    keep = [str(k) for k in (op.params.get("keep") or op.params.get("by") or [])]
    for key in keep:
        _column(op, key, source)
    out = {k: source.columns.get(k, "") for k in keep}
    out[str(op.params.get("name_as") or "measure")] = f"derived:{op.id}"
    out[str(op.params.get("value_as") or "value")] = f"derived:{op.id}"
    return StepSchema(out, source.dataset, source.period)


def _bucket(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
            archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    column = str(_require(op, "column"))
    _column(op, column, source)
    edges = op.params.get("edges") or op.params.get("bounds")
    labels = op.params.get("labels")
    if not edges and not labels:
        raise PlanError(f"{op.id}: a BUCKET needs 'edges' or 'labels'.")
    if edges is not None:
        if not isinstance(edges, list) or len(edges) < 1:
            raise PlanError(f"{op.id}: 'edges' must be a list of numbers.")
        numbers = [float(e) for e in edges]
        if numbers != sorted(numbers):
            raise PlanError(
                f"{op.id}: bucket edges must ascend. Out of order, a value falls "
                "into whichever band is tested first, which is not a band."
            )
        if labels is not None and len(labels) != len(numbers) + 1:
            raise PlanError(
                f"{op.id}: {len(numbers)} edges make {len(numbers) + 1} buckets, "
                f"but {len(labels)} labels were given."
            )
    out = dict(source.columns)
    out[str(op.params.get("as") or f"{column}_bucket")] = f"derived:{op.id}"
    return StepSchema(out, source.dataset, source.period)


def _passthrough_derive(name_key: str, default: str):
    """Operations that add one named column and keep the rest."""

    def handler(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
                archived: frozenset[str], warnings: list[str]) -> StepSchema:
        source = inputs[0]
        for key in ("column", "of", "numerator", "denominator", "value", "measure"):
            if op.params.get(key):
                _column(op, str(op.params[key]), source)
        for key in ("by", "partition_by", "within"):
            for column in op.params.get(key) or []:
                _column(op, str(column), source)
        out = dict(source.columns)
        out[str(op.params.get(name_key) or default)] = f"derived:{op.id}"
        return StepSchema(out, source.dataset, source.period)

    return handler


def _ratio(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
           archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    numerator = str(_require(op, "numerator"))
    denominator = str(_require(op, "denominator"))
    _column(op, numerator, source)
    _column(op, denominator, source)
    out = dict(source.columns)
    out[str(op.params.get("as") or "ratio")] = f"derived:{op.id}"
    return StepSchema(out, source.dataset, source.period)


def _compare(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
             archived: frozenset[str], warnings: list[str]) -> StepSchema:
    """Two periods side by side. A JOIN with the intent made explicit."""
    if len(inputs) != 2:
        raise PlanError(
            f"{op.id}: a COMPARE needs two inputs — the opening position and "
            "the closing one."
        )
    left, right = inputs
    on = op.params.get("on") or op.params.get("keys") or []
    if isinstance(on, str):
        on = [on]
    if not on:
        raise PlanError(
            f"{op.id}: a COMPARE needs the keys that identify the same thing in "
            "both periods."
        )
    for key in on:
        _column(op, str(key), left, "comparison key in the opening period")
        _column(op, str(key), right, "comparison key in the closing period")

    measures = op.params.get("measures") or op.params.get("columns") or []
    if not measures:
        raise PlanError(f"{op.id}: a COMPARE needs the measures to compare.")

    out = {str(k): left.columns.get(str(k), "") for k in on}
    for measure in measures:
        name = str(measure)
        _column(op, name, left, "measure in the opening period")
        _column(op, name, right, "measure in the closing period")
        out[f"{name}_opening"] = f"compare:{op.id}"
        out[f"{name}_closing"] = f"compare:{op.id}"
        out[f"{name}_change"] = f"compare:{op.id}"
        out[f"{name}_change_pct"] = f"compare:{op.id}"
    return StepSchema(out, "", right.period or left.period)


def _distribution(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
                  archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    column = str(_require(op, "column"))
    _column(op, column, source)
    out = {
        "bucket": f"derived:{op.id}",
        "count": f"aggregate:{op.id}",
        "share_pct": f"aggregate:{op.id}",
    }
    return StepSchema(out, source.dataset, source.period)


def _percentile(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
                archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    column = str(_require(op, "column"))
    _column(op, column, source)
    quantiles = op.params.get("quantiles") or op.params.get("q") or [0.25, 0.5, 0.75]
    for q in quantiles:
        if not 0 <= float(q) <= 1:
            raise PlanError(f"{op.id}: a quantile must be between 0 and 1, not {q}.")
    keys = [str(k) for k in (op.params.get("by") or [])]
    for key in keys:
        _column(op, key, source)
    out = {k: source.columns.get(k, "") for k in keys}
    for q in quantiles:
        out[f"p{int(float(q) * 100)}"] = f"aggregate:{op.id}"
    return StepSchema(out, source.dataset, source.period)


def _matrix(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
            archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    from_column = str(_require(op, "from", "from_column"))
    to_column = str(_require(op, "to", "to_column"))
    _column(op, from_column, source)
    _column(op, to_column, source)
    measure = op.params.get("measure") or op.params.get("value")
    if measure:
        _column(op, str(measure), source)
    return StepSchema(
        {"from_state": f"derived:{op.id}", "to_state": f"derived:{op.id}",
         "value": f"aggregate:{op.id}", "share_pct": f"aggregate:{op.id}"},
        source.dataset, source.period,
    )


def _reconcile(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
               archived: frozenset[str], warnings: list[str]) -> StepSchema:
    source = inputs[0]
    parts = _require(op, "parts")
    whole = str(_require(op, "whole", "total"))
    if not isinstance(parts, list) or not parts:
        raise PlanError(f"{op.id}: 'parts' must be a list of columns.")
    for part in parts:
        _column(op, str(part), source)
    _column(op, whole, source)
    out = dict(source.columns)
    out["reconciles"] = f"derived:{op.id}"
    out["difference"] = f"derived:{op.id}"
    return StepSchema(out, source.dataset, source.period)


def _visualize(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
               archived: frozenset[str], warnings: list[str]) -> StepSchema:
    """Declares a chart. Computes nothing, so it cannot change a number."""
    source = inputs[0]
    chart = str(op.params.get("chart") or op.params.get("type") or "table").lower()
    known = {"table", "line", "bar", "stacked_bar", "column", "pie", "donut",
             "scatter", "histogram", "box", "heatmap", "treemap", "matrix",
             "sankey", "waterfall", "kpi", "area"}
    if chart not in known:
        raise PlanError(
            f"{op.id}: '{chart}' is not a chart the interface can draw. "
            f"Available: {', '.join(sorted(known))}."
        )
    for key in ("x", "y", "series", "size", "colour", "color", "value", "label"):
        value = op.params.get(key)
        for name in ([value] if isinstance(value, str) else (value or [])):
            _column(op, str(name), source)
    return StepSchema(dict(source.columns), source.dataset, source.period)


# ---- kernels ---------------------------------------------------------------


def _kernel(op: Operation, inputs: list[StepSchema], catalog: Any, limits: Limits,
            archived: frozenset[str], warnings: list[str]) -> StepSchema:
    """A statistical operation, run by an allowlisted kernel.

    Validated here for its columns; the kernel registry validates its own
    parameters, because it is the thing that knows what they mean.
    """
    from backend.runtime.kernels import describe_kernel, kernel_for

    source = inputs[0]
    kernel = kernel_for(op)
    for key in ("column", "columns", "x", "y", "of", "target", "features"):
        value = op.params.get(key)
        for name in ([value] if isinstance(value, str) else (value or [])):
            _column(op, str(name), source)
    for key in ("by", "group_by", "partition_by"):
        for name in op.params.get(key) or []:
            _column(op, str(name), source)

    described = describe_kernel(kernel, op)
    return StepSchema({c: f"kernel:{op.id}" for c in described},
                      source.dataset, source.period)


_HANDLERS: dict[OpType, Any] = {
    OpType.SCAN: _scan,
    OpType.METHOD: _method,
    OpType.SELECT: _select,
    OpType.FILTER: _filter,
    OpType.DERIVE: _derive,
    OpType.CAST: _cast,
    OpType.NORMALIZE: _normalize,
    OpType.DEDUPLICATE: _deduplicate,
    OpType.SORT: _sort,
    OpType.LIMIT: _limit,
    OpType.TOP_N: _top_n,
    OpType.BOTTOM_N: _top_n,
    OpType.JOIN: _join,
    OpType.ASOF_JOIN: _asof_join,
    OpType.AGGREGATE_BEFORE_JOIN: _aggregate_before_join,
    OpType.RECONCILE_GRAIN: _aggregate_before_join,
    OpType.TEMPORAL_ALIGN: _temporal_align,
    OpType.RELATIONSHIP_PATH: _relationship_path,
    OpType.UNION: _union,
    OpType.APPEND: _union,
    OpType.GROUP: _group,
    OpType.AGGREGATE: _aggregate,
    OpType.DISTINCT_COUNT: _distinct_count,
    OpType.WINDOW: _window,
    OpType.LAG: _window,
    OpType.LEAD: _window,
    OpType.ROLLING: _window,
    OpType.MOVING_AVERAGE: _window,
    OpType.RANK: _window,
    OpType.PIVOT: _pivot,
    OpType.UNPIVOT: _unpivot,
    OpType.CROSSTAB: _pivot,
    OpType.SEGMENT: _passthrough_derive("as", "segment"),
    OpType.BUCKET: _bucket,
    OpType.COHORT: _passthrough_derive("as", "cohort"),
    OpType.VINTAGE: _passthrough_derive("as", "months_on_book"),
    OpType.COMPARE: _compare,
    OpType.DELTA: _passthrough_derive("as", "delta"),
    OpType.GROWTH: _passthrough_derive("as", "growth_pct"),
    OpType.CONTRIBUTION: _passthrough_derive("as", "contribution_pct"),
    OpType.RECONCILE: _reconcile,
    OpType.FLOW: _passthrough_derive("as", "flow"),
    OpType.WATERFALL: _passthrough_derive("as", "step_value"),
    OpType.MATRIX: _matrix,
    OpType.RATIO: _ratio,
    OpType.DISTRIBUTION: _distribution,
    OpType.PERCENTILE: _percentile,
    OpType.QUANTILE: _percentile,
    OpType.OUTLIER: _kernel,
    OpType.TREND: _kernel,
    OpType.CORRELATION: _kernel,
    OpType.STAT_TEST: _kernel,
    OpType.REGRESSION: _kernel,
    OpType.SCENARIO: _kernel,
    OpType.VISUALIZE: _visualize,
}


__all__ = [
    "DEFAULT_LIMITS",
    "Limits",
    "PlanRejected",
    "StepSchema",
    "ValidationReport",
    "validate",
]
