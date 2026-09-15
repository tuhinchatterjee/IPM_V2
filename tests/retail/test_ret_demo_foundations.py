"""Phase 2 of the demo completion contract: periods, metrics, source stamps.

Small fixed fixtures where the arithmetic has one right answer, and
book-derived checks where the point is that the data agrees with itself. An
expected value here is never produced by calling the thing under test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.retail import domains
from backend.retail import metric_registry as R
from backend.retail import periods as P
from backend.retail import source_stamp

# The book's real chronology, written out rather than read from the lake: a
# test that asks the data what the answer is cannot catch the data being wrong.
MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13)]
BOOK = [one for one in MONTHS if "2024-08" <= one <= "2026-08"]


# ======================= PERIODS: the clock is the data =====================

def test_per_01_the_latest_complete_quarter_is_q2_not_q3() -> None:
    """August completes nothing. The contract forbids calling it a Q3 close."""
    got = P.default_comparison(BOOK)
    assert got is not None
    assert got.current.label == "Q2 2026"
    assert got.current.months == ["2026-04", "2026-05", "2026-06"]
    assert got.prior.label == "Q1 2026"
    assert got.prior.months == ["2026-01", "2026-02", "2026-03"]
    assert got.current.complete and got.prior.complete


def test_per_02_quarter_to_date_is_offered_and_is_not_called_a_quarter() -> None:
    got = P.qtd_comparison(BOOK)
    assert got is not None
    assert got.current.months == ["2026-07", "2026-08"]
    assert got.current.complete is False
    assert got.current.kind == "quarter_to_date"
    # Two months against two months. A two-month window compared with a
    # three-month quarter is two questions wearing one label.
    assert len(got.prior.months) == len(got.current.months) == 2
    assert got.prior.months == ["2026-05", "2026-06"]


def test_per_03_a_twelve_month_outcome_stops_at_august_2025() -> None:
    got = P.maturity(BOOK)
    assert got is not None
    assert got.observation_cutoff == "2025-08"
    assert got.matured("2025-08") is True
    assert got.matured("2025-09") is False
    assert got.matured("2026-08") is False
    assert len(got.censored) == 12
    assert "censored" in got.to_dict()["statement"]


def test_per_04_a_quarter_missing_a_month_is_not_complete() -> None:
    """A gap in the book must not be papered over by the label."""
    holed = [one for one in BOOK if one != "2026-05"]
    got = P.default_comparison(holed)
    assert got is not None
    # Q2 is incomplete without May, so the answer steps back to Q1.
    assert got.current.label == "Q1 2026"


def test_per_05_month_arithmetic_crosses_the_year(
) -> None:
    assert P.shift("2026-01", -1) == "2025-12"
    assert P.shift("2025-12", 1) == "2026-01"
    assert P.shift("2026-08", -12) == "2025-08"
    assert P.span("2025-11", "2026-02") == ["2025-11", "2025-12",
                                            "2026-01", "2026-02"]


# ==================== METRICS: two screens cannot disagree ==================

def test_met_01_a_dpd_stock_may_not_be_compared_with_a_twelve_month_odr() -> None:
    """The comparison the contract singles out as meaningless."""
    assert R.comparable("ret.dpd30.exposure", "ret.odr.12m") is False
    why = R.refuse_comparison("ret.dpd30.exposure", "ret.odr.12m")
    assert "stock at month-end" in why
    assert "event rate over a window" in why


def test_met_02_odr_and_predicted_pd_are_the_one_allowed_pairing() -> None:
    assert R.comparable("ret.odr.12m", "ret.pd.mean_12m") is True
    assert R.refuse_comparison("ret.odr.12m", "ret.pd.mean_12m") == ""


def test_met_03_exposure_and_count_dpd_are_separate_ids() -> None:
    weighted = R.get("ret.dpd30.exposure")
    counted = R.get("ret.dpd30.accounts")
    assert weighted.weighting != counted.weighting
    assert weighted.denominator != counted.denominator
    assert R.comparable(weighted.metric_id, counted.metric_id) is True


def test_met_04_psi_is_the_published_formula() -> None:
    """Σ (pc − pr) ln(pc/pr), checked against arithmetic done by hand."""
    import math

    reference, current = [100, 100, 100, 100], [250, 50, 50, 50]
    # shares: reference .25 each; current .625, .125, .125, .125
    expected = ((0.625 - 0.25) * math.log(0.625 / 0.25)
                + 3 * ((0.125 - 0.25) * math.log(0.125 / 0.25)))
    got = R.stability_index(reference, current)
    assert got["index"] == pytest.approx(expected, abs=1e-6)
    assert got["smoothed_bins"] == 0


def test_met_05_an_empty_bin_is_smoothed_and_says_so() -> None:
    got = R.stability_index([100, 0, 100], [50, 50, 100])
    assert got["index"] is not None
    assert got["smoothed_bins"] == 1
    assert str(got["smoothing"]) in got["note"]


def test_met_06_an_empty_population_refuses_rather_than_returns_zero() -> None:
    got = R.stability_index([0, 0], [5, 5])
    assert got["index"] is None
    assert "empty" in got["because"]


def test_met_07_every_definition_names_its_denominator_and_horizon() -> None:
    for one in R.DEFINITIONS:
        assert one.numerator and one.denominator, one.metric_id
        assert one.population and one.horizon, one.metric_id
        assert one.version


def test_met_08_the_threshold_bands_are_declared_as_policy() -> None:
    """A PSI band is somebody's judgement; the module has to say so."""
    assert R.band(0.05) == "stable"
    assert R.band(0.20) == "watch"
    assert R.band(0.40) == "material"
    assert R.band(None) == "not available"
    assert "policy" in R.get("ret.psi.score").not_this.lower()


