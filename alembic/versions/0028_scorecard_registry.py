"""§12, §94: the Retail Scorecard Model Registry.

Ten tables, and the split between them is the point. What a scorecard
*computes* is small and already lives beside the lake: a binning
specification, an intercept and five or six coefficients. What an
institution *decided* about that scorecard is larger, changes on a different
clock, and has to outlive the build - which regenerates the demonstration
universe wholesale.

    scorecard_models            §12. One registered version. §35's
                                candidates are rows here with status
                                CANDIDATE; activating one never overwrites
                                the ACTIVE row, it writes a new one.
    scorecard_model_variables   Active and candidate variables. A variable
                                considered and not used is a fact a
                                validator asks about, and a five-term
                                equation cannot express it.
    scorecard_binning_specs     §10. Versioned WoE bins, never edited in
                                place, so re-binning on the validation
                                month is a new row somebody has to point a
                                model at rather than a quiet overwrite.
    scorecard_policy_limits     §26/§80. Every limit carries its source.
                                Seeded rows are DEMO_POLICY: conventional
                                PSI and CSI cutoffs are not regulatory
                                requirements and must not be shown as
                                though they were.
    scorecard_validation_runs   One validation of one model over one
                                period, carrying whether the performance
                                window had closed (§7).
    scorecard_findings          §48. A finding with the evidence and the
                                runs that produced it.
    scorecard_model_approvals   Append-only status transitions. The model
                                row says where it is; this says how it got
                                there.
    scorecard_dashboard_pins    What a user chose to watch.
    scorecard_reports           §51-§56. A generated report, storing the
                                disclaimer it was issued with rather than
                                rendering it fresh at download time.
    scorecard_report_evidence   §55. Every figure a report prints, and the
                                run and workbook cell it came from.

Every table that describes data carries `origin`, defaulting to
SYNTHETIC_DEMO (§2). Nothing generated here is client data, and the marker
travels with the row rather than sitting in a caption somebody can crop.

Reuses users, workflow, notifications, audit, Investigations, Analyses,
Trace and Assurance rather than restating them: a finding points at an
analysis run id, a report points at a validation run, and neither invents a
second copy of a table that already exists.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

TABLES = (
    "scorecard_report_evidence",
    "scorecard_reports",
    "scorecard_dashboard_pins",
    "scorecard_model_approvals",
    "scorecard_findings",
    "scorecard_validation_runs",
    "scorecard_policy_limits",
    "scorecard_binning_specs",
    "scorecard_model_variables",
    "scorecard_models",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE scorecard_models (
            id BIGSERIAL NOT NULL,
            model_id VARCHAR(64) NOT NULL,
            model_name VARCHAR(160) NOT NULL,
            scorecard_type VARCHAR(24) NOT NULL,
            model_version VARCHAR(32) NOT NULL,
            status VARCHAR(24) NOT NULL,
            owner VARCHAR(120) NOT NULL,
            developer VARCHAR(120) NOT NULL,
            validator VARCHAR(120) NOT NULL,
            development_period VARCHAR(64) NOT NULL,
            validation_period VARCHAR(64) NOT NULL,
            performance_horizon_months INTEGER NOT NULL,
            default_definition JSONB DEFAULT '{}'::jsonb NOT NULL,
            target VARCHAR(64) NOT NULL,
            population VARCHAR(240) NOT NULL,
            product_scope VARCHAR(240) NOT NULL,
            baseline_population VARCHAR(240) NOT NULL,
            binning_spec_version VARCHAR(48) NOT NULL,
            woe_spec_version VARCHAR(48) NOT NULL,
            intercept FLOAT NOT NULL,
            equation JSONB DEFAULT '{}'::jsonb NOT NULL,
            logit_direction VARCHAR(32) NOT NULL,
            pd_mapping VARCHAR(32) NOT NULL,
            base_score FLOAT,
            pdo FLOAT,
            base_odds FLOAT,
            score_direction VARCHAR(32) NOT NULL,
            min_score FLOAT,
            max_score FLOAT,
            cutoffs JSONB DEFAULT '{}'::jsonb NOT NULL,
            risk_bands JSONB DEFAULT '{}'::jsonb NOT NULL,
            implementation_date VARCHAR(24) NOT NULL,
            last_validation_date VARCHAR(24) NOT NULL,
            materiality VARCHAR(32) NOT NULL,
            model_risk_rating VARCHAR(32) NOT NULL,
            regulatory_references JSONB DEFAULT '[]'::jsonb NOT NULL,
            origin VARCHAR(32) NOT NULL,
            based_on_model_id VARCHAR(64) NOT NULL,
            notes TEXT NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_by VARCHAR(120) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_scorecard_model_version UNIQUE (tenant, model_id, model_version)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_model_type ON scorecard_models (tenant, scorecard_type, status)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_model_variables (
            id BIGSERIAL NOT NULL,
            model_id VARCHAR(64) NOT NULL,
            model_version VARCHAR(32) NOT NULL,
            variable VARCHAR(120) NOT NULL,
            role VARCHAR(24) NOT NULL,
            coefficient FLOAT,
            transformation VARCHAR(24) NOT NULL,
            information_value FLOAT,
            risk_direction VARCHAR(24) NOT NULL,
            scoreable BOOLEAN NOT NULL,
            position INTEGER NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_scorecard_model_variable UNIQUE (tenant, model_id, model_version, variable)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_model_variable_model ON scorecard_model_variables (tenant, model_id, model_version)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_binning_specs (
            id BIGSERIAL NOT NULL,
            spec_version VARCHAR(48) NOT NULL,
            scorecard_type VARCHAR(24) NOT NULL,
            development_population VARCHAR(240) NOT NULL,
            target VARCHAR(64) NOT NULL,
            spec JSONB DEFAULT '{}'::jsonb NOT NULL,
            variable_count INTEGER NOT NULL,
            origin VARCHAR(32) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_by VARCHAR(120) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_scorecard_binning_spec UNIQUE (tenant, spec_version)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_binning_spec_type ON scorecard_binning_specs (tenant, scorecard_type)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_policy_limits (
            id BIGSERIAL NOT NULL,
            policy_version VARCHAR(32) NOT NULL,
            metric VARCHAR(64) NOT NULL,
            scorecard_type VARCHAR(24) NOT NULL,
            source VARCHAR(32) NOT NULL,
            comparison VARCHAR(16) NOT NULL,
            warn_at FLOAT,
            breach_at FLOAT,
            unit VARCHAR(24) NOT NULL,
            rationale TEXT NOT NULL,
            approved_by VARCHAR(120) NOT NULL,
            approved_at TIMESTAMP WITH TIME ZONE,
            active BOOLEAN NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_scorecard_policy_limit UNIQUE (tenant, policy_version, metric, scorecard_type)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_policy_limit_metric ON scorecard_policy_limits (tenant, metric, active)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_validation_runs (
            id BIGSERIAL NOT NULL,
            run_id VARCHAR(48) NOT NULL,
            model_id VARCHAR(64) NOT NULL,
            model_version VARCHAR(32) NOT NULL,
            scorecard_type VARCHAR(24) NOT NULL,
            period VARCHAR(16) NOT NULL,
            matured BOOLEAN NOT NULL,
            performance_window_closes VARCHAR(16) NOT NULL,
            population_rows INTEGER NOT NULL,
            metrics JSONB DEFAULT '{}'::jsonb NOT NULL,
            opinion VARCHAR(48) NOT NULL,
            opinion_reasoning TEXT NOT NULL,
            policy_version VARCHAR(32) NOT NULL,
            binning_spec_version VARCHAR(48) NOT NULL,
            analysis_id VARCHAR(48) NOT NULL,
            trace_id VARCHAR(48) NOT NULL,
            origin VARCHAR(32) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_by VARCHAR(120) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_scorecard_run UNIQUE (tenant, run_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_run_model ON scorecard_validation_runs (tenant, model_id, period)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_findings (
            id BIGSERIAL NOT NULL,
            finding_id VARCHAR(48) NOT NULL,
            model_id VARCHAR(64) NOT NULL,
            model_version VARCHAR(32) NOT NULL,
            period VARCHAR(16) NOT NULL,
            category VARCHAR(48) NOT NULL,
            title VARCHAR(240) NOT NULL,
            description TEXT NOT NULL,
            severity VARCHAR(24) NOT NULL,
            metric VARCHAR(64) NOT NULL,
            observed FLOAT,
            limit_value FLOAT,
            limit_source VARCHAR(32) NOT NULL,
            breach BOOLEAN NOT NULL,
            impact TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            evidence JSONB DEFAULT '[]'::jsonb NOT NULL,
            analysis_run_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
            owner VARCHAR(120) NOT NULL,
            status VARCHAR(24) NOT NULL,
            due_date VARCHAR(24) NOT NULL,
            approved_by VARCHAR(120) NOT NULL,
            approved_at TIMESTAMP WITH TIME ZONE,
            closed_at TIMESTAMP WITH TIME ZONE,
            validation_run_id VARCHAR(48) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_by VARCHAR(120) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_scorecard_finding UNIQUE (tenant, finding_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_finding_model ON scorecard_findings (tenant, model_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_finding_severity ON scorecard_findings (tenant, severity, status)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_model_approvals (
            id BIGSERIAL NOT NULL,
            model_id VARCHAR(64) NOT NULL,
            model_version VARCHAR(32) NOT NULL,
            from_status VARCHAR(24) NOT NULL,
            to_status VARCHAR(24) NOT NULL,
            decision VARCHAR(24) NOT NULL,
            rationale TEXT NOT NULL,
            conditions TEXT NOT NULL,
            committee VARCHAR(120) NOT NULL,
            decided_by VARCHAR(120) NOT NULL,
            decided_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_approval_model ON scorecard_model_approvals (tenant, model_id, model_version, decided_at)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_dashboard_pins (
            id BIGSERIAL NOT NULL,
            user_id BIGINT,
            scorecard_type VARCHAR(24) NOT NULL,
            model_id VARCHAR(64) NOT NULL,
            kind VARCHAR(24) NOT NULL,
            reference VARCHAR(120) NOT NULL,
            label VARCHAR(160) NOT NULL,
            position INTEGER NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_scorecard_pin UNIQUE (tenant, user_id, scorecard_type, model_id, kind, reference),
            FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_pin_user ON scorecard_dashboard_pins (tenant, user_id, scorecard_type)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_reports (
            id BIGSERIAL NOT NULL,
            report_id VARCHAR(48) NOT NULL,
            model_id VARCHAR(64) NOT NULL,
            model_version VARCHAR(32) NOT NULL,
            scorecard_type VARCHAR(24) NOT NULL,
            period VARCHAR(16) NOT NULL,
            validation_run_id VARCHAR(48) NOT NULL,
            title VARCHAR(240) NOT NULL,
            structure_version VARCHAR(32) NOT NULL,
            opinion VARCHAR(48) NOT NULL,
            status VARCHAR(24) NOT NULL,
            docx_path VARCHAR(512) NOT NULL,
            evidence_path VARCHAR(512) NOT NULL,
            sections JSONB DEFAULT '[]'::jsonb NOT NULL,
            disclaimer TEXT NOT NULL,
            origin VARCHAR(32) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_by VARCHAR(120) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_scorecard_report UNIQUE (tenant, report_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_report_model ON scorecard_reports (tenant, model_id, period)
        """
    )
    op.execute(
        """
        CREATE TABLE scorecard_report_evidence (
            id BIGSERIAL NOT NULL,
            report_id VARCHAR(48) NOT NULL,
            section VARCHAR(120) NOT NULL,
            label VARCHAR(240) NOT NULL,
            metric VARCHAR(64) NOT NULL,
            value FLOAT,
            value_text VARCHAR(120) NOT NULL,
            validation_run_id VARCHAR(48) NOT NULL,
            analysis_id VARCHAR(48) NOT NULL,
            trace_id VARCHAR(48) NOT NULL,
            workbook_sheet VARCHAR(64) NOT NULL,
            workbook_cell VARCHAR(24) NOT NULL,
            position INTEGER NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_scorecard_report_evidence_report ON scorecard_report_evidence (tenant, report_id, position)
        """
    )


def downgrade() -> None:
    # Dropped children-first: findings and evidence reference a model row by
    # id rather than by foreign key, but the order still matters for anyone
    # reading this to understand what depends on what.
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
