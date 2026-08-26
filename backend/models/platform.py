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

# An investigation thread's lifecycle. LIVE means it is expected to be kept
# current; ARCHIVED means it is kept for the record and no longer refreshed.
INV_LIVE = "live"
INV_ARCHIVED = "archived"

# A Project's governed lifecycle. These are NOT decorative labels.
#
#   DRAFT      set up, not yet being worked on
#   ACTIVE     currently being worked on
#   IN_REVIEW  a workflow review request is actually outstanding
#   COMPLETED  the work is finished and the conclusions stand
#   ARCHIVED   kept for the record, no longer worked on
#
# IN_REVIEW in particular is derived from real workflow state rather than set by
# hand, which is why it is excluded from the manual transitions below: a status
# that can be typed in means nothing to a reviewer.
PJ_DRAFT = "draft"
PJ_ACTIVE = "active"
PJ_IN_REVIEW = "in_review"
PJ_COMPLETED = "completed"
PJ_ARCHIVED = "archived"
PROJECT_STATUSES = (PJ_DRAFT, PJ_ACTIVE, PJ_IN_REVIEW, PJ_COMPLETED, PJ_ARCHIVED)
PROJECT_STATUS_LABEL = {
    PJ_DRAFT: "Draft",
    PJ_ACTIVE: "Active",
    PJ_IN_REVIEW: "In review",
    PJ_COMPLETED: "Completed",
    PJ_ARCHIVED: "Archived",
}
#: Transitions a person may make directly. IN_REVIEW is deliberately absent —
#: it is entered by submitting the project for review, and left by the reviewer
#: deciding. See backend/services/projects.py.
PROJECT_MANUAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    PJ_DRAFT: (PJ_ACTIVE, PJ_ARCHIVED),
    PJ_ACTIVE: (PJ_COMPLETED, PJ_ARCHIVED, PJ_DRAFT),
    PJ_IN_REVIEW: (),
    PJ_COMPLETED: (PJ_ACTIVE, PJ_ARCHIVED),
    PJ_ARCHIVED: (PJ_ACTIVE,),
}

