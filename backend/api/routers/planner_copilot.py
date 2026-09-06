"""The Copilot's HTTP surface: drafts, the boundary, and publishing.

Separate from `planner.py` because it is a separate contract. The planner
router exposes the project as it exists; these routes are about a plan that
does not exist yet, and the one moment it starts to.

It borrows `get_db`, `_fail` and `_guard` from the planner router rather than
restating them, so a refusal reaches the browser as the same status with the
same shape whichever half of the module produced it.

Three things this file is careful about.

**The scope check runs first.** `/chat` classifies the message before it looks
at a draft, so an out-of-domain question costs one regex pass and returns a
sentence naming where the answer lives — it never reaches a tool, and it never
reaches a model.

**Publish is a POST with a confirmation in the body.** Not a side effect of
a chat turn. `confirm: true` has to be in the request, and `copilot.py`
checks it rather than trusting a paraphrase.

**Every mutation is marked AI_CHAT.** A change somebody typed into the
milestone table and the same change they asked the Copilot for are different
events in the audit trail forever, and that distinction is set here, at the
edge, rather than left to whichever handler happens to run.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.permissions import Principal, RequireAnalyst, RequireCommenter
from backend.api.routers.planner import _fail, _guard, get_db
from backend.planner import access as acl
from backend.planner import copilot
from backend.planner import draft as dr
from backend.planner import policy as pol
from backend.planner import scope as sc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/planner/copilot", tags=["project planner"])


def _refusal(exc: Exception) -> HTTPException:
    """A draft refusal, in the planner's own shape."""
    if isinstance(exc, copilot.NotConfirmed):
        return HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"error": "not_confirmed", "message": str(exc)})
    if isinstance(exc, pol.PolicyError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_policy", "message": str(exc)})
    if isinstance(exc, dr.DraftError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "draft_incomplete", "message": str(exc)})
    return _fail(exc)


def _run(fn: Any) -> Any:
    try:
        return _guard(fn)
    except HTTPException:
        raise
    except (dr.DraftError, pol.PolicyError, copilot.NotConfirmed) as exc:
        raise _refusal(exc) from exc


# =============================================================== the boundary


@router.get("/capabilities",
            summary="What the Copilot can do, and what it will not touch")
def capabilities(_principal: Principal = RequireCommenter) -> dict:
    """The allowlist, said out loud.

    Exposed because "why did it refuse that?" is a question somebody asks on a
    Tuesday, and the honest answer is a list rather than a shrug.
    """
    return copilot.catalogue()


class ScopeIn(BaseModel):
    message: str = Field(default="", max_length=4000)


@router.post("/scope", summary="Would the Copilot answer this?")
def check_scope(payload: ScopeIn, session: Session = Depends(get_db),
                principal: Principal = RequireCommenter) -> dict:
    return copilot.in_scope(session, principal, payload.message).to_dict()


# ================================================================== drafts


class DraftIn(BaseModel):
    name: str = Field(default="", max_length=200)


@router.post("/drafts", status_code=status.HTTP_201_CREATED,
             summary="Start a plan")
def start_draft(payload: DraftIn, session: Session = Depends(get_db),
                principal: Principal = RequireAnalyst) -> dict:
    row = _run(lambda: dr.create(session, principal, name=payload.name,
                                 source=copilot._source()))
    return dr.to_dict(row)


@router.get("/drafts", summary="Plans you are still writing")
def list_drafts(draft_status: str = Query(default="", alias="status"),
                session: Session = Depends(get_db),
                principal: Principal = RequireAnalyst) -> dict:
    rows = _run(lambda: dr.list_for(session, principal, status=draft_status))
    return {"drafts": [dr.to_dict(row) for row in rows]}


@router.get("/drafts/{key}", summary="One plan, with what it still needs")
def read_draft(key: str, session: Session = Depends(get_db),
               principal: Principal = RequireAnalyst) -> dict:
    row = _run(lambda: dr.load(session, principal, key))
    plan = row.plan or dr.empty()
    return {**dr.to_dict(row),
            "completeness": dr.check(plan).to_dict(),
            "catalogue": dr.catalogue(plan),
            "agentic_choices": pol.choices()}


