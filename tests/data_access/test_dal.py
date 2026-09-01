"""
Data Access Layer tests.

The DAL is the boundary that makes physical storage swappable, so these tests
are about the *contract*, not about DuckDB specifically: governed names resolve,
filters narrow, unknown names fail loudly with a useful message, and periods come
back in chronological order.

The suite skips itself when the analytical lake has not been built, so a clean
checkout without `python scripts/build_data_lake.py` does not report false
failures.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.data_access import get_catalog, get_data_source
from backend.data_access.context import AnalysisContext
from backend.data_access.protocol import (
    DataAccessError,
    DataSource,
    UnknownDatasetError,
    UnknownFieldError,
)

DATASET = "portfolio_facility"


@pytest.fixture(scope="module")
def source():
    src = get_data_source()
    if DATASET not in src.datasets():
        pytest.skip("Analytical lake not built — run `python scripts/build_data_lake.py`")
    return src


@pytest.fixture(scope="module")
def latest_period(source):
    return source.periods(DATASET)[-1]


@pytest.fixture()
def ctx(latest_period):
    return AnalysisContext(period=latest_period)


# ------------------------------------------------------------------ contract


def test_source_satisfies_the_protocol(source):
    """Structural check: whatever backend is configured must present the same
    interface, so the engine can be written against the protocol alone."""
    assert isinstance(source, DataSource)


def test_every_catalogued_dataset_has_data_on_disk(source):
    """The invariant that matters to the engine: anything the catalogue offers must
    actually be readable.

    The reverse is deliberately not asserted. Files can be left on disk by a
    dataset that was later unpublished or by a test run, and an orphaned
    directory is untidy rather than dangerous — the catalogue is the gate, so an
    uncatalogued directory is already invisible to every analysis.
    """
    on_disk = set(source.datasets())
    for dataset in get_catalog().all():
        assert dataset.name in on_disk, f"{dataset.name} is catalogued but has no data on disk"


def test_every_catalogue_field_has_a_definition_and_type():
    """The catalogue is the Data Dictionary. A field without a definition is a
    governance gap, not a cosmetic one."""
    for dataset in get_catalog().all():
        for field in dataset.fields.values():
            assert field.definition.strip(), f"{dataset.name}.{field.name} has no definition"
            assert field.data_type in {"string", "number", "integer", "boolean", "date"}
            assert field.source_column, f"{dataset.name}.{field.name} has no source column"


# -------------------------------------------------------------------- reads


def test_periods_are_chronological_not_alphabetical(source):
    """'Q1 2024' sorts before 'Q4 2023' alphabetically. If that ordering ever
    leaks through, every trend chart in the product silently reverses."""
    periods = source.periods(DATASET)
    assert periods == sorted(periods, key=lambda p: (int(p.split()[1]), int(p[1])))
    # The hazard is real only when the two orderings actually differ, which they
    # do whenever the book starts on a Q4: "Q1 2023" sorts before "Q4 2022"
    # alphabetically and would silently reverse every trend chart.
    assert periods != sorted(periods)


def test_fetch_returns_only_requested_fields(source, ctx):
    df = source.fetch(DATASET, context=ctx, fields=["account_id", "ead", "sector"])
    assert list(df.columns) == ["account_id", "ead", "sector"]
    assert len(df) > 0


def test_fetch_is_scoped_to_one_period(source, ctx):
    df = source.fetch(DATASET, context=ctx, fields=["period"])
    assert set(df["period"].unique()) == {ctx.period}


def test_period_argument_overrides_the_context(source, ctx):
    """Comparison analyses read the prior period without leaving their context."""
    prior = source.periods(DATASET)[-2]
    df = source.fetch(DATASET, context=ctx, fields=["period"], period=prior)
    assert set(df["period"].unique()) == {prior}


# ---------------------------------------------------------------- aggregation


def test_aggregate_groups_and_sums(source, ctx):
    agg = source.aggregate(DATASET, context=ctx, group_by=["ifrs9_stage"], measures={"ead": "sum"})
    assert set(agg.columns) == {"ifrs9_stage", "ead"}
    assert len(agg) >= 3  # IFRS 9 has three stages


def test_aggregate_matches_a_row_level_sum(source, ctx):
    """The whole point of pushdown is that it returns the same answer as doing the
    arithmetic in Python — just without moving the rows."""
    agg = source.aggregate(DATASET, context=ctx, group_by=["ifrs9_stage"], measures={"ead": "sum"})
    rows = source.fetch(DATASET, context=ctx, fields=["ifrs9_stage", "ead"])
    expected = rows.groupby("ifrs9_stage")["ead"].sum().sort_index()
    actual = agg.set_index("ifrs9_stage")["ead"].sort_index()
    pd.testing.assert_series_equal(actual, expected, check_names=False, rtol=1e-12)


def test_aggregate_with_no_group_by_returns_a_single_total(source, ctx):
    agg = source.aggregate(DATASET, context=ctx, group_by=[], measures={"ead": "sum"})
    assert len(agg) == 1


def test_nunique_counts_distinct_values(source, ctx):
    agg = source.aggregate(DATASET, context=ctx, group_by=[], measures={"customer_id": "nunique"})
    rows = source.fetch(DATASET, context=ctx, fields=["customer_id"])
    assert int(agg["customer_id"].iloc[0]) == rows["customer_id"].nunique()


# ------------------------------------------------------------------- filters


def test_filters_narrow_the_result(source, ctx):
    total = source.aggregate(DATASET, context=ctx, group_by=[], measures={"ead": "sum"})["ead"].iloc[0]
    filtered = source.aggregate(
        DATASET, context=ctx.with_filters(sector="Real Estate"), group_by=[], measures={"ead": "sum"}
    )["ead"].iloc[0]
    assert 0 < filtered < total


def test_list_filter_behaves_as_an_or(source, ctx):
    one = source.aggregate(
        DATASET, context=ctx.with_filters(sector="Real Estate"), group_by=[], measures={"ead": "sum"}
    )["ead"].iloc[0]
    two = source.aggregate(
        DATASET, context=ctx.with_filters(sector=["Real Estate", "Contracting"]), group_by=[],
        measures={"ead": "sum"},
    )["ead"].iloc[0]
    assert two > one


def test_all_is_not_treated_as_a_filter_value(source, ctx):
    """The UI sends "All" for an unset dropdown. Treating that as a literal value
    would return nothing and produce a misleading Trace node."""
    unfiltered = source.aggregate(DATASET, context=ctx, group_by=[], measures={"ead": "sum"})["ead"].iloc[0]
    with_all = source.aggregate(
        DATASET, context=ctx.with_filters(sector="All"), group_by=[], measures={"ead": "sum"}
    )["ead"].iloc[0]
    assert with_all == unfiltered


def test_filter_values_are_bound_not_interpolated(source, ctx):
    """Filter values can originate from a user or from an LLM-produced plan, so
    they are always bound parameters. A SQL fragment must come back as no rows,
    never as an executed statement."""
    hostile = "Real Estate'; DROP TABLE x; --"
    df = source.fetch(DATASET, context=ctx.with_filters(sector=hostile), fields=["account_id"])
    assert len(df) == 0


# -------------------------------------------------------------------- errors


def test_unknown_dataset_names_the_available_ones(source, ctx):
    with pytest.raises(UnknownDatasetError) as e:
        source.fetch("no_such_dataset", context=ctx)
    assert "portfolio_facility" in str(e.value)


def test_unknown_field_names_the_available_ones(source, ctx):
    with pytest.raises(UnknownFieldError) as e:
        source.fetch(DATASET, context=ctx, fields=["not_a_field"])
    assert "not_a_field" in str(e.value)


def test_missing_period_reports_what_is_available(source, ctx):
    with pytest.raises(DataAccessError) as e:
        source.fetch(DATASET, context=ctx, period="Q9 1999")
    assert "Q1 2026" in str(e.value)


def test_unsupported_aggregation_is_rejected(source, ctx):
    with pytest.raises(DataAccessError):
        source.aggregate(DATASET, context=ctx, group_by=[], measures={"ead": "median"})


# ------------------------------------------------------------------- context


def test_context_is_immutable_and_derives_new_objects():
    base = AnalysisContext(period="Q1 2026")
    narrowed = base.with_filters(sector="Energy")
    assert base.filters == {}, "deriving a context must not mutate the original"
    assert narrowed.filters == {"sector": "Energy"}
    assert narrowed.period == base.period


def test_context_describe_is_serialisable_for_trace():
    ctx = AnalysisContext(period="Q1 2026", compare_period="Q4 2025",
                          filters={"sector": "Energy", "region": "All"}, dataset_version=3)
    described = ctx.describe()
    assert described["compare_period"] == "Q4 2025"
    assert described["filters"] == {"sector": "Energy"}  # "All" dropped
    assert described["dataset_version"] == 3


def test_health_reports_what_is_available(source):
    health = source.health()
    assert health["status"] in {"ok", "empty"}
    assert DATASET in health["datasets"]
