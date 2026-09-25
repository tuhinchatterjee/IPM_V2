"""The reference calculator, checked against arithmetic done by hand.

UNIT · INDEPENDENT ORACLE · NO MODEL. No database, no provider, not even a
scripted one.

`reference_ecl.py` is what makes the candidate release's ECL a function worth
learning rather than a three-way product a model would recover to machine
precision. That only holds if the calculator is right, so every expected value
below is written out from the formulas in its header rather than taken from
the function under test.

The properties that matter, in the order they matter:

* a zero shock changes nothing, and a zero-length horizon costs nothing;
* survival, marginal PD and cumulative PD are one consistent set, not three
  independently plausible columns;
* discounting is real -- a Stage 3 exposure is NOT `ead x lgd`, and a book
  where it were would be back to the closed form section 11.1 forbids;
* maturity truncates rather than being ignored;
* scenario weights that do not sum to one are refused rather than scaled.
"""

from __future__ import annotations

import math

import pytest

from backend.cockpit_v4.scenario import reference_ecl as ref


def corporate(**over):
    body = {"pd_12m": 0.04, "lgd": 0.45, "ead": 100.0, "eir": 0.06,
            "remaining_maturity_months": 120.0}
    body.update(over)
    return ref.term_structure(**body, **ref.profile("corporate"))


# ---- the shapes are a declared contract -------------------------------

def test_the_first_bucket_is_exactly_twelve_months_in_both_books() -> None:
    """Which is what makes the twelve-month figure exact.

    If bucket 0 were any other length the twelve-month ECL would have to
    apportion part of a bucket, and section 8 is explicit that twelve-month
    and lifetime ECL are distinct measurements rather than one scaled into
    the other.
    """
    assert ref.CORPORATE_BUCKETS[0] == ref.TWELVE_MONTHS
    assert ref.RETAIL_BUCKETS[0] == ref.TWELVE_MONTHS


@pytest.mark.parametrize("book", ["corporate", "retail"])
def test_every_shape_describes_the_same_number_of_buckets(book) -> None:
    shapes = ref.profile(book)
    lengths = {len(v) for v in shapes.values()}
    assert len(lengths) == 1, f"{book}: {shapes.keys()} disagree on length"


def test_a_book_with_no_declared_profile_is_refused() -> None:
    with pytest.raises(ValueError, match="no declared term-structure"):
        ref.profile("mortgages")


def test_a_shape_shorter_than_the_term_structure_is_refused() -> None:
    """Silently truncating would measure a shorter life than the one asked
    for and report it as the lifetime figure."""
    with pytest.raises(ValueError, match="same number of buckets"):
        ref.term_structure(
            pd_12m=0.04, lgd=0.45, ead=100.0, eir=0.06,
            remaining_maturity_months=120.0,
            buckets=(12, 12), hazard_shape=(1.0,), lgd_shape=(1.0, 1.0),
            ead_shape=(1.0, 1.0))


# ---- discounting ------------------------------------------------------

def test_the_discount_factor_is_the_midpoint_one() -> None:
    assert ref.discount_factor(0.06, 6.0) == pytest.approx(1.06 ** -0.5)
    assert ref.discount_factor(0.06, 12.0) == pytest.approx(1.06 ** -1.0)


def test_a_zero_rate_does_not_discount() -> None:
    """And a negative one does not make a distant loss larger than a near
    one, which is what an unguarded formula would do."""
    assert ref.discount_factor(0.0, 24.0) == 1.0
    assert ref.discount_factor(-0.02, 24.0) == 1.0


def test_the_twelve_month_figure_is_the_discounted_product() -> None:
    """Bucket 0 by hand: survival 1, marginal PD 0.04, LGD 0.45, EAD 100,
    discounted at the six-month midpoint."""
    expected = 1.0 * 0.04 * 0.45 * 100.0 * (1.06 ** -0.5)
    got = ref.measure(per_scenario={"baseline": corporate()},
                      weights={"baseline": 1.0}, stage=1)
    # `PLACES` is where the published figure is rounded, once, at the end.
    # Comparing tighter than that would be checking the rounding rather than
    # the arithmetic.
    assert got.ecl_12m == pytest.approx(expected, abs=10.0 ** -ref.PLACES)


def test_the_twelve_month_figure_is_not_ead_times_pd_times_lgd() -> None:
    """The whole reason this calculator exists. A candidate book measured
    the accepted books' way would be a closed form, and section 11.1
    forbids calling a model trained on one an emulator."""
    closed_form = 100.0 * 0.04 * 0.45
    got = ref.measure(per_scenario={"baseline": corporate()},
                      weights={"baseline": 1.0}, stage=1)
    assert got.ecl_12m < closed_form
    assert abs(got.ecl_12m - closed_form) > 0.04


# ---- the term structure is internally consistent ----------------------

