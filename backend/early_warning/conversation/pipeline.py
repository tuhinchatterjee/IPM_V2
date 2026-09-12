"""
One Early Warning turn, from the question to the persisted thread.

The order, and why it is the order
-----------------------------------
    request_started
    sonnet_pass_1                 language, nothing resolved
    sonnet_pass_2                 the business request, thread in view
    ews_context_built             the domain, described
    opus_functionality_selection  WHO OWNS THIS — before any analysis exists
    opus_analysis_plan            only if Early Warning won
    validation
    execution
    result_packet
    opus_sufficiency_review
    opus_final_interpretation
    sonnet_summary_update
    thread_persisted

The one that matters is the fifth. Ownership is decided before a plan
exists, which means a question another functionality owns cannot reach this
domain's data even accidentally — there is no plan to run and nothing to
run it against. A selector placed after planning would be a preference; here
it is a gate.

The events are emitted rather than logged, and the tests assert the sequence.
A pipeline whose order is documented but not observable is one whose order
drifts.

The provider seam
-----------------
The stages are named after the models that serve them, and where a provider is
configured those models actually run: Sonnet for the two language passes and
the rolling summary, Opus for functionality selection, the analysis plan, the
sufficiency review and the final interpretation. See
`backend.early_warning.conversation.seam`, which is the one place an Early
Warning stage may reach a model and which reuses CreditProbe's own provider
and role configuration.

Every stage also has a deterministic implementation, and it is not a stub: it
is the floor the model is merged onto, the fallback when no provider is
configured or a call fails, the test seam, and the factual safety layer that
decides what a model is allowed to change. Where the deterministic path ran,
`engine` says `deterministic` and the ledger's model-call count says zero.
Nothing here records a model call that did not happen.
"""

from __future__ import annotations

import hashlib
import json
import re
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.early_warning import alternatives as alt_mod
from backend.early_warning import functionality as fn
from backend.early_warning import grain as grain_mod
from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import execute as ex
from backend.early_warning.conversation import normalise as norm
from backend.early_warning.conversation import packet as packet_mod
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import progress as progress_mod
from backend.early_warning.conversation import reading as reading_mod
from backend.early_warning.conversation import seam as seam_mod
from backend.early_warning.conversation import select as select_mod
from backend.early_warning.conversation import sufficiency as suff
from backend.early_warning.conversation import summary as summary_mod
from backend.early_warning.conversation import validate as val

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ stages

REQUEST_STARTED = "request_started"
SONNET_PASS_1 = "sonnet_pass_1"
SONNET_PASS_2 = "sonnet_pass_2"
CONTEXT_BUILT = "ews_context_built"
FUNCTIONALITY_SELECTED = "opus_functionality_selection"
PLAN_CREATED = "opus_analysis_plan"
VALIDATION_PASSED = "validation"
VALIDATION_FAILED = "validation_failed"
REPAIR_ATTEMPTED = "opus_plan_repair"
EXECUTION_COMPLETE = "execution"
EXECUTION_DECLINED = "execution_declined"
#: One governed analysis, as it finishes. `EXECUTION_COMPLETE` is emitted
#: after the whole loop, which is the right grain for the audit trail and the
#: wrong one for a reader watching: a six-analysis investigation would be one
#: line that sits still for twenty seconds and then says "done". This reports
#: each analysis as it lands, so the investigation visibly takes shape.
EXECUTION_STEP = "execution_step"
#: A stage announcing that it has BEGUN, carrying the user-facing step it is
#: about to work on. Every other event here is emitted when a stage FINISHES,
#: which is the right record of what happened and useless for saying what is
#: happening — the expensive part of a stage is over by the time its event
#: exists. Purely an instrumentation signal: it decides nothing, gates
#: nothing, and spends nothing.
STAGE_STARTED = "stage_started"
RESULT_PACKET = "result_packet"
SUFFICIENCY_COMPLETE = "opus_sufficiency_review"
REVISION_EXECUTED = "revision_executed"
FINAL_ANSWER = "opus_final_interpretation"
REDIRECT_ANSWER = "redirect_answer_created"
CLARIFICATION_ANSWER = "clarification_answer_created"
STOPPED_HONESTLY = "stopped_honestly"
SUMMARY_UPDATED = "sonnet_summary_update"
THREAD_PERSISTED = "thread_persisted"

#: The order the architecture specifies, for the trace a reader checks
#: against. Not every turn emits every one — a redirect emits none of the
#: analytical stages, which is the point of the gate.
STAGE_ORDER: tuple[str, ...] = (
    REQUEST_STARTED, SONNET_PASS_1, SONNET_PASS_2, CONTEXT_BUILT,
    FUNCTIONALITY_SELECTED, PLAN_CREATED, VALIDATION_PASSED,
    EXECUTION_COMPLETE, RESULT_PACKET, SUFFICIENCY_COMPLETE, FINAL_ANSWER,
    SUMMARY_UPDATED, THREAD_PERSISTED)

#: The stages that mean analytical data was reached. A redirect must emit
#: none of them, and the tests assert exactly that.
ANALYTICAL_STAGES: frozenset[str] = frozenset({
    PLAN_CREATED, VALIDATION_PASSED, EXECUTION_COMPLETE, REVISION_EXECUTED})


@dataclass
class Event:
    stage: str
    detail: dict[str, Any] = field(default_factory=dict)
    at_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "detail": dict(self.detail),
                "at_ms": self.at_ms}


