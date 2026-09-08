"""Metrics built from other metrics, across periods and across domains.

Why the existing formula tree is not enough, stated precisely
-------------------------------------------------------------
:mod:`backend.metrics.formula` is a tree whose every term reads ONE dataset at
ONE period. That is a deliberate and good limit — it is what makes a metric one
scan, one row and one trace — and it is exactly the limit two of §4's own
examples fall outside:

    (Current Quarter Exposure / Previous Quarter Exposure) - 1

    High-severity EWS exposure / total corporate exposure

The first needs two PERIODS. The second, where the two sides genuinely live in
different tables, needs two DATASETS. Neither is expressible as a term tree,
and neither should be forced into one.

A composite instead of a join
------------------------------
A composite is a small expression over LEGS, where each leg is either a
governed metric named by id or an ordinary single-dataset formula, each
evaluated at its own period offset, and the results combined arithmetically.

That is not a lesser version of a row-level join; for these metrics it is the
correct one. "High-severity EWS exposure over total corporate exposure" is a
ratio of two portfolio totals, and computing it by joining facility rows to
watchlist rows would introduce a fan-out question — one borrower, many
facilities — whose answer changes the number and which nothing in the
expression asks about. Two aggregates divided have no fan-out and no grain
question. Where somebody genuinely needs a row-level cross-domain predicate
("exposure of facilities whose borrower is on the watchlist"), that IS a join,
it needs a governed relationship, and :func:`problems` refuses it by name with
that sentence rather than approximating it.

Grain is checked, not assumed
------------------------------
Two legs may be combined only where they resolve to comparable populations:
the same portfolio scope, and periods drawn from the same calendar. A ratio of
a quarterly total to a monthly one is refused, because the number it produces
is meaningless and looks fine.

The dependency graph
---------------------
§14. A leg naming a governed metric is resolved through :func:`resolve`, which
walks the graph, refuses cycles explicitly by naming the loop, and collapses
duplicate subexpressions so a metric appearing twice is computed once. Nested
governed results are REUSED rather than recomputed where the period and scope
match, which is what stops a three-level composite from being eight scans.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.metrics import lens_domains as lens_domains_mod
from backend.metrics.formula import Formula, FormulaError

logger = logging.getLogger(__name__)

COMPOSITE_VERSION = "3.0.0"

#: What a composite does with its legs.
#:
#: `growth` is `numerator / denominator - 1`, kept as its own kind rather than
#: expressed as a ratio with a subtraction after it, because the subtraction is
#: what makes it a growth rate and a reader checking the definition should see
#: that word rather than infer it.
OPERATIONS = ("ratio", "growth", "difference", "sum", "product")

NEEDS_TWO = ("ratio", "growth", "difference", "product")

#: How far back a leg may look. Sixteen quarters is four years, which is longer
#: than any comparison a Lens draws and short enough that a mistyped offset is
#: refused rather than scanning the whole history.
MAX_PERIOD_OFFSET = 16

#: How deep the dependency graph may go. A metric built on a metric built on a
#: metric is reasonable; past this it is a spreadsheet.
MAX_DEPTH = 5


class CompositeError(FormulaError):
    """A composite the engine will not accept."""


class CircularDependency(CompositeError):
    """A metric that depends on itself, directly or through others."""


# ---------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Leg:
    """One side of a composite.

    Exactly one of `metric_id` and `formula` is set. The first reuses a
    governed definition — which is what §14 means by building formulas from
    other governed metrics — and the second carries an ordinary single-dataset
    formula written for this composite alone.
    """

    id: str
    label: str = ""
    metric_id: str = ""
    formula: Formula | None = None
    #: How many periods back this leg reads, relative to the composite's
    #: period. 0 is the period being shown; 1 is the one before it.
    period_offset: int = 0
    #: What the person called this side, verbatim from their formula. Held so
    #: the preview can say "Previous Quarter Exposure" rather than "leg b".
    said: str = ""

    def describe(self) -> str:
        what = self.metric_id or (self.formula.describe() if self.formula else "?")
        if self.period_offset:
            return f"{what} [{self.period_offset} period(s) back]"
        return what

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "metric_id": self.metric_id,
                "formula": self.formula.to_dict() if self.formula else None,
                "period_offset": self.period_offset, "said": self.said,
                "describes": self.describe()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Leg:
        raw = payload.get("formula")
        return cls(
            id=str(payload.get("id") or ""),
            label=str(payload.get("label") or ""),
            metric_id=str(payload.get("metric_id") or ""),
            formula=Formula.from_dict(raw) if raw else None,
            period_offset=int(payload.get("period_offset") or 0),
            said=str(payload.get("said") or ""))


@dataclass(frozen=True)
class Composite:
    """A metric expressed over other metrics."""

    operation: str = "ratio"
    numerator: Leg | None = None
    denominator: Leg | None = None
    scale: float = 1.0

    def describe(self) -> str:
        top = self.numerator.describe() if self.numerator else "?"
        if self.operation == "sum" or self.denominator is None:
            return top
        bottom = self.denominator.describe()
        tail = " × 100" if self.scale == 100 else (
            f" × {self.scale:g}" if self.scale != 1 else "")
        if self.operation == "growth":
            return f"({top}) / ({bottom}) − 1{tail}"
        if self.operation == "difference":
            return f"({top}) − ({bottom}){tail}"
        if self.operation == "product":
            return f"({top}) × ({bottom}){tail}"
        return f"({top}) / ({bottom}){tail}"

    @property
    def legs(self) -> tuple[Leg, ...]:
        return tuple(leg for leg in (self.numerator, self.denominator) if leg)

    @property
    def datasets(self) -> tuple[str, ...]:
        found: list[str] = []
        for leg in self.legs:
            for dataset in (leg.formula.datasets if leg.formula else ()):
                if dataset not in found:
                    found.append(dataset)
        return tuple(found)

    @property
    def metric_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(leg.metric_id for leg in self.legs
                                   if leg.metric_id))

    @property
    def crosses_periods(self) -> bool:
        return len({leg.period_offset for leg in self.legs}) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "numerator": self.numerator.to_dict() if self.numerator else None,
            "denominator": (self.denominator.to_dict()
                            if self.denominator else None),
            "scale": self.scale,
            "describes": self.describe(),
            "crosses_periods": self.crosses_periods,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Composite:
        top = payload.get("numerator")
        bottom = payload.get("denominator")
        return cls(
            operation=str(payload.get("operation") or "ratio"),
            numerator=Leg.from_dict(top) if top else None,
            denominator=Leg.from_dict(bottom) if bottom else None,
            scale=float(payload.get("scale") or 1.0))


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def problems(composite: Composite, *, catalog: Any = None,
             resolver: Any = None) -> list[str]:
    """Everything wrong with a composite, in sentences, all at once."""
    from backend.metrics import formula as formula_mod

    found: list[str] = []
    if composite.operation not in OPERATIONS:
        found.append(
            f"'{composite.operation}' is not something a composite metric "
            f"does. It is one of: {', '.join(OPERATIONS)}.")
    if composite.numerator is None:
        found.append("A composite metric needs a numerator.")
    if composite.operation in NEEDS_TWO and composite.denominator is None:
        found.append(
            f"A {composite.operation} needs both sides. What is it a "
            f"{composite.operation} of?")

    seen: set[str] = set()
    for leg, side in ((composite.numerator, "numerator"),
                      (composite.denominator, "denominator")):
        if leg is None:
            continue
        if not leg.id:
            found.append(f"The {side} needs an id, so the trace can name it.")
        elif leg.id in seen:
            found.append(f"Both sides are called '{leg.id}'.")
        seen.add(leg.id)

        if bool(leg.metric_id) == bool(leg.formula):
            found.append(
                f"The {side} must be either a governed metric or a formula, "
                "and this one is "
                + ("both" if leg.metric_id else "neither") + ".")
        if leg.period_offset < 0:
            found.append(
                f"The {side} looks {abs(leg.period_offset)} period(s) into the "
                "future, which is not a period the book has.")
        if leg.period_offset > MAX_PERIOD_OFFSET:
            found.append(
                f"The {side} looks {leg.period_offset} periods back, and "
                f"{MAX_PERIOD_OFFSET} is as far as a comparison goes.")
        if leg.formula is not None:
            found.extend(
                f"The {side}: {p}"
                for p in formula_mod.problems(leg.formula, catalog=catalog))
            found.extend(
                f"The {side}: {p}"
                for p in lens_domains_mod.check_formula(leg.formula))
        if leg.metric_id and resolver is not None:
            try:
                resolver(leg.metric_id)
            except Exception as e:  # noqa: BLE001 - reported as a sentence
                found.append(
                    f"The {side} names '{leg.metric_id}', which is not a "
                    f"metric this deployment has: {e}")

    if (composite.operation == "growth" and not composite.crosses_periods
            and composite.numerator and composite.denominator):
        found.append(
            "A growth rate compares two periods, and both sides of this one "
            "read the same period. Set a period offset on one of them, or "
            "make it a ratio.")

    found.extend(_grain_problems(composite, catalog=catalog, resolver=resolver))
    return found


def _grain_problems(composite: Composite, *, catalog: Any = None,
                    resolver: Any = None) -> list[str]:
    """Whether the two sides describe populations that may be divided.

    Two aggregates over the same calendar may be combined whatever tables they
    came from. Two aggregates over DIFFERENT calendars may not: a quarterly
    total over a monthly one is a number with no meaning, and it renders
    perfectly.
    """
    found: list[str] = []
    grains: dict[str, str] = {}
    for leg in composite.legs:
        datasets = list(leg.formula.datasets) if leg.formula else []
        if leg.metric_id and resolver is not None:
            try:
                datasets = list(resolver(leg.metric_id).datasets)
            except Exception:  # noqa: BLE001 - already reported by `problems`
                continue
        for dataset in datasets:
            grain = _period_grain(dataset, catalog=catalog)
            if grain:
                grains.setdefault(grain, dataset)
    if len(grains) > 1:
        pairs = ", ".join(f"{d} is {g}" for g, d in sorted(grains.items()))
        found.append(
            "The two sides are measured on different calendars — "
            f"{pairs} — so dividing one by the other produces a figure with "
            "no meaning. Build each side as its own metric, or bring them onto "
            "one reporting frequency.")
    return found


def _period_grain(dataset: str, *, catalog: Any = None) -> str:
    """Whether a dataset's periods are quarters, months or something else."""
    try:
        from backend.data_access import get_data_source

        periods = list(get_data_source().periods(dataset))
    except Exception:  # noqa: BLE001 - unknown grain is not a refusal
        return ""
    if not periods:
        return ""
    sample = periods[-1]
    if sample.upper().startswith("Q") or " Q" in sample.upper():
        return "quarterly"
    if len(sample) == 7 and sample[4] == "-":
        return "monthly"
    if len(sample) == 4 and sample.isdigit():
        return "annual"
    return ""


