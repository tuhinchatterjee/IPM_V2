"""HTTP surface of the What-If Analysis workspace (P5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import access, service, sharing, whatif

router = APIRouter(tags=["workspace-whatif"])


class Selection(BaseModel):
    mode: str = Field(pattern="^(rows|filtered|all)$")
    ids: list[str] = Field(default_factory=list, max_length=whatif.MAX_IDS)
    filters: list[dict[str, Any]] = Field(default_factory=list)


class SummaryBody(BaseModel):
    domain: str = Field(default="corporate", max_length=20)
    selection: Selection


class SaveBody(SummaryBody):
    name: str = Field(min_length=1, max_length=160)
    by_owner: bool = False


class CohortRef(BaseModel):
    cohort_id: str = Field(min_length=4, max_length=80)


class AdoptBody(BaseModel):
    name: str = Field(default="", max_length=160)


class AskContext(BaseModel):
    cohort_id: str = Field(default="", max_length=80)
    scenario_id: str = Field(default="", max_length=80)


class ShareBody(BaseModel):
    object_id: str = Field(min_length=4, max_length=80)
    to: list[str] = Field(min_length=1, max_length=20)
    message: str = Field(default="", max_length=2000)
    version: int | None = None


@router.get("/whatif/context")
async def whatif_context(domain: str = Query("corporate"),
                         who: dict[str, Any] = Depends(v4routes.principal)
                         ) -> dict[str, Any]:
    return whatif.context(who, domain)


@router.post("/whatif/selection/summary")
async def selection_summary(body: SummaryBody,
                            who: dict[str, Any] = Depends(v4routes.principal)
                            ) -> dict[str, Any]:
    return whatif.summary(access.book(who, body.domain),
                          body.selection.model_dump())


@router.post("/whatif/selection/cohort", status_code=201)
async def save_selection(body: SaveBody,
                         who: dict[str, Any] = Depends(v4routes.principal)
                         ) -> dict[str, Any]:
    return whatif.save_selection(access.book(who, body.domain), who,
                                 body.selection.model_dump(), name=body.name,
                                 by_owner=body.by_owner)


@router.post("/whatif/investigate", status_code=201)
async def investigate(body: CohortRef,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    return whatif.investigate(who, body.cohort_id)


@router.get("/whatif/threads/{thread_id}/cohort")
async def thread_cohort(thread_id: str,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    out = whatif.thread_cohort(who, thread_id)
    out.pop("_predicate", None)
    return out


@router.post("/whatif/threads/{thread_id}/adopt-cohort", status_code=201)
async def adopt_cohort(thread_id: str, body: AdoptBody,
                       who: dict[str, Any] = Depends(v4routes.principal)
                       ) -> dict[str, Any]:
    return whatif.adopt_thread_cohort(who, thread_id, name=body.name)


@router.post("/whatif/threads/{thread_id}/adopt-result", status_code=201)
async def adopt_result(thread_id: str,
                       who: dict[str, Any] = Depends(v4routes.principal)
                       ) -> dict[str, Any]:
    return whatif.adopt_thread_result(who, thread_id)


@router.post("/whatif/ask-context")
async def ask_context(body: AskContext,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    """The `ui_filters` block a What-If question carries into the run."""
    svc = service.objects()
    principal = service.principal(who)
    cohort = svc.get(body.cohort_id, principal) if body.cohort_id else None
    scenario = svc.get(body.scenario_id, principal) \
        if body.scenario_id else None
    return whatif.active_context(cohort, scenario)


@router.post("/share")
async def share_object(body: ShareBody,
                       who: dict[str, Any] = Depends(v4routes.principal)
                       ) -> dict[str, Any]:
    return sharing.share(service.objects(), service.principal(who),
                         body.object_id, to=body.to, message=body.message,
                         version=body.version)


__all__ = ["router"]
