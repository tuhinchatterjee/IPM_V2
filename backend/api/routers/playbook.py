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
from datetime import date

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.permissions import Principal, RequireAnalyst
from backend.exports import playbook_contract as contract
from backend.playbook import capabilities, intelligence, library, service, store
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


def _actor(principal: Principal) -> str:
    """Who is performing a governance act, as a string a row can keep.

    A confirmation, a recorded decision or a completed review has to name a
    person. `permissions._known_user` already refuses an unknown id and leaves
    `user_id` as None, so an unauthenticated caller reaches here with nothing
    to record — and the service layer refuses rather than writing a governance
    row with no actor in it.
    """
    return f"user:{principal.user_id}" if principal.user_id else ""


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
    #: §15: which dashboard object this turn is about — a metric, a finding, a
    #: section, a decision, Since Last Time, the stale metrics. The governed
    #: facts behind it become evidence, and the references are recorded on the
    #: message so the thread still says what "this" meant a month later.
    context_kind: str = Field(default="", max_length=32)
    context_target: str = Field(default="", max_length=128)
    #: Run the generation in a worker and answer immediately with the job to
    #: watch, rather than holding the request open until the document is
    #: finished. The browser always sets this; the synchronous path remains for
    #: callers that genuinely want one answer and one response.
    stream: bool = False


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

    The identity behind that state is withheld, as it is on every other surface
    a normal user reads: the state and what it means are what the interface
    needs, and the vendor and model are not. `/ai/status/audit` still serves
    them to an administrator, and the telemetry ledger still records which
    model produced which answer — the ban is on the screen, not on the machine.
    """
    from backend.playbook import provider
    from backend.release import product_copy

    del principal
    return product_copy.withhold_identity(
        {**capabilities.describe(), "provider": provider.status().as_dict()})


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
                    _source_payload(s) for s in repo.sources(session, ws.id)
                ],
                "artifacts": artifacts,
                # So a browser that has just loaded knows there is a generation
                # to attach to, rather than having to send the message again to
                # find out.
                "running_job": service.running_job(session, scope, ws.id),
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
    from backend.playbook import stream as streaming

    scope = _scope(principal)
    if body.stream:
        # Refused here rather than inside the worker: a deployment with no
        # credential must say so in the response to Send, not as an error event
        # thirty seconds into a stream that was never going to produce a
        # document.
        state = provider.status()
        if not state.configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "provider_not_configured",
                        "message": state.reason})
        try:
            with _session() as session:
                started = service.begin_generation(
                    session, scope, workspace_id,
                    text=body.text,
                    source_ids=body.source_ids or None,
                    export_revision_ids=body.export_revision_ids or None,
                    idempotency_key=body.idempotency_key,
                    context_kind=body.context_kind,
                    context_target=body.context_target)
        except repo.NotFound as exc:
            raise _not_found(exc) from exc
        except repo.StorageUnavailable as exc:
            raise _unavailable(exc) from exc

        if not started["duplicate"]:
            from backend.db.engine import get_session

            streaming.start(
                get_session, scope, workspace_id,
                job_id=started["job_id"],
                request={
                    "job_id": started["job_id"],
                    "text": body.text,
                    "source_ids": body.source_ids or None,
                    "export_revision_ids": body.export_revision_ids or None,
                    "formats": body.formats or None,
                    "artifact_id": body.artifact_id,
                    "base_version_id": body.base_version_id,
                    "task_kind": body.task,
                    "task_scope": body.scope,
                    "context_kind": body.context_kind,
                    "context_target": body.context_target,
                },
                runner=service.run_generation)
        return {**started,
                "stream_url": f"/api/v1/playbook/workspaces/{workspace_id}"
                              f"/stream?job_id={started['job_id']}"}

    try:
        with _session() as session:
            result = service.send_message(
                session, scope, workspace_id,
                text=body.text,
                source_ids=body.source_ids or None,
                export_revision_ids=body.export_revision_ids or None,
                formats=body.formats or None,
                artifact_id=body.artifact_id,
                base_version_id=body.base_version_id,
                idempotency_key=body.idempotency_key,
                task_kind=body.task, task_scope=body.scope,
                context_kind=body.context_kind,
                context_target=body.context_target,
            )
        # Outside the `with`, so the version and its files have committed
        # before the dashboard is asked to catch up. The projection runs in
        # its own session and cannot raise, so a status failure leaves a
        # delivered document rather than taking it down with it.
        from backend.db.engine import get_session

        result["dashboard"] = service.project_status(
            get_session, result.pop("projection", None) or {})
        return result
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


@router.get("/workspaces/{workspace_id}/stream")
def stream_generation(workspace_id: int, request: Request,
                      job_id: int = Query(...),
                      after: int = Query(default=0, ge=0),
                      principal: Principal = RequireAnalyst) -> Response:
    """Watch a generation: the states it moves through and the answer arriving.

    Server-sent events, and a reader rather than a runner — the generation is
    already going in a worker, and this connection can be opened, dropped and
    opened again without touching it. `after`, or a `Last-Event-ID` header,
    replays exactly what a client missed, which is what makes a refresh
    mid-generation continue rather than restart.

    What travels: `state`, `milestone`, `delta`, `artifact`, `done`, `error`,
    and keep-alive comments. `delta` carries answer text and nothing else — the
    provider's own stream also carries reasoning and tool inputs, and those are
    dropped before they reach this side of the wire.
    """
    from backend.db.engine import get_session
    from backend.playbook import stream as streaming

    scope = _scope(principal)
    # Authorised BEFORE a single byte is streamed, and against the job's own
    # workspace: a job id from another tenant is a 404 here exactly as it is
    # everywhere else.
    try:
        with _session() as session:
            job = service.job_status(session, scope, job_id)
            if job["workspace_id"] != workspace_id:
                raise repo.NotFound(f"No generation {job_id} in this workspace.")
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc

    resume = after
    header = request.headers.get("last-event-id", "")
    if not resume and header.isdigit():
        resume = int(header)

    def events():
        for event in streaming.follow(get_session, job_id, after=resume):
            yield streaming.sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Nginx and friends buffer by default, which turns a stream into
            # one long pause followed by everything at once.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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


@router.get("/workspaces/{workspace_id}/jobs/by-key/{idempotency_key}")
def job_by_key(workspace_id: int, idempotency_key: str,
               principal: Principal = RequireAnalyst) -> dict:
    """The generation a client's own key resolved to, in this workspace.

    How a synchronous generation becomes stoppable: the browser mints the key
    before it sends, so it can ask which job that key became and stop it while
    the send is still in flight.

    Addressed under the workspace because that is the scope a key has. The
    earlier form resolved a key across every workspace in the tenant, which
    could hand a client the id of a generation in a conversation it was not
    looking at.
    """
    scope = _scope(principal)
    try:
        with _session() as session:
            return service.job_by_key(session, scope, workspace_id,
                                      idempotency_key)
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


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, principal: Principal = RequireAnalyst) -> dict:
    """The key a retry of this generation should use.

    It hands back a key rather than starting the work, because a retry is the
    same request again — the client already holds the text, the attachments and
    the scope, and re-sending them under this key is one code path instead of a
    second, subtly different one that would have to be kept in step.
    """
    scope = _scope(principal)
    try:
        with _session() as session:
            return service.retry_generation(session, scope, job_id)
    except repo.Invalid as exc:
        raise _refused(exc, "not_retryable") from exc
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


# --------------------------------------------------------------------------
# Correcting a source
# --------------------------------------------------------------------------


class SourceCorrection(BaseModel):
    """What a person can overrule about a parsed file.

    Only two things, and both because the parser guesses at them: what kind of
    document this is, and which period it describes. Everything else about a
    source is a fact about the bytes and is not the user's to change.
    """

    source_role: str = Field(default="", max_length=32)
    reporting_period: str | None = Field(default=None, max_length=32)


@router.get("/sources/{source_id}")
def source(source_id: int, principal: Principal = RequireAnalyst) -> dict:
    """One source: its parse status and what was and was not read of it."""
    scope = _scope(principal)
    try:
        with _session() as session:
            return _source_payload(service.get_source(session, scope, source_id))
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.patch("/sources/{source_id}")
def correct_source(source_id: int, body: SourceCorrection,
                   principal: Principal = RequireAnalyst) -> dict:
    """Overrule what the parser decided about a file.

    Records that a PERSON set the value, not just the value — so a reader of
    the evidence can tell an inference from an instruction.
    """
    scope = _scope(principal)
    try:
        with _session() as session:
            return _source_payload(service.correct_source(
                session, scope, source_id,
                source_role=body.source_role,
                reporting_period=body.reporting_period))
    except repo.Invalid as exc:
        raise _refused(exc, "invalid_source_role") from exc
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/sources/{source_id}/retry")
def retry_source(source_id: int, principal: Principal = RequireAnalyst) -> dict:
    """Parse a stored file again, without asking for it to be uploaded twice."""
    scope = _scope(principal)
    try:
        with _session() as session:
            return _source_payload(
                service.retry_source(session, scope, source_id))
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except store.StorageError as exc:
        raise _not_found(exc) from exc
    except repo.StorageUnavailable as exc:
        raise _unavailable(exc) from exc


def _source_payload(source) -> dict:
    return {"id": source.id, "filename": source.filename,
            "role": source.source_role, "role_set_by": source.role_set_by,
            "status": source.status, "size_bytes": source.size_bytes,
            "reporting_period": source.reporting_period,
            "manifest": source.manifest,
            "failure_reason": source.failure_reason}


# ==========================================================================
# Document intelligence — Know the Status
# ==========================================================================
#
# Read-only except where a governance act is being recorded, and every such
# act names the person performing it. Nothing here calls a provider: the whole
# dashboard is computed from rows, so it is fast, reproducible and explainable.


class ClassifyIn(BaseModel):
    document_type: str = Field(max_length=48)
    committee_report: bool | None = None
    committee_name: str = Field(default="", max_length=160)
    reporting_period: str = Field(default="", max_length=48)
    owner: str = Field(default="", max_length=160)


class ConfirmMetricIn(BaseModel):
    """Confirm, change or ignore a suggested metric link.

    `metric_id` present with action="confirm" changes the mapping to that
    metric and confirms it in one step, which is what the Change action does.
    """

    action: str = Field(default="confirm", max_length=16)
    metric_id: str = Field(default="", max_length=160)


class ConfirmManyIn(BaseModel):
    binding_ids: list[int] = Field(default_factory=list)
    #: "high" confirms every high-confidence suggestion in one action, which
    #: is the bulk control §8 asks for. Never every suggestion regardless of
    #: confidence — that would be the automatic confirmation the rule forbids.
    confidence: str = Field(default="", max_length=16)


@router.get("/workspaces/{workspace_id}/intelligence")
def document_intelligence(workspace_id: int,
                          principal: Principal = RequireAnalyst) -> dict:
    """The Know the Status dashboard for one document."""
    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            return intelligence.dashboard(session, workspace_id).as_dict()
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.put("/workspaces/{workspace_id}/intelligence/profile")
def set_document_profile(workspace_id: int, body: ClassifyIn,
                         principal: Principal = RequireAnalyst) -> dict:
    """A person settles what kind of document this is. §2."""
    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            intelligence.classify(
                session, workspace_id, document_type=body.document_type,
                actor=_actor(principal),
                committee_report=body.committee_report,
                committee_name=body.committee_name,
                reporting_period=body.reporting_period, owner=body.owner)
            session.commit()
            return intelligence.dashboard(session, workspace_id).as_dict()
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except intelligence.UnknownDocumentType as exc:
        raise _refused(exc, code="invalid_request") from exc
    except intelligence.NotPermitted as exc:
        raise _refused(exc, code="not_permitted") from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}/intelligence/metrics")
def document_metrics(workspace_id: int,
                     principal: Principal = RequireAnalyst) -> dict:
    """The metric inventory, with governed links and suggestions kept apart."""
    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            return intelligence.dashboard(session, workspace_id).as_dict()["metrics"]
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/metrics/{binding_id}")
def decide_metric_binding(workspace_id: int, binding_id: int,
                          body: ConfirmMetricIn,
                          principal: Principal = RequireAnalyst) -> dict:
    """Confirm, change or ignore one suggested metric link."""
    from backend.models.playbook import PlaybookMetricBinding
    from backend.playbook.intelligence import binding as bind

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = session.get(PlaybookMetricBinding, binding_id)
            if row is None or row.workspace_id != workspace_id:
                raise repo.NotFound(f"No metric binding {binding_id} here.")
            if body.action == "ignore":
                bind.ignore(session, row)
            else:
                bind.confirm(session, row, actor=_actor(principal),
                             metric_id=body.metric_id)
            session.commit()
            return intelligence.dashboard(session, workspace_id).as_dict()["metrics"]
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except bind.NotConfirmable as exc:
        raise _refused(exc, code="not_confirmable") from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/metrics")
def confirm_metric_bindings(workspace_id: int, body: ConfirmManyIn,
                            principal: Principal = RequireAnalyst) -> dict:
    """Confirm several suggestions at once — §8's bulk review controls."""
    from backend.models.playbook import PlaybookMetricBinding
    from backend.playbook.intelligence import binding as bind

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            rows = (session.query(PlaybookMetricBinding)
                    .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                    .all())
            chosen = [r for r in rows if r.id in set(body.binding_ids)]
            if body.confidence:
                chosen += [r for r in rows
                           if r.binding_method == bind.SUGGESTED
                           and not r.confirmed_by_user
                           and r.confidence == body.confidence]
            for row in {r.id: r for r in chosen}.values():
                bind.confirm(session, row, actor=_actor(principal))
            session.commit()
            return intelligence.dashboard(session, workspace_id).as_dict()["metrics"]
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except bind.NotConfirmable as exc:
        raise _refused(exc, code="not_confirmable") from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/readiness")
