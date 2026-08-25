"""How each person likes to look at each dataset.

Column widths, hidden columns, frozen count and row density, stored per user and
per dataset. Per user rather than per browser: somebody who spends an afternoon
arranging the facility grid should find it arranged the next morning, and on the
other machine.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grid_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dataset", sa.String(length=160), nullable=False),
        sa.Column("preferences", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "dataset", name="uq_grid_preference"),
    )


def downgrade() -> None:
    op.drop_table("grid_preferences")
