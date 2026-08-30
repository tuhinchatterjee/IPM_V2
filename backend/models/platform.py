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
    text,
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
#
# Nine states, which are §44's nine. Two of the ids read differently from the
# brief's names — `submitted` is SENT and `withdrawn` is CANCELLED — and are
# deliberately NOT renamed: they are the state machine that projects, tests and
# every stored decision depend on, and rewriting them would edit history that
# exists precisely so it cannot be edited. The words people read are §44's.
WF_DRAFT = "draft"
WF_SUBMITTED = "submitted"
#: A recipient has opened it. An observation, recorded when it happens.
WF_OPENED = "opened"
WF_IN_REVIEW = "in_review"
#: Somebody has said something but has not yet decided.
WF_COMMENTED = "commented"
WF_APPROVED = "approved"
WF_REJECTED = "rejected"
#: The work asked for is done. Distinct from APPROVED, which is a judgement:
#: "assign action" and "FYI" are completed rather than approved.
WF_COMPLETED = "completed"
WF_WITHDRAWN = "withdrawn"
WF_OPEN_STATES = (WF_SUBMITTED, WF_OPENED, WF_IN_REVIEW, WF_COMMENTED)
WF_CLOSED_STATES = (WF_APPROVED, WF_REJECTED, WF_COMPLETED, WF_WITHDRAWN)

#: What is being ASKED FOR, as distinct from where the request has got to. §43.
WF_REVIEW = "review"
WF_COMMENT = "comment"
WF_APPROVE = "approve"
WF_REQUEST_CHANGES = "request_changes"
WF_FYI = "fyi"
WF_SIGN_OFF = "sign_off"
WF_ASSIGN_ACTION = "assign_action"
WF_ACTIONS = (
    WF_REVIEW, WF_COMMENT, WF_APPROVE, WF_REQUEST_CHANGES,
    WF_FYI, WF_SIGN_OFF, WF_ASSIGN_ACTION,
)

WF_PRIORITIES = ("low", "normal", "high", "urgent")

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
    #: The object AS IT WAS when it was sent, where the object is versioned.
    #: A decision recorded against version 3 must not silently become a
    #: decision about version 7.
    object_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    #: One of the nine WF_* states.
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    #: What is being asked for: review, comment, approve, sign off, FYI…
    #: Distinct from `state`, which is where the asking has got to.
    action: Mapped[str] = mapped_column(
        String(24), nullable=False, default=WF_REVIEW, server_default=WF_REVIEW
    )
    #: What the sender said when they sent it.
    message: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    priority: Mapped[str] = mapped_column(
        String(12), nullable=False, default="normal", server_default="normal"
    )
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    #: The FIRST recipient, kept so every caller written before multi-recipient
    #: still works and so "my work" has an index to use. The full set is in
    #: `recipients`; this is a denormalised head of it, never the truth on its
    #: own.
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    recipients: Mapped[list[WorkflowRecipient]] = relationship(
        back_populates="item", cascade="all, delete-orphan",
    )
    thread: Mapped[list[WorkflowMessage]] = relationship(
        back_populates="item", cascade="all, delete-orphan",
        order_by="WorkflowMessage.created_at",
    )

    __table_args__ = (Index("ix_workflow_object", "object_type", "object_id"),)


class WorkflowRecipient(Base):
    """One person or team a workflow item was sent to.

    A join table rather than a second nullable column on the item, because
    "three people and a team" is a set, and a set modelled as columns is how a
    schema ends up with `assigned_to_2`.

    `opened_at` is what makes §44's OPENED status an observation rather than a
    guess: the item has been opened when somebody it was sent to has opened it.
    """

    __tablename__ = "workflow_recipients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workflow_item_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_items.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    item: Mapped[WorkflowItem] = relationship(back_populates="recipients")

    __table_args__ = (
        UniqueConstraint("workflow_item_id", "user_id", "team_id",
                         name="uq_workflow_recipient"),
        Index("ix_workflow_recipients_user", "user_id"),
    )


class WorkflowMessage(Base):
    """One message in the conversation about a workflow item. §45.

    Internal only, on purpose: the brief says not to build external email, and
    what the product owes a user is that work addressed to them is visible the
    moment they open CreditProbe.

    `mentions` and `attachments` are documents rather than columns because both
    are written and read whole, belong to exactly one message, and are never
    queried across threads.
    """

    __tablename__ = "workflow_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workflow_item_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_items.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_messages.id", ondelete="CASCADE"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    #: `[{"user_id": 4}, {"team_id": 2}]` — who was named in the body.
    mentions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: `[{"type": "investigation", "id": "12", "label": "Contracting"}]`
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    item: Mapped[WorkflowItem] = relationship(back_populates="thread")

    __table_args__ = (
        Index("ix_workflow_messages_item", "workflow_item_id", "created_at"),
    )


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

    #: Whether a PROJECT thread has been published to the global list.
    #:
    #: A thread started inside a project belongs to that project, and appearing
    #: in Work → Investigations as well is a decision somebody takes rather than
    #: a side effect of asking a question there. Without this the only route
    #: from a project thread to the global list was to move it OUT of the
    #: project, which removes the project's own record of what was explored.
    #:
    #: Meaningless for a standalone thread, which is already global; the
    #: listing treats a null project as global whatever this says.
    published_globally: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

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
        Index("ix_investigations_published", "published_globally", "updated_at"),
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


# ================================================================== exports


class ExportRecord(Base):
    """One attempt to download an analysis as a workbook.

    §41. Append-only, and written whether or not the export succeeded: a refused
    download and a failed one are both things somebody will later need to
    explain, and a log that only records successes cannot answer "who tried".

    The row is deliberately wide. An export leaves the product — it lands on a
    laptop, it gets forwarded, and six months later the question is not "did an
    export happen" but "exactly which figures, from which data version, did that
    file contain, and who was allowed to have it". Everything needed to answer
    that is a column or a key in `detail`, so answering it never requires
    regenerating the file.
    """

    __tablename__ = "export_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    #: results | calculation_pack
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: What was exported. Kept as (type, id) rather than a foreign key so a run
    #: that is later deleted does not take its own download history with it.
    object_type: Mapped[str] = mapped_column(String(48), nullable=False,
                                             default="analysis_run")
    object_id: Mapped[str] = mapped_column(String(120), nullable=False)
    run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trace_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="")

    #: allowed | denied | failed
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="allowed")
    #: The authorisation basis — role:ADMIN, analyst:owner, viewer:published.
    authorization: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    #: SHA-256 of the bytes that were sent. Two downloads of the same run at the
    #: same trace version differ only in their timestamp and their downloader,
    #: so a differing hash is a real question.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    datasets: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    redactions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: The generation manifest: sheet names, fingerprints, build SHA, counts.
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_export_records_object", "object_type", "object_id", "created_at"),
        Index("ix_export_records_user", "user_id", "created_at"),
        Index("ix_export_records_run", "run_id", "created_at"),
    )


# ================================================================== agentic
#
# The governed agentic layer. Twelve tables, and the shape of them says what
# the layer is: a *record* of coordination, not a place where credit figures
# are computed. Every number a Risk Case carries came out of an AnalysisRun and
# is referenced by its id — there is no column here holding an ECL figure an
# agent decided on.
#
# Why the definitions are mirrored into the database at all, when
# backend/agentic/registry.py is the source: an administrator needs versions,
# evaluation scores, last-validation dates and history, and none of those
# belong in a Python file. The seed writes the definition; everything mutable
# about it lives here.


