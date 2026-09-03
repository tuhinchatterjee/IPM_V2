"""
The agent worker. §18.

One process, one loop: claim a job, run it, heartbeat while it runs, record what
happened, repeat. It is deliberately dull. Everything interesting about a run
lives in the orchestrator; everything interesting about durability lives in the
queue. What is left here is the part that has to be right about *stopping*.

Why it is a separate service
----------------------------
§18 asks for a separate `agent-worker` Docker service, and the reason is that a
proactive portfolio review takes minutes and scans millions of rows. Run inside
the API process it occupies a request worker for the duration, and every user
asking a question waits behind it. Run beside it, sharing the same image and the
same database, and the API stays responsive while the review runs.

Secrets
-------
None are read here. The worker reads `settings` like everything else, and the
container receives its environment at runtime — §18's "receive secrets at
runtime only; never include API keys in image layers" is a property of the
Dockerfile, and this module simply never writes one anywhere.

Stopping
--------
Two ways, and both leave a readable record.

**SIGTERM** (a container stopping) sets `draining`. The loop finishes the job it
is in the middle of, releases nothing, and exits. If the job is long, the
orchestrator's own cancellation checkpoints see the flag and stop it early.

**Cancellation** of one job sets a database flag. The orchestrator checks it
between tasks and stops, leaving the run marked cancelled with the tasks that
did complete still attached.

Neither path kills a process mid-write. A run that was interrupted says so.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.agentic import queue

logger = logging.getLogger(__name__)

#: How long to wait when there is nothing to do. Short enough that a user's
#: question is picked up promptly; long enough that an idle worker is not a
#: query per millisecond.
IDLE_SLEEP_SECONDS = 2.0

#: How often to extend the lease while a job runs. Comfortably inside
#: LEASE_SECONDS, so one slow beat does not lose the job.
HEARTBEAT_SECONDS = 20.0

#: How often to sweep for jobs whose worker vanished.
RECOVERY_EVERY_SECONDS = 60.0


# ---------------------------------------------------------------------------
# What a handler is
# ---------------------------------------------------------------------------

#: A handler takes the claimed job and a callable that reports whether the run
#: has been asked to stop, and returns nothing. It raises to fail.
Handler = Callable[[queue.Job, Callable[[], bool]], None]

_HANDLERS: dict[str, Handler] = {}


def register(kind: str, handler: Handler) -> None:
    """Attach a handler to a job kind.

    A registry rather than an import: the worker must be startable — and
    testable — without importing the whole orchestration stack, and a job kind
    with no handler is a clear failure rather than an import error at boot.
    """
    _HANDLERS[kind] = handler


def handler_for(kind: str) -> Handler | None:
    if kind not in _HANDLERS:
        _install_defaults()
    return _HANDLERS.get(kind)


def _install_defaults() -> None:
    """Wire the product's own handlers, once, on first use.

    Imported lazily and defensively: a worker whose orchestration module fails
    to import should say so against the job it could not run, not die at
    start-up leaving an empty queue and no explanation.
    """
    if _HANDLERS:
        return
    try:
        from backend.agentic import runner

        register(queue.AGENTIC_RUN, runner.run_agentic_job)
        register(queue.PROACTIVE_REVIEW, runner.run_proactive_job)
        register(queue.SCHEDULE_TICK, runner.run_schedule_tick)
    except Exception:  # noqa: BLE001 - reported per job, not at boot
        logger.exception("agentic handlers could not be loaded")

    try:
        # The Project Planner's overnight sweep. Registered here rather than
        # given a scheduler of its own: this queue already has idempotency,
        # retries and heartbeats, and a second one would be a second thing to
        # operate at three in the morning.
        from backend.planner import monitor as planner_monitor

        register(planner_monitor.PLANNER_SWEEP,
                 planner_monitor.run_sweep_job)
    except Exception:  # noqa: BLE001 - reported per job, not at boot
        logger.exception("the project planner sweep could not be loaded")


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------


@dataclass
class Worker:
    """One worker process."""

    worker_id: str = field(default_factory=queue.worker_id)
    kinds: tuple[str, ...] = ()
    build_sha: str = ""
    #: Set by SIGTERM, or by a test. The loop finishes its job and exits.
    draining: bool = False
    completed: int = 0
    failed: int = 0
    _last_recovery: float = 0.0

    # -- lifecycle ---------------------------------------------------------

    def install_signal_handlers(self) -> None:
        def stop(signum: int, _frame: Any) -> None:
            logger.info("worker %s draining on signal %s", self.worker_id,
                        signum)
            self.draining = True

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, stop)
            except ValueError:
                # Not the main thread — a test, or an embedded worker.
                pass

    def start(self) -> None:
        from backend.db.engine import get_session

        with get_session() as session:
            queue.register_worker(session, worker=self.worker_id,
                                  build_sha=self.build_sha)
        logger.info("agent worker %s started", self.worker_id)

    def stop(self) -> None:
        from backend.db.engine import get_session

        with get_session() as session:
            queue.worker_beat(session, worker=self.worker_id,
                              status="stopped", completed=self.completed,
                              failed=self.failed)
        logger.info("agent worker %s stopped (%s completed, %s failed)",
                    self.worker_id, self.completed, self.failed)

    # -- the loop ----------------------------------------------------------

    def run_forever(self, *, max_jobs: int = 0) -> int:
        """Claim and run jobs until asked to stop.

        `max_jobs` bounds the loop for tests and for a one-shot invocation. Zero
        means run until drained.
        """
        self.start()
        ran = 0
        try:
            while not self.draining and (max_jobs == 0 or ran < max_jobs):
                self._maybe_recover()
                did = self.run_once()
                if did:
                    ran += 1
                else:
                    time.sleep(IDLE_SLEEP_SECONDS)
        finally:
            self.stop()
        return ran

    def run_once(self) -> bool:
        """Claim one job and run it. Returns False when there was nothing."""
        from backend.db.engine import get_session

        with get_session() as session:
            job = queue.claim(session, worker=self.worker_id, kinds=self.kinds)
            if job is None:
                queue.worker_beat(session, worker=self.worker_id,
                                  status="idle", completed=self.completed,
                                  failed=self.failed)
                return False
            queue.worker_beat(session, worker=self.worker_id,
                              status="working", job_id=job.id,
                              completed=self.completed, failed=self.failed)

        self._execute(job)
        return True

    # -- one job -----------------------------------------------------------

    def _execute(self, job: queue.Job) -> None:
        from backend.db.engine import get_session

        beat = _Heartbeat(self.worker_id, job.id)
        beat.start()
        try:
            handler = handler_for(job.kind)
            if handler is None:
                raise LookupError(
                    f"No handler is registered for '{job.kind}' jobs.")
            handler(job, lambda: self.draining or beat.cancelled)
        except Exception as exc:  # noqa: BLE001 - recorded against the job
            beat.stop()
            self.failed += 1
            logger.exception("job %s (%s) failed", job.id, job.kind)
            with get_session() as session:
                queue.fail(session, job.id, error=f"{type(exc).__name__}: {exc}",
                           category=_category(exc),
                           retry=not isinstance(exc, LookupError))
            return

        beat.stop()
        with get_session() as session:
            if beat.cancelled:
                queue.stopped(session, job.id)
                logger.info("job %s stopped on request", job.id)
            else:
                queue.complete(session, job.id, worker=self.worker_id)
                self.completed += 1

    def _maybe_recover(self) -> None:
        """Sweep for jobs whose worker vanished.

        Any worker may sweep; the UPDATE is atomic, so several sweeping at once
        recover disjoint sets rather than fighting.
        """
        now = time.monotonic()
        if now - self._last_recovery < RECOVERY_EVERY_SECONDS:
            return
        self._last_recovery = now
        from backend.db.engine import get_session

        try:
            with get_session() as session:
                queue.recover_stale(session)
        except Exception:  # noqa: BLE001 - a sweep failing is not fatal
            logger.exception("stale-job recovery failed")


def _category(exc: BaseException) -> str:
    """A short, stable label for what went wrong, for the Runs tab.

    Categories rather than messages, because "what keeps failing" is a question
    about kinds of failure and a message contains a period, a dataset name and a
    row count that make every failure unique.
    """
    name = type(exc).__name__
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, LookupError):
        return "not_found"
    if isinstance(exc, (ConnectionError, OSError)):
        return "unavailable"
    return name[:48]


class _Heartbeat:
    """Extends the lease on a background thread while a job runs.

    A thread rather than a periodic call inside the handler, because the handler
    is an orchestrator that runs analytical scans and has no business knowing a
    queue exists. It also watches for a cancellation flag, so the handler's
    `should_stop()` is answered from the database rather than from hope.
    """

    def __init__(self, worker: str, job_id: int) -> None:
        self.worker = worker
        self.job_id = job_id
        self.cancelled = False
        self.lost = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._beat, name=f"heartbeat-{self.job_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _beat(self) -> None:
        from backend.db.engine import get_session

        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                with get_session() as session:
                    if not queue.heartbeat(session, self.job_id,
                                           worker=self.worker):
                        # Somebody decided this worker was dead. Two workers
                        # finishing one job is worse than one stopping.
                        self.lost = True
                        self.cancelled = True
                        logger.warning("job %s lease lost by %s", self.job_id,
                                       self.worker)
                        return
                    if queue.is_cancelled(session, self.job_id):
                        self.cancelled = True
                        return
            except Exception:  # noqa: BLE001 - a missed beat is not fatal
                logger.exception("heartbeat failed for job %s", self.job_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """`python -m backend.agentic.worker` — the container's command."""
    from backend.logging_setup import init_logging

    init_logging()
    worker = Worker(build_sha=_build_sha())
    worker.install_signal_handlers()
    worker.run_forever()
    return 0


def _build_sha() -> str:
    """Which build this worker is running. §81 asks for SHA reporting, and the
    reason it matters here is that a worker and an API on different images is a
    real and confusing failure: the API shows a plan the worker cannot run."""
    try:
        from backend.build_info import build_info

        return str(build_info().sha or "")[:64]
    except Exception:  # noqa: BLE001
        import os

        return os.environ.get("BUILD_SHA", "")[:64]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "HEARTBEAT_SECONDS",
    "IDLE_SLEEP_SECONDS",
    "RECOVERY_EVERY_SECONDS",
    "Handler",
    "Worker",
    "handler_for",
    "main",
    "register",
]
