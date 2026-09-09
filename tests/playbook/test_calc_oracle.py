"""The deterministic calculator and the ECL oracle. PB-014, PB-027.

These tests are the independent oracle the specification asks for: they assert
the arithmetic directly, without a model anywhere near them, so a generated
document can be checked against something that did not come from the same place
the document did.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.playbook import calc
from backend.playbook.calc import CalculationError, Input
from backend.playbook.fixtures import ecl_oracle as oracle


def _pct(name: str, value: str) -> Input:
    return Input(name=name, value=Decimal(value), unit=calc.PERCENT)


def _money(name: str, value: str) -> Input:
    return Input(name=name, value=Decimal(value), unit=calc.CURRENCY, scale="million")


class TestTheOracleReproducesTheSpecifiedFigures:
    """§14 states six inputs and several derived values. The derived ones must
    fall out of the inputs rather than being typed in beside them."""

    def test_weighted_ecl_prior_is_20_90(self):
        assert oracle.weighted_ecl("prior").rounded == Decimal("20.90")

    def test_weighted_ecl_current_is_22_77(self):
        assert oracle.weighted_ecl("current").rounded == Decimal("22.77")

    def test_movement_is_plus_1_87(self):
        assert oracle.weighted_ecl_movement().rounded == Decimal("1.87")

    def test_percent_change_is_about_plus_8_95(self):
        assert oracle.weighted_ecl_percent_change().rounded == Decimal("8.95")

    def test_coverage_ratios_carry_their_denominator(self):
        cov = oracle.coverage_ratio("current")
        assert cov.rounded == Decimal("2.17")
        assert "exposure" in cov.denominator

    def test_coverage_movement_is_basis_points_not_percent(self):
        mv = oracle.coverage_movement_bps()
        assert mv.unit == calc.BASIS_POINT
        assert mv.rounded == Decimal("7.9")

    def test_no_derived_figure_is_declared_as_a_constant(self):
        """The fixture may declare only the six inputs §14 states."""
        assert set(oracle.DECLARED) == {
            "exposure", "base_ecl", "upturn_ecl", "downturn_ecl",
        }

    def test_scenario_ordering_is_economically_coherent(self):
        for period in ("prior", "current"):
            assert oracle.scenario_ordering_is_coherent(period)

    def test_every_headline_figure_records_its_inputs(self):
        for name, c in oracle.headline().items():
            assert c.inputs, f"{name} has no recorded inputs"
            assert c.formula, f"{name} has no formula"


class TestWeightsMustBeComplete:
    def test_weights_that_do_not_sum_to_one_are_refused(self):
        comps = [_money("a", "10"), _money("b", "20")]
        weights = [
            Input(name="wa", value=Decimal("0.6"), unit=calc.RATIO),
            Input(name="wb", value=Decimal("0.3"), unit=calc.RATIO),
        ]
        with pytest.raises(CalculationError, match="sum to"):
            calc.weighted(comps, weights, name="x")

    def test_the_oracle_weights_do_sum_to_one(self):
        total = sum(Decimal(v) for v in oracle.WEIGHTS.values())
        assert total == Decimal("1.00")


class TestUnitsDoNotSilentlyConvert:
    """The unit slips that make a credit report wrong without looking wrong."""

    def test_percentage_point_change_is_not_percent_change(self):
        prior, current = _pct("cov prior", "2.09"), _pct("cov current", "2.17")
        pp = calc.pp_change(prior, current, name="pp")
        pc = calc.percent_change(prior, current, name="pc")
        assert pp.unit == calc.PERCENTAGE_POINT
        assert pc.unit == calc.PERCENT
        assert pp.rounded != pc.rounded

    def test_basis_points_are_a_hundred_times_percentage_points(self):
        prior, current = _pct("a", "2.09"), _pct("b", "2.17")
        pp = calc.pp_change(prior, current, name="pp", dp=4)
        bps = calc.bps_change(prior, current, name="bps", dp=4)
        assert bps.value == pp.value * 100

    def test_a_percentage_point_change_needs_two_percentages(self):
        with pytest.raises(CalculationError, match="only"):
            calc.pp_change(_money("a", "1"), _money("b", "2"), name="x")

    def test_mixed_units_cannot_be_subtracted(self):
        with pytest.raises(CalculationError, match="different units"):
            calc.delta(_money("a", "1"), _pct("b", "2"), name="x")

    def test_mixed_scales_cannot_be_subtracted(self):
        thousand = Input(name="a", value=Decimal("1"), unit=calc.CURRENCY, scale="thousand")
        million = _money("b", "1")
        with pytest.raises(CalculationError, match="scale"):
            calc.delta(thousand, million, name="x")


class TestUntrustworthyValuesAreRefused:
    def test_a_formula_string_is_not_a_result(self):
        with pytest.raises(CalculationError, match="formula string"):
            calc.dec("=B4*C4")

    def test_a_non_numeric_cell_is_refused_rather_than_zeroed(self):
        with pytest.raises(CalculationError):
            calc.dec("n/a")

    def test_a_boolean_is_not_a_figure(self):
        with pytest.raises(CalculationError):
            calc.dec(True)

    def test_a_float_keeps_its_shortest_form(self):
        assert calc.dec(19.2) == Decimal("19.2")

    def test_thousands_separators_are_read(self):
        assert calc.dec("1,050.00") == Decimal("1050.00")

    def test_percentage_change_from_zero_is_refused(self):
        with pytest.raises(CalculationError, match="zero"):
            calc.percent_change(_money("a", "0"), _money("b", "5"), name="x")

    def test_division_by_zero_is_refused(self):
        with pytest.raises(CalculationError, match="zero"):
            calc.ratio(_money("a", "5"), _money("b", "0"), name="x")


class TestCalculationsPersistWithoutFloatDrift:
    def test_values_serialise_as_strings(self):
        d = oracle.weighted_ecl("current").as_dict()
        assert d["value"] == "22.7700"
        assert d["rounded"] == "22.77"
        assert isinstance(d["value"], str)

    def test_inputs_carry_locators(self):
        d = oracle.weighted_ecl("current").as_dict()
        assert all(i["locator"] for i in d["inputs"])
