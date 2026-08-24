"""An analysis run belongs to an investigation, not a chat.

The bug this fixes
------------------
`analysis_runs.chat_id` pointed at the old `chats` table. Conversations moved to
`investigations` when the product hierarchy was built, but this foreign key did
not move with them — so every answer produced inside a conversation failed its
foreign-key check on the way to being stored.

The failure was swallowed (persistence is best-effort, so a database problem
cannot lose an answer somebody is already reading), which meant the symptom was
not an error but a missing id: every threaded answer came back with
`analysis_run_id` null, and the Trace button on every answer in the product was
dead. A governance product whose central promise is "every figure can be
followed back to the rows behind it" was quietly not keeping it.

Renamed as well as repointed. A column called `chat_id` holding an
investigation id is how this happens again.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("analysis_runs_chat_id_fkey", "analysis_runs", type_="foreignkey")
    op.alter_column("analysis_runs", "chat_id", new_column_name="investigation_id")

    # Any id already stored referred to a `chats` row, which is a different
    # table with its own numbering — carrying it across would attach runs to
    # unrelated investigations. There are none in practice, because the insert
    # was failing; clearing is the correct handling of any that exist.
    op.execute("UPDATE analysis_runs SET investigation_id = NULL")

    op.create_foreign_key(
        "analysis_runs_investigation_id_fkey", "analysis_runs", "investigations",
        ["investigation_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_analysis_runs_investigation", "analysis_runs",
                    ["investigation_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_investigation", table_name="analysis_runs")
    op.drop_constraint("analysis_runs_investigation_id_fkey", "analysis_runs",
                       type_="foreignkey")
    op.execute("UPDATE analysis_runs SET investigation_id = NULL")
    op.alter_column("analysis_runs", "investigation_id", new_column_name="chat_id")
    op.create_foreign_key(
        "analysis_runs_chat_id_fkey", "analysis_runs", "chats",
        ["chat_id"], ["id"], ondelete="SET NULL",
    )


# Imported for its side effect on the metadata comparison in tests.
_ = sa
