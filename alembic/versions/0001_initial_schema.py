"""initial schema — dataset versions/sheets, users, ai usage log

Revision ID: 0001
Revises:
Create Date: 2026-07-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="analyst"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_filename", sa.Text, nullable=False),
        sa.Column("origin", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_report", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("quarter_sheets", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("sheet_row_counts", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    # At most one active dataset version at any time.
    op.create_index(
        "one_active_dataset",
        "dataset_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "dataset_sheets",
        sa.Column("dataset_version_id", sa.Integer,
                  sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sheet_name", sa.String(64), primary_key=True),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("parquet", sa.LargeBinary, nullable=False),
    )

    op.create_table(
        "ai_usage_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB, nullable=True),
        sa.Column("prompt_chars", sa.Integer, nullable=True),
        sa.Column("completion_chars", sa.Integer, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ai_usage_log")
    op.drop_table("dataset_sheets")
    op.drop_index("one_active_dataset", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_table("users")
