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
from backend.orchestration import (
    analyst,
    association,
    compound,
    entities,
    followups,
    handlers,
    interpretation,
    investigation,
    referents,
    router,
    spelling,
)
from backend.orchestration import (
    assessment as az,
)
from backend.orchestration import capability as cap
from backend.orchestration import certified as cert
from backend.orchestration import conversation as cv
from backend.orchestration import coverage as cov
from backend.orchestration import decomposition as dcp
from backend.orchestration import guardrail as gr
from backend.orchestration import invariants as inv
from backend.orchestration import memory as wm
from backend.orchestration import reuse as ru
from backend.orchestration import routing as rt
from backend.orchestration import scope as sc
from backend.orchestration.context import retrieve
from backend.regulatory import intent as regulatory_intent
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
        # "LIMITED OFFLINE MODE" reads as a fault. It is a mode: the governed
        # local reader, which answers the supported banking questions
        # deterministically and traceably. "AI DEGRADED" stays, because a key
        # that is configured and failing IS a fault and an administrator needs
        # to know.
        "label": ("CreditProbe AI" if live else
                  ("AI DEGRADED" if configured else "GOVERNED LOCAL READER")),
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
    #: Set when a question was refused because it asks what a
    #: regulation says and no approved Regulatory Knowledge Release is
    #: active. Kept separate from `coverage` because the reason is
    #: different: the data is not missing, the APPROVED SOURCE is.
    regulatory: dict[str, Any] = field(default_factory=dict)
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
    #: §12: the Analysis Portfolio the planner chose, as the typed object
    #: rather than as the dict inside `investigation`. Kept separately because
    #: the coverage and follow-up code reads the scores and decisions, and
    #: round-tripping them through a dict would mean re-parsing what is
    #: already in hand.
    portfolio: Any = None
    #: What those probes actually did — datasets, periods, grains, invariants,
    #: evidence facts, Trace nodes. Set only on a composed answer. §3.
    composition: Any = None
    #: What was checked about the result, and what did not hold.
    invariants: Any = None
    #: The eight sections a client answer has to carry (P0.8). Composed from
    #: the analyst observations, so every sentence rests on a computed figure.
    sections: Any = None
    #: Whether this answer may be put in front of a client, and why not.
    #: P0.8's fourteen checks, run once, here, rather than distributed across
    #: the places that produce each part of the answer.
    gate: Any = None
    #: Which route and model answered this turn.
    decision: Any = None
    #: Which extra clauses of a compound question were answered in this turn,
    #: and which were left outstanding for the correction path.
    compound: dict[str, Any] = field(default_factory=dict)
    #: How the measures in the result move together, where the question asked
    #: whether a pattern holds. Never a cause.
    association: dict[str, Any] = field(default_factory=dict)
    #: The analyst-grade reading of a result that was already on the table,
    #: when this turn reused one instead of computing anything.
    assessment: Any = None
    #: Where those rows came from, and the fact that nothing was rescanned.
    provenance: Any = None
    #: The reused result itself, for the answer and the Trace.
    cached: Any = None
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

    # "Does the relationship between grade, ECL coverage and DSCR appear
    # consistent across grades?" was read as a question about how two datasets
    # JOIN, because it contains the word "relationship". It is a question about
    # a pattern in the figures, and answering it needs the runtime rather than
    # the catalogue.
    reading = _as_association(question, reading)

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

    # "Does this trend make sense?" — a question about the rows that are
    # already on the screen. Answered from them.
    #
    # This must come before every path that composes or executes anything. The
    # previous behaviour re-planned and re-executed to reproduce the table the
    # user was looking at while they typed: full analytical cost for a question
    # that needed none, a re-guess of a sentence that names no measure, and —
    # the part that actually matters — a SECOND result. Two executions a second
    # apart are two results, and describing the second one under a sentence
    # that says "this" is wrong even when the figures agree.
    if ru.wants(question) and not ru.asks_to_expand(question):
        return finish(_assess_previous(answered, question, state))

    # "Show it as a graph." The same rows, drawn differently.
    #
    # This never reached the runtime in the sense of producing different
    # figures — the row counts matched, which is what the test asserted — but
    # it re-planned and re-executed to get them. Paying the full analytical
    # cost of a question to change a chart type is not merely wasteful: two
    # executions are two results, and "show IT as a graph" promises the one
    # already on the screen.
    if continuation.action == cv.MODIFY_PRESENTATION:
        redrawn = _redraw_previous(answered, question, state, continuation)
        if redrawn is not None:
            return finish(redrawn)

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

    # Nothing in the governed universe is about this. Said plainly, and BEFORE
    # any clarification: a menu of figures invites the user to accept an answer
    # about exposure to a question about corporate governance.
    #
    # Checked before the unknown-borrower guard, because both can be true and
    # only one of them is the point. "Did the CEO of Al Rajhi Contracting
    # resign?" was answered "CreditProbe could not find Al Rajhi Contracting" —
    # accurate, and it implies that naming a borrower CreditProbe DOES hold
    # would produce an answer about a resignation. It would not.
    #
    # An association question is exempt. "Does this trend make sense?" names no
    # governed noun at all, so the coverage check found "make sense", did not
    # recognise it, and replied that CreditProbe holds no data about it — a
    # refusal to answer one of the most ordinary questions an analyst is asked,
    # about figures that were already on the screen.
    if not continuation.carries_context and not association.wants(question):
        held = cov.check(question, reading)
        if held.out_of_scope:
            answered.unsupported = held.sentence()
            answered.coverage = held.to_dict()
            return finish(answered)

    # A question about what a REGULATION SAYS, with no approved Regulatory
    # Knowledge Release to answer it from.
    #
    # Found by the demonstration question set. "What does the circular say
    # about provisioning for Stage 2?" ran a SIMPLE_ANALYSIS over
    # `ifrs9_staging` and presented the result, with no circular in the corpus
    # and no release active. The coverage check above had passed it, correctly:
    # provisioning and Stage 2 ARE governed concepts. Nothing asked the
    # different question - is this a request for a figure, or for the content
    # of a document? Those need different sources and only one of them exists.
    #
    # `backend/regulatory/assurance.py` already makes `release_active` a
    # CRITICAL gate. The gate was right and nothing routed to it.
    documentary = regulatory_intent.read(question)
    if documentary.documentary and not regulatory_intent.may_answer(
            _session_for_regulatory()):
        answered.unsupported = regulatory_intent.refusal(documentary)
        answered.regulatory = documentary.to_dict()
        return finish(answered)

    # A borrower CreditProbe does not hold is only the reason a question cannot
    # be answered when the question was otherwise answerable. "Did the CEO of
    # Al Rajhi Contracting resign?" was answered "CreditProbe could not find Al
    # Rajhi Contracting" — accurate, and it implies that naming a borrower it
    # DOES hold would produce an answer about a resignation. It would not.
    if cov.names_a_measure(question) or continuation.carries_context:
        unknown = _unknown_borrower(question, context)
        if unknown:
            answered.clarification = unknown
            return finish(answered)

    missing = _unavailable_period(question)
    if missing:
        answered.clarification = missing
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


