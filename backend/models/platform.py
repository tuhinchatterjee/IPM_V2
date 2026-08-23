"""
PostgreSQL tables for the application, governance and metadata layer.

What belongs here, and what does not
------------------------------------
PostgreSQL is the filing cabinet: everything the bank has *decided*, configured
or recorded. Users, projects, chats, the definitions of every analysis and every
data field, workflow approvals, and every trace.

Large monthly analytical data does NOT belong here. Millions of facility rows per
month live in Parquet and are read through the Data Access Layer
(docs/ARCHITECTURE.md §4.1). Putting them in PostgreSQL would be storing shipping
containers in a filing cabinet.

Phase 1 creates the governance spine — the tables the rest of the platform hangs
off. Later phases add teams, permissions, blueprints, lenses, documents and
workflow transitions on top of it without reshaping what is here.

These models share the declarative Base with backend/db/models.py (dataset
versions, users, AI usage), so everything lives in one schema and one Alembic
history.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
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

# Importing the core models registers `users`, `dataset_versions` and
# `ai_usage_log` on the shared metadata. Several tables here carry a foreign key
# to users.id, and SQLAlchemy can only resolve it if that Table object exists —
# without this import, any flush touching those tables fails with
# NoReferencedTableError depending purely on import order.
from backend.db import models as _core_models  # noqa: F401
from backend.db.base import Base

# --------------------------------------------------------------------------
# Lifecycle vocabularies. Kept as module constants rather than database enums so
# a new state does not require a migration — governance vocabularies change more
# often than table shapes do.
# --------------------------------------------------------------------------

RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_REJECTED = "rejected"  # the plan failed validation and was never executed

# Data Builder dataset lifecycle. A dataset becomes readable by the analytical
# engine only at PUBLISHED — see backend/services/data_builder.py.
DS_DRAFT = "draft"
DS_MAPPED = "mapped"
DS_VALIDATED = "validated"
DS_PUBLISHED = "published"
DS_ARCHIVED = "archived"
DATASET_LIFECYCLE = [DS_DRAFT, DS_MAPPED, DS_VALIDATED, DS_PUBLISHED]

# Field mapping outcomes.
MAP_MAPPED = "mapped"
MAP_UNMAPPED = "unmapped"
MAP_IGNORED = "ignored"
MAP_PROPOSED = "proposed"  # a new governed field the steward wants created

CERT_CERTIFIED = "certified"
CERT_USER_DEFINED = "user_defined"
CERT_DRAFT = "draft"
CERT_DEPRECATED = "deprecated"


# ============================================================ organisation


class Team(Base):
    """A group of users. Projects are owned by teams, which is how access is
    granted to a body of work rather than to individual objects one by one."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Role within the team: owner | member | viewer
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="member")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ================================================================= projects