@dataclass
class Turn:
    """One complete turn, and everything needed to audit it."""

    request_id: str
    question: str
    thread_id: str = ""
    mode: str = budget_mod.STANDARD
    events: list[Event] = field(default_factory=list)
    answer: dict[str, Any] = field(default_factory=dict)
    selection: dict[str, Any] = field(default_factory=dict)
    packet: packet_mod.ResultPacket | None = None
    rolling_summary: summary_mod.RollingSummary | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    #: Every model call that actually served a stage, in stage order. Empty
    #: when no provider is configured, which is not the same thing as a stage
    #: having been skipped.
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    #: Every ATTEMPT, including the ones that were charged and then failed.
    #: Read off the ledger rather than assembled here, so the arithmetic
    #: charged = succeeded + failed holds by construction. A trace reporting
    #: six calls and five served stages is then reconstructable rather than a
    #: discrepancy somebody has to guess at.
    model_attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def stages(self) -> list[str]:
        return [e.stage for e in self.events]

    @property
    def engines(self) -> dict[str, str]:
        """What actually served each stage — `model` or `deterministic`."""
        return {e.stage: str(e.detail.get("engine", ""))
                for e in self.events if e.detail.get("engine")}

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "thread_id": self.thread_id,
            "question": self.question, "mode": self.mode,
            "stages": self.stages,
            "events": [e.to_dict() for e in self.events],
            "answer": dict(self.answer),
            "functionality_selection": dict(self.selection),
            "result_packet": self.packet.to_dict() if self.packet else {},
            "rolling_summary": (self.rolling_summary.to_dict()
                                 if self.rolling_summary else {}),
            "budget": dict(self.budget),
            "model_calls": [dict(c) for c in self.model_calls],
            "model_attempts": [dict(c) for c in self.model_attempts],
            "engines": self.engines,
            "provider_configured": seam_mod.provider_available(),
        }


#: A request to read a dataset this domain does not hold, however it is
#: phrased. Refused rather than answered, because answering it with a
#: portfolio summary answers a question nobody asked and quietly implies the
#: refusal did not happen.
_OTHER_DOMAIN = re.compile(
    r"\b(ifrs\s?9|ifrs9|ratings? table|transactions? table|financials? table|"
    r"collateral register|facility book|general ledger|core banking|"
    r"cockpit (data|domain|dataset)|what.if (data|domain)|"
    r"scorecard (data|domain))\b", re.I)

#: An instruction aimed at the controls rather than at the data. Recorded
#: because a reader who typed it deserves to be told the controls held,
#: rather than receiving an answer that looks like compliance.
_OVERRIDE_ATTEMPT = re.compile(
    r"\bignore (the |your |all )?(rules?|instructions?|restrictions?|"
    r"constraints?|guardrails?)\b|\bbypass\b|\boverride the (lock|rules?)\b|"
    r"\bdisregard (the |your )?(rules?|instructions?)\b|"
    r"\bquery .* directly\b", re.I)


