"""A comment a validator can sign, on the run it was actually made against.

§15 of the retail demo contract asks for comments on every category and
every test-evidence card, carrying an assessment, a severity, a supporting
attachment, a reviewer response and a resolved/open status — attached to the
exact model, run, test and data version, with an edit history, surviving a
refresh, a category or model switch, a logout and a server restart, and
never silently re-attached to a later run.

The platform already has a comment table, object-keyed, reachable from every
screen. What it carries is a body, a resolution flag and an author. That is
the right table and the wrong columns, and the alternative — a second
`scv_comments` table — is the one thing `backend/models/scorecard_validation`
says out loud it will not introduce, because a second comment table is a
second audit trail and a second place to look.

So the platform comment gains what a governance comment needs, all nullable
and all ignorable by every existing caller:

  kind          whose statement it is. §15 is explicit that a
                system-calculated finding, an analyst's commentary and an
                approver's decision must not read as the same kind of
                sentence, and a column is the only way a report can keep
                them apart six months later.
  assessment    what the author concluded. Agreed, disagreed, accepted with
                an action, needs evidence.
  severity      the author's own severity, which may differ from the
                engine's — that disagreement is the point of the field, and
                it never overwrites the measured one.
  context       model id, model version, run key, test id, category, the
                period, the data as-of and the calculation versions, taken
                from the result the comment was made on. This is what stops
                a comment written about one run appearing under the next as
                though it had been made about it.
  attachments   references, in the shape `workflow_messages` already uses:
                `[{"kind": "...", "label": "...", "reference": "..."}]`.
                References rather than bytes, for the same reason.
  edited_at /
  supersedes_id an edit writes a NEW row that supersedes the old one, and
                the old row stays exactly as written. A comment is evidence;
                a schema that permits editing one in place is a schema in
                which "what did the reviewer actually say?" has no answer.

The index is on the object key, which already exists. The one added here is
on the run key inside `context`, because the report has to fetch every
comment on a run and doing that by scanning object ids means the report gets
slower with every unrelated comment in the installation.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("comments", sa.Column(
        "kind", sa.String(24), nullable=False, server_default="COMMENT"))
    op.add_column("comments", sa.Column(
        "assessment", sa.String(32), nullable=False, server_default=""))
    op.add_column("comments", sa.Column(
        "severity", sa.String(16), nullable=False, server_default=""))
    op.add_column("comments", sa.Column(
        "context", postgresql.JSONB(astext_type=sa.Text()),
        nullable=False, server_default="{}"))
    op.add_column("comments", sa.Column(
        "attachments", postgresql.JSONB(astext_type=sa.Text()),
        nullable=False, server_default="[]"))
    op.add_column("comments", sa.Column(
        "edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("comments", sa.Column(
        "supersedes_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_comments_supersedes", "comments", "comments",
                          ["supersedes_id"], ["id"], ondelete="SET NULL")
    # Every comment on one validation run, without scanning object ids.
    op.execute("""
        CREATE INDEX ix_comments_run
            ON comments ((context ->> 'run_key'))
         WHERE context ->> 'run_key' IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_comments_run")
    op.drop_constraint("fk_comments_supersedes", "comments",
                       type_="foreignkey")
    for column in ("supersedes_id", "edited_at", "attachments", "context",
                   "severity", "assessment", "kind"):
        op.drop_column("comments", column)
