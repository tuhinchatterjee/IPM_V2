"""
The Playbook workspace over HTTP.

Every route resolves a `Principal` and scopes what it reads and writes to that
caller's tenant — including the reads. The existing `/playbooks` router (the
standing-instruction feature, which this one does not touch) leaves its two GET
routes without a principal, so `REQUIRE_LOGIN` does not reach them; that is
recorded in docs/playbook/PROGRESS.md as a finding about that feature, and is
not repeated here.

Two refusals are load-bearing rather than defensive:

* An exported-analysis id that belongs to another tenant, or was never
  exported, returns 404 — the same answer for both, because "forbidden" would
  confirm the row exists. Skipping the picker and posting an id directly gets a
  caller nowhere.
* A download is served from persisted bytes and the file's own recorded name and
  MIME type, never from a path a caller supplies.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.permissions import Principal, RequireAnalyst
from backend.exports import playbook_contract as contract
from backend.playbook import capabilities, library, service, store
from backend.playbook import repository as repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playbook", tags=["playbook"])

MAX_TEXT = 4000


def _scope(principal: Principal) -> repo.Scope:
    """Which tenant this caller reads and writes in.

    Routed through `backend.agentic.principals.tenant_of`, which is the
    repository's single tenancy boundary. It is single-valued today; using it
    rather than hard-coding "" means Playbook becomes multi-tenant when that
    function does, rather than needing an audit of every query here.
    """
    from backend.agentic.principals import tenant_of

    return repo.Scope(tenant=tenant_of(principal),
                      user_id=getattr(principal, "user_id", None))


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable", "message": str(exc)})


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                         detail={"error": "not_found", "message": str(exc)})


def _refused(exc: Exception, code: str = "invalid_request") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": code, "message": str(exc)})


def _session():
    repo.require_db()
    from backend.db.engine import get_session

    return get_session()


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class WorkspaceIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    document_family: str = Field(default="", max_length=64)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class TableIn(BaseModel):
    id: str = Field(default="table", max_length=64)
    title: str = Field(default="", max_length=200)
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    units: dict[str, str] = Field(default_factory=dict)
    precision: dict[str, int] = Field(default_factory=dict)


class ExportIn(BaseModel):
    source_module: str = Field(max_length=32)
    title: str = Field(min_length=1, max_length=300)
    question: str = Field(default="", max_length=MAX_TEXT)
    narrative: str = Field(default="", max_length=200_000)
    tables: list[TableIn] = Field(default_factory=list)
    scope: dict = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    source_ref: dict = Field(default_factory=dict)
    source_revision: str = Field(default="", max_length=64)
    scope_kind: str = Field(default=contract.SCOPE_ANALYSIS, max_length=32)
    report_family: str = Field(default="", max_length=64)
    tags: list[str] = Field(default_factory=list)
    reporting_period: str = Field(default="", max_length=32)
    insight: str = Field(default="", max_length=MAX_TEXT)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    source_ids: list[int] = Field(default_factory=list)
    export_revision_ids: list[int] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    artifact_id: int | None = None
    base_version_id: int | None = None
    #: Supplied by the client so a refresh or a double-click resolves to the
    #: same job rather than to a second billable generation.
    idempotency_key: str = Field(default="", max_length=120)
    #: One of §8's task framings — create, update, coverage, propose, edit,
    #: present. Absent means the instruction travels as written, which is right
    #: for a request that is not one of those jobs.
    task: str = Field(default="", max_length=16)
    #: For `edit`: which part of the document may change. Everything else must
    #: come back unchanged.
    scope: str = Field(default="", max_length=200)


class DecisionIn(BaseModel):
    """Which proposed changes to accept, by stable id.

    Stable ids rather than display numbers: the interface resolves "1, 2 and 3"
    to ids before it gets here, because display numbers renumber and an
    instruction must not start meaning something else after a refresh.
    """

    approve: list[str] = Field(default_factory=list)
    reject: list[str] = Field(default_factory=list)
    #: Set only after the user has been shown a dependency conflict and has
    #: chosen to proceed anyway. Never a default.
    force: bool = False


# --------------------------------------------------------------------------
# Home and capabilities
# --------------------------------------------------------------------------


@router.get("/capabilities")
def get_capabilities(principal: Principal = RequireAnalyst) -> dict:
    """Which formats exist, and whether generation can run at all.

    The provider state is reported honestly and without a credential, so the
    interface can say "configuration required" rather than offering a button
    that will fail.
    """
    from backend.playbook import provider

    del principal
    return {**capabilities.describe(), "provider": provider.status().as_dict()}


@router.get("/home")
def home(limit: int = Query(default=6, ge=1, le=24),
         principal: Principal = RequireAnalyst) -> dict:
    """Everything the home screen shows, in the order it shows it."""
    scope = _scope(principal)
    try:
        with _session() as session:
            workspaces = repo.recent_workspaces(session, scope, limit)
            cards, total = library.browse(session, scope, limit=limit)
            return {
                "recent_playbooks": [
                    {"id": w.id, "title": w.title,
                     "document_family": w.document_family,
                     "state_summary": w.state_summary,
                     "demo": w.demo_origin,
                     "last_activity": w.last_activity_at.isoformat()
                     if w.last_activity_at else ""}
                    for w in workspaces
                ],
                "recent_exports": [c.as_dict() for c in cards],
                "export_total": total,
            }
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


# --------------------------------------------------------------------------
# Workspaces
# --------------------------------------------------------------------------


@router.get("/workspaces")
def list_workspaces(limit: int = Query(default=24, ge=1, le=100),
                    principal: Principal = RequireAnalyst) -> dict:
    scope = _scope(principal)
    try:
        with _session() as session:
            rows = repo.recent_workspaces(session, scope, limit)
            return {"workspaces": [
                {"id": w.id, "title": w.title,
                 "document_family": w.document_family,
                 "state_summary": w.state_summary, "demo": w.demo_origin,
                 "last_activity": w.last_activity_at.isoformat()
                 if w.last_activity_at else ""}
                for w in rows]}
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(body: WorkspaceIn,
                     principal: Principal = RequireAnalyst) -> dict:
    scope = _scope(principal)
    try:
        with _session() as session:
            ws = repo.create_workspace(session, scope, title=body.title,
                                       document_family=body.document_family)
            return {"id": ws.id, "title": ws.title}
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: int,
                  principal: Principal = RequireAnalyst) -> dict:
    """A whole thread: messages, sources, artifacts and every version."""
    scope = _scope(principal)
    try:
        with _session() as session:
            ws = repo.get_workspace(session, scope, workspace_id)
            artifacts = []
            for artifact in repo.artifacts(session, ws.id):
                versions = []
                for version in repo.versions(session, artifact.id):
                    versions.append({
                        "id": version.id, "version": version.version,
                        "change_summary": version.change_summary,
                        "origin": version.origin,
                        "created_at": version.created_at.isoformat()
                        if version.created_at else "",
                        "files": [
                            {"id": f.id, "format": f.format,
                             "filename": f.filename, "size_bytes": f.size_bytes,
                             "renderer": f.renderer, "validated": f.validated}
                            for f in repo.files(session, version.id)
                        ],
                    })
                artifacts.append({
                    "id": artifact.id, "kind": artifact.kind,
                    "title": artifact.title,
                    "current_version_id": artifact.current_version_id,
                    # Lineage, so the interface can tell a deck that is current
                    # from one built before the report was revised — and not
                    # offer to make one that already exists.
                    "derived_from_artifact_id": artifact.derived_from_artifact_id,
                    "derived_from_version_id": artifact.derived_from_version_id,
                    "versions": versions,
                })
            return {
                "id": ws.id, "title": ws.title,
                "document_family": ws.document_family,
                "state_summary": ws.state_summary, "demo": ws.demo_origin,
                "messages": [
                    {"id": m.id, "sequence": m.sequence, "role": m.role,
                     "content": m.content, "origin": m.origin,
                     "model": m.model,
                     "created_at": m.created_at.isoformat()
                     if m.created_at else ""}
                    for m in repo.messages(session, ws.id)
                ],
                "sources": [
                    {"id": s.id, "filename": s.filename, "role": s.source_role,
                     "status": s.status, "size_bytes": s.size_bytes,
                     "manifest": s.manifest,
                     "failure_reason": s.failure_reason}
                    for s in repo.sources(session, ws.id)
                ],
                "artifacts": artifacts,
            }
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.patch("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: int, body: RenameIn,
                     principal: Principal = RequireAnalyst) -> dict:
    scope = _scope(principal)
    try:
        with _session() as session:
            ws = repo.get_workspace(session, scope, workspace_id)
            ws.title = body.title
            return {"id": ws.id, "title": ws.title}
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


@router.post("/workspaces/{workspace_id}/sources",
             status_code=status.HTTP_201_CREATED)
async def upload_source(workspace_id: int,
                        file: UploadFile = File(...),
                        source_role: str = Form(default="supporting"),
                        principal: Principal = RequireAnalyst) -> dict:
    """Accept, store, parse and index one document.

    Parsing starts here so the user sees status and gaps immediately. It does
    not start a generation: uploading a file is not a request to write a report.
    """
    from backend.playbook.ingest import RejectedUpload

    scope = _scope(principal)
    content = await file.read()
    try:
        with _session() as session:
            source = service.add_source(
                session, scope, workspace_id,
                filename=file.filename or "document",
                content=content, source_role=source_role)
            return {"id": source.id, "filename": source.filename,
                    "status": source.status, "role": source.source_role,
                    "manifest": source.manifest,
                    "failure_reason": source.failure_reason}
    except RejectedUpload as exc:
        raise _refused(exc, "rejected_upload") from exc
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/messages",
             status_code=status.HTTP_201_CREATED)
def send_message(workspace_id: int, body: MessageIn,
                 principal: Principal = RequireAnalyst) -> dict:
    """Send one message and run the work it asks for.

    Synchronous, and the reason is the one `backend/exports/service.py` gives
    for the same choice: a job API with no worker behind it is a status endpoint
    that lies. The job row, its idempotency key and its milestones are all
    written, so moving this onto the existing agent queue later is a change of
    caller rather than a change of contract.
    """
    from backend.playbook import provider

    scope = _scope(principal)
    try:
        with _session() as session:
            return service.send_message(
                session, scope, workspace_id,
                text=body.text,
                source_ids=body.source_ids or None,
                export_revision_ids=body.export_revision_ids or None,
                formats=body.formats or None,
                artifact_id=body.artifact_id,
                base_version_id=body.base_version_id,
                idempotency_key=body.idempotency_key,
                task_kind=body.task, task_scope=body.scope,
            )
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StaleBaseVersion as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stale_base_version", "message": str(exc)},
        ) from exc
    except provider.ProviderNotConfigured as exc:
        # Not an error in the product: a deployment without a key still browses
        # its history and its files. Reported as configuration, never as a crash
        # and never as a canned answer.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "provider_not_configured", "message": str(exc)},
        ) from exc
    except provider.Cancelled as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "cancelled", "message": str(exc)}) from exc
    except capabilities.UnsupportedFormat as exc:
        raise _refused(exc, "unsupported_format") from exc
    except provider.AuthoringError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "authoring_failed", "message": str(exc),
                    "category": getattr(exc, "category", "")},
        ) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}/change-sets")
def list_change_sets(workspace_id: int,
                     principal: Principal = RequireAnalyst) -> dict:
    """Proposed changes and what has been decided about them."""
    from backend.models.playbook import PlaybookChangeSet

    scope = _scope(principal)
    try:
        with _session() as session:
            ws = repo.get_workspace(session, scope, workspace_id)
            rows = session.execute(
                select(PlaybookChangeSet)
                .where(PlaybookChangeSet.workspace_id == ws.id)
                .order_by(PlaybookChangeSet.id)
            ).scalars().all()
            return {"change_sets": [
                {
                    "id": cs.id,
                    "status": cs.status,
                    "base_version_id": cs.base_version_id,
                    "items": [
                        {"stable_id": i.stable_id,
                         "number": i.display_number,
                         "target_section": i.target_section,
                         "rationale": i.rationale,
                         "evidence": i.evidence,
                         "depends_on": i.depends_on,
                         "status": i.status}
                        for i in repo.change_items(session, cs.id)
                    ],
                }
                for cs in rows
            ]}
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/change-sets/{change_set_id}/decide")
def decide_change_set(workspace_id: int, change_set_id: int, body: DecisionIn,
                      principal: Principal = RequireAnalyst) -> dict:
    """Accept some proposed changes and not others.

    Records the decision; it does not rewrite the document. The next generation
    applies exactly what was approved, which is what makes "apply 1, 2 and 3"
    still true after a reload.
    """
    scope = _scope(principal)
    try:
        with _session() as session:
            result = service.decide_changes(
                session, scope, workspace_id, change_set_id,
                approve=body.approve, reject=body.reject, force=body.force)
            result["instruction"] = service.approved_instruction(
                session, change_set_id)
            return result
    except service.DependencyConflict as exc:
        # 409 rather than 422: the request is well formed and the document is
        # in a state that refuses it. The conflicts travel so the interface can
        # say which change depends on which.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "dependency_conflict", "message": str(exc),
                    "conflicts": exc.conflicts},
        ) from exc
    except repo.StaleBaseVersion as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stale_base_version", "message": str(exc)},
        ) from exc
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


# --------------------------------------------------------------------------
# The exported-analysis library
# --------------------------------------------------------------------------


@router.get("/exports")
def browse_exports(q: str = Query(default="", max_length=200),
                   module: list[str] = Query(default=[]),
                   period: str = Query(default="", max_length=32),
                   sort: str = Query(default="recent", max_length=16),
                   limit: int = Query(default=24, ge=1, le=100),
                   offset: int = Query(default=0, ge=0),
                   principal: Principal = RequireAnalyst) -> dict:
    scope = _scope(principal)
    try:
        with _session() as session:
            cards, total = library.browse(
                session, scope, query=q, modules=list(module) or None,
                period=period, sort=sort, limit=limit, offset=offset)
            return {"analyses": [c.as_dict() for c in cards], "total": total,
                    "counts": library.counts_by_module(session, scope),
                    "modules": list(contract.SOURCE_MODULES),
                    "implemented_modules": list(contract.IMPLEMENTED_MODULES)}
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/exports/revisions/{revision_id}")
def preview_export(revision_id: int,
                   principal: Principal = RequireAnalyst) -> dict:
    scope = _scope(principal)
    try:
        with _session() as session:
            return library.preview(session, scope, revision_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/exports", status_code=status.HTTP_201_CREATED)
def export_to_playbook(body: ExportIn,
                       principal: Principal = RequireAnalyst) -> dict:
    """Export one completed analysis into the library.

    Idempotent: the same snapshot exported twice returns the revision that
    already exists rather than creating a second copy of the same evidence.
    """
    scope = _scope(principal)
    snapshot = contract.Snapshot(
        source_module=body.source_module, title=body.title,
        question=body.question, narrative=body.narrative,
        tables=[contract.Table(id=t.id, title=t.title, columns=t.columns,
                               rows=t.rows, units=t.units,
                               precision=t.precision) for t in body.tables],
        scope=body.scope, assumptions=body.assumptions,
        limitations=body.limitations, caveats=body.caveats,
        source_ref=body.source_ref, source_revision=body.source_revision,
        scope_kind=body.scope_kind, report_family=body.report_family,
        tags=body.tags, reporting_period=body.reporting_period,
        insight=body.insight,
    )
    try:
        with _session() as session:
            result = library.create(session, scope, snapshot)
            return {"export_id": result.export_id,
                    "revision_id": result.revision_id,
                    "revision": result.revision,
                    "duplicate": result.duplicate,
                    "message": ("This analysis was already in your Playbook "
                                "library, unchanged."
                                if result.duplicate else
                                "Exported to Playbook.")}
    except contract.InvalidExport as exc:
        raise _refused(exc, "invalid_export") from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


# --------------------------------------------------------------------------
# Artifact files
# --------------------------------------------------------------------------


@router.get("/artifact-files/{file_id}/download")
def download_artifact(file_id: int,
                      principal: Principal = RequireAnalyst) -> Response:
    """Serve persisted bytes, with the recorded filename and MIME type.

    The path is read from the stored row, never from the caller, and the row is
    reached only through its workspace's tenant — so a direct request for
    somebody else's file is a 404 rather than a download.
    """
    from backend.models.playbook import (
        PlaybookArtifact,
        PlaybookArtifactFile,
        PlaybookArtifactVersion,
    )

    scope = _scope(principal)
    try:
        with _session() as session:
            row = session.get(PlaybookArtifactFile, file_id)
            if row is None:
                raise repo.NotFound(f"No artifact file {file_id}.")
            version = session.get(PlaybookArtifactVersion, row.version_id)
            artifact = (session.get(PlaybookArtifact, version.artifact_id)
                        if version else None)
            if artifact is None:
                raise repo.NotFound(f"No artifact file {file_id}.")
            repo.get_workspace(session, scope, artifact.workspace_id)
            content = store.read(row.bytes_path)
            return Response(
                content=content, media_type=row.mime,
                headers={
                    "Content-Disposition":
                        f'attachment; filename="{row.filename}"',
                    "Cache-Control": "no-store",
                },
            )
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except store.StorageError as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/artifacts/{artifact_id}/restore/{version_number}")
def restore_artifact_version(artifact_id: int, version_number: int,
                             principal: Principal = RequireAnalyst) -> dict:
    """Bring an earlier version back as the latest one.

    Forward-moving: restoring v1 over v3 writes a v4 carrying v1's content and
    v1's exact bytes. Nothing is deleted, because the record of what was tried
    is the reason version history exists.
    """
    scope = _scope(principal)
    try:
        with _session() as session:
            return service.restore_version(session, scope, artifact_id,
                                           version_number)
    except service.AlreadyCurrent as exc:
        raise _refused(exc, "already_current") from exc
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except store.StorageError as exc:
        # The version exists but its bytes do not. Refused rather than
        # restored, because a version whose download 404s is worse than a
        # restore that did not happen.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "files_missing", "message": str(exc)},
        ) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


# --------------------------------------------------------------------------
# Generations in flight
# --------------------------------------------------------------------------


@router.get("/jobs/by-key/{idempotency_key}")
def job_by_key(idempotency_key: str,
               principal: Principal = RequireAnalyst) -> dict:
    """The generation a client's own key resolved to.

    How a synchronous generation becomes stoppable: the browser mints the key
    before it sends, so it can ask which job that key became and stop it while
    the send is still in flight.
    """
    scope = _scope(principal)
    try:
        with _session() as session:
            return service.job_by_key(session, scope, idempotency_key)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/jobs/{job_id}")
def job(job_id: int, principal: Principal = RequireAnalyst) -> dict:
    """What a generation is doing. Real milestones, and no percentage."""
    scope = _scope(principal)
    try:
        with _session() as session:
            return service.job_status(session, scope, job_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, principal: Principal = RequireAnalyst) -> dict:
    """Ask a running generation to stop.

    Sets a flag the generating request reads between steps. Because a version
    is written last, stopping leaves the previous version exactly as it was.
    Cancelling something that already finished changes nothing and says so.
    """
    scope = _scope(principal)
    try:
        with _session() as session:
            return service.request_cancel(session, scope, job_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/artifacts/{artifact_id}/versions/{version_number}/preview")
def preview_artifact_version(artifact_id: int, version_number: int,
                             principal: Principal = RequireAnalyst) -> dict:
    """Read one version in the application, without downloading it.

    Rendered from the persisted content, so it shows what grounding actually
    left in the document rather than what the model first replied. The download
    remains the authoritative artifact; this is how somebody reads version 1
    without opening a file.
    """
    scope = _scope(principal)
    try:
        with _session() as session:
            return service.version_preview(session, scope, artifact_id,
                                           version_number)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc
