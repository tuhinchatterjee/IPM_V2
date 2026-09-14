"""Section status transitions, kept beside the section. Gate 4.

A status that changes with no record of who changed it, when, or from what is
not auditable — and "Approved" is exactly the status a governed document must
be able to account for months later. `history` is an append-only list on the
section row, so the audit travels with the thing it describes and a dashboard
that shows a section's state can show how it got there without a second query.

Additive. Nothing existing is altered or dropped.

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playbook_document_sections",
        sa.Column("history", JSONB, nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("playbook_document_sections", "history")
