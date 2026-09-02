"""The messaging centre: mailboxes, threads, attachments, review requests.

Authorization is at the bottom, not the top
--------------------------------------------
Nothing here decides who may read what. Every route resolves the CALLING user
and hands their id to the service, which asks `thread_participants` whether they
belong in the conversation. There is no user id in any path for that reason:
a route that took one would be a route somebody could point at a colleague.

`RequireCommenter` on the read and write paths is deliberate. §50 of the product
contract gives a VIEWER the right to read what is shared with them and to reply
where permitted, and refusing a viewer's reply after sending them something to
comment on would look exactly like a message that was ignored.

The four errors the service raises map to four statuses, once, here:
NotFound → 404, NotPermitted → 403, InvalidRequest → 400, Unavailable → 503.
A caller never has to read English to find out what went wrong.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireAdmin,
    RequireCommenter,
)
from backend.config import settings
from backend.services import collaboration as collab

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])


# ------------------------------------------------------------------ errors


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable",
                "message": "Messages need the application database."},
    )


def _signed_out() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "not_signed_in",
                "message": "Sign in to use CreditProbe."},
    )


def _me(principal: Principal) -> int:
    """The calling user's id, or a refusal.

    A messaging feature genuinely cannot work without knowing who is asking:
    "your inbox" has no meaning for an anonymous caller, and inventing one
    would mean showing somebody else's.
    """
    if not principal.user_id:
        raise _signed_out()
    return int(principal.user_id)


def _run(fn, *args, **kwargs) -> Any:
    """Call a service function in a transaction and translate its errors."""
    if not settings.has_database:
        raise _unavailable()
    from backend.db.engine import get_session

    try:
        with get_session() as session:
            return fn(session, *args, **kwargs)
    except collab.CollaborationUnavailable:
        raise _unavailable() from None
    except collab.NotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "not_found",
                                    "message": str(e)}) from None
    except collab.NotPermitted as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error": "forbidden",
                                    "message": str(e)}) from None
    except collab.InvalidRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"error": "invalid_request",
                                    "message": str(e)}) from None


# ------------------------------------------------------------------ models


class AttachmentIn(BaseModel):
    type: str = Field(..., description="investigation | analysis | report | file")
    object_id: str | None = Field(default=None)
    artifact_id: int | None = Field(default=None)
    label: str | None = Field(default=None)


class DraftIn(BaseModel):
    subject: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=collab.MAX_BODY)
    thread_id: int | None = None


class DraftPatch(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=collab.MAX_BODY)
    attachments: list[AttachmentIn] | None = None


class SendIn(BaseModel):
    to: list[int] = Field(default_factory=list)
    cc: list[int] = Field(default_factory=list)
    subject: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=collab.MAX_BODY)
    attachments: list[AttachmentIn] = Field(default_factory=list)
    request_type: str = Field(default=collab.REQ_FYI)
    priority: str = Field(default=collab.PRIORITY_NORMAL)
    due_at: datetime | None = None
    thread_id: int | None = None
    draft_id: int | None = None
    #: A value the composer generates once per Send press. Sending it twice —
    #: a double-click, a retried request — returns the first message rather
    #: than creating a second one.
    client_token: str = Field(default="", max_length=120)


class ReplyIn(BaseModel):
    body: str = Field(default="", max_length=collab.MAX_BODY)
    attachments: list[AttachmentIn] = Field(default_factory=list)
    request_type: str = Field(default=collab.REQ_FYI)
    priority: str = Field(default=collab.PRIORITY_NORMAL)
    due_at: datetime | None = None


class ReadIn(BaseModel):
    read: bool = True


class ArchiveIn(BaseModel):
    archived: bool = True


class StatusIn(BaseModel):
    status: str
    note: str = Field(default="", max_length=2000)


def _specs(items: list[AttachmentIn] | None) -> list[dict[str, Any]] | None:
    if items is None:
        return None
    return [i.model_dump(exclude_none=True) for i in items]


# ------------------------------------------------------------------- reads


@router.get("/counts", summary="The one personal-attention summary")
def counts(principal: Principal = RequireCommenter) -> dict:
    """Every badge, tab and tile in the product reads this one route.

    Returning box totals alongside the unread count is the point: a header
    badge and a mailbox tab that each count for themselves eventually disagree,
    and the number people stop believing is the one that governs whether they
    open the page at all.
    """
    return _run(collab.attention_summary, _me(principal))


@router.get("/directory", summary="Who a message can be sent to")
def directory(q: str = "", limit: int = 50,
              principal: Principal = RequireCommenter) -> dict:
    _me(principal)
    return {"users": _run(collab.directory, query=q, limit=limit)}


@router.get("", summary="One mailbox")
def mailbox(box: str = collab.BOX_INBOX, limit: int = 50, offset: int = 0,
            q: str = "", unread: bool = False, attachment_type: str = "",
            principal: Principal = RequireCommenter) -> dict:
    return _run(collab.list_box, user_id=_me(principal), box=box, limit=limit,
                offset=offset, query=q, unread_only=unread,
                attachment_type=attachment_type)


@router.get("/threads/{thread_id}", summary="One conversation in full")
def thread(thread_id: int, principal: Principal = RequireCommenter) -> dict:
    return _run(collab.get_thread, thread_id, user_id=_me(principal))


@router.get("/shareable", summary="Objects I can attach, as cards")
def shareable(object_type: str, q: str = "", limit: int = 20,
              principal: Principal = RequireCommenter) -> dict:
    """What the composer's "Share from CreditProbe" selector lists.

    Every card here has already been access-checked for the caller, so the
    picker cannot offer something the send would then refuse.
    """
    return {"items": _run(collab.shareable_objects, user_id=_me(principal),
                          object_type=object_type, query=q, limit=limit)}


@router.get("/shared-with-me", summary="Objects other people have shared")
def shared(limit: int = 25, principal: Principal = RequireCommenter) -> dict:
    return {"items": _run(collab.shared_with_me, _me(principal), limit=limit)}


@router.get("/requests/{message_id}/history",
            summary="Every transition of one review request")
def history(message_id: int, principal: Principal = RequireCommenter) -> dict:
    return {"events": _run(collab.request_history, message_id,
                           user_id=_me(principal))}


# ------------------------------------------------------------------ writes


@router.post("/drafts", status_code=201, summary="Start a private draft")
def new_draft(payload: DraftIn, principal: Principal = RequireCommenter) -> dict:
    return _run(collab.create_draft, sender_id=_me(principal),
                subject=payload.subject, body=payload.body,
                thread_id=payload.thread_id)


@router.patch("/drafts/{message_id}", summary="Rewrite an unsent message")
def edit_draft(message_id: int, payload: DraftPatch,
               principal: Principal = RequireCommenter) -> dict:
    return _run(collab.update_draft, message_id, user_id=_me(principal),
                subject=payload.subject, body=payload.body,
                attachments=_specs(payload.attachments))


@router.post("/send", status_code=201, summary="Send a message")
def send(payload: SendIn, principal: Principal = RequireCommenter) -> dict:
    return _run(collab.send_message, sender_id=_me(principal), to=payload.to,
                cc=payload.cc, subject=payload.subject, body=payload.body,
                attachments=_specs(payload.attachments),
                request_type=payload.request_type, priority=payload.priority,
                due_at=payload.due_at, thread_id=payload.thread_id,
                draft_id=payload.draft_id, client_token=payload.client_token)


@router.post("/threads/{thread_id}/reply", status_code=201,
             summary="Reply in a conversation")
def reply(thread_id: int, payload: ReplyIn,
          principal: Principal = RequireCommenter) -> dict:
    me = _me(principal)

    def _reply(session: Any) -> dict:
        # Everybody else in the thread. Replying to a conversation means
        # replying to the people in it — re-selecting recipients on every
        # reply is how somebody quietly falls out of a thread they were in.
        from sqlalchemy import select

        from backend.models.collaboration import ThreadParticipant

        collab._must_participate(session, thread_id, me)
        others = session.execute(
            select(ThreadParticipant.user_id).where(
                ThreadParticipant.thread_id == thread_id,
                ThreadParticipant.user_id != me,
            )
        ).scalars().all()
        if not others:
            raise collab.InvalidRequest(
                "There is nobody else in this conversation to reply to."
            )
        return collab.send_message(
            session, sender_id=me, to=list(others), body=payload.body,
            attachments=_specs(payload.attachments),
            request_type=payload.request_type, priority=payload.priority,
            due_at=payload.due_at, thread_id=thread_id,
        )

    return _run(_reply)


@router.post("/threads/{thread_id}/read", summary="Mark read or unread")
def read(thread_id: int, payload: ReadIn,
         principal: Principal = RequireCommenter) -> dict:
    return _run(collab.mark_read, thread_id, user_id=_me(principal),
                read=payload.read)


@router.post("/threads/{thread_id}/archive", summary="File it away, or restore")
def archive(thread_id: int, payload: ArchiveIn,
            principal: Principal = RequireCommenter) -> dict:
    return _run(collab.set_archived, thread_id, user_id=_me(principal),
                archived=payload.archived)


@router.post("/requests/{message_id}/status",
             summary="Move a review or action request")
def set_status(message_id: int, payload: StatusIn,
               principal: Principal = RequireCommenter) -> dict:
    return _run(collab.change_request_status, message_id,
                user_id=_me(principal), status=payload.status,
                note=payload.note)


# -------------------------------------------------------------- artifacts


@router.post("/artifacts", status_code=201, summary="Store a file to attach")
async def upload(file: UploadFile = File(...),
                 principal: Principal = RequireCommenter) -> dict:
    me = _me(principal)
    content = await file.read()
    row = _run(collab.store_artifact_view, filename=file.filename or "",
               content=content, created_by=me,
               content_type=file.content_type or "")
    return {"artifact_id": row["id"], "filename": row["filename"],
            "size_bytes": row["size_bytes"], "sha256": row["sha256"]}


@router.get("/artifacts/{artifact_id}", summary="Download an attached file")
def download(artifact_id: int,
             principal: Principal = RequireCommenter) -> Response:
    payload = _run(collab.download_artifact_view, artifact_id,
                   user_id=_me(principal))
    return Response(
        content=payload["content"],
        media_type=payload["content_type"] or "application/octet-stream",
        headers={
            "Content-Disposition":
                f'attachment; filename="{payload["filename"]}"',
            "X-Content-SHA256": payload["sha256"],
        },
    )


# ------------------------------------------------------- admin oversight
#
# ADMIN only, and counts only. These two routes exist so an administrator can
# see how the workflow is actually running — who has unread work, whose
# requests are overdue, who has not signed in — without any route anywhere
# returning the contents of somebody's mail. There is no message body, and no
# subject line, in either response.


@router.get("/admin/overview", summary="Operational overview of every user")
def admin_overview(q: str = "", include_inactive: bool = True,
                   limit: int = 100, offset: int = 0,
                   principal: Principal = RequireAdmin) -> dict:
    _me(principal)
    return _run(collab.admin_overview, query=q,
                include_inactive=include_inactive, limit=limit, offset=offset)


@router.get("/admin/users/{user_id}", summary="One user's operational profile")
def admin_user(user_id: int, principal: Principal = RequireAdmin) -> dict:
    _me(principal)
    return _run(collab.admin_user_profile, user_id)
