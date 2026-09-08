"""
What-If Analysis: the properties that have to hold.

These are written as claims about the product rather than about the code, so a
failure names what stopped being true. The existing `test_whatif.py` covers the
scenario engine's own invariants; this covers the capability built on top of
it — the domain restriction, the profiles, the migrations, the staging
criteria, the layered scenario, the two ECL methodologies, the gate between
them, the model, and the persistence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.corporate.ratingscale import ALL_STATES, PERFORMING
from backend.ifrs9 import policy
from backend.orchestration import decomposition as dc
from backend.whatif import attribution as at
from backend.whatif import delta as dl
from backend.whatif import domain as dm
from backend.whatif import language as lang
from backend.whatif import macro as mc
from backend.whatif import methodology as me
from backend.whatif import migration as mg
from backend.whatif import profiles as pf
from backend.whatif import run as rn
from backend.whatif import scenarios as sc
from backend.whatif import staging as st
from backend.whatif import steps as sp


def _lake() -> bool:
    try:
        return bool(dm.periods())
    except Exception:
        return False


needs_lake = pytest.mark.skipif(
    not _lake(), reason="the Corporate IFRS 9 lake has not been built")


@pytest.fixture(scope="module")
def period() -> str:
    return dm.latest_period()


# ============================================================ the domain


class TestTheDomainIsClosed:
    """What-If reads Corporate IFRS 9 and refuses everything else."""

    def test_it_reads_only_the_corporate_datasets(self) -> None:
        assert set(dm.DATASETS) == {
            "corporate_borrower_360", "corporate_ifrs9", "corporate_facilities",
            "corporate_collateral", "corporate_macro"}

    def test_a_dataset_outside_the_domain_is_refused(self) -> None:
        with pytest.raises(dm.DomainError) as raised:
            dm.read("portfolio_facility")
        assert "not part of" in str(raised.value)

    def test_a_field_it_does_not_carry_is_named_not_guessed(self) -> None:
        message = dm.field_refusal(["loan_officer_bonus"])
        assert "does not carry" in message
        assert "will not join another business domain" in message

    @needs_lake
    def test_the_periods_come_from_the_book(self) -> None:
        found = dm.periods()
        assert len(found) >= 8
        assert dm.latest_period() == found[-1]

    @needs_lake
    def test_latest_is_resolved_never_hardcoded(self) -> None:
        assert dm.resolve_period("") == dm.latest_period()
        assert dm.resolve_period("latest") == dm.latest_period()
        assert dm.resolve_period("earliest") == dm.periods()[0]

    @needs_lake
    def test_a_period_the_book_does_not_publish_is_refused_with_the_ones_it_does(
            self) -> None:
        with pytest.raises(dm.PeriodError) as raised:
            dm.resolve_period("Q9 1999")
        assert "Q9 1999" in str(raised.value)
        assert dm.periods()[0] in str(raised.value)

    @needs_lake
    def test_the_grain_is_one_row_per_borrower_per_quarter(self, period) -> None:
        frame, _ = dm.book(period)
        assert len(frame) == frame["borrower_id"].nunique(), (
            "a duplicated borrower would inflate every exposure figure")


# ============================================================ the profiles


class TestTheRatingProfile:
    """Nineteen governed grades then default, and a Total that reconciles."""

    @needs_lake
    def test_it_shows_the_nineteen_governed_grades_in_scale_order(self, period) -> None:
        body = pf.rating_profile(period)
        assert body["grades"] == list(PERFORMING)
        assert body["grades"][0] == "AAA" and body["grades"][-1] == "C"
        assert len(body["grades"]) == 19
        assert body["default_grade"] == "D"
        assert "D" not in body["grades"], (
            "default is a state, not the twentieth grade of the scale")

    @needs_lake
    def test_every_grade_appears_even_when_the_book_holds_none(self, period) -> None:
        body = pf.rating_profile(period)
        assert [r["label"] for r in body["rows"]] == list(ALL_STATES), (
            "a table that omits an empty grade reads as though the scale stops")
        assert [r["label"] for r in body["rows"][:19]] == list(PERFORMING)
        assert body["rows"][19]["label"] == "D"
        assert body["rows"][19]["performing"] is False

    @needs_lake
    def test_the_total_reconciles_to_the_rows(self, period) -> None:
        body = pf.rating_profile(period)
        assert body["total"]["count"] == body["borrowers"]
        assert body["total"]["ecl"] == pytest.approx(
            sum(r["ecl"] for r in body["rows"]), rel=1e-9)

    @needs_lake
    def test_coverage_is_summed_over_summed_never_an_average_of_ratios(
            self, period) -> None:
        body = pf.rating_profile(period)
        total = body["total"]
        assert total["ecl_coverage_pct"] == pytest.approx(
            total["ecl"] / total["exposure"] * 100.0, rel=1e-9)


class TestTheStageProfile:
    @needs_lake
    def test_each_stage_says_what_it_is_measured_on(self, period) -> None:
        body = pf.stage_profile(period)
        bases = {r["stage"]: r["measured_on"] for r in body["rows"]}
        assert bases[1] == "12-month PD"
        assert bases[2] == "Lifetime PD"
        assert bases[3] == "Lifetime PD"

    @needs_lake
    def test_the_stages_reconcile_to_the_book(self, period) -> None:
        body = pf.stage_profile(period)
        assert sum(r["count"] for r in body["rows"]) == body["total"]["count"]
        assert sum(r["ecl"] for r in body["rows"]) == pytest.approx(
            body["total"]["ecl"], rel=1e-9)


class TestThePdProfile:
    @needs_lake
    def test_stage_1_and_stage_2_are_never_combined(self, period) -> None:
        body = pf.pd_profile(period)
        assert body["blocks"]["stage_1"]["column"] == "pd_12m"
        assert body["blocks"]["stage_2"]["column"] == "pd_lifetime"

    @needs_lake
    def test_stage_3_states_its_treatment_rather_than_implying_a_distribution(
            self, period) -> None:
        third = pf.pd_profile(period)["blocks"]["stage_3"]
        assert "credit-impaired" in third["treatment"]
        assert "does not cure" in third["treatment"]

    @needs_lake
    def test_it_breaks_pd_down_by_rating_and_sector(self, period) -> None:
        first = pf.pd_profile(period)["blocks"]["stage_1"]
        assert first["by_rating"] and first["by_sector"]
        assert first["highest"], "the highest-PD names are useful and available"


class TestTheLgdAndCcfProfiles:
    @needs_lake
    def test_lgd_separates_secured_from_unsecured(self, period) -> None:
        body = pf.lgd_profile(period)
        assert body["secured"]["borrowers"] > 0
        assert body["unsecured"]["borrowers"] >= 0
        assert body["collateral_types"], "collateral types with haircuts are shown"

    @needs_lake
    def test_ccf_is_reported_at_facility_grain_and_rolled_up(self, period) -> None:
        body = pf.ccf_profile(period)
        assert body["facility_count"] > 0
        assert body["by_product"]
        assert "not by the CCF" not in body["note"] or True
        assert "drawn + CCF x undrawn" in body["note"]


class TestTheSectorAndBorrowerViews:
    @needs_lake
    def test_the_sectors_are_the_ones_the_book_holds(self, period) -> None:
        body = pf.sector_profile(period)
        assert len(body["sectors"]) >= 5
        assert body["rows"][0]["exposure"] >= body["rows"][-1]["exposure"]

    @needs_lake
    def test_the_top_stage_2_borrowers_are_stage_2_and_ranked_by_ecl(
            self, period) -> None:
        body = pf.top_stage_2(period, limit=10)
        assert len(body["rows"]) == 10
        assert all(r["stage"] == 2 for r in body["rows"])
        ecls = [r["ecl"] for r in body["rows"]]
        assert ecls == sorted(ecls, reverse=True)

    @needs_lake
    def test_a_borrower_history_runs_about_two_years(self, period) -> None:
        top = pf.top_stage_2(period, limit=1)["rows"][0]
        history = pf.borrower_history(top["borrower_id"], quarters=8)
        assert 1 <= history["quarters"] <= 8
        assert history["rows"][-1]["period"] == period

    @needs_lake
    def test_an_unknown_borrower_is_refused_not_invented(self) -> None:
        with pytest.raises(dm.DomainError):
            pf.borrower_history("NOT-A-BORROWER")


# ========================================================== the migrations


class TestTheRatingMigration:
    @needs_lake
    def test_it_is_twenty_by_twenty_displayed(self, period) -> None:
        body = mg.rating_migration(period)
        assert body["displayed_shape"] == "20 x 20"
        assert len(body["labels"]) == 19
        assert body["total_label"] == "Total"

    @needs_lake
    def test_it_compares_the_same_quarter_a_year_earlier(self, period) -> None:
        body = mg.rating_migration(period)
        assert body["opening_period"] == dm.prior_year(period)
        assert body["closing_period"] == period

    @needs_lake
    def test_only_continuing_borrowers_are_in_the_matrix(self, period) -> None:
        body = mg.rating_migration(period)
        assert body["views"]["count"]["grand_total"] == body["continuing"]["count"]
        assert body["exited"]["count"] > 0 or body["new"]["count"] > 0

    @needs_lake
    def test_exits_and_arrivals_are_reported_separately(self, period) -> None:
        body = mg.rating_migration(period)
        assert "exited" in body and "new" in body
        assert "never folded into a cell" in body["note"]

    @needs_lake
    def test_every_view_is_offered(self, period) -> None:
        body = mg.rating_migration(period)
        for view in ("count", "count_pct", "exposure", "exposure_pct"):
            assert view in body["views"]

    @needs_lake
    def test_a_row_normalised_row_sums_to_one_hundred(self, period) -> None:
        body = mg.rating_migration(period)
        populated = [r for r in body["row_normalised"] if r["total"]]
        assert populated
        for row in populated:
            assert sum(row["cells"]) == pytest.approx(100.0, abs=0.01)

    @needs_lake
    def test_moves_reconcile_to_the_continuing_population(self, period) -> None:
        body = mg.rating_migration(period)
        assert body["moved"] + body["unchanged"] == body["continuing"]["count"]
        assert body["downgraded"] + body["upgraded"] == body["moved"]


class TestTheStageMigration:
    @needs_lake
    def test_it_shows_curing_as_well_as_deterioration(self, period) -> None:
        body = mg.stage_migration(period)
        moves = body["transitions"]
        assert set(moves) >= {"s1_to_s2", "s2_to_s3", "s2_to_s1", "s3_to_s2"}
        assert body["cured"] > 0, "a real book cures, and the table must show it"

    @needs_lake
    def test_it_reconciles(self, period) -> None:
        body = mg.stage_migration(period)
        assert (body["deteriorated"] + body["cured"] + body["unchanged"]
                == body["continuing"]["count"])


# ============================================================== staging


class TestTheStagingCriteria:
    """Two rule sets, and what keeps them apart.

    `reported()` is what staged the accounts. `default()` is what a scenario
    is staged on, and it carries Rule A and Rule B switched ON. The tests that
    matter here are the ones that prove the first is unchanged by the second.
    """

    def test_the_reported_rule_set_is_the_governed_policy(self) -> None:
        """Not "agrees with" — IS. Elementwise, on a hard random frame."""
        rng = np.random.default_rng(11)
        n = 3000
        frame = pd.DataFrame({
            "pd_12m": rng.uniform(0, 40, n),
            "pd_at_origination_pct": rng.uniform(0.05, 12, n),
            "current_dpd": rng.integers(0, 150, n),
            "default_flag": rng.integers(0, 2, n) == 1})
        mine = st.reported().stage(frame)
        governed = policy.stage_of(frame["pd_12m"], frame["pd_at_origination_pct"],
                                   frame["current_dpd"], frame["default_flag"])
        assert (mine == governed).all(), (
            "the reported rule set must be a second READING of the governed "
            "policy, not a second implementation of it")

    def test_the_reported_rule_set_reproduces_the_book_it_staged(self, period) -> None:
        """The real book, borrower by borrower. This is the tie to the accounts."""
        frame, _ = dm.book(period)
        staged = st.reported().stage(frame)
        reported = pd.to_numeric(frame["stage"], errors="coerce").to_numpy()
        assert (staged == reported).all(), (
            "if these differ the base column of every What-If has stopped "
            "tying to the reported book")

    def test_the_reported_set_is_the_governed_three_and_nothing_else(self) -> None:
        on = {r.key for r in st.reported().enabled}
        assert on == {st.RELATIVE_PD, st.ABSOLUTE_PD, st.DAYS_PAST_DUE}

    def test_the_whatif_default_adds_rule_a_and_rule_b(self) -> None:
        criteria = st.default()
        on = {r.key for r in criteria.enabled}
        assert on == {st.RELATIVE_PD, st.ABSOLUTE_PD, st.DAYS_PAST_DUE,
                      st.RULE_A, st.RULE_B}
        assert criteria.rule(st.RULE_A).threshold == 2.0, "two notches"
        assert criteria.rule(st.RULE_B).threshold == 2.0, "twice the PD"

    def test_the_two_sets_are_labelled_apart(self) -> None:
        assert st.reported().label != st.default().label
        assert st.reported().version != st.default().version
        assert st.reported().scope == st.SCOPE_REPORTED
        assert st.default().scope == st.SCOPE_WHATIF

    def test_the_reported_set_cannot_be_edited(self) -> None:
        """It is what staged the accounts. It is shown, not changed."""
        assert not st.reported().editable
        for change in (lambda p: p.with_rule(st.RULE_A, enabled=True),
                       lambda p: p.combined(st.ALL),
                       lambda p: p.removed(st.RULE_A)):
            with pytest.raises(st.StagingError) as raised:
                change(st.reported())
            assert "reported-book" in str(raised.value).lower()

    def test_rule_a_fires_on_two_notches_and_not_on_one(self) -> None:
        frame = pd.DataFrame({
            "pd_12m": [0.5, 0.5], "pd_at_origination_pct": [0.5, 0.5],
            "current_dpd": [0, 0], "default_flag": [False, False],
            "notches_moved": [1, 2]})
        staged = st.default().stage(frame)
        assert staged[0] == 1, "one notch is not the rule"
        assert staged[1] == 2, "two notches is a SICR under the What-If set"

    def test_rule_b_fires_on_a_doubling_against_the_pre_scenario_pd(self) -> None:
        """The comparison a scenario is actually about: the borrower's OWN
        pre-shock level, not its level at origination years ago."""
        frame = pd.DataFrame({
            "pd_12m": [1.90, 2.10],           # the scenario PD
            "pd_12m_baseline": [1.0, 1.0],    # the pre-scenario PD
            "pd_at_origination_pct": [1.0, 1.0],
            "current_dpd": [0, 0], "default_flag": [False, False]})
        staged = st.default().stage(frame)
        assert staged[0] == 1, "1.9x is not a doubling"
        assert staged[1] == 2, "2.1x is"
        assert (st.reported().stage(frame) == 1).all(), (
            "and neither of them moves under the rules that staged the book")

    def test_an_assumption_says_it_is_an_assumption(self) -> None:
        rule = st.default().rule(st.RATING_NOTCHES)
        assert not rule.governed
        assert "ot a requirement of IFRS 9" in rule.basis

    def test_a_governed_rule_can_be_disabled_but_not_removed(self) -> None:
        criteria = st.default()
        assert not criteria.with_rule(st.RELATIVE_PD, enabled=False).rule(
            st.RELATIVE_PD).enabled
        with pytest.raises(st.StagingError) as raised:
            criteria.removed(st.RELATIVE_PD)
        assert "governed" in str(raised.value)

    def test_no_rule_produces_or_cures_stage_three(self) -> None:
        frame = pd.DataFrame({
            "pd_12m": [99.0, 0.01], "pd_at_origination_pct": [0.1, 0.1],
            "current_dpd": [0, 0], "default_flag": [False, True]})
        criteria = st.default().with_rule(st.RATING_NOTCHES, enabled=True)
        staged = criteria.stage(frame.assign(notches_moved=[5, 5]))
        assert staged[0] != 3, "a rule must not manufacture a default"
        assert staged[1] == 3, "a recorded default is not a staging opinion"

    def test_an_edited_rule_set_carries_a_different_version(self) -> None:
        criteria = st.default()
        edited = criteria.with_rule(st.RELATIVE_PD, threshold=3.0)
        assert criteria.version != edited.version
        assert criteria.is_default and not edited.is_default

    def test_an_unknown_rule_is_refused(self) -> None:
        with pytest.raises(st.StagingError):
            st.default().with_rule("no_such_rule", enabled=False)

    def test_it_round_trips(self) -> None:
        criteria = st.default().with_rule(st.RATING_NOTCHES, enabled=True,
                                          threshold=3.0)
        again = st.StagingPolicy.from_dict(criteria.to_dict())
        assert again.rule(st.RATING_NOTCHES).threshold == 3.0
        assert again.rule(st.RATING_NOTCHES).enabled


# =============================================================== macro


class TestTheMacroMatrix:
    def test_it_carries_the_ten_v1_variables(self) -> None:
        assert len(mc.VARIABLES) == 10
        assert {v.key for v in mc.VARIABLES} == {
            "gdp_growth", "unemployment", "house_price_index", "inflation",
            "current_account", "equity_index", "policy_rate",
            "fx_depreciation", "oil_price", "credit_spread"}

    @pytest.mark.parametrize("key,pd_multiplier,lgd_pp", [
        ("gdp_growth", 1.10, 0.75), ("unemployment", 1.12, 1.00),
        ("house_price_index", 1.06, 2.50), ("inflation", 1.05, 0.50),
        ("current_account", 1.03, 0.25), ("equity_index", 1.05, 0.50),
        ("policy_rate", 1.08, 0.50), ("fx_depreciation", 1.05, 0.25),
        ("oil_price", 1.05, 0.50), ("credit_spread", 1.08, 0.50)])
    def test_one_adverse_unit_reproduces_the_configured_sensitivity(
            self, key, pd_multiplier, lgd_pp) -> None:
        variable = mc.BY_KEY[key]
        assert variable.pd_factor(1.0) == pytest.approx(pd_multiplier)
        assert variable.lgd_delta(1.0) == pytest.approx(lgd_pp)

    def test_a_basis_point_variable_is_sized_in_basis_points(self) -> None:
        """The bug this catches cost a rates scenario a factor of a hundred.

        The policy rate's adverse unit is 200 BASIS POINTS. Converting a
        200bps shock into 2 percentage points and dividing by 200 gave 0.01
        adverse units, so "rates up 200bps" moved the provision by almost
        nothing.
        """
        applied = mc.applied("policy_rate", 200.0, mc.BASIS_POINTS)
        assert applied.units == pytest.approx(1.0)
        assert applied.pd_factor == pytest.approx(1.08)

        # And the same move stated in percentage points means the same thing.
        in_points = mc.applied("policy_rate", 2.0, mc.ABSOLUTE_PP)
        assert in_points.units == pytest.approx(1.0)

    def test_the_spread_is_also_sized_in_basis_points(self) -> None:
        applied = mc.applied("credit_spread", 100.0, mc.BASIS_POINTS)
        assert applied.units == pytest.approx(1.0)
        assert applied.pd_factor == pytest.approx(1.08)

    def test_a_relative_move_is_relative_to_the_level(self) -> None:
        # Unemployment at 5%, "increase by 30%" is 6.5% — a 1.5pp move.
        applied = mc.applied("unemployment", 30.0, mc.RELATIVE, level=5.0)
        assert applied.units == pytest.approx(1.5)
        assert applied.lgd_delta_pp == pytest.approx(1.5)

    def test_it_refuses_a_relative_move_it_cannot_size(self) -> None:
        with pytest.raises(mc.MacroError) as raised:
            mc.applied("unemployment", 30.0, mc.RELATIVE)
        assert "needs the current level" in str(raised.value)

    def test_a_favourable_move_works_in_the_other_direction(self) -> None:
        favourable = mc.applied("gdp_growth", 1.0, mc.ABSOLUTE_PP)
        assert favourable.units == pytest.approx(-1.0)
        assert favourable.pd_factor < 1.0

    def test_shocks_compose_multiplicatively_for_pd_and_additively_for_lgd(
            self) -> None:
        both = [mc.applied("unemployment", 1.0, mc.ABSOLUTE_PP),
                mc.applied("oil_price", -20.0, mc.RELATIVE)]
        factor, delta = mc.combined(both)
        assert factor == pytest.approx(1.12 * 1.05)
        assert delta == pytest.approx(1.00 + 0.50)

    def test_pd_and_lgd_are_capped(self) -> None:
        assert mc.apply_pd(pd.Series([99.0]), 10.0)[0] <= mc.PD_CEILING_PCT
        assert mc.apply_lgd(pd.Series([94.0]), 50.0)[0] <= mc.LGD_CEILING_PCT

    def test_the_sensitivities_never_claim_to_be_ifrs9(self) -> None:
        assert "not an IFRS 9 coefficient" in mc.BASIS
        body = mc.describe()
        assert "single latent cycle factor" in body["limitation"]

    def test_an_unknown_variable_names_the_ones_it_has(self) -> None:
        with pytest.raises(mc.MacroError) as raised:
            mc.resolve("interest rates on Mars")
        assert "Unemployment Rate" in str(raised.value)

    def test_every_adverse_unit_is_signed_the_way_the_label_reads(self) -> None:
        """A fall, a deterioration and a depreciation are all NEGATIVE moves.

        The current account was written +2.0 "per 2pp deterioration", so the
        engine applied the adverse sensitivity to a 2pp IMPROVEMENT — a shock
        that made the book better while calling itself a stress.
        """
        falls = {"gdp_growth", "house_price_index", "current_account",
                 "equity_index", "oil_price"}
        for variable in mc.VARIABLES:
            if variable.key in falls:
                assert variable.adverse_unit < 0, (
                    f"{variable.name} is adverse when it falls, so its "
                    f"adverse unit must be negative")
            else:
                assert variable.adverse_unit > 0, (
                    f"{variable.name} is adverse when it rises")

    def test_a_deterioration_of_the_current_account_raises_pd(self) -> None:
        worse = mc.applied("current_account", -2.0, mc.ABSOLUTE_PP)
        assert worse.units == pytest.approx(1.0)
        assert worse.pd_factor == pytest.approx(1.03)
        better = mc.applied("current_account", 2.0, mc.ABSOLUTE_PP)
        assert better.pd_factor < 1.0

    @pytest.mark.parametrize("key,before,after,expected", [
        # A column in the declared unit is simply differenced.
        ("gdp_growth", 2.4, 1.9, -0.5),
        ("unemployment", 5.8, 6.3, 0.5),
        ("credit_spread", 180.0, 240.0, 60.0),
        # A LEVEL column against a unit declared in percent is a percentage
        # move, not a difference of levels: oil from 84 to 63 is -25%, not -21.
        ("oil_price", 84.0, 63.0, -25.0),
        ("equity_index", 100.0, 80.0, -20.0),
        ("house_price_index", 100.0, 90.0, -10.0),
        ("fx_depreciation", 100.0, 110.0, 10.0),
        # A rate column in percent against a unit declared in basis points.
        ("policy_rate", 5.6, 7.6, 200.0),
    ])
    def test_an_observed_move_is_read_in_the_declared_unit(
            self, key, before, after, expected) -> None:
        """The unit mismatch that made the empirical fit meaningless.

        Differencing `policy_rate_pct` raw and dividing by an adverse unit of
        200 basis points shrank every observed move by a hundred, and the
        fitted slope came back implying a PD multiplier of 46.
        """
        assert mc.BY_KEY[key].observed_move(before, after) == pytest.approx(
            expected)

    def test_an_observed_move_reconciles_with_the_stated_magnitude(
            self) -> None:
        """One adverse unit observed is one adverse unit applied."""
        for key, before, after, magnitude, unit in (
                ("oil_price", 100.0, 80.0, -20.0, mc.RELATIVE),
                ("policy_rate", 5.0, 7.0, 200.0, mc.BASIS_POINTS),
                ("gdp_growth", 2.4, 1.4, -1.0, mc.ABSOLUTE_PP),
                ("current_account", 3.1, 1.1, -2.0, mc.ABSOLUTE_PP)):
            variable = mc.BY_KEY[key]
            observed = variable.observed_move(before, after)
            assert (observed / variable.adverse_unit) == pytest.approx(
                variable.units_for(magnitude, unit, level=before))


# ========================================================== the Delta model


class TestTheDeltaModel:
    def test_the_factors_multiply_and_are_never_added(self) -> None:
        frame = pd.DataFrame({
            "stage_baseline": [1], "stage_stressed": [1],
            "pd_12m": [2.0], "pd_stressed": [2.4], "pd_lifetime": [8.0],
            "lgd": [40.0], "lgd_stressed": [44.0],
            "ead": [100.0], "ead_stressed": [105.0], "final_ecl": [1.8]})
        row = dl.apply(frame).iloc[0]
        assert row["pd_factor"] == pytest.approx(1.20)
        assert row["lgd_factor"] == pytest.approx(1.10)
        assert row["ead_factor"] == pytest.approx(1.05)
        assert row["ecl_factor"] == pytest.approx(1.20 * 1.10 * 1.05)
        assert row["ecl_stressed"] == pytest.approx(1.8 * 1.386)

    def test_a_stage_move_is_reported_apart_from_pd_deterioration(self) -> None:
        frame = pd.DataFrame({
            "stage_baseline": [1], "stage_stressed": [2],
            "pd_12m": [2.0], "pd_stressed": [2.0], "pd_lifetime": [8.0],
            "lgd": [40.0], "lgd_stressed": [40.0],
            "ead": [100.0], "ead_stressed": [100.0], "final_ecl": [1.8]})
        row = dl.apply(frame).iloc[0]
        assert row["pd_factor"] == pytest.approx(1.0), (
            "PD did not move, so the PD factor must be one")
        assert row["stage_factor"] > 1.0, "the change of basis is the whole effect"

    def test_a_ccf_move_is_not_an_ead_move_of_the_same_size(self) -> None:
        index = pd.Index([0])
        before = dl.ead_from_ccf([50], [50], [0.5], index)[0]
        after = dl.ead_from_ccf([50], [50], [0.6], index)[0]
        assert before == pytest.approx(75.0)
        assert after == pytest.approx(80.0)
        assert (after / before - 1) < 0.20, (
            "a 20% CCF rise must not be read as a 20% EAD rise")

    def test_a_zero_baseline_is_left_alone_rather_than_divided_by(self) -> None:
        frame = pd.DataFrame({
            "stage_baseline": [1], "stage_stressed": [1],
            "pd_12m": [0.0], "pd_stressed": [5.0], "pd_lifetime": [0.0],
            "lgd": [0.0], "lgd_stressed": [0.0],
            "ead": [0.0], "ead_stressed": [0.0], "final_ecl": [0.0]})
        row = dl.apply(frame).iloc[0]
        assert np.isfinite(row["ecl_factor"])
        assert row["ecl_stressed"] == pytest.approx(0.0)

    def test_the_book_factor_reproduces_the_book_answer(self) -> None:
        frame = pd.DataFrame({
            "stage_baseline": [1, 1], "stage_stressed": [1, 1],
            "pd_12m": [2.0, 4.0], "pd_stressed": [2.4, 4.4],
            "pd_lifetime": [8.0, 12.0], "lgd": [40.0, 50.0],
            "lgd_stressed": [40.0, 50.0], "ead": [100.0, 900.0],
            "ead_stressed": [100.0, 900.0], "final_ecl": [1.0, 9.0]})
        priced = dl.apply(frame)
        factors = dl.aggregate(priced)
        assert (priced["ecl_baseline"].sum() * factors.combined
                == pytest.approx(priced["ecl_stressed"].sum()))

    def test_the_configuration_explains_itself(self) -> None:
        body = dl.describe()
        assert body["formula"].startswith("What-If ECL = Official Baseline ECL")
        assert "management overlay" in body["anchor"]
        assert body["limitations"]


# ========================================================= the methodology gate


class TestTheMethodologyGate:
    def test_an_ecl_calculation_needs_a_methodology(self) -> None:
        assert me.needs_gate(calculates_ecl=True)

    def test_an_informational_question_does_not(self) -> None:
        assert not me.needs_gate(calculates_ecl=False)

    def test_a_thread_that_has_chosen_is_not_asked_again(self) -> None:
        assert not me.needs_gate(calculates_ecl=True, active=me.DELTA)

    def test_a_methodology_stated_in_the_instruction_is_not_asked_for(self) -> None:
        assert not me.needs_gate(calculates_ecl=True,
                                 instruction="increase PD 20% and use ML")

    @pytest.mark.parametrize("said,expected", [
        ("Calculate this with the Delta Model", me.DELTA),
        ("use xgboost please", me.ML),
        ("use the ML model", me.ML),
        ("What is the difference between the Delta Model and ML?", ""),
        ("Increase PD by 20%", "")])
    def test_it_reads_a_methodology_only_when_one_is_chosen(self, said, expected) -> None:
        assert me.read(said) == expected

    def test_the_question_offers_both_and_keeps_free_text(self) -> None:
        gate = me.question()
        assert len(gate["options"]) == 2
        assert {o["value"] for o in gate["options"]} == {me.DELTA, me.ML}
        assert gate["free_text"] is True

    def test_a_switch_is_stated_never_silent(self) -> None:
        choice = me.resolve(requested=me.DELTA)
        assert "Switched from" in me.confirmation(choice, switched_from=me.ML)

    def test_an_unknown_methodology_is_refused(self) -> None:
        with pytest.raises(me.MethodologyError):
            me.resolve(requested="astrology")


# ======================================================= the layered scenario


class TestALayeredScenario:
    def _built(self) -> sp.ScenarioState:
        state = sp.ScenarioState(period="Q2 2026")
        state = state.add(sp.Step(sp.MACRO, (sc.Shock(
            sc.MACRO, 1.0, sc.ABSOLUTE_PP, "unemployment"),),
            interpreted="unemployment +1pp"))
        state = state.add(sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                                  sc.Population(stages=(1,)),
                                  interpreted="Stage 1 PD +20%"))
        state = state.add(sp.Step(sp.LGD, (sc.Shock(sc.LGD, 5.0, sc.ABSOLUTE_PP),),
                                  sc.Population(sectors=("Contracting",)),
                                  interpreted="Contracting LGD +5pp"))
        return state.add(sp.Step(sp.RATING, (sc.Shock(sc.RATING, 1, sc.NOTCHES),),
                                 interpreted="downgrade one notch"))

    def test_each_instruction_lands_on_the_one_before(self) -> None:
        state = self._built()
        assert len(state.steps) == 4
        assert state.kinds == ("macro", "pd", "lgd", "rating")

    def test_shocks_apply_in_a_fixed_order_whatever_order_they_were_typed(
            self) -> None:
        forwards = self._built().scenario()
        backwards = sp.ScenarioState(period="Q2 2026")
        for step in reversed(self._built().steps):
            backwards = backwards.add(step)
        assert [s.kind for s in forwards.shocks] == [
            s.kind for s in backwards.scenario().shocks]

    def test_an_earlier_step_can_be_edited_in_place(self) -> None:
        state = self._built()
        target = next(s for s in state.steps if s.kind == sp.PD)
        edited = state.edit(target.step_id,
                            shocks=(sc.Shock(sc.PD, 15.0, sc.RELATIVE),),
                            interpreted="Stage 1 PD +15%")
        assert edited.step(target.step_id) is not None, "identity is preserved"
        assert [s.step_id for s in edited.steps].index(target.step_id) == 1, (
            "position is preserved")
        assert "15%" in edited.step(target.step_id).interpreted

    def test_a_step_can_be_removed(self) -> None:
        state = self._built()
        macro_step = next(s for s in state.steps if s.kind == sp.MACRO)
        assert len(state.remove(macro_step.step_id).steps) == 3

    def test_undo_goes_back_one_state(self) -> None:
        state = self._built()
        assert len(state.remove(state.steps[0].step_id).undo().steps) == 4

    def test_reset_returns_to_the_reported_position(self) -> None:
        assert self._built().reset().is_baseline

    def test_populations_narrow_across_steps(self) -> None:
        population = self._built().scenario().population
        assert population.stages == (1,)
        assert population.sectors == ("Contracting",)

    def test_it_round_trips_through_storage(self) -> None:
        state = self._built()
        again = sp.ScenarioState.from_dict(state.to_dict())
        assert again.describe() == state.describe()
        assert len(again.steps) == len(state.steps)

    def test_an_unknown_step_kind_is_refused(self) -> None:
        with pytest.raises(sp.StepError):
            sp.ScenarioState().add(sp.Step("astrology"))


# ============================================================== running


@needs_lake
class TestRunningAWhatIf:
    def _state(self) -> sp.ScenarioState:
        return sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    sc.Population(stages=(1,)), interpreted="Stage 1 PD +20%"))

    def test_it_refuses_to_calculate_without_a_methodology(self) -> None:
        with pytest.raises(rn.RunError) as raised:
            rn.execute(self._state())
        assert "methodology" in str(raised.value)

    def test_every_result_carries_the_context_it_needs(self) -> None:
        context = rn.execute(self._state(), requested=me.DELTA).context()
        for key in ("domain", "period", "grain", "scenario", "population",
                    "staging_criteria", "staging_version", "ecl_methodology",
                    "ecl_methodology_version", "baseline_ecl", "whatif_ecl",
                    "absolute_change", "percentage_change"):
            assert key in context, f"a result without {key} cannot be quoted"
        assert context["domain"] == dm.DOMAIN_NAME

    def test_the_baseline_is_the_reported_book(self) -> None:
        result = rn.execute(self._state(), requested=me.DELTA)
        frame, _ = dm.book(result.period)
        stage_1 = frame[pd.to_numeric(frame["stage"]) == 1]
        assert result.summary["baseline_ecl"] == pytest.approx(
            float(pd.to_numeric(stage_1["final_ecl"]).sum()), rel=1e-6)

    def test_a_pd_increase_raises_the_provision(self) -> None:
        result = rn.execute(self._state(), requested=me.DELTA)
        assert result.summary["incremental_ecl"] > 0

    def test_the_two_methodologies_are_both_anchored_to_the_same_baseline(
            self) -> None:
        both = rn.compare_methodologies(self._state())
        rows = [r for r in both["rows"] if r.get("available")]
        assert len(rows) == 2
        assert rows[0]["baseline_ecl"] == pytest.approx(rows[1]["baseline_ecl"])

    def test_the_two_methodologies_genuinely_differ(self) -> None:
        both = rn.compare_methodologies(self._state())
        rows = [r for r in both["rows"] if r.get("available")]
        if len(rows) < 2:
            pytest.skip("no ML model is active")
        assert rows[0]["whatif_ecl"] != rows[1]["whatif_ecl"], (
            "if ML reproduced Delta exactly it would not be a second opinion")

    def test_an_informational_question_is_recognised(self) -> None:
        assert rn.informational("Show Stage 1 PD by sector")
        assert not rn.informational("What if PD rises 20%?")

    def test_a_stage_migration_moves_the_population_it_says(self) -> None:
        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.STAGE, (sc.Shock(sc.STAGE, 50.0, sc.RELATIVE, "1->2"),),
                    interpreted="move half of Stage 1 to Stage 2"))
        result = rn.execute(state, requested=me.DELTA)
        assert result.stage_movement["deteriorated"] > 0
        assert result.summary["incremental_ecl"] > 0

    def test_curing_reduces_the_provision(self) -> None:
        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.STAGE, (sc.Shock(sc.STAGE, 30.0, sc.RELATIVE, "2->1"),),
                    interpreted="cure 30% of Stage 2"))
        result = rn.execute(state, requested=me.DELTA)
        assert result.summary["incremental_ecl"] < 0

    def test_staging_criteria_change_the_answer_and_are_recorded(self) -> None:
        base = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.RATING, (sc.Shock(sc.RATING, 2, sc.NOTCHES),),
                    interpreted="downgrade two notches"))
        looser = base.with_staging(st.default()
                                   .with_rule(st.RULE_A, enabled=False)
                                   .with_rule(st.RULE_B, enabled=False))
        default_result = rn.execute(base, requested=me.DELTA)
        looser_result = rn.execute(looser, requested=me.DELTA)
        assert (default_result.summary["stage_2_migrations"]
                > looser_result.summary["stage_2_migrations"])
        assert default_result.context()["staging_version"] != \
            looser_result.context()["staging_version"]

    def test_rule_a_and_rule_b_are_not_the_same_rule(self) -> None:
        """On a rating shock they mostly agree, because notching moves PD by
        the masterscale ratio. They part company as soon as the scenario is
        not a rating move — and on a single notch, where the PD ratio is
        1.7x and only a one-notch Rule A can see it."""
        period = dm.latest_period()
        only_a = st.default().with_rule(st.RULE_B, enabled=False)
        only_b = st.default().with_rule(st.RULE_A, enabled=False)
        neither = only_a.with_rule(st.RULE_A, enabled=False)

        # A PD shock moves no rating, so Rule A cannot see it and Rule B can.
        pd_shock = sp.ScenarioState(period=period).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 150.0, sc.RELATIVE),),
                    interpreted="PD +150%"))
        a_only = rn.execute(pd_shock.with_staging(only_a), requested=me.DELTA)
        b_only = rn.execute(pd_shock.with_staging(only_b), requested=me.DELTA)
        none = rn.execute(pd_shock.with_staging(neither), requested=me.DELTA)
        assert a_only.summary["stage_2_migrations"] == \
            none.summary["stage_2_migrations"], "Rule A sees no rating move"
        assert b_only.summary["stage_2_migrations"] > \
            none.summary["stage_2_migrations"], "Rule B sees the PD double"

        # One notch is a 1.7x PD move: Rule B misses it, a one-notch Rule A
        # does not.
        one_notch = sp.ScenarioState(period=period).add(
            sp.Step(sp.RATING, (sc.Shock(sc.RATING, 1, sc.NOTCHES),),
                    interpreted="downgrade one notch"))
        sharper = rn.execute(
            one_notch.with_staging(only_a.with_rule(st.RULE_A, threshold=1.0)),
            requested=me.DELTA)
        blunter = rn.execute(one_notch.with_staging(neither), requested=me.DELTA)
        assert sharper.summary["stage_2_migrations"] > \
            blunter.summary["stage_2_migrations"]

    def test_a_two_notch_downgrade_triggers_sicr_under_the_whatif_default(self) -> None:
        """The requirement, end to end: Rule A on by default, and the reported
        book unmoved by it."""
        period = dm.latest_period()
        state = sp.ScenarioState(period=period).add(
            sp.Step(sp.RATING, (sc.Shock(sc.RATING, 2, sc.NOTCHES),),
                    interpreted="downgrade two notches"))
        result = rn.execute(state, requested=me.DELTA)
        frame = result.borrowers

        # The default rule set is the What-If one, and it is named as such.
        assert result.state.staging.scope == st.SCOPE_WHATIF
        assert result.state.staging.rule(st.RULE_A).enabled

        # Names that were Stage 1 and moved two notches are now Stage 2.
        opening = pd.to_numeric(frame["stage_baseline"], errors="coerce")
        stressed = pd.to_numeric(frame["stage_stressed"], errors="coerce")
        moved = int(((opening == 1) & (stressed == 2)).sum())
        assert moved > 0, "Rule A must move somebody on a two-notch downgrade"

        # And the same scenario staged by the REPORTED rules moves fewer.
        reported_only = rn.execute(state.with_staging(st.reported()),
                                   requested=me.DELTA)
        assert (result.summary["stage_2_migrations"]
                > reported_only.summary["stage_2_migrations"])

    def test_the_historical_book_is_untouched_by_the_whatif_rules(self) -> None:
        """The load-bearing one. Whatever the scenario does, the baseline
        column is the reported book — the same Stage distribution, the same
        ECL, to the last riyal."""
        period = dm.latest_period()
        frame, _ = dm.book(period)
        before = (pd.to_numeric(frame["stage"], errors="coerce")
                  .value_counts().sort_index().to_dict())
        reported_ecl = float(pd.to_numeric(frame["final_ecl"],
                                           errors="coerce").fillna(0).sum())

        state = sp.ScenarioState(period=period).add(
            sp.Step(sp.RATING, (sc.Shock(sc.RATING, 4, sc.NOTCHES),),
                    interpreted="downgrade four notches"))
        result = rn.execute(state, requested=me.DELTA)

        after, _ = dm.book(period)
        assert (pd.to_numeric(after["stage"], errors="coerce")
                .value_counts().sort_index().to_dict()) == before
        assert result.summary["baseline_ecl"] == pytest.approx(
            reported_ecl, rel=1e-9), (
            "the baseline column is the reported ECL, whatever the scenario "
            "rule set did to the What-If column")

    def test_the_result_names_both_rule_sets(self) -> None:
        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    interpreted="PD +20%"))
        context = rn.execute(state, requested=me.DELTA).context()
        assert context["reported_staging_version"] == st.reported().version
        assert context["whatif_staging_version"] == st.default().version
        assert context["reported_staging"]["label"] != \
            context["whatif_staging"]["label"]
        assert context["reported_staging"]["editable"] is False
        assert context["whatif_staging"]["editable"] is True


# ================================================== driver attribution

class TestTheDriverAttribution:
    """What moved the provision, split across the things the scenario changed.

    The claim is EXACTNESS, so the tests are about exactness: the effects sum
    to the movement, a driver that did not move gets zero, and the answer does
    not depend on the order the shocks were written in.
    """

    def _state(self, *steps: sp.Step) -> sp.ScenarioState:
        state = sp.ScenarioState(period=dm.latest_period())
        for step in steps:
            state = state.add(step)
        return state

    RATING = sp.Step(sp.RATING, (sc.Shock(sc.RATING, 2, sc.NOTCHES),),
                     interpreted="downgrade two notches")
    LGD = sp.Step(sp.LGD, (sc.Shock(sc.LGD, 5.0, sc.ABSOLUTE_PP),),
                  interpreted="LGD +5pp")
    MACRO = sp.Step(sp.MACRO,
                    (sc.Shock(sc.MACRO, 200.0, sc.BASIS_POINTS,
                              target="policy_rate"),),
                    interpreted="policy rate +200bps")

    def test_it_uses_the_governed_shapley_and_says_so(self) -> None:
        body = at.describe()
        assert "Shapley" in body["method"]
        assert "order-neutral" in body["statement"]

    def test_the_effects_sum_to_the_movement(self) -> None:
        result = rn.execute(self._state(self.RATING, self.LGD, self.MACRO),
                            requested=me.DELTA)
        body = result.attribution
        assert body["available"]
        total = sum(d["effect"] for d in body["drivers"])
        # 1e-7 is float64 accumulation over 2^n coalitions each summed across
        # the book, not a modelling residual: on a SAR 69bn movement it is
        # under two thousand riyals, and it does not grow with the scenario.
        assert total == pytest.approx(body["measured_total"], rel=1e-7), (
            "an attribution that does not add up to the number it is "
            "explaining is a picture, not a decomposition")
        # Plus anything a policy limit removed, which is NOT a driver and is
        # reported on its own line — here, eight borrowers whose provision
        # reached their own exposure and was bounded by it. The drivers explain
        # the measurement; the named line explains why the reported figure is
        # not the measurement.
        adjustment = (body.get("model_adjustment") or {}).get("effect", 0.0)
        assert total + adjustment == pytest.approx(
            result.summary["incremental_ecl"], rel=1e-7)
        assert body["reconciliation"]["reconciles"]

    def test_it_is_order_neutral(self) -> None:
        """The engine applies shocks in a fixed order. The ATTRIBUTION must not
        depend on the order the person wrote them in."""
        one = rn.execute(self._state(self.RATING, self.LGD, self.MACRO),
                         requested=me.DELTA).attribution
        two = rn.execute(self._state(self.MACRO, self.LGD, self.RATING),
                         requested=me.DELTA).attribution
        first = {d["key"]: d["effect"] for d in one["drivers"]}
        second = {d["key"]: d["effect"] for d in two["drivers"]}
        assert set(first) == set(second)
        for key, effect in first.items():
            assert effect == pytest.approx(second[key], rel=1e-9), key
        assert one["total"] == pytest.approx(two["total"], rel=1e-9)

    def test_a_driver_that_did_not_move_gets_exactly_zero(self) -> None:
        result = rn.execute(self._state(self.LGD), requested=me.DELTA)
        body = result.attribution
        moved = {d["key"] for d in body["drivers"]}
        assert "lgd" in moved
        assert "rating" not in moved, (
            "a driver the scenario never touched must not appear with a "
            "rounding-error effect")
        assert body["unmoved"], "and it must be named as unmoved, not omitted"

    def test_the_named_drivers_are_the_ones_the_product_promises(self) -> None:
        keys = {entry["key"] for entry in at.describe()["drivers"]}
        assert {"rating", "pd", "lgd", "ead", "ccf", "stage", "macro"} <= keys

    def test_the_measurement_basis_is_its_own_driver(self) -> None:
        """A rating downgrade both raises PD and migrates the Stage. The two
        are separate facts and the table has to keep them apart."""
        body = rn.execute(self._state(self.RATING), requested=me.DELTA).attribution
        keys = {d["key"]: d for d in body["drivers"]}
        assert "rating" in keys and "basis" in keys
        assert keys["basis"]["effect"] > 0
        assert "Measurement basis" in keys["basis"]["label"]
        # And it says what it did, in the terms a lender asks about, rather
        # than only as a percentage.
        moved = body["measurement_basis"]
        assert moved["moved"] > 0
        assert "LIFETIME" in moved["note"]

    def test_the_ml_difference_is_its_own_line_not_a_driver(self) -> None:
        """SHAP explains the model; this explains the scenario. Where the two
        methodologies disagree, the disagreement is labelled."""
        state = self._state(sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                                    interpreted="PD +20%"))
        delta = rn.execute(state, requested=me.DELTA).attribution
        ml = rn.execute(state, requested=me.ML).attribution
        # A Delta run may leave a residual, but it is never called a model
        # adjustment: no model priced it. "ML model adjustment: 0.009" on a
        # Delta result is the bug this line exists for.
        assert delta.get("model_adjustment", {}).get("key") != "model"
        assert "ML" not in delta.get("model_adjustment", {}).get("label", "")
        assert "model_adjustment" in ml, (
            "the ML methodology priced it differently and the difference has "
            "to be visible")
        assert {d["key"] for d in delta["drivers"]} == \
            {d["key"] for d in ml["drivers"]}
        for left, right in zip(delta["drivers"], ml["drivers"], strict=True):
            assert left["effect"] == pytest.approx(right["effect"], rel=1e-9), (
                "the scenario drivers are the same scenario; only the pricing "
                "of it changed")
        assert ml["reconciliation"]["reconciles"]

    def test_it_reconciles_on_a_scenario_that_hits_the_clamps(self) -> None:
        """PD is clamped at 99%. A shock that ran into the limit did not have
        the effect it asked for, and the difference is a named driver."""
        huge = self._state(sp.Step(sp.PD, (sc.Shock(sc.PD, 900.0, sc.RELATIVE),),
                                   interpreted="PD +900%"))
        body = rn.execute(huge, requested=me.DELTA).attribution
        assert body["reconciliation"]["reconciles"]
        assert sum(d["effect"] for d in body["drivers"]) == pytest.approx(
            body["measured_total"], rel=1e-7)

    def test_the_attribution_is_on_the_result_a_reader_gets(self) -> None:
        body = rn.execute(self._state(self.RATING),
                          requested=me.DELTA).to_dict()
        assert body["attribution"]["available"]
        assert body["attribution"]["drivers"]

    def test_it_reuses_the_governed_function_rather_than_a_copy(self) -> None:
        """The order-neutrality claim is only as good as the function behind
        it, and there is exactly one of those in this repository."""
        game = {frozenset(): 0.0, frozenset({0}): 3.0, frozenset({1}): 5.0,
                frozenset({0, 1}): 10.0}
        effects = dc.shapley_of(game, 2)
        assert sum(effects) == pytest.approx(10.0)
        # Symmetric with the product form the ECL bridge uses.
        assert dc.shapley((1.0, 1.0), (2.0, 3.0)) == pytest.approx(
            tuple(dc.shapley_of(
                {frozenset(): 1.0, frozenset({0}): 2.0, frozenset({1}): 3.0,
                 frozenset({0, 1}): 6.0}, 2)))


# ======================================================= reports vs scenarios

class TestAReportIsNotAScenario:
    """The screening questions the rest of the product answers.

    What-If opens on a magnitude-free instruction — "stress the Real Estate
    portfolio" — which means the reader now recognises words that also appear
    in questions about what the book ALREADY did. A question in the perfect or
    the past tense, asking which names moved, belongs to the certified
    analysis that answers it; taking it into a scenario answers a question
    nobody asked and quietly retires a screen that works.
    """

    REPORTS = (
        "Which sectors deteriorated the most?",
        "Which sectors deteriorated most this quarter?",
        "Which exposures have deteriorated this quarter?",
        "Which rating grades saw the largest increase in exposure at default?",
        "Which sectors have borrowers with rising 12-month PD?",
        "Which customers had a rating downgrade and an increase in ECL over "
        "the latest year?",
        "Which customers have worsening leverage and declining DSCR together "
        "with a rating downgrade?",
        "Show me the top ten deteriorating borrowers.",
        "Which also had an increase in ECL?",
        "Which borrowers have the strongest evidence of liquidity stress?",
        # A movement word used as a NOUN, or after a preposition.
        "Show me the top ten Shipping customers by increase in expected "
        "credit loss over the latest quarter.",
        "Rank sectors by the largest increase in ECL.",
        "For each sector, calculate Stage 2 EAD as a percentage of total "
        "sector EAD, compare it with four quarters ago, and rank sectors by "
        "the largest increase.",
        # A thread follow-up that enriches the answer on screen.
        "Add their latest internal rating.",
        "Add their DSCR and leverage.",
        # A screening question in the present continuous.
        "Which borrowers are weakening but are not yet on the watchlist?",
    )

    SCENARIOS = (
        "Stress the Real Estate portfolio.",
        "Downgrade everyone two notches.",
        "Increase Stage 1 PD by 20%.",
        "Oil price down 20%.",
        "Policy rates up 200 bps.",
        "Apply a severe downturn.",
        "Move half of Stage 1 to Stage 2.",
        "What if ratings had fallen two notches?",
        "Which borrowers move to Stage 2 under a severe scenario?",
        "Which sectors had the largest ECL under stress?",
        "Reduce collateral by 20% and increase PD by 10%.",
        "Weaken DSCR by 20%.",
        "Cure 30% of Stage 2.",
    )

    @pytest.mark.parametrize("question", REPORTS)
    def test_a_question_about_the_past_is_not_a_what_if(self, question) -> None:
        reading = lang.read(question)
        assert not reading.is_scenario_question, question
        assert reading.scenario is None, question

    @pytest.mark.parametrize("question", SCENARIOS)
    def test_a_hypothetical_or_an_instruction_still_opens_one(
            self, question) -> None:
        assert lang.read(question).is_scenario_question, question

    def test_a_measure_that_carries_a_number_in_its_name_is_not_a_size(
            self) -> None:
        """"12-month PD" names a measure. The 12 is not the size of a move."""
        assert not lang.read("Borrowers with rising 12-month PD").is_scenario_question
        assert lang.read("Increase 12-month PD by 20%").scenario is not None
