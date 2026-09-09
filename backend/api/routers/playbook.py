"""The committee pack lifecycle over HTTP.

Thin on purpose. Every route validates its payload shape, calls one service
function, and translates the refusal it gets back. There is no authorisation
logic here and no business rule here, because a rule enforced in a router is a
rule a second caller walks past — and the Playbook has two other callers
already, the agent tools and the demo builder.

Two things this router is careful about
----------------------------------------
**The source is never read from the request.** Every call passes
`source=SOURCE_UI`. A caller who could name their own source could name UI on
an agent's behalf, and every later `by_ai` check would answer no.

**A download is a `Response`, not a payload.** Bytes go back with a content
type and a filename, and the export was recorded before this function returns,
so a download that fails in transit is still in the log.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.permissions import Principal, RequireAnalyst, RequireCommenter
from backend.config import settings
from backend.db.engine import SessionLocal
from backend.models.playbook import SOURCE_UI
from backend.playbook import (
    access,
    compare,
    export,
    generation,
    monitor,
    narrative,
    readiness,
)
from backend.playbook import actions as act
from backend.playbook import findings as find
from backend.playbook import import_ as ingest
from backend.playbook import service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playbook", tags=["playbook"])

MAX_TEXT = 20_000


def get_db() -> Session:
    """A transactional session per request, committed on success."""
    if not settings.has_database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "database_unavailable",
                    "message": "Playbook keeps the committee record in "
                               "PostgreSQL, and this deployment has none "
                               "configured."})
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _fail(exc: Exception) -> HTTPException:
    """One place that turns a service refusal into an HTTP answer.

    `PackLocked` is a 409 rather than a 403 on purpose: the caller is not
    unauthorised, the object has moved into a state where nobody may write to
    it, and the answer is to raise an amendment rather than to ask for access.
    """
    if isinstance(exc, access.PackNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(exc)})
    if isinstance(exc, access.PackLocked):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "pack_locked", "message": str(exc)})
    if isinstance(exc, access.PackDenied):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": str(exc)})
    if isinstance(exc, svc.StaleWrite):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stale_write", "message": str(exc)})
    if isinstance(exc, narrative.NoProvider):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "no_ai_provider", "message": str(exc)})
    if isinstance(exc, narrative.Ungrounded):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "ungrounded_commentary", "message": str(exc)})
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "invalid_request", "message": str(exc)})


def _guard(fn: Any) -> Any:
    """Run a service call, translating its refusals. Used by every route."""
    try:
        return fn()
    except (access.PackNotFound, access.PackDenied, access.PackLocked,
            svc.StaleWrite, svc.InvalidPlaybook, narrative.NoProvider,
            narrative.Ungrounded, ValueError) as exc:
        raise _fail(exc) from exc


# =============================================================== payloads


class CommitteeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=MAX_TEXT)
    purpose: str = Field(default="", max_length=MAX_TEXT)
    business_area: str = Field(default="", max_length=120)
    cadence: str = "MONTHLY"
    meeting_weekday: int | None = Field(default=None, ge=0, le=6)
    confidentiality: str = "CONFIDENTIAL"
    standard_agenda: list[str] = Field(default_factory=list)
    workflow_offsets: dict[str, int] = Field(default_factory=dict)
    chair_id: int | None = None
    secretary_id: int | None = None


class CommitteePatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_TEXT)
    purpose: str | None = Field(default=None, max_length=MAX_TEXT)
    business_area: str | None = Field(default=None, max_length=120)
    cadence: str | None = None
    meeting_weekday: int | None = Field(default=None, ge=0, le=6)
    confidentiality: str | None = None
    standard_agenda: list[str] | None = None
    workflow_offsets: dict[str, int] | None = None
    chair_id: int | None = None
    secretary_id: int | None = None
    active: bool | None = None


class MemberIn(BaseModel):
    user_id: int
    business_role: str = "MEMBER"
    access_role: str = "VIEWER"
    title: str = Field(default="", max_length=160)
    notify: bool = True


class MemberPatch(BaseModel):
    business_role: str | None = None
    access_role: str | None = None
    title: str | None = Field(default=None, max_length=160)
    notify: bool | None = None
    active: bool | None = None


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(default="", max_length=40)
    committee_id: int | None = None
    description: str = Field(default="", max_length=MAX_TEXT)
    status: str = "DRAFT"
    confidentiality: str = "CONFIDENTIAL"
    sections: list[dict] = Field(default_factory=list)
    materiality_rules: list[dict] = Field(default_factory=list)
    required_domains: list[str] = Field(default_factory=list)
    required_datasets: list[str] = Field(default_factory=list)
    export_settings: dict = Field(default_factory=dict)


class PackIn(BaseModel):
    committee_id: int
    name: str = Field(default="", max_length=240)
    period: str = Field(default="", max_length=32)
    comparison_period: str = Field(default="", max_length=32)
    meeting_at: datetime | None = None
    as_of_date: date | None = None
    template_id: int | None = None
    owner_id: int | None = None


class PackPatch(BaseModel):
    expected_version: int | None = None
    name: str | None = Field(default=None, max_length=240)
    period: str | None = Field(default=None, max_length=32)
    comparison_period: str | None = Field(default=None, max_length=32)
    meeting_at: datetime | None = None
    as_of_date: date | None = None
    data_freeze_at: datetime | None = None
    owner_id: int | None = None
    confidentiality: str | None = None
    minutes: str | None = Field(default=None, max_length=MAX_TEXT)


class StatusIn(BaseModel):
    status: str
    note: str = Field(default="", max_length=MAX_TEXT)


class SectionIn(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    purpose: str = Field(default="", max_length=MAX_TEXT)
    position: int | None = None
    owner_id: int | None = None
    reviewer_id: int | None = None
    required: bool = True
    due_date: date | None = None
    narrative_instructions: str = Field(default="", max_length=MAX_TEXT)
    template_key: str = Field(default="", max_length=64)
    expected_version: int | None = None


class SectionPatch(BaseModel):
    expected_version: int | None = None
    title: str | None = Field(default=None, max_length=240)
    purpose: str | None = Field(default=None, max_length=MAX_TEXT)
    position: int | None = None
    owner_id: int | None = None
    reviewer_id: int | None = None
    required: bool | None = None
    due_date: date | None = None
    narrative_instructions: str | None = Field(default=None, max_length=MAX_TEXT)
    status: str | None = None


class ReviewIn(BaseModel):
    decision: str
    note: str = Field(default="", max_length=MAX_TEXT)
    conditions: str = Field(default="", max_length=MAX_TEXT)


class ReviewRequestIn(BaseModel):
    reviewer_id: int


class BlockIn(BaseModel):
    block_type: str
    title: str = Field(default="", max_length=240)
    body: str = Field(default="", max_length=MAX_TEXT)
    statement_kind: str = Field(default="", max_length=24)
    config: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)
    period: str = Field(default="", max_length=32)
    position: int | None = None
    expected_version: int | None = None


class BlockPatch(BaseModel):
    expected_version: int | None = None
    title: str | None = Field(default=None, max_length=240)
    body: str | None = Field(default=None, max_length=MAX_TEXT)
    statement_kind: str | None = Field(default=None, max_length=24)
    config: dict | None = None
    filters: dict | None = None
    period: str | None = Field(default=None, max_length=32)
    position: int | None = None
    ai_accepted: bool | None = None


class ReorderIn(BaseModel):
    section_ids: list[int] | None = None
    block_ids: list[int] | None = None
    section_id: int | None = None


class DraftIn(BaseModel):
    instructions: str = Field(default="", max_length=2000)
    block_id: int | None = None


class AmendIn(BaseModel):
    reason: str = Field(min_length=1, max_length=MAX_TEXT)


class DecisionIn(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    question: str = Field(default="", max_length=MAX_TEXT)
    recommendation: str = Field(default="", max_length=MAX_TEXT)
    alternatives: list[str] = Field(default_factory=list)
    impact: str = Field(default="", max_length=MAX_TEXT)
    section_id: int | None = None
    owner_id: int | None = None


class FindingIn(BaseModel):
    status: str
    response: str = Field(default="", max_length=MAX_TEXT)
    owner_id: int | None = None
    #: Only read for a dismissal, and required for one.
    reason: str = Field(default="", max_length=MAX_TEXT)


class ReopenIn(BaseModel):
    why: str = Field(min_length=1, max_length=MAX_TEXT)


class DecisionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    question: str | None = Field(default=None, max_length=MAX_TEXT)
    recommendation: str | None = Field(default=None, max_length=MAX_TEXT)
    alternatives: list[str] | None = None
    impact: str | None = Field(default=None, max_length=MAX_TEXT)
    owner_id: int | None = None
    status: str | None = None


class DecideIn(BaseModel):
    outcome: str
    decision_text: str = Field(default="", max_length=MAX_TEXT)
    conditions: str = Field(default="", max_length=MAX_TEXT)


class ActionIn(BaseModel):
    description: str = Field(min_length=1, max_length=MAX_TEXT)
    owner_id: int | None = None
    due_date: date | None = None
    priority: str = "MEDIUM"
    decision_id: int | None = None
    status: str = "DRAFT"


class ActionPatch(BaseModel):
    description: str | None = Field(default=None, max_length=MAX_TEXT)
    owner_id: int | None = None
    due_date: date | None = None
    priority: str | None = None
    status: str | None = None
    latest_update: str | None = Field(default=None, max_length=MAX_TEXT)
    closure_evidence: str | None = Field(default=None, max_length=MAX_TEXT)


class CloseIn(BaseModel):
    evidence: str = Field(default="", max_length=MAX_TEXT)
    completed: bool = True


class LinkIn(BaseModel):
    project_id: int
    task_code: str = Field(default="", max_length=32)
    workstream_id: int | None = None


def _set(payload: BaseModel) -> dict[str, Any]:
    """Only the fields the caller actually sent.

    `exclude_unset` rather than `exclude_none`: a caller clearing an owner
    sends `owner_id: null` and means it, and treating that as "not sent" makes
    a field impossible to clear through the API.
    """
    return payload.model_dump(exclude_unset=True)


# ============================================================= committees


@router.get("/committees", summary="Every committee you sit on")
def list_committees(session: Session = Depends(get_db),
                    principal: Principal = RequireCommenter) -> dict:
    return {"committees": _guard(
        lambda: svc.committees(session, principal, source=SOURCE_UI))}


@router.post("/committees", status_code=status.HTTP_201_CREATED,
             summary="Stand up a committee")
def create_committee(payload: CommitteeIn,
                     session: Session = Depends(get_db),
                     principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.create_committee(
        session, principal, source=SOURCE_UI, **payload.model_dump()))


@router.get("/committees/{committee_id}", summary="One committee")
def get_committee(committee_id: int, session: Session = Depends(get_db),
                  principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: svc.committee(session, committee_id, principal,
                                        source=SOURCE_UI))


@router.patch("/committees/{committee_id}", summary="Change a committee")
def patch_committee(committee_id: int, payload: CommitteePatch,
                    session: Session = Depends(get_db),
                    principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.update_committee(
        session, committee_id, principal, source=SOURCE_UI, **_set(payload)))


@router.post("/committees/{committee_id}/members",
             status_code=status.HTTP_201_CREATED,
             summary="Put somebody on a committee")
def add_member(committee_id: int, payload: MemberIn,
               session: Session = Depends(get_db),
               principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.add_member(
        session, committee_id, principal, source=SOURCE_UI,
        **payload.model_dump()))


@router.patch("/members/{member_id}", summary="Change somebody's role")
def patch_member(member_id: int, payload: MemberPatch,
                 session: Session = Depends(get_db),
                 principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.update_member(
        session, member_id, principal, source=SOURCE_UI, **_set(payload)))


# ============================================================== templates


@router.get("/templates", summary="Pack shapes you can build from")
def list_templates(committee_id: int | None = None,
                   session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> dict:
    return {"templates": _guard(lambda: svc.templates(
        session, principal, committee_id=committee_id, source=SOURCE_UI))}


@router.post("/templates", status_code=status.HTTP_201_CREATED,
             summary="Create a template, or a new version of one")
def create_template(payload: TemplateIn, session: Session = Depends(get_db),
                    principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.create_template(
        session, principal, source=SOURCE_UI, **payload.model_dump()))


@router.post("/templates/{template_id}/status",
             summary="Publish or retire a template version")
def set_template_status(template_id: int, payload: StatusIn,
                        session: Session = Depends(get_db),
                        principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.set_template_status(
        session, template_id, principal, status=payload.status,
        source=SOURCE_UI))


# ================================================================== packs


@router.get("/packs", summary="Packs across your committees")
def list_packs(committee_id: int | None = None,
               pack_status: str | None = Query(default=None, alias="status"),
               mine: bool = False,
               limit: int = Query(default=100, ge=1, le=500),
               session: Session = Depends(get_db),
               principal: Principal = RequireCommenter) -> dict:
    return {"packs": _guard(lambda: svc.packs(
        session, principal, committee_id=committee_id, status=pack_status,
        mine=mine, limit=limit, source=SOURCE_UI))}


@router.post("/packs", status_code=status.HTTP_201_CREATED,
             summary="Open the next pack")
def create_pack(payload: PackIn, session: Session = Depends(get_db),
                principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.create_pack(
        session, principal, source=SOURCE_UI, **payload.model_dump()))


@router.get("/packs/{pack_id}", summary="One pack, whole")
def get_pack(pack_id: int, session: Session = Depends(get_db),
             principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: svc.pack(session, pack_id, principal,
                                   source=SOURCE_UI))


@router.patch("/packs/{pack_id}", summary="Change a pack's heading")
def patch_pack(pack_id: int, payload: PackPatch,
               session: Session = Depends(get_db),
               principal: Principal = RequireAnalyst) -> dict:
    changes = _set(payload)
    expected = changes.pop("expected_version", None)
    return _guard(lambda: svc.update_pack(
        session, pack_id, principal, expected_version=expected,
        source=SOURCE_UI, **changes))


@router.post("/packs/{pack_id}/status", summary="Move a pack through its life")
def set_pack_status(pack_id: int, payload: StatusIn,
                    session: Session = Depends(get_db),
                    principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.set_pack_status(
        session, pack_id, principal, status=payload.status,
        note=payload.note, source=SOURCE_UI))


@router.get("/packs/{pack_id}/readiness",
            summary="Whether this pack can go to committee, and why not")
def get_readiness(pack_id: int, session: Session = Depends(get_db),
                  principal: Principal = RequireCommenter) -> dict:
    def run() -> dict:
        row, _ = access.readable_pack(session, pack_id, principal, SOURCE_UI)
        return {"pack_id": int(row.id), "code": str(row.code),
                **readiness.assess(session, row).to_dict()}

    return _guard(run)


@router.post("/packs/{pack_id}/generate",
             summary="Calculate every governed figure in the pack")
def generate_pack(pack_id: int, session: Session = Depends(get_db),
                  principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: generation.generate(
        session, pack_id, principal, source=SOURCE_UI).to_dict())


@router.post("/packs/{pack_id}/amend", status_code=status.HTTP_201_CREATED,
             summary="Correct an approved pack at a new version")
def amend_pack(pack_id: int, payload: AmendIn,
               session: Session = Depends(get_db),
               principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: generation.amend(
        session, pack_id, principal, reason=payload.reason,
        source=SOURCE_UI))


@router.get("/packs/{pack_id}/compare",
            summary="What changed since the previous committee")
def compare_pack(pack_id: int, session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: compare.against_previous(
        session, pack_id, principal, source=SOURCE_UI))


@router.get("/packs/{pack_id}/history", summary="Who changed what, and when")
def pack_history(pack_id: int, limit: int = Query(default=100, ge=1, le=500),
                 session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> dict:
    def run() -> dict:
        from sqlalchemy import select

        from backend.models.playbook import PlaybookEvent

        row, _ = access.readable_pack(session, pack_id, principal, SOURCE_UI)
        rows = session.execute(
            select(PlaybookEvent).where(PlaybookEvent.pack_id == row.id)
            .order_by(PlaybookEvent.id.desc()).limit(limit)).scalars().all()
        return {"pack_id": int(row.id), "events": [{
            "id": int(e.id),
            "at": e.created_at.isoformat() if e.created_at else None,
            "entity_type": str(e.entity_type), "entity_id": e.entity_id,
            "entity_ref": str(e.entity_ref), "action": str(e.action),
            "author_id": e.author_id, "source": str(e.source),
            "at_version": e.at_version, "changes": dict(e.changes or {}),
            "narrative": str(e.narrative),
        } for e in rows]}

    return _guard(run)


@router.post("/packs/{pack_id}/reorder", summary="Reorder sections or blocks")
def reorder(pack_id: int, payload: ReorderIn,
            session: Session = Depends(get_db),
            principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.reorder(
        session, pack_id, principal, section_ids=payload.section_ids,
        block_ids=payload.block_ids, section_id=payload.section_id,
        source=SOURCE_UI))


# =============================================================== sections


@router.post("/packs/{pack_id}/sections", status_code=status.HTTP_201_CREATED,
             summary="Add a page")
def create_section(pack_id: int, payload: SectionIn,
                   session: Session = Depends(get_db),
                   principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: svc.create_section(
        session, pack_id, principal, source=SOURCE_UI, **payload.model_dump()))


@router.patch("/sections/{section_id}", summary="Change a section")
def patch_section(section_id: int, payload: SectionPatch,
                  session: Session = Depends(get_db),
                  principal: Principal = RequireCommenter) -> dict:
    changes = _set(payload)
    expected = changes.pop("expected_version", None)
    return _guard(lambda: svc.update_section(
        session, section_id, principal, expected_version=expected,
        source=SOURCE_UI, **changes))


@router.delete("/sections/{section_id}",
               status_code=status.HTTP_204_NO_CONTENT,
               summary="Take a page out of a draft")
def delete_section(section_id: int, session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> Response:
    _guard(lambda: svc.delete_section(session, section_id, principal,
                                      source=SOURCE_UI))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sections/{section_id}/submit",
             summary="Say your section is ready to be read")
def submit_section(section_id: int, payload: StatusIn | None = None,
                   session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> dict:
    note = payload.note if payload is not None else ""
    return _guard(lambda: svc.submit_section(
        session, section_id, principal, note=note, source=SOURCE_UI))


@router.post("/sections/{section_id}/review",
             summary="Record that you read it, and what you thought")
def review_section(section_id: int, payload: ReviewIn,
                   session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: svc.review_section(
        session, section_id, principal, decision=payload.decision,
        note=payload.note, conditions=payload.conditions, source=SOURCE_UI))


@router.post("/sections/{section_id}/request-review",
             summary="Ask somebody to read a section")
def request_review(section_id: int, payload: ReviewRequestIn,
                   session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: svc.request_review(
        session, section_id, principal, reviewer_id=payload.reviewer_id,
        source=SOURCE_UI))


@router.post("/sections/{section_id}/commentary",
             summary="Draft commentary from this section's figures")
def draft_commentary(section_id: int, payload: DraftIn,
                     session: Session = Depends(get_db),
                     principal: Principal = RequireAnalyst) -> dict:
    def run() -> dict:
        made = narrative.draft(session, section_id, principal,
                               source=SOURCE_UI,
                               instructions=payload.instructions)
        block = narrative.write(session, section_id, principal, made,
                                source=SOURCE_UI, block_id=payload.block_id)
        return {"block": block, "draft": made.to_dict(), "accepted": False,
                "note": ("This is a draft. The pack cannot be approved until "
                         "somebody has read it and put their name to it.")}

    return _guard(run)


# ================================================================= blocks


@router.post("/sections/{section_id}/blocks",
             status_code=status.HTTP_201_CREATED, summary="Put something on a page")
def create_block(section_id: int, payload: BlockIn,
                 session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: svc.create_block(
        session, section_id, principal, source=SOURCE_UI,
        **payload.model_dump()))


@router.patch("/blocks/{block_id}", summary="Change one block")
def patch_block(block_id: int, payload: BlockPatch,
                session: Session = Depends(get_db),
                principal: Principal = RequireCommenter) -> dict:
    changes = _set(payload)
    expected = changes.pop("expected_version", None)
    return _guard(lambda: svc.update_block(
        session, block_id, principal, expected_version=expected,
        source=SOURCE_UI, **changes))


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Take something off a page")
def delete_block(block_id: int, session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> Response:
    _guard(lambda: svc.delete_block(session, block_id, principal,
                                    source=SOURCE_UI))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/blocks/{block_id}/refresh", summary="Recalculate one figure")
def refresh_block(block_id: int, session: Session = Depends(get_db),
                  principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: generation.refresh_block(
        session, block_id, principal, source=SOURCE_UI))


# ============================================================== decisions


@router.get("/decisions", summary="The decision log")
def list_decisions(committee_id: int | None = None, pack_id: int | None = None,
                   decision_status: str | None = Query(default=None,
                                                       alias="status"),
                   session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> dict:
    return {"decisions": _guard(lambda: act.decisions(
        session, principal, committee_id=committee_id, pack_id=pack_id,
        status=decision_status, source=SOURCE_UI))}


@router.post("/packs/{pack_id}/decisions", status_code=status.HTTP_201_CREATED,
             summary="Put a question to the committee")
def create_decision(pack_id: int, payload: DecisionIn,
                    session: Session = Depends(get_db),
                    principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: act.create_decision(
        session, pack_id, principal, source=SOURCE_UI, **payload.model_dump()))


@router.patch("/decisions/{decision_id}", summary="Change a decision paper")
def patch_decision(decision_id: int, payload: DecisionPatch,
                   session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: act.update_decision(
        session, decision_id, principal, source=SOURCE_UI, **_set(payload)))


@router.post("/decisions/{decision_id}/decide",
             summary="Record what the committee decided")
def decide(decision_id: int, payload: DecideIn,
           session: Session = Depends(get_db),
           principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: act.decide(
        session, decision_id, principal, outcome=payload.outcome,
        decision_text=payload.decision_text, conditions=payload.conditions,
        source=SOURCE_UI))


# ================================================================ actions


@router.get("/actions", summary="The action log, with live Planner progress")
def list_actions(committee_id: int | None = None, pack_id: int | None = None,
                 action_status: str | None = Query(default=None,
                                                   alias="status"),
                 mine: bool = False, overdue: bool = False,
                 session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> dict:
    return {"actions": _guard(lambda: act.actions(
        session, principal, committee_id=committee_id, pack_id=pack_id,
        status=action_status, mine=mine, overdue=overdue, source=SOURCE_UI))}


@router.post("/packs/{pack_id}/actions", status_code=status.HTTP_201_CREATED,
             summary="Record that somebody agreed to do something")
def create_action(pack_id: int, payload: ActionIn,
                  session: Session = Depends(get_db),
                  principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: act.create_action(
        session, pack_id, principal, source=SOURCE_UI, **payload.model_dump()))


@router.patch("/actions/{action_id}", summary="Update an action")
def patch_action(action_id: int, payload: ActionPatch,
                 session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: act.update_action(
        session, action_id, principal, source=SOURCE_UI, **_set(payload)))


@router.post("/actions/{action_id}/close",
             summary="Say the work is done, and what shows it")
def close_action(action_id: int, payload: CloseIn,
                 session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: act.close_action(
        session, action_id, principal, evidence=payload.evidence,
        completed=payload.completed, source=SOURCE_UI))


@router.post("/actions/{action_id}/planner",
             summary="Send a committee action to the Project Planner")
def link_action(action_id: int, payload: LinkIn,
                session: Session = Depends(get_db),
                principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: act.link_to_planner(
        session, action_id, principal, project_id=payload.project_id,
        task_code=payload.task_code, workstream_id=payload.workstream_id,
        source=SOURCE_UI))


# ================================================================= export


@router.get("/formats", summary="What a pack can be downloaded as")
def list_formats() -> dict:
    return {"formats": export.formats()}


@router.get("/packs/{pack_id}/export", summary="Download the pack")
def download(pack_id: int, fmt: str = Query(default="pdf", alias="format"),
             session: Session = Depends(get_db),
             principal: Principal = RequireCommenter) -> Response:
    outcome = _guard(lambda: export.export(
        session, pack_id, principal, fmt=fmt, source=SOURCE_UI))
    # Committed before the bytes go out, so a download that fails in transit
    # is still in the log. Somebody took a copy either way.
    session.commit()
    return Response(
        content=outcome["bytes"], media_type=outcome["media_type"],
        headers={
            "Content-Disposition":
                f'attachment; filename="{outcome["filename"]}"',
            "X-CreditProbe-Checksum": outcome["checksum"],
        })


# =============================================================== findings


@router.get("/findings", summary="What has been raised, most serious first")
def list_findings(pack_id: int | None = None, committee_id: int | None = None,
                  status_: str | None = Query(default=None, alias="status"),
                  severity: str | None = None, open_only: bool = False,
                  session: Session = Depends(get_db),
                  principal: Principal = RequireCommenter) -> dict:
    return {"findings": _guard(lambda: find.findings(
        session, principal, pack_id=pack_id, committee_id=committee_id,
        status=status_, severity=severity, open_only=open_only,
        source=SOURCE_UI))}


@router.get("/findings/{finding_id}",
            summary="One finding and the figure behind it")
def read_finding(finding_id: int, session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: find.finding(session, finding_id, principal,
                                       source=SOURCE_UI))


@router.post("/findings/{finding_id}/respond", summary="Answer a finding")
def respond_to_finding(finding_id: int, payload: FindingIn,
                       session: Session = Depends(get_db),
                       principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: find.respond(
        session, finding_id, principal, source=SOURCE_UI,
        **payload.model_dump()))


@router.post("/findings/{finding_id}/reopen",
             summary="Put an answered finding back on the list")
def reopen_finding(finding_id: int, payload: ReopenIn,
                   session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: find.reopen(session, finding_id, principal,
                                      why=payload.why, source=SOURCE_UI))


# ================================================================= import


class MapIn(BaseModel):
    metric_id: str = Field(min_length=1, max_length=160)


@router.get("/packs/{pack_id}/sources",
            summary="Documents attached to this pack")
def list_sources(pack_id: int, session: Session = Depends(get_db),
                 principal: Principal = RequireCommenter) -> dict:
    return {"sources": _guard(lambda: ingest.sources(
        session, pack_id, principal))}


@router.post("/packs/{pack_id}/import", status_code=status.HTTP_201_CREATED,
             summary="Read an existing pack into this draft")
async def import_document(pack_id: int, file: UploadFile = File(...),
                          as_content: bool = True,
                          session: Session = Depends(get_db),
                          principal: Principal = RequireAnalyst) -> dict:
    """Everything this produces is labelled as coming from the document.

    The file is read into memory once and checked before anything parses it —
    size, extension, magic bytes and, for a zip-based format, the contents it
    DECLARES. A file that fails any of those is refused without being opened.
    """
    data = await _bounded_read(file)
    return _guard(lambda: ingest.import_pack(
        session, pack_id, principal, data=data,
        filename=file.filename or "", content_type=file.content_type or "",
        as_content=bool(as_content)).to_dict())


#: Read a chunk at a time rather than the whole body at once.
_CHUNK = 1024 * 1024


async def _bounded_read(file: UploadFile) -> bytes:
    """Take at most one byte more than the limit, then stop.

    `await file.read()` with no argument takes the WHOLE body first and lets
    the size check happen afterwards, which means the limit is a thing the
    server discovers only once it has already accepted a ten-gigabyte upload.
    Reading in chunks and stopping at the first byte past the limit makes the
    refusal cost what the limit costs.

    The one extra byte matters: without it a file exactly at the limit and a
    file far above it are indistinguishable, and the honest refusal below
    would have to fire on a legitimate one.
    """
    room = ingest.MAX_BYTES + 1
    parts: list[bytes] = []
    taken = 0
    while taken < room:
        chunk = await file.read(min(_CHUNK, room - taken))
        if not chunk:
            break
        parts.append(chunk)
        taken += len(chunk)
    data = b"".join(parts)
    if len(data) > ingest.MAX_BYTES:
        # Phrased as `inspect` phrases it, because to somebody uploading a
        # file these are the same refusal arriving at different moments.
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"error": "too_large",
                    "message": (
                        f"That file is larger than "
                        f"{ingest.MAX_BYTES // (1024 * 1024)} MB, which is "
                        "the most a committee pack will read. A dataset that "
                        "size belongs in the Data Builder, where it can be "
                        "governed, rather than pasted into one pack.")})
    return data


@router.post("/blocks/{block_id}/map",
             summary="Point an imported table at a governed metric")
def map_block(block_id: int, payload: MapIn,
              session: Session = Depends(get_db),
              principal: Principal = RequireAnalyst) -> dict:
    return _guard(lambda: ingest.map_to_metric(
        session, block_id, principal, metric_id=payload.metric_id))


# ================================================================== sweep


@router.get("/chase", summary="What the committee sweep would send")
def chase(committee_id: int | None = None,
          session: Session = Depends(get_db),
          principal: Principal = RequireCommenter) -> dict:
    """A dry run. Reads what is outstanding and delivers nothing.

    The screen a pack owner opens to see who they are waiting on, which must
    not have the side effect of notifying all of them.
    """
    def run() -> dict:
        if committee_id is not None:
            access.committee_grant(session, committee_id, principal,
                                   SOURCE_UI)
            wanted = [int(committee_id)]
        else:
            wanted = access.readable_committee_ids(session, principal)
        outstanding = []
        for one in wanted:
            result = monitor.sweep(session, committee_id=one, dry_run=True)
            outstanding.extend(m.to_dict() for m in result.messages)
        return {"outstanding": outstanding, "count": len(outstanding)}

    return _guard(run)


__all__ = ["router"]
