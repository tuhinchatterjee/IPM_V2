"""
Playbooks over HTTP.

A caller may define a playbook, run it, and read what it found. A caller may not
supply a result, a figure, or an analysis that is not registered — the service
refuses each of those, and the refusal says why.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst, RequireDataSteward
from backend.services import playbooks as pb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playbooks", tags=["playbooks"])

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
        detail={"error": "invalid_playbook", "message": str(exc)},
    )


class AnalysisStep(BaseModel):
    analysis_id: str = Field(min_length=1, max_length=120)
    params: dict = Field(default_factory=dict)


class Condition(BaseModel):
    metric: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=200)
    operator: str = Field(max_length=4)
    threshold: float
    unit: str = Field(default="", max_length=24)
    severity: str = Field(default="warning", max_length=16)


class Actions(BaseModel):
    create_investigation: bool = False
    notify: list[int] = Field(default_factory=list)


class PlaybookIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=MAX_TEXT)
    trigger: str = Field(default=pb.TRIGGER_MANUAL, max_length=32)
    schedule: str = Field(default="", max_length=64)
    scope: dict = Field(default_factory=dict)
    analyses: list[AnalysisStep] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    actions: Actions = Field(default_factory=Actions)
    owner: str = Field(default="", max_length=160)


class PlaybookPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_TEXT)
    trigger: str | None = Field(default=None, max_length=32)
    schedule: str | None = Field(default=None, max_length=64)
    scope: dict | None = None
    analyses: list[AnalysisStep] | None = None
    conditions: list[Condition] | None = None
    actions: Actions | None = None
    owner: str | None = Field(default=None, max_length=160)


class StatusIn(BaseModel):
    status: str = Field(max_length=24)


class RunIn(BaseModel):
    period: str | None = Field(default=None, max_length=64)


@router.get("", summary="Playbooks")
def list_playbooks(status_filter: str | None = Query(default=None, alias="status")) -> dict:
    return {
        "playbooks": pb.listing(status=status_filter),
        "triggers": pb.TRIGGER_LABEL,
        "operators": pb.OPERATOR_LABEL,
        "severities": list(pb.SEVERITIES),
        "scope_dimensions": list(pb.SCOPE_DIMENSIONS),
        "statuses": list(pb.STATUSES),
    }


@router.post("", status_code=201, summary="Define a playbook")
def create_playbook(payload: PlaybookIn,
                    principal: Principal = RequireAnalyst) -> dict:
    try:
        return pb.create(
            name=payload.name, description=payload.description,
            trigger=payload.trigger, schedule=payload.schedule,
            scope=payload.scope,
            analyses=[a.model_dump() for a in payload.analyses],
            conditions=[c.model_dump() for c in payload.conditions],
            actions=payload.actions.model_dump(),
            owner=payload.owner, user_id=principal.user_id,
        ).to_dict()
    except pb.InvalidPlaybook as e:
        raise _refused(e) from e
    except pb.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.get("/{playbook_id}", summary="One playbook and its last run")
def get_playbook(playbook_id: int) -> dict:
    try:
        return pb.get(playbook_id).to_dict()
    except pb.PlaybookNotFound as e:
        raise _not_found(e) from e
    except pb.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.patch("/{playbook_id}", summary="Edit a playbook")
def update_playbook(playbook_id: int, payload: PlaybookPatch,
                    principal: Principal = RequireAnalyst) -> dict:
    changes = payload.model_dump(exclude_none=True)
    if "analyses" in changes:
        changes["analyses"] = [dict(a) for a in changes["analyses"]]
    if "conditions" in changes:
        changes["conditions"] = [dict(c) for c in changes["conditions"]]
    try:
        return pb.update(playbook_id, **changes).to_dict()
    except pb.PlaybookNotFound as e:
        raise _not_found(e) from e
    except pb.InvalidPlaybook as e:
        raise _refused(e) from e
    except pb.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/{playbook_id}/status", summary="Activate or pause a playbook")
def set_playbook_status(playbook_id: int, payload: StatusIn,
                        principal: Principal = RequireAnalyst) -> dict:
    try:
        return pb.set_status(playbook_id, payload.status).to_dict()
    except pb.PlaybookNotFound as e:
        raise _not_found(e) from e
    except pb.InvalidPlaybook as e:
        raise _refused(e) from e
    except pb.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/{playbook_id}/run", summary="Run a playbook now")
def run_playbook(playbook_id: int, payload: RunIn,
                 principal: Principal = RequireAnalyst) -> dict:
    """Execute the analyses, test the conditions, take the actions.

    The analyses go through the ordinary engine runner, so every figure carries
    a Trace exactly as it would if somebody had asked for it by hand.
    """
    try:
        return pb.run(playbook_id, period=payload.period,
                      user_id=principal.user_id).to_dict()
    except pb.PlaybookNotFound as e:
        raise _not_found(e) from e
    except pb.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.get("/{playbook_id}/runs", summary="What this playbook has found before")
def playbook_runs(playbook_id: int,
                  limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return {"runs": pb.runs(playbook_id, limit=limit)}


@router.delete("/{playbook_id}", status_code=204, summary="Delete a playbook")
def delete_playbook(playbook_id: int,
                    principal: Principal = RequireDataSteward) -> None:
    try:
        pb.delete(playbook_id)
    except pb.PlaybookNotFound as e:
        raise _not_found(e) from e
    except pb.StorageUnavailable as e:
        raise _unavailable(e) from e


__all__ = ["router"]
