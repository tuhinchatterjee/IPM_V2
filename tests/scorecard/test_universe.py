"""
The retail scorecard universe. §2, §5-§11, §74, §75, §91.

Two kinds of test here, and the second matters more.

**Acceptance.** §91's counts: twenty-five months, ten thousand rows in every
one of them, twenty-four candidate variables, three model versions. These
are cheap and they are what "complete" is measured against.

**That the data has something in it.** A universe that satisfies every count
and carries no signal would pass acceptance and be useless: every diagnostic
would come back "nothing found", and there would be no way to tell a working
diagnostic from a broken one. So the planted phenomena are asserted here —
the enquiry decay is really a decay, the channel mix really shifts, the
stress months really are worse — because those assertions are what make
every later test of a diagnostic meaningful.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.scorecard import binning as binning_mod
from backend.scorecard import build as build_mod
from backend.scorecard import catalogue as catalogue_mod
from backend.scorecard import equation as equation_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod

APP = vars_mod.APPLICATION_SCORECARD
BEH = vars_mod.BEHAVIORAL_SCORECARD


def _auc(y: np.ndarray, x: np.ndarray) -> float:
    """Mann-Whitney AUC, written out rather than imported.

    §92 asks for independent implementations where practical. This one is
    deliberately not the engine's, so a test that passes here and there is
    evidence rather than a tautology.
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    keep = ~np.isnan(x) & ~np.isnan(y)
    y, x = y[keep], x[keep]
    ranks = np.argsort(np.argsort(x)) + 1.0
    positives = y.sum()
    negatives = len(y) - positives
    if positives == 0 or negatives == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2)
                 / (positives * negatives))


# ------------------------------------------------------------- §91 counts


@pytest.mark.parametrize("months", [synth.APPLICATION_MONTHS,
                                    synth.BEHAVIORAL_MONTHS])
def test_there_are_at_least_twenty_five_months(months):
    assert len(months) >= 25


def test_the_development_window_does_not_overlap_any_validation_month():
    """The separation the whole binning argument rests on."""
    assert not set(synth.DEVELOPMENT_MONTHS) & set(synth.APPLICATION_MONTHS)
    assert max(synth.DEVELOPMENT_MONTHS) < min(synth.APPLICATION_MONTHS)


def test_each_scorecard_carries_at_least_twenty_four_candidates():
    assert len(vars_mod.catalogue(APP)) >= 24
    assert len(vars_mod.catalogue(BEH)) >= 24


def test_each_active_model_uses_five_or_six_variables():
    for scorecard_type, models in build_mod.MODEL_VARIABLES.items():
        for kind, names in models.items():
            assert 5 <= len(names) <= 6, (scorecard_type, kind)


def test_three_model_versions_exist_for_each_scorecard():
    for scorecard_type in (APP, BEH):
        assert len(build_mod.MODEL_VARIABLES[scorecard_type]) >= 3


def test_every_month_carries_more_than_ten_thousand_rows():
    """§91's floor, checked on the ends and the middle rather than all 25.

    Generating every month here would make this suite minutes long for a
    property the generator holds by construction; the row count is drawn
    from a fixed band and the panel is a fixed size.
    """
    for month, offset in (("2023-01", 0), ("2024-01", 12), ("2025-01", 24)):
        assert len(synth.application_month(month, offset=offset)) > 10_000

    panel = synth.behavioral_panel()
    for month, offset in (("2023-01", 0), ("2025-01", 24)):
        assert len(synth.behavioral_month(month, offset=offset,
                                          panel=panel)) > 10_000


# --------------------------------------------------------------- §2 honesty


def test_every_row_says_it_is_synthetic():
    frame = synth.application_month("2023-06", offset=5)
    assert (frame["origin"] == synth.ORIGIN).all()
    panel = synth.behavioral_panel()
    snapshot = synth.behavioral_month("2023-06", offset=5, panel=panel)
    assert (snapshot["origin"] == synth.ORIGIN).all()


def test_every_catalogue_entry_says_it_is_synthetic():
    for dataset in catalogue_mod.datasets():
        assert dataset["is_synthetic"] is True
        assert dataset["origin"] == synth.ORIGIN


def test_the_manifest_says_it_is_not_for_planners():
    body = synth.manifest()
    assert "never given to a planner" in body["not_for_planners"]
    assert len(body["phenomena"]) >= 9


# ------------------------------------------------------------- §7 maturity


