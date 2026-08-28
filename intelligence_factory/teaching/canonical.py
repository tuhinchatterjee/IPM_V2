"""
The canonical teaching cases. §13.

    "Add at least 500 canonical complex teaching cases across the families
     above. Do not inflate counts with trivial one-word paraphrases."

What this module is for
-----------------------
Migration (§13's first two bullets) brought 1,166 cases into the schema and
reached thirty-three of the forty-three available families. It could not reach
the other ten, and it left twenty more with a handful of cases each — because
the Phase 0 corpora were built to catch the Phase 0 defects, and the credit
work §7 names (as-of joins, grain reconciliation, roll rates, vintages, risk
appetite, contradictory signals) was not among them.

So this module covers exactly the thirty families migration leaves thin, and
nothing else. A case here exists because a family had no way to demonstrate
its obligation, not because a count needed rounding up.

Written, generated, and the difference
--------------------------------------
Same honest description as the complex corpus, and the same reason. Each
family has ONE reviewed blueprint: the sentence shape, the objectives a
correct answer must settle, the invariants, the contracts, and — most of the
value — the specific way the family's question is usually got wrong. The
blueprint is instantiated over the governed vocabulary: real sectors, real
segments, real measures read from the ontology, real dataset names.

The *specification* is reviewed once. The *subject* is governed. The
*phrasing* is generated. Writing five hundred sentences by hand would produce
five hundred variations on one person's phrasing and one specification copied
five hundred times, and a correction would have to be made five hundred times.

The trap is the case
--------------------
Every blueprint records what the family's question is usually got wrong as a
forbidden behaviour, because a case that only says what a right answer looks
like cannot distinguish a right answer from a plausible substitute. A roll
rate computed as the ratio of two closing snapshots looks exactly like a roll
rate. A vintage curve that re-forms the cohort each period looks exactly like
a vintage curve. Those are the cases.

No production data
------------------
Every borrower, sector, dataset and figure referenced here comes from the
synthetic Saudi universe, and no case carries a value at all: the cases teach
structure, which is §8's rule.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st
from intelligence_factory.teaching import migrate

CANONICAL_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# The governed vocabulary
# ---------------------------------------------------------------------------
# Read from the complex corpus rather than retyped, so a concept that is
# renamed in the ontology breaks both corpora at once instead of leaving this
# one quietly producing cases nothing can satisfy.
from intelligence_factory.complex import (  # noqa: E402 - after the docstring
    ADDITIVE,
    PERIODS,
    RATIOS,
    SECTORS,
    SEGMENTS,
)

#: The governed datasets, by the names the lake actually holds. A case naming
#: a dataset that does not exist teaches the planner to reach for it.
FACILITY = "portfolio_facility"
IFRS9 = "ifrs9_staging"
RATINGS = "customer_ratings"
TRANSITIONS = "rating_transitions"
DELINQUENCY = "facility_delinquency"
PAYMENTS = "payment_history"
FINANCIALS = "borrower_financials"
COVENANTS = "covenant_tests"
COLLATERAL = "collateral_register"
LIMITS = "facility_limits"
APPETITE = "risk_appetite_limits"
WATCHLIST = "watchlist_register"
RECOVERIES = "recoveries"
SCENARIOS = "scenario_definitions"
GROUPS = "group_structure"
PROFITABILITY = "facility_profitability"

#: Retail products and corporate instruments, so the two scope families can
#: speak the vocabulary their scope actually uses.
RETAIL_PRODUCTS: tuple[str, ...] = ("personal loans", "auto finance",
                                    "credit cards", "residential mortgages",
                                    "overdrafts")
CORPORATE_INSTRUMENTS: tuple[str, ...] = ("revolving credit facilities",
                                          "term loans", "letters of credit",
                                          "guarantees",
                                          "project finance facilities")

WINDOWS: tuple[str, ...] = ("over the latest quarter", "over the latest year",
                            "since the start of 2025",
                            "between Q2 2025 and Q2 2026",
                            "over the last two quarters")

BUCKETS: tuple[str, ...] = ("1-29", "30-59", "60-89", "90+")
GRADES: tuple[str, ...] = ("investment grade", "sub-investment grade",
                           "watch grade")
VINTAGES: tuple[str, ...] = ("2021", "2022", "2023", "2024")


def pick(items: tuple[Any, ...], seed: str, offset: int = 0) -> Any:
    """A deterministic choice.

    Hash-based rather than random, for the same reason the complex corpus is:
    a corpus whose cases move between runs produces scores that cannot be
    compared, and adding a family must not reshuffle the families before it.
    """
    digest = hashlib.sha256(f"canonical:{seed}:{offset}".encode()).digest()
    return items[int.from_bytes(digest[:4], "big") % len(items)]


def _other(items: tuple[Any, ...], chosen: Any, seed: str,
           offset: int = 0) -> Any:
    """A second, different choice. A cohort compared with itself is not a
    comparison, and a case that asks for one teaches nothing."""
    second = pick(items, seed, offset)
    if second == chosen:
        index = items.index(chosen)
        second = items[(index + 1) % len(items)]
    return second


# ---------------------------------------------------------------------------
# Building a case
# ---------------------------------------------------------------------------

#: What each difficulty implies about routing. §23's rule holds: these are
#: model ROLES, and configuration decides what serves them.
_ROUTE = {
    sc.FOUNDATIONAL: ("B_ROUTINE", "LOW"),
    sc.INTERMEDIATE: ("B_ROUTINE", "STANDARD"),
    sc.COMPLEX: ("C_COMPLEX", "STANDARD"),
    sc.EXPERT: ("C_COMPLEX", "HIGH"),
    sc.ADVERSARIAL: ("C_COMPLEX", "HIGH"),
}


@dataclass
class Turn:
    """One turn of a canonical thread, before it becomes a §9 turn."""

    message: str
    action: str = "NEW_REQUEST"
    behaviour: str = ""
    result_type: str = "TABLE"
    scope_delta: dict[str, Any] = field(default_factory=dict)
    reading: dict[str, Any] = field(default_factory=dict)
    plan_change: dict[str, Any] = field(default_factory=dict)
    referents: dict[str, Any] = field(default_factory=dict)
    presentation: dict[str, Any] = field(default_factory=dict)
    inherited: dict[str, Any] = field(default_factory=dict)


def build(*, family: str, title: str, turns: list[Turn],
          objectives: tuple[str, ...], difficulty: str, risk: str,
          capability: str = "ANALYSIS", outcome: str = fam.EXECUTE,
          officer: int = 2, **fields: Any) -> sc.TeachingCase:
    """One case, with everything a family's obligation needs already set.

    `fields` carries whatever the blueprint declares on top — concepts,
    datasets, invariants, contracts. Keeping them keyword rather than
    positional means a blueprint reads as a list of statements about the case
    rather than as an argument list nobody can check.
    """
    route, effort = _ROUTE[difficulty]
    case = sc.TeachingCase(
        title=title,
        family_id=family,
        question=turns[0].message,
        conversation_turns=[
            sc.Turn(turn_index=index, user_message=turn.message,
                    conversation_action=turn.action,
                    inherited_context=dict(turn.inherited),
                    scope_delta=dict(turn.scope_delta),
                    expected_reading=dict(turn.reading),
                    expected_plan_change=dict(turn.plan_change),
                    expected_result_type=turn.result_type,
                    expected_referent_resolution=dict(turn.referents),
                    expected_presentation=dict(turn.presentation),
                    expected_answer_behavior=turn.behaviour)
            for index, turn in enumerate(turns)],
        objectives=[sc.Objective(id=f"o{i}", text=text, kind="OBJECTIVE")
                    for i, text in enumerate(objectives)],
        expected_capability=capability,
        expected_conversation_action=turns[0].action,
        expected_outcome=outcome,
        expected_model_route=route,
        expected_effort=effort,
        expected_officer_level=officer,
        difficulty=difficulty,
        risk_level=risk,
        authoring_method=st.HUMAN,
        data_sensitivity=st.PUBLIC,
        ontology_version=migrate.ONTOLOGY_VERSION,
    )
    for name, value in fields.items():
        setattr(case, name, value)
    # Concepts go in the ontology's own vocabulary, so a need expressed in
    # business names matches them — §16's highest-weighted feature.
    case.concepts = [migrate.concept(c) for c in case.concepts]
    return case


def _forbids(*behaviours: str) -> dict[str, Any]:
    """What the family's question is usually got wrong.

    §4 gives no general "forbidden behaviours" field — the three it names are
    about datasets, relationships and tools — so a behavioural refusal goes in
    the scope contract, which is the field that says what a case is and is not
    for.
    """
    return {"forbidden_behaviours": list(behaviours)}


# ---------------------------------------------------------------------------
# The blueprints — metadata families
# ---------------------------------------------------------------------------


def _discovery(seed: str) -> sc.TeachingCase:
    """What data exists, answered without computing over it."""
    subject, dataset = pick((
        ("covenant testing", COVENANTS), ("collateral", COLLATERAL),
        ("delinquency", DELINQUENCY), ("recoveries", RECOVERIES),
        ("rating transitions", TRANSITIONS), ("risk appetite limits", APPETITE),
        ("borrower financials", FINANCIALS), ("payment behaviour", PAYMENTS),
        ("group structures", GROUPS), ("scenario definitions", SCENARIOS),
        ("facility profitability", PROFITABILITY), ("watchlist", WATCHLIST),
    ), seed, 1)
    opening = pick(("What data do you hold about", "Do you have anything on",
                    "What is available on", "Tell me what you have on"),
                   seed, 2)
    return build(
        family="DATA_DISCOVERY", title=f"What {subject} data exists",
        turns=[Turn(f"{opening} {subject}?", result_type="NARRATIVE",
                    behaviour="Must name the governed dataset and what it "
                              "covers. Must not compute anything.")],
        objectives=(f"name the governed datasets holding {subject} data",
                    "say what period range and grain they cover"),
        difficulty=sc.FOUNDATIONAL, risk="LOW", capability="DATA_DISCOVERY",
        officer=1, required_datasets=[dataset],
        analytical_plan_contract={"capability": "DATA_DISCOVERY",
                                  "reads_metadata_only": True},
        result_contract={"shape": "a description of held data"},
        scope_contract=_forbids("ANALYSIS", "inventing a dataset"))


def _dictionary_relationship(seed: str) -> sc.TeachingCase:
    """How two governed datasets join, and at what grain."""
    left, right, how = pick((
        (RATINGS, IFRS9, "borrower"), (FACILITY, IFRS9, "facility"),
        (FACILITY, COLLATERAL, "facility"), (FACILITY, COVENANTS, "borrower"),
        (FACILITY, DELINQUENCY, "facility"), (FINANCIALS, RATINGS, "borrower"),
        (FACILITY, GROUPS, "borrower"), (FACILITY, LIMITS, "facility"),
        (DELINQUENCY, PAYMENTS, "facility"), (IFRS9, SCENARIOS, "scenario"),
        (FACILITY, PROFITABILITY, "facility"), (FACILITY, WATCHLIST,
                                                "borrower"),
        (FACILITY, RECOVERIES, "facility"), (RATINGS, TRANSITIONS, "borrower"),
    ), seed, 1)
    return build(
        family="DATA_RELATIONSHIPS",
        title=f"How {left} reaches {right}",
        turns=[Turn(f"How is {left.replace('_', ' ')} connected to "
                    f"{right.replace('_', ' ')}?", result_type="NARRATIVE",
                    behaviour="Must name the join key and the grain the join "
                              "produces. Must not run the join.")],
        objectives=(f"name the declared relationship between {left} and "
                    f"{right}",
                    f"say that the join is at {how} grain",
                    "say what the join does to row counts"),
        difficulty=sc.INTERMEDIATE, risk="MEDIUM",
        capability="DATA_RELATIONSHIP", officer=1,
        required_datasets=[left, right], grain=how,
        required_relationships=[f"{left}->{right}"],
        analytical_plan_contract={"capability": "DATA_RELATIONSHIP",
                                  "reads_metadata_only": True},
        result_contract={"shape": "a relationship, with its key and grain"},
        scope_contract=_forbids("ANALYSIS", "inventing a join path"))


def _inspection(seed: str) -> sc.TeachingCase:
    """The shape of held data, as a fact about the data."""
    dataset = pick((TRANSITIONS, DELINQUENCY, COVENANTS, COLLATERAL,
                    FINANCIALS, RECOVERIES, PAYMENTS, APPETITE), seed, 1)
    aspect, objective = pick((
        ("how far back it goes", "state the earliest and latest period held"),
        ("how complete it is", "state the proportion of rows with the key "
                               "fields populated"),
        ("how many rows it holds", "state the row count and the grain those "
                                   "rows are at"),
        ("how often it is refreshed", "state the reporting frequency"),
    ), seed, 2)
    return build(
        family="DATA_INSPECTION",
        title=f"{dataset}: {aspect}",
        turns=[Turn(f"For {dataset.replace('_', ' ')}, {aspect}?",
                    result_type="NARRATIVE",
                    behaviour="Must answer about the data itself. Must not "
                              "answer with a portfolio figure.")],
        objectives=(objective,),
        difficulty=sc.FOUNDATIONAL, risk="LOW", capability="DATA_QUALITY",
        officer=1, required_datasets=[dataset],
        analytical_plan_contract={"capability": "DATA_QUALITY",
                                  "reads_metadata_only": True},
        result_contract={"shape": "a statement about coverage or quality"},
        scope_contract=_forbids("ANALYSIS", "answering with a portfolio "
                                            "figure"))


# ---------------------------------------------------------------------------
# The blueprints — calculation families
# ---------------------------------------------------------------------------


def _aggregation(seed: str) -> sc.TeachingCase:
    """One measure, one dimension, one period — with the aggregation the
    concept permits."""
    measure, concept = pick(ADDITIVE, seed, 1)
    dimension = pick(("sector", "segment", "IFRS 9 stage", "rating grade",
                      "region", "product"), seed, 2)
    period = pick(PERIODS, seed, 3)
    return build(
        family="SINGLE_DOMAIN_AGGREGATION",
        title=f"Total {measure} by {dimension}",
        turns=[Turn(f"What is total {measure} by {dimension} in {period}?",
                    behaviour="Must sum a measure that adds up, group by the "
                              "named dimension, and hold the period fixed.")],
        objectives=(f"total {measure} for {period}",
                    f"the same total broken down by {dimension}"),
        difficulty=sc.INTERMEDIATE, risk="LOW", officer=1,
        concepts=[concept], metrics=[measure], dimensions=[dimension],
        required_datasets=[FACILITY, IFRS9],
        operations=["SUM"], grain="facility",
        period_contract={"phrase": period, "basis": "single reporting date"},
        analytical_plan_contract={"measure": concept, "group_by": [dimension],
                                  "operation": "SUM"},
        invariants=["share_bounds", "period_single"],
        scope_contract=_forbids("summing a ratio",
                                "silently widening the period"))


def _filtering(seed: str) -> sc.TeachingCase:
    """A threshold is not a movement, and a filter is not an order."""
    ratio, concept = pick(RATIOS, seed, 1)
    sector = pick(SECTORS, seed, 2)
    limit = pick((10, 15, 20, 25, 30), seed, 3)
    rank_by, rank_concept = pick(ADDITIVE, seed, 4)
    return build(
        family="FILTERING_AND_RANKING",
        title=f"{sector} borrowers below a {ratio} threshold",
        turns=[Turn(f"Which {sector} borrowers have {ratio} below {limit}%? "
                    f"Rank them by {rank_by} and show the top ten.",
                    behaviour="Must read the threshold as a condition on the "
                              "level, not as a movement, and must honour the "
                              "row limit.")],
        objectives=(f"{sector} borrowers whose {ratio} is below the threshold",
                    f"those borrowers ranked by {rank_by}",
                    "the ranking truncated to ten rows"),
        difficulty=sc.COMPLEX, risk="MEDIUM", officer=2,
        concepts=[concept, rank_concept], metrics=[ratio, rank_by],
        filters=[{"field": "sector", "op": "=", "value": sector},
                 {"field": ratio, "op": "<", "value": f"{limit}%"}],
        required_datasets=[FACILITY, FINANCIALS], grain="borrower",
        operations=["FILTER", "RANK"],
        analytical_plan_contract={"filter": ratio, "rank": rank_concept,
                                  "limit": 10},
        invariants=["condition", "filter_equality", "row_limit"],
        scope_contract=_forbids("reading a threshold as a movement",
                                "ignoring the row limit"))


def _objective_coverage(seed: str) -> sc.TeachingCase:
    """Every objective settled, or said not to be. §21."""
    first, concept_a = pick(ADDITIVE, seed, 1)
    second, concept_b = pick(RATIOS, seed, 2)
    sector = pick(SECTORS, seed, 3)
    window = pick(WINDOWS, seed, 4)
    return build(
        family="OBJECTIVE_COVERAGE",
        title=f"Four objectives about {sector}",
        turns=[Turn(f"For {sector}: what is total {first}, how has it moved "
                    f"{window}, which borrowers have the weakest {second}, "
                    f"and what does that tell us about the book?",
                    behaviour="Must report coverage of all four objectives. "
                              "An objective it cannot settle must be reported "
                              "as unavailable, never omitted.")],
        objectives=(f"total {first} for {sector}",
                    f"the movement in {first} {window}",
                    f"the borrowers with the weakest {second}",
                    "an interpretation tying the three together"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=[concept_a, concept_b], metrics=[first, second],
        required_datasets=[FACILITY, IFRS9, FINANCIALS],
        period_contract={"phrase": window, "basis": "two reporting dates"},
        analytical_plan_contract={"objectives": 4, "coverage": "explicit"},
        result_contract={"shape": "an answer with an objective coverage "
                                  "statement"},
        invariants=["objective_coverage_complete"],
        scope_contract=_forbids("partial_objectives",
                                "a silent partial answer"))


def _ambiguity(seed: str) -> sc.TeachingCase:
    """One question that resolves the ambiguity, and no computation."""
    word, readings = pick((
        ("exposure", "drawn balance, exposure at default, or committed "
                     "limit"),
        ("coverage", "ECL coverage, collateral coverage, or interest "
                     "coverage"),
        ("default", "IFRS 9 stage 3, 90+ days past due, or the internal "
                    "default grade"),
        ("PD", "twelve-month PD or lifetime PD"),
        ("the book", "the whole portfolio, the corporate book, or the "
                     "segment last discussed"),
        ("last year", "the last four quarters or the prior calendar year"),
        ("rating", "the internal grade or the external rating"),
        ("utilisation", "against the approved limit or against the committed "
                        "limit"),
    ), seed, 1)
    dimension = pick(("sector", "segment", "rating grade", "region"), seed, 2)
    return build(
        family="AMBIGUITY", title=f"{word} means more than one thing",
        turns=[Turn(f"Show me {word} by {dimension}.",
                    result_type="CLARIFICATION",
                    behaviour="Must ask one question that resolves the "
                              "ambiguity. Must not guess a reading and "
                              "compute it.")],
        objectives=(f"resolve what {word} refers to before computing "
                    "anything",),
        difficulty=sc.EXPERT, risk="HIGH", outcome=fam.CLARIFY, officer=2,
        ambiguities=[word],
        clarification_contract={"ask": f"Do you mean {readings}?",
                                "options": readings,
                                "one_question_only": True},
        scope_contract=_forbids("ANALYSIS", "guessing a reading"))


# ---------------------------------------------------------------------------
# The blueprints — conversation families
# ---------------------------------------------------------------------------


def _multi_turn(seed: str) -> sc.TeachingCase:
    """A population carried across turns, then narrowed, widened or reset."""
    measure, concept = pick(ADDITIVE, seed, 1)
    sector = pick(SECTORS, seed, 2)
    other = _other(SECTORS, sector, seed, 3)
    follow, action, delta, behaviour = pick((
        ("Which of those are in Stage 2 or Stage 3?", "CONTINUE",
         {"narrowed": ["ifrs 9 stage"]},
         "Must filter the population already on screen, not the whole book."),
        (f"Only {other}.", "MODIFY_PREVIOUS", {"replaced": ["sector"]},
         "Must replace the sector filter and keep everything else."),
        ("Now compare all sectors.", "WIDEN_SCOPE", {"widened": ["sector"]},
         "Must drop the sector filter and keep the measure and period."),
        ("Forget those and show the whole portfolio.", "RESET_SCOPE",
         {"reset": ["population"]},
         "Must discard the carried population entirely."),
        ("Same question for the prior year.", "MODIFY_PREVIOUS",
         {"replaced": ["period"]},
         "Must move the period and keep the population definition."),
    ), seed, 4)
    opening = f"Show the ten largest {sector} borrowers by {measure}."
    return build(
        family="MULTI_TURN_REFERENTS",
        title=f"A carried population, then {action.lower().replace('_', ' ')}",
        turns=[
            Turn(opening, "NEW_REQUEST",
                 "Must return ten rows, ranked, filtered to the sector.",
                 reading={"capability": "ANALYSIS", "concepts": [concept]}),
            Turn(follow, action, behaviour,
                 inherited={"population": "the ten borrowers from turn 0",
                            "measure": concept},
                 scope_delta=delta,
                 referents={"those": "the ten borrowers from turn 0"},
                 plan_change={"kind": action.lower()}),
        ],
        objectives=(f"the ten largest {sector} borrowers by {measure}",
                    "the follow-up applied to the right population"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=[concept], metrics=[measure],
        required_datasets=[FACILITY, IFRS9], grain="borrower",
        operations=["RANK", "FILTER"],
        analytical_plan_contract={"rank": concept, "limit": 10},
        invariants=["row_limit", "filter_equality"],
        scope_contract=_forbids("re-running against the whole portfolio",
                                "losing the carried population"))


def _previous_result(seed: str) -> sc.TeachingCase:
    """Answered from the result already on screen, and said so."""
    measure, concept = pick(ADDITIVE, seed, 1)
    dimension = pick(("sector", "segment", "rating grade", "IFRS 9 stage"),
                     seed, 2)
    follow, behaviour = pick((
        ("Which of those is the largest?",
         "Must read the largest row off the result already computed."),
        ("What is the total across all of them?",
         "Must sum the rows already returned, not re-query the lake."),
        ("How many rows did that return?",
         "Must count the result on screen."),
        ("Which two are closest to each other?",
         "Must compare the rows already returned."),
        ("What share of the total does the top one hold?",
         "Must divide within the result already returned."),
    ), seed, 3)
    opening = f"What is total {measure} by {dimension} in the latest quarter?"
    return build(
        family="PREVIOUS_RESULT_REUSE",
        title=f"Reading an answer off a {dimension} breakdown",
        turns=[
            Turn(opening, "NEW_REQUEST",
                 "Must group the measure by the dimension for one period."),
            Turn(follow, "ASSESS_PREVIOUS_RESULT", behaviour,
                 result_type="SCALAR",
                 inherited={"result": "the breakdown from turn 0"},
                 referents={"those": "the rows of the previous result"},
                 plan_change={"kind": "reuse", "recompute": False}),
        ],
        objectives=(f"total {measure} by {dimension}",
                    "the follow-up answered from that result"),
        difficulty=sc.COMPLEX, risk="MEDIUM", officer=2,
        concepts=[concept], metrics=[measure], dimensions=[dimension],
        required_datasets=[FACILITY],
        analytical_plan_contract={"measure": concept,
                                  "group_by": [dimension]},
        result_contract={"shape": "a value read from the previous result, "
                                  "with the reuse stated"},
        invariants=["reuse_declared"],
        scope_contract=_forbids("recomputing what is already on screen",
                                "silently returning a different population"))


def _presentation(seed: str) -> sc.TeachingCase:
    """How a result is shown, changed without changing what was calculated."""
    measure, concept = pick(ADDITIVE, seed, 1)
    dimension = pick(("sector", "segment", "rating grade", "vintage"), seed, 2)
    follow, presentation, behaviour = pick((
        ("Show that as a chart.", {"chart": "bar"},
         "Must chart the result already computed."),
        ("Sort it the other way.", {"sort": "ascending"},
         "Must reorder the same rows."),
        ("Show it as percentages of the total.", {"units": "share"},
         "Must restate the same values as shares; the underlying figures do "
         "not change."),
        ("Just the top five.", {"limit": 5},
         "Must truncate the result already computed, not re-rank the book."),
        ("Put the periods across the top instead.", {"pivot": True},
         "Must transpose the same result."),
    ), seed, 3)
    opening = f"What is total {measure} by {dimension} in the latest quarter?"
    return build(
        family="PRESENTATION_MODIFICATION",
        title=f"{measure} by {dimension}, shown differently",
        turns=[
            Turn(opening, "NEW_REQUEST",
                 "Must group the measure by the dimension."),
            Turn(follow, "MODIFY_PRESENTATION", behaviour,
                 presentation=presentation,
                 inherited={"result": "the breakdown from turn 0"},
                 plan_change={"kind": "presentation", "recompute": False}),
        ],
        objectives=(f"total {measure} by {dimension}",
                    "the same result, presented as asked"),
        difficulty=sc.INTERMEDIATE, risk="LOW", officer=1,
        concepts=[concept], metrics=[measure], dimensions=[dimension],
        required_datasets=[FACILITY],
        analytical_plan_contract={"measure": concept,
                                  "group_by": [dimension]},
        visualization_contract=presentation,
        scope_contract=_forbids("recalculating the result",
                                "changing the population"))


# ---------------------------------------------------------------------------
# The blueprints — structure families
# ---------------------------------------------------------------------------


def _as_of(seed: str) -> sc.TeachingCase:
    """An attribute as it stood then, not as it stands now."""
    attribute, dataset = pick((
        ("internal rating", RATINGS), ("IFRS 9 stage", IFRS9),
        ("sector classification", FACILITY), ("collateral value", COLLATERAL),
        ("approved limit", LIMITS), ("watchlist status", WATCHLIST),
    ), seed, 1)
    period = pick(PERIODS, seed, 2)
    sector = pick(SECTORS, seed, 3)
    return build(
        family="AS_OF_JOIN",
        title=f"{attribute} as it stood in {period}",
        turns=[Turn(f"For {sector} borrowers, what was their {attribute} at "
                    f"the time of the {period} reporting date?",
                    behaviour="Must attach the attribute as it stood at the "
                              "analysis date. Attaching today's value is the "
                              "failure this case exists for.")],
        objectives=(f"the {sector} population as at {period}",
                    f"each borrower's {attribute} as at {period}"),
        difficulty=sc.EXPERT, risk="HIGH", officer=2,
        required_datasets=[FACILITY, dataset], grain="borrower",
        period_contract={"phrase": period, "basis": "as at the analysis date",
                         "as_of": True},
        join_contracts=[{"left": FACILITY, "right": dataset,
                         "kind": "as-of", "on": "borrower and period"}],
        analytical_plan_contract={"join": "as-of", "period": period},
        invariants=["as_of_alignment", "no_future_attribute"],
        scope_contract=_forbids("joining the current attribute",
                                "using an attribute dated after the analysis "
                                "date"))


def _grain(seed: str) -> sc.TeachingCase:
    """Between facility, borrower and portfolio, without double counting."""
    measure, concept = pick(ADDITIVE, seed, 1)
    attribute, dataset = pick((
        ("internal rating", RATINGS), ("group parent", GROUPS),
        ("covenant status", COVENANTS), ("sector", FACILITY),
    ), seed, 2)
    sector = pick(SECTORS, seed, 3)
    return build(
        family="GRAIN_RECONCILIATION",
        title=f"{measure} by borrower, reconciled to the facility total",
        turns=[Turn(f"Show total {measure} by borrower for {sector}, with "
                    f"each borrower's {attribute}, and confirm it ties back "
                    f"to the facility-level total.",
                    behaviour="Must aggregate to borrower grain before "
                              "attaching the borrower attribute. Attaching "
                              "first multiplies the facility rows.")],
        objectives=(f"{measure} aggregated to borrower grain",
                    f"each borrower's {attribute} attached once",
                    "a reconciliation back to the facility-level total"),
        difficulty=sc.EXPERT, risk="CRITICAL", officer=3,
        concepts=[concept], metrics=[measure],
        required_datasets=[FACILITY, dataset],
        grain="borrower",
        population_contract={"from": "facility", "to": "borrower",
                             "aggregate_before_join": True},
        join_contracts=[{"left": FACILITY, "right": dataset,
                         "kind": "one-to-one after aggregation"}],
        analytical_plan_contract={"aggregate_then_join": True},
        invariants=["totals_tie", "no_double_counting"],
        result_contract={"shape": "a borrower table with a reconciliation "
                                  "line"},
        scope_contract=_forbids("joining before aggregating",
                                "double counting a borrower's facilities"))


# ---------------------------------------------------------------------------
# The blueprints — migration families
# ---------------------------------------------------------------------------


def _rating_migration(seed: str) -> sc.TeachingCase:
    """Grades are ordinal, and the direction is not alphabetical."""
    scope = pick((*SECTORS, *SEGMENTS), seed, 1)
    window = pick(WINDOWS, seed, 2)
    shape, objective = pick((
        ("How many borrowers were downgraded",
         "the count of borrowers whose grade worsened"),
        ("How many notches did the book move on average",
         "the average notch movement, signed"),
        ("Show the migration matrix",
         "a from-grade by to-grade matrix"),
        ("Which borrowers moved into watch grade",
         "the borrowers entering watch grade"),
    ), seed, 3)
    return build(
        family="RATING_MIGRATION",
        title=f"Rating movement in {scope}",
        turns=[Turn(f"{shape} in {scope} {window}?",
                    behaviour="Must treat internal grades as ordinal in the "
                              "bank's own direction. A downgrade is a move "
                              "towards default, whatever the grade labels "
                              "sort as.")],
        objectives=(objective, "the two dates the movement is measured "
                               "between"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=["internal rating"], metrics=["internal rating"],
        required_datasets=[RATINGS, TRANSITIONS],
        grain="borrower",
        period_contract={"phrase": window, "basis": "two reporting dates"},
        analytical_plan_contract={"ordinal": True,
                                  "direction": "towards default"},
        invariants=["ordinal_direction", "population_matched_both_dates"],
        scope_contract=_forbids("sorting grades alphabetically",
                                "counting a borrower present at only one "
                                "date"))


def _stage_migration(seed: str) -> sc.TeachingCase:
    """IFRS 9 stage transitions, with SICR meaning kept."""
    scope = pick((*SECTORS, *SEGMENTS), seed, 1)
    window = pick(WINDOWS, seed, 2)
    frm, to = pick((("1", "2"), ("2", "3"), ("2", "1"), ("3", "2")), seed, 3)
    return build(
        family="STAGE_MIGRATION",
        title=f"Stage {frm} to Stage {to} movement in {scope}",
        turns=[Turn(f"How much exposure moved from Stage {frm} to Stage {to} "
                    f"in {scope} {window}, and how many borrowers does that "
                    f"represent?",
                    behaviour="Must count transitions between two dates on a "
                              "matched population, and must report exposure "
                              "and borrower counts separately.")],
        objectives=(f"exposure moving from Stage {frm} to Stage {to}",
                    "the borrower count behind that movement",
                    "the opening population the movement is measured over"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=["ifrs 9 stage", "exposure at default"],
        required_datasets=[IFRS9, FACILITY], grain="facility",
        period_contract={"phrase": window, "basis": "two reporting dates"},
        analytical_plan_contract={"transition": [frm, to],
                                  "matched_population": True},
        invariants=["population_matched_both_dates", "transitions_sum"],
        scope_contract=_forbids("comparing two closing distributions",
                                "reading a stage share change as a "
                                "transition"))


def _dpd_migration(seed: str) -> sc.TeachingCase:
    """Buckets are ordered, and a cure is a direction rather than an
    absence."""
    scope = pick((*SECTORS, *SEGMENTS), seed, 1)
    window = pick(WINDOWS, seed, 2)
    bucket = pick(BUCKETS[:-1], seed, 3)
    return build(
        family="DPD_MIGRATION",
        title=f"Delinquency movement out of the {bucket} bucket",
        turns=[Turn(f"For {scope}, how many accounts moved out of the "
                    f"{bucket} day bucket {window}, and where did they go?",
                    behaviour="Must treat buckets as ordered and split "
                              "movement into deterioration and cure. An "
                              "account that left the bucket is not the same "
                              "as an account that improved.")],
        objectives=(f"accounts leaving the {bucket} bucket",
                    "how many deteriorated into a later bucket",
                    "how many cured into an earlier bucket or current"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=["days past due"], required_datasets=[DELINQUENCY, FACILITY],
        grain="facility",
        period_contract={"phrase": window, "basis": "two reporting dates"},
        analytical_plan_contract={"buckets": list(BUCKETS), "ordered": True},
        invariants=["bucket_order", "flows_reconcile_to_opening"],
        scope_contract=_forbids("treating an exit as a cure",
                                "comparing two closing bucket "
                                "distributions"))


def _roll_rate(seed: str) -> sc.TeachingCase:
    """A flow over an opening population, not a ratio of two snapshots."""
    frm = pick(BUCKETS[:-1], seed, 1)
    index = BUCKETS.index(frm)
    to = BUCKETS[index + 1]
    scope = pick((*SECTORS, *SEGMENTS), seed, 2)
    period = pick(PERIODS, seed, 3)
    shape, objective = pick((
        (f"What proportion of accounts in the {frm} bucket rolled to {to}",
         f"the roll rate from {frm} to {to}"),
        (f"What proportion of accounts in the {frm} bucket cured",
         f"the cure rate out of {frm}"),
        (f"What is the net flow out of the {frm} bucket",
         f"the net movement out of {frm}, deterioration less cure"),
    ), seed, 4)
    return build(
        family="ROLL_RATE_AND_CURE",
        title=f"Roll and cure out of the {frm} bucket in {scope}",
        turns=[Turn(f"{shape} in {scope} during {period}?",
                    behaviour="Must divide the flow by the OPENING "
                              "population of the bucket. Dividing one closing "
                              "bucket by another produces a number that looks "
                              "like a roll rate and is not one.")],
        objectives=(objective,
                    f"the opening population of the {frm} bucket",
                    "the accounts that left, by where they went"),
        difficulty=sc.EXPERT, risk="CRITICAL", officer=3,
        concepts=["days past due"],
        required_datasets=[DELINQUENCY, PAYMENTS], grain="facility",
        period_contract={"phrase": period, "basis": "opening and closing"},
        formula_contract={"numerator": f"accounts moving {frm} to {to}",
                          "denominator": f"opening population of {frm}"},
        analytical_plan_contract={"flow_over_opening": True},
        invariants=["denominator_is_opening_population", "share_bounds"],
        scope_contract=_forbids("dividing two closing snapshots",
                                "using the closing bucket as the "
                                "denominator"))


# ---------------------------------------------------------------------------
# The blueprints — ECL families
# ---------------------------------------------------------------------------


def _ecl_movement(seed: str) -> sc.TeachingCase:
    """The change between two dates, with the population accounted for on
    both sides."""
    scope = pick((*SECTORS, *SEGMENTS), seed, 1)
    window = pick(WINDOWS, seed, 2)
    return build(
        family="ECL_MOVEMENT",
        title=f"ECL movement in {scope}",
        turns=[Turn(f"How has expected credit loss in {scope} moved {window}, "
                    f"and how much of the change is accounts that were not "
                    f"there at the start?",
                    behaviour="Must separate the movement on the matched "
                              "population from new and exited accounts. A net "
                              "change that mixes them explains nothing.")],
        objectives=(f"opening and closing ECL for {scope}",
                    "the change on the matched population",
                    "the contribution of new accounts",
                    "the contribution of exited accounts"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=["expected credit loss"], metrics=["expected credit loss"],
        required_datasets=[IFRS9, FACILITY], grain="facility",
        period_contract={"phrase": window, "basis": "two reporting dates"},
        population_contract={"matched": True, "report_new_and_exited": True},
        analytical_plan_contract={"movement": True, "population_split": True},
        invariants=["opening_plus_change_equals_closing"],
        scope_contract=_forbids("a net change with no population split",
                                "attributing new lending to deterioration"))


def _parameters(seed: str) -> sc.TeachingCase:
    """A risk parameter is weighted and bounded, never summed."""
    parameter, concept = pick((
        ("twelve-month PD", "twelve-month pd"),
        ("lifetime PD", "twelve-month pd"),
        ("LGD", "expected credit loss"),
        ("ECL coverage", "ecl coverage"),
    ), seed, 1)
    dimension = pick(("sector", "segment", "rating grade", "IFRS 9 stage",
                      "vintage"), seed, 2)
    period = pick(PERIODS, seed, 3)
    return build(
        family="PD_LGD_EAD_ANALYSIS",
        title=f"{parameter} by {dimension}",
        turns=[Turn(f"What is average {parameter} by {dimension} in {period}, "
                    f"weighted by exposure?",
                    behaviour="Must weight the parameter by exposure and keep "
                              "it within its bounds. Summing a parameter, or "
                              "averaging it unweighted, is the type error the "
                              "ontology exists to refuse.")],
        objectives=(f"exposure-weighted {parameter} for {period}",
                    f"the same figure broken down by {dimension}",
                    "the exposure behind each weighted figure"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=[concept, "exposure at default"], metrics=[parameter],
        dimensions=[dimension], required_datasets=[IFRS9, FACILITY],
        operations=["WEIGHTED_AVERAGE"], grain="facility",
        period_contract={"phrase": period, "basis": "single reporting date"},
        formula_contract={"weighting": "exposure at default"},
        analytical_plan_contract={"operation": "WEIGHTED_AVERAGE",
                                  "weight": "exposure at default"},
        invariants=["parameter_bounds", "weighted_not_summed"],
        scope_contract=_forbids("summing a parameter",
                                "an unweighted average across facilities",
                                "mixing twelve-month and lifetime PD"))


# ---------------------------------------------------------------------------
# The blueprints — portfolio families
# ---------------------------------------------------------------------------


def _mix(seed: str) -> sc.TeachingCase:
    """A change in mix is not a change in the risk of the parts."""
    dimension = pick(("sector", "segment", "rating grade", "product",
                      "vintage"), seed, 1)
    window = pick(WINDOWS, seed, 2)
    ratio, concept = pick(RATIOS, seed, 3)
    return build(
        family="PORTFOLIO_MIX",
        title=f"Mix versus rate in the {dimension} breakdown",
        turns=[Turn(f"{ratio.capitalize()} rose {window}. How much of that is "
                    f"the {dimension} mix changing and how much is {ratio} "
                    f"rising within each {dimension}?",
                    behaviour="Must separate the mix effect from the "
                              "within-group effect and reconcile the two back "
                              "to the total change.")],
        objectives=(f"the total change in {ratio} {window}",
                    f"the part explained by a change in {dimension} mix",
                    f"the part explained by {ratio} moving within each "
                    f"{dimension}",
                    "a reconciliation of the two effects to the total"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=[concept, "exposure at default"], dimensions=[dimension],
        required_datasets=[FACILITY, IFRS9],
        period_contract={"phrase": window, "basis": "two reporting dates"},
        formula_contract={"decomposition": ["mix", "within-group"]},
        analytical_plan_contract={"order_neutral": True},
        invariants=["components_reconcile"],
        scope_contract=_forbids("reporting the total change alone",
                                "attributing a mix shift to deterioration"))


def _concentration(seed: str) -> sc.TeachingCase:
    """Concentration by a governed method, not by whichever top-N is on
    screen."""
    dimension = pick(("sector", "borrower", "group", "region", "product"),
                     seed, 1)
    method, objective = pick((
        ("the Herfindahl index", "the Herfindahl index for the dimension"),
        ("the share held by the largest twenty", "the top-20 share"),
        ("the share of capital the largest exposures represent",
         "large exposures as a share of capital"),
        ("the Gini coefficient", "the Gini coefficient of the distribution"),
    ), seed, 2)
    period = pick(PERIODS, seed, 3)
    return build(
        family="CONCENTRATION",
        title=f"{dimension.capitalize()} concentration, measured",
        turns=[Turn(f"How concentrated is the book by {dimension} in "
                    f"{period}? Use {method}.",
                    behaviour="Must compute the named governed measure. A "
                              "top-ten list is a symptom of concentration, "
                              "not a measure of it.")],
        objectives=(objective,
                    f"the {dimension} distribution the measure is computed "
                    "over",
                    "how the measure compares with the prior period"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=["exposure at default"], dimensions=[dimension],
        required_datasets=[FACILITY, GROUPS], grain=dimension,
        method_contract={"measure": method, "governed": True},
        period_contract={"phrase": period, "basis": "single reporting date"},
        analytical_plan_contract={"method": "concentration"},
        invariants=["share_bounds", "distribution_complete"],
        scope_contract=_forbids("substituting a top-N list for a measure",
                                "excluding the tail from the denominator"))


def _vintage(seed: str) -> sc.TeachingCase:
    """A cohort fixed at origination, followed — not re-formed each period."""
    vintage = pick(VINTAGES, seed, 1)
    measure, objective = pick((
        ("Stage 2 share", "the Stage 2 share of the cohort by months on "
                          "book"),
        ("cumulative default rate", "the cumulative default rate by months "
                                    "on book"),
        ("ECL coverage", "cohort ECL coverage by months on book"),
        ("90+ delinquency", "the 90+ rate by months on book"),
    ), seed, 2)
    segment = pick(SEGMENTS, seed, 3)
    return build(
        family="VINTAGE_AND_COHORT",
        title=f"The {vintage} {segment} vintage, followed",
        turns=[Turn(f"For {segment} facilities originated in {vintage}, how "
                    f"has {measure} developed by months on book?",
                    behaviour="Must hold the cohort fixed at origination and "
                              "follow it. Re-forming the cohort each period "
                              "measures the book, not the vintage.")],
        objectives=(f"the {vintage} {segment} origination cohort, fixed",
                    objective,
                    "the number of facilities still on book at each point"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=["exposure at default", "ifrs 9 stage"],
        required_datasets=[FACILITY, IFRS9], grain="facility",
        dimensions=["months on book"],
        population_contract={"cohort": f"originated in {vintage}",
                             "fixed_at_origination": True},
        period_contract={"phrase": "by months on book",
                         "basis": "cohort-relative"},
        analytical_plan_contract={"cohort_fixed": True,
                                  "x_axis": "months on book"},
        invariants=["cohort_membership_fixed", "survivorship_reported"],
        scope_contract=_forbids("re-forming the cohort each period",
                                "reading calendar time as cohort time"))


def _appetite(seed: str) -> sc.TeachingCase:
    """A measured position against a stated limit — headroom or breach, not
    the measure alone."""
    subject, limit = pick((
        ("single-sector exposure", "the sector concentration limit"),
        ("Stage 3 share", "the impaired-asset tolerance"),
        ("large exposures", "the large exposure limit"),
        ("watchlist exposure", "the watchlist tolerance"),
        ("sub-investment grade exposure", "the rating-quality limit"),
    ), seed, 1)
    scope = pick(SECTORS, seed, 2)
    period = pick(PERIODS, seed, 3)
    return build(
        family="RISK_APPETITE",
        title=f"{subject.capitalize()} against appetite",
        turns=[Turn(f"Is {scope} {subject} within {limit} at {period}?",
                    behaviour="Must state the position, the limit, and the "
                              "headroom or breach. Returning the measure "
                              "without the limit answers a different "
                              "question.")],
        objectives=(f"the measured {subject} for {scope} at {period}",
                    f"the value of {limit}",
                    "the headroom or the size of the breach",
                    "the direction of travel since the prior period"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=3,
        concepts=["exposure at default"], required_datasets=[FACILITY,
                                                             APPETITE],
        period_contract={"phrase": period, "basis": "single reporting date"},
        analytical_plan_contract={"compare_against": "stated limit"},
        result_contract={"shape": "position, limit and headroom together"},
        invariants=["limit_stated", "headroom_signed"],
        scope_contract=_forbids("returning the measure without the limit",
                                "reporting a breach without its size"))


def _stress(seed: str) -> sc.TeachingCase:
    """Scenario-weighted and scenario-specific figures kept apart."""
    scenario = pick(("the severe downside scenario", "the baseline scenario",
                     "the upside scenario", "a 200bp rate shock",
                     "an oil price decline scenario"), seed, 1)
    scope = pick((*SECTORS, *SEGMENTS), seed, 2)
    return build(
        family="STRESS_AND_SCENARIO",
        title=f"{scope} under {scenario}",
        turns=[Turn(f"What happens to {scope} ECL under {scenario}, and how "
                    f"does that compare with the reported figure?",
                    behaviour="Must name the scenario behind every number and "
                              "keep the scenario-specific figure distinct "
                              "from the probability-weighted reported one.")],
        objectives=(f"{scope} ECL under {scenario}",
                    "the reported probability-weighted ECL",
                    "the difference between them",
                    "the scenario weights in force"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=["expected credit loss"],
        required_datasets=[IFRS9, SCENARIOS],
        analytical_plan_contract={"scenario_specific": True,
                                  "report_weights": True},
        result_contract={"shape": "figures labelled by scenario"},
        invariants=["scenario_named", "weights_sum_to_one"],
        scope_contract=_forbids("presenting a scenario figure as the "
                                "reported ECL",
                                "an unlabelled number"))


# ---------------------------------------------------------------------------
# The blueprints — borrower families
# ---------------------------------------------------------------------------


def _covenant(seed: str) -> sc.TeachingCase:
    """Headroom, breach, coverage and shortfall, each with the direction it
    actually has."""
    subject, direction = pick((
        ("covenant headroom", "less is worse"),
        ("collateral coverage", "less is worse"),
        ("loan-to-value", "more is worse"),
        ("collateral shortfall", "more is worse"),
        ("guarantee coverage", "less is worse"),
    ), seed, 1)
    scope = pick(SECTORS, seed, 2)
    window = pick(WINDOWS, seed, 3)
    return build(
        family="COVENANT_AND_COLLATERAL",
        title=f"{subject.capitalize()} in {scope}",
        turns=[Turn(f"Which {scope} borrowers have seen {subject} "
                    f"deteriorate {window}, and which are in breach now?",
                    behaviour=f"Must read {subject} with the direction it "
                              f"actually has: {direction}. Ranking the wrong "
                              "way returns the healthiest borrowers.")],
        objectives=(f"{scope} borrowers whose {subject} worsened {window}",
                    "those currently in breach",
                    "the size of each breach"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=["covenant headroom"], metrics=[subject],
        required_datasets=[COVENANTS, COLLATERAL, FACILITY], grain="borrower",
        period_contract={"phrase": window, "basis": "two reporting dates"},
        analytical_plan_contract={"direction_of_deterioration": direction},
        invariants=["direction_of_deterioration", "breach_flag_matches_test"],
        scope_contract=_forbids("ranking against the direction of "
                                "deterioration",
                                "treating a breach as a level"))


def _deterioration(seed: str) -> sc.TeachingCase:
    """Several financial signals combined without averaging away the
    direction."""
    scope = pick((*SECTORS, *SEGMENTS), seed, 1)
    window = pick(WINDOWS, seed, 2)
    first, concept_a = pick(RATIOS, seed, 3)
    second, concept_b = _other(RATIOS, (first, concept_a), seed, 4)
    return build(
        family="FINANCIAL_DETERIORATION",
        title=f"Financial deterioration in {scope}",
        turns=[Turn(f"Which {scope} borrowers show deteriorating {first} and "
                    f"{second} together {window}?",
                    behaviour="Must apply the direction of deterioration to "
                              "each ratio separately and intersect. A "
                              "combined score averages a worsening ratio "
                              "against an improving one and finds nothing.")],
        objectives=(f"{scope} borrowers whose {first} worsened {window}",
                    f"those whose {second} also worsened",
                    "the intersection of the two",
                    "the size of each movement"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=[concept_a, concept_b], metrics=[first, second],
        required_datasets=[FINANCIALS, FACILITY], grain="borrower",
        period_contract={"phrase": window, "basis": "two reporting dates"},
        analytical_plan_contract={"combine": "intersection",
                                  "per_ratio_direction": True},
        invariants=["direction_of_deterioration", "condition"],
        scope_contract=_forbids("single_condition",
                                "averaging opposing directions into one "
                                "score"))


def _early_warning(seed: str) -> sc.TeachingCase:
    """Signals turning before a stage or rating has moved."""
    scope = pick((*SECTORS, *SEGMENTS), seed, 1)
    window = pick(WINDOWS, seed, 2)
    signal, concept = pick((
        ("limit utilisation", "limit utilisation"),
        ("arrears", "arrears"),
        ("days past due", "days past due"),
        ("covenant headroom", "covenant headroom"),
        ("debt service coverage ratio", "debt service coverage ratio"),
    ), seed, 3)
    return build(
        family="EARLY_WARNING",
        title=f"Deterioration ahead of a stage move in {scope}",
        turns=[Turn(f"Which {scope} borrowers show {signal} deteriorating "
                    f"{window} while still in Stage 1 with an unchanged "
                    f"rating?",
                    behaviour="Must find the borrowers whose signal has moved "
                              "and whose stage and rating have not, and say "
                              "what would confirm the deterioration.")],
        objectives=(f"{scope} borrowers whose {signal} deteriorated {window}",
                    "those still in Stage 1",
                    "those whose rating is unchanged",
                    "what evidence would confirm the deterioration"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=[concept, "ifrs 9 stage", "internal rating"],
        required_datasets=[FACILITY, IFRS9, RATINGS, WATCHLIST],
        grain="borrower",
        period_contract={"phrase": window, "basis": "two reporting dates"},
        analytical_plan_contract={"signal_moved": True, "stage_unchanged": True},
        interpretation_contract={"must_name": "what would confirm the "
                                              "deterioration"},
        invariants=["condition", "direction_of_deterioration"],
        scope_contract=_forbids("returning borrowers already in Stage 2",
                                "claiming a stage move that has not "
                                "happened"))


# ---------------------------------------------------------------------------
# The blueprints — judgment and governance families
# ---------------------------------------------------------------------------


def _contradictory(seed: str) -> sc.TeachingCase:
    """Signals that point opposite ways, surfaced rather than resolved."""
    scope = pick((*SECTORS, *SEGMENTS), seed, 1)
    window = pick(WINDOWS, seed, 2)
    falling, rising = pick((
        ("expected credit loss", "days past due and rating downgrades"),
        ("Stage 2 exposure", "covenant breaches"),
        ("ECL coverage", "the 90+ delinquency rate"),
        ("watchlist exposure", "limit utilisation"),
        ("arrears", "the count of borrowers below covenant"),
    ), seed, 3)
    return build(
        family="CONTRADICTORY_SIGNALS",
        title=f"{falling.capitalize()} fell while {rising} rose",
        turns=[Turn(f"In {scope}, {falling} fell {window} while {rising} "
                    f"rose. What is going on?",
                    behaviour="Must report both directions and what could "
                              "reconcile them — a population change, a model "
                              "update, an overlay release. Must not resolve "
                              "the contradiction into one direction.")],
        objectives=(f"the movement in {falling}",
                    f"the movement in {rising}",
                    "the candidate explanations that would reconcile them",
                    "what evidence would distinguish between them"),
        difficulty=sc.EXPERT, risk="CRITICAL", officer=3,
        concepts=["expected credit loss", "days past due"],
        required_datasets=[IFRS9, FACILITY, DELINQUENCY, RATINGS],
        period_contract={"phrase": window, "basis": "two reporting dates"},
        analytical_plan_contract={"analyses": [f"movement in {falling}",
                                               f"movement in {rising}"],
                                  "reconcile": False},
        interpretation_contract={"must_surface": "both directions",
                                 "must_not": "pick one and narrate it"},
        result_contract={"shape": "both signals, then candidate "
                                  "explanations"},
        invariants=["both_signals_reported"],
        scope_contract=_forbids("resolving the contradiction silently",
                                "reporting only the reassuring direction"))


def _agentic(seed: str) -> sc.TeachingCase:
    """Work planned across agents and tools, within the gates that govern
    them."""
    scope = pick((*SECTORS, *SEGMENTS), seed, 1)
    task, objective, gate = pick((
        ("run a full review and open cases for anything that needs attention",
         "risk cases opened for the material findings",
         "case creation needs approval at the officer's level"),
        ("check the book against appetite and escalate any breach",
         "an escalation for each breach found",
         "escalation needs approval"),
        ("refresh the watchlist and tell me what changed",
         "the watchlist additions and removals",
         "a watchlist change is a material action"),
        ("review the new period and summarise what moved",
         "a summary of the period's movements",
         "review is read-only and needs no approval"),
    ), seed, 2)
    return build(
        family="AGENTIC_ORCHESTRATION",
        title=f"Coordinated review of {scope}",
        turns=[Turn(f"For {scope}, {task}.", result_type="NARRATIVE",
                    behaviour="Must plan the work across registered agents "
                              "and tools, stay inside the budget, and stop at "
                              "the approval gate rather than acting through "
                              "it.")],
        objectives=("the plan, as steps across registered agents",
                    "the deterministic analyses each step runs",
                    objective,
                    "the approval gate the plan stops at"),
        difficulty=sc.EXPERT, risk="CRITICAL", officer=4,
        expected_agent_roles=["portfolio_reviewer", "credit_analyst"],
        allowed_tools=["governed_analysis", "risk_case_draft"],
        forbidden_tools=["direct_write", "external_send"],
        required_datasets=[FACILITY, IFRS9, WATCHLIST],
        cost_budget=2.0, latency_budget=120.0,
        analytical_plan_contract={"steps": "registered agents only",
                                  "approval_gate": gate},
        trace_contract={"every_step_recorded": True,
                        "skipped_is_not_pass": True},
        security_constraints=["no action beyond the approval gate"],
        invariants=["within_budget", "approval_gate_respected"],
        scope_contract=_forbids("acting through an approval gate",
                                "using an unregistered tool"))


# ---------------------------------------------------------------------------
# The blueprints — scope families
# ---------------------------------------------------------------------------


def _corporate(seed: str) -> sc.TeachingCase:
    """Corporate vocabulary, grain and concepts."""
    instrument = pick(CORPORATE_INSTRUMENTS, seed, 1)
    sector = pick(SECTORS, seed, 2)
    subject, objective = pick((
        ("covenant headroom", "covenant headroom by obligor"),
        ("group exposure", "exposure aggregated to the group parent"),
        ("financial spreading coverage", "obligors with current spreads"),
        ("limit utilisation", "utilisation against the approved limit"),
        ("interest coverage", "obligors below the interest cover floor"),
    ), seed, 3)
    return build(
        family="CORPORATE_SCOPE",
        title=f"{subject.capitalize()} on {instrument}",
        turns=[Turn(f"For {sector} obligors with {instrument}, show "
                    f"{subject} at the latest reporting date.",
                    behaviour="Must work at obligor and facility grain and "
                              "use corporate concepts. Retail concepts do not "
                              "apply and must not be substituted.")],
        objectives=(f"{sector} obligors holding {instrument}", objective,
                    "the facility-to-obligor aggregation used"),
        difficulty=sc.COMPLEX, risk="MEDIUM", officer=2,
        portfolio_scope=fam.CORPORATE,
        industry_or_product_scope=instrument,
        concepts=["covenant headroom", "exposure at default"],
        required_datasets=[FACILITY, COVENANTS, FINANCIALS, GROUPS],
        grain="obligor",
        analytical_plan_contract={"grain": "obligor", "scope": "corporate"},
        invariants=["no_double_counting"],
        scope_contract=_forbids("using retail product concepts",
                                "reporting at account grain"))


def _retail(seed: str) -> sc.TeachingCase:
    """Retail vocabulary, grain and concepts."""
    product = pick(RETAIL_PRODUCTS, seed, 1)
    subject, objective = pick((
        ("the 30+ delinquency rate", "the 30+ rate by product"),
        ("the Stage 2 share", "the Stage 2 share of the product book"),
        ("the cure rate", "cures out of early delinquency"),
        ("behavioural score distribution", "the score band distribution"),
        ("utilisation", "utilisation across the product book"),
    ), seed, 2)
    vintage = pick(VINTAGES, seed, 3)
    return build(
        family="RETAIL_SCOPE",
        title=f"{subject.capitalize()} on {product}",
        turns=[Turn(f"For {product} originated in {vintage}, what is "
                    f"{subject} at the latest reporting date?",
                    behaviour="Must work at account and product grain and use "
                              "retail concepts. Corporate concepts — "
                              "covenants, obligor groups, financial "
                              "spreading — do not apply.")],
        objectives=(f"{product} accounts originated in {vintage}", objective,
                    "the account population the rate is computed over"),
        difficulty=sc.COMPLEX, risk="MEDIUM", officer=2,
        portfolio_scope=fam.RETAIL,
        industry_or_product_scope=product,
        concepts=["days past due", "ifrs 9 stage"],
        required_datasets=[FACILITY, DELINQUENCY, IFRS9], grain="account",
        population_contract={"cohort": f"originated in {vintage}"},
        analytical_plan_contract={"grain": "account", "scope": "retail"},
        invariants=["share_bounds"],
        scope_contract=_forbids("using covenant or obligor concepts",
                                "reporting at obligor grain"))


# ---------------------------------------------------------------------------
# The blueprint table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Blueprint:
    """One family's reviewed shape, and how many instances of it to build.

    The counts are not uniform. A family migration left with eighteen cases
    needs fewer than one it left empty, and a family whose obligation has
    several genuinely different shapes (a follow-up that narrows, widens or
    resets) needs enough instances to reach all of them.
    """

    family: str
    count: int
    make: Callable[[str], sc.TeachingCase]


BLUEPRINTS: tuple[Blueprint, ...] = (
    # Metadata — thin after migration, and cheap to deepen.
    Blueprint("DATA_DISCOVERY", 12, _discovery),
    Blueprint("DATA_RELATIONSHIPS", 12, _dictionary_relationship),
    Blueprint("DATA_INSPECTION", 12, _inspection),

    # Calculation.
    Blueprint("SINGLE_DOMAIN_AGGREGATION", 20, _aggregation),
    Blueprint("FILTERING_AND_RANKING", 20, _filtering),
    Blueprint("OBJECTIVE_COVERAGE", 20, _objective_coverage),
    Blueprint("AMBIGUITY", 20, _ambiguity),

    # Conversation — the families §13 counts as multi-turn.
    Blueprint("MULTI_TURN_REFERENTS", 40, _multi_turn),
    Blueprint("PREVIOUS_RESULT_REUSE", 35, _previous_result),
    Blueprint("PRESENTATION_MODIFICATION", 35, _presentation),

    # Structure — both families were empty.
    Blueprint("AS_OF_JOIN", 24, _as_of),
    Blueprint("GRAIN_RECONCILIATION", 24, _grain),

    # Migration and flow.
    Blueprint("RATING_MIGRATION", 20, _rating_migration),
    Blueprint("STAGE_MIGRATION", 20, _stage_migration),
    Blueprint("DPD_MIGRATION", 20, _dpd_migration),
    Blueprint("ROLL_RATE_AND_CURE", 24, _roll_rate),

    # ECL.
    Blueprint("ECL_MOVEMENT", 20, _ecl_movement),
    Blueprint("PD_LGD_EAD_ANALYSIS", 20, _parameters),

    # Portfolio.
    Blueprint("PORTFOLIO_MIX", 20, _mix),
    Blueprint("CONCENTRATION", 20, _concentration),
    Blueprint("VINTAGE_AND_COHORT", 24, _vintage),
    Blueprint("RISK_APPETITE", 24, _appetite),
    Blueprint("STRESS_AND_SCENARIO", 20, _stress),

    # Borrower.
    Blueprint("COVENANT_AND_COLLATERAL", 20, _covenant),
    Blueprint("FINANCIAL_DETERIORATION", 20, _deterioration),
    Blueprint("EARLY_WARNING", 20, _early_warning),

    # Judgment and governance.
    Blueprint("CONTRADICTORY_SIGNALS", 24, _contradictory),
    Blueprint("AGENTIC_ORCHESTRATION", 24, _agentic),

    # Scope — both families were empty.
    Blueprint("CORPORATE_SCOPE", 24, _corporate),
    Blueprint("RETAIL_SCOPE", 24, _retail),
)

#: What §13 asks the canonical corpus to reach. Held as data so the test that
#: checks the target reads the same number the corpus is built to.
TARGET = 500


def _slug(family_id: str) -> str:
    return family_id.lower().replace("_", "-")


def _finish(case: sc.TeachingCase, blueprint: Blueprint,
            index: int) -> sc.TeachingCase:
    case.family_id = blueprint.family
    case.source_provenance = (f"canonical:{blueprint.family}:{index}"
                              f"@{CANONICAL_VERSION}")
    case.tags = ["canonical", blueprint.family.lower()]
    case.cluster_id = migrate._cluster(case.question)
    case.description = (
        f"Canonical case for {blueprint.family}: a reviewed shape "
        "instantiated over the governed vocabulary.")
    return migrate.enrich(case)


#: How many seeds to try per case asked for, before accepting that the
#: blueprint's combination space is exhausted. Eight is generous: a blueprint
#: whose space is genuinely large finds a new combination in one or two tries,
#: and one whose space is small stops rather than spinning.
_ATTEMPTS = 8


def cases() -> list[sc.TeachingCase]:
    """Every canonical case, deterministically and without duplicates.

    Building `count` cases from `count` seeds produced forty-eight duplicates:
    a hash-based choice collides whenever the blueprint's combination space is
    smaller than the number of cases asked for, and DATA_RELATIONSHIPS has ten
    declared relationships to draw from however many cases are requested.

    Duplicates are exactly what §13 means by inflating the count. So a
    blueprint keeps drawing until it has the distinct cases it asked for or its
    space runs out, and `report` shows the shortfall rather than hiding it. A
    family that cannot reach its target is a family whose blueprint needs more
    shapes, which is a decision for a person, not a number to pad.
    """
    out: list[sc.TeachingCase] = []
    for blueprint in BLUEPRINTS:
        seen: set[str] = set()
        built: list[sc.TeachingCase] = []
        for attempt in range(blueprint.count * _ATTEMPTS):
            if len(built) >= blueprint.count:
                break
            case = _finish(blueprint.make(f"{blueprint.family}:{attempt}"),
                           blueprint, attempt)
            if case.fingerprint in seen:
                continue
            seen.add(case.fingerprint)
            built.append(case)
        for index, case in enumerate(built):
            case.case_id = f"can-{_slug(blueprint.family)}-{index:03d}"
        out.extend(built)
    return out


def report() -> dict[str, Any]:
    """What the canonical corpus contains, by family and by difficulty."""
    produced = cases()
    by_family: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    by_status: dict[str, int] = {}
    problems: dict[str, int] = {}

    for case in produced:
        by_family[case.family_id] = by_family.get(case.family_id, 0) + 1
        by_difficulty[case.difficulty] = \
            by_difficulty.get(case.difficulty, 0) + 1
        resolved = sc.resolve_status(case)
        by_status[resolved] = by_status.get(resolved, 0) + 1
        for problem in sc.validate(case):
            problems[problem.field] = problems.get(problem.field, 0) + 1

    short = {b.family: b.count - by_family.get(b.family, 0)
             for b in BLUEPRINTS if by_family.get(b.family, 0) < b.count}

    return {
        "total": len(produced),
        "target": TARGET,
        "short_of_blueprint": short,
        "by_family": by_family,
        "by_difficulty": by_difficulty,
        "by_status": by_status,
        "problems": problems,
        "multi_turn": sum(1 for c in produced if c.turn_count() > 1),
        "clusters": len({c.cluster_id for c in produced}),
    }


__all__ = ["BLUEPRINTS", "CANONICAL_VERSION", "TARGET", "Blueprint", "Turn",
           "build", "cases", "pick", "report"]