class AgentDefinition(Base):
    """One specialist's job description, as the product currently runs it.

    Seeded from `backend.agentic.registry`, which stays the source of the
    permissions themselves. What lives here is the operational state around a
    definition: which version is deployed, what it last scored, when it was last
    validated, and whether an administrator has retired it.
    """

    __tablename__ = "agent_definitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(24), nullable=False, default="1.0")
    business_name: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: The whole §13 contract as it was seeded, so a run months later can be
    #: read against the definition that actually governed it.
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: active | draft | retired
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    autonomy_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model_role: Mapped[str] = mapped_column(String(24), nullable=False, default="router")
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    evaluation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_validation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    certification_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unreviewed")
    #: The registry hash this row was seeded from. A definition whose registry
    #: fingerprint has moved is one whose permissions changed under it.
    registry_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_definition"),
        Index("ix_agent_definitions_status", "status"),
    )


class AgentEvent(Base):
    """Something happened that CreditProbe may want to act on. §34.

    `idempotency_key` is the whole point of the table. A dataset publication
    that is retried, replayed or delivered twice must produce ONE agentic run
    and ONE set of Risk Cases; the unique index is what makes "no duplicate
    cases on replay" (§70) a property of the schema rather than of whichever
    code path happened to check first.
    """

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: DATASET_PUBLISHED, NEW_PERIOD_AVAILABLE, RISK_THRESHOLD_BREACHED…
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Natural key for the thing that happened: dataset+period, case id, user.
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    object_type: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    object_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    period: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: received | accepted | ignored | failed
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="received")
    #: Why an event was ignored, where it was.
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("kind", "idempotency_key", name="uq_agent_event_once"),
        Index("ix_agent_events_kind", "kind", "created_at"),
    )


class AgentRun(Base):
    """One agentic run, from trigger to answer. §19.

    Wide on purpose, for the same reason ExportRecord is: the question asked of
    a run six months later is never "did it happen" but "which officer, which
    specialists, over which data versions, under which budget, validated how,
    and who approved what". Everything needed to answer that is a column or a
    key in one of the JSONB documents.
    """

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: A stable public identifier, so a Trace deep-link survives a restore.
    run_key: Mapped[str] = mapped_column(String(48), nullable=False)

    #: user_question | scheduled_review | event | manual_review
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_object_type: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    trigger_object_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_events.id", ondelete="SET NULL"), nullable=True)

    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    period: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    prior_period: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    #: The governed service identity a proactive run acts as. §57: a scheduled
    #: review is not "nobody", it is a principal with its own permissions.
    service_identity: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True)
    #: The AnalysisRun this run's primary answer was recorded as, when there
    #: was one. Keeps the agentic layer attached to the Trace it produced.
    analysis_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    officer_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    officer_title: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    selection_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    complexity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    planned_task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orchestrator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    specialists: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    #: queued | understanding | scoping | selecting_data | coordinating |
    #: calculating | validating | interpreting | complete | needs_input | failed
    #: | cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED")
    #: Every stage this run has passed through, with timestamps. §7's structured
    #: stages are an audit record, not only a spinner caption.
    stage_history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: The task DAG as planned, so a run that was cancelled still shows what it
    #: intended to do.
    task_graph: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    budgets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Catalogue, method, relationship and registry versions this run ran under.
    versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    findings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    conflicts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    handoffs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    assurance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    synthesis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    failure: Mapped[str] = mapped_column(Text, nullable=False, default="")
    failure_kind: Mapped[str] = mapped_column(String(48), nullable=False, default="")

    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    build_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tasks: Mapped[list[AgentTask]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
        order_by="AgentTask.id")

    __table_args__ = (
        UniqueConstraint("run_key", name="uq_agent_run_key"),
        Index("ix_agent_runs_status", "status", "created_at"),
        Index("ix_agent_runs_user", "user_id", "created_at"),
        Index("ix_agent_runs_trigger", "trigger", "created_at"),
    )


class AgentTask(Base):
    """One delegated task in a run's DAG. §16.

    `depends_on` holds task keys rather than row ids so a plan can be written
    before any of it is persisted — the DAG is decided in one place and saved in
    one transaction, rather than being assembled by a sequence of inserts each
    of which has to know the ids of the last.
    """

    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    #: Stable within a run: "t1", "validate", "screen".
    task_key: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Task keys that must complete first.
    depends_on: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Which parallel layer this task sits in. Computed from the DAG, stored so
    #: the Trace can draw it without recomputing a topological sort.
    layer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    tool: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Everything the task read, by reference: result ids, dataset versions.
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    data_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: pending | ready | running | complete | failed | skipped | cancelled |
    #: blocked | needs_approval
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    #: The AnalysisRun a calculating task produced, so every agentic figure has
    #: a Trace of its own.
    analysis_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    finding: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: passed | failed | not_required, with the checks underneath.
    validation_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_required")
    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tool_calls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_category: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: not_required | pending | approved | rejected
    approval_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_required")

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    run: Mapped[AgentRun] = relationship(back_populates="tasks")

    __table_args__ = (
        UniqueConstraint("run_id", "task_key", name="uq_agent_task_key"),
        Index("ix_agent_tasks_run", "run_id", "status"),
    )


class AgentJob(Base):
    """A durable unit of background work, and the lease on it. §17.

    This is the queue. A worker claims a row with SELECT … FOR UPDATE SKIP
    LOCKED, writes its own id and a lease expiry, and heartbeats while it works.
    A worker that dies leaves a lease that expires; the next sweep returns the
    job to `queued` and the work resumes rather than disappearing.

    `idempotency_key` is unique among live jobs, so enqueuing the same review
    twice produces one job — the second enqueue finds the first.
    """

    __tablename__ = "agent_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: agentic_run | proactive_review | schedule_tick
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True)

    #: queued | running | complete | failed | dead_letter | cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    #: Higher runs first. A user waiting on an answer outranks a nightly sweep.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_category: Mapped[str] = mapped_column(String(48), nullable=False, default="")

    #: The worker holding the lease, and when it expires.
    leased_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    leased_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: Set by a cancellation request. The worker checks it and stops cleanly
    #: rather than being killed, so a partial run is still a recorded run.
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_jobs_claim", "status", "priority", "scheduled_at"),
        Index("ix_agent_jobs_lease", "status", "lease_expires_at"),
        Index("ix_agent_jobs_idem", "kind", "idempotency_key"),
        # One LIVE job per idempotency key. Partial rather than a plain unique
        # constraint because the same review legitimately runs again next
        # quarter; what must not happen is two of them queued at once.
        Index("uq_agent_jobs_live", "kind", "idempotency_key", unique=True,
              postgresql_where=text("status IN ('queued', 'running')")),
    )


class AgentWorker(Base):
    """A worker process and when it last said it was alive. §18.

    Read by the health endpoint and by the stale-lease sweep. A worker row is
    not authority over anything — the lease on the job is — but it is how an
    operator answers "is anything actually running".
    """

    __tablename__ = "agent_workers"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    #: starting | idle | working | draining | stopped
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="starting")
    current_job_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    jobs_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    build_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_agent_workers_heartbeat", "heartbeat_at"),)


class AgentApproval(Base):
    """A material action an agent proposed, waiting for a person. §22.

    The row exists BEFORE the action does. An approval record created after the
    fact is a receipt, not a gate — the whole point is that the action cannot
    happen until this row says approved, and the action itself is described
    here in enough detail that the approver is not being asked to trust a
    summary.
    """

    __tablename__ = "agent_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    #: send_workflow | close_case | publish_data | certify_method | …
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: What the action would do, exactly, in a form the approver can read.
    proposal: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objects_affected: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: low | medium | high
    risk: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    #: reversible | partially_reversible | irreversible
    reversibility: Mapped[str] = mapped_column(
        String(24), nullable=False, default="reversible")
    #: Which role may decide. A gate anybody can open is not a gate.
    approver_role: Mapped[str] = mapped_column(String(24), nullable=False, default="ADMIN")

    #: pending | approved | rejected | changes_requested | expired
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_agent_approvals_status", "status", "created_at"),
        Index("ix_agent_approvals_run", "run_id"),
    )


