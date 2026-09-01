"""
The complex-query curriculum. P0.6.

    "Do not call three random cases 'high accuracy.'"

That is P0.7's sentence, and it is what this module exists to make impossible.
The development curriculum in `curriculum.py` has thirty-three hand-written
threads covering twenty-five families — enough to catch a regression, nowhere
near enough to support a claim about how CreditProbe handles hard questions.
P0.6 names twelve categories and a minimum count for each, and the counts are
large on purpose: a category with five cases produces a percentage that moves
twenty points when one case flips.

Written, generated, and the difference
--------------------------------------
Each category here has a small number of REVIEWED TEMPLATES — a sentence shape
with a specification of what a correct answer must do — and the cases are the
templates instantiated over the governed vocabulary: real sectors, real
measures, real periods, real dataset names, read from the ontology rather than
typed here.

That is a deliberate choice, and the honest description of it is: the
*specification* of every case is reviewed, the *subject* of each case is
governed, and the *phrasing* is generated. Writing nine hundred sentences by
hand would produce nine hundred variations on one person's phrasing and a
specification copied nine hundred times, which is worse in both halves.

What a case never carries is the ANSWER. Every expectation here is a statement
about what the product must DO — which concept it must resolve, which clause it
must not drop, which chart it must not draw, whether it must abstain. A stored
answer is a number somebody quietly aligns to whatever the product returns; a
specification cannot be satisfied by changing the product's mind.

Sealed holdout
--------------
Nothing here is sealed — this is the OPEN library, and prompts may be tuned
against it. `holdout.py` stays sealed and unchanged, and the import-graph test
that enforces the separation covers this module too, because it is imported by
the same package.

No production data
------------------
Every borrower, sector and figure referenced here comes from the synthetic
Saudi universe. P0.6 requires it, and it is also the only way this file can be
committed to a public branch.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from intelligence_factory.curriculum import Case, Turn

COMPLEX_CURRICULUM_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# The twelve categories, and the minimum P0.6 sets for each
# ---------------------------------------------------------------------------

SAME_TURN = "same-turn referent"
MULTI_CLAUSE = "multi-clause objective"
COHORT = "cohort comparison"
SCREEN = "multi-domain borrower screen"
INVESTIGATION = "portfolio investigation"
DECOMPOSITION = "ECL decomposition"
CAUSATION = "association vs causation"
ALIGNMENT = "period and population alignment"
CHART = "chart selection"
TRACE = "agentic Trace consistency"
ABSTENTION = "unsupported and abstention"
ERRORS = "error control"

#: The counts P0.6 names. Held as data so the test that checks them reads the
#: same numbers the generator does, and a category that quietly shrinks fails
#: rather than passing with a smaller sample.
REQUIRED: dict[str, int] = {
    SAME_TURN: 150,
    MULTI_CLAUSE: 150,
    COHORT: 100,
    SCREEN: 100,
    INVESTIGATION: 100,
    DECOMPOSITION: 75,
    CAUSATION: 75,
    ALIGNMENT: 75,
    CHART: 75,
    TRACE: 50,
    ABSTENTION: 50,
    ERRORS: 50,
}

CATEGORIES: tuple[str, ...] = tuple(REQUIRED)


# ---------------------------------------------------------------------------
# The governed vocabulary the cases are built over
# ---------------------------------------------------------------------------

#: Sectors from the synthetic universe. Named here rather than read from the
#: lake so the curriculum is the same on a machine that has not built it — a
#: corpus whose size depends on whether the data is present is a corpus whose
#: score is not comparable between runs.
SECTORS: tuple[str, ...] = (
    "Contracting", "Real Estate", "Manufacturing", "Wholesale & Retail Trade",
    "Hospitality & Tourism", "Transport & Logistics", "Healthcare",
    "Education", "Utilities", "Petrochemicals", "Agriculture", "Telecom",
)

SEGMENTS: tuple[str, ...] = ("Corporate", "SME", "Retail",
                             "Financial Institutions")

PERIODS: tuple[str, ...] = (
    "Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026")

#: The measures cases are built over, as (label, label): the phrase a user
#: would write IS the label the reading records, so a case asserts the thing
#: the product actually carries. Read from the ontology, so a concept that is
#: renamed breaks the curriculum rather than silently producing cases nothing
#: can satisfy.
#:
#: Split by what a sentence can legitimately do with them. "Total ECL coverage"
#: is not a sentence anybody writes, and a corpus full of questions no credit
#: officer would ask measures how the product handles questions no credit
#: officer would ask.
def _split() -> tuple[tuple[tuple[str, str], ...], ...]:
    from backend.semantics import ontology as on

    wanted = ("ecl", "ead", "exposure", "ecl_coverage", "dscr", "leverage",
              "utilisation", "dpd", "rating", "stage", "pd_12m",
              "covenant_headroom", "collateral", "limit", "arrears",
              "raroc", "interest_cover", "margin")
    plain: list[tuple[str, str]] = []
    additive: list[tuple[str, str]] = []
    rate: list[tuple[str, str]] = []
    for contract in on.contracts():
        if contract.concept_id not in wanted:
            continue
        # An ambiguous measure would make every case a clarification case,
        # which is a different category with its own cases.
        if contract.ambiguity is not None:
            continue
        pair = (contract.business_name.lower(), contract.business_name.lower())
        plain.append(pair)
        # "Total X" needs a measure that adds up. Summing a ratio is the type
        # error the ontology exists to refuse, so a case must not ask for it.
        if contract.permits(on.SUM) and not contract.is_categorical:
            additive.append(pair)
        if contract.is_ratio:
            rate.append(pair)
    return tuple(plain), tuple(additive), tuple(rate)


PLAIN, ADDITIVE, RATIOS = _split()
MEASURES = PLAIN


def _pick(items: tuple[Any, ...], seed: str, offset: int = 0) -> Any:
    """A deterministic choice from `items`.

    Hash-based rather than random, so the corpus is identical on every machine
    and adding a category does not reshuffle the ones before it. A curriculum
    whose cases move between runs produces scores that cannot be compared.
    """
    digest = hashlib.sha256(f"{seed}:{offset}".encode()).digest()
    return items[int.from_bytes(digest[:4], "big") % len(items)]


# ---------------------------------------------------------------------------
# The templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    """One reviewed sentence shape, and what a correct answer must do.

    `build` receives a seed and returns the turns. Everything a case asserts
    lives here, reviewed once, rather than being copied across a hundred
    generated cases where a correction would have to be made a hundred times.
    """

    key: str
    category: str
    title: str
    build: Any


def _same_turn(seed: str) -> list[Turn]:
    """A pronoun or head noun whose antecedent is in the SAME message.

    The defect this category exists for: "Show me customers whose DSCR fell
    below 1.2 and tell me which of them are in Contracting" was answered about
    the whole book, because referent resolution only looked at earlier TURNS.
    """
    sector = _pick(SECTORS, seed, 1)
    measure, concept = _pick(PLAIN, seed, 2)
    shape = _pick(("which of them are", "how many of those are",
                   "which of these are", "tell me which of them are"), seed, 3)
    # A neutral verb, because the point of this category is the REFERENT and
    # not the predicate. "Approved limit deteriorated" is not a sentence a
    # credit officer writes, and a corpus of sentences nobody writes measures
    # how the product handles sentences nobody writes.
    moved = _pick(("moved the most", "changed the most", "moved against us",
                   "shifted most"), seed, 4)
    return [Turn(
        question=(f"Show me the customers whose {measure} {moved} over the "
                  f"latest year, and {shape} in {sector}."),
        capability="ANALYSIS", concepts=(concept,),
        # The whole point: the answer must be about the cohort the first
        # clause defined, never about the book.
        forbidden=("whole_portfolio", "CLARIFY"))]


def _multi_clause(seed: str) -> list[Turn]:
    """Two or more objectives in one message, all of which must be settled.

    P0.3's rule, as a corpus: "Do not display a final answer while silently
    omitting objectives." A case passes only if every clause is addressed.
    """
    sector = _pick(SECTORS, seed, 1)
    first, concept_a = _pick(ADDITIVE, seed, 2)
    second, concept_b = _pick(PLAIN, seed, 3)
    return [Turn(
        question=(f"For {sector}, calculate total {first}, rank the borrowers "
                  f"by {second}, and say which of them moved the most over "
                  f"the last year."),
        capability="ANALYSIS", concepts=(concept_a, concept_b),
        invariants=("filter_equality",),
        forbidden=("partial_objectives",))]


def _cohort(seed: str) -> list[Turn]:
    """Two populations compared, where the comparison is the answer."""
    left = _pick(SECTORS, seed, 1)
    right = _pick(SECTORS, seed, 2)
    if right == left:
        right = SECTORS[(SECTORS.index(left) + 1) % len(SECTORS)]
    measure, concept = _pick(PLAIN, seed, 3)
    return [Turn(
        question=(f"How does {measure} in {left} compare with {right} over "
                  f"the latest year?"),
        capability="ANALYSIS", concepts=(concept,),
        forbidden=("single_cohort",))]


def _screen(seed: str) -> list[Turn]:
    """A borrower screen spanning several governed domains at once."""
    first, concept_a = _pick(PLAIN, seed, 1)
    second, concept_b = _pick(PLAIN, seed, 2)
    segment = _pick(SEGMENTS, seed, 3)
    return [Turn(
        question=(f"Which {segment} borrowers have both a deteriorating "
                  f"{first} and a deteriorating {second}?"),
        capability="ANALYSIS", concepts=(concept_a, concept_b),
        # Two conditions means an intersection. Answering with either one
        # alone is a longer list and a different question.
        forbidden=("single_condition",))]


def _investigation(seed: str) -> list[Turn]:
    """An open question about a portfolio or segment, with no named measure."""
    subject = _pick(SECTORS + SEGMENTS, seed, 1)
    opening = _pick(("What is going on in", "What should I be worried about in",
                     "Give me a read on", "How is", "What has changed in",
                     "Walk me through", "Where is the risk in"), seed, 2)
    when = _pick(("", " this quarter", " over the last year",
                  " since the start of 2025", " right now",
                  " compared with a year ago"), seed, 3)
    return [Turn(
        question=f"{opening} {subject}{when}?",
        capability="ANALYSIS", action="NEW_REQUEST",
        # A broad question is answered by an investigation, not refused for
        # naming no measure and not answered with one arbitrary figure.
        forbidden=("UNSUPPORTED", "single_measure"))]


def _decomposition(seed: str) -> list[Turn]:
    """An ECL movement attributed to its drivers. P0.4's category."""
    scope = _pick(("", *(f" in {s}" for s in SECTORS),
                   *(f" for {g}" for g in SEGMENTS)), seed, 1)
    verb = _pick(("Decompose", "Attribute", "Bridge", "Walk me through",
                  "Break down"), seed, 2)
    window = _pick(("over the latest year", "over the latest quarter",
                    "between Q2 2025 and Q2 2026",
                    "since the start of 2025"), seed, 3)
    return [Turn(
        question=(f"{verb} the change in ECL{scope} {window} into exposure, "
                  "stage migration, PD, LGD and portfolio mix."),
        capability="ANALYSIS", concepts=("ecl",),
        invariants=("components_reconcile",),
        # The failure this category exists for: an ECL movement BY SECTOR,
        # which reports where the change landed rather than what caused it.
        forbidden=("movement_by_dimension", "CLARIFY"))]


