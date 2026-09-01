"""§29-§37: Regulatory Intelligence — runs, requirements, corrections,
contradictions and drafts.

Five tables between the document and the release, and the split between them
is the governance:

    regulatory_runs            where a document is in §29's sixteen stages.
                               One row per RUN: re-extracting a circular
                               after an OCR engine arrives is a new attempt,
                               and folding it into the first would lose the
                               fact that the first could not read it.
    regulatory_requirements    §30's schema. What the text requires and what
                               it would touch HERE — a claim about
                               consequences, not a reading of words.
    regulatory_corrections     §33. What the machine read and what a person
                               said, side by side. A correction from one
                               user is not automatically authoritative, and
                               `authoritative` is False on every insert.
    regulatory_contradictions  §34's twelve classes and ten resolutions,
                               none of which is "delete the other one".
    regulatory_drafts          §35's proposed changes, addressed to whichever
                               subsystem owns the thing. Applied by none of
                               them until all five gates are cleared.

Nothing created here is retrievable. A requirement reaches a live answer
only through an active Regulatory Release.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE regulatory_runs (
            id BIGSERIAL NOT NULL,
            run_id VARCHAR(48) NOT NULL,
            document_id VARCHAR(64) NOT NULL,
            stage VARCHAR(48) NOT NULL,
            stage_history JSONB NOT NULL,
            blockers JSONB NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            started_by VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_regulatory_run UNIQUE (run_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_regulatory_run_document ON regulatory_runs (document_id, created_at)")
    op.execute("CREATE INDEX ix_regulatory_run_stage ON regulatory_runs (tenant, stage)")

    op.execute(
        """
        CREATE TABLE regulatory_requirements (
            id BIGSERIAL NOT NULL,
            requirement_id VARCHAR(48) NOT NULL,
            document_id VARCHAR(64) NOT NULL,
            run_id VARCHAR(48) NOT NULL,
            schema_version VARCHAR(16) NOT NULL,
            page INTEGER NOT NULL,
            section_number VARCHAR(64) NOT NULL,
            section_title VARCHAR(320) NOT NULL,
            paragraph VARCHAR(32) NOT NULL,
            excerpt TEXT NOT NULL,
            excerpt_truncated BOOLEAN NOT NULL,
            summary TEXT NOT NULL,
            requirement_type VARCHAR(24) NOT NULL,
            relevance VARCHAR(24) NOT NULL,
            topics JSONB NOT NULL,
            jurisdiction VARCHAR(64) NOT NULL,
            effective_from TIMESTAMP WITH TIME ZONE,
            effective_to TIMESTAMP WITH TIME ZONE,
            portfolio_scope JSONB NOT NULL,
            product_scope JSONB NOT NULL,
            affected JSONB NOT NULL,
            interpretation_confidence FLOAT NOT NULL,
            confidence_because JSONB NOT NULL,
            validation_status VARCHAR(32) NOT NULL,
            reviewer VARCHAR(64) NOT NULL,
            decision VARCHAR(32) NOT NULL,
            decision_reason TEXT NOT NULL,
            correction TEXT NOT NULL,
            version INTEGER NOT NULL,
            conflicts JSONB NOT NULL,
            promotion_status VARCHAR(24) NOT NULL,
            promoted_as VARCHAR(64) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_regulatory_requirement UNIQUE (requirement_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_regulatory_req_document ON regulatory_requirements (document_id, validation_status)")
    op.execute("CREATE INDEX ix_regulatory_req_queue ON regulatory_requirements (tenant, validation_status, interpretation_confidence)")
    op.execute("CREATE INDEX ix_regulatory_req_type ON regulatory_requirements (requirement_type, relevance)")

    op.execute(
        """
        CREATE TABLE regulatory_corrections (
            id BIGSERIAL NOT NULL,
            correction_id VARCHAR(48) NOT NULL,
            requirement_id VARCHAR(48) NOT NULL,
            document_id VARCHAR(64) NOT NULL,
            original_interpretation TEXT NOT NULL,
            original_type VARCHAR(24) NOT NULL,
            original_confidence FLOAT NOT NULL,
            correction TEXT NOT NULL,
            corrected_type VARCHAR(24) NOT NULL,
            reason TEXT NOT NULL,
            user_id VARCHAR(64) NOT NULL,
            user_role VARCHAR(32) NOT NULL,
            scope VARCHAR(160) NOT NULL,
            effective_date VARCHAR(32) NOT NULL,
            proposed_target JSONB NOT NULL,
            review_status VARCHAR(32) NOT NULL,
            conflict_impact JSONB NOT NULL,
            regression_tests JSONB NOT NULL,
            authoritative BOOLEAN NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_regulatory_correction UNIQUE (correction_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_regulatory_correction_req ON regulatory_corrections (requirement_id)")
    op.execute("CREATE INDEX ix_regulatory_correction_user ON regulatory_corrections (tenant, user_id)")

    op.execute(
        """
        CREATE TABLE regulatory_contradictions (
            id BIGSERIAL NOT NULL,
            contradiction_id VARCHAR(48) NOT NULL,
            requirement_id VARCHAR(48) NOT NULL,
            document_id VARCHAR(64) NOT NULL,
            conflict_class VARCHAR(48) NOT NULL,
            severity VARCHAR(16) NOT NULL,
            summary TEXT NOT NULL,
            incoming JSONB NOT NULL,
            existing JSONB NOT NULL,
            available_resolutions JSONB NOT NULL,
            resolution VARCHAR(40) NOT NULL,
            resolution_reason TEXT NOT NULL,
            effective_from VARCHAR(32) NOT NULL,
            split_axis VARCHAR(64) NOT NULL,
            resolved_by VARCHAR(64) NOT NULL,
            resolved_at TIMESTAMP WITH TIME ZONE,
            tenant VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_regulatory_contradiction UNIQUE (contradiction_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_regulatory_contradiction_req ON regulatory_contradictions (requirement_id)")
    op.execute("CREATE INDEX ix_regulatory_contradiction_open ON regulatory_contradictions (tenant, severity, resolution)")

    op.execute(
        """
        CREATE TABLE regulatory_drafts (
            id BIGSERIAL NOT NULL,
            draft_id VARCHAR(48) NOT NULL,
            requirement_id VARCHAR(48) NOT NULL,
            document_id VARCHAR(64) NOT NULL,
            target VARCHAR(64) NOT NULL,
            summary TEXT NOT NULL,
            payload JSONB NOT NULL,
            citation JSONB NOT NULL,
            effective_from VARCHAR(32) NOT NULL,
            governance_owner VARCHAR(160) NOT NULL,
            status VARCHAR(32) NOT NULL,
            gates_passed JSONB NOT NULL,
            version INTEGER NOT NULL,
            release_id VARCHAR(64) NOT NULL,
            tenant VARCHAR(64) NOT NULL,
            created_by VARCHAR(64) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_regulatory_draft UNIQUE (draft_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_regulatory_draft_status ON regulatory_drafts (tenant, status, target)")
    op.execute("CREATE INDEX ix_regulatory_draft_req ON regulatory_drafts (requirement_id)")


def downgrade() -> None:
    op.drop_table("regulatory_drafts")
    op.drop_table("regulatory_contradictions")
    op.drop_table("regulatory_corrections")
    op.drop_table("regulatory_requirements")
    op.drop_table("regulatory_runs")