def _refuses_to_leave_the_domain(text: str) -> dict[str, Any] | None:
    """Whether the request asks this domain to read another one.

    Answering such a request with whatever this domain DOES hold is the
    subtle failure: the reader asked for IFRS 9, received a portfolio
    summary, and has no way to tell whether the boundary held or whether
    that summary came from IFRS 9. So it is refused by name.
    """
    named = _OTHER_DOMAIN.search(text or "")
    pushed = _OVERRIDE_ATTEMPT.search(text or "")
    if not named and not pushed:
        return None
    what = named.group(0) if named else "another domain"
    direct = (f"Early Warning does not read {what}, and asking it to does not "
              f"change that.")
    reading = (
        "The upstream systems — IFRS 9 staging, the ratings feed, the "
        "facility book — have already fed this domain: their values are "
        "materialised into the monthly snapshots and scored there. Reading "
        "them again at answer time would be reading the same fact from two "
        "places that can disagree, which is why the boundary is enforced in "
        "the validator and in the executor rather than requested in a "
        "prompt. Nothing was run for this question."
        if named else
        "The domain boundary is enforced in the validator and in the "
        "executor, not in an instruction that a request can argue with. "
        "Nothing was run for this question.")
    return {
        "answered": False, "scope": "refused",
        "direct": direct, "interpretation": reading,
        "follow_ups": [
            "Which obligors carry the strongest credit-event signals?",
            "Show me the evidence behind a node, including its source system.",
            "How does the Early Warning model work?",
        ],
        "caveats": [
            "Early Warning answers from its own monthly snapshots. Where a "
            "figure came from upstream, the evidence answer names the source "
            "system so it can be verified there."],
    }


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def answer(question: str, *, thread_id: str = "",
           ui_state: dict[str, Any] | None = None,
           rolling_summary: dict[str, Any] | None = None,
           recent: list[dict[str, Any]] | None = None,
           mode: str = budget_mod.STANDARD,
           permissions: dict[str, Any] | None = None,
           compose: Callable[..., Any] | None = None,
           on_event: Callable[[Event], None] | None = None) -> Turn:
    """Answer one Early Warning question, or decline for a stated reason.

    `on_event` is handed every event as it is recorded, so a caller can show
    the turn happening rather than only its result. It is an observer and
    nothing more: it cannot change what runs, and an exception raised inside
    it is swallowed, because a progress panel must never be able to cost
    somebody their answer.
    """
    started = time.perf_counter()
    turn = Turn(request_id=uuid.uuid4().hex[:16], question=question,
                thread_id=thread_id, mode=mode)
    ledger = budget_mod.open_ledger(mode)

    def emit(stage: str, **detail: Any) -> None:
        # A stage that reached a model records the call ON the turn, from the
        # call's own metadata. This is the only way `model_calls` is ever
        # populated, so a stage cannot claim `engine: model` without one.
        call = detail.get("model_call")
        if isinstance(call, dict) and call.get("engine") == seam_mod.MODEL:
            turn.model_calls.append({"stage": stage, **call})
        event = Event(stage=stage, detail=detail,
                      at_ms=int((time.perf_counter() - started) * 1000))
        turn.events.append(event)
        if on_event is not None:
            try:
                on_event(event)
            except Exception:  # noqa: BLE001 - an observer cannot break a turn
                logger.warning("An Early Warning progress observer failed.",
                               exc_info=True)

    def begin(step: str) -> None:
        """Announce the user-facing step this stage is about to work on."""
        emit(STAGE_STARTED, step=step)

    emit(REQUEST_STARTED, mode=mode, thread=thread_id,
         has_ui_state=bool(ui_state), has_summary=bool(rolling_summary))

    prior = summary_mod.load(rolling_summary)

    # ---- pass one: language ------------------------------------------
    begin(progress_mod.UNDERSTANDING)
    cleaned = norm.clean(question, ledger=ledger)
    emit(SONNET_PASS_1, engine=cleaned.engine,
         cleaned=cleaned.cleaned_english,
         translation_applied=cleaned.translation_applied,
         uncertainties=len(cleaned.uncertainties),
         model_call=dict(cleaned.model_call))

    # ---- pass two: the business request -------------------------------
    begin(progress_mod.SCOPING)
    request = norm.read(cleaned, ui_state=ui_state,
                        rolling_summary=prior.to_dict(), recent=recent,
                        ledger=ledger)
    emit(SONNET_PASS_2, engine=request.engine,
         analyses=list(request.requested_analyses),
         scope=request.requested_scope,
         subquestions=len(request.subquestions),
         clarification_needed=request.clarification_needed,
         model_call=dict(request.model_call))

    # ---- the domain, described ----------------------------------------
    begin(progress_mod.EVIDENCE)
    package = grain_mod.build(
        request.normalized_business_request,
        period=request.requested_period or None,
        permissions=permissions,
        capabilities=[t for t in plan_mod.ANALYSIS_TYPES])
    emit(CONTEXT_BUILT, domain=package.domain_id, periods=len(package.periods),
         fields=package.field_count, customers=package.customer_count,
         context_hash=_hash({"d": package.domain_id,
                              "p": package.periods,
                              "f": package.field_count}))

    # ---- THE GATE: who owns this? -------------------------------------
    begin(progress_mod.OWNERSHIP)
    selection = select_mod.decide(request.normalized_business_request,
                                  ledger=ledger)
    turn.selection = selection.to_dict()
    emit(FUNCTIONALITY_SELECTED, selected=selection.selected,
         confidence=round(selection.confidence, 3),
         ambiguous=selection.ambiguous, engine=selection.engine,
         active_product_is_best=selection.active_product_is_best,
         model_call=dict(selection.model_call))

    if selection.ambiguous and not selection.active_product_is_best:
        begin(progress_mod.CLARIFYING)
        turn.answer = {
            "answered": False, "scope": "clarification",
            "direct": selection.clarification,
            "interpretation": selection.rationale,
            "follow_ups": [], "caveats": [
                "No analysis was run. Ownership is decided before any "
                "analysis is planned, and it was not clear enough to decide."],
        }
        emit(CLARIFICATION_ANSWER, reason="ownership_ambiguous")
        return _finish(turn, request, prior, ledger, ui_state, emit)

    if selection.selected != fn.EARLY_WARNING:
        begin(progress_mod.ROUTING)
        turn.answer = alt_mod.redirect_answer(
            request.normalized_business_request, selection)
        emit(REDIRECT_ANSWER, to=selection.selected,
             alternatives=len(turn.answer.get("alternatives") or []))
        return _finish(turn, request, prior, ledger, ui_state, emit)

    # Early Warning owns the subject, but the request asks it to read
    # somewhere it does not read. Refused by name rather than answered with
    # whatever this domain happens to hold — a reader who asked for IFRS 9
    # and received a portfolio summary cannot tell which of those two things
    # happened.
    refusal = _refuses_to_leave_the_domain(
        f"{turn.question} {request.normalized_business_request}")
    if refusal is not None:
        turn.answer = refusal
        emit(STOPPED_HONESTLY, reason="request_names_another_domain")
        return _finish(turn, request, prior, ledger, ui_state, emit)

    # Asked to CHANGE something rather than to read it. The screen path has
    # always refused this; the conversation did not, and "change Gulf
    # Contracting 2's score to 20" came back as a movement decomposition —
    # a fluent answer to a question nobody asked, and one that leaves a
    # reader unsure whether the score was changed. Refused before a plan
    # exists, because there is no analysis that would make it right.
    # A name that matches several obligors is asked about, not guessed at,
    # and nothing analytical runs until it is settled. Answering "show me Al
    # Rabia" with the portfolio summary is the worst of both: the reader's
    # name went nowhere and nothing said so.
    if request.ambiguous_obligors:
        begin(progress_mod.CLARIFYING)
        options = request.ambiguous_obligors
        matched = str(options[0].get("matched") or "that name")
        total = int(options[0].get("total") or len(options))
        turn.answer = {
            "answered": False, "scope": "ambiguous_borrower",
            "direct": (f"{total} obligors match {matched!r}. Which one did "
                       f"you mean?"),
            "interpretation": (
                "Nothing was run. Picking one of several names that match is "
                "a guess, and a guess that looks like an answer is worse than "
                "a question — the figures would be right about the wrong "
                "obligor."),
            "options": [
                {"customer_id": o["customer_id"],
                 "customer_name": o["customer_name"],
                 "label": (f"{o['customer_name']} — "
                           f"{float(o.get('ews_score') or 0):.1f} "
                           f"({str(o.get('ews_band') or '').replace('_', ' ').lower()})")}
                for o in options],
            "follow_ups": [f"Show me {o['customer_name']}." for o in options[:5]],
            "caveats": ["No analysis was run: the obligor is not yet decided."],
        }
        emit(CLARIFICATION_ANSWER, reason="ambiguous_obligor",
             candidates=total)
        return _finish(turn, request, prior, ledger, ui_state, emit)

    mutation = _refuses_to_mutate(
        f"{turn.question} {request.normalized_business_request}")
    if mutation is not None:
        turn.answer = mutation
        emit(STOPPED_HONESTLY, reason="request_asks_to_change_a_governed_value")
        return _finish(turn, request, prior, ledger, ui_state, emit)

    # ---- Early Warning won. Only now does a plan exist. ----------------
    try:
        return _analyse(turn, request, package, ledger, prior, ui_state,
                        emit, begin, compose)
    except budget_mod.Exhausted as stop:
        turn.answer = _stopped(str(stop), turn)
        emit(STOPPED_HONESTLY, reason=str(stop))
        return _finish(turn, request, prior, ledger, ui_state, emit)
    except Exception as failure:  # noqa: BLE001 - the turn must not 500
        # The outermost boundary. Everything below it is meant to fail into a
        # repair or an honest limitation, and this is what makes that a
        # guarantee rather than a hope: a reader who asked an ordinary
        # question gets a stated limitation and a persisted thread, not a
        # stack trace.
        logger.exception("An Early Warning turn failed unexpectedly.")
        turn.answer = _broke(failure, turn)
        emit(STOPPED_HONESTLY, reason=f"{type(failure).__name__}: {failure}",
             unexpected=True)
        return _finish(turn, request, prior, ledger, ui_state, emit)