def _as_association(question: str, reading: cap.Reading) -> cap.Reading:
    """Route a question about a PATTERN to the runtime rather than the catalogue.

    Only where the sentence asks whether a relationship holds — a narrow test,
    because "how is ratings data connected to IFRS 9?" is a genuine catalogue
    question about joins and must stay one. What is redirected is the family
    that asks whether the FIGURES are consistent, which no amount of metadata
    can answer.
    """
    import dataclasses

    if not association.wants(question):
        return reading
    if reading.intent in cap.COMPUTES:
        return reading
    if reading.intent not in cap.FROM_DATA_BUILDER:
        return reading
    return dataclasses.replace(
        reading, intent=cap.Capability.ANALYSIS,
        objective=(reading.objective
                   or "whether the pattern in the figures holds"))


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
    return _role_call(name)["model"]


def _role_call(name: str) -> dict[str, str]:
    """The model and effort for one job, in the shape a provider call takes.

    Both travel with the call so the telemetry records what actually served it.
    Inferring the role from the purpose afterwards worked until two stages
    shared a purpose, and a settings page that reports the wrong model is worse
    than one that reports none.
    """
    from backend.llm import roles

    try:
        configured = roles.role(name)
        return {"model": configured.model, "effort": configured.effort}
    except Exception:  # noqa: BLE001
        return {"model": "", "effort": ""}


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


