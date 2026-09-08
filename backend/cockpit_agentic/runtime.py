"""
One request, end to end. Specification sections 8, 9 and 11.

This is the server-owned state machine. The model requests transitions; this
approves them, updates the counters atomically, and stops.

The four properties this module is responsible for
--------------------------------------------------
**The gate is first and it is real.** Nothing reaches the validator before
`decision.may_execute` is true. A referral or a clarification returns from
`FUNCTIONALITY_ASSESSMENT` without ever entering `VALIDATING`, so "a referral
performs zero analytical executions" is structural rather than a promise.

**CreditProbe never authors a repair.** On failure it builds an
`ExecutionFailurePacket` and returns it to Opus. There is no branch in this
file that writes or edits SQL. `_execute_submission` runs what it was given.

**The counters are global and they do not reset.** Five submissions and three
rounds for the whole request, enforced by the ledger, which raises rather than
returns. A new plan does not buy a sixth attempt because `note_submission` does
not know what plan asked.

**A stop is honest.** Whatever ends the request -- the gate, the budget, the
deadline, an unrepairable failure, insufficient evidence -- the user gets an
envelope that says what was understood, what was tried, why it stopped and what
would help. There is no fallback to a deterministic narrative engine and no
canned decomposition standing in for an unavailable model (sections 17 and 18).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_agentic import DOMAIN, STANDARD
from backend.cockpit_agentic import catalog as catalog_mod
from backend.cockpit_agentic import context as context_mod
from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import failure as failure_mod
from backend.cockpit_agentic import opus as opus_mod
from backend.cockpit_agentic import scope as scope_mod
from backend.cockpit_agentic import sonnet as sonnet_mod
from backend.cockpit_agentic import sql as sql_mod
from backend.cockpit_agentic import states as st
from backend.cockpit_agentic.ledger import (STORE, BudgetExceeded, Ledger,
                                            Prices, STOP_CANCELLED,
                                            STOP_DEADLINE, STOP_NO_PROGRESS,
                                            STOP_ROUNDS, STOP_SUBMISSIONS)

logger = logging.getLogger(__name__)


@dataclass
class Outcome:
    """What the user gets, and everything needed to audit how."""

    request_id: str
    status: str
    envelope: K.AnswerEnvelope
    decision: K.FunctionalityDecision | None = None
    plan: K.AnalysisPlan | None = None
    results: list[K.ExecutionResultPacket] = field(default_factory=list)
    failures: list[K.ExecutionFailurePacket] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    machine: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    exchange: K.Exchange | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "domain_id": DOMAIN,
            "status": self.status,
            "answer": self.envelope.to_dict(),
            "functionality_decision": (self.decision.to_dict()
                                       if self.decision else None),
            "plan": self.plan.to_dict() if self.plan else None,
            "results": [r.to_dict() for r in self.results],
            "failures": [f.to_dict() for f in self.failures],
            "budget": dict(self.budget),
            "states": dict(self.machine),
            "context": dict(self.context),
        }


def _stop_envelope(*, reason: str, narrative: str, understood: str = "",
                   tried: list[str] | None = None, help_text: str = "",
                   limitations: list[str] | None = None) -> K.AnswerEnvelope:
    """A factual, server-generated stop. Never a fabricated analyst answer."""
    return K.AnswerEnvelope(
        kind="stop", narrative=narrative, complete=False, stop_reason=reason,
        what_was_understood=understood, what_was_tried=list(tried or []),
        what_would_help=help_text, limitations=list(limitations or []))


class Runtime:
    """One request. Construct, `run`, read the outcome."""

    def __init__(self, *, provider: Any, principal: Any,
                 dataset_release_id: str, coverage: Any, calendar: Any,
                 mode: str = STANDARD, request_id: str = "",
                 prices: Prices | None = None, store: Any = STORE) -> None:
        self.request_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        self.provider = provider
        self.mode = mode
        self.scope = scope_mod.for_principal(
            principal, dataset_release_id=dataset_release_id)
        self.catalog = catalog_mod.build(
            dataset_release_id=dataset_release_id, calendar=calendar,
            tenant_id=self.scope.tenant_id)
        self.coverage = coverage
        # Idempotent: the same request id continues one budget rather than
        # opening a second (section 9.3).
        self.ledger, self.resumed = store.open(
            request_id=self.request_id, mode=mode, prices=prices)
        self.machine = st.Machine()
        self.session: sql_mod.Session | None = None
        self.progress: list[str] = []

        self.decision: K.FunctionalityDecision | None = None
        self.plan: K.AnalysisPlan | None = None
        self.results: list[K.ExecutionResultPacket] = []
        self.failures: list[K.ExecutionFailurePacket] = []
        self.attempts: list[dict[str, Any]] = []
        self.artifacts = K.ArtifactManifest(request_id=self.request_id)
        self.completed_steps: list[str] = []
        self.context_packet: context_mod.CockpitContextPacket | None = None

    # -- progress -------------------------------------------------------

    def _advance(self, state: str, why: str = "") -> None:
        self.machine.advance(state, why)
        self.progress.append(st.progress(
            state, submission=self.ledger.submissions + 1,
            submission_max=self.ledger.limits.execution_submissions,
            round=max(1, self.ledger.analysis_rounds),
            round_max=self.ledger.limits.analysis_rounds))

    def cancel(self) -> None:
        self.ledger.cancel()

    # -- the run --------------------------------------------------------

    def run(self, question: str, *, ui_filters: dict[str, Any] | None = None,
            rolling_summary: dict[str, Any] | None = None,
            recent_exchanges: list[dict[str, Any]] | None = None) -> Outcome:
        try:
            return self._run(question, ui_filters=ui_filters,
                             rolling_summary=rolling_summary,
                             recent_exchanges=recent_exchanges)
        except BudgetExceeded as e:
            return self._budget_stop(e, question)
        except opus_mod.OpusUnavailable as e:
            # Section 17 and 18: no hidden fallback to the old deterministic
            # engine, and no canned decomposition standing in for a missing
            # model. The user is told the truth.
            return self._finish(
                st.PROVIDER_ERROR,
                _stop_envelope(
                    reason="provider_unavailable",
                    narrative=str(e),
                    understood=question,
                    help_text=("This is an operator or configuration matter, "
                               "not something rephrasing the question can "
                               "fix.")))
        except Exception as e:                              # noqa: BLE001
            from backend.llm.base import LLMError

            if not isinstance(e, (LLMError, context_mod.ContextTooLarge)):
                raise
            if isinstance(e, LLMError):
                # The provider's own reason, not a generic internal error. A
                # deployment with no credential must be told that, because it
                # is the actionable fact and no analysis was substituted for it.
                return self._finish(
                    st.PROVIDER_ERROR,
                    _stop_envelope(
                        reason="provider_unavailable", narrative=str(e),
                        understood=question,
                        help_text=("This is an operator or configuration "
                                   "matter. No answer was produced from a "
                                   "deterministic substitute.")))
            raise
        except context_mod.ContextTooLarge as e:
            return self._finish(
                st.CONTEXT_TOO_LARGE,
                _stop_envelope(
                    reason="context_too_large", narrative=str(e),
                    understood=question,
                    help_text=("An administrator can raise the per-call input "
                               "cap for this deployment. Rephrasing the "
                               "question cannot make the data dictionary "
                               "smaller.")))
        except Exception as e:                              # noqa: BLE001
            logger.exception("The Cockpit request failed")
            return self._finish(
                st.PROVIDER_ERROR,
                _stop_envelope(
                    reason="system_error",
                    narrative=("The Cockpit could not complete this request "
                               "because of an internal error. Nothing was "
                               "answered from a substitute."),
                    understood=question, help_text=str(e)[:200]))

    def _run(self, question: str, *, ui_filters, rolling_summary,
             recent_exchanges) -> Outcome:
        # ---- Sonnet pass 1 -------------------------------------------
        self._advance(st.NORMALIZING_1, "cleaning and translating")
        cleaned = sonnet_mod.clean(question, self.provider, self.ledger)

        # ---- Sonnet pass 2 -------------------------------------------
        self._advance(st.NORMALIZING_2, "normalizing into a business request")
        normalized = sonnet_mod.normalize(
            cleaned, self.provider, self.ledger, ui_filters=ui_filters,
            rolling_summary=rolling_summary, recent_exchanges=recent_exchanges)

        # ---- the context packet --------------------------------------
        self._advance(st.BUILDING_CONTEXT, "assembling the Cockpit catalogue")
        try:
            self.session = sql_mod.open_session(scope=self.scope,
                                                catalog=self.catalog)
        except sql_mod.SqlRejected as e:
            return self._finish(
                st.EXECUTION_FAILED,
                _stop_envelope(
                    reason=e.category, narrative=str(e), understood=question,
                    help_text=("This is an access or configuration matter for "
                               "an administrator.")))

        self.context_packet = context_mod.build(
            request_id=self.request_id, cleaned=cleaned, normalized=normalized,
            scope=self.scope, catalog=self.catalog, coverage=self.coverage,
            ledger=self.ledger, session=self.session,
            ui_filters=ui_filters, rolling_summary=rolling_summary,
            recent_exchanges=recent_exchanges)

        conversation = opus_mod.Conversation(
            provider=self.provider, ledger=self.ledger,
            packet=self.context_packet)

        # ---- the gate ------------------------------------------------
        self._advance(st.FUNCTIONALITY_ASSESSMENT,
                      "checking this is a Cockpit question")
        self.decision, self.plan, submission = opus_mod.gate_and_plan(
            conversation, self.context_packet)

        if not self.decision.may_execute:
            return self._not_ours(question, cleaned, normalized)

        # Section 6.2: a score never overrides ownership, and a tie is a
        # clarification. The server checks this rather than trusting the
        # decision field alone.
        if not self.decision.uniquely_highest_cockpit():
            self.decision.decision = K.CLARIFY_FUNCTIONALITY
            if not self.decision.clarification_question:
                self.decision.clarification_question = (
                    "This request could be handled by more than one part of "
                    "CreditProbe. Which would you like?")
            return self._not_ours(question, cleaned, normalized)

        # ---- the analysis loop ---------------------------------------
        self._advance(st.PLANNING, "planning the analysis")
        self.ledger.note_analysis_round()

        return self._loop(conversation, submission, question, cleaned,
                          normalized)

    # -- the loop --------------------------------------------------------

    def _loop(self, conversation, submission, question, cleaned,
              normalized) -> Outcome:
        while True:
            stopped = self.ledger.may_continue()
            if stopped:
                raise BudgetExceeded(stopped,
                                     self.ledger._stop_message(stopped))

            if submission is None:
                return self._insufficient(
                    question,
                    "The analysis produced no executable step, so nothing "
                    "could be run.")

            outcome = self._attempt(conversation, submission)
            if isinstance(outcome, Outcome):
                return outcome
            submission = outcome

    def _attempt(self, conversation, submission: K.ExecutionSubmission):
        """One validate-execute-review cycle. Returns the next submission, or
        an Outcome when the request is finished."""
        # ---- validate ------------------------------------------------
        if self.machine.state != st.VALIDATING:
            self._advance(st.VALIDATING, "checking the analysis against the "
                                         "data")
        try:
            number = self.ledger.note_submission(submission.fingerprint)
        except BudgetExceeded as e:
            if e.reason == STOP_NO_PROGRESS:
                return self._insufficient(
                    "", "The same query was proposed again after it had "
                        "already failed. Repeating it cannot make progress, so "
                        "the request stopped here rather than spending another "
                        "attempt on it.")
            raise
        submission = K.ExecutionSubmission(
            submission_id=submission.submission_id, plan_id=submission.plan_id,
            analysis_round=self.ledger.analysis_rounds,
            submission_number=number, steps=submission.steps,
            authored_by="opus")

        try:
            self.ledger.note_steps(len(submission.steps))
        except BudgetExceeded:
            raise

        step_results: list[K.StepResult] = []
        for step in submission.steps:
            rejection = self._validate(step)
            if rejection is None:
                self._advance(st.EXECUTING, f"running {step.step_id}") \
                    if self.machine.state == st.VALIDATING else None
                try:
                    result = sql_mod.execute(
                        step.code, self.session,
                        deadline_seconds=min(
                            self.ledger.limits.step_wall_seconds,
                            max(0.5, self.ledger.remaining_seconds)))
                except sql_mod.SqlRejected as e:
                    rejection = e
                else:
                    artifact = self.artifacts.add(K.Artifact(
                        artifact_id=f"art-{uuid.uuid4().hex[:8]}",
                        kind="table", domain_id=DOMAIN,
                        tenant_id=self.scope.tenant_id,
                        dataset_release_id=self.scope.dataset_release_id,
                        step_id=step.step_id, row_count=result.row_count,
                        byte_size=len(str(result.rows)),
                        columns=result.columns))
                    self.completed_steps.append(step.step_id)
                    step_results.append(K.StepResult(
                        step_id=step.step_id,
                        status=("empty" if result.row_count == 0
                                else "truncated" if result.truncated
                                else "success"),
                        executed_code=step.code, parameters=step.parameters,
                        columns=result.columns, row_count=result.row_count,
                        artifact_id=artifact.artifact_id, rows=result.rows,
                        truncated=result.truncated, warnings=result.warnings,
                        elapsed_seconds=result.elapsed_seconds))
                    continue

            # ---- failure: hand the facts back, author nothing ---------
            return self._failed_step(conversation, submission, step, rejection)

        # ---- results -> review ---------------------------------------
        packet = K.ExecutionResultPacket(
            request_id=self.request_id, plan_id=submission.plan_id,
            submission_id=submission.submission_id,
            submission_number=submission.submission_number,
            analysis_round=submission.analysis_round,
            dataset_release_id=self.scope.dataset_release_id,
            status=("empty" if all(s.status == "empty" for s in step_results)
                    else "partial" if any(s.status == "truncated"
                                          for s in step_results)
                    else "complete"),
            steps=step_results, budget=self.ledger.budget_view(),
            note=("A zero-row step means nothing matched the filters. It is "
                  "not a failure and it is not proof that the quantity is "
                  "zero."))
        self.results.append(packet)

        self._advance(st.REVIEWING, "reviewing the results")
        decision = opus_mod.review(conversation, packet, plan=self.plan,
                                   analysis_round=self.ledger.analysis_rounds)

        if decision.decision == K.ANSWER and decision.answer is not None:
            self._advance(st.ANSWERING, "preparing the answer")
            return self._answer(decision.answer, partial=False)

        if decision.decision == K.NEEDS_CLARIFICATION:
            return self._clarify(decision.clarification_question,
                                 decision.clarification_options)

        if decision.decision == K.REVISE_ANALYSIS:
            if self.ledger.rounds_remaining <= 0:
                return self._round_limited(decision)
            self._advance(st.PLANNING, "revising the analysis")
            self.ledger.note_analysis_round()
            self.plan = decision.revised_plan or self.plan
            return decision.revised_submission

        # INSUFFICIENT_DATA, SYSTEM_ERROR, BUDGET_LIMITED
        if decision.answer is not None:
            self._advance(st.ANSWERING, "preparing a partial answer")
            return self._answer(decision.answer, partial=True)
        return self._insufficient(
            "", decision.gap_addressed
            or "The results do not support an answer to the question as asked.")

    def _validate(self, step: K.ExecutionStep) -> sql_mod.SqlRejected | None:
        if step.language != K.SQL:
            return sql_mod.SqlRejected(
                K.SANDBOX_UNAVAILABLE,
                "Isolated Python execution is not enabled in this runtime, so "
                "only SQL steps can be run. This is a capability limitation, "
                "reported rather than downgraded to unsafe in-process "
                "execution.")
        try:
            sql_mod.check_structure(step.code)
            sql_mod.bind(step.code, self.session)
        except sql_mod.SqlRejected as e:
            return e
        return None

    def _failed_step(self, conversation, submission, step, rejection):
        """Build the factual packet, return it to Opus, and take what Opus
        writes. CreditProbe writes nothing."""
        packet = failure_mod.build(
            error=rejection, step=step, submission=submission,
            session=self.session, ledger=self.ledger,
            plan_id=submission.plan_id, request_id=self.request_id,
            completed_steps=list(self.completed_steps),
            reusable_artifacts=list(self.artifacts.artifacts),
            previous_attempts=list(self.attempts),
            phase=("validation" if self.machine.state == st.VALIDATING
                   else "execution"))
        self.failures.append(packet)
        self.attempts.append(failure_mod.summarize_attempt(step, rejection))

        if not packet.repairable:
            return self._failed(
                f"That request cannot be answered from the Cockpit: "
                f"{rejection}",
                reason=rejection.category)

        if self.ledger.submissions_remaining <= 0:
            return self._submissions_exhausted(conversation)

        stopped = self.ledger.may_continue()
        if stopped:
            raise BudgetExceeded(stopped, self.ledger._stop_message(stopped))

        # Back to PLANNING: only Opus may author the next candidate.
        self._advance(st.PLANNING, "returning the failure to the analyst")
        response = opus_mod.repair(conversation, packet, plan=self.plan,
                                   analysis_round=self.ledger.analysis_rounds)
        self.plan = response["plan"] or self.plan

        if response["action"] == "ask_a_targeted_clarification":
            return self._clarify(response["clarification_question"],
                                 response["clarification_options"])
        if response["action"] == "explain_and_stop" or \
                response["submission"] is None:
            return self._failed(
                response["explanation"]
                or "The analysis could not be completed against this data.",
                reason=rejection.category)
        if response["action"] == "revise_the_analysis_plan":
            if self.ledger.rounds_remaining > 0:
                self.ledger.note_analysis_round()
        return response["submission"]

    # -- terminal outcomes ----------------------------------------------

    def _not_ours(self, question, cleaned, normalized) -> Outcome:
        """A referral or a functionality clarification. Zero execution."""
        decision = self.decision
        assert decision is not None
        if decision.decision == K.REDIRECT:
            envelope = K.AnswerEnvelope(
                kind="referral",
                narrative=decision.public_explanation or decision.referral_reason,
                complete=True,
                referral={
                    "destination": decision.referral_destination,
                    "reason": decision.referral_reason,
                    "route": decision.referral_route or None,
                    "enabled": decision.referral_enabled,
                    "navigation_available": bool(decision.referral_route),
                },
                alternatives=decision.alternatives,
                limitations=([decision.mixed_scope_explanation]
                             if decision.mixed_scope else []))
            return self._finish(st.REDIRECTED, envelope)

        if decision.decision == K.UNSUPPORTED_REQUEST:
            return self._finish(st.UNSUPPORTED, K.AnswerEnvelope(
                kind="stop",
                narrative=decision.public_explanation
                or "No part of CreditProbe owns this request.",
                complete=False, stop_reason="unsupported",
                alternatives=decision.alternatives))

        return self._finish(st.CLARIFICATION_REQUIRED, K.AnswerEnvelope(
            kind="clarification",
            narrative=decision.public_explanation
            or decision.clarification_question,
            complete=False,
            clarification_question=decision.clarification_question,
            clarification_options=list(decision.clarification_options),
            alternatives=decision.alternatives))

    def _answer(self, envelope: K.AnswerEnvelope, *, partial: bool) -> Outcome:
        envelope = self._bind_figures(envelope)
        charts = self.ledger.limits.max_charts
        if len(envelope.charts) > charts:
            envelope.charts = envelope.charts[:charts]
            envelope.limitations.append(
                f"{charts} charts is the limit in {self.ledger.mode} mode; the "
                f"most relevant were kept.")
        if partial:
            envelope.complete = False
        return self._finish(st.PARTIAL if partial else st.COMPLETED, envelope)

    def _bind_figures(self, envelope: K.AnswerEnvelope) -> K.AnswerEnvelope:
        """Check the claimed evidence references exist. Section 7.9.

        Structural validation only, and this module does not pretend
        otherwise: that a fact id exists does not make the sentence containing
        it true. What it does catch is a citation to nothing.
        """
        known = {r.artifact_id for packet in self.results
                 for r in packet.steps if r.artifact_id}
        unknown = [f for f in envelope.fact_ids if f not in known]
        if unknown:
            envelope.fact_ids = [f for f in envelope.fact_ids if f in known]
            envelope.limitations.append(
                f"{len(unknown)} evidence reference(s) in this answer did not "
                f"match a result produced for this request and were removed.")
        return envelope

    def _clarify(self, question: str, options: list[str]) -> Outcome:
        return self._finish(st.CLARIFICATION_REQUIRED, K.AnswerEnvelope(
            kind="clarification",
            narrative=question or "A clarification is needed to continue.",
            complete=False, clarification_question=question,
            clarification_options=list(options or [])))

    def _insufficient(self, question: str, why: str) -> Outcome:
        return self._finish(st.INSUFFICIENT_DATA, _stop_envelope(
            reason="insufficient_data", narrative=why,
            understood=question,
            tried=[a["what_failed"] for a in self.attempts],
            help_text=("Naming the exact measure, period or cohort you want "
                       "would let the analysis be narrowed to what this data "
                       "supports.")))

    def _failed(self, why: str, *, reason: str) -> Outcome:
        return self._finish(st.EXECUTION_FAILED, _stop_envelope(
            reason=reason, narrative=why,
            tried=[a["what_failed"] for a in self.attempts]))

    def _round_limited(self, decision) -> Outcome:
        """Three rounds used and the evidence still insufficient. Section 14."""
        gaps = [s.gap for s in decision.per_subquestion if s.gap]
        if decision.answer is not None:
            return self._answer(decision.answer, partial=True)
        return self._finish(st.PARTIAL, _stop_envelope(
            reason=STOP_ROUNDS,
            narrative=(
                f"After {self.ledger.limits.analysis_rounds} analysis rounds "
                f"the evidence still does not settle the question as asked, so "
                f"the analysis stopped rather than inventing the remainder."),
            tried=[a["what_failed"] for a in self.attempts] or
                  [s.subquestion for s in decision.per_subquestion],
            limitations=gaps,
            help_text=(decision.clarification_question
                       or "Narrowing the question to one measure and one "
                          "period would let the remaining gap be closed.")))

    def _submissions_exhausted(self, conversation) -> Outcome:
        """Five submissions used. Section 8.3: reserve a bounded explanation if
        it is affordable, and a factual server envelope if it is not."""
        tried = [a["what_failed"] for a in self.attempts]
        narrative = (
            f"The analysis could not be executed within the "
            f"{self.ledger.limits.execution_submissions} attempts allowed for "
            f"one question. Each attempt failed for a reason recorded below, "
            f"and no further attempt is permitted.")
        return self._finish(st.EXECUTION_FAILED, _stop_envelope(
            reason=STOP_SUBMISSIONS, narrative=narrative, tried=tried,
            help_text=("Naming the exact fields, period or cohort you need "
                       "would let the query be written against data that is "
                       "definitely present. You are not being asked to fix "
                       "SQL: the failures above are the application's to "
                       "resolve.")))

    def _budget_stop(self, error: BudgetExceeded, question: str) -> Outcome:
        status = {
            STOP_DEADLINE: st.TIMED_OUT,
            STOP_CANCELLED: st.CANCELLED,
            STOP_SUBMISSIONS: st.EXECUTION_FAILED,
            STOP_ROUNDS: st.PARTIAL,
            STOP_NO_PROGRESS: st.INSUFFICIENT_DATA,
        }.get(error.reason, st.BUDGET_EXCEEDED)
        return self._finish(status, _stop_envelope(
            reason=error.reason, narrative=str(error), understood=question,
            tried=[a["what_failed"] for a in self.attempts],
            help_text=(
                "A new question starts a new budget. This one stopped where "
                "it did and its attempts are preserved so the next does not "
                "repeat them.")))

    def _finish(self, status: str, envelope: K.AnswerEnvelope) -> Outcome:
        if not self.machine.finished:
            if self.machine.may(status):
                self.machine.advance(status, "finished")
            elif self.machine.may(st.SUMMARIZING):
                self.machine.advance(st.SUMMARIZING, "finishing")
                self.machine.advance(status, "finished")
        envelope.status = status
        exchange = K.Exchange(
            exchange_id=self.request_id,
            question=(self.context_packet.payload["A_request"]
                      ["original_question"] if self.context_packet else ""),
            answer=envelope.narrative,
            kind=("referral" if status == st.REDIRECTED
                  else "clarification" if status == st.CLARIFICATION_REQUIRED
                  else "answer" if status == st.COMPLETED
                  else "stop"),
            fact_ids=list(envelope.fact_ids),
            dataset_release_id=self.scope.dataset_release_id)
        return Outcome(
            request_id=self.request_id, status=status, envelope=envelope,
            decision=self.decision, plan=self.plan, results=self.results,
            failures=self.failures, budget=self.ledger.to_dict(),
            machine={**self.machine.to_dict(), "progress": self.progress},
            context=(self.context_packet.to_dict() if self.context_packet
                     else {}),
            exchange=exchange)


__all__ = ["Outcome", "Runtime"]
