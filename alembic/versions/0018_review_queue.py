"""The Intelligence Review Queue.

P0.15. A place to put a reviewed failure, with what the right answer would
have been written in the same shape the curriculum specifies a case — so an
approved item becomes something the factory can measure against rather than
something a person has to read and reinterpret.

Two rules are load-bearing and both are about the human in the middle. Nothing
enters the curriculum without an adjudication and a reason. And nothing here
trains anything: approved items become CASES, and no weight anywhere changes
because of a row in this table.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_queue_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),

        # What happened.
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("current_reading", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("observed_plan", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("observed_result", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_layer", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("failure_category", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("observed_problem", sa.Text(), nullable=False,
                  server_default=""),

        # What it should have been.
        sa.Column("corrected_reading", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("corrected_expectations", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),

        # The human in the middle.
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="CAPTURED"),
        sa.Column("adjudicated_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("adjudicated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adjudication_note", sa.Text(), nullable=False,
                  server_default=""),

        # What happened after.
        sa.Column("regression_status", sa.String(16), nullable=False,
                  server_default="NOT_TESTED"),
        sa.Column("regression_checked_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("curriculum_case_id", sa.String(64), nullable=False,
                  server_default=""),

        sa.Column("source", sa.String(24), nullable=False,
                  server_default="manual"),
        sa.Column("run_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_review_queue_status", "review_queue_items",
                    ["status", "created_at"])
    op.create_index("ix_review_queue_layer", "review_queue_items",
                    ["failure_layer"])
    op.create_index("ix_review_queue_regression", "review_queue_items",
                    ["regression_status"])


def downgrade() -> None:
    op.drop_index("ix_review_queue_regression", table_name="review_queue_items")
    op.drop_index("ix_review_queue_layer", table_name="review_queue_items")
    op.drop_index("ix_review_queue_status", table_name="review_queue_items")
    op.drop_table("review_queue_items")