# Workflow states, as one vocabulary rather than three copies of the strings.
WF_DRAFT = "draft"
WF_SUBMITTED = "submitted"
WF_IN_REVIEW = "in_review"
WF_APPROVED = "approved"
WF_REJECTED = "rejected"
WF_WITHDRAWN = "withdrawn"
WF_OPEN_STATES = (WF_SUBMITTED, WF_IN_REVIEW)

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
    """The MASTER WORKSPACE. The top level of the product hierarchy.

        Project          this
          Investigation    a conversational thread
            Analysis         one deterministic engine result

    A Project — "Q1 2026 Board Pack", "Real Estate Deep Dive" — holds the
    investigations run for it, the analyses somebody kept, documents, people,
    and the standing context every question inside it should assume.

    `status` is a governed lifecycle (see PROJECT_STATUSES). It is not a
    decorative label: IN REVIEW means a workflow review request is genuinely
    outstanding, and every transition is recorded in project_status_events.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=PJ_DRAFT)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Default analytical scope for work in this project (period, filters).
    default_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Standing instructions every investigation in this project should assume —
    #: "we are reviewing the Real Estate book for the Q2 board pack". Read by the
    #: planner as context, never as a source of figures.
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")

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


class GridPreference(Base):
    """How one person likes to look at one dataset.

    Column widths, which columns are hidden, how many stay on screen while
    scrolling, and how tightly the rows are packed. Stored per USER and per
    DATASET rather than per browser: a data steward who has spent an afternoon
    arranging the facility grid should find it arranged the next morning, and on
    the other machine.

    Deliberately opaque JSON. This is a record of somebody's preference, not a
    governed object — nothing reads it but the grid that wrote it, and giving it
    a schema would mean a migration every time a column control is added.
    """

    __tablename__ = "grid_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dataset: Mapped[str] = mapped_column(String(160), nullable=False)
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "dataset", name="uq_grid_preference"),
    )


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
    #: The conversation this run was produced in. Points at `investigations`,
    #: which is where conversations live — it used to point at the old `chats`
    #: table, and every threaded answer failed its foreign key on the way to
    #: being stored, which left the Trace button dead on every answer.
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intent: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # period, filters

    # Wide enough for the longest status the orchestrator can produce.
    # `needs_clarification` is nineteen characters and did not fit in sixteen,
    # so every question CreditProbe stopped to ask about failed to persist — and
    # a run with no id has a dead Trace button.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=RUN_PENDING)
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
    #: ACTIVE or ARCHIVED. Archiving takes a domain off the working list without
    #: touching what it contains — the datasets stay readable and every analysis
    #: that depends on them keeps working, which is the difference between
    #: archiving and deleting.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")


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

    # ---- the data control plane ----
    # demo | client | supplementary. `demo` is CreditProbe's bundled synthetic book. The
    # distinction is not cosmetic: an analysis that reads demo data must say so,
    # and client data always wins over demo data for the same purpose.
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="demo")
    # Datasets that describe the same thing at different times or from different
    # source systems belong to one family, so replacing one is a governed act
    # rather than a new unrelated table appearing.
    dataset_family: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    # The governed purposes this dataset is the authoritative source for, e.g.
    # ["credit_facility_position"]. Empty means it answers no governed purpose
    # and no certified analysis will read it by purpose.
    authoritative_for: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

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
    """One Data Dictionary entry — the single definition of a field in CreditProbe.

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
    """A governed join between two datasets, e.g. Portfolio.facility_id -> ECL.facility_id.

    This is the single source of truth for how governed datasets may be joined.
    The dynamic planner reads it; nothing else keeps a second join registry,
    because two registries eventually disagree and the analysis silently follows
    the wrong one.

    Governance is on the row rather than in a policy document. Only an ACTIVE
    relationship may be used at runtime, and `version` is stamped onto every
    Trace that used it — so a steward changing a definition creates a new
    version rather than quietly altering what a past analysis did.
    """

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

    # ---- governance --------------------------------------------------------
    #: draft | validated | active | archived. Only ACTIVE is usable at runtime.
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    #: Bumped whenever the join keys, cardinality or temporal rule change. A
    #: Trace records the version it used, so history stays true.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The preferred edge when two datasets can be joined more than one way.
    is_preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: How sure the bank is that this join means what it says, 0-1. A proposed
    #: relationship starts below the threshold and cannot be used until raised.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: What the join MEANS in business terms — "the facility this covenant
    #: tests" — as opposed to which columns it matches on.
    semantic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: inner | left | asof. How unmatched rows are treated, recorded rather than
    #: decided at each call site.
    join_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="inner")
    #: same_period | latest_on_or_before | none. How periods align across a
    #: frequency change. `latest_on_or_before` is the as-of rule, and it is what
    #: stops an annual rating from being read from the future.
    temporal_rule: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="same_period")

    # ---- validation --------------------------------------------------------
    match_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    orphan_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    duplicate_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "from_dataset", "from_field", "to_dataset", "to_field", name="uq_relationship"
        ),
        Index("ix_dataset_relationships_lifecycle", "lifecycle"),
    )


class DatasetRelationshipVersion(Base):
    """What a relationship WAS, when a past analysis used it.

    Kept so a Trace from March still describes the join that actually ran, not
    the one somebody redefined in June. Without this, "why did this number
    change" has no answer that survives a governance edit.
    """

    __tablename__ = "dataset_relationship_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    relationship_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_relationships.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("relationship_id", "version", name="uq_relationship_version"),
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


# ========================================================== investigations


class Investigation(Base):
    """A CONVERSATIONAL THREAD. The middle level of the product hierarchy.

        Project          the master workspace
          Investigation    this: one continuing conversation
            Analysis         one deterministic engine result

    An Investigation is not one saved answer. It is the whole thread: every
    question the user asked, every answer CreditProbe AI gave, every analysis
    that ran inside it, and the data scope the thread settled on. Reopening one
    puts the person back exactly where they left off, with a composer at the
    bottom.

    That is a deliberate change from the earlier model, where an Investigation
    meant a single saved analytical output. A single output is an *Analysis*
    (see SavedAnalysis below); a conversation is an Investigation.

    `context` holds what the thread has already settled — the governed data
    domain and the reporting period — so the second question in a thread is not
    asked the same clarification as the first.
    """

    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    #: The question that opened the thread. Kept denormalised for listings.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # How the opening question was read, and what period it was answered for.
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: What this thread has settled: {"domain": ..., "from_period": ..., "to_period": ...}.
    #: Read before asking a clarification, so it is asked once per thread.
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=INV_LIVE)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    #: Kept from the earlier model so existing rows and their history survive.
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Turns in the thread, denormalised so a listing does not count rows.
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list[InvestigationVersion]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan",
        order_by="InvestigationVersion.version_number",
    )
    messages: Mapped[list[InvestigationMessage]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan",
        order_by="InvestigationMessage.sequence",
    )

    __table_args__ = (
        Index("ix_investigations_project", "project_id", "updated_at"),
        Index("ix_investigations_owner", "owner_id", "updated_at"),
    )


