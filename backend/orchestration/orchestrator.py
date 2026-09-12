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

import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any

from backend.llm import get_provider, is_configured, provider_status
from backend.metadata import answers as mda
from backend.metadata import questions as mdq
from backend.orchestration import analysis_planner as ap
from backend.orchestration import (
    absent_attributes,
    analyst,
    association,
    compound,
    dimensions,
    entities,
    followups,
    handlers,
    interpretation,
    investigation,
    metric_route,
    nth,
    scorecard_route,
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
from backend.product import routing as product_routing
from backend.regulatory import intent as regulatory_intent
from backend.semantics import ontology
from backend.whatif import language as whatif_language

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
    from backend.llm import public_health as ai_health
    from backend.llm import telemetry
    from backend.orchestration.vocabulary import get_vocabulary
    from backend.release import product_copy

    status = provider_status()
    observed = ai_health()
    vocab = get_vocabulary()
    live = observed["state"] == telemetry.CONNECTED
    configured = bool(observed["configured"])

    # §12. This payload is what the Ask screen renders its mode chip from, so
    # the vendor and the model come out of it here rather than being trusted
    # not to be displayed. `provider_status()` still knows both, and so does
    # /ai/status/audit; a normal user reads the STATE, which is the part that
    # tells them anything.
    return product_copy.withhold_identity({
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
    })


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
    #: The scorecard a validation turn was about. Carried so "what's the
    #: Gini?" two turns later does not have to name the model again.
    scorecard_model: str = ""
    #: The governed metric a metric-route turn reported. Carried so "which
    #: product is driving it?" stays on the metric instead of reaching the
    #: planner, which summed the days-past-due column and answered "1,260 days
    #: of days past due across 4 products".
    governed_metric: str = ""
    #: The breakdown that metric was reported by, where there was one.
    governed_dimension: str = ""
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

    # A question about the CATALOGUE is answered from the catalogue, and the
    # decision needs no model at all. This is checked before the router, for
    # two reasons. The first is correctness: "How many datasets are in the
    # IFRS 9 data domain? List them." was read as a count over the book and
    # answered "20,500 count of connected group size at Q2 2026" — the
    # analytical path did exactly what it is for, and should never have been
    # asked. The second is cost: a catalogue question has an answer that is
    # already known, so paying a model to rediscover it is slower and less
    # reliable than reading it.
    # Read from the user's OWN words. The spelling normaliser is tuned for
    # the bank's vocabulary — sector names, concept names — and turned "to
    # assess a borrower's credit risk" into "to assets a borrowers credit
    # risk", which is harmless for matching a concept and wrong to quote back
    # in a sentence that repeats what was asked.
    # A question about CREDITPROBE ITSELF is answered from the product
    # knowledge registry. Checked before the catalogue for the same reasons the
    # catalogue is checked before the router, and for one more: "What is
    # CreditProbe AI?" reached the analytical planner and came back as
    # "CreditProbe has no governed data about CreditProbe AI" — a true
    # statement about the borrower book and the worst possible answer to the
    # question. The product is not a dataset, and a question about it must
    # never be answered by looking for one.
    product_intent = product_routing.read(original)
    if product_intent.is_product:
        return _from_product(original, question, product_intent, fixed,
                             started)

    # A HYPOTHETICAL is not a question about the book as it is, and the
    # analytical planner has no way to express one: "what happens if every BBB
    # borrower is downgraded two notches" has no rows to select, because the
    # rows it is about do not exist yet. So it is routed to the scenario
    # engine, which computes the position the question describes, borrower by
    # borrower, against the same governed staging and measurement rules that
    # produced the reported book.
    scenario_reading = whatif_language.read(original)
    if scenario_reading.scenario is not None:
        return _from_whatif(original, question, scenario_reading, fixed,
                            started, state=state)
    if scenario_reading.opens_whatif:
        # A What-If question that does not yet carry a magnitude — "stress the
        # real estate portfolio", "use the severe scenario". It used to be
        # caught by a planner intent that ran the legacy engine on a different
        # book. That intent is gone, so the question is OPENED here rather than
        # falling through to a planner that would now leave it unmatched.
        return _opens_whatif(original, question, scenario_reading, fixed,
                             started)

    # "What datasets do you have?", "Tell me about Corporate IFRS 9",
    # "Show Q1 2025" — the dataset-aware half of the catalogue, answered from
    # the LIVE catalogue and the published rows. A list that was true when it
    # was written is wrong the first time a steward publishes a period, and
    # being confidently wrong about your own contents is worse than having
    # none.
    #
    # Above `mdq.read` because these three shapes need more than the metadata
    # service returns — a frequency, a semantic profile, and the actual rows —
    # and above the investigation gate because "tell me about" is in both
    # vocabularies and only one of them is right here. "Tell me about
    # Corporate IFRS 9" ran four governed probes over a population called
    # "Corporate" and reported that its ratings had been downgraded: a real
    # answer to a question about a DATASET. Everything else about the
    # catalogue still falls through to the one metadata service below.
    about_data = _about_the_data(original, memory=memory)
    if about_data is not None:
        return _from_catalogue(original, question, about_data,
                               fixed, started, state=state, memory=memory,
                               result=about_data.result,
                               dataset=about_data.dataset)

    catalogue_question = mdq.read(original)
    if catalogue_question is not None:
        return _from_catalogue(original, question, catalogue_question,
                               fixed, started, state=state, memory=memory)

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

    # "That one." "No, the other one." A pointer with no position.
    #
    # Both were answered by re-running the analysis already on the table and
    # presenting its figures again under a different question — nine turns of
    # one session came back with the same sentence. Which row the reader means
    # is a question only they can answer, and asking it is the answer.
    pointing = nth.points_without_saying_which(question)
    if pointing:
        rows = ru.cached_result(state)
        listed = _rows_to_choose_from(rows)
        if listed:
            answered.clarification = (
                f"Which one? \u201c{pointing}\u201d points at a row of the "
                f"previous answer and does not say which. It returned "
                f"{listed}. Name it, or say \u201cthe second one\u201d.")
            return finish(answered)

    # "Show it as a graph." The same rows, drawn differently.
    #
    # This never reached the runtime in the sense of producing different
    # figures — the row counts matched, which is what the test asserted — but
    # it re-planned and re-executed to get them. Paying the full analytical
    # cost of a question to change a chart type is not merely wasteful: two
    # executions are two results, and "show IT as a graph" promises the one
    # already on the screen.
    # "Back." One word, and it planned an analysis, executed it, and returned
    # a row count DIFFERENT from the answer it was supposed to be returning
    # to — then, on a thread carrying ten customers, widened to the whole
    # portfolio and reported a figure the reader had not asked for. A reader
    # who types one word to step back and watches the numbers change has been
    # given a reason to distrust both answers. Nothing is recomputed: the rows
    # already on the screen are shown again.
    if _steps_back(question):
        stepped = _show_previous_again(answered, question, state)
        if stepped is not None:
            return finish(stepped)

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

    # An identity detail no rewording produces. "Tell me the borrower's
    # employer name for the highest-ECL facility" bound ECL to a measure, bound
    # "employer name" to nothing, dropped the unbound half in silence, and was
    # then refused by the GRAIN contract — "the governed data behind it can only
    # be reported as one row for the whole book", which is about the wrong thing
    # and is not true of a book keyed one row per facility. Checked here, above
    # the planner, so the refusal names the field rather than the plan.
    #
    # Below the coverage check because a question about something the universe
    # holds nothing about at all is the broader refusal, and above the planner
    # because every path below this one would drop the phrase rather than
    # answer it.
    unheld = absent_attributes.read(question)
    if unheld is not None:
        answered.unsupported = unheld.sentence()
        answered.coverage = unheld.to_dict()
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

    # A governed RATE, SHARE or discrimination statistic asked for by name.
    #
    # "What is the 30+ DPD rate?" was answered "425.0 days of days past due" —
    # the planner summed the nearest column, because a rate is not a column and
    # the planner composes an analysis out of columns. The numerator, the
    # denominator and the scope are published in the Metric Catalogue, so the
    # answer comes from there and agrees with the lens tile by construction.
    #
    # Checked above the planner, and narrow by design: a plain sum, a cohort, a
    # threshold, a movement and a two-period comparison all fall straight
    # through to the composer, which does them better. See
    # backend/orchestration/metric_route.py.
    #
    # And never on a turn that MODIFIES the analysis already on the table. A
    # narrowing sentence carries the whole of the previous plan with it, and
    # "Only salary transfer customers." — asked of ECL by IFRS 9 stage for
    # personal finance — matched the published Salary-Transfer Share and was
    # answered with it: one number, 77.35%, in place of the measure, the
    # breakdown and the scope the reader was working in. A modification is a
    # change to an analysis, never a request for a different figure.
    modifying = continuation.action in (
        cv.MODIFICATIONS | {cv.ENRICH_PREVIOUS, cv.ASK_ABOUT_RESULT,
                            cv.ASSESS_PREVIOUS_RESULT, cv.NARROW_SCOPE,
                            cv.WIDEN_SCOPE})

    # A SCORECARD VALIDATION question, asked where the reader is standing.
    #
    # A Head of Retail Risk does not change modules to ask whether a scorecard
    # is holding up, and the Cockpit answered "how is our personal-finance
    # application scorecard performing?" with the average origination score of
    # the book. Then "what's the Gini?" was refused as an unknown borrower,
    # and the eleven turns after it fell into the credit-concern ranking and
    # returned the same twenty-five customers each time.
    #
    # The validation runner already computes all of it. This route only
    # decides that the sentence belongs to it, and which of the eight
    # scorecards it is about. See backend/orchestration/scorecard_route.py.
    validation = scorecard_route.read(
        question, carried_model=(state.scorecard_model if state else ""))
    if validation is not None:
        validated = _validation_answer(answered, validation, question)
        if validated is not None:
            return finish(validated)
    governed_metric = None if modifying else metric_route.read(
        question, carried_metric=(state.governed_metric if state else ""),
        carried_dimension=((state.governed_dimension if state else "")
                           or (state.dimensions[0] if state and state.dimensions
                               else "")))
    if governed_metric is not None:
        try:
            computed = metric_route.answer(governed_metric, question)
        except Exception:  # noqa: BLE001 - fall through, never substitute
            logger.exception("The metric route failed for %r", question)
            computed = None
        if computed is not None:
            answered.result = computed
            answered.governed_metric = governed_metric.metric_id
            answered.governed_dimension = governed_metric.dimension
            answered.reading = replace(
                reading,
                objective=f"The governed metric {governed_metric.metric.name}")
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
    # A follow-up that drills into a step of the analysis already on screen is
    # answered by that analysis, over the same population, rather than by a
    # fresh composition that shares a subject with it and nothing else.
    drilled = _drill_into_the_previous_analysis(question, state)
    if drilled is not None:
        answered.certified, answered.certified_params = drilled
        return finish(answered)

    if use_certified and not continuation.carries_context:
        found = cert.match(question, reading)
        if found is not None:
            answered.certified = found
            answered.certified_params = cert.parameters(
                found, reading, period=period, question=question,
                periods=list(getattr(context, "periods", [])))
            return finish(answered)

    return finish(_analyse(answered, question, reading, context, state,
                           continuation, period, extra_filters,
                           thread_datasets=list(memory.datasets)))


def _drill_into_the_previous_analysis(
        question: str, state: cv.ConversationState | None
        ) -> tuple[cert.Match, dict[str, Any]] | None:
    """A follow-up that drills into a step of the answer already on screen.

    Only the ECL bridge supports this today, and only immediately after it has
    run. The drill re-runs the SAME certified analysis with the same period and
    filters and publishes the borrowers behind one of its steps — figures out
    of the calculation the reader is looking at, not a new ranking beside it.
    """
    if state is None or not state.certified_analysis:
        return None
    from backend.orchestration import bridge_drill

    found = bridge_drill.read(question, state.certified_analysis)
    if found is None:
        return None

    params = dict(state.certified_params)
    params.update(found.parameters())

    match = cert.Match(
        analysis_id=state.certified_analysis,
        name="ECL Decomposition",
        overlap=1.0,
        matched="the step of the decomposition already on screen",
        when_to_use=found.because,
        period_requirement="point_in_time",
        params=params)
    logger.info("Follow-up %r drills into %s of %s.", question[:60],
                params[bridge_drill.PARAMETER], state.certified_analysis)
    return match, params


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


@dataclass
class _DataAnswer:
    """A catalogue answer that is ready to return, and what it was about."""

    result: Any
    dataset: str = ""
    why: str = "the question asks about the governed data itself"
    confidence: float = 1.0


def _about_the_data(question: str, *, memory: Any = None) -> Any:
    """The catalogue, one dataset, or that dataset at another period.

    Returns None for everything else, which is nearly every question. The
    three shapes are a thread: the second inherits nothing and the third
    inherits everything, because a reader who has just been shown a dataset
    and then types a period label means that dataset at that period.
    """
    from backend.orchestration import catalogue_answers as cat

    reading = cap.Reading(intent=cap.Capability.DATA_DISCOVERY,
                          objective="what the governed catalogue holds",
                          operation="list", source="catalogue")
    try:
        if cat.wants_catalogue(question):
            return _DataAnswer(
                result=cat.catalogue_result(question, reading))

        wanted = cat.resolve(question)
        period = cat.period_in(question)
        limit = cat.rows_wanted(question)

        if wanted is not None and (cat.wants_dataset(question)
                                   or cat.names_only_a_dataset(question)):
            return _DataAnswer(
                result=cat.overview_result(question, reading, wanted,
                                           period=period, limit=limit),
                dataset=wanted.name,
                why=f"the question asks about the {wanted.business_name} dataset")

        # A name the catalogue does not hold.
        #
        # Falling through answered "show me the Facility Master dataset" with
        # "there are 77 governed datasets", which answers a question nobody
        # asked and hides the fact that the name was not recognised. Checked
        # before the carried dataset, because naming a dataset — even one that
        # is not there — is not a follow-up about the last one.
        unknown = cat.named_but_unknown(question)
        if unknown and _carried_dataset(memory) is None:
            return _DataAnswer(
                result=cat.unknown_dataset_result(question, reading, unknown),
                why=f"the question names a dataset called {unknown}")

        # "Show Q1 2025." / "Show me 50 rows." — the dataset already on the
        # table. Only when there IS one: a bare period with no dataset behind
        # it is a period for whatever question comes next, not a subject.
        carried = _carried_dataset(memory)
        if carried is None:
            return None
        asked_period = cat.bare_period(question)
        if asked_period:
            return _DataAnswer(
                result=cat.overview_result(question, reading, carried,
                                           period=asked_period, limit=limit),
                dataset=carried.name,
                why=(f"a period on its own, which continues the "
                     f"{carried.business_name} dataset already on the table"))
        if limit != cat.PREVIEW_ROWS and cat.asks_for_rows(question):
            return _DataAnswer(
                result=cat.overview_result(
                    question, reading, carried,
                    period=period
                    or str(getattr(memory, "current_period", "") or ""),
                    limit=limit),
                dataset=carried.name,
                why=f"more rows of the {carried.business_name} dataset")
    except Exception as e:  # noqa: BLE001 - a catalogue answer is not worth a 500
        logger.warning("Could not answer %r from the catalogue: %s",
                       question, e)
    return None


def _carried_dataset(memory: Any) -> Any:
    """The dataset the thread is already looking at, if any."""
    from backend.metadata import service as svc_meta

    for name in list(getattr(memory, "datasets", None) or []):
        found = svc_meta.dataset(str(name))
        if found is not None:
            return found
    return None


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
            from backend.retail import profile

            who = "customer" if profile.is_retail() else "borrower"
            return (f"CreditProbe could not find {name} in the published data. "
                    "It only reads datasets that have been published and marked "
                    f"authoritative, so a {who} it has never been given "
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


#: Metadata questions whose subject, when unstated, is whatever the
#: conversation is already about.
_INHERITS_A_SUBJECT = frozenset({
    "PERIODS", "ROW_COUNT", "FIELD_LIST", "DATASET_DETAIL", "RELATIONSHIP",
})


def _catalogue_subject(request: Any, state: cv.ConversationState,
                       memory: Any) -> Any:
    """The subject a bare catalogue question inherits from the thread.

    "What IFRS 9 data do you have?" and then "What is the latest period?" is
    one conversation about one dataset. The second sentence names none, and
    answering it about the whole catalogue is the same forgetting §6 is
    about, arriving on the metadata path instead of the analytical one.
    """
    from backend.metadata import service as svc

    # Only where a missing subject MEANS "the one we are discussing". "What
    # datasets do you have?" and "what data is installed?" are about the whole
    # catalogue by construction, and giving them the thread's dataset turned a
    # question about 46 datasets into a question about one.
    if request.kind not in _INHERITS_A_SUBJECT:
        return request

    # A subject that names no governed dataset or domain is not a subject.
    # "What is the latest period?" resolves `period` — the name of the period
    # COLUMN — which is true and useless, and kept the question from
    # inheriting the dataset the conversation was about.
    named = request.subject
    if named and (svc.dataset(named) is not None or svc.domain(named) is not None):
        return request

    # The working memory is the right place to look: it records what the last
    # TURN was about, including the many turns that are not analyses, which is
    # exactly the case here — "What IFRS 9 data do you have?" settles a
    # dataset without running anything, so the analytical state stays empty.
    carried: list[str] = []
    if str(getattr(memory, "current_subject_type", "")).upper() == "DATASET":
        carried.append(str(getattr(memory, "current_subject", "")))
    carried.extend(str(n) for n in (getattr(memory, "datasets", ()) or ()))
    carried.extend(str(n) for n in (getattr(state, "datasets", ()) or ()))
    for name in carried:
        if name and svc.dataset(name) is not None:
            return replace(request, subject=name,
                           why=(f"{request.why} It is about {name}, which the "
                                f"conversation is already discussing."))
    for name in list(getattr(memory, "domains", ()) or ()) + list(
            getattr(state, "domains", ()) or ()):
        if name and svc.domain(str(name)) is not None:
            return replace(request, subject=str(name))
    return request


def _from_catalogue(original: str, question: str, request: Any,
                    fixed: Any, started: float, *,
                    state: cv.ConversationState | None = None,
                    memory: Any = None,
                    result: Any = None,
                    dataset: str = "") -> Answered:
    """Answer a question about the data from the one metadata service. §12-§14.

    Produces the same `Answered` every other route produces, so the API, the
    Trace and the answer panel need to know nothing about this path. The
    reading is recorded honestly: it was made deterministically, from the
    question's own nouns, with no model consulted.
    """
    if state is not None and result is None:
        request = _catalogue_subject(request, state, memory)
    reading = cap.Reading(
        intent=cap.Capability.DATA_DISCOVERY,
        objective=request.why,
        conversation_action=cv.NEW_REQUEST,
        operation="list",
        confidence=request.confidence,
        reasoning=request.why,
        source="catalogue",
    )
    answered = Answered(
        question=original, reading=reading,
        # A question about the catalogue is its own request — it is not a
        # modification of the analysis on screen. Recording it as one keeps
        # the Trace honest AND keeps the analytical population alive: the
        # state a metadata turn does not touch is the state the next
        # analytical turn inherits.
        continuation=cv.Continuation(
            action=cv.NEW_REQUEST,
            because="the question asks about the catalogue, not the book"),
        decision=rt.decide(question, deterministic=True),
        read_as=fixed.text if fixed.changes else "",
        corrections=list(fixed.changes))
    # A metadata question that names a dataset leaves that dataset in the
    # thread. "What periods of ifrs9_staging do you have?" followed by "Show me
    # Q3 2026" is one conversation, and a reader who has just been told which
    # periods exist should not have to name the dataset again to open one.
    if not dataset and result is None:
        named = str(getattr(request, "subject", "") or "")
        from backend.metadata import service as svc_meta

        if named and svc_meta.dataset(named) is not None:
            dataset = named
    if dataset:
        # So "Show Q1 2025" on the next turn knows which dataset it means.
        # Carried on the reading because that is where the working memory
        # reads a turn's datasets from. `Reading` is frozen, so it is rebuilt
        # rather than mutated.
        reading = replace(reading, datasets=(dataset,))
        # `Answered` was built with the reading as it was, so the rebuilt one
        # has to be put back or the thread learns nothing.
        answered.reading = reading
    if result is not None:
        answered.result = result
        answered.duration_ms = int((time.perf_counter() - started) * 1000)
        return answered
    try:
        payload = mda.respond(request)
    except Exception as e:  # noqa: BLE001 - a stated failure, not a substitution
        logger.exception("The metadata service failed for %r", question)
        answered.failure_kind = FAILED_ROUTE
        answered.failure = (
            f"CreditProbe could not read its own catalogue to answer that: {e}")
        answered.duration_ms = int((time.perf_counter() - started) * 1000)
        return answered

    answered.result = handlers.HandlerResult(
        answer=payload["answer"], rows=payload["rows"],
        columns=payload["columns"], values=payload["values"],
        detail=dict(payload["detail"],
                    metadata_request=payload["metadata_request"],
                    visualization=payload["visualization"]),
        follow_ups=payload["follow_ups"], warnings=payload["warnings"],
        # Never a chart. A list of datasets is not a distribution and a domain
        # is not a time series. §11 and §13.
        chart={},
        execution=payload["execution"],
        execution_label=payload["execution_label"])
    answered.duration_ms = int((time.perf_counter() - started) * 1000)
    return answered


def _from_product(original: str, question: str, intent: Any, fixed: Any,
                  started: float) -> Answered:
    """Answer a question about CreditProbe from the product knowledge registry.

    No model is consulted and no dataset is read. The answer is composed from
    reviewed narrative and live counts, so it is the same every time it is
    asked and it cannot describe a capability the installation does not have.
    """
    from backend.product import answers as product_answers
    from backend.product import routing as routing_module

    reading = cap.Reading(
        intent=cap.Capability.DATA_DISCOVERY,
        objective=intent.why,
        conversation_action=cv.NEW_REQUEST,
        operation="describe",
        confidence=1.0,
        reasoning=intent.why,
        source="product_knowledge",
    )
    answered = Answered(
        question=original, reading=reading,
        # A product question does not touch the analytical population. The
        # thread's sector and period survive it, so an officer can ask what
        # Early Warning is in the middle of an investigation and carry on.
        continuation=cv.Continuation(
            action=cv.NEW_REQUEST,
            because="the question asks about CreditProbe, not about the book"),
        decision=rt.decide(question, deterministic=True),
        read_as=fixed.text if fixed.changes else "",
        corrections=list(fixed.changes))

    composed = routing_module.answer(original)
    if composed is None:  # pragma: no cover - `is_product` guarantees one
        composed = product_answers.get_creditprobe_overview()
    payload = composed.to_dict()

    # The answer IS the Markdown. The structure has to travel in the string
    # the answer surface renders, not beside it: the first version kept the
    # sections in this payload and handed the surface a flattened wall of
    # prose, which is exactly what the reader saw.
    answered.result = handlers.HandlerResult(
        answer=payload["answer"],
        rows=[], columns=[], values={},
        detail={"product_knowledge": payload,
                "rich_text": "markdown",
                "visualization": payload["visualization"]},
        follow_ups=list(payload["follow_ups"]),
        warnings=[],
        # Never a chart. §19: a product or methodology explanation has no
        # quantitative shape, and a chart of feature counts is decoration.
        chart={},
        execution="product_knowledge",
        execution_label="Answered from the CreditProbe product knowledge "
                        "registry")
    answered.duration_ms = int((time.perf_counter() - started) * 1000)
    return answered


def _opens_whatif(original: str, question: str, reading: Any, fixed: Any,
                  started: float) -> Answered:
    """Open a What-If for a question that means one but has not sized it yet.

    "Stress the real estate portfolio" states an intention, not a magnitude.
    The answer says what was understood and what is missing, and hands back the
    ways to say it — it does NOT guess a size. Guessing would put a number in
    front of somebody that they never asked for and cannot argue with.

    This path exists because the planner intent that used to catch these
    questions ran the legacy engine on a different book, and has been retired.
    Retiring it without absorbing the vocabulary would have turned every
    magnitude-free stress question into an unmatched one.
    """
    from backend.whatif import domain as whatif_domain

    from backend.retail import profile as retail_profile

    retail = retail_profile.is_retail()

    severity = getattr(reading, "severity", "")
    population = (reading.scenario.population.describe()
                  if getattr(reading, "scenario", None)
                  else ("the whole retail book" if retail
                        else "the whole corporate book"))
    try:
        period = (_retail_latest_month() if retail
                  else whatif_domain.latest_period())
    except Exception:  # noqa: BLE001 - an unbuilt lake is not this answer's job
        period = ""

    lines = ["That is a What-If question. Before I can put a number on it, I "
             "need to know how big the movement is."]
    if severity:
        lines.append(
            f"You named a '{severity}' severity. This engine applies the shock "
            "a scenario states rather than a named preset, so tell me what "
            f"'{severity}' should mean here.")
    # The examples have to be things THIS engine can run. On a retail
    # installation the corporate list offered "downgrade them two notches" and
    # "unemployment up one percentage point" — a rating scale that was retired
    # and a macro-variable shock this engine does not implement — as clickable
    # suggestions in the Cockpit. Offering a reader an operation that will then
    # be refused is worse than offering nothing.
    if retail:
        lines.append(
            "For example: **increase personal-finance PD by 20% relative**, "
            "**increase LGD by 10%**, **reduce mortgage collateral values by "
            "10%**, or **shift the scenario weights toward downturn**.")
    else:
        lines.append(
            "For example: **downgrade them two notches**, **increase PD by "
            "20%**, **increase LGD by five percentage points**, or "
            "**unemployment up one percentage point**.")
    if period:
        lines.append(
            f"I will run it on the retail book at {period} unless you name "
            "another month, and every result names the methodology version "
            "that produced it."
            if retail else
            f"I will run it on Corporate IFRS 9 at {period} unless you name "
            "another quarter, and I will ask which ECL methodology to use "
            "before calculating.")

    answered = Answered(
        question=original,
        reading=cap.Reading(
            intent=cap.Capability.ANALYTICAL_QUERY
            if hasattr(cap.Capability, "ANALYTICAL_QUERY")
            else cap.Capability.DATA_DISCOVERY,
            objective="What-If: the movement has not been sized yet",
            conversation_action=cv.NEW_REQUEST,
            operation="scenario",
            confidence=1.0,
            reasoning="The question opens a What-If but carries no magnitude, "
                      "so it was answered with the question it still needs.",
            source="whatif_language"),
        continuation=cv.Continuation(
            action=cv.NEW_REQUEST,
            because="the question opens a What-If but does not size it"),
        decision=rt.decide(question, deterministic=True),
        read_as=fixed.text if fixed.changes else "",
        corrections=list(fixed.changes))
    answered.result = handlers.HandlerResult(
        answer="\n\n".join(lines),
        rows=[], columns=[], values={},
        detail={"opens_whatif": True, "severity": severity,
                "population": population, "period": period,
                "needs": "magnitude", "rich_text": "markdown"},
        follow_ups=(list(retail_profile.SCENARIO_STARTERS[:3]) if retail
                    else ["Downgrade them one notch.",
                          "Increase PD by 20%.",
                          "Increase LGD by five percentage points."]),
        warnings=[], chart={},
        execution="whatif_opening",
        execution_label="What-If Analysis")
    answered.duration_ms = int((time.perf_counter() - started) * 1000)
    return answered


def _published_measures() -> str:
    """The measures this installation actually publishes, named in a refusal.

    The sentence listed "exposure, impairment, ratings, delinquency,
    covenants". Two of those are corporate objects with nothing behind them
    here, and a refusal that names them tells a Head of Retail Risk the
    product was written for somebody else's book — in the answer to the most
    likely opening question in a demonstration.
    """
    from backend.retail import profile

    if not profile.is_retail():
        return "exposure, impairment, ratings, delinquency, covenants"
    return ("exposure, expected credit loss, IFRS 9 staging, delinquency, "
            "affordability and both scorecards")


def _retail_latest_month() -> str:
    """The newest published month of the retail book, or nothing.

    Read from the shipped manifest rather than the corporate lake, which a
    retail installation does not have.
    """
    import json

    from backend.config import settings

    path = settings.metadata_dir / "retail_dataset_manifest.json"
    if not path.exists():
        return ""
    manifest = json.loads(path.read_text())
    return str(manifest.get("last_snapshot", ""))[:7]


def _from_whatif(original: str, question: str, reading: Any, fixed: Any,
                 started: float, *, state: Any = None) -> Answered:
    """Answer a hypothetical by computing it, borrower by borrower.

    No model is consulted. The scenario is a typed object, the shocks are
    applied through the governed rating masterscale and the versioned
    sensitivity matrix, the SICR triggers are re-read against the stressed PD,
    and the ECL is re-measured on each borrower's stressed Stage's own basis —
    which is why the base column ties to the reported book and the stressed
    column can be argued with line by line.
    """
    from backend.whatif import answers as whatif_answers
    from backend.whatif import engine as whatif_engine
    from backend.whatif import trace as whatif_trace

    scenario = reading.scenario
    # A follow-up inside a scenario thread inherits the population the thread
    # settled, so "downgrade these borrowers" means the ones on the screen.
    carried = _carried_borrowers(state)
    if carried and not scenario.population.borrower_ids \
            and re.search(r"\bthese\b|\bthose\b|\bthem\b", original, re.I):
        from backend.whatif import scenarios as whatif_scenarios
        scenario = whatif_scenarios.Scenario(
            key=scenario.key, name=scenario.name, shocks=scenario.shocks,
            population=whatif_scenarios.Population(borrower_ids=tuple(carried)),
            assumptions=scenario.assumptions, severity=scenario.severity,
            rationale=scenario.rationale, period=scenario.period)

    capability_reading = cap.Reading(
        intent=cap.Capability.ANALYTICAL_QUERY
        if hasattr(cap.Capability, "ANALYTICAL_QUERY") else cap.Capability.DATA_DISCOVERY,
        objective=f"Scenario: {scenario.name}",
        conversation_action=cv.NEW_REQUEST,
        operation="scenario",
        confidence=1.0,
        reasoning="The question describes a hypothetical, so it was computed "
                  "rather than looked up.",
        source="whatif_engine",
    )
    answered = Answered(
        question=original, reading=capability_reading,
        continuation=cv.Continuation(
            action=cv.NEW_REQUEST,
            because="the question proposes a scenario over the book"),
        decision=rt.decide(question, deterministic=True),
        read_as=fixed.text if fixed.changes else "",
        corrections=list(fixed.changes))

    try:
        result = whatif_engine.run(scenario)
    except ValueError as exc:
        answered.failure_kind = FAILED_ROUTE
        answered.failure = (
            f"CreditProbe could not run that scenario. {exc}")
        answered.duration_ms = int((time.perf_counter() - started) * 1000)
        return answered

    composed = whatif_answers.compose_answer(result, reading)
    payload = composed.to_dict()
    table = whatif_answers.borrower_table(result, limit=200)
    rows = [dict(zip(table["columns"], row, strict=False))
            for row in table["rows"]]

    answered.result = handlers.HandlerResult(
        answer=payload["answer"],
        rows=rows,
        columns=[{"name": name, "label": name} for name in table["columns"]],
        values={
            "baseline_ecl": result.summary["baseline_ecl"],
            "stressed_ecl": result.summary["stressed_ecl"],
            "incremental_ecl": result.summary["incremental_ecl"],
            "stage_2_migrations": result.summary["stage_2_migrations"],
        },
        detail={"whatif": whatif_trace.detail(result),
                "product_knowledge": payload,
                "rich_text": "markdown"},
        graph=whatif_trace.build(result, original),
        follow_ups=list(payload["follow_ups"]),
        warnings=list(result.warnings),
        # Section 7 of the global contract: a scenario answer is a table and a
        # summary. A chart is offered only where the question asks for one.
        chart={},
        execution="whatif_scenario",
        execution_label="Computed by the CreditProbe scenario engine")
    answered.duration_ms = int((time.perf_counter() - started) * 1000)
    return answered


def _carried_borrowers(state: Any) -> list[str]:
    """Borrower identifiers the thread has already settled on."""
    if state is None:
        return []
    for attribute in ("borrower_ids", "entities", "population_ids"):
        found = getattr(state, attribute, None)
        if found:
            return [str(x) for x in found][:500]
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
             extra_filters: dict[str, Any] | None,
             thread_datasets: list[str] | None = None) -> Answered:
    """Compose, validate, run and interpret. Or say why it could not."""
    from backend.runtime.executor import ExecutionClass, execute

    reading = _with_overrides(reading, period, extra_filters)
    answered.reading = reading

    # A governed method, routed BEFORE the ambiguity gate. "Decompose the change
    # in ECL into exposure, stage migration, PD, LGD and mix" names exposure as
    # a DRIVER, not as the measure to compute, and the gate read it as the
    # measure — so the question that most needed this method was answered with a
    # menu asking which exposure figure to use.
    # ...unless the question asks for a DIMENSION. "Which sectors deteriorated
    # most this quarter?" names sectors as the thing it wants one row of, and
    # the bridge is a portfolio attribution: it answered with one opening
    # balance, one closing balance and five drivers, under a question about
    # seventeen sectors. The grain the question asks for decides what answers
    # it, and only a HEAD dimension counts here — "decompose the change in ECL
    # by sector" still belongs to the bridge.
    if dcp.wants(question) and not dimensions.read(question).is_head:
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
                        state=state, continuation=continuation,
                        thread_datasets=thread_datasets)
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
            # §8: no dead ends. A refusal that names the gap and stops is
            # still one — the reader is told what cannot be done and left with
            # nothing to do about it, which is the moment somebody closes the
            # tab. `Coverage.next_move` names what the catalogue does carry,
            # in prose rather than as a menu, and both branches carry it so
            # the two refusals cannot say different things.
            answered.unsupported = held.sentence() if held.out_of_scope else (
                "CreditProbe has no governed data about what that asks for. It "
                f"answers from the figures a steward has published — "
                f"{_published_measures()} — and it holds nothing that measures "
                "this. It has NOT answered a different question instead. "
                + held.next_move())
            answered.coverage = held.to_dict()
            return answered
        answered.clarification = e.clarification
        return answered
    except Exception as e:  # noqa: BLE001
        # Execution-guided repair. The first plan did not compose; the model is
        # asked again with the VALIDATION ERRORS — never with an expected
        # answer, which would be teaching to the test — and at most once.
        # With the traceback. An unexpected exception here is a DEFECT, and
        # the log line that recorded only its message — "list index out of
        # range" — was the only trace of it anywhere: the user saw a refusal,
        # the log saw a sentence, and nobody could see where it came from.
        logger.exception("Composing failed for %r (%s); escalating to repair.",
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

    # The SAME analysis, planned a second time from a sentence that changed
    # nothing.
    #
    # One misread opening question in a messy-language session was followed by
    # nine turns — a trend, a three-way comparison, two ambiguity repairs —
    # and every one of them returned the first answer's sentence verbatim,
    # because each resolved to a plan byte-identical to the one already on the
    # table. A reader who asks nine different questions and is given one
    # answer nine times has been told nothing, and has no way to know it.
    #
    # Compared on the PLAN rather than on the result, so this costs no
    # execution, and only where the turn pointed back: a reader who genuinely
    # re-asks the same question from a standing start is entitled to the same
    # answer.
    repeated = _repeats_the_previous_plan(build, state, continuation, question)
    if repeated:
        answered.clarification = repeated
        return answered

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
            question, reading,
            context=_decomposition_scope(reading, context, question),
            period=period, user_id=getattr(context, "user_id", None))
    except Exception as e:  # noqa: BLE001 - a method must not become a 500
        logger.exception("The ECL decomposition failed: %s", e)
        answered.failure = (
            "CreditProbe could not compute the ECL decomposition. Nothing "
            "partial has been reported as an answer.")
        answered.failure_kind = "EXECUTION"
    return answered


