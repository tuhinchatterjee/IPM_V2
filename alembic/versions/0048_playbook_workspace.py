"""The Playbook workspace: threads, sources, artifacts and versions. Playbook §6, §9, §15.

A playbook is a workspace, not a generated file — so the conversation, the
sources, the decisions and every artifact version are persisted, and reopening
one restores all of it. None of this may live in front-end state, because "this
section" and "only changes 1, 2 and 3" have to still mean something after a
refresh.

Three properties are enforced by the schema rather than by convention:

* **Evidence is pinned.** `playbook_attachments` references an export REVISION,
  with ON DELETE RESTRICT, so evidence a report was built on cannot vanish
  underneath it and a library update cannot retroactively change what a
  generation was answering.
* **A version is immutable.** `playbook_artifact_versions` rows are written
  once, carry their parent, and record which approved change items produced
  them. Restoring an older version writes a new row moving forward; nothing is
  rewound and nothing is deleted.
* **A generation runs once.** `uq_playbook_job_idempotency` means a refresh, a
  double-click or a retry finds the existing job instead of starting a second
  billable one.

This is a different feature from the `playbooks` / `playbook_runs` tables added
in 0005, which are the standing-instruction Playbook of docs/PRODUCT_SPEC.md §9.
Those are untouched.

Additive only. Nothing existing is altered or dropped.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('playbook_workspaces',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('tenant', sa.String(length=64), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('document_family', sa.String(length=64), nullable=False),
    sa.Column('state_summary', sa.Text(), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=False),
    sa.Column('demo_origin', sa.Boolean(), nullable=False),
    sa.Column('seed_version', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_playbook_workspaces_owner', 'playbook_workspaces', ['tenant', 'owner_id', 'last_activity_at'], unique=False)
    op.create_index('ix_playbook_workspaces_recent', 'playbook_workspaces', ['tenant', 'last_activity_at'], unique=False)
    op.create_table('playbook_artifacts',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('workspace_id', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('current_version_id', sa.BigInteger(), nullable=True),
    sa.Column('derived_from_artifact_id', sa.BigInteger(), nullable=True),
    sa.Column('derived_from_version_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['derived_from_artifact_id'], ['playbook_artifacts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['playbook_workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_playbook_artifacts_workspace', 'playbook_artifacts', ['workspace_id', 'updated_at'], unique=False)
    op.create_table('playbook_jobs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('workspace_id', sa.BigInteger(), nullable=False),
    sa.Column('tenant', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('idempotency_key', sa.String(length=120), nullable=False),
    sa.Column('agent_job_id', sa.BigInteger(), nullable=True),
    sa.Column('state', sa.String(length=24), nullable=False),
    sa.Column('milestones', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('provider_request_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('container_id', sa.String(length=120), nullable=False),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('cancelled', sa.Boolean(), nullable=False),
    sa.Column('requested_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['playbook_workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key', name='uq_playbook_job_idempotency')
    )
    op.create_index('ix_playbook_jobs_workspace', 'playbook_jobs', ['workspace_id', 'created_at'], unique=False)
    op.create_table('playbook_workspace_sources',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('workspace_id', sa.BigInteger(), nullable=False),
    sa.Column('tenant', sa.String(length=64), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('mime', sa.String(length=120), nullable=False),
    sa.Column('bytes_path', sa.Text(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('source_role', sa.String(length=32), nullable=False),
    sa.Column('role_set_by', sa.String(length=16), nullable=False),
    sa.Column('role_confidence', sa.String(length=16), nullable=False),
    sa.Column('reporting_period', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('failure_reason', sa.Text(), nullable=False),
    sa.Column('provider_file_id', sa.String(length=120), nullable=False),
    sa.Column('provider_file_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['playbook_workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_playbook_sources_workspace', 'playbook_workspace_sources', ['workspace_id', 'created_at'], unique=False)
    op.create_table('playbook_artifact_versions',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('artifact_id', sa.BigInteger(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('parent_version_id', sa.BigInteger(), nullable=True),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('applied_change_item_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('change_summary', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('origin', sa.String(length=24), nullable=False),
    sa.Column('validation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['playbook_artifacts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_version_id'], ['playbook_artifact_versions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('artifact_id', 'version', name='uq_playbook_artifact_version')
    )
    op.create_index('ix_playbook_artifact_versions_artifact', 'playbook_artifact_versions', ['artifact_id', 'version'], unique=False)
    op.create_table('playbook_messages',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('workspace_id', sa.BigInteger(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('origin', sa.String(length=24), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('request_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('author_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_id'], ['playbook_jobs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['playbook_workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'sequence', name='uq_playbook_message_seq')
    )
    op.create_index('ix_playbook_messages_thread', 'playbook_messages', ['workspace_id', 'sequence'], unique=False)
    op.create_table('playbook_workspace_source_chunks',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('locator', sa.String(length=300), nullable=False),
    sa.Column('path', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('token_estimate', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['playbook_workspace_sources.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'ordinal', name='uq_playbook_source_chunk')
    )
    op.create_index('ix_playbook_source_chunks_source', 'playbook_workspace_source_chunks', ['source_id', 'ordinal'], unique=False)
    op.create_table('playbook_artifact_files',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('version_id', sa.BigInteger(), nullable=False),
    sa.Column('format', sa.String(length=8), nullable=False),
    sa.Column('bytes_path', sa.Text(), nullable=False),
    sa.Column('mime', sa.String(length=120), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('renderer', sa.String(length=32), nullable=False),
    sa.Column('preview_path', sa.Text(), nullable=False),
    sa.Column('validated', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['version_id'], ['playbook_artifact_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version_id', 'format', name='uq_playbook_artifact_file_format')
    )
    op.create_table('playbook_attachments',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('workspace_id', sa.BigInteger(), nullable=False),
    sa.Column('message_id', sa.BigInteger(), nullable=True),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('export_revision_id', sa.BigInteger(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['export_revision_id'], ['analysis_export_revisions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['message_id'], ['playbook_messages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['playbook_workspace_sources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['playbook_workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_playbook_attachments_message', 'playbook_attachments', ['message_id', 'position'], unique=False)
    op.create_index('ix_playbook_attachments_workspace', 'playbook_attachments', ['workspace_id', 'position'], unique=False)
    op.create_table('playbook_change_sets',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('workspace_id', sa.BigInteger(), nullable=False),
    sa.Column('message_id', sa.BigInteger(), nullable=True),
    sa.Column('base_version_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['base_version_id'], ['playbook_artifact_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['message_id'], ['playbook_messages.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['playbook_workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_playbook_change_sets_workspace', 'playbook_change_sets', ['workspace_id', 'created_at'], unique=False)
    op.create_table('playbook_change_items',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('change_set_id', sa.BigInteger(), nullable=False),
    sa.Column('display_number', sa.Integer(), nullable=False),
    sa.Column('stable_id', sa.String(length=40), nullable=False),
    sa.Column('target_artifact_id', sa.BigInteger(), nullable=True),
    sa.Column('target_section', sa.String(length=300), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('proposed', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('calculation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('depends_on', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['change_set_id'], ['playbook_change_sets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['target_artifact_id'], ['playbook_artifacts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('change_set_id', 'display_number', name='uq_playbook_change_number'),
    sa.UniqueConstraint('change_set_id', 'stable_id', name='uq_playbook_change_stable_id')
    )


def downgrade() -> None:
    op.drop_table("playbook_change_items")
    op.drop_index("ix_playbook_change_sets_workspace", table_name="playbook_change_sets")
    op.drop_table("playbook_change_sets")
    op.drop_index("ix_playbook_attachments_workspace", table_name="playbook_attachments")
    op.drop_index("ix_playbook_attachments_message", table_name="playbook_attachments")
    op.drop_table("playbook_attachments")
    op.drop_table("playbook_artifact_files")
    op.drop_index("ix_playbook_source_chunks_source", table_name="playbook_workspace_source_chunks")
    op.drop_table("playbook_workspace_source_chunks")
    op.drop_index("ix_playbook_messages_thread", table_name="playbook_messages")
    op.drop_table("playbook_messages")
    op.drop_index("ix_playbook_artifact_versions_artifact", table_name="playbook_artifact_versions")
    op.drop_table("playbook_artifact_versions")
    op.drop_index("ix_playbook_sources_workspace", table_name="playbook_workspace_sources")
    op.drop_table("playbook_workspace_sources")
    op.drop_index("ix_playbook_jobs_workspace", table_name="playbook_jobs")
    op.drop_table("playbook_jobs")
    op.drop_index("ix_playbook_artifacts_workspace", table_name="playbook_artifacts")
    op.drop_table("playbook_artifacts")
    op.drop_index("ix_playbook_workspaces_recent", table_name="playbook_workspaces")
    op.drop_index("ix_playbook_workspaces_owner", table_name="playbook_workspaces")
    op.drop_table("playbook_workspaces")
