"""The exported-analysis library. Playbook §5.

"Saved in a module" and "exported to Playbook" are different states, and only
the second belongs here. An export is an explicit act, and what it produces is a
SELF-CONTAINED SNAPSHOT — narrative, tables, chart specification, scope, units,
assumptions, caveats and provenance — rather than a pointer at a screen the user
has already left.

Two tables because a snapshot must be able to age without lying. The family
carries identity and everything the library filters on; the revision carries the
content and is written once. Re-exporting an analysis that has since changed adds
revision n+1 and leaves n exactly as the report that cites it found it.

`uq_analysis_export_content` is the idempotency rule in the schema rather than in
a service: the same snapshot of the same analysis exports once, however many
times somebody clicks the button.

Additive only. Nothing existing is altered or dropped.

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('analysis_exports',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('tenant', sa.String(length=64), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('source_module', sa.String(length=32), nullable=False),
    sa.Column('source_ref', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('report_family', sa.String(length=64), nullable=False),
    sa.Column('reporting_period', sa.String(length=32), nullable=False),
    sa.Column('insight', sa.Text(), nullable=False),
    sa.Column('demo_origin', sa.Boolean(), nullable=False),
    sa.Column('seed_version', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_analysis_exports_library', 'analysis_exports', ['tenant', 'created_at'], unique=False)
    op.create_index('ix_analysis_exports_module', 'analysis_exports', ['tenant', 'source_module', 'created_at'], unique=False)
    op.create_table('analysis_export_revisions',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('export_id', sa.BigInteger(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('schema_version', sa.String(length=16), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('source_revision', sa.String(length=64), nullable=False),
    sa.Column('origin', sa.String(length=24), nullable=False),
    sa.Column('exported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('exported_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['export_id'], ['analysis_exports.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['exported_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('export_id', 'content_hash', name='uq_analysis_export_content'),
    sa.UniqueConstraint('export_id', 'revision', name='uq_analysis_export_revision')
    )


def downgrade() -> None:
    op.drop_table("analysis_export_revisions")
    op.drop_index("ix_analysis_exports_module", table_name="analysis_exports")
    op.drop_index("ix_analysis_exports_library", table_name="analysis_exports")
    op.drop_table("analysis_exports")
