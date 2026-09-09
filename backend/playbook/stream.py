"""
Streaming a generation, durably. Playbook §7, §16, PB-038.

The problem this solves
-----------------------
Streaming text to a browser is easy. Streaming it so that a refresh does not
lose the answer, does not kill the work, and does not start a second billable
generation is the actual requirement, and it rules out the obvious design.

The obvious design runs the generation inside the request that streams it. Then
a reload kills the run mid-way, the user sees a blank thread, and pressing send
again starts a second generation of the same turn. So instead:

* the generation runs in a **worker**, owned by the job rather than by any
  connection;
* every event it produces is **appended to the database** with a monotonic
  `seq`;
* a connection is a **reader** of that log — it replays from the client's
  cursor and then tails.

A reload therefore reconnects to the same job and replays what it missed. Two
browsers can watch the same generation. A dropped connection costs nothing. And
because the assistant's message and the artifact version are written only when
the run completes, an interrupted stream can never be read back as a finished
answer.

What is streamed, and what never is
-----------------------------------
Only user-visible answer text and real job states. The provider's own stream
carries more than that — reasoning blocks, tool inputs, the code the sandbox is
about to run — and none of it is forwarded: the writer takes `text_delta` and
nothing else. The system prompt, the evidence ledger and every credential stay
on this side of the wire.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from backend.models.playbook import PlaybookJob, PlaybookJobEvent

logger = logging.getLogger(__name__)

#: Text deltas are coalesced to this many characters before a row is written.
#: One row per token would make the log the slowest part of the system for no
#: visible benefit — the eye cannot read faster than this arrives.
DELTA_CHARS = 120
#: …or this long, whichever comes first, so a slow generation still shows
#: movement rather than appearing to stall.
DELTA_SECONDS = 0.35

#: How long a reader waits on the in-process signal before checking the
#: database anyway. The poll is not redundant: a worker in another process
#: writes rows this process is never notified about.
POLL_SECONDS = 0.4

#: A reader gives up after this long with no new event. A generation that has
#: genuinely stalled must not hold a connection open for ever.
IDLE_TIMEOUT_SECONDS = 900

#: Keep-alive comment interval, so an intermediary does not close a quiet
#: stream while a long tool call is running.
HEARTBEAT_SECONDS = 15


# --------------------------------------------------------------------------
# The log
# --------------------------------------------------------------------------


def emit(session, job_id: int, kind: str, data: dict | None = None) -> int:
    """Append one event and return its seq.

    The seq is computed from the log rather than held in memory, so a worker
    that restarts, or a second writer, cannot produce two events with the same
    number. The unique constraint is the backstop.
    """
    highest = session.execute(
        select(func.max(PlaybookJobEvent.seq))
        .where(PlaybookJobEvent.job_id == job_id)
    ).scalar() or 0
    event = PlaybookJobEvent(job_id=job_id, seq=highest + 1, kind=kind,
                             data=data or {})
    session.add(event)
    session.flush()
    return event.seq


def events_since(session, job_id: int, after: int = 0,
                 limit: int = 500) -> list[PlaybookJobEvent]:
    """Everything after the client's cursor, oldest first."""
    stmt = (select(PlaybookJobEvent)
            .where(PlaybookJobEvent.job_id == job_id,
                   PlaybookJobEvent.seq > after)
            .order_by(PlaybookJobEvent.seq)
            .limit(limit))
    return list(session.execute(stmt).scalars())


def replay_text(events: list[PlaybookJobEvent]) -> str:
    """The answer so far, from the deltas alone."""
    return "".join(e.data.get("text", "") for e in events if e.kind == "delta")


# --------------------------------------------------------------------------
# In-process fan-out
# --------------------------------------------------------------------------


