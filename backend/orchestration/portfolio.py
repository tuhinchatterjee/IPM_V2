"""The governed Analysis Portfolio Planner. §12.

"Investigate Contracting" could mean seven analyses. "Show EAD by sector"
means one. Both are open-ended in the sense that neither names a method, and
a planner that treated them the same would either drown the first in one
answer or bury the second under six it did not need.

§12's instruction is "do not blindly execute every method", which is a
constraint on BOTH directions. Running everything is expensive and unreadable;
running one thing because the first candidate scored highest leaves the
question half-answered. So selection here is marginal: a candidate earns its
place by what it adds to the analyses already chosen, and the planner stops
when the next-best candidate adds too little to be worth a reader's attention.

Everything the planner decided is kept - the candidates it considered, what it
chose, what it rejected and why, what each was expected to be worth and to
cost, and the dependency graph. A planner whose reasoning cannot be inspected
is indistinguishable from one that guessed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import objectives as obj

logger = logging.getLogger(__name__)

PORTFOLIO_VERSION = "1.0.0"

#: The most analyses one answer may carry. Above six §36 turns the response
#: into an Investigation review rather than a longer page, so a portfolio that
#: wanted eight would be answering in the wrong shape.
MAX_ANALYSES = 6

#: Marginal value below which a candidate is not worth a reader's attention.
#: The number that makes "Show EAD by sector" one analysis rather than seven:
#: once the analysis that directly answers it is selected, everything else is
#: an elaboration nobody asked for and scores under this.
MIN_MARGINAL_VALUE = 0.30

#: A candidate that cannot be computed is never selected, whatever it would
#: have been worth. Promising a line the catalogue cannot fill in is worse
#: than omitting it, because the reader believes it was checked.
MIN_AVAILABILITY = 0.5


# ---------------------------------------------------------------- candidates


@dataclass(frozen=True)
class Candidate:
    """One analysis the planner considered running."""

    analysis_id: str
    title: str
    #: The governed question this analysis asks, in the product's own words.
    question: str
    #: The concept it measures. Used for the independence score: two analyses
    #: over the same concept mostly tell a reader the same thing.
    concept_id: str = ""
    #: Which objective it serves. Empty means it is background - relevant to
    #: the request as a whole rather than to one clause of it.
    objective_id: str = ""
    datasets: tuple[str, ...] = ()
    #: Analyses that must finish first. A decomposition needs the total it is
    #: decomposing; an attribution needs the population it attributes over.
    depends_on: tuple[str, ...] = ()
    #: Why a reader should care that this ran.
    because: str = ""
    #: Marks an analysis whose only job is to check another. §37 wants these
    #: distinguished, and a validation-only analysis must never be presented
    #: as a finding.
    validation_only: bool = False
    #: How highly the caller rates this among candidates the request does not
    #: name, on 0..1. Domain knowledge the planner cannot derive: an officer
    #: investigating a sector asks what the exposure is before asking how it
    #: is provisioned, and nothing in the request says so. Without it, equally
    #: relevant candidates would be ordered alphabetically, which is a real
    #: way to put the least interesting analysis first.
    prior: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id, "title": self.title,
            "question": self.question, "concept_id": self.concept_id,
            "objective_id": self.objective_id,
            "datasets": list(self.datasets),
            "depends_on": list(self.depends_on), "because": self.because,
            "validation_only": self.validation_only, "prior": self.prior,
        }


@dataclass(frozen=True)
class Score:
    """§12's four axes, each on 0..1, plus what they come to together."""

    #: How directly this answers what was asked.
    relevance: float = 0.0
    #: Whether the governed data can actually compute it.
    availability: float = 0.0
    #: How much it adds beyond the analyses already selected. Recomputed as
    #: selection proceeds, which is what stops the planner.
    independence: float = 1.0
    #: Relative expense: datasets touched, joins traversed, periods spanned.
    cost: float = 0.0

    @property
    def expected_value_of_information(self) -> float:
        """What running this is expected to be worth.

        A product, not a sum: a candidate that is irrelevant, uncomputable or
        already covered is worth nothing, and averaging would let two good
        axes carry a fatal third.
        """
        return round(self.relevance * self.availability * self.independence, 4)

    @property
    def value_per_cost(self) -> float:
        return round(self.expected_value_of_information / max(self.cost, 0.1),
                     4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevance": round(self.relevance, 4),
            "availability": round(self.availability, 4),
            "independence": round(self.independence, 4),
            "cost": round(self.cost, 4),
            "expected_value_of_information":
                self.expected_value_of_information,
            "value_per_cost": self.value_per_cost,
        }


