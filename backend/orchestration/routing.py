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
    # §22 splits the routine planner from the complex one, so the complex
    # route is served by its own configured role. A deployment that set only
    # AI_PLANNER_MODEL still works — the complex role falls back to it — but
    # an administrator who wants a stronger model for forensic work no longer
    # has to pay for it on every "what is total EAD by sector".
    COMPLEX: "complex_planner",
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
    """One structural reason to think harder about a request.

    `direct` is §24's distinction, and it is not a big weight. A direct signal
    sends the request to the complex planner ON ITS OWN, whatever the rest of
    the score says — because "decompose the ECL movement" is a complex request
    even when it is the shortest sentence anybody typed that day, and a score
    threshold that could be reached by three cheap signals could also be
    missed by one expensive one.
    """

    id: str
    weight: int
    detail: str
    direct: bool = False


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

#: §24's direct signals, as the phrases that actually announce them. Each of
#: these sends the request straight to the complex planner: it is not that they
#: are worth many points, it is that a score threshold reachable by three cheap
#: signals could also be missed by one expensive one.
_DECOMPOSITION = re.compile(
    r"\bdecompos\w*|\battribut\w*\s+(?:the\s+)?(?:change|movement|increase|"
    r"decrease)|\bbridge\b|\bwalk me through the (?:change|movement)\b"
    r"|\bbreak (?:the )?(?:change|movement) down\b|\bwhat drove\b", re.I)

_MIGRATION = re.compile(
    r"\bmigration\b|\bmigrat\w+\b|\btransition matrix\b|\broll[ -]?rate\b"
    r"|\bcure rate\b|\bmoved (?:from|between) stage\b"
    r"|\b(?:up|down)graded?\b.{0,40}\b(?:and|while|alongside)\b", re.I)

_STRESS = re.compile(
    r"\bstress\b|\bscenario\b|\bsensitivit\w+|\bwhat if\b|\bshock\b"
    r"|\bdownside\b|\bsevere case\b", re.I)

_FORENSIC = re.compile(
    r"\bforensic\b|\bdeep dive\b|\bfull review\b|\breview the (?:whole|"
    r"entire|full)\b|\bpost[- ]?mortem\b|\broot cause\b"
    r"|\bwhy (?:did|has|is)\b.{0,40}\b(?:changed|moved|risen|fallen)\b",
    re.I)

_ORDER_NEUTRAL = re.compile(
    r"\border[- ]neutral\b|\bshapley\b|\bindependent of (?:the )?order\b"
    r"|\bwhichever order\b", re.I)

#: A nested ratio: a measure over another measure.
_NESTED = re.compile(
    r"\bdivided by\b|\bover total\b|\bas a (?:share|proportion|percentage)\b"
    r"|\bratio of\b.{0,30}\bto\b", re.I)


