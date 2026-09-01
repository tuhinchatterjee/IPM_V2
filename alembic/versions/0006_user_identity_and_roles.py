"""Give a user a name, an email and a team; widen the role column.

Revision ID: 0006
Revises: 0005

The Cockpit greets people by their first name, and the product has four roles
rather than the two the Dash-era column was sized for. Both need columns that do
not exist yet.

Nothing is destroyed. Existing rows keep their username and password, get empty
names, and have their lower-case "admin"/"analyst" role normalised to the
upper-case vocabulary the API uses — with anything unrecognised becoming VIEWER,
because the safe reading of an unknown role is the least powerful one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Server defaults so the ALTER succeeds on a table with rows, then dropped
    # so the application's own defaults are the only ones from here on.
    for column in ("first_name", "last_name"):
        op.add_column(
            "users",
            sa.Column(column, sa.String(length=80), nullable=False,
                      server_default=""),
        )
        op.alter_column("users", column, server_default=None)

    op.add_column(
        "users",
        sa.Column("email", sa.String(length=200), nullable=False, server_default=""),
    )
    op.alter_column("users", "email", server_default=None)

    op.add_column(
        "users",
        sa.Column("team", sa.String(length=120), nullable=False, server_default=""),
    )
    op.alter_column("users", "team", server_default=None)

    # "DATA_STEWARD" is 13 characters; the column was 16, which happens to fit,
    # but 24 leaves room for a role name somebody adds later without another
    # migration to widen it.
    op.alter_column(
        "users", "role",
        existing_type=sa.String(length=16),
        type_=sa.String(length=24),
        existing_nullable=False,
    )

    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE users
           SET role = CASE upper(trim(role))
                        WHEN 'ADMIN'        THEN 'ADMIN'
                        WHEN 'DATA_STEWARD' THEN 'DATA_STEWARD'
                        WHEN 'ANALYST'      THEN 'ANALYST'
                        WHEN 'VIEWER'       THEN 'VIEWER'
                        ELSE 'VIEWER'
                      END
    """))

    # A username is often already a name. Using it as the first name beats
    # greeting somebody as an empty string, and an administrator can correct it.
    conn.execute(sa.text("""
        UPDATE users
           SET first_name = initcap(split_part(username, '.', 1))
         WHERE first_name = '' AND username <> ''
    """))


def downgrade() -> None:
    op.alter_column(
        "users", "role",
        existing_type=sa.String(length=24),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    for column in ("team", "email", "last_name", "first_name"):
        op.drop_column("users", column)
