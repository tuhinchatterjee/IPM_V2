"""
Typed filters -> SQL, the only way a workspace request narrows a book.

A filter is `{"column", "op", "value" | "values"}`. The column must be a
declared column of the book's exposure relation (exact match against the
release schema, the same authority `scenario/selector.py` uses); the operator
comes from a closed set; values are type-checked. Two compilations:

* `bound(filters)` -> `(sql, params)` with `?` placeholders, for grid queries,
  aggregates and exports. User text never reaches the SQL string (SEC01).
* `literal(filters)` -> a predicate with literals checked against the
  scenario selector's allowlist (plus `+` for rating grades), for
  `scenario.cohort.freeze`, which takes a predicate string and says the
  caller must have validated it. This module is that caller; a value the
  selector would refuse is refused here too, never escaped.

Both compile the same filter list to the same row set, which
`test_bound_and_literal_predicates_select_the_same_rows` pins.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

#: The closed operator set.
OPS: tuple[str, ...] = ("eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in",
                        "contains", "between", "is_null", "not_null",
                        "is_true", "is_false")
_CMP = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<",
        "lte": "<="}
MAX_FILTERS = 24
MAX_VALUES = 500

#: What a text value may contain: the scenario selector's allowlist plus `+`
#: (rating grades such as "BB+"). No quote, backslash, semicolon or comment
#: marker can pass, so a literal never needs escaping -- it is refused instead.
SAFE_TEXT = re.compile(r"^[0-9A-Za-z \-&.,/()_:+]+$")


def _refuse(message: str, **extra: Any) -> None:
    raise HTTPException(422, {"error_code": "INVALID_FILTER",
                              "message": message, **extra})


def normalise(raw: Any, *, columns: Sequence[str]) -> list[dict[str, Any]]:
    """Checked, canonical filters, or a refusal naming what was wrong."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        _refuse("filters must be a list of {column, op, value} objects.")
    if len(raw) > MAX_FILTERS:
        _refuse(f"{len(raw)} filters; the limit is {MAX_FILTERS}.")
    allowed = set(columns)
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            _refuse(f"filters[{i}] must be an object.")
        unknown = set(item) - {"column", "op", "value", "values"}
        if unknown:
            _refuse(f"filters[{i}] carries {sorted(unknown)}; a filter is a "
                    f"column, an operator and a value -- there is no "
                    f"free-text predicate.")
        column = str(item.get("column") or "")
        if column not in allowed:
            _refuse(f"{column!r} is not a column of this book's exposure "
                    f"relation; nothing was guessed.", column=column)
        op = str(item.get("op") or "eq")
        if op not in OPS:
            _refuse(f"{op!r} is not an operator; they are {list(OPS)}.")
        entry: dict[str, Any] = {"column": column, "op": op}
        if op in ("in", "not_in"):
            values = item.get("values", item.get("value"))
            if (not isinstance(values, Sequence)
                    or isinstance(values, (str, bytes)) or not values):
                _refuse(f"filters[{i}] {op} needs a non-empty list.")
            if len(values) > MAX_VALUES:
                _refuse(f"filters[{i}] lists {len(values)} values; the limit "
                        f"is {MAX_VALUES}.")
            entry["values"] = [_scalar(v, i) for v in values]
        elif op == "between":
            values = item.get("values")
            if not isinstance(values, Sequence) or len(values) != 2:
                _refuse(f"filters[{i}] between needs [low, high].")
            low, high = values
            entry["values"] = [None if low in (None, "") else _number(low, i),
                               None if high in (None, "")
                               else _number(high, i)]
            if entry["values"] == [None, None]:
                _refuse(f"filters[{i}] between needs at least one bound.")
        elif op in ("is_null", "not_null", "is_true", "is_false"):
            pass
        elif op == "contains":
            entry["value"] = _text(item.get("value"), i)
        else:
            entry["value"] = _scalar(item.get("value"), i)
        out.append(entry)
    return out


def _number(value: Any, i: int) -> Any:
    if isinstance(value, bool):
        _refuse(f"filters[{i}] expects a number.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        _refuse(f"filters[{i}] expects a number, not {str(value)[:40]!r}.")
    return None  # pragma: no cover


def _text(value: Any, i: int) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        _refuse(f"filters[{i}] is empty.")
    if len(text) > 200 or not SAFE_TEXT.match(text):
        _refuse(f"filters[{i}] contains characters this runtime will not "
                f"write into a query. Letters, digits and ordinary "
                f"punctuation only; nothing is escaped.")
    return text


def _scalar(value: Any, i: int) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value if value is not None else "")
    try:
        if text and text.lstrip("-").replace(".", "", 1).isdigit():
            return Decimal(text)
    except InvalidOperation:  # pragma: no cover
        pass
    return _text(text, i)


