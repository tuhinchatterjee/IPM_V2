"""
The development curriculum: what CreditProbe is optimised against.

Two libraries, and the separation is the point
-----------------------------------------------
This one is **open**. Prompts are tuned against it, routing thresholds are
chosen against it, and it is the one to add a case to when a user reports a
failure. Everything here may be looked at while making the product better.

`holdout.py` is **sealed**. Nothing that shapes the product may read it, and an
import-graph test enforces that. A prompt tuned against the cases it is scored
on measures the tuning; the holdout is what turns a score into a claim.

What a case declares
--------------------
The same shape as the runtime benchmark: a thread of questions and, per turn,
what a correct answer would have had to DO — the capability, the conversation
action, the datasets, the period, the invariants. Never the answer itself. A
stored answer is a number that can be quietly aligned to whatever the product
returns; a specification cannot.

Coverage
--------
The twenty-four families §38 names, from data discovery through scope reset to
adversarial boundary cases. Each is a list of threads, and the module reports
what it covers so a gap is visible rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CURRICULUM_VERSION = "1.0.0"

# The families a curriculum has to cover to be worth measuring against.
DISCOVERY = "data discovery"
INSPECTION = "data inspection"
DICTIONARY = "data dictionary"
RELATIONSHIPS = "relationships"
CLASSIFICATION = "field classification"
METHODS = "methods"
SIMPLE = "simple calculation"
CONDITIONAL = "conditional aggregation"
NESTED = "nested ratio"
PERIODS = "period comparison"
MULTIDOMAIN = "multi-domain join"
RANKING = "ranking"
FILTERS = "filters"
INVESTIGATION = "broad investigation"
PRESENTATION = "presentation change"
COMPOUND = "compound question"
INCOMPLETE = "incomplete-response repair"
ENTITY = "entity resolution"
AMBIGUITY = "ambiguity"
UNSUPPORTED = "unsupported"
REFERENT = "multi-turn referent"
NARROW = "scope narrowing"
WIDEN = "scope widening"
RESET = "scope reset"
BOUNDARY = "adversarial boundary"

FAMILIES: tuple[str, ...] = (
    DISCOVERY, INSPECTION, DICTIONARY, RELATIONSHIPS, CLASSIFICATION, METHODS,
    SIMPLE, CONDITIONAL, NESTED, PERIODS, MULTIDOMAIN, RANKING, FILTERS,
    INVESTIGATION, PRESENTATION, COMPOUND, INCOMPLETE, ENTITY, AMBIGUITY,
    UNSUPPORTED, REFERENT, NARROW, WIDEN, RESET, BOUNDARY,
)


@dataclass
class Turn:
    """One question, and what a correct answer would have had to do."""

    question: str
    capability: str = ""
    action: str = ""
    datasets: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    period: str = ""
    #: EXECUTE | CLARIFY | UNSUPPORTED — what CreditProbe should do at all.
    outcome: str = "EXECUTE"
    #: Invariants a correct result must satisfy, in the words the runtime
    #: checks them by.
    invariants: tuple[str, ...] = ()
    #: What it must NOT do. A case with a forbidden behaviour is worth twice
    #: one without: it catches the substitution as well as the miss.
    forbidden: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "capability": self.capability,
                "action": self.action, "datasets": list(self.datasets),
                "concepts": list(self.concepts), "period": self.period,
                "outcome": self.outcome, "invariants": list(self.invariants),
                "forbidden": list(self.forbidden)}


@dataclass
class Case:
    """One thread, with the family it exercises."""

    id: str
    family: str
    title: str
    turns: list[Turn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "family": self.family, "title": self.title,
                "turns": [t.to_dict() for t in self.turns]}


def _c(case_id: str, family: str, title: str, *turns: Turn) -> Case:
    return Case(id=case_id, family=family, title=title, turns=list(turns))


CASES: tuple[Case, ...] = (
    # ---------------------------------------------------------- metadata
    _c("cur-disc-1", DISCOVERY, "What ratings data exists",
       Turn("What data do you have about borrower ratings?",
            capability="DATA_DISCOVERY", action="NEW_REQUEST",
            datasets=("customer_ratings",),
            forbidden=("ANALYSIS",))),
    _c("cur-disc-2", DISCOVERY, "What IFRS 9 data exists",
       Turn("What IFRS 9 data do you have?", capability="DATA_DISCOVERY",
            datasets=("ifrs9_staging",), forbidden=("ANALYSIS",))),
    _c("cur-insp-1", INSPECTION, "How much rating history",
       Turn("How many years of ratings history do you have?",
            capability="DATA_QUALITY", datasets=("customer_ratings",))),
    _c("cur-dict-1", DICTIONARY, "What DSCR means",
       Turn("What does DSCR mean?", capability="DATA_DICTIONARY",
            concepts=("debt service coverage",), forbidden=("ANALYSIS",))),
    _c("cur-dict-2", DICTIONARY, "The fields in a named dataset",
       Turn("What fields are in the watchlist data?",
            capability="DATA_DICTIONARY", datasets=("watchlist_register",))),
    _c("cur-rel-1", RELATIONSHIPS, "How ratings reach IFRS 9",
       Turn("How is ratings data connected to IFRS 9?",
            capability="DATA_RELATIONSHIP",
            datasets=("customer_ratings", "ifrs9_staging"))),
    _c("cur-meth-1", METHODS, "What methods exist for concentration",
       Turn("What methods do you have for concentration?",
            capability="METHOD_DISCOVERY")),

    # ------------------------------------------------------- calculation
    _c("cur-simple-1", SIMPLE, "Total EAD by sector",
       Turn("What is total EAD by sector in the latest quarter?",
            capability="ANALYSIS", concepts=("exposure at default",),
            datasets=("portfolio_facility",), period="latest",
            invariants=("share_bounds",))),
    _c("cur-rank-1", RANKING, "Largest Real Estate customers",
       Turn("Show me the five largest Real Estate customers by EAD.",
            capability="ANALYSIS", concepts=("exposure at default",),
            invariants=("row_limit", "filter_equality"),
            forbidden=("sector_concentration",))),
    _c("cur-cond-1", CONDITIONAL, "Stage 2 exposure",
       Turn("How much exposure at default is in Stage 2?",
            capability="ANALYSIS",
            concepts=("exposure at default", "IFRS 9 stage"))),
    _c("cur-nested-1", NESTED, "Stage 2 share by sector, compared",
       Turn("For each sector, calculate Stage 2 EAD divided by total sector "
            "EAD, compare it with four quarters ago, and rank sectors by the "
            "largest increase.",
            capability="ANALYSIS", concepts=("exposure at default",),
            invariants=("numerator_within_denominator", "share_bounds"))),
    _c("cur-period-1", PERIODS, "ECL movement over the year",
       Turn("How has expected credit loss moved over the latest year?",
            capability="ANALYSIS", concepts=("expected credit loss",))),
    _c("cur-multi-1", MULTIDOMAIN, "Three measures by rating grade",
       Turn("For each rating grade, show average ECL coverage, average "
            "leverage and average DSCR in the latest period.",
            capability="ANALYSIS",
            datasets=("ifrs9_staging", "customer_ratings"),
            forbidden=("DATA_QUALITY", "DATA_DISCOVERY"))),
    _c("cur-filter-1", FILTERS, "A threshold, not a movement",
       Turn("Which large Real Estate customers have worsening DPD, "
            "increasing ECL, a rating downgrade and covenant headroom below "
            "15%?",
            capability="ANALYSIS",
            invariants=("condition", "filter_equality"))),

    # ------------------------------------------------------ conversation
    _c("cur-ref-1", REFERENT, "A carried population",
       Turn("Show me the five largest Real Estate customers by EAD.",
            capability="ANALYSIS", invariants=("row_limit",)),
       Turn("Which of these are Stage 2 or Stage 3?",
            capability="ANALYSIS", action="CONTINUE")),
    _c("cur-ref-2", REFERENT, "An elided referent",
       Turn("Which customers have worsening leverage and declining DSCR "
            "together with a rating downgrade?", capability="ANALYSIS"),
       Turn("Show the ten largest by EAD.", action="MODIFY_PREVIOUS",
            invariants=("row_limit",)),
       Turn("Which also had an increase in ECL?", action="CONTINUE")),
    _c("cur-class-1", CLASSIFICATION, "Classifying a remembered field set",
       Turn("What fields are available in the ratings data?",
            capability="DATA_DICTIONARY"),
       Turn("Which of those fields are financial ratios?",
            action="METADATA_FOLLOWUP", forbidden=("ANALYSIS",))),
    _c("cur-pres-1", PRESENTATION, "A chart, not a recomputation",
       Turn("What is total EAD by sector in the latest quarter?",
            capability="ANALYSIS"),
       Turn("Show it as a graph.", action="MODIFY_PRESENTATION")),
    _c("cur-narrow-1", NARROW, "Narrowing to a sector",
       Turn("Which customers had a rating downgrade and an increase in ECL "
            "over the latest year?", capability="ANALYSIS"),
       Turn("Only Contracting.", action="MODIFY_PREVIOUS",
            invariants=("filter_equality",))),
    _c("cur-widen-1", WIDEN, "Widening to the whole book",
       Turn("Show the five largest Real Estate customers by EAD.",
            capability="ANALYSIS"),
       Turn("Now compare all sectors.", action="WIDEN_SCOPE")),
    _c("cur-reset-1", RESET, "Discarding the population",
       Turn("Show the five largest Real Estate customers by EAD.",
            capability="ANALYSIS"),
       Turn("Forget those and use the whole portfolio: what is total EAD by "
            "sector?", action="RESET_SCOPE")),
    _c("cur-nav-1", INSPECTION, "Opening what the thread is about",
       Turn("What IFRS 9 data do you have?", capability="DATA_DISCOVERY"),
       Turn("Open the latest dataset.", action="NAVIGATE")),
    _c("cur-comp-1", COMPOUND, "Two objectives in one sentence",
       Turn("What fields are in the ratings data, and which of them are "
            "financial ratios?", capability="DATA_DICTIONARY")),
    _c("cur-inc-1", INCOMPLETE, "Completing what was left out",
       Turn("What fields are in the ratings data, and which of them are "
            "financial ratios?", capability="DATA_DICTIONARY"),
       Turn("You didn't answer my second question.",
            action="CORRECT_INCOMPLETE_RESPONSE")),

    # ---------------------------------------------------------- refusals
    _c("cur-amb-1", AMBIGUITY, "Exposure means three things",
       Turn("Show me exposure.", outcome="CLARIFY",
            forbidden=("ANALYSIS",))),
    _c("cur-amb-2", AMBIGUITY, "Naming the measure answers",
       Turn("What is total exposure at default by sector?",
            capability="ANALYSIS", outcome="EXECUTE")),
    _c("cur-unsup-1", UNSUPPORTED, "Data CreditProbe does not hold",
       Turn("Which borrowers had their CEO resign in the last three months?",
            outcome="UNSUPPORTED", forbidden=("ANALYSIS", "CLARIFY"))),
    _c("cur-ent-1", ENTITY, "A borrower nobody has heard of",
       Turn("How much exposure do we have to Northwind Trading?",
            outcome="CLARIFY", forbidden=("ANALYSIS",))),
    _c("cur-inv-1", INVESTIGATION, "Investigate a sector",
       Turn("Something seems wrong with Contracting. Investigate it.",
            capability="ANALYSIS", outcome="EXECUTE")),

    # -------------------------------------------------------- boundaries
    _c("cur-bound-1", BOUNDARY, "A threshold read as a movement",
       Turn("Which customers have covenant headroom below 15%?",
            capability="ANALYSIS", invariants=("condition",))),
    _c("cur-bound-2", BOUNDARY, "A number after a movement word is a window",
       Turn("Which customers had an increase in ECL over the latest 6 "
            "months?", capability="ANALYSIS")),
    _c("cur-bound-3", BOUNDARY, "A sector name that is also a verb",
       Turn("Show Contracting customers whose ECL rose.",
            capability="ANALYSIS", invariants=("filter_equality",))),
    _c("cur-bound-4", BOUNDARY, "A ratio must not be summed",
       Turn("What is average DSCR by sector?", capability="ANALYSIS",
            concepts=("debt service coverage",))),
)

BY_ID: dict[str, Case] = {c.id: c for c in CASES}


def by_family(family: str) -> list[Case]:
    return [c for c in CASES if c.family == family]


def coverage() -> dict[str, int]:
    """How many cases each family has. A zero is a gap, and it is visible."""
    return {family: len(by_family(family)) for family in FAMILIES}


def gaps() -> list[str]:
    return [family for family, count in coverage().items() if count == 0]


def turn_count() -> int:
    return sum(len(c.turns) for c in CASES)


__all__ = ["BY_ID", "CASES", "CURRICULUM_VERSION", "FAMILIES", "Case", "Turn",
           "by_family", "coverage", "gaps", "turn_count"]