def _analyse(turn: Turn, request: Any, package: grain_mod.GrainPackage,
             ledger: budget_mod.Ledger, prior: summary_mod.RollingSummary,
             ui_state: dict[str, Any] | None,
             emit: Callable[..., None],
             begin: Callable[[str], None],
             compose: Callable[..., Any] | None) -> Turn:
    begin(progress_mod.PLANNING)
    plan = plan_mod.build(request, package, ledger=ledger)
    emit(PLAN_CREATED, steps=[s.analysis for s in plan.steps],
         output_grain=plan.output_grain, engine=plan.engine,
         plan_hash=_hash(plan.to_dict()),
         model_call=dict(plan.model_call))

    begin(progress_mod.VALIDATING)
    checked = val.check(plan, package,
                        permissions=package.permissions or None)
    while not checked.ok:
        emit(VALIDATION_FAILED,
             codes=[f.code for f in checked.failures],
             repairable=checked.repairable)
        if not checked.repairable:
            if plan.fallback is not None:
                # The model wrote a plan the validator refuses outright — a
                # dataset this domain does not hold, most often. The refusal
                # stands for that plan; the deterministic one is then
                # validated in its turn rather than waved through.
                emit(REPAIR_ATTEMPTED,
                     codes=[f.code for f in checked.failures],
                     fell_back_to="deterministic_plan",
                     repairs_spent=ledger.repairs)
                plan = plan.fallback
                plan.notes = list(plan.notes) + [
                    "The planned analysis was refused by the validator and "
                    "the deterministic plan was used instead."]
                checked = val.check(plan, package,
                                    permissions=package.permissions or None)
                continue
            turn.answer = _refused(checked, turn)
            emit(STOPPED_HONESTLY, reason="validation_not_repairable")
            return _finish(turn, request, prior, ledger, ui_state, emit)
        # A repair spends from the SAME ledger. That is what stops a
        # repeatedly-failing plan from being affordable forever.
        ledger.repair()
        failure_packet = val.failure_packet(
            plan, checked, package,
            question=turn.question, remaining=ledger.remaining())
        # The packet goes back to the planner that wrote the plan: what was
        # refused, why, and what the domain offers instead. A planner told
        # "invalid field" guesses again; one told which twelve groupings
        # exist fixes it. Where no model is available the deterministic
        # repair does the same job from the same packet.
        #
        # ONCE. A planner that could not fix it when told exactly what was
        # wrong will not fix it on the second telling, and a repair loop that
        # keeps asking is how a bounded turn becomes an unbounded one — it
        # spends the model calls the ANSWER needs on a correction that is not
        # converging. The second repair is deterministic, which terminates.
        repaired = (_repair_with_model(plan, package, failure_packet, checked,
                                       ledger)
                    if ledger.repairs == 1
                    else _repair(plan, checked, package))
        emit(REPAIR_ATTEMPTED, codes=[f.code for f in checked.failures],
             repairs_spent=ledger.repairs, engine=repaired.engine,
             unsupported=[u.get("reason") for u in
                          failure_packet.get("unsupported", [])],
             model_call=dict(repaired.model_call))
        plan = repaired
        checked = val.check(plan, package,
                            permissions=package.permissions or None)

    emit(VALIDATION_PASSED, checked=list(checked.checked),
         steps=len(plan.steps))

    begin(progress_mod.ANALYSING)

    # Every planned step gets its turn at the executor before any correction
    # gets a second one. An inline retry spends the execution a later planned
    # step was going to need, so one failing step could starve a step that
    # would have succeeded — which is how a six-step plan under a
    # six-execution ceiling stops before its sixth analysis.
    executed: list[ex.Executed] = []
    deferred: list[plan_mod.Step] = []
    declined: list[str] = []

    def _attempt(step: plan_mod.Step, *, corrected: bool) -> bool:
        """Run one step if the ceiling allows it. True if it ran and worked.

        The affordability question is asked BEFORE the charge and before the
        executor, so the step that cannot run is declined rather than
        attempted — and an exhausted ceiling ends this step, never the turn.
        A turn that let `Exhausted` escape from here would throw away every
        analysis that had already succeeded in order to report that the next
        one was one too many.
        """
        blocked = ledger.why_not("executions")
        if blocked:
            declined.append(step.analysis)
            return False
        ledger.execution()
        try:
            result = ex.run(step)
        except ex.ExecutionError as failure:
            ledger.settle_execution(analysis=step.analysis, ok=False,
                                    reason=failure.code, corrected=corrected)
            emit(EXECUTION_STEP, analysis=step.analysis, ok=False,
                 rows=0, corrected=corrected, group_by=step.group_by,
                 filters=dict(step.filters), period=step.period,
                 comparison_period=step.comparison_period)
            if corrected:
                return False
            # The last boundary held: the executor refused rather than
            # raising, and the refusal carries what the domain offers
            # instead. One bounded correction, queued behind the rest of the
            # plan; if it never gets budget the step is left out and the
            # sufficiency review names the part it could not cover.
            emit(VALIDATION_FAILED, codes=[failure.code],
                 repairable=True, at_step=step.analysis,
                 detail=str(failure), offered=list(failure.offered)[:8])
            if not ledger.can("repairs"):
                # Same rule as the executions ceiling: a spent allowance
                # costs this step its correction, not the turn its answer.
                return False
            ledger.repair()
            correction = _corrected(step, failure)
            emit(REPAIR_ATTEMPTED, codes=[failure.code],
                 repairs_spent=ledger.repairs,
                 engine="deterministic-step-repair",
                 corrected=correction is not None)
            if correction is not None:
                deferred.append(correction)
            return False
        executed.append(result)
        ledger.settle_execution(analysis=step.analysis, ok=True,
                                rows=result.row_count, corrected=corrected)
        emit(EXECUTION_STEP, analysis=step.analysis, ok=True,
             rows=result.row_count, corrected=corrected,
             group_by=step.group_by, filters=dict(step.filters),
             period=step.period, comparison_period=step.comparison_period)
        return True

    for step in plan.steps:
        _attempt(step, corrected=False)
    for step in deferred:
        _attempt(step, corrected=True)

    if declined:
        emit(EXECUTION_DECLINED, steps=declined[:8], count=len(declined),
             reason=ledger.why_not("executions") or "execution_declined",
             executed=len(executed))
    emit(EXECUTION_COMPLETE, steps=len(executed),
         rows=sum(e.row_count for e in executed),
         attempted=ledger.executions,
         succeeded=ledger.executions_succeeded,
         failed=ledger.executions_failed,
         declined=len(declined))

    packet = packet_mod.build(turn.question, request, plan, executed,
                              package=package, budget=ledger.to_dict())
    turn.packet = packet
    emit(RESULT_PACKET, figures=len(packet.figures), rows=len(packet.rows),
         packs=len(packet.packs), packet_hash=_hash(packet.figures))

    begin(progress_mod.CHECKING)
    reviewed = suff.review(request, plan, packet,
                           can_revise=ledger.may_revise(), ledger=ledger)
    emit(SUFFICIENCY_COMPLETE, complete=reviewed.complete,
         uncovered=list(reviewed.uncovered),
         presentation=reviewed.presentation, engine=reviewed.engine,
         model_call=dict(reviewed.model_call))

    while not reviewed.complete and reviewed.next_step is not None:
        if not ledger.may_revise():
            # A revision costs a revision, an execution and a second review,
            # and the answer still has to be written afterwards. Declining it
            # here returns the supported partial answer WITH its final
            # interpretation, which is a better turn than a fuller analysis
            # nobody got to read.
            emit(SUFFICIENCY_COMPLETE, complete=False,
                 uncovered=list(reviewed.uncovered),
                 presentation=reviewed.presentation,
                 engine=reviewed.engine,
                 revision_declined=ledger.why_not("model_calls"))
            reviewed.recommend_partial = True
            reviewed.next_step = None
            break
        ledger.revision()
        step = reviewed.next_step
        recheck = val.check(plan_mod.Plan(steps=[step]), package)
        if not recheck.ok:
            break
        if not ledger.can("executions"):
            break
        ledger.execution()
        try:
            revised = ex.run(step)
        except ex.ExecutionError as failure:
            # A revision spends from the same ledger and settles on it too,
            # so the executions a revision ran are visible beside the ones
            # the plan ran rather than folded into an untraceable total.
            ledger.settle_execution(analysis=step.analysis, ok=False,
                                    reason=failure.code)
            break
        executed.append(revised)
        ledger.settle_execution(analysis=step.analysis, ok=True,
                                rows=revised.row_count)
        emit(EXECUTION_STEP, analysis=step.analysis, ok=True,
             rows=revised.row_count, corrected=False,
             group_by=step.group_by, filters=dict(step.filters),
             period=step.period, comparison_period=step.comparison_period)
        emit(REVISION_EXECUTED, analysis=step.analysis,
             revisions_spent=ledger.revisions)
        plan.steps.append(step)
        packet = packet_mod.build(turn.question, request, plan, executed,
                                  package=package, budget=ledger.to_dict())
        turn.packet = packet
        reviewed = suff.review(request, plan, packet,
                               can_revise=ledger.may_revise(), ledger=ledger)
        emit(SUFFICIENCY_COMPLETE, complete=reviewed.complete,
             uncovered=list(reviewed.uncovered),
             presentation=reviewed.presentation, engine=reviewed.engine,
             model_call=dict(reviewed.model_call))

    begin(progress_mod.INTERPRETING)
    floor = _compose(turn, request, packet, reviewed, compose)
    read = reading_mod.write(turn.question, packet, floor, reviewed,
                             ledger=ledger)
    turn.answer = read.answer
    emit(FINAL_ANSWER, scope=turn.answer.get("scope", ""),
         complete=reviewed.complete,
         presentation=reviewed.presentation,
         engine=read.engine,
         ungrounded_figures=list(read.ungrounded),
         model_call=dict(read.model_call))
    return _finish(turn, request, prior, ledger, ui_state, emit)