class InvestigationMessage(Base):
    """One turn in an Investigation thread.

    A user turn carries the question. An assistant turn carries the direct
    answer in `content` and everything structured in `payload`: the plan, the
    executed steps, the interpretation, the follow-ups, and — when CreditProbe
    stopped to ask rather than answer — the clarification.

    `payload` is JSONB rather than a set of columns because it is written and
    read whole, always belongs to exactly one turn, and is never queried across
    threads. A document is the right shape for it, and it means the response
    format can grow without a migration.
    """

    __tablename__ = "investigation_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    investigation_id: Mapped[int] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
    )
    #: Position in the thread, 0-based. Unique per investigation.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: user | assistant | system
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: The execution behind an assistant turn. Its Trace is the evidence.
    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint("investigation_id", "sequence", name="uq_investigation_message_seq"),
        Index("ix_investigation_messages_thread", "investigation_id", "sequence"),
    )


class SavedAnalysis(Base):
    """An executed analysis somebody kept. The lowest level of the hierarchy.

    This is what Work → Analyses lists. It is one deterministic engine result,
    with everything needed to defend or reproduce it: which registered analysis
    at which version, which parameters, which filters, which periods, which
    execution produced it, and the result itself.

    It may have come out of an Investigation thread, been added to a Project, or
    both — or neither, if someone ran an analysis directly and kept it.
    """

    __tablename__ = "saved_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    #: The registered analysis, e.g. "stage_migration".
    analysis_id: Mapped[str] = mapped_column(String(120), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    certification: Mapped[str] = mapped_column(String(24), nullable=False, default=CERT_DRAFT)

    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: {"period": ..., "from_period": ..., "to_period": ...} as executed.
    period: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: The engine result as returned: rows, values, units, warnings, meta.
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Which governed datasets and versions it read. Recorded for defensibility.
    data_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_saved_analyses_project", "project_id", "created_at"),
        Index("ix_saved_analyses_investigation", "investigation_id", "created_at"),
        Index("ix_saved_analyses_owner", "owner_id", "created_at"),
    )


class ProjectStatusEvent(Base):
    """One change of a Project's lifecycle status.

    Project status is governed rather than decorative: IN REVIEW means a review
    request is actually outstanding, not that someone liked the label. Recording
    every transition is what lets the product refuse to invent one.
    """

    __tablename__ = "project_status_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_project_status_project", "project_id", "created_at"),)


class InvestigationVersion(Base):
    """One answer this investigation has had, and what changed to produce it.

    `change_narrative` is CreditProbe's account of the difference from the previous
    version, written from the two stored results. It is interpretation and is
    labelled as such wherever it is shown; the figures it quotes are the ones
    the engine returned on each run.
    """

    __tablename__ = "investigation_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    investigation_id: Mapped[int] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The execution that produced this version. Its Trace is the evidence.
    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )

    #: The periods this version was answered for, so a refresh can move them on.
    from_period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_period: Mapped[str | None] = mapped_column(String(64), nullable=True)

    narrative: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Headline figures, kept so two versions can be compared without re-running.
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: What changed since the previous version. Empty on version 1.
    change_narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")
    changes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("investigation_id", "version_number", name="uq_investigation_version"),
    )


# =============================================================== notifications


