"""Which book a governed dataset describes. B44.

Two portfolios now share one catalogue - the credit book the product has
always carried, and the corporate Borrower 360 universe - and they share
almost all of their vocabulary: both have customers, exposure at default, an
IFRS 9 stage, a covenant. Retrieval ranks datasets by how many of a question's
words they carry, so without a scope the twenty new corporate datasets
outscored the credit book on its own questions and "the ten largest customers
by exposure at default" came back as a clarification.

The default is CREDIT_BOOK, so every dataset that predates the distinction
keeps exactly the behaviour it had.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

COLUMN = "portfolio_scope"
TABLE = "dataset_definitions"
DEFAULT = "CREDIT_BOOK"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.String(length=32), nullable=False,
                  server_default=DEFAULT),
    )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