def _repair_with_model(plan: plan_mod.Plan, package: grain_mod.GrainPackage,
                       packet: dict[str, Any], checked: val.Result,
                       ledger: budget_mod.Ledger) -> plan_mod.Plan:
    """The refused plan, corrected — by the planner where one is configured.

    The deterministic repair is computed first and is what the model is
    merged onto, so a provider that is unavailable or unhelpful costs the
    quality of the correction rather than the turn.
    """
    from backend.early_warning.conversation import planner as planner_mod

    floor = _repair(plan, checked, package)
    try:
        return planner_mod.repair(None, package, plan, packet, floor,
                                  ledger=ledger)
    except Exception as failure:  # noqa: BLE001 - a repair must not lose a turn
        logger.warning("The Early Warning repair seam failed: %s", failure)
        return floor


def _corrected(step: plan_mod.Step,
               failure: ex.ExecutionError) -> plan_mod.Step | None:
    """One bounded correction to a step the executor refused.

    Uses only what the refusal itself offered. Nothing is invented, and a
    refusal that offered nothing gets no correction — the part is dropped and
    the answer says which one, which is better than running something else
    and reporting it as what was asked.
    """
    import copy

    offered = list(failure.offered or [])
    if not offered:
        return None
    fixed = copy.deepcopy(step)
    if failure.code == "ungroupable":
        fixed.group_by = offered[0]
    elif failure.code == "unknown_field":
        fixed.measures = [m for m in fixed.measures if m != fixed.order_by]
        fixed.measures = list(plan_mod.BASE_MEASURES)
        fixed.order_by = "ews_score"
        fixed.filters = {}
    elif failure.code == "no_data":
        fixed.period = offered[-1]
    else:
        return None
    return fixed if fixed.to_dict() != step.to_dict() else None