def _session_for_regulatory() -> Any:
    """A session to read the active Regulatory Release with, or None.

    None means "cannot tell", and `may_answer` treats that as NO. A regulatory
    answer given because the database was briefly unreachable is the worst
    possible reason to have given one.
    """
    try:
        from backend.db.engine import get_session

        with get_session() as session:
            return session
    except Exception:  # noqa: BLE001 - see the docstring
        return None


def demo_safe() -> bool:
    """Whether Demo Safe Mode is on.

    Read from the environment rather than a database so it cannot be changed
    by a request mid-demo, and so a deployment can pin it.

    Delegated to `backend.release.demo_safe`, which is the only module that
    should know the variable's name. This function read `DEMO_SAFE_MODE`
    while that one read `AI_DEMO_SAFE_MODE`, so the documented setting turned
    on the routing half of the mode and left the half that decides whether an
    answer may be shown switched off.
    """
    from backend.release import demo_safe as policy

    return policy.enabled()


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
        # The population was identified; the checks over it did not complete.
        # Said as a failure, not as a question about a population the user
        # already named.
        stopped = investigation.why_empty()
        if stopped:
            answered.failure = stopped
            answered.failure_kind = "INVESTIGATION_INCOMPLETE"
            return answered
        return None
    answered.result = result
    answered.investigation = request.to_dict()
    answered.portfolio = request.portfolio
    answered.composition = getattr(result, "composition", None)
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


def _first_clause(question: str, context: Any) -> tuple[str, Any]:
    """The first thing a compound sentence asks, with its own retrieval.

    Returns the question and context unchanged when the sentence asks one
    thing, which is nearly always. Retrieval is deterministic and costs no
    model call, so narrowing it for a compound question is free.
    """
    parts = compound.clauses(question)
    if len(parts) < 2:
        return question, context
    try:
        from backend.orchestration.context import retrieve

        return parts[0], retrieve(parts[0])
    except Exception as e:  # noqa: BLE001 - fall back to the whole sentence
        logger.info("Could not retrieve for the first clause of %r: %s",
                    question, e)
        return question, context


