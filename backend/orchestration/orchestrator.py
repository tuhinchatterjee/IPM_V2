"""
Ask CreditProbe, from question to answer.

This is the front door, and the order of its stages is the architecture:

    message
      → REMEMBER   what this investigation has already established
      → READ       the live model, against the catalogue and the conversation
      → GUARD      the governed semantic reader checks that reading
      → RESOLVE    "these" becomes five specific identities
      → ROUTE      metadata question, method question, or an analysis
      → PLAN       an Analytical IR, from concepts rather than from phrases
      → VALIDATE   against the governed catalogue (backend/runtime/validation)
      → EXECUTE    parameterised SQL and allowlisted kernels
      → INTERPRET  the model reads the RESULT, never the data

Four things about that order matter more than anything else in this module.

**Nothing computes before something has decided the request is a computation.**
A question about the catalogue never reaches the engine at all.

**The model plans; it does not calculate.** Every figure comes back from the
runtime. There is no branch in this file where model output becomes a number.

**A follow-up is planned from the conversation, not from the sentence.** "Which
of these are Stage 2?" is planned against the identities the previous run
returned — written down, not recalled.

**Nothing here answers a different question.** When a stage fails, the outcome is
a clarification or a stated failure. It is never a nearby analysis that happens
to have a certified answer. That substitution is the defect this rewrite exists
to remove, and there is no code path back to it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.llm import get_provider, is_configured, provider_status
from backend.orchestration import analysis_planner as ap
from backend.orchestration import capability as cap
from backend.orchestration import certified as cert
from backend.orchestration import conversation as cv
from backend.orchestration import coverage as cov
from backend.orchestration import (
    entities,
    followups,
    handlers,
    interpretation,
    investigation,
    referents,
    router,
    spelling,
)
from backend.orchestration import guardrail as gr
from backend.orchestration import invariants as inv
from backend.orchestration import memory as wm
from backend.orchestration import routing as rt
from backend.orchestration import scope as sc
from backend.orchestration.context import retrieve
from backend.semantics import ontology

logger = logging.getLogger(__name__)

#: The stages the UI shows while a question is being answered.
STAGES = [
    {"id": "remembering", "label": "Reading the conversation"},
    {"id": "reading", "label": "Reading the request"},
    {"id": "retrieving", "label": "Retrieving governed metadata"},
    {"id": "planning", "label": "Composing the analysis"},
    {"id": "running", "label": "Running the governed runtime"},
    {"id": "interpreting", "label": "Reading the result"},
]

#: Why an answer could not be produced. Each is a *stated* outcome shown to the
#: user — never a reason to run something else.
FAILED_PLAN = "plan_failed"
FAILED_RUNTIME = "runtime_failed"
FAILED_ROUTE = "unroutable"
#: The answer computed, and then contradicted the question it answered.
FAILED_INVARIANT = "invariant_failed"


def mode() -> dict[str, Any]:
    """What the product says about how it is answering questions.

    The honesty rule lives here, and it is stricter than it used to be. The
    label is derived from calls that have actually succeeded, not from the
    presence of a key: a configured provider whose requests are failing reports
    AI DEGRADED and says what is failing, rather than reporting the product's
    full intelligence over an offline reading.
    """
    from backend.build_info import build_info
    from backend.llm import health as ai_health
    from backend.llm import telemetry
    from backend.orchestration.vocabulary import get_vocabulary

    status = provider_status()
    observed = ai_health()
    vocab = get_vocabulary()
    live = observed["state"] == telemetry.CONNECTED
    configured = bool(observed["configured"])

    return {
        "mode": "model" if live else ("degraded" if configured else "offline"),
        "configured": configured,
        "live": live,
        "label": ("CreditProbe AI" if live else
                  ("AI DEGRADED" if configured else "LIMITED OFFLINE MODE")),
        "provider": status.provider,
        "model_name": status.model or None,
        "state": observed["state"],
        "state_label": observed["label"],
        "description": observed["detail"],
        "ai": observed,
        "roles": _roles(),
        "demo_safe": demo_safe(),
        "routes": [{"id": r, "label": rt.LABELS[r]} for r in rt.ROUTES],
        "build": build_info().to_dict(),
        "limitations": ([] if live else [
            "Questions phrased unusually may not be understood.",
            "Follow-up references are resolved by rule rather than by reading.",
            "The written interpretation is assembled from the result rather "
            "than composed.",
        ]),
        "stages": STAGES,
        "periods": list(vocab.periods),
        "latest_period": vocab.periods[-1] if vocab.periods else "",
        "dimensions": {k: len(v) for k, v in vocab.dimensions.items()},
        "capabilities": [
            {"id": name, "label": cap.LABELS[name],
             "computes": name in cap.COMPUTES}
            for name in cap.ALL
        ],
    }


@dataclass
class Answered:
    """What the orchestrator produces, before it is shaped for the API."""

    question: str
    reading: cap.Reading
    verdict: gr.Verdict = field(default_factory=gr.Verdict)
    continuation: cv.Continuation = field(default_factory=cv.Continuation)
    result: handlers.HandlerResult | None = None
    #: A certified methodology the request named by name. Selected BEFORE the
    #: composer runs — a route, not a rescue. See backend/orchestration/certified.
    certified: cert.Match | None = None
    certified_params: dict[str, Any] = field(default_factory=dict)
    build: ap.AnalysisBuild | None = None
    runtime: Any = None
    written: interpretation.Interpretation | None = None
    clarification: str = ""
    #: The governed choice behind a clarification, when the reason CreditProbe
    #: stopped is that one word means several different figures. Carries the
    #: options so the user picks rather than rephrases.
    ambiguity: dict[str, Any] = field(default_factory=dict)
    #: Set when the governed universe holds nothing about what was asked. A
    #: distinct outcome from a clarification: there is no menu that would make
    #: this answerable, and offering one invites the user to accept an answer to
    #: a different question.
    unsupported: str = ""
    #: Set when CreditProbe could not answer and is saying so. Never a reason to
    #: answer something else.
    failure: str = ""
    failure_kind: str = ""
    #: What the governed universe recognised in the request, when it stopped
    #: because it recognised nothing.
    coverage: dict[str, Any] = field(default_factory=dict)
    #: True when the answer came from what the previous turn produced rather
    #: than from a fresh read of the catalogue or a new analysis.
    from_memory: bool = False
    #: The clause of an earlier request this turn actually answered, when the
    #: user asked for a correction rather than asking a question. Shown, so the
    #: answer says which of their questions it went back to.
    restated: str = ""
    #: The question as CreditProbe read it, when a typo was corrected before
    #: reading, and the words it changed. Empty when it read what was typed.
    read_as: str = ""
    corrections: list[tuple[str, str]] = field(default_factory=list)
    #: The probes a broad investigation ran, when this turn was one.
    investigation: dict[str, Any] = field(default_factory=dict)
    #: What was checked about the result, and what did not hold.
    invariants: Any = None
    #: Which route and model answered this turn.
    decision: Any = None
    #: What this answer covers, and what this turn did to it.
    scope: Any = None
    #: Set when a key is configured and the live path could not be used.
    degraded_reason: str = ""
    #: Model calls made for this turn.
    calls: int = 0
    duration_ms: int = 0

    @property
    def computed(self) -> bool:
        return self.runtime is not None

    @property
    def answered(self) -> bool:
        return self.result is not None or self.runtime is not None


def answer(question: str, *, context: Any = None,
           state: cv.ConversationState | None = None,
           memory: wm.WorkingMemory | None = None,
           period: tuple[str, str] | None = None,
           extra_filters: dict[str, Any] | None = None,
           use_certified: bool = True) -> Answered:
    """Read, route, and either answer from metadata or compose and run.

    `period` is a comparison already chosen — from answering a clarification, or
    from refreshing a saved Investigation onto newer data. When it is given the
    planner uses it rather than reading a window out of the question, so a
    refresh onto a different pair of quarters does not silently re-derive the
    original one.

    Raises nothing for an unreadable question: it comes back as a clarification,
    because a question CreditProbe cannot read is a conversation rather than an
    error. It raises nothing for a failed plan either — that comes back as a
    stated failure, for the same reason.
    """
    started = time.perf_counter()
    state = state or cv.ConversationState()
    memory = memory or wm.WorkingMemory()

    # One adjacent-key slip used to cost the whole answer: the reader matches
    # concepts and dimension values by pattern, so `Real Estste` does not
    # degrade the reading, it removes it, and the user gets a menu of concepts
    # in reply to a question that named one. Corrected against the bank's own
    # vocabulary, conservatively, and reported.
    #
    # `asked` is what CreditProbe reads. `question` stays the user's own words,
    # because the answer is shown under the sentence they typed.
    fixed = spelling.normalise(question)
    original, question = question, fixed.text

    # The retrieval is widened by what the conversation is already about, so a
    # follow-up naming no dataset still gets the ones the thread is working in.
    context = context or retrieve(
        question,
        concepts=list(state.concepts or state.metrics),
        datasets=list(state.datasets) or list(memory.datasets))

    # Which route answers this, decided before any model is called. Cheap,
    # deterministic and recorded: a request whose route nobody can see is a
    # request nobody can reproduce.
    decision = rt.decide(question, memory=memory, demo_safe=demo_safe())
    read = router.read(question, context=context, state=state, memory=memory,
                       decision=decision)
    reading = read.reading

    # Re-scored now that the reading exists. The first pass could only see the
    # sentence; this one sees how many datasets and concepts it actually needs,
    # which is where most of the difficulty lives.
    decision = rt.decide(question, reading=reading, memory=memory,
                         demo_safe=demo_safe())
    continuation = referents.resolve(
        question, state, model_action=reading.conversation_action,
        memory=memory)

    answered = Answered(
        question=original, reading=reading, verdict=read.verdict,
        continuation=continuation, calls=read.calls,
        decision=read.decision or decision,
        degraded_reason=read.degraded_reason,
        read_as=fixed.text if fixed.changes else "",
        corrections=list(fixed.changes))

    # A follow-up about what the last turn produced, answered from it. Checked
    # before the dangling-referent guard, because "those" pointing at a field
    # set is resolved, not dangling — it just does not point at customers.
    def finish(target: Answered) -> Answered:
        target.duration_ms = int((time.perf_counter() - started) * 1000)
        return target

    # "You didn't answer my second question." The complaint itself names no
    # figure, so reading it literally produces a menu of concepts — which is
    # what used to happen. What the user is pointing at is the clause of their
    # PREVIOUS request that one result could not cover, and that clause is in
    # memory. It is re-asked here, verbatim, against the same context.
    asked = question
    if continuation.action == cv.CORRECT_INCOMPLETE_RESPONSE:
        left_out = _outstanding_clause(memory)
        if left_out:
            asked = left_out
            answered.restated = left_out

    from_memory = followups.answer(asked, continuation.action, memory, context)
    if from_memory is not None:
        answered.result = from_memory
        answered.from_memory = True
        answered.decision = rt.decide(question, deterministic=True)
        return finish(answered)

    # "Something seems wrong with Contracting. Investigate it." — a request to
    # look, not to compute one figure. Answered with a bounded set of governed
    # probes over the named population, each one an ordinary analysis.
    if investigation.wants_investigation(question):
        looked = _investigate(answered, question, context, memory)
        if looked is not None:
            return finish(looked)

    # A reference with nothing behind it. Asked rather than widened: answering
    # "which of these" against the whole book is a confident answer to a
    # question nobody asked.
    dangling = referents.unresolved(question, state)
    if dangling:
        answered.clarification = dangling
        return finish(answered)

    unknown = _unknown_borrower(question, context)
    if unknown:
        answered.clarification = unknown
        return finish(answered)

    missing = _unavailable_period(question)
    if missing:
        answered.clarification = missing
        return finish(answered)

    # Nothing in the governed universe is about this. Said plainly, and BEFORE
    # any clarification: a menu of figures invites the user to accept an answer
    # about exposure to a question about corporate governance.
    if not continuation.carries_context:
        held = cov.check(question, reading)
        if held.out_of_scope:
            answered.unsupported = held.sentence()
            answered.coverage = held.to_dict()
            return finish(answered)

    if reading.clarification:
        answered.clarification = reading.clarification
        return finish(answered)

    # A reading nobody should act on. Below the floor CreditProbe asks rather
    # than running, because a confident answer to the wrong question is the
    # failure this whole path exists to prevent.
    if reading.confidence < cap.MIN_CONFIDENCE and not reading.computes:
        answered.clarification = (
            "CreditProbe is not sure what that is asking for. Name the figure "
            "or the dataset you mean and it will compose the analysis.")
        return finish(answered)

    # Not an analysis: answer from governed metadata, with no engine call.
    #
    # There is deliberately NO fall-through from here into the planner. A
    # metadata capability whose handler cannot answer says so; sending it on to
    # the analysis planner is how "what fields are in the ratings data?" used to
    # come back as a portfolio figure.
    if reading.intent not in cap.COMPUTES:
        return finish(_from_metadata(answered, question, reading, context))

    # A methodology asked for by name is answered with the bank's approved
    # analysis. This is checked BEFORE composing, which is what makes it a route
    # rather than the rescue that used to sit after a failed composition.
    if use_certified and not continuation.carries_context:
        found = cert.match(question, reading)
        if found is not None:
            answered.certified = found
            answered.certified_params = cert.parameters(
                found, reading, period=period,
                periods=list(getattr(context, "periods", [])))
            return finish(answered)

    return finish(_analyse(answered, question, reading, context, state,
                           continuation, period, extra_filters))


def _repair_plan(answered: Answered, question: str, reading: cap.Reading,
                 context: Any, state: cv.ConversationState,
                 continuation: cv.Continuation,
                 period: tuple[str, str] | None,
                 error: str) -> tuple[Any, cap.Reading] | None:
    """One re-read with the complex model, told exactly what failed.

    Returns None when there is nothing to escalate to — no provider, or the
    turn has already used its repair. A second repair would be a negotiation,
    and a model unconvinced by the validation errors the first time will not be
    convinced by the same errors again; it would only cost the user another few
    seconds before the same outcome.
    """
    previous = answered.decision or rt.decide(question, reading=reading)
    if previous.repairs >= 1 or not is_configured():
        return None

    escalated = rt.escalate(previous, f"The first plan failed validation: {error}")
    answered.decision = escalated

    read = router.read(question, context=context, state=state,
                       decision=escalated)
    answered.calls += read.calls
    if read.reading is None or read.reading.source != "llm":
        return None

    try:
        rebuilt = ap.plan(read.reading, context, question=question,
                          period=period, state=state,
                          continuation=continuation)
    except Exception as e:  # noqa: BLE001 - the repair failed; say so upstream
        logger.info("The repaired plan failed too (%s).", e)
        return None
    return rebuilt, read.reading


def _roles() -> dict[str, Any]:
    """Which model does which job, and any problem with how it is configured.

    Never a key. An administrator who has set four model ids should be able to
    see all four and be told plainly when one of them is not a model the
    provider serves — silently answering with a different model would make a
    certification meaningless.
    """
    from backend.llm import roles

    described = roles.describe()
    try:
        described["problems"] = roles.verify(get_provider())
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not verify model roles: %s", e)
        described["problems"] = []
    return described


def _role_model(name: str) -> str:
    """The model configured for one job, or empty for the shared default."""
    from backend.llm import roles

    try:
        return roles.role(name).model
    except Exception:  # noqa: BLE001
        return ""


def _previous_scope(state: cv.ConversationState) -> sc.ScopeFrame:
    """The scope the last analytical turn settled on."""
    if not state or state.empty:
        return sc.ScopeFrame()
    return sc.ScopeFrame(
        entity_key=state.result.entity_key,
        entity_ids=list(state.result.entity_ids),
        datasets=list(state.datasets),
        filters=[{"field": f.get("kind") or f.get("field") or "",
                  "value": f.get("value") or ""} for f in state.filters],
        metrics=list(state.metrics or state.concepts),
        dimension=(state.dimensions[0] if state.dimensions else ""),
        opening=state.opening_period, closing=state.closing_period,
        grain=state.grain, top_n=state.top_n,
        presentation=state.visualization,
        fingerprint=state.plan_fingerprint)


def demo_safe() -> bool:
    """Whether Demo Safe Mode is on.

    Read from the environment rather than a database so it cannot be changed
    by a request mid-demo, and so a deployment can pin it.
    """
    import os

    return (os.environ.get("DEMO_SAFE_MODE") or "").strip().lower() in {
        "1", "true", "yes", "on"}


def _investigate(answered: Answered, question: str, context: Any,
                 memory: Any = None) -> Answered | None:
    """A broad look at a named population, or None to answer it normally.

    Returns None rather than forcing an investigation when the sentence looks
    like one but names nothing governed, or when every probe came back empty.
    A half-empty investigation is worse than the clarification it replaced.
    """
    request = investigation.read(question, context)
    if not request.valid:
        # "Investigate those." after a ranking. The sentence names no sector
        # because it does not need to — the population is the rows on screen,
        # and the whole point of typed memory is that it is still there. Only
        # a referent with NOTHING behind it is a clarification.
        carried = _carried_subject(memory)
        if carried:
            request = investigation.read(
                question.replace("those", carried).replace("them", carried),
                context)
        if not request.valid:
            if investigation.wants_investigation(question) \
                    and not request.subject:
                answered.clarification = investigation.clarification(question)
                return answered
            return None

    def one(probe: str, **kwargs: Any) -> Answered:
        return answer(probe, **kwargs)

    result = investigation.run(request, question, answer_one=one)
    if result is None:
        return None
    answered.result = result
    answered.investigation = request.to_dict()
    return answered


def _carried_subject(memory: Any) -> str:
    """The population the thread is already about, for a bare "those".

    The remembered SUBJECT rather than the member ids: an investigation runs
    governed probes over a dimension value, and "the five customer ids from the
    last table" is not a dimension value. Empty when the thread has no subject,
    which is the case that has to stay a clarification.
    """
    if memory is None or getattr(memory, "empty", True):
        return ""
    for value, _ in ((getattr(memory, "current_subject", ""), 0),):
        text = str(value or "").strip()
        # Only a real dimension value. A subject like "borrower_financials" is
        # a dataset the thread looked at, not a population to investigate.
        if text and " " not in text[:1] and "_" not in text:
            return text
    return ""


def _unknown_borrower(question: str, context: Any) -> str:
    """A named borrower the published data has never heard of.

    The one thing worse than not knowing who Northwind Trading is, is answering
    as though the question had not named them: "how much exposure do we have to
    Northwind Trading?" would come back as the exposure of the whole book,
    correctly calculated, answering a question nobody asked.

    Narrow on purpose — it is looking for a capitalised proper noun that matched
    no governed dimension value and no published borrower.
    """
    for name in referents_unresolved(question, context):
        if entities.known_borrower(name) is None:
            return (f"CreditProbe could not find {name} in the published data. "
                    "It only reads datasets that have been published and marked "
                    "authoritative, so a borrower it has never been given "
                    "cannot be looked up. Check the name, or ask a Data Steward "
                    "whether that book has been onboarded.")
    return ""


def referents_unresolved(question: str, context: Any) -> list[str]:
    try:
        return entities.unresolved_names(question, context)
    except Exception as e:  # noqa: BLE001 - never lose an answer to this check
        logger.info("Could not check named entities in %r: %s", question, e)
        return []


def _from_metadata(answered: Answered, question: str, reading: cap.Reading,
                   context: Any) -> Answered:
    """Answer a non-analytical capability, or say plainly that it cannot be."""
    if reading.intent == cap.Capability.CLARIFICATION:
        answered.clarification = (
            reading.clarification
            or "CreditProbe needs one more thing before it can answer that. "
               "Name the figure or the dataset you mean.")
        return answered

    try:
        handled = handlers.handle(question, reading, context)
    except Exception as e:  # noqa: BLE001 - a stated failure, not a substitution
        logger.exception("The %s handler failed for %r", reading.intent, question)
        answered.failure_kind = FAILED_ROUTE
        answered.failure = (
            f"CreditProbe could not answer that from its governed metadata. "
            f"The {cap.LABELS.get(reading.intent, reading.intent).lower()} "
            f"lookup failed: {e}")
        return answered

    if handled is None:
        answered.failure_kind = FAILED_ROUTE
        answered.failure = (
            "CreditProbe read this as "
            f"{cap.LABELS.get(reading.intent, reading.intent).lower()}, which "
            "it has no way to answer yet. It has NOT run a different analysis "
            "instead.")
        return answered

    answered.result = handled
    return answered


def _analyse(answered: Answered, question: str, reading: cap.Reading,
             context: Any, state: cv.ConversationState,
             continuation: cv.Continuation,
             period: tuple[str, str] | None,
             extra_filters: dict[str, Any] | None) -> Answered:
    """Compose, validate, run and interpret. Or say why it could not."""
    from backend.runtime.executor import ExecutionClass, execute

    reading = _with_overrides(reading, period, extra_filters)
    answered.reading = reading

    # One word, several materially different figures. Asked rather than
    # defaulted: "show me exposure" answered as drawn balance is wrong for an
    # impairment question and wrong for a concentration question, and it reads
    # exactly as confidently as the right answer would.
    ambiguous = _ambiguous_concept(question, reading, state, continuation)
    if ambiguous is not None:
        found, choice = ambiguous
        answered.clarification = choice.question
        answered.ambiguity = {
            "concept": found.concept_id,
            "business_name": found.business_name,
            "definition": found.definition,
            **choice.to_dict(),
        }
        return answered

    build = None
    try:
        build = ap.plan(reading, context, question=question, period=period,
                        state=state, continuation=continuation)
    except ap.CannotPlan as e:
        answered.clarification = e.clarification
        return answered
    except Exception as e:  # noqa: BLE001
        # Execution-guided repair. The first plan did not compose; the model is
        # asked again with the VALIDATION ERRORS — never with an expected
        # answer, which would be teaching to the test — and at most once.
        logger.info("Composing failed for %r (%s); escalating to repair.",
                    question, e)
        repaired = _repair_plan(answered, question, reading, context, state,
                                continuation, period, str(e))
        if repaired is None:
            answered.failure_kind = FAILED_PLAN
            answered.failure = (
                "CreditProbe could not compose a governed analysis for that "
                f"request. The AI interpretation failed validation: {e}")
            return answered
        build, reading = repaired
        answered.reading = reading

    answered.build = build

    try:
        answered.runtime = execute(
            build.plan, question=question, intent=build.summary,
            certification=ExecutionClass.DYNAMIC,
            population_steps=_population_steps(build))
    except Exception as e:  # noqa: BLE001
        logger.exception("The governed runtime failed for %r", question)
        answered.failure_kind = FAILED_RUNTIME
        answered.failure = (
            "CreditProbe composed the analysis but the governed runtime could "
            f"not complete it: {e}")
        return answered

    # The answer exists. Before anybody sees it, check that it matches the
    # question that was asked — every threshold, every filter, every promised
    # row count, tested against the rows themselves.
    answered.invariants = inv.check_result(build, answered.runtime, question)
    if not answered.invariants.ok:
        logger.warning("Invariants failed for %r: %s", question,
                       [f.check.rule for f in answered.invariants.failures])
        answered.failure_kind = FAILED_INVARIANT
        answered.failure = answered.invariants.sentence()
        return answered

    # What this answer covers, and how this turn changed it. Recorded whether
    # or not it changed: a scope that is only mentioned when it moves is a
    # scope nobody checks when it has not.
    answered.scope = sc.classify(
        _previous_scope(state),
        sc.frame_of(build, continuation, presentation=continuation.presentation),
        action=continuation.action)

    answered.written = interpretation.write(
        question, build.summary, answered.runtime, build=build,
        plan_note=_plan_note(build, continuation),
        model=_role_model("interpretation"))
    if answered.written is not None and answered.written.model:
        answered.calls += 1
    return answered


def _unavailable_period(question: str) -> str:
    """Ask rather than answer when the question names a period nobody holds.

    Falling through to the governed default put a Q2 2026 figure under a Q1
    2015 question with nothing on the screen to say so — the most quietly wrong
    answer the product can give, because every number in it is correct.
    """
    try:
        from backend.orchestration import periods as pd
        from backend.orchestration.vocabulary import get_vocabulary

        available = sorted(get_vocabulary().to_dict().get("periods") or [])
        named = pd.unavailable(question, available)
        if not named:
            return ""
        return (
            f"CreditProbe holds no data for {named}. The governed history runs "
            f"from {available[0]} to {available[-1]}. Name a period inside that "
            "range and it will compose the analysis.")
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not check the periods a question names: %s", e)
        return ""


def _outstanding_clause(memory: Any) -> str:
    """The part of the previous request that one answer could not have covered.

    Empty when there is nothing on record, in which case the correction is
    handled the ordinary way — the user is told what CreditProbe understood and
    asked which part it missed, rather than being given a guess.
    """
    if memory is None:
        return ""
    left = [c for c in (getattr(memory, "outstanding", None) or []) if c.strip()]
    return left[0].strip() if left else ""


def _ambiguous_concept(question: str, reading: cap.Reading,
                       state: cv.ConversationState,
                       continuation: cv.Continuation) -> Any:
    """A governed concept this request names but does not settle.

    Three things count as settling it, and all three are checked before the
    user is asked anything:

      * the request itself says which one ("exposure at default");
      * an explicit filter or metric already names the field; or
      * the conversation settled it earlier, and this turn is a follow-up.

    A follow-up inherits the choice deliberately. Asking "which exposure?" again
    on turn four of a thread that has been working in EAD since turn one is not
    caution, it is amnesia.
    """
    if continuation.carries_context and (state.metrics or state.concepts):
        return None

    settled = " ".join([question, " ".join(reading.metrics),
                        " ".join(f.get("field", "") for f in reading.filters)])
    return ontology.ambiguity_for(list(reading.concepts), settled)


def _with_overrides(reading: cap.Reading, period: tuple[str, str] | None,
                    extra_filters: dict[str, Any] | None) -> cap.Reading:
    """A reading with a chosen period and any Trace-modified filters folded in.

    Filters arriving from a Trace modification are governed choices the user
    made in the UI, so they are added to the READING rather than to the plan:
    everything downstream — the summary, the narrative, the share denominators —
    reads the population from the reading, and a filter bolted on later would
    not reach them.
    """
    if not period and not extra_filters:
        return reading

    import dataclasses

    entities = list(reading.entities)
    for kind, value in (extra_filters or {}).items():
        if isinstance(value, list):
            continue
        entities = [e for e in entities if e.get("kind") != kind]
        entities.append({"kind": str(kind), "value": str(value)})
    # A supplied window says WHICH periods, never that a comparison is wanted.
    # Forcing `two_period` here turned "rank them by EAD" — asked inside a thread
    # that had settled a year-long window — into a movement of the whole book
    # between two quarters. The reading's own requirement decides the shape; the
    # window only decides which periods that shape reads.
    return dataclasses.replace(
        reading, entities=tuple(entities),
        periods=tuple(period) if period else reading.periods)


def _plan_note(build: ap.AnalysisBuild,
               continuation: cv.Continuation) -> str:
    """One line telling the interpreter what this turn inherited.

    Without it a follow-up's interpretation reads as though the population were
    the whole book — the model is shown a five-row table and has no way to know
    those five were carried in rather than selected.
    """
    if not continuation.carries_context:
        return ""
    parts = []
    if continuation.has_population:
        parts.append(f"restricted to the {len(continuation.entity_ids)} "
                     f"{continuation.entity_key} the previous turn returned")
    for key, value in continuation.inherited.items():
        if key != "population":
            parts.append(f"{key} carried forward: {value}")
    if build.carried_concepts:
        parts.append("measures carried from the previous turn: "
                     + ", ".join(build.carried_concepts))
    if not parts:
        return ""
    return ("THIS IS A FOLLOW-UP. It was planned as a continuation — "
            + "; ".join(parts) + ".")


def _population_steps(build: ap.AnalysisBuild) -> list[str] | None:
    """Which steps the reconciliation should count.

    Only the two-period shapes have a population that narrows across several
    steps; a single-period aggregate has one scan and one group, and
    reconciling that would be a table with two rows saying nothing.
    """
    if build.shape not in (ap.COHORT, ap.MOVEMENT):
        return None
    return [str(op.get("id")) for op in build.plan.get("operations") or []]


# ------------------------------------------------------------- remembering


def remember(state: cv.ConversationState, answered: Answered, *,
             headline: str = "", run_id: int | None = None
             ) -> cv.ConversationState:
    """The conversation state after this turn.

    Two rules, and both were learned from watching follow-ups fail.

    **A metadata answer does not disturb the analytical state.** Asking what
    fields the ratings data has, mid-investigation, must not wipe the five
    customers you were working on.

    **A failed turn settles nothing.** A clarification or a stated failure is
    recorded as a turn — it is part of the conversation — but leaves every
    settled value exactly as it was, so answering the clarification continues
    where the thread left off rather than from nothing.
    """
    state.remember_turn(cv.Turn(
        question=answered.question,
        answer=headline or answered.clarification or answered.failure,
        intent=answered.reading.intent,
        run_id=run_id,
        status=("succeeded" if answered.answered else
                ("failed" if answered.failure else "needs_clarification")),
    ))

    if answered.runtime is None or answered.build is None:
        return state

    if not int(getattr(answered.runtime, "row_count", 0) or 0):
        # An empty result settles nothing. "None of these five are Stage 2"
        # answers the question truthfully and leaves the investigation exactly
        # where it was — carrying its filters forward would make the NEXT
        # question inherit a restriction that matched nobody, and every answer
        # after it would be empty for a reason no longer on screen.
        if answered.continuation.has_population and not state.result.has_population:
            state.result.entity_key = answered.continuation.entity_key
            state.result.entity_ids = list(answered.continuation.entity_ids)
            state.result.entity_labels = dict(answered.continuation.entity_labels)
        return state

    build = answered.build
    reading = answered.reading
    state.subject = reading.objective or answered.question
    state.intent = reading.intent
    state.conversation_action = answered.continuation.action
    state.concepts = [m.concept.label for m in build.matches]
    state.metrics = list(state.concepts)
    state.dimensions = [build.dimension] if build.dimension else []
    state.filters = [{"kind": f, "value": v} for f, v in build.filters]
    state.grain = build.grain
    state.shape = build.shape
    state.top_n = build.top_n
    state.conditions = [{**c.to_dict(), "describe": c.describe()}
                        for c in build.conditions]
    state.plan_summary = build.summary
    state.ir = dict(build.plan)
    state.datasets = list(build.datasets)
    state.join_path = list(build.joins)
    state.certified_methods = list(reading.candidate_methods)

    if build.opening and build.closing:
        state.opening_period, state.closing_period = build.opening, build.closing
        state.periods = [build.opening, build.closing]
    elif build.period:
        state.opening_period, state.closing_period = "", ""
        state.periods = [build.period]

    fresh = _snapshot(answered.runtime, build, run_id=run_id)
    if not fresh.has_population and answered.continuation.has_population:
        # A follow-up that matched nothing does not erase what "these" refers
        # to. "None of the five are Stage 2" leaves the five on the table, and
        # the next question is almost always about them.
        fresh.entity_key = answered.continuation.entity_key
        fresh.entity_ids = list(answered.continuation.entity_ids)
        fresh.entity_labels = dict(answered.continuation.entity_labels)
    state.result = fresh
    state.plan_fingerprint = str(
        getattr(answered.runtime, "fingerprint", "") or "")
    return state


#: Columns that identify a row, most specific first. The first one present in
#: the result is what a referent resolves against.
_IDENTITY_COLUMNS = ("customer_id", "account_id", "borrower_id")


def _snapshot(runtime: Any, build: ap.AnalysisBuild, *,
              run_id: int | None) -> cv.ResultShape:
    """What the result was, in the shape a follow-up needs it.

    Identities and a handful of headline rows — never the table. A follow-up
    re-reads governed data through the runtime; carrying rows forward would turn
    the next answer into a report about a cached copy of the book.
    """
    rows = list(getattr(runtime, "rows", []) or [])
    columns = [{"name": str(c.get("name")), "label": str(c.get("label")
                                                         or c.get("name")),
                "unit": str(c.get("unit") or "")}
               for c in (getattr(runtime, "columns", []) or [])]
    names = {c["name"] for c in columns}

    key = next((c for c in _IDENTITY_COLUMNS if c in names), "")
    if not key and build.dimension and build.dimension in names:
        # A grouped answer is keyed by its dimension: "show only the five
        # largest sectors" refers to sectors, and those are identities too.
        key = build.dimension

    ids: list[str] = []
    labels: dict[str, str] = {}
    if key:
        label_column = ("borrower_name" if "borrower_name" in names else "")
        for row in rows[:cv.MAX_ENTITY_IDS]:
            value = row.get(key)
            if value is None or str(value) == "":
                continue
            ids.append(str(value))
            if label_column and row.get(label_column):
                labels[str(value)] = str(row[label_column])

    return cv.ResultShape(
        columns=columns, row_count=len(rows), entity_key=key if ids else "",
        entity_ids=ids, entity_labels=labels,
        sample=[{k: v for k, v in row.items() if k in names}
                for row in rows[:cv.MAX_SNAPSHOT_ROWS]],
        run_id=run_id,
    )


__all__ = ["FAILED_PLAN", "FAILED_ROUTE", "FAILED_RUNTIME", "STAGES",
           "Answered", "answer", "get_provider", "is_configured", "mode",
           "remember"]
