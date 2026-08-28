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

#: Mirrors the runtime's own limits, checked here so a question is refused
#: with an explanation rather than by the compiler with a stack trace.
_MAX_JOINS = 10
_MAX_HOPS = 3

MAX_ROWS = 500
#: A ranking question wants the top of the list. Returning five hundred rows to
#: "which borrowers are closest to breach" is a table, not an answer.
MAX_RANKED = 50

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

_OPS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "="}

# ---- the shape of the answer ------------------------------------------------
#
# Three shapes, because three genuinely different questions get asked of the
# same joined data and answering one as another is a wrong answer rather than
# an ugly one.

#: "Which customers meet ALL of these conditions" — a filtered population.
COHORT = "cohort"
#: "Are these two things related" — no threshold, a measured association, and
#: an interpretation that says co-movement rather than cause.
ASSOCIATION = "association"
#: "Which are closest to / worst / top" — an ordering, not a threshold. A
#: question with no cut-off answered as though it had one invents the cut-off.
RANKING = "ranking"

_ASSOCIATION_WORDS = (r"more likely|less likely|associated with|correlat\w*|"
                      r"related to|relationship between|go(?:es)? together|"
                      r"tend to|predict\w*|co-?move")
_RANKING_WORDS = (r"closest to|nearest to|most at risk|worst|top \d+|"
                  r"highest|lowest|largest|biggest|riskiest|which .* are closest")

#: A level stated in the question — "Stage 2", "grade 8". Only where the
#: concept is ordinal and the number is small: "increased more than 20%" is a
#: movement and reading it as a level would filter on a figure nobody meant.
_LEVEL = re.compile(
    r"\b(stage|grade|bucket)\s*(\d{1,2})\b", re.IGNORECASE)

#: "negative sentiment", "positive signals". A polarity, not a movement: the
#: question is about where the measure IS, not about how it changed. Applied
#: only to signed measures — a "negative rating" is not a thing, and reading
#: one would filter the book to nothing while looking like it worked.
_POLARITY = re.compile(
    r"\b(negative|positive|adverse|favourable|favorable)\s+"
    r"(?P<measure>[a-z][a-z0-9\-]*(?:\s+[a-z][a-z0-9\-]*){0,3})",
    re.IGNORECASE)

#: Concepts a polarity may be applied to: a signed score centred on zero, or a
#: governed category with named polarities.
_SIGNED_CONCEPTS = frozenset({"sentiment"})


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
    shape: str = COHORT
    grain: str = CUSTOMER
    key: str = "customer_id"
    opening: str = ""
    closing: str = ""
    reading: cx.Reading = field(default_factory=cx.Reading)
    bindings: list[Binding] = field(default_factory=list)
    filters: list[tuple[str, str]] = field(default_factory=list)
    resolution: Resolution | None = None
    #: Identities carried forward from a previous turn — {"key": ..., "ids": [...]}.
    #: When set, every shape is restricted to exactly these rows rather than
    #: re-deriving a population that may have moved.
    population: dict[str, Any] | None = None
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
            "shape": self.shape,
            "grain": self.grain,
            "key": self.key,
            "opening_period": self.opening,
            "closing_period": self.closing,
            "datasets": self.datasets,
            "concepts": self.reading.to_dict(),
            "bindings": [b.to_dict() for b in self.bindings],
            # Also flat, under the name the single-dataset reading uses. The
            # answer panel renders one reading shape whichever path produced
            # it, and a key present on one and absent on the other is how a
            # panel that works for a single dataset breaks for three.
            "conditions": [b.condition.to_dict() for b in self.bindings],
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


def _bind_ordering(request: Any, reading: Any, *, resolver: Any,
                   conditions: list[Condition]) -> None:
    """Turn a RANK objective into an `order` condition.

    An `order` binding filters nothing — it names the column the answer is
    sorted by. That distinction already existed in `Condition.kind`; what P0.3
    adds is reading the RANKING CLAUSE for it instead of letting every measure
    in the message become a movement condition.
    """
    ranking = getattr(reading, "ranking", None)
    if ranking is None or not ranking.measure_phrase:
        return
    if any(c.kind == "order" for c in conditions):
        return
    found = resolver(ranking.measure_phrase, request.question)
    if not found:
        request.reasons.append(
            f"CreditProbe could not order by '{ranking.measure_phrase}' — it "
            f"names no governed measure.")
        return
    field, higher_is_worse = found
    conditions.append(Condition(
        field=field, kind="order", op="gte", value=0.0,
        phrase=ranking.measure_phrase, higher_is_worse=higher_is_worse))
    # The SHAPE is left alone. "Which customers ...? Rank them by EAD" is a
    # cohort question that also asks for an ordering, not a ranking question:
    # turning it into one would drop the conditions that define the cohort.