@dataclass(frozen=True)
class Situation:
    """What the caller knows that the question does not say. §24, §25.

    Every field here is a fact the router cannot read off the text: how many
    relationships the plan traverses, whether the last plan was rejected,
    whether the Risk Case behind this is critical. They are passed in rather
    than guessed, because a router that inferred "the previous plan failed"
    from wording would be inferring the one thing it must never get wrong.
    """

    relationships: int = 0
    grains: int = 0
    agents: int = 0
    #: A previous routine plan was rejected on this turn.
    plan_rejected: bool = False
    #: A previous run failed an invariant or a grounding check.
    validation_failed: bool = False
    #: Two agents reached findings that disagree.
    conflicting_findings: bool = False
    #: The Risk Case this sits under is CRITICAL.
    critical_case: bool = False
    #: The exposure at stake is material enough that a wrong answer matters.
    high_materiality: bool = False
    #: Multi-agent coordination is already under way.
    orchestrated: bool = False
    #: What is left of the turn's model budget. Zero means unbounded — an
    #: unset budget must not read as an exhausted one.
    cost_budget: float = 0.0
    cost_spent: float = 0.0

    @property
    def budget_exhausted(self) -> bool:
        return bool(self.cost_budget) and self.cost_spent >= self.cost_budget


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

    # ---- §25's persisted record ------------------------------------------
    #: The route this turn STARTED on. Kept separate from `route`, which is
    #: where it ended up: a turn that began routine and escalated is a
    #: different fact from one that went straight to the complex planner, and
    #: an evaluation that cannot tell them apart cannot tune the threshold.
    initial_route: str = ""
    #: True when a §24 direct signal decided this rather than the score.
    direct: bool = False
    #: The model the ROLE is configured with, and the model that actually
    #: served the call. §23: never a silent substitution — if these differ,
    #: something substituted, and the Trace says so.
    configured_model: str = ""
    served_model: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0
    #: The teaching cases retrieved for this route (§17, §45). Ids only.
    teaching_cases: list[str] = field(default_factory=list)
    #: Set when the configured complex role could not be served and §28's
    #: policy decided what to do instead.
    degraded: str = ""

    @property
    def final_route(self) -> str:
        """§25's name for what `route` holds. Both exist because the record
        reads better with the pair named, and code reads better with one."""
        return self.route

    @property
    def route_reasons(self) -> list[str]:
        return [s.detail for s in self.signals]

    @property
    def substituted(self) -> bool:
        """Whether a different model answered than the one configured.

        §23 forbids doing this silently. It does not forbid it happening — a
        provider can fall back on its own side — so the honest thing is to
        detect it and say so rather than to assume it cannot occur."""
        return bool(self.configured_model and self.served_model
                    and self.configured_model != self.served_model)

    def record(self) -> dict[str, Any]:
        """Everything §25 asks to be persisted, in one shape."""
        return {
            "initial_route": self.initial_route or self.route,
            "final_route": self.route,
            "route_score": self.score,
            "route_reasons": self.route_reasons,
            "direct": self.direct,
            "model_role": self.role,
            "configured_model": self.configured_model or self.model,
            "served_model": self.served_model,
            "substituted": self.substituted,
            "effort": self.effort,
            "escalation": self.escalated_from,
            "escalation_reason": self.reason if self.escalated_from else "",
            "degraded": self.degraded,
            "teaching_cases": list(self.teaching_cases),
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_estimate": round(self.cost_estimate, 6),
        }

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
            **self.record(),
        }


