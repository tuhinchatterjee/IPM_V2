"""
Which route answers this request, and which model — if any — is involved.

Four routes, and the first one is the important one
---------------------------------------------------
**A — no model at all.** A catalogue lookup, a field definition, a period
count, a presentation change, an SQL execution, an invariant check. These have
exact answers in governed metadata, and a model asked for one can only agree or
be wrong. Most turns in a working thread take this route, which is why the
product is usable without a provider at all.

**B — the routine model.** Ordinary intent reading, a straightforward plan, a
normal follow-up, a concise interpretation of a result that is already fixed.

**C — the complex model.** A broad investigation, a compound multi-domain
request, difficult ambiguity, methodology work, a re-plan after a rejection, or
anything happening in demo-safe mode where a misunderstanding is expensive.

**D — the critic.** Only reached when a plan has been rejected and there is
something specific to repair.

The escalation is the design
----------------------------
Route B's output is not trusted because a model produced it. It is validated
deterministically, and a failure escalates to C with the validation errors —
never with a gold answer, and never more than the policy allows. If C's plan
fails validation too, CreditProbe clarifies or abstains. **Nothing falls back
to an unrelated registered analysis**, at any point, for any reason.

Why the signals are counted rather than judged
----------------------------------------------
"Is this hard?" asked of a model costs a call to decide whether to make a call.
The signals here are structural — how many datasets, how many joins, how many
periods, whether a referent has to be resolved, whether the request names
several objectives — and they are counted deterministically, recorded on the
Trace, and cost nothing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

DETERMINISTIC = "A_DETERMINISTIC"
ROUTINE = "B_ROUTINE"
COMPLEX = "C_COMPLEX"
CRITIC = "D_CRITIC"

ROUTES: tuple[str, ...] = (DETERMINISTIC, ROUTINE, COMPLEX, CRITIC)

LABELS: dict[str, str] = {
    DETERMINISTIC: "Deterministic — no model call",
    ROUTINE: "Routine model",
    COMPLEX: "Complex planning model",
    CRITIC: "Critic — repairing a rejected plan",
}

#: Which configured role serves each route.
ROLE_OF: dict[str, str] = {
    ROUTINE: "router",
    COMPLEX: "planner",
    CRITIC: "critic",
}

#: The score at which a request stops being routine. Deliberately low: the cost
#: of over-thinking a simple question is a few cents and a second, and the cost
#: of under-thinking a compound one is a confident wrong answer in front of a
#: client.
COMPLEX_AT = 3


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    """One structural reason to think harder about a request."""

    id: str
    weight: int
    detail: str


#: Phrases that mean the request is open-ended rather than a single figure.
_BROAD = re.compile(
    r"\binvestigate\b|\blook into\b|\bdig into\b|\bwhat(?:'s| is) (?:going on|"
    r"happening|wrong)\b|\breview the\b|\banything (?:concerning|worrying)\b"
    r"|\bwhat should I\b|\btell me about\b", re.I)

#: A request that names more than one thing to produce.
_MULTI_OBJECTIVE = re.compile(
    r",\s*and\s+(?:which|what|how|show|list|rank|compare)\b"
    r"|\band also\b|\bas well as\b|\bplus\b.{0,30}\bfor each\b", re.I)

#: Methodology work, as opposed to using one.
_METHODOLOGY = re.compile(
    r"\b(?:create|define|build|change|amend|revise)\s+(?:a |the |our )?"
    r"(?:method|methodology|model|approach|framework|policy)\b"
    r"|\bhow should we (?:measure|define|calculate)\b", re.I)

#: Statistical or predictive work, which the governed runtime does not do and a
#: model must not pretend to.
_PREDICTIVE = re.compile(
    r"\bpredict\b|\bforecast\b|\bproject(?:ion|ed)?\b|\bregress\w*\b"
    r"|\bcorrelat\w*\b|\bprobability of\b|\blikelihood\b|\bexpected to\b", re.I)

#: A nested ratio: a measure over another measure.
_NESTED = re.compile(
    r"\bdivided by\b|\bover total\b|\bas a (?:share|proportion|percentage)\b"
    r"|\bratio of\b.{0,30}\bto\b", re.I)


@dataclass
class Decision:
    """Which route was chosen, and everything that decided it."""

    route: str = ROUTINE
    role: str = "router"
    model: str = ""
    effort: str = ""
    score: int = 0
    signals: list[Signal] = field(default_factory=list)
    #: Set when this decision replaced an earlier one.
    escalated_from: str = ""
    reason: str = ""
    #: How many repair attempts have been made on this turn.
    repairs: int = 0

    @property
    def uses_model(self) -> bool:
        return self.route != DETERMINISTIC

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "label": LABELS.get(self.route, self.route),
            "role": self.role,
            "model": self.model,
            "effort": self.effort,
            "score": self.score,
            "signals": [{"id": s.id, "weight": s.weight, "detail": s.detail}
                        for s in self.signals],
            "escalated_from": self.escalated_from,
            "reason": self.reason,
            "repairs": self.repairs,
            "uses_model": self.uses_model,
        }


def signals(question: str, *, reading: Any = None, continuation: Any = None,
            memory: Any = None, demo_safe: bool = False) -> list[Signal]:
    """Every structural reason this request is harder than a single figure."""
    text = " ".join((question or "").split())
    found: list[Signal] = []

    def add(sid: str, weight: int, detail: str) -> None:
        found.append(Signal(id=sid, weight=weight, detail=detail))

    datasets = list(getattr(reading, "datasets", ()) or ())
    concepts = list(getattr(reading, "concepts", ()) or ())
    periods = list(getattr(reading, "periods", ()) or ())

    if len(datasets) >= 3:
        add("datasets", 2, f"{len(datasets)} datasets are named or implied.")
    elif len(datasets) == 2:
        add("datasets", 1, "Two datasets have to be brought together.")

    if len(concepts) >= 4:
        add("concepts", 2, f"{len(concepts)} governed concepts are involved.")
    elif len(concepts) == 3:
        add("concepts", 1, "Three governed concepts are involved.")

    if len(periods) >= 2 or getattr(reading, "period_requirement", "") == "two_period":
        add("periods", 1, "Two reporting periods have to be aligned.")

    if getattr(continuation, "carries_context", False):
        add("referent", 1, "A reference to the previous turn has to be resolved.")

    if memory is not None and not getattr(memory, "empty", True):
        outstanding = list(getattr(memory, "outstanding", []) or [])
        if outstanding:
            add("incomplete", 2,
                "A part of the previous request was left unanswered.")

    if _BROAD.search(text):
        add("broad", 3, "The request is open-ended rather than one figure.")

    # How many objectives the request contains, counted by the P0.3
    # decomposer rather than guessed by a pattern here. Two places counting
    # the same thing is one too many, and the regex was the worse of the two:
    # it wanted ", and <wh-word>", so "…, rank sectors by the change, and SAY
    # which borrowers drove it" — four objectives — scored as one, and a
    # request that needed the complex planner took the routine route.
    objectives = _objective_count(text)
    if objectives >= 3:
        add("objectives", 3,
            f"The request names {objectives} things to produce.")
    elif objectives == 2:
        add("objectives", 2, "The request names two things to produce.")
    elif _MULTI_OBJECTIVE.search(text):
        add("objectives", 2, "The request names more than one thing to produce.")
    if _METHODOLOGY.search(text):
        add("methodology", 3, "The request is about a method, not a figure.")
    if _PREDICTIVE.search(text):
        add("predictive", 3,
            "The request asks for something statistical or forward-looking.")
    if _NESTED.search(text):
        add("nested", 2, "The request nests one measure inside another.")

    if getattr(reading, "clarification", ""):
        add("ambiguous", 2, "The first reading was not confident.")
    confidence = float(getattr(reading, "confidence", 1.0) or 0.0)
    if reading is not None and confidence and confidence < 0.6:
        add("low_confidence", 2,
            f"The reading was only {confidence:.0%} confident.")

    if demo_safe:
        add("demo_safe", 2,
            "Demo Safe Mode is on, where a misunderstanding is expensive.")

    return found


#: A clause that opens with a bare imperative is another thing to produce.
#: "…, compare it with four quarters ago, rank sectors by the change, and say
#: which borrowers drove it" is three, however the sentence is punctuated.
_IMPERATIVE = re.compile(
    r"(?:,|;|\band\b|\bthen\b)\s+(calculat\w*|comput\w*|compar\w*|rank\w*|"
    r"show\w*|list\w*|say\w*|tell\w*|identif\w*|decompos\w*|attribut\w*|"
    r"break\s*down|summaris\w*|summariz\w*|explain\w*|find\w*|report\w*)\b",
    re.I)


def _objective_count(text: str) -> int:
    """How many things this request asks CreditProbe to produce.

    Counted LIBERALLY here, and deliberately more liberally than the P0.3
    decomposer that governs the answer. The two consumers have opposite
    tolerances, and it is worth being explicit about why:

    `objectives.read` decides what the ANSWER must cover, so it refuses to
    split on a bare comma — "For every sector, calculate the Stage 2 share" is
    one request, and splitting it would make the product chase an objective
    nobody asked for.

    This decides which MODEL thinks about it. Over-routing a simple question
    costs a second and a few cents; under-routing a compound one produces a
    confident wrong answer in front of a client. So a serial list of
    imperatives counts here even where the decomposer keeps it whole, and the
    router takes whichever count is higher.

    Never raises: routing must not be the thing that fails.
    """
    serial = len(_IMPERATIVE.findall(text or "")) + 1 if text else 0
    try:
        from backend.orchestration import objectives as ob

        governed = len(ob.read(text).objectives)
    except Exception as e:  # noqa: BLE001 - routing must never be the failure
        logger.debug("Could not count objectives for routing: %s", e)
        governed = 0
    return max(serial, governed)


def decide(question: str, *, reading: Any = None, continuation: Any = None,
           memory: Any = None, deterministic: bool = False,
           demo_safe: bool = False) -> Decision:
    """Which route answers this, before any model is called.

    `deterministic` is set by the caller when it already knows governed
    services can answer — a presentation change, a metadata follow-up, a
    catalogue lookup. That is route A, and no scoring is needed to reach it.
    """
    if deterministic:
        return Decision(
            route=DETERMINISTIC, role="", model="", score=0,
            reason=("Governed services answer this exactly; a model could only "
                    "agree or be wrong."))

    found = signals(question, reading=reading, continuation=continuation,
                    memory=memory, demo_safe=demo_safe)
    score = sum(s.weight for s in found)
    route = COMPLEX if score >= COMPLEX_AT else ROUTINE
    chosen = _role_for(route)
    return Decision(
        route=route, role=chosen.name, model=chosen.model,
        effort=chosen.effort, score=score, signals=found,
        reason=("; ".join(s.detail for s in found[:3]) or
                 "Nothing about this request needs the complex model."))


def escalate(previous: Decision, why: str, *, to: str = COMPLEX) -> Decision:
    """Move to a harder route after something deterministic rejected the plan.

    The reason travels with the decision because it is what the next prompt is
    allowed to contain: the validation errors, and nothing else. A repair
    prompt that carried an expected answer would be teaching to the test.
    """
    chosen = _role_for(to)
    return Decision(
        route=to, role=chosen.name, model=chosen.model, effort=chosen.effort,
        score=previous.score, signals=list(previous.signals),
        escalated_from=previous.route, reason=why,
        repairs=previous.repairs + 1)


def _role_for(route: str) -> Any:
    from backend.llm import roles

    return roles.role(ROLE_OF.get(route, roles.ROUTER))


__all__ = [
    "COMPLEX",
    "COMPLEX_AT",
    "CRITIC",
    "DETERMINISTIC",
    "LABELS",
    "ROLE_OF",
    "ROUTES",
    "ROUTINE",
    "Decision",
    "Signal",
    "decide",
    "escalate",
    "signals",
]
