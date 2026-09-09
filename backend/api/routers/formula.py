"""Formula to code to a locked metric, over HTTP. §10–§13.

Five routes, one per step of the sequence §57 says the tranche is done only
when it works end to end:

    POST /formula/read      what you typed, located and flagged, not rewritten
    POST /formula/draft     the code, written and validated
    POST /formula/revise    your edit, revalidated and its meaning compared
    POST /formula/approve   you have read the code and accept it
    POST /formula/preview   run it on real data and show the exact arithmetic
    POST /formula/lock      store it as a governed metric

Why the artefact travels in the body
-------------------------------------
There is no draft table and no server-side session for a metric being built.
Every route takes the whole artefact and returns the whole artefact, exactly as
the existing metric builder's routes take a definition. Two things follow, and
both are the point:

* Nothing half-built exists in the catalogue for a Lens to find.
* §11's rule is structural. "Never trust user code merely because it came from
  the browser" is not a policy applied on one route — the browser is the ONLY
  source, so every route revalidates everything, and there is no path where a
  previously-validated artefact is taken on trust.

The approval checksum
----------------------
`approve` returns one and `preview` and `lock` require it. It covers the code,
the program and the declared shape, so a browser that showed one definition,
collected the approval and posted a different one is refused by name rather
than silently locking something nobody read.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst
from backend.metrics import formula_flow as flow
from backend.metrics.metric_code import MetricCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/formula", tags=["metrics"])

MAX_TEXT = 2000


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "metric_refused", "message": str(exc)})


def _not_approved(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": "approval_required", "message": str(exc)})


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable", "message": str(exc)})


# ------------------------------------------------------------------- shapes


class SaidIn(BaseModel):
    said: str = Field(min_length=1, max_length=MAX_TEXT)
    period: str = Field(default="", max_length=32)
    lens_id: int | None = None
    #: §5. Where the person was shown an unconventional formula and chose
    #: differently, this is what they chose. Empty means compute what they
    #: typed.
    keep_formula: str = Field(default="", max_length=MAX_TEXT)
    mode: str = Field(default="standard", max_length=16)


class CodeIn(BaseModel):
    """A whole artefact, back from the browser. Nothing in it is trusted."""

    code: dict = Field(default_factory=dict)
    period: str = Field(default="", max_length=32)
    approved_checksum: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=MAX_TEXT)
    #: The artefact as it stood before the person edited it, so `revise` can
    #: say what their edit changed about the metric's MEANING.
    previous: dict | None = None
    edited: bool = False
    shared: bool = True
    require_preview: bool = True


def _code(payload: CodeIn) -> MetricCode:
    if not payload.code:
        raise _refused(ValueError(
            "No metric definition was sent, so there is nothing to check."))
    return MetricCode.from_dict(payload.code)


def _budget(mode: str):
    """§46. One global budget per request, sized by the mode asked for.

    Standard and Deep differ in how much a request may spend, not in what it
    is allowed to reach — the domain boundary is the same in both, and Deep
    is a wider ceiling rather than a wider surface.
    """
    from backend.agentic.budgets import INTERACTIVE, PROACTIVE, Budget

    return Budget(limits=PROACTIVE if mode.lower() == "deep" else INTERACTIVE)


# ------------------------------------------------------------------- routes


@router.post("/read", summary="What you typed, read but not rewritten")
def read_formula(payload: SaidIn,
                 principal: Principal = RequireAnalyst) -> dict:
    """§4, §5, §34.

    The formula that comes back is always a substring of what was sent. Where
    it reads unconventionally, `unconventional` carries the reason, the
    conventional alternative and the three choices — and nothing has been
    applied.
    """
    return flow.read(payload.said, budget=_budget(payload.mode))


@router.post("/draft", summary="Write the code for this formula")
def draft_formula(payload: SaidIn,
                  principal: Principal = RequireAnalyst) -> dict:
    """§6–§9. The program, the SQL, and every check §8 asks for.

    A definition that fails validation still comes back, with the failures:
    §10 shows a person what was rejected and why, rather than an empty screen
    with an error on it.
    """
    lens = None
    if payload.lens_id:
        try:
            from backend.services import lenses as lens_service

            view = lens_service.get(payload.lens_id)
            lens = {"name": view.name, "purpose": view.description,
                    "audience": view.audience}
        except Exception:  # noqa: BLE001 - a Lens that is gone is not fatal
            lens = None
    return flow.draft(payload.said, period=payload.period, lens=lens,
                      user_id=principal.user_id,
                      keep_formula=payload.keep_formula,
                      budget=_budget(payload.mode))


@router.post("/revise", summary="Check code you edited")
def revise_formula(payload: CodeIn,
                   principal: Principal = RequireAnalyst) -> dict:
    """§11. Your edit, through the same validator, with its meaning compared.

    `divergence` says in words what the edit changed about the metric — a
    dataset added, a filter dropped, a denominator removed — and requires
    confirmation before anything proceeds. A reformatted query changes
    nothing and says nothing.
    """
    previous = MetricCode.from_dict(payload.previous) if payload.previous else None
    return flow.revise(_code(payload), period=payload.period,
                       edited_by_user=payload.edited, previous=previous)


@router.post("/approve", summary="Approve the code")
def approve_formula(payload: CodeIn,
                    principal: Principal = RequireAnalyst) -> dict:
    """§10. Revalidated first: an approval over code CreditProbe will not run
    is an approval of nothing."""
    return flow.approve(_code(payload), note=payload.note,
                        period=payload.period)


@router.post("/preview", summary="Run the approved code on real data")
def preview_formula(payload: CodeIn,
                    principal: Principal = RequireAnalyst) -> dict:
    """§12. The exact arithmetic: both periods, both figures, the division,
    the result, and the population behind each side."""
    try:
        return flow.preview(_code(payload), period=payload.period,
                            user_id=principal.user_id,
                            approved_checksum=payload.approved_checksum)
    except (flow.ApprovalRequired, flow.ApprovalStale) as e:
        raise _not_approved(e) from e


@router.post("/lock", summary="Store it as a governed metric")
def lock_formula(payload: CodeIn,
                 principal: Principal = RequireAnalyst) -> dict:
    """§13. Everything that was approved, persisted with the metric."""
    from backend.metrics import service

    try:
        return flow.lock(_code(payload), period=payload.period,
                         user_id=principal.user_id, shared=payload.shared,
                         approved_checksum=payload.approved_checksum,
                         require_preview=payload.require_preview)
    except (flow.ApprovalRequired, flow.ApprovalStale) as e:
        raise _not_approved(e) from e
    except service.MetricRefused as e:
        raise _refused(e) from e
    except service.StorageUnavailable as e:
        raise _unavailable(e) from e
