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
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireAnalyst,
    RequireCommenter,
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
    has to be something CreditProbe produced, not something a caller posted.
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
                "message": "CreditProbe needs the comparison period before it can answer, "
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
    """Send an object to people and/or teams, for a named action. §43, §44.

    `assigned_to` is kept for callers written before multi-recipient; when both
    it and `recipients` are given, it is folded in rather than ignored, because
    silently dropping a recipient is the failure that would go unnoticed.
    """

    object_type: str = Field(max_length=48)
    object_id: str = Field(max_length=120)
    object_version: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    assigned_to: int | None = None
    recipients: list[int] = Field(default_factory=list)
    teams: list[int] = Field(default_factory=list)
    action: str = Field(default="review", max_length=24)
    priority: str = Field(default="normal", max_length=12)
    due_at: datetime | None = None
    note: str = Field(default="", max_length=MAX_TEXT)

    def people(self) -> list[int]:
        return ([self.assigned_to] if self.assigned_to else []) + list(self.recipients)


class MessageIn(BaseModel):
    """One message in a workflow conversation. §45."""

    body: str = Field(min_length=1, max_length=MAX_TEXT)
    parent_id: int | None = None
    #: `[{"user_id": 4}, {"team_id": 2}]` — who is being named.
    mentions: list[dict] = Field(default_factory=list)
    #: `[{"type": "investigation", "id": "12", "label": "Contracting"}]`
    attachments: list[dict] = Field(default_factory=list)


class ResolveIn(BaseModel):
    resolved: bool = True


class TransitionIn(BaseModel):
    to_state: str = Field(max_length=24)
    comment: str = Field(default="", max_length=MAX_TEXT)


@router.get("/workflow/inbox", summary="Assigned, sent, mentions, due soon, done")
def workflow_inbox(principal: Principal = RequireCommenter) -> dict:
    return {
        **wf.inbox(principal.user_id),
        "states": wf.STATE_LABEL,
        "actions": wf.ACTION_LABEL,
        "reviewable": wf.REVIEWABLE,
    }


@router.post("/workflow", status_code=201, summary="Send something for review")
def submit_for_review(payload: SubmitIn, principal: Principal = RequireAnalyst) -> dict:
    try:
        return wf.send(
            object_type=payload.object_type, object_id=payload.object_id,
            object_version=payload.object_version,
            title=payload.title, recipients=payload.people(),
            teams=payload.teams, requested_by=principal.user_id,
            action=payload.action, message=payload.note,
            priority=payload.priority, due_at=payload.due_at,
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


@router.post("/workflow/{item_id}/opened",
             summary="Record that a recipient has looked at it")
def open_workflow(item_id: int, principal: Principal = RequireCommenter) -> dict:
    """§44's OPENED, as an observation rather than a claim.

    Called by the screen that shows the item. Idempotent: opening twice stamps
    once, and an item already in review does not go backwards because somebody
    reloaded the page.
    """
    try:
        return wf.opened(item_id, user_id=principal.user_id).to_dict()
    except wf.WorkflowNotFound as e:
        raise _not_found(e) from e
    except wf.WorkflowUnavailable as e:
        raise _unavailable(e) from e


@router.post("/workflow/{item_id}/messages", status_code=201,
             summary="Say something about this item")
def add_workflow_message(item_id: int, payload: MessageIn,
                         principal: Principal = RequireCommenter) -> dict:
    """§45. Internal only — no external email is sent, by design.

    Open to a Viewer for the same reason commenting is: an object sent to
    somebody for comment has to be answerable by them.
    """
    try:
        return wf.say(
            item_id, body=payload.body, author_id=principal.user_id,
            parent_id=payload.parent_id, mentions=payload.mentions,
            attachments=payload.attachments,
        )
    except wf.WorkflowNotFound as e:
        raise _not_found(e) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "empty_message", "message": str(e)},
        ) from e
    except wf.WorkflowUnavailable as e:
        raise _unavailable(e) from e


@router.post("/workflow/messages/{message_id}/resolve",
             summary="Mark a workflow message resolved")
