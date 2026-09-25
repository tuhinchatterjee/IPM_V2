""""Increase PD by 20" is four different instructions, and they differ by 10x.

UNIT. No database, no model, no provider call.

Section 5.1 of the What-If specification is a list of pairs a reader writes
almost identically and that produce different books. Oracle O06 pins three of
them on one starting value:

    PD 2% increased by 20 basis points  ->  2.2%   not 22% and not 2.02%
    PD 2% increased by 20% relative     ->  2.4%
    PD 2% set to 20%                    ->  20%

Every expected value in this file is written as a literal that was computed by
hand from the specification, never by calling the function under test. Section
17.1: "A test that calls the same defective function to obtain both actual and
expected values is not evidence."
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4.scenario import units as un


def D(text: str) -> Decimal:
    return Decimal(text)


# ---- O06: the three readings of "20" -----------------------------------

#: PD as the Corporate book stores it: a fraction, 2% = 0.02.
PD = D("0.02")


def test_o06_twenty_basis_points_is_not_twenty_percent() -> None:
    """2% + 20bp = 2.2%. The failure this catches reads 20bp as 20%."""
    moved = un.apply(PD, un.parse("20", un.BASIS_POINTS), storage=un.FRACTION)
    assert moved == D("0.022")
    assert moved != D("0.22"), "read as a relative percent"
    assert moved != D("0.0202"), "read as 20 basis points of the VALUE"


def test_o06_twenty_percent_relative_is_a_multiplication() -> None:
    """2% x 1.20 = 2.4%."""
    moved = un.apply(PD, un.parse("20", un.RELATIVE), storage=un.FRACTION)
    assert moved == D("0.024")


def test_o06_set_to_twenty_percent_is_a_replacement() -> None:
    """A third, much larger, result from the same digits."""
    moved = un.apply(PD, un.parse("20", un.SET_TO), storage=un.FRACTION)
    assert moved == D("0.2")


def test_o06_the_three_readings_are_all_different() -> None:
    results = {
        op: un.apply(PD, un.parse("20", op), storage=un.FRACTION)
        for op in (un.BASIS_POINTS, un.RELATIVE, un.SET_TO, un.ABSOLUTE_PP)
    }
    assert len(set(results.values())) == 4, results
    # And the one section 5.1 calls out separately.
    assert results[un.ABSOLUTE_PP] == D("0.22"), "2% + 20pp = 22%"


# ---- the storage bridge, which is where a plausible bug lives ----------

def test_a_percentage_point_means_the_same_in_both_conventions() -> None:
    """LGD +10pp: the book stores LGD as a percent and PD as a fraction.

    A helper that did not know which would add 10 to one column and 0.10 to
    the other and be wrong half the time.
    """
    ten_pp = un.parse("10", un.ABSOLUTE_PP)
    assert un.apply(D("40"), ten_pp, storage=un.PERCENT) == D("50")
    assert un.apply(D("0.40"), ten_pp, storage=un.FRACTION) == D("0.50")


def test_relative_is_storage_independent() -> None:
    """A relative move is a multiplication and needs no conversion."""
    twenty = un.parse("20", un.RELATIVE)
    assert un.apply(D("40"), twenty, storage=un.PERCENT) == D("48")
    assert un.apply(D("0.40"), twenty, storage=un.FRACTION) == D("0.48")


def test_set_to_names_the_value_in_the_fields_display_unit() -> None:
    """"Set LGD to 50%" is fifty on a percent column, 0.50 on a fraction."""
    fifty = un.parse("50", un.SET_TO)
    assert un.apply(D("40"), fifty, storage=un.PERCENT) == D("50")
    assert un.apply(D("0.40"), fifty, storage=un.FRACTION) == D("0.50")


def test_increase_to_and_increase_by_never_normalise_together() -> None:
    """Section 5.1 names this pair explicitly."""
    to_fifty = un.apply(D("40"), un.parse("50", un.SET_TO), storage=un.PERCENT)
    by_fifty = un.apply(D("40"), un.parse("50", un.RELATIVE),
                        storage=un.PERCENT)
    assert to_fifty == D("50")
    assert by_fifty == D("60")
    assert to_fifty != by_fifty


# ---- what a field will not accept --------------------------------------

@pytest.mark.parametrize("storage,operation", [
    (un.MONEY, un.ABSOLUTE_PP),
    (un.MONEY, un.BASIS_POINTS),
    (un.INDEX, un.BASIS_POINTS),
    (un.INDEX, un.ABSOLUTE_PP),
    (un.FRACTION, un.POINTS),
    (un.FRACTION, un.NOTCHES),
    (un.ORDINAL, un.RELATIVE),
    (un.PERCENT, un.ABSOLUTE_AMOUNT),
])
def test_a_category_error_is_refused_not_coerced(storage, operation) -> None:
    """A percentage-point move on a currency column means nothing."""
    with pytest.raises(un.UnitError) as caught:
        un.apply(D("100"), un.parse("5", operation), storage=storage)
    assert storage in str(caught.value)


def test_score_points_are_not_a_percentage() -> None:
    """Section 5.1: "Reduce the score by 50 points" is not 50%."""
    score = D("700")
    by_points = un.apply(score, un.parse("-50", un.POINTS), storage=un.INDEX)
    by_percent = un.apply(score, un.parse("-50", un.RELATIVE),
                          storage=un.INDEX)
    assert by_points == D("650")
    assert by_percent == D("350")


def test_half_a_notch_is_not_a_move() -> None:
    with pytest.raises(un.UnitError, match="half-notch"):
        un.parse("1.5", un.NOTCHES)


def test_a_float_is_refused_rather_than_converted() -> None:
    """Decimal(0.1) is not one tenth, and a tolerance loose enough to absorb
    that is loose enough to absorb a real error."""
    with pytest.raises(un.UnitError, match="float"):
        un.parse(0.1, un.RELATIVE)
    assert un.parse("0.1", un.RELATIVE).value == D("0.1")


def test_an_unknown_operation_is_refused() -> None:
    with pytest.raises(un.UnitError, match="not an operation"):
        un.Amount(value=D("1"), operation="increase_a_bit")


# ---- zero, which is where Delta stops ----------------------------------

def test_o11_zero_to_positive_has_no_ratio() -> None:
    """Oracle O11. Z's PD moves 0% -> 1% and proportional Delta cannot
    express it. None, not an epsilon denominator."""
    assert un.factor(D("0"), D("0.01")) is None


def test_zero_to_zero_is_neutral() -> None:
    """Nothing moved, so the factor is one -- not undefined."""
    assert un.factor(D("0"), D("0")) == D("1")


def test_an_ordinary_ratio_is_exact() -> None:
    assert un.factor(D("0.02"), D("0.024")) == D("1.2")


# ---- the three values a reader must see --------------------------------

def test_three_values_shows_relative_and_percentage_point_together() -> None:
    """Section 5.1 on "reduce unemployment by 10%": 6.0% becomes 5.4%, a
    change of -0.6 percentage points. Display all three."""
    shown = un.three_values(D("6.0"), un.parse("-10", un.RELATIVE),
                            storage=un.PERCENT)
    assert shown["baseline"] == "6"
    assert shown["scenario"] == "5.4"
    assert shown["change_percentage_points"] == "-0.6"
    assert shown["change_relative_pct"] == "-10"


def test_three_values_says_when_a_relative_change_is_not_defined() -> None:
    shown = un.three_values(D("0"), un.parse("5", un.ABSOLUTE_PP),
                            storage=un.FRACTION)
    assert shown["change_relative_pct"] == "not defined from a zero baseline"


def test_the_operation_describes_itself_for_the_audit_record() -> None:
    assert (un.parse("20", un.RELATIVE).describe()
            == "20% relative to baseline")
    assert (un.parse("-20", un.BASIS_POINTS).describe()
            == "-20 basis points")
    assert un.parse("2", un.MULTIPLY).describe() == "multiplied by 2"


# ---- properties --------------------------------------------------------

@pytest.mark.parametrize("storage,baseline", [
    (un.FRACTION, "0.03"), (un.PERCENT, "45"), (un.MONEY, "1000"),
    (un.INDEX, "700"),
])
def test_a_zero_shock_moves_nothing(storage, baseline) -> None:
    """The property every method's O09 depends on."""
    start = D(baseline)
    for operation in sorted(un.ALLOWED[storage]):
        if operation == un.SET_TO:
            continue
        neutral = "1" if operation == un.MULTIPLY else "0"
        assert un.apply(start, un.parse(neutral, operation),
                        storage=storage) == start, operation


@pytest.mark.parametrize("storage", [un.FRACTION, un.PERCENT])
def test_the_storage_conversion_round_trips(storage) -> None:
    for text in ("0", "0.0001", "0.5", "1", "37.25"):
        value = D(text)
        there = un.to_fraction(value, storage)
        assert un.from_fraction(there, storage) == value


def test_percentage_points_compose_additively() -> None:
    """+2pp then +3pp is +5pp, exactly, with no float drift."""
    once = un.apply(PD, un.parse("2", un.ABSOLUTE_PP), storage=un.FRACTION)
    twice = un.apply(once, un.parse("3", un.ABSOLUTE_PP), storage=un.FRACTION)
    assert twice == un.apply(PD, un.parse("5", un.ABSOLUTE_PP),
                             storage=un.FRACTION)
    assert twice == D("0.07")


def test_relative_moves_compose_multiplicatively_not_additively() -> None:
    """The arithmetic behind oracle O04: +20% then +10% is +32%, not +30%."""
    once = un.apply(D("100"), un.parse("20", un.RELATIVE), storage=un.MONEY)
    twice = un.apply(once, un.parse("10", un.RELATIVE), storage=un.MONEY)
    assert twice == D("132")
    assert twice != D("130")