def _decomposition_scope(reading: cap.Reading, context: Any,
                         question: str = "") -> Any:
    """The population the decomposition should read, not the whole book.

    The failure this prevents
    -------------------------
        "Give me the July to August ECL decomposition for personal finance"

    was answered with the movement of the WHOLE retail book — SAR 1,882,500
    against personal finance's SAR 981,593 — because the handler was handed the
    governed CONTEXT, which carries the catalogue rather than the population,
    and the filters the question stated never reached the read.
    """
    from backend.data_access.context import AnalysisContext
    from backend.orchestration.vocabulary import get_vocabulary

    vocabulary = get_vocabulary()
    governed = set(vocabulary.dimensions)
    filters = {str(f.get("field")): f.get("value")
               for f in (reading.filters or [])
               if str(f.get("field")) in governed and f.get("value")}
    if not filters:
        # The reading carries no filter, so read the population out of the
        # sentence against the governed values — the same resolver the planner
        # uses, so "personal finance" means the same thing on both paths.
        found = vocabulary.resolve_dimension_value(
            question or reading.objective or "")
        if found:
            filters = {found[0]: found[1]}
    if not filters:
        return context
    return AnalysisContext(period="", filters=filters,
                           user_id=getattr(context, "user_id", None))


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



_STEPS_BACK = re.compile(
    r"^\s*(?:go\s+)?back\s*[.!]?\s*$"
    r"|^\s*(?:take me\s+)?back to (?:that|the previous|the last)\b"
    r"|^\s*previous (?:answer|result|one)\s*[.!?]?\s*$",
    re.IGNORECASE)


