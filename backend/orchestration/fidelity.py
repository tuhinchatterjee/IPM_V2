"""
What the question asked for, written down before anything runs.

The failure this exists to prevent
----------------------------------
    "Which Shipping borrowers have rising utilisation, worsening liquidity,
     and increasing 12-month PD?"

answered with an exposure-at-default movement analysis for Transport &
Logistics. Not a narrower answer, not a caveated one — a different question,
about a different population, measuring a different thing, presented as the
answer to this one.

The condition-coverage gate in `gate.py` cannot catch that. It compares the
predicates the reading produced with the predicates the plan applied, and a
plan that abandoned the question entirely has no predicates to be missing.
Something has to hold the ORIGINAL request, in the user's terms, and compare
the finished analysis against it.

The rule
--------
The planner may change IMPLEMENTATION. It may not change OBJECTIVE.

Joining three datasets instead of two, rolling a facility measure up to the
borrower, taking the governed default window — all implementation, all fine.
Answering a different question because that one is easier, or already
certified, or the only shape the resolver could build — never.

What is recorded
----------------
Nine things, all read from the question rather than from the plan:

    the original question
    the population it named
    the predicates it set
    the measures it named
    the output fields it asked for
    the ranking it asked for
    the period it named
    the analytical objective — what KIND of answer it wants
    supporting context it offered

Objectives are a closed set, because the check that matters is whether the
answer is the same KIND of thing that was asked for. A question asking which
borrowers meet three conditions wants a POPULATION; an answer reporting how a
sector's exposure moved is a MOVEMENT. Those are different objectives, and no
amount of correct arithmetic makes one the other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------- objectives
#
# What KIND of answer the question wants. Deliberately few and deliberately
# coarse: the check is not "did the plan do exactly what I would have done",
# it is "is this the same sort of answer at all".

POPULATION = "population"    #: which entities meet these conditions
RANKING = "ranking"          #: the top or bottom N by a measure
AGGREGATE = "aggregate"      #: a total or a breakdown
MOVEMENT = "movement"        #: how a measure moved between two dates
ASSOCIATION = "association"  #: whether two measures moved together
CATALOGUE = "catalogue"      #: a question about the data itself
PRODUCT = "product"          #: a question about CreditProbe itself
UNKNOWN = "unknown"

OBJECTIVES: tuple[str, ...] = (POPULATION, RANKING, AGGREGATE, MOVEMENT,
                               ASSOCIATION, CATALOGUE, PRODUCT, UNKNOWN)

#: How each objective reads in a sentence a person can check.
OBJECTIVE_MEANS: dict[str, str] = {
    POPULATION: "which borrowers meet the stated conditions",
    RANKING: "the largest or worst by a named measure",
    AGGREGATE: "a total, or a breakdown of one",
    MOVEMENT: "how a measure moved between two dates",
    ASSOCIATION: "whether two measures moved together",
    CATALOGUE: "what the governed data holds",
    PRODUCT: "what CreditProbe is or does",
    UNKNOWN: "not determined",
}

#: "Which borrowers …", "list the customers that …". A question naming
#: entities and conditions wants the entities back.
_WANTS_POPULATION = re.compile(
    r"\bwhich\s+(?:\w+\s+){0,3}?(?:borrowers?|customers?|clients?|"
    r"counterpart(?:y|ies)|obligors?|names?|facilities|accounts?|entities|"
    r"groups?|exposures?)\b"
    r"|\b(?:list|show|give|find|identify)\s+(?:me\s+)?(?:the\s+|all\s+)?"
    r"(?:\w+\s+){0,3}?(?:borrowers?|customers?|clients?|obligors?|names?)\b"
    r"|\bwho\s+(?:has|have|are|is|were|was)\b",
    re.IGNORECASE)

_WANTS_RANKING = re.compile(
    r"\b(?:top|bottom|largest|biggest|smallest|highest|lowest|worst|best|"
    r"first|last)\s+\d*\s*\w*\b|\brank(?:ed|ing)?\b|\bmost\s+\w+\b",
    re.IGNORECASE)

_WANTS_AGGREGATE = re.compile(
    r"\b(?:total|sum|average|mean|median|count|how many|how much|"
    r"aggregate|breakdown|split|distribution|share of)\b", re.IGNORECASE)

_WANTS_MOVEMENT = re.compile(
    r"\bhow\s+(?:much\s+)?(?:did|has|have)\b|\bmovement\b|\bchange in\b"
    r"|\bmoved\b|\bwaterfall\b|\bdecomposition\b|\bdrove\b|\bdriven by\b",
    re.IGNORECASE)

_WANTS_ASSOCIATION = re.compile(
    r"\bcorrelat\w*\b|\brelationship between\b|\bmove together\b"
    r"|\bassociated with\b", re.IGNORECASE)


@dataclass(frozen=True)
class Contract:
    """The request, in the terms the person used, before any plan exists."""

    question: str = ""
    #: The governed population the question named — sector, stage, rating band,
    #: a list of borrowers carried in from the thread.
    population: tuple[str, ...] = ()
    #: The conditions, in the person's own words.
    predicates: tuple[str, ...] = ()
    #: The measures named, whether filtered on or merely reported.
    measures: tuple[str, ...] = ()
    #: Fields the question asked to see.
    output_fields: tuple[str, ...] = ()
    #: The ordering asked for, where one was.
    ranking: str = ""
    #: The reporting period or window named, in the person's words.
    period: tuple[str, ...] = ()
    #: What KIND of answer this is.
    objective: str = UNKNOWN
    #: Anything offered as background rather than as a requirement.
    context: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "population": list(self.population),
            "predicates": list(self.predicates),
            "measures": list(self.measures),
            "output_fields": list(self.output_fields),
            "ranking": self.ranking,
            "period": list(self.period),
            "objective": self.objective,
            "objective_means": OBJECTIVE_MEANS.get(self.objective, ""),
            "context": list(self.context),
        }


@dataclass(frozen=True)
class Divergence:
    """One way the finished analysis is not the analysis that was asked for."""

    kind: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail}


@dataclass(frozen=True)
class Verdict:
    """Whether the executed plan answers the question that was asked."""

    contract: Contract = field(default_factory=Contract)
    executed_objective: str = UNKNOWN
    divergences: tuple[Divergence, ...] = ()

    @property
    def faithful(self) -> bool:
        return not self.divergences

    @property
    def sentence(self) -> str:
        """What went wrong, for a person rather than for a log."""
        if not self.divergences:
            return ""
        return " ".join(d.detail for d in self.divergences)

    def to_dict(self) -> dict[str, Any]:
        return {"contract": self.contract.to_dict(),
                "executed_objective": self.executed_objective,
                "faithful": self.faithful,
                "divergences": [d.to_dict() for d in self.divergences]}


# ------------------------------------------------------------------- reading it


def objective_of(question: str) -> str:
    """What KIND of answer a question wants.

    Order matters and is the credit-risk reading, not the grammatical one. A
    question naming entities and conditions wants those entities back even when
    it also contains the word "total" — "which borrowers have total exposure
    above 100m" is a population question with a threshold in it, and reading it
    as an aggregate answers with one number where a list was asked for.
    """
    said = str(question or "")
    if not said.strip():
        return UNKNOWN
    if _WANTS_POPULATION.search(said):
        return POPULATION
    if _WANTS_ASSOCIATION.search(said):
        return ASSOCIATION
    if _WANTS_RANKING.search(said):
        return RANKING
    if _WANTS_MOVEMENT.search(said):
        return MOVEMENT
    if _WANTS_AGGREGATE.search(said):
        return AGGREGATE
    return UNKNOWN


#: How the planner's own shapes map onto the objective a person asked for.
#: `analysis_planner` names four shapes; a cohort IS a population, a movement
#: with conditions is still a population question answered over a window.
_SHAPE_OBJECTIVE: dict[str, str] = {
    "cohort": POPULATION,
    "ranking": RANKING,
    "aggregate": AGGREGATE,
    "movement": MOVEMENT,
    "share_movement": MOVEMENT,
    "association": ASSOCIATION,
}


def executed_objective(build: Any) -> str:
    """What KIND of answer the finished plan actually produces."""
    shape = str(getattr(build, "shape", "") or "").lower()
    objective = _SHAPE_OBJECTIVE.get(shape, UNKNOWN)
    if objective == MOVEMENT and list(getattr(build, "conditions", None) or []):
        # A movement plan that FILTERS on its conditions returns the borrowers
        # meeting them, which is a population however the builder names it.
        return POPULATION
    return objective


def _governed_values() -> set[str]:
    """Every value of a governed dimension the vocabulary publishes.

    Read from the same vocabulary the planner resolves filters against, so the
    contract and the plan cannot disagree about what counts as a population.
    Read on every call rather than cached: a sector added to the book must be
    recognisable in a question the same day.
    """
    from backend.orchestration.vocabulary import get_vocabulary

    found: set[str] = set()
    for name, values in (get_vocabulary().dimensions or {}).items():
        if name in _POPULATION_FIELDS:
            found |= {str(v).strip() for v in values if str(v).strip()}
    return found


#: Dimensions whose values NAME a population. A question mentioning one of
#: these values is about that population, and an analysis that does not
#: restrict to it is answering a wider question.
_POPULATION_FIELDS = frozenset({
    "sector", "industry", "segment", "region", "country", "rating_bucket",
    "grade_band", "product_type", "ifrs9_stage", "collections_stage",
})


def _population_in(question: str, *, reading: Any = None,
                   state: Any = None) -> tuple[str, ...]:
    """The governed population a question names, in the person's own words.

    Read from the QUESTION as well as from the semantic reading. The reading is
    the better source when it is available, but a contract that only works
    when a reading was produced cannot check a plan that ignored the question —
    and that is exactly the case it exists for.
    """
    found: list[str] = []
    for entity in list(getattr(reading, "entities", None) or []):
        value = str(getattr(entity, "value", entity) or "").strip()
        if value:
            found.append(value)

    said = str(question or "")
    try:
        for value in _governed_values():
            if len(value) < 3:
                # A one- or two-character code matches inside ordinary words.
                continue
            if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", said, re.I) \
                    and value not in found:
                found.append(value)
    except Exception:  # noqa: BLE001 - a missing catalogue is not an error here
        pass

    if state is not None:
        for _, value in list(getattr(state, "filter_pairs", lambda: [])() or []):
            if value and str(value) not in found:
                found.append(str(value))
    return tuple(dict.fromkeys(found))


def read(question: str, *, reading: Any = None, state: Any = None) -> Contract:
    """The contract this question implies, before a plan exists.

    Built from the question and the semantic reading — never from the plan,
    which is the thing it exists to check.
    """
    from backend.orchestration import semantics as sm
    from backend.orchestration import temporal as tm

    said = str(question or "")
    period = tuple(tm.read(said).texts())

    population = _population_in(said, reading=reading, state=state)

    predicates: list[str] = []
    for clause in sm.clauses(said):
        if sm.find_movement(clause) is not None \
                or sm.find_threshold(clause) is not None:
            predicates.append(" ".join(clause.split()))

    measures = tuple(str(m) for m in
                     (list(getattr(reading, "metrics", None) or [])
                      or list(getattr(reading, "concepts", None) or [])))

    ranking = ""
    found = _WANTS_RANKING.search(said)
    if found:
        ranking = found.group(0).strip()

    return Contract(
        question=said,
        population=population,
        predicates=tuple(dict.fromkeys(predicates)),
        measures=tuple(dict.fromkeys(measures)),
        output_fields=(),
        ranking=ranking,
        period=period,
        objective=objective_of(said),
    )


# ------------------------------------------------------------------ checking it

#: Divergence kinds, so a caller can act on the reason rather than on the text.
OBJECTIVE_CHANGED = "objective_changed"
POPULATION_LOST = "population_lost"
POPULATION_WIDENED = "population_widened"
PERIOD_MOVED = "period_moved"
PREDICATE_INVENTED = "predicate_invented"


def _values_of(build: Any) -> set[str]:
    return {str(v).strip().lower()
            for _, v in (getattr(build, "filters", None) or []) if str(v).strip()}


def compare(contract: Contract, build: Any, *,
            enforcement: Any = None) -> Verdict:
    """Whether the finished plan answers the contract's question.

    Four checks, each of which the live acceptance failed at least once:

    * **The objective changed.** A population question answered with a sector
      movement. This is the check the Shipping defect needed and the one no
      other layer performs.
    * **The population was lost.** The question named Shipping and the plan
      filters on nothing, or on something else.
    * **The period moved.** The question named Q1 2026 and the plan measured a
      window that does not contain it.
    * **A predicate was invented.** The plan filters on a governed value the
      question never mentioned and the conversation never settled.

    A NARROWER answer is not a divergence — "which borrowers" answered at the
    borrower grain over the closing quarter of a named window is right. Only a
    different KIND of answer, or a different population, is.
    """
    found: list[Divergence] = []
    ran = executed_objective(build)

    wanted = contract.objective
    if wanted not in (UNKNOWN, ran) and ran != UNKNOWN:
        # POPULATION answered as RANKING is acceptable: a ranked list of the
        # borrowers meeting the conditions is still those borrowers, and the
        # ordering is a presentation choice. Everything else is a substitution.
        if not (wanted == POPULATION and ran == RANKING):
            found.append(Divergence(
                kind=OBJECTIVE_CHANGED,
                detail=(f"The question asks for {OBJECTIVE_MEANS[wanted]}, and "
                        f"the analysis produced {OBJECTIVE_MEANS[ran]}. "
                        "CreditProbe does not answer one question with "
                        "another.")))

    if contract.population:
        applied = _values_of(build)
        for named in contract.population:
            lowered = named.strip().lower()
            if not lowered:
                continue
            if not any(lowered in value or value in lowered
                       for value in applied):
                found.append(Divergence(
                    kind=POPULATION_LOST,
                    detail=(f"The question is about {named}, and the analysis "
                            f"did not restrict to it.")))

    if contract.period:
        window = {str(getattr(build, "opening", "") or "").lower(),
                  str(getattr(build, "closing", "") or "").lower(),
                  str(getattr(build, "period", "") or "").lower()} - {""}
        if window:
            named = [p.lower() for p in contract.period
                     if re.search(r"\d{4}", p)]
            # Only an explicitly dated period is checked. "the latest year" is
            # a request for the governed default and cannot disagree with it.
            if named and not any(
                    any(part in slot or slot in part for slot in window)
                    for part in named):
                found.append(Divergence(
                    kind=PERIOD_MOVED,
                    detail=(f"The question names {', '.join(contract.period)} "
                            f"and the analysis measured "
                            f"{' to '.join(sorted(window))}.")))

    if enforcement is not None:
        wanted_fields = {t.field for t in (enforcement.requested or ())}
        for test in (enforcement.executed or ()):
            if test.field not in wanted_fields:  # pragma: no cover - defensive
                found.append(Divergence(
                    kind=PREDICATE_INVENTED,
                    detail=(f"The analysis filtered on {test.describe()}, "
                            "which the question did not ask for.")))

    return Verdict(contract=contract, executed_objective=ran,
                   divergences=tuple(found))


__all__ = [
    "AGGREGATE",
    "ASSOCIATION",
    "CATALOGUE",
    "Contract",
    "Divergence",
    "MOVEMENT",
    "OBJECTIVES",
    "OBJECTIVE_CHANGED",
    "OBJECTIVE_MEANS",
    "PERIOD_MOVED",
    "POPULATION",
    "POPULATION_LOST",
    "PREDICATE_INVENTED",
    "PRODUCT",
    "RANKING",
    "UNKNOWN",
    "Verdict",
    "compare",
    "executed_objective",
    "objective_of",
    "read",
]
