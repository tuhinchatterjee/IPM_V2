"""A cohort selection the SERVER composes, from a shape the model may send.

`cohort.freeze` takes a SQL predicate and says in its own docstring that the
predicate is *"already validated and bound by the caller"*. This module is
that caller, and this is the only place in the What-If candidate where a
fragment of SQL is built from something a model wrote.

## Why a typed selector rather than a predicate

The obvious design is to let the analyst write the `WHERE` clause. It is also
indefensible: `freeze` interpolates the predicate into a `SELECT` over the
exposure relation, so a predicate is a way to run arbitrary SQL against the
book under the run's own session. That is not a small widening of the
existing SQL authorization -- `execute_analysis` puts every query through
`v4_sql.check_structure`, `v4_sql.authorize` and `sqlbind.prove_bindable`
first, and a predicate arriving through `parameters` would reach the database
having passed none of them.

So nothing here is interpolated from model text. A selection is a list of
typed comparisons, and each part of each comparison is checked against
something the release itself declares:

* **the column** must be a column of the book's own exposure relation, by
  exact match against `schema.relations()`. Not a pattern, not a prefix.
* **the operator** must be one of `OPERATORS`, which is a closed tuple of
  seven. There is no `raw`, no `like` with a caller-supplied escape, and no
  operator that can carry a subquery.
* **the value** must survive `_literal`, which emits digits for a number and
  a quoted string for text whose characters are all in `SAFE_CHARS`. A value
  that is not representable is refused, never escaped-and-hoped.

The result is that the worst a malformed selection can do is fail to compile
into a predicate, which is a refused step. It cannot become a second clause.

## What this is not

It is not a query builder. It does not join, aggregate, order, limit or
project, and it never names a relation: `freeze` owns the `FROM`. All it
produces is the inside of one `AND`-joined parenthesised group.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.cockpit_v4 import schema as sc
from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario.errors import COHORT_UNRESOLVED, raise_for

#: The comparisons a selection may make. Closed, and deliberately small.
#:
#: `in` and `not_in` carry a list; the rest carry one value. There is no
#: `like`, because a pattern is a second language inside a string, and no
#: `between`, because two `>=`/`<=` rows say the same thing with no extra
#: parsing. Nothing here can introduce a subquery, a function call or a
#: comment.
OPERATORS: tuple[str, ...] = (
    "=", "!=", ">", ">=", "<", "<=", "in", "not_in")

#: Operators whose value is a LIST rather than a scalar.
LIST_OPERATORS: frozenset[str] = frozenset({"in", "not_in"})

#: What a text value may contain. Letters, digits, and the punctuation that
#: appears in the category names these books actually carry -- space, hyphen,
#: ampersand, full stop, comma, slash, brackets, underscore, colon.
#:
#: The single quote is deliberately NOT in this set, and that is the whole
#: mechanism: because a quote cannot pass this check, `_literal` never has a
#: quote to escape, and there is no escaping routine to get wrong. The cost
#: is real and is accepted -- a book whose sectors were named "Farmers'
#: Co-operative" could not be filtered on that value and would be told so by
#: name. Neither candidate book has such a value (checked against the
#: published categorical columns), and a refusal a reader can see beats an
#: escaping scheme a reader has to trust.
SAFE_CHARS = re.compile(r"^[0-9A-Za-z \-&.,/()_:]+$")

#: How many comparisons one selection may carry. A bound, so a pathological
#: request is refused rather than compiled into a predicate nobody can read.
MAX_FILTERS = 12

#: How many values one `in` may carry, for the same reason.
MAX_VALUES = 200


@dataclass(frozen=True)
class Filter:
    """One checked comparison."""

    column: str
    operator: str
    values: tuple[Any, ...]

    def sql(self) -> str:
        if self.operator in LIST_OPERATORS:
            inside = ", ".join(_literal(v) for v in self.values)
            verb = "IN" if self.operator == "in" else "NOT IN"
            return f"{self.column} {verb} ({inside})"
        return f"{self.column} {self.operator} {_literal(self.values[0])}"

    def describe(self) -> str:
        if self.operator in LIST_OPERATORS:
            shown = ", ".join(str(v) for v in self.values[:6])
            more = ("" if len(self.values) <= 6
                    else f" and {len(self.values) - 6} more")
            verb = "is one of" if self.operator == "in" else "is not one of"
            return f"{self.column} {verb} {shown}{more}"
        return f"{self.column} {self.operator} {self.values[0]}"


@dataclass(frozen=True)
class Selection:
    """A whole selection: its filters, its SQL and its own description."""

    domain_id: str
    filters: tuple[Filter, ...]
    selection: str = ch.BY_ROW

    def predicate(self) -> str:
        """The inside of one `AND`-joined group, or `""` for the whole book."""
        return " AND ".join(f"({f.sql()})" for f in self.filters)

    def describe(self) -> str:
        if not self.filters:
            return "every exposure in the book at this period"
        joined = "; ".join(f.describe() for f in self.filters)
        noun = ("the rows that match" if self.selection == ch.BY_ROW
                else "everything their owners hold")
        return f"{noun}, where {joined}"


def columns_of(domain_id: str) -> tuple[str, ...]:
    """The exposure relation's declared columns, for this book.

    Read from `schema.relations()` rather than from the live table, so a
    column name is checked against what the RELEASE declares it has. A
    catalogue and a table that disagree is a publication defect; either way
    the declared set is the authority a refusal can name.
    """
    grain = ch.GRAIN.get(domain_id)
    if grain is None:
        raise_for(COHORT_UNRESOLVED,
                  f"no exposure relation is recorded for {domain_id!r}.",
                  field_path="domain_id")
    wanted = grain["relation"]
    for spec in sc.relations(domain_id):
        if spec.name == wanted:
            return tuple(str(c) for c in spec.columns)
    raise_for(COHORT_UNRESOLVED,
              f"{wanted!r} is not a relation of the {domain_id} release, so "
              f"a cohort cannot be resolved against it.",
              field_path="domain_id")
    return ()                                    # pragma: no cover - raises


def parse(raw: Any, *, domain_id: str, path: str = "cohort") -> Selection:
    """A typed selection, or a refusal naming exactly what was wrong."""
    if raw is None:
        return Selection(domain_id=domain_id, filters=())
    if not isinstance(raw, Mapping):
        raise_for(COHORT_UNRESOLVED,
                  f"{path} must be an object describing which exposures to "
                  f"stress.", field_path=path)
    unknown = set(raw) - {"filters", "selection"}
    if unknown:
        raise_for(COHORT_UNRESOLVED,
                  f"{path} carries {sorted(unknown)}, which this runtime does "
                  f"not accept. A cohort is a list of typed comparisons and a "
                  f"selection of rows or owners -- there is no free-text "
                  f"predicate, by design.",
                  field_path=path)
    selection = str(raw.get("selection") or ch.BY_ROW)
    if selection not in ch.SELECTIONS:
        raise_for(COHORT_UNRESOLVED,
                  f"{path}.selection must be {ch.BY_ROW!r} (the rows that "
                  f"match) or {ch.BY_OWNER!r} (everything their owners hold). "
                  f"They are different populations and the difference is not "
                  f"a rounding.",
                  field_path=f"{path}.selection")
    entries = raw.get("filters") or []
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise_for(COHORT_UNRESOLVED,
                  f"{path}.filters must be a list of comparisons.",
                  field_path=f"{path}.filters")
    if len(entries) > MAX_FILTERS:
        raise_for(COHORT_UNRESOLVED,
                  f"{path}.filters carries {len(entries)} comparisons and the "
                  f"limit is {MAX_FILTERS}.",
                  field_path=f"{path}.filters")
    allowed = columns_of(domain_id)
    filters = tuple(
        _one(entry, allowed=allowed, path=f"{path}.filters[{i}]")
        for i, entry in enumerate(entries))
    return Selection(domain_id=domain_id, filters=filters,
                     selection=selection)


def _one(raw: Any, *, allowed: Sequence[str], path: str) -> Filter:
    if not isinstance(raw, Mapping):
        raise_for(COHORT_UNRESOLVED, f"{path} must be an object.",
                  field_path=path)
    unknown = set(raw) - {"column", "operator", "value", "values"}
    if unknown:
        raise_for(COHORT_UNRESOLVED,
                  f"{path} carries {sorted(unknown)}, which is not part of a "
                  f"comparison.", field_path=path)
    column = str(raw.get("column") or "")
    if column not in set(allowed):
        raise_for(COHORT_UNRESOLVED,
                  f"{column!r} is not a column of this book's exposure "
                  f"relation, so nothing was selected and nothing was "
                  f"guessed. It has: {', '.join(sorted(allowed))}.",
                  field_path=f"{path}.column")
    operator = str(raw.get("operator") or "=")
    if operator not in OPERATORS:
        raise_for(COHORT_UNRESOLVED,
                  f"{operator!r} is not a comparison this runtime makes. They "
                  f"are: {', '.join(OPERATORS)}.",
                  field_path=f"{path}.operator")
    if operator in LIST_OPERATORS:
        raw_values = raw.get("values")
        if raw_values is None:
            raw_values = raw.get("value")
        if (not isinstance(raw_values, Sequence)
                or isinstance(raw_values, (str, bytes))):
            raise_for(COHORT_UNRESOLVED,
                      f"{path} uses {operator!r}, which compares against a "
                      f"list of values.", field_path=f"{path}.values")
        if not raw_values:
            raise_for(COHORT_UNRESOLVED,
                      f"{path} uses {operator!r} with no values. An empty "
                      f"list selects nothing, which is not the whole book.",
                      field_path=f"{path}.values")
        if len(raw_values) > MAX_VALUES:
            raise_for(COHORT_UNRESOLVED,
                      f"{path} lists {len(raw_values)} values and the limit "
                      f"is {MAX_VALUES}.", field_path=f"{path}.values")
        values = tuple(_checked(v, path=f"{path}.values") for v in raw_values)
    else:
        if "values" in raw and "value" not in raw:
            raise_for(COHORT_UNRESOLVED,
                      f"{path} uses {operator!r}, which compares against one "
                      f"value, not a list.", field_path=f"{path}.value")
        values = (_checked(raw.get("value"), path=f"{path}.value"),)
    return Filter(column=column, operator=operator, values=values)


def literal_value(value: Any, *, path: str) -> Any:
    """A value this module is willing to write into SQL, or a refusal.

    Public because a rule's `where` scope needs exactly the same check as a
    cohort filter's value, and two functions that had to agree about which
    characters are safe would eventually stop agreeing.
    """
    return _checked(value, path=path)


def _checked(value: Any, *, path: str) -> Any:
    """A value this module is willing to write into SQL, or a refusal."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, Decimal)):
        return value
    if isinstance(value, float):
        # Floats do not survive a currency calculation and do not belong in a
        # predicate either. `units`' header is the reason: Decimal everywhere.
        try:
            return Decimal(str(value))
        except InvalidOperation:  # pragma: no cover - unreachable for floats
            raise_for(COHORT_UNRESOLVED,
                      f"{path} is not a number this runtime can compare.",
                      field_path=path)
    text = str(value if value is not None else "")
    if not text:
        raise_for(COHORT_UNRESOLVED,
                  f"{path} is empty. A comparison against nothing is not a "
                  f"comparison.", field_path=path)
    if len(text) > 200:
        raise_for(COHORT_UNRESOLVED,
                  f"{path} is {len(text)} characters long; the limit is 200.",
                  field_path=path)
    if not SAFE_CHARS.match(text):
        bad = sorted({c for c in text if not SAFE_CHARS.match(c)})
        raise_for(COHORT_UNRESOLVED,
                  f"{path} contains {bad}, which this runtime will not write "
                  f"into a query. A category name is letters, digits and "
                  f"ordinary punctuation; anything else is refused rather "
                  f"than escaped.", field_path=path)
    return text


def _literal(value: Any) -> str:
    """One value as SQL. Numbers as digits, text as a quoted string.

    No escaping happens here and none is needed: `_checked` has already
    refused every character that would need it, so a quote cannot reach this
    function. That ordering is the point -- an escaping routine is a thing
    that can be wrong, and a character allowlist checked earlier is not.
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, Decimal)):
        return str(value)
    text = str(value)
    if not SAFE_CHARS.match(text):
        # Reachable only if `_checked` were bypassed. Refuse rather than
        # escape: a caller who skipped the check is the defect, and an
        # escaping branch here would be the one path nothing has tested.
        raise_for(COHORT_UNRESOLVED,
                  "an unchecked value reached the SQL writer. Nothing was "
                  "quoted and nothing was run.",
                  field_path="cohort.filters")
    return f"'{text}'"


__all__ = ["Filter", "LIST_OPERATORS", "MAX_FILTERS", "MAX_VALUES",
           "OPERATORS", "SAFE_CHARS", "Selection", "columns_of",
           "literal_value", "parse"]