def test_an_immature_cohort_has_no_outcome_rather_than_a_zero():
    """The single most damaging thing this dataset could imply.

    A zero in `actual_default` on a cohort whose window has not closed reads
    as "did not default". It has to be absent.
    """
    assert not synth.matured("2025-06")
    frame = synth.application_month("2025-06", offset=29)
    assert frame["matured_flag"].iloc[0] is False or not frame[
        "matured_flag"].iloc[0]
    assert frame["actual_default"].isna().all()


def test_maturity_is_computed_from_the_horizon_and_the_data_end():
    assert synth.matured("2025-01", horizon=12, data_end="2026-01")
    assert not synth.matured("2025-02", horizon=12, data_end="2026-01")
    # A shorter horizon matures more cohorts. The rule is arithmetic, not a
    # stored flag, so changing the horizon changes the answer.
    assert synth.matured("2025-07", horizon=6, data_end="2026-01")


def test_the_latest_matured_month_is_not_the_latest_data_month():
    """§7's distinction, which the dashboard has to show separately."""
    later = (*synth.APPLICATION_MONTHS, "2025-02", "2025-03")
    assert synth.latest_matured(later) == "2025-01"
    assert later[-1] == "2025-03"


# ------------------------------------------------- §74's planted phenomena


def test_the_enquiry_variable_really_does_stop_discriminating():
    """APP-ENQUIRIES-DECAY, measured rather than asserted from the manifest."""
    early = synth.application_month("2023-01", offset=0)
    late = synth.application_month("2025-01", offset=24)
    early_auc = _auc(early["actual_default"], early["bureau_enquiries_6m"])
    late_auc = _auc(late["actual_default"], late["bureau_enquiries_6m"])
    assert early_auc > 0.55, early_auc
    assert late_auc < early_auc - 0.03, (early_auc, late_auc)


def test_a_variable_that_was_meant_to_hold_up_holds_up():
    """The control. Without it, a decay test passes on data where everything
    decayed — which would mean the generator was broken, not the variable."""
    early = synth.application_month("2023-01", offset=0)
    late = synth.application_month("2025-01", offset=24)
    early_auc = _auc(early["actual_default"], -early["bureau_score"].astype(
        float))
    late_auc = _auc(late["actual_default"], -late["bureau_score"].astype(
        float))
    assert early_auc > 0.65
    assert abs(early_auc - late_auc) < 0.03, (early_auc, late_auc)


def test_the_channel_mix_really_shifts():
    early = synth.application_month("2023-01", offset=0)
    late = synth.application_month("2025-01", offset=24)
    early_share = (early["application_channel"] == "DIGITAL").mean()
    late_share = (late["application_channel"] == "DIGITAL").mean()
    assert late_share > early_share * 1.5, (early_share, late_share)


def test_income_really_does_go_missing_more_often():
    early = synth.application_month("2023-01", offset=0)
    late = synth.application_month("2025-01", offset=24)
    assert early["monthly_income"].isna().mean() < 0.05
    assert late["monthly_income"].isna().mean() > 0.10


def test_the_observed_default_rate_really_deteriorates():
    early = synth.application_month("2023-01", offset=0)
    late = synth.application_month("2025-01", offset=24)
    assert late["actual_default"].mean() > early["actual_default"].mean()


def test_the_behavioral_stress_months_really_are_worse():
    panel = synth.behavioral_panel()
    calm = synth.behavioral_month("2023-06", offset=5, panel=panel)
    stressed = synth.behavioral_month("2024-10", offset=21, panel=panel)
    assert stressed["actual_default"].mean() > calm["actual_default"].mean() \
        * 1.3


def test_behavioral_utilisation_really_shifts():
    panel = synth.behavioral_panel()
    early = synth.behavioral_month("2023-01", offset=0, panel=panel)
    late = synth.behavioral_month("2025-01", offset=24, panel=panel)
    assert late["utilisation_pct"].mean() > early["utilisation_pct"].mean() \
        + 5.0


def test_the_behavioral_book_is_a_panel_and_not_25_random_samples():
    """§6. An account that was there in March is the same account in April."""
    panel = synth.behavioral_panel()
    march = synth.behavioral_month("2023-03", offset=2, panel=panel)
    april = synth.behavioral_month("2023-04", offset=3, panel=panel)
    shared = set(march["account_id"]) & set(april["account_id"])
    assert len(shared) > 0.9 * min(len(march), len(april))


# ------------------------------------------------------ §75 data quality


def test_no_variable_is_an_independent_random_column():
    """§75. Every predictor has to carry some relationship to the outcome."""
    frame = synth.application_month("2023-06", offset=5)
    informative = 0
    for variable in vars_mod.catalogue(APP):
        if variable.kind != "NUMERIC" or variable.name not in frame.columns:
            continue
        area = _auc(frame["actual_default"], frame[variable.name].astype(
            float))
        if not np.isnan(area) and abs(area - 0.5) > 0.02:
            informative += 1
    assert informative >= 12, informative


