"""§7-§24: feedback events, learning observations and governed local learning.

Nine tables. The shape of them IS the governance, so it is worth saying what
each one is for rather than listing columns:

    feedback_events              what a user said, immutably, linked to
                                 everything needed to reproduce the answer
    learning_observations        every question, labelled or not — because a
                                 corpus of complaints is a biased sample
    candidate_learning_cases     what a correction becomes, and the nine
                                 statuses between it and production
    learning_review_decisions    how a candidate got to where it is, kept
                                 separately from where it is
    learning_releases            the frozen manifest production runs under
    learning_release_activations every activation and rollback, in order, so
                                 rollback is a record rather than a
                                 reconstruction
    replay_runs                  production versus a candidate, case by case
    local_training_runs          §21's reproduction record; the artifact HASH
                                 is here and the artifact is not
    user_feedback_preferences    §13's channel A, per user, per tenant

Nothing here has an UPDATE path in the service layer for the two tables that
must not have one. A feedback event is revised by writing a new row that
points at the old one; an observation's label is the single field that
changes, and it changes once.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("supersedes", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("user_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("project_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("investigation_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("message_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("answer_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("assurance_record_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("agentic_run_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("plan_fingerprint", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("build_sha", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("rating", sa.String(16), nullable=False,
                  server_default="SKIP"),
        sa.Column("categories", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("surface", sa.String(24), nullable=False,
                  server_default="COCKPIT"),
        sa.Column("consent", sa.String(16), nullable=False,
                  server_default="UNSET"),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("reproducible", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("fingerprint", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("schema_version", sa.String(16), nullable=False,
                  server_default="1.0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_feedback_event_id", "feedback_events",
                               ["event_id"])
    op.create_index("ix_feedback_answer", "feedback_events", ["answer_id"])
    op.create_index("ix_feedback_tenant", "feedback_events",
                    ["tenant", "created_at"])
    op.create_index("ix_feedback_rating", "feedback_events",
                    ["rating", "created_at"])
    op.create_index("ix_feedback_investigation", "feedback_events",
                    ["investigation_id", "created_at"])
    op.create_index("ix_feedback_project", "feedback_events",
                    ["project_id", "created_at"])
    op.create_index("ix_feedback_user", "feedback_events",
                    ["user_id", "created_at"])

    op.create_table(
        "learning_observations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("observation_id", sa.String(64), nullable=False),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("user_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("project_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("investigation_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("message_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("answer_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("turn_index", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("officer_level", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=False,
                  server_default=""),
        sa.Column("plan_fingerprint", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("build_sha", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("label", sa.String(16), nullable=False,
                  server_default="UNLABELED"),
        sa.Column("rating", sa.String(16), nullable=False, server_default=""),
        sa.Column("feedback_event_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("fingerprint", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("schema_version", sa.String(16), nullable=False,
                  server_default="1.0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_observation_id", "learning_observations",
                               ["observation_id"])
    op.create_index("ix_observation_answer", "learning_observations",
                    ["answer_id"])
    op.create_index("ix_observation_tenant", "learning_observations",
                    ["tenant", "created_at"])
    op.create_index("ix_observation_label", "learning_observations",
                    ["label", "created_at"])
    op.create_index("ix_observation_fingerprint", "learning_observations",
                    ["fingerprint"])

    op.create_table(
        "candidate_learning_cases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False,
                  server_default="DRAFT"),
        sa.Column("failure_class", sa.String(24), nullable=False,
                  server_default="unclassified"),
        sa.Column("feedback_event_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("observation_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviewer", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("rejected_because", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("redacted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("release_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("schema_version", sa.String(16), nullable=False,
                  server_default="1.0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_candidate_id", "candidate_learning_cases",
                               ["candidate_id"])
    op.create_index("ix_candidate_status", "candidate_learning_cases",
                    ["status", "tenant"])
    op.create_index("ix_candidate_class", "candidate_learning_cases",
                    ["failure_class", "created_at"])
    op.create_index("ix_candidate_feedback", "candidate_learning_cases",
                    ["feedback_event_id"])

    op.create_table(
        "learning_review_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("action", sa.String(32), nullable=False, server_default=""),
        sa.Column("from_status", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("to_status", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("reviewer", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_review_decision_id",
                               "learning_review_decisions", ["decision_id"])
    op.create_index("ix_review_decision_candidate",
                    "learning_review_decisions",
                    ["candidate_id", "created_at"])
    op.create_index("ix_review_decision_reviewer", "learning_review_decisions",
                    ["reviewer", "created_at"])

    op.create_table(
        "learning_releases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("release_id", sa.String(64), nullable=False),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="DRAFT"),
        sa.Column("teaching_release_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("regulatory_release_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("candidate_count", sa.Integer(), nullable=False,
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
        sa.Column("build_sha", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_learning_release_id", "learning_releases",
                               ["release_id"])
    op.create_index("ix_learning_release_active", "learning_releases",
                    ["tenant", "status", "activated_at"])

    op.create_table(
        "learning_release_activations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("activation_id", sa.String(64), nullable=False),
        sa.Column("release_id", sa.String(64), nullable=False),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("action", sa.String(16), nullable=False,
                  server_default="ACTIVATED"),
        sa.Column("replaces", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("approver", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_activation_id",
                               "learning_release_activations",
                               ["activation_id"])
    op.create_index("ix_activation_release", "learning_release_activations",
                    ["release_id", "created_at"])
    op.create_index("ix_activation_tenant", "learning_release_activations",
                    ["tenant", "created_at"])

    op.create_table(
        "replay_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("release_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("case_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("improved", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("regressed", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("critical_regressions", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("clean", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("blocked_by", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("blocked_because", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_replay_run_id", "replay_runs", ["run_id"])
    op.create_index("ix_replay_release", "replay_runs",
                    ["release_id", "created_at"])
    op.create_index("ix_replay_tenant", "replay_runs", ["tenant",
                                                        "created_at"])

    op.create_table(
        "local_training_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("training_run_id", sa.String(64), nullable=False),
        sa.Column("task", sa.String(48), nullable=False, server_default=""),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("dataset_release_id", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("algorithm", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("build_sha", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("artifact_hash", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="QUEUED"),
        sa.Column("activated", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("approver", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("failure", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_training_run_id", "local_training_runs",
                               ["training_run_id"])
    op.create_index("ix_training_task", "local_training_runs",
                    ["task", "created_at"])
    op.create_index("ix_training_active", "local_training_runs",
                    ["tenant", "activated", "task"])

    op.create_table(
        "user_feedback_preferences",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("values", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("muted_threads", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_feedback_preference",
                               "user_feedback_preferences",
                               ["user_id", "tenant"])


def downgrade() -> None:
    op.drop_table("user_feedback_preferences")
    op.drop_index("ix_training_active", table_name="local_training_runs")
    op.drop_index("ix_training_task", table_name="local_training_runs")
    op.drop_table("local_training_runs")
    op.drop_index("ix_replay_tenant", table_name="replay_runs")
    op.drop_index("ix_replay_release", table_name="replay_runs")
    op.drop_table("replay_runs")
    op.drop_index("ix_activation_tenant",
                  table_name="learning_release_activations")
    op.drop_index("ix_activation_release",
                  table_name="learning_release_activations")
    op.drop_table("learning_release_activations")
    op.drop_index("ix_learning_release_active", table_name="learning_releases")
    op.drop_table("learning_releases")
    op.drop_index("ix_review_decision_reviewer",
                  table_name="learning_review_decisions")
    op.drop_index("ix_review_decision_candidate",
                  table_name="learning_review_decisions")
    op.drop_table("learning_review_decisions")
    op.drop_index("ix_candidate_feedback",
                  table_name="candidate_learning_cases")
    op.drop_index("ix_candidate_class", table_name="candidate_learning_cases")
    op.drop_index("ix_candidate_status", table_name="candidate_learning_cases")
    op.drop_table("candidate_learning_cases")
    op.drop_index("ix_observation_fingerprint",
                  table_name="learning_observations")
    op.drop_index("ix_observation_label", table_name="learning_observations")
    op.drop_index("ix_observation_tenant", table_name="learning_observations")
    op.drop_index("ix_observation_answer", table_name="learning_observations")
    op.drop_table("learning_observations")
    op.drop_index("ix_feedback_user", table_name="feedback_events")
    op.drop_index("ix_feedback_project", table_name="feedback_events")
    op.drop_index("ix_feedback_investigation", table_name="feedback_events")
    op.drop_index("ix_feedback_rating", table_name="feedback_events")
    op.drop_index("ix_feedback_tenant", table_name="feedback_events")
    op.drop_index("ix_feedback_answer", table_name="feedback_events")
    op.drop_table("feedback_events")
