"""§14.4: the bins a rank ordering is measured on, and what an inversion says.

The defect these were written against: DISC-RANK read PASS on all eight
registered scorecards. Not because the scorecards rank perfectly — three of
them do not — but because the bands were twelve equal slices of a DECLARED
300-to-900 range over a population occupying 555 to 707, which left the
populated bands wide enough to average a local inversion away.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backend.scorecard.validation import (
    findings,
    models,
    ranking,
    registry,
    runner,
    states,
)

CLEAN = "retail_beh_credit_card"
INVERTS = "retail_beh_home_loan"


@pytest.fixture(scope="module")
def clean_model() -> models.Model:
    return models.get(CLEAN)


@pytest.fixture(scope="module")
def inverting() -> models.Model:
    return models.get(INVERTS)


@pytest.fixture(scope="module")
def inverting_rank(inverting: models.Model) -> states.Result:
    return runner.run("DISC-RANK", inverting)


@pytest.fixture(scope="module")
def clean_rank(clean_model: models.Model) -> states.Result:
    return runner.run("DISC-RANK", clean_model)


# -------------------------------------------------------------- the bands


def test_bands_come_from_the_development_population(
        inverting: models.Model) -> None:
    """Fixed cut points, so a band means the same score in every cohort.

    Cutting each cohort at its own quantiles compares every cohort to
    itself, and the persistence question — does this pair invert every
    month — cannot be asked at all.
    """
    reference = runner.reference_population(inverting)
    scores = pd.to_numeric(reference.frame[inverting.score_column],
                           errors="coerce").dropna()
    edges = ranking.band_edges(inverting)
    assert edges[0] == -math.inf and edges[-1] == math.inf
    # Ten interior bands plus two open tails: twelve bands, thirteen edges.
    assert len(edges) == ranking.INTERIOR_BANDS + 3
    assert math.isclose(edges[1], float(scores.quantile(ranking.LOW_TAIL)),
                        rel_tol=1e-6)
    assert math.isclose(edges[-2], float(scores.quantile(ranking.HIGH_TAIL)),
                        rel_tol=1e-6)


def test_the_bands_are_open_at_both_ends(
        inverting_rank: states.Result) -> None:
    """A score outside the development support is graded, not dropped."""
    rows = inverting_rank.table
    assert rows[0]["score_from"] is None
    assert rows[-1]["score_to"] is None


def test_no_tie_group_is_split_across_two_bands(
        inverting: models.Model) -> None:
    """§14.4's binning rule, checked rather than asserted in a docstring.

    Equal-width bands over fixed cut points cannot split a tie group; a
    quantile cut routinely does, and the two halves then differ by whatever
    the row order happened to be. This proves the property on the real
    population rather than trusting the construction.
    """
    pool = runner.population(inverting)
    edges = ranking.band_edges(inverting, pool.frame)
    scores = pd.to_numeric(pool.frame[inverting.score_column],
                           errors="coerce")
    band = pd.cut(scores, bins=edges)
    per_score = band.groupby(scores, observed=True).nunique()
    assert int(per_score.max()) == 1


def test_bands_stay_the_same_when_the_rows_are_shuffled(
        inverting: models.Model) -> None:
    """No row-order artifact. Shuffle the frame; every band rate is identical."""
    pool = runner.population(inverting)
    edges = ranking.band_edges(inverting, pool.frame)
    straight = ranking.band_evidence(pool.frame, inverting, edges)
    shuffled = ranking.band_evidence(
        pool.frame.sample(frac=1.0, random_state=7), inverting, edges)
    assert [row["band"] for row in straight] == [row["band"] for row in shuffled]
    assert [row["observed_rate"] for row in straight] == \
        [row["observed_rate"] for row in shuffled]


@pytest.mark.parametrize("column", [
    "score_from", "score_to", "accounts", "customers", "events",
    "observed_rate", "interval_low", "interval_high", "mean_predicted_pd",
    "largest_tied_share"])
def test_every_band_row_carries_what_14_4_asks_for(
        inverting_rank: states.Result, column: str) -> None:
    for row in inverting_rank.table:
        assert column in row


def test_the_interval_contains_the_rate(
        inverting_rank: states.Result) -> None:
    for row in inverting_rank.table:
        assert row["interval_low"] <= row["observed_rate"] <= \
            row["interval_high"]


def test_wilson_never_reaches_below_zero() -> None:
    """The reason it is not the normal approximation.

    Fifteen defaults in eleven hundred accounts is a band a good scorecard
    produces routinely, and the normal interval on it runs negative.
    """
    low, high = ranking.wilson(15, 1125)
    assert low > 0.0
    assert low < 15 / 1125 < high


def test_thin_bands_are_shown_and_not_tested(
        inverting_rank: states.Result) -> None:
    thin = [row for row in inverting_rank.table if not row["supported"]]
    if not thin:
        pytest.skip("every band clears the support floor on this book")
    assert all(row["accounts"] < ranking.BAND_SUPPORT for row in thin)
    assert "without being tested for ordering" in inverting_rank.detail


# ---------------------------------------------------------- the inversion


def test_the_demo_carries_a_credible_local_inversion(
        inverting_rank: states.Result) -> None:
    """§14.4: computed from the controlled source data, not asserted."""
    assert inverting_rank.value >= 1
    spots = inverting_rank.lineage["inversions"]
    assert spots
    worst = spots[0]
    assert worst["safer_rate"] > worst["riskier_rate"]
    assert worst["accounts_safer"] >= ranking.BAND_SUPPORT
    assert worst["accounts_riskier"] >= ranking.BAND_SUPPORT


def test_the_inversion_reports_size_support_and_concentration(
        inverting_rank: states.Result) -> None:
    worst = inverting_rank.lineage["inversions"][0]
    assert worst["size"] > 0
    assert worst["relative_size"] > 0
    assert worst["events_safer"] >= 0 and worst["events_riskier"] >= 0
    assert worst["concentration"]["field"]
    assert 0.0 <= worst["concentration"]["share_in_band"] <= 1.0


def test_persistence_is_measured_over_real_cohorts(
        inverting: models.Model, inverting_rank: states.Result) -> None:
    """The defect this closes.

    On a repeated-snapshot book the pooled population holds one row per
    subject, at that subject's most recent matured observation. Grouping
    THAT by month groups facilities by when they last matured — twelve
    months of fifty accounts and one of four thousand — and reported "no
    cohort is thick enough to assess" on a book with thirteen closed
    cohorts of fifteen thousand.
    """
    persistence = inverting_rank.lineage["inversions"][0]["persistence"]
    assert persistence["cohorts"] == len(runner.matured_periods(inverting))
    assert persistence["assessable"] >= 1
    assert persistence["inverted"] <= persistence["assessable"]


def test_an_overlapping_interval_is_a_warning_not_a_failure(
        inverting_rank: states.Result) -> None:
    """A state that says what the evidence supports.

    An inversion whose two intervals overlap is real and is not separated
    by this population. Reporting it as FAIL claims a certainty the numbers
    do not carry; reporting it as PASS hides it. It is its own state.
    """
    worst = inverting_rank.lineage["inversions"][0]
    if worst["separated_by_the_evidence"]:
        assert inverting_rank.state == states.FAIL
    else:
        assert inverting_rank.state == states.WARNING
        assert "overlap" in inverting_rank.detail


def test_a_clean_scorecard_still_passes(clean_rank: states.Result) -> None:
    """The comparison §14.4 asks for has to actually be clean."""
    assert clean_rank.state == states.PASS
    assert clean_rank.value == 0.0
    assert not clean_rank.lineage["inversions"]


# --------------------------------------------------------- the comparison


def test_the_peer_test_measures_every_sibling_of_the_same_kind(
        inverting: models.Model) -> None:
    got = runner.run("DISC-RANK-PEER", inverting)
    assert got.measured, got.detail
    kinds = {models.get(row["model_id"]).scorecard_type
             for row in got.table}
    assert kinds == {inverting.scorecard_type}
    assert got.table[0]["model_id"] == inverting.model_id


def test_the_peer_test_says_portfolio_or_design(
        clean_model: models.Model) -> None:
    got = runner.run("DISC-RANK-PEER", clean_model)
    assert "monotonically" in got.detail


# ------------------------------------------------------------ the finding


def test_the_inversion_finding_reports_ks_without_claiming_cause(
        inverting: models.Model) -> None:
    """§14.4: evaluate whether it ACCOMPANIES a weaker KS.

    The engine may say the two coincide. It may not say one produced the
    other, because one run cannot show that.
    """
    results = runner.run_category(registry.DISCRIMINATION, inverting)
    raised = findings.assess(results, inverting)
    one = next(f for f in raised
               if f.finding_id == "F-PATTERN-LOCAL-INVERSION")
    assert "DISC-KS" in one.what
    lowered = one.what.lower()
    assert "accompany" in lowered or "local ordering defect" in lowered
    for forbidden in ("causes", "caused by", "because the ks",
                      "which is why the ks"):
        assert forbidden not in lowered


def test_a_clean_scorecard_raises_no_inversion_finding(
        clean_model: models.Model) -> None:
    results = runner.run_category(registry.DISCRIMINATION, clean_model)
    raised = findings.assess(results, clean_model)
    assert "F-PATTERN-LOCAL-INVERSION" not in {f.finding_id for f in raised}
