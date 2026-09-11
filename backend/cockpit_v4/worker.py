"""
The worker: claims a run, builds its services, drives it, settles it.

The lease is the point. A worker holds a lease with a fence number and
heartbeats every two seconds; the supervisor settles a run whose lease went
stale. A worker that comes back after being fenced cannot overwrite the
settled outcome, because every state write is a compare-and-swap on the run's
version and the store refuses a stale writer.

On worker loss the run becomes INTERRUPTED with its current operation and its
preserved artifacts. It is NOT replayed automatically: an uncertain paid
provider call or an executable batch may have already happened, and replaying
it spends money twice and can double-count an execution submission.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v4 import context as context_mod
from backend.cockpit_v4 import events as ev
from backend.cockpit_v4 import states as st
from backend.cockpit_v4.artifacts import ArtifactService
from backend.cockpit_v4.budgets import Ledger
from backend.cockpit_v4.catalog_tool import CatalogService
from backend.cockpit_v4.config import limits_for
from backend.cockpit_v4.contracts import TOOL_PRODUCT, provider_tools
from backend.cockpit_v4.execute_tool import ExecutionService
from backend.cockpit_v4.finalization import Finalizer
from backend.cockpit_v4.orchestration import Orchestrator, Outcome
from backend.cockpit_v4.provider import Analyst
from backend.cockpit_v4.run_store import LeaseLost, RunStore
from backend.cockpit_v4.service import PreflightFailed, Runtime

logger = logging.getLogger(__name__)


@dataclass
class Worker:
    """Executes runs from the durable outbox."""

    store: RunStore
    runtime: Runtime
    worker_id: str = field(default_factory=lambda: f"w-{uuid.uuid4().hex[:8]}")
    stop_event: threading.Event = field(default_factory=threading.Event)
    poll_seconds: float = 0.05

    def serve_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                record = self.store.claim_next(self.worker_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("V4 worker could not claim a run: %s", exc)
                record = None
            if record is None:
                self.stop_event.wait(self.poll_seconds)
                continue
            try:
                self.execute(record)
            except Exception:  # noqa: BLE001
                logger.exception("V4 worker failed on run %s", record.run_id)

    def stop(self) -> None:
        self.stop_event.set()

    # -- one run ---------------------------------------------------------

    def execute(self, record: Any) -> Outcome:
        started = time.monotonic()
        emitter = ev.Emitter(self.store, record.run_id,
                             started_monotonic=started)
        limits = limits_for(record.mode)
        ledger = Ledger(limits=limits, capability=self.runtime.capability,
                        store=self.store, run_id=record.run_id,
                        started_monotonic=started)

        beat = _Heartbeat(self.store, record.run_id, self.worker_id)
        beat.start()
        try:
            outcome = self._drive(record, emitter, ledger, limits)
        except PreflightFailed as exc:
            outcome = Outcome(st.FAILED, error_code=exc.code,
                              message=str(exc))
            emitter.append(ev.RUN_FAILED, stage="accepted",
                           operation="preflight", status=ev.STATUS_FAILED,
                           public_message=str(exc))
        finally:
            beat.stop()

        self._settle(record, outcome, emitter, ledger)
        return outcome

    def _drive(self, record: Any, emitter: ev.Emitter, ledger: Ledger,
               limits: Any) -> Outcome:
        principal = {"id": record.principal_id, "tenant": record.tenant_id}
        scope = self.runtime.scope_for(principal)

        session = None
        try:
            from backend.cockpit_agentic import sql as v3_sql

            session = v3_sql.open_session(scope=scope,
                                          catalog=self.runtime.catalog)
        except Exception as exc:  # noqa: BLE001
            # An unopenable session does not stop help or theory: those never
            # execute. It stops ANALYSIS, and the analyst is told so through
            # the tool rather than by a pre-emptive refusal of the question.
            logger.info("V4 SQL session unavailable for run %s: %s",
                        record.run_id, exc)

        seeded = self.store.thread_context(record.thread_id,
                                           tenant_id=record.tenant_id)
        packet = context_mod.build(
            question=record.question, principal=principal, scope=scope,
            catalog=self.runtime.catalog, limits=limits, mode=record.mode,
            release_summary=self.runtime.release_summary,
            ui_filters=record.ui_filters,
            recent_turns=self.store.recent_turns(
                record.thread_id, context_mod.DEFAULT_RECENT_TURNS),
            summary=self.store.get_summary(record.thread_id),
            capability=self.runtime.capability,
            investigation=(seeded or {}).get("body") if seeded else None)

        # One-generation broad Product Help. When the question names no
        # product detail beyond the synopsis the packet already carries,
        # `inspect_product_knowledge` is not offered on the FIRST action —
        # the live run that cost two generations and 28s spent the first one
        # retrieving what was already in front of it. The full set is
        # restored for every action after the first, so a misjudged question
        # costs nothing that it does not cost today.
        from backend.cockpit_v4 import product_knowledge as pk

        verdict = pk.coverage(record.question)
        withhold = ((TOOL_PRODUCT,)
                    if verdict["level"] == pk.COVERAGE_SYNOPSIS else ())
        full_tools = provider_tools()
        analyst = Analyst(
            provider=self.runtime.provider,
            capability=self.runtime.capability, ledger=ledger,
            system=packet.system_blocks,
            tools=provider_tools(withhold=withhold))
        analyst.user(packet.first_user_message)

        from backend.cockpit_v4 import pyrunner

        orchestrator = Orchestrator(
            run=record, store=self.store, ledger=ledger, analyst=analyst,
            catalog_service=CatalogService(
                catalog=self.runtime.catalog, scope=scope,
                coverage=self.runtime.coverage, session=session),
            execution_service=ExecutionService(
                session=session, scope=scope, catalog=self.runtime.catalog,
                store=self.store, run_id=record.run_id,
                tenant_id=record.tenant_id, release_id=record.release_id,
                limits=limits, python_runner=pyrunner.PythonRunner()),
            artifact_service=ArtifactService(
                store=self.store, tenant_id=record.tenant_id,
                release_id=record.release_id, limits=limits),
            finalizer=Finalizer(
                store=self.store, tenant_id=record.tenant_id,
                release_id=record.release_id, limits=limits),
            emitter=emitter, catalog=self.runtime.catalog,
            cancel_check=lambda: bool(
                (self.store.get_run(record.run_id) or record).cancel_requested),
            deferred_tools=full_tools if withhold else None,
            investigation=(seeded or {}).get("body") if seeded else None)
        orchestrator._version = record.version
        return orchestrator.run_to_completion()

    def _settle(self, record: Any, outcome: Outcome, emitter: ev.Emitter,
                ledger: Ledger) -> None:
        """Persist the answer, THEN publish `answer.ready`.

        Order matters: an answer that was emitted but not stored cannot be
        retrieved after a UI failure, and the user is told to ask again --
        paying for the same analysis twice.
        """
        try:
            current = self.store.get_run(record.run_id)
            version = current.version if current else record.version
            self.store.update_state(
                record.run_id, expect_version=version, state=outcome.state,
                operation="", budget=ledger.snapshot(),
                error_code=outcome.error_code, error_id=outcome.error_id,
                final_response=outcome.response, terminal=True)
        except LeaseLost:
            emitter.append(
                ev.RUN_INTERRUPTED, stage="publishing", operation="settle",
                status=ev.STATUS_FAILED,
                public_message=("This run was settled elsewhere; its result "
                                "was not overwritten."))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("V4 run %s could not be settled", record.run_id)
            emitter.append(
                ev.RUN_FAILED, stage="publishing", operation="settle",
                status=ev.STATUS_FAILED,
                public_message=f"The result could not be stored: {exc}")
            return

        if outcome.response is not None:
            try:
                self.store.append_turn(
                    thread_id=record.thread_id, run_id=record.run_id,
                    question=record.question, answer=outcome.response)
            except Exception:  # noqa: BLE001
                logger.warning("V4 could not append the thread turn for %s",
                               record.run_id)
            emitter.append(
                ev.ANSWER_READY, stage="publishing", operation="publish",
                status=ev.STATUS_OK,
                public_message="Answer ready.")
        elif (outcome.state not in (st.CANCELLED,)
              and not outcome.terminal_event_emitted):
            # Only when the orchestrator has not already said so, and said it
            # at the stage the run actually stopped at.
            emitter.append(
                ev.RUN_EXPIRED if outcome.state == st.EXPIRED
                else ev.RUN_FAILED,
                stage="publishing", operation="publish",
                status=ev.STATUS_FAILED, error_id=outcome.error_id,
                public_message=outcome.message
                or f"The request stopped: {outcome.error_code}.")

        # Memory maintenance runs AFTER the answer is published, on its own
        # quota, and cannot reopen this run.
        try:
            from backend.cockpit_v4 import memory

            memory.maybe_schedule(self.store, record.thread_id,
                                  cfg=self.runtime.cfg)
        except Exception:  # noqa: BLE001
            logger.info("V4 memory maintenance skipped for thread %s",
                        record.thread_id)


class _Heartbeat(threading.Thread):
    """Keeps the lease alive while the run works."""

    def __init__(self, store: RunStore, run_id: str, worker_id: str) -> None:
        super().__init__(daemon=True, name=f"v4-heartbeat-{run_id[:8]}")
        self.store = store
        self.run_id = run_id
        self.worker_id = worker_id
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.wait(2.0):
            try:
                self.store.heartbeat(self.run_id, self.worker_id)
            except LeaseLost:
                return
            except Exception:  # noqa: BLE001
                return

    def stop(self) -> None:
        self._stop.set()


__all__ = ["Worker"]