def _from_metadata(answered: Answered, question: str, reading: cap.Reading,
                   context: Any) -> Answered:
    """Answer a non-analytical capability, or say plainly that it cannot be."""
    if reading.intent == cap.Capability.CLARIFICATION:
        answered.clarification = (
            reading.clarification
            or "CreditProbe needs one more thing before it can answer that. "
               "Name the figure or the dataset you mean.")
        return answered

    # A compound question is retrieved for clause by clause. "What fields are
    # available in the ratings data, and which are financial ratios?" scored
    # the borrower financials table top on the strength of the SECOND clause,
    # and then answered the first one about the wrong dataset. The first clause
    # decides what the first answer is about.
    asked, context = _first_clause(question, context)

    try:
        handled = handlers.handle(asked, reading, context)
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

    # "What fields are available in the ratings data, AND which are financial
    # ratios?" is two questions. Answering the first and silently dropping the
    # second produces something that looks complete, which is why the next
    # message was "you didn't answer my second question". The remaining clauses
    # are put through the follow-up path against the answer just produced.
    answered.compound = compound.complete(answered, question, context).to_dict()
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

    # A governed method, routed BEFORE the ambiguity gate. "Decompose the change
    # in ECL into exposure, stage migration, PD, LGD and mix" names exposure as
    # a DRIVER, not as the measure to compute, and the gate read it as the
    # measure — so the question that most needed this method was answered with a
    # menu asking which exposure figure to use.
    if dcp.wants(question):
        return _decompose_ecl(answered, question, reading, context, period)

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
        # A clarification offers a menu, and a menu is only useful to somebody
        # who named something on it. Asked "what is the CEO's tenure?",
        # CreditProbe listed exposure at default, expected credit loss, rating
        # and days past due — inviting the reader to accept an answer to a
        # question they did not ask. Where the sentence names no governed
        # measure at all, the honest answer is that there is nothing to
        # measure, and it is said instead of the menu.
        if _nothing_to_measure(question, continuation):
            held = cov.check(question)
            answered.unsupported = held.sentence() if held.out_of_scope else (
                "CreditProbe has no governed data about what that asks for. It "
                "answers from the figures a steward has published — exposure, "
                "impairment, ratings, delinquency, covenants — and it holds "
                "nothing that measures this. It has NOT answered a different "
                "question instead.")
            answered.coverage = held.to_dict()
            return answered
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

    # Nothing matched. "0 customers where IFRS 9 stage is in 2, 3" is true and
    # useless; what an analyst says is where the population actually sits. That
    # needs a second question of the data, and it is asked only here — an empty
    # result is the one case where no working answer can be disturbed.
    if getattr(answered.runtime, "row_count", 0) == 0:
        from backend.orchestration import partition as pt

        build.partition = pt.explain(build, question)

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

    # What an analyst would notice, computed from the result. Given to the
    # model as the things worth saying rather than left to it to find, and
    # standing on its own where there is no model. A style guide produces prose
    # that sounds like analysis; a list of computed facts produces prose about
    # the largest driver by name.
    build.observations = analyst.observe(build, answered.runtime,
                                         answered.runtime.summary or {})

    # A question about whether a pattern holds gets the pattern described:
    # monotonicity, rank association, and the groups that do not fit it. Never a
    # cause — the caveat that goes with it is fixed wording for that reason.
    if association.wants(question):
        answered.association = _describe_association(build, answered.runtime)
        build.association = answered.association

    answered.written = interpretation.write(
        question, build.summary, answered.runtime, build=build,
        noticed=analyst.prompt_block(build.observations),
        plan_note=_plan_note(build, continuation),
        **_role_call("interpretation"))
    if answered.written is not None and answered.written.model:
        answered.calls += 1

    return answered


def _decompose_ecl(answered: Answered, question: str, reading: cap.Reading,
                   context: Any, period: tuple[str, str] | None) -> Answered:
    """Attribute a movement in ECL across the governed drivers. P0.4.

    A handler rather than a planned analysis: the attribution is per account
    across two periods and does not fit the aggregate/ranking/movement shapes
    the planner compiles. It returns the same HandlerResult shape as every
    other capability, so the answer surface renders one thing.
    """
    try:
        answered.result = dcp.answer(
            question, reading, context=context, period=period,
            user_id=getattr(context, "user_id", None))
    except Exception as e:  # noqa: BLE001 - a method must not become a 500
        logger.exception("The ECL decomposition failed: %s", e)
        answered.failure = (
            "CreditProbe could not compute the ECL decomposition. Nothing "
            "partial has been reported as an answer.")
        answered.failure_kind = "EXECUTION"
    return answered


def _nothing_to_measure(question: str, continuation: Any) -> bool:
    """Whether the honest answer is "we hold nothing about that" rather than a menu.

    Two conditions, and both are needed. The sentence must name no governed
    measure — otherwise it is a question CreditProbe could answer if it knew
    which figure was meant, and a menu is exactly right. And it must be ABOUT
    something the catalogue does not recognise, which is what the unknown terms
    say.

    Without the second condition this swallowed "how is the book doing?" — a
    vague question about the portfolio, which deserves a menu and got a refusal.
    Without the first it swallowed nothing at all, and "did the CEO resign?"
    was answered with a list of governed figures to choose between.
    """
    if getattr(continuation, "carries_context", False):
        return False
    if cov.names_a_measure(question):
        return False
    held = cov.check(question)
    return held.out_of_scope or len(held.unknown_terms) >= cov.MIN_UNKNOWN_TERMS


