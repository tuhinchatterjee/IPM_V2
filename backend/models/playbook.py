"""Playbook: the committee pack's system of record.

A committee pack is a governance record. Six months after a meeting, somebody
has to be able to say what the number was, which formula produced it, which
data version it read, who approved it and on what day — and get the same answer
they would have got on the day. That requirement, and not the editing
experience, is what this schema is shaped by.

What this module deliberately does NOT introduce
------------------------------------------------
A second user table, a second team table, a second notification table, a second
comment table, a second export log, a second audit trail, a second task engine,
a second metric-formula engine or an organisation/tenant table.

  identity            `users`                        (platform)
  grouping            `teams`                        (platform)
  comments            `comments`                     (platform, object-keyed)
  in-app notices      `notifications`                (platform, object-keyed)
  download log        `export_records`               (platform, object-keyed)
  execution of work   `planner_tasks`                (Project Planner)
  metric definitions  `backend.metrics.library`      (code, not rows)
  chart rendering     `backend.metrics.execution`    (the governed executor)

Every foreign key here points at the platform's own identities. Where a
committee action becomes real work, it links to a Project Planner task rather
than growing its own scheduler — the Planner stays the execution source of
truth, and Playbook holds the governance record of why the work exists.

Why a snapshot table exists
---------------------------
`playbook_snapshots` is the reason a pack is reproducible. A pack does not read
live metrics when it is opened; it reads the values that were calculated into
it, each with its formula version, period, filters and calculation trace. An
approved pack keeps its approved snapshots for ever. Refreshing a draft writes
NEW snapshot rows at a new pack version — it never edits an approved one.

Why so many statuses are stored rather than derived
---------------------------------------------------
Only the ones a scheduler or a list screen must sort and filter on at scale:
pack status, section status, meeting date, owner. Readiness — the judgement
about whether a pack can go to committee — is calculated by
`backend.playbook.readiness` from the facts, and is cached only alongside the
timestamp saying when it was computed. A stored judgement nobody can explain is
exactly the failure this separation prevents.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
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

# `users` and `teams` live in these modules and the foreign keys below point at
# them. Importing here means `import backend.models.playbook` is enough on its
# own: without it, a script that imports only this module gets
# NoReferencedTableError from inside SQLAlchemy's flush, which names the column
# and not the missing import.
import backend.models.planner  # noqa: F401 — registers `planner_tasks`
import backend.models.platform  # noqa: F401 — registers `teams`
from backend.db.models import Base  # noqa: E402 — registers `users`

# ============================================================== vocabularies
#
# Tuples rather than enums, for the reason the planner records: a database
# enum needs a migration to add a value, and these lists grow with the product.
# The service validates against them and says which values are allowed.

#: How often a committee sits.
CADENCES: tuple[str, ...] = (
    "WEEKLY", "FORTNIGHTLY", "MONTHLY", "QUARTERLY", "SEMI_ANNUAL",
    "ANNUAL", "AD_HOC",
)

#: What somebody IS on a committee. A business fact about the forum, printed on
#: the attendance page, and independent of what they may do in the software.
BUSINESS_ROLES: tuple[str, ...] = (
    "CHAIR", "SECRETARY", "PACK_OWNER", "MEMBER", "PRESENTER",
    "SUBJECT_MATTER_EXPERT", "OBSERVER",
)

#: What somebody may DO to this committee's packs. Enforced in the service on
#: every mutating call; never inferred from the business role, because a Chair
#: who is not an approver on a particular committee is an ordinary situation.
ACCESS_ROLES: tuple[str, ...] = (
    "OWNER", "EDITOR", "CONTRIBUTOR", "REVIEWER", "APPROVER", "VIEWER",
)

#: Ascending authority. `backend.playbook.access` compares by index, so adding
#: a role means deciding where it sits rather than editing every check.
ACCESS_RANK: dict[str, int] = {
    "VIEWER": 0, "CONTRIBUTOR": 1, "REVIEWER": 2, "EDITOR": 3,
    "APPROVER": 4, "OWNER": 5,
}

#: How confidential the pack is. Printed on every page of every export.
CONFIDENTIALITY: tuple[str, ...] = (
    "PUBLIC", "INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL",
)

TEMPLATE_STATUSES: tuple[str, ...] = ("DRAFT", "PUBLISHED", "RETIRED")

#: The pack's own lifecycle. `SUPERSEDED` is what an amended pack's previous
#: version becomes; `ARCHIVED` is a pack nobody is working on any more.
PACK_STATUSES: tuple[str, ...] = (
    "DRAFT", "DATA_PENDING", "GENERATING", "CONTRIBUTOR_REVIEW", "REVIEW",
    "CHANGES_REQUESTED", "READY_FOR_APPROVAL", "APPROVED", "PUBLISHED",
    "SUPERSEDED", "ARCHIVED",
)

#: Statuses in which the pack's content may still be edited. Everything else is
#: locked, and `backend.playbook.access` refuses a write against it.
EDITABLE_PACK_STATUSES: frozenset[str] = frozenset({
    "DRAFT", "DATA_PENDING", "GENERATING", "CONTRIBUTOR_REVIEW", "REVIEW",
    "CHANGES_REQUESTED", "READY_FOR_APPROVAL",
})

#: A pack in one of these has been signed off and is immutable. A correction
#: creates an amendment at a new version; it never rewrites one of these.
LOCKED_PACK_STATUSES: frozenset[str] = frozenset({
    "APPROVED", "PUBLISHED", "SUPERSEDED",
})

SECTION_STATUSES: tuple[str, ...] = (
    "NOT_STARTED", "DATA_PENDING", "DRAFTING", "READY_FOR_REVIEW",
    "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "LOCKED",
)

#: What a block IS. Deliberately typed rather than one HTML blob per section:
#: a governed KPI has a formula and a lineage, and a paragraph of human prose
#: does not, and a pack that cannot tell them apart cannot be audited.
BLOCK_TYPES: tuple[str, ...] = (
    "TITLE", "SUBTITLE", "KPI", "CHART", "TABLE", "AI_NARRATIVE",
    "NARRATIVE", "RISK_CALLOUT", "FINDING", "DECISION_REQUEST",
    "ACTION_LOG", "METHODOLOGY_NOTE", "DATA_QUALITY_NOTE", "APPENDIX",
    "SOURCE_DOCUMENT", "DIVIDER",
)

#: Blocks whose content is a governed calculation rather than words. These are
#: the ones that must carry a snapshot before a pack can be approved.
CALCULATED_BLOCK_TYPES: frozenset[str] = frozenset({"KPI", "CHART", "TABLE"})

#: The one import class that names no metric: a table lifted out of somebody's
#: file, which CreditProbe did not calculate and is not asserting.
IMPORTED_TABLE: str = "UNMAPPED_TABLE"


def carries_a_figure(block: object) -> bool:
    """Whether this block is one the pack must calculate before approval.

    Block TYPE alone is not enough. A TABLE that came out of an uploaded
    document is a table of somebody else's numbers: it will never carry a
    snapshot, by design, and treating it as an uncalculated figure blocks the
    pack's readiness forever on a reason that is not true.
    """
    return (str(getattr(block, "block_type", "")) in CALCULATED_BLOCK_TYPES
            and str(getattr(block, "import_class", "")) != IMPORTED_TABLE)

#: How a sentence in a pack relates to the data underneath it. §7.1: an
#: inference presented as a fact is the single most damaging thing an
#: automated commentary writer can do, so the distinction is stored, not
#: implied by wording.
STATEMENT_KINDS: tuple[str, ...] = (
    "FACT", "INFERENCE", "RECOMMENDATION", "OPEN_QUESTION", "NOT_RECORDED",
    "DATA_LIMITATION",
)

FINDING_TYPES: tuple[str, ...] = (
    "DETERIORATION", "IMPROVEMENT", "THRESHOLD_BREACH", "DATA_QUALITY",
    "MODEL_PERFORMANCE", "CONCENTRATION", "POLICY_EXCEPTION",
    "STAGING_CHANGE", "ECL_MOVEMENT", "OVERLAY", "ACTION_OVERDUE",
    "DECISION_REQUIRED", "NARRATIVE_INCONSISTENCY",
)

SEVERITIES: tuple[str, ...] = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")

#: Ascending, so "at least MEDIUM" is a comparison rather than a set.
SEVERITY_RANK: dict[str, int] = {
    "INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4,
}

#: A finding is never deleted. Dismissing one records who dismissed it and why,
#: which is the whole point of raising it deterministically in the first place.
FINDING_STATUSES: tuple[str, ...] = (
    "OPEN", "ACKNOWLEDGED", "EXPLAINED", "ACTIONED", "DISMISSED", "RESOLVED",
)

DECISION_STATUSES: tuple[str, ...] = (
    "DRAFT", "REQUIRED", "DEFERRED", "APPROVED", "REJECTED",
    "CONDITIONALLY_APPROVED", "WITHDRAWN",
)

ACTION_STATUSES: tuple[str, ...] = (
    "DRAFT", "OPEN", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED",
)

PRIORITIES: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

#: What a review says. `PENDING` is a review that has been requested and not
#: yet given — the row exists so the pack can say who it is waiting for.
REVIEW_DECISIONS: tuple[str, ...] = (
    "PENDING", "APPROVED", "CHANGES_REQUESTED", "DECLINED",
)

REVIEW_SCOPES: tuple[str, ...] = ("SECTION", "PACK")

#: Which door a change came through. The same vocabulary the Project Planner
#: uses, so one person reading two histories reads one vocabulary.
SOURCE_UI = "UI"
SOURCE_API = "API"
SOURCE_AI = "AI"
SOURCE_AI_CHAT = "AI_CHAT"
SOURCE_IMPORT = "IMPORT"
SOURCE_SYSTEM = "SYSTEM"
SOURCES: tuple[str, ...] = (
    SOURCE_UI, SOURCE_API, SOURCE_AI, SOURCE_AI_CHAT, SOURCE_IMPORT,
    SOURCE_SYSTEM,
)

#: What a source/evidence row points at.
SOURCE_KINDS: tuple[str, ...] = (
    "METRIC", "LENS", "DATASET", "CALCULATION_TRACE", "DOCUMENT",
    "PRIOR_PACK", "PLANNER_TASK", "DECISION", "HUMAN_INPUT", "IMPORTED",
)

#: How imported content is classified. §17: a number found in somebody's old
#: PowerPoint is not a governed CreditProbe figure, and the product says so on
#: the block rather than hoping the reader remembers.
IMPORT_CLASSES: tuple[str, ...] = (
    "IMPORTED_TEXT", "IMPORTED_IMAGE", "UNMAPPED_TABLE",
    "MAPPED_GOVERNED_METRIC", "SUPPORTING_DOCUMENT",
)

#: Why a metric has no value. §3.3 — these are four different facts and a
#: reader told the wrong one wastes an afternoon on the wrong question.
UNAVAILABLE_REASONS: tuple[str, ...] = (
    "OK", "NO_DATA", "NOT_MATURED", "CALCULATION_FAILED", "NOT_AUTHORISED",
    "PERIOD_MISSING", "METRIC_UNAVAILABLE",
)


# ================================================================ committees


class PlaybookCommittee(Base):
    """A recurring governance forum.

    The committee is the durable thing: it outlives any one pack, owns the
    cadence and the default workflow, and is what a template and a schedule
    hang off.
    """

    __tablename__ = "playbook_committees"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    business_area: Mapped[str] = mapped_column(String(120), nullable=False,
                                               default="")

    chair_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                 nullable=True)
    secretary_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                     nullable=True)

    cadence: Mapped[str] = mapped_column(String(24), nullable=False,
                                         default="MONTHLY")
    #: 0=Monday .. 6=Sunday. The day the forum normally sits, used to place the
    #: next meeting when a pack is created from the schedule.
    meeting_weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)

    default_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_templates.id", ondelete="SET NULL"), nullable=True)

    #: The standing agenda, as an ordered list of headings. Not the pack's
    #: sections — the agenda is what the meeting discusses and the sections are
    #: what the pack contains, and on a real committee they differ.
    standard_agenda: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                  default=list)
    #: Timing offsets in days before the meeting, e.g.
    #: {"create": 14, "inputs": 10, "data_check": 7, "generate": 5,
    #:  "review": 3, "escalate": 1}. Configurable per committee: §3.2 forbids
    #: hard-coding one cadence for every forum.
    workflow_offsets: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                   default=dict)

    confidentiality: Mapped[str] = mapped_column(String(32), nullable=False,
                                                 default="CONFIDENTIAL")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: Set on committees CreditProbe ships as a demonstration, and used by the
    #: demo refresh to find what it may move. Empty on anything a person made.
    demo_origin: Mapped[str] = mapped_column(String(40), nullable=False,
                                             default="", server_default=text("''"))
    #: The date the demonstration was built relative to, so it can be rolled
    #: forward by arithmetic instead of rebuilt.
    demo_anchor_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    members: Mapped[list[PlaybookMember]] = relationship(
        back_populates="committee", cascade="all, delete-orphan")
    packs: Mapped[list[PlaybookPack]] = relationship(
        back_populates="committee", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("code", name="uq_playbook_committee_code"),
        Index("ix_playbook_committees_active", "active", "business_area"),
        Index("ix_playbook_committees_demo", "demo_origin",
              postgresql_where=text("demo_origin <> ''")),
    )


class PlaybookMember(Base):
    """One person on one committee, in one business role and one access role.

    Two roles rather than one on purpose. `business_role` is what they are in
    the room and prints on the attendance page. `access_role` is what the
    software lets them do, and is the only one any permission check reads.
    """

    __tablename__ = "playbook_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    committee_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_committees.id", ondelete="CASCADE"),
        nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    business_role: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="MEMBER")
    access_role: Mapped[str] = mapped_column(String(24), nullable=False,
                                             default="VIEWER")
    #: What they are called on the attendance page — "Head of Retail Credit
    #: Risk". Stored because a job title changes and a pack tabled in March
    #: should still say what it said in March.
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    #: Whether they are sent this committee's reminders at all.
    notify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    committee: Mapped[PlaybookCommittee] = relationship(back_populates="members")

    __table_args__ = (
        UniqueConstraint("committee_id", "user_id",
                         name="uq_playbook_member"),
        Index("ix_playbook_members_user", "user_id", "active"),
    )


# ================================================================= templates


class PlaybookTemplate(Base):
    """A reusable pack shape, versioned.

    Versioned because a pack tabled last quarter was built from the template as
    it was then, and reproducing that pack means knowing which shape it came
    from. A new version is a new row; the old row is never edited.

    The section definitions live in `sections` as JSONB rather than in their own
    table. A template version is written once and read whole — there is no
    workflow that edits section four of version three in place — and keeping the
    shape in one document is what makes "which template version did this pack
    come from" a single foreign key instead of a join across a version graph.
    """

    __tablename__ = "playbook_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    committee_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_committees.id", ondelete="CASCADE"),
        nullable=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default="DRAFT")

    #: [{"key","title","purpose","order","owner_username","reviewer_username",
    #:   "blocks":[...], "narrative_instructions": "...", "required": bool}]
    sections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Materiality rules this template applies, as the findings engine reads
    #: them. See `backend.playbook.materiality` for the shape.
    materiality: Mapped[list] = mapped_column(JSONB, nullable=False,
                                              default=list)
    #: Domains and datasets the pack cannot be generated without.
    required_domains: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                   default=list)
    required_datasets: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                    default=list)
    #: Export presentation: theme, footer, whether an evidence workbook is
    #: offered alongside the document.
    export_settings: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                  default=dict)
    confidentiality: Mapped[str] = mapped_column(String(32), nullable=False,
                                                 default="CONFIDENTIAL")

    demo_origin: Mapped[str] = mapped_column(String(40), nullable=False,
                                             default="", server_default=text("''"))

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_playbook_template_version"),
        Index("ix_playbook_templates_committee", "committee_id", "status"),
    )


# ===================================================================== packs


class PlaybookPack(Base):
    """One committee report, for one meeting, for one reporting period.

    `template_id` points at the template VERSION the pack was created from, so
    a pack keeps its shape when the template moves on.
    """

    __tablename__ = "playbook_packs"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    committee_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_committees.id", ondelete="CASCADE"),
        nullable=False)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_templates.id", ondelete="SET NULL"), nullable=True)

    name: Mapped[str] = mapped_column(String(240), nullable=False)
    #: The reporting period, in the platform's own period vocabulary —
    #: "2025-07", "Q2 2026". Resolved through `backend.metrics.service`.
    period: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    comparison_period: Mapped[str] = mapped_column(String(32), nullable=False,
                                                   default="")
    meeting_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: The date the figures are as at, which is not the meeting date and not
    #: the day the pack was generated.
    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: After this, a draft refresh stops pulling new data: the pack is being
    #: reviewed against a fixed picture.
    data_freeze_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                 nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="DRAFT")
    confidentiality: Mapped[str] = mapped_column(String(32), nullable=False,
                                                 default="CONFIDENTIAL")

    #: The working version. Every content change bumps it, and optimistic
    #: concurrency compares against it so two editors cannot silently overwrite
    #: one another.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The version that was approved, if any. An approved pack renders from its
    #: snapshot rows at this version and never from live data.
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Set when this pack was created as an amendment of another.
    amends_pack_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="SET NULL"), nullable=True)
    amendment_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                  default="")
    #: The previous approved pack of the same committee, which "what changed
    #: since the previous committee" compares against. Stored rather than found
    #: by date so the comparison is stable when packs are backfilled.
    previous_pack_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="SET NULL"), nullable=True)

    #: Cached readiness, WITH the time it was computed. Never trusted without
    #: it: a percentage with no timestamp is a number nobody can defend.
    readiness_percent: Mapped[int] = mapped_column(Integer, nullable=False,
                                                   default=0)
    readiness_state: Mapped[str] = mapped_column(String(16), nullable=False,
                                                 default="RED")
    readiness_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: The blocking reasons, each one a sentence naming what and who.
    readiness_reasons: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                    default=list)
    data_state: Mapped[str] = mapped_column(String(16), nullable=False,
                                            default="RED")

    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: Free-text minutes, entered or pasted after the meeting.
    minutes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    demo_origin: Mapped[str] = mapped_column(String(40), nullable=False,
                                             default="", server_default=text("''"))

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    committee: Mapped[PlaybookCommittee] = relationship(back_populates="packs")
    sections: Mapped[list[PlaybookSection]] = relationship(
        back_populates="pack", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("code", name="uq_playbook_pack_code"),
        Index("ix_playbook_packs_committee", "committee_id", "meeting_at"),
        Index("ix_playbook_packs_status", "status", "meeting_at"),
        Index("ix_playbook_packs_owner", "owner_id", "status"),
        Index("ix_playbook_packs_demo", "demo_origin",
              postgresql_where=text("demo_origin <> ''")),
    )


class PlaybookSection(Base):
    """One ordered part of a pack, owned by one person and reviewed by another."""

    __tablename__ = "playbook_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=False)
    #: The template section this came from, so a pack can be compared with its
    #: template and with the same section of the previous pack.
    template_key: Mapped[str] = mapped_column(String(64), nullable=False,
                                              default="")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                 nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                    nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="NOT_STARTED")
    #: A section the pack cannot be approved without.
    required: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    #: What the AI is told this section is for, when it drafts commentary.
    narrative_instructions: Mapped[str] = mapped_column(Text, nullable=False,
                                                        default="")

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                     nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                    nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)

    pack: Mapped[PlaybookPack] = relationship(back_populates="sections")
    blocks: Mapped[list[PlaybookBlock]] = relationship(
        back_populates="section", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_playbook_sections_pack", "pack_id", "position"),
        Index("ix_playbook_sections_owner", "owner_id", "status"),
        Index("ix_playbook_sections_reviewer", "reviewer_id", "status"),
    )


class PlaybookBlock(Base):
    """One piece of content on a page.

    Typed, so the pack knows the difference between a governed figure and a
    sentence somebody wrote. `config` carries what the block needs to be
    re-rendered — metric id, dimension, period, filters, chart type — and
    `snapshot_id` points at the calculated value it is currently showing.
    """

    __tablename__ = "playbook_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_sections.id", ondelete="CASCADE"), nullable=False)
    #: Denormalised so a block can be authorised without loading its section.
    #: Written by the service, never by a caller.
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=False)

    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    #: The words, for a narrative block. Empty for a KPI.
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: FACT / INFERENCE / RECOMMENDATION / OPEN_QUESTION / ... for narrative
    #: blocks. Empty where it does not apply.
    statement_kind: Mapped[str] = mapped_column(String(24), nullable=False,
                                                default="")

    #: What to draw and how: {"metric_id","dimension","chart_type","limit",
    #: "aggregate","sort","direction","compare","columns", ...}
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: A period pinned to this block, overriding the pack's. Empty means the
    #: block follows the pack, which is what almost every block does.
    period: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_snapshots.id", ondelete="SET NULL"), nullable=True)

    #: Set on blocks that came out of an uploaded document, so the pack can say
    #: on the block itself that this is not a governed CreditProbe figure.
    import_class: Mapped[str] = mapped_column(String(32), nullable=False,
                                              default="")

    #: Who wrote this, and whether a person has accepted an AI draft.
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                  nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=SOURCE_UI)
    ai_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                              default=False)
    #: Cleared when the underlying data moves, so a reader is never shown AI
    #: prose written about numbers that have since changed.
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    section: Mapped[PlaybookSection] = relationship(back_populates="blocks")

    __table_args__ = (
        Index("ix_playbook_blocks_section", "section_id", "position"),
        Index("ix_playbook_blocks_pack", "pack_id", "block_type"),
    )


# ================================================================= snapshots


class PlaybookSnapshot(Base):
    """A governed figure, frozen at the moment it entered the pack.

    This table is why an approved pack can be reproduced. It holds the value
    AND everything needed to defend it: the formula version, the period it was
    computed for, the filters, the dataset it read, the numerator and
    denominator, and the run id of the calculation.

    Rows are never updated. Refreshing a draft writes new rows at a new
    `pack_version`; the rows an approved pack points at stay exactly as they
    were.
    """

    __tablename__ = "playbook_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=False)
    #: The pack version this snapshot was calculated at.
    pack_version: Mapped[int] = mapped_column(Integer, nullable=False,
                                              default=1)

    metric_id: Mapped[str] = mapped_column(String(160), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False,
                                             default="")
    #: The definition's own version, so a formula change after approval is
    #: detectable rather than silent.
    metric_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                default="")
    #: A hash of the formula tree. Two snapshots with the same hash were
    #: computed by the same arithmetic whatever the version string says.
    formula_hash: Mapped[str] = mapped_column(String(64), nullable=False,
                                              default="")

    period: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    comparison_period: Mapped[str] = mapped_column(String(32), nullable=False,
                                                   default="")
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    comparison_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The number as it should be READ — "14.1%", "SAR 207.7m". Stored so the
    #: export and the screen cannot round differently.
    display_value: Mapped[str] = mapped_column(String(64), nullable=False,
                                               default="")
    unit: Mapped[str] = mapped_column(String(24), nullable=False,
                                      default="number")
    decimals: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    higher_is_better: Mapped[bool | None] = mapped_column(Boolean,
                                                          nullable=True)

    numerator: Mapped[float | None] = mapped_column(Float, nullable=True)
    denominator: Mapped[float | None] = mapped_column(Float, nullable=True)
    rows_considered: Mapped[int] = mapped_column(Integer, nullable=False,
                                                 default=0)
    #: For a chart or table: the points/rows, exactly as drawn.
    series: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    #: OK / NO_DATA / NOT_MATURED / CALCULATION_FAILED / NOT_AUTHORISED. The
    #: four ways of having no number are four different facts (§3.3).
    availability: Mapped[str] = mapped_column(String(32), nullable=False,
                                              default="OK")
    unavailable_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                    default="")

    dataset: Mapped[str] = mapped_column(String(160), nullable=False,
                                         default="")
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False,
                                                 default="")
    source_fields: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                default=list)
    #: The full working — the definition panel and the calculation trace, as
    #: `backend.metrics.service.value` returns them.
    calculation: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                              default=dict)
    #: The executor's run id, which ties this figure to a Trace.
    run_id: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    sql: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Where it came from, if a Lens tile put it here.
    lens_id: Mapped[int | None] = mapped_column(
        ForeignKey("lenses.id", ondelete="SET NULL"), nullable=True)

    #: Whether the metric was verified against somebody's own number, at the
    #: time this snapshot was taken.
    verification_state: Mapped[str] = mapped_column(String(24), nullable=False,
                                                    default="")
    governed: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=True)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    calculated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                      nullable=True)

    __table_args__ = (
        Index("ix_playbook_snapshots_pack", "pack_id", "pack_version"),
        Index("ix_playbook_snapshots_metric", "pack_id", "metric_id"),
    )


# ================================================================== findings


class PlaybookFinding(Base):
    """A material observation, raised by a rule rather than by a model.

    `rule_key` and `rule_detail` are what make a finding challengeable: the
    pack can show exactly which threshold fired and on what number. §8 forbids
    asking a language model to decide materiality from scratch.
    """

    __tablename__ = "playbook_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=False)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_sections.id", ondelete="SET NULL"), nullable=True)

    finding_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False,
                                          default="MEDIUM")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: The numbers the finding rests on, stated so a reader can check it.
    factual_basis: Mapped[str] = mapped_column(Text, nullable=False, default="")

    metric_id: Mapped[str] = mapped_column(String(160), nullable=False,
                                           default="")
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_snapshots.id", ondelete="SET NULL"), nullable=True)
    period: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    #: The rule that raised it, and its inputs — threshold, observed, movement.
    rule_key: Mapped[str] = mapped_column(String(80), nullable=False,
                                          default="")
    rule_detail: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                              default=dict)
    #: Stable across regenerations, so a finding a person has already answered
    #: is not raised again as a new one.
    fingerprint: Mapped[str] = mapped_column(String(120), nullable=False,
                                             default="")

    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default="OPEN")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                 nullable=True)
    #: The management explanation, if one has been given.
    response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Why it was dismissed. A dismissal without one is refused by the service.
    dismissed_reason: Mapped[str] = mapped_column(Text, nullable=False,
                                                  default="")
    dismissed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                     nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    source: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=SOURCE_SYSTEM)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("pack_id", "fingerprint",
                         name="uq_playbook_finding_print"),
        Index("ix_playbook_findings_pack", "pack_id", "severity", "status"),
    )


# ================================================= decisions and actions


class PlaybookDecision(Base):
    """Something the committee is being asked to decide, and what it decided.

    AI may draft one of these. AI may never move it out of DRAFT: the
    `decided_by` column is written only by a person with APPROVER access, and
    `backend.playbook.access` is where that is enforced.
    """

    __tablename__ = "playbook_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    committee_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_committees.id", ondelete="CASCADE"),
        nullable=False)
    pack_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="SET NULL"), nullable=True)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_sections.id", ondelete="SET NULL"), nullable=True)

    reference: Mapped[str] = mapped_column(String(40), nullable=False,
                                           default="")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False,
                                                default="")
    alternatives: Mapped[list] = mapped_column(JSONB, nullable=False,
                                               default=list)
    impact: Mapped[str] = mapped_column(Text, nullable=False, default="")

    status: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="DRAFT")
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                     nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                 nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    decision_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="")

    source: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=SOURCE_UI)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_playbook_decisions_pack", "pack_id", "status"),
        Index("ix_playbook_decisions_committee", "committee_id", "status"),
    )


class PlaybookAction(Base):
    """Something somebody agreed to do, and where the work actually lives.

    `planner_task_id` is the link to the Project Planner. Playbook holds the
    governance record — which committee asked for this, off which decision, in
    which pack — and the Planner holds the task. There is no second scheduler
    and no second progress field that could disagree with the Planner's.
    """

    __tablename__ = "playbook_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    committee_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_committees.id", ondelete="CASCADE"),
        nullable=False)
    pack_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="SET NULL"), nullable=True)
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_decisions.id", ondelete="SET NULL"), nullable=True)

    reference: Mapped[str] = mapped_column(String(40), nullable=False,
                                           default="")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                 nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False,
                                          default="MEDIUM")
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default="DRAFT")
    latest_update: Mapped[str] = mapped_column(Text, nullable=False,
                                               default="")
    closure_evidence: Mapped[str] = mapped_column(Text, nullable=False,
                                                  default="")

    #: The Planner is the execution source of truth. These are a link, not a
    #: copy: progress and status are read from the task, never mirrored here.
    planner_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_projects.id", ondelete="SET NULL"), nullable=True)
    planner_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("planner_tasks.id", ondelete="SET NULL"), nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    linked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                  nullable=True)

    source: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=SOURCE_UI)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_playbook_actions_committee", "committee_id", "status"),
        Index("ix_playbook_actions_owner", "owner_id", "status", "due_date"),
        Index("ix_playbook_actions_task", "planner_task_id"),
    )


# ===================================================== review and approval


class PlaybookReview(Base):
    """One review of one section, or of the whole pack.

    Tied to the exact version reviewed. A reviewer who approved version 4 has
    not approved version 5, and `backend.playbook.access` refuses an approval
    whose `at_version` is behind the pack.
    """

    __tablename__ = "playbook_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=False)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_sections.id", ondelete="CASCADE"), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False,
                                       default="SECTION")

    reviewer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False,
                                          default="PENDING")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: The pack version this review was given against.
    at_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                     nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_playbook_reviews_pack", "pack_id", "decision"),
        Index("ix_playbook_reviews_reviewer", "reviewer_id", "decision"),
        Index("ix_playbook_reviews_section", "section_id", "decision"),
    )


class PlaybookVersion(Base):
    """An immutable copy of a whole pack at one version.

    Written when a pack is approved and when an amendment supersedes one. This
    is what "compare with the previous approved pack" reads, and what proves an
    approved pack has not been edited since: the document is stored, not
    regenerated.
    """

    __tablename__ = "playbook_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: draft | approved | superseded
    kind: Mapped[str] = mapped_column(String(24), nullable=False,
                                      default="draft")
    #: The whole pack as a document: sections, blocks, snapshot values,
    #: findings, decisions. Read back verbatim; never recomputed.
    document: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: SHA-256 of the canonical document, so a change is detectable.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("pack_id", "version", "kind",
                         name="uq_playbook_version"),
        Index("ix_playbook_versions_pack", "pack_id", "version"),
    )


# =============================================================== the record


class PlaybookEvent(Base):
    """Append-only history. What changed, who changed it, and through which door.

    The same shape as `planner_updates`, deliberately: one person reading a
    committee's history and a project's history should be reading one
    vocabulary. Nothing updates or deletes a row here.
    """

    __tablename__ = "playbook_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=True)
    committee_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_committees.id", ondelete="CASCADE"),
        nullable=True)

    #: pack | section | block | finding | decision | action | review | committee
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entity_ref: Mapped[str] = mapped_column(String(64), nullable=False,
                                            default="")
    #: created | updated | submitted | reviewed | approved | generated | ...
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    #: {field: [before, after]} — the same shape the planner uses.
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")

    at_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                  nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=SOURCE_UI)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_playbook_events_pack", "pack_id", "created_at"),
        Index("ix_playbook_events_entity", "entity_type", "entity_id"),
    )


class PlaybookReminder(Base):
    """One notification the agent has already sent.

    The fingerprint is what stops a sweep sending the same reminder every hour.
    Same mechanism as `planner_reminders`, and the same reason: a reminder loop
    with no memory trains people to ignore it.
    """

    __tablename__ = "playbook_reminders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=True)
    committee_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_committees.id", ondelete="CASCADE"),
        nullable=True)
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False,
                                             default="pack")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    #: input | review | approval | data | escalation | schedule
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    notification_id: Mapped[int | None] = mapped_column(BigInteger,
                                                        nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String(16), nullable=False,
                                       default="sent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_playbook_reminder_print"),
        Index("ix_playbook_reminders_pack", "pack_id", "trigger"),
        Index("ix_playbook_reminders_user", "user_id", "created_at"),
    )


class PlaybookSource(Base):
    """Where a figure or a statement came from, and uploaded supporting material.

    One table for both because they answer the same question — "what is this
    based on?" — and a reader following a citation should not have to know
    whether the answer is a governed metric or a PDF somebody attached.
    """

    __tablename__ = "playbook_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("playbook_packs.id", ondelete="CASCADE"), nullable=False)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_sections.id", ondelete="SET NULL"), nullable=True)
    block_id: Mapped[int | None] = mapped_column(
        ForeignKey("playbook_blocks.id", ondelete="CASCADE"), nullable=True)

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    #: What it points at, in the same (type, id) shape the platform uses
    #: elsewhere — metric id, lens id, dataset name, planner task id.
    reference: Mapped[str] = mapped_column(String(240), nullable=False,
                                           default="")
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: For an uploaded document: where the bytes are, and what they are.
    filename: Mapped[str] = mapped_column(String(255), nullable=False,
                                          default="")
    content_type: Mapped[str] = mapped_column(String(120), nullable=False,
                                              default="")
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                           default=0)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False,
                                             default="")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False,
                                          default="")
    #: How imported content is classified, so a number lifted out of a
    #: PowerPoint is never shown as though CreditProbe calculated it.
    import_class: Mapped[str] = mapped_column(String(32), nullable=False,
                                              default="")
    #: Warnings raised while extracting — a page that could not be read, a
    #: table whose columns did not line up.
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                    nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_playbook_sources_pack", "pack_id", "kind"),
        Index("ix_playbook_sources_block", "block_id"),
    )


__all__ = [
    "ACCESS_RANK",
    "ACCESS_ROLES",
    "ACTION_STATUSES",
    "BLOCK_TYPES",
    "BUSINESS_ROLES",
    "CADENCES",
    "CALCULATED_BLOCK_TYPES",
    "IMPORTED_TABLE",
    "carries_a_figure",
    "CONFIDENTIALITY",
    "DECISION_STATUSES",
    "EDITABLE_PACK_STATUSES",
    "FINDING_STATUSES",
    "FINDING_TYPES",
    "IMPORT_CLASSES",
    "LOCKED_PACK_STATUSES",
    "PACK_STATUSES",
    "PRIORITIES",
    "REVIEW_DECISIONS",
    "REVIEW_SCOPES",
    "SECTION_STATUSES",
    "SEVERITIES",
    "SEVERITY_RANK",
    "SOURCES",
    "SOURCE_AI",
    "SOURCE_AI_CHAT",
    "SOURCE_API",
    "SOURCE_IMPORT",
    "SOURCE_KINDS",
    "SOURCE_SYSTEM",
    "SOURCE_UI",
    "STATEMENT_KINDS",
    "TEMPLATE_STATUSES",
    "UNAVAILABLE_REASONS",
    "PlaybookAction",
    "PlaybookBlock",
    "PlaybookCommittee",
    "PlaybookDecision",
    "PlaybookEvent",
    "PlaybookFinding",
    "PlaybookMember",
    "PlaybookPack",
    "PlaybookReminder",
    "PlaybookReview",
    "PlaybookSection",
    "PlaybookSnapshot",
    "PlaybookSource",
    "PlaybookTemplate",
    "PlaybookVersion",
]
