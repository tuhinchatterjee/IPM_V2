"""Tab 3 Section D: causal-chain dedup, then the rank-weighted breadth
aggregation. The worked example reproduced here is the workbook's own —
nine signals in six causal chains, T&A score 62.217775.
"""

from __future__ import annotations

from backend.early_warning.aggregation import (
    FiredSignal,
    aggregate_ta_score,
    dedupe_causal_chains,
    ta_verdict_band,
)

_WORKED_EXAMPLE_SIGNALS = (
    FiredSignal("dep_decline", 46.0, "chain1"),
    FiredSignal("acct_credits", 37.26, "chain1"),
    FiredSignal("util_increase", 44.2, "chain2"),
    FiredSignal("sustained_util", 43.4, "chain2"),
    FiredSignal("repay_delay", 20.0, "chain3"),
    FiredSignal("contract_loss", 29.25, "chain4"),
    FiredSignal("adverse_results", 14.325, "chain4"),
    FiredSignal("supplier_distress_net", 38.4, "chain5"),
    FiredSignal("guarantor_deterioration_net", 55.0, "chain6"),
)


def test_causal_chain_dedup_keeps_only_the_strongest_per_chain():
    effective = dedupe_causal_chains(_WORKED_EXAMPLE_SIGNALS)
    by_key = {e.signal_key: e for e in effective}
    assert by_key["dep_decline"].effective_score == 46.0
    assert by_key["acct_credits"].effective_score == 0.0  # same chain, weaker
    assert by_key["util_increase"].effective_score == 44.2
    assert by_key["sustained_util"].effective_score == 0.0


def test_worked_example_breadth_and_ta_score():
    result = aggregate_ta_score(_WORKED_EXAMPLE_SIGNALS)
    assert abs(result.breadth_index - 0.267325) < 1e-6
    assert abs(result.ta_score - 62.217775) < 1e-4
    assert result.dominant_driver == "guarantor_deterioration_net"


def test_ta_verdict_band_scale():
    assert ta_verdict_band(19.9) == "VERY_LOW"
    assert ta_verdict_band(62.217775) == "HIGH"
    assert ta_verdict_band(85) == "VERY_HIGH"


def test_no_fired_signals_gives_zero():
    result = aggregate_ta_score(())
    assert result.ta_score == 0.0
    assert result.dominant_driver is None


def test_single_signal_is_its_own_score():
    result = aggregate_ta_score((FiredSignal("only", 60.0, "c1"),))
    assert result.ta_score == 60.0


def test_confirmed_sanctions_override_sets_ta_to_100():
    result = aggregate_ta_score(_WORKED_EXAMPLE_SIGNALS, confirmed_sanctions_match=True)
    assert result.ta_score == 100.0
    assert result.override_applied == "confirmed_sanctions_match"


def test_cross_default_override_sets_ta_to_100():
    result = aggregate_ta_score((), cross_default_acceleration_served=True)
    assert result.ta_score == 100.0
