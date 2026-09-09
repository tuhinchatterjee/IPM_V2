"""
Playbook's database access. Playbook §15.

Thin on purpose. Every function here does one persistence job and nothing else,
so `service.py` reads as the sequence of decisions it is rather than as SQL with
decisions mixed into it — the same split `backend/exports/service.py` makes and
for the same reason.

Two rules are enforced here rather than trusted to callers:

**A version is written once.** `new_version` computes the next number inside the
transaction that writes it, and the unique constraint on `(artifact_id, version)`
is what makes a concurrent second writer fail rather than overwrite.

**A stale base cannot win.** `new_version` refuses when the base version it was
told to build on is no longer the artifact's current one. That is PB-023: the
loser of a race is told, not silently discarded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from backend.models.playbook import (
    AnalysisExport,
    AnalysisExportRevision,
    PlaybookArtifact,
    PlaybookArtifactFile,
    PlaybookArtifactVersion,
    PlaybookAttachment,
    PlaybookChangeItem,
    PlaybookChangeSet,
    PlaybookJob,
    PlaybookMessage,
    PlaybookWorkspace,
    PlaybookWorkspaceSource,
    PlaybookWorkspaceSourceChunk,
)

logger = logging.getLogger(__name__)


class StorageUnavailable(RuntimeError):
    """Playbook needs the platform database and it is not configured."""


class StaleBaseVersion(RuntimeError):
    """The document moved on while this change was being prepared."""


class NotFound(LookupError):
    """No such workspace, source, artifact or export — for this caller."""


class Invalid(ValueError):
    """The request is well formed and asks for something that is not allowed."""


def require_db() -> None:
    from backend.config import settings

    if not settings.has_database:
        raise StorageUnavailable(
            "Playbook stores workspaces, sources and artifact versions in the "
            "platform database, which is not configured. Set DATABASE_URL."
        )


@dataclass(frozen=True)
class Scope:
    """Who is asking. Every read and write is filtered by this.

    Tenancy follows the convention the rest of the platform uses — a string
    column defaulting to "" — rather than inventing a second one.
    """

    tenant: str = ""
    user_id: int | None = None


# ------------------------------------------------------------------ workspaces


def create_workspace(session, scope: Scope, *, title: str,
                     document_family: str = "", demo_origin: bool = False,
                     seed_version: str = "") -> PlaybookWorkspace:
    ws = PlaybookWorkspace(
        tenant=scope.tenant, owner_id=scope.user_id, title=title,
        document_family=document_family, demo_origin=demo_origin,
        seed_version=seed_version,
    )
    session.add(ws)
    session.flush()
    return ws


def get_workspace(session, scope: Scope, workspace_id: int) -> PlaybookWorkspace:
    ws = session.get(PlaybookWorkspace, workspace_id)
    if ws is None or ws.tenant != scope.tenant:
        # A foreign-tenant id is reported as absent rather than as forbidden.
        # "Forbidden" confirms the row exists, which is itself information.
        raise NotFound(f"No Playbook workspace {workspace_id}.")
    return ws


def recent_workspaces(session, scope: Scope, limit: int = 6
                      ) -> list[PlaybookWorkspace]:
    stmt = (select(PlaybookWorkspace)
            .where(PlaybookWorkspace.tenant == scope.tenant)
            .order_by(PlaybookWorkspace.last_activity_at.desc())
            .limit(limit))
    return list(session.execute(stmt).scalars())


def touch(session, ws: PlaybookWorkspace, *, summary: str = "") -> None:
    from sqlalchemy import func

    ws.last_activity_at = func.now()
    ws.updated_at = func.now()
    if summary:
        ws.state_summary = summary


# -------------------------------------------------------------------- messages


def next_sequence(session, workspace_id: int) -> int:
    from sqlalchemy import func

    highest = session.execute(
        select(func.max(PlaybookMessage.sequence))
        .where(PlaybookMessage.workspace_id == workspace_id)
    ).scalar()
    return (highest or 0) + 1


def add_message(session, workspace_id: int, *, role: str, content: dict,
                origin: str, author_id: int | None = None, model: str = "",
                request_ids: list | None = None, usage: dict | None = None,
                job_id: int | None = None) -> PlaybookMessage:
    message = PlaybookMessage(
        workspace_id=workspace_id,
        sequence=next_sequence(session, workspace_id),
        role=role, content=content, origin=origin, author_id=author_id,
        model=model, request_ids=request_ids or [], usage=usage or {},
        job_id=job_id,
    )
    session.add(message)
    session.flush()
    return message


def messages(session, workspace_id: int) -> list[PlaybookMessage]:
    stmt = (select(PlaybookMessage)
            .where(PlaybookMessage.workspace_id == workspace_id)
            .order_by(PlaybookMessage.sequence))
    return list(session.execute(stmt).scalars())


# --------------------------------------------------------------------- sources


def add_source(session, workspace_id: int, scope: Scope, *, filename: str,
               mime: str, sha256: str, size_bytes: int,
               source_role: str = "supporting") -> PlaybookWorkspaceSource:
    source = PlaybookWorkspaceSource(
        workspace_id=workspace_id, tenant=scope.tenant, filename=filename,
        mime=mime, sha256=sha256, size_bytes=size_bytes,
        source_role=source_role, uploaded_by=scope.user_id, status="uploaded",
    )
    session.add(source)
    session.flush()
    return source


def set_chunks(session, source: PlaybookWorkspaceSource, chunks: list) -> None:
    """Replace a source's parsed content. Re-parsing is idempotent."""
    session.query(PlaybookWorkspaceSourceChunk).filter(
        PlaybookWorkspaceSourceChunk.source_id == source.id
    ).delete(synchronize_session=False)
    for chunk in chunks:
        row = chunk.as_row()
        session.add(PlaybookWorkspaceSourceChunk(
            source_id=source.id, ordinal=row["ordinal"], kind=row["kind"],
            locator=row["locator"], path=row["path"], text=row["text"],
            data=row["data"], token_estimate=row["token_estimate"],
        ))
    session.flush()