def _steps_back(question: str) -> bool:
    """Whether the sentence asks to return to the previous answer."""
    return bool(_STEPS_BACK.match(" ".join(str(question or "").split())))


def _show_previous_again(answered: Answered, question: str,
                         state: cv.ConversationState) -> Answered | None:
    """The previous result, unchanged and unrecomputed.

    Returns None where there is nothing to go back to, and the ordinary path
    then reads the sentence — which, from a standing start, is right.
    """
    from backend.orchestration import handlers

    cached = ru.cached_result(state)
    if cached is None or not cached.usable:
        return None
    provenance = ru.provenance_of(cached)
    answered.cached = cached
    answered.provenance = provenance
    answered.from_memory = True
    answered.decision = rt.decide(question, deterministic=True)
    said = cached.question or "the previous question"
    answered.result = handlers.HandlerResult(
        answer=(f"The previous answer, unchanged: {said}. "
                "Nothing was recomputed, so these are the same rows."),
        rows=[dict(r) for r in cached.rows],
        columns=[dict(c) for c in cached.columns],
        values=dict(getattr(cached, "values", {}) or {}),
        detail={"reuse": provenance.to_dict(), "previous": cached.to_dict(),
                "of": said},
        follow_ups=[],
        warnings=[],
    )
    return answered