def check(composite: Composite, *, catalog: Any = None,
          resolver: Any = None) -> Composite:
    found = problems(composite, catalog=catalog, resolver=resolver)
    if found:
        raise CompositeError(" ".join(found))
    return composite


# ---------------------------------------------------------------------------
# The dependency graph — §14
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """One metric in a resolved dependency graph."""

    metric_id: str
    depth: int = 0
    composite: Composite | None = None
    formula: Formula | None = None
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"metric_id": self.metric_id, "depth": self.depth,
                "kind": "composite" if self.composite else "formula",
                "depends_on": list(self.depends_on)}


@dataclass
class Graph:
    """What a metric is built from, all the way down."""

    root: str = ""
    nodes: dict[str, Node] = field(default_factory=dict)
    #: Subexpressions that appear more than once, and are computed once.
    shared: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"root": self.root,
                "nodes": [self.nodes[n].to_dict() for n in self.order],
                "evaluation_order": list(self.order),
                "shared": list(self.shared),
                "depth": max((n.depth for n in self.nodes.values()), default=0)}


def _composite_of(metric: Any) -> Composite | None:
    """The composite behind a governed metric, where it has one."""
    raw = getattr(metric, "composite", None)
    if isinstance(raw, Composite):
        return raw
    if isinstance(raw, dict) and raw:
        return Composite.from_dict(raw)
    return None