def recompute_readiness(workspace_id: int,
                        principal: Principal = RequireAnalyst) -> dict:
    """Score the document again from current rows.

    A read, in effect — it writes only the computed score and its working —
    so it needs no human actor: nothing here is a governance act.
    """
    from backend.playbook.intelligence import readiness as score

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            result = score.compute(session, workspace_id)
            session.commit()
            return result.as_dict()
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


class SectionStatusIn(BaseModel):
    status: str = Field(max_length=32)
    reason: str = Field(default="", max_length=500)


class ReviewerIn(BaseModel):
    reviewer: str = Field(max_length=160)


@router.get("/workspaces/{workspace_id}/intelligence/sections/{section_key}")
def section_detail(workspace_id: int, section_key: str,
                   principal: Principal = RequireAnalyst) -> dict:
    """One section with its metrics, findings, sources, reviews and history."""
    from backend.playbook.intelligence import sections as sect

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            artifact = intelligence.service._current_artifact(session,
                                                              workspace_id)
            if artifact is None:
                raise repo.NotFound("This workspace has no document yet.")
            found = sect.detail(session, artifact.id, section_key,
                                workspace_id)
            if not found:
                raise repo.NotFound(f"No section {section_key!r} here.")
            return found
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/sections/{section_key}/status")
def set_section_status(workspace_id: int, section_key: str,
                       body: SectionStatusIn,
                       principal: Principal = RequireAnalyst) -> dict:
    """Move a section's status. Review states require a named person."""
    from backend.models.playbook import PlaybookDocumentSection
    from backend.playbook.intelligence import sections as sect

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            artifact = intelligence.service._current_artifact(session,
                                                              workspace_id)
            row = (session.query(PlaybookDocumentSection)
                   .filter(PlaybookDocumentSection.artifact_id ==
                           (artifact.id if artifact else 0),
                           PlaybookDocumentSection.section_key == section_key)
                   .one_or_none())
            if row is None:
                raise repo.NotFound(f"No section {section_key!r} here.")
            sect.transition(session, row, to=body.status,
                            actor=_actor(principal), reason=body.reason)
            session.commit()
            return sect.detail(session, artifact.id, section_key, workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except sect.TransitionRefused as exc:
        raise _refused(exc, code="transition_refused") from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/sections/{section_key}/reviewer")
def assign_section_reviewer(workspace_id: int, section_key: str,
                            body: ReviewerIn,
                            principal: Principal = RequireAnalyst) -> dict:
    """Put a named person on a section. A governance act, so it names both."""
    from backend.models.playbook import PlaybookDocumentSection
    from backend.playbook.intelligence import sections as sect

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            artifact = intelligence.service._current_artifact(session,
                                                              workspace_id)
            row = (session.query(PlaybookDocumentSection)
                   .filter(PlaybookDocumentSection.artifact_id ==
                           (artifact.id if artifact else 0),
                           PlaybookDocumentSection.section_key == section_key)
                   .one_or_none())
            if row is None:
                raise repo.NotFound(f"No section {section_key!r} here.")
            sect.assign_reviewer(session, row, reviewer=body.reviewer,
                                 actor=_actor(principal))
            session.commit()
            return sect.detail(session, artifact.id, section_key, workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except sect.TransitionRefused as exc:
        raise _refused(exc, code="transition_refused") from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}/intelligence/since-last-time")
def since_last_time(workspace_id: int, version: int | None = None,
                    principal: Principal = RequireAnalyst) -> dict:
    """THEN against NOW, for every metric the document actually relied on."""
    from backend.playbook.intelligence import compare

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            return compare.since_last_time(session, workspace_id,
                                           version=version)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


# ==========================================================================
# Findings, decisions and actions — §6B, §6C, §27
# ==========================================================================
#
# The complete state and API contract for governed objects, ahead of the
# visual dashboard. Every route here is a thin shell over
# `backend.playbook.intelligence.governance`, which is where the rules live:
# the router never decides who may do what, it passes the caller's identity
# down and lets the one guard refuse. That is deliberate. A rule enforced in
# a router is a rule a worker, a test harness or a future surface can walk
# past; a rule enforced in the service is enforced everywhere.
#
# What is NOT here, on purpose:
#
# * **Claude drafting.** `gov.draft_answer` and `gov.propose_decision(
#   drafted_by_claude=True)` are reached from the authoring path, not from a
#   person's REST call. There is no route by which a client can ask the API
#   to attribute something to the model, and none by which the model can ask
#   the API to attribute something to a person.
# * **Recording a decision without a person.** `record` refuses an unnamed or
#   system actor, and `_actor()` yields "" for an unauthenticated caller, so
#   the refusal arrives as 422 rather than as a row nobody can be held to.
# * **Moving our status from an external system.** `read_back` writes
#   `external_status` and nothing else; a planner saying "done" is evidence.


class FindingIn(BaseModel):
    """Raise a finding by hand. Rule- and import-raised findings arrive
    through the analysis path, not through here."""

    title: str = Field(max_length=400)
    severity: str = Field(default="information", max_length=16)
    rationale: str = Field(default="", max_length=4000)
    section_key: str = Field(default="", max_length=128)
    metric_id: str = Field(default="", max_length=160)
    blocking: bool = False


class FindingMoveIn(BaseModel):
    status: str = Field(max_length=16)
    reason: str = Field(default="", max_length=2000)
    #: Supplied when a person answers in the same act as moving the finding.
    answer: str = Field(default="", max_length=8000)
    resolution: str = Field(default="", max_length=4000)


class OwnerIn(BaseModel):
    owner: str = Field(max_length=160)


class BlockingIn(BaseModel):
    blocking: bool
    reason: str = Field(default="", max_length=2000)


class EvidenceIn(BaseModel):
    locator: str = Field(default="", max_length=400)
    metric_id: str = Field(default="", max_length=160)
    previous_value: str = Field(default="", max_length=64)
    current_value: str = Field(default="", max_length=64)
    delta: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=2000)


