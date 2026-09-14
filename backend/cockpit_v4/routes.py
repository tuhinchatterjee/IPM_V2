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
from backend.cockpit_v4 import attention
from backend.cockpit_v4 import lake as lake_mod
from backend.cockpit_v4 import collaboration as collab
from backend.cockpit_v4 import config as config_mod
from backend.cockpit_v4.intake import normalize_question
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
            startup_sha: str = "", cfg: Any = None,
            preflight_error: str = "") -> None:
    """Install the REAL runtime, or None. Never a stand-in.

    `cfg` and `preflight_error` are carried separately precisely because
    `runtime` may be None: a runtime that could not be built still has a
    configuration worth reporting and a reason worth naming.
    """
    _STATE.update({"store": store, "runtime": runtime,
                   "cfg": cfg or getattr(runtime, "cfg", None),
                   "preflight_error": preflight_error,
                   "principal": principal_resolver,
                   "startup_sha": startup_sha})


def _config() -> Any:
    return _STATE.get("cfg") or getattr(
        _STATE.get("runtime"), "cfg", None) or config_mod.load()


def readiness() -> Any:
    """What this runtime can do. One answer, consulted by every route."""
    from backend.cockpit_v4 import readiness as ready_mod

    return ready_mod.assess(
        _STATE.get("runtime"), cfg=_config(),
        preflight_error=str(_STATE.get("preflight_error") or ""))


def _require(capability: str) -> Any:
    """The runtime, once this capability is known to be available."""
    readiness().require(capability)
    return _STATE["runtime"]


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
    #: Which book. Read only when a NEW conversation is being opened -- a
    #: thread that already exists decides for itself, and a request that
    #: disagrees with it is refused rather than obeyed or ignored.
    domain: str = ""
    ui_filters: dict[str, Any] = Field(default_factory=dict)


