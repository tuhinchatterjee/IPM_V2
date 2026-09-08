"""
Playbook, end to end. Playbook §6, §9, §10, §11.

The order of operations for one authoring request, in one place, so that the
sequence is reviewable rather than distributed across a router, a worker and a
provider wrapper.

    accept and read the sources        (ingest — locators and an honest manifest)
    assemble the evidence ledger       (only what was attached; gaps recorded)
    ask the author to write            (prose and structure; never a figure)
    check the draft against evidence   (grounding — unsupported figures removed)
    render the files                   (skill output, or local from the same doc)
    open every file and check it       (validation — nothing is ready untested)
    write an immutable version         (only now, and only if validation held)

Two decisions in that list are worth stating plainly.

**Grounding runs before rendering, and can invalidate a Skill's file.** The
document Skills write their files during the same provider turn that produces
the prose. If grounding then removes an unsupported figure, the file the Skill
wrote no longer matches the document — so it is discarded and the corrected
document is rendered locally instead. The alternative would be shipping a Word
file containing a number the chat has already retracted.

**A version is written last.** A failed generation produces no version, so the
previous good one is still current and still downloadable. There is no such
thing here as a "completed" version whose files do not open.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from backend.playbook import capabilities, grounding, ingest, prompts, provider, render, store, validate
from backend.playbook import document as D
from backend.playbook import evidence as ev
from backend.playbook import repository as repo

logger = logging.getLogger(__name__)

#: What a report is rendered into by default. PowerPoint is produced on request
#: rather than always, because a deck nobody asked for is noise.
DEFAULT_FORMATS = ("docx", "pdf")


@dataclass
class Outcome:
    """What one authoring run produced."""

    workspace_id: int
    artifact_id: int | None = None
    version_id: int | None = None
    version: int = 0
    document: D.Document | None = None
    files: dict[str, bytes] = field(default_factory=dict)
    validations: dict[str, validate.Validation] = field(default_factory=dict)
    grounding: grounding.GroundingResult | None = None
    renderer: str = ""
    model_served: str = ""
    request_ids: list[str] = field(default_factory=list)
    milestones: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.version_id) and all(v.ok for v in self.validations.values())


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


def add_source(session, scope: repo.Scope, workspace_id: int, *,
               filename: str, content: bytes,
               source_role: str = "supporting"):
    """Validate, store, parse and index one uploaded document.

    Parsing happens on upload so the user sees status and gaps immediately, but
    it does NOT start a generation: §4 is explicit that uploading a file is not
    a request to write a report.
    """
    ws = repo.get_workspace(session, scope, workspace_id)
    accepted = ingest.accept(filename, content)

    source = repo.add_source(
        session, ws.id, scope, filename=store.safe_filename(filename),
        mime=accepted.mime, sha256=store.sha256(content),
        size_bytes=accepted.size_bytes, source_role=source_role,
    )
    stored = store.put_source(ws.id, source.id, filename, content)
    source.bytes_path = stored.relative

    source.status = "parsing"
    session.flush()
    try:
        _, result = ingest.read(filename, content)
    except ingest.UnreadableSource as exc:
        source.status = "failed"
        source.failure_reason = str(exc)
        source.manifest = {"format": accepted.kind, "complete": False,
                           "read": [], "skipped": [], "warnings": [str(exc)]}
        session.flush()
        return source

    repo.set_chunks(session, source, result.chunks)
    source.manifest = result.manifest.as_dict()
    source.status = "parsed" if result.manifest.complete else "partial"
    session.flush()
    return source


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


def ledger_for(session, scope: repo.Scope, workspace_id: int, *,
               source_ids: list[int] | None = None,
               export_revision_ids: list[int] | None = None,
               calculations: list | None = None) -> ev.Ledger:
    """Assemble the evidence for one request from what was explicitly chosen.

    Nothing is included by being nearby. An empty selection produces an empty
    ledger, and the caller is expected to say so rather than quietly widening
    the search.
    """
    ledger = ev.Ledger()
    for source in repo.sources(session, workspace_id):
        if source_ids is not None and source.id not in source_ids:
            continue
        if source.status == "failed":
            ledger.omit(source.filename,
                        source.failure_reason or "the file could not be read")
            continue
        rows = repo.chunks(session, source.id)
        from backend.playbook.ingest.types import Chunk

        ev.from_chunks(
            [Chunk(kind=c.kind, locator=c.locator, text=c.text,
                   path=list(c.path or []), data=dict(c.data or {}),
                   ordinal=c.ordinal) for c in rows],
            label=f"{source.filename} ({source.source_role.replace('_', ' ')})",
            ledger=ledger,
        )
        for gap in (source.manifest or {}).get("skipped", []):
            ledger.omit(f"{source.filename}: {gap.get('what', '')}",
                        gap.get("why", ""))

    for revision_id in export_revision_ids or []:
        revision = repo.find_export_revision(session, scope, revision_id)
        ev.from_export(revision.payload or {}, export_id=revision.export_id,
                       revision=revision.revision, ledger=ledger)

    if calculations:
        ev.add_calculations(ledger, calculations)
    return ledger


# --------------------------------------------------------------------------
# Authoring
# --------------------------------------------------------------------------


def _render_locally(doc: D.Document, formats: list[str]) -> dict[str, bytes]:
    return {fmt: render.render(doc, fmt) for fmt in formats}


def _usable(files: dict[str, bytes], doc: D.Document,
            formats: list[str]) -> tuple[dict[str, bytes], dict, str]:
    """Validate what the Skills produced; fall back where it does not hold."""
    produced = {f: b for f, b in files.items() if f in formats}
    missing = [f for f in formats if f not in produced]
    results = validate.validate_all(produced, doc) if produced else {}
    failed = [f for f, v in results.items() if not v.ok]

    if not missing and not failed:
        return produced, results, capabilities.SKILL

    local = _render_locally(doc, formats)
    return local, validate.validate_all(local, doc), capabilities.LOCAL


def author_document(session, scope: repo.Scope, workspace_id: int, *,
                    instruction: str,
                    ledger: ev.Ledger,
                    title: str,
                    formats: list[str] | None = None,
                    artifact_id: int | None = None,
                    base_version_id: int | None = None,
                    change_summary: str = "",
                    on_milestone=None,
                    is_cancelled=None) -> Outcome:
    """One complete authoring run, from instruction to persisted version."""
    formats = list(formats or DEFAULT_FORMATS)
    for fmt in formats:
        capabilities.require(fmt)

    ws = repo.get_workspace(session, scope, workspace_id)
    outcome = Outcome(workspace_id=ws.id)

    system = prompts.system(formats=formats)
    user = "\n\n".join([instruction, ledger.render()])

    result = provider.author(
        system=system,
        messages=[{"role": "user", "content": user}],
        formats=formats,
        on_milestone=on_milestone,
        is_cancelled=is_cancelled,
    )
    outcome.model_served = result.model_served
    outcome.request_ids = list(result.request_ids)
    outcome.milestones = list(result.milestones)
    if result.downgraded:
        outcome.notes.append(
            f"The provider served {result.model_served} rather than the "
            f"configured {result.model_requested}."
        )

    doc = D.parse(result.text, title=title)
    if not doc.sections:
        raise provider.AuthoringError(
            "The author returned no document. Nothing was saved and the "
            "previous version is unchanged.", category="empty_output")

    ground = grounding.check(doc, ledger)
    outcome.grounding = ground
    if ground.note():
        outcome.notes.append(ground.note())

    skill_files = {f.format: f.content for f in result.files}
    if not ground.ok:
        # The Skill wrote its files from prose that has since had a figure
        # removed. Those files now disagree with the document, so they go.
        skill_files = {}
        outcome.notes.append(
            "The generated files were re-rendered after unsupported figures "
            "were removed, so that every format states the same thing."
        )

    files, validations, renderer = _usable(skill_files, doc, formats)
    outcome.files, outcome.validations, outcome.renderer = files, validations, renderer

    if any(not v.ok for v in validations.values()):
        raise provider.AuthoringError(
            "The generated files did not pass validation, so nothing was "
            "saved. "
            + "; ".join(i for v in validations.values() for i in v.issues),
            category="validation",
        )

    outcome.document = doc
    _persist(session, scope, ws, outcome, title=title, artifact_id=artifact_id,
             base_version_id=base_version_id, change_summary=change_summary,
             ledger=ledger)
    return outcome


def _persist(session, scope: repo.Scope, ws, outcome: Outcome, *, title: str,
             artifact_id: int | None, base_version_id: int | None,
             change_summary: str, ledger: ev.Ledger) -> None:
    doc = outcome.document
    from backend.models.playbook import PlaybookArtifact

    if artifact_id:
        artifact = session.get(PlaybookArtifact, artifact_id)
        if artifact is None or artifact.workspace_id != ws.id:
            raise repo.NotFound(f"No artifact {artifact_id} in this workspace.")
    else:
        artifact = repo.create_artifact(session, ws.id, kind="report",
                                        title=title)

    version = repo.new_version(
        session, artifact,
        content=doc.as_dict(),
        source_manifest={
            "locators": sorted(ledger.locators()),
            "omissions": list(ledger.omissions),
            "complete": ledger.complete,
        },
        content_hash=doc.content_hash(),
        change_summary=change_summary,
        base_version_id=base_version_id,
        created_by=scope.user_id,
        validation={f: v.as_dict() for f, v in outcome.validations.items()},
    )

    for fmt, content in outcome.files.items():
        cap = capabilities.require(fmt)
        filename = f"{_slug(title)}-v{version.version}.{fmt}"
        stored = store.put_artifact(ws.id, artifact.id, version.version,
                                    filename, content)
        repo.add_file(
            session, version, fmt=fmt, bytes_path=stored.relative,
            mime=cap.mime, filename=filename, size_bytes=stored.size_bytes,
            sha256=stored.sha256, renderer=outcome.renderer,
            validated=outcome.validations.get(fmt, validate.Validation(fmt)).ok,
        )

    repo.touch(session, ws, summary=change_summary or f"{title} v{version.version}")
    outcome.artifact_id = artifact.id
    outcome.version_id = version.id
    outcome.version = version.version


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in (text or "report")]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:60] or "report"


def content_hash(doc: D.Document) -> str:
    return hashlib.sha256(
        doc.plain_text().encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Sending a message
# --------------------------------------------------------------------------


def send_message(session, scope: repo.Scope, workspace_id: int, *,
                 text: str,
                 source_ids: list[int] | None = None,
                 export_revision_ids: list[int] | None = None,
                 formats: list[str] | None = None,
                 artifact_id: int | None = None,
                 base_version_id: int | None = None,
                 idempotency_key: str = "",
                 calculations: list | None = None,
                 on_milestone=None,
                 is_cancelled=None) -> dict:
    """One turn: persist what was asked, do it, persist what came back.

    The user's message and its attachments are written FIRST and committed with
    the job row, so a generation that fails still leaves a thread showing what
    was asked and what went wrong. A thread that loses the question when the
    answer fails is a thread nobody can retry from.

    `idempotency_key` is enforced by a unique constraint. A refresh, a
    double-click or a retry after a dropped connection finds the job that is
    already running rather than starting a second billable one.
    """
    from backend.models.playbook import PlaybookJob

    ws = repo.get_workspace(session, scope, workspace_id)
    formats = list(formats or DEFAULT_FORMATS)
    key = idempotency_key or f"ws{ws.id}:{repo.next_sequence(session, ws.id)}"

    existing = repo.jobs_by_key(session, key)
    if existing is not None:
        return {"job_id": existing.id, "state": existing.state,
                "duplicate": True,
                "message": "This request is already running." }

    job = PlaybookJob(workspace_id=ws.id, tenant=scope.tenant,
                      idempotency_key=key, state="queued",
                      requested_by=scope.user_id)
    session.add(job)
    session.flush()

    user_message = repo.add_message(
        session, ws.id, role="user",
        content={"text": text}, origin="user", author_id=scope.user_id)
    for position, source_id in enumerate(source_ids or []):
        repo.attach(session, ws.id, message_id=user_message.id,
                    source_id=source_id, position=position)
    for position, revision_id in enumerate(export_revision_ids or []):
        # Resolved through the tenant-scoped lookup, so an id that was never
        # exported — or belongs to somebody else — fails here rather than
        # becoming evidence.
        revision = repo.find_export_revision(session, scope, revision_id)
        repo.attach(session, ws.id, message_id=user_message.id,
                    export_revision_id=revision.id,
                    position=len(source_ids or []) + position)

    ledger = ledger_for(session, scope, ws.id, source_ids=source_ids,
                        export_revision_ids=export_revision_ids,
                        calculations=calculations)

    def milestone(state: str, detail: str = "") -> None:
        job.state = state if state in {"reviewing_sources", "drafting",
                                       "rendering", "validating"} else job.state
        job.milestones = list(job.milestones or []) + [
            {"state": state, "detail": detail}]
        if on_milestone:
            on_milestone(state, detail)

    try:
        outcome = author_document(
            session, scope, ws.id, instruction=text, ledger=ledger,
            title=ws.title, formats=formats, artifact_id=artifact_id,
            base_version_id=base_version_id,
            on_milestone=milestone, is_cancelled=is_cancelled)
    except provider.Cancelled as exc:
        job.state = "cancelled"
        job.finished_at = _now()
        repo.add_message(session, ws.id, role="assistant",
                         content={"text": "This generation was stopped. "
                                          "Nothing was saved."},
                         origin="system", job_id=job.id)
        raise exc
    except Exception as exc:
        job.state = "failed"
        job.error = str(exc)[:2000]
        job.finished_at = _now()
        repo.add_message(
            session, ws.id, role="assistant",
            content={"text": str(exc), "failed": True},
            origin="system", job_id=job.id)
        raise

    job.state = "ready"
    job.model = outcome.model_served
    job.provider_request_ids = list(outcome.request_ids)
    job.usage = {"requests": len(outcome.request_ids)}
    job.finished_at = _now()

    assistant = repo.add_message(
        session, ws.id, role="assistant",
        content={
            "text": outcome.document.plain_text() if outcome.document else "",
            "markdown": _markdown_of(outcome.document),
            "artifact_id": outcome.artifact_id,
            "version_id": outcome.version_id,
            "version": outcome.version,
            "notes": list(outcome.notes),
            "grounding": outcome.grounding.as_dict() if outcome.grounding else {},
            "evidence_complete": ledger.complete,
            "evidence_gaps": list(ledger.omissions),
        },
        origin="assistant_live", model=outcome.model_served,
        request_ids=list(outcome.request_ids), usage=outcome.usage()
        if hasattr(outcome, "usage") else {}, job_id=job.id)

    return {"job_id": job.id, "state": "ready", "duplicate": False,
            "message_id": assistant.id, "artifact_id": outcome.artifact_id,
            "version": outcome.version, "notes": list(outcome.notes)}


def _now():
    from sqlalchemy import func

    return func.now()


def _markdown_of(doc: D.Document | None) -> str:
    """Re-render the stored document as the Markdown the thread displays.

    Kept as a function rather than storing the model's raw reply, because what
    the thread shows must be what was actually SAVED — after grounding removed
    anything unsupported — not what the model first wrote.
    """
    if doc is None:
        return ""
    lines: list[str] = []
    if doc.title:
        lines.append(f"# {doc.title}")
        lines.append("")
    for section in doc.sections:
        if section.heading:
            lines.append(f"{'#' * min(section.level + 1, 6)} {section.heading}")
            lines.append("")
        for block in section.blocks:
            if block.kind == D.TABLE:
                columns = block.data.get("columns") or []
                if columns:
                    lines.append("| " + " | ".join(str(c) for c in columns) + " |")
                    lines.append("| " + " | ".join("---" for _ in columns) + " |")
                    for row in block.data.get("rows") or []:
                        lines.append("| " + " | ".join(
                            "" if v is None else str(v) for v in row) + " |")
                    lines.append("")
            elif block.kind in (D.BULLETS, D.NUMBERS):
                for i, item in enumerate(block.data.get("items", []), start=1):
                    lines.append(f"{i}. {item}" if block.kind == D.NUMBERS
                                 else f"- {item}")
                lines.append("")
            elif block.text:
                lines.append(block.text)
                lines.append("")
    return "\n".join(lines).strip()
