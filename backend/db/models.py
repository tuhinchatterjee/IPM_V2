"""
ORM models — the production schema.

Portfolio data lifecycle:
  * DatasetVersion — one row per uploaded (or the bundled) workbook, with its
    validation report and status. A partial unique index enforces exactly one
    `active` version at a time.
  * DatasetSheet — the sheet payloads for a version, each stored as a Parquet
    blob (dtype-faithful, so aggregations reproduce byte-identical figures).

Also created here (populated in later phases):
  * User — app-login accounts (Phase 3).
  * AiUsageLog — per-request AI usage/audit rows, no prompt text or PII (Phase 4).
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
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base

# Dataset version lifecycle states.
STATUS_STAGED = "staged"
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_REJECTED = "rejected"


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="uploaded")  # bundled|uploaded
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    quarter_sheets: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sheet_row_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    sheets: Mapped[list[DatasetSheet]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )

    # Only one version may be 'active' at any time.
    __table_args__ = (
        Index(
            "one_active_dataset",
            "status",
            unique=True,
            postgresql_where=(status == STATUS_ACTIVE),
        ),
    )


class DatasetSheet(Base):
    __tablename__ = "dataset_sheets"

    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), primary_key=True
    )
    sheet_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parquet: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    version: Mapped[DatasetVersion] = relationship(back_populates="sheets")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    #: ADMIN | DATA_STEWARD | ANALYST | VIEWER, stored upper-case to match
    #: backend/api/permissions.Role. Older rows may carry the lower-case
    #: "admin"/"analyst" of the Dash era; the API normalises when it reads.
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="ANALYST")
    #: What the product calls the person. The greeting uses the first name, so a
    #: blank one falls back to the username rather than to "there".
    first_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: Free text: "Credit Risk Analytics", "IFRS 9 Committee".
    team: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    #: What this person DOES — "Corporate Credit Manager", "IFRS 9 Manager".
    #: Distinct from `role`, which is what they may do. A directory that shows
    #: four people all labelled ANALYST tells a sender nothing about which of
    #: them owns the shipping book, and picking the wrong reviewer is a real
    #: cost of collapsing the two.
    job_title: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    #: The organisational unit. `team` is the working group; this is the part
    #: of the bank it sits in, and a directory is searched by both.
    department: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )
    #: When and by whom the account was suspended. Kept rather than inferred
    #: from `is_active` alone: "deactivated" is an event somebody performed,
    #: and reactivating must not erase that it happened.
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deactivated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiUsageLog(Base):
    __tablename__ = "ai_usage_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prompt_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok|error|rate_limited
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