def _assess_previous(answered: Answered, question: str,
                     state: cv.ConversationState) -> Answered:
    """Answer a question about the previous result, from the previous result.

    Three outcomes, and no fourth:

      * an assessment, computed by approved kernels over the stored rows;
      * a statement of what the stored result cannot establish, with the
        analysis that would — §18, and the reason this path exists: silently
        widening the scope to make a question answerable produces a confident
        answer about a population the user never asked about;
      * a fall-through to the ordinary planner, when there is no previous
        result at all and the sentence is somebody's opening question.

    Nothing here can reach governed data. `assessment.assess` is handed a
    `Cached` and nothing else, and `Cached` holds rows rather than a
    connection, so "no governed data was rescanned" is a property of what this
    function is able to call rather than a claim about what it chose to.
    """
    cached = ru.cached_result(state)
    if cached is None:
        # No previous result. Left to the ordinary path, which will read the
        # sentence, find no measure in it, and ask — which is right, because
        # from a standing start "does this trend make sense?" genuinely is
        # unanswerable.
        answered.continuation.action = cv.NEW_REQUEST
        answered.clarification = (
            "There is no previous result in this investigation to assess. Ask "
            "an analytical question first, and CreditProbe will describe the "
            "pattern in what it returns.")
        return answered

    answered.continuation.action = cv.ASSESS_PREVIOUS_RESULT
    answered.cached = cached
    found = az.assess(cached, question)
    answered.assessment = found
    answered.provenance = ru.provenance_of(
        cached, kernels_run=[k.get("kernel", "") for k in found.kernels])

    if not found.usable:
        answered.clarification = _cannot_assess(found)
        return answered

    answered.result = _assessment_result(question, cached, found,
                                         answered.provenance)
    answered.from_memory = True
    answered.decision = rt.decide(question, deterministic=True)
    answered.association = {
        **found.association, "sentence": found.conclusion,
        "caveat": found.caveat}
    return answered


def _redraw_previous(answered: Answered, question: str,
                     state: cv.ConversationState,
                     continuation: cv.Continuation) -> Answered | None:
    """Draw the previous result differently, without recomputing it.

    Returns None when there is no previous result to redraw, in which case the
    ordinary path runs and — correctly — asks what to draw.
    """
    from backend.orchestration import handlers, visualize

    cached = ru.cached_result(state)
    if cached is None or not cached.usable:
        return None

    requested = str(continuation.presentation or "")
    visual = visualize.choose(cached.columns, cached.rows, requested=requested)
    provenance = ru.provenance_of(cached)
    answered.cached = cached
    answered.provenance = provenance
    answered.from_memory = True
    answered.decision = rt.decide(question, deterministic=True)

    said = cached.question or "the previous result"
    answered.result = handlers.HandlerResult(
        answer=f"The same result, shown as {visual.label()}.",
        rows=[dict(r) for r in cached.rows],
        columns=[dict(c) for c in cached.columns],
        values={},
        detail={"reuse": provenance.to_dict(), "previous": cached.to_dict(),
                "presentation": visual.to_dict(), "of": said},
        graph=_redraw_graph(question, cached, visual, provenance),
        follow_ups=[],
        warnings=[],
    )
    return answered