def resolve(composite: Composite, *, resolver: Any, root: str = "",
            _seen: tuple[str, ...] = ()) -> Graph:
    """The whole dependency graph under a composite, with cycles refused.

    `resolver` takes a metric id and returns a metric definition. Passed in
    rather than imported so this module stays testable without the catalogue,
    and so a caller's permission-aware resolver is the one that is used.

    Cycles are named rather than reported as a depth limit: "corporate.a
    depends on corporate.b, which depends on corporate.a" is actionable and
    "maximum recursion depth exceeded" is not.
    """
    graph = Graph(root=root or "(new metric)")
    counts: dict[str, int] = {}

    def walk(node_composite: Composite | None, node_formula: Formula | None,
             metric_id: str, depth: int, chain: tuple[str, ...]) -> None:
        if depth > MAX_DEPTH:
            raise CompositeError(
                f"'{metric_id}' is built on metrics {MAX_DEPTH} levels deep. "
                "Past that a metric has stopped being a definition and become "
                "a spreadsheet — build the intermediate steps as their own "
                "published metrics.")
        node = Node(metric_id=metric_id, depth=depth,
                    composite=node_composite, formula=node_formula)
        if node_composite is not None:
            for leg in node_composite.legs:
                if not leg.metric_id:
                    continue
                counts[leg.metric_id] = counts.get(leg.metric_id, 0) + 1
                node.depends_on.append(leg.metric_id)
                if leg.metric_id in chain:
                    loop = " depends on ".join(
                        list(chain[chain.index(leg.metric_id):]) + [leg.metric_id])
                    raise CircularDependency(
                        f"This metric cannot be built: {loop}. A metric that "
                        "depends on itself has no value to compute.")
                if leg.metric_id in graph.nodes:
                    continue
                child = resolver(leg.metric_id)
                walk(_composite_of(child), getattr(child, "formula", None),
                     leg.metric_id, depth + 1, chain + (leg.metric_id,))
        graph.nodes[metric_id] = node
        graph.order.append(metric_id)

    walk(composite, None, graph.root, 0, (graph.root,) if root else ())
    graph.shared = sorted(m for m, n in counts.items() if n > 1)
    # Deepest first, so a leg's dependency is already computed when it is read.
    graph.order.sort(key=lambda n: -graph.nodes[n].depth)
    return graph


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------


