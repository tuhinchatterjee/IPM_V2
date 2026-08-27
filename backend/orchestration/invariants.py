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
from dataclasses import dataclass, field, replace
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
                  params={"column": column, "op": op, "value": float(value),
                          # Carried so the resolver can tell a LEVEL from a
                          # MOVEMENT. In a two-period result the bare column
                          # holds the opening value and `closing_` holds the
                          # present one, and "have headroom below 15%" is a
                          # claim about the present.
                          "kind": kind})]


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


#: "over the latest year", "in the past twelve months". A window the question
#: named, which the plan is free to satisfy with any two periods it likes
#: unless somebody checks.
_A_YEAR = re.compile(
    r"\b(?:latest|last|past|previous|trailing)\s+"
    r"(?:one\s+)?(?:year|12\s*months|twelve\s*months)\b"
    r"|\byear[- ]on[- ]year\b|\byoy\b", re.I)

#: A quarter label, so a window can be measured rather than trusted.
_QUARTER = re.compile(r"^\s*Q([1-4])\s+((?:19|20)\d{2})\s*$")


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

    # "Over the latest year" is a promise about the window, and the window is
    # chosen by the planner. A two-quarter comparison presented under a
    # year-on-year heading is wrong by three quarters and looks identical to
    # the right answer.
    opening = str(getattr(build, "opening", "") or "")
    closing = str(getattr(build, "closing", "") or "")
    if opening and closing and _A_YEAR.search(question or ""):
        checks.append(Check(
            rule="period_span",
            claim="the two periods compared are a year apart",
            params={"opening": opening, "closing": closing, "quarters": 4}))

    # "Rank by EAD" promises an order. A ranking whose rows are not in that
    # order is a list, and the reader will still read the first row as the
    # largest.
    ranked = _ranking_column(build)
    if ranked:
        checks.append(Check(
            rule="ordering",
            claim=f"ranked by {_readable(ranked)}, largest first",
            columns=(ranked,),
            params={"column": ranked, "direction": "desc"}))
    return checks


def _ranking_column(build: Any) -> str:
    """The measure a ranking promised to be ordered by, if it promised one."""
    if str(getattr(build, "shape", "") or "") != "ranking":
        return ""
    matches = list(getattr(build, "matches", None) or [])
    if not matches:
        return ""
    # An explicit ordering condition wins over the first measure: "show the
    # five largest by EAD, with their ECL" names two and orders by one.
    for condition in (getattr(build, "conditions", None) or []):
        if str(getattr(condition, "kind", "")) == "order":
            return str(getattr(condition, "column", "") or "")
    return str(getattr(matches[0], "field", "") or "")


def _readable(column: str) -> str:
    return str(column or "").replace("_", " ").strip()


def _number(value: Any) -> str:
    number = float(value)
    return f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"


# ---------------------------------------------------------------------------
# Running them
# ---------------------------------------------------------------------------


def _resolve(check: Check, columns: set[str]) -> Check:
    """The same check, against the names the result actually used.

    A condition is compiled from the governed field — `headroom_pct` — while
    the runtime emits it qualified by the dataset it came from,
    `covenant_tests_headroom_pct`. Left unresolved, the check was quietly
    skipped, which meant the one invariant written to catch "16.17% under a
    heading that says below 15%" would not have caught it.

    Only an UNAMBIGUOUS suffix match is accepted. Two columns ending in the
    same field name means the check cannot tell which one the claim was about,
    and guessing between them is how a check starts verifying the wrong number.

    A LEVEL condition is the exception, and it is the exception that matters. A
    two-period result carries the opening value under the bare name and the
    present one under `closing_`. "Customers who HAVE headroom below 15%" is a
    claim about the present, and checking it against the opening column passed
    while the answer contained a customer sitting at 17.41% today.
    """
    at_close = str(check.params.get("kind") or "") == "level"

    mapping: dict[str, str] = {}
    for wanted in check.columns:
        if not wanted or (wanted in columns and not at_close):
            continue
        matches = [c for c in columns if c.endswith(f"_{wanted}") or c == wanted]
        preferred = [c for c in matches if c.startswith("closing_")]
        rest = [c for c in matches if not c.startswith("closing_")]
        # A movement condition is about the change, so a `closing_` alias never
        # stands in for the column it asked about; a level condition wants
        # exactly that alias where the result has one.
        matches = (preferred or rest) if at_close else (rest or preferred)
        if len(matches) == 1:
            mapping[wanted] = matches[0]

    if not mapping:
        return check
    params = {k: mapping.get(v, v) if isinstance(v, str) else v
              for k, v in check.params.items()}
    return replace(check,
                   columns=tuple(mapping.get(c, c) for c in check.columns),
                   params=params)


