"""
The failure taxonomy. §34.

Why the list is closed
----------------------
    "Use taxonomy in UI and evaluation."

Both halves of that sentence need the same twenty-four names. A review queue
whose categories are free text produces "wrong answer" four hundred times and
answers no question anybody has; an evaluation whose categories are inferred
from the failing check produces categories nobody can act on. So the list is
here, once, closed, and both surfaces read it.

The taxonomy is about WHERE, not how badly
-------------------------------------------
Each category names the stage a failure belongs to — the reading, the plan, the
query, the invariants, the interpretation. That is deliberate: severity varies
with the question and the audience, and a taxonomy that mixed the two would
make "PLAN, high" and "PLAN, low" different categories. Severity lives on the
finding; the category lives here.

Three of them are not defects
------------------------------
UNSUPPORTED, CONTROLLED_FAILURE and COST_BUDGET record a product behaving
correctly under a constraint. They are in the taxonomy because they have to be
counted — a run that abstains a hundred times is telling you something — and
`DEFECTS` is the subset that means something is wrong. An accuracy figure that
counted a correct abstention as a failure would push the product towards
answering questions it should decline.
"""

from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "1.0.0"

# ---------------------------------------------------------------- the stages
READING = "reading"
DATA = "data"
PLANNING = "planning"
EXECUTION_STAGE = "execution"
ANSWER = "answer"
GOVERNANCE = "governance"
CONSTRAINT = "constraint"

STAGES: tuple[str, ...] = (READING, DATA, PLANNING, EXECUTION_STAGE, ANSWER,
                           GOVERNANCE, CONSTRAINT)


@dataclass(frozen=True)
class Category:
    """One place a run can go wrong, and what it looks like when it does."""

    id: str
    stage: str
    label: str
    #: What a reviewer is looking at when they choose this. Written as the
    #: observation, not the cause: "the answer omitted a clause" is something
    #: somebody can see, and "the decomposer under-split" is a diagnosis.
    looks_like: str
    #: False for the three that record correct behaviour under a constraint.
    defect: bool = True


CATEGORIES: tuple[Category, ...] = (
    # ---- reading -----------------------------------------------------------
    Category("INTENT", READING, "Intent",
             "The request was read as the wrong kind of thing — a catalogue "
             "question answered with an analysis, or the reverse."),
    Category("SAME_TURN_COREFERENCE", READING, "Same-turn coreference",
             "A pronoun whose antecedent was in the same sentence was "
             "resolved to the whole book, or to nothing."),
    Category("MULTI_TURN_CONTEXT", READING, "Multi-turn context",
             "A follow-up lost, kept or reset the previous population when it "
             "should have done one of the other two."),
    Category("OBJECTIVE_OMISSION", READING, "Objective omission",
             "The request asked for several things and the answer settled "
             "some of them without saying so."),
    Category("CONCEPT", READING, "Concept",
             "A governed concept was resolved to the wrong measure, or to a "
             "column name instead of a concept."),
    Category("AMBIGUITY", READING, "Ambiguity",
             "A genuinely ambiguous request was answered on a guess, or an "
             "unambiguous one was sent back for clarification."),

    # ---- data --------------------------------------------------------------
    Category("DATASET", DATA, "Dataset",
             "The analysis read the wrong governed dataset, or invented one."),
    Category("RELATIONSHIP", DATA, "Relationship",
             "Two datasets were joined along a path the Data Builder does not "
             "declare."),
    Category("PERIOD", DATA, "Period",
             "The periods on the two sides of a comparison were not the same, "
             "or a stated window was silently widened."),
    Category("GRAIN", DATA, "Grain",
             "Facility, borrower and portfolio rows were mixed, or a borrower "
             "attribute multiplied its facilities into a total."),

    # ---- planning and execution -------------------------------------------
    Category("PLAN", PLANNING, "Plan",
             "The plan does not answer the request it was built for, even "
             "where every step in it is individually valid."),
    Category("QUERY", EXECUTION_STAGE, "Query",
             "The compiled query does not implement the plan."),
    Category("EXECUTION", EXECUTION_STAGE, "Execution",
             "The run failed while computing — a kernel error, a timeout, a "
             "missing partition."),
    Category("INVARIANT", EXECUTION_STAGE, "Invariant",
             "The result violated a business invariant: a share outside "
             "bounds, components that do not reconcile, a total that moved."),

    # ---- the answer --------------------------------------------------------
    Category("GROUNDING", ANSWER, "Grounding",
             "The prose asserted something the computed result does not "
             "contain."),
    Category("INTERPRETATION", ANSWER, "Interpretation",
             "The interpretation was wrong, or claimed cause where the data "
             "supports only association."),
    Category("VISUALIZATION", ANSWER, "Visualization",
             "The chart misrepresents the result's shape, or a chart was "
             "drawn where none should have been."),
    Category("TRACE", ANSWER, "Trace",
             "The Trace disagrees with what actually ran — a skipped check "
             "shown as passed, a failed step in a green stage."),

    # ---- governance --------------------------------------------------------
    Category("SCOPE", GOVERNANCE, "Scope",
             "A corporate question was answered with retail semantics, or the "
             "reverse."),
    Category("PERMISSION", GOVERNANCE, "Permission",
             "Something was shown to somebody not entitled to see it, or "
             "withheld from somebody who was."),
    Category("PROVIDER", GOVERNANCE, "Provider",
             "The model provider failed, refused, or served a different model "
             "from the configured one."),

    # ---- correct behaviour under a constraint ------------------------------
    Category("UNSUPPORTED", CONSTRAINT, "Unsupported",
             "The data is genuinely not held and CreditProbe said so.",
             defect=False),
    Category("CONTROLLED_FAILURE", CONSTRAINT, "Controlled failure",
             "Something broke and the failure was reported rather than "
             "papered over.", defect=False),
    Category("COST_BUDGET", CONSTRAINT, "Cost budget",
             "The turn's model budget stopped work that would otherwise have "
             "continued.", defect=False),
)