def _causation(seed: str) -> list[Turn]:
    """A question that invites a causal claim the data cannot support."""
    measure, concept = _pick(PLAIN, seed, 1)
    other, concept_b = _pick(PLAIN, seed, 2)
    shape = _pick(("Does {a} cause {b}?",
                   "Why did {a} rise while {b} fell?",
                   "Is {a} driving {b}?",
                   "Prove that {a} explains {b}."), seed, 3)
    return [Turn(
        question=shape.format(a=measure, b=other),
        capability="ANALYSIS", concepts=(concept, concept_b),
        # The result shows what moved together, never why. "Consistent with"
        # is honest; "driven by" is not, unless the result carries the
        # attribution.
        forbidden=("causal_claim",))]


def _alignment(seed: str) -> list[Turn]:
    """A question whose two halves are about different periods or populations.

    The failure: comparing a Q2 2026 population against a Q2 2025 measure and
    reporting the difference as a movement.
    """
    early = _pick(PERIODS[:3], seed, 1)
    late = _pick(PERIODS[3:], seed, 2)
    measure, concept = _pick(PLAIN, seed, 3)
    return [Turn(
        question=(f"Compare {measure} for the customers who were in Stage 2 "
                  f"at {early} with where they are at {late}."),
        capability="ANALYSIS", concepts=(concept, "ifrs 9 stage"),
        # The population is fixed at the opening date and followed. Re-reading
        # it at the closing date answers a different question.
        forbidden=("population_drift",))]


