"""
Analysis Studio over HTTP.

Browse the method library, read a method and everything behind it, build a new
one from a description, run its validation pack, download that pack as a
workbook, fork a method, and — only when the evidence is there — certify it.

Two refusals are load-bearing and both return 422 with the reason:

  * a description CreditProbe cannot read produces the question it needs
    answered, never a guess at what was meant;
  * certification of a method whose pack has not passed is refused with every
    outstanding requirement listed, not the first one.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAdmin, RequireAnalyst
from backend.studio import service
from backend.studio.model import Category, Lifecycle
from backend.studio.registry import MethodNotFound, get_registry, reload_registry
from backend.studio.validation import build_forward_rate_pack, run_pack
from backend.studio.workbook import SHEETS, build_workbook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/studio", tags=["studio"])

MAX_TEXT = 4000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "refused", "message": str(exc)},
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)},
    )


class DescribeIn(BaseModel):
    description: str = Field(min_length=1, max_length=MAX_TEXT)


class BuildIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=MAX_TEXT)
    answers: dict[str, str] = Field(default_factory=dict)
    opening_period: str = Field(min_length=1, max_length=32)
    closing_period: str = Field(min_length=1, max_length=32)
    dataset: str = Field(default="portfolio_facility", max_length=160)
    method_id: str = Field(default="", max_length=160)
    #: Store it. Off by default: building is exploration, saving is a decision.
    save: bool = False


class CertifyIn(BaseModel):
    certified_by: str = Field(min_length=1, max_length=160)


class ForkIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    method_id: str = Field(default="", max_length=160)


class EditIn(BaseModel):
    changes: dict[str, str] = Field(default_factory=dict)
    change_note: str = Field(default="", max_length=MAX_TEXT)


# ------------------------------------------------------------------- library


@router.get("", summary="The method library")
def library(q: str = Query(default="", max_length=200),
            category: str = Query(default="", max_length=80),
            lifecycle: str = Query(default="", max_length=32),
            certified_only: bool = False,
            runnable_only: bool = False,
            limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    registry = get_registry()
    found = registry.search(q, category=category, lifecycle=lifecycle,
                            certified_only=certified_only,
                            runnable_only=runnable_only)
    return {
        "methods": [m.to_dict(full=False) for m in found[:limit]],
        "total_matched": len(found),
        "categories": registry.categories(),
        "lifecycles": [{"id": str(state), "label": state.name.title()}
                       for state in Lifecycle],
        "all_categories": [str(c) for c in Category],
        "stats": registry.stats(),
    }


@router.get("/certification", summary="Which claims were upheld, and which were not")
def certification() -> dict:
    """The audit behind the tick.

    Exposed rather than logged: "which methods claim certification, and on what
    evidence" is a question a model validation team asks, and the answer should
    not require reading source.
    """
    return get_registry().audit().to_dict()


@router.post("/reload", summary="Re-read the library and re-verify every claim")
def reload(principal: Principal = RequireAdmin) -> dict:
    return reload_registry().stats()


@router.get("/clarifications", summary="The decisions a forward rate has to make")
def clarifications() -> dict:
    from backend.studio.builder import FORWARD_RATE_CLARIFICATIONS

    return {"clarifications": [c.to_dict() for c in FORWARD_RATE_CLARIFICATIONS]}


# --------------------------------------------------------------- building


@router.post("/describe", summary="Read a description back before building it")
def describe(payload: DescribeIn, principal: Principal = RequireAnalyst) -> dict:
    reading = service.describe(payload.description)
    return {"reading": reading.to_dict()}


@router.post("/build", summary="Build a method and run its validation pack")
def build(payload: BuildIn, principal: Principal = RequireAnalyst) -> dict:
    try:
        method, pack = service.build(
            name=payload.name, description=payload.description,
            answers=payload.answers, opening_period=payload.opening_period,
            closing_period=payload.closing_period, dataset=payload.dataset,
            author=str(principal.user_id or ""), method_id=payload.method_id,
        )
    except service.StudioError as e:
        raise _refused(e) from e

    stored = False
    if payload.save:
        stored = service.save(method, user_id=principal.user_id)
    return {
        "method": method.to_dict(),
        "validation": pack.to_dict(),
        "saved": payload.save,
        "persisted": stored,
        "storage_note": ("" if stored or not payload.save else
                         "Saved for this session only — the Studio is running "
                         "without a database, so this method will not survive a "
                         "restart."),
    }


@router.get("/{method_id}", summary="One method, in full")
def get_method(method_id: str) -> dict:
    try:
        method = get_registry().get(method_id)
    except MethodNotFound as e:
        raise _not_found(e) from e
    return {"method": method.to_dict()}


@router.post("/{method_id}/validate", summary="Run the validation pack again")
def validate(method_id: str, principal: Principal = RequireAnalyst) -> dict:
    try:
        method = service.load(method_id)
    except service.StudioError as e:
        raise _not_found(e) from e
    if not method.plan:
        raise _refused(ValueError(
            "This method has no Analytical IR plan to run. Methods implemented "
            "by a certified engine analysis are validated with that analysis."))
    pack = service.revalidate(method)
    return {"method": method.to_dict(), "validation": pack.to_dict()}


@router.get("/{method_id}/validation-pack.xlsx",
            summary="Download the validation pack as a workbook")
def validation_pack(method_id: str, run: bool = True,
                    principal: Principal = RequireAnalyst) -> Response:
    try:
        method = service.load(method_id)
    except service.StudioError as e:
        raise _not_found(e) from e
    if not method.plan:
        raise _refused(ValueError(
            "A validation pack is built from an Analytical IR plan and this "
            "method does not have one."))

    pack = build_forward_rate_pack(method)
    if run:
        pack = run_pack(pack, method)
    workbook = build_workbook(method, pack,
                              generated_by=str(principal.user_id or ""))
    filename = f"{method.id}_validation_pack.xlsx"
    return Response(
        content=workbook, media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-CreditProbe-Sheets": ",".join(SHEETS)},
    )


@router.post("/{method_id}/certify", summary="Award CreditProbe Certified")
def certify(method_id: str, payload: CertifyIn,
            principal: Principal = RequireAdmin) -> dict:
    """Deliberately the narrowest permission in the Studio.

    A data steward may publish data and an analyst may build and run anything.
    Neither may decide that a method is the bank's certified way of measuring
    something.
    """
    try:
        method = service.load(method_id)
        service.certify(method, by=payload.certified_by)
    except service.StudioError as e:
        raise _refused(e) from e
    stored = service.save(method, user_id=principal.user_id)
    return {"method": method.to_dict(), "persisted": stored}


@router.post("/{method_id}/fork", status_code=201, summary="Fork a method")
def fork(method_id: str, payload: ForkIn,
         principal: Principal = RequireAnalyst) -> dict:
    try:
        source = service.load(method_id)
        copy = service.fork(source, name=payload.name,
                            by=str(principal.user_id or ""),
                            method_id=payload.method_id)
    except service.StudioError as e:
        raise _refused(e) from e
    stored = service.save(copy, user_id=principal.user_id)
    return {
        "method": copy.to_dict(), "forked_from": source.id, "persisted": stored,
        "note": ("The fork starts as a draft with no certification and no test "
                 "results, however certified its source was. Run its validation "
                 "pack before relying on it."),
    }


@router.post("/{method_id}/edit", summary="Edit a method's prose")
def edit(method_id: str, payload: EditIn,
         principal: Principal = RequireAnalyst) -> dict:
    try:
        method = service.load(method_id)
        method, diff = service.edit(method, dict(payload.changes),
                                    change_note=payload.change_note,
                                    by=str(principal.user_id or ""))
    except service.StudioError as e:
        raise _refused(e) from e
    stored = service.save(method, user_id=principal.user_id)
    return {"method": method.to_dict(), "changes": diff, "persisted": stored}
