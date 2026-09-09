"""
The independent arithmetic oracle. Brief §6.1.

Every expected number in this file was computed by hand from the brief's own
fixture table and is written out as a literal. Nothing here asks the production
calculator what it thinks the answer is and then asserts that it said it — the
whole point of an oracle is that it was derived somewhere else.

The fixture is DELIBERATELY simplified: exposure INR 100 crore, unchanged
between the dates; one period; unit discount factor; no overlay; no term
structure. Within each scenario the loss is `PD x LGD x EAD`. It validates the
arithmetic, the scenario weighting and the interaction allocation. It does NOT
validate the lifetime model, the staging policy or IFRS 9 compliance, and
nothing in this file should be read as if it did.
"""

from __future__ import annotations

import pytest

from backend.cockpit_v2 import attribution, ecl

EAD = 100.0  # INR crore

OPENING = [
    {"scenario_id": "base", "weight": 0.60, "pd": 0.020, "lgd": 0.30},
    {"scenario_id": "upturn", "weight": 0.20, "pd": 0.010, "lgd": 0.20},
    {"scenario_id": "downturn", "weight": 0.20, "pd": 0.040, "lgd": 0.50},
]
CLOSING = [
    {"scenario_id": "base", "weight": 0.60, "pd": 0.030, "lgd": 0.40},
    {"scenario_id": "upturn", "weight": 0.20, "pd": 0.015, "lgd": 0.30},
    {"scenario_id": "downturn", "weight": 0.20, "pd": 0.060, "lgd": 0.60},
]

# Hand-computed, from the brief's table.
#   base    opening 0.020 * 0.30 * 100 = 0.60   closing 0.030 * 0.40 * 100 = 1.20
#   upturn  opening 0.010 * 0.20 * 100 = 0.20   closing 0.015 * 0.30 * 100 = 0.45
#   downturn opening 0.040 * 0.50 * 100 = 2.00  closing 0.060 * 0.60 * 100 = 3.60
EXPECTED_OPENING_SCENARIO_ECL = {"base": 0.60, "upturn": 0.20, "downturn": 2.00}
EXPECTED_CLOSING_SCENARIO_ECL = {"base": 1.20, "upturn": 0.45, "downturn": 3.60}

#   weighted opening = 0.6*0.60 + 0.2*0.20 + 0.2*2.00 = 0.36 + 0.04 + 0.40 = 0.80
#   weighted closing = 0.6*1.20 + 0.2*0.45 + 0.2*3.60 = 0.72 + 0.09 + 0.72 = 1.53
EXPECTED_WEIGHTED_OPENING = 0.80
EXPECTED_WEIGHTED_CLOSING = 1.53
EXPECTED_NET_CHANGE = 0.73

#   v(none)     = 0.80
#   v({PD})     = closing PD, opening LGD
#                 0.6*(0.030*0.30*100) + 0.2*(0.015*0.20*100) + 0.2*(0.060*0.50*100)
#               = 0.6*0.90 + 0.2*0.30 + 0.2*3.00 = 0.54 + 0.06 + 0.60 = 1.20
#   v({LGD})    = opening PD, closing LGD
#                 0.6*(0.020*0.40*100) + 0.2*(0.010*0.30*100) + 0.2*(0.040*0.60*100)
#               = 0.6*0.80 + 0.2*0.30 + 0.2*2.40 = 0.48 + 0.06 + 0.48 = 1.02
#   v({PD,LGD}) = 1.53
#   phi_PD  = 0.5*(1.20 - 0.80) + 0.5*(1.53 - 1.02) = 0.200 + 0.255 = 0.455
#   phi_LGD = 0.5*(1.02 - 0.80) + 0.5*(1.53 - 1.20) = 0.110 + 0.165 = 0.275
EXPECTED_PD_CONTRIBUTION = 0.455
EXPECTED_LGD_CONTRIBUTION = 0.275
EXPECTED_PD_SHARE = 62.328767123287670  # 0.455 / 0.73 * 100
EXPECTED_LGD_SHARE = 37.671232876712330  # 0.275 / 0.73 * 100

#   weighted PD  = 0.6*0.020 + 0.2*0.010 + 0.2*0.040 = 0.012 + 0.002 + 0.008 = 0.022
#   weighted LGD = 0.6*0.30  + 0.2*0.20  + 0.2*0.50  = 0.18  + 0.04  + 0.10  = 0.32
#   0.022 * 0.32 * 100 = 0.704, which is NOT 0.80.
EXPECTED_WEIGHTED_PD = 0.022
EXPECTED_WEIGHTED_LGD = 0.32
EXPECTED_NAIVE_PRODUCT = 0.704

TOL = 1e-9


def _fixture(parameters, facility_id="ORACLE-1"):
    return ecl.simple_measurement(facility_id=facility_id, ead=EAD,
                                  scenario_parameters=parameters)


def test_opening_scenario_ecls_match_the_hand_computed_values():
    result = ecl.measure(_fixture(OPENING))
    got = {s.scenario_id: s.ecl for s in result.scenarios}
    for name, expected in EXPECTED_OPENING_SCENARIO_ECL.items():
        assert got[name] == pytest.approx(expected, abs=TOL), name


def test_closing_scenario_ecls_match_the_hand_computed_values():
    result = ecl.measure(_fixture(CLOSING))
    got = {s.scenario_id: s.ecl for s in result.scenarios}
    for name, expected in EXPECTED_CLOSING_SCENARIO_ECL.items():
        assert got[name] == pytest.approx(expected, abs=TOL), name


