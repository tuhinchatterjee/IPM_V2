"""Files that arrived, and what was decided about them.

Data arrives monthly, from a system, into a folder. The interesting question is
never "did the load succeed" but "is this the same shape as last time, and does
anybody know if it is not". Every arrival gets a row here whether it was
published or held, with the drift report and the reason attached.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_inbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_format", sa.String(length=16), nullable=False,
                  server_default="csv"),
        sa.Column("file_sha256", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("dataset", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("match_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("match_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="received"),
        sa.Column("decision", sa.String(length=24), nullable=False, server_default=""),
        sa.Column("decision_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("profile", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("drift", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("upload_id", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["upload_id"], ["dataset_uploads.id"],
                                ondelete="SET NULL"),
    )
    op.create_index("ix_data_inbox_status", "data_inbox", ["status", "received_at"])
    op.create_index("ix_data_inbox_dataset", "data_inbox", ["dataset"])


def downgrade() -> None:
    op.drop_index("ix_data_inbox_dataset", table_name="data_inbox")
    op.drop_index("ix_data_inbox_status", table_name="data_inbox")
    op.drop_table("data_inbox")
