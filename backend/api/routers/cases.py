"""
Risk Cases: the API behind Requires Attention. §40–§51.

Reading is filtered, acting is checked
--------------------------------------
`principals.visible_to` filters what comes back to the caller's own
permissions (§57), and every action goes through `require_act`. Hiding a button
is not authorisation — the interface hides what a user cannot do because showing
it would be rude, and these endpoints refuse it because doing it would be a
breach.

Three actions that create other objects
----------------------------------------
§48 **Investigate** opens an Investigation seeded from the case: its scope, its
period, its signals and its evidence, so the thread starts knowing what the case
knows rather than making the user restate it.

§49 **Add to project** links the case into a Project. Links, not copies — the
case stays where it is and the Project points at it.

§50 **Send for review** goes through the EXISTING workflow service. §50 is
explicit that a second workflow system must not be built, so this creates a
`WorkflowItem` exactly as the rest of the product does.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.agentic import cases, notifications, principals
from backend.api.permissions import Principal, current_principal
from backend.db.engine import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk-cases", tags=["risk cases"])

Caller = Depends(current_principal)


def _guard(principal: Principal, check: Any) -> None:
    try:
        check(principal)
    except principals.NotVisible as denied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "not_permitted", "message": str(denied)},
        ) from denied


def _load(session: Any, case_id: int) -> Any:
    found = cases.load(session, case_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found",
                    "message": f"Risk case {case_id} does not exist."})
    return found


def _require_user(principal: Principal) -> int:
    if principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_signed_in",
                    "message": ("This records who did it, so it needs a "
                                "signed-in user.")})
    return principal.user_id


# ---------------------------------------------------------------------------
# Reading — §40, §45, §46
# ---------------------------------------------------------------------------


@router.get("", summary="Cases requiring attention")
def listing(level: str = "ALL", period: str = "", limit: int = 50,
            mine: bool = False,
            principal: Principal = Caller) -> dict[str, Any]:
    """The Cockpit's Requires Attention list.

    `level` is one of §40's filter tabs. The counts come back with the list,
    from one grouped query, so the badge and the rows can never disagree.
    """
    with get_session() as session:
        wanted = cases.FILTER_LEVEL.get((level or "ALL").upper(), "")
        rows = cases.listing(
            session, level=wanted, period=period, limit=min(limit, 200),
            owner_id=principal.user_id if mine else None)
        visible = principals.visible_to(principal, rows)
        return {
            "summary": cases.summary_sentence(session, period=period),
            "counts": cases.counts(session, period=period),
            "filters": [
                {"id": f, "label": f.title() if f != "ALL" else "All"}
                for f in cases.FILTERS],
            "level": (level or "ALL").upper(),
            "period": period,
            "cases": [cases.view(c) for c in visible],
        }


@router.get("/{case_id}", summary="One case in full")
def detail(case_id: int, principal: Principal = Caller) -> dict[str, Any]:
    """§47's drawer: bottom line, why it matters, signals, timeline, evidence,
    analyses, trace, owner and next actions."""
    with get_session() as session:
        case = _load(session, case_id)
        if not principals.visible_to(principal, [case]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "not_permitted",
                        "message": "That case is not shared with you."})
        return cases.view(case,
                          events=cases.events_of(session, case_id),
                          links=cases.links_of(session, case_id))


# ---------------------------------------------------------------------------
# Lifecycle — §38, §43
# ---------------------------------------------------------------------------


class StatusIn(BaseModel):
    status: str
    note: str = Field(default="", max_length=2000)


@router.post("/{case_id}/status", summary="Move a case")
def transition(case_id: int, payload: StatusIn,
               principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_act)
    user_id = _require_user(principal)
    with get_session() as session:
        case = _load(session, case_id)
        try:
            cases.transition(session, case, payload.status.upper(),
                             user_id=user_id, note=payload.note)
        except cases.NotPermitted as denied:
            raise HTTPException(status_code=403,
                                detail={"error": "not_permitted",
                                        "message": str(denied)}) from denied
        except ValueError as bad:
            raise HTTPException(status_code=400,
                                detail={"error": "unknown_status",
                                        "message": str(bad)}) from bad
        return cases.view(case, events=cases.events_of(session, case_id))


class AssignIn(BaseModel):
    owner_id: int | None = None
    team_id: int | None = None
    note: str = Field(default="", max_length=1000)


@router.post("/{case_id}/assign", summary="Give a case an owner")
def assign(case_id: int, payload: AssignIn,
           principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_act)
    actor = _require_user(principal)
    with get_session() as session:
        case = _load(session, case_id)
        cases.assign(session, case, owner_id=payload.owner_id,
                     team_id=payload.team_id, user_id=actor,
                     note=payload.note)
        if payload.owner_id:
            notifications.case_assigned(session, case=case,
                                        user_id=payload.owner_id,
                                        actor_id=actor)
        return cases.view(case, events=cases.events_of(session, case_id))


class SnoozeIn(BaseModel):
    days: int = Field(ge=1, le=180)
    note: str = Field(default="", max_length=1000)


@router.post("/{case_id}/snooze", summary="Put a case aside")
def snooze(case_id: int, payload: SnoozeIn,
           principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_act)
    user_id = _require_user(principal)
    with get_session() as session:
        case = _load(session, case_id)
        cases.snooze(session, case, days=payload.days, user_id=user_id,
                     note=payload.note)
        return cases.view(case, events=cases.events_of(session, case_id))


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/{case_id}/dismiss", summary="Close a case with a reason")
def dismiss(case_id: int, payload: ReasonIn,
            principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_act)
    user_id = _require_user(principal)
    with get_session() as session:
        case = _load(session, case_id)
        cases.dismiss(session, case, reason=payload.reason, user_id=user_id)
        return cases.view(case, events=cases.events_of(session, case_id))


@router.post("/{case_id}/resolve", summary="Resolve a case")
def resolve(case_id: int, payload: ReasonIn,
            principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_act)
    user_id = _require_user(principal)
    with get_session() as session:
        case = _load(session, case_id)
        cases.resolve(session, case, resolution=payload.reason,
                      user_id=user_id)
        return cases.view(case, events=cases.events_of(session, case_id))


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/{case_id}/comments", summary="Comment on a case")
def comment(case_id: int, payload: CommentIn,
            principal: Principal = Caller) -> dict[str, Any]:
    """A VIEWER may comment. §50 of the workflow phase gave viewers exactly one
    write, and a case is one of the things they are asked to look at."""
    with get_session() as session:
        case = _load(session, case_id)
        cases.comment(session, case, body=payload.body,
                      user_id=principal.user_id)
        if case.owner_id and case.owner_id != principal.user_id:
            notifications.case_comment(session, case=case,
                                       user_id=case.owner_id,
                                       body=payload.body,
                                       actor_id=principal.user_id)
        return cases.view(case, events=cases.events_of(session, case_id))


# ---------------------------------------------------------------------------
# §48 — one-click Investigation
# ---------------------------------------------------------------------------


class InvestigateIn(BaseModel):
    project_id: int | None = None


@router.post("/{case_id}/investigate", summary="Open an Investigation")
def investigate(case_id: int, payload: InvestigateIn,
                principal: Principal = Caller) -> dict[str, Any]:
    """§48 — an Investigation seeded from the case.

    The thread opens with CreditProbe's own line naming the case, and the
    context carries the scope, the period, the signals and the evidence — so
    the user's first follow-up is answered against the case's population
    rather than against a fresh reading of a sentence they did not type.
    """
    _guard(principal, principals.require_act)
    user_id = _require_user(principal)
    from backend.services import threads

    with get_session() as session:
        case = _load(session, case_id)
        if case.investigation_id:
            return {"investigation_id": case.investigation_id,
                    "created": False,
                    "message": "This case already has an Investigation."}
        seed = _seed_for(case)
        question = _question_for(case)

    thread = threads.create(
        question=question, title=f"Risk case: {case.title}"[:300],
        project_id=payload.project_id, user_id=user_id, context=seed)
    threads.append(
        thread.id, role="assistant",
        content=(f"CreditProbe has opened this Investigation from Risk Case "
                 f"{case.case_key}.\n\n{case.conclusion}\n\n{case.why}"),
        user_id=user_id)

    with get_session() as session:
        case = _load(session, case_id)
        case.investigation_id = thread.id
        if payload.project_id:
            case.project_id = payload.project_id
        cases.link(session, case, object_type="investigation",
                   object_id=str(thread.id), label=thread.title,
                   relation="opened_from", user_id=user_id)
        cases.transition(session, case, cases.UNDER_INVESTIGATION,
                         user_id=user_id,
                         note="An Investigation was opened from this case.")
        return {"investigation_id": thread.id, "created": True,
                "question": question,
                "case": cases.view(case,
                                   events=cases.events_of(session, case_id))}


def _seed_for(case: Any) -> dict[str, Any]:
    """The context an Investigation inherits from a case.

    Scope and references only. The figures live in the analysis runs the case
    points at, and copying them here would create a second, ageing copy of a
    number the Trace already owns.
    """
    scope: dict[str, Any] = {"period": case.period}
    if case.prior_period:
        scope["compare_period"] = case.prior_period
    if case.level == cases.SEGMENT and case.entity:
        scope["sector"] = case.entity
    if case.level == cases.BORROWER and case.entity_id:
        scope["customer_id"] = case.entity_id
    return {
        "scope": scope,
        "risk_case": {
            "id": case.id, "key": case.case_key, "title": case.title,
            "level": case.level, "entity": case.entity,
            "severity": case.severity, "period": case.period,
            "signals": list(case.signals or []),
            "analyses": list(case.analyses or []),
        },
    }


def _question_for(case: Any) -> str:
    """The opening question, in the product's own vocabulary."""
    if case.level == cases.BORROWER:
        return (f"What is driving the deterioration at {case.entity} "
                f"in {case.period}?")
    if case.level == cases.SEGMENT:
        return (f"Something seems wrong with {case.entity}. "
                f"Investigate it for {case.period}.")
    if case.level == cases.DATA_QUALITY:
        return (f"What does {case.entity} cover, and which periods are "
                f"published?")
    return f"Review the portfolio for {case.period} and tell me what moved."