class ApplyIn(BaseModel):
    """One change, named.

    `command` is checked against `draft.COMMANDS` inside the service. It is
    not derived from the payload's shape, so a request cannot reach a mutation
    nobody wrote a screen for by describing itself cleverly.
    """

    command: str = Field(max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = None


@router.post("/drafts/{key}/apply", summary="Change the plan")
def apply_change(key: str, payload: ApplyIn,
                 session: Session = Depends(get_db),
                 principal: Principal = RequireAnalyst) -> dict:
    return _run(lambda: dr.apply(
        session, principal, key, payload.command, payload.payload,
        expected_version=payload.expected_version, source=copilot._source()))


class LinkIn(BaseModel):
    predecessor: str = Field(max_length=40)
    successor: str = Field(max_length=40)
    dependency_type: str = Field(default="FS", max_length=4)
    lag_days: int = 0


@router.post("/drafts/{key}/link-preview",
             summary="What linking these two would do")
def link_preview(key: str, payload: LinkIn,
                 session: Session = Depends(get_db),
                 principal: Principal = RequireAnalyst) -> dict:
    """States the effect; applies nothing.

    §17: a dependency that silently moved a date somebody had committed to is
    the thing this endpoint exists to prevent. Applying it is a second,
    deliberate call to `/apply` with `add_link`.
    """
    row = _run(lambda: dr.load(session, principal, key))
    return _run(lambda: dr.link_preview(
        row.plan or dr.empty(), payload.predecessor, payload.successor,
        dependency_type=payload.dependency_type,
        lag_days=payload.lag_days))


@router.get("/drafts/{key}/previous-task",
            summary="The task immediately before this one")
def previous_task(key: str, code: str = Query(max_length=40),
                  session: Session = Depends(get_db),
                  principal: Principal = RequireAnalyst) -> dict:
    row = _run(lambda: dr.load(session, principal, key))
    plan = row.plan or dr.empty()
    found = dr.previous_task(plan, code)
    return {"code": found, "item": dr.item(plan, found) if found else None}


@router.get("/drafts/{key}/preview",
            summary="Everything that would be created")
def preview(key: str, session: Session = Depends(get_db),
            principal: Principal = RequireAnalyst) -> dict:
    row = _run(lambda: dr.load(session, principal, key))
    return dr.preview(row.plan or dr.empty())


class PublishIn(BaseModel):
    """The confirmation, in the request.

    A separate field rather than the mere fact of a POST, so the person's
    "yes" is a thing the server can point at afterwards.
    """

    confirm: bool = False


@router.post("/drafts/{key}/publish", status_code=status.HTTP_201_CREATED,
             summary="Turn the plan into a real project")
def publish(key: str, payload: PublishIn,
            session: Session = Depends(get_db),
            principal: Principal = RequireAnalyst) -> dict:
    project = _run(lambda: copilot.confirm_publish(
        session, principal, key, confirm=payload.confirm))
    return {"project_id": int(project.id), "code": project.code,
            "name": project.name}


@router.delete("/drafts/{key}", summary="Throw a plan away")
def discard(key: str, session: Session = Depends(get_db),
            principal: Principal = RequireAnalyst) -> dict:
    _run(lambda: dr.discard(session, principal, key,
                            source=copilot._source()))
    return {"discarded": key}


# ================================================================== people


@router.get("/people", summary="Colleagues who can be named on a plan")
def people(search: str = Query(default="", max_length=120),
           limit: int = Query(default=20, ge=1, le=50),
           session: Session = Depends(get_db),
           principal: Principal = RequireAnalyst) -> dict:
    return copilot.people(session, principal, search=search, limit=limit)


# ==================================================================== chat


class ChatIn(BaseModel):
    message: str = Field(max_length=4000)
    draft: str = Field(default="", max_length=64)
    project_id: int | None = None


@router.post("/chat", summary="Say what you want, in words")
def chat(payload: ChatIn, session: Session = Depends(get_db),
         principal: Principal = RequireAnalyst) -> dict:
    """One conversational turn.

    The boundary check runs before anything else. A question about another
    part of CreditProbe returns a refusal that names where the answer lives,
    without reaching a tool and without reaching a model — which is both
    cheaper and the only version of this that cannot be talked around.

    What the turn does with an in-scope message is the caller's next call:
    this returns the resolved context (the draft, what it still needs, what
    can be linked to what) and the chat client turns it into a `/apply`. The
    two paths converge on `draft.apply`, which is the point of §39.
    """
    decision = copilot.in_scope(session, principal, payload.message)
    if not decision.in_scope:
        return {"in_scope": False, "refusal": decision.to_dict(),
                "message": decision.message}

    context: dict[str, Any] = {"in_scope": True,
                               "scope": decision.to_dict(),
                               "purpose": sc.PURPOSE}
    if payload.draft:
        row = _run(lambda: dr.load(session, principal, payload.draft))
        plan = row.plan or dr.empty()
        context["draft"] = dr.to_dict(row)
        context["completeness"] = dr.check(plan).to_dict()
        context["catalogue"] = dr.catalogue(plan)
        context["commands"] = list(dr.COMMANDS)
    if payload.project_id is not None:
        _run(lambda: acl.readable(session, int(payload.project_id),
                                  principal))
        context["project_id"] = int(payload.project_id)
    return context


__all__ = ["router"]
