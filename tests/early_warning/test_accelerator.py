"""The Version 2 accelerator: five weighted dimensions plus a separate,
class-specific decay factor, Tab 04 Section B/C of the corrected workbook.

The dimension math (weights, multiplier tables, blend formula) was already
correct in the earlier, incorrect workbook draft this module replaces —
verified here unchanged. What was wrong and is rebuilt: decay is not one
universal band table. All 8 of Tab 04 Section C's worked decay examples are
reproduced exactly, including the persistence hold (an uncured signal never
decays) and the hard staleness cut-off.
"""

from __future__ import annotations

from backend.early_warning.accelerator import (
    DIMENSION_WEIGHTS,
    HARD_CUTOFF_AGE_DAYS,
    HARD_CUTOFF_DECAY_FACTOR,
    AcceleratorInput,
    compute_accelerator,
    compute_decay,
    signal_score,
)


def test_dimension_weights_sum_to_one():
    assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9
    assert DIMENSION_WEIGHTS == {
        "magnitude": 0.30, "velocity": 0.20, "persistence": 0.20,
        "repetition": 0.10, "corroboration": 0.20,
    }


def test_worked_example_operating_deposit_balance_decline():
    """Tab 04 Section C: bands (3,3,3,2,3), decay 1.00 -> multiplier 1.15,
    trigger score 40 -> signal score 46."""
    result = compute_accelerator(AcceleratorInput(
        magnitude_band=3, velocity_band=3, persistence_band=3,
        repetition_band=2, corroboration_band=3, decay_factor=1.0,
    ))
    assert abs(result.accelerator_multiplier - 1.15) < 1e-9
    assert abs(signal_score(40, result.accelerator_multiplier) - 46.0) < 1e-9


def test_worked_example_reduction_in_account_credits():
    """Tab 04 Section C: bands (2,2,2,1,3), decay 0.90 -> multiplier
    0.9315, trigger score 40 -> signal score 37.26."""
    result = compute_accelerator(AcceleratorInput(
        magnitude_band=2, velocity_band=2, persistence_band=2,
        repetition_band=1, corroboration_band=3, decay_factor=0.90,
    ))
    assert abs(result.accelerator_multiplier - 0.9315) < 1e-9
    assert abs(signal_score(40, result.accelerator_multiplier) - 37.26) < 1e-9


def test_signal_score_capped_at_100():
    assert signal_score(100, 1.45) == 100.0


def test_practical_multiplier_range():
    """Tab 04 Section B: approximately 0.25-0.40 (stale, isolated, mild) to
    1.40-1.50 (fresh, large, fast, repeated, corroborated)."""
    worst = compute_accelerator(AcceleratorInput(1, 1, 1, 1, 1, decay_factor=0.176776695296637))
    best = compute_accelerator(AcceleratorInput(5, 5, 5, 5, 5, decay_factor=1.0))
    assert 0.15 < worst.accelerator_multiplier < 0.40
    assert 1.40 < best.accelerator_multiplier < 1.50


# ---------------------------------------------------------------------------
# The 8 worked decay examples, Tab 04 Section C, verbatim.
# ---------------------------------------------------------------------------

def test_excess_over_limit_cleared_12_days_ago():
    r = compute_decay("L1.1", cured=True, days_since_cure=12, age_days=12)
    assert abs(r.decay_factor - 0.672950096316178) < 1e-9
    assert r.in_scope


def test_excess_over_limit_still_active_90_days_keeps_full_weight():
    """The persistence hold: an uncured condition never decays, however old."""
    r = compute_decay("L1.2", cured=False, days_since_cure=0, age_days=90)
    assert r.decay_factor == 1.0
    assert r.in_scope


def test_returned_cheque_cured_60_days_ago():
    r = compute_decay("L1.3", cured=True, days_since_cure=60, age_days=60)
    assert abs(r.decay_factor - 0.39685026299205) < 1e-9
    assert r.in_scope


def test_covenant_breach_waived_100_days_ago():
    r = compute_decay("L2.T2", cured=True, days_since_cure=100, age_days=100)
    assert abs(r.decay_factor - 0.561231024154687) < 1e-9
    assert r.in_scope


def test_insolvency_petition_filed_200_days_ago_still_open():
    r = compute_decay("L3.2", cured=False, days_since_cure=0, age_days=200)
    assert r.decay_factor == 1.0
    assert r.in_scope


def test_rating_downgrade_150_days_ago_no_further_action():
    r = compute_decay("L3.3", cured=True, days_since_cure=150, age_days=150)
    assert abs(r.decay_factor - 0.176776695296637) < 1e-9
    assert r.in_scope


def test_contract_loss_reported_120_days_ago():
    r = compute_decay("L3.4", cured=True, days_since_cure=120, age_days=120)
    assert abs(r.decay_factor - 0.39685026299205) < 1e-9
    assert r.in_scope


def test_deposit_anomaly_cured_70_days_ago_is_excluded():
    """Compare against the 90-day-still-live excess over limit above: a
    cured, ageing deposit anomaly falls to about a tenth of its weight and
    drops out of scope; the still-live excess keeps full weight."""
    r = compute_decay("L1.1", cured=True, days_since_cure=70, age_days=70)
    assert abs(r.decay_factor - 0.0992125657480125) < 1e-9
    assert not r.in_scope


def test_hard_cutoff_constants():
    assert HARD_CUTOFF_DECAY_FACTOR == 0.15
    assert HARD_CUTOFF_AGE_DAYS == 400


def test_non_decaying_signal_never_fades():
    r = compute_decay("L3.2", cured=True, days_since_cure=10_000, age_days=10_000,
                       non_decaying=True)
    assert r.decay_factor == 1.0
    assert r.in_scope