def resolve_workflow_message(message_id: int, payload: ResolveIn,
                             principal: Principal = RequireCommenter) -> dict:
    try:
        return wf.resolve_message(message_id, resolved=payload.resolved)
    except wf.WorkflowNotFound as e:
        raise _not_found(e) from e
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
                principal: Principal = RequireCommenter) -> dict:
    """§50: a Viewer may comment. It is the one write a Viewer has.

    Sending somebody an object and asking them to comment on it, and then
    refusing their reply, is the failure this prevents — and it would have gone
    unnoticed, because the request would simply have looked unanswered.
    """
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


# ============================================================== documents
#
# §19. Work → Documents rendered a hard-coded array of three objects from
# `frontend/src/lib/demo.ts` before this: nothing stored, nothing editable,
# nothing downloadable, and the same three titles with the same dates on
# every installation whatever the book underneath had done.


def _doc_session():
    """A transactional session per request, committed on success."""
    from backend.config import settings
    from backend.db.engine import SessionLocal

    if not settings.has_database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "database_unavailable",
                    "message": ("Documents are kept in PostgreSQL, and this "
                                "deployment has none configured.")})
    handle = SessionLocal()
    try:
        yield handle
        handle.commit()
    except Exception:
        handle.rollback()
        raise
    finally:
        handle.close()


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    kind: str = Field(default="", max_length=120)
    product: str = Field(default="", max_length=48)
    summary: str = Field(default="", max_length=4000)
    body: str = Field(default="", max_length=400_000)
    as_of: str = Field(default="", max_length=32)
    project_id: int | None = None
    evidence: list[dict] = Field(default_factory=list)


class DocumentSaveIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    kind: str | None = Field(default=None, max_length=120)
    product: str | None = Field(default=None, max_length=48)
    summary: str | None = Field(default=None, max_length=4000)
    body: str | None = Field(default=None, max_length=400_000)
    as_of: str | None = Field(default=None, max_length=32)
    project_id: int | None = None
    evidence: list[dict] | None = None


@router.get("/documents", summary="Every current document")
def list_documents(product: str = Query(""), status_filter: str = Query(
                       "", alias="status"),
                   kind: str = Query(""), owner: str = Query(""),
                   project_id: int | None = Query(None),
                   search: str = Query(""),
                   include_historical: bool = Query(False),
                   limit: int = Query(100, ge=1, le=300),
                   principal: Principal = Depends(current_principal),
                   session=Depends(_doc_session)) -> dict:
    from backend.services import documents as docs

    rows = docs.listing(
        session, product=product, status=status_filter, kind=kind,
        owner=owner, project_id=project_id, search=search,
        current_only=not include_historical, limit=limit)
    return {
        "documents": [docs.header(session, row) for row in rows],
        "facets": docs.facets(session),
        "documents_version": docs.DOCUMENTS_VERSION,
    }


@router.post("/documents", status_code=201, summary="Write a new document")
def create_document(payload: DocumentIn,
                    principal: Principal = RequireAnalyst,
                    session=Depends(_doc_session)) -> dict:
    from backend.services import documents as docs

    try:
        row = docs.create(
            session, title=payload.title, kind=payload.kind,
            product=payload.product, summary=payload.summary,
            body=payload.body, as_of=payload.as_of,
            project_id=payload.project_id,
            owner_id=getattr(principal, "user_id", None),
            owner_name=(getattr(principal, "username", "") or ""),
            evidence=payload.evidence)
    except docs.DocumentError as e:
        raise HTTPException(status_code=422, detail={
            "error": "document_refused", "message": str(e)}) from e
    return docs.body_of(session, row)


@router.get("/documents/attachments/{attachment_id}",
            summary="Download one supporting file")