def signals(question: str, *, reading: Any = None, continuation: Any = None,
            memory: Any = None, demo_safe: bool = False,
            situation: Situation | None = None) -> list[Signal]:
    """Every structural reason this request is harder than a single figure."""
    text = " ".join((question or "").split())
    where = situation or Situation()
    found: list[Signal] = []

    def add(sid: str, weight: int, detail: str, *,
            direct: bool = False) -> None:
        found.append(Signal(id=sid, weight=weight, detail=detail,
                            direct=direct))

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
        # §24 lists methodology creation/change as a direct complex signal:
        # a method somebody will rely on afterwards is worth the better model
        # however short the sentence asking for it.
        add("methodology", 3, "The request is about a method, not a figure.",
            direct=True)
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

    # ---- §24's direct complex signals, read from the text ----------------
    if _DECOMPOSITION.search(text):
        add("decomposition", 4, "The request asks for an attribution of a "
                                "movement to its drivers.", direct=True)
    if _MIGRATION.search(text):
        add("migration", 3, "The request is about movement between grades, "
                            "stages or buckets.", direct=True)
    if _STRESS.search(text):
        add("stress", 3, "The request is about a scenario rather than the "
                         "reported position.", direct=True)
    if _FORENSIC.search(text):
        add("forensic", 4, "The request is a forensic review rather than a "
                           "figure.", direct=True)
    if _ORDER_NEUTRAL.search(text):
        add("order_neutral", 3, "The request needs an order-neutral "
                                "attribution.", direct=True)

    # ---- §24's direct signals the caller supplies -------------------------
    if where.relationships >= 3:
        add("relationships", 3,
            f"The plan traverses {where.relationships} governed "
            "relationships.", direct=True)
    elif where.relationships == 2:
        add("relationships", 1, "Two governed relationships are traversed.")
    if where.grains >= 2:
        add("grains", 3, f"{where.grains} grains have to be reconciled.",
            direct=True)
    if where.orchestrated or where.agents >= 2:
        add("agents", 3, "Several agents have to be coordinated.",
            direct=True)
    if where.conflicting_findings:
        add("conflict", 4, "Two agents reached findings that disagree.",
            direct=True)
    if where.plan_rejected:
        add("plan_rejected", 4, "A routine plan was already rejected on this "
                                "turn.", direct=True)
    if where.validation_failed:
        add("validation_failed", 4, "A previous run failed an invariant or a "
                                    "grounding check.", direct=True)
    if where.critical_case:
        add("critical_case", 4, "This sits under a critical Risk Case.",
            direct=True)
    if where.high_materiality:
        add("materiality", 3, "The exposure at stake is material.",
            direct=True)

    if demo_safe:
        add("demo_safe", 2,
            'Client Safe Mode is on, where a misunderstanding is expensive.')

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
           demo_safe: bool = False,
           situation: Situation | None = None) -> Decision:
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

    where = situation or Situation()
    found = signals(question, reading=reading, continuation=continuation,
                    memory=memory, demo_safe=demo_safe, situation=where)
    score = sum(s.weight for s in found)
    forced = [s for s in found if s.direct]

    # §24: a direct signal routes on its own. §25: the budget is the one thing
    # that can hold it back, and holding it back is recorded rather than
    # silently applied — an answer planned by the routine model because the
    # budget ran out is a different answer, and the Trace has to say so.
    route = COMPLEX if (forced or score >= COMPLEX_AT) else ROUTINE
    held = route == COMPLEX and where.budget_exhausted
    if held:
        route = ROUTINE

    chosen = _role_for(route)
    if forced:
        reason = forced[0].detail
    elif found:
        reason = "; ".join(s.detail for s in found[:3])
    else:
        reason = "Nothing about this request needs the complex model."
    if held:
        reason = (f"{reason} The complex route was indicated but the turn's "
                  "model budget is spent.")

    return Decision(
        route=route, role=chosen.name, model=chosen.model,
        effort=chosen.effort, score=score, signals=found,
        initial_route=route, direct=bool(forced) and not held,
        configured_model=chosen.model,
        degraded="budget" if held else "",
        reason=reason)


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
        repairs=previous.repairs + 1,
        # §25: the route a turn STARTED on survives every escalation. A turn
        # that began routine and ended at the critic is a different fact from
        # one that went straight to the complex planner, and an evaluation
        # that cannot tell them apart cannot tune the threshold.
        initial_route=previous.initial_route or previous.route,
        configured_model=chosen.model,
        teaching_cases=list(previous.teaching_cases))


def _role_for(route: str) -> Any:
    from backend.llm import roles

    return roles.role(ROLE_OF.get(route, roles.ROUTER))




# ---------------------------------------------------------------------------
# §27 — the escalation cascade
# ---------------------------------------------------------------------------

#: The stages a turn passes through. Named so the cascade can say where it is
#: rather than counting integers, and so the Trace (§45) can show the path.
READ = "reading"
RETRIEVE = "teaching_retrieval"
PLAN = "plan"
VALIDATE = "plan_validation"
EXECUTE = "execute"
INVARIANTS = "result_invariants"
INTERPRET = "interpretation"
RUBRIC = "interpretation_rubric"
PRESENT = "present"

STAGES: tuple[str, ...] = (READ, RETRIEVE, PLAN, VALIDATE, EXECUTE,
                           INVARIANTS, INTERPRET, RUBRIC, PRESENT)

