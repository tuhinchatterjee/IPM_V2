"""§33's fuller active-learning capture.

Seven columns the review queue was missing: what the USER said (as opposed to
what a reviewer concluded), which teaching cases the failing run was shown,
what the invariants said, the prose that was displayed, the release the run was
served by, the release an approved correction went into, and the teaching case
it became.

The two release columns are §33's "release inclusion", and they exist because
a correction that has been approved and not released has not fixed anything
yet — which is exactly the state that looks finished on a review screen.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("user_correction", sa.Text(), ""),
    ("observed_interpretation", sa.Text(), ""),
    ("observed_release_id", sa.String(64), ""),
    ("included_in_release", sa.String(64), ""),
    ("teaching_case_id", sa.String(64), ""),
)


def upgrade() -> None:
    for name, kind, default in _COLUMNS:
        op.add_column("review_queue_items",
                      sa.Column(name, kind, nullable=False,
                                server_default=default))
    op.add_column("review_queue_items",
                  sa.Column("retrieved_case_ids", postgresql.JSONB(),
                            nullable=False,
                            server_default=sa.text("'[]'::jsonb")))
    op.add_column("review_queue_items",
                  sa.Column("observed_invariants", postgresql.JSONB(),
                            nullable=False,
                            server_default=sa.text("'{}'::jsonb")))
    op.create_index("ix_review_queue_release", "review_queue_items",
                    ["included_in_release"])


def downgrade() -> None:
    op.drop_index("ix_review_queue_release", table_name="review_queue_items")
    for name in ("observed_invariants", "retrieved_case_ids",
                 *[c[0] for c in _COLUMNS]):
        op.drop_column("review_queue_items", name)
