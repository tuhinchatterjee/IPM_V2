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
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.permissions import Principal, RequireAnalyst, RequireCommenter
from backend.api.routers.planner import Durable, _fail, _guard, get_db
from backend.models.planner import PlannerProject
from backend.planner import access as acl
from backend.planner import copilot, live
from backend.planner import draft as dr
from backend.planner import language as lang
from backend.planner import policy as pol
from backend.planner import reading as rd
from backend.planner import scope as sc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/planner/copilot", tags=["project planner"],
                   route_class=Durable)


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
    # Something asked of a running project that this door does not open —
    # a bad request rather than a broken one, and the sentence `live` wrote
    # says which door it is behind.
    if isinstance(exc, live.LiveError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "not_this_way", "message": str(exc)})
    return _fail(exc)


def _run(fn: Any) -> Any:
    try:
        return _guard(fn)
    except HTTPException:
        raise
    except (dr.DraftError, live.LiveError, pol.PolicyError,
            copilot.NotConfirmed) as exc:
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
            # Everybody this plan names, so a screen can print "Priya Raman"
            # beside a task without holding the whole staff directory. On an
            # installation with five thousand people, that directory is not a
            # list a browser should be asked to keep.
            "people": dr.people_named(session, plan),
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


# =================================================================== codes


@router.get("/code-available", summary="Is this project code free?")
def code_available(code: str = Query(max_length=40),
                   session: Session = Depends(get_db),
                   _principal: Principal = RequireAnalyst) -> dict:
    """Whether a project code can still be used, asked before publish.

    §7 wants the duplicate caught while somebody is still on step one rather
    than at the end of an eight-step form. The taken project's NAME is only
    returned when the asker can read that project: a code check is not a way
    to enumerate work you are not on.
    """
    wanted = str(code or "").strip()
    if not wanted:
        return {"code": "", "available": False, "used_by": ""}
    existing = session.execute(
        select(PlannerProject).where(
            func.lower(PlannerProject.code) == wanted.lower())
    ).scalar_one_or_none()
    if existing is None:
        return {"code": wanted, "available": True, "used_by": ""}
    # `readable` REFUSES rather than returning false, which is right
    # everywhere else and is exactly what this route wants to absorb: being
    # told a code is taken is fine, being told whose project took it is not.
    try:
        acl.readable(session, int(existing.id), _principal)
        used_by = existing.name
    except Exception:  # noqa: BLE001 - any refusal means "not yours to see"
        used_by = "another project"
    return {"code": wanted, "available": False, "used_by": used_by}


# ================================================================== people


@router.get("/people", summary="Colleagues who can be named on a plan")
def people(search: str = Query(default="", max_length=120),
           # The governance step needs the WHOLE directory in one select,
           # not a page of it: a form where the sponsor you want is missing
           # because they were the fifty-first name is a form nobody can
           # finish. 50 was a chat-completion limit, and this is not chat.
           limit: int = Query(default=20, ge=1, le=500),
           session: Session = Depends(get_db),
           principal: Principal = RequireAnalyst) -> dict:
    return copilot.people(session, principal, search=search, limit=limit)


# ==================================================================== chat


class ChatIn(BaseModel):
    """One thing somebody said, and what they have already agreed to.

    `confirm` is the only way a commitment-changing sentence takes effect,
    and it re-reads the SAME message rather than accepting commands from the
    client. A body that could name its own commands would be a second way
    into the planner with none of the reading in front of it.
    """

    message: str = Field(max_length=4000)
    draft: str = Field(default="", max_length=64)
    project_id: int | None = None
    #: What the conversation was last about, so "it starts on the first" has
    #: a subject. Echoed back from the previous turn.
    focus: str = Field(default="", max_length=40)
    confirm: bool = False
    #: Answers to earlier clarifications, keyed by the words that were
    #: ambiguous: {"data review": "M01-T03"}.
    answers: dict[str, str] = Field(default_factory=dict)
    expected_version: int | None = None


