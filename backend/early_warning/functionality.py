"""
Which part of CreditProbe should answer this, and why it is not always this one.

The problem this solves
-----------------------
Early Warning holds exposure, sector, grade and stage, because the model
needs them. That means it CAN answer "show total exposure by sector" — and
it should not. The answer would be exposure by sector for the three hundred
obligors Early Warning happens to score, presented as though it were the
book, and the reader would have no way to tell. Data availability is not
functional ownership, and the distance between the two is where a product
quietly starts lying.

So ownership is decided before any analysis is planned, let alone run. If
another functionality owns the question, this one does not answer it — not
approximately, not "using the fields I have". It says who owns it, why, and
what it CAN answer that gets closest to the same objective.

Why the scores are readable
---------------------------
Every functionality is scored against the request and the scores travel with
the decision, so a routing that looks wrong can be argued with. A selector
that returns a name and no reasoning is one nobody can correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------ the products

EARLY_WARNING = "early_warning"
COCKPIT = "cockpit"
WHAT_IF = "what_if"
SCORECARD_VALIDATION = "scorecard_validation"
LENSES = "lenses"


@dataclass(frozen=True)
class Functionality:
    """One part of CreditProbe, described by what it is FOR."""

    key: str
    name: str
    owns: tuple[str, ...]
    does_not_own: tuple[str, ...]
    #: What the reader is told when this one wins and they were somewhere else.
    purpose: str
    #: Phrases that indicate this functionality, with a weight.
    signals: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "owns": list(self.owns),
                "does_not_own": list(self.does_not_own),
                "purpose": self.purpose}


CATALOGUE: tuple[Functionality, ...] = (
    Functionality(
        key=EARLY_WARNING, name="Early Warning",
        owns=(
            "current and emerging risk detection",
            "the Early Warning score, its trigger-and-accelerator dimension "
            "and its classifier dimension",
            "the four intelligence layers and the twenty-two sub-categories",
            "signal-level analysis and the evidence behind a signal",
            "score movement, and whether it was the condition or the notches",
            "diagnosis of what a deteriorating population has in common",
            "governed remediation, escalation and Early Warning investigations",
        ),
        does_not_own=(
            "hypothetical scenarios and shocks",
            "model discrimination, calibration and backtesting",
            "general portfolio reporting unrelated to warning signals",
            "specialist preconfigured dashboards",
        ),
        purpose=(
            "Early Warning reads what is observed and currently derived: "
            "which obligors are deteriorating now, on what evidence, and "
            "what to do about it."),
        signals=(
            (r"early warning|\bews\b", 3.0),
            (r"\bsignal\w*\b", 2.0),
            (r"deteriorat\w*|worsen\w*", 2.0),
            (r"\bwatchlist\b", 2.0),
            (r"\bl[1-4]\b|layer [1-4]", 2.5),
            (r"sub.categor\w*|\bl[1-4]\.\w+", 2.5),
            (r"classifier|trigger|accelerator|notch\w*|anchor", 2.5),
            (r"\bt&a\b|trigger and accelerator", 2.5),
            (r"why (is|are|has|have|did).*(flag|score|deteriorat|mov|ris|f[ae]ll)", 2.0),
            (r"\bevidence\b|\bcorroborat\w*", 1.5),
            (r"escalat\w*|remediat\w*|what should i do", 2.0),
            (r"high risk|very high|severity band", 1.5),
            (r"driver|driving|dominant", 1.5),
            (r"\bcure\b|\bdecay\b|persistence hold", 2.5),
        ),
    ),
    Functionality(
        key=COCKPIT, name="Cockpit",
        owns=(
            "general credit portfolio investigation and decomposition",
            "portfolio performance and composition",
            "customer, segment, rating and staging analysis across the book",
            "management questions about the portfolio as it stands",
        ),
        does_not_own=(
            "Early Warning signal methodology and its control workflow",
            "hypothetical scenario shocks",
            "scorecard and model validation",
            "the specialist Lens experience",
        ),
        purpose=(
            "The Cockpit investigates the credit portfolio itself — its "
            "composition, its performance and how it moved — across the whole "
            "book rather than the population Early Warning scores."),
        signals=(
            (r"\becl\b|expected credit loss", 2.0),
            (r"\bprovision\w*\b|impairment", 2.0),
            (r"total exposure|exposure by|portfolio exposure", 2.5),
            (r"stage (1|2|3) (distribution|split|mix)|staging (distribution|mix)", 2.0),
            (r"rating distribution|grade distribution", 2.0),
            (r"portfolio (performance|composition|overview|profile)", 2.5),
            (r"\bnpl\b|non.performing", 2.0),
            (r"\bcoverage ratio\b", 1.5),
            (r"how (big|large) is (the|our) (book|portfolio)", 2.5),
        ),
    ),
    Functionality(
        key=WHAT_IF, name="What-If Analysis",
        owns=(
            "hypothetical scenarios and shocks",
            "parameter overrides and recalculation",
            "scenario comparison",
            "consequence analysis under an assumed change",
        ),
        does_not_own=(
            "what is observed in the book today",
            "Early Warning signal detection",
            "model validation statistics",
        ),
        purpose=(
            "What-If Analysis applies an assumed change and recomputes the "
            "consequence. Early Warning evaluates what has actually been "
            "observed, so it has nothing to say about a scenario that has "
            "not happened."),
        signals=(
            (r"what (if|happens if|would happen)", 4.0),
            (r"\bif\b.*\b(fall|falls|fell|drop|drops|rise|rises|increase|"
             r"decrease|shock|down|up)\b.*\b\d+\s*%", 3.5),
            (r"\bscenario\w*\b", 3.0),
            (r"\bshock\w*\b", 3.5),
            (r"\bsimulat\w*\b", 3.0),
            (r"\bstress (test|testing)\b", 3.0),
            (r"\bsuppose\b|\bassume\b|\bhypothetical\w*\b", 3.0),
            (r"downgrade (every|all|each)|were downgraded", 3.0),
            (r"recompute|recalculat\w*", 2.5),
            (r"\bimpact (of|on)\b.*\b(oil|gdp|rate|price|macro)", 2.5),
        ),
    ),
    Functionality(
        key=SCORECARD_VALIDATION, name="Scorecard Validation",
        owns=(
            "model discrimination and rank ordering",
            "calibration",
            "Gini, AUC, KS and PSI",
            "stability and backtesting",
            "validation diagnostics",
        ),
        does_not_own=(
            "what the model currently says about a borrower",
            "Early Warning signal detection",
            "hypothetical scenarios",
        ),
        purpose=(
            "Scorecard Validation tests whether a model discriminates and is "
            "calibrated. Early Warning uses a model that is explicitly NOT "
            "calibrated — its weights are a documented starting calibration "
            "rather than estimates fitted to default data — so a validation "
            "statistic computed on it would be meaningless."),
        signals=(
            (r"\bgini\b", 4.0),
            (r"\bauc\b|area under", 4.0),
            (r"\bks\b statistic|kolmogorov", 4.0),
            (r"\bpsi\b|population stability", 4.0),
            (r"calibrat\w*", 3.5),
            (r"discriminat\w*", 3.0),
            (r"backtest\w*", 3.5),
            (r"rank order\w*", 3.0),
            (r"model (validation|performance|stability)", 3.0),
            (r"\bvalidat\w* (the|this|our) (model|scorecard)", 3.5),
        ),
    ),
    Functionality(
        key=LENSES, name="Lenses",
        owns=(
            "specialised governed dashboards and views",
            "role-specific preconfigured perspectives",
        ),
        does_not_own=(
            "ad-hoc analysis",
            "Early Warning signal detection",
        ),
        purpose=(
            "Lenses are preconfigured governed views built for a particular "
            "role. Early Warning answers questions; it does not open another "
            "product's dashboard."),
        signals=(
            (r"\blens(es)?\b", 4.0),
            (r"open the .* (dashboard|view|board)", 3.0),
            (r"\b(cro|cfo|ceo|board) (dashboard|view|pack)\b", 3.5),
            (r"specialist (dashboard|view)", 3.5),
        ),
    ),
)

BY_KEY: dict[str, Functionality] = {f.key: f for f in CATALOGUE}


@dataclass
class Selection:
    """Who owns this request, how sure, and why."""

    selected: str
    scores: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    rationale: str = ""
    active_product_is_best: bool = True
    ambiguous: bool = False
    clarification: str = ""
    #: Set only when the deterministic path decided. A model seam records its
    #: own engine so the audit trail never implies a model that did not run.
    engine: str = "deterministic"
    #: What served the decision — provider, model, role, latency — and, where
    #: a model proposed something the gate refused, what it proposed and why
    #: it was refused. Empty when the deterministic path ran alone.
    model_call: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return BY_KEY[self.selected].name if self.selected in BY_KEY else self.selected

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_functionality": self.selected,
            "selected_name": self.name,
            "fit_scores": {k: round(v, 2) for k, v in self.scores.items()},
            "confidence": round(self.confidence, 3),
            "ownership_rationale": self.rationale,
            "active_product_is_best": self.active_product_is_best,
            "ambiguous": self.ambiguous,
            "required_clarification": self.clarification,
            "engine": self.engine,
            "model_call": dict(self.model_call),
        }


#: Below this the two leaders are close enough that picking one is a guess.
AMBIGUITY_MARGIN = 0.75

#: A request has to look like SOMETHING. Below this nothing scored at all and
#: Early Warning keeps it rather than routing on noise.
MINIMUM_SIGNAL = 1.0


def _score(text: str, functionality: Functionality) -> tuple[float, list[str]]:
    total = 0.0
    matched: list[str] = []
    for pattern, weight in functionality.signals:
        found = re.search(pattern, text, re.I)
        if found:
            total += weight
            matched.append(found.group(0).strip())
    return total, matched


def select(request_text: str, *, active: str = EARLY_WARNING) -> Selection:
    """Decide who owns this request.

    Deterministic, and deliberately so: routing is a product control, and a
    control that answers differently on two identical inputs is not one. A
    provider seam may rewrite the rationale, but never the decision — see
    `conversation.select`.
    """
    text = (request_text or "").strip()
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    for functionality in CATALOGUE:
        value, matched = _score(text, functionality)
        scores[functionality.key] = value
        evidence[functionality.key] = matched

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    runner_up, runner_score = ranked[1] if len(ranked) > 1 else ("", 0.0)

    # Nothing matched. The active product keeps it rather than routing on
    # noise: a question this domain cannot answer is refused further down,
    # by the domain itself, which knows what it holds.
    if best_score < MINIMUM_SIGNAL:
        return Selection(
            selected=active, scores=scores, confidence=0.2,
            rationale=("Nothing in the request points clearly at another "
                       "functionality, so the active product keeps it."),
            active_product_is_best=(best == active),
            engine="deterministic")

    margin = best_score - runner_score
    if margin < AMBIGUITY_MARGIN and runner_up:
        first, second = BY_KEY[best], BY_KEY[runner_up]
        return Selection(
            selected=best, scores=scores, confidence=0.4,
            rationale=(f"The request reads as {first.name} and as "
                       f"{second.name} about equally, and picking one would "
                       f"be a guess."),
            active_product_is_best=(best == active),
            ambiguous=True,
            clarification=_clarification(first, second),
            engine="deterministic")

    won = BY_KEY[best]
    hits = ", ".join(repr(m) for m in evidence[best][:3]) or "the request shape"
    return Selection(
        selected=best, scores=scores,
        confidence=min(0.95, 0.5 + margin / 10.0),
        rationale=(f"{won.name} owns this: the request turns on {hits}, "
                   f"which is {won.name}'s subject rather than the active "
                   f"product's."
                   if best != active else
                   f"{won.name} owns this: the request turns on {hits}."),
        active_product_is_best=(best == active),
        engine="deterministic")


def _clarification(first: Functionality, second: Functionality) -> str:
    """One question, naming both readings in the reader's own terms."""
    if {first.key, second.key} == {EARLY_WARNING, WHAT_IF}:
        return ("Do you want the obligors' current Early Warning position, or "
                "a simulation of what would happen under that change?")
    if {first.key, second.key} == {EARLY_WARNING, COCKPIT}:
        return ("Do you want this for the population Early Warning scores and "
                "in Early Warning terms, or across the whole credit portfolio?")
    if {first.key, second.key} == {EARLY_WARNING, SCORECARD_VALIDATION}:
        return ("Do you want what the Early Warning model currently says about "
                "these obligors, or a test of how well the model performs?")
    return (f"Is this a question for {first.name} or for {second.name}?")


def describe_all() -> list[dict[str, Any]]:
    """The catalogue as the context packet carries it. Capability metadata
    only — no other functionality's data ever travels with it."""
    return [f.to_dict() for f in CATALOGUE]


__all__ = ["AMBIGUITY_MARGIN", "BY_KEY", "CATALOGUE", "COCKPIT",
           "EARLY_WARNING", "LENSES", "MINIMUM_SIGNAL",
           "SCORECARD_VALIDATION", "WHAT_IF", "Functionality", "Selection",
           "describe_all", "select"]
