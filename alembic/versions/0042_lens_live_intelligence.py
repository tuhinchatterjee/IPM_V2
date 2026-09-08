"""A Lens remembers what it said, and a metric remembers what was approved.

Two things arrive together because they are one feature: a Lens whose numbers
are produced by code somebody approved, and which can say what changed since
the last time it ran.

WHY ONE MIGRATION AND NOT TWO
------------------------------
§49 asks for one where it is feasible, and it is: the two halves are written
in one release, deployed together, and neither is useful without the other —
a refresh history over metrics nobody approved is a log, and an approved
metric that never records what it produced cannot be compared with itself.

WHAT IS ADDED TO `user_metrics`, AND WHY NOT FIFTEEN COLUMNS
-------------------------------------------------------------
§13 lists fifteen things to persist when a metric is locked: the name, the
user's original formula, the interpreted formula, the generated code, the
validated code, the explanation, the domains, the datasets, the grain, the
fields, the filters, the period behaviour, the lineage, the owner and the
version. Five of those already have columns. The rest are ONE artefact — it
is written whole at the moment of locking, read whole whenever the metric is
explained, and shown whole on the definition card — so it is one JSONB column
rather than ten that must be kept consistent with each other.

`user_formula` is pulled out beside it because it is the one part that gets
QUERIED: "which metrics did somebody write by hand, and what did they type?"
is a question governance asks, and it should be a WHERE clause rather than a
scan of every JSON document in the table.

`code` also carries a metric's COMPOSITE, where it has one. A
quarter-on-quarter change reads two periods and a cross-domain ratio reads two
datasets, and neither is expressible as the term tree in `definition` — so for
those metrics `definition` is an empty formula and the composite is what runs.

WHAT THE TWO NEW TABLES ARE FOR
--------------------------------
`lens_refreshes` is one execution of a Lens. Its two timestamps are the point:
`refreshed_at` is when it was CALCULATED and `reporting_period` is which
BUSINESS PERIOD it describes. §18 requires them to be distinguishable and §22
requires two separate histories over them, and a schema with one timestamp
would make "the book moved" and "somebody opened the page twice" the same
event.

`lens_metric_snapshots` is what each tile was worth at that execution,
including the tiles that produced nothing — a metric that was available last
refresh and is not now is a change worth reporting, and a table of successes
could not report it.

THE INDEXES, AND THE QUERIES THEY ARE FOR
------------------------------------------
`ix_lens_refreshes_comparable` covers §24's actual question, which is not "the
previous row" but "the most recent refresh of this Lens under the same filter
context and the same reporting-period semantics". Without a filter_hash in the
index that lookup is a scan of every refresh the Lens has ever had, on every
page load.

REVERSIBLE
----------
The downgrade drops both tables and both columns. It loses refresh history and
the approved-code record for every user metric, which is stated here rather
than discovered: going back means those metrics can still be CALCULATED — the
formula and the composite would go with `code`, so composites specifically
would stop working and would need rebuilding. A deployment that has locked a
composite metric should go forward.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- the approved code record, on the metric it belongs to ------------
    op.add_column(
        "user_metrics",
        sa.Column("code", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column(
        "user_metrics",
        sa.Column("user_formula", sa.Text(), nullable=False,
                  server_default=""))

    # ---- one execution of a Lens -----------------------------------------
    op.create_table(
        "lens_refreshes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("lens_id", sa.Integer(), nullable=False),
        # §18A: when it was calculated.
        sa.Column("refreshed_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        # §18B: which business period it describes. Never the same column.
        sa.Column("reporting_period", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("filter_hash", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("lens_definition_version", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("data_versions", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("trigger", sa.String(24), nullable=False,
                  server_default="lens_opened"),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="succeeded"),
        sa.Column("classification", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("compared_with_id", sa.BigInteger(), nullable=True),
        sa.Column("interpretation", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("duration_ms", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("budget", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("triggered_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lens_id"], ["lenses.id"],
                                ondelete="CASCADE"),
        # Self-referential: the refresh this one was compared with. SET NULL
        # rather than CASCADE — losing an old refresh must not delete the
        # newer one that referred to it.
        sa.ForeignKeyConstraint(["compared_with_id"], ["lens_refreshes.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lens_refreshes_lens", "lens_refreshes",
                    ["lens_id", "refreshed_at"])
    # §24's lookup, covered: the most recent COMPARABLE refresh, which is
    # scoped by filter context and reporting period before it is ordered by
    # time. Without the middle two columns this is a scan per page load.
    op.create_index("ix_lens_refreshes_comparable", "lens_refreshes",
                    ["lens_id", "filter_hash", "reporting_period",
                     "refreshed_at"])

    # ---- what each tile was worth at that execution ----------------------
    op.create_table(
        "lens_metric_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("refresh_id", sa.BigInteger(), nullable=False),
        sa.Column("panel_key", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("metric_id", sa.String(160), nullable=False,
                  server_default=""),
        sa.Column("kind", sa.String(24), nullable=False,
                  server_default="metric"),
        sa.Column("title", sa.String(240), nullable=False, server_default=""),
        sa.Column("metric_definition_version", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("definition_hash", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("comparison_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(24), nullable=False,
                  server_default="number"),
        sa.Column("decimals", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("grain", sa.String(240), nullable=False, server_default=""),
        sa.Column("coverage", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reporting_period", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("domains", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("series", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("query_version", sa.String(32), nullable=False,
                  server_default=""),
        sa.Column("data_version", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="succeeded"),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["refresh_id"], ["lens_refreshes.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # One row per tile per refresh. The constraint is what stops a retried
        # refresh from writing a second set of figures and doubling every
        # history series on the screen.
        sa.UniqueConstraint("refresh_id", "panel_key",
                            name="uq_lens_snapshot_panel"),
    )
    op.create_index("ix_lens_snapshots_metric", "lens_metric_snapshots",
                    ["metric_id", "refresh_id"])


def downgrade() -> None:
    op.drop_index("ix_lens_snapshots_metric",
                  table_name="lens_metric_snapshots")
    op.drop_table("lens_metric_snapshots")
    op.drop_index("ix_lens_refreshes_comparable", table_name="lens_refreshes")
    op.drop_index("ix_lens_refreshes_lens", table_name="lens_refreshes")
    op.drop_table("lens_refreshes")
    op.drop_column("user_metrics", "user_formula")
    op.drop_column("user_metrics", "code")
