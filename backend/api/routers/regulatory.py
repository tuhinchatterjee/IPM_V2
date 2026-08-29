"""
Regulatory circular knowledge and the human teaching corpus, over HTTP.
Part G, §5.

Who may do what, and why
-------------------------
Uploading a circular is a Data Steward's job: it puts a document into the
corpus every answer may quote. Reviewing a rule and approving a document is an
Administrator's — those are the acts that decide what CreditProbe is allowed
to say about the law. Reading the corpus report is open to any analyst,
because the honest counts are exactly what a user should be able to check
before trusting a regulatory answer.

Asking a regulatory question is open to any analyst, and returns nothing until
a release is active. That is not a permission error and the response says so.

What no route here does
------------------------
Nothing approves anything as a side effect. There is no route that uploads and
approves, no route that imports and publishes, and no route that activates a
release without a named approver who is not the only reviewer. Every one of
those would be a shortcut past the reason the area exists.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireAdmin,
    RequireAnalyst,
    RequireDataSteward,
)
from backend.db.engine import get_session
from backend.regulatory import extract as ex
from backend.regulatory import release as rl
from backend.regulatory import schema as rs
from backend.services import regulatory as svc
from backend.teaching import importer as im

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/regulatory", tags=["regulatory"])
corpus_router = APIRouter(prefix="/teaching-corpus", tags=["regulatory"])


def _tenant(principal: Principal) -> str:
    """The tenant a caller's uploads belong to.

    Single-tenant deployments carry no tenant on the principal, and "" is a
    real tenant rather than a wildcard: a document uploaded with no tenant is
    reachable only by callers with no tenant. That is fail-closed in the
    direction that matters — a mistake here shows one bank another bank's
    supervisory correspondence.
    """
    return str(getattr(principal, "tenant", "") or "")


def _roles_for(principal: Principal) -> frozenset[str]:
    """Which confidentiality classes this caller may read.

    An Administrator sees supervisory correspondence; everybody else sees
    public rulebooks and the bank's own restricted circulars. The exclusion is
    reported in the answer rather than silently narrowing it.
    """
    if str(getattr(principal, "role", "")).upper() == "ADMIN":
        return frozenset({rs.PUBLIC, rs.RESTRICTED, rs.CONFIDENTIAL})
    return frozenset({rs.PUBLIC, rs.RESTRICTED})


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


@router.get("/capability")
def capability(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """What this deployment can read, before anybody uploads anything."""
    del principal
    return {"extraction": ex.availability(),
            "formats": sorted(rs.EXTENSIONS),
            "confidentiality": {c: rs.CONFIDENTIALITY_MEANS[c]
                                for c in rs.CONFIDENTIALITY},
            "rule_kinds": {k: rs.RULE_MEANS[k] for k in rs.RULE_KINDS},
            "statuses": dict(rs.STATUS_MEANS),
            "max_bytes": __import__(
                "backend.regulatory.store", fromlist=["MAX_BYTES"]).MAX_BYTES}


@router.get("/report")
def report(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """The honest corpus counts. §6's discipline, applied to Part G."""
    with get_session() as session:
        return svc.corpus_report(session, tenant=_tenant(principal))


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post("/circulars", status_code=status.HTTP_201_CREATED)
async def upload_circular(
    file: UploadFile = File(...),
    title: str = Form(...),
    regulator: str = Form(...),
    reference: str = Form(...),
    effective: str = Form(...),
    issued: str = Form(""),
    expires: str = Form(""),
    jurisdiction: str = Form(""),
    language: str = Form("en"),
    confidentiality: str = Form(rs.RESTRICTED),
    supersedes: str = Form(""),
    notes: str = Form(""),
    principal: Principal = RequireDataSteward,
) -> dict[str, Any]:
    """Store one original, extract it, and report what came out.

    `supersedes` is a semicolon-separated list of the regulator's own
    references. Only explicit declarations count: a circular is never inferred
    to replace another because it covers the same ground, because regulators
    restate far more often than they replace and a guess silently removes a
    rule that is still in force.
    """
    payload = await file.read()
    replaced = [s.strip() for s in str(supersedes or "").split(";")
                if s.strip()]
    try:
        with get_session() as session:
            found = svc.upload(
                session, payload, filename=file.filename or "upload",
                title=title, regulator=regulator, reference=reference,
                effective=effective, issued=issued, expires=expires,
                jurisdiction=jurisdiction, language=language,
                confidentiality=confidentiality, tenant=_tenant(principal),
                supersedes=replaced,
                uploaded_by=str(getattr(principal, "user_id", "")),
                notes=notes, concepts=_concepts())
            session.commit()
            return found
    except svc.RegulatoryServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except rs.RegulatoryError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