def _redraw_graph(question: str, cached: Any, visual: Any,
                  provenance: Any) -> Any:
    """Four nodes: asked, the result it refers to, reused, drawn."""
    from backend.trace.model import NodeType, TraceGraph, TraceNode

    graph = TraceGraph()
    graph.add_node(TraceNode(id="question", type=NodeType.USER_PROMPT,
                             label="Question asked",
                             config={"question": question}))
    read = graph.add_node(TraceNode(
        id="intent", type=NodeType.CAPABILITY,
        label="Read as: a change of presentation",
        config={"conversation_action": cv.MODIFY_PRESENTATION,
                "computation_required": False,
                "rule": ("This changes how the result is shown, not what it "
                         "contains. " + NO_RESCAN)}))
    read.mark_ok()
    graph.connect("question", "intent")

    previous = graph.add_node(TraceNode(
        id="previous_result", type=NodeType.PREVIOUS_RESULT,
        label=(f"Previous result — {cached.scope_sentence()}"
               if cached.scope_sentence() else "Previous result"),
        config={"source_run_id": cached.run_id,
                "result_fingerprint": cached.fingerprint,
                "original_question": cached.question,
                "original_periods": list(cached.periods)}))
    previous.mark_ok(rows_out=cached.row_count)
    graph.connect("intent", "previous_result")

    reused = graph.add_node(TraceNode(
        id="reused_result", type=NodeType.REUSED_RESULT,
        label=f"{len(cached.rows)} rows reused — nothing recomputed",
        config={**provenance.to_dict(), "statement": NO_RESCAN}))
    reused.mark_cached(rows_in=cached.row_count, rows_out=len(cached.rows))
    graph.connect("previous_result", "reused_result")

    drawn = graph.add_node(TraceNode(
        id="visualisation", type=NodeType.VISUALIZATION,
        label=visual.label() or "Table",
        config=visual.to_dict()))
    drawn.mark_ok(rows_in=len(cached.rows), rows_out=len(cached.rows))
    graph.connect("reused_result", "visualisation")

    answer = graph.add_node(TraceNode(
        id="result", type=NodeType.RESULT, label="The same result, redrawn",
        config={"from": "the previous result", "statement": NO_RESCAN}))
    answer.mark_ok(rows_out=len(cached.rows))
    graph.connect("visualisation", "result")
    graph.compute_hashes()
    return graph


def _cannot_assess(found: Any) -> str:
    """What the stored result cannot establish, and what would.

    Both halves matter. Saying only what is missing leaves the user to design
    the follow-up CreditProbe just declined to guess at; saying only the offer
    hides the reason the question was not simply answered.
    """
    said = str(found.unavailable or "").strip()
    said = said[:1].upper() + said[1:] if said else "This cannot be assessed."
    offer = str(found.offer or "").strip()
    return f"{said}. {offer}".strip() if offer else f"{said}."


def _assessment_result(question: str, cached: Any, found: Any,
                       provenance: Any) -> Any:
    """The assessment as the shape the answer surface already renders.

    A `HandlerResult`, because the alternative is a second result shape and a
    second renderer, and the second renderer is the one that drifts.
    """
    from backend.orchestration import handlers, suggestions

    rows = [dict(r) for r in cached.rows]
    graph = _reuse_graph(question, cached, found, provenance)
    return handlers.HandlerResult(
        answer=found.conclusion,
        rows=rows,
        columns=[dict(c) for c in cached.columns],
        values={},
        detail={
            "assessment": found.to_dict(),
            "reuse": provenance.to_dict(),
            "previous": cached.to_dict(),
            "kernels_available": kernels_module().approved(),
        },
        graph=graph,
        follow_ups=list(found.next_analysis)[:suggestions.MAX_SUGGESTIONS],
        # Deliberately empty. The limitations and the causation caveat belong
        # to the narrative, which renders them once under Limitations; putting
        # the same sentences on the step as well showed the reader the caveat
        # twice, and three identical sentences read as three problems.
        warnings=[],
    )


#: The one sentence a reused answer's Trace must be able to state. Fixed
#: wording: it is a claim about what the product did, and a claim of that kind
#: cannot be paraphrased differently on different screens.
NO_RESCAN = "No governed data was rescanned for this follow-up."