def _chart(seed: str) -> list[Turn]:
    """A result whose only faithful picture is a particular kind — or none."""
    measure, concept = _pick(PLAIN, seed, 1)
    shape = _pick((
        ("Show {m} by sector as a chart.", "table_only"),
        ("Plot {m} over the last two years.", "categorical_axis"),
        ("Show me a heatmap of {m} by sector and quarter.", "measure_as_axis"),
        ("Show {m} for every customer as a bar chart.", "overplotting"),
        ("Show {m} and its percentage share on one chart.", "mixed_units"),
    ), seed, 2)
    return [Turn(
        question=shape[0].format(m=measure),
        capability="ANALYSIS", concepts=(concept,),
        # P0.11: a chart that does not say something true about the result is
        # replaced, and the replacement says why.
        forbidden=(shape[1],))]


def _trace(seed: str) -> list[Turn]:
    """An agentic run whose Trace must agree with what actually executed."""
    subject = _pick(SECTORS + SEGMENTS, seed, 1)
    shape = _pick(("Run a portfolio review of {s}.",
                   "Have an officer investigate {s}.",
                   "What does the agent make of {s}?",
                   "Review {s} and open cases where warranted.",
                   "Screen {s} for anything that needs attention."), seed, 2)
    return [Turn(
        question=shape.format(s=subject),
        capability="ANALYSIS",
        # P0.9: SKIPPED is not PASS. A stage may not report validated when
        # nothing was validated, and a failed Result stage blocks the run.
        forbidden=("validated_without_checks", "trace_disagrees"))]