def _validation_answer(answered: Answered, routed: Any,
                       question: str) -> Answered | None:
    """The validation runner's answer, rendered as a Cockpit answer.

    Computes nothing. Every figure here was produced by the same runner the
    Scorecard Validation module runs, over the same governed population, with
    the same limits and the same evidence rules — so the two surfaces cannot
    disagree, because there is only one of them.

    Returns None where the runner could not answer, and the ordinary path then
    reads the sentence. A route that substituted its own answer for a runner
    that declined would be the substitution this whole module exists to stop.
    """
    from backend.orchestration import handlers

    if routed.ask:
        answered.clarification = routed.ask
        answered.reading = replace(
            answered.reading,
            objective="Which scorecard the validation question is about")
        return answered

    try:
        body = scorecard_route.ask(question, routed.model_id)
    except Exception:  # noqa: BLE001 - fall through, never substitute
        logger.exception("The validation runner failed for %r", question)
        return None

    refusal = body.get("refusal") or {}
    clarify = body.get("clarify") or {}
    if refusal:
        answered.unsupported = str(refusal.get("why") or refusal.get("what") or "")
        return answered if answered.unsupported else None
    if clarify:
        asked = clarify.get("question") if isinstance(clarify, dict) else clarify
        if asked:
            answered.clarification = str(asked)
            return answered
        return None
    if not body.get("answered"):
        # The reader has no single tool for "how is it performing?" — that is
        # not one statistic, it is all of them, assessed. The findings engine
        # answers exactly that and was unreachable from the Cockpit, so the
        # question fell through to the planner and came back with the average
        # origination score of the book.
        if scorecard_route.asks_about_the_whole_scorecard(question):
            assessed = _validation_findings(answered, routed, question)
            if assessed is not None:
                return assessed
        return None

    # "Which risk band is most miscalibrated?" asks for a BAND. The category
    # run carries every band in its calibration chart, and answering with the
    # five category tests leaves the reader to find the band themselves in a
    # table that does not have one.
    banded = _worst_band(body, question, routed.model_id)
    if banded is not None:
        rows, columns, headline, caveats = banded
    else:
        rows, columns, headline, caveats = _validation_rows(body, routed.model_id)
    if not headline:
        return None
    answered.result = handlers.HandlerResult(
        answer=headline,
        rows=rows, columns=columns, values={},
        detail={"scorecard": {"model_id": routed.model_id,
                              "because": routed.because,
                              "reading": body.get("reading") or {}},
                "figures": body.get("figures") or ""},
        follow_ups=[], warnings=caveats,
    )
    answered.from_memory = False
    answered.decision = rt.decide(question, deterministic=True)
    answered.reading = replace(
        answered.reading,
        objective=f"Scorecard validation — {routed.model_id}")
    answered.scorecard_model = routed.model_id
    return answered


