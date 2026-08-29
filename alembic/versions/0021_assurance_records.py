"""§180's Investigation Assurance Record, and §208's retention rule.

One row per answered turn. The table is append-only by intent rather than by
constraint: §208 says historical scores are not rewritten, and the two columns
that DO change after insert (the feedback counts and `superseded_by`) are
deliberately the ones that record what happened AROUND the record rather than
what it concluded.

Staleness is not stored. A record is stale relative to a runtime, not in
itself, so it is computed at read time against the current build and releases
— which is what lets the row keep saying what was true when it was written.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assurance_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("assurance_record_id", sa.String(64), nullable=False),
        sa.Column("record_version", sa.String(16), nullable=False,
                  server_default="1.0.0"),

        sa.Column("tenant_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("investigation_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("project_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("message_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("answer_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("trace_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("agentic_run_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("answer_type", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("portfolio_scope", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("language", sa.String(8), nullable=False,
                  server_default="en"),
        sa.Column("turn_index", sa.Integer(), nullable=False,
                  server_default="0"),

        sa.Column("build_sha", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("app_version", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("intelligence_release_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("teaching_release_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("ontology_version", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("routing_policy_version", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("officer_level", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("model_route", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("blueprint_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("case_family", sa.String(48), nullable=False,
                  server_default=""),

        sa.Column("overall_status", sa.String(32), nullable=False,
                  server_default=""),
        # Nullable on purpose: the gates refuse a number more often than they
        # award one, and 0.0 would read as a very bad score rather than as no
        # score at all.
        sa.Column("operational_assurance", sa.Float(), nullable=True),
        sa.Column("coverage_pct", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("reference_match_pct", sa.Float(), nullable=True),
        sa.Column("reference_source", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("critical_failure_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("weights_version", sa.String(16), nullable=False,
                  server_default=""),

        sa.Column("checks", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("dimension_results", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("objective_coverage", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("limitations", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("context", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("repair_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("clarification_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fingerprint", sa.String(64), nullable=False,
                  server_default=""),

        sa.Column("good_feedback_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("bad_feedback_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("superseded_by", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("rerun_of", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                ondelete="SET NULL"),
        sa.UniqueConstraint("assurance_record_id",
                            name="uq_assurance_record_id"),
    )
    op.create_index("ix_assurance_investigation", "assurance_records",
                    ["investigation_id", "turn_index"])
    op.create_index("ix_assurance_recent", "assurance_records", ["created_at"])
    op.create_index("ix_assurance_status", "assurance_records",
                    ["overall_status", "created_at"])
    op.create_index("ix_assurance_user", "assurance_records",
                    ["user_id", "created_at"])
    op.create_index("ix_assurance_project", "assurance_records",
                    ["project_id", "created_at"])
    op.create_index("ix_assurance_release", "assurance_records",
                    ["intelligence_release_id", "created_at"])
    op.create_index("ix_assurance_answer", "assurance_records", ["answer_id"])


def downgrade() -> None:
    for name in ("ix_assurance_answer", "ix_assurance_release",
                 "ix_assurance_project", "ix_assurance_user",
                 "ix_assurance_status", "ix_assurance_recent",
                 "ix_assurance_investigation"):
        op.drop_index(name, table_name="assurance_records")
    op.drop_table("assurance_records")
