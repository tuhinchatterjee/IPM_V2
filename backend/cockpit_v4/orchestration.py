"""
The one analyst loop. A messenger with a ledger, not a second brain.

What this module does: assemble authorized context, dispatch one generation,
validate the action it asked for, run it, persist what happened, put the
result back, and repeat until the analyst finalizes or a bound stops it.

What this module must never do, and has no code for:
  * repair a query, a plan, a field reference or an answer;
  * compute a business number when execution failed;
  * fall back to V3, to a canned decomposition, or to another model;
  * claim an answer was delivered because it was generated.

Every loop back to `CONTEXT_READY` passes through a ledger call that consumes
something finite. There is no `continue` in this file that does not.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from datetime import datetime, timedelta, timezone

from backend.cockpit_v4 import DEEP, events as ev
from backend.cockpit_v4 import config as config_mod
from backend.cockpit_v4 import contracts as contracts_mod
from backend.cockpit_v4 import states as st
from backend.cockpit_v4.artifacts import ArtifactService
from backend.cockpit_v4.budgets import BudgetExceeded, Ledger
from backend.cockpit_v4.catalog_tool import CatalogService
from backend.cockpit_v4.contracts import (BATCHABLE, MAX_BATCHED_READS,
                                          Rejection, TOOL_EXECUTE,
                                          TOOL_FINALIZE, TOOL_INSPECT,
                                          TOOL_NAMES, TOOL_READ,
                                          parse_artifact, parse_catalog,
                                          parse_execution, parse_final,
                                          parse_intent,
                                          parse_product_knowledge,
                                          TOOL_PRODUCT, units_display)
from backend.cockpit_v4.execute_tool import (ExecutionService,
                                             no_progress_key)
from backend.cockpit_v4.finalization import Finalizer
from backend.cockpit_v4.provider import (Analyst, InputTooLarge,
                                         OutputTruncated, ProviderFailure)
from backend.cockpit_v4.run_store import (LeaseLost, StorageUnavailable,
                                          TerminalAlready)


class Cancelled(RuntimeError):
    """The user cancelled. Wins the race with a terminal answer atomically."""


@dataclass
class Outcome:
    state: str
    error_code: str = ""
    error_id: str = ""
    response: dict[str, Any] | None = None
    message: str = ""


#: Which disposition settles into which terminal state.
_DISPOSITION_STATE = {
    "answer": st.COMPLETED, "partial_answer": st.PARTIAL,
    "clarification": st.WAITING_FOR_USER, "referral": st.REFERRED,
    "unsupported": st.UNSUPPORTED, "safe_failure": st.FAILED,
}


@dataclass
class Orchestrator:
    """One run, start to terminal state."""

    run: Any
    store: Any
    ledger: Ledger
    analyst: Analyst
    catalog_service: CatalogService
    execution_service: ExecutionService
    artifact_service: ArtifactService
    finalizer: Finalizer
    emitter: ev.Emitter
    catalog: Any
    cancel_check: Any = None
    #: The full tool set, held back from the FIRST generation only. Set by
    #: the worker when `product_knowledge.coverage` says the synopsis
    #: already covers the question; restored before the second action so a
    #: misjudged question is never left without the tool it needs.
    deferred_tools: list[dict[str, Any]] | None = None
    #: The attention item this conversation was opened from, if any.
    investigation: dict[str, Any] | None = None
    #: Set once the analyst has been told to correct only its answer.
    answer_only: bool = False
    executed: bool = False
    #: Product-knowledge reads are cheap and bounded separately from the
    #: catalog: they touch no borrower data and open no analysis round.
    product_calls: int = 0
    intent: Any = None
    #: Set once the analytical allowance has been adopted, so it happens
    #: exactly once however many times the intent is re-declared.
    _analytical: bool = False
    #: The first analytical failure in this run, kept so a later deadline or
    #: cost stop cannot bury it.
    first_failure: dict[str, Any] | None = None
    _version: int = 0

    # -- helpers ---------------------------------------------------------

    def _cancelled(self) -> bool:
        if callable(self.cancel_check) and self.cancel_check():
            return True
        record = self.store.get_run(self.run.run_id)
        return bool(record and record.cancel_requested)

    def _guard(self) -> None:
        if self._cancelled():
            raise Cancelled("cancelled by the user")
        self.ledger.check_deadline()

    def _advance(self, state: str, *, operation: str = "") -> None:
        record = self.store.update_state(
            self.run.run_id, expect_version=self._version, state=state,
            operation=operation, budget=self.ledger.snapshot())
        self._version = record.version

    def _detail(self, body: dict[str, Any]) -> str:
        """Operator-only record. Redacted before it is written."""
        return self.store.put_detail(self.run.run_id, _redact(body))

    # -- the run ---------------------------------------------------------

    def run_to_completion(self) -> Outcome:
        try:
            return self._loop()
        except Cancelled:
            self.ledger.cancel()
            self.emitter.append(
                ev.RUN_CANCELLED, stage="publishing", operation="cancel",
                status=ev.STATUS_OK,
                public_message="Cancelled at your request.")
            return Outcome(st.CANCELLED, error_code=st.CANCELLED_BY_USER)
        except BudgetExceeded as exc:
            return self._stop(exc.code, str(exc))
        except InputTooLarge as exc:
            return self._stop(exc.code, str(exc))
        except OutputTruncated as exc:
            return self._stop(exc.code, str(exc))
        except ProviderFailure as exc:
            return self._stop(exc.code, str(exc))
        except (StorageUnavailable, LeaseLost, TerminalAlready) as exc:
            # No further paid or executable operation is launched when the
            # store cannot commit or this worker has been fenced.
            return Outcome(
                st.INTERRUPTED if isinstance(exc, (LeaseLost, TerminalAlready))
                else st.FAILED,
                error_code=(st.WORKER_LOST
                            if isinstance(exc, (LeaseLost, TerminalAlready))
                            else st.STORAGE_UNAVAILABLE),
                message=str(exc))
        except Exception as exc:  # noqa: BLE001
            # An application defect. Recorded under an error id that is
            # PERSISTED (V3's was only ever written to a log line), with the
            # operation it failed in, and never blamed on the provider.
            error_id = f"err-{uuid.uuid4().hex[:12]}"
            detail_ref = ""
            try:
                detail_ref = self._detail({
                    "exception_type": type(exc).__name__,
                    "message": str(exc)[:500],
                    "operation": getattr(self.run, "operation", ""),
                })
            except Exception:  # noqa: BLE001
                pass
            self.emitter.append(
                ev.RUN_FAILED, stage="publishing", operation="internal",
                status=ev.STATUS_FAILED, error_id=error_id,
                detail_ref=detail_ref,
                public_message=("Something inside CreditProbe failed while "
                                "handling this request. Nothing was answered "
                                "from a substitute."))
            return Outcome(st.FAILED, error_code=st.INTERNAL_ERROR,
                           error_id=error_id, message=str(exc)[:300])

    def _stop(self, code: str, message: str) -> Outcome:
        """A mechanical stop, generated from the error record.

        Never a fabricated analytical answer: when no model call remains
        affordable, CreditProbe states the reason and stops.

        The terminal code is the bound that ran out, but it is rarely the
        interesting fact. A run that hit a binder failure, retried, and then
        ran out of time stops as DEADLINE_EXPIRED -- and "what went wrong
        first" is the binder failure. Both are reported.
        """
        self.ledger.cancel()
        if self.first_failure:
            message = (f"{message} The first analytical failure in this run "
                       f"was: {self.first_failure['summary']}")
        state = st.EXPIRED if code == st.DEADLINE_EXPIRED else st.FAILED
        if self.executed and code in (st.DEADLINE_EXPIRED, st.COST_LIMIT,
                                      st.CALL_LIMIT, st.EXECUTION_LIMIT,
                                      st.ROUND_LIMIT):
            # Verified partial evidence exists; it is preserved and labelled.
            state = st.PARTIAL
        self.emitter.append(
            ev.RUN_EXPIRED if state == st.EXPIRED else ev.RUN_FAILED,
            stage="publishing", operation=code.lower(),
            status=ev.STATUS_FAILED, public_message=message,
            detail_ref=(self._detail({"terminal_code": code,
                                      "first_analytical_failure":
                                      self.first_failure})
                        if self.first_failure else ""))
        return Outcome(state, error_code=code, message=message)

    def _loop(self) -> Outcome:
        self.emitter.append(
            ev.RUN_STARTED, stage="accepted", operation="start",
            status=ev.STATUS_OK,
            public_message="Working on your question.")
        self.emitter.append(
            ev.CONTEXT_READY, stage="accepted", operation="context",
            status=ev.STATUS_OK,
            public_message="Authorized context assembled.")
        if self.investigation:
            # A real step, so it appears in the trace. Seeding is a context
            # load, not a hidden model action, and the panel says which.
            self.emitter.append(
                ev.CONTEXT_READY, stage="accepted",
                operation="investigation_context", status=ev.STATUS_OK,
                public_message=(
                    "Investigation context loaded · "
                    f"{self.investigation.get('segment', '')} · "
                    f"{self.investigation.get('reporting_quarter', '')}"
                    ).strip(" ·"))

        while True:
            self._guard()
            self._advance(st.MODEL_RUNNING, operation="generation")
            turn = self._generate()
            if turn is None:
                continue  # a bounded recovery consumed its allowance

            self._advance(st.ACTION_VALIDATING, operation="action")
            outcome = self._handle_turn(turn)
            if outcome is not None:
                return outcome

    # -- generation ------------------------------------------------------

    def _generate(self):
        reserved = self.ledger.limits.reserved_output_tokens
        if (self.deferred_tools is not None
                and self.ledger.counters.generation_attempts >= 1):
            # Second action onwards: the full tool set, whatever the first
            # action was. Withholding is a first-action economy, never a
            # capability the run can lose.
            self.analyst.tools = self.deferred_tools
            self.deferred_tools = None
            self.emitter.append(
                ev.CONTEXT_READY, stage="understanding",
                operation="tools_restored", status=ev.STATUS_OK,
                public_message="Product knowledge lookup available.")
        self.emitter.append(
            ev.MODEL_REQUESTED, stage="understanding", operation="generate",
            status=ev.STATUS_STARTED,
            attempt=self.ledger.counters.generation_attempts + 1,
            public_message=("Understanding the request"
                            if not self.analyst.messages[1:]
                            else "Preparing the next action"))
        try:
            turn = self.analyst.ask(purpose="analyst_action",
                                    max_output_tokens=reserved)
        except OutputTruncated as exc:
            # One structure regeneration, and the incomplete turn is not in
            # history. Nothing from a truncated response executes.
            self.ledger.spend_format_recovery()
            self.analyst.rollback_last_turn()
            self.emitter.append(
                ev.RETRY_REQUESTED, stage="understanding",
                operation="output_truncated", status=ev.STATUS_REJECTED,
                public_message=("The response was cut off before it was "
                                "complete; asking again once."))
            self.analyst.user(
                f"Your previous response was cut off at its "
                f"{exc.limit:,}-token output allowance and nothing from it "
                f"ran. Send one complete tool call. Keep it compact; do not "
                f"shorten the analysis itself.")
            return None
        except ProviderFailure as exc:
            if exc.retry_class == "transport":
                self.ledger.spend_transport_retry()
                self.emitter.append(
                    ev.RETRY_REQUESTED, stage="understanding",
                    operation="transport", status=ev.STATUS_REJECTED,
                    public_message="The request did not complete; retrying "
                                   "once.")
                return None
            raise

        self.emitter.append(
            ev.MODEL_RESPONSE_RECEIVED, stage="understanding",
            operation="generate", status=ev.STATUS_OK,
            attempt=self.ledger.counters.generation_attempts,
            detail_ref=self._detail({
                "model": turn.model, "request_id": turn.request_id,
                "stop_reason": turn.stop_reason,
                "counted_input_tokens": turn.counted_input_tokens,
                "count_method": turn.count_method,
                "reported_input_tokens": turn.input_tokens,
                "output_tokens": turn.output_tokens,
                "cache_read_tokens": turn.cache_read_tokens,
                "cache_write_tokens": turn.cache_write_tokens,
                "duration_ms": turn.duration_ms}),
            public_message="Response received.")
        self.store.save_messages(self.run.run_id, self.analyst.messages)
        return turn

    # -- action handling -------------------------------------------------

    def _handle_turn(self, turn) -> Outcome | None:
        calls = turn.tool_calls
        if not calls:
            # Free prose is not silently promoted into a validated answer.
            self.ledger.spend_format_recovery()
            self.analyst.user(
                "That response contained no tool call. Every action, "
                "including the final answer, is taken through one of: "
                + ", ".join(TOOL_NAMES) + ".")
            return None

        unknown = [c.name for c in calls if c.name not in TOOL_NAMES]
        if unknown:
            return self._reject_batch(
                calls, f"unknown tool(s) {unknown}; the available tools are "
                       f"{list(TOOL_NAMES)}.")

        names = {c.name for c in calls}
        if len(calls) > 1:
            if not names <= BATCHABLE:
                # Mixed execution/finalization batches are refused WITHOUT
                # side effects: there is no defined order and no safe partial
                # outcome for "run this query and also publish the answer".
                return self._reject_batch(
                    calls,
                    "only metadata and artifact reads may be batched. An "
                    "execution or a final response is one action per "
                    "response, and this batch had no side effects.")
            if len(calls) > MAX_BATCHED_READS:
                return self._reject_batch(
                    calls, f"at most {MAX_BATCHED_READS} reads may be "
                           f"batched; {len(calls)} were requested.")

        self.emitter.append(
            ev.MODEL_PARSED, stage="understanding", operation="parse",
            status=ev.STATUS_OK,
            public_message=f"Next action: {', '.join(sorted(names))}.")

        for call in calls:
            outcome = self._handle_call(call)
            if outcome is not None:
                return outcome
        return None

    def _reject_batch(self, calls, message: str) -> None:
        """Answer every call with a matching error. No side effects."""
        self.ledger.spend_format_recovery()
        for call in calls:
            self.analyst.tool_result(
                call.id, {"status": "rejected",
                          "error_code": st.INVALID_MODEL_OUTPUT,
                          "message": message}, is_error=True)
        self.emitter.append(
            ev.TOOL_FAILED, stage="understanding", operation="batch",
            status=ev.STATUS_REJECTED, public_message=message)
        return None

    def _handle_call(self, call) -> Outcome | None:
        self.emitter.append(
            ev.TOOL_REQUESTED, stage=_stage_for(call.name),
            operation=call.name, status=ev.STATUS_STARTED,
            public_message=_public_for(call.name))

        if self.answer_only and call.name != TOOL_FINALIZE:
            self._tool_error(
                call, st.ANSWER_VALIDATION,
                "This run is in answer-correction mode: only "
                "finalize_response is available and no new analysis can be "
                "started.")
            return None

        try:
            if call.name == TOOL_INSPECT:
                return self._do_catalog(call)
            if call.name == TOOL_PRODUCT:
                return self._do_product_knowledge(call)
            if call.name == TOOL_READ:
                return self._do_artifact(call)
            if call.name == TOOL_EXECUTE:
                return self._do_execute(call)
            return self._do_finalize(call)
        except Rejection as exc:
            self._tool_error(call, exc.code, exc.message,
                             field_path=exc.field_path, detail=exc.detail)
            return None

    def _tool_error(self, call, code: str, message: str, *,
                    field_path: str = "",
                    detail: dict[str, Any] | None = None) -> None:
        body = {"status": "rejected", "error_code": code, "message": message}
        if field_path:
            body["field"] = field_path
        if detail:
            body["detail"] = detail
        body["budgets_remaining"] = self.ledger.snapshot()
        self.analyst.tool_result(call.id, body, is_error=True)
        self.emitter.append(
            ev.TOOL_FAILED, stage=_stage_for(call.name), operation=call.name,
            status=ev.STATUS_REJECTED, public_message=message[:300],
            detail_ref=self._detail({"tool": call.name, "code": code,
                                     "field": field_path,
                                     "message": message}))

    # -- inspect_catalog -------------------------------------------------

    def _do_catalog(self, call) -> None:
        request = parse_catalog(call.arguments)
        self._record_intent(request.intent)
        self.ledger.spend_catalog_call()
        self._advance(st.TOOL_RUNNING, operation=TOOL_INSPECT)
        result = self.catalog_service.inspect(request)
        result["budgets_remaining"] = self.ledger.snapshot()
        self.analyst.tool_result(call.id, result)
        self.emitter.append(
            ev.TOOL_COMPLETED, stage="catalog", operation=TOOL_INSPECT,
            status=ev.STATUS_OK,
            public_message=(
                f"Read {len(result.get('fields') or [])} field definition(s)"
                + (f" across {len(result.get('discovery') or [])} relation(s)"
                   if result.get("discovery") else "") + "."),
            detail_ref=self._detail({
                "requested_fields": list(request.field_ids),
                "requested_relations": list(request.relation_ids),
                "detail": list(request.detail),
                "receipt": result.get("metadata_receipt_id")}))
        return None

    # -- inspect_product_knowledge ---------------------------------------

    def _do_product_knowledge(self, call) -> None:
        """Return product facts. Available in every mode.

        Reading what the product is is not analysis, so this does not require
        a declared data analysis and does not consume the catalog budget: a
        product-help question must be able to reach it without pretending to
        be something it is not.
        """
        from backend.cockpit_v4 import product_knowledge as pk

        request = parse_product_knowledge(call.arguments)
        self._record_intent(request.intent)
        self.ledger.check_deadline()
        self.product_calls += 1
        if self.product_calls > MAX_PRODUCT_CALLS:
            self._tool_error(
                call, st.CALL_LIMIT,
                f"All {MAX_PRODUCT_CALLS} product-knowledge reads for this "
                f"run were used. Answer from what you already have, or say "
                f"what you could not establish.")
            return None
        self._advance(st.TOOL_RUNNING, operation=TOOL_PRODUCT)
        result = pk.retrieve(query=request.query, topics=request.topics,
                             detail=request.detail)
        result["budgets_remaining"] = self.ledger.snapshot()
        self.analyst.tool_result(call.id, result)
        self.emitter.append(
            ev.TOOL_COMPLETED, stage="product_knowledge",
            operation=TOOL_PRODUCT, status=ev.STATUS_OK,
            public_message=(
                f"Read product knowledge: "
                f"{', '.join(result['topics_returned'])}."),
            detail_ref=self._detail({
                "query": request.query, "topics": list(request.topics),
                "detail": request.detail,
                "pack_version": result["pack_version"],
                "sections": [s.get("title") for s in result["sections"]]}))
        return None

    # -- read_artifact ---------------------------------------------------

    def _do_artifact(self, call) -> None:
        request = parse_artifact(call.arguments)
        self._record_intent(request.intent)
        self.ledger.spend_artifact_read()
        self._advance(st.TOOL_RUNNING, operation=TOOL_READ)
        result = self.artifact_service.read(request)
        result["budgets_remaining"] = self.ledger.snapshot()
        self.analyst.tool_result(call.id, result)
        self.emitter.append(
            ev.TOOL_COMPLETED, stage="reviewing", operation=TOOL_READ,
            status=ev.STATUS_OK,
            public_message=(
                f"Read {result.get('returned_rows', 0)} row(s) from stored "
                f"evidence." if result.get("status") == "ok"
                else "That reference is not available."))
        return None

    # -- execute_analysis ------------------------------------------------

    def _do_execute(self, call) -> None:
        # Counted BEFORE validation. A fully received execute_analysis
        # request cost a generation and a validation pass whether or not it
        # was well formed; free invalid submissions are an unbounded loop.
        ordinal = self.ledger.spend_submission()
        submission = parse_execution(
            call.arguments, max_steps=self.ledger.limits.steps_per_batch)
        self._record_intent(submission.intent)

        try:
            bind_report = self.execution_service.validate_batch(submission)
        except Rejection as rejection:
            # A submission refused at the binder is still a numbered
            # submission, and its exact SQL is still on file. "Which query, on
            # which attempt" has to be answerable for the one that never ran,
            # not only for the ones that did.
            submission_id = self.store.record_submission(
                run_id=self.run.run_id, ordinal=ordinal, round=0,
                payload=submission.to_dict(), status="rejected",
                no_progress_key="")
            detail = dict(rejection.detail or {})
            self._remember_failure(
                stage="validating", code=rejection.code,
                summary=(f"submission {ordinal} did not bind — "
                         f"{rejection.message}"
                         if detail.get("phase") == "bind"
                         else f"submission {ordinal} was refused — "
                              f"{rejection.message}"),
                detail={"submission": ordinal, **detail})
            self.emitter.append(
                ev.TOOL_FAILED, stage="validating", operation=TOOL_EXECUTE,
                status=ev.STATUS_REJECTED, submission=ordinal,
                public_message=(
                    "The query did not bind and was not run."
                    if detail.get("phase") == "bind"
                    else "The submission was refused before anything ran."),
                detail_ref=self._detail({
                    "submission_id": submission_id, "submission": ordinal,
                    "stage": "validating",
                    "error_code": rejection.code,
                    "field": rejection.field_path,
                    "message": rejection.message,
                    "steps": [{"step_id": s.step_id, "language": s.language,
                               "code": s.code, "parameters": s.parameters}
                              for s in submission.steps],
                    **detail}))
            raise
        self.ledger.spend_steps(len(submission.steps))
        key = no_progress_key(submission,
                              release_id=self.run.release_id)
        try:
            self.ledger.no_progress_check(key)
        except BudgetExceeded as exc:
            # NO_PROGRESS is a refusal of THIS submission, not the end of the
            # run: the slot is already spent, and the analyst may still write
            # different code or finalize a supported partial answer. Ending
            # the run here would throw away work that already succeeded.
            raise Rejection(exc.code, str(exc), field_path="steps",
                            detail={"budgets_remaining":
                                    self.ledger.snapshot()}) from exc
        round_no = self.ledger.open_round()

        submission_id = self.store.record_submission(
            run_id=self.run.run_id, ordinal=ordinal, round=round_no,
            payload=submission.to_dict(), status="running",
            no_progress_key=key)

        proven = len(bind_report.get("bound_now", ()))
        deferred = list(bind_report.get("bound_at_run_time", ()))
        self.emitter.append(
            ev.TOOL_VALIDATED, stage="validating", operation=TOOL_EXECUTE,
            status=ev.STATUS_OK, submission=ordinal, round=round_no,
            public_message=(
                f"Query validated and bound: {len(submission.steps)} step(s), "
                f"{submission.expected_output_grain} grain, "
                f"{units_display(submission.expected_units)}."
                + (f" {len(deferred)} step(s) bind against earlier results "
                   f"and are proven as they run." if deferred else "")),
            detail_ref=self._detail({
                "objective": submission.objective,
                "submission_id": submission_id,
                "bind_proof": {"method": "DuckDB EXPLAIN, nothing executed",
                               "proven_before_execution": proven,
                               "proven_at_run_time": deferred},
                "steps": [{"step_id": s.step_id, "language": s.language,
                           "purpose": s.purpose, "code": s.code,
                           "parameters": s.parameters}
                          for s in submission.steps],
                "fields_required": list(submission.fields_required),
                "metadata_receipts": list(submission.metadata_receipt_ids)}))

        self._advance(st.TOOL_RUNNING, operation=TOOL_EXECUTE)

        def on_step(phase: str, step, result) -> None:
            if phase == "started":
                self.emitter.append(
                    ev.TOOL_STARTED, stage="executing", operation=step.step_id,
                    status=ev.STATUS_STARTED, submission=ordinal,
                    round=round_no,
                    public_message=f"Executing {step.purpose}")
            elif phase == "completed":
                self.emitter.append(
                    ev.TOOL_COMPLETED, stage="executing",
                    operation=step.step_id, status=ev.STATUS_OK,
                    submission=ordinal, round=round_no,
                    public_message=(f"{step.purpose}: {result.row_count} "
                                    f"row(s)."),
                    detail_ref=self._detail({
                        "step_id": step.step_id,
                        "executed_code_digest": result.code_digest,
                        "submitted_code": step.code,
                        "artifact_id": result.artifact_id,
                        "warnings": result.warnings}))
            elif phase == "failed":
                bound = result.phase != "bind"
                self._remember_failure(
                    stage="executing", code=result.error_code,
                    summary=(f"step {step.step_id} of submission {ordinal} "
                             + ("failed while running — "
                                if bound else "did not bind — ")
                             + result.message),
                    detail={"submission": ordinal, "step_id": step.step_id,
                            "phase": result.phase,
                            **dict(result.engine_detail or {})})
                self.emitter.append(
                    ev.TOOL_FAILED, stage="executing",
                    operation=step.step_id, status=ev.STATUS_FAILED,
                    submission=ordinal, round=round_no,
                    # A query that never bound did not run, and the trace
                    # must not imply that it did.
                    public_message=(
                        f"{step.purpose} failed while running."
                        if bound else
                        f"{step.purpose} did not bind and was not run."),
                    detail_ref=self._detail({
                        "step_id": step.step_id,
                        "phase": result.phase or "runtime",
                        "executed": bound,
                        "failed_check": result.failed_check,
                        "error_code": result.error_code,
                        "message": result.message,
                        "parameters": step.parameters,
                        "submitted_code": step.code,
                        "failed_code_digest": result.code_digest,
                        **dict(result.engine_detail or {})}))

        batch = self.execution_service.run_batch(
            submission, submission_id=submission_id,
            deadline_seconds=min(self.ledger.remaining_seconds,
                                 self.ledger.limits.step_seconds
                                 * len(submission.steps)),
            on_step=on_step)
        self.store.set_submission_status(submission_id, batch.status)

        for result in batch.steps:
            if result.artifact_id:
                self.finalizer.run_artifacts.add(result.artifact_id)
                self.executed = True

        if batch.status == "ok":
            # A completed batch closes the round; the NEXT batch opens a new
            # one. A repair stays inside the round it failed in.
            self.ledger.close_round()
        else:
            # Record the failure class so a genuine environment recovery can
            # retry while an identical deterministic failure cannot.
            failed = next((s for s in batch.steps if s.status == "failed"),
                          None)
            if failed is not None:
                self.store.record_submission(
                    run_id=self.run.run_id, ordinal=ordinal, round=round_no,
                    payload={"failed": failed.step_id}, status="failed",
                    no_progress_key=no_progress_key(
                        submission, release_id=self.run.release_id,
                        error_class=failed.error_code))

        body = batch.to_dict()
        body["budgets_remaining"] = self.ledger.snapshot()
        if batch.status != "ok":
            body["note"] = (
                "CreditProbe did not modify or repair anything. Author the "
                "corrected code yourself, or finalize a supported partial "
                "answer.")
        self.analyst.tool_result(call.id, body,
                                 is_error=batch.status != "ok")
        return None

    # -- finalize_response -----------------------------------------------

    def _do_finalize(self, call) -> Outcome | None:
        final = parse_final(call.arguments)
        self._record_intent(final.intent)
        self._advance(st.FINAL_VALIDATING, operation=TOOL_FINALIZE)

        report = self.finalizer.validate(final, executed=self.executed)
        if not report.ok:
            self.emitter.append(
                ev.ANSWER_VALIDATED, stage="publishing",
                operation="answer_check", status=ev.STATUS_REJECTED,
                public_message="The response did not pass its evidence check.",
                detail_ref=self._detail({"problems": report.problems}))
            try:
                self.ledger.spend_answer_correction()
            except BudgetExceeded:
                # A second invalid answer is an explicit failure, not another
                # loop and never a fabricated narrative.
                return Outcome(
                    st.FAILED, error_code=st.ANSWER_VALIDATION,
                    message=("The response could not be validated against "
                             "the executed evidence and the one correction "
                             "for this run was already used."))
            self.answer_only = True
            from backend.cockpit_v4.finalization import rejection
            self._tool_error(call, st.ANSWER_VALIDATION,
                             rejection(report).message)
            return None

        charts = self.finalizer.surviving_charts(final)
        suggestions = self.finalizer.validate_suggestions(final, self.catalog)

        published = final.to_dict()
        published["narrative"] = report.rendered_narrative
        published["charts"] = charts
        published["suggested_questions"] = suggestions
        published["validation"] = report.to_dict()
        published["evidence_bound"] = bool(final.numeric_claims)
        published["executed"] = self.executed

        self.emitter.append(
            ev.ANSWER_VALIDATED, stage="publishing",
            operation="answer_check", status=ev.STATUS_OK,
            public_message=(f"Answer checked against "
                            f"{len(final.numeric_claims)} evidence-bound "
                            f"value(s)."))

        # The accepted tool result goes into canonical history BEFORE the
        # answer is published, so a reused history has no dangling tool_use.
        self.analyst.tool_result(call.id, {
            "status": "accepted", "published": True,
            "warnings": report.warnings})
        self.store.save_messages(self.run.run_id, self.analyst.messages)

        state = _DISPOSITION_STATE.get(final.disposition, st.COMPLETED)
        return Outcome(state, response=published)

    # -- intent ----------------------------------------------------------

    def _remember_failure(self, *, stage: str, code: str, summary: str,
                          detail: dict[str, Any] | None = None) -> None:
        """The FIRST one only. Later failures are in the event log anyway."""
        if self.first_failure is None:
            self.first_failure = {"stage": stage, "error_code": code,
                                  "summary": summary,
                                  "detail": dict(detail or {})}

    def _adopt_analytical_limits(self, intent) -> None:
        """A declared analysis gets the analytical time and cost allowance.

        The mode is not knowable at intake -- the question arrives as text --
        so the run starts on the product-help allowance and widens here, once
        and only upward, when the analyst says what this turn is. A Product
        Help run therefore keeps the tight bound it should have.
        """
        if self._analytical or intent.query_mode != contracts_mod.DATA_ANALYSIS:
            return
        self._analytical = True
        report = self.ledger.adopt(
            config_mod.analytical_limits_for(self.ledger.limits.mode))
        if not report["changed"]:
            return
        try:
            self.store.extend_deadline(
                self.run.run_id,
                (datetime.now(timezone.utc) + timedelta(
                    seconds=self.ledger.limits.deadline_seconds)
                 ).isoformat(timespec="milliseconds"))
        except Exception:  # noqa: BLE001 - a stale watchdog is not fatal here
            pass
        after = report["after"]
        self.emitter.append(
            ev.CONTEXT_READY, stage="understanding", operation="budget",
            status=ev.STATUS_OK,
            public_message=(
                f"Analysis allowance: {after['deadline_seconds']:.0f}s, "
                f"${after['spend_ceiling_usd']:.2f}."),
            detail_ref=self._detail({"budget_adopted": report}))

    def _record_intent(self, intent) -> None:
        if self.intent is not None and intent.to_dict() == self.intent.to_dict():
            return
        self.intent = intent
        self._adopt_analytical_limits(intent)
        self.emitter.append(
            ev.INTENT_VALIDATED, stage="understanding", operation="intent",
            status=ev.STATUS_OK,
            public_message=(f"{_mode_label(intent.query_mode)} · owned by "
                            f"{intent.owner.replace('_', ' ').title()}"),
            detail_ref=self._detail(intent.to_dict()))
        # Resolutions are shown, not hidden and not treated as refusals. A
        # reader should be able to see that "exposure at default" was read as
        # EAD and that the period was resolved to the latest populated
        # quarter, without either one having stopped the analysis.
        for label, lines in (("Resolved", intent.canonical_mappings),
                             ("Assumed", intent.resolved_assumptions)):
            for line in lines:
                self.emitter.append(
                    ev.INTENT_VALIDATED, stage="understanding",
                    operation="semantics", status=ev.STATUS_OK,
                    public_message=f"{label}: {line}")
        for line in intent.blocking_ambiguities:
            self.emitter.append(
                ev.INTENT_VALIDATED, stage="understanding",
                operation="ambiguity", status=ev.STATUS_REJECTED,
                public_message=f"Needs a decision: {line}")


#: Product-knowledge reads a single run may make. Generous, because each is
#: a dictionary lookup, and bounded, because nothing is unbounded.
MAX_PRODUCT_CALLS = 4


def _stage_for(tool: str) -> str:
    return {TOOL_INSPECT: "catalog", TOOL_PRODUCT: "product_knowledge",
            TOOL_EXECUTE: "preparing", TOOL_READ: "reviewing",
            TOOL_FINALIZE: "publishing"}.get(tool, "understanding")


def _public_for(tool: str) -> str:
    return {TOOL_INSPECT: "Reading relevant data definitions",
            TOOL_PRODUCT: "Reading product knowledge",
            TOOL_EXECUTE: "Preparing query",
            TOOL_READ: "Reading stored evidence",
            TOOL_FINALIZE: "Validating and publishing answer"}.get(
                tool, "Working")


def _mode_label(mode: str) -> str:
    return {"PRODUCT_HELP": "About CreditProbe",
            "THEORY_CONCEPT": "Credit concept",
            "DATA_ANALYSIS": "Portfolio analysis",
            "OTHER_FUNCTIONALITY": "Another part of CreditProbe",
            "CLARIFICATION_REQUIRED": "Needs clarification",
            "UNSUPPORTED": "Not supported here"}.get(mode, mode)


_SECRET_HINTS = ("api_key", "apikey", "authorization", "cookie", "token",
                 "secret", "password", "credential")


def _redact(body: Any) -> Any:
    """Strip anything that looks like a secret before it is persisted.

    Operator diagnostics may name a model and a request id. They may never
    carry a key, a cookie, an authorization header or an environment dump --
    and this runs on the way IN, so a downloadable trace cannot leak one.
    """
    if isinstance(body, dict):
        out = {}
        for key, value in body.items():
            if any(hint in str(key).lower() for hint in _SECRET_HINTS):
                out[key] = "[redacted]"
            else:
                out[key] = _redact(value)
        return out
    if isinstance(body, list):
        return [_redact(v) for v in body]
    if isinstance(body, str) and len(body) > 20:
        lowered = body.lower()
        if lowered.startswith(("sk-", "bearer ")):
            return "[redacted]"
    return body


__all__ = ["Cancelled", "Orchestrator", "Outcome"]