class DecisionProposeIn(BaseModel):
    question: str = Field(max_length=2000)
    recommendation: str = Field(default="", max_length=4000)
    options: list[str] = Field(default_factory=list)
    current_position: str = Field(default="", max_length=240)
    proposed_position: str = Field(default="", max_length=240)
    reporting_period: str = Field(default="", max_length=48)
    related_finding_ids: list[int] = Field(default_factory=list)


class DecisionMoveIn(BaseModel):
    status: str = Field(max_length=32)
    reason: str = Field(default="", max_length=2000)


class DecisionRecordIn(BaseModel):
    outcome: str = Field(max_length=16)
    rationale: str = Field(default="", max_length=4000)
    meeting: str = Field(default="", max_length=160)


class ActionSpec(BaseModel):
    title: str = Field(max_length=400)
    description: str = Field(default="", max_length=4000)
    owner: str = Field(default="", max_length=160)
    due_date: date | None = None


class ActionsFromDecisionIn(BaseModel):
    actions: list[ActionSpec] = Field(default_factory=list)


class ActionMoveIn(BaseModel):
    status: str = Field(max_length=24)
    #: Why it moved. Recorded on the audit entry; on a completion it is the
    #: only place the owner says what was actually done.
    reason: str = Field(default="", max_length=2000)