def verify(checks: list[Check], runtime: Any) -> Report:
    """Test every check against the rows the runtime actually returned."""
    rows = list(getattr(runtime, "rows", []) or [])
    columns = {str(c.get("name") if isinstance(c, dict) else getattr(c, "name", c))
               for c in (getattr(runtime, "columns", []) or [])}

    resolved = [_resolve(check, columns) for check in checks]
    report = Report(checks=resolved)

    for check in resolved:
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


def _period_span(check: Check, rows: list[dict[str, Any]],
                 runtime: Any) -> Failure | None:
    """Whether the two periods compared are as far apart as the question said."""
    del rows, runtime
    opening = _quarter_index(str(check.params.get("opening") or ""))
    closing = _quarter_index(str(check.params.get("closing") or ""))
    wanted = int(check.params.get("quarters") or 0)
    if opening is None or closing is None or not wanted:
        return None
    apart = closing - opening
    if apart == wanted:
        return None
    return Failure(
        check=check, offending=1,
        detail=(f"The question asked for a comparison a year apart and the "
                f"analysis compared {check.params.get('opening')} with "
                f"{check.params.get('closing')}, which is {apart} "
                f"{'quarter' if abs(apart) == 1 else 'quarters'}."))


def _quarter_index(label: str) -> int | None:
    """A quarter as a number of quarters, so two of them can be subtracted."""
    found = _QUARTER.match(label or "")
    if not found:
        return None
    return int(found.group(2)) * 4 + int(found.group(1)) - 1


