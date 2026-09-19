"""One live generation per workspace, enforced by the database.

What was wrong
--------------
Pressing Send during a running generation started a SECOND generation against
the same workspace. Both called the provider, both were charged, and only the
newer one was visible: `service.running_job` returns the newest unfinished job,
so the first kept running and billing with no way to see or stop it.

This was observed, not theorised. A real run shows four identical
"Draft the report from the attached sources." messages in one thread — a user
pressing Send again because nothing appeared to be happening — and each one
was accepted as new work.

Three things had to be true at once for that:

* the composer never learned a generation was running, so Send stayed live;
* the client's idempotency key is positional (`ws7:turn12`), so the same
  sentence sent again gets a DIFFERENT key and cannot be recognised;
* the server's only dedupe was that key. `0040` made it unique per workspace,
  which stops a refresh or a double-click from starting a second job — but
  nothing at all stopped a genuinely new key from starting one alongside a
  live job.

The first two are fixed in the interface and can be got round. This is the
guarantee underneath them: `playbook_jobs` may hold at most one row per
workspace with `finished_at IS NULL`. A check-then-insert would still race two
concurrent requests; a partial unique index cannot be raced, which is why
`agentic/queue.py` has used exactly this shape since it was written.

`heartbeat_at`
--------------
A constraint with no way out is a workspace that can be bricked. If the process
running a generation dies — a restart, a crash, a killed container — its row
keeps `finished_at IS NULL` for ever and every later send is refused.

So the worker stamps `heartbeat_at` as it writes each event, and a job that has
not been heard from is treated as dead and finished with an honest error rather
than blocking the conversation. Backfilled from `created_at` so existing rows
have an age and are recoverable.

Existing data
-------------
The index cannot be created while a workspace already holds two unfinished
jobs, and at least one deployment does. Those are historical rows for
generations that are certainly not still running, so the upgrade finishes all
but the newest per workspace first, recording why.

Revision ID: 0041
Revises: 0040
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

INDEX = "uq_playbook_job_one_live_per_workspace"

#: Said on the row itself, so a user who reopens an old thread reads why the
#: answer never came instead of seeing a generation apparently still running.
CLOSED = (
    "This generation was recorded as still running when one-live-job-per-"
    "workspace was introduced. It was not running; it is closed here."
)


def upgrade() -> None:
    op.add_column(
        "playbook_jobs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    # An age for every existing row, so none of them looks eternally fresh.
    op.execute("UPDATE playbook_jobs SET heartbeat_at = created_at "
               "WHERE heartbeat_at IS NULL")

    # Keep the newest unfinished job per workspace; close the rest. `ctid` is
    # not used — `id` is monotonic here and says which one the client would
    # have been watching.
    op.execute(
        sa.text(
            """
            UPDATE playbook_jobs AS j
               SET finished_at = COALESCE(j.finished_at, now()),
                   state       = CASE WHEN j.state IN ('ready', 'failed',
                                                       'cancelled')
                                      THEN j.state ELSE 'failed' END,
                   error       = CASE WHEN j.error = '' THEN :closed
                                      ELSE j.error END
             WHERE j.finished_at IS NULL
               AND j.id < (SELECT MAX(n.id) FROM playbook_jobs AS n
                            WHERE n.workspace_id = j.workspace_id
                              AND n.finished_at IS NULL)
            """
        ).bindparams(closed=CLOSED)
    )

    op.create_index(
        INDEX, "playbook_jobs", ["workspace_id"], unique=True,
        postgresql_where=sa.text("finished_at IS NULL"),
    )


def downgrade() -> None:
    # Both directions are safe. Dropping a constraint never fails on data, and
    # the rows closed above stay closed: reopening them would resurrect
    # generations that are not running.
    op.drop_index(INDEX, table_name="playbook_jobs")
    op.drop_column("playbook_jobs", "heartbeat_at")