@dataclass
class LegValue:
    """One side, computed, with everything that produced it."""

    leg: Leg
    value: float | None = None
    period: str = ""
    rows: int = 0
    dataset: str = ""
    unit: str = ""
    sql: str = ""
    run_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    domains: list[str] = field(default_factory=list)
    unavailable: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.leg.id, "label": self.leg.label or self.leg.said,
                "said": self.leg.said, "describes": self.leg.describe(),
                "metric_id": self.leg.metric_id,
                "period_offset": self.leg.period_offset,
                "value": self.value, "period": self.period, "rows": self.rows,
                "dataset": self.dataset, "unit": self.unit, "sql": self.sql,
                "run_id": self.run_id, "domains": list(self.domains),
                "detail": self.detail, "unavailable": self.unavailable}


@dataclass
class CompositeCalculation:
    """A composite, computed, and the exact arithmetic that produced it."""

    value: float | None = None
    composite: Composite | None = None
    numerator: LegValue | None = None
    denominator: LegValue | None = None
    period: str = ""
    warnings: list[str] = field(default_factory=list)
    unavailable: str = ""

    @property
    def final_expression(self) -> str:
        from backend.metrics.execution import _fmt

        if self.numerator is None:
            return "—"
        top = _fmt(self.numerator.value)
        if self.denominator is None:
            return f"{top}"
        bottom = _fmt(self.denominator.value)
        scale = (self.composite.scale if self.composite else 1.0)
        tail = f" × {scale:g}" if scale != 1 else ""
        operation = self.composite.operation if self.composite else "ratio"
        if operation == "growth":
            return f"({top} / {bottom}) − 1{tail} = {_fmt(self.value)}"
        if operation == "difference":
            return f"{top} − {bottom}{tail} = {_fmt(self.value)}"
        if operation == "product":
            return f"{top} × {bottom}{tail} = {_fmt(self.value)}"
        return f"{top} / {bottom}{tail} = {_fmt(self.value)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "composite": self.composite.to_dict() if self.composite else None,
            "numerator": self.numerator.to_dict() if self.numerator else None,
            "denominator": (self.denominator.to_dict()
                            if self.denominator else None),
            "final": self.final_expression,
            "period": self.period,
            "warnings": list(self.warnings),
            "unavailable": self.unavailable,
        }