class ActionUpdateIn(BaseModel):
    note: str = Field(max_length=4000)


class ActionExportIn(BaseModel):
    system: str = Field(default="project_planner", max_length=48)
    external_ref: str = Field(max_length=160)


def _governed(session, model, workspace_id: int, row_id: int):
    """Load one governed row, refusing one that belongs to another workspace.

    The workspace itself has already been resolved against the caller's
    tenant; this closes the second door, so a valid id from a workspace the
    caller can see cannot be acted on through a workspace they can see.
    """
    row = session.get(model, row_id)
    if row is None or row.workspace_id != workspace_id:
        raise repo.NotFound(f"No such record here: {row_id}.")
    return row


def _governance_error(exc: Exception) -> HTTPException:
    """Both refusals are the caller's to fix, and both say what to do."""
    from backend.playbook.intelligence import governance as gov

    code = ("not_permitted" if isinstance(exc, gov.NotPermitted)
            else "transition_refused")
    return _refused(exc, code=code)


@router.post("/workspaces/{workspace_id}/intelligence/findings",
             status_code=status.HTTP_201_CREATED)
def raise_finding(workspace_id: int, body: FindingIn,
                  principal: Principal = RequireAnalyst) -> dict:
    """A person raises a finding. Origin is recorded as human, always.

    A client cannot claim a different origin. Presenting a person's opinion
    as a threshold rule's output is exactly the misattribution §6B exists to
    prevent, so the origin here is not a parameter.
    """
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            gov.raise_finding(
                session, workspace_id, title=body.title,
                origin=gov.FROM_HUMAN, severity=body.severity,
                actor=_actor(principal), blocking=body.blocking,
                rationale=body.rationale, section_key=body.section_key,
                metric_id=body.metric_id)
            session.commit()
            return intelligence.service._findings_payload(session,
                                                          workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/findings/{finding_id}/status")
def move_finding(workspace_id: int, finding_id: int, body: FindingMoveIn,
                 principal: Principal = RequireAnalyst) -> dict:
    """Answer, accept, close, defer or reopen. A named person, every time."""
    from backend.models.playbook import PlaybookFinding
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookFinding, workspace_id, finding_id)
            gov.move_finding(session, row, to=body.status,
                             actor=_actor(principal), reason=body.reason,
                             answer=body.answer, resolution=body.resolution)
            session.commit()
            return intelligence.service._findings_payload(session,
                                                          workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/findings/{finding_id}/owner")
def assign_finding(workspace_id: int, finding_id: int, body: OwnerIn,
                   principal: Principal = RequireAnalyst) -> dict:
    """Put a named person on a finding."""
    from backend.models.playbook import PlaybookFinding
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookFinding, workspace_id, finding_id)
            gov.assign_finding(session, row, owner=body.owner,
                               actor=_actor(principal))
            session.commit()
            return intelligence.service._findings_payload(session,
                                                          workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/findings/{finding_id}/blocking")
def set_finding_blocking(workspace_id: int, finding_id: int, body: BlockingIn,
                         principal: Principal = RequireAnalyst) -> dict:
    """Make a finding block approval, or stop it blocking.

    The only way a model-suggested finding ever becomes a formal blocker, and
    it requires a person to say so on the record.
    """
    from backend.models.playbook import PlaybookFinding
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookFinding, workspace_id, finding_id)
            gov.set_blocking(session, row, blocking=body.blocking,
                             actor=_actor(principal), reason=body.reason)
            session.commit()
            return intelligence.service._findings_payload(session,
                                                          workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/findings/{finding_id}/evidence")
def attach_finding_evidence(workspace_id: int, finding_id: int,
                            body: EvidenceIn,
                            principal: Principal = RequireAnalyst) -> dict:
    """Record what a finding rests on, as the caller read it."""
    from backend.models.playbook import PlaybookFinding
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookFinding, workspace_id, finding_id)
            gov.attach_evidence(
                session, row, actor=_actor(principal), locator=body.locator,
                metric_id=body.metric_id, previous_value=body.previous_value,
                current_value=body.current_value, delta=body.delta,
                note=body.note)
            session.commit()
            return intelligence.service._findings_payload(session,
                                                          workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/decisions",
             status_code=status.HTTP_201_CREATED)
