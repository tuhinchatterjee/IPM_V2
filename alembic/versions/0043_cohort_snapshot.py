"""A cohort is an object, not a filter that is re-run.

Every handoff between the Cockpit, Early Warning, Borrower 360 and What-If used
to be a predicate: each module knew how to select "Alpha Card, 20-29 DPD, this
month" and the four agreed as long as the book beneath them did not move. When
it moved they resolved differently, and nothing in the product could see that
they had. The honest alternative — put the identifiers in the link — does not
survive eleven thousand customers and writes customer identifiers into browser
history and access logs.

So the identifiers are written once, here, and the link carries an opaque id.

Three tables because three lifetimes. `cohort_snapshots` is immutable from the
moment it is written and has no update path at all: a different scope is a new
row, which is what makes "refresh to latest" a new version rather than an edit,
and what makes a saved figure still true a month later. `saved_investigations`
adds the human layer — a name, a pin, a version — and is written as a DRAFT on
every import, before anybody presses Save, because the failure it prevents is a
reader losing a list by closing a tab. `investigation_notes` is append-only by
version, because in a dispute the previous wording is the part that matters.

None of the three holds a credit figure decided here. `totals` is what was
MEASURED at the source step, kept so a later reconciliation can prove the
cohort did not drift.

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cohort_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("occurrence_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("thread_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("step_id", sa.String(16), nullable=False, server_default=""),
        sa.Column("source_as_of", sa.String(16), nullable=False,
                  server_default=""),
        sa.Column("source_bundle_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("dataset_hashes", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("versions", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("metric_definition_ids", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("root_predicate", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("predicate", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("customer_ids", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("facility_ids", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("customer_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("facility_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("selection_mode", sa.String(24), nullable=False,
                  server_default="all_matched"),
        sa.Column("facility_mode", sa.String(32), nullable=False,
                  server_default="flagged_only"),
        sa.Column("restricted_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("content_hash", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("parent_snapshot_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("visited_steps", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("owner_user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("purpose", sa.String(120), nullable=False, server_default=""),
        sa.Column("permitted_fields", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence_refs", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totals", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cohort_snapshots_snapshot_id", "cohort_snapshots",
                    ["snapshot_id"], unique=True)
    op.create_index("ix_cohort_snapshots_content_hash", "cohort_snapshots",
                    ["content_hash"])
    op.create_index("ix_cohort_snapshots_case", "cohort_snapshots",
                    ["case_id", "source_as_of"])
    op.create_index("ix_cohort_snapshots_thread", "cohort_snapshots",
                    ["thread_id", "step_id"])
    op.create_index("ix_cohort_snapshots_owner", "cohort_snapshots",
                    ["owner_user_id", "created_at"])

    op.create_table(
        "saved_investigations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("saved_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("occurrence_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("thread_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_step", sa.String(16), nullable=False,
                  server_default=""),
        sa.Column("title", sa.String(240), nullable=False, server_default=""),
        sa.Column("issue", sa.Text(), nullable=False, server_default=""),
        sa.Column("segment", sa.String(160), nullable=False, server_default=""),
        sa.Column("state", sa.String(16), nullable=False,
                  server_default="draft"),
        sa.Column("pinned", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("noticed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("facility_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("odr", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("totals", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("owner_user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("share_scope", sa.String(16), nullable=False,
                  server_default="private"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("saved_id", "version",
                            name="uq_saved_investigation_version"),
    )
    op.create_index("ix_saved_investigations_saved_id", "saved_investigations",
                    ["saved_id"])
    op.create_index("ix_saved_investigations_snapshot_id",
                    "saved_investigations", ["snapshot_id"])
    op.create_index("ix_saved_investigations_owner", "saved_investigations",
                    ["owner_user_id", "created_at"])
    op.create_index("ix_saved_investigations_case", "saved_investigations",
                    ["case_id", "created_at"])

    op.create_table(
        "investigation_notes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("note_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("saved_id", sa.String(64), nullable=False),
        sa.Column("snapshot_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("subject_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("author_name", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("note_id", "version",
                            name="uq_investigation_note_version"),
    )
    op.create_index("ix_investigation_notes_note_id", "investigation_notes",
                    ["note_id"])
    op.create_index("ix_investigation_notes_saved_id", "investigation_notes",
                    ["saved_id"])
    op.create_index("ix_investigation_notes_saved", "investigation_notes",
                    ["saved_id", "created_at"])


def downgrade() -> None:
    op.drop_table("investigation_notes")
    op.drop_table("saved_investigations")
    op.drop_table("cohort_snapshots")