class _Hub:
    """Wakes readers in THIS process the moment a writer here appends.

    Purely an optimisation. Correctness comes from the database poll, which is
    what makes a reader in another process work at all. Losing a notification
    costs latency, never an event.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiters: dict[int, threading.Condition] = {}

    def _condition(self, job_id: int) -> threading.Condition:
        with self._lock:
            cond = self._waiters.get(job_id)
            if cond is None:
                cond = threading.Condition()
                self._waiters[job_id] = cond
            return cond

    def notify(self, job_id: int) -> None:
        cond = self._condition(job_id)
        with cond:
            cond.notify_all()

    def wait(self, job_id: int, timeout: float) -> None:
        cond = self._condition(job_id)
        with cond:
            cond.wait(timeout)

    def forget(self, job_id: int) -> None:
        with self._lock:
            self._waiters.pop(job_id, None)


HUB = _Hub()


# --------------------------------------------------------------------------
# The writer a generation is given
# --------------------------------------------------------------------------


@dataclass
class Writer:
    """What the generation calls. Coalesces deltas; commits as it goes.

    Committing each event immediately is the point: a reader in another
    connection — or another process — can only see what has been committed, and
    an event nobody can read is not a stream.
    """

    session: Any
    job_id: int
    _buffer: str = ""
    _last_flush: float = 0.0

    def state(self, name: str, detail: str = "") -> None:
        self.flush()
        self._write("state", {"state": name, "detail": detail})

    def milestone(self, name: str, detail: str = "") -> None:
        self.flush()
        self._write("milestone", {"state": name, "detail": detail})

    def delta(self, text: str) -> None:
        """User-visible answer text. Never anything else."""
        if not text:
            return
        if not self._last_flush:
            self._last_flush = time.time()
        self._buffer += text
        if (len(self._buffer) >= DELTA_CHARS
                or time.time() - self._last_flush >= DELTA_SECONDS):
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        text, self._buffer = self._buffer, ""
        self._last_flush = time.time()
        self._write("delta", {"text": text})

    def artifact(self, payload: dict) -> None:
        self.flush()
        self._write("artifact", payload)

    def done(self, payload: dict) -> None:
        self.flush()
        self._write("done", payload)

    def error(self, message: str, *, category: str = "",
              cancelled: bool = False) -> None:
        # The buffer is deliberately DISCARDED on failure. Half an answer, left
        # on screen as though it were the answer, is worse than none — and the
        # thread already carries the failure message.
        self._buffer = ""
        self._write("error", {"message": message, "category": category,
                              "cancelled": cancelled})

    def _write(self, kind: str, data: dict) -> None:
        try:
            emit(self.session, self.job_id, kind, data)
            self.session.commit()
        except Exception:  # noqa: BLE001
            # A log that cannot be written must not take the generation with
            # it. The work continues; the stream degrades to its final state,
            # which the client recovers by reloading the thread.
            logger.exception("Playbook stream event could not be written.")
            self.session.rollback()
            return
        HUB.notify(self.job_id)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def follow(session_factory: Callable[[], Any], job_id: int, *,
           after: int = 0,
           idle_timeout: float = IDLE_TIMEOUT_SECONDS,
           is_disconnected: Callable[[], bool] | None = None,
           ) -> Iterator[dict]:
    """Replay from `after`, then tail until the run ends.

    Yields plain dictionaries — `{"seq", "kind", "data"}` — and a heartbeat as
    `{"kind": "ping"}` so a quiet tool call does not look like a dead
    connection. Ends after `done` or `error`, when the job is finished and
    nothing more is coming, or when the client goes away.
    """
    cursor = after
    last_event = time.time()
    last_beat = time.time()

    while True:
        if is_disconnected and is_disconnected():
            return

        with session_factory() as session:
            rows = events_since(session, job_id, cursor)
            batch = [{"seq": r.seq, "kind": r.kind, "data": dict(r.data)}
                     for r in rows]
            finished = _is_finished(session, job_id) if not batch else False

        for event in batch:
            cursor = event["seq"]
            yield event
            if event["kind"] in {"done", "error"}:
                return

        if batch:
            last_event = last_beat = time.time()
            continue

        if finished:
            # The job ended without a terminal event — a worker that died
            # outright, say. The client is told rather than left hanging.
            yield {"seq": cursor, "kind": "error",
                   "data": {"message": "This generation ended without "
                                       "finishing. Nothing was saved.",
                            "category": "worker_lost", "cancelled": False}}
            return

        now = time.time()
        if now - last_event > idle_timeout:
            yield {"seq": cursor, "kind": "error",
                   "data": {"message": "This generation stopped responding. "
                                       "Nothing was saved.",
                            "category": "idle_timeout", "cancelled": False}}
            return
        if now - last_beat >= HEARTBEAT_SECONDS:
            last_beat = now
            yield {"seq": cursor, "kind": "ping", "data": {}}

        HUB.wait(job_id, POLL_SECONDS)


def _is_finished(session, job_id: int) -> bool:
    job = session.get(PlaybookJob, job_id)
    return bool(job and job.finished_at is not None)


def sse(event: dict) -> str:
    """One event in the wire format.

    `id:` carries the seq so a browser reconnecting can send `Last-Event-ID`
    and be given exactly what it missed.
    """
    import json

    if event["kind"] == "ping":
        return ": keep-alive\n\n"
    return (f"id: {event['seq']}\n"
            f"event: {event['kind']}\n"
            f"data: {json.dumps(event['data'], separators=(',', ':'))}\n\n")


# --------------------------------------------------------------------------
# The worker
# --------------------------------------------------------------------------


def start(session_factory: Callable[[], Any], scope, workspace_id: int,
          *, job_id: int, request: dict,
          runner: Callable[..., dict] | None = None) -> None:
    """Run one generation in a thread, writing its events as it goes.

    A thread rather than the request that started it, and the whole point is
    what that buys: the browser can reload, or close, and the generation
    carries on. It is also what makes the stop button meaningful — there is
    something still running to stop.

    The thread owns its own session. Sharing the request's would mean a
    generation whose writes are invisible until a connection that has since
    gone away commits them.
    """
    def work() -> None:
        from backend.playbook import workspace_service as service

        run = runner or service.send_message
        with session_factory() as session:
            writer = Writer(session=session, job_id=job_id)
            try:
                writer.state("reviewing_sources")
                result = run(
                    session, scope, workspace_id,
                    on_milestone=lambda state, detail="": writer.state(
                        state, detail),
                    on_delta=writer.delta,
                    is_cancelled=service.cancellation_watcher(job_id),
                    **request,
                )
            except Exception as exc:  # noqa: BLE001 — every ending is an event
                session.rollback()
                _finish_with_error(session_factory, writer, job_id, exc)
                return

            session.commit()
            if result.get("artifact_id"):
                writer.artifact({"artifact_id": result["artifact_id"],
                                 "version": result.get("version", 0),
                                 "version_id": result.get("version_id")})
            writer.done({"message_id": result.get("message_id"),
                         "artifact_id": result.get("artifact_id"),
                         "version": result.get("version", 0),
                         "notes": result.get("notes") or []})
        HUB.forget(job_id)

    thread = threading.Thread(target=work, name=f"playbook-job-{job_id}",
                              daemon=True)
    thread.start()


def _finish_with_error(session_factory, writer: Writer, job_id: int,
                       exc: Exception) -> None:
    """Close a failed run: the job row, then the event, in that order.

    The order matters. A client that sees `error` reloads the thread, and the
    thread must already say the same thing — a stream that reports a failure
    the database has not recorded yet reads as a bug in the product rather than
    a failure of the run.
    """
    from backend.playbook import provider
    from backend.playbook import workspace_service as service

    cancelled = isinstance(exc, provider.Cancelled)
    category = getattr(exc, "category", "") or (
        "cancelled" if cancelled else "authoring_failed")
    message = (
        "This generation was stopped. Nothing was saved and the previous "
        "version is unchanged." if cancelled else str(exc))

    try:
        with session_factory() as session:
            service.mark_job_finished(
                session, job_id,
                state="cancelled" if cancelled else "failed",
                error="" if cancelled else str(exc)[:2000])
            session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Playbook job %s could not be closed.", job_id)

    writer.error(message, category=category, cancelled=cancelled)
    HUB.forget(job_id)