class AgentSchedule(Base):
    """A governed schedule: when CreditProbe reviews something on its own. §31."""

    __tablename__ = "agent_schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: on_dataset_published | monthly | quarterly | daily | weekly | manual
    trigger: Mapped[str] = mapped_column(String(48), nullable=False)
    #: portfolio | segment | watchlist | unresolved_cases
    scope: Mapped[str] = mapped_column(String(48), nullable=False, default="portfolio")
    scope_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    agents: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    methods: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Which domains must be published before this schedule may run.
    data_requirement: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    approval_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft_only")
    notify: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    budget: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"))

    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("name", name="uq_agent_schedule_name"),)


class AgentPolicy(Base):
    """The rules agents run under, versioned. §32.

    Versioned by row rather than by update: a policy change is evidence, and a
    run months ago has to be readable against the policy that governed it. Only
    one version of a policy key is `active` at a time.
    """

    __tablename__ = "agent_policies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_agent_policy_version"),
        Index("ix_agent_policies_active", "key", "active"),
    )


class RiskCase(Base):
    """Something in the book that requires attention. §37.

    A Risk Case is NOT an Investigation (§1). An Investigation is a
    conversation somebody is having; a Risk Case is a finding with a lifecycle,
    an owner and a due date, which may CAUSE an Investigation.

    Every figure on a case is a reference. `metrics` holds the numbers with the
    analysis run each came from, `analyses` holds the run ids, and `severity` is
    computed by a versioned formula — never by a model (§39).
    """

    __tablename__ = "risk_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_key: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    #: BORROWER | SEGMENT | PORTFOLIO | DATA_QUALITY
    level: Mapped[str] = mapped_column(String(24), nullable=False)
    #: What the case is about: a borrower name, a sector, the portfolio, a
    #: dataset. Kept as a label plus an id rather than a foreign key because the
    #: four levels point at four different kinds of thing.
    entity: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    #: sector | region | product | rating_band | portfolio_segment | business_unit
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    prior_period: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    #: critical | high | medium | low
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    severity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: The components the score was built from, and the formula version. §39
    #: requires this to be transparent; a score with no arithmetic behind it is
    #: exactly what the LLM is not allowed to produce.
    severity_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    severity_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: How much of the evidence a full case would carry is actually present.
    evidence_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    exposure: Mapped[float | None] = mapped_column(Float, nullable=True)
    exposure_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    metrics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    signals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: The one sentence a reader gets first.
    conclusion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    why: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: AnalysisRun ids behind the case.
    analyses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    source_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_events.id", ondelete="SET NULL"), nullable=True)
    agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    #: NEW | TRIAGED | UNDER_REVIEW | UNDER_INVESTIGATION | ACTION_PENDING |
    #: MONITORING | RESOLVED | DISMISSED | SNOOZED
    status: Mapped[str] = mapped_column(String(28), nullable=False, default="NEW")
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    snooze_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    dismiss_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolution: Mapped[str] = mapped_column(Text, nullable=False, default="")

    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    workflow_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_items.id", ondelete="SET NULL"), nullable=True)

    #: The natural key that makes a replayed review update this case rather
    #: than create a second one. §70: "no duplicate cases on replay".
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    events: Mapped[list[RiskCaseEvent]] = relationship(
        back_populates="case", cascade="all, delete-orphan",
        order_by="RiskCaseEvent.created_at")
    links: Mapped[list[RiskCaseLink]] = relationship(
        back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("case_key", name="uq_risk_case_key"),
        UniqueConstraint("dedupe_key", name="uq_risk_case_dedupe"),
        Index("ix_risk_cases_open", "status", "severity_score"),
        Index("ix_risk_cases_level", "level", "period"),
        Index("ix_risk_cases_owner", "owner_id", "status"),
    )


class RiskCaseLink(Base):
    """Something attached to a case: an analysis, an investigation, a project,
    a workflow item, another case.

    A join table rather than more columns on the case, because §49 says not to
    duplicate data: the case points at objects that live where they live.
    """

    __tablename__ = "risk_case_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("risk_cases.id", ondelete="CASCADE"), nullable=False)
    #: analysis | investigation | project | workflow | case | dataset
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="evidence")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    case: Mapped[RiskCase] = relationship(back_populates="links")

    __table_args__ = (
        UniqueConstraint("case_id", "object_type", "object_id",
                         name="uq_risk_case_link"),
        Index("ix_risk_case_links_object", "object_type", "object_id"),
    )


class RiskCaseEvent(Base):
    """One thing that happened to a case: a status change, a comment, an
    assignment, a snooze. Append-only — a case's history is evidence.

    Comments and status changes share a table because on a case they are the
    same thing: a timeline. Splitting them produces two lists a reader has to
    interleave in their head to understand what happened.
    """

    __tablename__ = "risk_case_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("risk_cases.id", ondelete="CASCADE"), nullable=False)
    #: created | status | assigned | comment | snoozed | dismissed | resolved |
    #: linked | workflow | refreshed
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    from_status: Mapped[str] = mapped_column(String(28), nullable=False, default="")
    to_status: Mapped[str] = mapped_column(String(28), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    #: Set when the actor was an agent rather than a person.
    actor_agent: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    case: Mapped[RiskCase] = relationship(back_populates="events")

    __table_args__ = (Index("ix_risk_case_events_case", "case_id", "created_at"),)


# ===========================================================================
# The Intelligence Review Queue — P0.15
# ===========================================================================


class ReviewQueueItem(Base):
    """A failure somebody reviewed, and what the right answer would have been.

    P0.15's active learning. Not a bug tracker: a bug report says what went
    wrong, and this says what CreditProbe should have DONE instead, in the
    same shape the curriculum specifies a case — which is what makes an
    approved item something the factory can measure against rather than
    something a person has to read and reinterpret.

    Two rules are load-bearing and both are about the human in the middle.

    **Nothing enters the curriculum without adjudication.** An item is captured
    automatically and promoted only by a person who wrote down the corrected
    reading. A queue that promotes its own contents is a product learning from
    its own mistakes, which is how a wrong answer becomes the standard.

    **No automatic production self-training.** Nothing here is fed back into a
    model, and no weight anywhere changes because of a row in this table.
    Approved items become CASES — specifications the product is evaluated
    against, in a corpus a person can read.
    """

    __tablename__ = "review_queue_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # ---- what happened -----------------------------------------------------
    #: The question exactly as it was asked. Never paraphrased on the way in:
    #: the phrasing is frequently the defect.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    #: How CreditProbe read it — the structured reading, as JSON.
    current_reading: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                  default=dict)
    #: The plan it built and the result it produced. What was actually shown.
    observed_plan: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                default=dict)
    observed_result: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                  default=dict)
    #: Which of the sixteen evaluation layers this failed at, and which of the
    #: ten failure categories it belongs to. Both named rather than free text,
    #: so the queue can be counted.
    failure_layer: Mapped[str] = mapped_column(String(48), nullable=False,
                                               default="")
    failure_category: Mapped[str] = mapped_column(String(32), nullable=False,
                                                  default="")
    #: What a reviewer saw. The words a person used, kept as they wrote them.
    observed_problem: Mapped[str] = mapped_column(Text, nullable=False,
                                                  default="")

    # ---- what it should have been ------------------------------------------
    #: The corrected structured reading, in the shape a Reading carries.
    corrected_reading: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                    default=dict)
    #: What a correct answer must DO — capability, concepts, datasets,
    #: invariants, forbidden behaviours. A specification, never an answer: a
    #: stored figure is one somebody quietly aligns to whatever the product
    #: returns.
    corrected_expectations: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                         default=dict)

    # ---- the human in the middle -------------------------------------------
    #: CAPTURED | UNDER_REVIEW | APPROVED | REJECTED | DUPLICATE
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default="CAPTURED")
    adjudicated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    adjudicated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: Why the reviewer decided what they decided. Required to approve: an
    #: approval with no reasoning is a click, and the curriculum inherits it.
    adjudication_note: Mapped[str] = mapped_column(Text, nullable=False,
                                                   default="")

    # ---- what happened after -----------------------------------------------
    #: NOT_TESTED | FAILING | PASSING | RETIRED. Whether the product now does
    #: what the corrected expectations say. An approved item that has never
    #: been run is NOT_TESTED, which is not the same as passing.
    regression_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                                   default="NOT_TESTED")
    regression_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: The curriculum case id this became, once approved.
    curriculum_case_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                    default="")

    # ---- §33's fuller capture ----------------------------------------------
    #: What the user said was wrong, in their words. Kept apart from
    #: `observed_problem`, which is what a reviewer wrote: a user saying "these
    #: aren't the right customers" and a reviewer writing "the population was
    #: not narrowed to the carried cohort" are different evidence, and merging
    #: them loses the half that is not an interpretation.
    user_correction: Mapped[str] = mapped_column(Text, nullable=False,
                                                 default="")
    #: The teaching cases retrieved for the failing run. Ids only. §33 asks
    #: for them because "the planner was shown three examples of the wrong
    #: family" is a fix and "the plan was wrong" is not.
    retrieved_case_ids: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                     default=list)
    #: Which invariants ran and what they said.
    observed_invariants: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                      default=dict)
    #: The prose that was shown. Recorded because a grounding failure is only
    #: visible in the sentence that made the claim.
    observed_interpretation: Mapped[str] = mapped_column(Text, nullable=False,
                                                         default="")
    #: The Teaching Release the failing run was served by, and the release the
    #: approved correction went into. §33's "release inclusion": a correction
    #: that has been approved and not released has not fixed anything yet.
    observed_release_id: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     default="")
    included_in_release: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     default="")
    #: The teaching case an approved correction became.
    teaching_case_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                  default="")

    #: Where it came from: cockpit | agentic | evaluation | manual | feedback.
    source: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default="manual")
    #: The run this was captured from, so the Trace can be reopened.
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        Index("ix_review_queue_status", "status", "created_at"),
        Index("ix_review_queue_layer", "failure_layer"),
        Index("ix_review_queue_regression", "regression_status"),
    )


