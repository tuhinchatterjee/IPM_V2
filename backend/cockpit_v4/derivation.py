"""
Validating arithmetic that is real but has no row of its own.

The defect this exists for
--------------------------
A live run asked for exposure at default by sector. Everything worked: the
request was understood, EAD resolved to `ead_reported`, the latest quarter
resolved from the calendar, the SQL bound, it executed, twelve rows came
back. Then publication was refused, twice:

    claim 'total_ead' names row 'all sectors', which is not in artifact ...
    claim 'top4_pct' names row 'top 4 sectors', which is not in artifact ...

The analyst had done nothing wrong. A total across twelve sectors is a real
number a credit officer needs, and so is the share carried by the largest
four -- but neither is a cell in the result, because the query grouped by
sector and did not also produce a total row. Faced with a validator that
would only accept a pointer to one physical cell, the only move left was to
invent a row name, and inventing it is what got the answer rejected.

The fix is not to trust the analyst's arithmetic. It is to let a claim SHOW
its arithmetic, over cells that really exist, and to recompute it here.

What this is not
----------------
Not an expression language. There is no parser, no `eval`, no Python in the
payload and no way to write a new operation. A derivation names one operation
from a closed set, and each operation knows its own arity and how it consumes
its operands. Everything a claim can say is one of the twelve shapes below,
and anything else is refused by name.

Nesting is bounded at exactly one level -- an operation over operands, where
an operand is a set of cells in one column of one artifact. That is enough
for every derived figure a Cockpit answer has needed (a total, a share, a
movement, a growth rate, a weighted average, a rank), and it keeps the
schema finite, which matters because the provider's tool dialect rejects the
recursive constructs a deeper tree would need.

Exactness
---------
Every value is `Decimal`, parsed from the artifact's own stored string form.
Floats are not used anywhere in this module: a book total that reads
20720.343518249818 in one place and 20720.34351824982 in another is a
reconciliation argument nobody should have to have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

# ---- the closed operation set ------------------------------------------

IDENTITY = "identity"
SUM = "sum"
DIFFERENCE = "difference"
RATIO = "ratio"
PERCENTAGE = "percentage"
PERCENTAGE_CHANGE = "percentage_change"
SHARE_OF_TOTAL = "share_of_total"
WEIGHTED_AVERAGE = "weighted_average"
MIN = "min"
MAX = "max"
COUNT = "count"
RANK = "rank"

#: operation -> (operand count, one-line meaning). The arity is part of the
#: contract: an operation given the wrong number of operands is refused
#: before any arithmetic happens.
OPERATIONS: dict[str, tuple[int, str]] = {
    IDENTITY: (1, "the single referenced cell, unchanged"),
    SUM: (1, "the sum of the referenced cells"),
    MIN: (1, "the smallest of the referenced cells"),
    MAX: (1, "the largest of the referenced cells"),
    COUNT: (1, "how many referenced cells hold a value"),
    DIFFERENCE: (2, "sum(first) - sum(second)"),
    RATIO: (2, "sum(first) / sum(second)"),
    PERCENTAGE: (2, "100 * sum(first) / sum(second)"),
    PERCENTAGE_CHANGE: (2,
                        "100 * (sum(first) - sum(second)) / sum(second), "
                        "where the first operand is the later period"),
    SHARE_OF_TOTAL: (2,
                     "sum(first) / sum(second), where the first operand's "
                     "rows must be a subset of the second's"),
    WEIGHTED_AVERAGE: (2,
                       "sum(value * weight) / sum(weight), over the same "
                       "rows in the same order"),
    RANK: (2, "the 1-based position of the first operand's single cell "
              "within the second operand's cells, largest first"),
}

#: Operations whose result is a proportion of one (`ratio`, `share_of_total`)
#: and operations whose result is already multiplied by a hundred. Units are
#: checked against this, because "percent" and "percentage point" being
#: confused is how a 0.4 becomes a 40.
FRACTION_OPERATIONS = frozenset({RATIO, SHARE_OF_TOTAL})
PERCENT_OPERATIONS = frozenset({PERCENTAGE, PERCENTAGE_CHANGE})

#: Unit strings that mean "a proportion expressed out of one hundred".
PERCENT_UNITS = frozenset({"percent", "%", "pct", "percentage"})
#: Unit strings that mean "a proportion of one".
FRACTION_UNITS = frozenset({"ratio", "fraction", "share", "proportion", "x"})

#: A derived figure is compared against the recomputation at this relative
#: tolerance. It is not a licence to be approximately right: it absorbs the
#: last place of a decimal string the analyst rounded for display, and
#: nothing wider. A dropped row moves these figures by whole millions.
DEFAULT_TOLERANCE = Decimal("1e-9")

#: No derivation may reference more cells than this. A claim that needs more
#: is not a claim, it is a table.
MAX_REFS = 500


class DerivationError(Exception):
    """A derivation that cannot be recomputed, with the reason to send back."""


@dataclass(frozen=True)
class CellSet:
    """Cells in ONE column of ONE artifact, named by row id.

    `row_ids` accepts the ids the result packet publishes (`r0`, `r1`, ...),
    a plain index, or a `column=value` key. All three resolve to the same
    rows; the packet publishes the first form because it is stable and
    unambiguous even when two rows share a label.
    """

    artifact_id: str
    column_id: str
    row_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "column_id": self.column_id,
                "row_ids": list(self.row_ids)}


@dataclass(frozen=True)
class Derivation:
    operation: str
    operands: tuple[CellSet, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"operation": self.operation,
                "operands": [o.to_dict() for o in self.operands]}

    @property
    def artifact_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(o.artifact_id for o in self.operands))


def parse(body: Any) -> Derivation:
    """Read a derivation from a model payload, refusing anything unsupported."""
    if not isinstance(body, dict):
        raise DerivationError("A derivation must be an object naming an "
                              "operation and its operands.")
    operation = str(body.get("operation") or "").strip()
    if operation not in OPERATIONS:
        raise DerivationError(
            f"{operation!r} is not a supported derivation. Supported "
            f"operations are: {', '.join(sorted(OPERATIONS))}.")
    raw = body.get("operands")
    if not isinstance(raw, list) or not raw:
        raise DerivationError(
            f"derivation {operation!r} needs an 'operands' list.")
    arity = OPERATIONS[operation][0]
    if len(raw) != arity:
        raise DerivationError(
            f"derivation {operation!r} takes {arity} operand"
            f"{'s' if arity > 1 else ''} ({OPERATIONS[operation][1]}), and "
            f"{len(raw)} were given.")
    operands = []
    total_refs = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise DerivationError(
                f"operand {index} of {operation!r} must be an object naming "
                f"artifact_id, column_id and row_ids.")
        artifact_id = str(item.get("artifact_id") or "").strip()
        column_id = str(item.get("column_id") or "").strip()
        rows = item.get("row_ids")
        if not artifact_id or not column_id:
            raise DerivationError(
                f"operand {index} of {operation!r} must name both an "
                f"artifact_id and a column_id.")
        if not isinstance(rows, list) or not rows:
            raise DerivationError(
                f"operand {index} of {operation!r} must name at least one "
                f"row in 'row_ids'.")
        row_ids = tuple(str(r) for r in rows)
        total_refs += len(row_ids)
        if total_refs > MAX_REFS:
            raise DerivationError(
                f"a single derivation may reference at most {MAX_REFS} "
                f"cells; this one references more. Publish it as a table.")
        operands.append(CellSet(artifact_id, column_id, row_ids))
    return Derivation(operation, tuple(operands))


# ---- resolving cells ---------------------------------------------------

_MISSING = object()


def row_id_for(index: int) -> str:
    """The published id of a result row. Positional, stable within a run."""
    return f"r{index}"


def _index_of(row_id: str, rows: list[dict[str, Any]]) -> int:
    """Resolve a published row id, a bare index, or a `column=value` key."""
    key = str(row_id or "").strip()
    if not key:
        return -1
    if key.startswith("r") and key[1:].isdigit():
        index = int(key[1:])
        return index if 0 <= index < len(rows) else -1
    if key.isdigit():
        index = int(key)
        return index if 0 <= index < len(rows) else -1
    if "=" in key:
        name, _, wanted = key.partition("=")
        name, wanted = name.strip(), wanted.strip()
        for i, row in enumerate(rows):
            if str(row.get(name, "")) == wanted:
                return i
        return -1
    for i, row in enumerate(rows):
        if any(str(v) == key for v in row.values()):
            return i
    return -1


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise DerivationError(
            f"{value!r} is not a number this can compute with.") from exc


@dataclass
class _Resolved:
    values: list[Decimal]
    indices: list[int]


def _resolve(cells: CellSet, artifacts: dict[str, dict[str, Any]],
             *, label: str) -> _Resolved:
    record = artifacts.get(cells.artifact_id)
    if record is None:
        raise DerivationError(
            f"{label} references artifact {cells.artifact_id!r}, which this "
            f"run did not produce or which is not available to you.")
    if cells.column_id not in record["columns"]:
        raise DerivationError(
            f"{label} names column {cells.column_id!r}, which is not in "
            f"artifact {cells.artifact_id!r}. Its columns are "
            f"{record['columns']}.")
    rows = record["rows"]
    seen: set[int] = set()
    values: list[Decimal] = []
    indices: list[int] = []
    for row_id in cells.row_ids:
        index = _index_of(row_id, rows)
        if index < 0:
            raise DerivationError(
                f"{label} names row {row_id!r}, which is not in artifact "
                f"{cells.artifact_id!r}. That artifact has "
                f"{len(rows)} rows, addressed r0 to r{len(rows) - 1}.")
        if index in seen:
            raise DerivationError(
                f"{label} references row {row_id!r} more than once. A cell "
                f"counted twice is not a sum.")
        seen.add(index)
        cell = rows[index].get(cells.column_id, _MISSING)
        if cell is _MISSING:
            raise DerivationError(
                f"{label} names column {cells.column_id!r}, which row "
                f"{row_id!r} does not hold.")
        if cell is None:
            raise DerivationError(
                f"{label} includes row {row_id!r}, whose "
                f"{cells.column_id!r} is NULL. A null is not zero: exclude "
                f"the row and say so, or report the figure as unavailable.")
        values.append(_decimal(cell))
        indices.append(index)
    return _Resolved(values, indices)


# ---- the operations ----------------------------------------------------

def _sum(resolved: _Resolved) -> Decimal:
    return sum(resolved.values, Decimal(0))


def _divide(numerator: Decimal, denominator: Decimal, *, what: str
            ) -> Decimal:
    if denominator == 0:
        raise DerivationError(
            f"{what} divides by zero. A zero base has no meaningful "
            f"percentage: say the base was zero rather than publishing a "
            f"number.")
    return numerator / denominator


def plain(value: Decimal) -> Decimal:
    """The same number, never in exponent notation.

    `Decimal` renders some exact results as "0E+12" or "1E+3", and the
    answer contract requires a plain decimal string -- rightly, because that
    value is quoted to a credit officer. A zero Stage 2 share came back as
    "0E+12" and a correct answer was refused for its formatting, which is
    the engine handing out a value its own contract will not accept. The
    number is unchanged; only its written form is.
    """
    return Decimal(format(value, "f"))


def compute(derivation: Derivation, artifacts: dict[str, dict[str, Any]], *,
            label: str = "this claim") -> Decimal:
    """Recompute a derived value from the stored artifacts. Exact, no floats.

    The result is always in plain form, so `str()` of it is a value the
    answer contract accepts.
    """
    return plain(_compute(derivation, artifacts, label=label))


def _compute(derivation: Derivation, artifacts: dict[str, dict[str, Any]], *,
             label: str) -> Decimal:
    operation = derivation.operation
    resolved = [
        _resolve(cells, artifacts,
                 label=(f"{label} operand {i + 1}" if len(derivation.operands)
                        > 1 else label))
        for i, cells in enumerate(derivation.operands)]

    if operation == IDENTITY:
        if len(resolved[0].values) != 1:
            raise DerivationError(
                f"{label} uses 'identity', which names exactly one cell; "
                f"{len(resolved[0].values)} were given. Use 'sum' for more "
                f"than one.")
        return resolved[0].values[0]
    if operation == SUM:
        return _sum(resolved[0])
    if operation == MIN:
        return min(resolved[0].values)
    if operation == MAX:
        return max(resolved[0].values)
    if operation == COUNT:
        return Decimal(len(resolved[0].values))
    if operation == DIFFERENCE:
        return _sum(resolved[0]) - _sum(resolved[1])
    if operation == RATIO:
        return _divide(_sum(resolved[0]), _sum(resolved[1]), what=label)
    if operation == PERCENTAGE:
        return Decimal(100) * _divide(_sum(resolved[0]), _sum(resolved[1]),
                                      what=label)
    if operation == PERCENTAGE_CHANGE:
        base = _sum(resolved[1])
        return Decimal(100) * _divide(_sum(resolved[0]) - base, base,
                                      what=label)
    if operation == SHARE_OF_TOTAL:
        part, whole = derivation.operands[0], derivation.operands[1]
        if part.artifact_id != whole.artifact_id:
            raise DerivationError(
                f"{label} takes a share of a total across two different "
                f"artifacts. A share must be a part of its own whole.")
        if not set(resolved[0].indices) <= set(resolved[1].indices):
            stray = sorted(set(resolved[0].indices) - set(resolved[1].indices))
            raise DerivationError(
                f"{label} is a share of a total whose numerator includes "
                f"rows the denominator does not: "
                f"{[row_id_for(i) for i in stray]}. The part must be inside "
                f"the whole.")
        return _divide(_sum(resolved[0]), _sum(resolved[1]), what=label)
    if operation == WEIGHTED_AVERAGE:
        values, weights = resolved[0], resolved[1]
        if values.indices != weights.indices:
            raise DerivationError(
                f"{label} is a weighted average whose values and weights "
                f"are not the same rows in the same order. Name the same "
                f"row_ids for both operands.")
        weighted = sum((v * w for v, w in zip(values.values, weights.values)),
                       Decimal(0))
        return _divide(weighted, _sum(weights), what=label)
    if operation == RANK:
        if len(resolved[0].values) != 1:
            raise DerivationError(
                f"{label} ranks one cell within a population; its first "
                f"operand names {len(resolved[0].values)} cells.")
        target = resolved[0].values[0]
        if not set(resolved[0].indices) <= set(resolved[1].indices):
            raise DerivationError(
                f"{label} ranks a row that is not in the population it is "
                f"ranked against.")
        return Decimal(sum(1 for v in resolved[1].values if v > target) + 1)
    raise DerivationError(f"{operation!r} is not a supported derivation.")


# ---- unit agreement ----------------------------------------------------

def unit_problem(derivation: Derivation, unit: str) -> str:
    """Catch the percent / percentage-point / fraction confusions."""
    lowered = str(unit or "").strip().lower()
    if derivation.operation in PERCENT_OPERATIONS:
        if lowered in FRACTION_UNITS:
            return (f"a {derivation.operation!r} derivation already "
                    f"multiplies by a hundred, so its unit cannot be "
                    f"{unit!r}. Use 'percent', or use 'ratio' as the "
                    f"operation.")
        if lowered in {"percentage point", "percentage points", "pp", "bps",
                       "basis points"}:
            return (f"a {derivation.operation!r} derivation produces a "
                    f"percentage, not a {unit}. A difference between two "
                    f"percentages is a percentage point; this is not that.")
    if derivation.operation in FRACTION_OPERATIONS and lowered in PERCENT_UNITS:
        return (f"a {derivation.operation!r} derivation produces a "
                f"proportion of one, so its unit cannot be {unit!r}. Use "
                f"'percentage' as the operation, or state the unit as a "
                f"ratio.")
    if derivation.operation == COUNT and (lowered in PERCENT_UNITS
                                          or lowered in FRACTION_UNITS):
        return f"a count is not measured in {unit!r}."
    return ""


def describe() -> list[dict[str, Any]]:
    """The operation table, for the guide sent with every result packet."""
    return [{"operation": name, "operands": arity, "meaning": meaning}
            for name, (arity, meaning) in sorted(OPERATIONS.items())]


__all__ = [
    "COUNT", "CellSet", "DEFAULT_TOLERANCE", "DIFFERENCE", "Derivation",
    "DerivationError", "FRACTION_OPERATIONS", "IDENTITY", "MAX", "MAX_REFS",
    "MIN", "OPERATIONS", "PERCENTAGE", "PERCENTAGE_CHANGE",
    "PERCENT_OPERATIONS", "RANK", "RATIO", "SHARE_OF_TOTAL", "SUM",
    "WEIGHTED_AVERAGE", "compute", "describe", "parse", "plain",
    "row_id_for",
    "unit_problem"]
