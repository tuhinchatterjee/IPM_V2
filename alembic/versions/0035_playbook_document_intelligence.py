"""Document intelligence: a Playbook document as a governed, living object.

What this adds, and why each table exists
-----------------------------------------
Playbook could write a document and prove every figure in it. It could not
answer the questions a person actually asks of a governed paper afterwards:
what kind of document is this, how complete is it, which sections are stale,
what did this metric say when the paper was written, what does it say now, what
is unresolved, and what is the committee being asked to decide.

Ten tables, all additive, nothing existing altered or dropped.

* `playbook_document_profiles` — what a document IS. Type, family, whether it
  is a committee paper, the committee, the period, the meeting, the owner. The
  system may suggest; the user decides, and `classified_by` records which.
* `playbook_document_sections` — per-section status, reviewer and page range,
  keyed by a STABLE key rather than the heading, because retitling a section is
  inside the scope of editing it and must not reset its review state.
* `playbook_metric_bindings` — which governed metrics a document contains, and
  on what authority. A binding carries how it was made (`binding_method`) and
  whether a person confirmed it, so a suggestion can never be mistaken for a
  confirmed link.
* `playbook_metric_snapshots` — THEN. Frozen when a version is written and
  never rewritten, which is what makes "the value this paper relied on"
  answerable a year later.
* `playbook_findings`, `playbook_decisions`, `playbook_actions` — the
  governance objects a committee paper is FOR. A decision records the human who
  made it; nothing else may.
* `playbook_reviews` — who is reviewing what, and whether they have finished.
* `playbook_readiness` — the computed components behind every percentage, with
  the explanation stored beside the score so a number can always be clicked
  and understood.
* `playbook_source_parses` — one row per parse of a source's immutable bytes,
  with the parser version. Improving the parser makes old parses stale; a
  re-read is then a local, free operation rather than a re-upload.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playbook_document_profiles",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("workspace_id", sa.BigInteger,
                  sa.ForeignKey("playbook_workspaces.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("document_type", sa.String(48), nullable=False,
                  server_default="general"),
        sa.Column("report_family", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("committee_report", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("committee_name", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("reporting_period", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("meeting_date", sa.Date, nullable=True),
        sa.Column("owner", sa.String(160), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False,
                  server_default="drafting"),
        sa.Column("previous_artifact_id", sa.BigInteger, nullable=True),
        # "inferred" or "user". A suggestion the user never saw is not a
        # classification, and the difference has to survive in the row.
        sa.Column("classified_by", sa.String(16), nullable=False,
                  server_default="inferred"),
        sa.Column("classification_confidence", sa.String(16), nullable=False,
                  server_default=""),
        #: Which sections this document type requires, and the weights its
        #: completion score uses. Per document, so no single formula is
        #: hard-coded for every kind of paper.
        sa.Column("requirements", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "playbook_document_sections",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("artifact_id", sa.BigInteger,
                  sa.ForeignKey("playbook_artifacts.id", ondelete="CASCADE"),
                  nullable=False),
        # Stable across a retitle, which `merge` explicitly permits.
        sa.Column("section_key", sa.String(128), nullable=False),
        sa.Column("heading", sa.String(400), nullable=False, server_default=""),
        sa.Column("ordinal", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False,
                  server_default="draft"),
        sa.Column("first_seen_version", sa.Integer, nullable=False,
                  server_default="1"),
        sa.Column("last_changed_version", sa.Integer, nullable=False,
                  server_default="1"),
        sa.Column("content_hash", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("page_from", sa.Integer, nullable=True),
        sa.Column("page_to", sa.Integer, nullable=True),
        sa.Column("word_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("stale_reason", sa.Text, nullable=False, server_default=""),
        sa.Column("reviewer", sa.String(160), nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("artifact_id", "section_key",
                            name="uq_playbook_section_key"),
    )
    op.create_index("ix_playbook_sections_artifact",
                    "playbook_document_sections", ["artifact_id", "ordinal"])

    op.create_table(
        "playbook_metric_bindings",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("workspace_id", sa.BigInteger,
                  sa.ForeignKey("playbook_workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artifact_id", sa.BigInteger,
                  sa.ForeignKey("playbook_artifacts.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("section_key", sa.String(128), nullable=False,
                  server_default=""),
        # Identity. `metric_id` is the governed key; the label is what the
        # document happens to call it and is never what a binding rests on.
        sa.Column("metric_id", sa.String(160), nullable=False),
        sa.Column("canonical_name", sa.String(240), nullable=False,
                  server_default=""),
        sa.Column("catalogue_id", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("label", sa.String(240), nullable=False, server_default=""),
        # Dimensions that make two same-named metrics different metrics.
        sa.Column("unit", sa.String(32), nullable=False, server_default=""),
        sa.Column("currency", sa.String(16), nullable=False, server_default=""),
        sa.Column("population", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("segment", sa.String(160), nullable=False, server_default=""),
        sa.Column("reporting_period", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("scenario", sa.String(96), nullable=False, server_default=""),
        # Provenance.
        sa.Column("source_module", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("source_export_revision_id", sa.BigInteger, nullable=True),
        sa.Column("source_id", sa.BigInteger, nullable=True),
        sa.Column("source_locator", sa.String(400), nullable=False,
                  server_default=""),
        # Three readings of one fact, as `sheets` now preserves them.
        sa.Column("value_in_document", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("display_value", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("raw_value", sa.String(96), nullable=False,
                  server_default=""),
        sa.Column("as_of", sa.String(48), nullable=False, server_default=""),
        # How the link was made, and whether a person stands behind it.
        sa.Column("binding_method", sa.String(32), nullable=False,
                  server_default="unlinked"),
        sa.Column("confidence", sa.String(16), nullable=False,
                  server_default=""),
        sa.Column("confirmed_by_user", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("confirmed_by", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_strategy", sa.String(32), nullable=False,
                  server_default="on_request"),
        sa.Column("freshness", sa.String(24), nullable=False,
                  server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_playbook_bindings_workspace",
                    "playbook_metric_bindings", ["workspace_id", "metric_id"])

    op.create_table(
        "playbook_metric_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("artifact_id", sa.BigInteger,
                  sa.ForeignKey("playbook_artifacts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("version_id", sa.BigInteger, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("section_key", sa.String(128), nullable=False,
                  server_default=""),
        sa.Column("metric_id", sa.String(160), nullable=False),
        sa.Column("label", sa.String(240), nullable=False, server_default=""),
        sa.Column("value", sa.String(96), nullable=False, server_default=""),
        sa.Column("display_value", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("unit", sa.String(32), nullable=False, server_default=""),
        sa.Column("as_of", sa.String(48), nullable=False, server_default=""),
        sa.Column("reporting_period", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("source_locator", sa.String(400), nullable=False,
                  server_default=""),
        sa.Column("source_export_revision_id", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        # One reading per metric per version. Frozen, and never updated: a
        # snapshot that moves when today's data moves is not a snapshot.
        sa.UniqueConstraint("version_id", "metric_id", "section_key",
                            name="uq_playbook_snapshot_metric"),
    )
    op.create_index("ix_playbook_snapshots_artifact",
                    "playbook_metric_snapshots", ["artifact_id", "version"])

    op.create_table(
        "playbook_findings",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("workspace_id", sa.BigInteger,
                  sa.ForeignKey("playbook_workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artifact_id", sa.BigInteger, nullable=True),
        sa.Column("section_key", sa.String(128), nullable=False,
                  server_default=""),
        sa.Column("reference", sa.String(32), nullable=False, server_default=""),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False,
                  server_default="information"),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="open"),
        sa.Column("raised_by", sa.String(32), nullable=False,
                  server_default="rule"),
        sa.Column("rationale", sa.Text, nullable=False, server_default=""),
        sa.Column("metric_id", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("threshold", sa.String(64), nullable=False, server_default=""),
        sa.Column("previous_value", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("current_value", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("source_locator", sa.String(400), nullable=False,
                  server_default=""),
        sa.Column("owner", sa.String(160), nullable=False, server_default=""),
        sa.Column("answer", sa.Text, nullable=False, server_default=""),
        sa.Column("answered_by", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.Text, nullable=False, server_default=""),
        # A high finding left unanswered is what stops a pack being ready.
        sa.Column("blocking", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("evidence", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_playbook_findings_workspace", "playbook_findings",
                    ["workspace_id", "status", "severity"])

    op.create_table(
        "playbook_decisions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("workspace_id", sa.BigInteger,
                  sa.ForeignKey("playbook_workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artifact_id", sa.BigInteger, nullable=True),
        sa.Column("reference", sa.String(32), nullable=False, server_default=""),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("recommendation", sa.Text, nullable=False,
                  server_default=""),
        sa.Column("options", JSONB, nullable=False, server_default="[]"),
        sa.Column("current_position", sa.String(240), nullable=False,
                  server_default=""),
        sa.Column("proposed_position", sa.String(240), nullable=False,
                  server_default=""),
        sa.Column("effective_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="outstanding"),
        sa.Column("outcome", sa.String(32), nullable=False, server_default=""),
        # Who decided. Never a model: a decision with no human actor is not a
        # decision, and the column is how that is enforced rather than hoped.
        sa.Column("decided_by", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meeting", sa.String(160), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text, nullable=False, server_default=""),
        sa.Column("evidence", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_playbook_decisions_workspace", "playbook_decisions",
                    ["workspace_id", "status"])

    op.create_table(
        "playbook_actions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("workspace_id", sa.BigInteger,
                  sa.ForeignKey("playbook_workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("decision_id", sa.BigInteger,
                  sa.ForeignKey("playbook_decisions.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("finding_id", sa.BigInteger,
                  sa.ForeignKey("playbook_findings.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("reference", sa.String(32), nullable=False, server_default=""),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("owner", sa.String(160), nullable=False, server_default=""),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="open"),
        sa.Column("last_update", sa.Text, nullable=False, server_default=""),
        sa.Column("last_update_at", sa.DateTime(timezone=True), nullable=True),
        # Where execution lives when a planner is connected. A clean contract,
        # so this branch does not depend on a module that is not here.
        sa.Column("external_system", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("external_ref", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_playbook_actions_workspace", "playbook_actions",
                    ["workspace_id", "status"])

    op.create_table(
        "playbook_reviews",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("workspace_id", sa.BigInteger,
                  sa.ForeignKey("playbook_workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artifact_id", sa.BigInteger, nullable=True),
        sa.Column("section_key", sa.String(128), nullable=False,
                  server_default=""),
        sa.Column("reviewer", sa.String(160), nullable=False),
        sa.Column("role", sa.String(48), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="requested"),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column("requested_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_playbook_reviews_workspace", "playbook_reviews",
                    ["workspace_id", "status"])

    op.create_table(
        "playbook_readiness",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("workspace_id", sa.BigInteger,
                  sa.ForeignKey("playbook_workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("artifact_id", sa.BigInteger, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completion_pct", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("readiness_pct", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("approval_status", sa.String(32), nullable=False,
                  server_default="pending"),
        # Every component that produced the two percentages, with its own
        # score, its explanation and its blocking reason. A number nobody can
        # click into is a number nobody should trust.
        sa.Column("components", JSONB, nullable=False, server_default="[]"),
        sa.Column("blockers", JSONB, nullable=False, server_default="[]"),
        sa.Column("statistics", JSONB, nullable=False, server_default="{}"),
        sa.Column("computed_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "artifact_id",
                            name="uq_playbook_readiness_artifact"),
    )

    op.create_table(
        "playbook_source_parses",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source_id", sa.BigInteger,
                  sa.ForeignKey("playbook_sources.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="parsed"),
        sa.Column("chunk_count", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("manifest", JSONB, nullable=False, server_default="{}"),
        sa.Column("failure_reason", sa.Text, nullable=False, server_default=""),
        sa.Column("superseded", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_id", "revision",
                            name="uq_playbook_source_parse_revision"),
    )
    op.create_index("ix_playbook_source_parses_source",
                    "playbook_source_parses", ["source_id", "revision"])


def downgrade() -> None:
    for table in ("playbook_source_parses", "playbook_readiness",
                  "playbook_reviews", "playbook_actions", "playbook_decisions",
                  "playbook_findings", "playbook_metric_snapshots",
                  "playbook_metric_bindings", "playbook_document_sections",
                  "playbook_document_profiles"):
        op.drop_table(table)
