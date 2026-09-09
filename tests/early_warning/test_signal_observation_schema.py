"""A signal that cannot show its own working is a number, not evidence.

The workbook asks every scored signal to be able to show the trigger
severity it started from, each of the five accelerator dimension bands that
scaled it, and the decay factor that aged it. The customer report's
evidence-and-lineage table asks the same signal for its source system, its
signal class, its half-life and the decay actually applied. All of those are
computed while the score is being produced; until this schema existed the
build threw them away and both questions could only be answered by
re-deriving them somewhere else — and a re-derivation is not evidence, it is
a second opinion that happens to agree.

These tests hold the persisted explanation to the arithmetic it claims.
"""

from __future__ import annotations

import pytest

from backend.early_warning import accelerator as accel
from backend.early_warning import v2_service as svc

EXPLANATION_COLUMNS = (
    "layer", "trigger_severity_band", "trigger_severity_score",
    "magnitude_band", "velocity_band", "persistence_band",
    "repetition_band", "corroboration_band",
    "magnitude_multiplier", "velocity_multiplier", "persistence_multiplier",
    "repetition_multiplier", "corroboration_multiplier",
    "accelerator_multiplier", "decay_factor", "decay_class",
    "half_life_days", "decay_floor", "cured", "days_since_cure", "age_days",
    "occurrences", "source_domain", "source_dataset", "is_synthetic",
)


@pytest.fixture(scope="module")
def observations():
    try:
        period = svc.latest_period()
    except Exception:  # noqa: BLE001 - the domain is not built in this checkout
        pytest.skip("Early Warning V2 domain is not built")
    frame = svc._load(svc.SIGNAL_OBSERVATION)
    frame = frame[frame["snapshot_month"] == period]
    if frame.empty:
        pytest.skip("no signals fired in the latest period")
    return frame


def test_every_explanation_column_is_present(observations):
    missing = [c for c in EXPLANATION_COLUMNS if c not in observations.columns]
    assert not missing, f"signal observations cannot explain themselves: {missing}"


def test_severity_times_accelerator_reproduces_the_score(observations):
    """The published formula, checked against what was actually written.

    `signal_score = MIN(100, trigger severity x accelerator multiplier)`. If
    the persisted parts do not multiply back to the persisted whole, the
    explanation belongs to a different calculation than the score.
    """
    for _, row in observations.iterrows():
        expected = min(100.0, row["trigger_severity_score"] * row["accelerator_multiplier"])
        assert row["signal_score"] == pytest.approx(expected, abs=0.01), row["signal_key"]


def test_an_uncured_condition_keeps_full_weight(observations):
    """The persistence hold. A live condition does not age.

    This is the specific behaviour the corrected workbook introduced and the
    superseded one got wrong: the decay clock starts on cure, so a 90-day
    overdue that is still overdue carries a decay factor of 1.00 however old
    it is.
    """
    uncured = observations[~observations["cured"].astype(bool)]
    if uncured.empty:
        pytest.skip("no uncured signal in this period")
    assert (uncured["decay_factor"] == 1.0).all()
    assert (uncured["days_since_cure"] == 0).all()


def test_decay_class_and_half_life_agree_with_the_sub_category(observations):
    for _, row in observations.iterrows():
        published = accel.SUBCATEGORY_DECAY_CLASS.get(row["sub_category"])
        if published is None:
            continue
        assert row["decay_class"] == published.name, row["signal_key"]
        assert row["half_life_days"] == published.half_life_days, row["signal_key"]


def test_dimension_bands_are_inside_the_published_scale(observations):
    for dimension in ("magnitude", "velocity", "persistence", "repetition",
                      "corroboration"):
        bands = observations[f"{dimension}_band"]
        assert bands.between(1, 5).all(), dimension


def test_layer_3_is_always_flagged_synthetic(observations):
    """No live external-intelligence feed exists in this deployment, so every
    Layer 3 reading is governed synthetic demonstration data and must say so
    wherever it is read — including here, one row from the answer."""
    layer3 = observations[observations["layer"] == "L3"]
    if layer3.empty:
        pytest.skip("no Layer 3 signal fired in this period")
    assert layer3["is_synthetic"].astype(bool).all()
    assert (layer3["source_dataset"] == "early_warning_external_event_synthetic").all()


def test_signal_evidence_returns_one_signals_full_reading(observations):
    row = observations.iloc[0]
    found = svc.signal_evidence(row["customer_id"], row["signal_key"],
                                row["snapshot_month"])
    assert found is not None
    assert found["signal_key"] == row["signal_key"]
    assert found["decay_class"]
    assert found["source_domain"]


def test_signal_evidence_says_nothing_rather_than_zero(observations):
    row = observations.iloc[0]
    assert svc.signal_evidence(row["customer_id"], "not_a_real_signal",
                               row["snapshot_month"]) is None