def _repair(plan: plan_mod.Plan, checked: val.Result,
            package: grain_mod.GrainPackage) -> plan_mod.Plan:
    """Fix what the failure packet named, in place, within the same plan.

    Deterministic repair: an unknown field is replaced by the nearest real
    one the validator offered, an unknown period by the nearest published
    one. A live planner repairs the same structure from the same packet.
    """
    from backend.early_warning import executable as ex_mod

    steps = list(plan.steps)
    dropped: set[int] = set()
    notes = list(plan.notes)
    for failure in checked.failures:
        if failure.step_index < 0 or failure.step_index >= len(steps):
            continue
        step = steps[failure.step_index]
        offered = failure.offered
        if failure.code == "unknown_field":
            if failure.role == ex_mod.FILTER:
                # A condition nobody can honour. Dropping just the filter
                # would silently widen the population the step reports on,
                # which is the same answer to a different question — so the
                # step goes, and the sufficiency review names the part of the
                # request it could not cover.
                dropped.add(failure.step_index)
                notes.append(
                    f"A step was dropped: it filtered on "
                    f"{failure.field_name!r}, which this domain does not "
                    f"hold, and running it unfiltered would have answered a "
                    f"wider question than the one asked.")
                continue
            if failure.role == ex_mod.ORDER_BY:
                step.order_by = "ews_score"
                continue
            bad = {failure.field_name} if failure.field_name else set()
            step.measures = [m for m in step.measures if m not in bad]
            if offered:
                step.measures.append(offered[0])
            if not step.measures:
                step.measures = list(plan_mod.BASE_MEASURES)
            if step.order_by not in step.measures:
                step.order_by = "ews_score"
        elif failure.code in ("unknown_period", "future_leakage") and offered:
            if failure.code == "future_leakage":
                step.comparison_period = offered[-1]
            else:
                step.period = offered[-1]
        elif failure.code == "ungroupable" and offered:
            step.group_by = offered[0]
        elif failure.code == "missing_comparison" and offered:
            step.comparison_period = offered[0]
        elif failure.code == "unknown_layer" and offered:
            step.layer = offered[0]
        elif failure.code == "unbounded":
            step.limit = val.MAX_ROWS
        elif failure.code == "grain_unsafe" and offered:
            step.period = offered[-1]
    kept = [step for i, step in enumerate(steps) if i not in dropped]
    if not kept:
        # Every step was unhonourable. The deterministic plan the model
        # replaced is a better answer than no analysis at all, and it is
        # validated in its turn like everything else.
        kept = list((plan.fallback or plan).steps) or steps
        notes.append("Every planned step was refused, so the deterministic "
                     "plan was used instead.")
    return plan_mod.Plan(steps=kept[:val.MAX_STEPS],
                         output_grain=plan.output_grain, intent=plan.intent,
                         engine="deterministic-repair", notes=notes,
                         fallback=plan.fallback)


