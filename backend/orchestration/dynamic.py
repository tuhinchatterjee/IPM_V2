"""
Dynamic analysis — questions with no prebuilt answer.

The library holds hundreds of methods and the engine holds dozens of certified
analyses, and between them they still do not cover "Real Estate customers whose
ECL rose more than 20%, whose rating fell at least two notches, and whose EAD
did not decline over the latest year." Nobody built that, and nobody will:
questions of that shape are combinatorial, and a product that can only answer
the ones somebody anticipated is a report pack with a chat box on it.

So CreditProbe composes. This module reads such a question into a small,
explicit request — grain, period span, governed filters, and a list of
conditions on how measures moved — and turns that into an Analytical IR plan
which then goes through the same validator, compiler and runtime as everything
else.

Three properties make that safe, and none of them is "we trust the reading":

  * the reading produces DATA (fields, comparisons, numbers), never a fragment
    of SQL or code. There is nowhere in a Condition to put a semicolon that
    means anything;
  * every field named is checked against the governed catalogue before a plan is
    built, and an unrecognised one is a refusal rather than a guess;
  * the result is labelled DYNAMIC ANALYSIS, not certified. It was composed for
    this question and has never been reviewed by anybody, and the interface says
    so wherever the figure appears.

What it will not do
-------------------
Guess. A question it cannot read completely produces a refusal naming the part
it could not read — because the failure mode this whole product exists to avoid
is a confident number answering a slightly different question.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.data_access.catalog import get_catalog

logger = logging.getLogger(__name__)

#: What a dynamic analysis may read. One dataset in this release — the facility
#: position — because a composed join across governed datasets needs the
#: relationship model that Data Builder is still growing.
DEFAULT_DATASET = "portfolio_facility"

MAX_CONDITIONS = 6
MAX_ROWS = 500


# ---------------------------------------------------------------- the reading


@dataclass(frozen=True)
class Condition:
    """One thing that must be true of how a measure moved.

    `kind` decides what is compared, and it is the part people get wrong in
    conversation: "ECL increased more than 20%" is a relative change, "rating
    deteriorated two notches" is an absolute one on an ordinal scale, and
    "EAD did not decline" is a floor on the absolute change. They are different
    comparisons and the answer differs by more than rounding.
    """

    field: str
    kind: str          # change_pct | change_abs | level
    op: str            # gt | gte | lt | lte
    value: float
    phrase: str = ""
    #: True where a HIGHER number is worse — a rating grade, days past due.
    higher_is_worse: bool = True

    @property
    def column(self) -> str:
        return {"change_pct": f"{self.field}_change_pct",
                "change_abs": f"{self.field}_change",
                "level": self.field}[self.kind]

    @property
    def label(self) -> str:
        """What a credit officer calls this measure."""
        return FIELD_LABELS.get(self.field, self.field.replace("_", " "))

    def describe(self) -> str:
        """The condition in the words somebody would check it in.

        Read back rather than echoed: the user's own phrasing is what has to be
        checked, and repeating it proves nothing about how it was understood.
        A zero threshold is a floor, not a movement, and is said as one.
        """
        unit = "%" if self.kind == "change_pct" else ""
        if self.kind == "level":
            word = {"gt": "above", "gte": "at or above",
                    "lt": "below", "lte": "at or below"}[self.op]
            return f"{self.label} {word} {self.value:g}{unit}"

        if self.value == 0:
            if self.op == "gt":
                return f"{self.label} rose"
            if self.op == "lt":
                return f"{self.label} fell"
            # A floor at zero: "did not fall" rather than "rose or stayed", which
            # is the same set and not how anybody says it.
            return f"{self.label} did not {'fall' if self.op == 'gte' else 'rise'}"

        magnitude = abs(self.value)
        rising = self.value > 0
        movement = "rose" if rising else "fell"
        if self.field == "internal_grade":
            movement = "worsened" if rising else "improved"
            unit = unit or " notches"
        strict = self.op in ("gt", "lt")
        qualifier = "more than" if strict else "at least"
        return f"{self.label} {movement} {qualifier} {magnitude:g}{unit}"

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "kind": self.kind, "op": self.op,
                "value": self.value, "phrase": self.phrase,
                "column": self.column, "description": self.describe()}


@dataclass
class DynamicRequest:
    """What CreditProbe made of a question it has no prebuilt answer for."""

    understood: bool = False
    dataset: str = DEFAULT_DATASET
    grain: str = "customer"
    key: str = "customer_id"
    opening: str = ""
    closing: str = ""
    filters: list[tuple[str, str]] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    summary: str = ""
    #: Why it could not be read, when it could not. Every reason, not the first.
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "understood": self.understood, "dataset": self.dataset,
            "grain": self.grain, "opening_period": self.opening,
            "closing_period": self.closing,
            "filters": [{"field": f, "value": v} for f, v in self.filters],
            "conditions": [c.to_dict() for c in self.conditions],
            "columns": list(self.columns), "summary": self.summary,
            "reasons": list(self.reasons),
        }


# ------------------------------------------------------------- measure lexicon

#: What a credit officer calls each governed field, for reading a condition
#: back. A condition described as "total_ecl" has been read correctly and
#: communicated badly, and the user cannot tell those apart.
FIELD_LABELS = {
    "total_ecl": "ECL", "ecl_coverage_pct": "ECL coverage", "ead": "EAD",
    "exposure": "drawn exposure", "undrawn": "undrawn", "limit_amount": "limit",
    "utilisation_pct": "utilisation", "pd_12m_pct": "12-month PD",
    "pd_lifetime_pct": "lifetime PD", "lgd_pct": "LGD",
    "internal_grade": "internal rating", "dpd_days": "days past due",
    "collateral_value": "collateral value",
    "covenant_headroom_pct": "covenant headroom", "dscr": "DSCR",
    "raroc_pct": "RAROC", "ifrs9_stage": "IFRS 9 stage",
}

#: What people call each governed field. Longest phrase wins, so "expected
#: credit loss" is not read as "credit". Every target is a real column on the
#: facility position — a phrase mapping to a field the catalogue does not have
#: is a refusal, not a silently dropped condition.
MEASURES: list[tuple[str, str, bool]] = [
    # phrase, governed field, higher_is_worse
    (r"expected credit loss|\becl\b|impairment", "total_ecl", True),
    (r"ecl coverage|coverage ratio|provision coverage", "ecl_coverage_pct", False),
    (r"exposure at default|\bead\b", "ead", True),
    (r"drawn exposure|\bexposure\b", "exposure", True),
    (r"undrawn", "undrawn", True),
    (r"limit", "limit_amount", True),
    (r"utilisation|utilization", "utilisation_pct", True),
    (r"lifetime pd|lifetime probability of default", "pd_lifetime_pct", True),
    (r"\bpd\b|probability of default", "pd_12m_pct", True),
    (r"\blgd\b|loss given default", "lgd_pct", True),
    (r"rating|grade|notch", "internal_grade", True),
    (r"days past due|\bdpd\b|arrears", "dpd_days", True),
    (r"collateral", "collateral_value", False),
    (r"covenant headroom|headroom", "covenant_headroom_pct", False),
    (r"\bdscr\b|debt service", "dscr", False),
    (r"\braroc\b|return on capital", "raroc_pct", False),
    (r"stage", "ifrs9_stage", True),
]

#: Words for movement, and which way they point. A word meaning "got worse"
#: resolves against the measure's own direction: a rating deteriorating is a
#: higher grade number, coverage deteriorating is a lower percentage.
_WORSE = (r"increas\w*|ris\w*|ros\w*|grew|grow\w*|climb\w*|jump\w*|up\b|higher|"
          r"deteriorat\w*|worsen\w*|weaken\w*|widen\w*|"
          r"fell|fall\w*|declin\w*|drop\w*|slip\w*|lower|reduc\w*|decreas\w*|"
          r"improv\w*|strengthen\w*|narrow\w*|tighten\w*")

_UP_WORDS = {"increas", "ris", "ros", "grew", "grow", "climb", "jump", "up",
             "higher", "widen"}
_DOWN_WORDS = {"fell", "fall", "declin", "drop", "slip", "lower", "reduc",
               "decreas", "narrow"}
_WORSE_WORDS = {"deteriorat", "worsen", "weaken"}
_BETTER_WORDS = {"improv", "strengthen", "tighten"}

#: "more than 20%", "at least two notches", "by over 5"
_MAGNITUDE = (
    r"(?:by\s+)?(?P<qualifier>more than|at least|over|greater than|less than|"
    r"no more than|at most|under)?\s*"
    r"(?P<number>\d+(?:\.\d+)?|one|two|three|four|five)\s*"
    r"(?P<unit>%|per ?cent|percent|notch(?:es)?|bps|basis points)?"
)

_WORDS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}

_CLAUSE = re.compile(
    r"(?P<measure>[a-z0-9 %\-]{2,40}?)\s+"
    r"(?P<negation>did not |didn't |has not |have not |hasn't |haven't )?"
    r"(?P<direction>" + _WORSE + r")"
    r"(?P<rest>.*)",
    re.IGNORECASE,
)

#: Where one condition ends and the next begins. Questions of this shape are
#: written as lists — "A rose more than 20%, B fell two notches, and C did not
#: decline" — so the conditions are read one clause at a time. Matching the
#: whole sentence instead lets a greedy tail swallow the clause after it, which
#: silently answers a narrower question.
_SEPARATOR = re.compile(r"\s*(?:,|;|\band\b|\bwhile\b|\bwhose\b(?=[^,;]*\b(?:"
                        + _WORSE + r")))\s*", re.IGNORECASE)


def _measure_for(text: str) -> tuple[str, bool] | None:
    """The governed field a phrase names, or None. Longest match wins."""
    best: tuple[int, str, bool] | None = None
    for pattern, target, higher_is_worse in MEASURES:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and (best is None or len(match.group(0)) > best[0]):
            best = (len(match.group(0)), target, higher_is_worse)
    return (best[1], best[2]) if best else None


def _direction(word: str, higher_is_worse: bool) -> str:
    """"up" or "down", resolving deteriorate/improve against the measure.

    Matched on the stem the word STARTS with rather than by stripping suffixes:
    "increased", "increases" and "increasing" all begin with "increas", and
    stripping instead of prefixing turns "decline" into something that matches
    nothing.
    """
    lowered = word.lower()
    for prefix in _UP_WORDS:
        if lowered.startswith(prefix):
            return "up"
    for prefix in _DOWN_WORDS:
        if lowered.startswith(prefix):
            return "down"
    for prefix in _WORSE_WORDS:
        if lowered.startswith(prefix):
            return "up" if higher_is_worse else "down"
    for prefix in _BETTER_WORDS:
        if lowered.startswith(prefix):
            return "down" if higher_is_worse else "up"
    return ""


def read_conditions(question: str, *, resolver: Any = None
                    ) -> tuple[list[Condition], list[str]]:
    """Every movement condition in the question, and anything unreadable.

    Reads clause by clause rather than matching whole sentence templates: a
    question carries three or four of these joined by commas and "and", and a
    template that has to anticipate the combination stops working at the fourth.

    `resolver` replaces the flat measure lexicon below with something that knows
    about governed concepts across several datasets. Passing one is how the
    multi-dataset planner reuses the clause reading — the direction words, the
    magnitudes, the negations — without a second copy of it drifting out of
    step with this one. It takes (phrase, question) and returns
    (field, higher_is_worse) or None.
    """
    conditions: list[Condition] = []
    unread: list[str] = []
    seen: set[tuple[str, str]] = set()

    for clause in _SEPARATOR.split(question):
        if not clause or not clause.strip():
            continue
        match = _CLAUSE.search(clause)
        if match is None:
            continue
        phrase = match.group(0).strip()
        measure = (resolver(match.group("measure"), question) if resolver
                   else _measure_for(match.group("measure")))
        if measure is None:
            continue
        target, higher_is_worse = measure

        direction = _direction(match.group("direction"), higher_is_worse)
        if not direction:
            unread.append(phrase)
            continue

        negated = bool(match.group("negation"))
        rest = match.group("rest") or ""
        magnitude = re.search(_MAGNITUDE, rest, re.IGNORECASE)

        # "did not decline" is a floor at zero: no magnitude, and the comparison
        # is the opposite of the direction named.
        if negated and not (magnitude and magnitude.group("number")):
            op = "gte" if direction == "down" else "lte"
            kind = "change_abs"
            value = 0.0
        elif magnitude and magnitude.group("number"):
            raw = magnitude.group("number").lower()
            value = _WORDS.get(raw, None)
            if value is None:
                value = float(raw)
            unit = (magnitude.group("unit") or "").lower()
            qualifier = (magnitude.group("qualifier") or "").lower()

            if unit in ("%", "per cent", "percent"):
                kind = "change_pct"
            elif unit in ("bps", "basis points"):
                kind, value = "change_abs", value / 100.0
            else:
                kind = "change_abs"

            strict = qualifier in ("more than", "over", "greater than", "less than",
                                   "under")
            if direction == "down":
                # A fall of more than 20% is a change below -20.
                value = -value
                op = "lt" if strict else "lte"
            else:
                op = "gt" if strict else "gte"
        else:
            # A direction with no magnitude — "ECL increased" — is a movement of
            # any size in that direction.
            kind = "change_abs"
            value = 0.0
            op = "gt" if direction == "up" else "lt"

        key = (target, kind)
        if key in seen:
            continue
        seen.add(key)
        conditions.append(Condition(field=target, kind=kind, op=op, value=value,
                                    phrase=phrase, higher_is_worse=higher_is_worse))

    return conditions, unread


# ------------------------------------------------------------- reading it all


_HORIZONS = [
    (r"latest year|last year|past year|year on year|over a year|twelve months|12 months", 4),
    (r"latest quarter|last quarter|previous quarter|quarter on quarter", 1),
    (r"six months|two quarters|half year", 2),
    (r"two years|24 months", 8),
]


def read_question(question: str, *, periods: list[str],
                  dimensions: dict[str, list[str]] | None = None,
                  dataset: str = DEFAULT_DATASET) -> DynamicRequest:
    """Read a cohort question into an explicit request, or refuse.

    Deterministic. The reading decides what will be computed, and a reading that
    varies between two identical questions makes every answer unreproducible —
    which is the opposite of what this product sells.
    """
    request = DynamicRequest(dataset=dataset)
    text = " ".join(str(question).split())
    lowered = text.lower()

    if not periods:
        request.reasons.append("No reporting periods are published.")
        return request

    horizon = 0
    for pattern, quarters in _HORIZONS:
        if re.search(pattern, lowered):
            horizon = quarters
            break
    if not horizon:
        request.reasons.append(
            "The question does not say over what period the change should be "
            "measured. Say 'over the latest year' or name two quarters.")
    else:
        index = len(periods) - 1 - horizon
        if index < 0:
            request.reasons.append(
                f"That span needs {horizon + 1} periods and only {len(periods)} "
                "are published.")
        else:
            request.opening = periods[index]
            request.closing = periods[-1]

    if re.search(r"\bcustomers?\b|\bobligors?\b|\bborrowers?\b|\bnames?\b", lowered):
        request.grain, request.key = "customer", "customer_id"
    elif re.search(r"\bfacilit|\baccounts?\b|\bloans?\b|\bexposures?\b", lowered):
        request.grain, request.key = "facility", "account_id"

    for dimension, values in (dimensions or {}).items():
        for value in sorted(values, key=len, reverse=True):
            if len(str(value)) >= 4 and str(value).lower() in lowered:
                request.filters.append((dimension, str(value)))
                break

    conditions, unread = read_conditions(text)
    if unread:
        request.reasons.append(
            "CreditProbe could not read: " + "; ".join(f"'{u}'" for u in unread))
    if not conditions:
        request.reasons.append(
            "The question names no measurable condition. A dynamic analysis "
            "needs at least one — how a measure moved, and by how much.")
    if len(conditions) > MAX_CONDITIONS:
        request.reasons.append(
            f"{len(conditions)} conditions is more than this release composes "
            f"in one analysis ({MAX_CONDITIONS}).")

    # Every field must exist in the governed catalogue. A phrase that maps to a
    # field this dataset does not carry is a refusal naming the field, never a
    # dropped condition — dropping one answers a narrower question silently.
    try:
        governed = set(get_catalog().dataset(dataset).fields)
    except Exception as e:
        request.reasons.append(f"The dataset '{dataset}' is not available: {e}")
        governed = set()

    for condition in conditions:
        if condition.field not in governed:
            request.reasons.append(
                f"'{condition.field}' is not a field of {dataset}, so "
                f"'{condition.phrase}' cannot be computed.")
    if request.key not in governed:
        request.reasons.append(f"'{request.key}' is not a field of {dataset}.")
    for dimension, _ in request.filters:
        if dimension not in governed:
            request.reasons.append(f"'{dimension}' is not a field of {dataset}.")

    request.conditions = conditions
    request.understood = not request.reasons
    if request.understood:
        request.summary = _summary(request)
    return request


def _plural(grain: str) -> str:
    """"facilities", not "facilitys". A small thing that reads as carelessness."""
    return {"facility": "facilities", "customer": "customers"}.get(grain, f"{grain}s")


def _summary(request: DynamicRequest) -> str:
    """The reading, in the words a person would check it in."""
    where = ", ".join(f"{value}" for _, value in request.filters)
    plural = _plural(request.grain)
    subject = f"{where} {plural}" if where else plural
    clauses = list(dict.fromkeys(c.describe() for c in request.conditions))
    joined = (clauses[0] if len(clauses) == 1
              else ", ".join(clauses[:-1]) + f", and {clauses[-1]}")
    return (f"All {subject.strip()} whose {joined}, measured between "
            f"{request.opening} and {request.closing}.")


# --------------------------------------------------------------- building the IR


def build_plan(request: DynamicRequest) -> dict[str, Any]:
    """The Analytical IR for a read request.

    Written out as an explicit plan rather than generated: the shape of a
    cohort question — read both dates, join on the identifier, derive the
    movements, filter on them — is a known thing, and a known thing belongs in
    code where it can be reviewed and tested. What varies with the question is
    which fields and which thresholds, and those are data.
    """
    if not request.understood:
        raise ValueError("; ".join(request.reasons) or "The question was not read.")

    measures = sorted({c.field for c in request.conditions})
    dimensions = sorted({f for f, _ in request.filters})
    label = {"customer": "customer_id", "facility": "account_id"}[request.grain]

    opening_fields = sorted({request.key, label, *measures, *dimensions,
                             "borrower_name", "sector", "ead"}
                            & set(get_catalog().dataset(request.dataset).fields))
    closing_fields = sorted({request.key, *measures}
                            & set(get_catalog().dataset(request.dataset).fields))

    operations: list[dict[str, Any]] = [
        {"id": "opening", "op": "SCAN",
         "params": {"dataset": request.dataset, "period": request.opening,
                    "fields": opening_fields},
         "label": f"Read {request.dataset} at {request.opening}"},
        {"id": "closing", "op": "SCAN",
         "params": {"dataset": request.dataset, "period": request.closing,
                    "fields": closing_fields},
         "label": f"Read {request.dataset} at {request.closing}"},
    ]

    # A customer holds several facilities, so both sides are rolled up to the
    # grain being asked about BEFORE the join. Joining first would multiply a
    # customer's rows by its facility count and count one movement many times.
    for side, source, fields in (("opening_grain", "opening", measures),
                                 ("closing_grain", "closing", measures)):
        operations.append({
            "id": side, "op": "GROUP", "inputs": [source],
            "params": {
                "by": [request.key],
                "aggregates": [_rollup(f) for f in fields],
            },
            "label": f"Roll up to one row per {request.grain}",
        })

    if request.filters:
        operations.append({
            "id": "attributes", "op": "GROUP", "inputs": ["opening"],
            "params": {
                "by": [request.key, *dimensions],
                "aggregates": [{"function": "sum", "column": "ead", "as": "opening_ead"}],
            },
            "label": "Carry the governed attributes at the opening date",
        })
        operations.append({
            "id": "segment", "op": "FILTER", "inputs": ["attributes"],
            "params": {"where": [{"column": f, "op": "=", "value": v}
                                 for f, v in request.filters]},
            "label": "Apply the governed filter",
        })
        base = "segment"
        operations.append({
            "id": "opening_scoped", "op": "JOIN", "inputs": [base, "opening_grain"],
            "params": {"kind": "inner", "on": [request.key], "right_prefix": ""},
            "label": "Keep only the segment asked about",
        })
        left = "opening_scoped"
    else:
        left = "opening_grain"

    operations.append({
        "id": "movement", "op": "JOIN", "inputs": [left, "closing_grain"],
        "params": {"kind": "inner", "on": [request.key], "right_prefix": "closing_"},
        "label": f"Match each {request.grain} to its position at {request.closing}",
    })

    derived: list[dict[str, Any]] = []
    for measure in measures:
        change = {"type": "function", "function": "subtract",
                  "args": [f"closing_{measure}", measure]}
        derived.append({"as": f"{measure}_change", "expression": change})
        derived.append({
            "as": f"{measure}_change_pct",
            # Guarded: a customer whose opening ECL was zero has no percentage
            # change, and returning infinity there would put it top of the list.
            "expression": {
                "type": "case",
                "whens": [[{"type": "function", "function": "gt",
                            "args": [measure, {"type": "literal", "value": 0}]},
                           {"type": "function", "function": "multiply",
                            "args": [{"type": "function", "function": "divide",
                                      "args": [change, measure]},
                                     {"type": "literal", "value": 100}]}]],
                "otherwise": {"type": "literal", "value": None},
            },
        })
    operations.append({
        "id": "movements", "op": "DERIVE", "inputs": ["movement"],
        "params": {"columns": derived},
        "label": "Derive the movement in each measure",
    })

    operations.append({
        "id": "cohort", "op": "FILTER", "inputs": ["movements"],
        "params": {"where": [{"column": c.column, "op": _OPS[c.op], "value": c.value}
                             for c in request.conditions]},
        "label": "Keep only those meeting every condition",
    })

    sort_by = request.conditions[0].column
    operations.append({
        "id": "ranked", "op": "SORT", "inputs": ["cohort"],
        "params": {"by": [{"column": sort_by,
                           "direction": "desc" if request.conditions[0].op in
                                        ("gt", "gte") else "asc"}]},
        "label": "Largest movement first",
    })
    operations.append({
        "id": "result", "op": "LIMIT", "inputs": ["ranked"],
        "params": {"n": MAX_ROWS},
        "label": f"The first {MAX_ROWS} rows",
    })

    return {
        "id": "dynamic_cohort",
        "operations": operations,
        "meta": {"kind": "dynamic_cohort", "grain": request.grain,
                 "opening_period": request.opening,
                 "closing_period": request.closing,
                 "conditions": [c.to_dict() for c in request.conditions],
                 "filters": [{"field": f, "value": v} for f, v in request.filters]},
    }


_OPS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}

#: How each measure rolls up from facility to customer. A sum for money, the
#: worst value for an ordinal or a rate — averaging a rating across four
#: facilities produces a grade nobody assigned.
_WORST_MAX = {"internal_grade", "dpd_days", "ifrs9_stage", "pd_12m_pct",
              "pd_lifetime_pct", "lgd_pct", "utilisation_pct"}
_WORST_MIN = {"ecl_coverage_pct", "covenant_headroom_pct", "dscr", "raroc_pct"}


def _rollup(measure: str) -> dict[str, Any]:
    if measure in _WORST_MAX:
        return {"function": "max", "column": measure, "as": measure}
    if measure in _WORST_MIN:
        return {"function": "min", "column": measure, "as": measure}
    return {"function": "sum", "column": measure, "as": measure}


__all__ = [
    "DEFAULT_DATASET",
    "Condition",
    "DynamicRequest",
    "build_plan",
    "read_conditions",
    "read_question",
]