def _concepts() -> tuple[str, ...]:
    """The governed concept labels, so an extracted rule can be found by the
    words a credit officer would use for it."""
    try:
        from backend.semantics import ontology

        return tuple(str(c.label) for c in ontology.concepts())
    except Exception:  # noqa: BLE001 - a rule with no concepts is still a rule
        return ()


@router.get("/circulars")
def list_circulars(principal: Principal = RequireAnalyst,
                   status_filter: str = "") -> dict[str, Any]:
    with get_session() as session:
        found = svc.documents(session, tenant=_tenant(principal),
                              status=status_filter)
    allowed = _roles_for(principal)
    return {"circulars": [c.to_dict() for c in found
                          if c.confidentiality in allowed],
            "withheld": sum(1 for c in found
                            if c.confidentiality not in allowed)}


@router.get("/circulars/{circular_id}")
def read_circular(circular_id: str,
                  principal: Principal = RequireAnalyst) -> dict[str, Any]:
    with get_session() as session:
        try:
            row = svc.document(session, circular_id)
        except svc.RegulatoryServiceError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        if row.tenant != _tenant(principal):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "no such circular")
        if row.confidentiality not in _roles_for(principal):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"{row.confidentiality} content is not readable at this role")
        return {**dict(row.body or {}), "extraction": dict(row.extraction
                                                           or {})}


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


@router.get("/review-queue")
def review_queue(principal: Principal = RequireAdmin,
                 limit: int = 50) -> dict[str, Any]:
    """What an SME should look at next, hardest first."""
    with get_session() as session:
        rows = svc.review_queue(session, tenant=_tenant(principal),
                                limit=limit)
    return {"rows": rows, "count": len(rows),
            "decisions": list(rl.DECISIONS),
            "ordering": ("Thresholds first: a wrong number is quoted verbatim "
                         "into a credit paper. Then exceptions, then "
                         "obligations, then definitions.")}


class ReviewRequest(BaseModel):
    decision: str = Field(..., description="; ".join(rl.DECISIONS))
    note: str = Field(..., min_length=1)
    text: str = ""


