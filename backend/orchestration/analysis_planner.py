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
import re as _re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import concepts as cx
from backend.orchestration import conversation as cv
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
#: A conditional share of a total, per group, compared across two periods.
#: Its own shape rather than a movement with extra columns, because the answer
#: is read completely differently: the figure that matters is the change in the
#: SHARE, and a narrative built for a movement reports the measure's own total
#: and says nothing about the ratio the question asked for.
SHARE_MOVEMENT = "share_movement"

#: How many rows a ranking returns when the question did not say. Ten is what
#: "the largest" means in a credit review; more is a report, not an answer.
DEFAULT_TOP_N = 10

#: The comparison window a movement question means when it does not say. A year
#: is the credit review cycle, and it is the window annual sources — ratings,
#: borrower financials — are published on. Stated on every answer that uses it.
DEFAULT_HORIZON_QUARTERS = 4
MAX_TOP_N = 200

#: The id of the synthetic concept that counts a population.
#:
#: "How many customers are in Stage 2?" and "replace EAD with number of
#: customers" both want a distinct count at the analysis grain. That is not a
#: governed measure — no field carries it — so it cannot come out of the concept
#: resolver. Modelling it as a concept anyway is what lets it flow through the
#: summary, the ordering, the share and the Trace exactly like a real measure,
#: instead of becoming a special case in eight places.
COUNT_CONCEPT = "population_count"

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
    #: How this plan relates to the previous turn's, where it does.
    continuation: Any = None
    #: Measures inherited from the conversation rather than named in the
    #: question. Shown on the Trace so an unasked-for column is explained.
    carried_concepts: list[str] = field(default_factory=list)
    #: Where the population actually sits on the attribute that excluded all of
    #: it. Set only when the result came back empty — see `partition`.
    partition: Any = None

    @property
    def datasets(self) -> list[str]:
        """Every governed source this plan reads, base and enrichments alike.

        The enriched sources come off the joins rather than being tracked
        separately: a dataset that was joined in IS a dataset the answer read,
        and reporting only the base made a two-source answer look single-source
        on the Trace and in validation.
        """
        if self.request is not None:
            return list(self.request.datasets)
        out = [self.dataset] if self.dataset else []
        for join in self.joins:
            target = str(join.get("to") or "")
            if target and target not in out:
                out.append(target)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": self.shape, "dataset": self.dataset, "grain": self.grain,
            "period": self.period, "opening_period": self.opening,
            "closing_period": self.closing, "dimension": self.dimension,
            "top_n": self.top_n, "datasets": self.datasets,
            "filters": [{"field": f, "value": v} for f, v in self.filters],
            "conditions": [c.to_dict() for c in self.conditions],
            "concepts": [m.to_dict() for m in self.matches],
            "carried_concepts": list(self.carried_concepts),
            "continuation": (self.continuation.to_dict()
                             if self.continuation is not None else None),
            "summary": self.summary,
            "warnings": list(self.warnings),
        }


def _count_match(dataset: str, column: str, key: str, grain: str,
                 phrase: str) -> cx.ConceptMatch:
    """A ConceptMatch that counts distinct rows at the grain.

    `field` is the OUTPUT column rather than the one counted, because
    everything downstream — the narrative, the share, the Trace — reads a
    measure's value out of the result by `match.field`. The key it counts is
    supplied separately where the aggregate is built.
    """
    # The definition's last word IS the counted column: the aggregate needs the
    # key while everything downstream needs the output column, and a Candidate
    # carries one field. Stated here rather than left implicit because the
    # aggregate builder reads it back.
    candidate = cx.Candidate(
        dataset=dataset, field=column,
        definition=f"Distinct values counted in the column {key}",
        is_default=True)
    concept = cx.Concept(
        id=COUNT_CONCEPT, label=f"{grain}s", pattern="",
        candidates=(candidate,), higher_is_worse=False, unit="")
    return cx.ConceptMatch(
        concept=concept, candidate=candidate, phrase=phrase,
        reason=f"counted as distinct {key} in the population")


