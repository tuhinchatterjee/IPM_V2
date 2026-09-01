"""Which reader produced the answer somebody rated. §11.

An answer's feedback already recorded WHAT was rated (the answer, the plan
fingerprint), WHO rated it, WHEN, and WHAT BUILD it came from. It did not
record HOW the question was read, and on a deployment with no external
provider that is the single largest difference between two answers to the
same question: the deterministic reader over the governed catalogue
understands credit concepts but not arbitrary phrasing, so "not helpful" on
an offline reading and "not helpful" on a live one are two different defects
with two different owners.

Without it, an aggregated view of the feedback cannot tell a reviewer whether
the phrasing failed or the analysis did, and a governed review workflow that
cannot separate those will spend its time on the wrong half.

Captured server-side from the provider's own state rather than sent by the
browser, because a client can be wrong about it and a rating attributed to
the wrong reader is worse than one with no reader at all.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows keep "" rather than being guessed at. A backfill would
    # assert a reader for answers produced before this column existed, and an
    # invented provenance is worse than a missing one.
    op.add_column(
        "answer_feedback",
        sa.Column("planner_mode", sa.String(length=32), nullable=False,
                  server_default=""))
    op.add_column(
        "answer_feedback",
        sa.Column("model", sa.String(length=64), nullable=False,
                  server_default=""))
    op.create_index("ix_answer_feedback_mode", "answer_feedback",
                    ["tenant", "planner_mode", "direction"])


def downgrade() -> None:
    op.drop_index("ix_answer_feedback_mode", table_name="answer_feedback")
    op.drop_column("answer_feedback", "model")
    op.drop_column("answer_feedback", "planner_mode")