def propose_decision(workspace_id: int, body: DecisionProposeIn,
                     principal: Principal = RequireAnalyst) -> dict:
    """Put a decision on the paper. It arrives PROPOSED, never decided."""
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            gov.propose_decision(
                session, workspace_id, question=body.question,
                recommendation=body.recommendation,
                options=body.options or None, actor=_actor(principal),
                current_position=body.current_position,
                proposed_position=body.proposed_position,
                reporting_period=body.reporting_period,
                related_finding_ids=body.related_finding_ids)
            session.commit()
            return intelligence.service._decisions_payload(session,
                                                           workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/decisions/{decision_id}/status")
def move_decision(workspace_id: int, decision_id: int, body: DecisionMoveIn,
                  principal: Principal = RequireAnalyst) -> dict:
    """Move a decision short of deciding it.

    `decided` is refused here even for a person: recording an outcome is a
    separate act with its own route, because it needs the outcome and the
    rationale, and a status change that quietly implies one is how a pack
    ends up asserting a decision nobody took.
    """
    from backend.models.playbook import PlaybookDecision
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookDecision, workspace_id,
                            decision_id)
            gov.move_decision(session, row, to=body.status,
                              actor=_actor(principal), reason=body.reason)
            session.commit()
            return intelligence.service._decisions_payload(session,
                                                           workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/decisions/{decision_id}/record")
def record_decision(workspace_id: int, decision_id: int,
                    body: DecisionRecordIn,
                    principal: Principal = RequireAnalyst) -> dict:
    """A person records what the committee decided."""
    from backend.models.playbook import PlaybookDecision
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookDecision, workspace_id,
                            decision_id)
            gov.record(session, row, outcome=body.outcome,
                       actor=_actor(principal), rationale=body.rationale,
                       meeting=body.meeting)
            session.commit()
            return intelligence.service._decisions_payload(session,
                                                           workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/decisions/{decision_id}/actions",
             status_code=status.HTTP_201_CREATED)
