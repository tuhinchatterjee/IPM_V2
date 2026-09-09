"""Tab 4b: Layer 4 propagation. All six of Section D's worked rows are
reproduced exactly, plus the portfolio-contagion weighting from Section F.
"""

from __future__ import annotations

from backend.early_warning.network import (
    MIN_EDGE_CONFIDENCE_BAND,
    PropagationInput,
    portfolio_weighted_exposure,
    propagate,
)


def test_al_faris_trading_upstream_one_hop():
    r = propagate(PropagationInput(80, "upstream", 1, 4, 3, 1))
    assert abs(r.dependency_weight - 0.8) < 1e-9
    assert abs(r.transmission_factor - 0.6) < 1e-9
    assert abs(r.propagated_score - 38.4) < 1e-6
    assert r.scored


def test_tier2_resin_producer_upstream_two_hops():
    r = propagate(PropagationInput(90, "upstream", 2, 2, 5, 3))
    assert abs(r.dependency_weight - 0.455) < 1e-9
    assert abs(r.transmission_factor - 0.2475) < 1e-9
    assert abs(r.propagated_score - 10.135125) < 1e-6


def test_gulf_contracting_downstream_one_hop():
    r = propagate(PropagationInput(70, "downstream", 1, 3, 2, 2))
    assert abs(r.dependency_weight - 0.45) < 1e-9
    assert abs(r.transmission_factor - 0.765) < 1e-9
    assert abs(r.propagated_score - 24.0975) < 1e-6


def test_offtaker_downstream_two_hops_scored_flag_false_at_band4():
    r = propagate(PropagationInput(85, "downstream", 2, 1, 3, 4))
    assert abs(r.dependency_weight - 0.15) < 1e-9
    assert abs(r.transmission_factor - 0.257125) < 1e-6
    assert abs(r.propagated_score - 3.27834375) < 1e-6
    # workbook's own worked example still computes this row's arithmetic,
    # but Section G's governance policy (band 3 or better) flags it unscored
    assert r.scored is False
    assert 4 > MIN_EDGE_CONFIDENCE_BAND


def test_parent_holding_company_ownership():
    r = propagate(PropagationInput(60, "ownership", 1, 4, 3, 1))
    assert abs(r.dependency_weight - 0.8) < 1e-9
    assert abs(r.transmission_factor - 0.9) < 1e-9
    assert abs(r.propagated_score - 43.2) < 1e-6


def test_guarantor_credit_support_full_transmission():
    r = propagate(PropagationInput(55, "credit_support", 1, 5, 3, 1))
    assert abs(r.dependency_weight - 1.0) < 1e-9
    assert abs(r.transmission_factor - 1.0) < 1e-9
    assert abs(r.propagated_score - 55.0) < 1e-6


def test_propagated_score_never_exceeds_counterparty_score():
    r = propagate(PropagationInput(counterparty_score=40, relationship_type="credit_support",
                                    hops=1, dependency_share_band=5, substitutability_band=5,
                                    edge_confidence_band=1))
    assert r.propagated_score <= 40


def test_hop_decay_zero_beyond_three_hops():
    r = propagate(PropagationInput(80, "upstream", 4, 5, 5, 1))
    assert r.propagated_score == 0.0


def test_portfolio_weighted_exposure_worked_examples():
    assert abs(portfolio_weighted_exposure(120, 38.4) - 46.08) < 1e-6
    assert abs(portfolio_weighted_exposure(85, 44.6) - 37.91) < 1e-6
    assert abs(portfolio_weighted_exposure(45, 24.8) - 11.16) < 1e-6
    assert abs(portfolio_weighted_exposure(30, 20.8) - 6.24) < 1e-6
