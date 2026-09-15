"""A Risk Case says what KIND of finding it is.

`Draft.about` has always existed: the review rules set it, and `dedupe_key`
hashes it so that a replay of the same rule over the same product and period
updates the case rather than opening a second one. But it was never written to
a column, and a hash is not readable — so once a case was stored, nothing could
ask what rule had raised it except by matching on its title.

That mattered the moment a second thing started reading cases. An investigation
opened from a case has to know which kind of finding it is continuing: a
question like "what should we do about it?" is answered from the card book
inside a card investigation and must not be answered that way anywhere else,
and the only honest way to tell them apart is for the case to say what it is.
Inferring it from the title would make a route depend on wording, which is the
kind of coupling that breaks silently when somebody improves a sentence.

So `about` becomes a column. Existing rows get an empty string, which is what
they have always effectively had: no rule recorded, and no route may assume one.

Revision ID: 0042
Revises: 0041
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "risk_cases",
        sa.Column("about", sa.String(length=64), nullable=False,
                  server_default=""))


def downgrade() -> None:
    op.drop_column("risk_cases", "about")