class TeachingCase(Base):
    """A governed teaching case. §4.

    Why the schema is here twice
    ----------------------------
    `backend/teaching/schema.py` is the contract: seventy-two fields, the
    validation rules, the fingerprint. This is storage, and it carries a
    deliberate subset as real columns — the ones retrieval filters on, the ones
    the Studio lists by, and the ones §13 counts by family. Everything else
    lives in ``body``, which is the case's own ``to_dict()``.

    The alternative was seventy-two columns. That reads as thorough and behaves
    badly: every schema change becomes a migration, most of the columns are
    never filtered on, and the JSONB half would exist anyway for the contracts.
    The split is chosen so a query the product actually runs — "approved
    ECL_CHANGE_DECOMPOSITION cases, not stale, in this cluster" — is an index
    scan and not a JSONB traversal.

    Versions are rows, not updates
    ------------------------------
    ``(case_id, case_version)`` is unique. Editing an approved case writes a
    new version rather than overwriting the reviewed one, because a retrieval
    that happened last week must stay explicable: an approved case whose
    content can change underneath its approval is an approval that means
    nothing.
    """

    __tablename__ = "teaching_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # ---- identity ----------------------------------------------------------
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False,
                                              default=1)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    family_id: Mapped[str] = mapped_column(String(48), nullable=False,
                                           default="")
    subfamily: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False,
                                          default="en")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    #: CORPORATE | RETAIL | NONE
    portfolio_scope: Mapped[str] = mapped_column(String(16), nullable=False,
                                                 default="NONE")
    industry_or_product_scope: Mapped[str] = mapped_column(
        String(96), nullable=False, default="")
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False,
                                            default="INTERMEDIATE")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False,
                                            default="MEDIUM")

    # ---- what was asked ----------------------------------------------------
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Counted rather than derived from ``body`` so §13's "at least 100 must be
    #: multi-turn" is a query and not a scan.
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ---- what should happen ------------------------------------------------
    expected_capability: Mapped[str] = mapped_column(String(48),
                                                     nullable=False,
                                                     default="")
    expected_conversation_action: Mapped[str] = mapped_column(
        String(48), nullable=False, default="")
    #: EXECUTE | CLARIFY | UNSUPPORTED | FAIL
    expected_outcome: Mapped[str] = mapped_column(String(16), nullable=False,
                                                  default="EXECUTE")
    expected_officer_level: Mapped[int] = mapped_column(Integer,
                                                        nullable=False,
                                                        default=0)
    #: A model ROLE — never a provider model ID (§23).
    expected_model_route: Mapped[str] = mapped_column(String(24),
                                                      nullable=False,
                                                      default="")
    expected_effort: Mapped[str] = mapped_column(String(16), nullable=False,
                                                 default="")
    grain: Mapped[str] = mapped_column(String(48), nullable=False, default="")

    # ---- filterable content ------------------------------------------------
    #: Denormalised out of ``body`` for retrieval. The full lists stay in the
    #: body; these are what a candidate query filters on.
    concepts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    required_datasets: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                    default=list)
    operations: Mapped[list] = mapped_column(JSONB, nullable=False,
                                             default=list)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # ---- the whole case ----------------------------------------------------
    #: ``TeachingCase.to_dict()``. The contracts, the turns, the discourse, the
    #: objectives — everything the columns above do not carry.
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ---- governance --------------------------------------------------------
    #: DRAFT | AUTO_VALIDATED | SME_REVIEW_REQUIRED | APPROVED | REJECTED |
    #: RETIRED | STALE | SYSTEM_VALIDATED
    review_status: Mapped[str] = mapped_column(String(24), nullable=False,
                                               default="DRAFT")
    authoring_method: Mapped[str] = mapped_column(String(32), nullable=False,
                                                  default="HUMAN")
    #: STRUCTURE_ONLY | DIAGNOSTIC | CLIENT
    data_sensitivity: Mapped[str] = mapped_column(String(24), nullable=False,
                                                  default="STRUCTURE_ONLY")
    source_provenance: Mapped[str] = mapped_column(Text, nullable=False,
                                                   default="")
    #: For SYSTEM_VALIDATED cases: which §6 source it was derived from.
    system_source: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="")
    reviewer: Mapped[str] = mapped_column(String(120), nullable=False,
                                          default="")
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    # ---- the staleness axes (§5) -------------------------------------------
    ontology_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                  default="")
    method_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                default="")
    relationship_version: Mapped[str] = mapped_column(String(24),
                                                      nullable=False,
                                                      default="")
    dataset_contract_version: Mapped[str] = mapped_column(String(24),
                                                          nullable=False,
                                                          default="")
    planner_schema_version: Mapped[str] = mapped_column(String(24),
                                                        nullable=False,
                                                        default="")
    prompt_schema_version: Mapped[str] = mapped_column(String(24),
                                                       nullable=False,
                                                       default="")
    model_family: Mapped[str] = mapped_column(String(48), nullable=False,
                                              default="")
    prompt_compatibility: Mapped[str] = mapped_column(String(48),
                                                      nullable=False,
                                                      default="")
    family_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                default="")
    #: Why it went STALE, as a comma-joined list of axes. Written when the
    #: status changes so the reason survives the revalidation that clears it.
    stale_axes: Mapped[str] = mapped_column(String(240), nullable=False,
                                            default="")

    # ---- identity of content -----------------------------------------------
    #: What the case teaches, hashed. Two cases with one fingerprint are
    #: duplicates however differently they are worded.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    #: §15's paraphrase cluster. Variants share one, and an evaluation split
    #: cuts on this rather than on individual questions.
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")

    cost_budget: Mapped[float] = mapped_column(Float, nullable=False,
                                               default=0.0)
    latency_budget: Mapped[float] = mapped_column(Float, nullable=False,
                                                  default=0.0)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("case_id", "case_version",
                         name="uq_teaching_case_version"),
        Index("ix_teaching_case_family", "family_id", "review_status"),
        Index("ix_teaching_case_status", "review_status", "difficulty"),
        Index("ix_teaching_case_fingerprint", "fingerprint"),
        Index("ix_teaching_case_cluster", "cluster_id"),
        Index("ix_teaching_case_scope", "portfolio_scope", "language"),
    )