#: The period label this book actually stores: "Q2 2026". The metric service
#: also understands "2026-Q2", "2026-06" and "2026", and `shift` delegates to
#: it for those — but the shape the analytics layer writes is this one, and a
#: shift that did not recognise it returned empty. That is the defect this
#: constant exists to stop: an empty period does not mean "no comparison", it
#: means "every period", so a denominator computed with one silently became
#: the sum of the whole history and the growth rate read -94%.
_QUARTER_LABEL = re.compile(r"^Q([1-4])\s+(\d{4})$")


def shift(period: str, *, back: int) -> str:
    """The period `back` steps before this one, on this book's own calendar.

    Returns empty when the period cannot be shifted — an unrecognised label,
    or a shift the calendar does not support. Callers must treat empty as a
    refusal rather than as "unfiltered": :func:`_run_leg` does, by name.
    """
    if not back:
        return period
    text = (period or "").strip()
    labelled = _QUARTER_LABEL.match(text)
    if labelled:
        quarter, year = int(labelled.group(1)), int(labelled.group(2))
        total = year * 4 + (quarter - 1) - back
        return f"Q{total % 4 + 1} {total // 4:04d}"

    from backend.metrics import service as metrics

    return metrics._shift_period(text, months=3 * back)


def _combine(top: float | None, bottom: float | None, *, operation: str,
             scale: float) -> tuple[float | None, str]:
    """The final arithmetic, and why there is no answer when there is none."""
    if top is None:
        return None, "The numerator could not be computed."
    if operation == "sum" or bottom is None and operation == "sum":
        return top * scale, ""
    if bottom is None:
        return None, "The denominator could not be computed."
    if operation in ("ratio", "growth"):
        if bottom == 0:
            return None, (
                "The denominator is zero, so the ratio has no value. That is "
                "reported rather than shown as zero or as infinity, because "
                "both of those read as an answer.")
        ratio = top / bottom
        return ((ratio - 1.0) * scale if operation == "growth"
                else ratio * scale), ""
    if operation == "difference":
        return (top - bottom) * scale, ""
    if operation == "product":
        return top * bottom * scale, ""
    return None, f"'{operation}' is not an operation this engine performs."


def run(composite: Composite, *, period: str = "", scope: tuple[Any, ...] = (),
        user_id: int | None = None, resolver: Any = None,
        cache: dict[tuple[Any, ...], LegValue] | None = None
        ) -> CompositeCalculation:
    """Compute a composite, showing every step.

    `cache` is the §14 reuse: a leg keyed by (metric or formula, period, scope)
    is computed once however many times the expression names it. Passed in so a
    Lens rendering several composites over the same governed metric shares one.
    """
    from backend.metrics import service as metrics

    calculation = CompositeCalculation(composite=composite, period=period)
    shared: dict[tuple[Any, ...], LegValue] = cache if cache is not None else {}
    resolver = resolver or (lambda mid: metrics.resolve(mid, user_id=user_id))

    for leg, slot in ((composite.numerator, "numerator"),
                      (composite.denominator, "denominator")):
        if leg is None:
            continue
        computed = _run_leg(leg, period=period, scope=scope, user_id=user_id,
                            resolver=resolver, shared=shared)
        setattr(calculation, slot, computed)
        if computed.unavailable:
            calculation.warnings.append(
                f"{leg.label or leg.id}: {computed.unavailable}")

    value, why = _combine(
        calculation.numerator.value if calculation.numerator else None,
        calculation.denominator.value if calculation.denominator else None,
        operation=composite.operation, scale=composite.scale)
    calculation.value = value
    if value is None and not calculation.unavailable:
        calculation.unavailable = why or "This composite produced no value."
    return calculation