@router.post("/chat", summary="Say what you want, in words")
def chat(payload: ChatIn, session: Session = Depends(get_db),
         principal: Principal = RequireAnalyst) -> dict:
    """One conversational turn, from words to a changed plan.

    The order is the whole design.

    1. **Scope.** A question about another part of CreditProbe returns a
       sentence naming where the answer lives, without reaching a tool, a
       model or a draft.
    2. **Read.** `language.read` turns the message into resolved proposals
       drawn from `draft.COMMANDS` and nothing else. Names become codes and
       user ids HERE, against the plan and directory this person can see.
    3. **Ask.** Anything ambiguous comes back as a short question with the
       candidates as buttons. Nothing is applied while a question is open:
       a turn that half-understood and acted anyway is worse than one that
       asked.
    4. **Confirm.** If any proposal moves a commitment — a date, an owner, a
       dependency, the monitoring policy, a removal — the whole set is shown
       and nothing happens until `confirm` comes back. Pure additions apply
       straight away, because nothing was promised about a milestone that did
       not exist a moment ago.
    5. **Apply.** Through `draft.apply`, the same writer the panels use, so
       the permission check, the cycle check, the date validation and the
       AI_CHAT audit row all happen exactly once and in one place.
    """
    # The plan is read first, so the boundary knows the names in the thing
    # being talked about — whether that is a draft nobody has published or a
    # project that is already running.
    plan: dict[str, Any] = {}
    # Every project named in the request is checked, even one this turn will
    # not read: a draft turn that also carried somebody else's project id
    # would echo that id back unchecked, which is a small leak today and the
    # kind of thing a later change turns into a large one.
    if payload.project_id is not None:
        _run(lambda: acl.readable(session, int(payload.project_id),
                                  principal))
    if payload.draft:
        row = _run(lambda: dr.load(session, principal, payload.draft))
        plan = row.plan or dr.empty()
    elif payload.project_id is not None:
        plan = _run(lambda: live.plan_of(session, principal,
                                         int(payload.project_id)))

    decision = copilot.in_scope(session, principal, payload.message, plan=plan)
    if not decision.in_scope:
        return {"in_scope": False, "refusal": decision.to_dict(),
                "message": decision.message}

    context: dict[str, Any] = {"in_scope": True,
                               "scope": decision.to_dict(),
                               "purpose": sc.PURPOSE}
    if payload.project_id is not None:
        context["project_id"] = int(payload.project_id)
    if not payload.draft and payload.project_id is None:
        context["commands"] = []
        context["said"] = _no_draft_yet(payload.message)
        return context

    reading = lang.read(payload.message, lang.Context(
        plan=plan,
        directory=rd.Directory(copilot.people_for(
            session, principal, payload.message, plan)),
        today=date.today(),
        focus=payload.focus,
        answers={rd.normalise(k): str(v)
                 for k, v in (payload.answers or {}).items()}))

    context.update({
        "commands": [c.to_dict() for c in reading.commands],
        "questions": [q.to_dict() for q in reading.questions],
        "unread": reading.unread,
        "reader": reading.source,
        "focus": reading.focus,
    })

    # A change to a running project moves a commitment somebody has already
    # made, so nothing on one applies without confirmation — not even the
    # additions a draft applies straight away. There is no such thing as a
    # task added to a live project that nobody promised anything about.
    live_edit = not payload.draft
    needs_confirmation = live_edit or any(c.preview for c in reading.commands)
    needs_confirmation = needs_confirmation and bool(reading.commands)
    if reading.questions or (needs_confirmation and not payload.confirm):
        context["needs_confirmation"] = bool(
            needs_confirmation and not reading.questions)
        context["applied"] = []
        context["said"] = _describe(reading, applied=False)
        context.update(_state(session, principal, payload))
        return context

    if reading.commands:
        outcome = _run(lambda: (
            live.apply_all(session, principal, int(payload.project_id),
                           reading.commands, source=copilot._source())
            if live_edit else
            lang.apply_all(session, principal, payload.draft,
                           reading.commands, source=copilot._source())))
        context["applied"] = outcome["applied"]
        context["created"] = outcome["created"]
    else:
        context["applied"] = []
    context["needs_confirmation"] = False
    context["said"] = _describe(reading, applied=bool(reading.commands))
    context.update(_state(session, principal, payload))
    return context


def _state(session: Session, principal: Principal,
           payload: ChatIn) -> dict[str, Any]:
    """Whatever was changed, as it stands now.

    A draft turn returns the draft; a project turn returns the project's own
    plan. Both for the same reason — §9 asks that a change made in chat
    appear beside the conversation immediately, and the cheapest guarantee is
    for the chat response to BE the new state.
    """
    if payload.draft:
        return _draft_state(session, principal, payload.draft)
    if payload.project_id is None:
        return {}
    plan = _run(lambda: live.plan_of(session, principal,
                                     int(payload.project_id)))
    return {"project_plan": plan, "catalogue": dr.catalogue(plan)}


def _draft_state(session: Session, principal: Principal,
                 key: str) -> dict[str, Any]:
    """The plan as it stands after this turn.

    Returned on every turn so the panels beside the conversation are never
    stale: §9 asks that a change made in chat appear in the panel
    immediately, and the cheapest way to guarantee that is for the chat
    response to BE the panel's new state.
    """
    row = dr.load(session, principal, key)
    plan = row.plan or dr.empty()
    return {"draft": dr.to_dict(row),
            "completeness": dr.check(plan).to_dict(),
            "catalogue": dr.catalogue(plan)}


def _no_draft_yet(message: str) -> str:
    del message
    return ("That is delivery, so it is mine. Open the plan you mean, or "
            "start a new one, and I will work on it with you.")


def _describe(reading: lang.Reading, *, applied: bool) -> str:
    """What the Copilot says back, in the same voice whichever reader ran."""
    if reading.questions:
        return reading.questions[0].text
    if not reading.commands:
        if reading.unread:
            return ("I did not follow “" + reading.unread[0] + "”. Try "
                    "naming the milestone or task, and what you want changed "
                    "about it.")
        return ("I did not catch a change in that. Tell me what to add, who "
                "owns it, or when it is due.")
    lines = [c.sentence for c in reading.commands if c.sentence]
    if applied:
        head = ("Done." if len(lines) == 1
                else f"Done — {len(lines)} changes.")
    else:
        head = ("This is what that would do. Say go ahead and I will make "
                "the change." if len(lines) == 1 else
                f"This is what that would do — {len(lines)} changes. Say go "
                "ahead and I will make them.")
    return head + "\n" + "\n".join(f"· {line}" for line in lines)


__all__ = ["router"]
