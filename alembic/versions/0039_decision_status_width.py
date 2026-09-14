"""Widen playbook_decisions.status and correct its default. Gate 7.

Two defects in one column
-------------------------
**The width.** `0035` sized this column at 16 characters, when the only
statuses it had to carry were short. §6C names five, and one of them —
``ready_for_decision`` — is eighteen characters long. Writing it raised
``StringDataRightTruncation`` at the database, after the audit entry had
already been appended in memory.

The alternative was to shorten the vocabulary. That was rejected: the status
is read by people on the dashboard and named in the specification, and a
column width is not a reason to call a thing something else. 32 characters
holds the vocabulary as it stands without inviting a free-text status.

**The default.** `0035` defaulted the column to ``outstanding``, a word from
the vocabulary that preceded §6C and is not one of the five statuses. A row
created without an explicit status would therefore land in a state
`move_decision` refuses to move out of — a decision that could never be
recorded. Any such row is moved to ``proposed`` here, which is what it meant.

Widening a ``varchar`` is metadata-only in PostgreSQL and rewrites no rows.
The downgrade narrows it again, which can only run while every stored status
still fits; that is asserted rather than assumed.

Revision ID: 0039
Revises: 0038
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "playbook_decisions", "status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
        server_default="proposed",
    )
    op.execute(
        "UPDATE playbook_decisions SET status = 'proposed' "
        "WHERE status = 'outstanding'"
    )


def downgrade() -> None:
    too_long = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM playbook_decisions WHERE length(status) > 16"
    )).scalar_one()
    if too_long:
        raise RuntimeError(
            f"{too_long} decision(s) hold a status longer than 16 characters; "
            "narrowing the column would truncate them. Move those decisions "
            "to a shorter status first."
        )
    op.alter_column(
        "playbook_decisions", "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
        server_default="outstanding",
    )
