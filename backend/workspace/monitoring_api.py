"""HTTP surface of the Monitoring Centre (P10)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import lenses, monitoring, service
from backend.workspace.errors import GovernedRoute

router = APIRouter(tags=["workspace-monitoring"], route_class=GovernedRoute)


class ActBody(BaseModel):
    note: str = Field(default="", max_length=2000)
    assignee: str = Field(default="", max_length=120)


class FollowBody(BaseModel):
    on: bool = True


#: An unknown view, severity or book is refused (422), never silently read
#: as "everything".
_VIEW_PATTERN = f"^({'|'.join(monitoring.VIEWS)})$"
_SEVERITY_PATTERN = f"^(|{'|'.join(monitoring.SEVERITY_ORDER)})$"


@router.get("/monitoring")
async def centre(view: str = Query("active", pattern=_VIEW_PATTERN),
                 severity: str = Query("", pattern=_SEVERITY_PATTERN),
                 lens: str = Query("", max_length=80),
                 domain: str = Query("", pattern="^(|corporate|retail)$"),
                 assignee: str = Query("", max_length=120),
                 who: dict[str, Any] = Depends(v4routes.principal)
                 ) -> dict[str, Any]:
    monitoring.ensure_scheduler()
    return monitoring.listing(service.objects(), who, view=view,
                              severity=severity, lens_id=lens, domain=domain,
                              assignee=assignee)


@router.get("/monitoring/alerts/{alert_id}")
async def alert(alert_id: str,
                who: dict[str, Any] = Depends(v4routes.principal)
                ) -> dict[str, Any]:
    return monitoring.detail(service.objects(), who, alert_id)


@router.post("/monitoring/alerts/{alert_id}/investigate", status_code=201)
async def investigate(alert_id: str,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    return monitoring.investigate(service.objects(), who, alert_id)


@router.post("/monitoring/alerts/{alert_id}/cohort", status_code=201)
async def cohort(alert_id: str,
                 who: dict[str, Any] = Depends(v4routes.principal)
                 ) -> dict[str, Any]:
    return monitoring.cohort_for(service.objects(), who, alert_id)


@router.post("/monitoring/alerts/{alert_id}/{action}")
async def act(alert_id: str, action: str, body: ActBody,
              who: dict[str, Any] = Depends(v4routes.principal)
              ) -> dict[str, Any]:
    return monitoring.act(service.objects(), who, alert_id, action,
                          note=body.note, assignee=body.assignee)


@router.post("/monitoring/tick")
async def tick(who: dict[str, Any] = Depends(v4routes.principal)
               ) -> dict[str, Any]:
    """Refresh every Lens that is due now (the scheduler's own step)."""
    svc = service.objects()
    monitoring.ensure_seeded(svc, who)
    return monitoring.tick(svc, tenants=[service.principal(who).tenant])


@router.post("/lenses/{object_id}/follow")
async def follow(object_id: str, body: FollowBody,
                 who: dict[str, Any] = Depends(v4routes.principal)
                 ) -> dict[str, Any]:
    svc = service.objects()
    p = service.principal(who)
    svc.get(object_id, p)
    svc.store.subscribe(tenant_id=p.tenant, object_id=object_id,
                        user_id=p.id, on=body.on)
    return {"following": body.on,
            "followers": svc.store.subscribers(object_id,
                                               tenant_id=p.tenant)}


@router.post("/lenses/{object_id}/refresh-and-alert")
async def refresh_and_alert(object_id: str,
                            who: dict[str, Any] = Depends(v4routes.principal)
                            ) -> dict[str, Any]:
    svc = service.objects()
    obs = lenses.refresh(svc, who, object_id)
    return {"observation": obs,
            "alerts": monitoring.after_refresh(svc, who, object_id, obs)}


__all__ = ["router"]
