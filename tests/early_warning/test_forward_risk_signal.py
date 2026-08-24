"""
The Forward Risk Signal.

The properties defended here are the ones that make the signal trustworthy
rather than merely functional:

  * the score decomposes EXACTLY — contributions plus intercept equal the score,
    to floating-point precision. Every explanation screen depends on this
  * the panel has no target leakage: factors come from t, outcomes from t+1
  * the fit refuses to produce a model from too little evidence
  * a fitted sign that disagrees with credit intuition is FLAGGED, not hidden
  * the model is tested out of time, and ranks better than chance
  * nothing can be called validated without a validation record
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.early_warning import backtest as bt
from backend.early_warning import lifecycle as lc
from backend.early_warning import service as ew
from backend.early_warning.factors import FACTORS, compute_factors
from backend.early_warning.model import (
    FittingError,
    SignalSpecification,
    Weight,
    band_for,
    fit_specification,
    score_frame,
)
from backend.early_warning.targets import TARGETS, UnknownTargetError, target


@pytest.fixture(scope="module")
def fitted() -> ew.FitResult:
    return ew.fit_and_backtest("stage1_to_stage2")


# ------------------------------------------------------------------ targets


def test_every_target_is_eligible_only_from_its_own_stage():
    for definition in TARGETS:
        assert definition.from_stage != definition.to_stage
        assert str(definition.from_stage) in definition.eligible_note


def test_an_unknown_target_says_which_ones_exist():
    with pytest.raises(UnknownTargetError) as e:
        target("stage4_to_stage9")
    assert "stage1_to_stage2" in str(e.value)


# ------------------------------------------------------------------ factors


def test_every_factor_declares_a_direction_and_a_family():
    for definition in FACTORS:
        assert definition.direction in ("up-is-worse", "up-is-better")
        assert definition.family
        assert definition.definition.endswith("."), definition.id


def test_a_missing_value_becomes_the_median_not_zero():
    """Zero is a real utilisation. Treating unknown as zero would score a gap in
    the data as though something were known."""
    frame = pd.DataFrame({
        "utilisation_pct": [40.0, 60.0, None],
        "prev_utilisation_pct": [40.0, 60.0, 50.0],
        "dpd_days": [0, 0, 0], "rollover_count": [0, 0, 0],
        "dscr": [2.0, 2.0, 2.0], "covenant_headroom_pct": [10.0, 10.0, 10.0],
        "internal_grade": [4, 4, 4], "prev_risk_rating": ["CP-4"] * 3,
        "pd_12m_pct": [1.0, 1.0, 1.0], "downgrade_prob_pct": [5.0, 5.0, 5.0],
        "ead": [10.0, 10.0, 10.0], "collateral_value": [5.0, 5.0, 5.0],
        "lgd_pct": [40.0, 40.0, 40.0], "news_sentiment": [0.0, 0.0, 0.0],
        "sector": ["Contracting"] * 3,
    })
    factors = compute_factors(frame, {"Contracting": 0.0})
    assert factors["utilisation"].iloc[2] == pytest.approx(50.0)


def test_the_factor_matrix_has_exactly_the_declared_factors():
    frame = pd.DataFrame({
        "utilisation_pct": [40.0], "prev_utilisation_pct": [30.0],
        "dpd_days": [0], "rollover_count": [0], "dscr": [2.0],
        "covenant_headroom_pct": [10.0], "internal_grade": [4],
        "prev_risk_rating": ["CP-3"], "pd_12m_pct": [1.0],
        "downgrade_prob_pct": [5.0], "ead": [10.0], "collateral_value": [5.0],
        "lgd_pct": [40.0], "news_sentiment": [0.0], "sector": ["Contracting"],
    })
    factors = compute_factors(frame, {})
    assert list(factors.columns) == [f.id for f in FACTORS]
    # A rating that moved from CP-3 to grade 4 is one notch of deterioration.
    assert factors["notch_move"].iloc[0] == pytest.approx(1.0)


# ------------------------------------------------------------------ fitting


def test_the_fit_refuses_a_population_too_small_to_learn_from():
    factors = pd.DataFrame(
        {f.id: np.zeros(100) for f in FACTORS}
    )
    with pytest.raises(FittingError) as e:
        fit_specification(factors, pd.Series(np.zeros(100)),
                          target_id="stage1_to_stage2")
    assert "500" in str(e.value)


def test_the_fit_refuses_a_population_with_almost_no_events():
    rng = np.random.default_rng(1)
    factors = pd.DataFrame({f.id: rng.normal(size=2000) for f in FACTORS})
    outcome = pd.Series(np.concatenate([np.ones(5), np.zeros(1995)]))
    with pytest.raises(FittingError) as e:
        fit_specification(factors, outcome, target_id="stage1_to_stage2")
    assert "40" in str(e.value)


def test_the_fit_recovers_a_relationship_that_is_really_there():
    """A factor that genuinely drives the outcome must come back with the right
    sign. If this fails, nothing else about the module means anything."""
    rng = np.random.default_rng(7)
    n = 4000
    values = {f.id: rng.normal(size=n) for f in FACTORS}
    factors = pd.DataFrame(values)
    logit = -2.0 + 1.5 * factors["days_past_due"] - 1.2 * factors["dscr"]
    outcome = pd.Series((rng.random(n) < 1 / (1 + np.exp(-logit))).astype(float))

    spec = fit_specification(factors, outcome, target_id="stage1_to_stage2")
    assert spec.weight_for("days_past_due").weight > 0.8
    assert spec.weight_for("dscr").weight < -0.6


def test_a_counter_intuitive_weight_is_flagged_rather_than_hidden():
    against = Weight(factor_id="dscr", weight=0.5, mean=0.0, std=1.0)
    with_expectation = Weight(factor_id="dscr", weight=-0.5, mean=0.0, std=1.0)
    # DSCR is up-is-better, so a POSITIVE weight disagrees with expectation.
    assert against.agrees_with_expectation is False
    assert with_expectation.agrees_with_expectation is True


# ------------------------------------------------------------------ scoring


def test_the_score_decomposes_exactly():
    """The property every explanation screen rests on. If the contributions do
    not sum to the score, the screen is a story rather than a decomposition."""
    rng = np.random.default_rng(3)
    n = 200
    factors = pd.DataFrame({f.id: rng.normal(size=n) for f in FACTORS})
    frame = pd.DataFrame({
        "account_id": [f"A{i}" for i in range(n)],
        "customer_id": ["C"] * n, "borrower_name": ["X"] * n,
        "sector": ["Contracting"] * n, "segment": ["SME"] * n,
        "ead": np.ones(n), "ifrs9_stage": np.ones(n, dtype=int),
    })
    spec = SignalSpecification(
        target_id="stage1_to_stage2",
        intercept=-2.4,
        weights=tuple(
            Weight(factor_id=f.id, weight=0.1 * (i + 1), mean=0.0, std=1.0)
            for i, f in enumerate(FACTORS)
        ),
    )
    for scored in score_frame(spec, frame, factors):
        assert scored.score == pytest.approx(
            scored.intercept + sum(scored.contributions.values()), abs=1e-9
        )
        assert sum(scored.family_contributions.values()) == pytest.approx(
            sum(scored.contributions.values()), abs=1e-9
        )
        assert scored.probability == pytest.approx(
            1 / (1 + math.exp(-scored.score)), abs=1e-12
        )


def test_bands_are_fixed_probabilities_not_quantiles():
    """A band defined by the worst decile moves whenever the book moves, so a
    facility that improved could stay in "High" forever."""
    assert band_for(30.0) == "Severe"
    assert band_for(12.0) == "High"
    assert band_for(4.9) == "Moderate"
    assert band_for(0.0) == "Low"


# ---------------------------------------------------------------- the panel


def test_the_panel_pairs_this_quarters_factors_with_next_quarters_outcome():
    definition = target("stage1_to_stage2")
    panel = ew.build_panel(definition)
    periods = sorted(set(panel.periods), key=lambda p: (int(p.split()[1]), int(p[1])))
    from backend.data_access.duckdb_source import DuckDBSource

    book_periods = DuckDBSource().periods("portfolio_facility")
    # The last period has no following quarter, so it can carry no outcome and
    # must not appear in the panel at all.
    assert book_periods[-1] not in periods
    assert len(periods) == len(book_periods) - 1


def test_only_eligible_facilities_are_in_the_panel():
    panel = ew.build_panel(target("stage2_to_stage3"))
    assert (panel.frame["ifrs9_stage"] == 2).all()


# ------------------------------------------------------------- backtesting


def test_auc_of_a_perfect_ranking_is_one_and_of_a_reversed_one_is_zero():
    scores = np.array([0.1, 0.2, 0.3, 0.4])
    assert bt.auc(scores, np.array([0.0, 0.0, 1.0, 1.0])) == pytest.approx(1.0)
    assert bt.auc(scores, np.array([1.0, 1.0, 0.0, 0.0])) == pytest.approx(0.0)


def test_auc_of_a_constant_score_is_a_coin_toss():
    """Every rank is tied, so no ordering exists and the honest answer is 0.5."""
    scores = np.full(100, 0.4)
    outcome = np.concatenate([np.ones(30), np.zeros(70)])
    assert bt.auc(scores, outcome) == pytest.approx(0.5)


def test_the_deciles_account_for_every_event():
    rng = np.random.default_rng(11)
    scores = rng.random(1000)
    outcome = (rng.random(1000) < 0.1).astype(float)
    rows = bt.deciles(scores, outcome)
    assert len(rows) == 10
    assert sum(r.events for r in rows) == int(outcome.sum())
    assert rows[-1].cumulative_capture_pct == pytest.approx(100.0)


def test_the_signal_is_tested_on_periods_it_was_never_fitted_on(fitted):
    assert not set(fitted.backtest.fitted_periods) & set(fitted.backtest.tested_periods)
    assert fitted.backtest.tested_periods


def test_the_signal_ranks_better_than_chance_out_of_time(fitted):
    assert fitted.backtest.auc > 0.6
    # The worst-scoring tenth should hold well over a tenth of the transitions,
    # or the ordering is not doing anything a credit officer could use.
    assert fitted.backtest.top_decile_capture_pct > 15.0


def test_the_verdict_always_says_it_is_not_a_validation(fitted):
    assert "not a validation" in fitted.backtest.verdict
    assert fitted.backtest.to_dict()["is_validation"] is False


# -------------------------------------------------------------- lifecycle


def test_a_model_cannot_call_itself_validated_without_a_record():
    assert lc.effective_lifecycle("validated", None) == lc.CANDIDATE
    assert lc.effective_lifecycle("approved", {}) == lc.CANDIDATE
    assert "validated" not in lc.label_for("validated", None).lower()


def test_a_partial_validation_record_is_not_a_validation():
    """One name in a box is somebody signing their own homework."""
    assert lc.has_validation({"validated_by": "Model Risk"}) is False
    assert lc.has_validation({
        "validated_by": "Model Risk", "validated_on": "2026-03-31",
        "report_reference": "MRM-2026-014",
    }) is True


def test_a_complete_record_permits_the_word():
    record = {
        "validated_by": "Model Risk", "validated_on": "2026-03-31",
        "report_reference": "MRM-2026-014",
    }
    assert lc.effective_lifecycle("validated", record) == lc.VALIDATED
    assert lc.label_for("validated", record) == "Independently validated"
    assert "Model Risk" in lc.notice_for("validated", record)


def test_an_unvalidated_model_is_named_a_prototype():
    name = lc.display_name("Stage 1 to Stage 2", lc.PROTOTYPE, None)
    assert name.startswith("Prototype Forward Risk Signal")
    notice = lc.notice_for(lc.PROTOTYPE, None)
    assert "not a production or regulatory model" in notice


def test_the_capability_never_describes_itself_as_production():
    for text in (lc.CAPABILITY_LABEL, lc.CAPABILITY_NOTICE):
        assert "production model" not in text.replace(
            "not a production or regulatory model", ""
        )
