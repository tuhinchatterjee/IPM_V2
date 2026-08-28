"""Record every workbook download.

§41 of the export contract. A workbook leaves the product: it lands on a
laptop, it is forwarded, and the question six months later is never "did an
export happen" but "which figures, from which data version, did that file
carry, and who was entitled to it".

So every attempt gets a row — allowed, denied or failed alike. A log that
recorded only successes could not answer "who tried", which is the question an
access review actually asks.

Append-only by convention rather than by constraint: nothing in the product
updates or deletes these rows, and the audit history reads them in order.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("object_type", sa.String(length=48), nullable=False,
                  server_default="analysis_run"),
        sa.Column("object_id", sa.String(length=120), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("trace_version", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=24), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="allowed"),
        sa.Column("authorization", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("filename", sa.String(length=255), nullable=False,
                  server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("datasets", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="[]"),
        sa.Column("redactions", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="[]"),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_export_records_object", "export_records",
                    ["object_type", "object_id", "created_at"])
    op.create_index("ix_export_records_user", "export_records",
                    ["user_id", "created_at"])
    op.create_index("ix_export_records_run", "export_records",
                    ["run_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_export_records_run", table_name="export_records")
    op.drop_index("ix_export_records_user", table_name="export_records")
    op.drop_index("ix_export_records_object", table_name="export_records")
    op.drop_table("export_records")