def _digest(body: StartRun, who: dict[str, Any]) -> str:
    payload = json.dumps({"q": body.question, "t": body.thread_id,
                          "m": body.mode, "r": body.release_id,
                          "d": body.domain,
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
    from backend.cockpit_v4 import readiness as ready_mod

    state = readiness()
    # A run this runtime cannot process must not be accepted.
    #
    # The live failure: with the release unpublished the API answered 202,
    # the browser showed "Request accepted", and the worker had never been
    # started -- so the run sat in ACCEPTED until the user gave up. 202 is a
    # promise to do the work. Nothing that cannot keep it may send one.
    #
    # Product Help is refused separately and for a different reason: it needs
    # a model, not a portfolio, so a runtime with no release open can still
    # answer what the product does.
    if not state[ready_mod.PRODUCT_HELP_READY]:
        state.require(ready_mod.PRODUCT_HELP_READY)
    if not state[ready_mod.SQL_ANALYSIS_READY]:
        # The question's own mode is not known until the analyst declares an
        # intent, which is a model call away. What IS known here is that no
        # analysis can run at all, so a question is accepted only if Product
        # Help could answer it -- and the refusal names the capability.
        state.require(ready_mod.SQL_ANALYSIS_READY)
    runtime = _STATE.get("runtime")
    cfg = _config()

    mode = body.mode.lower() if body.mode.lower() in MODES else STANDARD
    from backend.cockpit_v4 import domain_resolver as resolver
    from backend.cockpit_v4 import domains as dom_mod

    tenant = str(who.get("tenant") or "")
    thread_id = body.thread_id
    pinned = ""
    if thread_id:
        owner = store.thread_owner(thread_id)
        if owner is None or owner[0] != tenant:
            # Does not reveal whether the thread exists for someone else.
            raise HTTPException(404, {"error_code": "NOT_FOUND",
                                      "message": "No such conversation."})
        pinned = (store.thread_domain(thread_id) or {}).get("domain_id", "")

    # The book, decided once. Inside a thread the thread wins; a request that
    # names a different one is REFUSED rather than obeyed or silently
    # overruled, because evidence from two books in one transcript cannot be
    # told apart afterwards.
    try:
        scope = resolver.resolve(thread_domain=pinned, requested=body.domain,
                                 tenant_id=tenant or lake_mod.DEFAULT_TENANT)
    except resolver.DomainPinned as exc:
        raise HTTPException(409, {
            "error_code": "DOMAIN_PINNED",
            "message": str(exc),
            "thread_domain": exc.thread_domain,
            "requested_domain": exc.asked,
            "action": {"label": f"Start a "
                                f"{dom_mod.SHORT_LABELS[exc.asked]} "
                                f"conversation",
                       "domain": exc.asked}}) from exc
    except resolver.DomainUnavailable as exc:
        raise HTTPException(503, {
            "error_code": st.DATA_UNAVAILABLE, "message": str(exc),
            "domain_id": exc.domain_id,
            "provision_command": resolver.provision_command(
                exc.domain_id)}) from exc
    except dom_mod.UnknownDomain as exc:
        raise HTTPException(400, {"error_code": "UNKNOWN_DOMAIN",
                                  "message": str(exc)}) from exc

    if not thread_id:
        thread_id = store.create_thread(
            tenant_id=tenant, principal_id=str(who.get("id") or ""),
            domain_id=scope.domain_id, release_id=scope.release_id,
            release_fingerprint=scope.release_fingerprint)

    # A conversation is named the moment it has a question in it, not when
    # the answer lands. Naming it on `append_turn` meant a reader watched a
    # thread called "New conversation" for the whole time it was working --
    # and a thread whose run failed kept that name for ever. No model call:
    # the title is the question.
    store.title_thread_from_question(thread_id, body.question)

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
    # Mechanical only — Unicode, whitespace, invisible controls. See
    # `intake.normalize_question`: nothing about the wording, the spelling,
    # the language or any number is touched here.
    normalized = normalize_question(body.question)
    try:
        record, created = store.accept_run(
            thread_id=thread_id, tenant_id=str(who.get("tenant") or ""),
            principal_id=str(who.get("id") or ""), question=normalized.text,
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
        emitter = ev.Emitter(store, record.run_id,
                             started_monotonic=time.monotonic())
        emitter.append(
            ev.RUN_ACCEPTED, stage="accepted", operation="intake",
            status=ev.STATUS_OK,
            public_message=f"Request accepted · release {record.release_id}")
        if normalized.changed:
            # Recorded because it happened, and only when it happened. A
            # trace that says text was normalised when it was not is the
            # same defect as a trace that hides it.
            emitter.append(
                ev.RUN_ACCEPTED, stage="accepted", operation="normalize",
                status=ev.STATUS_OK,
                detail_ref=store.put_detail(record.run_id, {
                    "normalization": normalized.report(),
                    "original": normalized.original[:8000]}),
                public_message="Question text normalized (formatting only).")

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


# ---- the Cockpit home feed ---------------------------------------------

def _attention_session(who: dict[str, Any]) -> tuple[Any, Any, Any]:
    """The read-only session, catalog and config the feed is computed from.

    Same scope machinery an analysis uses: the release is pinned by the
    server, the tenant comes from the principal, and neither can be widened
    by the request.
    """
    # Typed, before anything is dereferenced. The live failure was an
    # AttributeError from a stand-in runtime reaching this line -- a raw 500
    # with a traceback in it, where the honest answer is "this runtime has no
    # release open, and here is the command that publishes it".
    from backend.cockpit_v4 import readiness as ready_mod

    runtime = _require(ready_mod.ATTENTION_READY)

    from backend.cockpit_agentic import sql as v3_sql

    scope = runtime.scope_for(who)
    try:
        session = v3_sql.open_session(scope=scope, catalog=runtime.catalog)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, {
            "error_code": "ATTENTION_UNAVAILABLE",
            "message": ("The segment attention feed could not read the "
                        f"pinned release: {exc}")}) from exc
    return session, runtime, scope


def _domain_feed(who: dict[str, Any], domain_id: str, *,
                 refresh: bool = False) -> dict[str, Any]:
    """The dashboard for ONE book, computed from that book's own release.

    Switching domains is not a relabel and not a filter over one dataset: it
    opens a different release, a different catalogue and a different session,
    and the cache entry it fills is keyed by domain, release and fingerprint
    so it can never be served to the other book.
    """
    from backend.cockpit_v4 import attention_v2
    from backend.cockpit_v4 import catalog as cat_mod
    from backend.cockpit_v4 import domain_resolver as resolver

    tenant = str(who.get("tenant") or "") or lake_mod.DEFAULT_TENANT
    try:
        scope = resolver.scope_for(domain_id, tenant_id=tenant)
    except resolver.DomainUnavailable as exc:
        # One book being unpublished never makes the other stand in for it.
        raise HTTPException(503, {
            "error_code": st.DATA_UNAVAILABLE,
            "message": str(exc),
            "component": f"{domain_id}_attention_feed",
            "domain_id": domain_id,
            "provision_command": resolver.provision_command(domain_id),
        }) from exc
    try:
        session = cat_mod.open_session(
            catalog=cat_mod.build(domain_id=scope.domain_id,
                                  release_id=scope.release_id,
                                  tenant_id=tenant))
    except PermissionError as exc:
        # A tenant this release holds nothing for. Refused with the reason
        # and a typed code -- not an unhandled 500, and emphatically not an
        # empty feed, which would read as "your portfolio is fine".
        raise HTTPException(403, {
            "error_code": st.SECURITY_DENIED, "message": str(exc),
            "component": f"{domain_id}_attention_feed",
            "domain_id": domain_id}) from exc
    try:
        return attention_v2.cached(session=session, scope=scope,
                                   tenant_id=tenant, refresh=refresh)
    except attention_v2.AttentionUnavailable as exc:
        # A component-level failure with a reference, never a bare 404 and
        # never a claim that the backend is down: Ask keeps working.
        raise HTTPException(503, {
            "error_code": st.DATA_UNAVAILABLE, "message": str(exc),
            "component": f"{domain_id}_attention_feed",
            "domain_id": domain_id,
            "error_reference": "att-" + hashlib.sha256(
                str(exc).encode("utf-8")).hexdigest()[:12]}) from exc


def _feed(who: dict[str, Any], *, refresh: bool = False) -> dict[str, Any]:
    session, runtime, _scope = _attention_session(who)
    catalog = runtime.catalog
    currency = " ".join(
        part for part in (getattr(catalog, "reporting_currency", ""),
                          getattr(catalog, "amount_scale", "")) if part)
    calendar = getattr(catalog, "calendar", None)
    quarters = [str(q) for q in (getattr(calendar, "populated", ()) or ())]
    try:
        return attention.cached(
            session=session, release_id=str(runtime.cfg.release_id),
            tenant_id=str(who.get("tenant") or ""), quarters=quarters,
            currency=currency, refresh=refresh)
    except attention.AttentionUnavailable as exc:
        # A component-level failure with a reference, never a bare 404 and
        # never a claim that the backend is down: Ask keeps working.
        raise HTTPException(503, {
            "error_code": exc.code, "message": exc.message,
            "component": "segment_attention_feed",
            "error_reference": "att-" + hashlib.sha256(
                exc.message.encode("utf-8")).hexdigest()[:12]}) from exc


@router.get("/domains")
async def domain_list(who: dict[str, Any] = Depends(principal)
                      ) -> dict[str, Any]:
    """Which books this runtime serves, and whether each can be asked.

    §56, §57: reported separately. One domain being unpublished does not make
    the other unavailable and absolutely does not make it a substitute, so a
    switch can disable the book that is missing and say why.
    """
    from backend.cockpit_v4 import domain_resolver as resolver

    tenant = str(who.get("tenant") or "") or lake_mod.DEFAULT_TENANT
    return resolver.availability(tenant_id=tenant).to_dict()


@router.get("/attention")
async def attention_feed(refresh: bool = Query(False),
                         domain: str = Query(""),
                         who: dict[str, Any] = Depends(principal)
                         ) -> dict[str, Any]:
    """One book's dashboard: what requires attention, and this month's ECL.

    Deterministic, cached per tenant AND domain AND release fingerprint, and
    free of model calls: rendering this page costs nothing at the provider.
    """
    from backend.cockpit_v4 import domains as dom_mod

    try:
        domain_id = dom_mod.parse(domain)
    except dom_mod.UnknownDomain as exc:
        raise HTTPException(400, {"error_code": "UNKNOWN_DOMAIN",
                                  "message": str(exc)}) from exc
    return _domain_feed(who, domain_id, refresh=refresh)


@router.get("/attention-legacy")
async def attention_feed_legacy(refresh: bool = Query(False),
                                who: dict[str, Any] = Depends(principal)
                                ) -> dict[str, Any]:
    """The quarterly corporate feed, kept while its suite still reads it."""
    feed = _feed(who, refresh=refresh)
    public = {k: v for k, v in feed.items() if k not in ("method", "dropped")}
    public["method_summary"] = {
        "formula": feed["method"]["formula"],
        "indicators": len(feed["method"]["indicators"]),
        "candidates_considered": feed["method"]["candidates_considered"],
        "candidates_dropped": feed["method"]["candidates_dropped"],
    }
    return public


def _find_across_domains(who: dict[str, Any], item_id: str
                         ) -> tuple[dict[str, Any], dict[str, Any]]:
    """The item, and the feed it belongs to, whichever book that is.

    An item id carries its domain in the seed it was hashed from, so looking
    in both books cannot confuse them: at most one can hold this id, and the
    feed returned is the one that does.
    """
    from backend.cockpit_v4 import attention_v2
    from backend.cockpit_v4 import domains as dom_mod

    for domain_id in dom_mod.DOMAIN_IDS:
        try:
            feed = _domain_feed(who, domain_id)
        except HTTPException:
            continue  # a book that is not published holds no items
        item = attention_v2.find_item(feed, item_id)
        if item is not None:
            return item, feed
    raise HTTPException(404, {"error_code": "NOT_FOUND",
                              "message": "No such attention item."})


@router.get("/attention/{item_id}")
async def attention_item(item_id: str,
                         who: dict[str, Any] = Depends(principal)
                         ) -> dict[str, Any]:
    """One item with its full technical evidence, for Trace / operator view."""
    item, feed = _find_across_domains(who, item_id)
    return {"item": item,
            "domain_id": feed["domain_id"],
            "method": feed["method_summary"],
            "method_summary": feed["method_summary"],
            "release_id": feed["release_id"],
            "release_fingerprint": feed["release_fingerprint"],
            "reporting_quarter": feed["reporting_month"],
            "reporting_month": feed["reporting_month"]}


@router.post("/attention/{item_id}/investigate", status_code=201)
async def investigate(item_id: str,
                      who: dict[str, Any] = Depends(principal)
                      ) -> dict[str, Any]:
    """Open a V4 thread seeded with this attention item.

    The seed is stored on the THREAD, so the segment, the quarter, the
    comparison period and the evidence are carried by every turn in it. That
    is what lets the next question be "show me the customers behind this"
    rather than the whole sentence again.
    """
    item, feed = _find_across_domains(who, item_id)
    store = _store()
    tenant = str(who.get("tenant") or "")
    # §53: the thread is opened in the book the finding came FROM. A
    # corporate card cannot seed a retail conversation, because the evidence
    # the seed names lives in one release and nowhere else.
    thread_id = store.create_thread(
        tenant_id=tenant, principal_id=str(who.get("id") or ""),
        domain_id=feed["domain_id"], release_id=feed["release_id"],
        release_fingerprint=feed["release_fingerprint"])
    seed = {
        "item_id": item["item_id"],
        "origin": item["section"],
        "domain_id": feed["domain_id"],
        "release_id": feed["release_id"],
        "release_fingerprint": feed["release_fingerprint"],
        "headline": item["headline"],
        "segment": item["segment"],
        "segment_dimension": item["segment_dimension"],
        "reporting_quarter": item["reporting_quarter"],
        "comparison_quarter": item["comparison_quarter"],
        "comparison_basis": item["comparison_basis"],
        "metric": item["metric"],
        "metric_label": item["metric_label"],
        "issue": item["what_changed"],
        "why_it_appeared": item["why_it_appeared"],
        "movement": item["movement"],
        "key_numbers": item["key_numbers"],
        "evidence": item["evidence"],
        "drilldown": item.get("drilldown", {}),
        "evidence_url": item["evidence_url"],
    }
    store.set_thread_context(thread_id, tenant_id=tenant,
                             kind="attention_item", body=seed)
    # A seeded thread is ABOUT something before anybody types in it. Naming
    # it after the case beats "New conversation" in a list of conversations,
    # and it costs no model call: the headline is already written.
    store.set_thread_title(thread_id, tenant_id=tenant,
                           title=str(item["headline"])[:120])
    return {"thread_id": thread_id, "item_id": item["item_id"], "seed": seed,
            "suggested_questions": (item.get("drilldown", {})
                                    .get("suggested_questions", []))}


@router.get("/session")
async def session_summary(who: dict[str, Any] = Depends(principal)
                          ) -> dict[str, Any]:
    """Who is asking, and what they can reopen.

    The landing page greets by name when a name is available and greets
    plainly when it is not. It never invents one, and the time of day is
    computed in the browser from the reader's own clock rather than the
    server's.
    """
    runtime = _STATE.get("runtime")
    store = _store()
    tenant = str(who.get("tenant") or "")
    display = str(who.get("name") or "").strip()
    return {
        # A person's name, or nothing. A profile label -- "Local UAT",
        # "Service Account", the name of a deployment -- is NOT a person and
        # travels separately, so the greeting cannot accidentally address one.
        "display_name": display,
        "profile_label": str(who.get("profile_label") or "").strip(),
        "tenant": tenant,
        "release_id": str(getattr(getattr(runtime, "cfg", None),
                                  "release_id", "") or ""),
        "recent_threads": store.recent_threads(
            tenant_id=tenant, principal_id=str(who.get("id") or ""), limit=5),
    }


@router.get("/threads/{thread_id}")
async def read_thread(thread_id: str,
                      who: dict[str, Any] = Depends(principal)
                      ) -> dict[str, Any]:
    """Reopen a real persisted conversation. Never a fabricated history."""
    store = _store()
    tenant = str(who.get("tenant") or "")
    owner = store.thread_owner(thread_id)
    if owner is None or owner[0] != tenant:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such conversation."})
    context = store.thread_context(thread_id, tenant_id=tenant)
    turns = store.thread_turns(thread_id)
    title = store.thread_title(thread_id)
    if not title and turns:
        title = str(turns[0].get("question") or "")
    from backend.cockpit_v4 import domains as dom_mod

    # Which book this conversation was held in. Decided when it was created
    # and carried with the transcript, so a reader reopening it months later
    # is not left inferring the domain from the vocabulary of the answers.
    pinned = store.thread_domain(thread_id) or {}
    domain_id = pinned.get("domain_id") or dom_mod.DEFAULT_DOMAIN
    return {"thread_id": thread_id,
            "title": title,
            "domain_id": domain_id,
            "domain_label": dom_mod.LABELS.get(domain_id, domain_id),
            "domain_short_label": dom_mod.SHORT_LABELS.get(domain_id,
                                                           domain_id),
            "release_id": pinned.get("release_id", ""),
            "release_fingerprint": pinned.get("release_fingerprint", ""),
            # EVERY turn, oldest first. A transcript that renders only its
            # last few exchanges is a window, and a reader scrolling up to
            # find what they asked half an hour ago finds nothing.
            "turns": turns,
            "turn_count": len(turns),
            "created_at": store.thread_created_at(thread_id),
            "context": context or {},
            "release": _release_header()}


def _release_header() -> dict[str, Any]:
    """What the numbers in this thread mean. Travels with the transcript."""
    from backend.cockpit_v4 import release as release_mod

    runtime = _STATE.get("runtime")
    if runtime is None:
        return {}
    return release_mod.header(
        release_id=str(_config().release_id),
        catalog=getattr(runtime, "catalog", None),
        release_summary=getattr(runtime, "release_summary", None)).to_dict()


class RenameThread(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.post("/threads/{thread_id}/title")
async def rename_thread(thread_id: str, body: RenameThread,
                        who: dict[str, Any] = Depends(principal)
                        ) -> dict[str, Any]:
    """Rename a conversation. Tenant-checked: a URL is not an authorization."""
    store = _store()
    tenant = str(who.get("tenant") or "")
    if not store.set_thread_title(thread_id, tenant_id=tenant,
                                  title=body.title):
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such conversation."})
    return {"thread_id": thread_id,
            "title": store.thread_title(thread_id)}


# ---- what a credit officer does with an answer -------------------------
#
# Save it, put it in an investigation, comment on it, share it with a
# colleague, notify someone. All five are V4's own storage and routes; none
# of them calls the previous Cockpit's investigation API.
#
# The notifier is the part with teeth. It is constructed with no transport
# and an empty recipient allow-list, so this build records notifications and
# sends none. `GET /notifications` says so on every row, and the outbox
# listing carries `delivered: false` rather than a hopeful "queued".

_NOTIFIER = collab.Notifier()


def notifier() -> collab.Notifier:
    installed = _STATE.get("notifier")
    return installed if isinstance(installed, collab.Notifier) else _NOTIFIER


def _refuse(exc: collab.CollaborationError) -> HTTPException:
    return HTTPException(400, {"error_code": exc.code, "message": exc.message})


class SaveAnalysis(BaseModel):
    run_id: str = Field(min_length=1)
    title: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2000)


class NewInvestigation(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=4000)
    origin: str = Field(default="", max_length=120)
    thread_id: str = ""
    saved_ids: list[str] = Field(default_factory=list)


class InvestigationItem(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    ref_id: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=200)


class InvestigationStatus(BaseModel):
    status: str


class NewComment(BaseModel):
    subject_kind: str
    subject_id: str
    body: str = Field(min_length=1, max_length=collab.MAX_BODY)


class NewShare(BaseModel):
    subject_kind: str
    subject_id: str
    audience_id: str = Field(min_length=1, max_length=200)
    message: str = Field(default="", max_length=2000)
    notify_email: str = ""


@router.post("/saved-analyses", status_code=201)
async def save_analysis(body: SaveAnalysis,
                        who: dict[str, Any] = Depends(principal)
                        ) -> dict[str, Any]:
    """Keep the PUBLISHED answer, not a re-rendering of it.

    A saved analysis that regenerated its text would drift from what the
    reader actually saw and approved, so the stored copy is the response
    itself, with the artifact ids it cites.
    """
    store = _store()
    tenant = str(who.get("tenant") or "")
    record = store.get_run(body.run_id)
    if record is None or record.tenant_id != tenant:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such analysis."})
    if record.state not in st.TERMINAL_STATES or not record.final_response:
        raise HTTPException(
            409, {"error_code": "NOT_FINISHED",
                  "message": "An analysis can be saved once it has finished."})
    saved = store.save_analysis(
        tenant_id=tenant, principal_id=str(who.get("id") or ""),
        thread_id=record.thread_id, run_id=record.run_id,
        title=(body.title.strip() or record.question[:120]),
        note=body.note, question=record.question,
        release_id=record.release_id,
        body=collab.summarize_answer(record.final_response))
    return saved


@router.get("/saved-analyses")
async def list_saved(who: dict[str, Any] = Depends(principal)
                     ) -> dict[str, Any]:
    return {"saved": _store().list_saved_analyses(
        tenant_id=str(who.get("tenant") or ""))}


@router.get("/saved-analyses/{saved_id}")
async def read_saved(saved_id: str,
                     who: dict[str, Any] = Depends(principal)
                     ) -> dict[str, Any]:
    saved = _store().get_saved_analysis(
        saved_id, tenant_id=str(who.get("tenant") or ""))
    if saved is None:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such saved analysis."})
    return saved


@router.post("/investigations", status_code=201)
async def create_investigation(body: NewInvestigation,
                               who: dict[str, Any] = Depends(principal)
                               ) -> dict[str, Any]:
    store = _store()
    tenant = str(who.get("tenant") or "")
    actor = str(who.get("id") or "")
    investigation = store.create_investigation(
        tenant_id=tenant, principal_id=actor, title=body.title.strip(),
        summary=body.summary, origin=body.origin, thread_id=body.thread_id)
    for saved_id in body.saved_ids:
        saved = store.get_saved_analysis(saved_id, tenant_id=tenant)
        if saved is None:
            raise HTTPException(
                404, {"error_code": "NOT_FOUND",
                      "message": f"Saved analysis {saved_id} is not "
                                 f"available to you."})
        store.add_investigation_item(
            investigation_id=investigation["investigation_id"],
            tenant_id=tenant, kind=collab.SAVED_ANALYSIS, ref_id=saved_id,
            label=saved["title"], added_by=actor)
    return store.get_investigation(investigation["investigation_id"],
                                   tenant_id=tenant)


@router.get("/investigations")
async def list_investigations(who: dict[str, Any] = Depends(principal)
                              ) -> dict[str, Any]:
    return {"investigations": _store().list_investigations(
        tenant_id=str(who.get("tenant") or ""))}


@router.get("/investigations/{investigation_id}")
async def read_investigation(investigation_id: str,
                             who: dict[str, Any] = Depends(principal)
                             ) -> dict[str, Any]:
    found = _store().get_investigation(
        investigation_id, tenant_id=str(who.get("tenant") or ""))
    if found is None:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such investigation."})
    return found


@router.post("/investigations/{investigation_id}/items", status_code=201)
async def add_investigation_item(investigation_id: str,
                                 body: InvestigationItem,
                                 who: dict[str, Any] = Depends(principal)
                                 ) -> dict[str, Any]:
    store = _store()
    tenant = str(who.get("tenant") or "")
    entry = store.add_investigation_item(
        investigation_id=investigation_id, tenant_id=tenant, kind=body.kind,
        ref_id=body.ref_id, label=body.label,
        added_by=str(who.get("id") or ""))
    if entry is None:
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such investigation."})
    return entry


@router.post("/investigations/{investigation_id}/status")
async def set_investigation_status(investigation_id: str,
                                   body: InvestigationStatus,
                                   who: dict[str, Any] = Depends(principal)
                                   ) -> dict[str, Any]:
    if body.status not in collab.STATUSES:
        raise HTTPException(
            400, {"error_code": "UNKNOWN_STATUS",
                  "message": f"Status is one of "
                             f"{', '.join(collab.STATUSES)}."})
    tenant = str(who.get("tenant") or "")
    if not _store().set_investigation_status(investigation_id,
                                             tenant_id=tenant,
                                             status=body.status):
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such investigation."})
    return _store().get_investigation(investigation_id, tenant_id=tenant)


def _subject_exists(store, tenant: str, kind: str, subject_id: str) -> bool:
    if kind == collab.SAVED_ANALYSIS:
        return store.get_saved_analysis(subject_id,
                                        tenant_id=tenant) is not None
    return store.get_investigation(subject_id, tenant_id=tenant) is not None


@router.post("/comments", status_code=201)
async def add_comment(body: NewComment,
                      who: dict[str, Any] = Depends(principal)
                      ) -> dict[str, Any]:
    store = _store()
    tenant = str(who.get("tenant") or "")
    try:
        collab.check_subject(body.subject_kind, body.subject_id)
    except collab.CollaborationError as exc:
        raise _refuse(exc) from exc
    if not _subject_exists(store, tenant, body.subject_kind, body.subject_id):
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such item."})
    return store.add_comment(
        tenant_id=tenant, subject_kind=body.subject_kind,
        subject_id=body.subject_id, author_id=str(who.get("id") or ""),
        body=body.body)


@router.get("/comments")
async def list_comments(subject_kind: str = Query(...),
                        subject_id: str = Query(...),
                        who: dict[str, Any] = Depends(principal)
                        ) -> dict[str, Any]:
    tenant = str(who.get("tenant") or "")
    store = _store()
    if not _subject_exists(store, tenant, subject_kind, subject_id):
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such item."})
    return {"comments": store.list_comments(
        tenant_id=tenant, subject_kind=subject_kind, subject_id=subject_id)}


@router.post("/shares", status_code=201)
async def share(body: NewShare, who: dict[str, Any] = Depends(principal)
                ) -> dict[str, Any]:
    """Share inside the bank. An optional notification is RECORDED, not sent.

    The response always carries the outbox row, including the reason it was
    not delivered, so nothing in the UI can honestly render "email sent".
    """
    store = _store()
    tenant = str(who.get("tenant") or "")
    try:
        collab.check_subject(body.subject_kind, body.subject_id)
    except collab.CollaborationError as exc:
        raise _refuse(exc) from exc
    if not _subject_exists(store, tenant, body.subject_kind, body.subject_id):
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such item."})
    record = store.add_share(
        tenant_id=tenant, subject_kind=body.subject_kind,
        subject_id=body.subject_id, shared_by=str(who.get("id") or ""),
        audience_id=body.audience_id.strip(), message=body.message)
    notification = None
    if body.notify_email.strip():
        try:
            notification = notifier().notify(
                store, tenant_id=tenant, actor_id=str(who.get("id") or ""),
                recipient=body.notify_email.strip(),
                subject=f"Shared with you: {body.subject_kind}",
                body=body.message or "A colleague shared this with you.",
                subject_kind=body.subject_kind, subject_id=body.subject_id)
        except collab.CollaborationError as exc:
            raise _refuse(exc) from exc
    return {"share": record, "notification": notification,
            "delivery": notifier().describe()}


@router.get("/shares")
async def list_shares(subject_kind: str = Query(default=""),
                      subject_id: str = Query(default=""),
                      who: dict[str, Any] = Depends(principal)
                      ) -> dict[str, Any]:
    return {"shares": _store().list_shares(
        tenant_id=str(who.get("tenant") or ""), subject_kind=subject_kind,
        subject_id=subject_id)}


@router.get("/notifications")
async def list_notifications(who: dict[str, Any] = Depends(principal)
                             ) -> dict[str, Any]:
    """The outbox. Every row says whether it was delivered, and why not."""
    return {"delivery": notifier().describe(),
            "notifications": _store().list_notifications(
                tenant_id=str(who.get("tenant") or ""))}


@router.get("/diagnostics")
async def get_diagnostics() -> dict[str, Any]:
    runtime = _STATE.get("runtime")
    cfg = getattr(runtime, "cfg", None)
    return diagnostics(cfg, startup_sha=str(_STATE.get("startup_sha") or ""))


#: The routes the application SHELL polls, served at the paths it already
#: uses. Separate from `router` because these are a compatibility surface, not
#: part of the V4 contract: the shell must not report the whole backend
#: offline merely because this runtime does not serve the dashboard.
compat_router = APIRouter(prefix="/api/v1", tags=["cockpit-v4-compat"])


@compat_router.get("/health")
async def shell_health() -> dict[str, Any]:
    """`HealthResponse`, describing THIS runtime truthfully.

    Unauthenticated on purpose: it is the same contract the main backend's
    `/api/v1/health` serves, it carries no tenant data, and a status
    indicator that needs a session to say "I am up" cannot say it on the
    screen where it matters.
    """
    from backend.cockpit_v4.compat_health import health_payload

    state = readiness()
    return health_payload(
        _config(), startup_sha=str(_STATE.get("startup_sha") or ""),
        capabilities=state.to_dict(),
        preflight_error=str(_STATE.get("preflight_error") or ""))


@router.get("/runs/{run_id}/trace")
async def read_trace(run_id: str,
                     who: dict[str, Any] = Depends(principal)
                     ) -> dict[str, Any]:
    """What this run did, after it finished. §28.

    The live panel shows a run while it happens; a reader who comes back to
    a past turn -- their own, an hour later, or after a reload -- had no way
    to see the same thing. This serves the COMMITTED events, which is the
    same material the stream delivered, plus what the run cost and which
    release answered it.

    It costs no model call and it reads no model reasoning. Public
    operations, their timings and their outcomes; nothing that was not
    already written down while the run was going.
    """
    record = _authorize(run_id, who)
    store = _store()
    events = [e.to_dict() if hasattr(e, "to_dict") else dict(e)
              for e in store.events_since(run_id, 0)]
    return {
        "run_id": run_id,
        "thread_id": record.thread_id,
        "question": record.question,
        "state": record.state,
        "mode": record.mode,
        "error_code": record.error_code,
        "created_at": record.created_at,
        "events": events,
        "budget": record.budget or {},
        "release": _release_header(),
    }


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


__all__ = ["compat_router", "install", "router"]