def _compose(turn: Turn, request: Any, packet: packet_mod.ResultPacket,
             reviewed: suff.Review,
             compose: Callable[..., Any] | None) -> dict[str, Any]:
    """The answer, written from the packet and from nothing else."""
    from backend.early_warning import compose as cp

    # The intent decides WHICH reading, not just whether there is one. The
    # product already has a composer per question shape — the action library
    # reading, the escalation route reading, the movement decomposition —
    # and routing every intent through the generic one would answer "what
    # should I do?" with the obligor's position, which is the question
    # before it.
    pack = packet.primary
    intent = str((packet.plan or {}).get("intent") or "")
    writer = compose or _writer_for(intent, pack)
    if pack is None:
        return {
            "answered": False, "scope": "no_evidence",
            "direct": ("Nothing was returned for that scope, so there is no "
                       "position to report."),
            "interpretation": "",
            "follow_ups": ["Show the published months."],
            "caveats": list(packet.caveats),
        }
    written = writer(pack)
    points = list(written.points)

    # A reader who asked "which names drive it?" needs the names. The
    # ranking step returned them; without this they sit in the packet while
    # the answer restates the population the reader was already looking at.
    #
    # Not when the reading IS the ranking, though. This line predates the
    # ranking composer and was the patch for its absence — keeping both
    # prints the names twice, once as a sentence and once as a list. The
    # same is true of a layer population, whose composer lists the names with
    # the layer score each is on; the generic line lists them again ordered
    # by exposure and scored on a measure the question did not ask about.
    if pack.scope not in ("ranking", "layer_population"):
        ranked = _ranked_obligors(packet)
        if ranked:
            points.insert(0, ranked)

    points += _other_readings(packet, pack, cp)

    out = {
        "answered": True,
        "scope": pack.scope,
        "direct": written.direct,
        "interpretation": written.interpretation,
        "points": points,
        "drivers": list(written.drivers),
        "follow_ups": list(written.follow_ups),
        "caveats": list(written.caveats),
        "presentation": reviewed.presentation,
        "complete": reviewed.complete,
    }
    # Said before the number, not after it. A reader who asked for a
    # probability and is shown 95.0 has their answer before they reach a
    # caveat at the bottom.
    if _asked_for_a_probability(turn.question):
        out["direct"] = f"{_NOT_A_PROBABILITY} {out['direct']}"
        out["caveats"] = [_NOT_A_PROBABILITY] + list(out["caveats"])

    if not reviewed.complete:
        # A partial answer that does not say so is the failure the whole
        # sufficiency review exists to prevent.
        missing = ", ".join(reviewed.uncovered) or "part of the request"
        out["caveats"] = list(out["caveats"]) + [
            f"This answer is partial: the request also asked for a "
            f"{missing}, and the evidence for it was not produced within "
            f"this turn's budget."]
    del turn, request
    return out


#: A question that asks the score to be something it is not.
#:
#: The Early Warning score orders obligors by how much warning evidence they
#: carry. It is not fitted to default outcomes and it is not a probability,
#: and the whole product says so — in the methodology, in the calibration
#: caveat, in the network score's own published label. It did not say so
#: where it matters most: asked "what is the probability that Gulf
#: Contracting 2 defaults?" it answered "95.0 (very high)" and let the
#: reader draw the obvious and wrong conclusion.
_ASKS_FOR_A_PROBABILITY = re.compile(
    r"\bprobabilit\w*|\blikelihood\b|\bhow likely\b|\bchance\b|"
    r"\bodds\b|\bwhat are the odds\b|\bpd\b|\bexpected loss\b|"
    r"\bwill (?:it|they|he|she|this|that) default\b|"
    r"\bgoing to default\b|\bdefault rate\b|\brisk of default\b", re.I)

_NOT_A_PROBABILITY = (
    "The Early Warning score is not a probability of default. It orders "
    "obligors by how much warning evidence they carry and is not fitted to "
    "default outcomes, so it cannot be read as a likelihood, a PD or an "
    "expected loss. Where a probability is needed the rating model's PD is "
    "the governed source, and it is a different number for a different "
    "question.")


def _asked_for_a_probability(text: str) -> bool:
    return bool(_ASKS_FOR_A_PROBABILITY.search(text or ""))


def _refuses_to_mutate(text: str) -> dict[str, Any] | None:
    """A request to change a governed value, refused with the route that does
    exist.

    The patterns are the screen path's own, imported rather than restated:
    two definitions of what counts as a mutation is two chances for one of
    them to miss.
    """
    from backend.early_warning import ask as ask_mod

    if ask_mod._REFUSE_SCORE_CHANGE.search(text):
        return {
            "answered": False, "scope": "refusal", "refused": True,
            "direct": ("CreditProbe does not change a score on request. The "
                       "assistant explains and navigates; an override goes "
                       "through the documented override path, where it is "
                       "recorded and counted as a control."),
            "interpretation": (
                "Nothing was changed and nothing was run. A score that could "
                "be argued down in a chat window would not be a control, and "
                "the override path exists so that a change has an author, a "
                "reason and a record."),
            "points": [], "drivers": [],
            "follow_ups": ["Why is this obligor scored where it is?",
                           "Show me the evidence behind that node.",
                           "What action should I take?"],
            "caveats": ["No analysis was run: the request asked for a change "
                        "rather than for a reading."],
        }
    if ask_mod._REFUSE_CLOSE.search(text):
        return {
            "answered": False, "scope": "refusal", "refused": True,
            "direct": ("Closing a case is not something the chat layer does. "
                       "It proposes; the escalation matrix decides, and a "
                       "case closes on its evidence test rather than on a "
                       "request."),
            "interpretation": (
                "The evidence test is recorded on the action itself, so what "
                "closes this case is a fact somebody can check rather than a "
                "decision taken in conversation."),
            "points": [], "drivers": [],
            "follow_ups": ["What action should I take?",
                           "What evidence closes this case?"],
            "caveats": ["No analysis was run: the request asked for a case "
                        "decision rather than for a reading."],
        }
    return None


def _other_readings(packet: packet_mod.ResultPacket, headline: Any,
                    cp: Any) -> list[str]:
    """The parts of a multi-part question the headline does not answer.

    "Why has Contracting deteriorated over six months, is it concentrated in
    a handful of names, and which layer is driving it?" is three questions.
    The planner runs three steps and the packet holds three packs, and then
    one composer writes from ONE of them and the other two sit in the packet
    unread. The reader gets a third of what they asked for, presented as the
    whole answer.

    Each remaining pack's own composer writes its own leading sentence, so
    these lines are as grounded as the headline is — they are the same
    writers over the same facts, not a summary of them.
    """
    lines: list[str] = []
    seen = {headline.scope}
    for pack in packet.packs:
        if pack is headline or pack.scope in seen:
            continue
        writer = cp.COMPOSERS.get(pack.scope)
        if writer is None:
            continue
        seen.add(pack.scope)
        try:
            said = writer(pack).direct
        except Exception:  # noqa: BLE001 - a supporting line is not the turn
            continue
        if said and said not in lines:
            lines.append(said)
    return lines