def read_question(question: str, *, catalogue: Any, periods: list[str],
                  dimensions: dict[str, list[str]] | None = None,
                  relationships: list[dict[str, Any]] | None = None,
                  base: str = DEFAULT_BASE,
                  reading: Any = None) -> MultiRequest:
    """Read a question into an explicit multi-dataset request, or refuse.

    Deterministic throughout. The reading decides which datasets are joined and
    therefore what is computed; a reading that varies between two identical
    questions makes every answer unreproducible.

    `reading` is the P0.3 objective decomposition. With one, movement
    conditions are read only from the clauses that DEFINE the population, and
    the measure a ranking clause names becomes an ordering rather than a fifth
    condition. Without it, "Rank them by EAD" contributed a condition on EAD
    and the answer was quietly about a narrower cohort than the one asked for.
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

    # Movement conditions come from the clauses that DEFINE the population.
    # With no objective reading that is the whole message, which is what this
    # did before P0.3.
    condition_text = request.question
    if reading is not None:
        from backend.orchestration.dynamic import _defining_text

        condition_text = _defining_text(reading) or request.question

    conditions, unread = read_conditions(condition_text, resolver=resolver)
    if unread:
        request.reasons.append(
            "CreditProbe could not read: " + "; ".join(f"'{u}'" for u in unread))

    # The ranking the request asked for, as an ordering rather than a filter.
    if reading is not None:
        _bind_ordering(request, reading, resolver=resolver, conditions=conditions)

    # A level stated outright — "Stage 2 accounts" — is a filter on where the
    # population IS, not on how it moved. Read separately because the movement
    # reader would either miss it or, worse, read the number as a magnitude.
    levels = _read_levels(request.question, known=known, catalogue=catalogue)
    for match, value, comparison in levels:
        by_phrase[match.field] = match
        conditions.append(Condition(
            field=match.field, kind="level", op=comparison, value=value,
            phrase=match.phrase, higher_is_worse=match.concept.higher_is_worse))

    lowered = request.question.lower()
    if re.search(_ASSOCIATION_WORDS, lowered):
        request.shape = ASSOCIATION
    elif re.search(_RANKING_WORDS, lowered):
        request.shape = RANKING

    movement = [c for c in conditions if c.kind != "level"]
    if request.shape == ASSOCIATION and len(movement) < 2:
        request.reasons.append(
            "An association needs two measures that both move. Name the second "
            "one — CreditProbe will not correlate a measure with itself.")
    elif request.shape == COHORT and not conditions:
        request.reasons.append(
            "The question names no measurable condition. Say how a measure "
            "moved, and by how much.")
    elif request.shape == RANKING:
        # "Closest to covenant breach" names a measure and no movement. That is
        # a legitimate question — the ranking IS the answer — so every concept
        # the question named becomes something it is ordered by, with no
        # threshold invented for one it did not set.
        bound = {c.field for c in conditions}
        for candidate in request.reading.matches:
            if candidate.field in bound:
                continue
            by_phrase[candidate.field] = candidate
            conditions.append(Condition(
                field=candidate.field, kind="order", op="gte", value=0.0,
                phrase=candidate.phrase,
                higher_is_worse=candidate.concept.higher_is_worse))
        if not conditions:
            request.reasons.append(
                "The question asks which are worst, but names no measure to "
                "rank them by.")

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

    # ---- 6. join safety, before anything is built
    edges = request.resolution.edges()
    if len(edges) * 2 > _MAX_JOINS:
        request.reasons.append(
            f"Answering this needs {len(edges)} governed joins on each side of "
            f"the comparison, which is more than the runtime will compose "
            f"({_MAX_JOINS}). Narrow the question — each extra source costs "
            "population as well as time.")
    for path in request.resolution.paths:
        if path.hops > _MAX_HOPS:
            request.reasons.append(
                f"Reaching {path.target} takes {path.hops} hops through the "
                "governed relationships. Past three, so little of the original "
                "population survives that the answer stops describing the "
                "book it started from.")

    # ---- 7. is the reading good enough to run?
    request.understood = not request.reasons and not request.clarifications
    if request.understood:
        request.summary = _summary(request)
    return request


def _read_levels(question: str, *, known: dict[str, set[str]],
                 catalogue: Any) -> list[tuple[cx.ConceptMatch, Any, str]]:
    """Levels stated outright in the question — "Stage 2", "grade 8".

    Only for ordinal concepts, and only where the number is adjacent to the
    word. "ECL increased more than 20%" contains a number too, and reading it
    as a level would filter the book to an ECL of exactly 20.
    """
    out: list[tuple[cx.ConceptMatch, float]] = []
    for found in _POLARITY.finditer(question):
        local = cx.read_concepts(found.group("measure"), known=known,
                                 catalogue=catalogue)
        if not local.matches:
            continue
        match = local.matches[0]
        if match.concept.id not in _SIGNED_CONCEPTS:
            continue
        settled = cx.resolve_concept(match.concept, question, known=known,
                                     catalogue=catalogue, phrase=found.group(0))
        chosen = settled or match
        word = found.group(1).lower()
        if chosen.concept.is_categorical:
            mapped = dict(chosen.concept.polarity).get(word)
            if mapped is None:
                continue
            out.append((chosen, mapped, "eq"))
        else:
            out.append((chosen, 0.0,
                        "lt" if word in ("negative", "adverse") else "gt"))

    for found in _LEVEL.finditer(question):
        word, number = found.group(1), found.group(2)
        local = cx.read_concepts(word, known=known, catalogue=catalogue)
        if not local.matches:
            continue
        match = local.matches[0]
        if not match.concept.is_ordinal:
            continue
        settled = cx.resolve_concept(match.concept, question, known=known,
                                     catalogue=catalogue,
                                     phrase=found.group(0))
        out.append((settled or match, float(number), "eq"))
    return out


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
    if match.concept.is_categorical:
        return "any_value"
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
    if request.population:
        filter_fields.append(str(request.population.get("key") or ""))
    filter_fields = [f for f in filter_fields if f]

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

    # A category is compared, never differenced. Only quantities get a change
    # and a percentage change derived for them.
    measures = list(dict.fromkeys(
        column_for[(b.dataset, b.field)] for b in request.bindings
        if (b.dataset, b.field) in column_for
        and not b.match.concept.is_categorical))

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

    # Governed dimension filters and any level stated outright apply to every
    # shape; a threshold on how a measure MOVED applies only where the question
    # actually set one.
    # Same-dimension values are grouped into one `in`. Two `=` predicates on
    # `ifrs9_stage` would be ANDed and select nothing — an empty result that
    # looks like a finding rather than like a bug.
    grouped: dict[str, list[str]] = {}
    for dimension, value in request.filters:
        grouped.setdefault(dimension, []).append(value)
    standing = [
        ({"column": dimension, "op": "=", "value": values[0]} if len(values) == 1
         else {"column": dimension, "op": "in", "values": values})
        for dimension, values in grouped.items()
    ]
    if request.population and request.population.get("ids"):
        standing.append({"column": str(request.population["key"]), "op": "in",
                         "values": [str(v) for v in request.population["ids"]]})
    standing += [{"column": _condition_column(b, column_for,
                                              two_period=_two_period(request)),
                  "op": _OPS[b.condition.op], "value": b.condition.value}
                 for b in request.bindings if b.condition.kind == "level"]

    movement = [b for b in request.bindings
                if b.condition.kind not in ("level", "order")]
    ordering_only = [b for b in request.bindings if b.condition.kind == "order"]

    if request.shape == ASSOCIATION:
        _association(operations, request, column_for, standing, movement)
    elif request.shape == RANKING:
        _ranking(operations, request, column_for, standing,
                 movement + ordering_only)
    else:
        _cohort(operations, request, column_for, standing, movement)

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



def _two_period(request: Any) -> bool:
    """Whether the plan joined a closing position onto an opening one."""
    opening = str(getattr(request, "opening", "") or "")
    closing = str(getattr(request, "closing", "") or "")
    return bool(opening and closing and opening != closing)


def _cohort(operations: list[dict[str, Any]], request: MultiRequest,
            column_for: dict[tuple[str, str], str],
            standing: list[dict[str, Any]], movement: list[Binding]) -> None:
    """Everything meeting every condition, worst first."""
    where = standing + [
        {"column": _condition_column(b, column_for,
                                     two_period=_two_period(request)),
         "op": _OPS[b.condition.op], "value": b.condition.value}
        for b in movement]
    operations.append({
        "id": "cohort", "op": "FILTER", "inputs": ["movements"],
        "params": {"where": where or [{"column": request.key,
                                       "op": "is_not_null"}]},
        "label": "Keep only those meeting every condition",
    })

    # The ordering the request ASKED for, where a clause asked for one. An
    # `order` binding is a measure named to rank by rather than to filter on
    # (P0.3), and it takes precedence over the fallback below — otherwise
    # "Rank them by EAD" produced a cohort ordered by whichever condition
    # happened to be read first, and the requested ranking never happened.
    ordering = next((b for b in request.bindings
                     if b.condition.kind == "order"), None)
    if ordering is not None:
        # `_condition_column` already resolves an `order` binding to the
        # CLOSING position, which is what "rank them by EAD" means: the
        # exposure they carry now, not how much it moved.
        sort_column = _condition_column(ordering, column_for,
                                        two_period=_two_period(request))
        sort_label = f"Ranked by {ordering.match.concept.label}, largest first"
        direction = "desc"
    else:
        first = (movement or request.bindings)[0]
        sort_column = _condition_column(first, column_for,
                                        two_period=_two_period(request))
        direction = ("desc" if first.condition.op in ("gt", "gte", "eq")
                     else "asc")
        sort_label = "Largest movement first"

    operations.append({
        "id": "ranked", "op": "SORT", "inputs": ["cohort"],
        "params": {"by": [{"column": sort_column, "direction": direction}]},
        "label": sort_label,
    })
    operations.append({
        "id": "result", "op": "LIMIT", "inputs": ["ranked"],
        "params": {"n": MAX_ROWS},
        "label": f"The first {MAX_ROWS} rows",
    })


def _ranking(operations: list[dict[str, Any]], request: MultiRequest,
             column_for: dict[tuple[str, str], str],
             standing: list[dict[str, Any]], movement: list[Binding]) -> None:
    """An ordering, with no threshold invented.

    "Which borrowers are closest to covenant breach" sets no cut-off, and
    answering it as though it had one would put a number in the analysis that
    nobody chose. So the population is filtered only by what the question
    actually said, and then ordered.
    """
    operations.append({
        "id": "cohort", "op": "FILTER", "inputs": ["movements"],
        "params": {"where": standing or [{"column": request.key,
                                          "op": "is_not_null"}]},
        "label": ("Apply the conditions the question stated — no threshold is "
                  "invented for a question that set none"),
    })

    ordering = []
    for binding in (movement or request.bindings):
        column = _condition_column(binding, column_for,
                                   two_period=_two_period(request))
        # Worst first: for a measure where higher is worse, descending.
        ordering.append({
            "column": column,
            "direction": "desc" if binding.match.concept.higher_is_worse else "asc",
        })
    operations.append({
        "id": "ranked", "op": "SORT", "inputs": ["cohort"],
        "params": {"by": ordering},
        "label": "Worst first, by each measure the question named",
    })
    operations.append({
        "id": "result", "op": "LIMIT", "inputs": ["ranked"],
        "params": {"n": MAX_RANKED},
        "label": (f"The {MAX_RANKED} worst. A ranking question wants the top "
                  "of the list, not the whole book."),
    })


def _association(operations: list[dict[str, Any]], request: MultiRequest,
                 column_for: dict[tuple[str, str], str],
                 standing: list[dict[str, Any]], movement: list[Binding]) -> None:
    """Whether two measures moved together — and nothing stronger than that.

    No threshold, because the question did not set one, and no direction of
    causation, because a correlation cannot establish one. The kernel returns
    a coefficient and a sample size; the interpretation that goes with it says
    co-movement, and says it in those words.
    """
    operations.append({
        "id": "cohort", "op": "FILTER", "inputs": ["movements"],
        "params": {"where": standing or [{"column": request.key,
                                          "op": "is_not_null"}]},
        "label": "The population the association is measured over",
    })
    first, second = movement[0], movement[1]
    left = _condition_column(first, column_for,
                             two_period=_two_period(request))
    right = _condition_column(second, column_for,
                              two_period=_two_period(request))
    operations.append({
        "id": "result", "op": "CORRELATION", "inputs": ["cohort"],
        "params": {"x": left, "y": right, "columns": [left, right],
                   "method": "pearson"},
        "label": (f"Measure how {first.match.concept.label} and "
                  f"{second.match.concept.label} moved together"),
    })


def _condition_column(binding: Binding,
                      column_for: dict[tuple[str, str], str],
                      *, two_period: bool = False) -> str:
    """The column a condition actually tests, after the joins renamed things.

    The two-period case is where this went wrong, and the failure was silent.
    A movement plan joins the closing position on under a `closing_` prefix,
    which leaves the BARE column holding the OPENING value. A level condition —
    "customers who have covenant headroom below 15%" — was compiled against the
    bare column, so it selected customers whose headroom was below 15% a year
    ago, and the answer contained a customer sitting at 17.41% today under a
    heading that said below 15%.

    "Have" is the present tense. A level is tested at the closing position; a
    movement is tested on the change, which is what it was always about.
    """
    measure = column_for[(binding.dataset, binding.field)]
    at_close = f"closing_{measure}" if two_period else measure
    return {"change_pct": f"{measure}_change_pct",
            "change_abs": f"{measure}_change",
            "level": at_close,
            # An ordering binding filters on nothing; it names the column the
            # answer is sorted by — and "closest to breach" means closest now.
            "order": at_close}[binding.condition.kind]


def _join_edge(operations: list[dict[str, Any]], joins: list[dict[str, Any]],
               warnings: list[str], current: str, edge: Edge, *, label: str,
               period: str, request: MultiRequest, catalogue: Any,
               fields_of: dict[str, set[str]],
               by_dataset: dict[str, list[cx.ConceptMatch]],
               carry: tuple[str, ...] = ()
               ) -> tuple[str, dict[tuple[str, str], str]]:
    """Add one governed hop: scan the far side, roll it up, join it on.

    Returns the new step and, for every concept it brought in, the column name
    that concept now lives under — so the steps after it name the right column
    rather than the one they hoped for.

    `carry` names columns this hop must bring forward for a LATER hop to join
    on. A two-hop path — ratings to facility to impairment — joins the second
    hop on `account_id`, which only the middle dataset has; without carrying it
    the plan asked for a key at a step that had never read it, and the whole
    multi-measure answer was lost to a validation error.
    """
    target = edge.right
    available = fields_of.get(target, set())
    wanted = sorted(
        {edge.right_field, *carry,
         *[m.field for m in by_dataset.get(target, [])]}
        & available)
    if edge.right_field not in wanted:
        wanted = sorted({edge.right_field, *wanted})

    target_period_field = ""
    try:
        target_period_field = catalogue.dataset(target).period_field
    except Exception:
        target_period_field = ""

    scan_period = (_period_in(target, period, catalogue)
                   if target_period_field and not edge.is_asof else None)
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
    carried = tuple(c for c in carry if c in wanted and c != edge.right_field)
    if edge.multiplies_left and not edge.is_asof and not carried:
        # A hop that has to carry a key onward cannot be rolled up here: the
        # roll-up is to one row per join key, and the key the NEXT hop needs
        # does not survive it. The multiplication it guards against is handled
        # by the grouping at the end of the plan instead.
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
    brought = {(target, m.field): f"{prefix}{m.field}"
               for m in by_dataset.get(target, [])}
    # A carried key comes through under the join's prefix, so the next hop has
    # to be told its new name. Recorded the same way a measure is, keyed by the
    # dataset it came from.
    for column in carried:
        brought[(target, column)] = f"{prefix}{column}"
    return join_id, brought


def _period_in(dataset: str, period: str, catalogue: Any) -> str | None:
    """The period to read `dataset` at, given the one the analysis is about.

    Datasets do not share a calendar. The rating history is annual and the
    impairment run is quarterly, so an analysis anchored on "2025" asked
    ifrs9_staging for a period it has never published and the whole answer was
    lost to "no data for period '2025'".

    The rule is the conservative one: the latest period this dataset publishes
    that does not run past the one asked for. Reading a later period would
    answer with impairment the rating had not seen.
    """
    if not period:
        return None
    try:
        from backend.data_access import get_data_source

        published = list(get_data_source().periods(dataset) or [])
    except Exception:  # noqa: BLE001
        return period
    if not published or period in published:
        return period

    year = re.search(r"(\d{4})", period)
    if year is None:
        return period
    ceiling = year.group(1)
    within = [p for p in published
              if (m := re.search(r"(\d{4})", p)) and m.group(1) <= ceiling]
    return within[-1] if within else published[-1]


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
