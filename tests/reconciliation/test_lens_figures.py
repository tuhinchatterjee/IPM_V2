"""Are the figures on the specialist lenses right?

The same gate `test_numbers.py` applies to the validation statistics, applied
to the Metric Catalogue. Every figure below is computed twice:

  * once by the production stack — `metrics.value(...)`, which compiles the
    metric's formula to the analytical IR, validates it against the governed
    catalogue and executes it through DuckDB, exactly as a lens tile does;
  * once here, by reading the parquet partitions with pandas and applying the
    metric's stated definition by hand.

The second path shares no code with the first. It does not import
`backend.metrics.execution`, does not build a plan, and never sees the IR. It
reads columns and does arithmetic. That is the whole value: a check that ran
the same compiler would reproduce the same compiler bug and agree with it to
fifteen decimal places.

What is reconciled
------------------
The eighteen metrics added for the specialist lenses, because a metric nobody
has independently recomputed is a metric nobody has checked; and one figure of
each shape that was already there — a level, a share, a weighted average — so
that the harness itself is proved against numbers with a known history.

On tolerances
-------------
Every assertion uses 1e-9, which is two float summations in different orders
and nothing else. Nothing here is looser, because nothing here has a reason to
be: both paths sum the same column over the same rows. A figure that needs a
wider tolerance than this has a difference in its definition, and widening the
tolerance would hide exactly the thing this file exists to find.
"""

from __future__ import annotations

import pytest

from tests.reconciliation import independent as check

EXACT = 1e-9

STAGING = "ifrs9_staging"
BEHAVIOURAL = "retail_behavioral_scorecard_monthly_validation"

#: A quarter the staging dataset genuinely has, with movement in it.
QUARTER = "Q2 2026"
#: A month the behavioural dataset genuinely has.
MONTH = "2025-07"


def _lake_present() -> bool:
    return check.analytics_root().exists()


pytestmark = pytest.mark.skipif(
    not _lake_present(),
    reason="the analytics lake is not built in this working copy")


@pytest.fixture(scope="module")
def staging():
    return check.read(STAGING, periods=(QUARTER,), period_field="period")


@pytest.fixture(scope="module")
def behaviour():
    return check.read(BEHAVIOURAL, periods=(MONTH,),
                      period_field="observation_month")


def produced(metric_id: str, period: str) -> float:
    """What the platform says, through the path a lens tile uses."""
    from backend.metrics import service as metrics

    answer = metrics.value(metric_id, period=period)
    assert answer["available"], (
        f"{metric_id} produced no value for {period}: "
        f"{answer['unavailable']}")
    return float(answer["value"])


def agree(metric_id: str, period: str, expected: float) -> None:
    got = produced(metric_id, period)
    assert got == pytest.approx(expected, rel=EXACT, abs=EXACT), (
        f"{metric_id} for {period}: the platform says {got!r} and an "
        f"independent read of the parquet says {expected!r}")


# --------------------------------------------- the harness proves itself


def test_the_independent_path_does_not_import_the_metric_engine():
    """The moment it does, every test below becomes a tautology."""
    import inspect

    source = inspect.getsource(check)
    for forbidden in ("backend.metrics.execution", "backend.metrics.formula",
                      "backend.runtime.ir", "backend.runtime.executor"):
        assert forbidden not in source, forbidden


# ------------------------------------------ IFRS 9: levels already shipped


def test_total_exposure(staging):
    agree("corporate.ifrs9.total_ead", QUARTER, staging["ead"].sum())


def test_total_ecl(staging):
    agree("corporate.ifrs9.total_ecl", QUARTER, staging["total_ecl"].sum())


def test_coverage_is_the_provision_over_the_exposure(staging):
    agree("corporate.ifrs9.coverage", QUARTER,
          100.0 * staging["total_ecl"].sum() / staging["ead"].sum())


def test_exposure_weighted_pd(staging):
    weighted = (staging["pd_12m_pct"] * staging["ead"]).sum()
    agree("corporate.ifrs9.weighted_pd", QUARTER,
          weighted / staging["ead"].sum())


# ------------------------------------------------- IFRS 9: stage migration


@pytest.mark.parametrize("metric_id,frm,to", [
    ("corporate.ifrs9.stage_1_to_2_ead", 1, 2),
    ("corporate.ifrs9.stage_2_to_1_ead", 2, 1),
    ("corporate.ifrs9.stage_2_to_3_ead", 2, 3),
])
def test_a_stage_transition_is_the_exposure_that_made_it(staging, metric_id,
                                                         frm, to):
    moved = staging[(staging["prior_stage"] == frm)
                    & (staging["ifrs9_stage"] == to)]
    assert len(moved) > 0, (
        f"no facility moved {frm}->{to} in {QUARTER}; this reconciliation "
        "would pass on an empty set and prove nothing")
    agree(metric_id, QUARTER, moved["ead"].sum())


def test_new_defaults_are_entries_to_stage_three_from_anywhere(staging):
    entered = staging[(staging["prior_stage"] != 3)
                      & (staging["ifrs9_stage"] == 3)]
    assert len(entered) > 0
    agree("corporate.ifrs9.new_default_ead", QUARTER, entered["ead"].sum())


def test_cures_are_exits_from_stage_three_to_anywhere(staging):
    left = staging[(staging["prior_stage"] == 3)
                   & (staging["ifrs9_stage"] != 3)]
    assert len(left) > 0
    agree("corporate.ifrs9.cured_ead", QUARTER, left["ead"].sum())