def download_attachment(attachment_id: int,
                        principal: Principal = Depends(current_principal),
                        session=Depends(_doc_session)):
    """Keyed on an integer id and nothing else.

    §19: do not expose internal filesystem paths as downloads. The bytes
    live in the row, so there is no path in the URL for anybody to
    traverse — the stored filename is used only in the Content-Disposition
    header, with its quotes and line breaks stripped.
    """
    from fastapi import Response

    from backend.services import documents as docs

    try:
        one = docs.attachment(session, attachment_id)
    except docs.NotFound as e:
        raise _not_found(e) from e
    safe = "".join(c for c in one.filename
                   if c.isalnum() or c in "-_. ()").strip() or "attachment"
    return Response(
        content=one.content, media_type=one.content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.get("/documents/{document_id}", summary="One document, whole")
def read_document(document_id: int,
                  principal: Principal = Depends(current_principal),
                  session=Depends(_doc_session)) -> dict:
    from backend.services import documents as docs

    try:
        return docs.body_of(session, docs.get(session, document_id))
    except docs.NotFound as e:
        raise _not_found(e) from e


@router.patch("/documents/{document_id}", summary="Save a draft")
def save_document(document_id: int, payload: DocumentSaveIn,
                  principal: Principal = RequireAnalyst,
                  session=Depends(_doc_session)) -> dict:
    """Autosave and manual save land here. An approved revision refuses."""
    from backend.services import documents as docs

    try:
        row = docs.save(
            session, document_id, title=payload.title, body=payload.body,
            summary=payload.summary, kind=payload.kind,
            product=payload.product, as_of=payload.as_of,
            project_id=payload.project_id, evidence=payload.evidence)
    except docs.Immutable as e:
        raise HTTPException(status_code=409, detail={
            "error": "approved_record", "message": str(e)}) from e
    except docs.NotFound as e:
        raise _not_found(e) from e
    return docs.body_of(session, row)


@router.post("/documents/{document_id}/revisions",
             summary="Create a new draft revision")
def revise_document(document_id: int,
                    principal: Principal = RequireAnalyst,
                    session=Depends(_doc_session)) -> dict:
    from backend.services import documents as docs

    try:
        row = docs.revise(
            session, document_id,
            owner_id=getattr(principal, "user_id", None),
            owner_name=(getattr(principal, "username", "") or ""))
    except docs.NotFound as e:
        raise _not_found(e) from e
    return docs.body_of(session, row)


@router.get("/documents/{document_id}/revisions",
            summary="Every revision of this paper")
def document_revisions(document_id: int,
                       principal: Principal = Depends(current_principal),
                       session=Depends(_doc_session)) -> dict:
    from backend.services import documents as docs

    try:
        return {"document_id": document_id,
                "revisions": docs.revisions(session, document_id)}
    except docs.NotFound as e:
        raise _not_found(e) from e


@router.post("/documents/{document_id}/status", summary="Move it along")
def move_document(document_id: int, to: str = Query(...),
                  principal: Principal = RequireAnalyst,
                  session=Depends(_doc_session)) -> dict:
    from backend.services import documents as docs

    try:
        row = docs.set_status(
            session, document_id, to,
            by=(getattr(principal, "username", "") or ""))
    except docs.NotFound as e:
        raise _not_found(e) from e
    except docs.DocumentError as e:
        raise HTTPException(status_code=422, detail={
            "error": "transition_refused", "message": str(e)}) from e
    return docs.body_of(session, row)


@router.delete("/documents/{document_id}", summary="Archive it")
def archive_document(document_id: int,
                     principal: Principal = RequireAnalyst,
                     session=Depends(_doc_session)) -> dict:
    """Archived, never deleted. A paper somebody wrote is not scratch."""
    from backend.services import documents as docs

    try:
        docs.remove(session, document_id)
    except docs.NotFound as e:
        raise _not_found(e) from e
    return {"document_id": document_id, "status": "archived"}


@router.get("/documents/{document_id}/support.zip",
            summary="The document and all its evidence")
def document_bundle(document_id: int,
                    principal: Principal = Depends(current_principal),
                    session=Depends(_doc_session)):
    from fastapi import Response

    from backend.services import documents as docs

    try:
        blob, filename = docs.support_bundle(session, document_id)
    except docs.NotFound as e:
        raise _not_found(e) from e
    return Response(
        content=blob, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/documents/{document_id}/document.docx",
            summary="The document as Word")
def document_docx(document_id: int,
                  principal: Principal = Depends(current_principal),
                  session=Depends(_doc_session)):
    from fastapi import Response

    from backend.services import documents as docs
    from backend.services import documents_docx

    try:
        row = docs.get(session, document_id)
    except docs.NotFound as e:
        raise _not_found(e) from e
    blob = documents_docx.write(session, row)
    return Response(
        content=blob,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"),
        headers={"Content-Disposition":
                 f'attachment; filename="{docs._slug(row.title)}.docx"'})