BY_ID: dict[str, Category] = {c.id: c for c in CATEGORIES}
IDS: tuple[str, ...] = tuple(c.id for c in CATEGORIES)

#: The subset that means something is wrong. An accuracy figure counting a
#: correct abstention as a failure would push the product towards answering
#: questions it should decline.
DEFECTS: frozenset[str] = frozenset(c.id for c in CATEGORIES if c.defect)

#: Failures that make an answer unshowable however good the rest of the run
#: was. §30 requires zero critical regressions before a model may be adopted,
#: and this is what "critical" means.
CRITICAL: frozenset[str] = frozenset({
    "GROUNDING",      # prose asserting something the result does not contain
    "INVARIANT",      # a figure that does not reconcile
    "GRAIN",          # a double-counted total
    "RELATIONSHIP",   # a join nobody declared
    "PERMISSION",     # something shown to the wrong person
    "SCOPE",          # retail semantics on a corporate answer
    "TRACE",          # a Trace that disagrees with what ran
})


def get(category_id: str) -> Category | None:
    return BY_ID.get(str(category_id or "").strip().upper())


def known(category_id: str) -> bool:
    return get(category_id) is not None


def in_stage(stage: str) -> tuple[Category, ...]:
    return tuple(c for c in CATEGORIES if c.stage == stage)


def is_defect(category_id: str) -> bool:
    """Whether this category means something went wrong.

    An unknown category counts as a defect. Same reasoning as every other
    unknown in this codebase: a value nobody recognises must not be the one
    that quietly improves the score.
    """
    found = get(category_id)
    return found.defect if found else True


def is_critical(category_id: str) -> bool:
    return str(category_id or "").strip().upper() in CRITICAL


def tally(categories: list[str]) -> dict[str, int]:
    """How many of each. Every category appears, including the zeroes — a
    taxonomy reported only where it fired cannot show what is not happening."""
    counts = {name: 0 for name in IDS}
    for name in categories:
        key = str(name or "").strip().upper()
        counts[key] = counts.get(key, 0) + 1
    return counts


def summary(categories: list[str]) -> dict[str, int]:
    counts = tally(categories)
    return {
        "total": sum(counts.values()),
        "defects": sum(v for k, v in counts.items() if is_defect(k)),
        "critical": sum(v for k, v in counts.items() if is_critical(k)),
        "constrained": sum(v for k, v in counts.items() if not is_defect(k)),
    }


__all__ = ["BY_ID", "CATEGORIES", "CRITICAL", "DEFECTS", "IDS", "STAGES",
           "TAXONOMY_VERSION", "Category", "get", "in_stage", "is_critical",
           "is_defect", "known", "summary", "tally"]
