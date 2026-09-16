"""Documents: the papers people write, as rows rather than as a constant.

Before this, Work → Documents rendered `DOCUMENTS` from
`frontend/src/lib/demo.ts` — a hard-coded array of three objects. Nothing
was stored, nothing could be edited, nothing could be downloaded, and every
installation showed the same three titles with the same dates whatever the
book underneath had done.

§19 asks for the other thing entirely: an editable central document with a
section outline, supporting evidence, review controls, autosave, revision
history, comments, a Word download and a support bundle. That needs two
tables.

`documents` holds the paper. A revision is a ROW, not a version column,
because §19 requires an approved record to be an immutable snapshot and
editing to create a new draft revision — which a column with an update path
cannot express. `supersedes_id` chains them and `is_current` marks the one a
reader lands on.

`document_attachments` holds supporting files as BYTES. §19 is explicit that
supporting files are real downloadable content with the correct MIME type
and that internal filesystem paths must not be exposed as downloads. Both
halves are one decision: a path in a download URL is a path somebody will
eventually traverse. The URL carries an integer id and nothing else.

Comments come from the platform `comments` table, keyed on object_type
"document" — the same table the validation commentary uses, for the same
reason: one comment table, one audit trail, one place to look.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(120), nullable=False, server_default=""),
        sa.Column("product", sa.String(48), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="draft"),
        sa.Column("as_of", sa.String(32), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("project_id", sa.BigInteger(),
                  sa.ForeignKey("projects.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("owner_id", sa.BigInteger(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("owner_name", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("data_versions", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("supersedes_id", sa.BigInteger(), nullable=True),
        sa.Column("seed_key", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("seeded", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("user_edited", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_foreign_key("fk_documents_supersedes", "documents", "documents",
                          ["supersedes_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_documents_current", "documents",
                    ["is_current", "updated_at"])
    op.create_index("ix_documents_seed", "documents", ["seed_key"])
    op.create_index("ix_documents_project", "documents", ["project_id"])

    op.create_table(
        "document_attachments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("document_id", sa.BigInteger(),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(120), nullable=False,
                  server_default="application/octet-stream"),
        sa.Column("role", sa.String(32), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_document_attachments_doc", "document_attachments",
                    ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_document_attachments_doc",
                  table_name="document_attachments")
    op.drop_table("document_attachments")
    op.drop_index("ix_documents_project", table_name="documents")
    op.drop_index("ix_documents_seed", table_name="documents")
    op.drop_index("ix_documents_current", table_name="documents")
    op.drop_constraint("fk_documents_supersedes", "documents",
                       type_="foreignkey")
    op.drop_table("documents")