def _abstention(seed: str) -> list[Turn]:
    """A question the governed universe holds nothing about.

    Answering a different question is worse than refusing, because it reads
    exactly like an answer.
    """
    subject = _pick((
        "the CEO's tenure at {s} borrowers",
        "how many staff our {s} clients employ",
        "the share price of our {s} borrowers",
        "which {s} borrowers have ISO certification",
        "the credit rating we will assign next quarter in {s}",
        "what our {s} competitors are pricing at",
    ), seed, 1)
    sector = _pick(SECTORS, seed, 2)
    return [Turn(
        question=f"What is {subject.format(s=sector)}?",
        outcome="UNSUPPORTED",
        forbidden=("ANALYSIS", "substituted_measure"))]


def _errors(seed: str) -> list[Turn]:
    """A request that must fail in a NAMED way rather than as a bare 500."""
    shape = _pick((
        "Show me {m} for Q9 2099.",
        "Show me {m} for the Nonexistent sector.",
        "Show me {m} joined to the payroll system.",
        "Show me {m} for customer ZZ-000000.",
        "Show me {m} at a grain of individual transactions.",
    ), seed, 1)
    measure, concept = _pick(PLAIN, seed, 2)
    return [Turn(
        question=shape.format(m=measure),
        concepts=(concept,),
        # P0.10: ten categories, a message a person can act on, and a
        # correlation id. Never an anonymous "something went wrong".
        forbidden=("uncategorised_failure", "stack_trace"))]