@dataclass
class Decision:
    """What the planner did about one candidate, and why."""

    candidate: Candidate
    score: Score
    selected: bool = False
    reason: str = ""
    #: §37: the analysis that carries the answer, as against the ones that
    #: support it.
    primary: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {**self.candidate.to_dict(), "score": self.score.to_dict(),
                "selected": self.selected, "reason": self.reason,
                "primary": self.primary}


@dataclass
class Portfolio:
    """Everything the planner considered, chose, rejected and expects."""

    request: str
    decisions: list[Decision] = field(default_factory=list)
    #: Objectives no selected analysis serves, with why.
    uncovered: dict[str, str] = field(default_factory=dict)
    selection_reason: str = ""
    version: str = PORTFOLIO_VERSION

    @property
    def candidates(self) -> list[Candidate]:
        return [d.candidate for d in self.decisions]

    @property
    def selected(self) -> list[Decision]:
        return [d for d in self.decisions if d.selected]

    @property
    def rejected(self) -> list[Decision]:
        return [d for d in self.decisions if not d.selected]

    @property
    def primary(self) -> list[Decision]:
        return [d for d in self.selected if d.primary]

    @property
    def supporting(self) -> list[Decision]:
        return [d for d in self.selected
                if not d.primary and not d.candidate.validation_only]

    @property
    def validation(self) -> list[Decision]:
        return [d for d in self.selected if d.candidate.validation_only]

    @property
    def expected_value_of_information(self) -> float:
        return round(sum(d.score.expected_value_of_information
                         for d in self.selected), 4)

    @property
    def cost_estimate(self) -> float:
        return round(sum(d.score.cost for d in self.selected), 4)

    def layers(self) -> list[list[str]]:
        """Selected analyses grouped into rounds that may run in parallel.

        §12 step 5: execute independent analyses in parallel where safe. Two
        analyses are safe together when neither depends on the other; the
        layering is what makes that decidable rather than hopeful.
        """
        remaining = {d.candidate.analysis_id: set(d.candidate.depends_on)
                     & {s.candidate.analysis_id for s in self.selected}
                     for d in self.selected}
        out: list[list[str]] = []
        while remaining:
            ready = sorted(k for k, deps in remaining.items() if not deps)
            if not ready:
                # A cycle. Report it rather than looping: an analysis graph
                # that cannot be ordered is a planning defect, and running it
                # in an arbitrary order would hide that.
                logger.error("portfolio dependency cycle among %s",
                             sorted(remaining))
                out.append(sorted(remaining))
                break
            out.append(ready)
            for key in ready:
                remaining.pop(key)
            for deps in remaining.values():
                deps.difference_update(ready)
        return out

    @property
    def parallelism(self) -> int:
        """The widest round. What the executor could actually run at once."""
        return max((len(layer) for layer in self.layers()), default=0)

    def dependency_graph(self) -> dict[str, list[str]]:
        return {d.candidate.analysis_id: list(d.candidate.depends_on)
                for d in self.selected}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "request": self.request,
            "candidate_analyses": [d.to_dict() for d in self.decisions],
            "selected_analyses": [d.to_dict() for d in self.selected],
            "rejected_analyses": [d.to_dict() for d in self.rejected],
            "selection_reason": self.selection_reason,
            "expected_value_of_information":
                self.expected_value_of_information,
            "cost_estimate": self.cost_estimate,
            "dependency_graph": self.dependency_graph(),
            "layers": self.layers(),
            "parallelism": self.parallelism,
            "primary": [d.candidate.analysis_id for d in self.primary],
            "supporting": [d.candidate.analysis_id for d in self.supporting],
            "validation_only": [d.candidate.analysis_id
                                for d in self.validation],
            "uncovered_objectives": dict(self.uncovered),
        }


