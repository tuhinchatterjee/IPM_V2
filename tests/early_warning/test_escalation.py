"""The escalation ladder, specialist routes, and severity/materiality
routing (implementation plan Section 12)."""

from __future__ import annotations

from backend.early_warning import escalation as esc


def test_six_level_ladder_l0_to_l5():
    assert [rung["level"] for rung in esc.LADDER] == ["L0", "L1", "L2", "L3", "L4", "L5"]


def test_five_specialist_routes():
    assert [route["code"] for route in esc.SPECIALIST_ROUTES] == ["S1", "S2", "S3", "S4", "S5"]


def test_exposure_tier_boundaries():
    assert esc.exposure_tier(10) == "<50m"
    assert esc.exposure_tier(49.9) == "<50m"
    assert esc.exposure_tier(50) == "50-150m"
    assert esc.exposure_tier(149.9) == "50-150m"
    assert esc.exposure_tier(150) == "150-400m"
    assert esc.exposure_tier(399.9) == "150-400m"
    assert esc.exposure_tier(400) == ">400m"
    assert esc.exposure_tier(10_000) == ">400m"


def test_severity_decides_urgency_materiality_decides_altitude():
    """Same severity, larger exposure -> higher escalation level."""
    small = esc.route_for("VERY_HIGH", 10)
    large = esc.route_for("VERY_HIGH", 500)
    assert small["escalated_to"] == ["L2", "S3"]
    assert large["escalated_to"] == ["L4", "L5"]
    assert small["decision_sla_days"] == large["decision_sla_days"] == 5


def test_very_low_severity_has_no_escalation_regardless_of_exposure():
    for tier_exposure in (10, 100, 300, 1000):
        route = esc.route_for("VERY_LOW", tier_exposure)
        assert route["escalated_to"] == []


def test_low_severity_still_escalates_at_very_high_exposure():
    """A large enough exposure escalates even a low-severity finding —
    materiality still matters at the bottom of the severity scale."""
    route = esc.route_for("LOW", 500)
    assert route["escalated_to"] == ["L1"]


def test_default_bundle_shape():
    bundle = esc.default_bundle()
    assert set(bundle.keys()) == {"ladder", "specialist_routes", "exposure_tiers", "routing_matrix"}
    assert len(bundle["exposure_tiers"]) == 4
