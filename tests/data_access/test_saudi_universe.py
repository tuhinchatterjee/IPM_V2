"""
The demonstration universe, and the promises it makes.

These are not tests of the generator's arithmetic. They are tests of the things
the rest of the product relies on being true about the data:

  * it is big enough and long enough to demonstrate a forward risk signal
  * it is LONGITUDINAL — the same facilities across quarters, so a migration is a
    migration rather than two unrelated snapshots
  * the IFRS 9 staging table agrees with the facility book it describes
  * all three early-warning transitions actually occur, in the order a real book
    produces them: more Stage 1 to 2 than anything else, and Stage 1 straight to
    default the rarest
  * deterioration is genuinely predictable from what was observable beforehand,
    which is the claim the Early Warning module rests on
  * every row says it is synthetic

If the universe is regenerated with different parameters, these are the
properties that must survive it.
"""

from __future__ import annotations

import pytest

from backend.data_access.catalog import get_catalog
from backend.data_access.context import AnalysisContext
from backend.data_access.duckdb_source import DuckDBSource

FACILITY = "portfolio_facility"
STAGING = "ifrs9_staging"
RATINGS = "customer_ratings"
MACRO = "macro_saudi"


@pytest.fixture(scope="module")
def source() -> DuckDBSource:
    return DuckDBSource()


def _has(source: DuckDBSource, dataset: str) -> bool:
    return dataset in source.datasets()


def read(source: DuckDBSource, dataset: str, period: str, fields: list[str]):
    """One period of one dataset, with no filters. The context is the Data Access
    Layer's unit of scope, so even an unfiltered read declares one."""
    return source.fetch(
        dataset, context=AnalysisContext(period=period), fields=fields, period=period,
    )


# ------------------------------------------------------------------- scale


def test_the_book_is_long_enough_to_show_a_trend(source):
    periods = source.periods(FACILITY)
    assert len(periods) >= 15, "A forward signal needs history to be fitted on."


def test_every_quarter_is_a_real_portfolio(source):
    for period in source.periods(FACILITY):
        df = read(source, FACILITY, period, ["account_id"])
        assert len(df) >= 15_000, f"{period} has only {len(df):,} facilities."


def test_the_rating_history_covers_eight_cycles(source):
    if not _has(source, RATINGS):
        pytest.skip("customer_ratings is not built")
    periods = source.periods(RATINGS)
    assert len(periods) >= 8
    for period in periods:
        df = read(source, RATINGS, period, ["customer_id"])
        assert df["customer_id"].nunique() >= 1_600


def test_there_is_a_macroeconomic_series_behind_the_book(source):
    if not _has(source, MACRO):
        pytest.skip("macro_saudi is not built")
    assert len(source.periods(MACRO)) >= len(source.periods(FACILITY))


# ------------------------------------------------------------ coherence


def test_the_same_facilities_persist_across_quarters(source):
    """Without this the book is fifteen unrelated snapshots and no migration
    anybody reports is a migration."""
    periods = source.periods(FACILITY)
    first = set(read(source, FACILITY, periods[0], ["account_id"])["account_id"])
    last = set(read(source, FACILITY, periods[-1], ["account_id"])["account_id"])
    overlap = len(first & last) / max(len(first), 1)
    assert overlap > 0.9, f"Only {overlap:.0%} of facilities survive the book."


def test_staging_agrees_with_the_facility_book(source):
    if not _has(source, STAGING):
        pytest.skip("ifrs9_staging is not built")
    period = source.periods(FACILITY)[-1]
    book = read(source, FACILITY, period,
                ["account_id", "ifrs9_stage"]).set_index("account_id")
    staging = read(source, STAGING, period,
                   ["account_id", "ifrs9_stage"]).set_index("account_id")
    assert set(book.index) == set(staging.index)
    joined = book.join(staging, rsuffix="_staging")
    assert (joined["ifrs9_stage"] == joined["ifrs9_stage_staging"]).all()


def test_the_periods_are_in_order(source):
    periods = source.periods(FACILITY)
    assert periods == sorted(periods, key=lambda p: (int(p.split()[1]), int(p[1])))


# ------------------------------------------------------------ migrations


def test_all_three_early_warning_transitions_occur(source):
    """A model cannot be fitted for a transition the data never contains."""
    if not _has(source, STAGING):
        pytest.skip("ifrs9_staging is not built")
    counts = _migration_counts(source)
    assert counts["1->2"] > 0
    assert counts["1->3"] > 0
    assert counts["2->3"] > 0


def test_migrations_occur_in_the_proportions_a_real_book_produces(source):
    """Deterioration goes through Stage 2. A book where facilities routinely
    jumped from performing straight to impaired would teach a model a transition
    that does not happen."""
    if not _has(source, STAGING):
        pytest.skip("ifrs9_staging is not built")
    counts = _migration_counts(source)
    assert counts["1->2"] > counts["1->3"]
    assert counts["1->2"] > counts["2->3"]


def _migration_counts(source: DuckDBSource) -> dict[str, int]:
    out = {"1->2": 0, "1->3": 0, "2->3": 0}
    for period in source.periods(STAGING):
        df = read(source, STAGING, period, ["prior_stage", "ifrs9_stage"])
        for key, (before, after) in {
            "1->2": (1, 2), "1->3": (1, 3), "2->3": (2, 3),
        }.items():
            out[key] += int(
                ((df["prior_stage"] == before) & (df["ifrs9_stage"] == after)).sum()
            )
    return out


def test_deterioration_is_visible_before_it_happens(source):
    """The claim the whole Early Warning module rests on.

    Facilities that migrate out of Stage 1 next quarter should already look
    worse this quarter than the ones that do not. If that is not true in the
    data, no model fitted on it means anything, however good its statistics
    look.
    """
    if not _has(source, STAGING):
        pytest.skip("ifrs9_staging is not built")
    periods = source.periods(FACILITY)
    now, later = periods[-4], periods[-3]

    before = read(
        source, FACILITY, now,
        ["account_id", "ifrs9_stage", "utilisation_pct",
         "covenant_headroom_pct", "pd_12m_pct"],
    ).set_index("account_id")
    after = read(
        source, STAGING, later, ["account_id", "ifrs9_stage"],
    ).set_index("account_id")

    stage_one = before[before["ifrs9_stage"] == 1].join(after, rsuffix="_next")
    migrating = stage_one[stage_one["ifrs9_stage_next"] > 1]
    staying = stage_one[stage_one["ifrs9_stage_next"] == 1]

    assert len(migrating) >= 30, "Too few migrations to say anything."
    assert migrating["pd_12m_pct"].mean() > staying["pd_12m_pct"].mean()
    assert migrating["utilisation_pct"].mean() > staying["utilisation_pct"].mean()
    assert (
        migrating["covenant_headroom_pct"].mean()
        < staying["covenant_headroom_pct"].mean()
    )


# ---------------------------------------------------------- provenance


def test_every_generated_dataset_declares_itself_synthetic():
    catalog = get_catalog()
    for name in (FACILITY, STAGING, RATINGS, MACRO):
        if name not in catalog.names():
            continue
        dataset = catalog.dataset(name)
        assert dataset.is_synthetic is True
        assert dataset.origin == "demo"


def test_the_generated_rows_carry_their_own_provenance(source):
    """Not only the catalogue. A row that leaves the catalogue behind — exported,
    pasted into a deck — should still say what it is."""
    if not _has(source, STAGING):
        pytest.skip("ifrs9_staging is not built")
    period = source.periods(STAGING)[-1]
    df = read(source, STAGING, period, ["data_origin"])
    assert df["data_origin"].str.contains("SYNTHETIC").all()