class Notification(Base):
    """Something a person needs to know about, in the application.

    Deliberately in-app only. Email and push are a deployment concern with their
    own approvals; the product's promise is that work assigned to you is visible
    when you open CreditProbe.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # assigned | mentioned | approved | rejected | commented | shared | refreshed
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: What it is about, so the notification can link straight to it.
    object_type: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    object_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_notifications_user", "user_id", "read_at", "created_at"),)


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


# ==================================================================== lenses


class Lens(Base):
    """A live dashboard somebody built by describing it.

    A Lens is not a saved screenshot. `definition` holds the structured
    specification — which certified analyses to run, over which governed data
    domains, for which period, with which filters, and how to lay the result
    out — and the workspace executes that specification against whatever is
    published now. Two people opening the same Lens a month apart see different
    figures produced by the same governed method, which is the point.

    The specification is versioned in `revisions` so a conversational change
    ("show this by region instead") is a recorded edit rather than an
    overwrite.
    """

    __tablename__ = "lenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audience: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    #: The LensDefinition: tiles, domains, period, filters, layout, refresh.
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: draft | published | archived
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: seeded | ai | manual — where the definition came from.
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    revisions: Mapped[list[LensRevision]] = relationship(
        back_populates="lens", cascade="all, delete-orphan",
        order_by="LensRevision.version",
    )


class LensRevision(Base):
    """One version of a Lens specification, and what was asked for to produce it."""

    __tablename__ = "lens_revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lens_id: Mapped[int] = mapped_column(
        ForeignKey("lenses.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: The plain-language request that produced this revision, if any.
    request: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: What CreditProbe understood the request to mean.
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lens: Mapped[Lens] = relationship(back_populates="revisions")

    __table_args__ = (UniqueConstraint("lens_id", "version", name="uq_lens_revision"),)


# ================================================================= playbooks


class Playbook(Base):
    """A reusable monitoring recipe.

    A Playbook answers four questions and nothing else: WHEN does it run, WHAT
    does it look at, WHICH analyses does it run, and WHAT counts as something
    worth telling a person about. It replaces the earlier Blueprint concept,
    which described an analytical template but had no trigger, no condition and
    no consequence — so it never did anything on its own.

    `conditions` are evaluated against engine results only. A Playbook cannot
    raise an alert on a figure no registered analysis produced.
    """

    __tablename__ = "playbooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: manual | new_data | scheduled
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    #: Cron-like description for a scheduled playbook, e.g. "quarterly".
    schedule: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: {"sector": ..., "segment": ...} — governed dimensions only.
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: [{"analysis_id": ..., "params": {...}}, ...]
    analyses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: [{"metric": ..., "operator": ">", "threshold": 2.0, "unit": "pp", "severity": ...}]
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: {"create_investigation": true, "notify": [...], "update_lens": "cro", ...}
    actions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: draft | active | paused
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    owner: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_hint: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list[PlaybookRun]] = relationship(
        back_populates="playbook", cascade="all, delete-orphan",
        order_by="PlaybookRun.created_at.desc()",
    )


class PlaybookRun(Base):
    """One execution of a Playbook, and what it decided."""

    __tablename__ = "playbook_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    playbook_id: Mapped[int] = mapped_column(
        ForeignKey("playbooks.id", ondelete="CASCADE"), nullable=False
    )
    #: succeeded | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded")
    #: Which periods it looked at.
    period: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: One entry per analysis: id, run id, key figures.
    results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: One entry per condition: met/not met, the figure, the threshold.
    evaluations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: What it did as a result.
    actions_taken: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    alerted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    playbook: Mapped[Playbook] = relationship(back_populates="runs")

    __table_args__ = (Index("ix_playbook_runs_playbook", "playbook_id", "created_at"),)


# ============================================================= early warning


class EarlyWarningModel(Base):
    """One version of the Forward Risk Signal scoring methodology.

    Never overwritten. Changing a weight in Model Lab creates a NEW row, so the
    score a borrower had last quarter can always be reproduced from the
    methodology that was in force at the time. `specification` holds the whole
    factor architecture — families, factors, transformations, weights,
    thresholds — as a document, because it is read and written whole and its
    shape is expected to change.

    `lifecycle` is separate from the analysis certification vocabulary on
    purpose. A CreditProbe Certified Analysis is a validated *calculation*; an
    early-warning model is a *predictive* artefact and needs its own evidence
    before anyone may call it validated.
    """

    __tablename__ = "early_warning_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: stage1_to_stage2 | stage1_to_stage3 | stage2_to_stage3
    target: Mapped[str] = mapped_column(String(48), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: prototype | candidate | validated | approved | retired
    lifecycle: Mapped[str] = mapped_column(String(24), nullable=False, default="prototype")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    specification: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: What changed against the previous version, and why.
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Backtest output, when it has been run. Empty means unvalidated.
    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("target", "version", name="uq_early_warning_model_version"),
        Index("ix_early_warning_active", "target", "is_active"),
    )


# ============================================================ analysis studio


class StudioMethod(Base):
    """A method the bank authored, forked or edited.

    Library methods are code, because they are a product decision and belong in
    review. These are not: they encode how one bank has decided to measure
    something, which is the bank's property and the bank's audit trail. So they
    live here, and both surface through one registry.

    The whole definition is one JSON document rather than forty columns. What a
    method IS keeps changing as the Studio grows, and the alternative is a
    migration every time a field is added — for a document nothing but the
    Studio reads. The columns that exist are the ones something else has to
    query on: which methods carry the tick, who owns them, what they were forked
    from.
    """

    __tablename__ = "studio_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    method_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    version: Mapped[str] = mapped_column(String(24), nullable=False, default="1.0.0")
    #: What it was forked from, so a variant's lineage survives a rename.
    forked_from: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_studio_methods_lifecycle", "lifecycle"),
        Index("ix_studio_methods_category", "category"),
    )


# =============================================================== data inbox


class InboxItem(Base):
    """One file that arrived, and what was decided about it.

    Data does not arrive because somebody sat down to onboard it. It arrives
    monthly, from a system, into a folder, and the interesting question is never
    "did the load succeed" — it is "is this file the same shape as the last one,
    and if not, does anybody know". So every arrival gets a row here whether it
    was published or held, and the row keeps the drift report and the reason.

    Kept separate from DatasetUpload deliberately. An upload is a file somebody
    chose to put into a dataset; an inbox item is a file that turned up, which
    may not belong to any dataset yet and may never be published at all.
    """

    __tablename__ = "data_inbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False, default="csv")
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    #: The governed dataset this was matched to. Empty when nothing matched —
    #: which is a state to show, not an error to swallow.
    dataset: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # received | profiled | held | published | rejected | unmatched
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="received")
    #: auto_publish | hold | reject — what the policy said, before any person.
    decision: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    #: Why, in the words a steward would use. Always populated when a decision is.
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    drift: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: Set when a person overrode the policy, so an override is never invisible.
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_uploads.id", ondelete="SET NULL"), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_data_inbox_status", "status", "received_at"),
        Index("ix_data_inbox_dataset", "dataset"),
    )


# =============================================================================
# AI validation — what the intelligence check found, and when
# =============================================================================
#
# Kept in PostgreSQL rather than in memory because the point of a score is the
# comparison: "94 last Tuesday, 79 today" is what tells somebody a model change,
# a prompt change or a data change broke something. A number that vanished on
# restart could not do that job.
#
# What is NOT stored here is the benchmark's expected answer. Gold data lives in
# the evaluation package and is loaded only by the runner, after execution — see
# backend/validation/ for the isolation rule and the test that enforces it.


class AiValidationRun(Base):
    """One user-triggered intelligence check."""

    __tablename__ = "ai_validation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)

    #: What was being validated. A score earned against one model on one build
    #: says nothing about another, which is what makes a run stale.
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    build_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    app_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    benchmark_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="")
    data_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    #: offline | configured | connected | degraded, as observed during the run.
    ai_state: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed")

    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    band: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partial: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Per-dimension averages — intent, plan, dataset, relationship, period,
    #: result, context, grounding.
    components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    selected_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    cases: Mapped[list[AiValidationCase]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
        order_by="AiValidationCase.position")

    __table_args__ = (
        Index("ix_ai_validation_runs_created", "created_at"),
    )


class AiValidationCase(Base):
    """One benchmark thread inside a run, with everything needed to inspect it."""

    __tablename__ = "ai_validation_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_validation_runs.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    benchmark_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")

    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: True when the live model was not used for any turn. Such a case fails the
    #: live-AI benchmark whatever its numbers say — the point of the check is
    #: whether the AI works, not whether the deterministic reader does.
    used_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)

    components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: One entry per turn: what was asked, what CreditProbe answered, what the
    #: independently computed reference was, and how they compared.
    turns: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Why the score was not 100, in plain language.
    deductions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: The reference answer, revealed to the user only after execution.
    reference: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    run: Mapped[AiValidationRun] = relationship(back_populates="cases")

    __table_args__ = (
        Index("ix_ai_validation_cases_run", "run_id", "position"),
    )