def bound(filters: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    """`(sql, params)`: placeholders only; column names are allowlisted."""
    parts: list[str] = []
    params: list[Any] = []
    for f in filters:
        col, op = f["column"], f["op"]
        if op in _CMP:
            parts.append(f"{col} {_CMP[op]} ?")
            params.append(_param(f["value"]))
        elif op in ("in", "not_in"):
            marks = ", ".join("?" for _ in f["values"])
            parts.append(f"{col} {'IN' if op == 'in' else 'NOT IN'} ({marks})")
            params.extend(_param(v) for v in f["values"])
        elif op == "contains":
            parts.append(f"contains(lower(CAST({col} AS VARCHAR)), lower(?))")
            params.append(f["value"])
        elif op == "between":
            low, high = f["values"]
            if low is not None:
                parts.append(f"{col} >= ?")
                params.append(float(low))
            if high is not None:
                parts.append(f"{col} <= ?")
                params.append(float(high))
        elif op == "is_null":
            parts.append(f"{col} IS NULL")
        elif op == "not_null":
            parts.append(f"{col} IS NOT NULL")
        elif op == "is_true":
            parts.append(f"{col} = TRUE")
        elif op == "is_false":
            parts.append(f"{col} = FALSE")
    return " AND ".join(f"({p})" for p in parts), params


def _param(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def literal(filters: list[dict[str, Any]]) -> str:
    """The same predicate with allowlist-checked literals, for `cohort.freeze`."""
    def lit(value: Any) -> str:
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, Decimal)):
            return str(value)
        if isinstance(value, float):
            return str(Decimal(str(value)))
        text = str(value)
        if not SAFE_TEXT.match(text):
            # Reachable only if `normalise` were bypassed: refuse, never escape.
            _refuse("an unchecked value reached the SQL writer; nothing ran.")
        return f"'{text}'"

    parts: list[str] = []
    for f in filters:
        col, op = f["column"], f["op"]
        if op in _CMP:
            parts.append(f"{col} {_CMP[op]} {lit(f['value'])}")
        elif op in ("in", "not_in"):
            inside = ", ".join(lit(v) for v in f["values"])
            parts.append(f"{col} {'IN' if op == 'in' else 'NOT IN'} ({inside})")
        elif op == "contains":
            parts.append(f"contains(lower(CAST({col} AS VARCHAR)), "
                         f"lower({lit(f['value'])}))")
        elif op == "between":
            low, high = f["values"]
            if low is not None:
                parts.append(f"{col} >= {lit(low)}")
            if high is not None:
                parts.append(f"{col} <= {lit(high)}")
        elif op == "is_null":
            parts.append(f"{col} IS NULL")
        elif op == "not_null":
            parts.append(f"{col} IS NOT NULL")
        elif op == "is_true":
            parts.append(f"{col} = TRUE")
        elif op == "is_false":
            parts.append(f"{col} = FALSE")
    return " AND ".join(f"({p})" for p in parts)


def predicate_hash(filters: list[dict[str, Any]], *, selection: str,
                   period: str, domain_id: str) -> str:
    """The identity of the QUESTION a cohort asked (the membership hash is the
    identity of the ANSWER). Canonical, so equal filters hash equally."""
    canon = sorted(json.dumps(f, sort_keys=True, default=str)
                    for f in filters)
    blob = json.dumps({"filters": canon, "selection": selection,
                       "period": period, "domain": domain_id},
                      sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def describe(filters: list[dict[str, Any]]) -> str:
    words = {"eq": "=", "neq": "≠", "gt": ">", "gte": "≥", "lt": "<",
             "lte": "≤", "in": "is one of", "not_in": "is not one of",
             "contains": "contains", "between": "between",
             "is_null": "is empty", "not_null": "is not empty",
             "is_true": "is yes", "is_false": "is no"}
    out = []
    for f in filters:
        if "values" in f:
            shown = ", ".join(str(v) for v in f["values"][:5]
                              if v is not None)
            more = f" (+{len(f['values']) - 5})" if len(f["values"]) > 5 else ""
            out.append(f"{f['column']} {words[f['op']]} {shown}{more}")
        elif "value" in f:
            out.append(f"{f['column']} {words[f['op']]} {f['value']}")
        else:
            out.append(f"{f['column']} {words[f['op']]}")
    return "; ".join(out) or "the whole book"


__all__ = ["MAX_FILTERS", "OPS", "bound", "describe", "literal", "normalise",
           "predicate_hash"]