class TeachingCaseEvent(Base):
    """Every status change a teaching case went through, and who made it.

    A review workflow with no audit trail is a workflow that cannot answer the
    only question anyone asks of it afterwards: who approved this, when, and
    what did they say. Kept as its own table rather than a JSONB column on the
    case so an approval survives the case being superseded by a new version.
    """

    __tablename__ = "teaching_case_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False,
                                              default=1)
    from_status: Mapped[str] = mapped_column(String(24), nullable=False,
                                             default="")
    to_status: Mapped[str] = mapped_column(String(24), nullable=False,
                                           default="")
    #: The person, by name as recorded at the time. A user row can be renamed
    #: or removed; what an audit trail says must not change when it is.
    actor: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: Why. Required for an approval or a rejection.
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Whatever the transition needs recorded: the validation problems, the
    #: staleness axes, the source a system validation rested on.
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                         server_default=func.now())

    __table_args__ = (
        Index("ix_teaching_event_case", "case_id", "case_version", "at"),
        Index("ix_teaching_event_status", "to_status", "at"),
    )


class AssuranceRecord(Base):
    """§180's Investigation Assurance Record, as stored. Part F.

    One row per answered turn. §208 makes this table append-only in
    practice: a record is historical evidence tied to the build, data,
    models and releases that produced it, and "do not rewrite historical
    scores" means the columns below are written once and read forever.
    Staleness is therefore not a column that gets updated — it is computed
    against the CURRENT runtime at read time, so the record keeps saying
    what was true when it was made while the reader still learns that the
    world has moved on.

    The verdict is stored alongside the checks rather than only derived,
    because the weights and gates that produced it are themselves
    versioned: recomputing an old record under today's policy would
    silently restate history, which is the thing §208 forbids.
    """

    __tablename__ = "assurance_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: The stable public identifier used in URLs and exports.
    assurance_record_id: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     unique=True)
    record_version: Mapped[str] = mapped_column(String(16), nullable=False,
                                                default="1.0.0")

    # ---- what was answered -------------------------------------------------
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    investigation_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                  default="")
    project_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    message_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    answer_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    agentic_run_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                default="")
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_type: Mapped[str] = mapped_column(String(32), nullable=False,
                                             default="")
    portfolio_scope: Mapped[str] = mapped_column(String(64), nullable=False,
                                                 default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False,
                                          default="en")
    #: Position in the thread, so a timeline orders by something better than
    #: a timestamp two turns can share.
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False,
                                            default=0)

    # ---- under what ---------------------------------------------------------
    build_sha: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    app_version: Mapped[str] = mapped_column(String(32), nullable=False,
                                             default="")
    intelligence_release_id: Mapped[str] = mapped_column(String(64),
                                                         nullable=False,
                                                         default="")
    teaching_release_id: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     default="")
    ontology_version: Mapped[str] = mapped_column(String(32), nullable=False,
                                                  default="")
    routing_policy_version: Mapped[str] = mapped_column(String(32),
                                                        nullable=False,
                                                        default="")
    officer_level: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0)
    model_route: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    blueprint_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                              default="")
    case_family: Mapped[str] = mapped_column(String(48), nullable=False,
                                             default="")

    # ---- the verdict, as computed at the time -------------------------------
    overall_status: Mapped[str] = mapped_column(String(32), nullable=False,
                                                default="")
    #: §184. NULL where the gates refused a number — which is most of the
    #: interesting cases, and is why this is nullable rather than 0.
    operational_assurance: Mapped[float | None] = mapped_column(Float,
                                                                nullable=True)
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False,
                                                default=0.0)
    #: Kept in its own column, never merged with the one above.
    reference_match_pct: Mapped[float | None] = mapped_column(Float,
                                                              nullable=True)
    reference_source: Mapped[str] = mapped_column(String(120), nullable=False,
                                                  default="")
    critical_failure_count: Mapped[int] = mapped_column(Integer,
                                                        nullable=False,
                                                        default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0)
    weights_version: Mapped[str] = mapped_column(String(16), nullable=False,
                                                 default="")

    # ---- the evidence -------------------------------------------------------
    #: Every check, as recorded. The drill-down reads from here.
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Per-dimension roll-up as computed at the time, so §203's contribution
    #: view does not have to re-derive history.
    dimension_results: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                    default=dict)
    objective_coverage: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                     default=dict)
    limitations: Mapped[list] = mapped_column(JSONB, nullable=False,
                                              default=list)
    #: The rest of §180's fields that do not each deserve a column: served
    #: models, method and relationship versions, data versions, result
    #: fingerprints, retrieved teaching case ids, agent roles, run ids.
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    repair_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                              default=0)
    clarification_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                                     default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False,
                                             default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False,
                                            default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False,
                                            default=0.0)
    #: §182's tamper check. Recomputed on read; a mismatch is reported rather
    #: than repaired, because a record that silently heals is not evidence.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")

    # ---- what happened afterwards ------------------------------------------
    #: §199. Raw counts only. This never feeds the score — the column exists
    #: so a reviewer can see that people disagreed with an answer the gates
    #: were happy with, which is a reason to look rather than a reason to
    #: change a number.
    good_feedback_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                                     default=0)
    bad_feedback_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                                    default=0)
    #: Set when this turn was re-run after a fix, pointing at the newer
    #: record. §200 compares the two; neither one is edited.
    superseded_by: Mapped[str] = mapped_column(String(64), nullable=False,
                                               default="")
    rerun_of: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    __table_args__ = (
        Index("ix_assurance_investigation", "investigation_id", "turn_index"),
        Index("ix_assurance_recent", "created_at"),
        Index("ix_assurance_status", "overall_status", "created_at"),
        Index("ix_assurance_user", "user_id", "created_at"),
        Index("ix_assurance_project", "project_id", "created_at"),
        Index("ix_assurance_release", "intelligence_release_id",
              "created_at"),
        Index("ix_assurance_answer", "answer_id"),
    )


