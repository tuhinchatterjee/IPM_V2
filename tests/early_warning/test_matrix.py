"""The published 5x5 anchor matrix, Tab 06 Section D, transcribed verbatim."""

from __future__ import annotations

import pytest

from backend.early_warning.matrix import anchor


def test_full_matrix_verbatim():
    expected = {
        ("VERY_LOW", "VERY_LOW"): 5, ("VERY_LOW", "LOW"): 8, ("VERY_LOW", "MEDIUM"): 12,
        ("VERY_LOW", "HIGH"): 16, ("VERY_LOW", "VERY_HIGH"): 22,
        ("LOW", "VERY_LOW"): 15, ("LOW", "LOW"): 20, ("LOW", "MEDIUM"): 26,
        ("LOW", "HIGH"): 33, ("LOW", "VERY_HIGH"): 40,
        ("MEDIUM", "VERY_LOW"): 28, ("MEDIUM", "LOW"): 35, ("MEDIUM", "MEDIUM"): 43,
        ("MEDIUM", "HIGH"): 52, ("MEDIUM", "VERY_HIGH"): 60,
        ("HIGH", "VERY_LOW"): 45, ("HIGH", "LOW"): 54, ("HIGH", "MEDIUM"): 63,
        ("HIGH", "HIGH"): 72, ("HIGH", "VERY_HIGH"): 80,
        ("VERY_HIGH", "VERY_LOW"): 65, ("VERY_HIGH", "LOW"): 74, ("VERY_HIGH", "MEDIUM"): 83,
        ("VERY_HIGH", "HIGH"): 90, ("VERY_HIGH", "VERY_HIGH"): 95,
    }
    for (ta_band, c_band), value in expected.items():
        assert anchor(ta_band, c_band) == value, (ta_band, c_band)


def test_rawabi_anchor_is_72():
    assert anchor("HIGH", "HIGH") == 72


def test_no_signal_no_alert_reading():
    """"An obligor with no live signal is not an alert" — the VERY_LOW T&A
    row tops out at 22, well short of any alert band."""
    assert anchor("VERY_LOW", "VERY_HIGH") == 22


def test_very_high_ta_is_always_an_alert():
    """"one with a very high T&A score is an alert regardless" — the
    VERY_HIGH T&A row starts at 65."""
    assert anchor("VERY_HIGH", "VERY_LOW") == 65


def test_unknown_band_raises():
    with pytest.raises(ValueError):
        anchor("NOT_A_BAND", "HIGH")
    with pytest.raises(ValueError):
        anchor("HIGH", "NOT_A_BAND")