TEMPLATES: tuple[Template, ...] = (
    Template("same-turn", SAME_TURN,
             "A referent whose antecedent is in the same message", _same_turn),
    Template("multi-clause", MULTI_CLAUSE,
             "Several objectives in one message", _multi_clause),
    Template("cohort", COHORT, "Two populations compared", _cohort),
    Template("screen", SCREEN, "A borrower screen across domains", _screen),
    Template("investigation", INVESTIGATION,
             "An open question about a portfolio", _investigation),
    Template("decomposition", DECOMPOSITION,
             "An ECL movement attributed to drivers", _decomposition),
    Template("causation", CAUSATION,
             "A question inviting an unsupported causal claim", _causation),
    Template("alignment", ALIGNMENT,
             "Two halves about different periods or populations", _alignment),
    Template("chart", CHART, "A result with one faithful picture", _chart),
    Template("trace", TRACE, "A run whose Trace must match what executed",
             _trace),
    Template("abstention", ABSTENTION,
             "A question nothing governed can answer", _abstention),
    Template("errors", ERRORS, "A request that must fail in a named way",
             _errors),
)

_BY_CATEGORY: dict[str, Template] = {t.category: t for t in TEMPLATES}


# ---------------------------------------------------------------------------
# Building the corpus
# ---------------------------------------------------------------------------


def cases_for(category: str, count: int | None = None) -> list[Case]:
    """`count` cases in one category, deterministically.

    Duplicates are dropped rather than counted: a corpus that reports nine
    hundred cases and contains six hundred distinct questions is measuring six
    hundred things and claiming nine hundred.
    """
    template = _BY_CATEGORY.get(category)
    if template is None:
        raise KeyError(f"no template for category {category!r}")
    wanted = REQUIRED[category] if count is None else count

    out: list[Case] = []
    seen: set[str] = set()
    attempt = 0
    # Bounded so a template that cannot produce `wanted` distinct questions
    # fails visibly rather than looping. The test asserts the counts, so a
    # short category is a failure rather than a silent shortfall.
    while len(out) < wanted and attempt < wanted * 40:
        seed = f"{template.key}:{attempt}"
        attempt += 1
        turns = template.build(seed)
        signature = "|".join(t.question for t in turns)
        if signature in seen:
            continue
        seen.add(signature)
        out.append(Case(id=f"cx-{template.key}-{len(out) + 1:04d}",
                        family=category, title=template.title,
                        turns=list(turns)))
    return out


def cases() -> list[Case]:
    """The whole complex-query corpus, in category order."""
    out: list[Case] = []
    for category in CATEGORIES:
        out.extend(cases_for(category))
    return out


def coverage() -> dict[str, Any]:
    """What the corpus contains, for the release manifest.

    Reports the REQUIRED count beside the built one, so a category that falls
    short is visible in the manifest rather than only in a test.
    """
    built = {category: len(cases_for(category)) for category in CATEGORIES}
    return {
        "version": COMPLEX_CURRICULUM_VERSION,
        "categories": [
            {"category": category, "required": REQUIRED[category],
             "built": built[category], "meets": built[category] >= REQUIRED[category]}
            for category in CATEGORIES],
        "total_required": sum(REQUIRED.values()),
        "total_built": sum(built.values()),
        "complete": all(built[c] >= REQUIRED[c] for c in CATEGORIES),
        "templates": len(TEMPLATES),
        "synthetic_only": True,
    }


__all__ = [
    "ABSTENTION",
    "ALIGNMENT",
    "CATEGORIES",
    "CAUSATION",
    "CHART",
    "COHORT",
    "COMPLEX_CURRICULUM_VERSION",
    "DECOMPOSITION",
    "ERRORS",
    "INVESTIGATION",
    "MULTI_CLAUSE",
    "REQUIRED",
    "SAME_TURN",
    "SCREEN",
    "TEMPLATES",
    "TRACE",
    "Template",
    "cases",
    "cases_for",
    "coverage",
]