#: What one row of a validation answer carries. Named once so the table and
#: the sentence above it cannot drift apart.
_VALIDATION_COLUMNS = [
    {"name": "test_id", "label": "Test", "semantic": "text", "align": "left"},
    {"name": "state", "label": "Outcome", "semantic": "text", "align": "left"},
    {"name": "value", "label": "Measured", "semantic": "number",
     "decimals": 4, "align": "right"},
    {"name": "limit", "label": "Limit", "semantic": "number",
     "decimals": 4, "align": "right"},
    {"name": "detail", "label": "What it says", "semantic": "text",
     "align": "left"},
]


def _validation_rows(body: dict[str, Any], model_id: str
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                                str, list[str]]:
    """Rows, columns, the sentence, and what the runner said to be careful of."""
    result = body.get("result") or {}
    caveats: list[str] = []
    figures = str(body.get("figures") or "")
    if figures:
        caveats.append(figures)

    # Three shapes, one renderer. A single test comes back as
    # {"test": …, "result": {…}}; a category as {"results": [ … ]}; and a few
    # tools return the Result at the top level. Reading only the last of the
    # three is why "what's the Gini?" produced nothing to render and fell
    # through to the planner, which asked which figure to measure.
    nested = result.get("result") if isinstance(result.get("result"), dict) else None
    if nested and nested.get("test_id"):
        singles = [nested]
    elif result.get("test_id"):
        singles = [result]
    else:
        singles = [r for r in (result.get("results") or []) if isinstance(r, dict)]
    rows = [{"test_id": str(r.get("test_id") or ""),
             "state": str(r.get("state_label") or r.get("state") or ""),
             "value": r.get("value"),
             "limit": r.get("limit"),
             "detail": str(r.get("detail") or "")}
            for r in singles if isinstance(r, dict)]
    if not rows:
        return [], [], "", caveats

    first = singles[0]
    period = str(first.get("period") or "")
    version = str(first.get("model_version") or "")
    observations = first.get("observations")
    events = first.get("events")
    # The cohort, the sample and the version, in the sentence rather than only
    # in the table: a discrimination figure with no population behind it is
    # the number an auditor asks the second question about.
    where = []
    if period:
        where.append(f"over {period}")
    if isinstance(observations, (int, float)) and observations:
        carried = (f" carrying {int(events):,} defaults"
                   if isinstance(events, (int, float)) and events else "")
        where.append(f"on {int(observations):,} observations{carried}")
    said = ", ".join(where)
    lead = str(first.get("detail") or "").strip()
    name = _scorecard_name(model_id)
    headline = (f"{name}"
                + (f" v{version}" if version else "")
                + (f" — {lead}" if lead else "")
                + (f" Measured {said}." if said and said not in lead else ""))
    if len(rows) > 1:
        headline = (f"{name}" + (f" v{version}" if version else "")
                    + f" — {len(rows)} "
                    + str(result.get("category") or "validation")
                    + " tests. " + lead)
    return rows, list(_VALIDATION_COLUMNS), headline, caveats