# ---------------------------------------------------------------------------
# §49 — case to Project
# ---------------------------------------------------------------------------


class ProjectIn(BaseModel):
    project_id: int | None = None
    name: str = Field(default="", max_length=200)


@router.post("/{case_id}/project", summary="Add a case to a Project")
def to_project(case_id: int, payload: ProjectIn,
               principal: Principal = Caller) -> dict[str, Any]:
    """§49 — link, never copy.

    An existing Project when one is named; a new one when a name is given.
    The case is LINKED into it: the Project points at the case, the
    Investigation and the analyses, and nothing is duplicated.
    """
    _guard(principal, principals.require_act)
    user_id = _require_user(principal)
    from backend.models.platform import Project

    with get_session() as session:
        case = _load(session, case_id)
        project_id = payload.project_id
        created = False
        if project_id is None:
            name = payload.name or f"{case.entity or 'Portfolio'} — {case.period}"
            project = Project(name=name[:200],
                              description=case.conclusion[:2000],
                              owner_id=user_id,
                              default_context=_seed_for(case))
            session.add(project)
            session.flush()
            project_id = project.id
            created = True
        elif session.get(Project, project_id) is None:
            raise HTTPException(status_code=404,
                                detail={"error": "not_found",
                                        "message": "No such project."})

        case.project_id = project_id
        cases.link(session, case, object_type="project",
                   object_id=str(project_id), label=payload.name,
                   relation="belongs_to", user_id=user_id)
        cases.comment(session, case,
                      body=f"Added to project {project_id}.",
                      user_id=user_id)
        return {"project_id": project_id, "created": created,
                "case": cases.view(case,
                                   events=cases.events_of(session, case_id),
                                   links=cases.links_of(session, case_id))}