def _run_leg(leg: Leg, *, period: str, scope: tuple[Any, ...],
             user_id: int | None, resolver: Any,
             shared: dict[tuple[Any, ...], LegValue]) -> LegValue:
    from backend.metrics import execution
    from backend.metrics import service as metrics

    at = shift(period, back=leg.period_offset) if period else period
    if leg.period_offset and period and not at:
        # An unshiftable period is a refusal, never an empty filter. Running
        # the leg with `at=""` would scan every period the book has and
        # report the total as though it were one quarter.
        return LegValue(
            leg=leg, unavailable=(
                f"CreditProbe could not work out the period {leg.period_offset} "
                f"before '{period}' on this book's calendar, so this side has "
                "no comparison period to read. It is reported rather than "
                "computed over every period at once."))
    key: tuple[Any, ...] = (leg.metric_id, leg.formula.describe()
                            if leg.formula else "", at, scope)
    hit = shared.get(key)
    if hit is not None:
        # A copy carrying THIS leg's identity: the value is shared, the label
        # and the offset belong to the side that asked for it.
        return LegValue(leg=leg, value=hit.value, period=hit.period,
                        rows=hit.rows, dataset=hit.dataset, unit=hit.unit,
                        sql=hit.sql, run_id=hit.run_id, detail=hit.detail,
                        domains=list(hit.domains),
                        unavailable=hit.unavailable)

    formula = leg.formula
    unit = ""
    leg_scope = scope
    if leg.metric_id:
        try:
            metric = resolver(leg.metric_id)
        except Exception as e:  # noqa: BLE001 - reported on the leg
            return LegValue(leg=leg, unavailable=str(e))
        nested = _composite_of(metric)
        if nested is not None:
            inner = run(nested, period=at, scope=scope, user_id=user_id,
                        resolver=resolver, cache=shared)
            value = LegValue(
                leg=leg, value=inner.value, period=at, unit=metric.unit,
                dataset=", ".join(nested.datasets),
                detail={"composite": inner.to_dict()},
                domains=list(lens_domains_mod.metric_domains(metric)),
                unavailable=inner.unavailable)
            shared[key] = value
            return value
        formula = metric.formula
        unit = metric.unit
        leg_scope = scope or tuple(getattr(metric, "scope", ()) or ())

    if formula is None:
        return LegValue(leg=leg, unavailable="This side has no definition.")

    try:
        calculation = execution.run(formula, period=at, scope=leg_scope,
                                    question=leg.label or leg.said)
    except Exception as e:  # noqa: BLE001 - reported on the leg, not raised
        logger.warning("composite leg %s failed: %s", leg.id, e)
        return LegValue(leg=leg, period=at, unavailable=str(e))

    value = LegValue(
        leg=leg, value=calculation.value, period=at,
        rows=calculation.rows_considered, dataset=calculation.dataset,
        unit=unit, sql=calculation.sql, run_id=calculation.run_id,
        detail=calculation.to_dict(),
        domains=list(lens_domains_mod.formula_domains(formula)),
        unavailable=calculation.unavailable)
    shared[key] = value
    _ = metrics  # imported for the resolver default above
    return value


# ---------------------------------------------------------------------------
# §15: the same composite, across a dimension
# ---------------------------------------------------------------------------


