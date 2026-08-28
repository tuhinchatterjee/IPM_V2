"""The governed teaching case library.

Part A §4-§6. A versioned TeachingCase with the columns retrieval filters on,
the whole case in JSONB beside them, and an audit trail of every status change.

``(case_id, case_version)`` is unique: editing an approved case writes a new
version rather than overwriting the reviewed one. An approved case whose
content can change underneath its approval is an approval that means nothing.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teaching_cases",
        sa.Column("id", sa.BigInteger(), primary_key=True),

        # Identity.
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("title", sa.String(240), nullable=False, server_default=""),
        sa.Column("family_id", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("subfamily", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("language", sa.String(8), nullable=False,
                  server_default="en"),
        sa.Column("locale", sa.String(16), nullable=False, server_default=""),
        sa.Column("portfolio_scope", sa.String(16), nullable=False,
                  server_default="NONE"),
        sa.Column("industry_or_product_scope", sa.String(96), nullable=False,
                  server_default=""),
        sa.Column("difficulty", sa.String(16), nullable=False,
                  server_default="INTERMEDIATE"),
        sa.Column("risk_level", sa.String(16), nullable=False,
                  server_default="MEDIUM"),

        # What was asked.
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("turn_count", sa.Integer(), nullable=False,
                  server_default="0"),

        # What should happen.
        sa.Column("expected_capability", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("expected_conversation_action", sa.String(48),
                  nullable=False, server_default=""),
        sa.Column("expected_outcome", sa.String(16), nullable=False,
                  server_default="EXECUTE"),
        sa.Column("expected_officer_level", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("expected_model_route", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("expected_effort", sa.String(16), nullable=False,
                  server_default=""),
        sa.Column("grain", sa.String(48), nullable=False, server_default=""),

        # Filterable content, denormalised out of the body.
        sa.Column("concepts", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("required_datasets", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("operations", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("tags", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),

        # The whole case.
        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),

        # Governance.
        sa.Column("review_status", sa.String(24), nullable=False,
                  server_default="DRAFT"),
        sa.Column("authoring_method", sa.String(32), nullable=False,
                  server_default="HUMAN"),
        sa.Column("data_sensitivity", sa.String(24), nullable=False,
                  server_default="STRUCTURE_ONLY"),
        sa.Column("source_provenance", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("system_source", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("reviewer", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("reviewed_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True),
                  nullable=True),

        # The staleness axes.
        sa.Column("ontology_version", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("method_version", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("relationship_version", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("dataset_contract_version", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("planner_schema_version", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("prompt_schema_version", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("model_family", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("prompt_compatibility", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("family_version", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("stale_axes", sa.String(240), nullable=False,
                  server_default=""),

        # Identity of content.
        sa.Column("fingerprint", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("cluster_id", sa.String(64), nullable=False,
                  server_default=""),

        sa.Column("cost_budget", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("latency_budget", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),

        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),

        sa.UniqueConstraint("case_id", "case_version",
                            name="uq_teaching_case_version"),
    )
    op.create_index("ix_teaching_case_family", "teaching_cases",
                    ["family_id", "review_status"])
    op.create_index("ix_teaching_case_status", "teaching_cases",
                    ["review_status", "difficulty"])
    op.create_index("ix_teaching_case_fingerprint", "teaching_cases",
                    ["fingerprint"])
    op.create_index("ix_teaching_case_cluster", "teaching_cases",
                    ["cluster_id"])
    op.create_index("ix_teaching_case_scope", "teaching_cases",
                    ["portfolio_scope", "language"])

    op.create_table(
        "teaching_case_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("from_status", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("to_status", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("actor", sa.String(120), nullable=False, server_default=""),
        sa.Column("actor_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_teaching_event_case", "teaching_case_events",
                    ["case_id", "case_version", "at"])
    op.create_index("ix_teaching_event_status", "teaching_case_events",
                    ["to_status", "at"])


def downgrade() -> None:
    op.drop_index("ix_teaching_event_status",
                  table_name="teaching_case_events")
    op.drop_index("ix_teaching_event_case", table_name="teaching_case_events")
    op.drop_table("teaching_case_events")
    for name in ("ix_teaching_case_scope", "ix_teaching_case_cluster",
                 "ix_teaching_case_fingerprint", "ix_teaching_case_status",
                 "ix_teaching_case_family"):
        op.drop_index(name, table_name="teaching_cases")
    op.drop_table("teaching_cases")