# ---------------------------------------------------------------------------
# §50 — case workflow, through the existing service
# ---------------------------------------------------------------------------


class ReviewRequestIn(BaseModel):
    recipients: list[int] = Field(default_factory=list)
    teams: list[int] = Field(default_factory=list)
    action: str = Field(default="review", max_length=24)
    message: str = Field(default="", max_length=4000)
    priority: str = Field(default="normal", max_length=12)
    due_at: str = Field(default="", max_length=40)


@router.post("/{case_id}/review", summary="Send a case for review")
def send_for_review(case_id: int, payload: ReviewRequestIn,
                    principal: Principal = Caller) -> dict[str, Any]:
    """§50 — the EXISTING workflow service, not a second one."""
    _guard(principal, principals.require_act)
    user_id = _require_user(principal)
    from backend.services import workflow

    with get_session() as session:
        case = _load(session, case_id)
        title = f"Review risk case: {case.title}"[:300]
        body = payload.message or (f"{case.conclusion}\n\n{case.why}")

    try:
        item = workflow.send(
            object_type="risk_case", object_id=str(case_id), title=title,
            action=payload.action, message=body, priority=payload.priority,
            requested_by=user_id, recipients=list(payload.recipients),
            teams=list(payload.teams),
            due_at=payload.due_at or None)
    except workflow.InvalidTransition as bad:
        raise HTTPException(status_code=400,
                            detail={"error": "invalid_request",
                                    "message": str(bad)}) from bad

    with get_session() as session:
        case = _load(session, case_id)
        case.workflow_item_id = item.id
        cases.link(session, case, object_type="workflow",
                   object_id=str(case.workflow_item_id), label=title,
                   relation="review", user_id=user_id)
        cases.transition(session, case, cases.ACTION_PENDING, user_id=user_id,
                         note="Sent for review.")
        return {"workflow_item_id": case.workflow_item_id,
                "case": cases.view(case,
                                   events=cases.events_of(session, case_id),
                                   links=cases.links_of(session, case_id))}