# -------------------------------------------------------------------- scoring


#: Actions that need another analysis to have run first, and what they need.
#: A decomposition of a change needs the change; an attribution needs the
#: population it is attributing within.
_NEEDS: dict[str, tuple[str, ...]] = {
    obj.DECOMPOSE: (obj.COMPARE, obj.AGGREGATE),
    obj.ATTRIBUTE: (obj.RANK, obj.SELECT, obj.AGGREGATE),
    obj.ASSESS: (obj.AGGREGATE, obj.COMPARE),
    obj.DESCRIBE: (obj.AGGREGATE, obj.RANK, obj.COMPARE, obj.DECOMPOSE),
    obj.RANK: (obj.SELECT,),
}


def _relevance(candidate: Candidate, reading: obj.Reading | None,
               request: str) -> float:
    """How directly this answers what was asked.

    An analysis tied to a declared objective is what the user asked for. One
    whose concept the request names is adjacent to it. One that is neither is
    background - worth something in an open investigation, worth nothing when
    the request was specific.
    """
    if candidate.objective_id:
        return 1.0
    text = " ".join((request or "").lower().split())
    if candidate.concept_id and re.search(
            rf"\b{re.escape(candidate.concept_id.replace('_', ' '))}\b", text):
        return 0.8
    named_measure = bool(reading and any(
        o.measure_phrase for o in reading.objectives))
    # A request that named its measure has told us what it wants. Background
    # analyses are worth much less against it than against "investigate this".
    ceiling = 0.25 if named_measure else 0.7
    # The caller's prior orders the background candidates among themselves.
    # It can lower a background candidate and it can raise one, but it can
    # never lift a background analysis to the standing of one the user
    # actually asked for.
    return round(ceiling * (0.5 + 0.5 * max(0.0, min(1.0, candidate.prior))),
                 4)


def _availability(candidate: Candidate, computable: set[str]) -> float:
    """Whether the governed data can compute it, from the catalogue.

    Not a guess: `computable` is the set of concept ids the live catalogue can
    currently serve. A candidate over a concept nobody publishes scores zero
    and is never selected, so the answer never promises a line it cannot fill.
    """
    if not candidate.concept_id:
        return 1.0
    if not computable:
        # The catalogue could not be read. Unknown is not available: selecting
        # on an unread catalogue would be selecting on hope.
        return 0.0
    return 1.0 if candidate.concept_id in computable else 0.0


def _independence(candidate: Candidate,
                  chosen: list[Candidate]) -> float:
    """How much this adds beyond what is already selected.

    Two analyses over the same concept mostly tell a reader the same thing,
    and two over the same datasets tell them a related thing. This is the
    score that falls as the portfolio fills, and it is why the planner stops.

    It does NOT apply between two analyses serving different declared
    objectives. The user asked for both, and "you already have a similar
    figure" is not a reason to leave half a question unanswered - a total
    and a decomposition of that total share every dataset and every concept
    by construction, and dropping the second is the silent omission §11
    forbids.
    """
    if not chosen:
        return 1.0
    worst = 1.0
    for other in chosen:
        if (candidate.objective_id and other.objective_id
                and candidate.objective_id != other.objective_id):
            continue
        overlap = 0.0
        if candidate.concept_id and candidate.concept_id == other.concept_id:
            overlap += 0.7
        if candidate.datasets and other.datasets:
            shared = set(candidate.datasets) & set(other.datasets)
            union = set(candidate.datasets) | set(other.datasets)
            overlap += 0.3 * (len(shared) / len(union))
        worst = min(worst, max(0.0, 1.0 - overlap))
    return round(worst, 4)


def _cost(candidate: Candidate) -> float:
    """Relative expense. Datasets touched, and joins implied by touching them.

    Deliberately coarse. A cost model precise enough to be wrong in detail
    would invite decisions it cannot support; this one only has to separate
    "one table, one period" from "four tables joined across a year".
    """
    tables = max(len(candidate.datasets), 1)
    joins = max(tables - 1, 0)
    return round(0.4 + 0.3 * tables + 0.5 * joins, 4)


