"""Data domains gain a status.

A domain that is no longer being loaded should come off the working list without
anything it contains breaking. That is the difference between archiving and
deleting, and it needs somewhere to be recorded.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A server default so existing rows become ACTIVE without a second pass,
    # then dropped so the application decides the value from here on.
    op.add_column(
        "data_domains",
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="ACTIVE"),
    )
    op.alter_column("data_domains", "status", server_default=None)


def downgrade() -> None:
    op.drop_column("data_domains", "status")