class CannotPlan(Exception):
    """The reading is not enough to build a plan, and says what is missing."""

    def __init__(self, reason: str, *, clarification: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.clarification = clarification or reason


# --------------------------------------------------------------- the entry


def plan(reading: Reading, context: GovernedContext, *,
         question: str = "",
         period: tuple[str, str] | None = None,
         state: cv.ConversationState | None = None,
         continuation: cv.Continuation | None = None) -> AnalysisBuild:
    """Build the IR one reading implies, or say what is missing.

    Never guesses a threshold or a dimension the reading did not carry. A
    question that cannot be planned raises rather than narrowing itself into one
    that can — a confident answer to a nearby question is the failure this whole
    rebuild is about.

    A **period** is the one exception, and deliberately so. "Which customers were
    downgraded?" names no window, but every credit officer asking it means the
    review cycle. Stopping to ask costs a round trip and makes the product look
    unsure of something it is not unsure of, so the governed default is taken and
    the answer states which two periods it used.
    """
    from backend.data_access import get_catalog

    catalogue = get_catalog()
    text = question or reading.objective
    known = {d.name: {f["name"] for f in d.fields} for d in context.datasets}
    if not known:
        known = cx.catalogue_fields(catalogue)

    carrying = bool(continuation and continuation.carries_context and state
                    and state.has_analysis)

    # Concepts the question names, plus the ones the conversation is already
    # about. "Show only the five largest sectors" names no measure at all; it
    # means the measure of the answer it is modifying, and re-resolving from the
    # inherited labels is what turns it into a plan rather than a clarification.
    inherited_metrics = list(state.metrics or state.concepts) if carrying else []
    resolved = cx.read_concepts(text, known=known, catalogue=catalogue)
    matches = list(resolved.matches)
    carried_concepts: list[str] = []
    if carrying and inherited_metrics:
        named = {m.concept.label for m in matches}
        extra = [label for label in inherited_metrics if label not in named]
        if extra:
            more = cx.read_concepts(" ".join(extra), known=known,
                                    catalogue=catalogue)
            fresh = [m for m in more.matches if m.concept.label not in named]
            if continuation and continuation.action == cv.MODIFY_PREVIOUS \
                    and matches:
                # "Rank those by ECL instead" REPLACES the measure. Carrying the
                # old one as well would answer a question with two orderings.
                fresh = []
            matches.extend(fresh)
            carried_concepts = [m.concept.label for m in fresh]

    count_grain = _wants_count(text, reading)
    if not count_grain and carrying and not resolved.matches:
        # "Break that down by sector" after a count is still a count. The
        # sentence names no measure at all, so the measure is whatever the
        # conversation was already reporting — and a count is not a concept the
        # resolver can rediscover from the inherited labels.
        count_grain = bool((state.ir.get("meta") or {}).get("count_column"))
    if count_grain and _replaces(text):
        # "Replace EAD with number of customers" — the count IS the measure now.
        # Keeping the old one as well would answer with two measures where the
        # user asked for one, and the sentence names the measure it is
        # replacing, so a resolver alone cannot tell them apart.
        matches = []
        carried_concepts = []

    if not matches and not count_grain:
        raise CannotPlan(
            "No governed measure was named.",
            clarification=(
                "Which figure should CreditProbe measure? Name one of the "
                "governed concepts — exposure at default, expected credit "
                "loss, internal rating, days past due — and it will compose "
                "the analysis."))

    filters = _filters(reading, context)
    if carrying:
        filters = _inherit_filters(filters, state, context, continuation)
    inherited_top_n = (state.top_n if carrying and state and not _explicit_top_n(text)
                       else 0)
    # Governed values are masked out before movement detection. "Contracting"
    # is a sector; read as a verb it asserts that something contracted, and a
    # ranking of Contracting customers was planned as a cohort of shrinking
    # ones — a different question with no obvious symptom.
    conditions = _conditions(_without_values(text, filters), matches)
    if carrying and not resolved.matches and state.conditions:
        # The question named no measure of its own — "only show Contracting" —
        # so it is narrowing the analysis that just ran rather than starting a
        # different one. Dropping the conditions here would quietly turn "the
        # Contracting names that were downgraded" into "every Contracting name".
        conditions = _restore_conditions(state.conditions, matches)
    dimension = _dimension(reading, context, text)
    if not dimension and carrying and state.dimensions:
        first = state.dimensions[0]
        if first in context.dimensions:
            dimension = first
    shape = _shape(reading, conditions, dimension, text)

    if carrying and not reading.periods and not period and state.opening_period \
            and state.closing_period and shape in (COHORT, MOVEMENT):
        period = (state.opening_period, state.closing_period)
        if continuation is not None:
            continuation.inherited["comparison"] = (
                f"{state.opening_period} → {state.closing_period}")

    # A conditional share compared across two periods. Checked before the
    # ordinary movement shape, which would report the measure's own total and
    # quietly drop the "divided by total" the question was actually about.
    if wants_conditional_share(text) and reading.period_requirement == "two_period":
        try:
            build = _conditional_share(reading, context, text, matches, filters,
                                       dimension, catalogue, period=period)
            if continuation is not None:
                build.continuation = continuation
            return build
        except CannotPlan as e:
            logger.info("A conditional share could not be composed (%s); "
                        "falling back to the ordinary shapes.", e)

    if shape == MOVEMENT and not conditions:
        # "How has ECL changed?" wants the movement, not a list of every
        # facility that moved. Reported as the two totals and the change
        # between them, which is the answer somebody asking that sentence is
        # holding in their head.
        build = _movement(reading, context, text, matches, filters, dimension,
                          catalogue, period=period)
    elif shape in (COHORT, MOVEMENT):
        build = _two_period(reading, context, text, matches, filters,
                            conditions, shape, period=period,
                            population=continuation if carrying else None)
    else:
        build = _single_period(
            reading, context, text, matches, filters, dimension, shape,
            catalogue,
            population=continuation if carrying else None,
            count_grain=count_grain, inherited_top_n=inherited_top_n,
            inherited_count_of=(str((state.ir.get("meta") or {}).get("count_of")
                                    or "") if carrying else ""),
            fallback_dataset=_fallback_dataset(state if carrying else None),
            preferred_datasets=list(state.datasets) if carrying else None)

    if carried_concepts:
        build.carried_concepts = carried_concepts
    if continuation is not None:
        build.continuation = continuation
    return build


def _fallback_dataset(state: cv.ConversationState | None) -> str:
    """Where to read from when no measure named a dataset.

    Only reachable for a population count — "how many customers are in Stage
    2?" names a filter and a grain but no governed measure at all. The
    conversation's own source is preferred over the default book, so a count
    that follows a rating question is counted in the rating population.
    """
    if state is not None and state.datasets:
        return state.datasets[0]
    return multi.DEFAULT_BASE


def _replaces(text: str) -> bool:
    """Whether the sentence swaps one measure for another rather than adding."""
    import re

    return re.search(r"\breplace\b|\binstead of\b|\brather than\b",
                     (text or "").lower()) is not None


def _restore_conditions(saved: list[dict[str, Any]],
                        matches: list[cx.ConceptMatch]) -> list[Condition]:
    """The previous turn's movement conditions, rebuilt.

    Only the ones whose field is still being read. A condition on a measure the
    new plan does not carry cannot be evaluated, and keeping it would fail the
    validator rather than narrow the answer.
    """
    fields = {m.field for m in matches}
    out: list[Condition] = []
    for raw in saved:
        field_name = str(raw.get("field") or "")
        if field_name not in fields:
            continue
        out.append(Condition(
            field=field_name, kind=str(raw.get("kind") or "change_abs"),
            op=str(raw.get("op") or "gt"), value=raw.get("value", 0),
            phrase=str(raw.get("phrase") or ""),
            higher_is_worse=bool(raw.get("higher_is_worse", True))))
    return out


def _count_subject(text: str) -> str:
    """What the question asked to count — "number of customers" → customer."""
    import re

    lowered = (text or "").lower()
    if re.search(r"\b(?:customers?|borrowers?|obligors?|clients?|names?)\b",
                 lowered):
        return "customer"
    if re.search(r"\b(?:facilities|facility|accounts?|loans?)\b", lowered):
        return "facility"
    return ""


def _wants_count(text: str, reading: Reading) -> bool:
    """Whether the answer is a count of the population rather than a measure.

    "How many customers are in Stage 2?" and "replace EAD with number of
    customers" both want a distinct count at the grain. That is not a governed
    concept and cannot come out of the concept resolver, so it is recognised
    here — as a shape of request, not as a phrase-to-analysis rule.
    """
    import re

    lowered = (text or "").lower()
    if re.search(r"\bnumber of (?:customers?|borrowers?|names?|obligors?|"
                 r"clients?|facilities|accounts?)\b", lowered):
        return True
    if re.search(r"\bhow many (?:customers?|borrowers?|names?|obligors?|"
                 r"clients?|facilities|accounts?)\b", lowered):
        return True
    return re.search(r"\bcount of\b", lowered) is not None or (
        reading.operation == "count"
        and re.search(r"\bcustomers?\b|\bborrowers?\b|\bfacilities\b",
                      lowered) is not None)


def _inherit_filters(filters: list[tuple[str, str]],
                     state: cv.ConversationState, context: GovernedContext,
                     continuation: cv.Continuation | None
                     ) -> list[tuple[str, str]]:
    """Carry the conversation's filters, letting this turn override per field.

    Per field rather than wholesale: "only show Contracting" replaces the sector
    the thread had settled, and does not also drop the stage restriction that
    was never mentioned.
    """
    named = {field_name for field_name, _ in filters}
    out = list(filters)
    carried: list[str] = []
    for field_name, value in state.filter_pairs():
        if field_name in named:
            continue
        if field_name in context.dimensions and value in context.dimensions[field_name]:
            out.append((field_name, value))
            carried.append(f"{field_name} = {value}")
    if carried and continuation is not None:
        continuation.inherited["filters"] = ", ".join(carried)
    return out


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
        # "The five largest sectors" is a grouped total that has been cut to
        # five, not a ranking of five rows at the record grain. Keeping it an
        # AGGREGATE is what makes the cut a modification of the answer already
        # on screen rather than a different analysis.
        return AGGREGATE if dimension else RANKING
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


def _without_values(text: str, filters: list[tuple[str, str]]) -> str:
    """The question with its governed filter values blanked out."""
    import re

    out = text or ""
    for _, value in filters:
        if len(value) < 4:
            continue
        out = re.sub(rf"\b{re.escape(value)}\b", " ", out, flags=re.I)
    return out


def _conditions(text: str, matches: list[cx.ConceptMatch]) -> list[Condition]:
    """One condition per concept the question attached a test to.

    Two kinds of test, and the difference is not cosmetic. A **movement** asks
    how the measure changed between two periods; a **threshold** asks which
    side of a line it is on right now. "Covenant headroom below 15%" is the
    second, and reading it as the first returned borrowers at 16.17% headroom
    under a heading promising below 15% — a contradiction visible in the
    answer's own table.
    """
    out: list[Condition] = []
    for match in matches:
        movement = sm.movement_near(text, match.phrase)
        condition = sm.condition_for(match, movement)
        if condition is not None:
            out.append(condition)
            continue
        # No movement on this concept. A level test attached to it still is a
        # condition, and one the user can check by eye.
        level = sm.threshold_condition(
            match, sm.threshold_near(text, match.phrase))
        if level is not None:
            out.append(level)
    return out


def _dimension(reading: Reading, context: GovernedContext, text: str) -> str:
    if reading.dimensions:
        first = reading.dimensions[0]
        if first in context.dimensions:
            return first
    import re

    lowered = text.lower()
    for name in context.dimensions:
        # Both spellings. A governed dimension is `ifrs9_stage`; a person
        # writes "by IFRS 9 stage", and matching only the underscored form
        # meant "total EAD by IFRS 9 stage" grouped by nothing and reported
        # the number of distinct stages.
        for spelling in {name, name.replace("_", " "),
                         _re.sub(r"(\d)", r" \1 ", name.replace("_", " "))}:
            written = _re.escape(spelling).replace(r"\ ", r"\s*")
            if _re.search(rf"\bby {written}\b|\bper {written}\b"
                          rf"|\bfor (?:each|every) {written}\b"
                          rf"|\b(?:grouped|broken down) by {written}\b"
                          rf"|\bacross {written}s?\b|\b{written} "
                          rf"(?:breakdown|split|distribution)\b", lowered):
                return name
    # The dimension named as the thing being ranked: "the five largest SECTORS".
    # Without this the plural noun is read as a grain and the answer comes back
    # as five facilities, which is a different question with a similar shape.
    for name in context.dimensions:
        readable = re.escape(name.replace("_", " "))
        if re.search(rf"\b(?:largest|biggest|smallest|top|bottom|worst|best|"
                     rf"first|\d+)\s+(?:\w+\s+){{0,2}}{readable}s?\b", lowered):
            return name
    return _grouping_concept(lowered)


#: "for each X" / "by X" / "per X", where X is what the answer breaks down by.
_GROUPED_BY = _re.compile(
    r"\b(?:for each|for every|by|per|across|grouped by|broken down by)\s+"
    r"(?P<phrase>[a-z][a-z ]{2,30}?)\s*(?:,|\.|;|\?|$|\band\b|\bshow\b|"
    r"\bwith\b|\bin the\b)")


def _grouping_concept(lowered: str) -> str:
    """A governed CONCEPT used as the breakdown, where no dimension fits.

    "For each rating grade, show average ECL coverage…" groups by a field, not
    by one of the small governed dimensions a filter uses. The rating grade is
    an ordinal scale with ten values and it is exactly what the answer should
    have one row per; without this the plan grouped by nothing and returned a
    single row of nulls under a heading promising a breakdown.

    Restricted to ordinal and categorical concepts on purpose. Grouping by a
    continuous money measure produces one row per distinct amount, which is not
    a breakdown — it is the raw table with extra steps.
    """
    from backend.semantics import ontology

    match = _GROUPED_BY.search(lowered)
    if match is None:
        return ""
    phrase = match.group("phrase").strip()

    for concept in cx.CONCEPTS:
        if not _re.search(concept.pattern, phrase):
            continue
        contract = ontology.contract(concept.id)
        if contract is None or not (contract.is_ordinal or contract.is_categorical):
            continue
        return concept.default_candidate().field
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
    if match.concept.id == COUNT_CONCEPT:
        return "count_distinct"
    if match.concept.is_ordinal:
        return "max"
    return _ROLLUP.get(match.concept.unit or "", "sum")


#: The grain each identity column implies. The inverse of `_grain_key`.
#: Keys that identify a real counterparty, as opposed to a grouping dimension.
#: A borrower name belongs beside one of these and nowhere else.
_ENTITY_KEYS = frozenset({"customer_id", "borrower_id", "account_id"})

_GRAIN_OF_KEY: dict[str, str] = {"customer_id": "customer",
                                 "account_id": "facility",
                                 "sector": "sector"}


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
    # The LAST period the reading named, not the first. A reading that carries
    # a window — "the latest quarter" resolves to a pair — means its close when
    # only one period is wanted; taking the opening would answer as at the wrong
    # quarter without anything looking wrong.
    for period in reversed(list(reading.periods)):
        if period in available:
            return period
    return available[-1] if available else ""


# ------------------------------------------------------- single-period plans


def _predicates(filters: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Governed filters as IR predicates, with same-field values grouped.

    "Which of these are Stage 2 or Stage 3?" resolves two entities on the same
    dimension. Emitting them as two `=` predicates ANDs them together and
    selects nothing at all — a wrong answer that looks like a correct empty
    one, which is the worst shape a defect can take here.
    """
    grouped: dict[str, list[str]] = {}
    for field_name, value in filters:
        grouped.setdefault(field_name, []).append(value)
    out: list[dict[str, Any]] = []
    for field_name, values in grouped.items():
        if len(values) == 1:
            out.append({"column": field_name, "op": "=", "value": values[0]})
        else:
            out.append({"column": field_name, "op": "in", "values": values})
    return out


def _filter_label(filters: list[tuple[str, str]]) -> str:
    grouped: dict[str, list[str]] = {}
    for field_name, value in filters:
        grouped.setdefault(field_name, []).append(value)
    parts = []
    for field_name, values in grouped.items():
        readable = field_name.replace("_", " ")
        parts.append(f"{readable} " + (values[0] if len(values) == 1
                                       else "in " + ", ".join(values)))
    return ", ".join(parts)


class _JoinShim:
    """The three attributes `multi._join_edge` reads off a request.

    A single-period enrichment is not a cohort request, but the hop it needs —
    scan the far side, roll it up to the key, join it on the governed
    relationship — is exactly the same hop. Reusing that builder rather than
    writing a second one keeps grain reconciliation in one place; two
    implementations of "do not multiply the book" is how one of them ends up
    wrong.
    """

    def __init__(self, base: str, grain: str, key: str) -> None:
        self.base = base
        self.grain = grain
        self.key = key
        self.filters: list[tuple[str, str]] = []


@dataclass
class _Enrichment:
    """The governed hops that will bring other datasets onto the base frame.

    Resolved BEFORE the base is scanned, because the scan has to read the
    columns those hops join on. Building the scan first and discovering the join
    key afterwards is how a plan ends up asking for `account_id` at a step that
    never read it.
    """

    resolution: Any = None
    reachable: dict[str, list[cx.ConceptMatch]] = field(default_factory=dict)
    unreachable: list[str] = field(default_factory=list)
    #: Columns the base frame must carry for the hops to work.
    left_keys: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.resolution is not None and self.reachable)


def _resolve_enrichment(base: str,
                        extras: dict[str, list[cx.ConceptMatch]]
                        ) -> _Enrichment:
    """Which of the other datasets can be reached over a declared relationship.

    A dataset with no governed path to the base is NOT joined on a guessed key —
    it is dropped, and the answer says which measure could not be brought in and
    why. A join CreditProbe invented would produce a number nobody could
    reconcile.
    """
    from backend.orchestration.context import relationship_rows
    from backend.runtime.joins import build_graph, resolve

    if not extras:
        return _Enrichment()

    rows = relationship_rows()
    if not rows:
        return _Enrichment(unreachable=sorted(extras))

    resolution = resolve(build_graph(rows), base=base, targets=sorted(extras))
    # A path whose first hop joins on a column the base does not carry cannot
    # start. That happens when the base was chosen for the population rather
    # than for its joins, and it is better caught here — where the measure is
    # reported as unreachable — than at validation, where the whole answer is
    # lost to a message about a missing column.
    from backend.data_access import get_catalog

    try:
        base_fields = set(get_catalog().dataset(base).fields)
    except Exception:  # noqa: BLE001
        base_fields = set()
    usable = [p for p in resolution.paths
              if not base_fields or not p.edges
              or p.edges[0].left_field in base_fields]
    resolution.paths = usable
    reached = {p.target for p in resolution.paths}
    return _Enrichment(
        resolution=resolution,
        reachable={n: m for n, m in extras.items() if n in reached},
        unreachable=sorted(n for n in extras if n not in reached),
        left_keys=sorted({e.left_field for p in resolution.paths
                          for e in p.edges}),
    )


class _JoinShim:
    """The three attributes `multi._join_edge` reads off a request.

    A single-period enrichment is not a cohort request, but the hop it needs —
    scan the far side, roll it up to the key, join it on the governed
    relationship — is exactly the same hop. Reusing that builder rather than
    writing a second one keeps grain reconciliation in one place; two
    implementations of "do not multiply the book" is how one of them ends up
    wrong.
    """

    def __init__(self, base: str, grain: str, key: str) -> None:
        self.base = base
        self.grain = grain
        self.key = key
        self.filters: list[tuple[str, str]] = []


def _apply_enrichment(operations: list[dict[str, Any]], current: str, *,
                      enrichment: _Enrichment, base: str, period: str,
                      grain: str, key: str, catalogue: Any,
                      fields_of: dict[str, set[str]],
                      warnings: list[str]
                      ) -> tuple[str, dict[tuple[str, str], str],
                                 list[dict[str, Any]]]:
    """Add the resolved hops to the plan, in path order."""
    if not enrichment.active:
        return current, {}, []

    import dataclasses

    shim = _JoinShim(base, grain, key)
    columns: dict[tuple[str, str], str] = {}
    joins: list[dict[str, Any]] = []
    for index, path in enumerate(enrichment.resolution.paths):
        # What each column is actually called at this point in the plan. A hop
        # prefixes everything it brings, so the second hop of a two-hop path
        # joins on `portfolio_facility_account_id` rather than `account_id`.
        renamed: dict[str, str] = {}
        edges = list(path.edges)
        for position, edge in enumerate(edges):
            following = edges[position + 1:]
            carry = tuple({e.left_field for e in following})
            left = renamed.get(edge.left_field, edge.left_field)
            hop = (edge if left == edge.left_field
                   else dataclasses.replace(edge, left_field=left))
            current, brought = multi._join_edge(
                operations, joins, warnings, current, hop,
                label=f"enrich{index}", period=period, request=shim,
                catalogue=catalogue, fields_of=fields_of,
                by_dataset=enrichment.reachable, carry=carry)
            for (dataset, column), actual in brought.items():
                del dataset
                if column in carry:
                    renamed[column] = actual
            columns.update(brought)
    return current, columns, joins


def _single_period(reading: Reading, context: GovernedContext, text: str,
                   matches: list[cx.ConceptMatch],
                   filters: list[tuple[str, str]], dimension: str,
                   shape: str, catalogue: Any, *,
                   population: cv.Continuation | None = None,
                   count_grain: bool = False,
                   inherited_top_n: int = 0,
                   inherited_count_of: str = "",
                   fallback_dataset: str = "",
                   preferred_datasets: list[str] | None = None) -> AnalysisBuild:
    """AGGREGATE and RANKING: read one period, scope it, group, order, cut.

    Three things this does that the phrase-matching planner could not.

    **Scope to a population.** When the conversation carries identities — the
    five customers the previous turn returned — the plan filters to exactly
    those ids rather than re-deriving "the five largest", which could quietly
    come back as a different five.

    **Reach across datasets.** A measure that lives somewhere else is joined in
    over a declared relationship, so "add their latest internal rating" is one
    table rather than two answers.

    **Count a population.** "Replace EAD with number of customers" wants a
    distinct count at the grain, which is not a governed measure and is
    therefore not something a concept resolver can produce.
    """
    by_dataset: dict[str, list[cx.ConceptMatch]] = {}
    for match in matches:
        by_dataset.setdefault(match.dataset, []).append(match)

    fields_of = {d.name: set(d.fields) for d in catalogue.all()}
    base = (_base_dataset(by_dataset, fields_of, filters, dimension, population,
                          preferred=preferred_datasets,
                          period=_asked_period(reading, context))
            or fallback_dataset)
    if not base:
        raise CannotPlan(
            "No governed dataset carries the figures this asks for.",
            clarification=(
                "CreditProbe could not find a governed source for that. Name "
                "the measure or the dataset you mean."))
    available = fields_of.get(base, set())

    period = _period_for(reading, context, base)
    if not period:
        raise CannotPlan(f"{base} has no published periods to read.")

    grain = _grain(reading, text, base)
    if population and population.has_population:
        # A follow-up about five customers is answered per customer, whatever
        # grain the dataset it happens to be read from is keyed on. Without
        # this, "which of these are Stage 2?" comes back one row per facility
        # and the five names the question was about are no longer visible.
        carried_grain = _GRAIN_OF_KEY.get(population.entity_key, "")
        if carried_grain:
            grain = carried_grain
    key = _grain_key(grain)
    if key not in available:
        # The dataset cannot be reported at that grain. Fall back to whatever
        # it IS keyed on rather than inventing a column.
        key = next((k for k in ("customer_id", "account_id")
                    if k in available), "")

    # What a count would count, decided before the scan is built so the column
    # can be read. "Number of CUSTOMERS by sector" counts customer_id while
    # grouping by sector; reusing the group key instead gives a column of ones.
    counted, count_key = "", ""
    if count_grain:
        counted = _count_subject(text) or inherited_count_of or grain
        count_key = _grain_key(counted)
        if count_key not in available:
            counted, count_key = grain, key

    warnings: list[str] = []
    filter_fields = [f for f, _ in filters if f in available]
    dropped = sorted({f for f, _ in filters if f not in available})
    if dropped:
        # A filter that cannot be applied is not a caveat, it is a different
        # question. "Total ECL for Watch customers" dropped the rating bucket
        # and returned the ECL of the entire book — every figure correct, the
        # population wrong, and nothing in the headline to say so. The warning
        # under the table was read by nobody, which is the point.
        #
        # So CreditProbe stops. An abstention is a slower conversation; the
        # alternative is a number in a credit paper that answers a question
        # nobody asked.
        wanted = ", ".join(v for f, v in filters if f in dropped) or \
            ", ".join(d.replace("_", " ") for d in dropped)
        raise CannotPlan(
            f"{base} does not carry {', '.join(dropped)}.",
            clarification=(
                f"CreditProbe cannot restrict this answer to {wanted}: the "
                f"governed data behind it ({base}) does not carry "
                f"{', '.join(d.replace('_', ' ') for d in dropped)}, and no "
                "active relationship brings it in. Ask for the figure without "
                "that restriction, or ask a data steward to relate the two "
                "datasets in Data Builder."))

    # A breakdown the base does not carry may still be reachable. "For each
    # rating grade, show average ECL coverage" is anchored on the impairment
    # run — it has the quarter the question asked for — and the grade is one
    # governed hop away. Dropping the breakdown produced a single row of
    # portfolio totals under a heading promising one row per grade.
    deferred_dimension = ""
    if dimension and dimension not in available:
        carried_by = next((n for n, fields in fields_of.items()
                           if n != base and dimension in fields), "")
        if carried_by:
            deferred_dimension, dimension = dimension, ""
        else:
            warnings.append(
                f"{base} does not carry {dimension}, so the answer is not "
                "broken down by it.")
            dimension = ""

    # A concept used as the BREAKDOWN is not also a measure. "For each rating
    # grade, show average leverage" names the rating twice — once as the thing
    # to group by and once as a concept the reader recognised — and averaging
    # the grade beside the grades it is grouped by is meaningless arithmetic
    # printed in a column nobody asked for.
    base_measures = [m for m in by_dataset.get(base, [])
                     if m.field in available and m.field != dimension]
    extras = {name: [m for m in found if m.field in fields_of.get(name, set())
                     and m.field != deferred_dimension]
              for name, found in by_dataset.items() if name != base}
    extras = {name: found for name, found in extras.items() if found}
    if deferred_dimension:
        # The breakdown column has to be scanned by the hop that brings it,
        # even though it is not a measure. Registered here so the enrichment
        # resolves a path to its dataset.
        for name, fields in fields_of.items():
            if name != base and deferred_dimension in fields:
                for match in by_dataset.get(name, []):
                    if match.field == deferred_dimension:
                        extras.setdefault(name, []).append(match)
                break
    enrichment = _resolve_enrichment(base, extras)
    for name in enrichment.unreachable:
        labels = ", ".join(m.concept.label for m in extras[name])
        warnings.append(
            f"{labels} could not be brought in: no active relationship "
            f"connects {name} to {base}. A data steward can declare one in "
            "Data Builder.")

    if not base_measures and not extras and not count_grain:
        raise CannotPlan(f"{base} does not carry the measures named.")

    scoped = bool(population and population.has_population
                  and population.entity_key in available)
    if population and population.has_population and not scoped:
        warnings.append(
            f"The previous result is keyed by {population.entity_key}, which "
            f"{base} does not carry, so this answer covers the whole "
            "population rather than only those rows.")

    wanted_fields = {key, *filter_fields, *([dimension] if dimension else []),
                     *([population.entity_key] if scoped else []),
                     *([count_key] if count_key else []),
                     *[m.field for m in base_measures]}
    if enrichment.active:
        # Two things a plain single-dataset plan does not need. The columns the
        # hops join on — omit one and the join asks for a key the step never
        # read — and the period column, because an as-of hop aligns the
        # reporting period onto the far side's latest completed cycle and has to
        # read the period it is aligning from.
        wanted_fields.update(enrichment.left_keys)
        wanted_fields.add(_period_field(catalogue, base))
    read_fields = sorted(f for f in wanted_fields if f in available)
    operations: list[dict[str, Any]] = [{
        "id": "source", "op": "SCAN",
        "params": {"dataset": base, "period": period, "fields": read_fields,
                   "alias": f"{base}@{period}"},
        "label": f"Read {base} at {period}",
    }]
    current = "source"

    if scoped:
        assert population is not None
        operations.append({
            "id": "population", "op": "FILTER", "inputs": [current],
            "params": {"where": [{"column": population.entity_key, "op": "in",
                                  "values": list(population.entity_ids)}]},
            "label": (f"Restrict to the {len(population.entity_ids)} "
                      f"{population.entity_key} the previous answer returned"),
        })
        current = "population"

    if filters:
        operations.append({
            "id": "scoped", "op": "FILTER", "inputs": [current],
            "params": {"where": _predicates(filters)},
            "label": "Restrict to " + _filter_label(filters),
        })
        current = "scoped"

    current, joined_columns, joins = _apply_enrichment(
        operations, current, enrichment=enrichment, base=base, period=period,
        grain=grain, key=key, catalogue=catalogue, fields_of=fields_of,
        warnings=warnings)

    # Where each measure ends up living once the joins have run.
    if deferred_dimension:
        moved = next((column for (_, field), column in joined_columns.items()
                      if field == deferred_dimension), "")
        if moved:
            dimension = moved
        else:
            warnings.append(
                f"{deferred_dimension} could not be brought in, so the answer "
                "is not broken down by it.")

    measures: list[tuple[str, cx.ConceptMatch]] = [
        (m.field, m) for m in base_measures]
    for name, found in enrichment.reachable.items():
        for match in found:
            column = joined_columns.get((name, match.field), match.field)
            if column == dimension:
                continue
            measures.append((column, match))

    if not measures and not count_grain:
        raise CannotPlan(
            "None of the measures named could be read at this grain.",
            clarification=(
                "CreditProbe could not bring the figures this asks for onto one "
                "table. Name one measure and it will compose the analysis."))

    if scoped and not dimension and key:
        # A follow-up about a named population is answered one row per member.
        # Rolling it into a single total answers "what do these five come to?"
        # when the question was "what are these five?".
        group_by = [key]
        label = f"One row per {grain} in the carried population"
    elif shape == AGGREGATE and dimension:
        group_by = [dimension]
        label = f"Total by {dimension}"
    elif shape == RANKING:
        group_by = ([key] if key else []) + ([dimension] if dimension else [])
        label = f"Aggregate to one row per {grain}"
    else:
        group_by = [dimension] if dimension else []
        label = "Aggregate across the population"

    count_column = ""
    if count_key:
        count_column = f"{counted}_count"
        measures.insert(0, (count_column, _count_match(
            base, count_column, count_key, counted, f"number of {counted}s")))

    aggregates = [
        {"function": _rollup_for(m),
         "column": (m.candidate.definition.split()[-1]
                    if m.concept.id == COUNT_CONCEPT else column),
         "as": column}
        for column, m in measures]
    # The readable name belongs on a row that IS a borrower. Carrying it onto a
    # row that is a sector picks one name arbitrarily out of hundreds, which
    # looks like a finding and is not one.
    #
    # The guard used to be "the key is in the grouping", which is true of a
    # ranking OF SECTORS too — `key` is then `sector`. So a five-row sector
    # ranking carried a Borrower column naming one arbitrary company per
    # sector, in a table where the borrower means nothing at all.
    if key in _ENTITY_KEYS and key in group_by and "borrower_name" in available:
        aggregates.append({"function": "any_value", "column": "borrower_name",
                           "as": "borrower_name"})
        if "borrower_name" not in read_fields:
            operations[0]["params"]["fields"] = sorted(
                set(read_fields) | {"borrower_name"})

    # A filter the result cannot show is a filter nothing can check. "The five
    # largest Real Estate customers" filtered on sector and then aggregated the
    # sector away, so the invariant that tests the heading against the rows was
    # skipped for want of a column — on exactly the claim it exists to prove.
    #
    # `any_value` is exact here rather than arbitrary: every row inside the
    # group satisfied the equality before the aggregation ran, so they all
    # carry the same value.
    carried = {a["as"] for a in aggregates} | set(group_by)
    for field_name in filter_fields:
        if field_name not in carried and field_name in available:
            aggregates.append({"function": "any_value", "column": field_name,
                               "as": field_name})
            carried.add(field_name)

    if group_by:
        operations.append({
            "id": "grouped", "op": "GROUP", "inputs": [current],
            "params": {"by": group_by, "aggregates": aggregates},
            "label": label,
        })
    else:
        operations.append({
            "id": "grouped", "op": "AGGREGATE", "inputs": [current],
            "params": {"aggregates": aggregates},
            "label": "Total across the population",
        })
    current = "grouped"

    order_column, ordered_by = _order_by(measures, count_column, text)
    descending = _descending(ordered_by, text) if ordered_by else True

    # A share, computed against the population the question actually asked
    # about. "The five largest Real Estate customers" wants each one's share of
    # REAL ESTATE exposure; dividing by the whole book instead answers a
    # different question, and reporting the filtered population's share of
    # itself as 100% — which is what a concentration analysis run on a filtered
    # book does — answers no question at all.
    #
    # The window runs BEFORE the cut, so "each one's percentage of total
    # portfolio EAD" after "show only the five largest" still divides by all
    # fifteen sectors rather than by the five on screen.
    share_of = ""
    wants_share = (shape == RANKING or (shape == AGGREGATE and dimension))
    rollup = ("sum" if order_column == count_column
              else (_ROLLUP.get(ordered_by.concept.unit or "") if ordered_by
                    else ""))
    if wants_share and order_column and rollup == "sum" and not count_grain:
        share_of = f"{order_column}_share_pct"
        operations.append({
            "id": "denominator", "op": "WINDOW", "inputs": [current],
            "params": {"function": "sum", "column": order_column,
                       "as": f"{order_column}_population"},
            "label": ("Total " + (ordered_by.concept.label if ordered_by
                                  else "count")
                      + (" across " + _filter_label(filters) if filters
                         else " across the population")),
        })
        operations.append({
            "id": "shared", "op": "RATIO", "inputs": ["denominator"],
            "params": {"numerator": order_column,
                       "denominator": f"{order_column}_population",
                       "as": share_of, "as_percent": True},
            "label": (f"Each {dimension or grain}'s share of that total — not "
                      "of the whole book, which the question did not ask about"),
        })
        current = "shared"

    if order_column:
        operations.append({
            "id": "ranked", "op": "SORT", "inputs": [current],
            "params": {"by": [{"column": order_column,
                               "direction": "desc" if descending else "asc"}]},
            "label": ("Order by "
                      + (ordered_by.concept.label if ordered_by
                         else f"number of {grain}s")
                      + (", largest first" if descending else ", smallest first")),
        })
        current = "ranked"

    # A grouped aggregate is cut too when the question asked for a number of
    # groups, or when the conversation had already cut it and this turn did not
    # widen it again. Without the second half, "now show each one's share"
    # silently puts the other ten sectors back on screen.
    stated = _explicit_top_n(text)
    top_n = 0
    if shape == RANKING:
        top_n = stated or inherited_top_n or DEFAULT_TOP_N
    elif stated or inherited_top_n:
        top_n = stated or inherited_top_n
    if top_n:
        operations.append({
            "id": "result", "op": "LIMIT", "inputs": [current],
            "params": {"n": top_n},
            "label": (f"The {top_n} the question asked for" if stated else
                      f"The {top_n} this investigation was already looking at"),
        })

    used = [m for _, m in measures]
    summary = _summary(shape, used, filters, dimension, period, grain, top_n)
    if scoped and population is not None:
        summary += (f", restricted to the {len(population.entity_ids)} "
                    f"{population.entity_key} carried forward from the "
                    "previous answer")
    datasets = [base, *enrichment.reachable]
    plan_doc = {
        "id": f"dynamic_{shape}",
        "operations": operations,
        "meta": {
            "kind": f"dynamic_{shape}", "grain": grain, "period": period,
            "dataset": base, "datasets": datasets,
            "dimension": dimension, "top_n": top_n,
            "share_column": share_of,
            "share_of": _filter_label(filters) or "the population",
            "concepts": [m.to_dict() for m in used],
            "filters": [{"field": f, "value": v} for f, v in filters],
            "conditions": [],
            "count_column": count_column,
            # What was counted, so a follow-up that adds a breakdown keeps
            # counting the same thing. "Break that down by sector" after a
            # customer count must not start counting facilities.
            "count_of": counted,
            "population": ({"key": population.entity_key,
                            "count": len(population.entity_ids)}
                           if scoped and population else None),
            "join_path": joins,
            "explanation": summary,
        },
    }
    return AnalysisBuild(
        plan=plan_doc, shape=shape, reading=reading, matches=used,
        conditions=[], filters=filters, dataset=base, grain=grain,
        period=period, dimension=dimension, top_n=top_n, warnings=warnings,
        summary=summary, joins=joins,
    )


def _period_field(catalogue: Any, dataset: str) -> str:
    try:
        return str(catalogue.dataset(dataset).period_field or "period")
    except Exception:  # noqa: BLE001
        return "period"


def _base_dataset(by_dataset: dict[str, list[cx.ConceptMatch]],
                  fields_of: dict[str, set[str]],
                  filters: list[tuple[str, str]], dimension: str,
                  population: cv.Continuation | None,
                  preferred: list[str] | None = None,
                  period: str = "") -> str:
    """Which dataset the frame is built from.

    The one that can express the question's scope, preferred over the one that
    happens to carry the first measure. A ranking of Real Estate customers has
    to start from a source carrying `sector`, or the filter has to be dropped
    and the answer silently covers the whole book.

    `period` is the reporting period the question asked about, and it is the
    first thing checked. Datasets do not share a calendar: an annual rating
    history cannot be the base for a question about the latest quarter, and
    building from it forced an as-of chain through two hops that lost every row.
    """
    wanted = {f for f, _ in filters} | ({dimension} if dimension else set())
    if population and population.has_population:
        wanted.add(population.entity_key)

    # Ties are common — two sources both carry the key and one filter — and the
    # tie-break matters more than the score. The conversation's own source wins,
    # because a follow-up that silently moves to a different book changes what
    # the population means without changing anything the user can see.
    order = list(preferred or [])
    calendar = _publishes(period) if period else set()

    def score(name: str) -> tuple[int, int, int, int, int]:
        fields = fields_of.get(name, set())
        return (1 if not calendar or name in calendar else 0,
                len(wanted & fields), len(by_dataset.get(name, [])),
                1 if name in order else 0, -len(fields))

    return max(by_dataset, key=score) if by_dataset else ""


def _publishes(period: str) -> set[str]:
    """Every dataset that has published the given period."""
    try:
        from backend.data_access import get_data_source

        source = get_data_source()
        return {name for name in source.datasets()
                if period in (source.periods(name) or [])}
    except Exception:  # noqa: BLE001
        return set()


def _asked_period(reading: Reading, context: GovernedContext) -> str:
    """The single period this request is about, if it names or implies one."""
    named = [p for p in (reading.periods or ()) if p]
    if named:
        return named[-1]
    return str(getattr(context, "latest_period", "") or "")


def _order_by(measures: list[tuple[str, cx.ConceptMatch]], count_column: str,
              text: str) -> tuple[str, cx.ConceptMatch | None]:
    """Which column the answer is ordered by.

    The measure the question named last wins where it named several, because
    "rank those by ECL" puts the ordering measure at the end of the sentence.
    Falls back to the first, and to the count where counting is all there is.
    """
    if not measures:
        return (count_column, None)
    lowered = (text or "").lower()
    best = measures[0]
    best_at = -1
    for column, match in measures:
        at = lowered.rfind(match.phrase.lower()) if match.phrase else -1
        if at > best_at:
            best, best_at = (column, match), at
    return best


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
        readable = dimension.replace("_", " ")
        cut = f"the {top_n} largest {readable}s" if top_n else readable
        return f"{names} by {cut}{where} at {period}."
    if shape == RANKING:
        return (f"The {top_n} {grain}s with the largest {names}{where} "
                f"at {period}.")
    return f"{names}{where} at {period}."


def _movement(reading: Reading, context: GovernedContext, text: str,
              matches: list[cx.ConceptMatch], filters: list[tuple[str, str]],
              dimension: str, catalogue: Any, *,
              period: tuple[str, str] | None = None) -> AnalysisBuild:
    """How a measure moved between two dates, as two totals and a change.

    One scan across both periods rather than two scans joined: the periods are
    a column, so grouping by it gives both totals from one pass, and there is
    no join to lose rows at.
    """
    dataset = matches[0].dataset
    fields_of = {d.name: set(d.fields) for d in catalogue.all()}
    available = fields_of.get(dataset, set())

    annual_only = all(_is_annual(m.dataset, context) for m in matches)
    if period:
        opening, closing, reason, assumed = period[0], period[1], "", False
    else:
        opening, closing, reason, assumed = _two_periods(
            reading, context, text, annual_only=annual_only)
    if reason:
        raise CannotPlan(reason, clarification=reason)

    summary_of = context.dataset(dataset)
    published = list(summary_of.periods) if summary_of else []
    for name, value in (("opening", opening), ("closing", closing)):
        if published and value not in published:
            raise CannotPlan(
                f"{dataset} has no data for {value}.",
                clarification=(f"{dataset} is published for "
                               f"{published[0]} to {published[-1]}; it has no "
                               f"{name} period at {value}."))

    if "period" not in available:
        raise CannotPlan(f"{dataset} is not reported by period.")

    measures = [m for m in matches if m.dataset == dataset
                and m.field in available]
    if not measures:
        raise CannotPlan(f"{dataset} does not carry the measures named.")

    if dimension and dimension not in available:
        dimension = ""
    filters = [(f, v) for f, v in filters if f in available]

    read_fields = sorted({"period", *[f for f, _ in filters],
                          *([dimension] if dimension else []),
                          *[m.field for m in measures]} & available)
    operations: list[dict[str, Any]] = [{
        "id": "source", "op": "SCAN",
        "params": {"dataset": dataset, "fields": read_fields,
                   "alias": dataset},
        "label": f"Read {dataset}",
    }]
    where = [{"column": "period", "op": "in", "value": [opening, closing]}]
    where += [{"column": f, "op": "=", "value": v} for f, v in filters]
    operations.append({
        "id": "scoped", "op": "FILTER", "inputs": ["source"],
        "params": {"where": where},
        "label": (f"Keep {opening} and {closing}"
                  + (", " + ", ".join(v for _, v in filters) if filters else "")),
    })
    group_by = ["period"] + ([dimension] if dimension else [])
    operations.append({
        "id": "totals", "op": "GROUP", "inputs": ["scoped"],
        "params": {"by": group_by,
                   "aggregates": [{"function": _rollup_for(m),
                                   "column": m.field, "as": m.field}
                                  for m in measures]},
        "label": ("Total at each reporting date"
                  + (f", by {dimension}" if dimension else "")),
    })
    # Not sorted by period: "Q1 2026" sorts before "Q4 2025" as text, and a
    # movement read in the wrong direction is a sign error. The rows are
    # matched to their periods by name where they are read.
    operations.append({
        "id": "result", "op": "SORT", "inputs": ["totals"],
        "params": {"by": [{"column": measures[0].field, "direction": "desc"}]},
        "label": f"Largest {measures[0].concept.label} first",
    })

    label = measures[0].concept.label
    summary = (f"How {label} moved between {opening} and {closing}"
               + (f", by {dimension}" if dimension else "") + ".")
    warnings: list[str] = []
    if assumed:
        warnings.append(
            f"The question did not say over what period to measure the change, "
            f"so CreditProbe compared {opening} with {closing}.")

    plan_doc = {
        "id": "dynamic_movement",
        "operations": operations,
        "meta": {
            "kind": "dynamic_movement", "grain": dimension or "portfolio",
            "opening_period": opening, "closing_period": closing,
            "dataset": dataset, "datasets": [dataset], "dimension": dimension,
            "concepts": [m.to_dict() for m in measures],
            "filters": [{"field": f, "value": v} for f, v in filters],
            "conditions": [], "explanation": summary,
        },
    }
    return AnalysisBuild(
        plan=plan_doc, shape=MOVEMENT, reading=reading, matches=measures,
        conditions=[], filters=filters, dataset=dataset,
        grain=dimension or "portfolio", opening=opening, closing=closing,
        dimension=dimension, warnings=warnings, summary=summary,
    )


# ------------------------------------------------- conditional share of a total


#: A share of a total, asked for in the ways people ask for one.
_SHARE_OF_TOTAL = _re.compile(
    r"\bdivided by (?:the )?total\b|\bas a (?:share|proportion|percentage|%)"
    r"\b|\bshare of (?:the )?total\b|\bproportion of\b|\bratio to total\b"
    r"|\bover (?:the )?total\b|\bpercent(?:age)? of (?:the )?total\b", _re.I)


def wants_conditional_share(text: str) -> bool:
    return bool(_SHARE_OF_TOTAL.search(text or ""))


def _qualifier(text: str, matches: list[cx.ConceptMatch],
               measure: cx.ConceptMatch) -> tuple[str, Any, str] | None:
    """The condition that narrows the numerator — "Stage 2" in Stage 2 EAD.

    Read from a governed concept with a value beside it, so the numerator is a
    field and a value the catalogue recognises rather than a phrase.
    """
    lowered = (text or "").lower()
    for match in matches:
        if match is measure or match.field == measure.field:
            continue
        phrase = match.phrase.lower()
        # The value is usually inside the phrase the concept reader matched —
        # "Stage 2" is one match, not a concept and a number beside it.
        inside = _re.search(r"(\d+(?:\.\d+)?)", phrase)
        found = inside or _re.search(
            rf"{_re.escape(phrase)}\s*(?:=|is|of)?\s*(\d+(?:\.\d+)?)",
            lowered)
        if found is None:
            found = _re.search(
                rf"(\d+(?:\.\d+)?)\s*{_re.escape(phrase)}", lowered)
        if found is None:
            continue
        raw = found.group(1)
        value: Any = float(raw) if "." in raw else int(raw)
        return match.field, value, f"{match.concept.label} {raw}"
    return None


def _conditional_share(reading: Reading, context: GovernedContext, text: str,
                       matches: list[cx.ConceptMatch],
                       filters: list[tuple[str, str]], dimension: str,
                       catalogue: Any, *,
                       period: tuple[str, str] | None) -> AnalysisBuild:
    """A conditional share, per group, compared across two periods.

    "For each sector, Stage 2 EAD divided by total sector EAD, compared with
    four quarters ago, ranked by the largest increase."

    Computed in ONE pass rather than as four queries stitched together. The
    numerator and the denominator have to be taken over the same rows, and
    every extra pass is another chance to filter one side and not the other —
    an error that produces a share nobody can reconcile rather than a failure
    anybody notices.

        opening_qualified = SUM(measure) WHERE period = opening AND qualifier
        opening_total     = SUM(measure) WHERE period = opening
        opening_share     = opening_qualified / opening_total
        ... the same at closing ...
        change_pp         = closing_share - opening_share
    """
    measure = next((m for m in matches if not m.concept.is_ordinal
                    and not m.concept.is_categorical), None)
    if measure is None:
        raise CannotPlan("A share needs a measure to take a share of.")

    qualifier = _qualifier(text, matches, measure)
    if qualifier is None:
        raise CannotPlan("A conditional share needs a condition on the "
                         "numerator.")
    field, value, label = qualifier

    dataset = measure.dataset
    fields_of = {d.name: set(d.fields) for d in catalogue.all()}
    available = fields_of.get(dataset, set())
    if field not in available:
        # The qualifier lives elsewhere. Prefer a dataset that carries both,
        # so the share needs no join and cannot be miscounted by one.
        both = [name for name, fields in fields_of.items()
                if {measure.field, field} <= fields
                and (not dimension or dimension in fields)]
        if not both:
            raise CannotPlan(
                f"No governed dataset carries both {measure.field} and "
                f"{field}, so this share cannot be computed without a join "
                "that would change what it means.")
        dataset = both[0]
        available = fields_of[dataset]

    if period:
        opening, closing, assumed = period[0], period[1], False
    else:
        opening, closing, _why, assumed = _two_periods(reading, context, text)

    if dimension and dimension not in available:
        dimension = ""
    # The qualifier is the NUMERATOR's condition, not the population's. Leaving
    # it in the general filters restricted the denominator too, and every
    # sector came back at exactly 100% — a share that is its own total.
    filters = [(f, v) for f, v in filters if f in available and f != field]

    read_fields = sorted({"period", field, measure.field,
                          *[f for f, _ in filters],
                          *([dimension] if dimension else [])} & available)
    operations: list[dict[str, Any]] = [{
        "id": "source", "op": "SCAN",
        "params": {"dataset": dataset, "fields": read_fields, "alias": dataset},
        "label": f"Read {dataset}",
    }]
    where = [{"column": "period", "op": "in", "value": [opening, closing]}]
    where += [{"column": f, "op": "=", "value": v} for f, v in filters]
    operations.append({
        "id": "scoped", "op": "FILTER", "inputs": ["source"],
        "params": {"where": where},
        "label": f"Keep {opening} and {closing}",
    })

    def conditional(name: str, at: str, qualified: bool) -> dict[str, Any]:
        clauses = [{"column": "period", "op": "=", "value": at}]
        if qualified:
            clauses.append({"column": field, "op": "=", "value": value})
        return {"function": "sum_where", "column": measure.field,
                "as": name, "where": clauses}

    if not dimension:
        raise CannotPlan(
            "A share by group needs a group to break it down by.",
            clarification=("Which breakdown should CreditProbe use for that "
                           "share — sector, region or segment?"))

    operations.append({
        "id": "shares", "op": "GROUP", "inputs": ["scoped"],
        "params": {
            "by": [dimension],
            "aggregates": [
                conditional("opening_qualified", opening, True),
                conditional("opening_total", opening, False),
                conditional("closing_qualified", closing, True),
                conditional("closing_total", closing, False),
            ]},
        "label": (f"{label} and total {measure.concept.label} at each date"
                  + (f", by {dimension}" if dimension else "")),
    })
    def share_of(numerator: str, denominator: str) -> dict[str, Any]:
        """numerator / NULLIF(denominator, 0) * 100, as a governed expression.

        Guarded rather than divided plainly: a sector with no exposure at the
        opening date has no share, and an unguarded division would put a
        division-by-zero error — or an infinity that sorts to the top — in
        front of a credit officer as a finding.
        """
        return {"type": "function", "function": "multiply", "args": [
            {"type": "function", "function": "divide", "args": [
                numerator,
                {"type": "function", "function": "nullif",
                 "args": [denominator, {"type": "literal", "value": 0}]},
            ]},
            {"type": "literal", "value": 100},
        ]}

    operations.append({
        "id": "derived", "op": "DERIVE", "inputs": ["shares"],
        "params": {"columns": [
            {"as": "opening_share_pct",
             "expression": share_of("opening_qualified", "opening_total")},
            {"as": "closing_share_pct",
             "expression": share_of("closing_qualified", "closing_total")},
        ]},
        "label": f"{label} as a percentage of the total, at each date",
    })
    operations.append({
        "id": "change", "op": "DERIVE", "inputs": ["derived"],
        "params": {"columns": [
            {"as": "change_pp",
             "expression": {"type": "function", "function": "subtract",
                            "args": ["closing_share_pct",
                                     "opening_share_pct"]}},
        ]},
        "label": "The change in the share, in percentage points",
    })
    operations.append({
        "id": "result", "op": "SORT", "inputs": ["change"],
        "params": {"by": [{"column": "change_pp", "direction": "desc"}]},
        "label": "Largest increase in the share first",
    })

    summary = (f"{label} as a share of total {measure.concept.label}"
               + (f", by {dimension}" if dimension else "")
               + f", between {opening} and {closing}, ranked by the largest "
               "increase.")
    warnings: list[str] = []
    if assumed:
        warnings.append(
            "The question did not say what to compare against, so CreditProbe "
            f"compared {opening} with {closing}.")

    plan_doc = {
        "id": "dynamic_share_movement",
        "operations": operations,
        "meta": {
            "kind": "dynamic_share_movement",
            "grain": dimension or "portfolio",
            "opening_period": opening, "closing_period": closing,
            "dataset": dataset, "datasets": [dataset], "dimension": dimension,
            "concepts": [measure.to_dict()],
            "numerator": {"field": field, "value": value, "label": label},
            "filters": [{"field": f, "value": v} for f, v in filters],
            "conditions": [], "explanation": summary,
        },
    }
    return AnalysisBuild(
        plan=plan_doc, shape=SHARE_MOVEMENT, reading=reading, matches=[measure],
        conditions=[], filters=filters, dataset=dataset,
        grain=dimension or "portfolio", opening=opening, closing=closing,
        dimension=dimension, warnings=warnings, summary=summary,
    )


# --------------------------------------------------------- two-period plans


def _two_period(reading: Reading, context: GovernedContext, text: str,
                matches: list[cx.ConceptMatch],
                filters: list[tuple[str, str]],
                conditions: list[Condition], shape: str, *,
                period: tuple[str, str] | None = None,
                population: cv.Continuation | None = None) -> AnalysisBuild:
    """Delegate to the multi-dataset builder, driven by the reading.

    The reading has already done the part that used to be a regex: which
    concepts, which governed fields, which movement each one asserts. What is
    built here is the `MultiRequest` that machinery consumes — the joins, the
    grain reconciliation and the as-of alignment are its job, not this one's.
    """
    from backend.data_access import get_catalog
    from backend.runtime.joins import build_graph, resolve

    catalogue = get_catalog()
    if period:
        opening, closing, reason, assumed = period[0], period[1], "", False
    else:
        # Every measure published only once a year? Then the previous cycle is
        # the only comparison there is.
        annual_only = bool(matches) and all(
            _is_annual(m.dataset, context) for m in matches)
        opening, closing, reason, assumed = _two_periods(
            reading, context, text, annual_only=annual_only)
    if reason:
        raise CannotPlan(reason, clarification=reason)

    grain = _grain(reading, text, matches[0].dataset)
    if population and population.has_population:
        grain = _GRAIN_OF_KEY.get(population.entity_key, grain)
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

    scoped = bool(population and population.has_population)
    request = multi.MultiRequest(
        question=text, understood=True, base=base,
        shape=multi.COHORT if shape == COHORT else multi.RANKING,
        grain=grain, key=key, opening=opening, closing=closing,
        reading=cx.Reading(matches=list(matches)),
        bindings=bindings, filters=filters, resolution=resolution,
        population=({"key": population.entity_key,
                     "ids": list(population.entity_ids)}
                    if scoped and population else None),
        summary=_two_period_summary(conditions, filters, opening, closing, grain),
        confidence={"reading": reading.confidence},
    )
    built = multi.build_plan(request, catalogue=catalogue)
    warnings = list(built.warnings)
    if assumed:
        warnings.append(
            f"The question did not name a comparison window, so CreditProbe "
            f"used the governed default — the latest year, {opening} to "
            f"{closing}. Name two periods to measure a different window.")
    if scoped and population is not None:
        warnings.append(
            f"Restricted to the {len(population.entity_ids)} "
            f"{population.entity_key} the previous answer returned.")
    return AnalysisBuild(
        plan=built.plan, shape=shape, reading=reading, matches=list(matches),
        conditions=conditions, filters=filters, grain=grain,
        opening=opening, closing=closing, joins=built.joins,
        warnings=warnings, summary=request.summary, request=request,
    )


def _is_annual(dataset: str, context: GovernedContext) -> bool:
    """Whether this source publishes once a year.

    Read from the published periods rather than assumed from the name: a
    dataset whose periods are bare years has one cycle per year, and one
    sensible comparison.
    """
    summary = context.dataset(dataset)
    if summary is None or not summary.periods:
        return False
    return all(str(p).strip().isdigit() and len(str(p).strip()) == 4
               for p in summary.periods)


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


def _two_periods(reading: Reading, context: GovernedContext, text: str, *,
                 annual_only: bool = False) -> tuple[str, str, str, bool]:
    """Opening and closing, and whether the window had to be assumed.

    The product used to stop and ask whenever a movement question named no
    window. That was the wrong instinct applied too widely: "which customers
    were downgraded over the latest year" names one perfectly clearly, and
    "which customers were downgraded" means the review cycle to everyone who
    asks it. Both came back as a question, and the second one came back as a
    question the user had no reason to expect.

    So: read what the question said, using the full temporal vocabulary; and
    where it said nothing, take the governed default and report that it was
    taken. A window is only refused when the data cannot express one.

    `annual_only` is kept because it still changes the *wording* — a comparison
    of annual measures is a cycle-on-cycle comparison, not a year-on-year one.
    """
    from backend.orchestration import periods as pd

    available = context.periods
    if not available:
        return "", "", "No reporting periods are published.", False
    if len(available) < 2:
        return "", "", ("Only one reporting period is published, so there is "
                        "nothing to compare it with."), False

    named = [p for p in reading.periods if p in available]
    if len(named) >= 2:
        ordered = sorted(named, key=available.index)
        return ordered[0], ordered[-1], "", False

    read = pd.read_period_intent(text, list(available))
    if read.specified and read.from_period and read.to_period \
            and read.from_period != read.to_period:
        return read.from_period, read.to_period, "", False

    if len(named) == 1:
        # One period named: compare it with the same point a year earlier,
        # which is the window a credit review means.
        index = available.index(named[0])
        steps = 1 if annual_only else DEFAULT_HORIZON_QUARTERS
        start = max(0, index - steps)
        if start == index:
            return "", "", (f"{named[0]} is the earliest published period, so "
                            "there is nothing before it to compare."), False
        return available[start], named[0], "", True

    default = pd.governed_default(list(available))
    if not default.specified or not default.from_period or not default.to_period:
        return "", "", default.source, False
    return default.from_period, default.to_period, "", True


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