def _ranked_obligors(packet: packet_mod.ResultPacket) -> str:
    """The obligors a ranking step named, largest exposure first.

    Ordered by exposure rather than by score: a reader asking which names
    drive a population is asking which ones matter, and a very high score on
    a small exposure does not.
    """
    from backend.early_warning import units

    step = next((s for s in packet.steps
                 if s.get("analysis") == plan_mod.RANKING), None)
    if not step or not step.get("rows"):
        return ""
    named = []
    for row in step["rows"][:5]:
        name = str(row.get("customer_name") or row.get("customer_id") or "")
        if not name:
            continue
        score = row.get("ews_score")
        exposure = row.get("exposure")
        piece = name
        if score is not None:
            piece += f" at {float(score):.0f}"
        if exposure is not None:
            piece += f" on {units.money(float(exposure))}"
        named.append(piece)
    if not named:
        return ""
    more = (f", and {len(step['rows']) - len(named)} more"
            if len(step["rows"]) > len(named) else "")
    return (f"The names carrying it, largest exposure first: "
            f"{'; '.join(named)}{more}.")


def _writer_for(intent: str, pack: Any) -> Callable[..., Any]:
    """The composer whose reading answers THIS question."""
    from backend.early_warning import compose as cp

    if pack is None or getattr(pack, "scope", "") != "borrower":
        return cp.compose
    if intent == "escalation":
        return cp.escalation
    if intent == "action":
        return cp.action
    if intent == "movement":
        return cp.borrower_movement
    return cp.compose


def _refused(checked: val.Result, turn: Turn) -> dict[str, Any]:
    reasons = "; ".join(f.message for f in checked.failures)
    return {
        "answered": False, "scope": "refused",
        "direct": "That analysis was refused before it ran.",
        "interpretation": reasons,
        "follow_ups": [], "caveats": [
            "Validation runs before execution, so a refused plan reaches no "
            "data at all."],
        "request_id": turn.request_id,
    }


def _stopped(reason: str, turn: Turn) -> dict[str, Any]:
    return {
        "answered": False, "scope": "stopped",
        "direct": f"This turn stopped before it finished: {reason}.",
        "interpretation": (
            "What was attempted is on the trace. Nothing was invented to "
            "fill the gap — an answer completed past its own evidence is "
            "worse than one that stops."),
        "follow_ups": ["Ask the same question in Deep mode."],
        "caveats": [], "request_id": turn.request_id,
    }


def _broke(failure: Exception, turn: Turn) -> dict[str, Any]:
    """An unexpected failure, said plainly rather than thrown."""
    return {
        "answered": False, "scope": "stopped",
        "direct": ("This turn could not be completed, and nothing partial is "
                   "being reported as though it were an answer."),
        "interpretation": (
            f"The analysis stopped on an unexpected {type(failure).__name__}. "
            f"What ran before it is on the trace, and the thread is intact — "
            f"the same question can be asked again. Nothing was invented to "
            f"fill the gap."),
        "follow_ups": ["Ask the same question again.",
                       "Ask for the portfolio position for this month."],
        "caveats": ["The failure is recorded against this request id."],
        "request_id": turn.request_id,
    }


def _finish(turn: Turn, request: Any, prior: summary_mod.RollingSummary,
            ledger: budget_mod.Ledger, ui_state: dict[str, Any] | None,
            emit: Callable[..., None]) -> Turn:
    """One summary update, then persistence. Always both, on every path."""
    emit(STAGE_STARTED, step=progress_mod.CONTEXT)
    turn.rolling_summary = summary_mod.update(
        prior, question=turn.question, request=request, answer=turn.answer,
        packet=turn.packet, ui_state=ui_state, ledger=ledger)
    emit(SUMMARY_UPDATED, turns=turn.rolling_summary.turns,
         engine=turn.rolling_summary.engine,
         model_call=dict(turn.rolling_summary.model_call))
    turn.budget = ledger.to_dict()
    turn.model_attempts = [dict(c) for c in ledger.calls]
    emit(THREAD_PERSISTED, thread=turn.thread_id,
         summary_version=turn.rolling_summary.version,
         model_calls_charged=ledger.model_calls,
         model_calls_succeeded=ledger.model_calls_succeeded,
         model_calls_failed=ledger.model_calls_failed)
    return turn


__all__ = ["ANALYTICAL_STAGES", "STAGE_ORDER",
           "CLARIFICATION_ANSWER", "CONTEXT_BUILT",
           "EXECUTION_COMPLETE", "EXECUTION_DECLINED", "EXECUTION_STEP",
           "Event", "FINAL_ANSWER",
           "FUNCTIONALITY_SELECTED", "PLAN_CREATED", "REDIRECT_ANSWER",
           "REPAIR_ATTEMPTED", "REQUEST_STARTED", "RESULT_PACKET",
           "REVISION_EXECUTED", "SONNET_PASS_1", "SONNET_PASS_2",
           "STAGE_STARTED", "STOPPED_HONESTLY", "SUFFICIENCY_COMPLETE",
           "SUMMARY_UPDATED",
           "THREAD_PERSISTED", "Turn", "VALIDATION_FAILED",
           "VALIDATION_PASSED", "answer"]
