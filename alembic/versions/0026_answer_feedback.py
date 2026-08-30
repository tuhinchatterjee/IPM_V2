"""§39-§45: per-answer feedback and what a correction becomes.

Two tables, and the split is the governance.

    answer_feedback         what the user said. Immutable, with no status
                            column: what somebody said in March does not
                            change when we decide what to do about it.
    answer_feedback_status  one row per transition through §45's states —
                            Received, Under Review, Fixed, Released, and
                            Reviewed-not-changing. The history rather than
                            the current value, so "how long did this sit
                            unreviewed?" and "who decided not to fix it?"
                            are both answerable.

Neither table has a `weight` or a `gold` column. §41: good feedback is not
automatically gold. §44: raw thumbs do not change validation scores. A
column that could carry a weight is a column somebody eventually multiplies
a score by.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE answer_feedback (
            id BIGSERIAL NOT NULL,
            feedback_id VARCHAR(48) NOT NULL,
            answer_id VARCHAR(64) NOT NULL,
            direction VARCHAR(8) NOT NULL,
            answer_kind VARCHAR(32) NOT NULL,
            language VARCHAR(8) NOT NULL,
            reasons JSONB NOT NULL,
            correction JSONB NOT NULL,
            anchor_kind VARCHAR(24) NOT NULL,
            anchor_ref VARCHAR(240) NOT NULL,
            build_sha VARCHAR(40) NOT NULL,
            plan_fingerprint VARCHAR(64) NOT NULL,
            teaching_release_id VARCHAR(64) NOT NULL,
            investigation_id VARCHAR(64) NOT NULL,
            immediate_changes JSONB NOT NULL,
            governed_fields JSONB NOT NULL,
            ledger_entry_id VARCHAR(48) NOT NULL,
            user_id VARCHAR(64) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_answer_feedback UNIQUE (feedback_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_answer_feedback_kind ON answer_feedback (tenant, answer_kind, direction)")
    op.execute("CREATE INDEX ix_answer_feedback_user ON answer_feedback (tenant, user_id, created_at)")
    op.execute("CREATE INDEX ix_answer_feedback_answer ON answer_feedback (answer_id)")

    op.execute(
        """
        CREATE TABLE answer_feedback_status (
            id BIGSERIAL NOT NULL,
            feedback_id VARCHAR(48) NOT NULL,
            status VARCHAR(32) NOT NULL,
            reason TEXT NOT NULL,
            by VARCHAR(64) NOT NULL,
            linked_kind VARCHAR(32) NOT NULL,
            linked_id VARCHAR(64) NOT NULL,
            release_id VARCHAR(64) NOT NULL,
            score_impact JSONB NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id)
        )
        """
    )
    op.execute("CREATE INDEX ix_answer_feedback_status_fb ON answer_feedback_status (feedback_id, created_at)")
    op.execute("CREATE INDEX ix_answer_feedback_status_open ON answer_feedback_status (tenant, status)")


def downgrade() -> None:
    op.drop_table("answer_feedback_status")
    op.drop_table("answer_feedback")

