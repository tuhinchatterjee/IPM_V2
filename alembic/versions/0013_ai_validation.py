"""AI validation runs, and room for the status the orchestrator actually writes.

Two things.

**A widened status column.** `analysis_runs.status` was sixteen characters, and
`needs_clarification` is nineteen. Every question CreditProbe stopped to ask
about failed to persist with a truncation error, which left the answer on screen
carrying no run id — and therefore a dead Trace button. It went unnoticed while a
fallback quietly turned most of those questions into `succeeded` instead.

**Somewhere to keep an intelligence check.** A score is only useful next to the
last one: "94 on Tuesday, 79 today" is what tells somebody that a model change, a
prompt change or a data change broke something. Each run records what it was
validating — provider, model, build, benchmark version, data version — so a
score can be marked stale when any of those move on.

The benchmark's expected answers are NOT stored here. Gold data lives in the
evaluation package, is loaded only after execution, and is never reachable from
production orchestration. See backend/validation/.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("analysis_runs", "status",
                    existing_type=sa.String(length=16),
                    type_=sa.String(length=32), existing_nullable=False)

    op.create_table(
        "ai_validation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("model", sa.String(length=128), nullable=False,
                  server_default=""),
        sa.Column("build_sha", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("app_version", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("benchmark_version", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("data_version", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("ai_state", sa.String(length=24), nullable=False,
                  server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="completed"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("band", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("partial", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("components", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("selected_ids", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("notes", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
    )
    op.create_index("ix_ai_validation_runs_created", "ai_validation_runs",
                    ["created_at"])

    op.create_table(
        "ai_validation_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(),
                  sa.ForeignKey("ai_validation_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("benchmark_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("verdict", sa.String(length=16), nullable=False,
                  server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_fallback", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("components", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("turns", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("deductions", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("reference", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
    )
    op.create_index("ix_ai_validation_cases_run", "ai_validation_cases",
                    ["run_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_ai_validation_cases_run", table_name="ai_validation_cases")
    op.drop_table("ai_validation_cases")
    op.drop_index("ix_ai_validation_runs_created", table_name="ai_validation_runs")
    op.drop_table("ai_validation_runs")
    op.alter_column("analysis_runs", "status",
                    existing_type=sa.String(length=32),
                    type_=sa.String(length=16), existing_nullable=False)
