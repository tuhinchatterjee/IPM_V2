"""A reminder records how far up the ladder it went.

`trigger` already says WHAT happened — overdue, blocked, the sponsor alert.
It does not say HOW FAR the message travelled, and "was the sponsor told?" is
the question a governance review actually asks. Deriving it from the trigger
would work for two of the five rungs and guess at the rest.

Empty for a plain reminder to the person who owns the work, which is not an
escalation at all.

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "planner_reminders",
        sa.Column("level", sa.String(length=16), nullable=False,
                  server_default=sa.text("''")))


def downgrade() -> None:
    op.drop_column("planner_reminders", "level")
