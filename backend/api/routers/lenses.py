"""
Lenses over HTTP.

A caller may define a lens, ask for a change to one, render it, and read its
revision history. A caller may not supply a figure or name an analysis the
Engine Registry does not have — the service refuses both, and says why.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst, RequireDataSteward
from backend.services import lenses as ln

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lenses", tags=["lenses"])

MAX_TEXT = 2000


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable", "message": str(exc)},
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)},
    )


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "invalid_lens", "message": str(exc)},
    )


class PanelIn(BaseModel):
    analysis_id: str = Field(min_length=1, max_length=120)
    title: str = Field(default="", max_length=200)
    visual: str = Field(default="auto", max_length=16)
    params: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)
    note: str = Field(default="", max_length=MAX_TEXT)


class LensIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=MAX_TEXT)
    audience: str = Field(default="", max_length=120)
    panels: list[PanelIn] = Field(default_factory=list)
    project_id: int | None = None


class AskIn(BaseModel):
    """A request in words. Applied only if `apply` is set."""

    request: str = Field(min_length=1, max_length=500)
    apply: bool = True


class StatusIn(BaseModel):
    status: str = Field(max_length=24)


@router.get("", summary="Lenses")
def list_lenses(status_filter: str | None = Query(default=None, alias="status")) -> dict:
    return {
        "lenses": ln.listing(status=status_filter),
        "visuals": list(ln.VISUALS),
        "statuses": list(ln.STATUSES),
        "max_panels": ln.MAX_PANELS,
    }


@router.post("", status_code=201, summary="Create a lens")
def create_lens(payload: LensIn, principal: Principal = RequireAnalyst) -> dict:
    try:
        return ln.create(
            name=payload.name,
            panels=[ln.Panel.from_dict(p.model_dump()) for p in payload.panels],
            description=payload.description, audience=payload.audience,
            project_id=payload.project_id, user_id=principal.user_id,
        ).to_dict()
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/build", status_code=201, summary="Build a lens by describing it")
def build_lens(payload: AskIn, principal: Principal = RequireAnalyst) -> dict:
    """Turn a description into a lens.

    The description is matched against the Engine Registry's own metadata, so it
    can only ever resolve to analyses that exist. Anything it asks for that the
    registry has nothing for comes back as a refusal with the reason.
    """
    try:
        proposal = ln.propose(payload.request)
    except ln.InvalidLens as e:
        raise _refused(e) from e
    if not proposal.panels:
        return {"lens": None, "proposal": proposal.to_dict()}
    if not payload.apply:
        return {"lens": None, "proposal": proposal.to_dict()}
    try:
        lens = ln.create(
            name=payload.request[:200], panels=proposal.panels,
            description=proposal.change_summary, origin="ai",
            request=payload.request, user_id=principal.user_id,
        )
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e
    return {"lens": lens.to_dict(), "proposal": proposal.to_dict()}


@router.get("/{lens_id}", summary="One lens and its revisions")
def get_lens(lens_id: int) -> dict:
    try:
        return ln.get(lens_id).to_dict()
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.get("/{lens_id}/render", summary="Run every panel now")
def render_lens(lens_id: int, period: str | None = None) -> dict:
    """A lens is what the book says today, not what it said when it was built."""
    try:
        return ln.render(lens_id, period=period)
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/{lens_id}/ask", summary="Change a lens by asking")
def ask_lens(lens_id: int, payload: AskIn,
             principal: Principal = RequireAnalyst) -> dict:
    """"Add the sector breakdown", "drop the stress panel".

    Every applied change is a new revision with a sentence saying what changed,
    and the previous one is kept so it can be put back.
    """
    try:
        current = [ln.Panel.from_dict(p) for p in ln.get(lens_id).panels]
        proposal = ln.propose(payload.request, existing=current)
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e

    if not payload.apply or not proposal.change_summary:
        return {"lens": ln.get(lens_id).to_dict(), "proposal": proposal.to_dict()}

    try:
        lens = ln.revise(
            lens_id, proposal.panels, request=payload.request,
            change_summary=proposal.change_summary, user_id=principal.user_id,
        )
    except ln.InvalidLens as e:
        raise _refused(e) from e
    return {"lens": lens.to_dict(), "proposal": proposal.to_dict()}


@router.post("/{lens_id}/restore/{version}", summary="Put back an earlier version")
def restore_lens(lens_id: int, version: int,
                 principal: Principal = RequireAnalyst) -> dict:
    try:
        return ln.restore(lens_id, version, user_id=principal.user_id).to_dict()
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/{lens_id}/status", summary="Publish or archive a lens")
def set_lens_status(lens_id: int, payload: StatusIn,
                    principal: Principal = RequireAnalyst) -> dict:
    try:
        return ln.set_status(lens_id, payload.status).to_dict()
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.delete("/{lens_id}", status_code=204, summary="Delete a lens")
def delete_lens(lens_id: int, principal: Principal = RequireDataSteward) -> None:
    try:
        ln.delete(lens_id)
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


__all__ = ["router"]
