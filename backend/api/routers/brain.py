"""The Brain Center, over HTTP. §13-§26.

Eleven tabs' worth of routes, and the shape of them is the governance.

**Reading is wide, changing is narrow.** Anyone who may see the Studio may
read what Brain is running, what it has learned and what each import
measured. Building an export, uploading a candidate and running an
evaluation are stewards' work. Activating and rolling back are an
administrator's alone, because that is the action that changes what every
answer in the bank is made of.

**Uploading is not installing.** A POST to /imports puts a package in
quarantine and returns what the security scan found. It does not activate
anything, it cannot activate anything, and the candidate's teaching cases
are not in the retrieval path at any point before an installation row
reaches ACTIVE.

**Nothing here calls a provider.** Inspection, compatibility, conflict
detection and the ledger are all deterministic. The one route that measures
anything — the Lift Lab — reads a recorded evaluation rather than running a
model, so opening the Brain Center costs nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.ai_studio import permissions as spm
from backend.api.permissions import (
    Principal,
    RequireBrainActivate,
    RequireBrainEvaluate,
    RequireBrainExport,
    RequireBrainImport,
    RequireBrainRollback,
    RequireBrainSigners,
    RequireBrainView,
)
from backend.brain import bundle as bundle_mod
from backend.brain import conflicts as conflicts_mod
from backend.brain import ledger as ledger_mod
from backend.brain import liftlab, pack, quarantine, security
from backend.brain import status as bstatus
from backend.services import brain_center as bc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brain", tags=["brain"])

#: The largest upload the route will read into memory before inspecting it.
#: Deliberately the same number `security` enforces: a route that accepted
#: more than the scanner will accept would spend the memory to find out.
MAX_UPLOAD_BYTES = security.MAX_PACKAGE_BYTES


def _session():
    from backend.db.engine import SessionLocal

    return SessionLocal()


def _actor(principal: Principal) -> str:
    return f"user:{principal.user_id}" if principal.user_id else "system"


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                         detail={"error": "brain_refused",
                                 "message": str(exc)})


# =========================================================== CURRENT BRAIN


@router.get("/overview")
def overview(principal: Principal = RequireBrainView) -> dict[str, Any]:
    """§25's CURRENT BRAIN tab. What is running, and how honest it is.

    The counts are kept apart on purpose. Captured, approved and activated
    are three different numbers, and a screen that added them would report
    an installation that has learned nothing as one that has learned a great
    deal.
    """
    from backend.semantics import ontology

    with _session() as session:
        census = bc.ledger_census(session, tenant="")
        history = bc.installation_history(session, tenant="")
    active = next((h for h in history if h["state"] == "ACTIVE"), None)
    return {
        "current": {
            "ontology_version": ontology.ONTOLOGY_VERSION,
            "package_schema_version": pack.PACKAGE_SCHEMA_VERSION,
            "ledger_schema_version": ledger_mod.LEDGER_SCHEMA_VERSION,
            "installed_brain": active,
        },
        "dimensions": list(liftlab.DIMENSIONS),
        "learning": census,
        "retrieval_policy": bstatus.policy_summary(),
        "installations": len(history),
        "known_limitations": [
            "Every improvement number on this screen was measured against "
            "this installation's own sealed holdout. A Brain that scores "
            "well here has not been shown to score well anywhere else.",
            "Learning captured is not learning approved, and learning "
            "approved is not learning activated. The three counts above are "
            "deliberately not added together.",
        ],
    }


# =========================================================== LEARNING LEDGER


class LedgerBody(BaseModel):
    source: str = Field(..., max_length=32)
    summary: str = Field(..., max_length=2000)
    object_kind: str = Field(default="", max_length=32)
    object_id: str = Field(default="", max_length=64)
    body: dict[str, Any] = Field(default_factory=dict)


@router.get("/ledger")
def ledger(limit: int = Query(default=100, ge=1, le=500),
           principal: Principal = RequireBrainView) -> dict[str, Any]:
    """§13. What has been learned here, and how little of it is production."""
    with _session() as session:
        census = bc.ledger_census(session, tenant="")
    return {
        "census": census,
        "sources": list(ledger_mod.SOURCES),
        "review_statuses": list(ledger_mod.REVIEW_STATUSES),
        "portability_states": list(ledger_mod.PORTABILITY),
        "eligibility_conditions": [
            {"check": name, "means": why}
            for name, why in ledger_mod.ELIGIBILITY],
        "note": (
            "An entry is never updated and never deleted. A wrong entry is "
            "superseded by a new one that points at it, so what this "
            "installation believed at the time stays answerable."
        ),
    }


@router.post("/ledger", status_code=status.HTTP_201_CREATED)
def capture_learning(payload: LedgerBody,
                     principal: Principal = RequireBrainView
                     ) -> dict[str, Any]:
    """Record one thing learned. Activates nothing, by construction."""
    try:
        entry = ledger_mod.capture(
            payload.source, payload.summary,
            object_kind=payload.object_kind, object_id=payload.object_id,
            body=payload.body, user_id=_actor(principal))
    except ledger_mod.LedgerError as exc:
        raise _refused(exc) from exc
    with _session() as session:
        row = bc.record_learning(session, entry, tenant="")
        session.commit()
        return {"entry_id": row.entry_id, "review_status": row.review_status,
                "portability": row.portability,
                "activates_nothing": True}


# ==================================================================== EXPORT


class ExportBody(BaseModel):
    kind: str = Field(default=pack.BRAIN_PACK, max_length=16)
    brain_id: str = Field(..., max_length=64)
    brain_name: str = Field(..., max_length=160)
    brain_version: str = Field(..., max_length=32)
    baseline_release_id: str = Field(default="", max_length=64)
    known_limitations: list[str] = Field(default_factory=list)


@router.get("/export/kinds")
def export_kinds(principal: Principal = RequireBrainView) -> dict[str, Any]:
    """The three packages, and what each is for."""
    return {
        "kinds": [
            {"id": pack.BRAIN_PACK, "suffix": pack.SUFFIX[pack.BRAIN_PACK],
             "label": "Brain Pack",
             "purpose": "The whole intelligence layer. Send this when "
                        "another installation should think the way this one "
                        "does."},
            {"id": pack.LEARNING_BUNDLE,
             "suffix": pack.SUFFIX[pack.LEARNING_BUNDLE],
             "label": "Learning Bundle",
             "purpose": "The delta since a named baseline. Send this when "
                        "the receiver already has a Brain and should get the "
                        "improvement rather than a replacement.",
             "requires": ["baseline_release_id"]},
            {"id": pack.DEVELOPER_BUNDLE,
             "suffix": pack.SUFFIX[pack.DEVELOPER_BUNDLE],
             "label": "Developer Intelligence Bundle",
             "purpose": "The approved assets plus README_FOR_CLAUDE_CODE.md, "
                        "for reading in a development session rather than "
                        "installing into a running system."},
        ],
        "never_included": list(bundle_mod.DEVELOPER_EXCLUSIONS),
        "exportable_case_status": bundle_mod.EXPORTABLE_CASE_STATUS,
    }


@router.post("/export", status_code=status.HTTP_201_CREATED)
def build_export(payload: ExportBody,
                 principal: Principal = RequireBrainExport) -> dict[str, Any]:
    """Build a package, or refuse to.

    Every check that runs on import runs inside the writer, so a package
    this installation would refuse to import is one it refuses to write.
    """
    manifest = pack.Manifest(
        brain_id=payload.brain_id, brain_name=payload.brain_name,
        brain_version=payload.brain_version,
        created_by=_actor(principal),
        known_limitations=tuple(payload.known_limitations),
    )
    _stamp(manifest)
    with _session() as session:
        try:
            row = bc.build_export(
                session, kind=payload.kind, manifest=manifest,
                actor=_actor(principal),
                baseline_release_id=payload.baseline_release_id)
        except (bc.BrainCenterError, bundle_mod.BundleError,
                pack.PackError) as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"package_id": row.package_id, "kind": row.package_kind,
                "sha256": row.sha256, "size_bytes": row.size_bytes,
                "entry_count": row.entry_count,
                "download": f"/api/v1/brain/export/{row.package_id}"}


def _stamp(manifest: pack.Manifest) -> None:
    """Fill in what this installation knows about itself."""
    from backend import build_info
    from backend.semantics import ontology

    manifest.app_version = getattr(build_info, "VERSION", "0.0.0")
    manifest.minimum_app_version = manifest.app_version
    manifest.maximum_tested_app_version = manifest.app_version
    manifest.source_build_sha = getattr(build_info, "GIT_SHA", "") or "unknown"
    manifest.source_instance_id = getattr(build_info, "INSTANCE_ID", "") \
        or "creditprobe-local"
    manifest.ontology_version = ontology.ONTOLOGY_VERSION


@router.get("/export/{package_id}")
def download_export(package_id: str,
                    principal: Principal = RequireBrainExport):
    """Hand back the bytes of a package this installation built."""
    with _session() as session:
        try:
            row = bc._require_package(session, package_id)
        except bc.BrainCenterError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail={"error": "not_found",
                                        "message": str(exc)}) from exc
        if row.direction != bc.EXPORT or not row.storage_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found",
                        "message": "that package has no downloadable "
                                   "payload here"})
        filename = f"{row.brain_name or 'brain'}-{row.brain_version}" \
                   f"{pack.SUFFIX.get(row.package_kind, '.zip')}"
        return FileResponse(row.storage_path, filename=filename,
                            media_type="application/zip")


# =================================================== IMPORTS and QUARANTINE


@router.get("/imports")
def imports(principal: Principal = RequireBrainView) -> dict[str, Any]:
    """§16. Every candidate, and how far through the pipeline it got."""
    from sqlalchemy import select

    from backend.models.platform import BrainImport

    with _session() as session:
        rows = session.execute(
            select(BrainImport).order_by(
                BrainImport.created_at.desc())).scalars().all()
        return {
            "pipeline": list(quarantine.PIPELINE),
            "quarantined_stages": sorted(quarantine.QUARANTINED),
            "imports": [{
                "import_id": r.import_id,
                "package_id": r.package_id,
                "stage": r.stage,
                "state": r.state,
                "blockers": r.blockers or [],
                "approvals": r.approvals or [],
                "decision": r.decision,
                "uploaded_by": r.uploaded_by,
                "created_at": r.created_at.isoformat()
                if r.created_at else "",
                "retrievable": False,
            } for r in rows],
            "note": (
                "No candidate is in the retrieval path. A Brain's teaching "
                "cases reach a live answer only once its installation is "
                "ACTIVE."
            ),
        }


@router.post("/imports", status_code=status.HTTP_201_CREATED)
async def upload(file: UploadFile = File(...),
                 principal: Principal = RequireBrainImport) -> dict[str, Any]:
    """Take a package into quarantine. Never into production.

    The package is inspected from its own archive metadata before any member
    is read out, so a decompression bomb is refused rather than expanded.
    """
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise _refused(ValueError(
            f"this package is {len(payload)} bytes; the limit is "
            f"{MAX_UPLOAD_BYTES}"))
    with _session() as session:
        package, record = bc.receive_package(
            session, payload, filename=file.filename or "upload.cpbrain",
            actor=_actor(principal))
        session.commit()
        return {
            "import_id": record.import_id,
            "package_id": package.package_id,
            "stage": record.stage,
            "state": record.state,
            "blockers": record.blockers or [],
            "signature_state": package.signature_state,
            "signer_trust": package.signer_trust,
            "activated": False,
            "note": ("This package is in quarantine. Nothing in it can reach "
                     "a live answer until it is evaluated, approved and "
                     "activated."),
        }


@router.get("/imports/{import_id}")
def read_import(import_id: str,
                principal: Principal = RequireBrainView) -> dict[str, Any]:
    with _session() as session:
        try:
            record = bc._require_import(session, import_id)
        except bc.BrainCenterError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail={"error": "not_found",
                                        "message": str(exc)}) from exc
        ok, reasons = bc.may_activate(session, import_id)
        return {
            "import_id": record.import_id,
            "package_id": record.package_id,
            "stage": record.stage,
            "state": record.state,
            "history": record.stage_history or [],
            "blockers": record.blockers or [],
            "security": record.security_report or {},
            "compatibility": record.compatibility_report or {},
            "diff": record.component_diff or {},
            "evaluation": record.evaluation or {},
            "impact": record.impact_report or {},
            "approvals": record.approvals or [],
            "may_activate": ok,
            "activation_blocked_by": reasons,
        }


class StageBody(BaseModel):
    stage: str = Field(..., max_length=32)
    passed: bool = True
    detail: str = Field(default="", max_length=2000)


@router.post("/imports/{import_id}/advance")
def advance(import_id: str, payload: StageBody,
            principal: Principal = RequireBrainEvaluate) -> dict[str, Any]:
    """Move one stage. Refuses a skipped stage rather than allowing it."""
    with _session() as session:
        try:
            record = bc.advance_import(
                session, import_id, payload.stage, actor=_actor(principal),
                passed=payload.passed, detail=payload.detail)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"import_id": record.import_id, "stage": record.stage,
                "state": record.state, "blockers": record.blockers or []}


# ============================================================= COMPATIBILITY


@router.post("/imports/{import_id}/compatibility")
def compatibility(import_id: str,
                  principal: Principal = RequireBrainEvaluate
                  ) -> dict[str, Any]:
    """§17. What this receiver can and cannot run from this package."""
    with _session() as session:
        try:
            report = bc.check_compatibility(session, import_id)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        session.commit()
        return report


# ================================================================= CONFLICTS


class ResolveBody(BaseModel):
    resolution: str = Field(..., max_length=32)
    reason: str = Field(..., max_length=2000)
    split_axis: str = Field(default="", max_length=48)


@router.get("/conflicts")
def list_conflicts(import_id: str = Query(default=""),
                   principal: Principal = RequireBrainView) -> dict[str, Any]:
    """§20/§21. Contradictory learning, and how each was settled."""
    from sqlalchemy import select

    from backend.models.platform import BrainConflict

    with _session() as session:
        query = select(BrainConflict).order_by(BrainConflict.created_at.desc())
        if import_id:
            query = query.where(BrainConflict.import_id == import_id)
        rows = session.execute(query).scalars().all()
        return {
            "classes": [{"id": cid, "means": means}
                        for cid, means in conflicts_mod.CLASSES],
            "resolutions": list(conflicts_mod.RESOLUTIONS),
            "conflicts": [{
                "conflict_id": r.conflict_id,
                "import_id": r.import_id,
                "conflict_class": r.conflict_class,
                "severity": r.severity,
                "summary": r.summary,
                "incoming": r.incoming or {},
                "existing": r.existing or {},
                "recommendation": r.recommendation,
                "recommendation_reason": r.recommendation_reason,
                "resolution": r.resolution,
                "resolution_reason": r.resolution_reason,
                "split_axis": r.split_axis,
                "resolved_by": r.resolved_by,
            } for r in rows],
            "note": (
                "There is no 'newer wins'. Recency is not evidence, and a "
                "receiver that adopted a stranger's threshold because it "
                "arrived later would have no answer when asked why."
            ),
        }


@router.post("/conflicts/{conflict_id}/resolve")
def resolve(conflict_id: str, payload: ResolveBody,
            principal: Principal = RequireBrainEvaluate) -> dict[str, Any]:
    with _session() as session:
        try:
            row = bc.resolve_conflict(
                session, conflict_id, resolution=payload.resolution,
                reason=payload.reason, actor=_actor(principal),
                split_axis=payload.split_axis)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"conflict_id": row.conflict_id, "resolution": row.resolution,
                "resolved_by": row.resolved_by,
                "split_axis": row.split_axis}


# =================================================================== LIFT LAB


@router.get("/lift/{import_id}")
def lift(import_id: str,
         principal: Principal = RequireBrainView) -> dict[str, Any]:
    """§18/§19. The measured lift, and what it does not establish."""
    with _session() as session:
        try:
            record = bc._require_import(session, import_id)
        except bc.BrainCenterError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail={"error": "not_found",
                                        "message": str(exc)}) from exc
        evaluation = record.evaluation or {}
        return {
            "import_id": import_id,
            "measured": bool(evaluation),
            "evaluation": evaluation,
            "impact": record.impact_report or {},
            "rules": {
                "minimum_cases": liftlab.MINIMUM_CASES,
                "material_points": liftlab.MATERIAL_POINTS,
                "senders_holdout_measures_nothing": True,
                "critical_regression_overrides_average": True,
            },
            "note": (
                "" if evaluation else
                "This candidate has not been evaluated. That is not a "
                "neutral result: approving it would be approving a claim."
            ),
        }


# ============================================ APPROVAL, INSTALL and ROLLBACK


class ApprovalBody(BaseModel):
    role: str = Field(default="REVIEWER", max_length=32)
    note: str = Field(default="", max_length=2000)


@router.post("/imports/{import_id}/approve")
def approve(import_id: str, payload: ApprovalBody,
            principal: Principal = RequireBrainActivate) -> dict[str, Any]:
    """Record one approval. Not an activation."""
    with _session() as session:
        try:
            record = bc.approve_import(session, import_id,
                                       actor=_actor(principal),
                                       role=payload.role, note=payload.note)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        ok, reasons = bc.may_activate(session, import_id)
        session.commit()
        return {"import_id": record.import_id,
                "approvals": record.approvals or [],
                "may_activate": ok, "activation_blocked_by": reasons}


class ActivateBody(BaseModel):
    release_id: str = Field(default="", max_length=64)


@router.post("/imports/{import_id}/activate")
def activate(import_id: str, payload: ActivateBody,
             principal: Principal = RequireBrainActivate) -> dict[str, Any]:
    """§22. Make an evaluated, approved, compatible Brain the active one."""
    with _session() as session:
        try:
            installation = bc.activate_import(
                session, import_id, actor=_actor(principal),
                release_id=payload.release_id)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"installation_id": installation.installation_id,
                "state": installation.state,
                "activated_at": installation.activated_at.isoformat()
                if installation.activated_at else ""}


class RollbackBody(BaseModel):
    reason: str = Field(..., max_length=2000)


@router.post("/installations/{installation_id}/rollback")
def rollback(installation_id: str, payload: RollbackBody,
             principal: Principal = RequireBrainRollback) -> dict[str, Any]:
    """§23. Undo an activation. The record of it stays."""
    with _session() as session:
        try:
            row = bc.roll_back(session, installation_id,
                               actor=_actor(principal),
                               reason=payload.reason)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"installation_id": row.installation_id, "state": row.state,
                "rolled_back_at": row.rolled_back_at.isoformat()
                if row.rolled_back_at else "",
                "reason": row.rollback_reason}


class DeleteBody(BaseModel):
    reason: str = Field(..., max_length=2000)


@router.post("/imports/{import_id}/delete")
def delete(import_id: str, payload: DeleteBody,
           principal: Principal = RequireBrainRollback) -> dict[str, Any]:
    """§23. Delete a candidate that never activated.

    Only before activation. Once a Brain has answered a question, deleting
    what it was would leave those answers unexplainable.
    """
    with _session() as session:
        try:
            record = bc.delete_import(session, import_id,
                                      actor=_actor(principal),
                                      why=payload.reason)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"import_id": record.import_id, "state": record.state,
                "payload_purged": True, "record_kept": True}


# ============================================ INSTALLATIONS and ROLLBACKS


@router.get("/installations")
def installations(principal: Principal = RequireBrainView) -> dict[str, Any]:
    """§24's timeline.

    Every row answers §24's question by itself: what was integrated, when,
    by whom, and how much improvement it produced. A row that cannot answer
    the last part says so rather than showing a blank.
    """
    with _session() as session:
        history = bc.installation_history(session, tenant="")
    return {
        "installations": history,
        "rollbacks": [h for h in history if h["state"] == "ROLLED_BACK"],
        "answers": ("What Brain was integrated, when, by whom, and how much "
                    "improvement did it produce?"),
    }


# ================================================================== SECURITY


class SignerBody(BaseModel):
    key_id: str = Field(..., max_length=64)
    label: str = Field(default="", max_length=160)
    organization: str = Field(default="", max_length=160)
    trust_level: str = Field(default=bc.TRUST_LOW, max_length=16)
    reason: str = Field(..., max_length=2000)
    key_fingerprint: str = Field(default="", max_length=64)


@router.get("/security")
def security_policy(principal: Principal = RequireBrainView
                    ) -> dict[str, Any]:
    """§26. What is enforced, and the signers this installation trusts."""
    from sqlalchemy import select

    from backend.models.platform import BrainSigner

    with _session() as session:
        signers = session.execute(select(BrainSigner)).scalars().all()
        return {
            "limits": {
                "max_package_bytes": security.MAX_PACKAGE_BYTES,
                "max_entry_bytes": security.MAX_ENTRY_BYTES,
                "max_total_bytes": security.MAX_TOTAL_BYTES,
                "max_entries": security.MAX_ENTRIES,
                "max_compression_ratio": security.MAX_COMPRESSION_RATIO,
            },
            "allowed_formats": sorted(security.ALLOWED_SUFFIXES),
            "never_packaged": list(pack.FORBIDDEN_PATHS),
            "enforced": [
                "Package hashes, checked per member.",
                "Digital signature, verified against a key in the registry "
                "below and never against one that arrived with the package.",
                "Zip-slip protection: no member may escape the extraction "
                "root, and no symlink member is accepted at all.",
                "Decompression-bomb protection, decided from declared sizes "
                "before any member is read out.",
                "An allowlist of formats, not a blocklist of bad ones.",
                "No deserialization of arbitrary objects: every member is "
                "JSON, JSONL, Markdown or CSV, and nothing in a package "
                "runs.",
                "A secret scanner that reports what it found without ever "
                "echoing the secret.",
                "A client-data scanner: a Brain carries patterns, not rows.",
            ],
            "signers": [{
                "key_id": s.key_id, "label": s.label,
                "organization": s.organization,
                "trust_level": s.trust_level,
                "added_by": s.added_by, "added_reason": s.added_reason,
                "revoked_by": s.revoked_by,
                "revoked_reason": s.revoked_reason,
            } for s in signers],
            "untrusted_signer_policy": (
                "A package from an untrusted signer may be inspected and "
                "evaluated, and may not be activated. Blocking it at upload "
                "would stop a reviewer examining a package they had every "
                "right to look at."
            ),
            "permissions": {p: spm.MEANS[p] for p in (
                spm.BRAIN_VIEW, spm.BRAIN_EXPORT, spm.BRAIN_IMPORT,
                spm.BRAIN_ACTIVATE)},
        }


@router.post("/security/signers", status_code=status.HTTP_201_CREATED)
def add_signer(payload: SignerBody,
               principal: Principal = RequireBrainSigners) -> dict[str, Any]:
    with _session() as session:
        try:
            row = bc.add_signer(
                session, key_id=payload.key_id, label=payload.label,
                actor=_actor(principal), reason=payload.reason,
                trust_level=payload.trust_level,
                organization=payload.organization,
                key_fingerprint=payload.key_fingerprint)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"key_id": row.key_id, "trust_level": row.trust_level,
                "added_by": row.added_by}


@router.post("/security/signers/{key_id}/revoke")
def revoke_signer(key_id: str, payload: RollbackBody,
                  principal: Principal = RequireBrainSigners
                  ) -> dict[str, Any]:
    """Withdraw trust. Brains already activated stay activated.

    Revocation is not a rollback: a Brain that has been answering questions
    for three months does not become wrong because its signer did.
    """
    with _session() as session:
        try:
            row = bc.revoke_signer(session, key_id, actor=_actor(principal),
                                   reason=payload.reason)
        except bc.BrainCenterError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"key_id": row.key_id, "trust_level": row.trust_level,
                "revoked_by": row.revoked_by,
                "activated_brains_unaffected": True}


# ================================================== §21/§22 MERGE LAB: MERGE


class MergeBody(BaseModel):
    brain_name: str = Field(..., max_length=120)
    brain_version: str = Field(default="1.0.0", max_length=32)
    #: conflict_id -> the body a person wrote for CREATE NEW VERSION or
    #: MERGE MANUALLY. The merge will not invent these.
    authored: dict[str, dict[str, Any]] = Field(default_factory=dict)


@router.get("/merge/{import_id}")
def merge_preview(import_id: str,
                  principal: Principal = RequireBrainView) -> dict[str, Any]:
    """§21/§22. What a merge with this import would produce."""
    with _session() as session:
        try:
            return bc.merge_preview(session, import_id)
        except bc.BrainCenterError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": str(exc)}) from exc


@router.post("/merge/{import_id}", status_code=status.HTTP_201_CREATED)
def build_merge(import_id: str, payload: MergeBody,
                principal: Principal = RequireBrainEvaluate) -> dict[str, Any]:
    """§21/§22. Produce the third Brain from two, as a package.

    It is written, not activated. A merged Brain has never been evaluated,
    so it takes the same quarantine, Lift Lab and approval path as any
    other Brain that arrived from somewhere else.
    """
    from backend.brain import merge as merge_mod

    with _session() as session:
        try:
            row = bc.build_merge(
                session, import_id, actor=_actor(principal),
                brain_name=payload.brain_name,
                brain_version=payload.brain_version,
                authored=payload.authored)
        except (bc.BrainCenterError, merge_mod.MergeError,
                pack.PackError) as exc:
            raise _refused(exc) from exc
        session.commit()
        return {
            "package_id": row.package_id,
            "brain_id": row.brain_id,
            "brain_name": row.brain_name,
            "brain_version": row.brain_version,
            "entry_count": row.entry_count,
            "size_bytes": row.size_bytes,
            "evaluated": False,
            "next_step": (
                "This Brain has never been run. Measure it against your own "
                "baseline in the Lift Lab before activating any part of it."),
        }
