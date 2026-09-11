"""
The persisted event sequence, and the SSE frames built from it.

Why events are persisted rather than pushed
-------------------------------------------
A pushed event that nobody received did not happen, and a UI that renders a
stage it inferred is guessing. So every event here is committed to the run
store BEFORE it is streamed, carries a monotonic `seq` within its run, and is
replayable from a cursor. A browser that reconnects reads the same rows the
worker wrote; it never reconstructs a missing step, and it never invents one.

Heartbeats are deliberately NOT durable. They are a transport liveness signal,
not a state change, and writing a row every five seconds would bury the actual
timeline in noise.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.cockpit_v4 import EVENT_SCHEMA_VERSION

# ---- event types -------------------------------------------------------

RUN_ACCEPTED = "run.accepted"
RUN_STARTED = "run.started"
CONTEXT_READY = "context.ready"
MODEL_REQUESTED = "model.requested"
MODEL_RESPONSE_RECEIVED = "model.response_received"
MODEL_PARSED = "model.parsed"
INTENT_VALIDATED = "intent.validated"
TOOL_REQUESTED = "tool.requested"
TOOL_VALIDATED = "tool.validated"
TOOL_STARTED = "tool.started"
TOOL_COMPLETED = "tool.completed"
TOOL_FAILED = "tool.failed"
RETRY_REQUESTED = "retry.requested"
ANSWER_VALIDATED = "answer.validated"
ANSWER_READY = "answer.ready"
RUN_FAILED = "run.failed"
RUN_CANCELLED = "run.cancelled"
RUN_EXPIRED = "run.expired"
RUN_INTERRUPTED = "run.interrupted"
MEMORY_STARTED = "memory.started"
MEMORY_COMPLETED = "memory.completed"
MEMORY_FAILED = "memory.failed"

EVENT_TYPES: tuple[str, ...] = (
    RUN_ACCEPTED, RUN_STARTED, CONTEXT_READY, MODEL_REQUESTED,
    MODEL_RESPONSE_RECEIVED, MODEL_PARSED, INTENT_VALIDATED, TOOL_REQUESTED,
    TOOL_VALIDATED, TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED,
    RETRY_REQUESTED, ANSWER_VALIDATED, ANSWER_READY, RUN_FAILED,
    RUN_CANCELLED, RUN_EXPIRED, RUN_INTERRUPTED, MEMORY_STARTED,
    MEMORY_COMPLETED, MEMORY_FAILED)

#: Events after which no further analytical event may be appended to the run.
TERMINAL_EVENTS: frozenset[str] = frozenset({
    ANSWER_READY, RUN_FAILED, RUN_CANCELLED, RUN_EXPIRED, RUN_INTERRUPTED})

#: Memory runs on its own linked sequence and cannot reopen a settled run.
MEMORY_EVENTS: frozenset[str] = frozenset({
    MEMORY_STARTED, MEMORY_COMPLETED, MEMORY_FAILED})

STATUS_STARTED = "started"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_REJECTED = "rejected"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Event:
    """One committed fact about a run. Every field is something that happened.

    `public_message` is business language for the process panel. `detail_ref`
    points at an operator-only record: model ids, request sizes, provider
    request ids, the exact code. Nothing secret, and no private reasoning,
    goes into either -- see `detail.py` redaction on the way in.
    """

    run_id: str
    seq: int
    event_type: str
    stage: str
    operation: str
    status: str
    public_message: str
    occurred_at: str = field(default_factory=now_iso)
    elapsed_ms: int = 0
    attempt: int = 0
    submission: int = 0
    round: int = 0
    detail_ref: str = ""
    error_id: str = ""
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    event_id: str = field(default_factory=lambda: f"ev-{uuid.uuid4().hex}")
    schema_version: str = EVENT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "event_id": self.event_id,
            "run_id": self.run_id, "seq": self.seq,
            "event_type": self.event_type, "stage": self.stage,
            "operation": self.operation, "status": self.status,
            "occurred_at": self.occurred_at, "elapsed_ms": self.elapsed_ms,
            "attempt": self.attempt, "submission": self.submission,
            "round": self.round, "public_message": self.public_message,
            "detail_ref": self.detail_ref, "error_id": self.error_id,
            "trace_id": self.trace_id, "span_id": self.span_id,
            "parent_span_id": self.parent_span_id}

    def to_sse(self) -> str:
        """One `text/event-stream` frame, with the id a reconnect resumes from."""
        body = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)
        return (f"id: {self.seq}\n"
                f"event: {self.event_type}\n"
                f"data: {body}\n\n")


def heartbeat_frame() -> str:
    """A comment frame. Keeps the connection warm; commits nothing."""
    return f": heartbeat {int(time.time())}\n\n"


class Emitter:
    """Appends events for one run. The only writer of the run's sequence.

    Deliberately not a queue: `append` returns after the row is committed, so
    a caller that has an event id knows the fact is durable. The publish path
    reads committed rows.
    """

    def __init__(self, store: Any, run_id: str, *, started_monotonic: float,
                 trace_id: str = "") -> None:
        self.store = store
        self.run_id = run_id
        self._t0 = started_monotonic
        self.trace_id = trace_id or f"tr-{uuid.uuid4().hex}"
        self._span: str = ""

    def span(self, span_id: str) -> None:
        self._span = span_id

    def append(self, event_type: str, *, stage: str, operation: str,
               status: str, public_message: str, attempt: int = 0,
               submission: int = 0, round: int = 0, detail_ref: str = "",
               error_id: str = "", parent_span_id: str = "") -> Event:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type!r}")
        event = Event(
            run_id=self.run_id, seq=0, event_type=event_type, stage=stage,
            operation=operation, status=status, public_message=public_message,
            elapsed_ms=int((time.monotonic() - self._t0) * 1000),
            attempt=attempt, submission=submission, round=round,
            detail_ref=detail_ref, error_id=error_id, trace_id=self.trace_id,
            span_id=self._span or f"sp-{uuid.uuid4().hex[:16]}",
            parent_span_id=parent_span_id)
        return self.store.append_event(event)


#: The business-language stage labels the process panel shows. A stage that
#: has not started is shown as prospective, never as done: `PROSPECTIVE` is
#: what the UI renders with an empty circle.
STAGE_LABELS: dict[str, str] = {
    "accepted": "Request accepted",
    "understanding": "Understanding the request",
    "catalog": "Reading relevant data definitions",
    "product_knowledge": "Reading product knowledge",
    "preparing": "Preparing query",
    "validating": "Validating query",
    "executing": "Executing query",
    "reviewing": "Reviewing results",
    "publishing": "Validating and publishing answer",
    "memory": "Memory maintenance",
}

#: The order the panel lays stages out in when it has no events yet. The
#: ACTUAL path is dynamic -- product help never reaches `catalog` -- so this
#: is a layout hint, not a promise that every stage runs.
STAGE_ORDER: tuple[str, ...] = (
    "accepted", "understanding", "product_knowledge", "catalog", "preparing",
    "validating", "executing", "reviewing", "publishing")


__all__ = ["ANSWER_READY", "ANSWER_VALIDATED", "CONTEXT_READY", "Emitter",
           "EVENT_TYPES", "Event", "INTENT_VALIDATED", "MEMORY_COMPLETED",
           "MEMORY_EVENTS", "MEMORY_FAILED", "MEMORY_STARTED",
           "MODEL_PARSED", "MODEL_REQUESTED", "MODEL_RESPONSE_RECEIVED",
           "RETRY_REQUESTED", "RUN_ACCEPTED", "RUN_CANCELLED", "RUN_EXPIRED",
           "RUN_FAILED", "RUN_INTERRUPTED", "RUN_STARTED", "STAGE_LABELS",
           "STAGE_ORDER", "STATUS_FAILED", "STATUS_OK", "STATUS_REJECTED",
           "STATUS_STARTED", "TERMINAL_EVENTS", "TOOL_COMPLETED",
           "TOOL_FAILED", "TOOL_REQUESTED", "TOOL_STARTED", "TOOL_VALIDATED",
           "heartbeat_frame", "now_iso"]