class RegulatoryDocument(Base):
    """A circular, its metadata and everything read out of it. Part G.

    Same split as `TeachingCase`, for the same reason. The columns are what
    retrieval filters on — regulator, reference, the effective window, status,
    confidentiality, tenant — and the pages, sections and extraction detail
    live in ``body``, which is the document's own ``to_dict()``. The ORIGINAL
    is not here at all: it is on disk under its hash, because a rulebook is
    tens of megabytes, is read whole or not at all, and would bloat every
    backup to no purpose.

    ``content_hash`` is the anchor. It is unique per tenant, so a bulk upload
    that includes the same circular twice ends with one document and not two,
    and every citation resolves through it: a reader who wants to check a
    quoted obligation can be handed the bytes it was taken from and can prove
    they are the bytes that were uploaded.

    Nothing here is approved by being written. A row arrives UPLOADED, becomes
    EXTRACTED, and reaches APPROVED only through a named SME and an activated
    Regulatory Knowledge Release.
    """

    __tablename__ = "regulatory_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    circular_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # ---- what the regulator called it --------------------------------------
    title: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    regulator: Mapped[str] = mapped_column(String(120), nullable=False,
                                           default="")
    reference: Mapped[str] = mapped_column(String(120), nullable=False,
                                           default="")
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False,
                                              default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False,
                                          default="en")

    # ---- when it applies ---------------------------------------------------
    #: Dates as ISO strings rather than DATE columns. The window is compared
    #: as a whole and never arithmetic'd, ISO strings sort correctly, and a
    #: circular with no effective date has to be storable so it can be
    #: reported as unusable rather than rejected at the door.
    issued_on: Mapped[str] = mapped_column(String(10), nullable=False,
                                           default="")
    effective_on: Mapped[str] = mapped_column(String(10), nullable=False,
                                              default="")
    expires_on: Mapped[str] = mapped_column(String(10), nullable=False,
                                            default="")

    # ---- the original ------------------------------------------------------
    file_format: Mapped[str] = mapped_column(String(8), nullable=False,
                                             default="")
    filename: Mapped[str] = mapped_column(String(240), nullable=False,
                                          default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False,
                                              default="")
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                           default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ---- governance --------------------------------------------------------
    status: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="UPLOADED")
    confidentiality: Mapped[str] = mapped_column(String(16), nullable=False,
                                                 default="RESTRICTED")
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    supersedes: Mapped[list] = mapped_column(JSONB, nullable=False,
                                             default=list)
    superseded_by: Mapped[str] = mapped_column(String(120), nullable=False,
                                               default="")

    #: The whole document contract: pages, sections, rules, extraction notes.
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: What extraction did, kept beside the document so a re-extraction after
    #: a library upgrade can be told apart from the first attempt.
    extraction: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                             default=dict)

    rule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved_rule_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                                     default=0)

    uploaded_by: Mapped[str] = mapped_column(String(120), nullable=False,
                                             default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False,
                                                default="1.0.0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant", "content_hash",
                         name="uq_regulatory_tenant_hash"),
        UniqueConstraint("circular_id", name="uq_regulatory_circular_id"),
        Index("ix_regulatory_reference", "regulator", "reference"),
        Index("ix_regulatory_effective", "effective_on", "expires_on"),
        Index("ix_regulatory_status", "status", "tenant"),
        Index("ix_regulatory_tenant", "tenant", "created_at"),
    )


class RegulatoryRelease(Base):
    """A frozen set of approved regulatory knowledge. Part G.

    Production uses ONE active release per tenant. An answer records which,
    so "what regulatory knowledge was this based on?" has an answer that is
    still true next quarter — rather than "whatever had been approved by the
    time it ran", which is not one.

    Rollback is activating the previous release. Nothing is deleted, so a
    rollback is a normal operation and not a recovery.
    """

    __tablename__ = "regulatory_releases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="DRAFT")

    #: circular_id -> approved rule ids, and the hash each was frozen against.
    contents: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    circular_hashes: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                  default=dict)
    circular_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                                default=0)
    rule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    reviewers: Mapped[list] = mapped_column(JSONB, nullable=False,
                                            default=list)
    approver: Mapped[str] = mapped_column(String(120), nullable=False,
                                          default="")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False,
                                            default="")
    #: What this release IS, independent of who made it or when — so a
    #: rollback is recognisable as a return to a known state.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    replaces: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("release_id", name="uq_regulatory_release_id"),
        Index("ix_regulatory_release_active", "tenant", "status",
              "activated_at"),
    )


class FeedbackEventRow(Base):
    """§10's immutable feedback event.

    Append-only by construction rather than by trigger: there is no update
    path in the service, and a revision is a NEW row carrying `supersedes`.
    §10 is explicit — "a subsequent edit creates a new version/event; do not
    overwrite historical feedback" — because a user who changes their mind has
    said two things and which came first is part of what they said.

    The columns are what the Inbox filters and the metrics group by. The
    twenty-four links live in ``body``, which is the event's own ``to_dict()``,
    for the same reason the teaching library splits: a query the product
    actually runs is an index scan, and the rest would be seventy columns
    nothing filters on.
    """

    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=1)
    supersedes: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")

    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                         default="")
    project_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    investigation_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                  default="")
    message_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    answer_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    assurance_record_id: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     default="")
    agentic_run_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                default="")
    plan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                                  default="")
    build_sha: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")

    #: YES | PARTLY | NO | NOT_SURE | SKIP
    rating: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="SKIP")
    categories: Mapped[list] = mapped_column(JSONB, nullable=False,
                                             default=list)
    surface: Mapped[str] = mapped_column(String(24), nullable=False,
                                         default="COCKPIT")
    consent: Mapped[str] = mapped_column(String(16), nullable=False,
                                         default="UNSET")
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reproducible: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                               default=False)

    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False,
                                                default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_feedback_event_id"),
        Index("ix_feedback_answer", "answer_id"),
        Index("ix_feedback_tenant", "tenant", "created_at"),
        Index("ix_feedback_rating", "rating", "created_at"),
        Index("ix_feedback_investigation", "investigation_id", "created_at"),
        Index("ix_feedback_project", "project_id", "created_at"),
        Index("ix_feedback_user", "user_id", "created_at"),
    )


class LearningObservationRow(Base):
    """§12's observation: one row per question, whether or not anybody rated it.

    A corpus of complaints is a biased sample of the answers that were wrong.
    Recording every question is what makes "how often does this go wrong?" a
    different question from "how often does somebody say so?".

    `label` is UNLABELED until a feedback event arrives. It is explicitly not
    "satisfied": §12 says "do not assume no feedback means satisfaction", and
    the response rate on a feedback prompt is low enough everywhere that
    reading silence as approval would mean concluding most answers were good
    on the evidence of nothing.
    """

    __tablename__ = "learning_observations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                         default="")
    project_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    investigation_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                  default="")
    message_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    answer_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False,
                                            default=0)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")

    officer_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False,
                                         default="")
    plan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                                  default="")
    build_sha: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False,
                                            default=0)

    #: UNLABELED | LABELED | DECLINED
    label: Mapped[str] = mapped_column(String(16), nullable=False,
                                       default="UNLABELED")
    rating: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="")
    feedback_event_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                   default="")

    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False,
                                                default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    __table_args__ = (
        UniqueConstraint("observation_id", name="uq_observation_id"),
        Index("ix_observation_answer", "answer_id"),
        Index("ix_observation_tenant", "tenant", "created_at"),
        Index("ix_observation_label", "label", "created_at"),
        Index("ix_observation_fingerprint", "fingerprint"),
    )