def test_the_transition_amounts_account_for_every_facility_that_moved(staging):
    """Nothing moved that no transition metric counts.

    The five amounts are not a partition — 1->3 is inside new defaults and not
    inside any of the three named transitions — so this checks the weaker and
    more useful property: the exposure the platform calls "changed stage" is
    exactly the exposure whose prior stage differs from its stage.
    """
    changed = staging[staging["prior_stage"] != staging["ifrs9_stage"]]
    agree("corporate.ifrs9.stage_moved", QUARTER,
          100.0 * changed["ead"].sum() / staging["ead"].sum())


@pytest.mark.parametrize("metric_id,base,moved", [
    ("corporate.ifrs9.stage_2_inflow_rate",
     lambda d: d["prior_stage"] == 1,
     lambda d: (d["prior_stage"] == 1) & (d["ifrs9_stage"] == 2)),
    ("corporate.ifrs9.new_default_rate",
     lambda d: d["prior_stage"] != 3,
     lambda d: (d["prior_stage"] != 3) & (d["ifrs9_stage"] == 3)),
    ("corporate.ifrs9.cure_rate",
     lambda d: d["prior_stage"] == 3,
     lambda d: (d["prior_stage"] == 3) & (d["ifrs9_stage"] != 3)),
])
def test_a_transition_rate_is_over_the_population_that_could_have_moved(
        staging, metric_id, base, moved):
    """The denominator is the origin stage, not the book.

    This is the assertion that would catch the easy mistake: a new-default
    rate over total exposure looks reasonable, falls whenever the book grows,
    and is not a default rate.
    """
    denominator = staging[base(staging)]["ead"].sum()
    numerator = staging[moved(staging)]["ead"].sum()
    assert denominator > 0 and numerator > 0
    agree(metric_id, QUARTER, 100.0 * numerator / denominator)
    # And it is NOT the same number over the whole book, or the test above
    # would pass for the wrong reason.
    assert denominator != staging["ead"].sum()


# ------------------------------------------------------- IFRS 9: triggers


@pytest.mark.parametrize("metric_id,column", [
    ("corporate.ifrs9.sicr_dpd", "sicr_dpd_trigger"),
    ("corporate.ifrs9.sicr_pd", "sicr_pd_trigger"),
    ("corporate.ifrs9.sicr_rating", "sicr_rating_trigger"),
    ("corporate.ifrs9.sicr_watchlist", "sicr_watchlist_trigger"),
    ("corporate.ifrs9.sicr_covenant", "sicr_covenant_trigger"),
])
def test_a_sicr_trigger_rate_is_the_exposure_it_fired_on(staging, metric_id,
                                                         column):
    fired = staging[staging[column].astype(bool)]["ead"].sum()
    agree(metric_id, QUARTER, 100.0 * fired / staging["ead"].sum())


def test_the_trigger_rates_overlap_rather_than_partition(staging):
    """The metric panels say so; the data has to agree, or the note is wrong."""
    columns = ["sicr_dpd_trigger", "sicr_pd_trigger", "sicr_rating_trigger",
               "sicr_watchlist_trigger", "sicr_covenant_trigger"]
    separately = sum(staging[staging[c].astype(bool)]["ead"].sum()
                     for c in columns)
    together = staging[staging["sicr_any_trigger"].astype(bool)]["ead"].sum()
    assert separately > together, (
        "no facility fires two triggers, so the panels' warning that these "
        "overlap is not true of this data and should not be shown")


def test_pd_drift_is_exposure_weighted(staging):
    weighted = (staging["pd_ratio_to_origination"] * staging["ead"]).sum()
    agree("corporate.ifrs9.pd_drift", QUARTER,
          weighted / staging["ead"].sum())
    # Unweighted would be a different number, so the weighting is doing work.
    assert staging["pd_ratio_to_origination"].mean() != pytest.approx(
        weighted / staging["ead"].sum(), rel=1e-6)


# --------------------------------------------------- retail: in and out of


def test_the_cure_rate_is_over_the_accounts_that_went_behind(behaviour):
    behind = behaviour[behaviour["max_dpd_3m"] >= 30]
    cured = behind[behind["current_dpd"] == 0]
    assert len(behind) > 0 and len(cured) > 0
    agree("retail.cure_rate_3m", MONTH, 100.0 * len(cured) / len(behind))
    # Over every account it would be a different, smaller number: the point of
    # a cure rate is the population it is over.
    assert len(behind) != len(behaviour)


def test_repeat_delinquency_is_over_every_account(behaviour):
    repeat = behaviour[behaviour["times_dpd_30plus_6m"] >= 2]
    assert len(repeat) > 0
    agree("retail.repeat_delinquency_rate", MONTH,
          100.0 * len(repeat) / len(behaviour))


def test_repeat_delinquency_is_not_the_thirty_day_bucket(behaviour):
    """The panel says the two measure different things. They have to."""
    repeat = (behaviour["times_dpd_30plus_6m"] >= 2).sum()
    behind_now = (behaviour["current_dpd"] >= 30).sum()
    assert repeat != behind_now


def test_the_retail_arrears_buckets_nest(behaviour):
    """Nothing is 90+ days late without being 30+ days late."""
    for wider, narrower in ((1, 30), (30, 60), (60, 90)):
        assert ((behaviour["current_dpd"] >= wider).sum()
                >= (behaviour["current_dpd"] >= narrower).sum())


@pytest.mark.parametrize("metric_id,bucket", [
    ("retail.dpd_30_count", 30),
    ("retail.dpd_60_count", 60),
    ("retail.dpd_90_count", 90),
])
def test_an_arrears_bucket_is_the_share_of_accounts_in_it(behaviour, metric_id,
                                                          bucket):
    late = (behaviour["current_dpd"] >= bucket).sum()
    agree(metric_id, MONTH, 100.0 * late / len(behaviour))
