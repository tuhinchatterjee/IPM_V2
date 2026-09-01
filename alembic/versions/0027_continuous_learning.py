"""§57, §59, §72: Continuous Learning — baselines, snapshots and partition use.

Three append-only tables, and append-only is the whole subsystem: a
measurement that can be recomputed after somebody noticed the number looked
wrong is not a measurement.

    learning_baselines  §57. What this installation was and how it performed
                        when a Brain was activated or a release went live.
                        Mostly versions, because "compared to what?" is
                        answered by an ontology version and a case-set
                        version, not by a date.
    learning_snapshots  §59. A measurement at a moment, against a baseline.
                        Every development figure has its validation twin in
                        the next column — development is the set that was
                        tuned against and always looks better, so storing
                        one of each pair would be storing the flattering one.
    evaluation_uses     §72. Which partition was evaluated and why, so
                        validation drifting into a second development set is
                        visible while it is still reversible.

No sealed-holdout CONTENT appears in any of them. §58 names six places it
may never reach and the continuous-learning UI is one; the holdout's
VERSION is recorded, which says which exam was sat without circulating the
questions.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE learning_baselines (
            id BIGSERIAL NOT NULL,
            baseline_id VARCHAR(48) NOT NULL,
            instance_id VARCHAR(64) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            activated_at TIMESTAMP WITH TIME ZONE,
            build_sha VARCHAR(40) NOT NULL,
            app_version VARCHAR(32) NOT NULL,
            brain_id VARCHAR(64) NOT NULL,
            brain_version VARCHAR(32) NOT NULL,
            intelligence_release_id VARCHAR(64) NOT NULL,
            teaching_release_id VARCHAR(64) NOT NULL,
            regulatory_release_id VARCHAR(64) NOT NULL,
            ontology_version VARCHAR(16) NOT NULL,
            blueprint_version VARCHAR(16) NOT NULL,
            judgment_policy_version VARCHAR(16) NOT NULL,
            visualization_grammar_version VARCHAR(16) NOT NULL,
            routing_policy_version VARCHAR(16) NOT NULL,
            prompt_versions JSONB NOT NULL,
            model_role_configuration JSONB NOT NULL,
            development_set_version VARCHAR(32) NOT NULL,
            validation_set_version VARCHAR(32) NOT NULL,
            sealed_holdout_version VARCHAR(32) NOT NULL,
            development_metrics JSONB NOT NULL,
            validation_metrics JSONB NOT NULL,
            critical_failure_counts JSONB NOT NULL,
            coverage_metrics JSONB NOT NULL,
            six_dimension_scores JSONB NOT NULL,
            subcomponent_scores JSONB NOT NULL,
            case_counts JSONB NOT NULL,
            learning_ledger_counts JSONB NOT NULL,
            approved_learning_counts JSONB NOT NULL,
            known_limitations JSONB NOT NULL,
            fingerprint VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_learning_baseline UNIQUE (baseline_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_learning_baseline_tenant ON learning_baselines (tenant, created_at)")
    op.execute("CREATE INDEX ix_learning_baseline_brain ON learning_baselines (brain_id, brain_version)")

    op.execute(
        """
        CREATE TABLE learning_snapshots (
            id BIGSERIAL NOT NULL,
            snapshot_id VARCHAR(48) NOT NULL,
            instance_id VARCHAR(64) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            window_start TIMESTAMP WITH TIME ZONE,
            window_end TIMESTAMP WITH TIME ZONE,
            trigger VARCHAR(32) NOT NULL,
            brain_id VARCHAR(64) NOT NULL,
            brain_version VARCHAR(32) NOT NULL,
            intelligence_release_id VARCHAR(64) NOT NULL,
            development_set_version VARCHAR(32) NOT NULL,
            validation_set_version VARCHAR(32) NOT NULL,
            development_scores JSONB NOT NULL,
            validation_scores JSONB NOT NULL,
            six_dimension_scores_dev JSONB NOT NULL,
            six_dimension_scores_validation JSONB NOT NULL,
            subcomponent_scores_dev JSONB NOT NULL,
            subcomponent_scores_validation JSONB NOT NULL,
            critical_failures_dev INTEGER NOT NULL,
            critical_failures_validation INTEGER NOT NULL,
            coverage_dev FLOAT NOT NULL,
            coverage_validation FLOAT NOT NULL,
            accepted_answer_precision_dev FLOAT NOT NULL,
            accepted_answer_precision_validation FLOAT NOT NULL,
            abstention_rate_dev FLOAT NOT NULL,
            abstention_rate_validation FLOAT NOT NULL,
            case_count_dev INTEGER NOT NULL,
            case_count_validation INTEGER NOT NULL,
            latency_ms FLOAT NOT NULL,
            tokens BIGINT NOT NULL,
            estimated_cost FLOAT NOT NULL,
            new_learning_captured INTEGER NOT NULL,
            new_learning_reviewed INTEGER NOT NULL,
            new_learning_approved INTEGER NOT NULL,
            new_learning_rejected INTEGER NOT NULL,
            new_learning_activated INTEGER NOT NULL,
            new_teaching_cases INTEGER NOT NULL,
            new_regulatory_items INTEGER NOT NULL,
            new_blueprint_changes INTEGER NOT NULL,
            new_policy_changes INTEGER NOT NULL,
            new_method_changes INTEGER NOT NULL,
            new_feedback_regressions INTEGER NOT NULL,
            open_learning_items INTEGER NOT NULL,
            known_limitations JSONB NOT NULL,
            comparison_baseline_id VARCHAR(48) NOT NULL,
            fingerprint VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_learning_snapshot UNIQUE (snapshot_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_learning_snapshot_window ON learning_snapshots (tenant, created_at)")
    op.execute("CREATE INDEX ix_learning_snapshot_trigger ON learning_snapshots (tenant, trigger, created_at)")
    op.execute("CREATE INDEX ix_learning_snapshot_baseline ON learning_snapshots (comparison_baseline_id)")

    op.execute(
        """
        CREATE TABLE evaluation_uses (
            id BIGSERIAL NOT NULL,
            partition VARCHAR(24) NOT NULL,
            purpose VARCHAR(240) NOT NULL,
            by VARCHAR(64) NOT NULL,
            snapshot_id VARCHAR(48) NOT NULL,
            case_count INTEGER NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id)
        )
        """
    )
    op.execute("CREATE INDEX ix_evaluation_use_partition ON evaluation_uses (tenant, partition, created_at)")


def downgrade() -> None:
    op.drop_table("evaluation_uses")
    op.drop_table("learning_snapshots")
    op.drop_table("learning_baselines")