def sources(session, workspace_id: int) -> list[PlaybookWorkspaceSource]:
    stmt = (select(PlaybookWorkspaceSource)
            .where(PlaybookWorkspaceSource.workspace_id == workspace_id)
            .order_by(PlaybookWorkspaceSource.id))
    return list(session.execute(stmt).scalars())


def chunks(session, source_id: int) -> list[PlaybookWorkspaceSourceChunk]:
    stmt = (select(PlaybookWorkspaceSourceChunk)
            .where(PlaybookWorkspaceSourceChunk.source_id == source_id)
            .order_by(PlaybookWorkspaceSourceChunk.ordinal))
    return list(session.execute(stmt).scalars())


# ----------------------------------------------------------------- attachments


def attach(session, workspace_id: int, *, message_id: int | None = None,
           source_id: int | None = None, export_revision_id: int | None = None,
           position: int = 0) -> PlaybookAttachment:
    if not source_id and not export_revision_id:
        raise ValueError("an attachment must reference a source or an export")
    row = PlaybookAttachment(
        workspace_id=workspace_id, message_id=message_id,
        kind="source" if source_id else "export_revision",
        source_id=source_id, export_revision_id=export_revision_id,
        position=position,
    )
    session.add(row)
    session.flush()
    return row


def attachments(session, workspace_id: int,
                message_id: int | None = None) -> list[PlaybookAttachment]:
    stmt = select(PlaybookAttachment).where(
        PlaybookAttachment.workspace_id == workspace_id)
    if message_id is not None:
        stmt = stmt.where(PlaybookAttachment.message_id == message_id)
    return list(session.execute(stmt.order_by(PlaybookAttachment.position)).scalars())


# ------------------------------------------------------------------- artifacts


def create_artifact(session, workspace_id: int, *, kind: str, title: str,
                    derived_from_artifact_id: int | None = None,
                    derived_from_version_id: int | None = None
                    ) -> PlaybookArtifact:
    artifact = PlaybookArtifact(
        workspace_id=workspace_id, kind=kind, title=title,
        derived_from_artifact_id=derived_from_artifact_id,
        derived_from_version_id=derived_from_version_id,
    )
    session.add(artifact)
    session.flush()
    return artifact