def _ordering(check: Check, rows: list[dict[str, Any]],
              runtime: Any) -> Failure | None:
    """Whether a ranking is actually in the order it claims."""
    del runtime
    column = str(check.params.get("column") or "")
    descending = str(check.params.get("direction") or "desc") == "desc"
    values = [row.get(column) for row in rows]
    numbers = [float(v) for v in values
               if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(numbers) < 2 or len(numbers) != len(values):
        return None
    for index in range(len(numbers) - 1):
        left, right = numbers[index], numbers[index + 1]
        if (left < right - TOLERANCE) if descending else (left > right + TOLERANCE):
            return Failure(
                check=check, offending=1,
                example={"row": index + 2, column: right},
                detail=(f"The answer claims to be ranked by "
                        f"{_readable(column)} and row {index + 2} is larger "
                        f"than row {index + 1}."))
    return None


_HANDLERS: dict[str, Any] = {
    "row_limit": _row_limit,
    "period_span": _period_span,
    "ordering": _ordering,
    "filter_equality": _filter_equality,
    "condition": _condition,
    "numerator_within_denominator": _numerator_within,
    "share_bounds": _share_bounds,
    "non_negative": _non_negative,
    "ordinal_range": _ordinal_range,
    "unique_key": _unique_key,
}


def _from_result(runtime: Any) -> list[Check]:
    """Checks the RESULT earns, whatever the plan intended.

    A share is bounds-checked because it is on the screen, not because the plan
    declared itself a share analysis. "What is total EAD by sector?" returns a
    percentage-of-book column alongside the amount, and gating that only on the
    `share_movement` shape left the one number a credit officer reads off the
    table as the one number nothing verified.

    Derived from the column names the runtime actually produced, so a new plan
    shape that emits a share inherits the check without being taught to.
    """
    checks: list[Check] = []
    columns = [str(c.get("name") if isinstance(c, dict) else getattr(c, "name", c))
               for c in (getattr(runtime, "columns", []) or [])]
    known = set(columns)

    shares = [c for c in columns if c == "share_pct" or c.endswith("_share_pct")]
    if shares:
        checks.append(Check(
            rule="share_bounds",
            claim="a share lies between 0 and 100%",
            columns=tuple(shares),
            params={"minimum": 0.0, "maximum": 100.0}))

    # `ead` beside `ead_population` is a part and its whole. The part cannot
    # exceed it, and a join that fanned out is exactly how it would.
    for column in columns:
        whole = f"{column}_population"
        if whole in known:
            checks.append(Check(
                rule="numerator_within_denominator",
                claim=f"{_readable(column)} cannot exceed the population it is "
                      "measured against",
                columns=(column, whole),
                params={"numerator": column, "denominator": whole}))
    return checks


def check_result(build: Any, runtime: Any, question: str = "") -> Report:
    """Compile and run every invariant this answer promised."""
    try:
        checks = compile_checks(build, question)
        seen = {(c.rule, c.columns) for c in checks}
        checks.extend(c for c in _from_result(runtime)
                      if (c.rule, c.columns) not in seen)
        return verify(checks, runtime)
    except Exception as e:  # noqa: BLE001
        logger.warning("Invariants could not be compiled: %s", e)
        return Report()


# ---------------------------------------------------------------------------
# The same checks, against the sentence rather than the rows
# ---------------------------------------------------------------------------
#
# The row checks above would not have caught the failure that made this
# necessary. A screen for covenant headroom below 15% returned rows that all
# satisfied it, and the PROSE above the table named a borrower at 16.17%. Every
# figure was real, every row was correct, and the answer contradicted its own
# heading — which is the single most damaging thing this product can do,
# because it is the sentence a credit officer quotes.

#: How close a figure has to be to the measure's name to be read as a claim
#: about it. Within one clause, in practice.
PROSE_WINDOW = 70

_PROSE_NUMBER = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(%|pp|x)?")


def check_prose(checks: list[Check], texts: list[str], *,
                labels: dict[str, str] | None = None,
                units: dict[str, str] | None = None) -> list[Failure]:
    """Every threshold the question set, tested against what the answer SAYS.

    Only threshold checks on a level — "headroom below 15%", "ECL coverage
    above 20%". A movement condition is about a change and is not something a
    sentence quotes as a level, so testing prose against it would flag correct
    writing.

    Deliberately conservative, in three ways that each removed a whole class of
    false positive:

    * The figure must sit within `PROSE_WINDOW` characters of the measure's own
      name, in the same sentence.
    * It must carry the measure's UNIT. Without that rule the demonstration
      book's borrower names — "Al Rajhi Contracting 4471" — were read as
      headroom figures of 4,471%, and a check that flags correct answers is a
      check that gets turned off.
    * A figure equal to the threshold is the threshold being restated, not a
      value violating it.

    A measure whose unit cannot be established is not checked at all. A bare
    number beside a bare measure cannot be told apart from an account code, and
    guessing is how this stops being trustworthy.
    """
    out: list[Failure] = []
    for check in checks:
        if check.rule != "condition":
            continue
        column = str(check.params.get("column") or "")
        op = str(check.params.get("op") or "")
        bound = check.params.get("value")
        if not column or op not in _OPS or not isinstance(bound, (int, float)):
            continue
        # A change is not a level. "ECL rose by 22%" under "ECL rose more than
        # 20%" is correct writing and must not be flagged.
        if column.endswith(("_change", "_change_pct")):
            continue

        unit = _unit_for(column, (units or {}).get(column, ""))
        if not unit:
            continue

        vocabulary = _vocabulary(column, (labels or {}).get(column, ""))
        satisfies = _OPS[op][1]
        for text in texts:
            found = _violating(text, vocabulary, satisfies, float(bound), unit)
            if found is None:
                continue
            value, sentence = found
            out.append(Failure(
                check=check, offending=1,
                example={"value": value, "sentence": sentence[:200]},
                detail=(f"The answer promises {check.claim} and the text says "
                        f"{_number(value)} — a figure that does not satisfy "
                        "the question's own threshold.")))
            break
    return out


def _vocabulary(column: str, label: str) -> tuple[str, ...]:
    """The words a sentence uses for this measure.

    The column name broken into words, plus the concept's business label. Words
    shorter than four characters are dropped: "pct" and "ecl" would match
    almost anything, and a proximity test on a word that appears everywhere is
    no test at all.
    """
    words = set()
    for source in (column, label):
        for word in re.split(r"[^a-z0-9]+", str(source or "").lower()):
            if len(word) >= 4 and word not in ("value", "total", "amount"):
                words.add(word)
    return tuple(sorted(words))


#: What a column's name says its unit is, where the ontology did not.
_UNIT_SUFFIX = (("_pct", "%"), ("_percent", "%"), ("_pp", "pp"),
                ("_ratio", "x"), ("_times", "x"), ("_multiple", "x"))


def _unit_for(column: str, declared: str) -> str:
    unit = str(declared or "").strip()
    if unit in ("%", "pp", "x"):
        return unit
    lowered = str(column or "").lower()
    for suffix, found in _UNIT_SUFFIX:
        if lowered.endswith(suffix):
            return found
    return ""


def _violating(text: str, vocabulary: tuple[str, ...], satisfies: Any,
               bound: float, unit: str) -> tuple[float, str] | None:
    if not text or not vocabulary:
        return None
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        lowered = sentence.lower()
        anchors = [m.start() for word in vocabulary
                   for m in re.finditer(re.escape(word), lowered)]
        if not anchors:
            continue
        for match in _PROSE_NUMBER.finditer(sentence):
            if (match.group(2) or "") != unit:
                continue
            raw = match.group(1).replace(",", "")
            try:
                value = float(raw)
            except ValueError:
                continue
            # The threshold restated is not a violation of itself.
            if abs(value - bound) <= TOLERANCE:
                continue
            if any(abs(match.start() - anchor) <= PROSE_WINDOW
                   for anchor in anchors) and not satisfies(value, bound):
                return value, sentence.strip()
    return None


__all__ = ["PROSE_WINDOW", "Check", "Failure", "Report", "check_prose",
           "check_result", "compile_checks", "verify"]
