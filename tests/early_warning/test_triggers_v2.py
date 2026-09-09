"""The Version 2 trigger inventory: 67 dynamic triggers, Tab 3 Section A."""

from __future__ import annotations

import pytest

from backend.early_warning.triggers_v2 import (
    SEVERITY_SCORE,
    TRIGGER_DEFINITIONS,
    trigger_score_for_band,
)


def test_sixty_seven_triggers_with_unique_keys():
    assert len(TRIGGER_DEFINITIONS) == 67
    assert len({t.key for t in TRIGGER_DEFINITIONS}) == 67


def test_every_trigger_has_five_severity_bands():
    for t in TRIGGER_DEFINITIONS:
        assert [b.band for b in t.bands] == [1, 2, 3, 4, 5]
        assert [b.score for b in t.bands] == [20, 40, 60, 80, 100]


def test_trigger_score_formula():
    assert trigger_score_for_band(1) == 20
    assert trigger_score_for_band(2) == 40
    assert trigger_score_for_band(3) == 60
    assert trigger_score_for_band(4) == 80
    assert trigger_score_for_band(5) == 100
    assert SEVERITY_SCORE == {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}


def test_invalid_band_rejected():
    with pytest.raises(ValueError):
        trigger_score_for_band(6)
    with pytest.raises(ValueError):
        trigger_score_for_band(0)


def test_layers_covered():
    layers = {t.layer for t in TRIGGER_DEFINITIONS}
    assert layers == {"L1", "L2", "L3", "L4"}
    counts = {l: sum(1 for t in TRIGGER_DEFINITIONS if t.layer == l) for l in layers}
    assert counts == {"L1": 19, "L2": 7, "L3": 28, "L4": 13}


def test_sanctions_and_cross_default_triggers_present():
    assert "sanctions_listing_or_match" in {t.key for t in TRIGGER_DEFINITIONS}
    assert "cross_default_relationship_triggered" in {t.key for t in TRIGGER_DEFINITIONS}
