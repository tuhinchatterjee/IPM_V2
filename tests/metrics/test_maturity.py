"""An outcome that has not happened yet must not be reported as zero.

The defect these tests hold shut was found by reading the Retail Credit Risk
lens rather than by a failing test. It showed "Retail Default Rate 0.0%" for
July 2025 — and 0.0% is a claim about the book. The truth was a claim about
the calendar: no account observed in July has had its performance window
close, so `actual_default` is false for every row, and a metric counting those
rows divides zero defaults by nineteen thousand accounts and calls it nought.

The same held for the application cohort bad rate, whose own `exclusions` note
already said immature cohorts understate the rate. A caveat in an info panel a
reader may never open is not the same as not showing a fabricated zero.

Both metrics are now scoped to matured rows and dated to the latest matured
period, which is what every other outcome metric on these datasets — Gini, KS,
predicted-versus-observed — already did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import settings
from backend.metrics import service as metrics

pd = pytest.importorskip("pandas")

#: The two metrics that read an outcome over a performance window.
OUTCOMES = ("retail.default_rate", "retail.application_bad_rate")

DATASETS = {
    "retail.default_rate": (
        "retail_behavioral_scorecard_monthly_validation", "observation_month"),
    "retail.application_bad_rate": (
        "retail_application_scorecard_monthly_validation", "application_month"),
}


def _partitions(dataset: str) -> list[str]:
    root = Path(settings.analytics_dir) / dataset
    if not root.exists():
        return []
    return sorted(p.name.split("=", 1)[1] for p in root.iterdir() if p.is_dir())


def _frame(dataset: str, field: str, period: str):
    root = Path(settings.analytics_dir) / dataset / f"{field}={period}"
    files = sorted(root.glob("*.parquet"))
    if not files:
        return None
    return pd.concat([pd.read_parquet(f) for f in files])


@pytest.mark.parametrize("metric_id", OUTCOMES)
def test_an_immature_period_has_no_value_rather_than_zero(metric_id):
    dataset, field = DATASETS[metric_id]
    periods = _partitions(dataset)
    if not periods:
        pytest.skip(f"{dataset} is not in this deployment's lake")

    immature = None
    for period in reversed(periods):
        frame = _frame(dataset, field, period)
        if frame is not None and int(frame["matured_flag"].sum()) == 0:
            immature = period
            break
    if immature is None:
        pytest.skip("every period in this lake has matured rows")

    outcome = metrics.value(metric_id, period=immature)
    assert outcome["value"] is None, (
        f"{metric_id} reported {outcome['value']!r} for {immature}, where no "
        "account's performance window has closed. A number here is a claim "
        "the data does not support.")
    assert outcome["available"] is False
    assert outcome["unavailable"], "and it has to say why"


@pytest.mark.parametrize("metric_id", OUTCOMES)
def test_the_default_period_is_one_where_the_outcome_exists(metric_id):
    dataset, field = DATASETS[metric_id]
    if not _partitions(dataset):
        pytest.skip(f"{dataset} is not in this deployment's lake")

    outcome = metrics.value(metric_id)
    assert outcome["value"] is not None, (
        f"{metric_id} has no value for its own default period, so the lens "
        "shows a gap where a number should be")
    frame = _frame(dataset, field, outcome["period"])
    assert frame is not None
    assert int(frame["matured_flag"].sum()) > 0, (
        f"{metric_id} defaulted to {outcome['period']}, which has no matured "
        "rows")


@pytest.mark.parametrize("metric_id", OUTCOMES)
def test_the_rate_is_the_one_the_matured_rows_support(metric_id):
    """Computed again from the parquet, over the matured rows only."""
    dataset, field = DATASETS[metric_id]
    if not _partitions(dataset):
        pytest.skip(f"{dataset} is not in this deployment's lake")

    outcome = metrics.value(metric_id)
    frame = _frame(dataset, field, outcome["period"])
    matured = frame[frame["matured_flag"] == True]  # noqa: E712
    expected = 100.0 * matured["actual_default"].mean()
    assert outcome["value"] == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("metric_id", OUTCOMES)
def test_the_metric_says_it_counts_only_closed_windows(metric_id):
    """The reader has to be able to find out, not only be given the number."""
    metric = metrics.resolve(metric_id)
    said = " ".join([metric.transformation, metric.exclusions]).lower()
    assert "matured_flag" in {c.field for c in metric.scope}
    assert "window" in said and ("closed" in said or "finished" in said)


def test_a_metric_scoped_to_nothing_says_so_rather_than_naming_a_filter():
    """The message a reader gets when a scope empties the period.

    "No rows matched its terms" sends somebody looking for a broken filter.
    The scope is doing exactly what it was written to do; what changed is the
    population, and that is what the tile should say.
    """
    dataset, field = DATASETS["retail.default_rate"]
    periods = _partitions(dataset)
    if not periods:
        pytest.skip(f"{dataset} is not in this deployment's lake")
    immature = next(
        (p for p in reversed(periods)
         if (f := _frame(dataset, field, p)) is not None
         and int(f["matured_flag"].sum()) == 0), None)
    if immature is None:
        pytest.skip("every period in this lake has matured rows")

    said = metrics.value("retail.default_rate", period=immature)["unavailable"]
    assert "scope" in said
    assert "not a failure" in said
