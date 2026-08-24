"""
The workspace: saved investigations, review, comments and notifications.

Everything here is about what happens AFTER an answer exists — keeping it,
bringing it up to date, sending it to someone, and being told when it comes
back. None of it computes anything; a refresh delegates to the same executor a
question does, so a refreshed figure is produced by the engine exactly as the
original was.

Roles are declared on every mutating endpoint. Saving, refreshing and reviewing
are analyst-level acts; reading is open to viewers. Archiving a saved
investigation removes it from what people rely on, so it needs a steward.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireAnalyst,
    RequireDataSteward,
    current_principal,
)
from backend.orchestration import investigations as inv
from backend.orchestration.executor import run_investigation
from backend.services import workflow as wf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspace", tags=["workspace"])

MAX_TEXT = 4000


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


# ========================================================== investigations


class SaveIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    title: str = Field(default="", max_length=300)
    project_id: int | None = None
    from_period: str | None = Field(default=None, max_length=64)
    to_period: str | None = Field(default=None, max_length=64)


class RefreshIn(BaseModel):
    from_period: str | None = Field(default=None, max_length=64)
    to_period: str | None = Field(default=None, max_length=64)


@router.get("/investigations", summary="Saved investigations")
def list_investigations(
    project_id: int | None = None,
    owner_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return {"investigations": inv.listing(project_id=project_id, owner_id=owner_id,
                                          limit=limit)}


@router.post("/investigations", status_code=201, summary="Save an answer")
def save_investigation(payload: SaveIn, principal: Principal = RequireAnalyst) -> dict:
    """Run the question and keep the answer as a saved investigation.

    The question is executed rather than trusted from the client: what gets saved
    has to be something IPM produced, not something a caller posted.
    """
    period = (
        (payload.from_period, payload.to_period)
        if payload.from_period and payload.to_period else None
    )
    result = run_investigation(
        payload.question, user_id=principal.user_id, project_id=payload.project_id,
        persist=True, period=period,
    )
    if result.status == "needs_clarification":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "needs_clarification",
                "message": "IPM needs the comparison period before it can answer, "
                           "so there is nothing to save yet.",
                "clarification": result.clarification.to_dict() if result.clarification else None,
            },
        )
    try:
        saved = inv.save(result, title=payload.title, project_id=payload.project_id,
                         user_id=principal.user_id)
    except inv.StorageUnavailable as e:
        raise _unavailable(e) from e
    return saved.to_dict()


@router.get("/investigations/{investigation_id}", summary="One saved investigation")
def get_investigation(investigation_id: int, version: int | None = None) -> dict:
    try:
        return inv.load(investigation_id, version).to_dict()
    except inv.InvestigationNotFound as e:
        raise _not_found(e) from e
    except inv.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/investigations/{investigation_id}/refresh",
             summary="Re-run and store the new answer")
def refresh_investigation(investigation_id: int, payload: RefreshIn,
                          principal: Principal = RequireAnalyst) -> dict:
    period = (
        (payload.from_period, payload.to_period)
        if payload.from_period and payload.to_period else None
    )
    try:
        return inv.refresh(investigation_id, user_id=principal.user_id,
                           period=period).to_dict()
    except inv.InvestigationNotFound as e:
        raise _not_found(e) from e
    except inv.StorageUnavailable as e:
        raise _unavailable(e) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "cannot_refresh", "message": str(e)},
        ) from e


@router.post("/investigations/{investigation_id}/archive", summary="Stop keeping it current")
def archive_investigation(investigation_id: int,
                          principal: Principal = RequireDataSteward) -> dict:
    try:
        return inv.archive(investigation_id).to_dict()
    except inv.InvestigationNotFound as e:
        raise _not_found(e) from e
    except inv.StorageUnavailable as e:
        raise _unavailable(e) from e


# ================================================================= workflow


class SubmitIn(BaseModel):
    object_type: str = Field(max_length=48)
    object_id: str = Field(max_length=120)
    title: str = Field(min_length=1, max_length=300)
    assigned_to: int | None = None
    note: str = Field(default="", max_length=MAX_TEXT)


class TransitionIn(BaseModel):
    to_state: str = Field(max_length=24)
    comment: str = Field(default="", max_length=MAX_TEXT)


@router.get("/workflow/inbox", summary="My work, what I sent, and what is done")
def workflow_inbox(principal: Principal = RequireAnalyst) -> dict:
    return {
        **wf.inbox(principal.user_id),
        "states": wf.STATE_LABEL,
        "reviewable": wf.REVIEWABLE,
    }


@router.post("/workflow", status_code=201, summary="Send something for review")
def submit_for_review(payload: SubmitIn, principal: Principal = RequireAnalyst) -> dict:
    try:
        return wf.submit(
            object_type=payload.object_type, object_id=payload.object_id,
            title=payload.title, assigned_to=payload.assigned_to,
            requested_by=principal.user_id, note=payload.note,
        ).to_dict()
    except wf.InvalidTransition as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "not_reviewable", "message": str(e)},
        ) from e
    except wf.WorkflowUnavailable as e:
        raise _unavailable(e) from e


@router.get("/workflow/{item_id}", summary="One review and its full history")
def get_workflow(item_id: int) -> dict:
    try:
        return wf.get(item_id).to_dict()
    except wf.WorkflowNotFound as e:
        raise _not_found(e) from e
    except wf.WorkflowUnavailable as e:
        raise _unavailable(e) from e


@router.post("/workflow/{item_id}/transition", summary="Approve, reject or take it up")
def move_workflow(item_id: int, payload: TransitionIn,
                  principal: Principal = RequireAnalyst) -> dict:
    try:
        return wf.transition(item_id, payload.to_state, actor_id=principal.user_id,
                             comment=payload.comment).to_dict()
    except wf.WorkflowNotFound as e:
        raise _not_found(e) from e
    except wf.InvalidTransition as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_transition", "message": str(e)},
        ) from e
    except wf.WorkflowUnavailable as e:
        raise _unavailable(e) from e


@router.get("/workflow/for/{object_type}/{object_id}",
            summary="Every review this object has been through")
def workflow_for_object(object_type: str, object_id: str) -> dict:
    return {"reviews": wf.for_object(object_type, object_id)}


# ================================================================= comments


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_TEXT)
    parent_id: int | None = None
    notify_user_id: int | None = None


@router.get("/comments/{object_type}/{object_id}", summary="Comments on one object")
def list_comments(object_type: str, object_id: str) -> dict:
    return {"comments": wf.comments(object_type, object_id)}


@router.post("/comments/{object_type}/{object_id}", status_code=201, summary="Comment")
def add_comment(object_type: str, object_id: str, payload: CommentIn,
                principal: Principal = RequireAnalyst) -> dict:
    try:
        return wf.comment(
            object_type=object_type, object_id=object_id, body=payload.body,
            author_id=principal.user_id, parent_id=payload.parent_id,
            notify_user_id=payload.notify_user_id,
        )
    except wf.WorkflowUnavailable as e:
        raise _unavailable(e) from e
    except ValueError as e:
        raise HTTPException(status_code=422,
                            detail={"error": "empty_comment", "message": str(e)}) from e


@router.post("/comments/{comment_id}/resolve", summary="Mark a comment resolved")
def resolve(comment_id: int, resolved: bool = True,
            principal: Principal = RequireAnalyst) -> dict:
    try:
        return wf.resolve_comment(comment_id, resolved=resolved)
    except wf.WorkflowNotFound as e:
        raise _not_found(e) from e
    except wf.WorkflowUnavailable as e:
        raise _unavailable(e) from e


# ============================================================ notifications


@router.get("/notifications", summary="What has happened that concerns me")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(current_principal),
) -> dict:
    return {
        "notifications": wf.notifications(principal.user_id, unread_only=unread_only,
                                          limit=limit),
        "unread": wf.unread_count(principal.user_id),
    }


@router.post("/notifications/read", summary="Mark notifications read")
def read_notifications(notification_id: int | None = None,
                       principal: Principal = RequireAnalyst) -> dict:
    if principal.user_id is None:
        # Nothing was ever addressed to an anonymous caller, so there is nothing
        # to mark. Saying so beats a silent success.
        return {"marked": 0, "unread": 0}
    try:
        marked = wf.mark_read(principal.user_id, notification_id)
    except wf.WorkflowUnavailable as e:
        raise _unavailable(e) from e
    return {"marked": marked, "unread": wf.unread_count(principal.user_id)}


__all__ = ["router"]