def test_weighted_ecl_at_both_dates():
    assert ecl.measure(_fixture(OPENING)).weighted_model_ecl == pytest.approx(
        EXPECTED_WEIGHTED_OPENING, abs=TOL)
    assert ecl.measure(_fixture(CLOSING)).weighted_model_ecl == pytest.approx(
        EXPECTED_WEIGHTED_CLOSING, abs=TOL)


def test_weighted_parameters_do_not_reproduce_weighted_ecl():
    """Brief §4.3 and question A2.9. The shortcut is wrong and provably so."""
    opening = ecl.measure(_fixture(OPENING))
    assert opening.weighted_twelve_month_pd == pytest.approx(
        EXPECTED_WEIGHTED_PD, abs=TOL)
    assert opening.weighted_lgd == pytest.approx(EXPECTED_WEIGHTED_LGD, abs=TOL)
    assert opening.naive_parameter_product == pytest.approx(
        EXPECTED_NAIVE_PRODUCT, abs=TOL)
    assert opening.naive_parameter_product != pytest.approx(
        opening.weighted_model_ecl, abs=1e-6)


def test_symmetric_two_factor_attribution():
    """PD +0.455 and LGD +0.275, summing exactly to the 0.73 change."""
    found = attribution.decompose_ecl_factors(
        [_fixture(OPENING)], [_fixture(CLOSING)],
        opening_date="2024-09-30", closing_date="2024-12-31",
        groups=(attribution.FACTOR_PD, attribution.FACTOR_LGD))

    assert found.opening_ecl == pytest.approx(EXPECTED_WEIGHTED_OPENING, abs=TOL)
    assert found.closing_ecl == pytest.approx(EXPECTED_WEIGHTED_CLOSING, abs=TOL)
    assert found.net_change == pytest.approx(EXPECTED_NET_CHANGE, abs=TOL)

    pd = found.factor(attribution.FACTOR_PD)
    lgd = found.factor(attribution.FACTOR_LGD)
    assert pd.contribution == pytest.approx(EXPECTED_PD_CONTRIBUTION, abs=TOL)
    assert lgd.contribution == pytest.approx(EXPECTED_LGD_CONTRIBUTION, abs=TOL)
    assert pd.share_of_net_change == pytest.approx(EXPECTED_PD_SHARE, abs=1e-6)
    assert lgd.share_of_net_change == pytest.approx(EXPECTED_LGD_SHARE, abs=1e-6)


def test_the_bridge_reconciles_exactly():
    found = attribution.decompose_ecl_factors(
        [_fixture(OPENING)], [_fixture(CLOSING)],
        groups=(attribution.FACTOR_PD, attribution.FACTOR_LGD))
    assert found.reconciled is True
    assert found.residual == pytest.approx(0.0, abs=1e-12)
    total = (sum(f.contribution for f in found.factors)
             + sum(s.amount for s in found.structural))
    assert total == pytest.approx(found.net_change, abs=1e-12)


def test_the_full_six_group_engine_gives_the_same_answer_on_this_fixture():
    """Groups that did not move must contribute exactly zero.

    The fixture changes only PD and LGD, so running the full six-group engine
    over it has to put 0.455 on PD, 0.275 on LGD and nothing anywhere else. A
    factor engine that leaked a few paise onto discounting would still
    reconcile, and would still be wrong.
    """
    found = attribution.decompose_ecl_factors(
        [_fixture(OPENING)], [_fixture(CLOSING)])
    contributions = {f.factor: f.contribution for f in found.factors}
    assert contributions[attribution.FACTOR_PD] == pytest.approx(
        EXPECTED_PD_CONTRIBUTION, abs=TOL)
    assert contributions[attribution.FACTOR_LGD] == pytest.approx(
        EXPECTED_LGD_CONTRIBUTION, abs=TOL)
    for other in (attribution.FACTOR_EAD, attribution.FACTOR_STAGING,
                  attribution.FACTOR_WEIGHTS, attribution.FACTOR_DISCOUNT):
        assert contributions[other] == pytest.approx(0.0, abs=TOL), other
    assert found.reconciled is True


def test_shapley_is_order_independent():
    """The allocation must not depend on the order the groups are listed in."""
    forward = attribution.decompose_ecl_factors(
        [_fixture(OPENING)], [_fixture(CLOSING)],
        groups=(attribution.FACTOR_PD, attribution.FACTOR_LGD))
    reverse = attribution.decompose_ecl_factors(
        [_fixture(OPENING)], [_fixture(CLOSING)],
        groups=(attribution.FACTOR_LGD, attribution.FACTOR_PD))
    assert (forward.factor(attribution.FACTOR_PD).contribution
            == pytest.approx(reverse.factor(attribution.FACTOR_PD).contribution,
                             abs=1e-12))


def test_scenario_weights_must_sum_to_one():
    with pytest.raises(ecl.EclInputError):
        _fixture([
            {"scenario_id": "base", "weight": 0.60, "pd": 0.02, "lgd": 0.30},
            {"scenario_id": "upturn", "weight": 0.20, "pd": 0.01, "lgd": 0.20},
        ])


def test_a_lifetime_pd_is_not_an_annual_pd_times_years():
    """Brief §4.3. Four years at a 2% annual PD is not 8%."""
    hazard = [ecl.annual_pd_to_hazard(0.02)] * 16
    four_years = ecl.cumulative_pd(hazard, 16)
    assert four_years < 0.08
    assert four_years == pytest.approx(1 - 0.98 ** 4, abs=1e-12)
    one_year = ecl.cumulative_pd(hazard, 4)
    assert one_year == pytest.approx(0.02, abs=1e-12)