#: §27's maxima. One of each, and the reason they are constants rather than
#: configuration is that every one of them is a LOOP if it is not capped: a
#: critic that can be re-invoked on its own failure will be, and the failure
#: that made the first pass necessary is usually still there on the fourth.
MAX_ROUTINE_PLANS = 1
MAX_COMPLEX_REPLANS = 1
MAX_CRITIC_PASSES = 1
MAX_INTERPRETATION_REPAIRS = 1


class CascadeExhausted(RuntimeError):
    """Every permitted attempt has been made.

    Raised rather than returned because the caller has exactly one correct
    response — stop and report what happened — and a return value that can be
    ignored is one that will be.
    """


@dataclass
class Cascade:
    """§27's ladder, and the record of how far up it a turn went.

    Deliberately a small state machine rather than a loop with counters
    scattered through the orchestrator. Every attempt asks this object for
    permission, so the caps hold wherever the call is made from, and the
    record of what was attempted is in one place for the Trace to read.
    """

    routine_plans: int = 0
    complex_replans: int = 0
    critic_passes: int = 0
    interpretation_repairs: int = 0
    #: Every step taken, in order: (stage, route, why).
    steps: list[tuple[str, str, str]] = field(default_factory=list)

    def note(self, stage: str, route: str = "", why: str = "") -> None:
        self.steps.append((stage, route, why))

    def may_plan_routine(self) -> bool:
        return self.routine_plans < MAX_ROUTINE_PLANS

    def may_replan_complex(self) -> bool:
        return self.complex_replans < MAX_COMPLEX_REPLANS

    def may_run_critic(self) -> bool:
        return self.critic_passes < MAX_CRITIC_PASSES

    def may_repair_interpretation(self) -> bool:
        return self.interpretation_repairs < MAX_INTERPRETATION_REPAIRS

    def attempt(self, route: str, *, why: str = "") -> None:
        """Record an attempt on a route, refusing one past its cap."""
        if route == ROUTINE:
            if not self.may_plan_routine():
                raise CascadeExhausted(
                    "The routine planner has already had its one attempt.")
            self.routine_plans += 1
        elif route == COMPLEX:
            if not self.may_replan_complex():
                raise CascadeExhausted(
                    "The complex planner has already replanned once.")
            self.complex_replans += 1
        elif route == CRITIC:
            if not self.may_run_critic():
                raise CascadeExhausted(
                    "The critic has already had its one pass.")
            self.critic_passes += 1
        self.note(PLAN, route, why)

    def repair_interpretation(self, why: str = "") -> None:
        if not self.may_repair_interpretation():
            raise CascadeExhausted(
                "The interpretation has already been repaired once.")
        self.interpretation_repairs += 1
        self.note(INTERPRET, "", why)

    @property
    def model_calls(self) -> int:
        return (self.routine_plans + self.complex_replans + self.critic_passes
                + self.interpretation_repairs)

    @property
    def exhausted(self) -> bool:
        """Nothing further is permitted on this turn."""
        return not (self.may_plan_routine() or self.may_replan_complex()
                    or self.may_run_critic())

    def to_dict(self) -> dict[str, Any]:
        return {
            "routine_plans": self.routine_plans,
            "complex_replans": self.complex_replans,
            "critic_passes": self.critic_passes,
            "interpretation_repairs": self.interpretation_repairs,
            "model_calls": self.model_calls,
            "exhausted": self.exhausted,
            "steps": [{"stage": stage, "route": route, "why": why}
                      for stage, route, why in self.steps],
        }


# ---------------------------------------------------------------------------
# §28 — what to do when the complex role cannot be served
# ---------------------------------------------------------------------------

FAIL_SAFE = "FAIL_SAFE"
ROUTINE_WITH_WARNING = "ROUTINE_WITH_WARNING"
QUEUE_FOR_REVIEW = "QUEUE_FOR_REVIEW"

