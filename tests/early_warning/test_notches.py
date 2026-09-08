"""The five post-anchor notch modifiers, Tab 06 Section E: each -1/0/+1,
net capped at +/-2, 8 points per notch.
"""

from __future__ import annotations

import pytest

from backend.early_warning.notches import NOTCH_KEYS, NET_NOTCH_CAP, POINTS_PER_NOTCH, apply_notches


def test_five_notch_keys():
    assert NOTCH_KEYS == (
        "network_contagion", "direction_of_travel", "evidence_quality",
        "data_staleness", "management_and_governance",
    )


def test_rawabi_two_negative_notches():
    result = apply_notches(72, {"network_contagion": -1, "direction_of_travel": -1})
    assert result.net_notches_raw == -2
    assert result.net_notches_capped == -2
    assert result.final_before_caps == 56.0


def test_net_capped_at_plus_two_even_with_five_positive_notches():
    result = apply_notches(50, {k: 1 for k in NOTCH_KEYS})
    assert result.net_notches_raw == 5
    assert result.net_notches_capped == NET_NOTCH_CAP
    assert result.final_before_caps == 50 + POINTS_PER_NOTCH * 2


def test_net_capped_at_minus_two_even_with_five_negative_notches():
    result = apply_notches(50, {k: -1 for k in NOTCH_KEYS})
    assert result.net_notches_capped == -NET_NOTCH_CAP
    assert result.final_before_caps == 50 - POINTS_PER_NOTCH * 2


def test_clamped_to_zero_and_hundred():
    assert apply_notches(5, {"network_contagion": -1, "direction_of_travel": -1}).final_before_caps == 0.0
    assert apply_notches(95, {"network_contagion": 1, "direction_of_travel": 1}).final_before_caps == 100.0


def test_missing_notches_default_to_zero():
    result = apply_notches(50, {})
    assert result.net_notches_raw == 0
    assert result.final_before_caps == 50.0


def test_invalid_notch_key_rejected():
    with pytest.raises(ValueError):
        apply_notches(50, {"not_a_notch": 1})


def test_invalid_notch_value_rejected():
    with pytest.raises(ValueError):
        apply_notches(50, {"network_contagion": 2})


def test_reasons_recorded_for_every_notch():
    result = apply_notches(50, {"network_contagion": 1})
    assert result.reasons["network_contagion"] == (
        "A connected party is in confirmed distress and the dependency is material")
    assert result.reasons["direction_of_travel"] == "Flat"
