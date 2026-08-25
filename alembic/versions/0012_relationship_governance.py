"""Relationships become governed objects the runtime can trust.

The dynamic planner is about to start composing joins from these rows, which
means a relationship stops being documentation and becomes executable. So it
gains a lifecycle (only ACTIVE runs), a version (stamped onto every Trace that
used it, so a governance edit cannot silently rewrite history), a confidence, a
join policy, a temporal rule for as-of joins across a frequency change, and the
validation statistics — match rate, orphans, duplicates — that decide whether it
may be promoted at all.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

COLUMNS = [
    ("lifecycle", sa.String(length=16), "draft"),
    ("version", sa.Integer(), "1"),
    ("is_preferred", sa.Boolean(), "true"),
    ("confidence", sa.Float(), "1.0"),
    ("join_policy", sa.String(length=16), "inner"),
    ("temporal_rule", sa.String(length=32), "same_period"),
]


def upgrade() -> None:
    for name, type_, default in COLUMNS:
        op.add_column("dataset_relationships",
                      sa.Column(name, type_, nullable=False, server_default=default))
    op.add_column("dataset_relationships",
                  sa.Column("semantic", sa.Text(), nullable=False, server_default=""))
    for name in ("match_rate", "orphan_rate", "duplicate_rate"):
        op.add_column("dataset_relationships", sa.Column(name, sa.Float(), nullable=True))
    op.add_column("dataset_relationships",
                  sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dataset_relationships",
                  sa.Column("validation", postgresql.JSONB(), nullable=False,
                            server_default=sa.text("'{}'::jsonb")))
    op.create_index("ix_dataset_relationships_lifecycle", "dataset_relationships",
                    ["lifecycle"])

    op.create_table(
        "dataset_relationship_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("relationship_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["relationship_id"], ["dataset_relationships.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("relationship_id", "version", name="uq_relationship_version"),
    )


def downgrade() -> None:
    op.drop_table("dataset_relationship_versions")
    op.drop_index("ix_dataset_relationships_lifecycle",
                  table_name="dataset_relationships")
    for name in ("validation", "validated_at", "duplicate_rate", "orphan_rate",
                 "match_rate", "semantic"):
        op.drop_column("dataset_relationships", name)
    for name, _, _ in COLUMNS:
        op.drop_column("dataset_relationships", name)
