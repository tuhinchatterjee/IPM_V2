"""the product hierarchy, lenses, playbooks and early warning

This migration makes the CreditProbe AI hierarchy real in the database:

    Project          the master workspace
      Investigation    a conversational thread
        Analysis         one deterministic engine result

Until now "Investigation" meant a single saved analytical output. It now means
the whole conversation, and the single saved output has its own table. Nothing
is destroyed to get there: every existing investigation_version row is copied
forward into both the new thread (as an assistant turn) and the new
saved_analyses table, and investigation_versions is left in place so the
refresh/compare history remains readable.

New tables:

  investigation_messages   one turn in a thread
  saved_analyses           an executed analysis somebody kept
  project_status_events    the governed lifecycle history of a project
  lenses / lens_revisions  live dashboards and their versioned specifications
  playbooks / playbook_runs  monitoring recipes and what they decided
  early_warning_models     one version of the Forward Risk Signal methodology

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------- investigations
    op.add_column(
        'investigations',
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        'investigations',
        sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'investigations',
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column('investigations', 'context', server_default=None)
    op.alter_column('investigations', 'message_count', server_default=None)

    op.create_table(
        'investigation_messages',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('investigation_id', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('analysis_run_id', sa.BigInteger(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['analysis_run_id'], ['analysis_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['investigation_id'], ['investigations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('investigation_id', 'sequence', name='uq_investigation_message_seq'),
    )
    op.create_index('ix_investigation_messages_thread', 'investigation_messages',
                    ['investigation_id', 'sequence'], unique=False)

    # ------------------------------------------------------- saved analyses
    op.create_table(
        'saved_analyses',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('analysis_id', sa.String(length=120), nullable=False),
        sa.Column('analysis_version', sa.String(length=24), nullable=False),
        sa.Column('certification', sa.String(length=24), nullable=False),
        sa.Column('analysis_run_id', sa.BigInteger(), nullable=True),
        sa.Column('investigation_id', sa.BigInteger(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('period', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('data_versions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['analysis_run_id'], ['analysis_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['investigation_id'], ['investigations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_saved_analyses_project', 'saved_analyses',
                    ['project_id', 'created_at'], unique=False)
    op.create_index('ix_saved_analyses_investigation', 'saved_analyses',
                    ['investigation_id', 'created_at'], unique=False)
    op.create_index('ix_saved_analyses_owner', 'saved_analyses',
                    ['owner_id', 'created_at'], unique=False)

    # ---------------------------------------------------------- projects
    op.add_column('projects', sa.Column('instructions', sa.Text(), nullable=False,
                                        server_default=''))
    op.alter_column('projects', 'instructions', server_default=None)

    op.create_table(
        'project_status_events',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(length=24), nullable=True),
        sa.Column('to_status', sa.String(length=24), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_project_status_project', 'project_status_events',
                    ['project_id', 'created_at'], unique=False)

    # ------------------------------------------------------------- lenses
    op.create_table(
        'lenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('audience', sa.String(length=120), nullable=False),
        sa.Column('definition', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('origin', sa.String(length=24), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_table(
        'lens_revisions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('lens_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('definition', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('request', sa.Text(), nullable=False),
        sa.Column('change_summary', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['lens_id'], ['lenses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lens_id', 'version', name='uq_lens_revision'),
    )

    # ---------------------------------------------------------- playbooks
    op.create_table(
        'playbooks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('trigger', sa.String(length=32), nullable=False),
        sa.Column('schedule', sa.String(length=64), nullable=False),
        sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('analyses', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('actions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('origin', sa.String(length=24), nullable=False),
        sa.Column('owner', sa.String(length=160), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_hint', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_table(
        'playbook_runs',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('playbook_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('period', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('evaluations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('actions_taken', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('alerted', sa.Boolean(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('investigation_id', sa.BigInteger(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['investigation_id'], ['investigations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['playbook_id'], ['playbooks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_playbook_runs_playbook', 'playbook_runs',
                    ['playbook_id', 'created_at'], unique=False)

    # ------------------------------------------------------ early warning
    op.create_table(
        'early_warning_models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('target', sa.String(length=48), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('lifecycle', sa.String(length=24), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('specification', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('change_note', sa.Text(), nullable=False),
        sa.Column('validation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('target', 'version', name='uq_early_warning_model_version'),
    )
    op.create_index('ix_early_warning_active', 'early_warning_models',
                    ['target', 'is_active'], unique=False)

    # ================================================= carry existing data
    #
    # Existing investigations were saved single answers. Each becomes a thread
    # with one user turn (the question) and one assistant turn per stored
    # version, and each version that has an execution behind it also becomes a
    # saved Analysis. Nothing is deleted: investigation_versions stays.
    conn = op.get_bind()

    conn.execute(sa.text("""
        INSERT INTO investigation_messages
            (investigation_id, sequence, role, content, payload, analysis_run_id,
             created_by, created_at)
        SELECT i.id, 0, 'user', i.question, '{}'::jsonb, NULL, i.owner_id, i.created_at
        FROM investigations i
        WHERE NOT EXISTS (
            SELECT 1 FROM investigation_messages m WHERE m.investigation_id = i.id
        )
    """))

    conn.execute(sa.text("""
        INSERT INTO investigation_messages
            (investigation_id, sequence, role, content, payload, analysis_run_id,
             created_by, created_at)
        SELECT
            v.investigation_id,
            v.version_number,
            'assistant',
            COALESCE(v.narrative->>'direct_answer', v.narrative->>'summary', ''),
            jsonb_build_object(
                'narrative', v.narrative,
                'migrated_from_version', v.version_number,
                'change_narrative', v.change_narrative
            ),
            v.analysis_run_id,
            v.created_by,
            v.created_at
        FROM investigation_versions v
        WHERE NOT EXISTS (
            SELECT 1 FROM investigation_messages m
            WHERE m.investigation_id = v.investigation_id
              AND m.sequence = v.version_number
        )
    """))

    conn.execute(sa.text("""
        INSERT INTO saved_analyses
            (title, analysis_id, analysis_version, certification, analysis_run_id,
             investigation_id, project_id, params, filters, period, result,
             data_versions, note, owner_id, created_at)
        SELECT
            LEFT(i.title, 300),
            COALESCE(r.plan->'steps'->0->>'analysis_id', 'unknown'),
            '',
            'certified',
            v.analysis_run_id,
            v.investigation_id,
            i.project_id,
            '{}'::jsonb,
            '{}'::jsonb,
            jsonb_build_object('from_period', v.from_period, 'to_period', v.to_period),
            COALESCE(v.metrics, '{}'::jsonb),
            '{}'::jsonb,
            'Carried forward from a saved investigation.',
            i.owner_id,
            v.created_at
        FROM investigation_versions v
        JOIN investigations i ON i.id = v.investigation_id
        LEFT JOIN analysis_runs r ON r.id = v.analysis_run_id
        WHERE v.analysis_run_id IS NOT NULL
    """))

    conn.execute(sa.text("""
        UPDATE investigations i SET
            message_count = COALESCE(
                (SELECT COUNT(*) FROM investigation_messages m
                 WHERE m.investigation_id = i.id), 0),
            last_message_at = (
                SELECT MAX(m.created_at) FROM investigation_messages m
                WHERE m.investigation_id = i.id),
            context = COALESCE(i.scope, '{}'::jsonb)
    """))

    # Existing projects carried a free-text status. Anything outside the governed
    # vocabulary becomes ACTIVE, and the change is recorded like any other.
    conn.execute(sa.text("""
        UPDATE projects
        SET status = 'active'
        WHERE status NOT IN ('draft','active','in_review','completed','archived')
    """))
    conn.execute(sa.text("""
        INSERT INTO project_status_events (project_id, from_status, to_status, note, created_at)
        SELECT p.id, NULL, p.status,
               'Recorded when the governed project lifecycle was introduced.',
               p.created_at
        FROM projects p
        WHERE NOT EXISTS (
            SELECT 1 FROM project_status_events e WHERE e.project_id = p.id
        )
    """))


def downgrade() -> None:
    op.drop_index('ix_early_warning_active', table_name='early_warning_models')
    op.drop_table('early_warning_models')
    op.drop_index('ix_playbook_runs_playbook', table_name='playbook_runs')
    op.drop_table('playbook_runs')
    op.drop_table('playbooks')
    op.drop_table('lens_revisions')
    op.drop_table('lenses')
    op.drop_index('ix_project_status_project', table_name='project_status_events')
    op.drop_table('project_status_events')
    op.drop_column('projects', 'instructions')
    op.drop_index('ix_saved_analyses_owner', table_name='saved_analyses')
    op.drop_index('ix_saved_analyses_investigation', table_name='saved_analyses')
    op.drop_index('ix_saved_analyses_project', table_name='saved_analyses')
    op.drop_table('saved_analyses')
    op.drop_index('ix_investigation_messages_thread', table_name='investigation_messages')
    op.drop_table('investigation_messages')
    op.drop_column('investigations', 'last_message_at')
    op.drop_column('investigations', 'message_count')
    op.drop_column('investigations', 'context')