class Project(Base):
    """A container for a body of work — "Q1 2026 Board Pack", "Real Estate Deep
    Dive". Holds chats, investigations, saved analyses, traces and scenarios."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Default analytical scope for work in this project (period, filters).
    default_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    chats: Mapped[list[Chat]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Chat(Base):
    """A threaded conversation inside a project. Every analytical result produced
    in it stays linked to its Trace."""

    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="New chat")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="chats")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_chats_project", "project_id"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # When an assistant turn produced an analysis, this points at the run — which
    # is what puts a Trace button on the result.
    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chat: Mapped[Chat] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_chat_messages_chat", "chat_id", "created_at"),)


# ============================================================ analysis runs


class AnalysisRun(Base):
    """One execution of one plan.

    Records the question, the plan the planner produced, the outcome, and — most
    importantly for governance — the dataset version and the exact function
    versions used. That is what makes a number reproducible nine months later.
    """

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    chat_id: Mapped[int | None] = mapped_column(ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intent: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # period, filters

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RUN_PENDING)
    # Populated when a plan is rejected by the validator. Rejections are recorded,
    # not discarded: "what did the model try to do that we refused?" is an
    # auditable question.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")
    follow_ups: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Provenance.
    dataset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    function_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trace_versions: Mapped[list[TraceVersionRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_analysis_runs_project", "project_id", "created_at"),)


# ==================================================================== trace


class TraceVersionRow(Base):
    """One version of a trace graph.

    The original is never mutated. A modification creates a new row whose
    `parent_version_id` points at what it was derived from, so the full history of
    how an analysis evolved is preserved and can be compared side by side.

    The graph itself is stored as JSONB rather than as node/edge tables: it is
    read and written whole, always belongs to exactly one version, and is never
    queried across runs. A document is the right shape for it.
    """

    __tablename__ = "trace_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("trace_versions.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="Original")

    graph: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    node_hashes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[AnalysisRun] = relationship(back_populates="trace_versions")

    __table_args__ = (
        UniqueConstraint("analysis_run_id", "version_number", name="uq_trace_version_per_run"),
    )


class TraceModificationRow(Base):
    """A requested change to a trace, and what it did.

    Recording the request, the interpretation, the affected nodes and the
    before/after is what turns "the AI changed something" into a reviewable
    decision.
    """

    __tablename__ = "trace_modifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    from_version_id: Mapped[int] = mapped_column(
        ForeignKey("trace_versions.id", ondelete="CASCADE"), nullable=False
    )
    to_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("trace_versions.id", ondelete="SET NULL"), nullable=True
    )
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    interpretation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    affected_nodes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    hash_diff: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # proposed | accepted | rejected | failed — a modification is previewed before
    # it is applied, so "proposed but not accepted" is a real state.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ========================================================== engine builder


class EngineDefinition(Base):
    """An analytical capability as governed metadata.

    The Python implementation lives in backend/engine/functions/. This table is
    the *governance* record: who owns it, what it declares, which version is
    current, and whether the bank has certified it. Engine Builder edits this.
    """

    __tablename__ = "engine_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="monitor")
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="Credit Risk Analytics")
    certification: Mapped[str] = mapped_column(String(24), nullable=False, default=CERT_DRAFT)
    current_version: Mapped[str] = mapped_column(String(24), nullable=False, default="1.0.0")
    contract: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list[EngineVersion]] = relationship(
        back_populates="definition", cascade="all, delete-orphan"
    )


class EngineVersion(Base):
    """One immutable version of an analytical capability.

    Certified versions are never edited — a change means a new version. That is
    what lets an analysis run months ago be reproduced exactly.
    """

    __tablename__ = "engine_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_definition_id: Mapped[int] = mapped_column(
        ForeignKey("engine_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(24), nullable=False)
    contract: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    certification: Mapped[str] = mapped_column(String(24), nullable=False, default=CERT_DRAFT)
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    certified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    certified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    definition: Mapped[EngineDefinition] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("engine_definition_id", "version", name="uq_engine_version"),
    )


class EngineTest(Base):
    """A test case for an analytical capability, and its last result.

    An analysis may not be certified while any of its tests is failing — the same
    control the climate engine already enforces with its quality checks.
    """

    __tablename__ = "engine_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_definition_id: Mapped[int] = mapped_column(
        ForeignKey("engine_definitions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    expected: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tolerance: Mapped[float] = mapped_column(nullable=False, default=1e-9)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # passed | failed
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")


# ============================================================= data builder


class DataDomain(Base):
    """A top-level grouping of datasets, e.g. "Core Portfolio / Facility"."""

    __tablename__ = "data_domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DatasetDefinition(Base):
    """A governed dataset. Mirrors metadata/catalog.json.

    In Phase 1 the catalogue is generated to a JSON file by the data-lake build,
    which is what the Data Access Layer reads. Phase 5 makes this table the
    editable source of truth and generates the file from it, so the shape is the
    same on purpose — nothing above the catalogue changes when it moves.
    """

    __tablename__ = "dataset_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    business_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    grain: Mapped[str] = mapped_column(Text, nullable=False, default="")
    primary_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    period_field: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    refresh_frequency: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    sensitivity: Mapped[str] = mapped_column(String(24), nullable=False, default="internal")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    version: Mapped[str] = mapped_column(String(24), nullable=False, default="1.0.0")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    storage_location: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ---- Data Builder lifecycle (Phase 2) ----
    # draft -> mapped -> validated -> published. Only `published` datasets are
    # visible to the analytical engine.
    lifecycle: Mapped[str] = mapped_column(String(24), nullable=False, default=DS_DRAFT)
    # upload | bundled — `bundled` marks the datasets produced by the original
    # scripts/build_data_lake.py path, which keeps working untouched.
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, default="upload")
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    fields: Mapped[list[FieldDefinition]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    uploads: Mapped[list[DatasetUpload]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    mappings: Mapped[list[FieldMapping]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    versions: Mapped[list[DataVersion]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class FieldDefinition(Base):
    """One Data Dictionary entry — the single definition of a field in IPM.

    Explain, the planner's resolution of business terms, and the Data Builder UI
    all read this, so there is exactly one definition of "EAD" in the system.
    """

    __tablename__ = "field_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_definitions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    business_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    definition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_type: Mapped[str] = mapped_column(String(24), nullable=False, default="string")
    unit: Mapped[str | None] = mapped_column(String(48), nullable=True)
    allowed_values: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sensitivity: Mapped[str] = mapped_column(String(24), nullable=False, default="internal")
    source_system: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    source_field: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    dataset: Mapped[DatasetDefinition] = relationship(back_populates="fields")

    __table_args__ = (UniqueConstraint("dataset_id", "name", name="uq_field_per_dataset"),)


class DataQualityRule(Base):
    """A rule the data must satisfy, and the result of its last evaluation."""

    __tablename__ = "data_quality_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_definitions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(48), nullable=False, default="not_null")
    expression: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="error")
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatasetUpload(Base):
    """One uploaded source file, and what inspecting it found.

    The uploaded bytes are written to the RAW layer and never modified. This row
    records where they went, their checksum, and the automatic profile (columns,
    inferred types, null rates, ranges) so the mapping screen has something to
    show without re-reading the file.
    """

    __tablename__ = "dataset_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_definitions.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)  # csv | xlsx | parquet
    sheet_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped[DatasetDefinition] = relationship(back_populates="uploads")


class FieldMapping(Base):
    """One source column, and what it becomes in the governed model.

    Mapping is kept separate from FieldDefinition on purpose: the dictionary
    describes the *governed* field (what "EAD" means to the bank), while the
    mapping records which of this file's columns supplies it. The same governed
    field is fed by differently-named columns in different source systems.
    """

    __tablename__ = "field_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_definitions.id", ondelete="CASCADE"), nullable=False
    )
    source_column: Mapped[str] = mapped_column(String(300), nullable=False)
    governed_field: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=MAP_UNMAPPED)
    # How confident the automatic suggestion was, 0-1. Null when set by hand.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    dataset: Mapped[DatasetDefinition] = relationship(back_populates="mappings")

    __table_args__ = (
        UniqueConstraint("dataset_id", "source_column", name="uq_mapping_per_source_column"),
    )


class DatasetRelationship(Base):
    """A governed join between two datasets, e.g. Portfolio.facility_id -> ECL.facility_id."""

    __tablename__ = "dataset_relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    from_dataset: Mapped[str] = mapped_column(String(160), nullable=False)
    from_field: Mapped[str] = mapped_column(String(160), nullable=False)
    to_dataset: Mapped[str] = mapped_column(String(160), nullable=False)
    to_field: Mapped[str] = mapped_column(String(160), nullable=False)
    cardinality: Mapped[str] = mapped_column(String(24), nullable=False, default="many_to_one")
    # key | reporting_period — a reporting-period link is checked differently
    # (the periods must align) from an identifier link (the values must exist).
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="key")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "from_dataset", "from_field", "to_dataset", "to_field", name="uq_relationship"
        ),
    )


class DataVersion(Base):
    """An immutable published release of a dataset.

    Publishing writes the curated Parquet and records this row. The raw upload is
    never touched, so any published figure can always be re-derived from exactly
    the bytes the source system sent.
    """

    __tablename__ = "data_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_uploads.id", ondelete="SET NULL"), nullable=True
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    field_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    periods: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    analytics_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    curated_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    catalog_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    quality_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped[DatasetDefinition] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_data_version"),)

# ================================================================== stress


class StressScenario(Base):
    """A named, versioned, parameterised shock.

    Scenarios are objects rather than free text precisely so a stressed number can
    be reproduced exactly and argued with in a committee.
    """

    __tablename__ = "stress_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="moderate")
    version: Mapped[str] = mapped_column(String(24), nullable=False, default="1.0.0")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("name", "version", name="uq_scenario_version"),)


# ================================================================ workflow


class WorkflowItem(Base):
    """A review/approval task on something that carries institutional weight:
    certifying an analysis, publishing a dataset, approving a scenario, signing
    off a document."""

    __tablename__ = "workflow_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(48), nullable=False)
    object_id: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # draft | submitted | in_review | approved | rejected | withdrawn
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_workflow_object", "object_type", "object_id"),)


class WorkflowEvent(Base):
    """An immutable decision record. Append-only: a workflow's history is evidence
    and is never edited."""

    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workflow_item_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_items.id", ondelete="CASCADE"), nullable=False
    )
    from_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comment(Base):
    """A comment attached to any object — a result, a trace node, a dataset, a
    document paragraph."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(48), nullable=False)
    object_id: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_comments_object", "object_type", "object_id"),)


# ============================================================== app config


class AppSetting(Base):
    """Key/value application configuration that an administrator can change at
    runtime — reporting calendar, defaults, feature switches.

    Secrets never live here. Those come from environment variables and are never
    written to the database or committed to the repository.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserPreference(Base):
    """Per-user settings. Theme choice lives here — the Theme Gallery writes it."""

    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme: Mapped[str] = mapped_column(String(48), nullable=False, default="executive-light")
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