def create_decision_actions(workspace_id: int, decision_id: int,
                            body: ActionsFromDecisionIn,
                            principal: Principal = RequireAnalyst) -> dict:
    """Create the work a recorded decision implies. Refused before it is."""
    from backend.models.playbook import PlaybookDecision
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookDecision, workspace_id,
                            decision_id)
            gov.actions_from_decision(
                session, row, actor=_actor(principal),
                actions=[spec.model_dump() for spec in body.actions])
            session.commit()
            return intelligence.service._actions_payload(session, workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/actions",
             status_code=status.HTTP_201_CREATED)
def create_action(workspace_id: int, body: ActionSpec,
                  principal: Principal = RequireAnalyst) -> dict:
    """Raise an action directly, for work that follows from no decision."""
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            gov.create_action(session, workspace_id, title=body.title,
                              actor=_actor(principal),
                              description=body.description, owner=body.owner,
                              due_date=body.due_date)
            session.commit()
            return intelligence.service._actions_payload(session, workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/actions/{action_id}/status")
def move_action(workspace_id: int, action_id: int, body: ActionMoveIn,
                principal: Principal = RequireAnalyst) -> dict:
    """Move an action. Completing one records who said it was done."""
    from backend.models.playbook import PlaybookAction
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookAction, workspace_id, action_id)
            gov.move_action(session, row, to=body.status,
                            actor=_actor(principal), note=body.reason)
            session.commit()
            return intelligence.service._actions_payload(session, workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/actions/{action_id}/update")
def update_action(workspace_id: int, action_id: int, body: ActionUpdateIn,
                  principal: Principal = RequireAnalyst) -> dict:
    """An owner says where an action stands, without moving it."""
    from backend.models.playbook import PlaybookAction
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookAction, workspace_id, action_id)
            gov.update_action(session, row, note=body.note,
                              actor=_actor(principal))
            session.commit()
            return intelligence.service._actions_payload(session, workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}/intelligence/actions/{action_id}/export")