class CandidateLearningCase(Base):
    """§15's candidate, and the nine statuses it moves through.

    `user_correction` and the `proposed_*` fields inside ``body`` are kept
    apart on purpose: §8 says "do not treat a user correction as automatically
    correct", and the separation is what makes that enforceable rather than
    hoped for. Nothing copies the first into the second without a reviewer.
    """

    __tablename__ = "candidate_learning_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="DRAFT")
    failure_class: Mapped[str] = mapped_column(String(24), nullable=False,
                                               default="unclassified")

    feedback_event_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                   default="")
    observation_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                default="")
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")

    reviewer: Mapped[str] = mapped_column(String(120), nullable=False,
                                          default="")
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rejected_because: Mapped[str] = mapped_column(Text, nullable=False,
                                                  default="")
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=False)
    release_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")

    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False,
                                                default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_candidate_id"),
        Index("ix_candidate_status", "status", "tenant"),
        Index("ix_candidate_class", "failure_class", "created_at"),
        Index("ix_candidate_feedback", "feedback_event_id"),
    )


class LearningReviewDecision(Base):
    """One reviewer action on one candidate, kept forever.

    Separate from the candidate's own status because the status is where a
    case IS and this is how it got there. A case that went NEEDS_REVIEW →
    REJECTED → NEEDS_REVIEW → HUMAN_APPROVED has a history worth reading, and
    a single `reviewer` column on the case would show only the last person to
    touch it.
    """

    __tablename__ = "learning_review_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    action: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="")
    from_status: Mapped[str] = mapped_column(String(32), nullable=False,
                                             default="")
    to_status: Mapped[str] = mapped_column(String(32), nullable=False,
                                           default="")
    reviewer: Mapped[str] = mapped_column(String(120), nullable=False,
                                          default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_review_decision_id"),
        Index("ix_review_decision_candidate", "candidate_id", "created_at"),
        Index("ix_review_decision_reviewer", "reviewer", "created_at"),
    )


class LearningReleaseRow(Base):
    """§24's frozen manifest, and the one active release production uses."""

    __tablename__ = "learning_releases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="DRAFT")

    teaching_release_id: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     default="")
    regulatory_release_id: Mapped[str] = mapped_column(String(64),
                                                       nullable=False,
                                                       default="")
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                                 default=0)
    reviewers: Mapped[list] = mapped_column(JSONB, nullable=False,
                                            default=list)
    approver: Mapped[str] = mapped_column(String(120), nullable=False,
                                          default="")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False,
                                            default="")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    replaces: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    build_sha: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("release_id", name="uq_learning_release_id"),
        Index("ix_learning_release_active", "tenant", "status",
              "activated_at"),
    )


class LearningReleaseActivation(Base):
    """Every activation and every rollback, in order.

    §24 asks for rollback support, and rollback is only trustworthy if the
    sequence of activations is a record rather than a reconstruction. This is
    the record: who activated what, when, over what, and why a rollback
    happened.
    """

    __tablename__ = "learning_release_activations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    activation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    release_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    #: ACTIVATED | ROLLED_BACK
    action: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="ACTIVATED")
    replaces: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    approver: Mapped[str] = mapped_column(String(120), nullable=False,
                                          default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    __table_args__ = (
        UniqueConstraint("activation_id", name="uq_activation_id"),
        Index("ix_activation_release", "release_id", "created_at"),
        Index("ix_activation_tenant", "tenant", "created_at"),
    )


class ReplayRun(Base):
    """§37's Replay Lab run: production versus a candidate, case by case."""

    __tablename__ = "replay_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    release_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    case_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                            default=0)
    improved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    regressed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_regressions: Mapped[int] = mapped_column(Integer, nullable=False,
                                                      default=0)
    clean: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_by: Mapped[str] = mapped_column(String(120), nullable=False,
                                            default="")
    blocked_because: Mapped[str] = mapped_column(Text, nullable=False,
                                                 default="")
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_replay_run_id"),
        Index("ix_replay_release", "release_id", "created_at"),
        Index("ix_replay_tenant", "tenant", "created_at"),
    )


class LocalTrainingRun(Base):
    """§21's local training run, and the artifact it produced.

    The artifact's HASH is here; the artifact is not. Same reasoning as the
    regulatory originals: a model file is read whole and never queried, and a
    hash is what a reproduction check actually needs.
    """

    __tablename__ = "local_training_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    training_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    dataset_release_id: Mapped[str] = mapped_column(String(64),
                                                    nullable=False,
                                                    default="")
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    build_sha: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False,
                                               default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="QUEUED")
    activated: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=False)
    approver: Mapped[str] = mapped_column(String(120), nullable=False,
                                          default="")
    failure: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    __table_args__ = (
        UniqueConstraint("training_run_id", name="uq_training_run_id"),
        Index("ix_training_task", "task", "created_at"),
        Index("ix_training_active", "tenant", "activated", "task"),
    )


class UserFeedbackPreference(Base):
    """§13's channel A: presentation settings, per user, per tenant.

    The only thing in the learning layer that takes effect without a review,
    and the closed set in `backend/learning/preference.py` is why that is
    safe. `muted_threads` carries §7's "don't ask again in this thread".
    """

    __tablename__ = "user_feedback_preferences"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="")
    values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    muted_threads: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "tenant", name="uq_feedback_preference"),
    )


# ==========================================================================
# The AI Brain: the Learning Ledger, packages, quarantine, installations,
# conflicts and the trusted signer registry. §13-§26.
#
# Six tables, and the split between them is the governance:
#
#   brain_ledger_entries   everything this installation learned, from any
#                          source, whether or not anyone acted on it. Never
#                          updated, never deleted; a wrong entry is
#                          superseded by a new one that points at it.
#   brain_packages         a package that exists — exported by us or
#                          uploaded to us. The bytes and the manifest.
#   brain_imports          what is happening to an uploaded package as it
#                          moves through §16's fifteen stages. Separate from
#                          the package because one package can be evaluated,
#                          rejected, and evaluated again later against a
#                          different baseline.
#   brain_installations    §24's history: what was integrated, when, by
#                          whom, and how much improvement it produced.
#   brain_conflicts        contradictory learning found between an import
#                          and what is already here, and how it was settled.
#   brain_signers          §26's trusted signer registry. Trust is a
#                          decision recorded here, not a property of a key.
# ==========================================================================


class BrainLedgerEntry(Base):
    """§13/§14. One thing learned, immutable, and portable only by decision.

    There is no UPDATE path in the service layer, and `superseded_by` is why
    that costs nothing: an entry found to be wrong is corrected by a new row
    pointing back at this one, so "what did we believe in March, and was it
    any good?" stays answerable in December.

    `portability` defaults to NON_PORTABLE. Most learning names a borrower
    or quotes a confidential document and is nobody else's business;
    travelling is a gate an entry passes, not a property it starts with.
    """

    __tablename__ = "brain_ledger_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(48), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False,
                                                default="1.0.0")
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                         default="")

    object_kind: Mapped[str] = mapped_column(String(32), nullable=False,
                                             default="")
    object_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                           default="")
    related_ids: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                              default=dict)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: What it was learned against. A lesson learned under a different
    #: ontology may not mean the same thing now.
    build_sha: Mapped[str] = mapped_column(String(40), nullable=False,
                                           default="")
    intelligence_release_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="")
    teaching_release_id: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     default="")
    ontology_version: Mapped[str] = mapped_column(String(16), nullable=False,
                                                  default="")

    classification: Mapped[str] = mapped_column(String(24), nullable=False,
                                                default="LOCAL")
    portability: Mapped[str] = mapped_column(String(24), nullable=False,
                                             default="NON_PORTABLE")
    portability_blockers: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                       default=list)
    redaction_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                                  default="NONE")
    review_status: Mapped[str] = mapped_column(String(24), nullable=False,
                                               default="CAPTURED")
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    candidate_components: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                       default=list)
    candidate_case_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                   default="")
    candidate_policy_id: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     default="")
    candidate_method_id: Mapped[str] = mapped_column(String(64),
                                                     nullable=False,
                                                     default="")
    candidate_ontology_change: Mapped[str] = mapped_column(
        Text, nullable=False, default="")

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    released_in: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    #: Set when a later entry corrects this one. The ledger is a history.
    superseded_by: Mapped[str] = mapped_column(String(48), nullable=False,
                                               default="")
    #: What makes this the same observation as another. The same steward
    #: mapping the same field twice is one thing learned, not two.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("entry_id", name="uq_brain_ledger_entry"),
        Index("ix_brain_ledger_source", "tenant", "source", "created_at"),
        Index("ix_brain_ledger_status", "tenant", "review_status",
              "portability"),
        Index("ix_brain_ledger_fingerprint", "tenant", "fingerprint"),
        Index("ix_brain_ledger_object", "object_kind", "object_id"),
    )