@router.post("/circulars/{circular_id}/rules/{rule_id}/review")
def review_rule(circular_id: str, rule_id: str, body: ReviewRequest,
                principal: Principal = RequireAdmin) -> dict[str, Any]:
    reviewer = str(getattr(principal, "user_id", "") or "").strip()
    try:
        with get_session() as session:
            found = svc.review_rule(session, circular_id, rule_id,
                                    decision=body.decision, reviewer=reviewer,
                                    note=body.note, text=body.text)
            session.commit()
            return found
    except (svc.RegulatoryServiceError, rl.ReleaseError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


class ApproveRequest(BaseModel):
    note: str = Field(..., min_length=1)


@router.post("/circulars/{circular_id}/approve")
def approve(circular_id: str, body: ApproveRequest,
            principal: Principal = RequireAdmin) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.approve_document(
                session, circular_id,
                approver=str(getattr(principal, "user_id", "")),
                note=body.note)
            session.commit()
            return found
    except svc.RegulatoryServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------


class ReleaseRequest(BaseModel):
    note: str = ""


@router.post("/releases", status_code=status.HTTP_201_CREATED)
def build_release(body: ReleaseRequest,
                  principal: Principal = RequireAdmin) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.build_release(
                session, created_by=str(getattr(principal, "user_id", "")),
                tenant=_tenant(principal), note=body.note)
            session.commit()
            return found
    except rl.ReleaseError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/releases")
def list_releases(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    with get_session() as session:
        found = svc.releases(session, tenant=_tenant(principal))
        active = svc.active_release(session, tenant=_tenant(principal))
    return {"releases": found,
            "active": active.release_id if active else "",
            "note": ("Production uses one active release. An answer records "
                     "which, so what it was based on stays explicable.")}


@router.post("/releases/{release_id}/activate")
def activate(release_id: str,
             principal: Principal = RequireAdmin) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.activate_release(
                session, release_id,
                approver=str(getattr(principal, "user_id", "")))
            session.commit()
            return found
    except (svc.RegulatoryServiceError, rl.ReleaseError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


class RollbackRequest(BaseModel):
    why: str = Field(..., min_length=1)


@router.post("/releases/rollback")
def rollback(body: RollbackRequest,
             principal: Principal = RequireAdmin) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.rollback_release(
                session, approver=str(getattr(principal, "user_id", "")),
                why=body.why, tenant=_tenant(principal))
            session.commit()
            return found
    except (svc.RegulatoryServiceError, rl.ReleaseError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3)
    #: The REPORTING date, not today. A paper written for Q2 2025 must quote
    #: the rules in force then.
    as_of: str = ""
    kinds: list[str] = Field(default_factory=list)
    limit: int = 8


@router.post("/ask")
def ask(body: AskRequest,
        principal: Principal = RequireAnalyst) -> dict[str, Any]:
    when = date.today()
    if body.as_of:
        try:
            when = date.fromisoformat(body.as_of[:10])
        except ValueError as e:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{body.as_of!r} is not a date. A regulatory answer is always "
                "as of a reporting date.") from e
    kinds = tuple(k for k in body.kinds if k in rs.RULE_KINDS)
    with get_session() as session:
        return svc.ask(session, body.question, when=when,
                       tenant=_tenant(principal),
                       roles=_roles_for(principal), kinds=kinds,
                       limit=max(1, min(int(body.limit or 8), 50)))


# ---------------------------------------------------------------------------
# The human teaching corpus
# ---------------------------------------------------------------------------


@corpus_router.get("/template")
def template(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """The 500+ Q&A template, as rows the client fills in.

    Generated from the same tuple the importer validates against, so the file
    a bank fills in and the contract it is checked against cannot drift apart.
    """
    del principal
    return {"columns": im.template_rows(),
            "required": list(im.REQUIRED_COLUMNS),
            "formats": list(im.IMPORT_FORMATS),
            "max_rows": im.MAX_ROWS,
            "note": ("Column names are matched by what they mean, so a "
                     "workbook that calls the question column 'Prompt' or "
                     "'User Question' imports without being rewritten. Any "
                     "column nothing was read from is reported rather than "
                     "ignored.")}


@corpus_router.post("/preview")
async def preview(file: UploadFile = File(...),
                  principal: Principal = RequireDataSteward) -> dict[str, Any]:
    """What an import would do, before it does any of it."""
    del principal
    payload = await file.read()
    name = (file.filename or "").lower()
    file_format = (im.XLSX if name.endswith((".xlsx", ".xlsm"))
                   else im.JSONL if name.endswith((".jsonl", ".ndjson"))
                   else im.CSV)
    found = im.preview(payload, file_format,
                       batch=f"pre{uuid.uuid4().hex[:6]}")
    return {**found.to_dict(), "errors": im.error_workbook(found)}


class ImportRequest(BaseModel):
    #: The caller confirming they have seen the preview. An import that ran
    #: straight from an upload would give nobody the chance to notice that
    #: column F was never read.
    confirmed: bool = False
    note: str = ""


@corpus_router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_corpus(
    file: UploadFile = File(...),
    confirmed: bool = Form(False),
    note: str = Form(""),
    principal: Principal = RequireDataSteward,
) -> dict[str, Any]:
    """Write the accepted rows as cases awaiting review.

    Nothing here is approved. Every case arrives SME_REVIEW_REQUIRED with
    `authoring_method = HUMAN`, is not retrievable, and does not enter a
    Teaching Release by being written.
    """
    if not confirmed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "run the preview and confirm it before importing: an import whose "
            "first visible output is a count gives nobody the chance to "
            "notice a column that was never read")

    from backend.services import teaching_library as tl

    payload = await file.read()
    name = (file.filename or "").lower()
    file_format = (im.XLSX if name.endswith((".xlsx", ".xlsm"))
                   else im.JSONL if name.endswith((".jsonl", ".ndjson"))
                   else im.CSV)
    batch = f"imp{uuid.uuid4().hex[:6]}"
    found = im.preview(payload, file_format, batch=batch)
    if found.fatal:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, found.fatal)

    actor = str(getattr(principal, "user_id", "") or "import")
    written = 0
    failed: list[dict[str, Any]] = []
    with get_session() as session:
        for row in found.importable:
            try:
                tl.save(session, row.case, actor=actor)
                written += 1
            except Exception as e:  # noqa: BLE001 - one row, not the batch
                failed.append({"row": row.number, "why": str(e)})
        session.commit()

    return {**found.to_dict(), "batch": batch, "written": written,
            "failed": failed, "note": note,
            "status": "SME_REVIEW_REQUIRED",
            "retrievable": False,
            "what_happens_next": (
                f"{written} case(s) are in the library awaiting review. None "
                "of them is retrievable, none is in a Teaching Release, and "
                "none becomes either by having been uploaded.")}


__all__ = ["corpus_router", "router"]
