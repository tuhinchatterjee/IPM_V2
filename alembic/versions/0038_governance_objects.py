"""Findings, decisions and actions as governed objects. Gates 6 and 7.

What was missing
----------------
Gate 1 gave these three tables the shape of governance objects. Running them
as governance objects needs four more things on each:

* **an audit trail** — `history`, append-only, with the human actor, the
  timestamp, the previous state, the new state and the reason. §26 asks that
  no LLM be able to fake this; an append-only column written only by a service
  that refuses an unnamed actor is how that is enforced rather than hoped;
* **who finished it** — a finding records who ANSWERED it and, separately, who
  ACCEPTED or CLOSED it, because drafting an answer and standing behind it are
  different acts and Claude may do only the first. An action records who
  completed it;
* **the delta and the version** a finding was raised against, so "previous
  5.86%, current 6.47%, +0.61pp" survives beside the finding rather than being
  recomputed from data that has since moved;
* **the planner seam** — an action carries an external status and when it was
  last synced, so a future Project Planner can own execution and report back
  without anything here depending on it existing.

Additive. Nothing existing is altered or dropped.

Revision ID: 0038
Revises: 0037
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- findings ---------------------------------------------------------
    op.add_column("playbook_findings",
                  sa.Column("version_id", sa.BigInteger, nullable=True))
    op.add_column("playbook_findings",
                  sa.Column("delta", sa.String(64), nullable=False,
                            server_default=""))
    op.add_column("playbook_findings",
                  sa.Column("resolved_by", sa.String(160), nullable=False,
                            server_default=""))
    op.add_column("playbook_findings",
                  sa.Column("resolved_at", sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column("playbook_findings",
                  sa.Column("history", JSONB, nullable=False,
                            server_default="[]"))

    # --- decisions --------------------------------------------------------
    op.add_column("playbook_decisions",
                  sa.Column("reporting_period", sa.String(48), nullable=False,
                            server_default=""))
    op.add_column("playbook_decisions",
                  sa.Column("related_finding_ids", JSONB, nullable=False,
                            server_default="[]"))
    op.add_column("playbook_decisions",
                  sa.Column("history", JSONB, nullable=False,
                            server_default="[]"))

    # --- actions ----------------------------------------------------------
    op.add_column("playbook_actions",
                  sa.Column("description", sa.Text, nullable=False,
                            server_default=""))
    op.add_column("playbook_actions",
                  sa.Column("completed_by", sa.String(160), nullable=False,
                            server_default=""))
    op.add_column("playbook_actions",
                  sa.Column("completed_at", sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column("playbook_actions",
                  sa.Column("notes", JSONB, nullable=False,
                            server_default="[]"))
    op.add_column("playbook_actions",
                  sa.Column("external_status", sa.String(48), nullable=False,
                            server_default=""))
    op.add_column("playbook_actions",
                  sa.Column("external_synced_at", sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column("playbook_actions",
                  sa.Column("history", JSONB, nullable=False,
                            server_default="[]"))


def downgrade() -> None:
    for column in ("history", "resolved_at", "resolved_by", "delta",
                   "version_id"):
        op.drop_column("playbook_findings", column)
    for column in ("history", "related_finding_ids", "reporting_period"):
        op.drop_column("playbook_decisions", column)
    for column in ("history", "external_synced_at", "external_status",
                   "notes", "completed_at", "completed_by", "description"):
        op.drop_column("playbook_actions", column)
