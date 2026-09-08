"""
PostgreSQL tables for the Playbook workspace — CreditProbe's chat-first
document workspace.

Not the other Playbook
----------------------
`platform.Playbook` and `platform.PlaybookRun` are a different, older and
still-live feature: a STANDING INSTRUCTION that runs certified analyses on a
trigger and tests thresholds (docs/PRODUCT_SPEC.md §9). Nothing here touches it.
A Playbook *workspace* is the other sense of the word — a conversation in which
somebody builds and improves a committee report, a validation report or a deck
out of evidence they chose. The two share a word and nothing else, which is why
every table below is prefixed `playbook_workspace`-side rather than reusing
`playbooks`.

The three rules these tables exist to enforce
---------------------------------------------
**Evidence is pinned, not referenced.** A message attaches an export REVISION,
never an export. The library moving on afterwards cannot retroactively change
what a generated report was built from — which is the difference between a
provenance record and a hyperlink.

**A version is immutable.** `playbook_artifact_versions` rows are written once.
A revision that supersedes another does not edit it; restoring an older version
moves FORWARD as a new version, so the history of what was tried survives. A
failed generation writes no version at all, which is why the previous good
artifact is still the current one after a failure.

**The model does not supply figures.** Every number a report states must
reconcile to something in this schema — an export revision's payload, a parsed
source chunk with a locator, or a recorded deterministic calculation. That is
the repository's governing rule (README, "The language model is not the
calculator") applied to authored prose rather than to analysis.

These models share the declarative Base with backend/models/platform.py and
backend/db/models.py, so all three live in one schema and one Alembic history.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Registers `users` on the shared metadata. Almost every table below
# carries a foreign key to users.id, and SQLAlchemy can only resolve it
# if that Table object exists — without this import, a flush fails with
# NoReferencedTableError depending purely on which module was imported
# first. `backend/models/platform.py` carries the same import for the
# same reason.
from backend.db import models as _core_models  # noqa: F401
from backend.db.base import Base

# --------------------------------------------------------------------------
# Vocabularies. Closed lists, declared once, so a typo cannot invent a state.
# --------------------------------------------------------------------------

#: Which module an analysis was exported from. `what_if` is declared but has no
#: producing surface on this baseline — see docs/playbook/INTEGRATION_NOTES.md.
SOURCE_MODULES = (
    "cockpit",
    "early_warning",
    "what_if",
    "scorecard_validation",
    "lenses",
)

#: What a source document IS to the request, which is not the same as its file
#: type. A previous report and an empty template are both .docx and are not
#: remotely the same input.
SOURCE_ROLES = (
    "previous_report",
    "template",
    "methodology",
    "results",
    "supporting",
)

#: Where a row's content came from. Kept separate from `role` so a seeded
#: assistant turn can never be presented as something a model wrote: §13 of the
#: specification forbids model attribution for synthetic fixture text.
ORIGINS = ("user", "assistant_live", "seed_fixture", "system")

#: Artifact families. A report and the deck derived from it are different
#: artifacts with their own version histories, linked by lineage.
ARTIFACT_KINDS = ("report", "presentation", "workbook")

#: The formats a version can be rendered into. Enforced against the capability
#: registry, so an unsupported request is refused rather than faked.
ARTIFACT_FORMATS = ("docx", "pdf", "pptx", "xlsx")

SOURCE_STATUSES = ("uploaded", "parsing", "parsed", "partial", "failed")

CHANGE_ITEM_STATUSES = ("proposed", "approved", "rejected", "applied", "superseded")

JOB_STATES = (
    "queued",
    "reviewing_sources",
    "drafting",
    "rendering",
    "validating",
    "ready",
    "cancelled",
    "failed",
)


# --------------------------------------------------------------------------
# The exported-analysis library
# --------------------------------------------------------------------------


class AnalysisExport(Base):
    """One analysis somebody explicitly exported to Playbook.

    "Saved in a module" and "exported to Playbook" are different states, and the
    library contains only the second. This row is the family; the content lives
    in its revisions, because re-exporting a changed analysis must produce new
    evidence rather than silently rewriting evidence a report already cites.
    """

    __tablename__ = "analysis_exports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    source_module: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Thread / run / result identifiers and a stable in-product link, as the
    #: source module knows them. Shape varies by module, so it is JSONB rather
    #: than five nullable columns that are wrong for four of the five.
    source_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Which document family this evidence usually serves, for library filtering.
    report_family: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: Reporting period as exported, e.g. "Q2 2026". Denormalised from the payload
    #: so the library can filter and sort without opening every snapshot.
    reporting_period: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    #: One sentence for the library card. Not a substitute for the payload.
    insight: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: True for clearly labelled pre-exported demonstration fixtures.
    demo_origin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seed_version: Mapped[str] = mapped_column(String(24), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    revisions: Mapped[list[AnalysisExportRevision]] = relationship(
        back_populates="export",
        cascade="all, delete-orphan",
        order_by="AnalysisExportRevision.revision",
    )

    __table_args__ = (
        Index("ix_analysis_exports_library", "tenant", "created_at"),
        Index("ix_analysis_exports_module", "tenant", "source_module", "created_at"),
    )


class AnalysisExportRevision(Base):
    """An immutable snapshot of what one analysis said at one moment.

    Self-contained on purpose: it must still be useful when the user has left
    the source screen, when the source thread is archived, and when the book has
    been rebuilt. It stores what was persisted at export time and never
    recomputes — the rule `backend/exports/contract.py` already states for
    workbooks, applied to the evidence a report is built on.

    `content_hash` is unique per family, which is what makes re-exporting an
    unchanged analysis idempotent instead of accumulating identical evidence.
    """

    __tablename__ = "analysis_export_revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    export_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_exports.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)

    #: The full contract payload: narrative, tables, chart specs, scope, units,
    #: assumptions, limitations, provenance locators, data-quality warnings.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The source's own revision at export time, where the module has one.
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="user")

    exported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    exported_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    export: Mapped[AnalysisExport] = relationship(back_populates="revisions")

    __table_args__ = (
        UniqueConstraint("export_id", "revision", name="uq_analysis_export_revision"),
        # Idempotency: the same snapshot of the same analysis exports once.
        UniqueConstraint("export_id", "content_hash", name="uq_analysis_export_content"),
    )


# --------------------------------------------------------------------------
# The workspace and its conversation
# --------------------------------------------------------------------------


class PlaybookWorkspace(Base):
    """One ongoing piece of document work, with its whole history.

    A playbook is a workspace, not a generated file. Reopening it restores the
    conversation, the sources, the decisions and every artifact version — which
    is why none of that lives in front-end state.
    """

    __tablename__ = "playbook_workspaces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: The user's own words. Renameable, and never silently rewritten.
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    document_family: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: One line for the home card: where this work has actually got to.
    state_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Standing instructions the user gave that later turns must still honour.
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")

    demo_origin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seed_version: Mapped[str] = mapped_column(String(24), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list[PlaybookMessage]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by="PlaybookMessage.sequence",
    )

    __table_args__ = (
        Index("ix_playbook_workspaces_recent", "tenant", "last_activity_at"),
        Index("ix_playbook_workspaces_owner", "tenant", "owner_id", "last_activity_at"),
    )


class PlaybookMessage(Base):
    """One turn. Content is structured blocks rather than one text blob, so an
    answer's headings, tables, source references and artifact cards survive a
    reload as themselves rather than as markup somebody has to re-parse.

    `origin` distinguishes a live model answer from seeded fixture text. §13
    requires that separation: a demonstration may show a realistic history, but
    it may not attribute prewritten prose to a model that never wrote it.
    """

    __tablename__ = "playbook_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="user")

    #: Provider accounting, for the honest-operations requirements. Never a
    #: prompt, never source content, never anything key-shaped.
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    request_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_jobs.id", ondelete="SET NULL"), nullable=True
    )
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workspace: Mapped[PlaybookWorkspace] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint("workspace_id", "sequence", name="uq_playbook_message_seq"),
        Index("ix_playbook_messages_thread", "workspace_id", "sequence"),
    )


# --------------------------------------------------------------------------
# Sources: what the user supplied, and what was actually read of it
# --------------------------------------------------------------------------


class PlaybookSource(Base):
    """An uploaded document, and an honest account of how much of it was read.

    `manifest` is the part that matters. Claiming to have checked every sheet
    when four were skipped is the failure this column exists to make impossible:
    what was read, what was not, and why, travels with the file.
    """

    __tablename__ = "playbook_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    #: Path under the configured upload directory. The bytes are never stored in
    #: a front-end component or an ephemeral execution container.
    bytes_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    source_role: Mapped[str] = mapped_column(String(32), nullable=False, default="supporting")
    #: How the role was decided: `inferred` or `user`. A user's correction is
    #: never overwritten by a later inference.
    role_set_by: Mapped[str] = mapped_column(String(16), nullable=False, default="inferred")
    role_confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    reporting_period: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploaded")
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: The Files API id, when this source has been uploaded for code execution.
    #: Server-side only: a file id is never accepted from a client, because the
    #: Files API is workspace-scoped and one user's id would read another's file.
    provider_file_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    provider_file_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunks: Mapped[list[PlaybookSourceChunk]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="PlaybookSourceChunk.ordinal",
    )

    __table_args__ = (Index("ix_playbook_sources_workspace", "workspace_id", "created_at"),)


class PlaybookSourceChunk(Base):
    """One addressable piece of a source, with the locator that points back at it.

    The locator is the whole point: `xlsx://ECL!B12`, `docx://para/17`,
    `pdf://p4`, `pptx://slide/6`. A report that cites a figure can say where the
    figure came from, and a section-level edit can find what it is editing.
    """

    __tablename__ = "playbook_source_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_sources.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    locator: Mapped[str] = mapped_column(String(300), nullable=False)
    #: Heading path, e.g. ["4. Results", "4.2 Coverage"], for section addressing.
    path: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Typed content for tables and sheet ranges: columns, units, rows.
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source: Mapped[PlaybookSource] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("source_id", "ordinal", name="uq_playbook_source_chunk"),
        Index("ix_playbook_source_chunks_source", "source_id", "ordinal"),
    )


class PlaybookAttachment(Base):
    """What one message brought with it.

    An export attaches by REVISION. Pinning the revision at submission is what
    stops a library update, arriving while a generation is in flight, from
    changing what that generation was answering.
    """

    __tablename__ = "playbook_attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    #: Null means the attachment belongs to the workspace rather than one turn.
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_messages.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_sources.id", ondelete="CASCADE"), nullable=True
    )
    export_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_export_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_playbook_attachments_message", "message_id", "position"),
        Index("ix_playbook_attachments_workspace", "workspace_id", "position"),
    )


# --------------------------------------------------------------------------
# Artifacts and their immutable versions
# --------------------------------------------------------------------------


class PlaybookArtifact(Base):
    """A document being worked on, across all of its versions.

    A deck derived from a report is its own artifact with its own history, and
    records the report version it came from. That is why lineage is two columns
    here rather than one shared version chain.
    """

    __tablename__ = "playbook_artifacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    current_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    derived_from_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    derived_from_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    versions: Mapped[list[PlaybookArtifactVersion]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        order_by="PlaybookArtifactVersion.version",
        foreign_keys="PlaybookArtifactVersion.artifact_id",
    )

    __table_args__ = (Index("ix_playbook_artifacts_workspace", "workspace_id", "updated_at"),)


class PlaybookArtifactVersion(Base):
    """One immutable revision of a document.

    Written once and never updated. `parent_version_id` gives the chain,
    `applied_change_item_ids` says exactly which approved changes produced it,
    and `source_manifest` records the evidence it was built from — so "what
    changed, and on what authority" is answerable months later without a
    reconstruction.

    Restoring an older version writes a NEW row whose parent is the current one.
    Nothing is deleted, because the history of what was tried is itself evidence.
    """

    __tablename__ = "playbook_artifact_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_artifact_versions.id", ondelete="SET NULL"), nullable=True
    )
    #: The canonical document: source-linked sections, tables, findings, prose.
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Which sources and export revisions this version was built from.
    source_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    applied_change_item_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: What changed, in a sentence, for the in-app change log.
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="assistant_live")
    #: Parse-back and reconciliation results. A version whose validation failed
    #: is never labelled ready and never becomes `current_version_id`.
    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifact: Mapped[PlaybookArtifact] = relationship(
        back_populates="versions", foreign_keys=[artifact_id]
    )
    files: Mapped[list[PlaybookArtifactFile]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("artifact_id", "version", name="uq_playbook_artifact_version"),
        Index("ix_playbook_artifact_versions_artifact", "artifact_id", "version"),
    )


class PlaybookArtifactFile(Base):
    """The actual bytes of one version in one format.

    A file card that cannot be downloaded is not a file, so the bytes are
    fetched out of the provider's container and written to durable storage
    BEFORE a job is allowed to complete. `renderer` records which path produced
    it, because "generated by a document Skill" and "rendered locally" are
    different claims and only one of them may be made at a time.
    """

    __tablename__ = "playbook_artifact_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_artifact_versions.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    bytes_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    renderer: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    #: A rendered preview (page or slide images) for in-app inspection.
    preview_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    version: Mapped[PlaybookArtifactVersion] = relationship(back_populates="files")

    __table_args__ = (
        UniqueConstraint("version_id", "format", name="uq_playbook_artifact_file_format"),
    )


# --------------------------------------------------------------------------
# Proposals and decisions
# --------------------------------------------------------------------------


class PlaybookChangeSet(Base):
    """A numbered set of proposed changes, against the version it was proposed on.

    `base_version_id` is what makes "apply 1, 2 and 3" survive a refresh and a
    later turn — and what lets a proposal made against a superseded version be
    recognised as stale instead of applied to the wrong document.
    """

    __tablename__ = "playbook_change_sets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_messages.id", ondelete="SET NULL"), nullable=True
    )
    base_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_artifact_versions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list[PlaybookChangeItem]] = relationship(
        back_populates="change_set",
        cascade="all, delete-orphan",
        order_by="PlaybookChangeItem.display_number",
    )

    __table_args__ = (Index("ix_playbook_change_sets_workspace", "workspace_id", "created_at"),)


class PlaybookChangeItem(Base):
    """One proposed change, with everything needed to decide it.

    `display_number` is what the user sees and says ("apply 1, 2 and 3");
    `stable_id` is what the system acts on. They are separate because display
    numbers renumber and an instruction must not start meaning something else.
    """

    __tablename__ = "playbook_change_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    change_set_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_change_sets.id", ondelete="CASCADE"), nullable=False
    )
    display_number: Mapped[int] = mapped_column(Integer, nullable=False)
    stable_id: Mapped[str] = mapped_column(String(40), nullable=False)

    target_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    target_section: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Locators and export revisions supporting the proposal.
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: The proposed text, table or action.
    proposed: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Any deterministic calculation the change depends on, with provenance.
    calculation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Stable ids of items this one materially depends on. An approved change
    #: whose dependency was rejected is explained, never silently forced through.
    depends_on: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    change_set: Mapped[PlaybookChangeSet] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("change_set_id", "display_number", name="uq_playbook_change_number"),
        UniqueConstraint("change_set_id", "stable_id", name="uq_playbook_change_stable_id"),
    )


# --------------------------------------------------------------------------
# Generation jobs
# --------------------------------------------------------------------------


class PlaybookJob(Base):
    """One generation, and everything needed not to run it twice.

    `idempotency_key` is unique. A refresh, a double-click or a retry after a
    dropped connection finds the existing job rather than starting a second
    billable generation — the durable half of the guarantee whose in-flight half
    is the agent queue's one-live-job-per-key index.
    """

    __tablename__ = "playbook_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="authoring")
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    #: The row in the shared durable queue that actually runs this.
    agent_job_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    state: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    #: Real milestones only. There is no percentage here because there is no
    #: honest basis for one.
    milestones: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    provider_request_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    container_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_playbook_job_idempotency"),
        Index("ix_playbook_jobs_workspace", "workspace_id", "created_at"),
    )
