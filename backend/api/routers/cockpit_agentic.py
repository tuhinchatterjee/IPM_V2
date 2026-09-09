"""
The Cockpit Agentic V3 API surface.

    GET  /cockpit/diagnostics        what this runtime is, and what is raised
    GET  /cockpit/catalogue          the authorized field dictionary
    POST /cockpit/ask                answer one question
    POST /cockpit/cancel/{request}   stop a running request

A separate router rather than a branch inside `/ask`. The existing surface
carries the legacy deterministic path and the legacy analyst, and section 17
forbids the Cockpit falling back to either — the cleanest way to guarantee that
is for the Cockpit path not to pass through them at all.

Two things this surface does not accept, unchanged from `/ask`: SQL, and code.
The only free text it takes is a question or a clarification reply.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst
from backend.cockpit_agentic import DEEP, MODES, STANDARD, service, thread

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cockpit", tags=["cockpit"])

MAX_QUESTION_CHARS = 2000


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    #: Standard or Deep. Never upgraded silently (section 9.6), so an absent
    #: value takes the configured default rather than the larger budget.
    mode: str = Field(default="", max_length=16)
    thread_id: str = Field(default="", max_length=128)
    #: The pinned release. One request never mixes two.
    dataset_release_id: str = Field(default=service.DEFAULT_RELEASE,
                                    max_length=128)
    #: Filters selected on the screen. REQUESTS, not grants: they become
    #: inherited scope and are overridden by anything the user states.
    filters: dict[str, Any] = Field(default_factory=dict)
    #: An idempotency key. The same one continues one budget rather than
    #: opening a second (section 9.3).
    request_id: str = Field(default="", max_length=64)
    #: How many complete exchanges to carry. Three by default, five when
    #: needed, eight absolute maximum, all under the history token cap.
    recent_pairs: int = Field(default=thread.DEFAULT_PAIRS, ge=1,
                              le=thread.HARD_CAP_PAIRS)
    referenced_exchange_ids: list[str] = Field(default_factory=list,
                                               max_length=8)


@router.get("/diagnostics", summary="What this Cockpit runtime is")
def diagnostics(principal: Principal = RequireAnalyst) -> dict:
    """Branch, release, limits, and which guardrails are running raised.

    A demonstration where nobody can tell which build and which limits answered
    is a demonstration of nothing.
    """
    try:
        return service.diagnostics(principal)
    except Exception as e:                                  # noqa: BLE001
        logger.warning("Cockpit diagnostics could not be read: %s", e)
        return {"cockpit_agentic_v3": False, "available": False,
                "reason": str(e)}


@router.get("/catalogue", summary="The authorized field dictionary")
def catalogue(dataset_release_id: str = service.DEFAULT_RELEASE,
              principal: Principal = RequireAnalyst) -> dict:
    """The complete dictionary for this domain, scoped to the principal."""
    from backend.cockpit_agentic import catalog as catalog_mod
    from backend.cockpit_agentic import scope as scope_mod
    from backend.cockpit_agentic import store

    try:
        calendar = store.load_calendar(dataset_release_id)
    except store.ReleaseNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=str(e)) from e
    scope = scope_mod.for_principal(principal,
                                    dataset_release_id=dataset_release_id)
    built = catalog_mod.build(dataset_release_id=dataset_release_id,
                              calendar=calendar, tenant_id=scope.tenant_id)
    body = built.to_dict()
    # Metadata is scoped too: a listing is filtered BEFORE it is described.
    body["relations"] = {name: block
                         for name, block in body["relations"].items()
                         if scope.permits(name)}
    body["scope"] = scope.to_dict()
    return body


@router.post("/ask", summary="Answer one Cockpit question")
def ask(payload: AskIn, principal: Principal = RequireAnalyst) -> dict:
    """One question, one budget, one answer, referral, clarification or stop.

    There is no fallback path here. If the Cockpit cannot answer, the response
    says why.
    """
    mode = (payload.mode or "").strip().lower()
    if mode and mode not in MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "unknown_mode",
                    "message": f"{payload.mode!r} is not a mode.",
                    "modes": list(MODES)})
    try:
        answer = service.ask(
            payload.question, principal, thread_id=payload.thread_id,
            mode=mode, dataset_release_id=payload.dataset_release_id,
            ui_filters=dict(payload.filters), request_id=payload.request_id,
            pairs=payload.recent_pairs,
            referenced_exchange_ids=list(payload.referenced_exchange_ids))
    except service.ReleaseUnavailable as e:
        # Section 38: the pinned release, or nothing. Reported as its own
        # terminal state so the browser can say what happened rather than
        # showing a generic outage for a request that was well formed.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={"error": "DATA_UNAVAILABLE",
                                    "status": "DATA_UNAVAILABLE",
                                    "message": str(e)}) from e
    except service.NotAvailable as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={"error": "cockpit_unavailable",
                                    "message": str(e)}) from e
    return answer.to_dict()


@router.post("/cancel/{request_id}", summary="Stop a running request")
def cancel(request_id: str, principal: Principal = RequireAnalyst) -> dict:
    """Cancel stops new work. It does not retroactively remove provider charges
    already incurred, and this says so rather than implying otherwise."""
    from backend.cockpit_agentic.ledger import STORE

    ledger, _resumed = STORE.open(request_id=request_id)
    ledger.cancel()
    return {"request_id": request_id, "cancelled": True,
            "budget": ledger.budget_view(),
            "note": ("New work has stopped and running work is being "
                     "cancelled. Charges already incurred with the provider "
                     "are not reversed.")}


__all__ = ["router"]
