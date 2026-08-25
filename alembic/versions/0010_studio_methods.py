"""Methods the bank authored, forked or edited.

Library methods ship as code. These belong to the bank — how it has decided to
measure something, and the trail of who decided it. The definition is one JSON
document because what a method IS keeps growing; the columns are only the ones
something other than the Studio has to query on.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("method_id", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False,
                  server_default=""),
        sa.Column("lifecycle", sa.String(length=32), nullable=False,
                  server_default="DRAFT"),
        sa.Column("version", sa.String(length=24), nullable=False,
                  server_default="1.0.0"),
        sa.Column("forked_from", sa.String(length=160), nullable=False,
                  server_default=""),
        sa.Column("definition", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("method_id", name="uq_studio_method_id"),
    )
    op.create_index("ix_studio_methods_lifecycle", "studio_methods", ["lifecycle"])
    op.create_index("ix_studio_methods_category", "studio_methods", ["category"])


def downgrade() -> None:
    op.drop_index("ix_studio_methods_category", table_name="studio_methods")
    op.drop_index("ix_studio_methods_lifecycle", table_name="studio_methods")
    op.drop_table("studio_methods")