def test_survival_is_the_running_product_of_not_defaulting() -> None:
    buckets = corporate()
    running = 1.0
    for bucket in buckets:
        assert bucket.survival == pytest.approx(running, abs=1e-12)
        running *= (1.0 - bucket.pd_marginal)


def test_cumulative_pd_agrees_with_survival() -> None:
    for bucket in corporate():
        assert bucket.pd_cumulative == pytest.approx(
            1.0 - bucket.survival * (1.0 - bucket.pd_marginal), abs=1e-12)


def test_cumulative_pd_only_rises() -> None:
    values = [b.pd_cumulative for b in corporate()]
    assert values == sorted(values)


def test_the_marginal_pd_converts_the_annual_hazard_to_the_bucket() -> None:
    """A 24-month bucket at hazard h is `1 - (1-h)^2`, not `2h`."""
    buckets = corporate()
    long_one = buckets[3]
    assert long_one.months == 24.0
    assert long_one.pd_marginal == pytest.approx(
        1.0 - (1.0 - long_one.hazard) ** 2.0, abs=1e-12)
    assert long_one.pd_marginal < 2.0 * long_one.hazard


def test_the_expected_shortfall_is_the_five_factors_multiplied() -> None:
    for bucket in corporate():
        assert bucket.expected_shortfall == pytest.approx(
            bucket.survival * bucket.pd_marginal * bucket.lgd * bucket.ead
            * bucket.discount_factor, abs=1e-12)


def test_the_lifetime_figure_is_the_sum_of_every_bucket() -> None:
    buckets = corporate()
    got = ref.measure(per_scenario={"baseline": buckets},
                      weights={"baseline": 1.0}, stage=2)
    assert got.ecl_lifetime == pytest.approx(
        math.fsum(b.expected_shortfall for b in buckets), abs=1e-6)
    assert got.ecl_recognised == got.ecl_lifetime


def test_lifetime_is_not_the_annual_figure_times_a_number_of_years() -> None:
    """Section 8 names this approximation as an error. Ten years of a 1.75
    figure would be 17.5; the measurement is under half of that."""
    got = ref.measure(per_scenario={"baseline": corporate()},
                      weights={"baseline": 1.0}, stage=2)
    assert got.ecl_lifetime < got.ecl_12m * 10.0 * 0.6


# ---- stages -----------------------------------------------------------

def test_stage_one_recognises_twelve_months_and_stage_two_lifetime() -> None:
    buckets = {"baseline": corporate()}
    one = ref.measure(per_scenario=buckets, weights={"baseline": 1.0},
                      stage=1)
    two = ref.measure(per_scenario=buckets, weights={"baseline": 1.0},
                      stage=2)
    assert one.ecl_recognised == one.ecl_12m
    assert two.ecl_recognised == two.ecl_lifetime
    assert two.ecl_recognised > one.ecl_recognised


def test_stage_three_defaults_immediately_and_stops() -> None:
    buckets = corporate(pd_12m=1.0)
    defaulted = ref.term_structure(
        pd_12m=1.0, lgd=0.45, ead=100.0, eir=0.06,
        remaining_maturity_months=120.0, defaulted=True,
        **ref.profile("corporate"))
    assert len(defaulted) == 1
    assert defaulted[0].pd_marginal == 1.0
    assert len(buckets) > 1, "only `defaulted` collapses the structure"


def test_a_defaulted_exposure_is_still_discounted() -> None:
    """`ead x lgd` would be the accepted books' answer. Recovery takes time
    and this calculator says so, which is also why a Stage 3 figure here is
    not a closed form."""
    defaulted = ref.term_structure(
        pd_12m=1.0, lgd=0.45, ead=100.0, eir=0.06,
        remaining_maturity_months=120.0, defaulted=True,
        **ref.profile("corporate"))
    got = ref.measure(per_scenario={"baseline": defaulted},
                      weights={"baseline": 1.0}, stage=3)
    assert got.ecl_recognised == pytest.approx(
        0.45 * 100.0 * (1.06 ** -0.5), abs=1e-6)
    assert got.ecl_recognised < 45.0


def test_a_stage_outside_one_two_three_is_refused() -> None:
    with pytest.raises(ValueError, match="not 1, 2 or 3"):
        ref.measure(per_scenario={"baseline": corporate()},
                    weights={"baseline": 1.0}, stage=4)


# ---- maturity ---------------------------------------------------------

def test_maturity_truncates_the_structure() -> None:
    buckets = corporate(remaining_maturity_months=18.0)
    assert [b.months for b in buckets] == [12.0, 6.0]


def test_a_part_bucket_carries_its_own_length_into_the_hazard() -> None:
    """Six months of a bucket is not twelve months of it."""
    part = corporate(remaining_maturity_months=18.0)[1]
    assert part.pd_marginal == pytest.approx(
        1.0 - (1.0 - part.hazard) ** 0.5, abs=1e-12)


