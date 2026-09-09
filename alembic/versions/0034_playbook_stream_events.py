"""The durable stream: one row per event a generation emitted. Playbook §7, §16.

Why the stream is persisted rather than only pushed
---------------------------------------------------
A conversation that streams is easy. A conversation that streams and survives a
refresh is not, and this table is the difference.

The generation runs in a background worker, not inside the request that started
it, so a browser that reloads mid-generation does not kill the work and does not
start a second one. Every event the worker produces — the states it moves
through, the text as it arrives, the artifact it finally wrote — is appended
here with a monotonic `seq`. A client that reconnects replays from the last
`seq` it saw and then tails, which is why a refresh at any moment shows the
answer so far rather than a blank thread or a duplicate run.

Two things this table deliberately does NOT hold:

* **Anything hidden.** Only user-visible answer text and real job states are
  written. Reasoning blocks, tool inputs, internal prompts and credentials never
  reach it, because the writer forwards `text_delta` alone.
* **The answer itself.** A partial stream lives only here. The assistant's
  message and the artifact version are written to `playbook_messages` and
  `playbook_artifact_versions` when the run COMPLETES, so an interrupted
  generation can never be read back as a finished analysis or exported as one.

Additive only. Nothing existing is altered or dropped.

Revision ID: 0034
Revises: 0033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playbook_job_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        # Monotonic per job, assigned by the writer. The client's cursor, and
        # the SSE `id:` field, so a reconnect resumes exactly where it stopped.
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["playbook_jobs.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "seq", name="uq_playbook_job_event_seq"),
    )
    op.create_index("ix_playbook_job_events_job", "playbook_job_events",
                    ["job_id", "seq"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_playbook_job_events_job", table_name="playbook_job_events")
    op.drop_table("playbook_job_events")
