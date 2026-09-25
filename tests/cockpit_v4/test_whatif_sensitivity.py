"""Stored macro sensitivities: the arithmetic, the gates and the refusals.

REAL DATABASE · NO MODEL where a test reads the published artifact; pure
arithmetic everywhere else. No provider in this module, not even a scripted
one, and nothing here fits a model in a chat turn -- which is itself one of
the things asserted.

The S-series oracles this module carries:

* **S01** the registry reports actual support and every missing entry.
* **S02** native units and shock conventions survive into the artifact.
* **S03** effective sample is distinct periods, never repeated facility rows.
* **S04** lag is chosen on training-only forward validation.
* **S05** the published native derivative equals a finite difference of the
  fitted function.
* **S06** "reduce unemployment by 10%" from 6.0% is 5.4%, a change of −0.6
  percentage points. Never −4%, never a ten-point move.
* **S07** at +0.20 PD points per unemployment point, 3.00% becomes 2.88%.
* **S08** several factors aggregate as the declared linear sum, labelled.
* **S09** the nonlinear translation at zero shock returns the OBSERVED
  baseline exactly.
* **S10** a factor that is not supportably estimable is refused for automatic
  translation, and the reader's own assumption is accepted instead.
* **S11** an absent factor is UNAVAILABLE, never a sensitivity of zero.
* **S16** an artifact fitted against different bytes is STALE and refused.

S12–S15 (rating notches, the two scorecards, stage moves, sector totals) are
mapping behaviour and live with P6's tests; the parts of S12 and S13 that are
properties of the published data are already asserted in
`test_whatif_candidate_release.py`.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.scenario import candidate_schema as cs
from backend.cockpit_v4.scenario import errors as err
from backend.cockpit_v4.scenario import units
from backend.cockpit_v4.scenario.generate import macro as mv
from backend.cockpit_v4.scenario.sensitivity import PARAMETERS, panel
from backend.cockpit_v4.scenario.sensitivity import artifact as art
from backend.cockpit_v4.scenario.sensitivity import build as sens
from backend.cockpit_v4.scenario.sensitivity import estimate as est
from backend.cockpit_v4.scenario.sensitivity import readiness as rd

D = Decimal

#: A slope with §7.4's own numbers in it, built by hand so the worked example
#: is checked against the specification rather than against whatever this
#: release happened to fit.
WORKED_EXAMPLE = art.Slope(
    parameter="pd_pit_12m", factor_id="MEV03", lag=0,
    native_derivative=0.20,
    native_derivative_unit=art.UNIT_SENTENCE["percentage_points"],
    reference_parameter_value=0.03, reference_factor_value=6.0,
    coefficient=6.8729, readiness=rd.SUPPORTED_ESTIMATE,
    limitation="Worked example.", support_low=4.0, support_high=8.0,
    ci_low=0.10, ci_high=0.30, artifact_version=art.ARTIFACT_VERSION,
    source_fingerprint="a" * 64)


def _unsupported(**over: object) -> art.Slope:
    fields = dict(
        parameter="pd_pit_12m", factor_id="MEV08", lag=0,
        native_derivative=-0.03,
        native_derivative_unit=art.UNIT_SENTENCE["relative_percent"],
        reference_parameter_value=0.03, reference_factor_value=100.0,
        coefficient=-1.0, readiness=rd.DIAGNOSTIC_ONLY,
        limitation="The sign agrees in only 52% of period resamples.",
        support_low=90.0, support_high=110.0, ci_low=-0.09, ci_high=0.08,
        artifact_version=art.ARTIFACT_VERSION, source_fingerprint="a" * 64)
    fields.update(over)
    return art.Slope(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# S06 / S07 -- the worked example, which is the whole reason for units.py
# --------------------------------------------------------------------------

def test_s06_reduce_unemployment_by_ten_percent_is_six_to_five_point_four():
    """S06. 6.0% cut by 10% is 5.4%: a −0.6 point move, not a −10 point one.

    Three answers are wrong here and each is a plausible mistake. −4% reads
    the relative cut as a percentage-point subtraction of ten from six. 5.9%
    reads it as ten basis points. −10 points reads the reader's "10%" as the
    move itself. The specification asks for all three numbers to be shown for
    exactly this reason, so all three are asserted.
    """
    told = units.three_values(
        D("6.0"), units.parse("-10", units.RELATIVE, "reduce by 10%"),
        storage=units.PERCENT)
    assert told["baseline"] == "6"
    assert told["scenario"] == "5.4"
    assert told["change"] == "-0.6"
    assert told["change_percentage_points"] == "-0.6"
    assert told["change_relative_pct"] == "-10"
    assert told["operation"] == "-10% relative to baseline"


def test_s07_a_two_tenths_slope_takes_three_percent_to_two_point_eight_eight():
    """S07. 0.20 PD points per unemployment point, −0.6 points, 3.00% → 2.88%.

    The arithmetic is `0.20 × −0.6 = −0.12` percentage points, and a baseline
    of 3.00% becomes 2.88%. A slope applied to the reader's "10%" instead of
    to the converted −0.6 would give 1.00%, which is a different answer to a
    different question.
    """
    moved = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                          factor_scenario=5.4, parameter_baseline=0.03)
    assert moved.factor_change == pytest.approx(-0.6)
    assert moved.parameter_change_pp == pytest.approx(-0.12)
    assert moved.parameter_scenario == pytest.approx(0.0288)
    assert "3.00% to 2.88%" in moved.describe()
    assert "-0.12 percentage points" in moved.describe()


def test_s06_and_s07_compose_from_the_readers_own_words():
    """The two halves joined: the reader says "10%" and gets 2.88%."""
    scenario = units.apply(
        D("6.0"), units.parse("-10", units.RELATIVE), storage=units.PERCENT)
    moved = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                          factor_scenario=float(scenario),
                          parameter_baseline=0.03)
    assert round(moved.parameter_scenario * 100, 2) == 2.88


def test_the_translation_carries_all_three_numbers():
    """Section 5.1. A new value on its own cannot be checked by a reader."""
    moved = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                          factor_scenario=5.4, parameter_baseline=0.03)
    assert moved.factor_baseline == 6.0
    assert moved.factor_scenario == 5.4
    assert moved.factor_change == pytest.approx(-0.6)
    assert moved.parameter_baseline == 0.03
    assert moved.parameter_scenario == pytest.approx(0.0288)
    assert moved.parameter_change_pp == pytest.approx(-0.12)


# --------------------------------------------------------------------------
# S08 / S09 -- the two declared translations
# --------------------------------------------------------------------------

def test_s08_several_factors_aggregate_as_the_declared_linear_sum():
    """S08. `SUM of native_sensitivity x change`, and labelled as marginal."""
    second = art.Slope(**{**WORKED_EXAMPLE.__dict__, "factor_id": "MEV01",
                          "native_derivative": -0.15, "support_low": -2.0,
                          "support_high": 8.0})
    total = art.aggregate(
        [(WORKED_EXAMPLE, 6.0, 5.4), (second, 3.2, 1.2)],
        parameter_baseline=0.03)
    # 0.20 x -0.6  +  -0.15 x -2.0  =  -0.12 + 0.30  =  +0.18
    assert total.parameter_change_pp == pytest.approx(0.18)
    assert total.parameter_scenario == pytest.approx(0.0318)
    assert any("not a jointly estimated model" in w for w in total.warnings)


def test_an_aggregate_across_two_parameters_is_refused():
    """A PD response and an LGD response are not the same quantity."""
    other = art.Slope(**{**WORKED_EXAMPLE.__dict__, "parameter": "lgd_pct"})
    with pytest.raises(ValueError, match="different quantities"):
        art.aggregate([(WORKED_EXAMPLE, 6.0, 5.4), (other, 6.0, 5.4)],
                      parameter_baseline=0.03)


def test_s09_the_nonlinear_translation_at_zero_shock_is_the_baseline():
    """S09. Zero shock returns the OBSERVED baseline, exactly.

    Not the model's fitted value for the baseline period, which is what a
    translation that ran the baseline through the fitted function would
    return, and which would move a number the reader can see on their screen
    without anything having been asked for.
    """
    still = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                          factor_scenario=6.0, parameter_baseline=0.0317,
                          method=art.NONLINEAR)
    assert still.parameter_scenario == 0.0317
    assert still.parameter_change_pp == 0.0


def test_the_two_translations_are_offered_by_name_and_differ():
    """Section 7.2 forbids silently substituting one for the other."""
    linear = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                           factor_scenario=9.0, parameter_baseline=0.03,
                           method=art.LINEAR)
    curved = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                           factor_scenario=9.0, parameter_baseline=0.03,
                           method=art.NONLINEAR)
    assert linear.method == art.LINEAR and curved.method == art.NONLINEAR
    assert linear.parameter_scenario != curved.parameter_scenario
    # The fitted link cannot leave (0, 1); the linear form can and says so.
    assert 0.0 < curved.parameter_scenario < 1.0


def test_an_unknown_translation_is_refused_rather_than_defaulted():
    with pytest.raises(err.ScenarioError) as raised:
        art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                      factor_scenario=5.4, method="whatever_is_closest")
    assert raised.value.code == err.SENSITIVITY_NOT_SUPPORTED


def test_a_shock_outside_the_fitted_range_carries_an_extrapolation_warning():
    moved = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                          factor_scenario=12.0, parameter_baseline=0.03)
    assert any("extrapolation" in w for w in moved.warnings)
    assert moved.parameter_scenario == pytest.approx(0.0420)


def test_a_linear_translation_that_goes_negative_says_so():
    """A probability below zero is a result to flag, not to clamp silently."""
    moved = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                          factor_scenario=-30.0, parameter_baseline=0.03)
    assert moved.parameter_scenario < 0
    assert any("cannot be negative" in w for w in moved.warnings)


# --------------------------------------------------------------------------
# S10 / S16 -- what a scenario is not allowed to translate through
# --------------------------------------------------------------------------

def test_s10_an_unsupported_factor_is_refused_for_automatic_translation():
    """S10. Refused, with the reason, and with the way forward named."""
    with pytest.raises(err.ScenarioError) as raised:
        art.translate(_unsupported(), factor_baseline=100.0,
                      factor_scenario=95.0)
    assert raised.value.code == err.SENSITIVITY_NOT_SUPPORTED
    message = str(raised.value)
    assert "52% of period resamples" in message
    assert "State the parameter change you want to assume" in message


def test_s10_the_readers_own_assumption_is_a_different_route_entirely():
    """An assumption is applied as an assumption, and labelled one.

    The refusal above is not a dead end: section 7.3 says an unsupported
    factor *"remains unavailable for automatic translation unless the user
    supplies an explicit assumption"*. That route is `units.apply` on the
    parameter directly, with no sensitivity in it at all, and it carries
    `USER_ASSUMPTION` rather than an estimate's status.
    """
    assumed = units.three_values(
        D("3.00"), units.parse("0.5", units.ABSOLUTE_PP, "add half a point"),
        storage=units.PERCENT)
    assert assumed["scenario"] == "3.5"
    assert assumed["change_percentage_points"] == "+0.5"
    assert rd.USER_ASSUMPTION in rd.STATUSES


def test_s16_an_artifact_fitted_against_other_bytes_is_refused():
    """S16. A fit against a different book describes a different book."""
    with pytest.raises(err.ScenarioError) as raised:
        art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                      factor_scenario=5.4, in_use_fingerprint="b" * 64)
    assert raised.value.code == err.SENSITIVITY_NOT_SUPPORTED
    assert "describes a different book" in str(raised.value)


def test_s16_the_matching_fingerprint_is_not_refused():
    moved = art.translate(WORKED_EXAMPLE, factor_baseline=6.0,
                          factor_scenario=5.4, in_use_fingerprint="a" * 64)
    assert moved.parameter_scenario == pytest.approx(0.0288)


def test_staleness_needs_two_fingerprints_to_compare():
    """A missing fingerprint is not evidence of a match."""
    assert rd.is_stale("a" * 64, "b" * 64) is True
    assert rd.is_stale("a" * 64, "a" * 64) is False
    assert rd.is_stale("", "b" * 64) is False


# --------------------------------------------------------------------------
# S03 / S04 -- the honesty gates
# --------------------------------------------------------------------------

def test_s03_repeated_facility_rows_do_not_buy_a_longer_history():
    """S03. Twenty quarters across three thousand facilities are twenty."""
    quarters = [f"2024Q{q}" for q in (1, 2, 3, 4)]
    one_row_each = quarters
    many_rows_each = [q for q in quarters for _facility in range(3000)]
    assert rd.effective_periods(one_row_each) == 4
    assert rd.effective_periods(many_rows_each) == 4
    assert len(many_rows_each) == 12_000


def test_the_complexity_ceiling_is_one_on_a_twenty_period_book():
    """`max(1, floor((training − 5) / 5))`, stated rather than implied."""
    assert rd.max_effective_df(12) == 1.0
    assert rd.max_effective_df(13) == 1.0
    assert rd.max_effective_df(20) == 3.0
    assert rd.max_effective_df(3) == 1.0


def test_too_few_training_periods_is_insufficient_history_not_a_small_slope():
    verdict = rd.judge(available=True, training_periods=8,
                       validation_periods=4, effective_df=0.9,
                       collinearity=1.2, sign_stability=0.99, blocks=3)
    assert verdict.status == rd.INSUFFICIENT_HISTORY
    assert verdict.publishable is False
    assert "Facility rows do not count" in verdict.limitation


def test_the_gates_report_the_first_thing_wrong_not_the_last_one_checked():
    """A reader needs the fundamental reason, not the most statistical one."""
    assert rd.judge(available=False, training_periods=0,
                    validation_periods=0, effective_df=0.0,
                    collinearity=99.0, sign_stability=0.0,
                    blocks=0).status == rd.UNAVAILABLE
    assert rd.judge(available=True, training_periods=13,
                    validation_periods=6, effective_df=0.95,
                    collinearity=9.0, sign_stability=0.99,
                    blocks=3).status == rd.DIAGNOSTIC_ONLY
    assert rd.judge(available=True, training_periods=13,
                    validation_periods=6, effective_df=0.95,
                    collinearity=1.5, sign_stability=0.55,
                    blocks=3).status == rd.DIAGNOSTIC_ONLY


def test_a_supported_estimate_still_says_it_is_synthetic():
    verdict = rd.judge(available=True, training_periods=13,
                       validation_periods=6, effective_df=0.95,
                       collinearity=1.5, sign_stability=0.99, blocks=3)
    assert verdict.status == rd.SUPPORTED_ESTIMATE
    assert verdict.publishable is True
    assert "SYNTHETIC_DEMO" in verdict.limitation
    assert "not that the relationship holds in any real economy" \
        in " ".join(verdict.limitation.split())


def test_s04_the_lag_is_chosen_on_forward_validation_not_on_fit_quality():
    """S04. The selected lag is the one with the lower VALIDATION error.

    Built so the two disagree: the outcome answers to the lagged factor, so
    lag 1 must win on held-forward error even though a fitter maximising
    in-sample fit would be free to prefer lag 0.
    """
    periods = [f"2022Q{q}" for q in (1, 2, 3, 4)] + \
              [f"{y}Q{q}" for y in (2023, 2024, 2025, 2026) for q in (1, 2, 3, 4)]
    factor = {p: 5.0 + 2.0 * math.sin(i * 0.9) for i, p in enumerate(periods)}
    values = [factor[p] for p in periods]
    # logit(q_t) responds to the change in the factor one period earlier.
    parameter = {periods[0]: 0.03}
    for i in range(1, len(periods)):
        previous = values[i - 1] - values[max(i - 2, 0)]
        parameter[periods[i]] = est.inverse_logit(
            est.logit(parameter[periods[i - 1]]) + 0.35 * previous)
    fitted = est.fit(parameter="pd_pit_12m", factor_id="MEV03",
                     parameter_by_period=parameter, factor_by_period=factor,
                     periods=periods)
    assert fitted is not None
    assert fitted.lag == 1
    assert fitted.coefficient == pytest.approx(0.35, rel=0.05)


# --------------------------------------------------------------------------
# S05 -- the published derivative against a measured one
# --------------------------------------------------------------------------

def test_s05_the_published_derivative_matches_a_finite_difference():
    """S05. Two routes to one number: analytic `q(1−q)β` and a measured slope.

    A missing logistic derivative, a factor of a hundred, or an inverse link
    applied twice would all leave a plausible-looking number in the artifact
    and would all fail here.
    """
    for reference, beta in ((0.03, 0.42), (0.005, -1.3), (0.28, 0.07)):
        fitted = est.Fit(
            parameter="pd_pit_12m", factor_id="MEV03", lag=0,
            coefficient=beta, intercept=0.0, effective_df=0.95,
            reference_parameter=reference, reference_factor=6.0,
            native_derivative=reference * (1 - reference) * beta * 100.0,
            standardised_response=0.0, fit_error=0.0, validation_error=0.0,
            training_periods=13, validation_periods=6, train_start="a",
            train_end="b", support_low=0.0, support_high=10.0,
            std_error=0.0, ci_low=0.0, ci_high=0.0, sign_stability=1.0,
            blocks=3, collinearity=1.0,
            verdict=rd.judge(available=True, training_periods=13,
                             validation_periods=6, effective_df=0.95,
                             collinearity=1.0, sign_stability=1.0, blocks=3))
        assert est.finite_difference(fitted) == pytest.approx(
            fitted.native_derivative, rel=1e-7)
        assert sens.verify([fitted]) == []


def test_a_derivative_that_forgot_the_logistic_term_is_caught():
    """The check has to be able to fail, or it is not a check."""
    fitted = est.Fit(
        parameter="pd_pit_12m", factor_id="MEV03", lag=0, coefficient=0.42,
        intercept=0.0, effective_df=0.95, reference_parameter=0.03,
        reference_factor=6.0,
        native_derivative=0.42 * 100.0,  # the q(1-q) is missing
        standardised_response=0.0, fit_error=0.0, validation_error=0.0,
        training_periods=13, validation_periods=6, train_start="a",
        train_end="b", support_low=0.0, support_high=10.0, std_error=0.0,
        ci_low=0.0, ci_high=0.0, sign_stability=1.0, blocks=3,
        collinearity=1.0,
        verdict=rd.Verdict(rd.SUPPORTED_ESTIMATE, ""))
    assert sens.verify([fitted])


# --------------------------------------------------------------------------
# The estimator's own properties
# --------------------------------------------------------------------------

def test_the_ridge_penalty_does_not_depend_on_the_factors_unit():
    """A relative penalty shrinks oil and GDP growth by the same fraction.

    The same series measured in two units must give the same shrinkage. With
    an ABSOLUTE penalty it did not: a factor whose differences are large is
    barely touched and one whose differences are small is shrunk to nothing,
    which would grade factors by their unit rather than by their evidence.
    """
    xs = [0.4, -0.3, 0.9, -1.1, 0.2, 0.7, -0.6, 0.5]
    ys = [0.8 * x for x in xs]
    small, _a, df_small = est.ridge(xs, ys)
    big, _b, df_big = est.ridge([x * 1000 for x in xs], ys)
    assert small == pytest.approx(0.8 / (1 + est.PENALTY))
    assert big * 1000 == pytest.approx(small)
    assert df_small == pytest.approx(df_big)
    assert df_small == pytest.approx(1.0 / (1.0 + est.PENALTY))


def test_the_resampled_interval_contains_its_own_point_estimate():
    """An interval that excludes the estimate it describes is a defect.

    It was one: with an absolute penalty a resample of repeated contiguous
    blocks spans less of the training range, so its sum of squares is smaller
    and it was shrunk harder than the point estimate. On a noiseless series
    every interval came back attenuated and the point estimate fell outside.
    """
    xs = [0.4, -0.3, 0.9, -1.1, 0.2, 0.7, -0.6, 0.5, -0.2, 0.6, 0.1, -0.8]
    ys = [0.8 * x + 0.01 for x in xs]
    beta, _alpha, _df = est.ridge(xs, ys)
    slopes = est.block_resample(xs, ys)
    assert slopes
    assert min(slopes) <= beta <= max(slopes)


def test_block_resampling_is_deterministic():
    xs = [0.4, -0.3, 0.9, -1.1, 0.2, 0.7, -0.6, 0.5, -0.2, 0.6, 0.1, -0.8]
    ys = [0.8 * x + 0.01 for x in xs]
    assert est.block_resample(xs, ys) == est.block_resample(xs, ys)


def test_too_few_blocks_returns_no_interval_rather_than_a_decorative_one():
    xs = [0.4, -0.3, 0.9, -1.1, 0.2]
    assert est.block_resample(xs, [0.8 * x for x in xs]) == []
    assert rd.blocks_available(xs) == 1
    assert rd.judge(available=True, training_periods=13, validation_periods=6,
                    effective_df=0.95, collinearity=1.2, sign_stability=0.99,
                    blocks=1).status == rd.DIAGNOSTIC_ONLY


def test_the_estimator_recovers_a_coefficient_that_was_put_in_on_purpose():
    """The point of generating the book macro-first (see CANDIDATE_RELEASE)."""
    periods = [f"{y}Q{q}" for y in (2021, 2022, 2023, 2024, 2025)
               for q in (1, 2, 3, 4)]
    factor = {p: 6.0 + 1.4 * math.sin(i * 0.7) for i, p in enumerate(periods)}
    values = [factor[p] for p in periods]
    parameter = {periods[0]: 0.03}
    for i in range(1, len(periods)):
        parameter[periods[i]] = est.inverse_logit(
            est.logit(parameter[periods[i - 1]])
            + 0.5 * (values[i] - values[i - 1]))
    fitted = est.fit(parameter="pd_pit_12m", factor_id="MEV03",
                     parameter_by_period=parameter, factor_by_period=factor,
                     periods=periods)
    assert fitted is not None
    assert fitted.lag == 0
    assert fitted.coefficient == pytest.approx(0.5 / (1 + est.PENALTY),
                                               rel=1e-6)


def test_a_history_too_short_to_difference_returns_nothing_at_all():
    assert est.fit(parameter="pd_pit_12m", factor_id="MEV03",
                   parameter_by_period={"2025Q1": 0.03, "2025Q2": 0.031},
                   factor_by_period={"2025Q1": 6.0, "2025Q2": 6.1},
                   periods=["2025Q1", "2025Q2"]) is None


# --------------------------------------------------------------------------
# S01 / S02 / S11 -- the registry, its units, and its absences
# --------------------------------------------------------------------------

@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_s01_all_twenty_candidates_appear_with_a_support_status(domain_id):
    """S01. Twenty rows, not sixteen with four silent gaps."""
    registry = mv.registry(domain_id)
    assert len(registry) == 20
    assert [r["factor_id"] for r in registry] == [
        f"MEV{n:02d}" for n in range(1, 21)]
    present, absent = mv.factor_count(domain_id)
    assert present + absent == 20
    assert absent > 0


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_s11_an_absent_factor_has_a_reason_and_no_series(domain_id):
    """S11. Never a zero, and never imputed from a related series."""
    missing = panel.unavailable(domain_id)
    assert missing
    for factor_id, reason in missing:
        assert len(reason) > 40
        with pytest.raises(KeyError):
            mv.series(domain_id, factor_id, ("2025Q1",))


def test_an_absent_factor_gets_artifact_rows_saying_unavailable():
    """A reader asking about MEV07 in the Retail book gets an answer."""
    rows = art.rows([], domain_id=dom.RETAIL, period="2026-08",
                    period_column="reporting_month",
                    release_id=cs.RELEASES[dom.RETAIL], fingerprint="f" * 64,
                    tenant_id=lake.DEFAULT_TENANT, conventions={},
                    method=est.METHOD, fitted_at="2026-08",
                    unavailable=panel.unavailable(dom.RETAIL))
    for_oil = [r for r in rows if r["factor_id"] == "MEV07"]
    assert len(for_oil) == len(PARAMETERS)
    for row in for_oil:
        assert row["readiness"] == rd.UNAVAILABLE
        assert row["native_derivative"] == 0.0
        assert "none is imputed" in row["limitation"]
        assert row["origin"] == cs.ORIGIN


def test_s02_the_published_unit_sentence_follows_the_shock_convention():
    """S02. What "+20" means to this factor, spelled out beside the number."""
    conventions = panel.conventions(dom.CORPORATE)
    assert conventions["MEV03"] == mv.PERCENTAGE_POINTS
    assert conventions["MEV05"] == mv.BASIS_POINTS
    assert conventions["MEV07"] == mv.RELATIVE_PERCENT
    for convention in set(conventions.values()):
        assert convention in art.UNIT_SENTENCE
    assert "hundredth" in art.UNIT_SENTENCE[mv.BASIS_POINTS]


# --------------------------------------------------------------------------
# The cohort the fit reads
# --------------------------------------------------------------------------

def _rows(entities, periods, *, defaulted=()):
    return [{"facility_id": e, "reporting_quarter": p,
             "ead_sar_mn": 10.0, "stage": 3 if e in defaulted else 1,
             "default_flag": 1 if e in defaulted else 0,
             "pd_pit_12m": 0.03, "pd_lifetime": 0.06, "lgd_pct": 45.0}
            for e in entities for p in periods]


def test_the_cohort_is_the_exposures_present_in_every_period():
    periods = ["2025Q1", "2025Q2", "2025Q3"]
    rows = _rows(["F1", "F2"], periods) + _rows(["F3"], periods[:2])
    cohort, defaulted, partial = panel.fixed_cohort(
        rows, key="facility_id", period_column="reporting_quarter",
        periods=periods)
    assert cohort == frozenset({"F1", "F2"})
    assert partial == 1
    assert defaulted == 0


def test_an_exposure_that_ever_defaults_leaves_the_cohort_and_is_counted():
    """A Stage 3 PD of 1.0 is the staging rule, not a macro response."""
    periods = ["2025Q1", "2025Q2", "2025Q3"]
    rows = _rows(["F1", "F2"], periods, defaulted={"F2"})
    cohort, defaulted, partial = panel.fixed_cohort(
        rows, key="facility_id", period_column="reporting_quarter",
        periods=periods)
    assert cohort == frozenset({"F1"})
    assert defaulted == 1
    assert partial == 0


def test_the_weights_are_frozen_so_a_drawdown_is_not_a_macro_effect():
    """A fixed cohort is not enough: live EAD weights move the aggregate.

    Two facilities, both with an unchanged PD. The riskier one doubles its
    EAD. With live weights the cohort average PD would rise and a fitter
    would read a deterioration that did not happen to any loan.
    """
    rows = [
        {"facility_id": "F1", "reporting_quarter": "2025Q1",
         "ead_sar_mn": 100.0, "stage": 1, "default_flag": 0,
         "pd_pit_12m": 0.01, "pd_lifetime": 0.02, "lgd_pct": 40.0},
        {"facility_id": "F1", "reporting_quarter": "2025Q2",
         "ead_sar_mn": 100.0, "stage": 1, "default_flag": 0,
         "pd_pit_12m": 0.01, "pd_lifetime": 0.02, "lgd_pct": 40.0},
        {"facility_id": "F2", "reporting_quarter": "2025Q1",
         "ead_sar_mn": 100.0, "stage": 1, "default_flag": 0,
         "pd_pit_12m": 0.09, "pd_lifetime": 0.18, "lgd_pct": 40.0},
        {"facility_id": "F2", "reporting_quarter": "2025Q2",
         "ead_sar_mn": 300.0, "stage": 1, "default_flag": 0,
         "pd_pit_12m": 0.09, "pd_lifetime": 0.18, "lgd_pct": 40.0},
    ]
    series = panel.parameter_series(
        rows, key="facility_id", period_column="reporting_quarter",
        cohort=frozenset({"F1", "F2"}), weight_period="2025Q1")
    assert series["pd_pit_12m"]["2025Q1"] == pytest.approx(0.05)
    assert series["pd_pit_12m"]["2025Q2"] == pytest.approx(0.05)


def test_lgd_is_carried_into_the_fit_as_a_fraction():
    """`lgd_pct` is stored as a percent and a logit needs a fraction."""
    periods = ["2025Q1"]
    series = panel.parameter_series(
        _rows(["F1"], periods), key="facility_id",
        period_column="reporting_quarter", cohort=frozenset({"F1"}),
        weight_period="2025Q1")
    assert series["lgd_pct"]["2025Q1"] == pytest.approx(0.45)
    assert series["pd_pit_12m"]["2025Q1"] == pytest.approx(0.03)


def test_the_input_digest_moves_when_a_single_period_moves():
    """S16's detector: a generator change that shifts one aggregate."""
    book = panel.Book(
        domain_id=dom.CORPORATE, release_id="r", periods=("2025Q1", "2025Q2"),
        parameters={"pd_pit_12m": {"2025Q1": 0.03, "2025Q2": 0.031}},
        factors={"MEV03": {"2025Q1": 6.0, "2025Q2": 6.1}},
        cohort_size=10, excluded_defaulted=0, excluded_partial=0,
        weight_period="2025Q1")
    moved = panel.Book(**{**book.__dict__,
                          "parameters": {"pd_pit_12m": {"2025Q1": 0.03,
                                                        "2025Q2": 0.0310001}}})
    assert book.digest == panel.input_digest(book)
    assert book.digest != moved.digest
    assert len(book.digest) == 64


