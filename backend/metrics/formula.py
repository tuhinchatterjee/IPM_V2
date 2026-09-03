"""What a metric IS, as data a person can read and a machine can check.

A metric definition here is never a formula string. It is a small tree —
terms, a numerator, a denominator, a final operation — with every leaf naming
a governed dataset, a governed field and a governed aggregation. That shape
buys three things a string cannot:

**No evaluation.** Nothing here is `eval`ed, and no part of a definition
reaches the database as text. The tree compiles to CreditProbe's existing
analytical IR, which the existing validator checks against the catalogue and
the existing compiler turns into parameterised SQL. There is one calculation
system in this product, not two.

**A trace that is the calculation.** Because the numerator is a list of terms
rather than an expression, "Stage 2 EAD plus Stage 3 EAD over total eligible
EAD" can be shown term by term with the row counts behind each one — and the
numbers on that screen are the ones that produced the answer, not a
reconstruction of them.

**Refusal where a string would guess.** A term naming a field that is not in
the dataset, an aggregation that is not in the governed set, a comparison
operator nobody has approved — each is a refusal with a sentence, at
definition time, before anything runs.

One deliberate limit, stated rather than hidden: every term in a metric must
read the same dataset. A ratio whose numerator comes from one table and whose
denominator from another is a join, and a join has a grain question behind it
that this module cannot answer on somebody's behalf. `Metric.problems()` says
so by name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FORMULA_VERSION = "1.0.0"


class FormulaError(ValueError):
    """A definition the engine will not accept."""


# ---------------------------------------------------------------------------
# The governed vocabulary
# ---------------------------------------------------------------------------

#: Aggregations a term may use. Mapped onto the analytical IR's own set, which
#: the compiler already knows how to write safely. A name outside this set is
#: refused rather than passed through.
AGGREGATIONS: dict[str, str] = {
    "sum": "sum",
    "count": "count",
    "count_distinct": "count_distinct",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "median": "median",
    "stddev": "stddev",
    "weighted_avg": "weighted_avg",
}

#: Comparisons a filter may use, and how many values each takes.
COMPARISONS: dict[str, str] = {
    "=": "one", "!=": "one", "<": "one", "<=": "one", ">": "one", ">=": "one",
    "in": "many", "not_in": "many", "between": "two",
    "is_null": "none", "is_not_null": "none",
    "contains": "one", "starts_with": "one", "ends_with": "one",
}

#: How the terms on one side combine. Deliberately short: a side that needs
#: more than this is a metric that should be built from other metrics.
COMBINERS = ("add", "subtract", "multiply", "divide", "first")

#: What the whole metric is. Drives the unit, the default visualisations and
#: whether a denominator is required — and, importantly, what is NOT required:
#: forcing a numerator and denominator onto a plain sum is how a builder ends
#: up asking somebody what the denominator of "total exposure" is.
KINDS = (
    "direct", "count", "distinct_count", "sum", "average", "weighted_average",
    "ratio", "percentage", "rate", "change", "growth", "difference",
    "function",
)

#: Kinds that need a denominator, and are refused without one.
NEEDS_DENOMINATOR = ("ratio", "percentage", "rate")

#: Units. A number with no unit is a number somebody will read as the wrong
#: thing exactly once.
UNITS = ("percent", "ratio", "currency", "count", "days", "score", "index",
         "number")


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    """One filter, as a field, an operator and a value — never as text."""

    field: str
    op: str = "="
    value: Any = None

    def describe(self) -> str:
        if self.op in ("is_null", "is_not_null"):
            return f"{self.field} {self.op.replace('_', ' ')}"
        if self.op == "between" and isinstance(self.value, (list, tuple)):
            return f"{self.field} between {self.value[0]} and {self.value[1]}"
        if self.op in ("in", "not_in") and isinstance(self.value, (list, tuple)):
            return (f"{self.field} {self.op.replace('_', ' ')} "
                    f"[{', '.join(str(v) for v in self.value)}]")
        return f"{self.field} {self.op} {self.value}"

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "op": self.op, "value": self.value}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Condition:
        return cls(field=str(payload.get("field") or ""),
                   op=str(payload.get("op") or "="),
                   value=payload.get("value"))


@dataclass(frozen=True)
class Term:
    """One measured quantity: an aggregation of one field over some rows.

    The smallest thing with a number in it, and the unit of the trace: every
    term reports its own row count and its own value, which is what makes
    "why is the numerator 220 million?" answerable.
    """

    id: str
    label: str
    dataset: str
    aggregate: str = "sum"
    #: Empty for `count`, which counts rows rather than values.
    field: str = ""
    #: Only for `weighted_avg`.
    weight_field: str = ""
    where: tuple[Condition, ...] = ()

    def describe(self) -> str:
        what = (f"{self.aggregate}({self.field})" if self.field
                else f"{self.aggregate}(*)")
        if self.weight_field:
            what = f"{self.aggregate}({self.field} weighted by {self.weight_field})"
        if not self.where:
            return what
        return f"{what} where " + " and ".join(c.describe() for c in self.where)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "dataset": self.dataset,
                "aggregate": self.aggregate, "field": self.field,
                "weight_field": self.weight_field,
                "where": [c.to_dict() for c in self.where],
                "describes": self.describe()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Term:
        return cls(
            id=str(payload.get("id") or ""),
            label=str(payload.get("label") or ""),
            dataset=str(payload.get("dataset") or ""),
            aggregate=str(payload.get("aggregate") or "sum"),
            field=str(payload.get("field") or ""),
            weight_field=str(payload.get("weight_field") or ""),
            where=tuple(Condition.from_dict(c)
                        for c in (payload.get("where") or [])))


@dataclass(frozen=True)
class Side:
    """A numerator or a denominator: terms, and how they combine."""

    terms: tuple[Term, ...] = ()
    combine: str = "add"

    def describe(self) -> str:
        if not self.terms:
            return ""
        joiner = {"add": " + ", "subtract": " − ", "multiply": " × ",
                  "divide": " ÷ "}.get(self.combine, ", ")
        if self.combine == "first" or len(self.terms) == 1:
            return self.terms[0].label or self.terms[0].describe()
        return joiner.join(t.label or t.describe() for t in self.terms)

    def to_dict(self) -> dict[str, Any]:
        return {"terms": [t.to_dict() for t in self.terms],
                "combine": self.combine, "describes": self.describe()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Side:
        return cls(terms=tuple(Term.from_dict(t)
                               for t in (payload.get("terms") or [])),
                   combine=str(payload.get("combine") or "add"))


@dataclass(frozen=True)
class Formula:
    """The whole calculation.

    `scale` is what turns a ratio into a percentage. Kept as a number rather
    than baked into the kind so that "per thousand accounts" needs no new
    concept.
    """

    kind: str = "sum"
    numerator: Side = field(default_factory=Side)
    denominator: Side | None = None
    scale: float = 1.0
    #: For `function` metrics — Gini, KS, PSI — the governed function that
    #: computes them. Pretending those are numerator-over-denominator ratios
    #: would be a lie with a formula panel on it.
    function: str = ""
    function_args: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        if self.kind == "function":
            return f"{self.function}({self.numerator.describe()})"
        top = self.numerator.describe()
        if self.denominator is None:
            return top
        bottom = self.denominator.describe()
        tail = " × 100" if self.scale == 100 else (
            f" × {self.scale:g}" if self.scale != 1 else "")
        return f"({top}) / ({bottom}){tail}"

    @property
    def terms(self) -> tuple[Term, ...]:
        below = self.denominator.terms if self.denominator else ()
        return tuple(self.numerator.terms) + tuple(below)

    @property
    def datasets(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t.dataset for t in self.terms if t.dataset))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "numerator": self.numerator.to_dict(),
            "denominator": (self.denominator.to_dict()
                            if self.denominator else None),
            "scale": self.scale,
            "function": self.function,
            "function_args": dict(self.function_args),
            "describes": self.describe(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Formula:
        below = payload.get("denominator")
        return cls(
            kind=str(payload.get("kind") or "sum"),
            numerator=Side.from_dict(payload.get("numerator") or {}),
            denominator=Side.from_dict(below) if below else None,
            scale=float(payload.get("scale") or 1.0),
            function=str(payload.get("function") or ""),
            function_args=dict(payload.get("function_args") or {}))


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def problems(formula: Formula, *, catalog: Any = None) -> list[str]:
    """Everything wrong with a definition, in sentences, all at once.

    All at once on purpose: a person fixing a metric one refusal at a time
    gives up at about the third. Each sentence names the term it is about,
    because a builder with six terms needs to know which.
    """
    found: list[str] = []

    if formula.kind not in KINDS:
        found.append(
            f"'{formula.kind}' is not a kind of metric CreditProbe knows how "
            f"to calculate. It is one of: {', '.join(KINDS)}.")

    if not formula.numerator.terms and formula.kind != "function":
        found.append("A metric needs at least one term to measure.")

    if formula.kind in NEEDS_DENOMINATOR and (
            formula.denominator is None or not formula.denominator.terms):
        found.append(
            f"A {formula.kind} needs a denominator. What is it a "
            f"{formula.kind} of?")

    if formula.kind not in NEEDS_DENOMINATOR and formula.denominator and (
            formula.denominator.terms):
        found.append(
            f"A {formula.kind} has no denominator, but one has been defined. "
            "Change the kind to a ratio, a percentage or a rate, or remove it.")

    for side, name in ((formula.numerator, "numerator"),
                       (formula.denominator, "denominator")):
        if side is None:
            continue
        if side.combine not in COMBINERS:
            found.append(
                f"The {name} combines its terms with '{side.combine}', which "
                f"is not something the engine does. Use one of: "
                f"{', '.join(COMBINERS)}.")
        if side.combine == "divide" and len(side.terms) > 2:
            found.append(
                f"The {name} divides {len(side.terms)} terms, which has no "
                "single meaning. Divide two, or build the rest as its own "
                "metric.")

    seen: set[str] = set()
    for term in formula.terms:
        where = f"Term {term.id or term.label or '?'}"
        if not term.id:
            found.append("Every term needs an id, so the trace can name it.")
        elif term.id in seen:
            found.append(f"Two terms are both called '{term.id}'.")
        seen.add(term.id)

        if term.aggregate not in AGGREGATIONS:
            found.append(
                f"{where}: '{term.aggregate}' is not an aggregation the "
                f"engine performs. It is one of: "
                f"{', '.join(sorted(AGGREGATIONS))}.")
        if term.aggregate != "count" and not term.field:
            found.append(
                f"{where}: {term.aggregate} needs a field to work on. Only "
                "count works without one.")
        if term.aggregate == "weighted_avg" and not term.weight_field:
            found.append(f"{where}: a weighted average needs a weight field.")
        if not term.dataset:
            found.append(f"{where}: no dataset. Every number comes from one.")
        for condition in term.where:
            if condition.op not in COMPARISONS:
                found.append(
                    f"{where}: '{condition.op}' is not a comparison the engine "
                    f"performs. It is one of: {', '.join(sorted(COMPARISONS))}.")
                continue
            arity = COMPARISONS[condition.op]
            if arity == "none" and condition.value not in (None, "", []):
                found.append(
                    f"{where}: {condition.op} takes no value.")
            if arity == "many" and not isinstance(condition.value,
                                                  (list, tuple)):
                found.append(
                    f"{where}: {condition.op} takes a list of values.")
            if arity == "two" and not (
                    isinstance(condition.value, (list, tuple))
                    and len(condition.value) == 2):
                found.append(f"{where}: between takes exactly two values.")
            if not condition.field:
                found.append(f"{where}: a filter with no field.")

    if len(formula.datasets) > 1:
        found.append(
            "Every term in a metric has to read the same dataset. This one "
            f"reads {', '.join(formula.datasets)}. A number whose numerator "
            "comes from one table and whose denominator comes from another is "
            "a join, and the grain question behind a join is not one this "
            "builder can answer on your behalf — build each side as its own "
            "metric, or bring the fields into one dataset in Data Builder.")

    if catalog is not None:
        found.extend(_against_catalogue(formula, catalog))
    return found


def _against_catalogue(formula: Formula, catalog: Any) -> list[str]:
    """Whether the datasets and fields a definition names actually exist."""
    found: list[str] = []
    for term in formula.terms:
        if not term.dataset:
            continue
        try:
            dataset = catalog.dataset(term.dataset)
        except Exception:  # noqa: BLE001 - unknown name, reported as one
            found.append(
                f"Term {term.id}: there is no governed dataset called "
                f"'{term.dataset}'.")
            continue
        wanted = [f for f in (term.field, term.weight_field) if f]
        wanted += [c.field for c in term.where if c.field]
        for name in wanted:
            if name not in dataset.fields:
                found.append(
                    f"Term {term.id}: '{name}' is not a field of "
                    f"{term.dataset}. Available: "
                    f"{', '.join(sorted(dataset.fields)[:8])}…")
    return found


def check(formula: Formula, *, catalog: Any = None) -> Formula:
    """Return the formula, or raise with everything wrong with it."""
    found = problems(formula, catalog=catalog)
    if found:
        raise FormulaError(" ".join(found))
    return formula


__all__ = [
    "FORMULA_VERSION", "FormulaError",
    "AGGREGATIONS", "COMPARISONS", "COMBINERS", "KINDS",
    "NEEDS_DENOMINATOR", "UNITS",
    "Condition", "Term", "Side", "Formula",
    "problems", "check",
]