def _reuse_graph(question: str, cached: Any, found: Any,
                 provenance: Any) -> Any:
    """The Trace for an answer computed from a result that already existed.

    Five nodes, and deliberately no others. There is no dataset node, no join
    node and no SQL node, because none of those ran — and inventing one so the
    picture looks as full as an analytical Trace would make every genuine
    Trace in the product less believable.
    """
    from backend.trace.model import NodeType, TraceGraph, TraceNode

    graph = TraceGraph()
    graph.add_node(TraceNode(
        id="question", type=NodeType.USER_PROMPT,
        label="Question asked", config={"question": question}))

    read = graph.add_node(TraceNode(
        id="intent", type=NodeType.CAPABILITY,
        label="Read as: a question about the previous result",
        config={
            "conversation_action": cv.ASSESS_PREVIOUS_RESULT,
            "computation_required": False,
            "rule": ("This question asks whether the pattern in the result "
                     "already on the table holds. It is answered from that "
                     "result. " + NO_RESCAN),
        }))
    read.mark_ok()
    graph.connect("question", "intent")

    previous = graph.add_node(TraceNode(
        id="previous_result", type=NodeType.PREVIOUS_RESULT,
        label=(f"Previous result — {cached.scope_sentence()}"
               if cached.scope_sentence() else "Previous result"),
        config={
            "source_run_id": cached.run_id,
            "result_fingerprint": cached.fingerprint,
            "original_question": cached.question,
            "original_periods": list(cached.periods),
            "original_scope": cached.scope_sentence(),
            "original_filters": [dict(f) for f in cached.filters],
            "datasets": list(cached.datasets),
            "plan_summary": cached.plan_summary,
        }))
    previous.mark_ok(rows_out=cached.row_count)
    graph.connect("intent", "previous_result")

    reused = graph.add_node(TraceNode(
        id="reused_result", type=NodeType.REUSED_RESULT,
        label=f"{len(cached.rows)} rows reused — nothing rescanned",
        config={
            **provenance.to_dict(),
            "read_from": cached.source,
            "statement": NO_RESCAN,
            "rule": ("A question about a result is answered from that result. "
                     "Re-executing the analysis would produce a SECOND result, "
                     "and describing it under a sentence that says \"this\" "
                     "would be wrong even where the figures agreed."),
        }))
    reused.mark_cached(rows_in=cached.row_count, rows_out=len(cached.rows))
    graph.connect("previous_result", "reused_result")

    statistic = graph.add_node(TraceNode(
        id="derived_statistic", type=NodeType.KERNEL,
        label=_kernel_label(found),
        config={
            "kernels": [dict(k) for k in found.kernels],
            "approved": kernels_module().approved(),
            "limitations": list(found.limitations),
            "rule": ("Only allowlisted numerical kernels may run over a "
                     "reused result. A kernel is a named function in "
                     "backend/orchestration/kernels.py; there is no generated "
                     "expression and no arbitrary code path."),
        }))
    statistic.mark_ok(rows_in=len(cached.rows),
                      rows_out=len(found.kernels))
    graph.connect("reused_result", "derived_statistic")

    check = graph.add_node(TraceNode(
        id="evidence", type=NodeType.RECONCILIATION,
        label=f"{len(found.evidence_values)} figures the answer could quote",
        config={
            "values": dict(found.evidence_values),
            "entities": _assessed_entities(found),
            "causal_claim": False,
            "caveat": found.caveat,
            "rule": ("The assessment may quote only figures a kernel "
                     "computed and only groups the previous result named. It "
                     "may describe how the measures move together; it may not "
                     "assert that one causes the other."),
        }))
    check.mark_ok()
    graph.connect("derived_statistic", "evidence")

    answer = graph.add_node(TraceNode(
        id="result", type=NodeType.RESULT,
        label=found.conclusion or "Assessment",
        config={"from": "the previous result", "statement": NO_RESCAN,
                "next_analysis": list(found.next_analysis)}))
    answer.mark_ok(rows_out=len(cached.rows))
    graph.connect("evidence", "result")
    graph.compute_hashes()
    return graph


def _kernel_label(found: Any) -> str:
    names = sorted({str(k.get("kernel") or "") for k in found.kernels})
    names = [n for n in names if n]
    if not names:
        return "No statistic could be derived"
    shown = ", ".join(n.replace("_", " ") for n in names[:4])
    return f"{len(found.kernels)} approved kernels — {shown}"


def _assessed_entities(found: Any) -> list[str]:
    """Every group the assessment is allowed to name."""
    out: list[str] = []
    for pair in (found.association.get("pairs") or []):
        out.extend(str(x) for x in (pair.get("exceptions") or []))
    for trend in (found.association.get("trends") or []):
        out.extend(str(x) for x in (trend.get("breaks") or []))
    return sorted({x for x in out if x})


def kernels_module() -> Any:
    from backend.orchestration import kernels

    return kernels