def test_the_default_rate_is_plausible_rather_than_impossible():
    """§75. A 40% book and a 0.01% book are both signs of a broken sim."""
    frame = synth.application_month("2023-06", offset=5)
    rate = frame["actual_default"].mean()
    assert 0.01 < rate < 0.20, rate


def test_regenerating_a_month_reproduces_it_exactly():
    first = synth.application_month("2024-03", offset=14)
    second = synth.application_month("2024-03", offset=14)
    assert first["bureau_score"].sum() == second["bureau_score"].sum()
    assert first["actual_default"].sum() == second["actual_default"].sum()


def test_generating_one_month_does_not_perturb_another():
    """Why the seed is derived per month rather than drawn sequentially."""
    before = synth.application_month("2024-04", offset=15)
    synth.application_month("2023-11", offset=10)
    after = synth.application_month("2024-04", offset=15)
    assert before["bureau_score"].sum() == after["bureau_score"].sum()


# --------------------------------------------------- §10 binning and WoE


@pytest.fixture(scope="module")
def application_spec():
    development = synth.application_development()
    columns = build_mod._model_columns(APP)
    return development, binning_mod.fit(
        development, scorecard_type=APP, spec_version="test-1.0.0",
        target=build_mod.TARGET,
        kinds=build_mod._kinds_for(APP, tuple(columns)))


def test_the_binning_produces_a_woe_and_an_iv_for_every_variable(
        application_spec):
    _, spec = application_spec
    for name, binning in spec.variables.items():
        assert binning.bins, name
        assert binning.information_value > 0, name


def test_applying_a_spec_is_a_lookup_and_never_a_fit(application_spec):
    """§10's rule, checked structurally.

    Applying the spec to a different population must produce the WoE values
    the spec holds — not values refitted on that population.
    """
    _, spec = application_spec
    month = synth.application_month("2025-01", offset=24)
    applied = spec.apply(month, variables=["bureau_score"])
    observed = set(applied["bureau_score_woe"].round(6))
    fitted = {round(b.woe, 6) for b in spec.variables["bureau_score"].bins}
    assert observed <= fitted


def test_a_variable_with_no_approved_binning_is_refused(application_spec):
    _, spec = application_spec
    month = synth.application_month("2023-01", offset=0)
    with pytest.raises(binning_mod.BinningError) as caught:
        spec.apply(month, variables=["monthly_rent"])
    assert "inventing the mapping" in str(caught.value)


def test_missing_values_get_their_own_fitted_bin(application_spec):
    """"Declined to state income" is itself predictive."""
    _, spec = application_spec
    binning = spec.variables.get("debt_burden_ratio")
    assert binning is not None
    specials = [b for b in binning.bins if b.bin_id == binning_mod.MISSING_BIN]
    assert specials and specials[0].count > 0


def test_an_unseen_category_is_neutral_and_counted(application_spec):
    """It cannot have a fitted WoE, so it gets zero — and gets counted."""
    _, spec = application_spec
    binning = binning_mod.VariableBinning(
        variable="x", kind="CATEGORICAL",
        bins=[binning_mod.Bin(bin_id="B1", label="A", members=("A",),
                              woe=0.4)])
    found = binning.bin_for("SOMETHING_NEW")
    assert found.bin_id == binning_mod.UNSEEN_BIN
    assert found.woe == 0.0


def test_a_development_sample_with_no_bads_is_refused():
    import pandas as pd

    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0], build_mod.TARGET: [0, 0, 0]})
    with pytest.raises(binning_mod.BinningError) as caught:
        binning_mod.fit_variable(frame, "x", build_mod.TARGET, kind="NUMERIC")
    assert "score every future month with a constant" in str(caught.value)


# --------------------------------------------------------- §3/§4 catalogue


def test_both_domains_are_registered_with_their_families():
    body = catalogue_mod.summary()
    assert set(body["domains"]) == {APP, BEH}
    assert body["family_counts"][APP] >= 7
    assert body["family_counts"][BEH] >= 7


def test_the_forbidden_cross_domain_join_is_declared_as_forbidden():
    """§78. Both sides carry customer_id and mean different things by it."""
    forbidden = [r for r in catalogue_mod.RELATIONSHIPS
                 if r["kind"] == "FORBIDDEN"]
    assert len(forbidden) == 1
    assert "two default definitions" in forbidden[0]["why"]


