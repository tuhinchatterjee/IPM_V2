"""The corporate universe keeps B1's promises. B1, B3.

These are the claims a reader of the documentation is entitled to check, so
they are asserted against the built data rather than against the constants
that were supposed to produce it. A test that reads ENTITY_COUNT and asserts
it is 3,800 proves the constant, not the universe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.corporate import ORIGIN
from backend.corporate import domains as domains_mod
from backend.corporate import universe as universe_mod


class TestScale:
    def test_at_least_3200_distinct_borrowers(self, universe):
        master = universe["corporate_customer_master"]
        assert master["borrower_id"].nunique() >= 3_200

    def test_inside_the_suggested_target_band(self, universe):
        count = universe["corporate_customer_master"]["borrower_id"].nunique()
        assert 3_500 <= count <= 4_000

    def test_sixteen_quarterly_snapshots(self, universe):
        assert len(universe.quarters) >= 16

    def test_window_runs_q3_2022_to_q2_2026(self, universe):
        assert universe.quarters[0] == "Q3 2022"
        assert universe.quarters[-1] == "Q2 2026"

    def test_every_quarter_carries_over_3000_active_borrowers(self, universe):
        counts = (universe["corporate_customer_master"]
                  .groupby("period")["borrower_id"].nunique())
        assert counts.min() > 3_000, (
            f"smallest quarter has {counts.min()} borrowers; B1 requires more "
            "than 3,000 in every quarter")

    def test_borrower_ids_are_stable_across_time(self, universe):
        """A borrower present in two quarters is the SAME borrower.

        The failure this catches is a generator that re-draws identity per
        quarter: every panel measure - a rating migration, a stage move, an
        exposure trend - becomes meaningless if the id does not identify.
        """
        master = universe["corporate_customer_master"]
        varying = (master.groupby("borrower_id")[
            ["legal_name", "sector", "segment", "cr_number"]].nunique() > 1)
        assert not varying.any().any(), (
            "these borrowers change identity between quarters:\n"
            f"{varying[varying.any(axis=1)]}")

    def test_entries_and_exits_both_happen(self, universe):
        master = universe["corporate_customer_master"]
        span = master.groupby("borrower_id")["period"].agg(["min", "max"])
        assert (span["min"] != universe.quarters[0]).sum() > 0, "no entries"
        assert (span["max"] != universe.quarters[-1]).sum() > 0, "no exits"


class TestOrigin:
    def test_every_dataset_declares_synthetic_origin(self, universe):
        missing = [name for name, frame in universe.frames.items()
                   if "origin" not in frame.columns]
        assert missing == [], f"no origin column on: {missing}"

    def test_every_row_carries_synthetic_demo(self, universe):
        for name, frame in universe.frames.items():
            values = set(frame["origin"].unique())
            assert values == {ORIGIN}, f"{name} carries origins {values}"


class TestDomains:
    def test_nineteen_domains(self):
        assert len(domains_mod.DOMAINS) == 19

    def test_b3_names_all_present(self):
        expected = {
            "CORPORATE CUSTOMER MASTER", "CORPORATE RATINGS",
            "CORPORATE FACILITIES / EXPOSURE", "CORPORATE IFRS 9",
            "CORPORATE DPD / DELINQUENCY", "CORPORATE FINANCIALS",
            "CORPORATE COVENANTS", "CORPORATE COLLATERAL",
            "CORPORATE GUARANTEES", "CORPORATE LIMITS / LARGE EXPOSURES",
            "CORPORATE WATCHLIST / QUALITATIVE SIGNALS",
            "CORPORATE RESTRUCTURING / FORBEARANCE",
            "CORPORATE PROFITABILITY / RAROC",
            "CORPORATE OWNERSHIP & CONTROL GRAPH",
            "CORPORATE SUPPLY CHAIN GRAPH", "CORPORATE EXPOSURE NETWORK",
            "CORPORATE CONNECTED COUNTERPARTY GRAPH",
            "CORPORATE ENTITY RESOLUTION", "CORPORATE GRAPH DATA QUALITY",
        }
        assert {d.name for d in domains_mod.DOMAINS} == expected

    def test_each_dataset_has_exactly_one_owning_domain(self):
        seen: dict[str, str] = {}
        for domain in domains_mod.DOMAINS:
            for dataset in domain.datasets:
                assert dataset not in seen, (
                    f"{dataset} claimed by {seen[dataset]} and {domain.name}")
                seen[dataset] = domain.name

    def test_authority_lookup_names_the_owner(self):
        assert domains_mod.authority_for("corporate_ecl").name == (
            "CORPORATE IFRS 9")
        assert domains_mod.authority_for("corporate_dpd").name == (
            "CORPORATE DPD / DELINQUENCY")

    def test_unknown_purpose_raises_with_the_known_list(self):
        with pytest.raises(KeyError) as caught:
            domains_mod.authority_for("corporate_vibes")
        assert "corporate_ecl" in str(caught.value)


class TestDeterminism:
    def test_two_builds_are_identical(self):
        first = universe_mod.build(periods=universe_mod.QUARTERS[:3])
        second = universe_mod.build(periods=universe_mod.QUARTERS[:3])
        for name in first.frames:
            assert first[name].equals(second[name]), f"{name} differs"

    def test_a_different_seed_gives_a_different_universe(self):
        first = universe_mod.build(periods=universe_mod.QUARTERS[:2])
        other = universe_mod.build(periods=universe_mod.QUARTERS[:2],
                                   seed=universe_mod.SEED + 1)
        assert not first["corporate_ratings"].equals(
            other["corporate_ratings"])


class TestCreditCoherence:
    """The domains agree with each other, because they share one latent state."""

    def test_stage_3_borrowers_are_in_default_or_ninety_days_past_due(
            self, universe):
        ifrs9 = universe["corporate_ifrs9"]
        stage3 = ifrs9[ifrs9["stage"] == 3]
        assert (stage3["default_flag"] | (stage3["current_dpd"] >= 90)).all()

    def test_stage_1_borrowers_have_no_sicr_trigger(self, universe):
        ifrs9 = universe["corporate_ifrs9"]
        assert not ifrs9.loc[ifrs9["stage"] == 1, "sicr_flag"].any()

    def test_the_default_grade_is_only_used_for_defaults(self, universe):
        """D is an OUTCOME, not a PD band.

        A scale that grades a 40% PD as "D" makes the default rate
        unmeasurable, because the grade and the outcome stop being separate
        facts.
        """
        ratings = universe["corporate_ratings"].merge(
            universe["corporate_ifrs9"][["borrower_id", "period",
                                         "default_flag"]],
            on=["borrower_id", "period"])
        graded_d = ratings["internal_rating"] == "D"
        assert (graded_d == ratings["default_flag"]).all()

    def test_worse_ratings_carry_higher_pd(self, universe):
        ifrs9 = universe["corporate_ifrs9"].merge(
            universe["corporate_ratings"][["borrower_id", "period",
                                           "internal_rating_numeric"]],
            on=["borrower_id", "period"])
        by_grade = ifrs9.groupby("internal_rating_numeric")["pd_12m"].median()
        performing = by_grade.loc[by_grade.index < 14]
        assert performing.is_monotonic_increasing, performing.to_dict()

    def test_the_cycle_is_visible_in_the_stage_mix(self, universe):
        ifrs9 = universe["corporate_ifrs9"]
        share = (ifrs9.groupby("period", sort=False)["stage"]
                 .apply(lambda s: float((s >= 2).mean())))
        peak = share["Q3 2022"]
        trough = share.max()
        assert trough > peak * 1.5, (
            "the downturn should be visible: Stage 2+3 share moves from "
            f"{peak:.1%} to {trough:.1%}")

    def test_ecl_never_exceeds_exposure(self, universe):
        ifrs9 = universe["corporate_ifrs9"]
        assert (ifrs9["final_ecl"] <= ifrs9["ead"] + 1e-6).all()

    def test_ecl_coverage_is_zero_where_there_is_no_exposure(self, universe):
        ifrs9 = universe["corporate_ifrs9"]
        assert (ifrs9.loc[ifrs9["ead"] == 0, "ecl_coverage"] == 0).all()

    def test_undrawn_plus_drawn_never_exceeds_the_limit(self, universe):
        facilities = universe["corporate_facilities"]
        total = facilities["drawn_exposure"] + facilities["undrawn_commitment"]
        assert (total <= facilities["limit_amount"] + 1e-6).all()

    def test_ead_lies_between_drawn_and_the_full_limit(self, universe):
        facilities = universe["corporate_facilities"]
        assert (facilities["ifrs9_ead"] >= facilities["drawn_exposure"]
                - 1e-6).all()
        assert (facilities["ifrs9_ead"] <= facilities["limit_amount"]
                + 1e-6).all()


class TestCovenants:
    def test_headroom_sign_matches_the_breach_flag_in_both_directions(
            self, universe):
        covenants = universe["corporate_covenants"]
        assert ((covenants["headroom_pct"] < 0)
                == covenants["breach_flag"]).all()

    def test_maximum_covenants_breach_when_observed_exceeds_threshold(
            self, universe):
        covenants = universe["corporate_covenants"]
        maxima = covenants[covenants["direction"] == "MAXIMUM"]
        assert ((maxima["observed_value"] > maxima["threshold"])
                == maxima["breach_flag"]).all()

    def test_minimum_covenants_breach_when_observed_falls_below(
            self, universe):
        covenants = universe["corporate_covenants"]
        minima = covenants[covenants["direction"] == "MINIMUM"]
        assert ((minima["observed_value"] < minima["threshold"])
                == minima["breach_flag"]).all()

    def test_breaches_rise_through_the_downturn(self, universe):
        rate = (universe["corporate_covenants"]
                .groupby("period", sort=False)["breach_flag"].mean())
        assert rate["Q3 2022"] < 0.10, "too many breaches at the top of cycle"
        assert rate.max() > rate["Q3 2022"] * 2

    def test_a_waiver_never_clears_the_breach(self, universe):
        """A waived breach is still a breach.

        Netting a waiver off the flag would make "how many covenants breached"
        and "how many breaches were waived" the same number, and the second
        question would become unanswerable.
        """
        covenants = universe["corporate_covenants"]
        waived = covenants[covenants["waiver_granted"]]
        assert waived["breach_flag"].all()

    def test_tests_are_against_a_statement_that_was_already_published(
            self, universe):
        covenants = universe["corporate_covenants"]
        assert (pd.to_datetime(covenants["tested_on_statement_date"])
                <= pd.to_datetime(covenants["period_end_date"])).all()


class TestFinancialsAndStaleness:
    def test_statements_are_annual_per_borrower(self, universe):
        financials = universe["corporate_financials"]
        duplicated = financials.duplicated(["borrower_id", "fiscal_year"])
        assert not duplicated.any()

    def test_publication_always_lags_the_statement_date(self, universe):
        financials = universe["corporate_financials"]
        assert (pd.to_datetime(financials["statement_published_date"])
                > pd.to_datetime(financials["financial_statement_date"])).all()

    def test_leverage_is_consistent_with_debt_over_ebitda(self, universe):
        """Recomputable from the published components, to within rounding.

        A RELATIVE tolerance, not an absolute one. Debt, EBITDA and leverage
        are each published to two decimals, and the ratio of two rounded
        numbers is not the rounded ratio: where EBITDA is small, a hundredth
        of rounding on the denominator moves the quotient by more than a
        hundredth. Asserting an absolute tolerance would be asserting
        something arithmetic does not offer.
        """
        financials = universe["corporate_financials"]
        positive = financials[financials["ebitda"] > 0].head(2_000)
        implied = positive["debt"] / positive["ebitda"]
        assert np.allclose(implied, positive["leverage"], rtol=0.005,
                           atol=0.01)

    def test_the_balance_sheet_balances(self, universe):
        financials = universe["corporate_financials"]
        assert np.allclose(
            financials["total_assets"],
            financials["total_liabilities"] + financials["book_equity"],
            atol=0.05)


class TestCollateralAndLimits:
    def test_eligible_value_never_exceeds_market_value(self, universe):
        collateral = universe["corporate_collateral"]
        assert (collateral["collateral_eligible_value"]
                <= collateral["collateral_market_value"] + 1e-6).all()

    def test_some_valuations_are_genuinely_overdue(self, universe):
        """Stale security has to be findable.

        The first version drew valuation age uniformly INSIDE the revaluation
        interval, which makes an overdue valuation arithmetically impossible
        and hides the collateral finding a credit officer most needs.
        """
        collateral = universe["corporate_collateral"]
        overdue = collateral["valuation_overdue"].mean()
        assert 0.05 < overdue < 0.45, f"overdue share is {overdue:.1%}"

    def test_the_capital_reference_is_labelled_unverified(self, universe):
        limits = universe["corporate_limits"]
        assert limits["parameter_caveat"].str.contains(
            "UNVERIFIED REGULATORY PARAMETER").all()

    def test_group_utilisation_is_not_computed_before_the_graph_runs(
            self, universe):
        """B2. The limits domain must not invent a group.

        "The group" is a derived answer that depends on how connectedness was
        defined. A number written here before the graph has been asked would
        make this domain quietly authoritative over a question nobody has put.
        """
        limits = universe["corporate_limits"]
        assert limits["group_utilisation_pct"].isna().all()
        assert (limits["group_utilisation_status"]
                == "NOT YET COMPUTED").all()


class TestProfitability:
    def test_raroc_follows_from_its_own_components(self, universe):
        profitability = universe["corporate_profitability"].head(2_000)
        with_capital = profitability[profitability["regulatory_capital"] > 0]
        implied = (with_capital["net_profit"]
                   / with_capital["regulatory_capital"] * 100)
        assert np.allclose(implied, with_capital["raroc_pct"], atol=0.05)

    def test_the_methodology_is_stated_on_every_row(self, universe):
        profitability = universe["corporate_profitability"]
        assert profitability["methodology"].str.contains("B55").all()

    def test_weaker_stages_consume_more_capital(self, universe):
        profitability = universe["corporate_profitability"]
        weights = profitability.groupby("stage")["risk_weight_applied"].max()
        assert weights.is_monotonic_increasing