# ================= SOURCE STAMPS: the recurring upgrade defect ==============

def test_stp_01_every_derived_view_records_the_book_it_came_from() -> None:
    """The gap the contract names: three views carried no stamp at all."""
    from backend.config import settings

    root = Path(settings.analytics_dir)
    published = source_stamp.book_hash()
    assert published, "the book carries no manifest hash"
    for view in domains.DERIVED:
        stamp = root / view.dataset / "_built_from.json"
        assert stamp.exists(), f"{view.dataset} carries no source stamp"
        held = json.loads(stamp.read_text()).get("manifest_hash")
        assert held == published, (
            f"{view.dataset} was built from {held!r}, not the published "
            f"{published!r}")


def test_stp_02_a_changed_book_makes_every_view_stale(tmp_path) -> None:
    """Mutate the stamp, not the book: the same arithmetic, far cheaper."""
    from backend.config import settings

    root = Path(settings.analytics_dir)
    view = domains.DERIVED[0].dataset
    path = root / view / "_built_from.json"
    held = path.read_text()
    try:
        path.write_text(json.dumps({"manifest_hash": "0" * 64}))
        assert source_stamp.stale(root, view) is True
    finally:
        path.write_text(held)
    assert source_stamp.stale(root, view) is False


def test_stp_03_stamping_happens_on_completion_not_on_writing() -> None:
    """The defect: `record()` was inside `if written:`.

    A view already holding every month writes nothing, so it was never
    stamped — and an unstamped view can never be found stale, which is the
    one thing the stamp exists to do.
    """
    import inspect

    source = inspect.getsource(domains.build)
    assert "if _complete(target, months):" in source
    body = source[source.index("if written:"):]
    head = body[:body.index("if _complete")]
    assert "source_stamp.record" not in head, (
        "recording the stamp is back inside the write branch")


def test_stp_04_an_unstamped_view_is_reconciled_before_it_is_trusted() -> None:
    import inspect

    source = inspect.getsource(domains.build)
    assert "_stamp_of(root, view.dataset)" in source
    assert "reconcile(analytics_dir=root)" in source
