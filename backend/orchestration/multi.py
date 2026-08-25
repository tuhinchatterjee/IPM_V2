"""
Multi-dataset dynamic analysis: questions that need more than one governed
source.

The question this exists for
----------------------------
"Show Real Estate customers whose ECL increased more than 20%, rating
deteriorated at least two notches, and EAD did not decline over the latest
year."

That needs three datasets — the impairment run for ECL, the annual rating cycle
for the grade, the facility position for exposure and sector — reported at two
different frequencies, joined at customer level, compared across two periods.
Nothing in the question names a dataset, a join key, a cardinality or a period
alignment, and nothing should.

What this module does with it
-----------------------------
    concepts        "ECL" → ifrs9_staging.total_ecl, and the answer says so
    datasets        every concept's dataset, plus the base the question is about
    join path       resolved from the GOVERNED relationship graph, never
                    invented here
    grain           read from the question ("customers" → customer level), and
                    every many-side rolled up to it BEFORE the join
    periods         opening and closing, with an annual source read as-of the
                    analysis date and never later
    IR              built explicitly, then validated, compiled and executed by
                    the same runtime as everything else

Two properties are worth stating plainly, because they are the ones that make a
composed join safe rather than merely convenient:

**No join key is invented.** Every join in the emitted plan comes from an ACTIVE
relationship row, and the plan records which one, at which version. A dataset
pair with no governed relationship is a refusal, not a guess at a common column
name.

**No join can multiply the book.** A path crossing a one-to-many or
many-to-many edge gets an explicit AGGREGATE_BEFORE_JOIN on the many side,
rolled up to the analysis grain, before the join happens. An ordinal measure
rolls up by its worst value and never by its average, because an average rating
across four facilities is a grade nobody assigned.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import concepts as cx
from backend.orchestration.dynamic import Condition, read_conditions
from backend.runtime.joins import (
    Edge,
    JoinGraph,
    Resolution,
    build_graph,
    resolve,
)

logger = logging.getLogger(__name__)

#: The dataset an analysis starts from. The facility position is the hub of the
#: governed model — almost everything joins to it — so it is where a path
#: search begins unless the question is plainly about something else.
DEFAULT_BASE = "portfolio_facility"

MAX_ROWS = 500

#: A question naming this many concepts across this many datasets is composed.
#: Below it, the single-dataset path or the certified library answers better.
MIN_DATASETS_FOR_MULTI = 2

# ---- grain ------------------------------------------------------------------

CUSTOMER = "customer"
FACILITY = "facility"
SECTOR = "sector"

GRAIN_KEY = {CUSTOMER: "customer_id", FACILITY: "account_id", SECTOR: "sector"}

#: What a row of each governed dataset is about, so the planner knows whether a
#: side has to be rolled up before it is joined. Read from the catalogue's grain
#: sentence where it can be, and stated here where the sentence is prose.
DATASET_GRAIN = {
    "portfolio_facility": FACILITY,
    "ifrs9_staging": FACILITY,
    "facility_delinquency": FACILITY,
    "facility_limits": FACILITY,
    "facility_profitability": FACILITY,
    "payment_history": FACILITY,
    "recoveries": FACILITY,
    "collateral_register": FACILITY,
    "covenant_tests": FACILITY,
    "customer_ratings": CUSTOMER,
    "borrower_financials": CUSTOMER,
    "watchlist_register": CUSTOMER,
    "climate_risk": CUSTOMER,
    "group_structure": CUSTOMER,
    "rating_transitions": CUSTOMER,
    "credit_memo_signals": CUSTOMER,
    "macro_saudi": "period",
    "risk_appetite_limits": SECTOR,
    "pd_model_performance": "segment",
    "scenario_definitions": "period",
}

#: Dimensions carried through to the output so a result is readable. Taken with
#: `any_value` because they do not vary within a group; a sum of sectors is
#: nonsense and an average of them is worse.
CARRIED_DIMENSIONS = ["borrower_name", "sector", "region", "segment"]

_HORIZONS = [
    (r"latest year|last year|past year|year on year|over a year|twelve months|12 months", 4),
    (r"latest quarter|last quarter|previous quarter|quarter on quarter", 1),
    (r"six months|two quarters|half year", 2),
    (r"two years|24 months", 8),
]

_OPS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


# ---------------------------------------------------------------- the reading


@dataclass
class Binding:
    """One condition, and the governed field behind it."""

    condition: Condition
    match: cx.ConceptMatch

    @property
    def dataset(self) -> str:
        return self.match.dataset

    @property
    def field(self) -> str:
        return self.match.field

    def to_dict(self) -> dict[str, Any]:
        return {"condition": self.condition.to_dict(),
                "concept": self.match.to_dict()}


@dataclass
class MultiRequest:
    """What CreditProbe made of a question needing several datasets."""

    question: str = ""
    understood: bool = False
    base: str = DEFAULT_BASE
    grain: str = CUSTOMER
    key: str = "customer_id"
    opening: str = ""
    closing: str = ""
    reading: cx.Reading = field(default_factory=cx.Reading)
    bindings: list[Binding] = field(default_factory=list)
    filters: list[tuple[str, str]] = field(default_factory=list)
    resolution: Resolution | None = None
    summary: str = ""
    reasons: list[str] = field(default_factory=list)
    #: Concepts where more than one governed field could have been meant.
    clarifications: list[cx.ConceptMatch] = field(default_factory=list)
    #: How sure the reading is, per stage. Low anywhere means ask.
    confidence: dict[str, float] = field(default_factory=dict)

    @property
    def datasets(self) -> list[str]:
        out = [self.base]
        for binding in self.bindings:
            if binding.dataset not in out:
                out.append(binding.dataset)
        return out

    @property
    def is_multi(self) -> bool:
        return len(self.datasets) >= MIN_DATASETS_FOR_MULTI

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "understood": self.understood,
            "base": self.base,
            "grain": self.grain,
            "key": self.key,
            "opening_period": self.opening,
            "closing_period": self.closing,
            "datasets": self.datasets,
            "concepts": self.reading.to_dict(),
            "bindings": [b.to_dict() for b in self.bindings],
            "filters": [{"field": f, "value": v} for f, v in self.filters],
            "join_plan": self.resolution.to_dict() if self.resolution else None,
            "summary": self.summary,
            "reasons": list(self.reasons),
            "clarifications": [c.to_dict() for c in self.clarifications],
            "confidence": dict(self.confidence),
        }


def _grain_of(question: str) -> str:
    lowered = question.lower()
    if re.search(r"\bsectors?\b|\bindustr", lowered):
        return SECTOR
    if re.search(r"\bcustomers?\b|\bobligors?\b|\bborrowers?\b|\bnames?\b|\bclients?\b",
                 lowered):
        return CUSTOMER
    if re.search(r"\bfacilit|\baccounts?\b|\bloans?\b", lowered):
        return FACILITY
    return CUSTOMER


def _periods(question: str, available: list[str]) -> tuple[str, str, str]:
    """Opening and closing period, or the reason there is none."""
    lowered = question.lower()
    if not available:
        return "", "", "No reporting periods are published."
    horizon = 0
    for pattern, quarters in _HORIZONS:
        if re.search(pattern, lowered):
            horizon = quarters
            break
    if not horizon:
        return "", "", (
            "The question does not say over what period the change should be "
            "measured. Say 'over the latest year' or name two quarters.")
    index = len(available) - 1 - horizon
    if index < 0:
        return "", "", (
            f"That span needs {horizon + 1} periods and only {len(available)} "
            "are published.")
    return available[index], available[-1], ""


def read_question(question: str, *, catalogue: Any, periods: list[str],
                  dimensions: dict[str, list[str]] | None = None,
                  relationships: list[dict[str, Any]] | None = None,
                  base: str = DEFAULT_BASE) -> MultiRequest:
    """Read a question into an explicit multi-dataset request, or refuse.

    Deterministic throughout. The reading decides which datasets are joined and
    therefore what is computed; a reading that varies between two identical
    questions makes every answer unreproducible.
    """
    request = MultiRequest(question=" ".join(str(question).split()), base=base)
    known = cx.catalogue_fields(catalogue)

    # ---- 1. concepts
    request.reading = cx.read_concepts(request.question, known=known,
                                       catalogue=catalogue)
    request.reasons.extend(request.reading.unresolved)
    request.clarifications = list(request.reading.needs_clarification)
    request.confidence["fields"] = (
        min((m.confidence for m in request.reading.matches), default=0.0))

    # ---- 2. grain and periods
    request.grain = _grain_of(request.question)
    request.key = GRAIN_KEY[request.grain]
    request.opening, request.closing, why = _periods(request.question, periods)
    if why:
        request.reasons.append(why)
    request.confidence["grain"] = 1.0 if request.grain else 0.5

    # ---- 3. governed dimension filters
    for dimension, values in (dimensions or {}).items():
        for value in sorted(values, key=len, reverse=True):
            if len(str(value)) >= 4 and str(value).lower() in request.question.lower():
                request.filters.append((dimension, str(value)))
                break

    # ---- 4. conditions, bound to the concepts
    by_phrase: dict[str, cx.ConceptMatch] = {}

    def resolver(phrase: str, whole: str) -> tuple[str, bool] | None:
        """Map a measure phrase onto a governed concept.

        Reuses the clause reading in `dynamic` — the direction words, the
        magnitudes, the negations — and replaces only the lexicon, so there is
        one implementation of "increased more than 20%" rather than two that
        drift.
        """
        local = cx.read_concepts(phrase, known=known, catalogue=catalogue)
        if not local.matches:
            return None
        match = local.matches[0]
        # Re-resolve against the WHOLE question so a qualifier anywhere in it
        # ("regulatory EAD") still selects the right candidate.
        settled = cx.resolve_concept(match.concept, whole, known=known,
                                     catalogue=catalogue, phrase=match.phrase)
        chosen = settled or match
        by_phrase[chosen.field] = chosen
        return chosen.field, chosen.concept.higher_is_worse

    conditions, unread = read_conditions(request.question, resolver=resolver)
    if unread:
        request.reasons.append(
            "CreditProbe could not read: " + "; ".join(f"'{u}'" for u in unread))
    if not conditions:
        request.reasons.append(
            "The question names no measurable condition. Say how a measure "
            "moved, and by how much.")

    for condition in conditions:
        match = by_phrase.get(condition.field)
        if match is None:
            request.reasons.append(
                f"'{condition.field}' could not be traced back to a governed "
                "concept.")
            continue
        request.bindings.append(Binding(condition=condition, match=match))

    # ---- 5. the join path, from the governed relationship graph
    graph = build_graph(relationships or [])
    targets = [d for d in request.datasets if d != request.base]
    request.resolution = resolve(graph, base=request.base, targets=targets)
    request.confidence["join_path"] = (
        min((p.score for p in request.resolution.paths), default=1.0))
    for why in request.resolution.unreachable.values():
        request.reasons.append(why)

    # ---- 6. is the reading good enough to run?
    request.understood = not request.reasons and not request.clarifications
    if request.understood:
        request.summary = _summary(request)
    return request


def _plural(grain: str) -> str:
    return {FACILITY: "facilities", CUSTOMER: "customers",
            SECTOR: "sectors"}.get(grain, f"{grain}s")


def _summary(request: MultiRequest) -> str:
    where = ", ".join(value for _, value in request.filters)
    subject = f"{where} {_plural(request.grain)}" if where else _plural(request.grain)
    clauses = list(dict.fromkeys(b.condition.describe() for b in request.bindings))
    joined = (clauses[0] if len(clauses) == 1
              else ", ".join(clauses[:-1]) + f", and {clauses[-1]}")
    return (f"All {subject} whose {joined}, measured between "
            f"{request.opening} and {request.closing}.")


def explain(request: MultiRequest) -> str:
    """The plan in plain language — an auditable summary, not reasoning.

    Says which governed sources were used and why, what grain the answer is at,
    and how the periods were aligned. Everything in it is a fact about the plan;
    none of it is the model's account of how it decided.
    """
    if not request.resolution:
        return ""
    lines = [
        f"To answer this question, CreditProbe read "
        f"{len(request.datasets)} governed source"
        f"{'' if len(request.datasets) == 1 else 's'}:"
    ]
    seen: set[str] = set()
    for binding in request.bindings:
        if binding.dataset in seen:
            continue
        seen.add(binding.dataset)
        lines.append(f"  · {binding.dataset} for {binding.match.concept.label}")
    if request.base not in seen:
        lines.append(f"  · {request.base} for the population, exposure and sector")

    for path in request.resolution.paths:
        lines.append(
            f"  · joined via {path.describe()}"
            + (" (as-of: the latest observation on or before the analysis "
               "period)" if path.needs_asof else ""))

    lines.append(
        f"The analysis compares {request.opening} with {request.closing} and "
        f"reports at {request.grain} level.")
    if any(p.multiplies for p in request.resolution.paths):
        lines.append(
            "Sources with more than one row per "
            f"{request.grain} were aggregated to {request.grain} level before "
            "being joined, so nothing is double-counted.")
    return "\n".join(lines)


# --------------------------------------------------------------- building the IR


#: How a measure rolls up when a side has to be aggregated to the analysis
#: grain. An ordinal takes its worst value; money sums; a rate takes its worst.
def _rollup(match: cx.ConceptMatch) -> str:
    if match.concept.is_ordinal:
        return "max" if match.concept.higher_is_worse else "min"
    if match.concept.unit in ("USD mn", ""):
        return "sum" if match.concept.unit == "USD mn" else "max"
    return "max" if match.concept.higher_is_worse else "min"


@dataclass
class PlanBuild:
    """The emitted plan and everything the Trace needs to explain it."""

    plan: dict[str, Any]
    request: MultiRequest
    #: One entry per join, for the lineage panel.
    joins: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_plan(request: MultiRequest, *, catalogue: Any) -> PlanBuild:
    """The Analytical IR for a multi-dataset cohort question.

    Written as an explicit builder rather than generated by a model: the shape
    of a cohort question — read both dates, roll each side up to the grain,
    join on governed keys, derive the movements, filter — is a known thing, and
    a known thing belongs in code where it can be reviewed and tested. What
    varies with the question is which concepts, which datasets and which
    thresholds, and those are data.
    """
    if not request.understood:
        raise ValueError("; ".join(request.reasons) or "The question was not read.")
    assert request.resolution is not None

    operations: list[dict[str, Any]] = []
    joins: list[dict[str, Any]] = []
    warnings: list[str] = []
    key = request.key

    fields_of = {d.name: set(d.fields) for d in catalogue.all()}
    by_dataset: dict[str, list[cx.ConceptMatch]] = {}
    for binding in request.bindings:
        by_dataset.setdefault(binding.dataset, []).append(binding.match)

    dimensions = [c for c in CARRIED_DIMENSIONS
                  if c in fields_of.get(request.base, set())]
    filter_fields = [f for f, _ in request.filters]

    base_grain = DATASET_GRAIN.get(request.base, FACILITY)

    # Which sources can be joined BEFORE the roll-up and which after. This is
    # the grain reconciliation, and getting the order wrong is not a
    # performance detail: a facility-grained source has to be joined while the
    # frame still carries account_id, and a customer-grained one has to wait
    # until the frame is one row per customer or the join multiplies it back
    # out again.
    pre_grain, post_grain = [], []
    for path in request.resolution.paths:
        target_grain = DATASET_GRAIN.get(path.target, base_grain)
        (pre_grain if target_grain == base_grain else post_grain).append(path)

    #: Where each concept's value ends up living once the joins have run.
    #: Keyed by (dataset, field) because the same field name means different
    #: things in two datasets, which is the whole reason for prefixing.
    column_for: dict[tuple[str, str], str] = {
        (request.base, m.field): m.field for m in by_dataset.get(request.base, [])
    }

    def side(label: str, period: str) -> str:
        """Build one period's frame: the base, joined to every other source.

        In three movements, in this order:

          1. read the base and join everything reported at the base's own grain
             — while the frame still carries the key those sources join on;
          2. reconcile to the grain the ANSWER is at, rolling every measure up
             by the aggregation its concept calls for;
          3. join everything reported at a coarser grain — a customer's rating,
             the quarter's macro reading — now that the frame is one row per
             analysis key and the join cannot fan it back out.
        """
        gathered: list[tuple[str, cx.ConceptMatch]] = [
            (m.field, m) for m in by_dataset.get(request.base, [])]
        base_fields = sorted(
            {key, "period", *dimensions, *filter_fields,
             *[m.field for m in by_dataset.get(request.base, [])],
             *[e.left_field for pth in pre_grain + post_grain for e in pth.edges]}
            & fields_of.get(request.base, set()))
        scan_id = f"{label}_base"
        operations.append({
            "id": scan_id, "op": "SCAN",
            "params": {"dataset": request.base, "period": period,
                       "fields": base_fields, "alias": f"{request.base}@{period}"},
            "label": f"Read {request.base} at {period}",
        })

        current = scan_id
        for path in pre_grain:
            for edge in path.edges:
                current, mapped = _join_edge(
                    operations, joins, warnings, current, edge, label=label,
                    period=period, request=request, catalogue=catalogue,
                    fields_of=fields_of, by_dataset=by_dataset)
                for (dataset, source_field), column in mapped.items():
                    column_for[(dataset, source_field)] = column
                    match = next(m for m in by_dataset[dataset]
                                 if m.field == source_field)
                    gathered.append((column, match))

        if base_grain != request.grain or pre_grain:
            rolled = f"{label}_grain"
            operations.append({
                "id": rolled, "op": "RECONCILE_GRAIN", "inputs": [current],
                "params": {
                    "by": [key],
                    "aggregates": [
                        *[{"function": _rollup(m), "column": column, "as": column}
                          for column, m in gathered],
                        *[{"function": "any_value", "column": c, "as": c}
                          for c in dict.fromkeys([*dimensions, *filter_fields,
                                                  "period"])
                          if c != key and c in base_fields],
                    ],
                },
                "label": (f"Reconcile to one row per {request.grain} — the "
                          "grain the answer is reported at"),
            })
            current = rolled

        for path in post_grain:
            for edge in path.edges:
                current, mapped = _join_edge(
                    operations, joins, warnings, current, edge, label=label,
                    period=period, request=request, catalogue=catalogue,
                    fields_of=fields_of, by_dataset=by_dataset)
                column_for.update(mapped)
        return current

    opening = side("opening", request.opening)
    closing = side("closing", request.closing)

    operations.append({
        "id": "movement", "op": "JOIN", "inputs": [opening, closing],
        "params": {"kind": "inner", "on": [key], "right_prefix": "closing_"},
        "label": (f"Match each {request.grain} at {request.opening} to itself "
                  f"at {request.closing}"),
    })

    # The governed relationships this plan used, recorded as a step so the path
    # appears on the Trace rather than in a footnote.
    operations.append({
        "id": "path", "op": "RELATIONSHIP_PATH", "inputs": ["movement"],
        "params": {"path": [
            {"relationship_id": e.relationship_id,
             "relationship_name": e.name,
             "relationship_version": e.version,
             "from": e.left, "to": e.right,
             "keys": [e.left_field, e.right_field],
             "cardinality": e.cardinality,
             "temporal_rule": e.temporal_rule}
            for e in request.resolution.edges()]},
        "label": f"{len(request.resolution.edges())} governed relationships used",
    })

    measures = list(dict.fromkeys(
        column_for[(b.dataset, b.field)] for b in request.bindings))

    derived: list[dict[str, Any]] = []
    for measure in measures:
        change = {"type": "function", "function": "subtract",
                  "args": [f"closing_{measure}", measure]}
        derived.append({"as": f"{measure}_change", "expression": change})
        derived.append({
            "as": f"{measure}_change_pct",
            # Guarded: a customer whose opening ECL was zero has no percentage
            # change, and returning infinity would put it top of the list.
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
        "id": "movements", "op": "DERIVE", "inputs": ["path"],
        "params": {"columns": derived},
        "label": "Derive the movement in each measure",
    })

    where = [{"column": _condition_column(b, column_for),
              "op": _OPS[b.condition.op], "value": b.condition.value}
             for b in request.bindings]
    for dimension, value in request.filters:
        where.append({"column": dimension, "op": "=", "value": value})
    operations.append({
        "id": "cohort", "op": "FILTER", "inputs": ["movements"],
        "params": {"where": where},
        "label": "Keep only those meeting every condition",
    })

    first = request.bindings[0]
    operations.append({
        "id": "ranked", "op": "SORT", "inputs": ["cohort"],
        "params": {"by": [{"column": _condition_column(first, column_for),
                           "direction": ("desc" if first.condition.op in ("gt", "gte")
                                         else "asc")}]},
        "label": "Largest movement first",
    })
    operations.append({
        "id": "result", "op": "LIMIT", "inputs": ["ranked"],
        "params": {"n": MAX_ROWS},
        "label": f"The first {MAX_ROWS} rows",
    })

    plan = {
        "id": "dynamic_multi_dataset",
        "operations": operations,
        "meta": {
            "kind": "multi_dataset_cohort",
            "grain": request.grain,
            "opening_period": request.opening,
            "closing_period": request.closing,
            "datasets": request.datasets,
            "conditions": [b.condition.to_dict() for b in request.bindings],
            "concepts": [b.match.to_dict() for b in request.bindings],
            "filters": [{"field": f, "value": v} for f, v in request.filters],
            "join_path": request.resolution.to_dict(),
            "explanation": explain(request),
        },
    }
    return PlanBuild(plan=plan, request=request, joins=joins,
                     warnings=warnings + list(request.resolution.warnings))


def _condition_column(binding: Binding,
                      column_for: dict[tuple[str, str], str]) -> str:
    """The column a condition actually tests, after the joins renamed things."""
    measure = column_for[(binding.dataset, binding.field)]
    return {"change_pct": f"{measure}_change_pct",
            "change_abs": f"{measure}_change",
            "level": measure}[binding.condition.kind]


def _join_edge(operations: list[dict[str, Any]], joins: list[dict[str, Any]],
               warnings: list[str], current: str, edge: Edge, *, label: str,
               period: str, request: MultiRequest, catalogue: Any,
               fields_of: dict[str, set[str]],
               by_dataset: dict[str, list[cx.ConceptMatch]]
               ) -> tuple[str, dict[tuple[str, str], str]]:
    """Add one governed hop: scan the far side, roll it up, join it on.

    Returns the new step and, for every concept it brought in, the column name
    that concept now lives under — so the steps after it name the right column
    rather than the one they hoped for.
    """
    target = edge.right
    available = fields_of.get(target, set())
    wanted = sorted(
        {edge.right_field, *[m.field for m in by_dataset.get(target, [])]}
        & available)
    if edge.right_field not in wanted:
        wanted = sorted({edge.right_field, *wanted})

    target_period_field = ""
    try:
        target_period_field = catalogue.dataset(target).period_field
    except Exception:
        target_period_field = ""

    scan_period = period if target_period_field and not edge.is_asof else None
    if edge.is_asof and target_period_field and target_period_field not in wanted:
        wanted = sorted({*wanted, target_period_field})

    # Every joined dataset gets its own prefix. Deterministic and
    # collision-free: `ead` from the impairment run and `ead` from the facility
    # position are different figures, and letting one silently win the column
    # name is how an analysis answers a question about the wrong one.
    prefix = f"{_slug(target)}_"
    scan_id = f"{label}_{_slug(target)}"
    operations.append({
        "id": scan_id, "op": "SCAN",
        "params": {"dataset": target,
                   **({"period": scan_period} if scan_period else {}),
                   "fields": wanted,
                   "alias": f"{target}@{scan_period or 'all periods'}"},
        "label": (f"Read {target}"
                  + (f" at {scan_period}" if scan_period
                     else " across every period, for the as-of match")),
    })

    side = scan_id
    # The many side is rolled up to the join key BEFORE the join. Without this
    # the join multiplies the left-hand book by however many rows the right has
    # per key, and every figure downstream is silently overstated.
    if edge.multiplies_left and not edge.is_asof:
        rolled = f"{scan_id}_grain"
        aggregates = [
            {"function": _rollup(m), "column": m.field, "as": m.field}
            for m in by_dataset.get(target, [])] or [
            {"function": "count", "as": f"{_slug(target)}_rows"}]
        operations.append({
            "id": rolled, "op": "AGGREGATE_BEFORE_JOIN", "inputs": [side],
            "params": {"by": [edge.right_field], "aggregates": aggregates},
            "label": (f"Roll {target} up to one row per {edge.right_field} so "
                      "the join cannot multiply the book"),
        })
        side = rolled
        warnings.append(
            f"{target} has more than one row per {edge.right_field}, so it was "
            f"aggregated to {request.grain} level before joining.")

    if edge.is_asof:
        aligned = f"{label}_aligned_{_slug(target)}"
        operations.append({
            "id": aligned, "op": "TEMPORAL_ALIGN", "inputs": [current],
            "params": {"column": "period", "as": "_asof_period",
                       "rule": "completed_year_of_quarter"},
            "label": (f"Map the reporting quarter onto the latest COMPLETED "
                      f"{target} cycle — Q2 2026 reads the 2025 cycle, because "
                      "the 2026 one had not finished"),
        })
        join_id = f"{label}_asof_{_slug(target)}"
        operations.append({
            "id": join_id, "op": "ASOF_JOIN", "inputs": [aligned, side],
            "params": {
                "on": [{"left": edge.left_field, "right": edge.right_field}],
                "left_order": "_asof_period",
                "right_order": target_period_field or "period",
                "direction": "backward", "order_as": "text",
                "right_prefix": prefix,
            },
            "label": (f"Take each {request.grain}'s latest {target} "
                      "observation dated on or before the analysis period"),
        })
    else:
        join_id = f"{label}_join_{_slug(target)}"
        operations.append({
            "id": join_id, "op": "JOIN", "inputs": [current, side],
            "params": {"kind": "inner",
                       "on": [{"left": edge.left_field, "right": edge.right_field}],
                       "right_prefix": prefix},
            "label": f"Join {target} on {edge.left_field}",
        })

    joins.append({
        "step": join_id, "relationship_id": edge.relationship_id,
        "relationship_name": edge.name, "relationship_version": edge.version,
        "from": edge.left, "to": target,
        "keys": [edge.left_field, edge.right_field],
        "cardinality": edge.cardinality, "temporal_rule": edge.temporal_rule,
        "policy": "asof" if edge.is_asof else "inner",
        "aggregated_first": edge.multiplies_left and not edge.is_asof,
        "period": scan_period or "as-of",
        "semantic": edge.semantic,
    })
    return join_id, {(target, m.field): f"{prefix}{m.field}"
                     for m in by_dataset.get(target, [])}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


__all__ = [
    "CUSTOMER",
    "DATASET_GRAIN",
    "DEFAULT_BASE",
    "FACILITY",
    "MIN_DATASETS_FOR_MULTI",
    "Binding",
    "JoinGraph",
    "MultiRequest",
    "PlanBuild",
    "build_plan",
    "explain",
    "read_question",
]