def _scorecard_name(model_id: str) -> str:
    try:
        from backend.scorecard.validation import models as registry

        for model in registry.all_models():
            if model.model_id == model_id:
                return str(model.name)
    except Exception:  # noqa: BLE001
        pass
    return model_id


#: One row per finding, in the severity order the engine returns them in.
_FINDING_COLUMNS = [
    {"name": "severity", "label": "Severity", "semantic": "text", "align": "left"},
    {"name": "title", "label": "Finding", "semantic": "text", "align": "left"},
    {"name": "category", "label": "Category", "semantic": "text", "align": "left"},
    {"name": "what", "label": "What the test found", "semantic": "text",
     "align": "left"},
]


def _validation_findings(answered: Answered, routed: Any,
                         question: str) -> Answered | None:
    """Every applicable test on one scorecard, assessed.

    Computes nothing of its own: this is the findings engine's output, which
    is what the Scorecard Validation module shows on the same scorecard.
    """
    from backend.orchestration import handlers

    try:
        body = scorecard_route.findings(routed.model_id)
    except Exception:  # noqa: BLE001 - fall through, never substitute
        logger.exception("The findings engine failed for %r", routed.model_id)
        return None
    found = list(body.get("findings") or [])
    if not found:
        return None
    summary = body.get("summary") or {}
    counts = dict(summary.get("by_severity") or {})
    rows = [{"severity": str(f.get("severity") or ""),
             "title": str(f.get("title") or ""),
             "category": str(f.get("category") or ""),
             "what": str(f.get("what") or "")}
            for f in found if isinstance(f, dict)]
    said = ", ".join(f"{n} {level.lower()}" for level, n in counts.items() if n)
    name = _scorecard_name(routed.model_id)
    worst = rows[0]["title"] if rows else ""
    headline = (f"{name} — {int(summary.get('total') or len(rows))} findings"
                + (f" ({said})" if said else "") + "."
                + (f" The one to read first is: {worst}." if worst else ""))
    answered.result = handlers.HandlerResult(
        answer=headline, rows=rows, columns=list(_FINDING_COLUMNS), values={},
        detail={"scorecard": {"model_id": routed.model_id,
                              "because": routed.because},
                "summary": summary},
        follow_ups=[], warnings=[
            "Every figure here was computed by the validation runner over the "
            "governed population. A finding is evidence for a judgement, not "
            "the judgement: CreditProbe does not approve or withdraw a model."],
    )
    answered.decision = rt.decide(question, deterministic=True)
    answered.reading = replace(
        answered.reading,
        objective=f"Scorecard validation findings — {routed.model_id}")
    answered.scorecard_model = routed.model_id
    return answered


