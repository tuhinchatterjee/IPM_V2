"""
The additive V4 API. New paths; V3's contract is untouched.

`POST /runs` accepts and returns promptly. It does NOT generate anything
before it has committed the run and its outbox row in one transaction: an
HTTP 202 means the work is durable and claimable, not that an answer exists.
If the store cannot commit, the request is rejected and no run is claimed --
because "accepted" that later evaporates is worse than a refusal.

SSE is authenticated like any result endpoint. A run id is not a bearer
token, and a stream that anyone with the id can read leaks a tenant's
analysis.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.cockpit_v4 import DEEP, MODES, STANDARD
from backend.cockpit_v4 import config as config_mod
from backend.cockpit_v4 import events as ev
from backend.cockpit_v4 import states as st
from backend.cockpit_v4.run_store import (IdempotencyConflict, RunStore,
                                          StorageUnavailable)
from backend.cockpit_v4.service import PreflightFailed, diagnostics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cockpit-v4", tags=["cockpit-v4"])

#: Set by the application factory. Kept explicit rather than global magic so
#: a test can install its own store and runtime.
_STATE: dict[str, Any] = {}


def install(*, store: RunStore, runtime: Any, principal_resolver: Any,
            startup_sha: str = "") -> None:
    _STATE.update({"store": store, "runtime": runtime,
                   "principal": principal_resolver,
                   "startup_sha": startup_sha})


def _store() -> RunStore:
    store = _STATE.get("store")
    if store is None:
        raise HTTPException(503, {"error_code": st.STORAGE_UNAVAILABLE,
                                  "message": "The V4 runtime is not started."})
    return store


async def principal(request: Request) -> dict[str, Any]:
    """Server-derived identity. Never read from the request body."""
    resolver = _STATE.get("principal")
    if resolver is None:
        raise HTTPException(503, {"error_code": st.INTERNAL_ERROR,
                                  "message": "No principal resolver is "
                                             "installed."})
    who = resolver(request)
    if not who:
        raise HTTPException(401, {"error_code": "UNAUTHENTICATED",
                                  "message": "Sign in to use the Cockpit."})
    return who


class StartRun(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    thread_id: str = ""
    mode: str = STANDARD
    release_id: str = ""
    ui_filters: dict[str, Any] = Field(default_factory=dict)


def _digest(body: StartRun, who: dict[str, Any]) -> str:
    payload = json.dumps({"q": body.question, "t": body.thread_id,
                          "m": body.mode, "r": body.release_id,
                          "f": body.ui_filters, "p": who.get("id")},
                         sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@router.post("/threads")
async def create_thread(who: dict[str, Any] = Depends(principal)
                        ) -> dict[str, Any]:
    """A server-generated conversation id. Never a shared global constant."""
    thread_id = _store().create_thread(tenant_id=str(who.get("tenant") or ""),
                                       principal_id=str(who.get("id") or ""))
    return {"thread_id": thread_id}


@router.post("/runs", status_code=202)
async def start_run(body: StartRun, request: Request,
                    idempotency_key: str = Header("", alias="Idempotency-Key"),
                    who: dict[str, Any] = Depends(principal)) -> JSONResponse:
    store = _store()
    runtime = _STATE.get("runtime")
    cfg = getattr(runtime, "cfg", None) or config_mod.load()

    mode = body.mode.lower() if body.mode.lower() in MODES else STANDARD
    thread_id = body.thread_id
    if thread_id:
        owner = store.thread_owner(thread_id)
        if owner is None or owner[0] != str(who.get("tenant") or ""):
            # Does not reveal whether the thread exists for someone else.
            raise HTTPException(404, {"error_code": "NOT_FOUND",
                                      "message": "No such conversation."})
    else:
        thread_id = store.create_thread(
            tenant_id=str(who.get("tenant") or ""),
            principal_id=str(who.get("id") or ""))

    limits = config_mod.limits_for(mode)

    # An idempotent retry is the SAME run. It is resolved before the
    # concurrency check, or a dropped 202 would come back as a 409 the
    # caller has no way to clear.
    digest = _digest(body, who)
    existing, stored_digest = store.run_for_key(
        str(who.get("id") or ""), idempotency_key)
    if existing is not None:
        if stored_digest != digest:
            raise HTTPException(409, {
                "error_code": "IDEMPOTENCY_CONFLICT",
                "message": ("This idempotency key was already used for a "
                            "different request.")})
        return _accepted(existing, created=False)

    if store.active_runs_for(thread_id=thread_id) >= 1:
        raise HTTPException(409, {
            "error_code": "RUN_IN_PROGRESS",
            "message": "This conversation already has a request running."})
    if store.active_runs_for(principal_id=str(who.get("id") or "")) >= 2:
        raise HTTPException(429, {
            "error_code": "TOO_MANY_RUNS",
            "message": "You already have two requests running."})

    deadline_at = _deadline(limits.deadline_seconds)
    try:
        record, created = store.accept_run(
            thread_id=thread_id, tenant_id=str(who.get("tenant") or ""),
            principal_id=str(who.get("id") or ""), question=body.question,
            mode=mode, release_id=body.release_id or cfg.release_id,
            ui_filters=dict(body.ui_filters),
            idempotency_key=idempotency_key, body_digest=digest,
            startup_sha=str(_STATE.get("startup_sha") or ""),
            deadline_at=deadline_at)
    except IdempotencyConflict as exc:
        raise HTTPException(409, {"error_code": "IDEMPOTENCY_CONFLICT",
                                  "message": str(exc)}) from exc
    except StorageUnavailable as exc:
        # No run is claimed when the store cannot commit.
        raise HTTPException(503, {
            "error_code": st.STORAGE_UNAVAILABLE,
            "message": ("The request was not accepted because it could not "
                        "be stored durably. Nothing is running.")}) from exc

    if created:
        ev.Emitter(store, record.run_id,
                   started_monotonic=time.monotonic()).append(
            ev.RUN_ACCEPTED, stage="accepted", operation="intake",
            status=ev.STATUS_OK,
            public_message=f"Request accepted · release {record.release_id}")

    return _accepted(record, created=created)


def _accepted(record: Any, *, created: bool) -> JSONResponse:
    return JSONResponse(status_code=202, content={
        "run_id": record.run_id, "thread_id": record.thread_id,
        "state": record.state, "mode": record.mode,
        "release_id": record.release_id, "duplicate": not created,
        "status_url": f"{router.prefix}/runs/{record.run_id}",
        "events_url": f"{router.prefix}/runs/{record.run_id}/events",
        "cancel_url": f"{router.prefix}/runs/{record.run_id}/cancel",
        "note": ("Accepted means durable and claimable. It does not mean "
                 "answered.")})


def _deadline(seconds: float) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc)
            + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


def _authorize(run_id: str, who: dict[str, Any]) -> Any:
    record = _store().get_run(run_id)
    if record is None or record.tenant_id != str(who.get("tenant") or ""):
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such run."})
    return record


@router.get("/runs/{run_id}")
async def get_run(run_id: str, who: dict[str, Any] = Depends(principal)
                  ) -> dict[str, Any]:
    record = _authorize(run_id, who)
    store = _store()
    body = record.to_dict()
    body["last_event_seq"] = store.last_seq(run_id)
    body["terminal"] = st.is_terminal(record.state)
    body["note"] = ("HTTP 200 means this status was read. It does not mean "
                    "the analysis succeeded.")
    return body


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, who: dict[str, Any] = Depends(principal)
                     ) -> dict[str, Any]:
    record = _authorize(run_id, who)
    if st.is_terminal(record.state):
        # Idempotent, and it does not un-settle a finished run.
        return {"run_id": run_id, "state": record.state,
                "cancelled": False,
                "message": "This run had already finished."}
    updated = _store().request_cancel(run_id)
    return {"run_id": run_id, "state": getattr(updated, "state", record.state),
            "cancelled": True}


@router.post("/runs/{run_id}/delivered")
async def acknowledge(run_id: str, who: dict[str, Any] = Depends(principal)
                      ) -> dict[str, Any]:
    """Presentation acknowledgement, kept separate from analytical status."""
    _authorize(run_id, who)
    _store().mark_delivered(run_id)
    return {"run_id": run_id, "acknowledged": True}


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
async def read_artifact(run_id: str, artifact_id: str,
                        offset: int = Query(0, ge=0),
                        limit: int = Query(100, ge=1, le=1000),
                        who: dict[str, Any] = Depends(principal)
                        ) -> dict[str, Any]:
    _authorize(run_id, who)
    record = _store().get_artifact(artifact_id,
                                   tenant_id=str(who.get("tenant") or ""))
    if record is None or record["run_id"] != run_id:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such artifact."})
    rows = record["rows"][offset:offset + limit]
    return {"artifact_id": artifact_id, "columns": record["columns"],
            "total_rows": record["row_count"], "offset": offset,
            "rows": rows,
            "omitted_rows": max(0, record["row_count"] - (offset + len(rows))),
            "executed_code_digest": record["code_digest"]}


@router.get("/diagnostics")
async def get_diagnostics() -> dict[str, Any]:
    runtime = _STATE.get("runtime")
    cfg = getattr(runtime, "cfg", None)
    return diagnostics(cfg, startup_sha=str(_STATE.get("startup_sha") or ""))


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request,
                        last_event_id: str = Header("", alias="Last-Event-ID"),
                        cursor: int = Query(0, ge=0),
                        who: dict[str, Any] = Depends(principal)
                        ) -> StreamingResponse:
    """Ordered SSE with replay from a cursor and a heartbeat.

    A browser disconnect does not cancel the run and a reconnect never
    resubmits the question: the client sends `Last-Event-ID` and gets the
    committed events it missed, in order.
    """
    record = _authorize(run_id, who)
    store = _store()
    start = cursor
    if last_event_id:
        try:
            start = max(start, int(last_event_id))
        except ValueError:
            start = cursor

    cfg = getattr(_STATE.get("runtime"), "cfg", None) or config_mod.load()
    heartbeat = max(1.0, float(cfg.heartbeat_seconds))

    async def publish():
        seq = start
        last_beat = time.monotonic()
        # A bounded delivery buffer: a slow subscriber is disconnected and
        # replays, rather than growing the worker's memory without limit.
        while True:
            if await request.is_disconnected():
                return
            try:
                batch = store.events_since(run_id, seq, limit=200)
            except Exception as exc:  # noqa: BLE001
                yield (f"event: stream.error\ndata: "
                       f"{json.dumps({'message': str(exc)[:200]})}\n\n")
                return
            for event in batch:
                seq = event.seq
                yield event.to_sse()
                last_beat = time.monotonic()
                if event.event_type in ev.TERMINAL_EVENTS:
                    current = store.get_run(run_id)
                    yield ("event: run.settled\ndata: "
                           + json.dumps(current.to_dict() if current else {},
                                        default=str) + "\n\n")
                    return
            current = store.get_run(run_id)
            if current is not None and st.is_terminal(current.state) \
                    and seq >= store.last_seq(run_id):
                yield ("event: run.settled\ndata: "
                       + json.dumps(current.to_dict(), default=str) + "\n\n")
                return
            if time.monotonic() - last_beat >= heartbeat:
                yield ev.heartbeat_frame()
                last_beat = time.monotonic()
            await asyncio.sleep(0.1)

    return StreamingResponse(
        publish(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform",
                 "Connection": "keep-alive",
                 # Defeats proxy buffering that would hold events until the
                 # response completes -- which is exactly the failure the
                 # live panel exists to make impossible.
                 "X-Accel-Buffering": "no"})


__all__ = ["install", "router"]
