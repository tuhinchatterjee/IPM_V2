"""The Version 2 accelerator: five weighted dimensions plus a separate
recency/decay factor, Tab 3 Section B/C.

Both worked-example rows are reproduced exactly, including the recency band
that differs between them (band 1 for the first, band 2 for the second) —
this is the only place decay enters the signal score, and the workbook does
not specify per-signal-class half-lives or a persistence-hold/cure-date
mechanism (Conflict B): one universal band table, verified here.
"""

from __future__ import annotations

from backend.early_warning.accelerator import (
    DIMENSION_WEIGHTS,
    AcceleratorInput,
    compute_accelerator,
    recency_band_index,
    recency_factor,
    signal_score,
)


def test_dimension_weights_sum_to_one():
    assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9
    assert DIMENSION_WEIGHTS == {
        "magnitude": 0.30, "velocity": 0.20, "persistence": 0.20,
        "repetition": 0.10, "corroboration": 0.20,
    }


def test_recency_bands():
    assert recency_factor(0) == 1.00
    assert recency_factor(7) == 1.00
    assert recency_factor(8) == 0.90
    assert recency_factor(30) == 0.90
    assert recency_factor(31) == 0.75
    assert recency_factor(60) == 0.75
    assert recency_factor(61) == 0.55
    assert recency_factor(120) == 0.55
    assert recency_factor(121) == 0.35
    assert recency_factor(10_000) == 0.35


def test_recency_band_index():
    assert recency_band_index(3) == 1
    assert recency_band_index(15) == 2
    assert recency_band_index(45) == 3
    assert recency_band_index(90) == 4
    assert recency_band_index(400) == 5


def test_worked_example_operating_deposit_balance_decline():
    """Tab 3 Section C: bands (3,3,3,2,3), recency band 1 -> multiplier 1.15,
    trigger score 40 -> signal score 46."""
    result = compute_accelerator(AcceleratorInput(
        magnitude_band=3, velocity_band=3, persistence_band=3,
        repetition_band=2, corroboration_band=3, age_days=5,
    ))
    assert abs(result.accelerator_multiplier - 1.15) < 1e-9
    assert abs(signal_score(40, result.accelerator_multiplier) - 46.0) < 1e-9


def test_worked_example_reduction_in_account_credits():
    """Tab 3 Section C: bands (2,2,2,1,3), recency band 2 -> multiplier
    0.9315, trigger score 40 -> signal score 37.26."""
    result = compute_accelerator(AcceleratorInput(
        magnitude_band=2, velocity_band=2, persistence_band=2,
        repetition_band=1, corroboration_band=3, age_days=15,
    ))
    assert abs(result.accelerator_multiplier - 0.9315) < 1e-9
    assert abs(signal_score(40, result.accelerator_multiplier) - 37.26) < 1e-9


def test_signal_score_capped_at_100():
    assert signal_score(100, 1.45) == 100.0


def test_practical_multiplier_range():
    """Tab 3 Section B: "approximately 0.30 (stale, isolated, mild) to 1.47
    (fresh, large, fast, repeated, corroborated)"."""
    worst = compute_accelerator(AcceleratorInput(1, 1, 1, 1, 1, age_days=500))
    best = compute_accelerator(AcceleratorInput(5, 5, 5, 5, 5, age_days=0))
    assert 0.25 < worst.accelerator_multiplier < 0.40
    assert 1.40 < best.accelerator_multiplier < 1.50