def action_export_payload(workspace_id: int, action_id: int,
                          principal: Principal = RequireAnalyst) -> dict:
    """What a planner would need to take this action on. Changes nothing.

    The seam §7 asks for: Playbook works completely without a Project
    Planner, and hands one everything it needs if the user has it.
    """
    from backend.models.playbook import PlaybookAction
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookAction, workspace_id, action_id)
            return gov.export_payload(row)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/intelligence/actions/{action_id}/export")
def record_action_export(workspace_id: int, action_id: int,
                         body: ActionExportIn,
                         principal: Principal = RequireAnalyst) -> dict:
    """Note that an action now lives in an external system too."""
    from backend.models.playbook import PlaybookAction
    from backend.playbook.intelligence import governance as gov

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            row = _governed(session, PlaybookAction, workspace_id, action_id)
            gov.record_export(session, row, system=body.system,
                              external_ref=body.external_ref,
                              actor=_actor(principal))
            session.commit()
            return intelligence.service._actions_payload(session, workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except (gov.NotPermitted, gov.TransitionRefused) as exc:
        raise _governance_error(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}/intelligence/context")
def chat_context(workspace_id: int, kind: str = Query(max_length=32),
                 target: str = Query(default="", max_length=128),
                 principal: Principal = RequireAnalyst) -> dict:
    """Turn a dashboard object into a chat context. §15.

    A read. It populates the composer — with a question the user may rewrite,
    the §8 task framing that question belongs to, and the explicit references
    the turn is about. Nothing is generated and nothing is sent: the user
    still presses send, and the same `kind`/`target` then travel on the
    message so the turn's evidence is rebuilt from the dashboard as it stands
    at that moment rather than from a copy the browser held.
    """
    from backend.playbook.intelligence import context as dashboard

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            return dashboard.build(session, workspace_id, kind=kind,
                                   target=target).as_dict()
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except dashboard.UnknownContext as exc:
        raise _refused(exc, code="unknown_context") from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}/intelligence/context-actions")
def chat_context_actions(workspace_id: int,
                         principal: Principal = RequireAnalyst) -> dict:
    """Which context actions this document can offer right now.

    Built by attempting each one that needs no target, so a dashboard never
    offers "Explain these movements" on a document that has nothing to
    compare. The per-object actions are always available — clicking a
    finding that exists can always draft an answer to it.
    """
    from backend.playbook.intelligence import context as dashboard

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            offered, withheld = [], []
            for kind, (needs_target, _) in dashboard.BUILDERS.items():
                if needs_target:
                    offered.append({"kind": kind, "needs_target": True})
                    continue
                try:
                    built = dashboard.build(session, workspace_id, kind=kind)
                except dashboard.UnknownContext as exc:
                    withheld.append({"kind": kind, "reason": str(exc)})
                else:
                    offered.append({"kind": kind, "needs_target": False,
                                    "action": built.action,
                                    "label": built.label})
            return {"offered": offered, "withheld": withheld}
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


# ==========================================================================
# Stale sources and re-reading. §18
# ==========================================================================
#
# The bytes are immutable, so a better reader is a reason to read again and
# never a reason to ask for the file a second time. Every route here reads
# stored bytes locally: no upload, no provider call, nothing billable.