def _describe_association(build: Any, runtime: Any) -> dict[str, Any]:
    """The association in this result, or an empty dict when there is none."""
    from backend.orchestration import presentation as pr

    try:
        found = association.analyse(pr.schema(runtime, build),
                                    list(getattr(runtime, "rows", []) or []))
    except Exception as e:  # noqa: BLE001 - a description must not lose an answer
        logger.warning("The association could not be described: %s", e)
        return {}
    if not found.usable:
        return {**found.to_dict(), "sentence": "", "caveat": ""}
    return {**found.to_dict(), "sentence": association.describe(found),
            "caveat": association.CAVEAT}


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

    fresh = _snapshot(answered.runtime, build, run_id=run_id,
                      question=answered.question)
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


def _result_fingerprint(runtime: Any) -> str:
    """One short string identifying the execution that produced these rows.

    The runtime's fingerprint is a dict of five component hashes plus the
    dataset versions, which is exactly right on the Trace and useless as an
    identifier: stringifying it puts eight hundred characters into the
    conversation state and into every reused answer's provenance. The run hash
    is the single value that changes whenever any component does, so that is
    what is carried; anything without one is digested instead of truncated,
    because a truncated hash is a hash that collides.
    """
    import hashlib
    import json

    found = getattr(runtime, "fingerprint", None)
    if isinstance(found, dict):
        run = str(found.get("run") or "").strip()
        if run:
            return run
        digest = json.dumps(found, sort_keys=True, separators=(",", ":"),
                            default=str)
        return hashlib.sha256(digest.encode()).hexdigest()[:16]
    return str(found or "")


#: Columns that identify a row, most specific first. The first one present in
#: the result is what a referent resolves against.
_IDENTITY_COLUMNS = ("customer_id", "account_id", "borrower_id")


def _snapshot(runtime: Any, build: ap.AnalysisBuild, *,
              run_id: int | None, question: str = "") -> cv.ResultShape:
    """What the result was, in the shape a follow-up needs it.

    Identities and a handful of headline rows — never the table. A follow-up
    re-reads governed data through the runtime; carrying rows forward would turn
    the next answer into a report about a cached copy of the book.
    """
    from backend.orchestration import presentation as pr

    rows = list(getattr(runtime, "rows", []) or [])
    # The FULL presentation schema, not a three-key summary of it.
    #
    # A follow-up that reasons about this result needs to know which column is
    # the subject and which are measures, and that lives in `rank` and
    # `semantic`. Carrying only name/label/unit meant "does this trend make
    # sense?" could not tell a rating grade stored as an integer from a third
    # measure to correlate against the other two.
    try:
        columns = [dict(c) for c in pr.schema(runtime, build)]
    except Exception as e:  # noqa: BLE001 - a snapshot must not lose an answer
        logger.warning("Could not snapshot the presentation schema: %s", e)
        columns = [{"name": str(c.get("name")),
                    "label": str(c.get("label") or c.get("name")),
                    "unit": str(c.get("unit") or "")}
                   for c in (getattr(runtime, "columns", []) or [])]
    names = {str(c.get("name")) for c in columns}

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

    # The result itself, so a question ABOUT it does not have to re-run the
    # analysis that produced it. Capped: past `MAX_REUSE_ROWS` this is a
    # listing rather than a grouped result, and the reuse path reads those
    # back out of the stored run instead of pinning them to every turn.
    carried = [{k: v for k, v in row.items() if k in names}
               for row in rows[:cv.MAX_REUSE_ROWS]]

    return cv.ResultShape(
        columns=columns, row_count=len(rows), entity_key=key if ids else "",
        entity_ids=ids, entity_labels=labels,
        rows=carried, truncated=len(rows) > cv.MAX_REUSE_ROWS,
        fingerprint=_result_fingerprint(runtime),
        question=question,
        sample=[{k: v for k, v in row.items() if k in names}
                for row in rows[:cv.MAX_SNAPSHOT_ROWS]],
        run_id=run_id,
    )


__all__ = ["FAILED_PLAN", "FAILED_ROUTE", "FAILED_RUNTIME", "STAGES",
           "Answered", "answer", "get_provider", "is_configured", "mode",
           "remember"]
