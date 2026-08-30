"""§13-§26: the AI Brain — ledger, packages, quarantine, installations,
conflicts and trusted signers.

Six tables. What each is for, because the split between them is the
governance rather than an implementation detail:

    brain_ledger_entries  everything this installation learned, from any of
                          §13's seventeen sources, whether or not anyone
                          acted on it. No UPDATE path: an entry found wrong
                          is superseded by a new row pointing at it.
    brain_packages        a package that exists — one we exported or one
                          uploaded to us. Manifest stored as it arrived.
    brain_imports         where an uploaded package is in §16's fifteen
                          stages. One row per attempt, so a package we
                          rejected once and accepted later keeps both facts.
    brain_installations   §24's history, with the measured columns first
                          class: baseline, candidate, the six-dimension
                          deltas, critical fixes and critical regressions.
    brain_conflicts       contradictory learning and how it was settled.
    brain_signers         §26's trusted signer registry. Trust is a decision
                          a named person recorded, not a claim a key makes.

Nothing created here is readable by live retrieval. A candidate's teaching
cases reach an answer only once a brain_installations row is ACTIVE.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "brain_ledger_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entry_id", sa.String(length=48), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False,
                  server_default="1.0.0"),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("tenant", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("user_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("object_kind", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("object_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("related_ids", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("build_sha", sa.String(length=40), nullable=False,
                  server_default=""),
        sa.Column("intelligence_release_id", sa.String(length=64),
                  nullable=False, server_default=""),
        sa.Column("teaching_release_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("ontology_version", sa.String(length=16), nullable=False,
                  server_default=""),
        sa.Column("classification", sa.String(length=24), nullable=False,
                  server_default="LOCAL"),
        sa.Column("portability", sa.String(length=24), nullable=False,
                  server_default="NON_PORTABLE"),
        sa.Column("portability_blockers", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("redaction_status", sa.String(length=16), nullable=False,
                  server_default="NONE"),
        sa.Column("review_status", sa.String(length=24), nullable=False,
                  server_default="CAPTURED"),
        sa.Column("reviewer", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("candidate_components", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("candidate_case_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("candidate_policy_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("candidate_method_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("candidate_ontology_change", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_in", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("fingerprint", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", name="uq_brain_ledger_entry"),
    )
    op.create_index("ix_brain_ledger_source", "brain_ledger_entries",
                    ["tenant", "source", "created_at"])
    op.create_index("ix_brain_ledger_status", "brain_ledger_entries",
                    ["tenant", "review_status", "portability"])
    op.create_index("ix_brain_ledger_fingerprint", "brain_ledger_entries",
                    ["tenant", "fingerprint"])
    op.create_index("ix_brain_ledger_object", "brain_ledger_entries",
                    ["object_kind", "object_id"])

    op.create_table(
        "brain_packages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("package_id", sa.String(length=48), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False,
                  server_default="IMPORT"),
        sa.Column("package_kind", sa.String(length=16), nullable=False,
                  server_default="cpbrain"),
        sa.Column("brain_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("brain_name", sa.String(length=160), nullable=False,
                  server_default=""),
        sa.Column("brain_version", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("manifest", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("sha256", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("entry_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("signature_state", sa.String(length=24), nullable=False,
                  server_default="UNSIGNED"),
        sa.Column("signing_key_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("signer_trust", sa.String(length=24), nullable=False,
                  server_default="UNKNOWN"),
        sa.Column("storage_path", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("payload_purged_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("tenant", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_by", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("package_id", name="uq_brain_package"),
    )
    op.create_index("ix_brain_package_tenant", "brain_packages",
                    ["tenant", "direction", "created_at"])
    op.create_index("ix_brain_package_sha", "brain_packages", ["sha256"])

    op.create_table(
        "brain_imports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("import_id", sa.String(length=48), nullable=False),
        sa.Column("package_id", sa.String(length=48), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False,
                  server_default="UPLOADED"),
        sa.Column("state", sa.String(length=24), nullable=False,
                  server_default="IN_QUARANTINE"),
        sa.Column("stage_history", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("blockers", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("security_report", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("compatibility_report", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("component_diff", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("evaluation", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("impact_report", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("approvals", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("decision", sa.String(length=24), nullable=False,
                  server_default=""),
        sa.Column("decision_reason", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("decided_by", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("uploaded_by", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", name="uq_brain_import"),
    )
    op.create_index("ix_brain_import_stage", "brain_imports",
                    ["tenant", "state", "stage"])
    op.create_index("ix_brain_import_package", "brain_imports",
                    ["package_id"])

    op.create_table(
        "brain_installations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("installation_id", sa.String(length=48), nullable=False),
        sa.Column("import_id", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("package_id", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("brain_name", sa.String(length=160), nullable=False,
                  server_default=""),
        sa.Column("brain_version", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("source_instance_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("source_user", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("installed_by", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("approved_by", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("components", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("conflicts", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("baseline_metrics", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("candidate_metrics", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("dimension_deltas", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("critical_fixes", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("critical_regressions", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("release_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("state", sa.String(length=24), nullable=False,
                  server_default="STAGED"),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_reason", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("post_activation_verification", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("tenant", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id", name="uq_brain_installation"),
    )
    op.create_index("ix_brain_installation_state", "brain_installations",
                    ["tenant", "state", "activated_at"])
    op.create_index("ix_brain_installation_import", "brain_installations",
                    ["import_id"])

    op.create_table(
        "brain_conflicts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conflict_id", sa.String(length=48), nullable=False),
        sa.Column("import_id", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("conflict_class", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False,
                  server_default="MEDIUM"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("incoming", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("existing", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("recommendation", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("recommendation_reason", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("resolution", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("resolution_reason", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("split_axis", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("resolved_by", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conflict_id", name="uq_brain_conflict"),
    )
    op.create_index("ix_brain_conflict_import", "brain_conflicts",
                    ["import_id", "severity"])

    op.create_table(
        "brain_signers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False,
                  server_default=""),
        sa.Column("organization", sa.String(length=160), nullable=False,
                  server_default=""),
        sa.Column("trust_level", sa.String(length=16), nullable=False,
                  server_default="LOW"),
        sa.Column("key_fingerprint", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("added_by", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("added_reason", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("revoked_by", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("revoked_reason", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant", "key_id", name="uq_brain_signer"),
    )
    op.create_index("ix_brain_signer_trust", "brain_signers",
                    ["tenant", "trust_level"])


def downgrade() -> None:
    op.drop_table("brain_signers")
    op.drop_table("brain_conflicts")
    op.drop_table("brain_installations")
    op.drop_table("brain_imports")
    op.drop_table("brain_packages")
    op.drop_table("brain_ledger_entries")
