"""A person's own working set on the Borrower 360. B12.

Two things a credit officer does between sessions and could not do before:
keep a borrower to hand, and keep a search worth running again.

Both live in one table because they are the same kind of object — a
person's working set, scoped to them and to their tenant. Neither is a
property of the borrower, and neither is shared: a pinned name is somebody's
judgement about what to watch this week, and publishing one person's watch
list to their team is a different feature needing a different approval.

A saved cohort stores the QUERY rather than the borrower ids it matched. The
corporate book is rebuilt quarterly, so a stored id list would quietly stop
meaning what it meant — "Contracting names over the group limit" is still
that question next quarter, and the ids it returns are not.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

TABLE = "borrower_360_workspace"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("user_id", sa.BigInteger(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False,
                  server_default=""),
        sa.Column("query", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("position", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("noted", sa.String(length=240), nullable=False,
                  server_default=""),
        sa.Column("tenant", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant", "user_id", "kind", "reference",
                            name="uq_borrower_360_workspace"),
    )
    op.create_index("ix_borrower_360_workspace_user", TABLE,
                    ["tenant", "user_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_borrower_360_workspace_user", table_name=TABLE)
    op.drop_table(TABLE)
