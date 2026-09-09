"""
The factor attribution engine, on real generated data. Brief §5.4.

The oracle in `test_ecl_oracle.py` checks the arithmetic against hand-computed
literals. This file checks the properties that have to hold on every book: the
bridge reconciles, the allocation is order-independent, the exact reduction
agrees with the unreduced computation, and a factor that did not move gets
exactly nothing.
"""

from __future__ import annotations

import pytest

from backend.cockpit_v2 import attribution as attr
from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import ecl as ecl_mod
from backend.cockpit_v2 import generate as generate_mod


@pytest.fixture(scope="module")
def pilot():
    return generate_mod.build_demo(publish=list(cal.PILOT_QUARTERS),
                                   borrowers=12, facilities_target=22)


@pytest.fixture(scope="module")
def bridge(pilot):
    opening, closing = pilot.published
    return attr.decompose_ecl_factors(
        list(pilot.measurements[opening].values()),
        list(pilot.measurements[closing].values()),
        opening_date=cal.iso(opening), closing_date=cal.iso(closing))


def test_the_bridge_reconciles_on_generated_data(bridge):
    total = (sum(f.contribution for f in bridge.factors)
             + sum(s.amount for s in bridge.structural))
    assert total == pytest.approx(bridge.net_change, abs=1e-9)
    assert bridge.reconciled is True
    assert abs(bridge.residual) < ecl_mod.RECONCILIATION_TOLERANCE


def test_there_is_no_unexplained_plug(bridge):
    """Every line is named. Nothing is called 'other'."""
    names = ({f.factor for f in bridge.factors}
             | {s.line for s in bridge.structural})
    assert "other" not in names
    assert "unexplained" not in names
    assert set(attr.FACTOR_GROUPS) <= names


def test_the_factor_groups_do_not_overlap(bridge):
    """Six groups, each meaning one thing, listed once."""
    factors = [f.factor for f in bridge.factors]
    assert len(factors) == len(set(factors))
    assert set(factors) == set(attr.FACTOR_GROUPS)


def test_shares_sum_to_one_hundred_percent(bridge):
    shares = [f.share_of_net_change for f in bridge.factors
              if f.share_of_net_change is not None]
    structural = [s.amount / bridge.net_change * 100.0
                  for s in bridge.structural]
    assert sum(shares) + sum(structural) == pytest.approx(100.0, abs=1e-6)


def test_the_exact_reduction_agrees_with_the_unreduced_computation(pilot):
    """Skipping unmoved groups must change nothing but the time it takes.

    The engine evaluates only the factor groups whose inputs actually differ
    between the two dates. That is exact — an unmoved group has a zero marginal
    contribution in every coalition — but "exact" is a claim, so it is checked
    here against a Shapley computed over all six groups for every facility.
    """
    opening, closing = pilot.published
    reduced = attr.decompose_ecl_factors(
        list(pilot.measurements[opening].values()),
        list(pilot.measurements[closing].values()))

    unreduced: dict[str, float] = {g: 0.0 for g in attr.FACTOR_GROUPS}
    for facility_id, open_m in pilot.measurements[opening].items():
        close_m = pilot.measurements[closing].get(facility_id)
        if close_m is None or open_m.method != close_m.method:
            continue

        def value(subset, _o=open_m, _c=close_m):
            return ecl_mod.measure(
                attr._switched(_o, _c, subset)).weighted_model_ecl

        for group, amount in attr.shapley_contributions(
                value, attr.FACTOR_GROUPS).items():
            unreduced[group] += amount

    for factor in reduced.factors:
        assert factor.contribution == pytest.approx(
            unreduced[factor.factor], abs=1e-9), factor.factor


