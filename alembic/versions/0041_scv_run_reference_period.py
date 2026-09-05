"""A reference period is a period, not a sentence about one.

Revision 0040 wrote `scv_runs.reference_period` from the model registry's
`development_population`, which is prose: "2021-01..2022-12 applications,
matured to a twelve-month outcome." Sixty-five characters into a
VARCHAR(32). The SME champion's happens to be short enough to fit, so the
column looked correct until a Retail Application run was recorded and
PostgreSQL refused the insert.

Two things are wrong there and only one of them is the width. A column named
`reference_period` that holds a paragraph is a column the next reader will put
in a period filter, and widening it to 300 would have preserved the mistake
with more room. So:

  * `development_population` (new, 300) holds the prose — what population the
    model was BUILT on, which is a property of the model and belongs on the
    run because a run has to say what it was validating against.

  * `reference_period` keeps its name and its width and now holds an actual
    period: the benchmark period the stability tests compared to, taken from
    the results themselves rather than from the registry.

Existing rows are migrated rather than dropped: the prose moves across, and
`reference_period` is cleared wherever it holds something that is not a period,
because leaving a sentence in a period column is how the next query returns
nothing and nobody can see why.

Reversible. The downgrade folds the prose back into `reference_period`, which
is lossy for anything longer than 32 characters — stated here rather than
discovered, and the reason to go forward rather than back.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scv_runs",
                  sa.Column("development_population", sa.String(300),
                            nullable=False, server_default=""))
    # Move the prose across, then clear the period column of anything that is
    # not a period. A period is YYYY-MM, optionally a YYYY-MM..YYYY-MM span.
    op.execute("""
        UPDATE scv_runs
           SET development_population = reference_period
         WHERE reference_period <> ''
    """)
    op.execute(r"""
        UPDATE scv_runs
           SET reference_period = ''
         WHERE reference_period !~ '^\d{4}-\d{2}(\.\.\d{4}-\d{2})?$'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE scv_runs
           SET reference_period = LEFT(development_population, 32)
         WHERE reference_period = '' AND development_population <> ''
    """)
    op.drop_column("scv_runs", "development_population")
