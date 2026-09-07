"""Early Warning V2: governed methodology and escalation configuration.

Two versioned JSONB bundles, not a dozen narrow relational tables — the same
pattern `early_warning_models` already uses for the fitted Forward Risk
Signal. The 123-signal catalogue, 35 classifiers, 67 triggers, accelerator
and network parameters, and the override/reason-code tables are transcribed
once in `backend/early_warning/{catalog,classifiers_v2,triggers_v2,
accelerator,network,combination,reasons}.py`, verified there against the
workbook's own worked examples, and seeded into
`early_warning_methodology_versions` as one document per version so a score
computed six months ago can always be reconstructed under the methodology
that was actually in force.

The escalation ladder (L0-L5), specialist routes (S1-S5) and routing matrix
are versioned separately in `early_warning_escalation_versions`, because
that changes on a different cadence and by different roles than the scoring
mathematics: a governance change to who is notified at what exposure tier is
not a change to how a score is computed.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "early_warning_methodology_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bundle", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("version", name="uq_early_warning_methodology_version"),
    )
    op.create_index("ix_early_warning_methodology_active",
                     "early_warning_methodology_versions", ["is_active"])

    op.create_table(
        "early_warning_escalation_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bundle", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("version", name="uq_early_warning_escalation_version"),
    )
    op.create_index("ix_early_warning_escalation_active",
                     "early_warning_escalation_versions", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_early_warning_escalation_active",
                   table_name="early_warning_escalation_versions")
    op.drop_table("early_warning_escalation_versions")
    op.drop_index("ix_early_warning_methodology_active",
                   table_name="early_warning_methodology_versions")
    op.drop_table("early_warning_methodology_versions")