def new_version(session, artifact: PlaybookArtifact, *, content: dict,
                source_manifest: dict, content_hash: str,
                change_summary: str = "", origin: str = "assistant_live",
                applied_change_item_ids: list | None = None,
                base_version_id: int | None = None,
                created_by: int | None = None,
                validation: dict | None = None) -> PlaybookArtifactVersion:
    """Write the next immutable version.

    Refuses when `base_version_id` is not the artifact's current version. A
    proposal prepared against v2 must not be applied to v3 as though nothing had
    happened in between: the user is told the document moved, and decides.
    """
    if base_version_id is not None and artifact.current_version_id is not None:
        if base_version_id != artifact.current_version_id:
            raise StaleBaseVersion(
                "This change was prepared against an earlier version of the "
                "document, which has since been revised. Nothing was applied."
            )
    from sqlalchemy import func

    highest = session.execute(
        select(func.max(PlaybookArtifactVersion.version))
        .where(PlaybookArtifactVersion.artifact_id == artifact.id)
    ).scalar() or 0

    version = PlaybookArtifactVersion(
        artifact_id=artifact.id, version=highest + 1,
        parent_version_id=artifact.current_version_id,
        content=content, source_manifest=source_manifest,
        applied_change_item_ids=applied_change_item_ids or [],
        change_summary=change_summary, content_hash=content_hash,
        origin=origin, created_by=created_by, validation=validation or {},
    )
    session.add(version)
    session.flush()
    artifact.current_version_id = version.id
    artifact.updated_at = func.now()
    session.flush()
    return version


def add_file(session, version: PlaybookArtifactVersion, *, fmt: str,
             bytes_path: str, mime: str, filename: str, size_bytes: int,
             sha256: str, renderer: str, validated: bool,
             preview_path: str = "") -> PlaybookArtifactFile:
    row = PlaybookArtifactFile(
        version_id=version.id, format=fmt, bytes_path=bytes_path, mime=mime,
        filename=filename, size_bytes=size_bytes, sha256=sha256,
        renderer=renderer, validated=validated, preview_path=preview_path,
    )
    session.add(row)
    session.flush()
    return row


def artifacts(session, workspace_id: int) -> list[PlaybookArtifact]:
    stmt = (select(PlaybookArtifact)
            .where(PlaybookArtifact.workspace_id == workspace_id)
            .order_by(PlaybookArtifact.id))
    return list(session.execute(stmt).scalars())


def versions(session, artifact_id: int) -> list[PlaybookArtifactVersion]:
    stmt = (select(PlaybookArtifactVersion)
            .where(PlaybookArtifactVersion.artifact_id == artifact_id)
            .order_by(PlaybookArtifactVersion.version))
    return list(session.execute(stmt).scalars())


def files(session, version_id: int) -> list[PlaybookArtifactFile]:
    stmt = (select(PlaybookArtifactFile)
            .where(PlaybookArtifactFile.version_id == version_id)
            .order_by(PlaybookArtifactFile.format))
    return list(session.execute(stmt).scalars())


# ----------------------------------------------------------------- change sets


def create_change_set(session, workspace_id: int, *, message_id: int | None,
                      base_version_id: int | None,
                      items: list[dict]) -> PlaybookChangeSet:
    change_set = PlaybookChangeSet(
        workspace_id=workspace_id, message_id=message_id,
        base_version_id=base_version_id,
    )
    session.add(change_set)
    session.flush()
    for n, item in enumerate(items, start=1):
        session.add(PlaybookChangeItem(
            change_set_id=change_set.id,
            display_number=item.get("display_number", n),
            stable_id=item["stable_id"],
            target_section=item.get("target_section", ""),
            rationale=item.get("rationale", ""),
            evidence=item.get("evidence") or {},
            proposed=item.get("proposed") or {},
            calculation=item.get("calculation") or {},
            depends_on=item.get("depends_on") or [],
        ))
    session.flush()
    return change_set


def change_items(session, change_set_id: int) -> list[PlaybookChangeItem]:
    stmt = (select(PlaybookChangeItem)
            .where(PlaybookChangeItem.change_set_id == change_set_id)
            .order_by(PlaybookChangeItem.display_number))
    return list(session.execute(stmt).scalars())


# ------------------------------------------------------------------- exporting


def find_export_revision(session, scope: Scope, revision_id: int
                         ) -> AnalysisExportRevision:
    """One export revision, or NotFound.

    The tenant check is the backend half of PB-005: a caller who skips the
    picker and posts an id directly gets the same answer as one whose id does
    not exist.
    """
    revision = session.get(AnalysisExportRevision, revision_id)
    if revision is None:
        raise NotFound(f"No exported analysis revision {revision_id}.")
    export = session.get(AnalysisExport, revision.export_id)
    if export is None or export.tenant != scope.tenant:
        raise NotFound(f"No exported analysis revision {revision_id}.")
    return revision


def jobs_by_key(session, idempotency_key: str) -> PlaybookJob | None:
    return session.execute(
        select(PlaybookJob).where(
            PlaybookJob.idempotency_key == idempotency_key)
    ).scalars().first()