@router.get("/workspaces/{workspace_id}/sources/parses")
def source_readings(workspace_id: int,
                    principal: Principal = RequireAnalyst) -> dict:
    """Where every source's reading stands, and which need re-reading."""
    from backend.playbook import reparse

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            return reparse.summary(session, workspace_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.get("/sources/{source_id}/parses")
def source_parse_history(source_id: int,
                         principal: Principal = RequireAnalyst) -> dict:
    """Every reading this source has had. Lineage, preserved.

    A document generated three months ago can be traced to the reading it was
    actually written from, which is why superseded revisions are kept rather
    than replaced.
    """
    from backend.playbook import reparse

    scope = _scope(principal)
    try:
        with _session() as session:
            source = service.get_source(session, scope, source_id)
            return {
                "source_id": source.id,
                "filename": source.filename,
                "current": reparse.state(session, source).as_dict(),
                "revisions": [{
                    "revision": r.revision,
                    "parser_version": r.parser_version,
                    "schema_version": r.schema_version,
                    "status": r.status,
                    "chunk_count": r.chunk_count,
                    "failure_reason": r.failure_reason,
                    "superseded": r.superseded,
                    "manifest": dict(r.manifest or {}),
                    "created_at": (r.created_at.isoformat()
                                   if r.created_at else ""),
                } for r in reparse.history(session, source.id)],
            }
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/sources/{source_id}/reread")
def reread_source(source_id: int,
                  principal: Principal = RequireAnalyst) -> dict:
    """Read this source's stored bytes again with the reader in force now.

    Replaces the chunks the next generation will draw on. It does NOT rewrite
    any document: a report already written is not revised because its source
    was read again — §16's governed refresh is where that decision belongs,
    and it is a person's.
    """
    from backend.playbook import reparse

    scope = _scope(principal)
    try:
        with _session() as session:
            result = reparse.reread(session, scope, source_id)
            session.commit()
            return result.as_dict()
    except reparse.BytesGone as exc:
        raise _refused(exc, code="bytes_gone") from exc
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.post("/workspaces/{workspace_id}/sources/reread")
def reread_stale_sources(workspace_id: int,
                         principal: Principal = RequireAnalyst) -> dict:
    """Re-read every stale source in this workspace.

    One failure does not stop the rest: a file whose bytes are gone is
    reported and the others are still brought up to date.
    """
    from backend.playbook import reparse

    scope = _scope(principal)
    try:
        with _session() as session:
            result = reparse.reread_stale(session, scope, workspace_id)
            session.commit()
            return result
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


# ==========================================================================
# History, and checking for updates. §20, §23, §24
# ==========================================================================


@router.get("/workspaces/{workspace_id}/intelligence/history")
def document_history(workspace_id: int, kind: str = Query(default=""),
                     limit: int = Query(default=200, ge=1, le=1000),
                     principal: Principal = RequireAnalyst) -> dict:
    """Everything that happened to this document, newest first.

    Assembled from the trails the rows already keep rather than from a second
    event log beside them. A separate log could disagree with the rows it
    describes, and the one that disagrees is always the one somebody reads.
    """
    from backend.playbook.intelligence import history

    scope = _scope(principal)
    kinds = [k.strip() for k in kind.split(",") if k.strip()]
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            return history.feed(session, workspace_id, kinds=kinds or None,
                                limit=limit)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}/intelligence/updates")
def check_for_updates(workspace_id: int,
                      principal: Principal = RequireAnalyst) -> dict:
    """What has moved since this document was written, as a proposal.

    A read. Nothing is applied, nothing is rewritten, and the document is
    exactly as it was when this returns — §16 is explicit that new data is a
    reason to tell somebody, not a licence to edit a governed pack.
    """
    from backend.playbook.intelligence import refresh

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            return refresh.check(session, workspace_id).as_dict()
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


@router.get("/workspaces/{workspace_id}/sources/{source_id}/metric-updates")
def uploaded_metric_updates(workspace_id: int, source_id: int,
                            principal: Principal = RequireAnalyst) -> dict:
    """Which tracked metrics a newly uploaded file appears to update. §24.

    Appears to. Every row is a suggestion and says so: a column header
    resembling a metric this document tracks is not evidence that it is that
    metric. Confirming is a person's act, through the metrics routes.
    """
    from backend.playbook.intelligence import refresh

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            return refresh.proposals_from_source(session, workspace_id,
                                                 source_id)
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc


class ApplyUploadedIn(BaseModel):
    """Which of the uploaded readings a person is standing behind."""

    binding_ids: list[int] = Field(default_factory=list)


@router.post("/workspaces/{workspace_id}/sources/{source_id}/metric-updates")
def apply_uploaded_metric_updates(workspace_id: int, source_id: int,
                                  body: ApplyUploadedIn,
                                  principal: Principal = RequireAnalyst
                                  ) -> dict:
    """Make confirmed uploaded readings the governed current values. §24.

    Only the ones named. A resemblance between a column header and a tracked
    metric is not an identity, so nothing here happens without a person
    choosing it, and the act records who.
    """
    from backend.playbook.intelligence import governance as gov
    from backend.playbook.intelligence import refresh

    scope = _scope(principal)
    try:
        with _session() as session:
            repo.get_workspace(session, scope, workspace_id)
            result = refresh.apply_uploaded(
                session, workspace_id, source_id,
                binding_ids=body.binding_ids, actor=_actor(principal))
            session.commit()
            return result
    except repo.NotFound as exc:
        raise _not_found(exc) from exc
    except gov.NotPermitted as exc:
        raise _refused(exc, code="not_permitted") from exc
    except RuntimeError as exc:
        raise _unavailable(exc) from exc