_ASKS_WHICH_BAND = re.compile(
    r"\bwhich\b[^?]{0,40}\b(?:risk\s+)?(?:band|bucket|grade|decile)s?\b"
    r"|\b(?:band|bucket|grade|decile)s?\b[^?]{0,30}\b(?:most|worst|least)\b",
    re.IGNORECASE)

_BAND_COLUMNS = [
    {"name": "band", "label": "Band", "semantic": "text", "align": "left"},
    {"name": "score_from", "label": "Score from", "semantic": "number",
     "decimals": 1, "align": "right"},
    {"name": "score_to", "label": "Score to", "semantic": "number",
     "decimals": 1, "align": "right"},
    {"name": "observations", "label": "Observations", "semantic": "count",
     "decimals": 0, "align": "right"},
    {"name": "events", "label": "Defaults", "semantic": "count",
     "decimals": 0, "align": "right"},
    {"name": "average_predicted_pd", "label": "Predicted PD",
     "semantic": "percent", "decimals": 4, "align": "right"},
    {"name": "observed_default_rate", "label": "Observed rate",
     "semantic": "percent", "decimals": 4, "align": "right"},
    {"name": "gap", "label": "Observed − predicted", "semantic": "percent",
     "decimals": 4, "align": "right"},
    {"name": "evidence", "label": "Evidence", "semantic": "text",
     "align": "left"},
]


def _worst_band(body: dict[str, Any], question: str, model_id: str
                ) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                           str, list[str]] | None:
    """The calibration bands, and which of them is furthest out.

    Ranked by the gap between observed and predicted, and the evidence label
    the runner attached travels with it: a band of a thousand observations
    carrying seven defaults is not evidence of miscalibration however large
    its gap looks.
    """
    if not _ASKS_WHICH_BAND.search(str(question or "")):
        return None
    result = body.get("result") or {}
    candidates = []
    if isinstance(result.get("result"), dict):
        candidates.append(result["result"])
    candidates.extend(r for r in (result.get("results") or [])
                      if isinstance(r, dict))
    buckets: list[dict[str, Any]] = []
    for found in candidates:
        chart = found.get("chart") or {}
        if str(chart.get("kind") or "") == "calibration" and chart.get("buckets"):
            buckets = [b for b in chart["buckets"] if isinstance(b, dict)]
            break
    if not buckets:
        return None

    rows = []
    for bucket in buckets:
        observed = bucket.get("observed_default_rate")
        predicted = bucket.get("average_predicted_pd")
        gap = (float(observed) - float(predicted)
               if isinstance(observed, (int, float))
               and isinstance(predicted, (int, float)) else None)
        rows.append({**{k: bucket.get(k) for k in
                        ("band", "score_from", "score_to", "observations",
                         "events", "average_predicted_pd",
                         "observed_default_rate", "evidence")},
                     "gap": gap})
    scored = [r for r in rows if isinstance(r.get("gap"), (int, float))]
    if not scored:
        return None
    worst = max(scored, key=lambda r: abs(float(r["gap"])))
    direction = "under" if float(worst["gap"]) > 0 else "over"
    name = _scorecard_name(model_id)
    headline = (
        f"{name} — band {worst['band']} is the furthest out: observed "
        f"{float(worst['observed_default_rate']) * 100:.2f}% against a "
        f"predicted {float(worst['average_predicted_pd']) * 100:.2f}%, so it "
        f"is {direction}-predicted by "
        f"{abs(float(worst['gap'])) * 100:.2f} percentage points on "
        f"{int(worst['observations']):,} observations carrying "
        f"{int(worst['events']):,} defaults"
        + (f" — {str(worst.get('evidence') or '').lower()}."
           if worst.get("evidence") else "."))
    caveats = [str(body.get("figures") or "")] if body.get("figures") else []
    caveats.append(
        "A band's gap is only as good as its sample. The evidence column is "
        "the runner's own sufficiency judgement, and a band marked "
        "INSUFFICIENT EVIDENCE is not evidence of miscalibration.")
    return rows, list(_BAND_COLUMNS), headline, caveats


#: A sentence that deliberately asks for the same thing again.
_ASKS_AGAIN = re.compile(
    r"\b(?:again|re-?run|refresh|re-?calculate|recompute|repeat|"
    r"same\s+(?:thing|question|analysis)|once\s+more)\b", re.IGNORECASE)