def score(candidate: Candidate, *, reading: obj.Reading | None,
          request: str, computable: set[str],
          chosen: list[Candidate]) -> Score:
    return Score(
        relevance=_relevance(candidate, reading, request),
        availability=_availability(candidate, computable),
        independence=_independence(candidate, chosen),
        cost=_cost(candidate),
    )


# ------------------------------------------------------------------ selection


def plan(request: str, candidates: list[Candidate], *,
         reading: obj.Reading | None = None,
         computable: set[str] | None = None,
         max_analyses: int = MAX_ANALYSES,
         cost_budget: float = 0.0) -> Portfolio:
    """Choose the minimum sufficient portfolio. §12 steps 1-4.

    Greedy on marginal value: take the best remaining candidate, recompute
    what everything else is now worth given that choice, and stop when the
    best remaining is not worth a reader's attention. Greedy rather than
    exhaustive because the independence score makes the objective submodular -
    each choice can only lower what the others add - and the reader-facing
    difference between the greedy portfolio and the optimal one is smaller
    than the difference between six analyses and five.

    Every declared objective must end up served by something. One that is not
    is recorded in `uncovered` with the reason, so §11's coverage can report
    it rather than the answer quietly omitting it.
    """
    available = computable if computable is not None else set()
    pool = list(candidates)
    chosen: list[Candidate] = []
    decisions: dict[str, Decision] = {}
    spent = 0.0

    while pool and len(chosen) < max_analyses:
        scored = [(c, score(c, reading=reading, request=request,
                            computable=available, chosen=chosen))
                  for c in pool]
        scored.sort(key=lambda pair: (-pair[1].expected_value_of_information,
                                      pair[1].cost, pair[0].analysis_id))
        best, best_score = scored[0]

        if best_score.availability < MIN_AVAILABILITY:
            break
        if best_score.expected_value_of_information < MIN_MARGINAL_VALUE:
            break
        if cost_budget and spent + best_score.cost > cost_budget:
            break

        chosen.append(best)
        spent += best_score.cost
        decisions[best.analysis_id] = Decision(
            candidate=best, score=best_score, selected=True,
            reason=_why_selected(best, best_score, len(chosen)))
        pool.remove(best)

    # Everything left is rejected, scored against the portfolio as it ended up.
    for candidate in pool:
        final = score(candidate, reading=reading, request=request,
                      computable=available, chosen=chosen)
        decisions[candidate.analysis_id] = Decision(
            candidate=candidate, score=final, selected=False,
            reason=_why_rejected(final, len(chosen), max_analyses,
                                 spent, cost_budget))

    portfolio = Portfolio(
        request=request,
        decisions=[decisions[c.analysis_id] for c in candidates])
    _designate(portfolio)
    portfolio.uncovered = _uncovered(portfolio, reading)
    portfolio.selection_reason = _summary(portfolio, len(candidates))
    return portfolio


def _why_selected(candidate: Candidate, scored: Score, position: int) -> str:
    """Why this one, said in terms a reader can check.

    The distinction that matters is whether the user asked for this analysis
    or the planner proposed it. Calling a background check "what you asked
    for" because it happened to be picked first would misdescribe the answer.
    """
    asked_for = scored.relevance >= 0.8
    if position == 1:
        return ("the analysis that directly answers the request"
                if asked_for else
                "the strongest of the checks proposed for this request "
                f"(value {scored.expected_value_of_information:.2f})")
    if asked_for:
        return "the request asks for this as well"
    return (f"adds {scored.independence:.0%} beyond the analyses already "
            f"chosen; {candidate.because or 'proposed for this request'}")


def _why_rejected(scored: Score, taken: int, cap: int, spent: float,
                  budget: float) -> str:
    if scored.availability < MIN_AVAILABILITY:
        return ("the governed data cannot compute this, and promising a line "
                "the catalogue cannot fill is worse than leaving it out")
    if taken >= cap:
        return (f"the portfolio was already at its cap of {cap}; above that "
                "the answer becomes a card wall rather than an answer")
    if budget and spent + scored.cost > budget:
        return "it would have taken the portfolio past its cost budget"
    if scored.independence < 0.5:
        return (f"it repeats {1 - scored.independence:.0%} of what a selected "
                "analysis already shows")
    if scored.relevance < 0.5:
        return "the request did not ask for this and does not imply it"
    return (f"its marginal value ({scored.expected_value_of_information:.2f}) "
            f"is below the {MIN_MARGINAL_VALUE:.2f} worth a reader's "
            "attention")


