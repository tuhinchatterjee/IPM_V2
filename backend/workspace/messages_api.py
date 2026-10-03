"""HTTP surface of Messages (P7): governed objects between people."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import messages, service, sharing
from backend.workspace.errors import GovernedRoute

router = APIRouter(tags=["workspace-messages"], route_class=GovernedRoute)


class Send(BaseModel):
    object_id: str = Field(min_length=4, max_length=80)
    to: list[str] = Field(min_length=1, max_length=20)
    message: str = Field(default="", max_length=2000)
    version: int | None = None


class RunBody(BaseModel):
    cohort_id: str = Field(default="", max_length=80)
    baseline: dict[str, Any] | None = None
    latest: bool = False


class CompareBody(BaseModel):
    with_result_ids: list[str] = Field(min_length=1, max_length=5)
    method: str = Field(default="", max_length=20)


class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.get("/messages")
async def inbox(box: str = Query("inbox", pattern="^(inbox|sent|all)$"),
                who: dict[str, Any] = Depends(v4routes.principal)
                ) -> dict[str, Any]:
    return messages.inbox(service.objects(), who, box=box)


@router.post("/messages", status_code=201)
async def send(body: Send, who: dict[str, Any] = Depends(v4routes.principal)
               ) -> dict[str, Any]:
    return sharing.share(service.objects(), service.principal(who),
                         body.object_id, to=body.to, message=body.message,
                         version=body.version)


@router.get("/messages/{share_id}")
async def detail(share_id: str,
                 who: dict[str, Any] = Depends(v4routes.principal)
                 ) -> dict[str, Any]:
    return messages.detail(service.objects(), who, share_id)


@router.post("/messages/{share_id}/run", status_code=201)
async def run(share_id: str, body: RunBody,
              who: dict[str, Any] = Depends(v4routes.principal)
              ) -> dict[str, Any]:
    return messages.run(service.objects(), who, share_id,
                        cohort_id=body.cohort_id, baseline=body.baseline,
                        latest=body.latest)


@router.post("/messages/{share_id}/duplicate", status_code=201)
async def duplicate(share_id: str,
                    who: dict[str, Any] = Depends(v4routes.principal)
                    ) -> dict[str, Any]:
    return messages.duplicate(service.objects(), who, share_id)


@router.post("/messages/{share_id}/save", status_code=201)
async def save(share_id: str,
               who: dict[str, Any] = Depends(v4routes.principal)
               ) -> dict[str, Any]:
    return messages.save(service.objects(), who, share_id)


@router.post("/messages/{share_id}/compare", status_code=201)
async def compare(share_id: str, body: CompareBody,
                  who: dict[str, Any] = Depends(v4routes.principal)
                  ) -> dict[str, Any]:
    return messages.compare(service.objects(), who, share_id,
                            body.with_result_ids, method=body.method)


@router.post("/messages/{share_id}/investigate", status_code=201)
async def investigate(share_id: str,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    return messages.investigate(service.objects(), who, share_id)


@router.post("/messages/{share_id}/whatif", status_code=201)
async def whatif_population(share_id: str,
                            who: dict[str, Any] = Depends(v4routes.principal)
                            ) -> dict[str, Any]:
    return messages.whatif_population(service.objects(), who, share_id)


@router.post("/messages/{share_id}/comments", status_code=201)
async def comment(share_id: str, body: CommentBody,
                  who: dict[str, Any] = Depends(v4routes.principal)
                  ) -> dict[str, Any]:
    return messages.comment(service.objects(), who, share_id, body.body)


__all__ = ["router"]
