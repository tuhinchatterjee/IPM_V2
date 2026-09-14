"""An idempotency key belongs to a conversation, not to the deployment.

What was wrong
--------------
`0033` made `playbook_jobs.idempotency_key` globally unique, and
`jobs_by_key` looked it up globally. The browser happens to namespace its own
keys by workspace (`ws7:turn3`), so the defect never showed in the UI — but
the guarantee rested on client discipline rather than on anything the server
enforced.

Any other caller — a script, a soak harness, a future surface — that minted
the same key in two workspaces got a silent and bad failure: the second send
was reported as a DUPLICATE of the first workspace's job, no question was
written to the second thread, and the client was handed a job id belonging to
a conversation it was not looking at.

The fix is to say what the key actually means. An idempotency key identifies
one send within one conversation, so it is unique per workspace and is looked
up per workspace. The guarantee §20 asks for — a refresh or a double-click
never starts a second billable generation — is unchanged and is now enforced
by the database rather than by a naming convention in a React component.

Safe to apply in either direction. Narrowing a unique constraint can never
fail on existing rows: every set of rows unique on `(idempotency_key)` is
also unique on `(workspace_id, idempotency_key)`. The downgrade widens it
again and therefore CAN fail, so it checks first and says what it found.

Revision ID: 0040
Revises: 0039
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

NAME = "uq_playbook_job_idempotency"


def upgrade() -> None:
    op.drop_constraint(NAME, "playbook_jobs", type_="unique")
    op.create_unique_constraint(NAME, "playbook_jobs",
                                ["workspace_id", "idempotency_key"])


def downgrade() -> None:
    clashes = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM (SELECT idempotency_key FROM playbook_jobs "
        "GROUP BY idempotency_key HAVING count(*) > 1) AS d"
    )).scalar_one()
    if clashes:
        raise RuntimeError(
            f"{clashes} idempotency key(s) are used in more than one "
            "workspace, so a global unique constraint cannot be restored. "
            "Those jobs would have to be removed or re-keyed first.")
    op.drop_constraint(NAME, "playbook_jobs", type_="unique")
    op.create_unique_constraint(NAME, "playbook_jobs", ["idempotency_key"])