def test_sensitive_fields_are_marked_restricted_in_the_catalogue():
    entry = next(d for d in catalogue_mod.datasets()
                 if d["name"].endswith("application_scorecard_monthly_validation"))
    by_name = {f["name"]: f for f in entry["fields"]}
    for name in vars_mod.sensitive(APP):
        assert by_name[name]["sensitivity"] == "restricted", name


# ------------------------------------------------------- §13/§16 equations


def test_a_sensitive_field_may_not_be_scored():
    """The tag in the dictionary is a control, not a comment."""
    equation = equation_mod.Equation(
        model_name="bad", scorecard_type=APP, intercept=-3.0,
        terms=[equation_mod.Term("applicant_age", -0.5),
               equation_mod.Term("bureau_score", -0.7),
               equation_mod.Term("debt_burden_ratio", -0.4),
               equation_mod.Term("bureau_max_dpd_12m", -0.3),
               equation_mod.Term("credit_card_utilisation", -0.4)])
    found = equation_mod.validate(equation)
    assert not found.valid
    assert any(p.check == "variable_is_scoreable" for p in found.blockers)


def test_a_variable_outside_the_dictionary_is_refused():
    equation = equation_mod.Equation(
        model_name="bad", scorecard_type=APP, intercept=-3.0,
        terms=[equation_mod.Term("lucky_number", -0.5)])
    found = equation_mod.validate(equation)
    assert any(p.check == "variable_exists" for p in found.blockers)


def test_a_backwards_coefficient_is_reported_rather_than_fitted_around():
    equation = equation_mod.Equation(
        model_name="odd", scorecard_type=APP, intercept=-3.0,
        terms=[equation_mod.Term("bureau_score", +0.7)])
    found = equation_mod.validate(equation)
    warnings = [p for p in found.problems
                if p.check == "coefficient_sign_matches_credit_sense"]
    assert warnings
    assert "reads the factor backwards" in warnings[0].detail


def test_score_direction_has_no_default():
    """§13. Both conventions are correct and they invert every statistic."""
    with pytest.raises(equation_mod.EquationError) as caught:
        equation_mod.ScoreMapping.from_dict(
            {"base_score": 600, "pdo": 20, "base_odds": 50})
    assert "no default" in str(caught.value)


def test_the_score_mapping_reproduces_the_briefs_formula():
    mapping = equation_mod.ScoreMapping.from_dict(build_mod.SCORE_MAPPING)
    import math

    assert mapping.factor == pytest.approx(20.0 / math.log(2.0))
    assert mapping.offset == pytest.approx(
        600.0 - mapping.factor * math.log(50.0))
    # Higher score is better, so a worse logit must score lower.
    assert mapping.score(-3.0) > mapping.score(3.0)


def test_a_score_that_rises_with_pd_under_higher_is_better_is_refused():
    """The bug that inverts every discrimination statistic silently."""
    equation = equation_mod.Equation(
        model_name="inverted", scorecard_type=APP, intercept=-3.0,
        terms=[equation_mod.Term("bureau_score", -0.7)],
        score_mapping=equation_mod.ScoreMapping(
            base_score=600, pdo=-20, base_odds=50,
            score_direction=equation_mod.HIGHER_SCORE_IS_BETTER))
    found = equation_mod.validate(equation)
    assert not found.valid


def test_a_missing_woe_column_is_refused_rather_than_treated_as_zero():
    equation = equation_mod.Equation(
        model_name="m", scorecard_type=APP, intercept=-3.0,
        terms=[equation_mod.Term("bureau_score", -0.7)])
    with pytest.raises(equation_mod.EquationError) as caught:
        equation.logit({})
    assert "different model from the one that was approved" in str(
        caught.value)


def test_the_diff_reports_a_candidate_and_never_an_overwrite():
    current = equation_mod.Equation(
        model_name="v1", scorecard_type=APP, intercept=-3.0,
        terms=[equation_mod.Term("bureau_score", -0.7),
               equation_mod.Term("bureau_enquiries_6m", -0.4)])
    candidate = equation_mod.Equation(
        model_name="v2", scorecard_type=APP, intercept=-2.9,
        terms=[equation_mod.Term("bureau_score", -0.75),
               equation_mod.Term("loan_to_income", -0.3)])
    body = equation_mod.diff(current, candidate)
    assert body["variables_added"] == ["loan_to_income"]
    assert body["variables_removed"] == ["bureau_enquiries_6m"]
    assert "bureau_score" in body["coefficients_changed"]
    assert body["material"] is True
    assert "never overwrites the active model" in body["status"]
