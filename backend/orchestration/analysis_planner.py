"""
From a reading to an Analytical IR.

This is what replaced the phrase-to-named-analysis map. Nothing here matches a
sentence against a catalogue of anticipated questions; it takes the structured
reading — governed concepts, entities, dimensions, operation, periods — and
builds the plan those imply.

Four shapes cover what a credit officer asks:

``AGGREGATE``   one period, grouped by a dimension, measures summed or averaged.
                "What is total EAD by sector in the latest quarter?"
``RANKING``     one period, filtered, aggregated to the analysis grain, ordered,
                cut to N. "Show the five largest Real Estate customers by EAD."
``COHORT``      two periods, every stated condition true. "Which customers had a
                rating downgrade and an increase in ECL over the latest year?"
``MOVEMENT``    two periods, no conditions — how a measure moved.

The two single-period shapes are built here. The two-period shapes are built by
`multi.build_plan`, which already knows how to reconcile grains, walk governed
relationships and align annual sources as-of a quarterly book — that machinery
is not duplicated, it is driven from the reading instead of from a regex.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import concepts as cx
from backend.orchestration import multi
from backend.orchestration import semantics as sm
from backend.orchestration.capability import Reading
from backend.orchestration.context import GovernedContext
from backend.orchestration.dynamic import Condition

logger = logging.getLogger(__name__)

AGGREGATE = "aggregate"
RANKING = "ranking"
COHORT = "cohort"
MOVEMENT = "movement"

#: How many rows a ranking returns when the question did not say. Ten is what
#: "the largest" means in a credit review; more is a report, not an answer.
DEFAULT_TOP_N = 10

#: The comparison window a movement question means when it does not say. A year
#: is the credit review cycle, and it is the window annual sources — ratings,
#: borrower financials — are published on. Stated on every answer that uses it.
DEFAULT_HORIZON_QUARTERS = 4
MAX_TOP_N = 200

#: Aggregations by what the measure IS. Summing a percentage is meaningless and
#: averaging an exposure hides the book, so neither is left to a default.
_ROLLUP: dict[str, str] = {
    "USD mn": "sum", "%": "avg", "x": "avg", "days": "max",
    "grade": "max", "notches": "sum",
}


@dataclass
class AnalysisBuild:
    """The plan, and everything the answer and the Trace need to explain it."""

    plan: dict[str, Any]
    shape: str
    reading: Reading
    #: The governed fields the plan reads, resolved from concepts.
    matches: list[cx.ConceptMatch] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    filters: list[tuple[str, str]] = field(default_factory=list)
    dataset: str = ""
    grain: str = "customer"
    period: str = ""
    opening: str = ""
    closing: str = ""
    dimension: str = ""
    top_n: int = 0
    joins: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""
    #: Populated for the two-period shapes, which delegate to multi.build_plan.
    request: Any = None

    @property
    def datasets(self) -> list[str]:
        if self.request is not None:
            return list(self.request.datasets)
        return [self.dataset] if self.dataset else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": self.shape, "dataset": self.dataset, "grain": self.grain,
            "period": self.period, "opening_period": self.opening,
            "closing_period": self.closing, "dimension": self.dimension,
            "top_n": self.top_n, "datasets": self.datasets,
            "filters": [{"field": f, "value": v} for f, v in self.filters],
            "conditions": [c.to_dict() for c in self.conditions],
            "concepts": [m.to_dict() for m in self.matches],
            "summary": self.summary,
            "warnings": list(self.warnings),
        }


class CannotPlan(Exception):
    """The reading is not enough to build a plan, and says what is missing."""

    def __init__(self, reason: str, *, clarification: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.clarification = clarification or reason


# --------------------------------------------------------------- the entry


def plan(reading: Reading, context: GovernedContext, *,
         question: str = "") -> AnalysisBuild:
    """Build the IR one reading implies, or say what is missing.

    Never guesses a threshold, a period or a dimension the reading did not
    carry. A question that cannot be planned raises rather than narrowing
    itself into one that can — a confident answer to a nearby question is the
    failure this whole rebuild is about.
    """
    from backend.data_access import get_catalog

    catalogue = get_catalog()
    text = question or reading.objective
    known = {d.name: {f["name"] for f in d.fields} for d in context.datasets}
    if not known:
        known = cx.catalogue_fields(catalogue)

    resolved = cx.read_concepts(text, known=known, catalogue=catalogue)
    matches = resolved.matches
    if not matches:
        raise CannotPlan(
            "No governed measure was named.",
            clarification=(
                "Which figure should CreditProbe measure? Name one of the "
                "governed concepts — exposure at default, expected credit "
                "loss, internal rating, days past due — and it will compose "
                "the analysis."))

    filters = _filters(reading, context)
    conditions = _conditions(text, matches)
    dimension = _dimension(reading, context, text)
    shape = _shape(reading, conditions, dimension, text)

    if shape in (COHORT, MOVEMENT):
        return _two_period(reading, context, text, matches, filters,
                           conditions, shape)
    return _single_period(reading, context, text, matches, filters,
                          dimension, shape, catalogue)


# --------------------------------------------------------------- the pieces


def _shape(reading: Reading, conditions: list[Condition],
           dimension: str, text: str) -> str:
    """Which of the four shapes this reading is.

    Order matters. A question with movement conditions is a cohort even if it
    also names a dimension, because the conditions are what select the
    population and the dimension is only how it is displayed.
    """
    if conditions:
        return COHORT
    if reading.period_requirement == "two_period":
        return MOVEMENT
    if reading.operation == "rank" or _explicit_top_n(text):
        return RANKING
    if dimension or reading.operation in {"distribution", "sum", "average",
                                          "count"}:
        return AGGREGATE
    return RANKING if reading.operation == "list" else AGGREGATE


def _filters(reading: Reading, context: GovernedContext) -> list[tuple[str, str]]:
    """Governed filters from the entities the reading resolved."""
    permitted = context.dimensions
    out: list[tuple[str, str]] = []
    for entity in reading.entities:
        kind, value = entity.get("kind", ""), entity.get("value", "")
        if kind in permitted and value in permitted[kind]:
            out.append((kind, value))
    return out


def _conditions(text: str, matches: list[cx.ConceptMatch]) -> list[Condition]:
    """One condition per concept the question attached a movement to."""
    out: list[Condition] = []
    for match in matches:
        movement = sm.movement_near(text, match.phrase)
        condition = sm.condition_for(match, movement)
        if condition is not None:
            out.append(condition)
    return out


def _dimension(reading: Reading, context: GovernedContext, text: str) -> str:
    if reading.dimensions:
        first = reading.dimensions[0]
        if first in context.dimensions:
            return first
    import re

    lowered = text.lower()
    for name in context.dimensions:
        if re.search(rf"\bby {re.escape(name)}\b|\bper {re.escape(name)}\b"
                     rf"|\bacross {re.escape(name)}s?\b|\b{re.escape(name)} "
                     rf"(?:breakdown|split|distribution)\b", lowered):
            return name
    return ""


def _explicit_top_n(text: str) -> int:
    """A count the question actually stated. Zero means it did not."""
    import re

    lowered = (text or "").lower()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20,
             "fifty": 50, "hundred": 100}
    match = re.search(
        r"\b(?:top|largest|biggest|smallest|bottom|worst|best|first)\s+"
        r"(\d+|" + "|".join(words) + r")\b", lowered)
    if not match:
        match = re.search(
            r"\b(\d+|" + "|".join(words) + r")\s+(?:largest|biggest|smallest|"
            r"worst|best|top|highest|lowest)\b", lowered)
    if not match:
        return 0
    raw = match.group(1)
    value = int(raw) if raw.isdigit() else words.get(raw, 0)
    return min(value, MAX_TOP_N)


def _rollup_for(match: cx.ConceptMatch) -> str:
    """How this measure aggregates, decided by what it is.

    Summing a coverage percentage produces a number with no meaning, and
    averaging exposure hides the size of the book. Neither is a default worth
    having, so the unit decides.
    """
    if match.concept.is_ordinal:
        return "max"
    return _ROLLUP.get(match.concept.unit or "", "sum")


def _grain_key(grain: str) -> str:
    return {"customer": "customer_id", "facility": "account_id",
            "sector": "sector"}.get(grain, "customer_id")


def _period_for(reading: Reading, context: GovernedContext,
                dataset: str) -> str:
    """The period to read, preferring what the reading named.

    Falls back to the dataset's own latest published period rather than the
    vocabulary's, because a dataset published one quarter behind the book must
    be read where it has data instead of returning nothing.
    """
    summary = context.dataset(dataset)
    available = list(summary.periods) if summary else list(context.periods)
    for period in reading.periods:
        if period in available:
            return period
    return available[-1] if available else ""


# ------------------------------------------------------- single-period plans


def _single_period(reading: Reading, context: GovernedContext, text: str,
                   matches: list[cx.ConceptMatch],
                   filters: list[tuple[str, str]], dimension: str,
                   shape: str, catalogue: Any) -> AnalysisBuild:
    """AGGREGATE and RANKING: read one period, group, order, cut.

    Both are one dataset. A single-period question spanning two governed
    sources is rare and is planned as a cohort with no conditions instead,
    where the join machinery already lives.
    """
    dataset = matches[0].dataset
    same = [m for m in matches if m.dataset == dataset]
    fields_of = {d.name: set(d.fields) for d in catalogue.all()}
    available = fields_of.get(dataset, set())

    period = _period_for(reading, context, dataset)
    if not period:
        raise CannotPlan(f"{dataset} has no published periods to read.")

    grain = _grain(reading, text, dataset)
    key = _grain_key(grain)
    if key not in available:
        # The dataset cannot be reported at that grain. Fall back to whatever
        # it IS keyed on rather than inventing a column.
        key = next((k for k in ("customer_id", "account_id")
                    if k in available), "")

    filter_fields = [f for f, _ in filters if f in available]
    dropped = [f for f, _ in filters if f not in available]
    warnings: list[str] = []
    if dropped:
        warnings.append(
            f"{dataset} does not carry {', '.join(dropped)}, so that filter "
            "could not be applied here.")
        filters = [(f, v) for f, v in filters if f in available]

    if dimension and dimension not in available:
        warnings.append(
            f"{dataset} does not carry {dimension}, so the answer is not "
            "broken down by it.")
        dimension = ""

    measures = [m for m in same if m.field in available]
    if not measures:
        raise CannotPlan(f"{dataset} does not carry the measures named.")

    read_fields = sorted({key, *filter_fields, *([dimension] if dimension else []),
                          *[m.field for m in measures]} & available)
    operations: list[dict[str, Any]] = [{
        "id": "source", "op": "SCAN",
        "params": {"dataset": dataset, "period": period, "fields": read_fields,
                   "alias": f"{dataset}@{period}"},
        "label": f"Read {dataset} at {period}",
    }]
    current = "source"

    if filters:
        operations.append({
            "id": "scoped", "op": "FILTER", "inputs": [current],
            "params": {"where": [{"column": f, "op": "=", "value": v}
                                 for f, v in filters]},
            "label": "Restrict to " + ", ".join(v for _, v in filters),
        })
        current = "scoped"

    if shape == AGGREGATE and dimension:
        group_by = [dimension]
        label = f"Total by {dimension}"
    elif shape == RANKING:
        group_by = [key] + ([dimension] if dimension else [])
        label = f"Aggregate to one row per {grain}"
    else:
        group_by = [dimension] if dimension else []
        label = "Aggregate across the population"

    aggregates = [{"function": _rollup_for(m), "column": m.field,
                   "as": m.field} for m in measures]
    if shape == RANKING and "borrower_name" in available:
        aggregates.append({"function": "any_value", "column": "borrower_name",
                           "as": "borrower_name"})
        if "borrower_name" not in read_fields:
            operations[0]["params"]["fields"] = sorted(
                set(read_fields) | {"borrower_name"})

    if group_by:
        operations.append({
            "id": "grouped", "op": "GROUP", "inputs": [current],
            "params": {"by": group_by, "aggregates": aggregates},
            "label": label,
        })
        current = "grouped"
    else:
        operations.append({
            "id": "grouped", "op": "AGGREGATE", "inputs": [current],
            "params": {"aggregates": aggregates},
            "label": "Total across the population",
        })
        current = "grouped"

    ordered_by = measures[0]
    descending = _descending(ordered_by, text)

    # A share, computed against the population the question actually asked
    # about. "The five largest Real Estate customers" wants each one's share of
    # REAL ESTATE exposure; dividing by the whole book instead answers a
    # different question, and reporting the filtered population's share of
    # itself as 100% — which is what a concentration analysis run on a filtered
    # book does — answers no question at all.
    share_of = ""
    if shape == RANKING and _ROLLUP.get(ordered_by.concept.unit or "") == "sum":
        share_of = f"{ordered_by.field}_share_pct"
        operations.append({
            "id": "population", "op": "WINDOW", "inputs": [current],
            "params": {"function": "sum", "column": ordered_by.field,
                       "as": f"{ordered_by.field}_population"},
            "label": ("Total " + ordered_by.concept.label
                      + (" across " + ", ".join(v for _, v in filters)
                         if filters else " across the population")),
        })
        operations.append({
            "id": "shared", "op": "RATIO", "inputs": ["population"],
            "params": {"numerator": ordered_by.field,
                       "denominator": f"{ordered_by.field}_population",
                       "as": share_of, "as_percent": True},
            "label": (f"Each {grain}'s share of that total — not of the whole "
                      "book, which the question did not ask about"),
        })
        current = "shared"

    operations.append({
        "id": "ranked", "op": "SORT", "inputs": [current],
        "params": {"by": [{"column": ordered_by.field,
                           "direction": "desc" if descending else "asc"}]},
        "label": (f"Order by {ordered_by.concept.label}, "
                  + ("largest first" if descending else "smallest first")),
    })
    current = "ranked"

    top_n = 0
    if shape == RANKING:
        top_n = _explicit_top_n(text) or DEFAULT_TOP_N
        operations.append({
            "id": "result", "op": "LIMIT", "inputs": [current],
            "params": {"n": top_n},
            "label": f"The {top_n} the question asked for",
        })

    summary = _summary(shape, measures, filters, dimension, period, grain, top_n)
    plan_doc = {
        "id": f"dynamic_{shape}",
        "operations": operations,
        "meta": {
            "kind": f"dynamic_{shape}", "grain": grain, "period": period,
            "dataset": dataset, "datasets": [dataset],
            "dimension": dimension, "top_n": top_n,
            "share_column": share_of,
            "share_of": ", ".join(v for _, v in filters) or "the population",
            "concepts": [m.to_dict() for m in measures],
            "filters": [{"field": f, "value": v} for f, v in filters],
            "conditions": [],
            "explanation": summary,
        },
    }
    return AnalysisBuild(
        plan=plan_doc, shape=shape, reading=reading, matches=measures,
        conditions=[], filters=filters, dataset=dataset, grain=grain,
        period=period, dimension=dimension, top_n=top_n, warnings=warnings,
        summary=summary,
    )


def _grain(reading: Reading, text: str, dataset: str) -> str:
    import re

    lowered = (text or "").lower()
    if re.search(r"\bcustomers?\b|\bborrowers?\b|\bobligors?\b|\bclients?\b|"
                 r"\bnames?\b|\bgroups?\b", lowered):
        return "customer"
    if re.search(r"\bfacilit|\baccounts?\b|\bloans?\b", lowered):
        return "facility"
    return multi.DATASET_GRAIN.get(dataset, "customer")


def _descending(match: cx.ConceptMatch, text: str) -> bool:
    """Largest first unless the question asked for the other end."""
    import re

    lowered = (text or "").lower()
    if re.search(r"\b(?:smallest|lowest|bottom|least|weakest)\b", lowered):
        return False
    if re.search(r"\b(?:largest|biggest|highest|top|most|worst)\b", lowered):
        return True
    return True


def _summary(shape: str, measures: list[cx.ConceptMatch],
             filters: list[tuple[str, str]], dimension: str, period: str,
             grain: str, top_n: int) -> str:
    names = ", ".join(m.concept.label for m in measures)
    where = " for " + ", ".join(v for _, v in filters) if filters else ""
    if shape == AGGREGATE and dimension:
        return f"{names} by {dimension}{where} at {period}."
    if shape == RANKING:
        return (f"The {top_n} {grain}s with the largest {names}{where} "
                f"at {period}.")
    return f"{names}{where} at {period}."


# --------------------------------------------------------- two-period plans


def _two_period(reading: Reading, context: GovernedContext, text: str,
                matches: list[cx.ConceptMatch],
                filters: list[tuple[str, str]],
                conditions: list[Condition], shape: str) -> AnalysisBuild:
    """Delegate to the multi-dataset builder, driven by the reading.

    The reading has already done the part that used to be a regex: which
    concepts, which governed fields, which movement each one asserts. What is
    built here is the `MultiRequest` that machinery consumes — the joins, the
    grain reconciliation and the as-of alignment are its job, not this one's.
    """
    from backend.data_access import get_catalog
    from backend.runtime.joins import build_graph, resolve

    catalogue = get_catalog()
    opening, closing, reason, assumed = _two_periods(reading, context, text)
    if reason:
        raise CannotPlan(reason, clarification=reason)

    grain = _grain(reading, text, matches[0].dataset)
    if grain == "sector":
        grain = "customer"
    key = _grain_key(grain)

    by_field = {m.field: m for m in matches}
    bindings = [multi.Binding(condition=c, match=by_field[c.field])
                for c in conditions if c.field in by_field]
    # A measure named with no movement still has to be read — it is what the
    # answer reports even when it does not filter.
    for match in matches:
        if all(b.match is not match for b in bindings):
            bindings.append(multi.Binding(
                condition=Condition(field=match.field, kind="order", op="gt",
                                    value=0, phrase=match.phrase,
                                    higher_is_worse=match.concept.higher_is_worse),
                match=match))

    base = multi.DEFAULT_BASE
    targets = sorted({b.dataset for b in bindings} - {base})
    graph = build_graph(_relationship_rows(context))
    resolution = resolve(graph, base=base, targets=targets)
    if not resolution.ok:
        missing = ", ".join(resolution.unreachable) or "the sources named"
        raise CannotPlan(
            f"No governed relationship reaches {missing}.",
            clarification=(
                f"CreditProbe cannot join {missing} to {base}: no active "
                "relationship connects them. A data steward can declare one in "
                "Data Builder."))

    request = multi.MultiRequest(
        question=text, understood=True, base=base,
        shape=multi.COHORT if shape == COHORT else multi.RANKING,
        grain=grain, key=key, opening=opening, closing=closing,
        reading=cx.Reading(matches=list(matches)),
        bindings=bindings, filters=filters, resolution=resolution,
        summary=_two_period_summary(conditions, filters, opening, closing, grain),
        confidence={"reading": reading.confidence},
    )
    built = multi.build_plan(request, catalogue=catalogue)
    warnings = list(built.warnings)
    if assumed:
        warnings.append(
            f"The question did not say over what period to measure the change, "
            f"so CreditProbe compared {opening} with {closing} — the latest "
            "year. Name two periods to measure a different window.")
    return AnalysisBuild(
        plan=built.plan, shape=shape, reading=reading, matches=list(matches),
        conditions=conditions, filters=filters, grain=grain,
        opening=opening, closing=closing, joins=built.joins,
        warnings=warnings, summary=request.summary, request=request,
    )


def _relationship_rows(context: GovernedContext) -> list[dict[str, Any]]:
    return [
        {"id": r.relationship_id, "from_dataset": r.from_dataset,
         "from_field": r.from_field, "to_dataset": r.to_dataset,
         "to_field": r.to_field, "cardinality": r.cardinality,
         "join_policy": r.join_policy, "temporal_rule": r.temporal_rule,
         "semantic": r.semantic, "version": r.version,
         "match_rate": r.match_rate, "confidence": 1.0,
         "validated_at": True if r.match_rate is not None else None}
        for r in context.relationships
    ]


def _two_periods(reading: Reading, context: GovernedContext,
                 text: str) -> tuple[str, str, str, bool]:
    """Opening and closing, and whether the window had to be assumed."""
    periods = context.periods
    if not periods:
        return "", "", "No reporting periods are published.", False

    named = [p for p in reading.periods if p in periods]
    if len(named) >= 2:
        ordered = sorted(named, key=periods.index)
        return ordered[0], ordered[-1], "", False

    import re

    lowered = (text or "").lower()
    horizons = ((r"\bover the (?:latest|last|past) year\b|\byear[- ]on[- ]year\b"
                 r"|\bannual(?:ly)?\b|\bin the last year\b|\bover a year\b", 4),
                (r"\bover the (?:latest|last|past) quarter\b|\bquarter[- ]on[- ]"
                 r"quarter\b|\bsince last quarter\b", 1),
                (r"\bover (?:the )?(?:latest|last|past) two years\b", 8),
                (r"\bsince \d{4}\b", 0))
    quarters = 0
    stated = False
    for pattern, span in horizons:
        if re.search(pattern, lowered):
            quarters = span
            stated = True
            break

    if not quarters:
        # A credit review compares against a year ago unless it says otherwise,
        # and refusing to answer until the user restates the obvious is worse
        # service than answering and saying which window was used. The window
        # is carried into the summary and shown on the answer, so a reader who
        # meant something else can see that immediately rather than discover it
        # in a committee.
        quarters = DEFAULT_HORIZON_QUARTERS

    if len(named) == 1:
        index = periods.index(named[0])
        start = max(0, index - quarters)
        return periods[start], named[0], "", not stated

    index = len(periods) - 1 - quarters
    if index < 0:
        return "", "", (f"That span needs {quarters + 1} periods and only "
                        f"{len(periods)} are published."), False
    return periods[index], periods[-1], "", not stated


def _two_period_summary(conditions: list[Condition],
                        filters: list[tuple[str, str]],
                        opening: str, closing: str, grain: str) -> str:
    where = " ".join(v for _, v in filters)
    subject = f"{where} {grain}s" if where else f"{grain}s"
    if not conditions:
        return f"How {subject} moved between {opening} and {closing}."
    stated = ", ".join(c.describe() for c in conditions)
    return f"All {subject} where {stated}, measured between {opening} and {closing}."


__all__ = [
    "AGGREGATE",
    "COHORT",
    "DEFAULT_TOP_N",
    "MOVEMENT",
    "RANKING",
    "AnalysisBuild",
    "CannotPlan",
    "plan",
]
