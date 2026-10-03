"""
HTTP surface for the shared governed objects: cohorts, findings,
investigations, and the generic read/history/lineage/comment verbs every
object kind shares. Scenario, Lens, alert and message routes live beside this
in their own modules but reach the same `ObjectService`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import access, cohorts, grid, service
from backend.workspace.errors import GovernedRoute
from backend.workspace.objects import KINDS

router = APIRouter(tags=["workspace-objects"], route_class=GovernedRoute)


class FreezeCohort(BaseModel):
    domain: str = Field(default="corporate", max_length=20)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    selection: str = Field(default="row", pattern="^(row|owner)$")
    source: dict[str, Any] = Field(default_factory=lambda: {"kind": "manual"})
    snapshot: bool = False
    tags: list[str] = Field(default_factory=list)


@router.post("/cohorts")
async def freeze_cohort(body: FreezeCohort,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    book = access.book(who, body.domain)
    return cohorts.freeze(
        book, service.objects(), service.principal(who), name=body.name,
        filters=body.filters, selection=body.selection, source=body.source,
        snapshot=body.snapshot, description=body.description, tags=body.tags)


@router.get("/cohorts")
async def list_cohorts(domain: str = Query(""),
                       who: dict[str, Any] = Depends(v4routes.principal)
                       ) -> dict[str, Any]:
    domain_id = access.parse_domain(domain) if domain else ""
    svc = service.objects()
    items = svc.list("cohort", service.principal(who), domain_id=domain_id)
    return {"cohorts": [{**svc.summary(o), "counts": o["body"]["counts"],
                         "ead": o["body"]["ead"], "ecl": o["body"]["ecl"],
                         "filter_description": o["body"].get(
                             "filter_description", ""),
                         "source": o["body"].get("source", {})}
                        for o in items]}


@router.get("/cohorts/{object_id}/verify")
async def verify_cohort(object_id: str,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    cohort = service.objects().get(object_id, service.principal(who))
    book = access.book(who, cohort["domain_id"])
    return cohorts.verify(book, cohort)


@router.post("/cohorts/{object_id}/refresh")
async def refresh_cohort(object_id: str,
                         who: dict[str, Any] = Depends(v4routes.principal)
                         ) -> dict[str, Any]:
    svc = service.objects()
    principal = service.principal(who)
    cohort = svc.get(object_id, principal)
    book = access.book(who, cohort["domain_id"])
    return cohorts.refresh(book, svc, principal, cohort)


@router.get("/cohorts/{object_id}/rows")
async def cohort_rows(object_id: str, offset: int = Query(0, ge=0),
                      limit: int = Query(50, ge=1, le=500),
                      version: int | None = Query(None),
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    """The cohort's rows, re-read through the READER's own book session."""
    cohort = service.objects().get(object_id, service.principal(who),
                                   version=version)
    book = access.book(who, cohort["domain_id"])
    body = cohort["body"]
    filters = body["filters"]
    if body["selection"] == "owner":
        owner = grid.SPEC[book.domain_id]["owner"]
        ids = sorted({str(r.get(owner)) for r in grid.rows_for(
            book, filters=filters, period=body["period"],
            columns=[owner])[2]})
        filters = [{"column": owner, "op": "in", "values": ids[:500]}]
    return grid.query(book, filters=filters, offset=offset, limit=limit,
                      period=body["period"])


class NewObject(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    domain: str = Field(default="", max_length=20)
    body: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)


@router.post("/objects/{kind}")
async def create_object(kind: str, payload: NewObject,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    if kind not in ("finding", "investigation"):
        raise HTTPException(400, {
            "error_code": "USE_THE_KIND_ROUTE",
            "message": f"a {kind} is created through its own workspace "
                       f"route, which validates it against the engine."})
    domain_id = access.parse_domain(payload.domain) if payload.domain else ""
    book = access.book(who, domain_id) if domain_id else None
    return service.objects().create(
        kind, service.principal(who), payload.body, title=payload.title,
        domain_id=domain_id,
        release_id=book.release_id if book else "",
        fingerprint=book.fingerprint if book else "",
        period=book.latest_period if book else "", tags=payload.tags,
        trace_refs=payload.trace_refs)


@router.get("/objects/{object_id}")
async def get_object(object_id: str, version: int | None = Query(None),
                     who: dict[str, Any] = Depends(v4routes.principal)
                     ) -> dict[str, Any]:
    return service.objects().get(object_id, service.principal(who),
                                 version=version)


@router.get("/objects/{object_id}/history")
async def object_history(object_id: str,
                         who: dict[str, Any] = Depends(v4routes.principal)
                         ) -> dict[str, Any]:
    svc = service.objects()
    return {"versions": [svc.summary(v) | {"lineage": v["lineage"]}
                         for v in svc.history(object_id,
                                              service.principal(who))]}


@router.get("/objects/{object_id}/lineage")
async def object_lineage(object_id: str,
                         who: dict[str, Any] = Depends(v4routes.principal)
                         ) -> dict[str, Any]:
    return service.objects().lineage_tree(object_id, service.principal(who))


class Comment(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    version: int | None = None


@router.post("/objects/{object_id}/comments")
async def comment(object_id: str, payload: Comment,
                  who: dict[str, Any] = Depends(v4routes.principal)
                  ) -> dict[str, Any]:
    principal = service.principal(who)
    obj = service.objects().get(object_id, principal,
                                version=payload.version)
    return service.store().add_comment(
        tenant_id=principal.tenant, object_id=object_id,
        version=obj["version"], author_id=principal.id, body=payload.body)


@router.get("/objects/{object_id}/comments")
async def comments(object_id: str,
                   who: dict[str, Any] = Depends(v4routes.principal)
                   ) -> dict[str, Any]:
    principal = service.principal(who)
    service.objects().get(object_id, principal)
    return {"comments": service.store().comments(object_id,
                                                 tenant_id=principal.tenant)}


@router.get("/kinds")
async def kinds() -> dict[str, Any]:
    return {"kinds": sorted(KINDS)}


__all__ = ["router"]