# --------------------------------------------------------------------------
# The retrieval contract: reading a sensitivity never fits one
# --------------------------------------------------------------------------

def test_the_read_half_does_not_import_the_fitting_half():
    """Section 7.1. The import graph is what keeps this true, not a comment."""
    source = (art.__file__ and open(art.__file__, encoding="utf-8").read())
    assert "sensitivity import estimate" not in source
    assert "sensitivity import panel" not in source
    assert "sensitivity import build" not in source


def test_nothing_a_chat_turn_reaches_imports_the_estimator():
    """`estimate`, `panel` and `build` are offline-only, by construction."""
    import pathlib
    root = pathlib.Path(art.__file__).resolve().parents[3]
    offenders = []
    for path in (root / "backend" / "cockpit_v4").rglob("*.py"):
        if "scenario/sensitivity" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for module in ("sensitivity import estimate", "sensitivity import panel",
                       "sensitivity import build", "sensitivity.estimate",
                       "sensitivity.panel", "sensitivity.build"):
            if module in text:
                offenders.append(f"{path.name}: {module}")
    assert offenders == []


def test_a_published_row_reads_back_as_the_slope_it_was():
    rows = art.rows(
        [], domain_id=dom.CORPORATE, period="2026Q2",
        period_column="reporting_quarter",
        release_id=cs.RELEASES[dom.CORPORATE], fingerprint="c" * 64,
        tenant_id=lake.DEFAULT_TENANT, conventions={}, method=est.METHOD,
        fitted_at="2026Q2", unavailable=[("MEV14", "Not generated here, "
                                          "and not imputed from another "
                                          "series either.")])
    slope = art.from_row(rows[0])
    assert slope.factor_id == "MEV14"
    assert slope.readiness == rd.UNAVAILABLE
    assert slope.supported is False
    assert slope.source_fingerprint == "c" * 64