def test_a_factor_that_did_not_move_contributes_exactly_zero(pilot):
    """The scenario-weight story's borrower is the clean case.

    Its PD, LGD, EAD and discounting are held at a reference quarter, so only
    the weights differ between the two dates and every other group must be
    exactly nought — not nearly nought.
    """
    opening, closing = pilot.published
    borrower = next((b for b, s in pilot.assignments.items()
                     if s == "STORY_WEIGHTS_ONLY"), "")
    assert borrower, "the pilot must carry the scenario-weight story"

    o = [m for k, m in pilot.measurements[opening].items()
         if k.startswith(borrower + "-")]
    c = [m for k, m in pilot.measurements[closing].items()
         if k.startswith(borrower + "-")]
    found = attr.decompose_ecl_factors(o, c)

    contributions = {f.factor: f.contribution for f in found.factors}
    assert contributions[attr.FACTOR_PD] == 0.0
    assert contributions[attr.FACTOR_LGD] == 0.0
    assert contributions[attr.FACTOR_WEIGHTS] != 0.0
    assert found.reconciled is True


def test_entry_and_exit_are_not_attributed_to_a_parameter(bridge):
    entry = next(s for s in bridge.structural if s.line == attr.LINE_ENTRY)
    exited = next(s for s in bridge.structural if s.line == attr.LINE_EXIT)
    assert entry.accounts == bridge.entered_accounts
    assert exited.accounts == bridge.exited_accounts
    if bridge.entered_accounts:
        assert entry.amount > 0
    if bridge.exited_accounts:
        assert exited.amount < 0


def test_a_zero_net_change_withholds_shares_rather_than_dividing():
    """Brief §5.1. Do not divide into meaningless contribution percentages."""
    fixture = ecl_mod.simple_measurement(
        facility_id="F1", ead=100.0,
        scenario_parameters=[{"scenario_id": "base", "weight": 1.0,
                              "pd": 0.02, "lgd": 0.30}])
    found = attr.decompose_ecl_factors([fixture], [fixture])
    assert found.net_change == pytest.approx(0.0, abs=1e-12)
    assert found.shares_available is False
    assert all(f.share_of_net_change is None for f in found.factors)
    assert any("effectively zero" in limitation
               for limitation in found.limitations)


def test_a_method_change_is_reported_rather_than_attributed():
    """A performing account that becomes credit-impaired is not a PD move."""
    performing = ecl_mod.performing_measurement(
        facility_id="F1", borrower_id="B1", reporting_date="2026-03-31",
        stage=1, remaining_periods=12, effective_rate=0.08,
        scenario_parameters=[{"scenario_id": "base", "weight": 1.0,
                              "twelve_month_pd": 0.02, "lgd": 0.4,
                              "ead": 100.0}])
    impaired = ecl_mod.impaired_measurement(
        facility_id="F1", borrower_id="B1", reporting_date="2026-06-30",
        gross_carrying_amount=100.0, effective_rate=0.08,
        scenario_parameters=[{"scenario_id": "base", "weight": 1.0,
                              "recovery_rate": 0.4,
                              "recovery_lag_years": 2.0}])
    found = attr.decompose_ecl_factors([performing], [impaired])

    method = next(s for s in found.structural if s.line == attr.LINE_METHOD)
    assert method.accounts == 1
    assert method.amount != 0.0
    assert all(f.contribution == 0.0 for f in found.factors)
    assert found.reconciled is True
    assert any("measurement method" in limitation
               for limitation in found.limitations)


def test_a_forward_sensitivity_is_not_a_historical_attribution():
    base = ecl_mod.simple_measurement(
        facility_id="F1", ead=100.0,
        scenario_parameters=[{"scenario_id": "base", "weight": 1.0,
                              "pd": 0.02, "lgd": 0.30}])
    shocked = ecl_mod.simple_measurement(
        facility_id="F1", ead=100.0,
        scenario_parameters=[{"scenario_id": "base", "weight": 1.0,
                              "pd": 0.04, "lgd": 0.30}])
    found = attr.forward_sensitivity(base, factor=attr.FACTOR_PD,
                                     shocked=shocked)
    assert found["is_historical_attribution"] is False
    assert found["kind"] == "forward_hypothetical_sensitivity"
    assert found["difference"] == pytest.approx(0.6, abs=1e-9)


def test_the_decomposition_declares_it_is_not_causation(bridge):
    payload = bridge.to_dict()
    assert "not evidence of a real-world cause" in \
        payload["attribution_is_not_causation"]