def _designate(portfolio: Portfolio) -> None:
    """§37: mark the analyses that carry the answer.

    An analysis tied to an objective is primary - the user asked for it. Where
    nothing is tied to an objective, the highest-value selection carries the
    answer. Everything else supports it, and the UI must not give them equal
    weight.
    """
    selected = portfolio.selected
    if not selected:
        return
    tied = [d for d in selected if d.candidate.objective_id
            and not d.candidate.validation_only]
    if tied:
        for decision in tied:
            decision.primary = True
        return
    best = max((d for d in selected if not d.candidate.validation_only),
               key=lambda d: d.score.expected_value_of_information,
               default=None)
    if best is not None:
        best.primary = True


def _uncovered(portfolio: Portfolio,
               reading: obj.Reading | None) -> dict[str, str]:
    """Objectives nothing selected will answer.

    The join between §12 and §11. A planner that quietly dropped an objective
    would produce an answer that looks complete, and the coverage report is
    the only thing that would have said otherwise.
    """
    if reading is None:
        return {}
    served = {d.candidate.objective_id for d in portfolio.selected
              if d.candidate.objective_id}
    out: dict[str, str] = {}
    for objective in reading.objectives:
        if objective.objective_id in served:
            continue
        rejected = [d for d in portfolio.rejected
                    if d.candidate.objective_id == objective.objective_id]
        if rejected:
            worst = min(rejected,
                        key=lambda d: d.score.expected_value_of_information)
            out[objective.objective_id] = worst.reason
        else:
            out[objective.objective_id] = (
                "no governed analysis was proposed for this objective")
    return out


def _summary(portfolio: Portfolio, considered: int) -> str:
    """The sentence the Trace and the answer show about the choice."""
    taken = len(portfolio.selected)
    if not taken:
        return (f"{considered} analyses were considered and none was worth "
                "running: either the governed data cannot compute them or "
                "they do not answer what was asked")
    if taken == 1:
        return (f"One analysis answers this. {considered - 1} others were "
                "considered and would have added little to it"
                if considered > 1 else "One analysis answers this")
    return (f"{taken} of {considered} analyses were selected: enough to "
            f"answer every part of the request without repeating "
            f"what an earlier one already shows")


def settle_objectives(portfolio: Portfolio,
                      reading: obj.Reading) -> None:
    """Mark objectives no analysis will serve, before anything runs. §11.

    Done at planning time rather than at assembly time on purpose: an
    objective the planner already knows it cannot serve should say so from
    the start, not appear to be in progress and then vanish.
    """
    for objective_id, reason in portfolio.uncovered.items():
        objective = reading.objective(objective_id)
        if objective is not None and objective.status == obj.PLANNED:
            objective.settle(obj.UNAVAILABLE, note=reason)
    for decision in portfolio.selected:
        objective = reading.objective(decision.candidate.objective_id)
        if objective is not None:
            objective.planned_task = decision.candidate.analysis_id


def infer_dependencies(candidates: list[Candidate],
                       reading: obj.Reading) -> list[Candidate]:
    """Wire the dependency graph from what each objective's action needs.

    A decomposition cannot run before the comparison it decomposes, and an
    attribution cannot run before the population it attributes within exists.
    Derived from the objective actions rather than declared by hand, so a
    candidate list that grows keeps its ordering correct.
    """
    by_objective = {c.objective_id: c for c in candidates if c.objective_id}
    actions = {o.objective_id: o.action for o in reading.objectives}
    out: list[Candidate] = []
    for candidate in candidates:
        action = actions.get(candidate.objective_id, "")
        needs = _NEEDS.get(action, ())
        upstream = tuple(sorted(
            other.analysis_id
            for objective_id, other in by_objective.items()
            if other.analysis_id != candidate.analysis_id
            and actions.get(objective_id, "") in needs))
        out.append(Candidate(
            **{**candidate.__dict__,
               "depends_on": tuple(dict.fromkeys(
                   (*candidate.depends_on, *upstream)))}))
    return out
