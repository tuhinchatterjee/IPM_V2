"""
The sealed holdout: what a certification score is actually measured on.

Sealed means one thing
-----------------------
Nothing that shapes the product may read this module. Not the prompts, not the
routing thresholds, not the retrieval policy, not the abstention thresholds,
and not `curriculum.py` — an import-graph test asserts each of those, and a
runtime test asserts the orchestration path never loads this module even
dynamically.

A prompt tuned against the cases it is scored on measures the tuning. Every
number the factory reports as evidence comes from here, and its value is
entirely a function of nobody having looked at it while making the product
better.

Different in kind, not only in content
---------------------------------------
A holdout that is the curriculum with different nouns measures memorisation of
the curriculum. These cases differ in the ways real questions differ:

* **unseen entities** — borrowers and sectors the curriculum never names;
* **unseen periods** — windows the curriculum never asks about;
* **unseen aliases** — the same concept under a word nobody wrote down;
* **adversarial ambiguity** — sentences with two defensible readings;
* **multi-turn scope changes** — narrow, widen, reset, in orders the
  curriculum does not use;
* **boundary values** — 14.99, 15.00, 15.01 against a threshold of 15;
* **compound requests** — three objectives where the curriculum has two.

Why it is the size it is
-------------------------
Twenty-four cases could not certify anything. A Wilson interval over twenty
accepted answers supports no rate claim at all however they come out, so the
first certification run produced a build that behaved correctly and a manifest
that had to say its precision was unclaimable. The set was enlarged until a
clean run could actually demonstrate the gate — about sixty consecutive clean
cases at 95% confidence — and every case added was written from the
specification and run once, not written and then adjusted.

Enlarging a holdout for statistical adequacy is not tuning against it. Tuning
would be reading a failure and softening the case.

Two cases WERE revised, and the difference matters enough to write down. A case
is revised only when its expectation is wrong about the governed data — when no
correct product could satisfy it — never because the product failed it. Both
revisions are recorded in `CORRECTIONS` below, with the evidence, and both are
published on the release manifest so anyone reading a certification score can
see exactly which expectations changed and decide for themselves.

What it never contains
----------------------
An expected ANSWER. Like the curriculum and the runtime benchmark, a case
declares what a correct answer must DO. A stored figure can be quietly aligned
to whatever the product returns by somebody fixing a "wrong" test; a
specification cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

HOLDOUT_VERSION = "1.2.0"

#: The families a holdout must exercise for its score to mean anything. Not
#: the curriculum's twenty-five: a holdout tests generalisation, so it is
#: organised by the KIND of unseen thing rather than by capability.
UNSEEN_ENTITY = "unseen entity"
UNSEEN_PERIOD = "unseen period"
UNSEEN_ALIAS = "unseen alias"
ADVERSARIAL = "adversarial ambiguity"
SCOPE = "multi-turn scope change"
BOUNDARY = "boundary value"
COMPOUND = "compound request"
BROAD = "broad investigation"

KINDS: tuple[str, ...] = (UNSEEN_ENTITY, UNSEEN_PERIOD, UNSEEN_ALIAS,
                          ADVERSARIAL, SCOPE, BOUNDARY, COMPOUND, BROAD)


@dataclass
class Turn:
    question: str
    #: EXECUTE | CLARIFY | UNSUPPORTED.
    outcome: str = "EXECUTE"
    capability: str = ""
    action: str = ""
    concepts: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    #: Cases that must never fail, whatever the aggregate says. A wrong answer
    #: here is not a percentage point, it is a release blocker.
    critical: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "outcome": self.outcome,
                "capability": self.capability, "action": self.action,
                "concepts": list(self.concepts), "datasets": list(self.datasets),
                "invariants": list(self.invariants),
                "forbidden": list(self.forbidden), "critical": self.critical}


@dataclass
class Case:
    id: str
    kind: str
    title: str
    turns: list[Turn] = field(default_factory=list)

    @property
    def critical(self) -> bool:
        return any(t.critical for t in self.turns)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "title": self.title,
                "critical": self.critical,
                "turns": [t.to_dict() for t in self.turns]}


def _c(case_id: str, kind: str, title: str, *turns: Turn) -> Case:
    return Case(id=case_id, kind=kind, title=title, turns=list(turns))


CASES: tuple[Case, ...] = (
    # ------------------------------------------------- entities not seen
    _c("hold-ent-1", UNSEEN_ENTITY, "A sector the curriculum never names",
       Turn("What is total exposure at default in Petrochemicals?",
            capability="ANALYSIS", invariants=("filter_equality",))),
    _c("hold-ent-2", UNSEEN_ENTITY, "A region the curriculum never names",
       Turn("Which Tabuk customers had an increase in ECL over the latest "
            "year?", capability="ANALYSIS",
            invariants=("filter_equality",))),
    _c("hold-ent-3", UNSEEN_ENTITY, "A borrower that does not exist",
       Turn("How much do we lend to Arcadia Shipping?", outcome="CLARIFY",
            forbidden=("ANALYSIS",), critical=True)),

    # ------------------------------------------------- periods not seen
    _c("hold-per-1", UNSEEN_PERIOD, "A named historic quarter",
       Turn("What was total exposure at default in Q4 2024?",
            capability="ANALYSIS", concepts=("exposure at default",))),
    _c("hold-per-2", UNSEEN_PERIOD, "A two-year window",
       Turn("How has expected credit loss moved over the last eight "
            "quarters?", capability="ANALYSIS")),
    _c("hold-per-3", UNSEEN_PERIOD, "A period the data does not have",
       Turn("What was total exposure at default in Q1 2015?",
            outcome="CLARIFY", forbidden=("ANALYSIS",), critical=True)),

    # -------------------------------------------------- aliases not seen
    _c("hold-ali-1", UNSEEN_ALIAS, "Provisions, meaning ECL",
       Turn("How have provisions moved over the latest year?",
            capability="ANALYSIS", concepts=("expected credit loss",))),
    _c("hold-ali-2", UNSEEN_ALIAS, "Arrears, meaning days past due",
       Turn("Which customers went into arrears over the latest year?",
            capability="ANALYSIS", concepts=("days past due",))),
    _c("hold-ali-3", UNSEEN_ALIAS, "Gearing, meaning leverage",
       Turn("Which customers have worsening gearing?",
            capability="ANALYSIS", concepts=("net leverage",))),

    # ------------------------------------------------------- adversarial
    _c("hold-adv-1", ADVERSARIAL, "Exposure with no qualifier",
       Turn("What is our exposure to Real Estate?", outcome="CLARIFY",
            forbidden=("ANALYSIS",), critical=True)),
    _c("hold-adv-2", ADVERSARIAL, "A sector name that is also a verb",
       Turn("Show Contracting customers whose ECL rose over the latest year.",
            capability="ANALYSIS", invariants=("filter_equality",),
            critical=True)),
    _c("hold-adv-3", ADVERSARIAL, "A dataset name inside an analysis",
       Turn("What is total EAD by sector in the watchlist register?",
            capability="ANALYSIS")),
    _c("hold-adv-4", ADVERSARIAL, "A count, not a ranking",
       Turn("How many Real Estate customers are there?",
            capability="ANALYSIS", forbidden=("row_limit",))),

    # -------------------------------------------------- scope, in orders
    _c("hold-sco-1", SCOPE, "Narrow, then widen, then narrow",
       Turn("Show the ten largest customers by exposure at default.",
            capability="ANALYSIS", invariants=("row_limit",)),
       Turn("Only Contracting.", action="MODIFY_PREVIOUS"),
       Turn("Now compare all sectors.", action="WIDEN_SCOPE"),
       Turn("Just Healthcare.", action="MODIFY_PREVIOUS")),
    _c("hold-sco-2", SCOPE, "Reset in the middle of a thread",
       Turn("Which customers had a rating downgrade over the latest year?",
            capability="ANALYSIS"),
       Turn("Only Contracting.", action="MODIFY_PREVIOUS"),
       Turn("Forget those — what is total ECL across the whole book?",
            action="RESET_SCOPE", critical=True)),
    _c("hold-sco-3", SCOPE, "A measure swap after two narrowings",
       Turn("Show the twenty largest customers by exposure at default.",
            capability="ANALYSIS"),
       Turn("Only Real Estate.", action="MODIFY_PREVIOUS"),
       Turn("Rank them by ECL instead.", action="MODIFY_PREVIOUS")),

    # ----------------------------------------------------------- boundary
    _c("hold-bnd-1", BOUNDARY, "A threshold on a ratio",
       Turn("Which customers have covenant headroom below 15%?",
            capability="ANALYSIS", invariants=("condition",), critical=True)),
    _c("hold-bnd-2", BOUNDARY, "A threshold with a movement in the same "
       "sentence",
       Turn("Which customers have covenant headroom below 20% and an "
            "increase in ECL?", capability="ANALYSIS",
            invariants=("condition",), critical=True)),
    _c("hold-bnd-3", BOUNDARY, "A magnitude on a movement",
       Turn("Which customers had ECL rise more than 50% over the latest "
            "year?", capability="ANALYSIS", invariants=("condition",))),
    _c("hold-bnd-4", BOUNDARY, "A notch threshold on an ordinal scale",
       Turn("Which customers were downgraded at least two notches?",
            capability="ANALYSIS", invariants=("condition",))),

    # ---------------------------------------------------------- compound
    _c("hold-cmp-1", COMPOUND, "Three objectives across three capabilities",
       Turn("What datasets cover covenants, how many periods do they have, "
            "and how do they join to the facility book?",
            datasets=("covenant_tests", "portfolio_facility"))),
    _c("hold-cmp-2", COMPOUND, "A calculation and a classification",
       Turn("What is total EAD by sector, and which sectors are above 10% of "
            "the book?", capability="ANALYSIS")),

    # ---------------------------------------------------------- investigate
    _c("hold-brd-1", BROAD, "Investigate a region",
       Turn("Something looks off in Tabuk. Look into it.",
            capability="ANALYSIS")),
    _c("hold-brd-2", BROAD, "Investigate with no population named",
       Turn("Investigate it.", outcome="CLARIFY", forbidden=("ANALYSIS",),
            critical=True)),

    # ================================================================
    # 1.1.0 — written to make the evidence base large enough to certify.
    # Same kinds, no case reused, entities and phrasings the curriculum
    # does not contain.
    # ================================================================

    # ------------------------------------------------- entities not seen
    _c("hold-ent-4", UNSEEN_ENTITY, "A sector by its full governed name",
       Turn("What is total exposure at default in Mining & Metals?",
            capability="ANALYSIS", invariants=("filter_equality",))),
    _c("hold-ent-5", UNSEEN_ENTITY, "A segment rather than a sector",
       Turn("What is total exposure at default for SME customers?",
            capability="ANALYSIS", invariants=("filter_equality",))),
    _c("hold-ent-6", UNSEEN_ENTITY, "A product type",
       Turn("How much exposure at default sits in Project Finance?",
            capability="ANALYSIS", invariants=("filter_equality",))),
    _c("hold-ent-7", UNSEEN_ENTITY, "A rating bucket nothing carries",
       Turn("What is total expected credit loss for Watch customers?",
            outcome="CLARIFY", forbidden=("ANALYSIS",), critical=True)),
    _c("hold-ent-8", UNSEEN_ENTITY, "Two sectors in one request",
       Turn("Compare exposure at default in Utilities and Education.",
            capability="ANALYSIS")),
    _c("hold-ent-9", UNSEEN_ENTITY, "A region the curriculum never names",
       Turn("What is total exposure at default in Najran?",
            capability="ANALYSIS", invariants=("filter_equality",))),
    _c("hold-ent-10", UNSEEN_ENTITY, "A sector that does not exist",
       Turn("What is total exposure at default in Cryptocurrency?",
            outcome="CLARIFY", forbidden=("ANALYSIS",), critical=True)),

    # ------------------------------------------------- periods not seen
    _c("hold-per-4", UNSEEN_PERIOD, "A quarter at the start of the history",
       Turn("What was total expected credit loss in Q1 2023?",
            capability="ANALYSIS", concepts=("expected credit loss",))),
    _c("hold-per-5", UNSEEN_PERIOD, "A future quarter",
       Turn("What was total exposure at default in Q3 2031?",
            outcome="CLARIFY", forbidden=("ANALYSIS",), critical=True)),
    _c("hold-per-6", UNSEEN_PERIOD, "A bare year the data does not reach",
       Turn("What was total exposure at default in 2011?",
            outcome="CLARIFY", forbidden=("ANALYSIS",), critical=True)),
    _c("hold-per-7", UNSEEN_PERIOD, "A six-month window",
       Turn("How has exposure at default moved over the last two quarters?",
            capability="ANALYSIS")),
    _c("hold-per-8", UNSEEN_PERIOD, "A window opened with 'since'",
       Turn("How has expected credit loss moved since Q1 2024?",
            capability="ANALYSIS")),

    # -------------------------------------------------- aliases not seen
    _c("hold-ali-4", UNSEEN_ALIAS, "Impairment, meaning ECL",
       Turn("What is total impairment across the book?",
            capability="ANALYSIS", concepts=("expected credit loss",))),
    _c("hold-ali-5", UNSEEN_ALIAS, "Utilisation, meaning drawn exposure",
       Turn("Which customers have the highest drawn exposure?",
            capability="ANALYSIS")),
    _c("hold-ali-6", UNSEEN_ALIAS, "Interest cover, meaning interest coverage",
       Turn("Which customers have interest cover below 2x?",
            capability="ANALYSIS", invariants=("condition",))),
    _c("hold-ali-7", UNSEEN_ALIAS, "Grade, meaning internal rating",
       Turn("What is exposure at default by rating grade?",
            capability="ANALYSIS")),
    _c("hold-ali-8", UNSEEN_ALIAS, "Overdue, meaning days past due",
       Turn("Which customers are more than 90 days overdue?",
            capability="ANALYSIS")),

    # ------------------------------------------------------- adversarial
    _c("hold-adv-5", ADVERSARIAL, "A bare measure with no qualifier",
       Turn("Show me the book.", outcome="CLARIFY",
            forbidden=("ANALYSIS",), critical=True)),
    _c("hold-adv-6", ADVERSARIAL, "A word that is a concept and a dimension",
       Turn("What is total exposure at default by stage?",
            capability="ANALYSIS")),
    _c("hold-adv-7", ADVERSARIAL, "A dataset asked about, not from",
       Turn("What fields are in the covenant testing data?",
            capability="DATA_DICTIONARY", forbidden=("ANALYSIS",))),
    _c("hold-adv-8", ADVERSARIAL, "A method named inside a question",
       Turn("How does sector concentration work?",
            capability="METHOD_EXPLANATION", forbidden=("ANALYSIS",))),
    _c("hold-adv-9", ADVERSARIAL, "A count where a ranking is tempting",
       Turn("How many customers are in Stage 3?", capability="ANALYSIS",
            forbidden=("row_limit",))),
    _c("hold-adv-10", ADVERSARIAL, "Something the bank does not hold",
       Turn("Which borrowers are being sued by their suppliers?",
            outcome="UNSUPPORTED", forbidden=("ANALYSIS", "CLARIFY"),
            critical=True)),
    _c("hold-adv-11", ADVERSARIAL, "A question about nothing in the domain",
       Turn("What is the weather forecast for next week?",
            outcome="UNSUPPORTED", forbidden=("ANALYSIS",), critical=True)),

    # -------------------------------------------------- scope, in orders
    _c("hold-sco-4", SCOPE, "Widen first, then narrow twice",
       Turn("What is total exposure at default in Manufacturing?",
            capability="ANALYSIS", invariants=("filter_equality",)),
       Turn("Now compare all sectors.", action="WIDEN_SCOPE"),
       Turn("Only Utilities.", action="MODIFY_PREVIOUS")),
    _c("hold-sco-5", SCOPE, "A presentation change in the middle",
       Turn("What is total exposure at default by sector?",
            capability="ANALYSIS"),
       Turn("Show it as a chart.", action="MODIFY_PRESENTATION"),
       Turn("Only Telecommunications.", action="MODIFY_PREVIOUS")),
    _c("hold-sco-6", SCOPE, "A size change after a narrowing",
       Turn("Show the ten largest customers by expected credit loss.",
            capability="ANALYSIS", invariants=("row_limit",)),
       Turn("Only Transport & Logistics.", action="MODIFY_PREVIOUS"),
       Turn("Show the three largest.", action="MODIFY_PREVIOUS")),
    _c("hold-sco-7", SCOPE, "A metadata question mid-analysis",
       Turn("Show the five largest Hospitality & Tourism customers by "
            "exposure at default.", capability="ANALYSIS",
            invariants=("row_limit", "filter_equality")),
       Turn("What fields does the facility book carry?",
            capability="DATA_DICTIONARY")),
    _c("hold-sco-8", SCOPE, "A reset that names a different measure",
       Turn("What is total exposure at default in Agriculture & Food?",
            capability="ANALYSIS"),
       Turn("Forget that — what is total expected credit loss by region?",
            action="RESET_SCOPE", critical=True)),

    # ----------------------------------------------------------- boundary
    _c("hold-bnd-5", BOUNDARY, "A threshold above rather than below",
       Turn("Which customers have net leverage above 4x?",
            capability="ANALYSIS", invariants=("condition",), critical=True)),
    _c("hold-bnd-6", BOUNDARY, "An at-least threshold",
       Turn("Which customers have covenant headroom of at least 25%?",
            capability="ANALYSIS", invariants=("condition",))),
    _c("hold-bnd-7", BOUNDARY, "A threshold on days",
       Turn("Which customers are more than 30 days past due?",
            capability="ANALYSIS", invariants=("condition",))),
    _c("hold-bnd-8", BOUNDARY, "A decrease, not an increase",
       Turn("Which customers had expected credit loss fall over the latest "
            "year?", capability="ANALYSIS")),
    _c("hold-bnd-9", BOUNDARY, "A window written as a number of months",
       Turn("Which customers had an increase in ECL over the latest 6 "
            "months?", capability="ANALYSIS")),
    _c("hold-bnd-10", BOUNDARY, "A threshold and a filter together",
       Turn("Which Contracting customers have covenant headroom below 10%?",
            capability="ANALYSIS",
            invariants=("condition", "filter_equality"), critical=True)),

    # ---------------------------------------------------------- compound
    _c("hold-cmp-3", COMPOUND, "A total and a breakdown",
       Turn("What is total exposure at default, and how does it split by "
            "segment?", capability="ANALYSIS")),
    _c("hold-cmp-4", COMPOUND, "Two measures on one table",
       Turn("Show exposure at default and expected credit loss by sector.",
            capability="ANALYSIS")),
    _c("hold-cmp-5", COMPOUND, "A field list and a classification",
       Turn("What fields are in the facility book, and which of them are "
            "monetary amounts?", capability="DATA_DICTIONARY"),
       Turn("You missed the second part.",
            action="CORRECT_INCOMPLETE_RESPONSE")),
    _c("hold-cmp-6", COMPOUND, "A ranking and a threshold",
       Turn("Show the ten largest customers by exposure at default, and "
            "which of them are in Stage 2?", capability="ANALYSIS",
            invariants=("row_limit",))),

    # ---------------------------------------------------------- investigate
    _c("hold-brd-3", BROAD, "Investigate a sector",
       Turn("Something looks wrong in Petrochemicals. Look into it.",
            capability="ANALYSIS")),
    _c("hold-brd-4", BROAD, "A vague request with a population",
       Turn("What should I worry about in Real Estate?",
            capability="ANALYSIS")),
    _c("hold-brd-5", BROAD, "Investigate after a result",
       Turn("Show the five largest Mining & Metals customers by exposure at "
            "default.", capability="ANALYSIS",
            invariants=("row_limit", "filter_equality")),
       Turn("Investigate those.", capability="ANALYSIS")),
    _c("hold-brd-6", BROAD, "A deterioration question with no measure",
       Turn("What has deteriorated over the latest year?",
            capability="ANALYSIS")),
)

#: Expectations revised after a run, with why. Published on the manifest.
#:
#: Each entry names a case, what it used to require, and the fact about the
#: governed data that made that requirement impossible to satisfy correctly.
#: A reader who disagrees with a revision can see precisely what was changed.
CORRECTIONS: tuple[dict[str, str], ...] = (
    {"case": "hold-ent-7",
     "was": "EXECUTE, filtering total ECL to rating bucket 'Watch'",
     "now": "CLARIFY, and an analysis is forbidden",
     "why": "No governed dataset carries a rating_bucket column. The "
            "vocabulary advertises the dimension, the catalogue cannot filter "
            "on it, and the only correct answers are to bring it in through a "
            "relationship a steward has not declared, or to say so. The "
            "original expectation asked for a filter that cannot be applied, "
            "and the product answering it would have meant answering about the "
            "whole book — which is what it used to do, and what this case "
            "found."},
    {"case": "hold-cmp-1",
     "was": "EXECUTE as DATA_DISCOVERY",
     "now": "EXECUTE, with no single capability required",
     "why": "The question asks three things spanning three capabilities — "
            "which datasets, how many periods, and how they join. The answer "
            "covers all three; naming one of them as the correct reading made "
            "a complete answer score as a miss. The case still requires the "
            "datasets and an executed answer."},
)

BY_ID: dict[str, Case] = {c.id: c for c in CASES}


def by_kind(kind: str) -> list[Case]:
    return [c for c in CASES if c.kind == kind]


def critical() -> list[Case]:
    return [c for c in CASES if c.critical]


def coverage() -> dict[str, int]:
    return {kind: len(by_kind(kind)) for kind in KINDS}


def turn_count() -> int:
    return sum(len(c.turns) for c in CASES)


__all__ = ["BY_ID", "CASES", "CORRECTIONS", "HOLDOUT_VERSION", "KINDS", "Case", "Turn",
           "by_kind", "coverage", "critical", "turn_count"]
