"""A task can say which milestone it is under.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-06

The plan a person builds in the Copilot hangs tasks off milestones — the codes
say so (`M01-T01`), the panel groups by it, and the escalation ladder walks
task → milestone → project looking for somebody to tell. None of that survived
publication, because there was nowhere to put it: `planner_tasks` had a
workstream and a parent task and no milestone.

Nullable, and it stays nullable. A workstream is a slice of the org chart and
a milestone is a date, and plenty of real projects have tasks that belong to
one and not the other. Deleting a milestone leaves its tasks alone rather than
taking them with it — the work did not stop existing because the date did.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("planner_tasks", sa.Column(
        "milestone_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_planner_tasks_milestone", "planner_tasks",
                          "planner_milestones", ["milestone_id"], ["id"],
                          ondelete="SET NULL")
    # Read on every sweep — "what is under M02, and is any of it late?" — so
    # it is worth an index even on a table this size.
    op.create_index("ix_planner_tasks_milestone", "planner_tasks",
                    ["milestone_id"])


def downgrade() -> None:
    op.drop_index("ix_planner_tasks_milestone", table_name="planner_tasks")
    op.drop_constraint("fk_planner_tasks_milestone", "planner_tasks",
                       type_="foreignkey")
    op.drop_column("planner_tasks", "milestone_id")