def _repeats_the_previous_plan(build: Any, state: cv.ConversationState,
                               continuation: cv.Continuation,
                               question: str) -> str:
    """Whether this turn composed the analysis already on the table.

    Returns the sentence to ask instead, or "" to run it. Nothing here reads
    governed data: it compares two plans.
    """
    if state is None or not state.ir or not build or not build.plan:
        return ""
    if not getattr(continuation, "carries_context", False):
        return ""
    if _ASKS_AGAIN.search(str(question or "")):
        return ""
    # A plan with something new to SAY is not a repeat, whatever its
    # operations are. A composite asked for a six-month window runs at one
    # date and says so — the figures repeat, the answer does not.
    if getattr(build, "warnings", None):
        return ""
    # The OPERATIONS, not the whole document: `meta` carries the explanation
    # and the grain contract, which differ between two runs of the same
    # analysis without the analysis differing at all.
    def _executed(plan: dict[str, Any]) -> Any:
        return (plan.get("dataset"), plan.get("period"),
                json.dumps(plan.get("operations") or [], sort_keys=True,
                           default=str))

    if _executed(dict(build.plan)) != _executed(dict(state.ir)):
        return ""
    settled = state.plan_summary or "the previous analysis"
    return (
        "CreditProbe read that as the same analysis it has just run — "
        f"{settled} — so it has not run it a second time and given you the "
        "same figures under a different question. Say what should change: a "
        "different figure, a different population, a different period, or a "
        "breakdown.")


def _rows_to_choose_from(cached: Any, limit: int = 6) -> str:
    """The previous answer's rows, named, for a clarification that points back."""
    if cached is None or not getattr(cached, "usable", False):
        return ""
    rows = list(getattr(cached, "rows", None) or [])
    columns = list(getattr(cached, "columns", None) or [])
    if len(rows) < 2:
        return ""
    key = ""
    for column in columns:
        name = str(column.get("name") or "")
        if column.get("is_identity") or name.endswith(("_id", "_label")) \
                or str(column.get("semantic") or "") == "text":
            key = name
            break
    if not key:
        key = str((columns[0] or {}).get("name") or "") if columns else ""
    if not key:
        return ""
    names = [str(r.get(key)) for r in rows[:limit] if r.get(key) is not None]
    if not names:
        return ""
    more = f" and {len(rows) - len(names)} more" if len(rows) > len(names) else ""
    return ", ".join(names) + more

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
    visual = visualize.choose(cached.columns, cached.rows, requested=requested,
                              question=question)
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

    An ENTITY LIST is the exception. "Show Stage 2 borrowers" is answered with
    the largest ten, and ten is a cut — a reader of a population question needs
    to know what it was cut from, and the reconciliation is where that number
    already lives.
    """
    if build.shape not in (ap.COHORT, ap.MOVEMENT) \
            and not getattr(build, "entity_list", False):
        return None
    return [str(op.get("id")) for op in build.plan.get("operations") or []]


# ------------------------------------------------------------- remembering


#: Entity kinds that name a POPULATION rather than a measure or a date. A
#: clarification about which figure to compute does not put the population in
#: question, so these survive it.
_POPULATION_KINDS: frozenset[str] = frozenset({
    "sector", "industry", "stage", "rating", "grade", "segment", "region",
    "country", "product", "portfolio", "group", "watchlist",
})


def _keep_the_population_the_question_named(state: cv.ConversationState,
                                            answered: Answered) -> None:
    """Hold on to the population a clarified question named. R2 §6.

    A turn that ends in a clarification settles nothing, and that is right
    almost everywhere: answering "which figure did you mean?" should continue
    the thread rather than restart it, so the settled values must survive
    untouched.

    It is wrong in exactly one place. On the FIRST turn there is nothing to
    continue from, and the population the question itself named is dropped
    with everything else. "Why did Shipping deteriorate this quarter?" was
    read correctly — the reader resolved the sector — and then CreditProbe
    asked which figure to measure and forgot which sector it had been asked
    about, so the reply landed on the whole book.

    So: only when the state has no population, and only for entity kinds that
    name a population rather than a measure or a date. The user said Shipping.
    The clarification is about which figure, not about which sector, and
    nothing about the ambiguity puts the sector in doubt.
    """
    if not state.filter_pairs():
        found: list[dict[str, str]] = []
        for entity in getattr(answered.reading, "entities", ()) or ():
            kind = str((entity or {}).get("kind") or "").lower()
            value = str((entity or {}).get("value") or "")
            if kind in _POPULATION_KINDS and value:
                found.append({"kind": kind, "value": value})
        if found:
            state.filters = found

    # The quarter, for the same reason and with the same restraint. "Why did
    # Shipping deteriorate THIS QUARTER" names a reporting period as
    # definitely as it names a sector, and a thread that kept the sector while
    # losing the quarter would answer a different question just as
    # confidently — which is the failure mode this whole rule exists to stop.
    if not state.periods:
        periods = [str(p) for p in
                   (getattr(answered.reading, "periods", ()) or ()) if p]
        if periods:
            state.periods = periods


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

    # §9: a clarification must not destroy context. The question CreditProbe
    # could not plan is held so the reply — "expected credit loss." — can be
    # merged with it rather than read as a fresh request that names a measure
    # and asks nothing. Cleared the moment a turn settles something, so a
    # clarification answered two turns later is not silently re-merged.
    state.pending = answered.question if answered.clarification else ""

    # Which certified analysis is on screen, and what it ran with. A follow-up
    # that drills into one of its steps needs both: the analysis to re-run and
    # the population to re-run it over. Cleared by any analytical turn that
    # settles something else, so a drill-down cannot reach past the answer it
    # is actually looking at.
    # A certified route is recorded when it is SELECTED: the analysis itself is
    # executed downstream, so `answered.answered` is still false here and
    # waiting for it would mean never recording the one route a drill-down
    # needs. A clarification or a stated failure settles nothing, as everywhere
    # else in this function.
    if answered.certified is not None:
        state.certified_analysis = answered.certified.analysis_id
        state.certified_params = dict(answered.certified_params)
    elif answered.answered:
        state.certified_analysis = ""
        state.certified_params = {}

    # The scorecard a validation turn settled. Held like the certified
    # analysis is: a follow-up that names no model is about the one on screen,
    # and an analytical turn about the BOOK leaves it alone rather than
    # clearing it, because "what is ECL by product?" in the middle of a
    # validation conversation does not end the validation conversation.
    if answered.scorecard_model:
        state.scorecard_model = answered.scorecard_model
    if answered.governed_metric:
        state.governed_metric = answered.governed_metric
        if answered.governed_dimension:
            state.governed_dimension = answered.governed_dimension

    if answered.runtime is None or answered.build is None:
        _keep_the_population_the_question_named(state, answered)
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
    # The measure the ANSWER led with first, where a movement over several
    # measures chose one. A follow-up that inherits the analysis inherits the
    # figure the reader was just shown: "what changed this month?" leads with
    # ECL, and "which customers drove that?" ranked by gross carrying amount
    # because that happened to be the first match the planner listed.
    if (build.shape == ap.MOVEMENT and not build.conditions
            and not build.dimension and len(build.matches) > 1
            and answered.runtime is not None):
        from backend.orchestration import assembly as asm

        led = asm._led_by_the_largest_move(build, answered.runtime.rows)
        if led is not None:
            state.concepts = ([led.concept.label]
                              + [m.concept.label for m in build.matches
                                 if m.field != led.field])
    state.metrics = list(state.concepts)
    # A composite matches no concept, so the two lines above leave a
    # concern or deterioration ranking with no measure on the state at all.
    # Recorded by the words that named it, which is what the planner needs to
    # find it again, and cleared by any turn that settles an ordinary measure
    # so a composite cannot reach past the answer on screen.
    _meta = (build.plan or {}).get("meta") or {}
    _composite = (_meta.get("composite") or {}) if isinstance(_meta, dict) else {}
    state.composite = str(_composite.get("matched") or "") if not build.matches else ""
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
