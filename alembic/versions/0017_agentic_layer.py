"""The governed agentic layer: agents, runs, tasks, jobs, cases.

Twelve tables. What they are for, and what they are deliberately not for:

They record COORDINATION. An agent run says which officer was selected, which
specialists were delegated to, which governed tools they called, over which data
versions, under which budget, checked by whom, and approved by which person.
Every credit figure any of it produced lives where credit figures already live —
in an AnalysisRun with a Trace and a plan fingerprint — and is referenced from
here by id. There is no column in this migration that holds an ECL number an
agent decided on, and that absence is the architecture.

Three constraints carry most of the safety:

- `uq_agent_event_once` on (kind, idempotency_key). A publication delivered
  twice produces one event, therefore one run, therefore one set of cases.
- `uq_risk_case_dedupe` on dedupe_key. A replayed review updates the case it
  already made rather than making a second one — §70's "no duplicate cases on
  replay" as a database constraint rather than an if-statement.
- `ix_agent_jobs_claim`. The queue's claim query is
  `... WHERE status='queued' AND scheduled_at <= now() ORDER BY priority DESC,
  scheduled_at FOR UPDATE SKIP LOCKED LIMIT 1`, and this index is what makes it
  a seek rather than a scan of every job ever run.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _json(name: str, default: str = "'{}'::jsonb", nullable: bool = False):
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()),
                     nullable=nullable, server_default=sa.text(default))


def _list(name: str):
    return _json(name, "'[]'::jsonb")


def upgrade() -> None:
    # ------------------------------------------------------- definitions
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=24), nullable=False,
                  server_default="1.0"),
        sa.Column("business_name", sa.String(length=120), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
        _json("definition"),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="active"),
        sa.Column("autonomy_level", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("model_role", sa.String(length=24), nullable=False,
                  server_default="router"),
        sa.Column("owner", sa.String(length=120), nullable=False,
                  server_default=""),
        sa.Column("evaluation_score", sa.Float(), nullable=True),
        sa.Column("last_validation_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("certification_state", sa.String(length=24), nullable=False,
                  server_default="unreviewed"),
        sa.Column("registry_fingerprint", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_definition"),
    )
    op.create_index("ix_agent_definitions_status", "agent_definitions",
                    ["status"])

    # ------------------------------------------------------------ events
    op.create_table(
        "agent_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("object_type", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("object_id", sa.String(length=120), nullable=False,
                  server_default=""),
        sa.Column("period", sa.String(length=32), nullable=False,
                  server_default=""),
        _json("payload"),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="received"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "idempotency_key",
                            name="uq_agent_event_once"),
    )
    op.create_index("ix_agent_events_kind", "agent_events",
                    ["kind", "created_at"])

    # -------------------------------------------------------------- runs
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_key", sa.String(length=48), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("trigger_object_type", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("trigger_object_id", sa.String(length=120), nullable=False,
                  server_default=""),
        sa.Column("event_id", sa.BigInteger(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("period", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("prior_period", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("service_identity", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("role", sa.String(length=24), nullable=False,
                  server_default=""),
        sa.Column("project_id", sa.BigInteger(), nullable=True),
        sa.Column("investigation_id", sa.BigInteger(), nullable=True),
        sa.Column("analysis_run_id", sa.BigInteger(), nullable=True),
        sa.Column("officer_level", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("officer_title", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("selection_reason", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("complexity_score", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("risk_score", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("agent_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("planned_task_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("orchestrator", sa.String(length=64), nullable=False,
                  server_default=""),
        _list("specialists"),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="queued"),
        sa.Column("stage", sa.String(length=24), nullable=False,
                  server_default="QUEUED"),
        _list("stage_history"),
        _json("plan"),
        _json("task_graph"),
        _json("budgets"),
        _json("usage"),
        _json("versions"),
        _list("findings"),
        _list("conflicts"),
        _list("handoffs"),
        _json("validation"),
        _json("assurance"),
        sa.Column("synthesis", sa.Text(), nullable=False, server_default=""),
        sa.Column("failure", sa.Text(), nullable=False, server_default=""),
        sa.Column("failure_kind", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("trace_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("build_sha", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["agent_events.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_agent_run_key"),
    )
    op.create_index("ix_agent_runs_status", "agent_runs",
                    ["status", "created_at"])
    op.create_index("ix_agent_runs_user", "agent_runs", ["user_id", "created_at"])
    op.create_index("ix_agent_runs_trigger", "agent_runs",
                    ["trigger", "created_at"])

    # ------------------------------------------------------------- tasks
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("task_key", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
        _list("depends_on"),
        sa.Column("layer", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool", sa.String(length=64), nullable=False,
                  server_default=""),
        _json("parameters"),
        _json("inputs"),
        _json("data_versions"),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="pending"),
        sa.Column("analysis_run_id", sa.BigInteger(), nullable=True),
        _json("result"),
        sa.Column("finding", sa.Text(), nullable=False, server_default=""),
        _json("evidence"),
        sa.Column("validation_state", sa.String(length=24), nullable=False,
                  server_default="not_required"),
        _json("validation"),
        _list("tool_calls"),
        sa.Column("retry_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("error_category", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("approval_state", sa.String(length=24), nullable=False,
                  server_default="not_required"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "task_key", name="uq_agent_task_key"),
    )
    op.create_index("ix_agent_tasks_run", "agent_tasks", ["run_id", "status"])

    # -------------------------------------------------------------- jobs
    op.create_table(
        "agent_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        _json("payload"),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False,
                  server_default="3"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False,
                  server_default="900"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_category", sa.String(length=48), nullable=False,
                  server_default=""),
        sa.Column("leased_by", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # The claim query's index. Without it every claim scans the whole table,
    # which is fine on day one and is not on day four hundred.
    op.create_index("ix_agent_jobs_claim", "agent_jobs",
                    ["status", "priority", "scheduled_at"])
    op.create_index("ix_agent_jobs_lease", "agent_jobs",
                    ["status", "lease_expires_at"])
    op.create_index("ix_agent_jobs_idem", "agent_jobs",
                    ["kind", "idempotency_key"])
    # One LIVE job per idempotency key. A partial index rather than a plain
    # unique constraint, because the same review legitimately runs again next
    # quarter — what must not happen is two of them queued at once.
    op.create_index(
        "uq_agent_jobs_live", "agent_jobs", ["kind", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"))

    # ----------------------------------------------------------- workers
    op.create_table(
        "agent_workers",
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column("hostname", sa.String(length=120), nullable=False,
                  server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="starting"),
        sa.Column("current_job_id", sa.BigInteger(), nullable=True),
        sa.Column("jobs_completed", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("jobs_failed", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("build_sha", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index("ix_agent_workers_heartbeat", "agent_workers",
                    ["heartbeat_at"])

    # --------------------------------------------------------- approvals
    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("task_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        _json("proposal"),
        _json("evidence"),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        _list("objects_affected"),
        sa.Column("risk", sa.String(length=16), nullable=False,
                  server_default="medium"),
        sa.Column("reversibility", sa.String(length=24), nullable=False,
                  server_default="reversible"),
        sa.Column("approver_role", sa.String(length=24), nullable=False,
                  server_default="ADMIN"),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="pending"),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_approvals_status", "agent_approvals",
                    ["status", "created_at"])
    op.create_index("ix_agent_approvals_run", "agent_approvals", ["run_id"])

    # --------------------------------------------------------- schedules
    op.create_table(
        "agent_schedules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("trigger", sa.String(length=48), nullable=False),
        sa.Column("scope", sa.String(length=48), nullable=False,
                  server_default="portfolio"),
        _json("scope_detail"),
        _list("agents"),
        _list("methods"),
        _list("data_requirement"),
        sa.Column("approval_policy", sa.String(length=32), nullable=False,
                  server_default="draft_only"),
        _list("notify"),
        _json("budget"),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_agent_schedule_name"),
    )

    # ---------------------------------------------------------- policies
    op.create_table(
        "agent_policies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        _json("value"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", "version", name="uq_agent_policy_version"),
    )
    op.create_index("ix_agent_policies_active", "agent_policies",
                    ["key", "active"])

    # ------------------------------------------------------- risk cases
    op.create_table(
        "risk_cases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_key", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("level", sa.String(length=24), nullable=False),
        sa.Column("entity", sa.String(length=200), nullable=False,
                  server_default=""),
        sa.Column("entity_id", sa.String(length=120), nullable=False,
                  server_default=""),
        sa.Column("entity_kind", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column("prior_period", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.Column("severity", sa.String(length=16), nullable=False,
                  server_default="medium"),
        sa.Column("severity_score", sa.Float(), nullable=False,
                  server_default="0"),
        _json("severity_detail"),
        sa.Column("severity_version", sa.String(length=16), nullable=False,
                  server_default="1.0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_coverage", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("exposure", sa.Float(), nullable=True),
        sa.Column("exposure_unit", sa.String(length=16), nullable=False,
                  server_default=""),
        _list("metrics"),
        _list("signals"),
        sa.Column("conclusion", sa.Text(), nullable=False, server_default=""),
        sa.Column("why", sa.Text(), nullable=False, server_default=""),
        _json("evidence"),
        _list("analyses"),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_run_id", sa.BigInteger(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=28), nullable=False,
                  server_default="NEW"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismiss_reason", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("resolution", sa.Text(), nullable=False, server_default=""),
        sa.Column("investigation_id", sa.BigInteger(), nullable=True),
        sa.Column("project_id", sa.BigInteger(), nullable=True),
        sa.Column("workflow_item_id", sa.BigInteger(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_event_id"], ["agent_events.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_item_id"], ["workflow_items.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_key", name="uq_risk_case_key"),
        sa.UniqueConstraint("dedupe_key", name="uq_risk_case_dedupe"),
    )
    op.create_index("ix_risk_cases_open", "risk_cases",
                    ["status", "severity_score"])
    op.create_index("ix_risk_cases_level", "risk_cases", ["level", "period"])
    op.create_index("ix_risk_cases_owner", "risk_cases", ["owner_id", "status"])

    op.create_table(
        "risk_case_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False,
                  server_default=""),
        sa.Column("relation", sa.String(length=32), nullable=False,
                  server_default="evidence"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["risk_cases.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "object_type", "object_id",
                            name="uq_risk_case_link"),
    )
    op.create_index("ix_risk_case_links_object", "risk_case_links",
                    ["object_type", "object_id"])

    op.create_table(
        "risk_case_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("from_status", sa.String(length=28), nullable=False,
                  server_default=""),
        sa.Column("to_status", sa.String(length=28), nullable=False,
                  server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        _json("detail"),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_agent", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["risk_cases.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_case_events_case", "risk_case_events",
                    ["case_id", "created_at"])


def downgrade() -> None:
    for table in ("risk_case_events", "risk_case_links", "risk_cases",
                  "agent_policies", "agent_schedules", "agent_approvals",
                  "agent_workers", "agent_jobs", "agent_tasks", "agent_runs",
                  "agent_events", "agent_definitions"):
        op.drop_table(table)