def breakdown(composite: Composite, *, dimension: str, period: str = "",
              scope: tuple[Any, ...] = (), where: tuple[Any, ...] = (),
              sort: str = "value", direction: str = "desc",
              limit: int = 20, user_id: int | None = None,
              resolver: Any = None) -> dict[str, Any]:
    """A composite metric across one dimension. §15.

    Each leg is broken out on its own, at its own period, and the two are
    combined GROUP BY GROUP with the same arithmetic the single figure uses.
    That is what makes a bar comparable to the KPI above it: not a similar
    calculation, the same one applied per group.

    A label present on one side and not the other produces no point rather
    than a point computed against a missing denominator. Dropping it silently
    would shrink the population the chart claims to cover, so the count of
    what was dropped travels with the result and the chart says so.
    """
    from backend.metrics import execution
    from backend.metrics import service as metrics

    resolver = resolver or (lambda mid: metrics.resolve(mid, user_id=user_id))

    sides: dict[str, dict[str, Any]] = {}
    datasets: list[str] = []
    for leg, name in ((composite.numerator, "numerator"),
                      (composite.denominator, "denominator")):
        if leg is None:
            continue
        formula = leg.formula
        leg_scope = scope
        if leg.metric_id:
            try:
                metric = resolver(leg.metric_id)
            except Exception as e:  # noqa: BLE001 - reported, not raised
                return _no_chart(dimension, period, f"{name}: {e}")
            formula = metric.formula
            leg_scope = scope or tuple(getattr(metric, "scope", ()) or ())
        if formula is None:
            return _no_chart(dimension, period,
                             f"The {name} has no definition to break out.")
        at = shift(period, back=leg.period_offset) if period else period
        if leg.period_offset and period and not at:
            return _no_chart(
                dimension, period,
                f"CreditProbe could not work out the period "
                f"{leg.period_offset} before '{period}', so the {name} has no "
                "period to read.")
        if dimension not in (formula.datasets and
                             _dimension_fields(formula.datasets[0]) or set()):
            return _no_chart(
                dimension, period,
                f"'{dimension}' is not a field of "
                f"{formula.datasets[0] if formula.datasets else 'this side'}, "
                f"so the {name} cannot be broken out by it.")
        try:
            drawn = execution.breakdown(
                formula, dimension=dimension, period=at, scope=leg_scope,
                where=where, sort="label", direction="asc",
                limit=execution.MAX_GROUPS,
                question=f"{leg.label or name} by {dimension}")
        except Exception as e:  # noqa: BLE001 - reported on the chart
            return _no_chart(dimension, period, str(e))
        sides[name] = drawn
        datasets.extend(formula.datasets)

    top = sides.get("numerator")
    if top is None:
        return _no_chart(dimension, period, "There is no numerator to draw.")
    bottom = sides.get("denominator")

    by_label_top = {p["label"]: p for p in top["points"]}
    by_label_bottom = ({p["label"]: p for p in bottom["points"]}
                       if bottom else {})

    points: list[dict[str, Any]] = []
    dropped: list[str] = []
    for label, point in by_label_top.items():
        other = by_label_bottom.get(label) if bottom is not None else None
        if bottom is not None and other is None:
            dropped.append(label)
            continue
        value, why = _combine(
            point.get("value"),
            other.get("value") if other else None,
            operation=composite.operation, scale=composite.scale)
        points.append({
            "label": label, "value": value,
            "rows": int(point.get("rows") or 0),
            "unavailable": why if value is None else "",
        })

    if sort == "period":
        from backend.metrics.service import _period_order

        points.sort(key=lambda p: _period_order(p["label"]),
                    reverse=(direction == "desc"))
    elif sort == "label":
        points.sort(key=lambda p: p["label"], reverse=(direction == "desc"))
    else:
        with_value = [p for p in points if p["value"] is not None]
        without = [p for p in points if p["value"] is None]
        with_value.sort(key=lambda p: p["value"],
                        reverse=(direction == "desc"))
        points = [*with_value, *without]

    found = len(points)
    shown = points[:max(1, int(limit))]
    note = ""
    if dropped:
        note = (f"{len(dropped)} group(s) appear on one side of this ratio and "
                f"not the other, so no point is drawn for them: "
                f"{', '.join(sorted(dropped)[:5])}"
                + ("…" if len(dropped) > 5 else "") + ".")
    return {
        "dimension": dimension,
        "points": shown,
        "period": top.get("period") or period,
        "dataset": ", ".join(dict.fromkeys(datasets)),
        "sql": top.get("sql", ""),
        "run_id": top.get("run_id", ""),
        "groups_found": found,
        "truncated": found > len(shown),
        "unavailable": "",
        "note": note,
    }


def _no_chart(dimension: str, period: str, why: str) -> dict[str, Any]:
    return {"dimension": dimension, "points": [], "period": period,
            "dataset": "", "sql": "", "run_id": "", "groups_found": 0,
            "truncated": False, "unavailable": why, "note": ""}


def _dimension_fields(dataset: str) -> set[str]:
    try:
        from backend.data_access.catalog import get_catalog

        return set(get_catalog().dataset(dataset).fields)
    except Exception:  # noqa: BLE001
        return set()


def domains_of(composite: Composite, *, resolver: Any = None) -> tuple[str, ...]:
    """Which Lens domains a composite reads, across both sides."""
    found: list[str] = []
    for leg in composite.legs:
        if leg.formula is not None:
            for domain in lens_domains_mod.formula_domains(leg.formula):
                if domain not in found:
                    found.append(domain)
        elif leg.metric_id and resolver is not None:
            try:
                metric = resolver(leg.metric_id)
            except Exception:  # noqa: BLE001
                continue
            for domain in lens_domains_mod.metric_domains(metric):
                if domain not in found:
                    found.append(domain)
    return tuple(d for d in lens_domains_mod.LENS_DOMAINS if d in found)


__all__ = [
    "COMPOSITE_VERSION", "MAX_DEPTH", "MAX_PERIOD_OFFSET", "NEEDS_TWO",
    "OPERATIONS", "CircularDependency", "Composite", "CompositeCalculation",
    "CompositeError", "Graph", "Leg", "LegValue", "Node",
    "breakdown", "check", "domains_of", "problems", "resolve", "run",
    "shift",
]
