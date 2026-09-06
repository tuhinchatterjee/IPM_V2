"""A project is drafted before it exists, and chased the way its manager asked.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-05

Four things the Project Planner Copilot needs that the schema did not carry.

**Who to escalate to, at three levels.** The project already knew its sponsor
and its manager. It did not know who to tell when a delay stops being the
owner's problem, and neither did a milestone or a task. Escalation is not a
role — a person can be the escalation owner for one milestone and a
contributor on the next — so it is a column on each of the three, and the
monitor walks task → milestone → project until it finds one. Nullable at
every level on purpose: inheritance is the normal case, and forcing the same
name onto fifty tasks is how a plan becomes a form nobody fills in honestly.

**How hard to chase.** `reminder_days` and `stale_after_days` were already on
the project, which is most of a policy and none of an answer to "how should
the agent behave here?". `agentic_mode` names the answer — Light, Standard,
Critical, Custom — and `agentic_policy` carries the thresholds when the answer
is Custom. Both default to Standard, so every project that exists today keeps
being monitored exactly as it is.

**What a milestone is.** It had a name, an owner and a target date. A plan
that a person builds milestone by milestone needs a start as well as an end,
a critical date that is not the end date (the date after which the milestone
cannot recover, which is what a committee actually cares about), a priority,
and a progress figure. Added rather than derived: the derived number answers
"how much of the work under this is done", and the stated one answers "what
does the owner say", and a project where those disagree is a project worth
looking at.

**A draft is not a project.** `planner_drafts` holds a plan being built. It
is deliberately ONE table with a JSONB document rather than a shadow copy of
the six planner tables. A draft is a working document: nobody reports across
drafts, nothing joins to a draft milestone, and the moment it is published it
becomes real rows through the ordinary service layer. Six draft tables would
be six more things to migrate every time the real schema moves, and the first
time they drifted the preview would show something publish could not create.
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
    # ------------------------------------------------ escalation, at three levels
    op.add_column("planner_projects", sa.Column(
        "owner_id", sa.BigInteger(), nullable=True))
    op.add_column("planner_projects", sa.Column(
        "escalation_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_planner_projects_owner", "planner_projects",
                          "users", ["owner_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_planner_projects_escalation", "planner_projects",
                          "users", ["escalation_id"], ["id"],
                          ondelete="SET NULL")

    op.add_column("planner_milestones", sa.Column(
        "escalation_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_planner_milestones_escalation",
                          "planner_milestones", "users", ["escalation_id"],
                          ["id"], ondelete="SET NULL")

    op.add_column("planner_tasks", sa.Column(
        "escalation_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_planner_tasks_escalation", "planner_tasks",
                          "users", ["escalation_id"], ["id"],
                          ondelete="SET NULL")

    # ------------------------------------------------------- the agentic policy
    op.add_column("planner_projects", sa.Column(
        "agentic_mode", sa.String(length=16), nullable=False,
        server_default="STANDARD"))
    op.add_column("planner_projects", sa.Column(
        "agentic_policy", postgresql.JSONB(astext_type=sa.Text()),
        nullable=False, server_default=sa.text("'{}'::jsonb")))

    # ------------------------------------------------- a milestone is a period
    op.add_column("planner_milestones", sa.Column(
        "start_date", sa.Date(), nullable=True))
    op.add_column("planner_milestones", sa.Column(
        "critical_date", sa.Date(), nullable=True))
    op.add_column("planner_milestones", sa.Column(
        "priority", sa.String(length=16), nullable=False,
        server_default="MEDIUM"))
    op.add_column("planner_milestones", sa.Column(
        "percent_complete", sa.Integer(), nullable=False,
        server_default="0"))

    # A task may carry the date after which it can no longer recover, which is
    # not its due date and is what the critical-path warning is really about.
    op.add_column("planner_tasks", sa.Column(
        "critical_date", sa.Date(), nullable=True))

    # ---------------------------------------------------------------- drafts
    op.create_table(
        "planner_drafts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=200), nullable=False, default=""),
        sa.Column("code", sa.String(length=40), nullable=False, default=""),
        # DRAFTING, READY or PUBLISHED. A published draft is kept rather than
        # deleted: it is the record of what was approved, and the project it
        # became is the record of what exists.
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="DRAFTING"),
        # Which part of the flow the person had reached, so returning to a
        # saved draft resumes rather than restarts.
        sa.Column("step", sa.String(length=32), nullable=False,
                  server_default="OVERVIEW"),
        # The plan itself: overview, governance, agentic policy, milestones,
        # tasks and links. One document, because a draft is a document.
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        # The project this draft became, once it was published. Null until
        # then, and the reason a published draft is worth keeping.
        sa.Column("project_id", sa.BigInteger(), nullable=True),
        # Optimistic concurrency, the same mechanism the planner rows use:
        # two people editing one draft from two screens is not hypothetical.
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"],
                                ondelete="SET NULL"),
        # RESTRICT rather than CASCADE: deleting a published project should
        # not silently take the record of what was approved with it.
        sa.ForeignKeyConstraint(["project_id"], ["planner_projects.id"],
                                ondelete="RESTRICT"),
    )
    op.create_index("ix_planner_drafts_created_by", "planner_drafts",
                    ["created_by"])
    op.create_index("ix_planner_drafts_status", "planner_drafts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_planner_drafts_status", table_name="planner_drafts")
    op.drop_index("ix_planner_drafts_created_by", table_name="planner_drafts")
    op.drop_table("planner_drafts")

    op.drop_column("planner_tasks", "critical_date")
    op.drop_column("planner_milestones", "percent_complete")
    op.drop_column("planner_milestones", "priority")
    op.drop_column("planner_milestones", "critical_date")
    op.drop_column("planner_milestones", "start_date")

    op.drop_column("planner_projects", "agentic_policy")
    op.drop_column("planner_projects", "agentic_mode")

    op.drop_constraint("fk_planner_tasks_escalation", "planner_tasks",
                       type_="foreignkey")
    op.drop_column("planner_tasks", "escalation_id")
    op.drop_constraint("fk_planner_milestones_escalation",
                       "planner_milestones", type_="foreignkey")
    op.drop_column("planner_milestones", "escalation_id")
    op.drop_constraint("fk_planner_projects_escalation", "planner_projects",
                       type_="foreignkey")
    op.drop_constraint("fk_planner_projects_owner", "planner_projects",
                       type_="foreignkey")
    op.drop_column("planner_projects", "escalation_id")
    op.drop_column("planner_projects", "owner_id")
