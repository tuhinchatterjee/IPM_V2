"""A project's investigation may be published to the global list, deliberately.

§4 of the collaboration brief states the rule the product had been enforcing
only by accident of a WHERE clause:

    A Project-only Investigation must not appear in the global Investigation
    list unless the user explicitly chooses PUBLISH TO GLOBAL INVESTIGATIONS.

The first half already held — Work → Investigations selects `project_id IS
NULL`, which is what stops a project being a tag rather than a container. The
second half had no way to happen at all. The only route from a project thread
to the global list was to move it OUT of the project, which is not publishing:
it removes the project's record of what was explored.

So a thread now carries whether it has been published. Default false, because
work done inside a project is the project's until somebody says otherwise, and
a migration that opted every existing project thread into the global list would
be exactly the pile §4 is written to prevent.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("published_globally", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        "investigations",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column("published_by", sa.BigInteger(),
                  sa.ForeignKey("users.id"), nullable=True),
    )
    # The global listing filters on it, so it is indexed with the sort key the
    # listing uses rather than on its own.
    op.create_index(
        "ix_investigations_published",
        "investigations",
        ["published_globally", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_investigations_published", table_name="investigations")
    op.drop_column("investigations", "published_by")
    op.drop_column("investigations", "published_at")
    op.drop_column("investigations", "published_globally")
