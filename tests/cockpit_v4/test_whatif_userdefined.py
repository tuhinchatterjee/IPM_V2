"""Five ways to state an impact, and an allocation that adds up exactly.

UNIT · NO MODEL. Decimal arithmetic. No database, no provider, not even a
scripted one.

Section 12 gives five forms and no sixth, and the tests below treat that as
the contract it is: a statement either matches one of them or is refused with
all five named. There is no expression language to sandbox here, which is the
point -- a closed set of declared forms is stricter than a restricted
evaluator and has nothing to escape from.

The rest is the allocation. A reader who says "ECL becomes 22,000" has stated
a total, and a record-level table that sums to 21,999.98 tells them not to
trust either number. Largest-remainder makes the sum exact by construction,
and the property test below is what says so for targets the examples do not
name.

Covers the reachable parts of section 16's D10, D11, C16 and R03, and O10 of
section 17.1.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4.scenario import userdefined as ud
from backend.cockpit_v4.scenario.errors import ScenarioError

D = Decimal

#: The section 17.1 rows, as bare baselines.
BASELINES = [D("8000"), D("10000"), D("1800"), D("0")]
KEYS = ["A", "B", "C", "Z"]
BASELINE_TOTAL = D("19800")
BASELINE_EAD = D("1690000")


# ---- the five forms ----------------------------------------------------

def test_there_are_exactly_five_ways_to_state_an_impact() -> None:
    assert len(ud.FORMS) == 5
    assert set(ud.FORMS) == {ud.RELATIVE, ud.ABSOLUTE, ud.TARGET_AMOUNT,
                             ud.TARGET_RATE, ud.ELASTICITY}


def test_a_sixth_form_is_refused_with_the_five_named() -> None:
    with pytest.raises(ScenarioError) as caught:
        ud.Assumption(form="roughly_double", value=D("2"))
    for name in ud.FORMS:
        assert name in str(caught.value)


def test_relative_moves_the_total_by_a_percentage() -> None:
    got = ud.target_total(ud.Assumption(form=ud.RELATIVE, value=D("15")),
                          baseline_ecl=BASELINE_TOTAL,
                          baseline_ead=BASELINE_EAD)
    assert got == D("22770.00")


def test_absolute_adds_an_amount() -> None:
    got = ud.target_total(ud.Assumption(form=ud.ABSOLUTE, value=D("250")),
                          baseline_ecl=BASELINE_TOTAL,
                          baseline_ead=BASELINE_EAD)
    assert got == D("20050.00")


def test_a_target_amount_is_the_total_itself() -> None:
    got = ud.target_total(
        ud.Assumption(form=ud.TARGET_AMOUNT, value=D("22000")),
        baseline_ecl=BASELINE_TOTAL, baseline_ead=BASELINE_EAD)
    assert got == D("22000.00")


def test_a_target_rate_is_a_coverage_on_exposure() -> None:
    """1.5% of 1,690,000 is 25,350: a rate on EAD, not on ECL, and reading
    it as the wrong denominator would be off by two orders of magnitude."""
    got = ud.target_total(
        ud.Assumption(form=ud.TARGET_RATE, value=D("1.5")),
        baseline_ecl=BASELINE_TOTAL, baseline_ead=BASELINE_EAD)
    assert got == D("25350.00")
    assert got != BASELINE_TOTAL * D("1.5") / 100


def test_a_coverage_target_on_a_cohort_with_no_exposure_is_refused() -> None:
    with pytest.raises(ScenarioError, match="baseline EAD is zero"):
        ud.target_total(ud.Assumption(form=ud.TARGET_RATE, value=D("1.5")),
                        baseline_ecl=BASELINE_TOTAL, baseline_ead=D("0"))


def test_an_elasticity_acts_on_a_stated_driver_move() -> None:
    """1.4% of ECL for each 1% of PD, with PD up 20%, is ECL up 28%."""
    got = ud.target_total(
        ud.Assumption(form=ud.ELASTICITY, value=D("1.4"),
                      driver_move_pct=D("20"), driver_field="pd_pit_12m"),
        baseline_ecl=D("10000"), baseline_ead=BASELINE_EAD)
    assert got == D("12800.00")


def test_an_elasticity_with_nothing_moving_is_not_an_impact() -> None:
    """A sensitivity of 1.4 says nothing until something has moved."""
    with pytest.raises(ScenarioError, match="needs a driver move"):
        ud.Assumption(form=ud.ELASTICITY, value=D("1.4"))


def test_an_assumption_that_would_make_ecl_negative_is_refused() -> None:
    with pytest.raises(ScenarioError, match="cannot be negative"):
        ud.target_total(ud.Assumption(form=ud.ABSOLUTE, value=D("-25000")),
                        baseline_ecl=BASELINE_TOTAL,
                        baseline_ead=BASELINE_EAD)


def test_each_form_describes_itself_differently() -> None:
    """A preview that said "ECL moves 15" for all five would be showing a
    reader a number without its meaning."""
    said = {
        ud.Assumption(form=ud.RELATIVE, value=D("15")).describe(),
        ud.Assumption(form=ud.ABSOLUTE, value=D("15")).describe(),
        ud.Assumption(form=ud.TARGET_AMOUNT, value=D("15")).describe(),
        ud.Assumption(form=ud.TARGET_RATE, value=D("15")).describe(),
        ud.Assumption(form=ud.ELASTICITY, value=D("15"),
                      driver_move_pct=D("1")).describe(),
    }
    assert len(said) == 5


def test_an_elasticity_on_a_one_percent_move_is_a_relative_change() -> None:
    """Not a coincidence and not a defect: 15% of ECL per 1% of the driver,
    with the driver up 1%, IS ECL up 15%. The two forms agreeing where they
    describe the same thing is the check, not a collision."""
    both = {ud.Assumption(form=ud.RELATIVE, value=D("15")),
            ud.Assumption(form=ud.ELASTICITY, value=D("15"),
                          driver_move_pct=D("1"))}
    totals = {ud.target_total(a, baseline_ecl=BASELINE_TOTAL,
                              baseline_ead=BASELINE_EAD) for a in both}
    assert totals == {D("22770.00")}


def test_the_five_forms_give_five_different_totals() -> None:
    totals = {
        str(ud.target_total(a, baseline_ecl=BASELINE_TOTAL,
                            baseline_ead=BASELINE_EAD))
        for a in (ud.Assumption(form=ud.RELATIVE, value=D("15")),
                  ud.Assumption(form=ud.ABSOLUTE, value=D("15")),
                  ud.Assumption(form=ud.TARGET_AMOUNT, value=D("15")),
                  ud.Assumption(form=ud.TARGET_RATE, value=D("15")),
                  ud.Assumption(form=ud.ELASTICITY, value=D("15"),
                                driver_move_pct=D("2")))}
    assert len(totals) == 5


# ---- no expression language, and no float ------------------------------

def test_a_float_is_refused_rather_than_converted() -> None:
    with pytest.raises(ScenarioError, match="float"):
        ud.from_payload({"form": ud.RELATIVE, "value": 15.0})


def test_a_payload_carries_numbers_as_strings() -> None:
    got = ud.from_payload({"form": ud.RELATIVE, "value": "15",
                           "stated_as": "assume ECL rises about 15%"})
    assert got.value == D("15")
    assert got.stated_as == "assume ECL rises about 15%"


def test_the_reader_s_own_words_are_kept_out_of_the_arithmetic() -> None:
    """The statement is audit material; only the typed fields decide a
    number, so two identical assumptions worded differently compute the
    same thing."""
    plain = ud.Assumption(form=ud.RELATIVE, value=D("15"),
                          stated_as="up about a sixth")
    formal = ud.Assumption(form=ud.RELATIVE, value=D("15"),
                           stated_as="+15% on reported ECL")
    assert plain.canonical() == formal.canonical()


# ---- the allocation ----------------------------------------------------

def test_the_allocation_sums_to_the_target_exactly() -> None:
    got = ud.allocate(D("22000.00"), BASELINES, keys=KEYS)
    assert sum(got, D(0)) == D("22000.00")
    assert ud.reconciles(got, D("22000.00"))


def test_no_row_sits_more_than_one_quantum_from_its_share() -> None:
    target = D("22000.00")
    total = sum(BASELINES, D(0))
    got = ud.allocate(target, BASELINES, keys=KEYS)
    for baseline, allocated in zip(BASELINES, got, strict=True):
        share = baseline / total * target
        assert abs(allocated - share) <= ud.QUANTUM


def test_a_zero_baseline_receives_nothing() -> None:
    """There is no proportional share of nothing, and allocating one would
    report ECL on a facility the book says carries none."""
    got = ud.allocate(D("22000.00"), BASELINES, keys=KEYS)
    assert got[KEYS.index("Z")] == D("0")


def test_a_cohort_of_zeros_cannot_carry_a_total() -> None:
    with pytest.raises(ScenarioError, match="nothing here can carry it"):
        ud.allocate(D("100"), [D("0"), D("0")], keys=["a", "b"])


def test_a_cohort_of_zeros_can_carry_a_zero() -> None:
    assert ud.allocate(D("0"), [D("0"), D("0")]) == [D("0"), D("0")]


def test_a_negative_target_allocates_and_still_reconciles() -> None:
    """A scenario where ECL falls is as ordinary as one where it rises, and
    flooring toward negative infinity keeps the leftover non-negative in
    both directions."""
    got = ud.allocate(D("-1000.00"), BASELINES, keys=KEYS)
    assert sum(got, D(0)) == D("-1000.00")
    assert all(v <= 0 for v in got)


@pytest.mark.parametrize("cents", [1, 7, 33, 99, 100, 12345, -5, -101])
def test_the_allocation_reconciles_for_any_target(cents) -> None:
    target = D(cents) / 100
    got = ud.allocate(target, BASELINES, keys=KEYS)
    assert sum(got, D(0)) == target


@pytest.mark.parametrize("size", [1, 2, 3, 7, 50])
def test_the_allocation_reconciles_for_any_cohort_size(size) -> None:
    baselines = [D(i + 1) * D("13.37") for i in range(size)]
    keys = [f"e{i:03d}" for i in range(size)]
    target = D("9999.99")
    got = ud.allocate(target, baselines, keys=keys)
    assert sum(got, D(0)) == target
    assert len(got) == size


def test_a_finer_quantum_is_honoured() -> None:
    got = ud.allocate(D("1.000000"), [D("1"), D("2")],
                      keys=["a", "b"], quantum=D("0.000001"))
    assert sum(got, D(0)) == D("1.000000")
    assert got == [D("0.333333"), D("0.666667")]


def test_rows_goes_from_a_statement_to_a_per_row_answer() -> None:
    got = ud.rows(ud.Assumption(form=ud.TARGET_AMOUNT, value=D("22000")),
                  BASELINES, baseline_ead=BASELINE_EAD, keys=KEYS)
    assert sum(got, D(0)) == D("22000.00")
    assert got[KEYS.index("Z")] == D("0")


def test_a_statement_that_changes_nothing_returns_the_baselines() -> None:
    got = ud.rows(ud.Assumption(form=ud.RELATIVE, value=D("0")),
                  BASELINES, baseline_ead=BASELINE_EAD, keys=KEYS)
    assert sum(got, D(0)) == BASELINE_TOTAL
    assert got == [D("8000.00"), D("10000.00"), D("1800.00"), D("0.00")]
