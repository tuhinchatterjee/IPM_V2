"""A snapshot carries the whole context of the reading it froze. Gate 5.

`playbook_metric_snapshots` held unit, period and as-of, which is enough to
show a value and not enough to decide whether two values are the same series.
Currency, population, segment and scenario are what separate a retail rate
from a corporate one and a base case from a downturn — and a comparison that
cannot see them will happily subtract one from the other and present the
result as a movement.

So THEN carries the same context NOW does, and `compare` refuses rather than
misleads when they disagree.

Additive. Nothing existing is altered or dropped.

Revision ID: 0037
Revises: 0036
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

_COLUMNS = (("currency", 16), ("population", 160), ("segment", 160),
            ("scenario", 96))


def upgrade() -> None:
    for name, length in _COLUMNS:
        op.add_column("playbook_metric_snapshots",
                      sa.Column(name, sa.String(length), nullable=False,
                                server_default=""))


def downgrade() -> None:
    for name, _ in _COLUMNS:
        op.drop_column("playbook_metric_snapshots", name)
