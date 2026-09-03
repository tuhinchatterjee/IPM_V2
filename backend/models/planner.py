"""The Project Planner's system of record.

A delivery project — an IFRS 9 model redevelopment, a collections
transformation — is not the same thing as the analytical workspace
CreditProbe already calls a `project`, which is a container for chats and
investigations. Both are real and both are called "project" by the people who
use them, so these tables carry the `planner_` prefix and nothing here touches
the analytical ones.

What this module deliberately does NOT introduce
------------------------------------------------
A second user table, a second team table, a second notification table, a second
audit table, or an organisation/tenant table. CreditProbe is single-tenant:
identity is `users`, grouping is `teams`, and the access boundary for a
delivery project is its own participant list. Every foreign key here points at
the platform's own identities.

Why so many columns are stored rather than derived
--------------------------------------------------
They are not. Everything a scheduler or a screen has to be able to sort and
filter on at scale is stored — status, dates, owner, the blocked flag — and
everything that is a judgement about those facts (overdue, due soon, stale,
health, percent complete at the project level) is calculated by
`backend.planner.control` and only cached where the cache records when it was
computed. A stored value nobody can explain is the failure this separation
exists to prevent.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
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

# `users` and `teams` are defined in these modules, and the foreign keys below
# point at them. Importing them here rather than relying on the caller means
# `import backend.models.planner` is enough on its own: without it, a test or a
# script that imports only this module gets NoReferencedTableError from deep
# inside SQLAlchemy's flush, which names the column and not the missing import.
import backend.models.platform  # noqa: F401 — registers `teams`
from backend.db.models import Base  # noqa: E402 — registers `users`

# ============================================================== vocabularies
#
# Stored as short strings rather than database enums. The platform's other
# lifecycles do the same, and a native enum makes every later status addition a
# migration with a table rewrite behind it.

PROJECT_DRAFT = "DRAFT"
PROJECT_ACTIVE = "ACTIVE"
PROJECT_ON_HOLD = "ON_HOLD"
PROJECT_COMPLETED = "COMPLETED"
PROJECT_CANCELLED = "CANCELLED"
PROJECT_STATUSES = (PROJECT_DRAFT, PROJECT_ACTIVE, PROJECT_ON_HOLD,
                    PROJECT_COMPLETED, PROJECT_CANCELLED)
#: The statuses whose schedule is still live. A cancelled project cannot be
#: late, and a completed one cannot be chased.
PROJECT_OPEN = (PROJECT_DRAFT, PROJECT_ACTIVE, PROJECT_ON_HOLD)

TASK_NOT_STARTED = "NOT_STARTED"
TASK_IN_PROGRESS = "IN_PROGRESS"
TASK_BLOCKED = "BLOCKED"
TASK_IN_REVIEW = "IN_REVIEW"
TASK_COMPLETED = "COMPLETED"
TASK_CANCELLED = "CANCELLED"
TASK_STATUSES = (TASK_NOT_STARTED, TASK_IN_PROGRESS, TASK_BLOCKED,
                 TASK_IN_REVIEW, TASK_COMPLETED, TASK_CANCELLED)
#: Still owed. Everything else is either delivered or withdrawn, and neither
#: can be overdue.
TASK_OPEN = (TASK_NOT_STARTED, TASK_IN_PROGRESS, TASK_BLOCKED, TASK_IN_REVIEW)
TASK_CLOSED = (TASK_COMPLETED, TASK_CANCELLED)

MILESTONE_PENDING = "PENDING"
MILESTONE_AT_RISK = "AT_RISK"
MILESTONE_ACHIEVED = "ACHIEVED"
MILESTONE_MISSED = "MISSED"
MILESTONE_CANCELLED = "CANCELLED"
MILESTONE_STATUSES = (MILESTONE_PENDING, MILESTONE_AT_RISK,
                      MILESTONE_ACHIEVED, MILESTONE_MISSED,
                      MILESTONE_CANCELLED)
MILESTONE_OPEN = (MILESTONE_PENDING, MILESTONE_AT_RISK)

PRIORITY_LOW = "LOW"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_HIGH = "HIGH"
PRIORITY_CRITICAL = "CRITICAL"
PRIORITIES = (PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH, PRIORITY_CRITICAL)

HEALTH_GREEN = "GREEN"
HEALTH_AMBER = "AMBER"
HEALTH_RED = "RED"
HEALTH_UNKNOWN = "UNKNOWN"
HEALTHS = (HEALTH_GREEN, HEALTH_AMBER, HEALTH_RED, HEALTH_UNKNOWN)

#: What somebody DOES on the project. Distinct from `access`, which is what
#: they may change. A sponsor who reads and a sponsor who edits are the same
#: business role and different permissions, and collapsing the two is how a
#: reviewer ends up able to move somebody else's deadline.
ROLE_SPONSOR = "SPONSOR"
ROLE_OWNER = "PROJECT_OWNER"
ROLE_MANAGER = "PROJECT_MANAGER"
ROLE_WORKSTREAM_LEAD = "WORKSTREAM_LEAD"
ROLE_TASK_OWNER = "TASK_OWNER"
ROLE_CONTRIBUTOR = "CONTRIBUTOR"
ROLE_REVIEWER = "REVIEWER"
ROLE_VIEWER = "VIEWER"
PROJECT_ROLES = (ROLE_SPONSOR, ROLE_OWNER, ROLE_MANAGER, ROLE_WORKSTREAM_LEAD,
                 ROLE_TASK_OWNER, ROLE_CONTRIBUTOR, ROLE_REVIEWER, ROLE_VIEWER)

#: What somebody MAY DO. Ordered weakest to strongest; `backend.planner.access`
#: compares them by index, so the order here is load-bearing.
ACCESS_VIEWER = "VIEWER"
ACCESS_CONTRIBUTOR = "CONTRIBUTOR"
ACCESS_EDITOR = "EDITOR"
ACCESS_OWNER = "OWNER"
ACCESS_LEVELS = (ACCESS_VIEWER, ACCESS_CONTRIBUTOR, ACCESS_EDITOR,
                 ACCESS_OWNER)

RAID_RISK = "RISK"
RAID_ASSUMPTION = "ASSUMPTION"
RAID_ISSUE = "ISSUE"
RAID_DECISION = "DECISION"
RAID_TYPES = (RAID_RISK, RAID_ASSUMPTION, RAID_ISSUE, RAID_DECISION)

RAID_OPEN = "OPEN"
RAID_IN_PROGRESS = "IN_PROGRESS"
RAID_RESOLVED = "RESOLVED"
RAID_CLOSED = "CLOSED"
RAID_ACCEPTED = "ACCEPTED"
RAID_STATUSES = (RAID_OPEN, RAID_IN_PROGRESS, RAID_RESOLVED, RAID_CLOSED,
                 RAID_ACCEPTED)
RAID_LIVE = (RAID_OPEN, RAID_IN_PROGRESS)

SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"
SEVERITIES = (SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH, SEVERITY_CRITICAL)

DEP_FINISH_TO_START = "FS"
DEP_START_TO_START = "SS"
DEP_FINISH_TO_FINISH = "FF"
DEP_START_TO_FINISH = "SF"
DEPENDENCY_TYPES = (DEP_FINISH_TO_START, DEP_START_TO_START,
                    DEP_FINISH_TO_FINISH, DEP_START_TO_FINISH)

ENTITY_TASK = "TASK"
ENTITY_MILESTONE = "MILESTONE"
ENTITY_PROJECT = "PROJECT"
ENTITY_RAID = "RAID"
ENTITY_TYPES = (ENTITY_TASK, ENTITY_MILESTONE, ENTITY_PROJECT, ENTITY_RAID)

#: Where a change came from. The whole point of recording it is that an update
#: somebody typed and an update an agent proposed are different evidence, and a
#: reader who cannot tell them apart cannot audit either.
SOURCE_UI = "UI"
SOURCE_API = "API"
SOURCE_AI = "AI"
#: A change a person asked for in conversation and the agent applied on their
#: behalf. Distinct from `AI` on purpose: "an agent did this" and "a named
#: person told the agent to do this, in these words" are different governance
#: facts, and only the second one has somebody who can be asked about it.
SOURCE_AI_CHAT = "AI_CHAT"
SOURCE_EXCEL = "EXCEL_IMPORT"
SOURCE_SYSTEM = "SYSTEM"
SOURCES = (SOURCE_UI, SOURCE_API, SOURCE_AI, SOURCE_AI_CHAT, SOURCE_EXCEL,
           SOURCE_SYSTEM)

CADENCE_WEEKLY = "WEEKLY"
CADENCE_FORTNIGHTLY = "FORTNIGHTLY"
CADENCE_MONTHLY = "MONTHLY"
CADENCE_NONE = "NONE"
CADENCES = (CADENCE_WEEKLY, CADENCE_FORTNIGHTLY, CADENCE_MONTHLY,
            CADENCE_NONE)


# ================================================================== project


class PlannerProject(Base):
    """One delivery project.

    `code` is the identifier people use in conversation and in spreadsheets —
    IFRS9-2026 — and it is what an imported workbook joins on. `id` is the
    database's business and never appears in a workbook, because a surrogate
    key in a column somebody edits by hand is a data-loss incident waiting for
    a copy-paste.
    """

    __tablename__ = "planner_projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    business_context: Mapped[str] = mapped_column(Text, nullable=False,
                                                  default="")

    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=PROJECT_DRAFT)
    priority: Mapped[str] = mapped_column(String(16), nullable=False,
                                          default=PRIORITY_MEDIUM)

    sponsor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    reporting_cadence: Mapped[str] = mapped_column(String(16), nullable=False,
                                                   default=CADENCE_WEEKLY)
    #: Days before a due date at which the owner is reminded. Stored per
    #: project so a programme with a monthly rhythm is not chased daily.
    reminder_days: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                default=list)
    #: Days without an update after which a near-term task is considered stale.
    stale_after_days: Mapped[int] = mapped_column(Integer, nullable=False,
                                                  default=7)

    # ---- calculated, with the time they were calculated -------------------
    #
    # Cached so a portfolio of a hundred projects is one query rather than a
    # hundred recalculations, and stamped so a screen can say how fresh the
    # number is rather than implying it is live.
    calculated_percent_complete: Mapped[float] = mapped_column(
        Integer, nullable=False, default=0)
    calculated_health: Mapped[str] = mapped_column(String(12), nullable=False,
                                                   default=HEALTH_UNKNOWN)
    calculated_health_reason: Mapped[str] = mapped_column(
        Text, nullable=False, default="")
    calculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    # ---- a human may disagree, on the record ------------------------------
    manual_health: Mapped[str] = mapped_column(String(12), nullable=False,
                                               default="")
    manual_health_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                      default="")
    manual_health_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    manual_health_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=False)
    #: Bumped on every mutation. A stale editor sends the version it read and
    #: is refused rather than silently overwriting somebody else's edit.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    participants: Mapped[list[PlannerParticipant]] = relationship(
        back_populates="project", cascade="all, delete-orphan")
    workstreams: Mapped[list[PlannerWorkstream]] = relationship(
        back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[list[PlannerTask]] = relationship(
        back_populates="project", cascade="all, delete-orphan")
    milestones: Mapped[list[PlannerMilestone]] = relationship(
        back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','ON_HOLD','COMPLETED','CANCELLED')",
            name="ck_planner_project_status"),
        Index("ix_planner_projects_status", "status", "archived"),
        Index("ix_planner_projects_manager", "manager_id"),
    )


class PlannerParticipant(Base):
    """Who is on a project, what they do on it, and what they may change.

    The access boundary. CreditProbe has no organisation table, so this row is
    what stands between a delivery project and everybody else in the bank:
    without one, a user cannot read the project, list its tasks, export it,
    import against it or reach it through an agent.
    """

    __tablename__ = "planner_participants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    project_role: Mapped[str] = mapped_column(String(24), nullable=False,
                                              default=ROLE_CONTRIBUTOR)
    access: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=ACCESS_CONTRIBUTOR)
    workstream_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_workstreams.id", ondelete="SET NULL"),
        nullable=True)
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    added_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    project: Mapped[PlannerProject] = relationship(
        back_populates="participants")

    __table_args__ = (
        UniqueConstraint("project_id", "user_id",
                         name="uq_planner_participant"),
        CheckConstraint(
            "access IN ('VIEWER','CONTRIBUTOR','EDITOR','OWNER')",
            name="ck_planner_participant_access"),
        Index("ix_planner_participants_user", "user_id", "project_id"),
    )


class PlannerWorkstream(Base):
    """A strand of delivery inside a project — Data, Methodology, Validation."""

    __tablename__ = "planner_workstreams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="CASCADE"), nullable=False)
    #: The identifier a workbook uses — WS-DATA. Unique inside the project only.
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=PROJECT_ACTIVE)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    project: Mapped[PlannerProject] = relationship(
        back_populates="workstreams")

    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_planner_workstream"),
        Index("ix_planner_workstreams_project", "project_id", "sequence"),
    )


class PlannerTask(Base):
    """A unit of work somebody owns.

    Subtasks are the same table with `parent_id` set. A separate subtask table
    would double every query, every permission check and every import rule for
    a distinction that is one nullable column.
    """

    __tablename__ = "planner_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="CASCADE"), nullable=False)
    #: T-101. What a person says out loud and what a workbook joins on.
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    workstream_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_workstreams.id", ondelete="SET NULL"),
        nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_tasks.id", ondelete="CASCADE"), nullable=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: User ids. A join table would be correct and is not worth six extra
    #: queries per screen for a list that is read whole and written whole.
    contributor_ids: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                  default=list)

    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=TASK_NOT_STARTED)
    priority: Mapped[str] = mapped_column(String(16), nullable=False,
                                          default=PRIORITY_MEDIUM)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effort_days: Mapped[float | None] = mapped_column(Integer, nullable=True)

    percent_complete: Mapped[int] = mapped_column(Integer, nullable=False,
                                                  default=0)
    #: How much this task counts for in the project's progress. A one-day
    #: administrative task and a three-month build are both "a task", and
    #: averaging them unweighted is how a project reads 50% complete with all
    #: of the hard half still to do.
    weight: Mapped[float] = mapped_column(Integer, nullable=False, default=1)

    critical: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                          default=False)
    blocker_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                default="")
    next_step: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: The last thing anybody said about it, denormalised so a list of two
    #: hundred tasks does not become two hundred subqueries.
    last_update_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_update_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_update_text: Mapped[str] = mapped_column(Text, nullable=False,
                                                  default="")

    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    project: Mapped[PlannerProject] = relationship(back_populates="tasks")

    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_planner_task_code"),
        CheckConstraint("percent_complete >= 0 AND percent_complete <= 100",
                        name="ck_planner_task_percent"),
        CheckConstraint("weight >= 0", name="ck_planner_task_weight"),
        CheckConstraint(
            "status IN ('NOT_STARTED','IN_PROGRESS','BLOCKED','IN_REVIEW',"
            "'COMPLETED','CANCELLED')",
            name="ck_planner_task_status"),
        # The scheduler's own query: open tasks with a due date, by project.
        Index("ix_planner_tasks_due", "project_id", "status", "due_date"),
        Index("ix_planner_tasks_owner", "owner_id", "status", "due_date"),
        Index("ix_planner_tasks_workstream", "workstream_id"),
        Index("ix_planner_tasks_parent", "parent_id"),
    )


class PlannerMilestone(Base):
    """A date the project is judged against.

    Separate from tasks because a milestone is a commitment rather than work:
    it has no percentage, it is either met or it is not, and a project's health
    turns on it much harder than on any single task.
    """

    __tablename__ = "planner_milestones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    workstream_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_workstreams.id", ondelete="SET NULL"),
        nullable=True)

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=MILESTONE_PENDING)
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    project: Mapped[PlannerProject] = relationship(
        back_populates="milestones")

    __table_args__ = (
        UniqueConstraint("project_id", "code",
                         name="uq_planner_milestone_code"),
        Index("ix_planner_milestones_target", "project_id", "status",
              "target_date"),
    )


class PlannerDependency(Base):
    """One thing has to happen before another.

    Both ends are (type, id) rather than two nullable foreign keys, because a
    milestone can depend on a task and a task on a milestone, and four nullable
    columns to express one edge is a shape nobody can query.
    """

    __tablename__ = "planner_dependencies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="CASCADE"), nullable=False)

    predecessor_type: Mapped[str] = mapped_column(String(16), nullable=False,
                                                  default=ENTITY_TASK)
    predecessor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    successor_type: Mapped[str] = mapped_column(String(16), nullable=False,
                                                default=ENTITY_TASK)
    successor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    dependency_type: Mapped[str] = mapped_column(String(4), nullable=False,
                                                 default=DEP_FINISH_TO_START)
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "predecessor_type", "predecessor_id",
                         "successor_type", "successor_id",
                         name="uq_planner_dependency"),
        CheckConstraint("dependency_type IN ('FS','SS','FF','SF')",
                        name="ck_planner_dependency_type"),
        Index("ix_planner_dependencies_pred", "project_id",
              "predecessor_type", "predecessor_id"),
        Index("ix_planner_dependencies_succ", "project_id",
              "successor_type", "successor_id"),
    )


class PlannerRaid(Base):
    """Risks, assumptions, issues and decisions.

    One table rather than four: they share every field that matters, they are
    read together on one screen, and a project review asks "what is open"
    across all of them at once.
    """

    __tablename__ = "planner_raid"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    workstream_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_workstreams.id", ondelete="SET NULL"),
        nullable=True)

    raid_type: Mapped[str] = mapped_column(String(16), nullable=False,
                                           default=RAID_RISK)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    raised_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolved_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    probability: Mapped[str] = mapped_column(String(16), nullable=False,
                                             default="")
    impact: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False,
                                          default=SEVERITY_MEDIUM)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=RAID_OPEN)

    mitigation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolution: Mapped[str] = mapped_column(Text, nullable=False, default="")

    linked_entity_type: Mapped[str] = mapped_column(String(16), nullable=False,
                                                    default="")
    linked_entity_id: Mapped[int | None] = mapped_column(BigInteger,
                                                         nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_planner_raid_code"),
        CheckConstraint(
            "raid_type IN ('RISK','ASSUMPTION','ISSUE','DECISION')",
            name="ck_planner_raid_type"),
        Index("ix_planner_raid_open", "project_id", "status", "severity"),
    )


class PlannerUpdate(Base):
    """What changed, when, who said so, and what it was before.

    Append-only. Nothing in the services updates or deletes a row here: "what
    changed since Friday?" is answerable only from a record that was not
    rewritten, and a status history that can be edited is not a history.
    """

    __tablename__ = "planner_updates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False,
                                             default=ENTITY_TASK)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: The human-facing code, kept alongside the id so the history survives a
    #: task being deleted and still reads as "T-104".
    entity_code: Mapped[str] = mapped_column(String(40), nullable=False,
                                             default="")

    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: What KIND of change: status, progress, blocker, owner, date, comment,
    #: created, deleted, health, membership.
    action: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="comment")

    old_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                            default="")
    new_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                            default="")
    old_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)

    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blocker: Mapped[str] = mapped_column(Text, nullable=False, default="")
    next_step: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Anything else the change touched, as {field: [before, after]}.
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    source: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=SOURCE_UI)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "source IN ('UI','API','AI','AI_CHAT','EXCEL_IMPORT','SYSTEM')",
            name="ck_planner_update_source"),
        # "What changed in this project since Friday?" is exactly this index.
        Index("ix_planner_updates_project_time", "project_id", "created_at"),
        Index("ix_planner_updates_entity", "project_id", "entity_type",
              "entity_id", "created_at"),
    )


class PlannerReminder(Base):
    """One reminder that has already been sent.

    The whole purpose of the table is NOT sending it twice. The monitor runs on
    a schedule; without a record of what it has already said, a task due in
    three days generates a three-day reminder on every cycle until it is done,
    and the person stops reading any of them.
    """

    __tablename__ = "planner_reminders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False,
                                             default=ENTITY_TASK)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    #: due_7 | due_3 | due_1 | due_today | overdue | stale | update_requested
    #: | milestone_7 | milestone_overdue | health_red
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    #: What the reminder was ABOUT, so a due date that moves re-arms it. Two
    #: reminders with the same fingerprint are the same reminder.
    fingerprint: Mapped[str] = mapped_column(String(120), nullable=False)
    notification_id: Mapped[int | None] = mapped_column(BigInteger,
                                                        nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ---- the chase, once it is a request rather than a nudge --------------
    #
    # An update REQUEST is a reminder somebody is expected to answer, and a
    # project manager's real question is "who have we asked, and did they come
    # back?". That is one row's worth of state on the reminder that carried
    # the ask, not a second table: a chase IS a reminder with a follow-up, and
    # the fingerprint that stops the reminder repeating is exactly the key
    # that stops the same person being chased twice for the same thing.
    #
    # sent | answered | cancelled. A plain reminder stays 'sent' forever and
    # is never shown on the requests screen, which filters on `asked`.
    state: Mapped[str] = mapped_column(String(16), nullable=False,
                                       default="sent",
                                       server_default=text("'sent'"))
    #: True only for reminders raised as an explicit request for an update.
    asked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                        server_default=text("false"))
    #: Why the request was raised, in the sentence the engine wrote.
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="",
                                        server_default=text("''"))
    #: Who asked. Null when the monitor raised it on nobody's behalf, which is
    #: the normal case and the point of the feature.
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: The history row the owner wrote in answer, so the manager can read the
    #: reply beside the request rather than hunting for it in the timeline.
    response_update_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_updates.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_planner_reminder_print"),
        Index("ix_planner_reminders_entity", "project_id", "entity_type",
              "entity_id"),
        Index("ix_planner_reminders_asked", "project_id", "asked", "state"),
        Index("ix_planner_reminders_user", "user_id", "state"),
    )


class PlannerImport(Base):
    """A workbook somebody uploaded, and what was decided about it.

    Kept after the import so "who loaded this plan, from which file, and what
    did the checks say" has an answer that outlives the upload.
    """

    __tablename__ = "planner_imports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="SET NULL"), nullable=True)
    project_code: Mapped[str] = mapped_column(String(40), nullable=False,
                                              default="")
    filename: Mapped[str] = mapped_column(String(300), nullable=False,
                                          default="")
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False,
                                             default="")
    #: UPLOADED | VALIDATED | FAILED | COMMITTED | DISCARDED
    state: Mapped[str] = mapped_column(String(16), nullable=False,
                                       default="UPLOADED")
    #: The parsed workbook, held between preview and commit so the commit
    #: applies exactly what the person was shown rather than re-reading a file
    #: that may have changed underneath them.
    staged: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    findings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_planner_imports_project", "project_id", "uploaded_at"),
    )


__all__ = [
    "PROJECT_STATUSES", "PROJECT_OPEN", "PROJECT_DRAFT", "PROJECT_ACTIVE",
    "PROJECT_ON_HOLD", "PROJECT_COMPLETED", "PROJECT_CANCELLED",
    "TASK_STATUSES", "TASK_OPEN", "TASK_CLOSED", "TASK_NOT_STARTED",
    "TASK_IN_PROGRESS", "TASK_BLOCKED", "TASK_IN_REVIEW", "TASK_COMPLETED",
    "TASK_CANCELLED",
    "MILESTONE_STATUSES", "MILESTONE_OPEN", "MILESTONE_PENDING",
    "MILESTONE_AT_RISK", "MILESTONE_ACHIEVED", "MILESTONE_MISSED",
    "MILESTONE_CANCELLED",
    "PRIORITIES", "PRIORITY_LOW", "PRIORITY_MEDIUM", "PRIORITY_HIGH",
    "PRIORITY_CRITICAL",
    "HEALTHS", "HEALTH_GREEN", "HEALTH_AMBER", "HEALTH_RED", "HEALTH_UNKNOWN",
    "PROJECT_ROLES", "ROLE_SPONSOR", "ROLE_OWNER", "ROLE_MANAGER",
    "ROLE_WORKSTREAM_LEAD", "ROLE_TASK_OWNER", "ROLE_CONTRIBUTOR",
    "ROLE_REVIEWER", "ROLE_VIEWER",
    "ACCESS_LEVELS", "ACCESS_VIEWER", "ACCESS_CONTRIBUTOR", "ACCESS_EDITOR",
    "ACCESS_OWNER",
    "RAID_TYPES", "RAID_RISK", "RAID_ASSUMPTION", "RAID_ISSUE",
    "RAID_DECISION", "RAID_STATUSES", "RAID_LIVE", "RAID_OPEN",
    "RAID_IN_PROGRESS", "RAID_RESOLVED", "RAID_CLOSED", "RAID_ACCEPTED",
    "SEVERITIES", "SEVERITY_LOW", "SEVERITY_MEDIUM", "SEVERITY_HIGH",
    "SEVERITY_CRITICAL",
    "DEPENDENCY_TYPES", "DEP_FINISH_TO_START", "DEP_START_TO_START",
    "DEP_FINISH_TO_FINISH", "DEP_START_TO_FINISH",
    "ENTITY_TYPES", "ENTITY_TASK", "ENTITY_MILESTONE", "ENTITY_PROJECT",
    "ENTITY_RAID",
    "SOURCES", "SOURCE_UI", "SOURCE_API", "SOURCE_AI", "SOURCE_AI_CHAT",
    "SOURCE_EXCEL",
    "SOURCE_SYSTEM",
    "CADENCES", "CADENCE_WEEKLY", "CADENCE_FORTNIGHTLY", "CADENCE_MONTHLY",
    "CADENCE_NONE",
    "PlannerProject", "PlannerParticipant", "PlannerWorkstream",
    "PlannerTask", "PlannerMilestone", "PlannerDependency", "PlannerRaid",
    "PlannerUpdate", "PlannerReminder", "PlannerImport",
]