def test_a_matured_exposure_measures_to_nothing() -> None:
    assert corporate(remaining_maturity_months=0.0) == ()
    got = ref.measure(per_scenario={"baseline": ()},
                      weights={"baseline": 1.0}, stage=1)
    assert got.ecl_total == 0.0


# ---- scenarios --------------------------------------------------------

def test_the_weighted_figure_is_the_expectation_over_scenarios() -> None:
    per = {"baseline": corporate(pd_12m=0.04),
           "downside": corporate(pd_12m=0.07),
           "upside": corporate(pd_12m=0.03)}
    weights = {"baseline": 0.5, "downside": 0.3, "upside": 0.2}
    expected = math.fsum(
        weights[name] * math.fsum(
            b.expected_shortfall for b in buckets if b.start_month < 12)
        for name, buckets in per.items())
    got = ref.measure(per_scenario=per, weights=weights, stage=1)
    assert got.ecl_12m == pytest.approx(expected, abs=1e-6)


def test_a_weighted_figure_sits_between_its_scenarios() -> None:
    per = {"baseline": corporate(pd_12m=0.04),
           "downside": corporate(pd_12m=0.07),
           "upside": corporate(pd_12m=0.03)}
    weights = {"baseline": 0.5, "downside": 0.3, "upside": 0.2}
    each = {n: ref.horizon_ecl(b, months=12.0) for n, b in per.items()}
    got = ref.measure(per_scenario=per, weights=weights, stage=1)
    assert min(each.values()) < got.ecl_12m < max(each.values())


def test_weights_that_do_not_sum_to_one_are_refused() -> None:
    """Scaling them silently would hide a missing scenario or a
    double-counted one."""
    with pytest.raises(ValueError, match="not 1"):
        ref.measure(per_scenario={"baseline": corporate(),
                                  "downside": corporate(pd_12m=0.07)},
                    weights={"baseline": 0.5, "downside": 0.3}, stage=1)


# ---- overlay ----------------------------------------------------------

def test_the_overlay_is_added_and_not_scaled() -> None:
    plain = ref.measure(per_scenario={"baseline": corporate()},
                        weights={"baseline": 1.0}, stage=1)
    held = ref.measure(per_scenario={"baseline": corporate()},
                       weights={"baseline": 1.0}, stage=1, overlay=0.5)
    assert held.ecl_total == pytest.approx(plain.ecl_total + 0.5, abs=1e-9)
    assert held.ecl_recognised == plain.ecl_recognised


def test_the_recognised_figure_excludes_the_overlay() -> None:
    """So a run can hold the overlay fixed while a stress moves the modelled
    part -- section 9.1's rule, and oracle O08's arithmetic."""
    held = ref.measure(per_scenario={"baseline": corporate()},
                       weights={"baseline": 1.0}, stage=1, overlay=0.5)
    assert held.ecl_total - held.overlay == pytest.approx(
        held.ecl_recognised, abs=1e-9)


# ---- the ML target ----------------------------------------------------

def test_the_rate_is_ecl_over_its_declared_denominator() -> None:
    got = ref.measure(per_scenario={"baseline": corporate()},
                      weights={"baseline": 1.0}, stage=1)
    assert got.rate(100.0) == pytest.approx(got.ecl_total / 100.0, abs=1e-8)


def test_a_zero_denominator_has_no_rate_rather_than_an_infinity() -> None:
    got = ref.measure(per_scenario={"baseline": corporate()},
                      weights={"baseline": 1.0}, stage=1)
    assert got.rate(0.0) == 0.0


def test_the_rate_is_not_exposure_share() -> None:
    """M01. A rate on EAD and a share of the book are different quantities,
    and a model trained on the second is not an ECL model."""
    got = ref.measure(per_scenario={"baseline": corporate()},
                      weights={"baseline": 1.0}, stage=1)
    assert 0.0 < got.rate(100.0) < 0.05


# ---- zero shocks ------------------------------------------------------

def test_a_zero_pd_measures_to_zero_without_dividing_by_anything() -> None:
    got = ref.measure(per_scenario={"baseline": corporate(pd_12m=0.0)},
                      weights={"baseline": 1.0}, stage=1)
    assert got.ecl_total == 0.0


def test_an_identical_rerun_returns_an_identical_measurement() -> None:
    """Section 14.2's determinism, at the smallest scale it can be checked."""
    first = ref.measure(per_scenario={"baseline": corporate()},
                        weights={"baseline": 1.0}, stage=2)
    second = ref.measure(per_scenario={"baseline": corporate()},
                         weights={"baseline": 1.0}, stage=2)
    assert first.ecl_12m == second.ecl_12m
    assert first.ecl_lifetime == second.ecl_lifetime


def test_the_calculator_publishes_its_own_version() -> None:
    """So a figure can be traced to the arithmetic that made it, and a later
    change to these formulas is a new version rather than a restatement."""
    assert ref.VERSION.startswith("whatif-reference-ecl-")