class BrainPackage(Base):
    """A Brain Pack, Learning Bundle or Developer Bundle that exists.

    Exported by us or uploaded to us; `direction` says which. The manifest
    is stored as it arrived rather than as we interpreted it, because a
    compatibility argument later is an argument about what the sender
    actually claimed.

    `storage_path` may be emptied by a payload purge while the row stays.
    §23: the bytes go, the record of what was installed does not.
    """

    __tablename__ = "brain_packages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    package_id: Mapped[str] = mapped_column(String(48), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False,
                                           default="IMPORT")
    package_kind: Mapped[str] = mapped_column(String(16), nullable=False,
                                              default="cpbrain")

    brain_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    brain_name: Mapped[str] = mapped_column(String(160), nullable=False,
                                            default="")
    brain_version: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="")

    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: SHA-256 of the package bytes. What a later "is this the same package?"
    #: is answered with.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                            default=0)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                             default=0)

    signature_state: Mapped[str] = mapped_column(String(24), nullable=False,
                                                 default="UNSIGNED")
    signing_key_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                                default="")
    signer_trust: Mapped[str] = mapped_column(String(24), nullable=False,
                                              default="UNKNOWN")

    storage_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("package_id", name="uq_brain_package"),
        Index("ix_brain_package_tenant", "tenant", "direction", "created_at"),
        Index("ix_brain_package_sha", "sha256"),
    )


class BrainImport(Base):
    """§16's quarantine. Where an uploaded package is in the pipeline.

    One row per attempt rather than per package: the same package may be
    evaluated, rejected on a conflict, and evaluated again months later
    against a different baseline, and collapsing those into one row would
    lose the fact that we said no the first time.

    Nothing here is retrievable by the live runtime. The candidate's
    teaching cases do not reach retrieval until an installation row exists
    and is ACTIVE.
    """

    __tablename__ = "brain_imports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_id: Mapped[str] = mapped_column(String(48), nullable=False)
    package_id: Mapped[str] = mapped_column(String(48), nullable=False)

    stage: Mapped[str] = mapped_column(String(32), nullable=False,
                                       default="UPLOADED")
    state: Mapped[str] = mapped_column(String(24), nullable=False,
                                       default="IN_QUARANTINE")
    #: Every stage this import has passed, in order, with when and by whom.
    stage_history: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                default=list)
    #: What is stopping it. An import with blockers may be inspected and
    #: evaluated; it may not activate.
    blockers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    security_report: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                  default=dict)
    compatibility_report: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                       default=dict)
    component_diff: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                 default=dict)
    evaluation: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                             default=dict)
    impact_report: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                default=dict)

    approvals: Mapped[list] = mapped_column(JSONB, nullable=False,
                                            default=list)
    decision: Mapped[str] = mapped_column(String(24), nullable=False,
                                          default="")
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                 default="")
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    uploaded_by: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("import_id", name="uq_brain_import"),
        Index("ix_brain_import_stage", "tenant", "state", "stage"),
        Index("ix_brain_import_package", "package_id"),
    )


class BrainInstallation(Base):
    """§24's history. What was integrated, when, by whom, and what it did.

    The measured columns are the point. An installation row that records
    only "installed on the 4th" cannot answer the question §24 says the user
    must be able to answer, so baseline, candidate, the six-dimension deltas
    and the critical fixes and regressions are first-class here rather than
    buried in a report nobody kept.
    """

    __tablename__ = "brain_installations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(48), nullable=False)
    import_id: Mapped[str] = mapped_column(String(48), nullable=False,
                                           default="")
    package_id: Mapped[str] = mapped_column(String(48), nullable=False,
                                            default="")

    brain_name: Mapped[str] = mapped_column(String(160), nullable=False,
                                            default="")
    brain_version: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="")
    source_instance_id: Mapped[str] = mapped_column(String(64),
                                                    nullable=False,
                                                    default="")
    source_user: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")

    installed_by: Mapped[str] = mapped_column(String(64), nullable=False,
                                              default="")
    approved_by: Mapped[list] = mapped_column(JSONB, nullable=False,
                                              default=list)
    components: Mapped[list] = mapped_column(JSONB, nullable=False,
                                             default=list)
    conflicts: Mapped[list] = mapped_column(JSONB, nullable=False,
                                            default=list)

    baseline_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                   default=dict)
    candidate_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                    default=dict)
    dimension_deltas: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                   default=dict)
    critical_fixes: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                 default=list)
    critical_regressions: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                       default=list)

    release_id: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    state: Mapped[str] = mapped_column(String(24), nullable=False,
                                       default="STAGED")
    staged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    rollback_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                 default="")
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    post_activation_verification: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict)

    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("installation_id", name="uq_brain_installation"),
        Index("ix_brain_installation_state", "tenant", "state",
              "activated_at"),
        Index("ix_brain_installation_import", "import_id"),
    )


class BrainConflict(Base):
    """§20/§21. Learning that contradicts learning already here.

    `resolution` has no NEWER_WINS. Recency is not evidence, and a table
    that offered it would make "the import is more recent" a reason, which
    is how a receiver quietly adopts a stranger's threshold.
    """

    __tablename__ = "brain_conflicts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conflict_id: Mapped[str] = mapped_column(String(48), nullable=False)
    import_id: Mapped[str] = mapped_column(String(48), nullable=False,
                                           default="")

    conflict_class: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False,
                                          default="MEDIUM")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    incoming: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    existing: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False,
                                                default="")
    recommendation_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                       default="")

    resolution: Mapped[str] = mapped_column(String(32), nullable=False,
                                            default="")
    resolution_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                   default="")
    #: The axis a SCOPE_SPLIT splits on. Required for that resolution and
    #: empty for every other, because a split with no axis is a deferral
    #: wearing a decision's name.
    split_axis: Mapped[str] = mapped_column(String(48), nullable=False,
                                            default="")
    resolved_by: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("conflict_id", name="uq_brain_conflict"),
        Index("ix_brain_conflict_import", "import_id", "severity"),
    )


class BrainSigner(Base):
    """§26's trusted signer registry.

    Trust is a decision recorded here by a named person, not a property a
    key asserts about itself. A package signed by a key that is not in this
    table may be inspected and evaluated — blocking at upload would stop a
    reviewer examining a package they had every right to look at — and may
    not be activated.
    """

    __tablename__ = "brain_signers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False,
                                       default="")
    organization: Mapped[str] = mapped_column(String(160), nullable=False,
                                              default="")
    #: HIGH, LOW or REVOKED. HIGH is what §26 requires before activation.
    trust_level: Mapped[str] = mapped_column(String(16), nullable=False,
                                             default="LOW")
    #: A hash of the shared verification key. Never the key itself: this
    #: table is read by the Brain Center and read by support.
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False,
                                                 default="")

    added_by: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    added_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revoked_by: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    revoked_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                default="")
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant", "key_id", name="uq_brain_signer"),
        Index("ix_brain_signer_trust", "tenant", "trust_level"),
    )