POLICIES: tuple[str, ...] = (FAIL_SAFE, ROUTINE_WITH_WARNING,
                             QUEUE_FOR_REVIEW)

POLICY_ENV = "AI_COMPLEX_UNAVAILABLE_POLICY"


def unavailable_policy(*, demo_safe: bool = False) -> str:
    """The configured policy, with §28's default.

    FAIL_SAFE in Demo Safe Mode whatever is configured. A demo is the one
    setting where a degraded answer is worse than no answer: nobody in the
    room can tell that the plan came from the weaker model, and the whole
    point of the mode is that what is shown can be relied on.
    """
    import os

    configured = (os.environ.get(POLICY_ENV) or "").strip().upper()
    if demo_safe:
        return FAIL_SAFE
    if configured in POLICIES:
        return configured
    if configured:
        logger.warning("%s=%r is not one of %s; using %s.",
                       POLICY_ENV, configured, ", ".join(POLICIES), FAIL_SAFE)
    return FAIL_SAFE


@dataclass(frozen=True)
class Degraded:
    """What §28's policy decided, when the complex role could not be served."""

    policy: str
    #: The route to use instead, or "" when there is none.
    route: str = ""
    #: What the user is told. Never empty: §28 forbids a silent downgrade, and
    #: an empty sentence is what a silent downgrade looks like from here.
    message: str = ""
    #: Whether the answer may be shown at all.
    answerable: bool = False
    #: Whether a review item should be raised.
    queue: bool = False
    #: Whether the plan must be validated more strictly than usual.
    stricter_validation: bool = False


def when_complex_unavailable(reason: str, *, demo_safe: bool = False,
                             policy: str = "") -> Degraded:
    """§28, as a decision the caller cannot ignore.

    "Never silently downgrade from configured Opus-class role" is the whole
    section, and it is enforced by the shape of the return value rather than
    by discipline: every branch carries a message, and the ROUTINE_WITH_WARNING
    branch carries `stricter_validation` as well, because a weaker planner
    checked no harder is exactly the silent downgrade the section forbids.
    """
    # Demo Safe Mode wins over an explicit argument as well as over the
    # environment. A caller passing a policy while the mode is on is almost
    # always a caller that does not know the mode is on, and the one place a
    # degraded answer costs most is the room where nobody can tell.
    chosen = (FAIL_SAFE if demo_safe
              else (policy or "").strip().upper()
              or unavailable_policy(demo_safe=False))

    if chosen == ROUTINE_WITH_WARNING:
        return Degraded(
            policy=chosen, route=ROUTINE, answerable=True,
            stricter_validation=True,
            message=("The complex planning model is unavailable "
                     f"({reason}). This answer was planned by the routine "
                     "model at its highest supported effort and validated "
                     "more strictly. Treat it as provisional."))
    if chosen == QUEUE_FOR_REVIEW:
        return Degraded(
            policy=chosen, route="", answerable=False, queue=True,
            message=("The complex planning model is unavailable "
                     f"({reason}). This request needs it, so it has been "
                     "queued for review rather than answered by a weaker "
                     "model."))
    return Degraded(
        policy=FAIL_SAFE, route="", answerable=False,
        message=("The complex planning model is unavailable "
                 f"({reason}). This request needs it, and CreditProbe will "
                 "not answer it with a different model."))


__all__ = [
    "COMPLEX",
    "CascadeExhausted",
    "Cascade",
    "Degraded",
    "FAIL_SAFE",
    "MAX_COMPLEX_REPLANS",
    "MAX_CRITIC_PASSES",
    "MAX_INTERPRETATION_REPAIRS",
    "MAX_ROUTINE_PLANS",
    "POLICIES",
    "POLICY_ENV",
    "QUEUE_FOR_REVIEW",
    "ROUTINE_WITH_WARNING",
    "STAGES",
    "Situation",
    "unavailable_policy",
    "when_complex_unavailable",
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
