"""One period of one dataset, staged and then published.

Why a period release is not a dataset version
----------------------------------------------
`data_versions` records the whole dataset at a moment, and publishing one
rewrites every period of it. That is right when a book is loaded in full and
wrong when a steward sends the next quarter: adding Q3 2026 to a fifteen-quarter
book must not require re-sending fourteen quarters, and must not delete them if
it does.

`data_period_releases` is scoped to a period and versioned within it. Replacing
Q1 2025 creates version 2 and marks version 1 SUPERSEDED; both rows stay,
because an investigation run last quarter still names the version it read and a
lineage that deletes its own history cannot answer "what did we see at the
time".

Why the states are a column and not a boolean
----------------------------------------------
Publication is never a side effect of an upload. A file that arrives is
UPLOADED; everything after that is something a check or a person did to it, and
each transition is recorded with who did it and why. A file that fails its
contract stops at FAILED rather than being published with warnings, because a
period a reader can see is a period they will act on.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_period_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(),
                  sa.ForeignKey("dataset_definitions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("period", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("mode", sa.String(length=24), nullable=False,
                  server_default="NEW_PERIOD"),
        sa.Column("state", sa.String(length=24), nullable=False,
                  server_default="UPLOADED"),
        sa.Column("row_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("field_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("staged_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_path", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("source_filename", sa.String(length=255), nullable=False,
                  server_default=""),
        sa.Column("source_sha256", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("validation", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.Integer(),
                  sa.ForeignKey("data_period_releases.id",
                                ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("dataset_id", "period", "version",
                            name="uq_period_release"),
    )
    op.create_index("ix_period_release_dataset", "data_period_releases",
                    ["dataset_id", "period"])
    op.create_index("ix_period_release_state", "data_period_releases",
                    ["state"])


def downgrade() -> None:
    op.drop_index("ix_period_release_state", table_name="data_period_releases")
    op.drop_index("ix_period_release_dataset",
                  table_name="data_period_releases")
    op.drop_table("data_period_releases")
