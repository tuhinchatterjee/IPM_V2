"""HTTP surface of Lenses 2.0 (P9)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import lenses, service

router = APIRouter(tags=["workspace-lenses"])


class RenderBody(BaseModel):
    version: int | None = None
    periods: dict[str, str] = Field(default_factory=dict)
    cross_filters: list[dict[str, Any]] = Field(default_factory=list,
                                                max_length=12)


class ProposeBody(BaseModel):
    prompt: str = Field(default="", max_length=2000)
    base: dict[str, Any] | None = None
    domain: str = Field(default="", max_length=20)
    from_investigation: str = Field(default="", max_length=80)
    from_thread: str = Field(default="", max_length=80)


class SaveBody(BaseModel):
    spec: dict[str, Any]
    source: dict[str, Any] | None = None


class ReviseBody(BaseModel):
    changes: dict[str, Any]
    reason: str = Field(min_length=1, max_length=200)


@router.get("/lenses")
async def library(q: str = Query("", max_length=200),
                  persona: str = Query("", max_length=80),
                  domain: str = Query("", max_length=20),
                  who: dict[str, Any] = Depends(v4routes.principal)
                  ) -> dict[str, Any]:
    return lenses.listing(service.objects(), who, q=q, persona=persona,
                          domain=domain)


@router.post("/lenses/propose")
async def propose(body: ProposeBody,
                  who: dict[str, Any] = Depends(v4routes.principal)
                  ) -> dict[str, Any]:
    svc = service.objects()
    if body.from_investigation:
        return lenses.from_investigation(svc, who, body.from_investigation)
    if body.from_thread:
        return lenses.from_thread(svc, who, body.from_thread)
    return lenses.propose(who, body.prompt, base=body.base,
                          domain=body.domain)


@router.post("/lenses", status_code=201)
async def save(body: SaveBody,
               who: dict[str, Any] = Depends(v4routes.principal)
               ) -> dict[str, Any]:
    return lenses.save(service.objects(), who, body.spec, source=body.source)


@router.post("/lenses/{object_id}/render")
async def render(object_id: str, body: RenderBody,
                 who: dict[str, Any] = Depends(v4routes.principal)
                 ) -> dict[str, Any]:
    return lenses.render(service.objects(), who, object_id,
                         version=body.version, periods=body.periods,
                         cross=body.cross_filters)


@router.post("/lenses/{object_id}/refresh")
async def refresh(object_id: str,
                  who: dict[str, Any] = Depends(v4routes.principal)
                  ) -> dict[str, Any]:
    return lenses.refresh(service.objects(), who, object_id)


@router.get("/lenses/{object_id}/observations")
async def observations(object_id: str,
                       who: dict[str, Any] = Depends(v4routes.principal)
                       ) -> dict[str, Any]:
    return {"observations": lenses.history(service.objects(), who,
                                           object_id)}


@router.post("/lenses/{object_id}/revise")
async def revise(object_id: str, body: ReviseBody,
                 who: dict[str, Any] = Depends(v4routes.principal)
                 ) -> dict[str, Any]:
    return lenses.revise(service.objects(), who, object_id, body.changes,
                         reason=body.reason)


__all__ = ["router"]
