"""A change made through conversation is its own source.

`AI` already existed and means "an agent did this". A person saying "update
T-104 to 70%, waiting on Finance" and the agent applying it is a different
governance fact: there is a named human whose instruction it was, and who can
be asked about it. Recording both as `AI` would lose exactly the distinction a
reviewer is looking for.

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_OLD = "source IN ('UI','API','AI','EXCEL_IMPORT','SYSTEM')"
_NEW = "source IN ('UI','API','AI','AI_CHAT','EXCEL_IMPORT','SYSTEM')"


def upgrade() -> None:
    op.drop_constraint("ck_planner_update_source", "planner_updates",
                       type_="check")
    op.create_check_constraint("ck_planner_update_source", "planner_updates",
                               _NEW)


def downgrade() -> None:
    # Rows written through conversation would violate the narrower rule, so
    # they are relabelled rather than left to fail the constraint. `AI` is the
    # value they would have carried before this revision existed.
    op.execute("UPDATE planner_updates SET source = 'AI' "
               "WHERE source = 'AI_CHAT'")
    op.drop_constraint("ck_planner_update_source", "planner_updates",
                       type_="check")
    op.create_check_constraint("ck_planner_update_source", "planner_updates",
                               _OLD)
