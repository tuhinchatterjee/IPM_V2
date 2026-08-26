"""
Arithmetic that has to hold before an answer is allowed on the screen.

The failure this exists for
---------------------------
    "Which large Real Estate customers have worsening DPD, increasing ECL, a
     rating downgrade and covenant headroom below 15%?"

came back with a borrower at **16.17% headroom**, in a table headed by a
question that said below 15. One parse had gone wrong upstream. The parse is
fixed, but a product whose correctness depends on every parse being right is a
product that will print this again next quarter under a different heading.

So the claim is checked against the result. The question said *below 15%*; every
row is tested for it; a row that is not below 15% means the answer does not
match the question, and the answer does not ship.

Why check the result rather than the plan
-----------------------------------------
A plan can be reviewed and still be wrong — the filter can be right and applied
at the wrong grain, or applied after an aggregation that has already averaged
the thing being filtered. The result is the artefact the user acts on, and it is
the only place where "the answer matches the question" is a fact rather than an
argument.

What a failure does
-------------------
Blocks the display. Not a warning under the table: a warning under a number is
read by nobody, and a credit officer who has seen the number has already
believed it. The orchestrator gets one repair attempt; if the repaired plan
fails too, the user is told plainly what could not be guaranteed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Floating point comparisons need a little room. A headroom stored as
#: 14.999999999999998 satisfies "below 15" and would fail an exact test, which
#: would block a correct answer — the worst possible outcome for a check whose
#: whole purpose is trust.
TOLERANCE = 1e-9

#: Relative tolerance for a share that should not exceed its total. Percentages
#: computed in floating point over millions of rows drift in the last place.
SHARE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Check:
    """One thing that must be true of the result."""

    rule: str
    #: What the user asked for, in their words where possible.
    claim: str
    #: The columns it is tested against.
    columns: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "claim": self.claim,
                "columns": list(self.columns), "params": dict(self.params)}


@dataclass
class Failure:
    """One check that did not hold, and the row that proves it."""

    check: Check
    detail: str
    example: dict[str, Any] = field(default_factory=dict)
    offending: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.check.rule, "claim": self.check.claim,
                "detail": self.detail, "offending_rows": self.offending,
                "example": dict(self.example)}


@dataclass
class Report:
    """What was checked, and what did not hold."""

    checks: list[Check] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    #: Checks that could not run because the column was not in the result.
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def sentence(self) -> str:
        """Why the answer is not being shown, in one paragraph."""
        if self.ok:
            return ""
        lines = [f.detail for f in self.failures]
        return (
            "CreditProbe computed an answer and then found it did not match "
            "the question, so it is not showing it. "
            + " ".join(lines)
            + " Rather than present a table whose rows contradict its own "
            "heading, CreditProbe has stopped.")

    def to_dict(self) -> dict[str, Any]:
        return {"checked": [c.to_dict() for c in self.checks],
                "passed": len(self.checks) - len(self.failures),
                "failed": [f.to_dict() for f in self.failures],
                "skipped": list(self.skipped),
                "ok": self.ok}


# ---------------------------------------------------------------------------
# Compiling the checks from what was asked
# ---------------------------------------------------------------------------

_OPS = {
    "lt": ("below", lambda a, b: a < b + TOLERANCE),
    "lte": ("at most", lambda a, b: a <= b + TOLERANCE),
    "gt": ("above", lambda a, b: a > b - TOLERANCE),
    "gte": ("at least", lambda a, b: a >= b - TOLERANCE),
    "eq": ("equal to", lambda a, b: abs(a - b) <= TOLERANCE),
}


def compile_checks(build: Any, question: str = "") -> list[Check]:
    """Everything the answer promised, as checks against its own rows."""
    checks: list[Check] = []

    top_n = int(getattr(build, "top_n", 0) or 0)
    if top_n:
        checks.append(Check(
            rule="row_limit",
            claim=f"the {top_n} asked for",
            params={"limit": top_n}))

    for field_name, value in (getattr(build, "filters", None) or []):
        checks.append(Check(
            rule="filter_equality",
            claim=f"{field_name.replace('_', ' ')} is {value}",
            columns=(field_name,),
            params={"column": field_name, "value": value}))

    for condition in (getattr(build, "conditions", None) or []):
        checks.extend(_from_condition(condition))

    if getattr(build, "shape", "") == "share_movement":
        checks.extend([
            Check(rule="numerator_within_denominator",
                  claim="the qualifying amount cannot exceed the total",
                  columns=("opening_qualified", "opening_total"),
                  params={"numerator": "opening_qualified",
                          "denominator": "opening_total"}),
            Check(rule="numerator_within_denominator",
                  claim="the qualifying amount cannot exceed the total",
                  columns=("closing_qualified", "closing_total"),
                  params={"numerator": "closing_qualified",
                          "denominator": "closing_total"}),
            Check(rule="share_bounds",
                  claim="a share lies between 0 and 100%",
                  columns=("opening_share_pct", "closing_share_pct"),
                  params={"minimum": 0.0, "maximum": 100.0}),
        ])

    checks.extend(_from_ontology(build))
    checks.extend(_from_question(question, build))
    return checks


def _from_condition(condition: Any) -> list[Check]:
    """The check a movement or level condition promises about every row."""
    column = getattr(condition, "column", "")
    kind = getattr(condition, "kind", "")
    op = getattr(condition, "op", "")
    value = getattr(condition, "value", None)
    if not column or op not in _OPS or not isinstance(value, (int, float)):
        return []

    word = _OPS[op][0]
    if kind == "level":
        claim = f"{_readable(column)} is {word} {_number(value)}"
    else:
        moved = "the change in " + _readable(getattr(condition, "field", column))
        claim = f"{moved} is {word} {_number(value)}"
    return [Check(rule="condition", claim=claim, columns=(column,),
                  params={"column": column, "op": op, "value": float(value)})]


def _from_ontology(build: Any) -> list[Check]:
    """Contract invariants for every concept the answer reports."""
    from backend.semantics import ontology

    checks: list[Check] = []
    for match in (getattr(build, "matches", None) or []):
        contract = ontology.contract(getattr(match.concept, "id", ""))
        if contract is None:
            continue
        for invariant in contract.invariants:
            if invariant.rule == "non_negative":
                checks.append(Check(
                    rule="non_negative", claim=invariant.detail,
                    columns=(match.field,),
                    params={"column": match.field}))
            elif invariant.rule == "ordinal_range":
                checks.append(Check(
                    rule="ordinal_range", claim=invariant.detail,
                    columns=(match.field,),
                    params={"column": match.field, **invariant.params}))
    return checks


_UNIQUE = re.compile(r"\b(?:each|per|one row per|distinct|unique)\s+"
                     r"(customer|borrower|facility|account)\b", re.I)


def _from_question(question: str, build: Any) -> list[Check]:
    """Checks the sentence itself promises, beyond what the plan recorded."""
    checks: list[Check] = []
    grain = str(getattr(build, "grain", "") or "")
    key = {"customer": "customer_id", "facility": "account_id"}.get(grain, "")
    if key and _UNIQUE.search(question or ""):
        checks.append(Check(
            rule="unique_key",
            claim=f"one row per {grain}",
            columns=(key,), params={"column": key}))
    return checks


def _readable(column: str) -> str:
    return str(column or "").replace("_", " ").strip()


def _number(value: Any) -> str:
    number = float(value)
    return f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"


# ---------------------------------------------------------------------------
# Running them
# ---------------------------------------------------------------------------


def verify(checks: list[Check], runtime: Any) -> Report:
    """Test every check against the rows the runtime actually returned."""
    report = Report(checks=list(checks))
    rows = list(getattr(runtime, "rows", []) or [])
    columns = {str(c.get("name") if isinstance(c, dict) else getattr(c, "name", c))
               for c in (getattr(runtime, "columns", []) or [])}

    for check in checks:
        missing = [c for c in check.columns if c and c not in columns]
        if missing:
            report.skipped.append(
                f"{check.claim} — the result does not carry "
                f"{', '.join(missing)}.")
            continue
        failure = _run(check, rows, runtime)
        if failure is not None:
            report.failures.append(failure)
    return report


def _run(check: Check, rows: list[dict[str, Any]], runtime: Any) -> Failure | None:
    handler = _HANDLERS.get(check.rule)
    if handler is None:
        return None
    try:
        return handler(check, rows, runtime)
    except Exception as e:  # noqa: BLE001 - a broken check must not lose an answer
        logger.warning("Invariant %s could not be evaluated: %s", check.rule, e)
        return None


def _row_limit(check: Check, rows: list[dict[str, Any]], runtime: Any) -> Failure | None:
    limit = int(check.params.get("limit") or 0)
    total = int(getattr(runtime, "row_count", len(rows)) or len(rows))
    if not limit or total <= limit:
        return None
    return Failure(
        check=check, offending=total - limit,
        detail=(f"The question asked for {limit} and the answer has {total} "
                "rows."))


def _filter_equality(check: Check, rows: list[dict[str, Any]],
                     runtime: Any) -> Failure | None:
    del runtime
    column = str(check.params["column"])
    wanted = str(check.params["value"]).strip().lower()
    bad = [r for r in rows
           if str(r.get(column, "")).strip().lower() != wanted]
    if not bad:
        return None
    return Failure(
        check=check, offending=len(bad), example=dict(bad[0]),
        detail=(f"The question restricted {_readable(column)} to "
                f"{check.params['value']}, and {len(bad)} of {len(rows)} rows "
                f"are not — the first is {bad[0].get(column)!r}."))


def _condition(check: Check, rows: list[dict[str, Any]],
               runtime: Any) -> Failure | None:
    del runtime
    column = str(check.params["column"])
    op = str(check.params["op"])
    value = float(check.params["value"])
    holds = _OPS[op][1]

    bad = []
    for row in rows:
        actual = row.get(column)
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            continue
        if not holds(float(actual), value):
            bad.append(row)
    if not bad:
        return None
    return Failure(
        check=check, offending=len(bad), example=dict(bad[0]),
        detail=(f"The question asked for {check.claim}, and {len(bad)} of "
                f"{len(rows)} rows are not — the first is "
                f"{bad[0].get(column)}."))


def _numerator_within(check: Check, rows: list[dict[str, Any]],
                      runtime: Any) -> Failure | None:
    del runtime
    numerator = str(check.params["numerator"])
    denominator = str(check.params["denominator"])
    bad = [r for r in rows
           if isinstance(r.get(numerator), (int, float))
           and isinstance(r.get(denominator), (int, float))
           and float(r[numerator]) > float(r[denominator]) * (1 + SHARE_TOLERANCE)]
    if not bad:
        return None
    return Failure(
        check=check, offending=len(bad), example=dict(bad[0]),
        detail=(f"{_readable(numerator)} exceeds {_readable(denominator)} in "
                f"{len(bad)} rows, which cannot happen if they were taken over "
                "the same population."))


def _share_bounds(check: Check, rows: list[dict[str, Any]],
                  runtime: Any) -> Failure | None:
    del runtime
    low = float(check.params.get("minimum", 0.0))
    high = float(check.params.get("maximum", 100.0))
    for column in check.columns:
        bad = [r for r in rows
               if isinstance(r.get(column), (int, float))
               and not (low - TOLERANCE <= float(r[column]) <= high + TOLERANCE)]
        if bad:
            return Failure(
                check=check, offending=len(bad), example=dict(bad[0]),
                detail=(f"{_readable(column)} is {bad[0][column]}, outside the "
                        f"{low:g} to {high:g} a share has to lie in."))
    return None


def _non_negative(check: Check, rows: list[dict[str, Any]],
                  runtime: Any) -> Failure | None:
    del runtime
    column = str(check.params["column"])
    bad = [r for r in rows
           if isinstance(r.get(column), (int, float))
           and not isinstance(r.get(column), bool)
           and float(r[column]) < -TOLERANCE]
    if not bad:
        return None
    return Failure(
        check=check, offending=len(bad), example=dict(bad[0]),
        detail=(f"{_readable(column)} is {bad[0][column]} in {len(bad)} rows, "
                "and it cannot be negative."))


def _ordinal_range(check: Check, rows: list[dict[str, Any]],
                   runtime: Any) -> Failure | None:
    del runtime
    column = str(check.params["column"])
    low = float(check.params.get("minimum", 0))
    high = float(check.params.get("maximum", 0))
    if not high:
        return None
    bad = [r for r in rows
           if isinstance(r.get(column), (int, float))
           and not isinstance(r.get(column), bool)
           and not (low <= float(r[column]) <= high)]
    if not bad:
        return None
    return Failure(
        check=check, offending=len(bad), example=dict(bad[0]),
        detail=(f"{_readable(column)} is {bad[0][column]}, outside the "
                f"{low:g} to {high:g} the governed scale allows."))


def _unique_key(check: Check, rows: list[dict[str, Any]],
                runtime: Any) -> Failure | None:
    del runtime
    column = str(check.params["column"])
    seen: set[str] = set()
    duplicates: list[dict[str, Any]] = []
    for row in rows:
        identity = str(row.get(column, ""))
        if identity and identity in seen:
            duplicates.append(row)
        seen.add(identity)
    if not duplicates:
        return None
    return Failure(
        check=check, offending=len(duplicates), example=dict(duplicates[0]),
        detail=(f"The answer promises {check.claim} and {column} repeats "
                f"{len(duplicates)} times — the rows are at a finer grain than "
                "the question asked for."))


_HANDLERS: dict[str, Any] = {
    "row_limit": _row_limit,
    "filter_equality": _filter_equality,
    "condition": _condition,
    "numerator_within_denominator": _numerator_within,
    "share_bounds": _share_bounds,
    "non_negative": _non_negative,
    "ordinal_range": _ordinal_range,
    "unique_key": _unique_key,
}


def check_result(build: Any, runtime: Any, question: str = "") -> Report:
    """Compile and run every invariant this answer promised."""
    try:
        return verify(compile_checks(build, question), runtime)
    except Exception as e:  # noqa: BLE001
        logger.warning("Invariants could not be compiled: %s", e)
        return Report()


__all__ = ["Check", "Failure", "Report", "check_result", "compile_checks",
           "verify"]