# --------------------------------------------------------------------------
# The published artifact, read the way a methodology question reads it
# --------------------------------------------------------------------------

REAL = pytest.mark.usefixtures("_candidate_published")

BOOKS = (
    (dom.CORPORATE, "whatif_corp_sensitivity", "reporting_quarter"),
    (dom.RETAIL, "whatif_retail_sensitivity", "reporting_month"),
)


@pytest.fixture(scope="module")
def _candidate_published():
    import pathlib as _pathlib

    from backend.cockpit_v4 import analytical_runtime as arun

    if not _pathlib.Path("data/cockpit_v4_lake").exists():
        pytest.skip("the published lake is not present in this worktree")
    missing = [r for r in cs.RELEASES.values() if not lake.exists(r)]
    if missing:
        pytest.skip(f"candidate release(s) {missing} are not published; "
                    f"run scripts/whatif/seed_candidate.py")
    arun.reset()
    yield
    arun.reset()


@pytest.fixture()
def enabled(monkeypatch):
    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4.scenario import flags as fl

    for variable in fl.VARIABLES.values():
        monkeypatch.setenv(variable, "1")
    arun.reset()
    yield
    arun.reset()


def _artifact(domain_id, relation):
    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4 import domain_resolver as resolver

    scope = resolver.scope_for(domain_id, tenant_id=lake.DEFAULT_TENANT)
    connection = arun.for_domain(domain_id).session.connection
    assert relation in scope.relations
    columns = [d[0] for d in connection.execute(
        f"SELECT * FROM {relation} LIMIT 0").description]
    rows = connection.execute(
        f"SELECT * FROM {relation} ORDER BY parameter, factor_id").fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows], scope


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_every_candidate_factor_has_a_row_for_every_parameter(
        enabled, domain_id, relation, period_column) -> None:
    """S01 in the published data: twenty factors x three parameters, no gaps.

    A factor the book carries gets a fitted row; one it does not gets an
    UNAVAILABLE row with a reason. Sixty rows either way, which is what makes
    "is there a sensitivity to oil in the Retail book?" an answerable
    question rather than a silence.
    """
    rows, _scope = _artifact(domain_id, relation)
    assert len(rows) == 20 * len(PARAMETERS)
    for parameter in PARAMETERS:
        seen = {r["factor_id"] for r in rows if r["parameter"] == parameter}
        assert seen == {f"MEV{n:02d}" for n in range(1, 21)}


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_the_published_rows_are_all_labelled_synthetic(
        enabled, domain_id, relation, period_column) -> None:
    rows, _scope = _artifact(domain_id, relation)
    assert {r["origin"] for r in rows} == {cs.ORIGIN}
    assert {r["artifact_version"] for r in rows} == {art.ARTIFACT_VERSION}


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_absent_factors_are_unavailable_and_never_a_zero_slope(
        enabled, domain_id, relation, period_column) -> None:
    """S11 in the published data."""
    rows, _scope = _artifact(domain_id, relation)
    absent = {f for f, _r in panel.unavailable(domain_id)}
    assert absent
    for row in rows:
        if row["factor_id"] in absent:
            assert row["readiness"] == rd.UNAVAILABLE
            assert row["method"] == ""
            assert len(row["limitation"]) > 40
        else:
            assert row["readiness"] in (rd.SUPPORTED_ESTIMATE,
                                        rd.DIAGNOSTIC_ONLY)
            assert row["method"] == est.METHOD


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_no_published_row_claims_more_periods_than_the_calendar_has(
        enabled, domain_id, relation, period_column) -> None:
    """S03 in the published data. The book has twenty periods, full stop."""
    rows, scope = _artifact(domain_id, relation)
    manifest = lake.read_manifest(scope.release_id)
    calendar = len(manifest["reporting_periods"])
    assert calendar == 20
    for row in rows:
        assert row["training_periods"] + row["validation_periods"] <= calendar
        assert row["effective_df"] <= row["max_df_allowed"] + 1e-9 or \
            row["readiness"] != rd.SUPPORTED_ESTIMATE


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_a_supported_row_carries_everything_needed_to_use_it(
        enabled, domain_id, relation, period_column) -> None:
    """Section 7.4's required contents, checked on the published rows."""
    rows, _scope = _artifact(domain_id, relation)
    supported = [r for r in rows if r["readiness"] == rd.SUPPORTED_ESTIMATE]
    assert supported
    for row in supported:
        slope = art.from_row(row)
        assert slope.native_derivative != 0.0
        assert slope.reference_parameter_value > 0.0
        assert slope.native_derivative_unit
        assert slope.support_low < slope.support_high
        assert min(row["ci_low"], row["ci_high"]) <= slope.native_derivative \
            <= max(row["ci_low"], row["ci_high"])
        assert row["sign_stability"] >= rd.MIN_SIGN_STABILITY
        assert row["collinearity"] <= rd.MAX_COLLINEARITY
        assert row["train_start"] and row["train_end"]
        assert "SYNTHETIC_DEMO" in row["limitation"]


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_the_published_slopes_have_the_signs_the_book_was_built_with(
        enabled, domain_id, relation, period_column) -> None:
    """The generator put a direction in; the estimator has to find it.

    Conditions worsening raise PD, and each factor's `loading` says which way
    it moves when they do. A factor with a positive loading -- unemployment,
    the policy rate -- must therefore come back with a POSITIVE slope on PD,
    and one with a negative loading -- GDP growth, oil, equities -- with a
    negative one. Getting this backwards would be the clearest possible sign
    that the fit is reading noise.
    """
    rows, _scope = _artifact(domain_id, relation)
    checked = 0
    for row in rows:
        if row["parameter"] != "pd_pit_12m":
            continue
        if row["readiness"] != rd.SUPPORTED_ESTIMATE:
            continue
        loading = mv.BY_ID[row["factor_id"]].loading
        assert (row["native_derivative"] > 0) == (loading > 0), (
            f"{row['factor_id']} loads {loading:+.2f} on worsening "
            f"conditions but its PD slope is "
            f"{row['native_derivative']:+.4f}")
        checked += 1
    assert checked >= 8


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_the_stored_digest_matches_the_release_it_was_fitted_against(
        enabled, domain_id, relation, period_column) -> None:
    """S16's other half: the artifact in place is NOT stale.

    Recomputed from the manifest the release published, so a refit that never
    happened, or a book rebuilt under the same id, would show up here.
    """
    rows, scope = _artifact(domain_id, relation)
    manifest = lake.read_manifest(scope.release_id)
    stored = manifest["notes"]["sensitivity_input_digest"]
    fitted = [r for r in rows if r["method"] == est.METHOD]
    assert fitted
    for row in fitted:
        assert row["source_release_id"] == scope.release_id
        assert row["source_fingerprint"] == stored
        art.require_usable(art.from_row(row), in_use_fingerprint=stored) \
            if row["readiness"] == rd.SUPPORTED_ESTIMATE else None


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_a_translation_through_a_published_slope_is_arithmetic_not_a_refit(
        enabled, domain_id, relation, period_column) -> None:
    """Section 7.1. The read path never touches the fitting path.

    The whole journey a methodology question makes: read the published row,
    turn it into a `Slope`, translate a shock through it. No estimator, no
    panel, no book scan.
    """
    rows, scope = _artifact(domain_id, relation)
    manifest = lake.read_manifest(scope.release_id)
    stored = manifest["notes"]["sensitivity_input_digest"]
    usable = [r for r in rows if r["readiness"] == rd.SUPPORTED_ESTIMATE]
    assert usable
    row = usable[0]
    slope = art.from_row(row)
    moved = art.translate(
        slope, factor_baseline=slope.reference_factor_value,
        factor_scenario=slope.reference_factor_value + 1.0,
        in_use_fingerprint=stored)
    assert moved.factor_change == pytest.approx(1.0)
    assert moved.parameter_change_pp == pytest.approx(slope.native_derivative)


@REAL
@pytest.mark.parametrize("domain_id,relation,period_column", BOOKS)
def test_a_diagnostic_row_is_refused_for_automatic_translation(
        enabled, domain_id, relation, period_column) -> None:
    """S10 on the published data, not on a hand-built slope."""
    rows, _scope = _artifact(domain_id, relation)
    diagnostic = [r for r in rows if r["readiness"] == rd.DIAGNOSTIC_ONLY]
    assert diagnostic, "this book published no diagnostic rows to refuse"
    for row in diagnostic[:5]:
        with pytest.raises(err.ScenarioError) as raised:
            art.translate(art.from_row(row), factor_baseline=1.0,
                          factor_scenario=2.0)
        assert raised.value.code == err.SENSITIVITY_NOT_SUPPORTED
