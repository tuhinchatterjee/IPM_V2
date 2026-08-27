"""Send an object to several people, for a named action, with a message thread.

What was there
--------------
One reviewer, one object, six states, and no way to say anything except a
transition comment. That is enough for "certify this analysis" and nothing else.
§43 asks for the loop credit risk actually runs: send a Project, an
Investigation or an Analysis to a person, several people or a team, for one of
seven named actions, with a message, a priority and a due date, and hold the
conversation about it against the object rather than in email.

What is added
-------------
**Recipients.** A join table rather than a second nullable column, because
"three people and a team" is a set and modelling a set as columns is how you
end up with `assigned_to_2`. Each row records when that recipient opened the
item, which is what makes the OPENED status in §44 an observation rather than a
guess.

**A message thread.** §45: replies, @mentions, attachments and resolution,
attached to the workflow item. Deliberately internal — the brief says "Do not
build external email", and the product owes a user only that work addressed to
them is visible the moment they open CreditProbe.

**The fields §44 names.** action requested, message, priority, and the version
of the object as it was when it was sent — so a decision recorded against
version 3 does not silently become a decision about version 7.

The state vocabulary
--------------------
Three states are added — `opened`, `commented`, `completed` — which with the
six that exist give exactly the nine §44 lists. Two of the existing ids are
spelled differently from the brief (`submitted` for SENT, `withdrawn` for
CANCELLED) and are NOT renamed: they are the state machine that projects,
tests and stored history all depend on, and a rename would rewrite decisions
that are meant to be immutable. The labels people read are §44's words.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_items",
                  sa.Column("action", sa.String(length=24), nullable=False,
                            server_default="review"))
    op.add_column("workflow_items",
                  sa.Column("message", sa.Text(), nullable=False,
                            server_default=""))
    op.add_column("workflow_items",
                  sa.Column("priority", sa.String(length=12), nullable=False,
                            server_default="normal"))
    op.add_column("workflow_items",
                  sa.Column("object_version", sa.String(length=64),
                            nullable=True))

    op.create_table(
        "workflow_recipients",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("workflow_item_id", sa.BigInteger(),
                  sa.ForeignKey("workflow_items.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("team_id", sa.BigInteger(), sa.ForeignKey("teams.id"),
                  nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_item_id", "user_id", "team_id",
                            name="uq_workflow_recipient"),
    )
    op.create_index("ix_workflow_recipients_user", "workflow_recipients",
                    ["user_id"])

    op.create_table(
        "workflow_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("workflow_item_id", sa.BigInteger(),
                  sa.ForeignKey("workflow_items.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("parent_id", sa.BigInteger(),
                  sa.ForeignKey("workflow_messages.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        # Who was named, and what was attached. Documents rather than columns:
        # both are written and read whole and never queried across threads.
        sa.Column("mentions", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("attachments", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_messages_item", "workflow_messages",
                    ["workflow_item_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_workflow_messages_item", table_name="workflow_messages")
    op.drop_table("workflow_messages")
    op.drop_index("ix_workflow_recipients_user", table_name="workflow_recipients")
    op.drop_table("workflow_recipients")
    op.drop_column("workflow_items", "object_version")
    op.drop_column("workflow_items", "priority")
    op.drop_column("workflow_items", "message")
    op.drop_column("workflow_items", "action")
