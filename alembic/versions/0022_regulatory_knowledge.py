"""Part G: regulatory circulars and Regulatory Knowledge Releases.

Two tables, and one thing deliberately not in either of them: the original.

A regulator's consolidated rulebook is tens of megabytes, is read whole or not
at all, and is never queried. Held as a large object it would bloat every
backup to no purpose and make "give me the document behind this citation" a
database round trip. So the bytes live on disk under their SHA-256 and the
metadata lives here, where it is filtered on — regulator, reference, the
effective window, status, confidentiality, tenant.

`uq_regulatory_tenant_hash` is what makes a bulk upload idempotent: the same
circular twice ends with one document and two references to it, rather than a
corpus that double-counts every rule the second copy carried.

Nothing arrives approved. A row is UPLOADED, becomes EXTRACTED, and reaches
APPROVED only through a named SME and an activated release.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regulatory_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("circular_id", sa.String(64), nullable=False),

        sa.Column("title", sa.String(400), nullable=False, server_default=""),
        sa.Column("regulator", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("reference", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("jurisdiction", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("language", sa.String(8), nullable=False,
                  server_default="en"),

        # ISO strings rather than DATE. The window is compared as a whole and
        # never arithmetic'd, ISO strings sort correctly, and a circular with
        # no effective date has to be storable so it can be REPORTED as
        # unusable rather than refused at the door and lost.
        sa.Column("issued_on", sa.String(10), nullable=False,
                  server_default=""),
        sa.Column("effective_on", sa.String(10), nullable=False,
                  server_default=""),
        sa.Column("expires_on", sa.String(10), nullable=False,
                  server_default=""),

        sa.Column("file_format", sa.String(8), nullable=False,
                  server_default=""),
        sa.Column("filename", sa.String(240), nullable=False,
                  server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("byte_size", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False,
                  server_default="0"),

        sa.Column("status", sa.String(32), nullable=False,
                  server_default="UPLOADED"),
        sa.Column("confidentiality", sa.String(16), nullable=False,
                  server_default="RESTRICTED"),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("supersedes", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("superseded_by", sa.String(120), nullable=False,
                  server_default=""),

        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("extraction", postgresql.JSONB(), nullable=False,
                  server_default="{}"),

        sa.Column("rule_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("approved_rule_count", sa.Integer(), nullable=False,
                  server_default="0"),

        sa.Column("uploaded_by", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("schema_version", sa.String(16), nullable=False,
                  server_default="1.0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_regulatory_tenant_hash",
                               "regulatory_documents",
                               ["tenant", "content_hash"])
    op.create_unique_constraint("uq_regulatory_circular_id",
                               "regulatory_documents", ["circular_id"])
    op.create_index("ix_regulatory_reference", "regulatory_documents",
                    ["regulator", "reference"])
    op.create_index("ix_regulatory_effective", "regulatory_documents",
                    ["effective_on", "expires_on"])
    op.create_index("ix_regulatory_status", "regulatory_documents",
                    ["status", "tenant"])
    op.create_index("ix_regulatory_tenant", "regulatory_documents",
                    ["tenant", "created_at"])

    op.create_table(
        "regulatory_releases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("release_id", sa.String(64), nullable=False),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="DRAFT"),

        sa.Column("contents", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("circular_hashes", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("circular_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("rule_count", sa.Integer(), nullable=False,
                  server_default="0"),

        sa.Column("reviewers", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("approver", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("created_by", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("fingerprint", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("replaces", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_regulatory_release_id",
                               "regulatory_releases", ["release_id"])
    op.create_index("ix_regulatory_release_active", "regulatory_releases",
                    ["tenant", "status", "activated_at"])


def downgrade() -> None:
    op.drop_index("ix_regulatory_release_active",
                  table_name="regulatory_releases")
    op.drop_table("regulatory_releases")
    op.drop_index("ix_regulatory_tenant", table_name="regulatory_documents")
    op.drop_index("ix_regulatory_status", table_name="regulatory_documents")
    op.drop_index("ix_regulatory_effective", table_name="regulatory_documents")
    op.drop_index("ix_regulatory_reference", table_name="regulatory_documents")
    op.drop_table("regulatory_documents")
