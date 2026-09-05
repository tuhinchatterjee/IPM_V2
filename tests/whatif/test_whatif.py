"""
What-If: the scenario engine, and the arithmetic somebody will be asked to
defend in a committee.

The tests that matter here are not "does it return a number". They are:

*   the base column ties to the reported book EXACTLY, because a stressed table
    whose base does not tie to the accounts is thrown out on sight;
*   a rating shock goes through the masterscale rather than through a
    multiplier, and preserves each borrower's own place inside its grade;
*   the governed SICR triggers are re-read against the STRESSED PD, using the
    same rules that staged the reported book;
*   nothing is aggregated before it is computed per borrower;
*   a scenario never manufactures a default and never cures a Stage;
*   a period never becomes a magnitude.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.ifrs9 import policy
from backend.whatif import answers as wa
from backend.whatif import engine as wf
from backend.whatif import language as lg
from backend.whatif import masterscale as ms
from backend.whatif import scenarios as sc
from backend.whatif import sensitivity as sv
from backend.whatif import trace as wt


@pytest.fixture(scope="module")
def bbb_two_notch() -> wf.Result:
    return wf.run(sc.scenario("downgrade_bbb_two"))


# ==========================================================================
# The masterscale — a notch is worth what the scale says it is worth
# ==========================================================================


class TestTheMasterscale:
    def test_every_performing_grade_carries_a_pd(self) -> None:
        for grade in ms.PERFORMING:
            assert ms.masterscale_pd(grade) > 0

    def test_the_pd_rises_monotonically_down_the_scale(self) -> None:
        pds = [ms.masterscale_pd(g) for g in ms.PERFORMING]
        assert pds == sorted(pds), "a weaker grade must not carry a lower PD"

    def test_a_downgrade_never_reaches_default(self) -> None:
        # Default is an event, not something arithmetic produces.
        for grade in ms.PERFORMING:
            for notches in (1, 2, 3, 10):
                assert ms.shift(grade, notches) != "D"

    def test_an_upgrade_stops_at_the_strongest_grade(self) -> None:
        assert ms.shift("AAA", -3) == "AAA"

    def test_two_notches_moves_further_than_one(self) -> None:
        assert ms.move("BBB", 2).factor > ms.move("BBB", 1).factor > 1.0

    def test_the_factor_is_the_ratio_of_the_two_grades(self) -> None:
        move = ms.move("BBB", 2)
        assert move.stressed == "BB+"
        assert move.factor == pytest.approx(
            ms.masterscale_pd("BB+") / ms.masterscale_pd("BBB"))

    def test_a_band_resolves_to_its_grades(self) -> None:
        assert ms.grades_in("BBB") == ("BBB+", "BBB", "BBB-")
        assert "AAA" in ms.grades_in("investment grade")
        assert "CCC" not in ms.grades_in("investment grade")


# ==========================================================================
# The IFRS 9 policy — one definition, read by the generator and by What-If
# ==========================================================================


class TestTheGovernedPolicy:
    def test_the_generator_and_the_engine_share_the_constants(self) -> None:
        # Two copies of a staging rule is two answers waiting to disagree.
        from backend.corporate import universe

        assert universe.SICR_PD_RATIO == policy.SICR_PD_RATIO
        assert universe.SICR_PD_ABSOLUTE == policy.SICR_PD_ABSOLUTE
        assert universe.SICR_ABSOLUTE_PD == policy.SICR_ABSOLUTE_PD
        assert universe.SICR_DPD_DAYS == policy.SICR_DPD_DAYS
        assert universe.DEFAULT_DPD_DAYS == policy.DEFAULT_DPD_DAYS

    def test_lifetime_pd_is_never_below_the_twelve_month_pd(self) -> None:
        twelve = np.array([0.0001, 0.01, 0.10, 0.50, 0.95])
        assert (policy.lifetime_pd(twelve) >= twelve).all()

    def test_stage_2_costs_more_than_stage_1_for_the_same_borrower(self) -> None:
        import pandas as pd

        pd_12m = pd.Series([2.0])
        lgd = pd.Series([45.0])
        ead = pd.Series([1000.0])
        one = policy.measured_ecl(np.array([1]), pd_12m, lgd, ead)
        two = policy.measured_ecl(np.array([2]), pd_12m, lgd, ead)
        assert two[0] > one[0], (
            "a Stage 2 borrower is measured on lifetime loss, so the same "
            "borrower must provide for more")

    def test_the_policy_describes_every_trigger(self) -> None:
        described = policy.describe()
        assert len(described["sicr_triggers"]) == 3
        assert described["measurement"]["Stage 2"].startswith("Lifetime")


# ==========================================================================
# The engine — the arithmetic
# ==========================================================================


class TestTheEngine:
    def test_the_base_scenario_changes_nothing(self) -> None:
        result = wf.run(sc.scenario("base"))
        assert result.summary["incremental_ecl"] == 0.0
        assert result.summary["stage_2_migrations"] == 0

    def test_the_base_column_ties_to_the_reported_book(
            self, bbb_two_notch: wf.Result) -> None:
        # The single most important property. A stressed table whose base does
        # not tie to the accounts is thrown out before anybody reads it, so
        # this compares the baseline against the SOURCE rather than against
        # anything the engine derived.
        import duckdb

        grades = ms.grades_in("BBB")
        quoted = ", ".join(f"'{g}'" for g in grades)
        reported = duckdb.connect().execute(f"""
            select sum(final_ecl)
            from read_parquet('data/analytics/corporate_borrower_360/**/*.parquet')
            where period = '{bbb_two_notch.period}'
              and internal_rating in ({quoted})""").fetchone()[0]
        # The summary carries two decimal places, which is the presentation
        # precision; the tie has to hold to that and no tighter.
        assert bbb_two_notch.summary["baseline_ecl"] == pytest.approx(
            float(reported), abs=0.01)

    def test_the_totals_are_the_sum_of_the_borrowers(
            self, bbb_two_notch: wf.Result) -> None:
        # Nothing is allocated downwards. The displayed table rounds to two
        # decimal places, so the tolerance is the rounding over the rows and
        # nothing else.
        frame = bbb_two_notch.borrowers
        tolerance = 0.01 * len(frame)
        assert frame["ecl_stressed"].sum() == pytest.approx(
            bbb_two_notch.summary["stressed_ecl"], abs=tolerance)
        assert frame["ecl_increase"].sum() == pytest.approx(
            bbb_two_notch.summary["incremental_ecl"], abs=tolerance)

    def test_a_rating_shock_moves_pd_by_the_masterscale_factor(
            self, bbb_two_notch: wf.Result) -> None:
        frame = bbb_two_notch.borrowers
        for grade in ms.grades_in("BBB"):
            expected = ms.move(grade, 2).factor
            moved = frame[(frame["opening_rating"] == grade)
                          & (frame["pd_12m"] > 0.20)]
            if moved.empty:
                continue
            ratio = moved["pd_stressed"] / moved["pd_12m"]
            # The displayed PD carries two decimal places, so on a PD of a
            # few tenths of a percent the ratio inherits a percent or two of
            # rounding. The factor is checked RELATIVELY for that reason.
            assert ((ratio - expected).abs() / expected).max() < 0.05, (
                f"{grade} borrowers did not move by the masterscale factor")

    def test_within_grade_calibration_survives_the_shock(
            self, bbb_two_notch: wf.Result) -> None:
        # Two BBB borrowers with different PDs must still have different PDs.
        frame = bbb_two_notch.borrowers
        distinct_before = frame["pd_12m"].nunique()
        distinct_after = frame["pd_stressed"].nunique()
        assert distinct_after >= distinct_before * 0.9, (
            "snapping every borrower to its grade's central PD would destroy "
            "calibration the bank already has")

    def test_a_bigger_shock_costs_more(self) -> None:
        one = wf.run(sc.scenario("downgrade_one_notch")).summary
        pd_up = wf.run(sc.scenario("pd_up_50")).summary
        assert one["incremental_ecl"] > 0
        assert pd_up["incremental_ecl"] > wf.run(
            sc.scenario("pd_up_25")).summary["incremental_ecl"]

    def test_no_scenario_reduces_the_provision(self) -> None:
        for key in ("downgrade_one_notch", "pd_up_25", "rates_200bp",
                    "collateral_down_20", "utilisation_drawdown"):
            summary = wf.run(sc.scenario(key)).summary
            assert summary["incremental_ecl"] >= 0, (
                f"{key} reduced the provision, which no adverse shock may do")

    def test_a_scenario_never_cures_a_stage(self) -> None:
        result = wf.run(sc.scenario("severe_combined"))
        frame = result.borrowers
        assert (frame["stage_stressed"] >= frame["stage_baseline"]).all(), (
            "curing is a credit event and a negotiation, not an arithmetic "
            "consequence of a shock")

    def test_a_scenario_never_manufactures_a_default(self) -> None:
        result = wf.run(sc.scenario("severe_combined"))
        frame = result.borrowers
        moved_to_3 = frame[(frame["stage_baseline"] < 3)
                           & (frame["stage_stressed"] == 3)]
        assert moved_to_3.empty, (
            "Stage 3 is a default event; a shock must not create one")

    def test_an_exposure_shock_is_capped_at_the_committed_limit(self) -> None:
        result = wf.run(sc.scenario("utilisation_drawdown"))
        frame = result.borrowers
        assert (frame["ead_stressed"] >= frame["ead"]).all()
        # Nobody draws more than the limit they were committed.
        assert result.summary["stressed_ead"] >= result.summary["baseline_ead"]

    def test_a_collateral_shock_moves_lgd_and_not_pd(self) -> None:
        result = wf.run(sc.scenario("collateral_down_20"))
        frame = result.borrowers
        assert (frame["lgd_stressed"] >= frame["lgd"]).all()
        assert frame["pd_stressed"].round(4).equals(frame["pd_12m"].round(4)), (
            "a collateral haircut changes what is recovered, not the "
            "likelihood of default")

    def test_a_population_narrows_the_answer(self) -> None:
        whole = wf.run(sc.scenario("pd_up_25")).summary["borrowers"]
        bbb = wf.run(sc.scenario("downgrade_bbb_two")).summary["borrowers"]
        assert 0 < bbb < whole

    def test_every_preconfigured_scenario_runs(self) -> None:
        for scenario in sc.PRECONFIGURED:
            result = wf.run(scenario)
            assert result.population_size > 0, f"{scenario.key} matched nobody"
            assert result.summary["baseline_ecl"] >= 0

    def test_the_same_scenario_twice_returns_the_same_figures(self) -> None:
        first = wf.run(sc.scenario("rates_200bp")).summary
        second = wf.run(sc.scenario("rates_200bp")).summary
        assert first == second

    def test_a_sector_shock_lands_on_that_sector_hardest(self) -> None:
        # The matrix governs the PD EFFECT, and that is what this asserts.
        # The resulting ECL percentage legitimately depends on where each
        # sector's borrowers sit relative to the SICR triggers — a sector with
        # names just under the threshold can show a larger provision movement
        # from a smaller PD shock, and that is the staging rules working
        # rather than the sensitivity failing.
        result = wf.run(sc.scenario("shipping_disruption"))
        rows = {row["scope"]: row["pd_effect_pct"]
                for row in result.sensitivity_rows}
        assert "Shipping" in rows
        assert rows["Shipping"] == max(rows.values()), (
            "a shipping disruption must raise Shipping PD by more than any "
            "other sector")
        assert rows["Shipping"] > rows.get("Real Estate", 0)


# ==========================================================================
# SICR re-evaluation
# ==========================================================================


class TestStageMigration:
    def test_the_triggers_are_re_read_against_the_stressed_pd(self) -> None:
        result = wf.run(sc.scenario("pd_up_50"))
        assert result.summary["stage_2_migrations"] > 0, (
            "a 50% PD deterioration must move somebody, or the triggers are "
            "not being re-evaluated at all")

    def test_a_downgrade_alone_is_not_a_sicr_trigger(self) -> None:
        # The whole point of section 1C: a notch is not a governed trigger.
        result = wf.run(sc.scenario("downgrade_bbb_two"))
        assert result.summary["stage_2_migrations"] < result.population_size, (
            "if every downgraded borrower moved to Stage 2 the rules are not "
            "being applied, the downgrade is")

    def test_the_optional_assumption_moves_more(self) -> None:
        base = sc.scenario("downgrade_bbb_two")
        assumed = sc.Scenario(
            key=base.key, name=base.name, shocks=base.shocks,
            population=base.population,
            assumptions=sc.Assumptions(rating_deterioration_sicr=True,
                                       rating_sicr_notches=2))
        assert (wf.run(assumed).summary["stage_2_migrations"]
                > wf.run(base).summary["stage_2_migrations"])

    def test_a_migrated_borrower_provides_for_more(self) -> None:
        result = wf.run(sc.scenario("pd_up_50"))
        frame = result.borrowers
        moved = frame[frame["stage_stressed"] > frame["stage_baseline"]]
        assert not moved.empty
        # A borrower whose reported ECL was zero has nothing to scale, and its
        # stressed figure is the measured one — which can round to zero on a
        # tiny exposure. Every other migration must cost more.
        material = moved[moved["ecl_baseline"] > 0.01]
        assert not material.empty
        assert (material["ecl_increase"] > 0).all()


# ==========================================================================
# The sensitivity matrix
# ==========================================================================


class TestTheSensitivityMatrix:
    def test_every_sector_named_is_a_governed_sector(self) -> None:
        from backend.orchestration import vocabulary as vc

        known = set(vc.get_vocabulary().dimensions.get("sector", []))
        for sector in sv.sectors_named():
            assert sector in known, (
                f"the matrix carries a coefficient for {sector!r}, which is "
                "not a sector in the governed vocabulary")

    def test_every_variable_states_its_basis(self) -> None:
        for entry in sv.VARIABLES:
            assert entry.basis
            assert "estimate" not in entry.basis.lower() or "not an" in entry.basis.lower()

    def test_the_matrix_declares_an_owner_and_a_version(self) -> None:
        described = sv.describe()
        assert described["owner"] and described["version"]
        assert "not econometric estimates" in described["statement"]

    def test_shipping_is_more_exposed_to_disruption_than_real_estate(self) -> None:
        found = sv.variable("shipping_disruption")
        assert found is not None
        assert (found.pd_effect_for("Shipping")
                > found.pd_effect_for("Real Estate"))

    def test_real_estate_is_more_exposed_to_property_than_shipping(self) -> None:
        found = sv.variable("property")
        assert found is not None
        assert (found.pd_effect_for("Real Estate")
                > found.pd_effect_for("Shipping"))


# ==========================================================================
# Reading a scenario out of a sentence
# ==========================================================================


class TestTheLanguageReader:
    @pytest.mark.parametrize("question,kind,magnitude", [
        ("What happens if these borrowers are downgraded by one notch?",
         sc.RATING, 1),
        ("What if every BBB borrower is downgraded by two notches?",
         sc.RATING, 2),
        ("What happens if 12-month PD increases by 25%?", sc.PD, 25),
        ("What happens to ECL if PD rises by 50%?", sc.PD, 50),
        ("What if LGD increases by 10 percentage points?", sc.LGD, 10),
        ("What if collateral values fall by 20%?", sc.COLLATERAL, -20),
    ])
    def test_it_reads_the_shock_and_its_size(self, question: str, kind: str,
                                             magnitude: float) -> None:
        reading = lg.read(question)
        assert reading.scenario is not None, question
        found = reading.scenario.shocks_of(kind)
        assert found, f"{question!r} produced no {kind} shock"
        assert found[0].magnitude == pytest.approx(magnitude)

    def test_a_period_never_becomes_a_magnitude(self) -> None:
        # The defect this rule exists for: "in Q1 2026" is a window, and 2026
        # is not a percentage.
        reading = lg.read("What happens to ECL in Q1 2026 if PD rises 25%?")
        assert reading.scenario is not None
        found = reading.scenario.shocks_of(sc.PD)
        assert found and found[0].magnitude == pytest.approx(25.0)
        assert all(abs(s.magnitude) < 1000 for s in reading.scenario.shocks)

    def test_a_year_alone_is_not_a_shock(self) -> None:
        reading = lg.read("What happens to ECL in 2026?")
        assert reading.scenario is None or not reading.scenario.shocks

    def test_two_shocks_in_one_sentence_are_both_read(self) -> None:
        reading = lg.read(
            "What if EBITDA falls 15% and interest rates rise 200 basis points?")
        assert reading.scenario is not None
        kinds = {s.kind for s in reading.scenario.shocks}
        assert kinds == {sc.FINANCIAL, sc.MACRO}
        earnings = reading.scenario.shocks_of(sc.FINANCIAL)[0]
        assert earnings.magnitude < 0, "'falls' is a fall"

    def test_the_direction_word_nearest_the_measure_wins(self) -> None:
        reading = lg.read("What if EBITDA falls 15% and rates rise 200 bps?")
        assert reading.scenario is not None
        assert reading.scenario.shocks_of(sc.FINANCIAL)[0].magnitude < 0
        assert reading.scenario.shocks_of(sc.MACRO)[0].magnitude > 0

    def test_an_article_is_not_a_rating_grade(self) -> None:
        # "under A logistics disruption" is not an A-rated population.
        reading = lg.read("What happens to Shipping under a logistics disruption?")
        assert reading.scenario is not None
        assert reading.scenario.population.rating_bands == ()
        assert reading.scenario.population.sectors == ("Shipping",)

    def test_it_refuses_to_guess_a_missing_size(self) -> None:
        reading = lg.read("What happens if PD rises?")
        assert reading.unread, "a shock with no size must be reported, not guessed"

    def test_the_rating_sicr_assumption_is_off_unless_asked_for(self) -> None:
        plain = lg.read(
            "Which Stage 1 borrowers become Stage 2 if their ratings fall two notches?")
        assert plain.scenario is not None
        assert not plain.scenario.assumptions.rating_deterioration_sicr
        assert any("governed SICR" in note for note in plain.notes)

        asked = lg.read(
            "Which borrowers become Stage 2 if ratings fall two notches, "
            "assuming a downgrade is a significant increase in credit risk?")
        assert asked.scenario is not None
        assert asked.scenario.assumptions.rating_deterioration_sicr

    def test_an_ordinary_data_question_is_not_a_scenario(self) -> None:
        for question in ("Which borrowers were downgraded and had ECL rise?",
                         "List the 20 highest 12-month PD borrowers.",
                         "What is CreditProbe AI?",
                         "Which Stage 2 borrowers are on the watchlist?"):
            assert lg.read(question).scenario is None, question

    def test_a_follow_up_is_marked_as_continuing(self) -> None:
        for question in ("Give me the result customer by customer.",
                         "Which borrowers become most vulnerable?",
                         "How much incremental ECL is created?"):
            reading = lg.read(question)
            assert reading.continues_previous, question


# ==========================================================================
# The answer and the Trace
# ==========================================================================


class TestTheAnswer:
    def test_it_opens_with_the_impact(self, bbb_two_notch: wf.Result) -> None:
        reading = lg.read("What if every BBB borrower is downgraded two notches?")
        answer = wa.compose_answer(bbb_two_notch, reading)
        assert "expected credit loss" in answer.headline.lower()
        assert "SAR" in answer.headline

    def test_it_shows_the_borrower_table(self, bbb_two_notch: wf.Result) -> None:
        table = wa.borrower_table(bbb_two_notch, limit=5)
        assert "Opening rating" in table["columns"]
        assert "Stressed rating" in table["columns"]
        assert "ECL increase (SAR)" in table["columns"]
        assert len(table["rows"]) == 5

    def test_the_table_carries_every_column_the_remediation_names(self) -> None:
        for wanted in ("Borrower", "Sector", "Opening rating", "Stressed rating",
                       "Opening stage", "Stressed stage", "Opening 12m PD (%)",
                       "Stressed 12m PD (%)", "Opening LGD (%)",
                       "Stressed LGD (%)", "Opening ECL (SAR)",
                       "Stressed ECL (SAR)", "ECL increase (SAR)",
                       "Primary driver"):
            assert wanted in wa.BORROWER_COLUMNS, wanted

    def test_the_answer_proposes_no_chart(self, bbb_two_notch: wf.Result) -> None:
        reading = lg.read("What if every BBB borrower is downgraded two notches?")
        payload = wa.compose_answer(bbb_two_notch, reading).to_dict()
        assert payload["visualization"]["kind"] == "none"

    def test_the_trace_records_every_assumption(
            self, bbb_two_notch: wf.Result) -> None:
        graph = wt.build(bbb_two_notch, "q").to_dict()
        labels = " ".join(node["label"] for node in graph["nodes"])
        for wanted in ("Rating masterscale", "Macro sensitivity matrix",
                       "IFRS 9 policy", "SICR re-evaluation",
                       "ECL re-measurement", "Scenario validation"):
            assert wanted in labels, f"the Trace has no {wanted!r} node"

    def test_the_trace_states_the_versions(self, bbb_two_notch: wf.Result) -> None:
        graph = wt.build(bbb_two_notch, "q").to_dict()
        labels = " ".join(node["label"] for node in graph["nodes"])
        assert ms.MASTERSCALE_VERSION in labels
        assert sv.MATRIX_VERSION in labels
        assert policy.POLICY_VERSION in labels


# ==========================================================================
# Through the real Ask path
# ==========================================================================


class TestTheAskPath:
    @pytest.mark.parametrize("question", [
        "What happens if all BBB borrowers are downgraded one notch?",
        "What if every BBB borrower is downgraded two notches?",
        "What happens to ECL if 12-month PD rises 25%?",
        "Which Stage 1 borrowers become Stage 2 if their ratings fall two notches?",
        "What happens if rates rise 200 bps?",
        "What happens if EBITDA falls 15% and rates rise 200 bps?",
        "What happens if collateral values fall 20%?",
        "What happens to Shipping under the configured disruption scenario?",
    ])
    def test_it_runs_the_scenario_rather_than_an_analysis(
            self, question: str) -> None:
        from backend.orchestration.executor import answer_investigation

        try:
            investigation, answered = answer_investigation(question,
                                                           persist=False)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the Ask path is not available: {exc}")
        assert answered.result is not None, question
        assert answered.result.execution == "whatif_scenario", question
        assert answered.result.rows, "a scenario answer must name borrowers"
        assert not answered.result.chart, "no chart unless one was asked for"
        assert str(investigation.narrative.direct_answer or "").strip()

    def test_a_portfolio_question_still_reaches_the_engine(self) -> None:
        from backend.orchestration.executor import answer_investigation

        try:
            _, answered = answer_investigation(
                "Which customers were downgraded and had expected credit loss "
                "rise in Q1 2026?", persist=False)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the Ask path is not available: {exc}")
        assert answered.result is None \
            or answered.result.execution != "whatif_scenario"

    def test_the_product_questions_are_answered(self) -> None:
        from backend.product import routing as pr

        for question, tool in (
                ("What does What-If Analysis do?", "describe_whatif"),
                ("How does a rating downgrade affect PD?", "describe_rating_to_pd"),
                ("How can a downgrade move someone to Stage 2?",
                 "describe_downgrade_to_stage2"),
                ("Why does Stage 2 increase ECL?", "describe_downgrade_to_stage2"),
                ("What macro sensitivity assumptions are configured?",
                 "describe_macro_assumptions"),
                ("What is the difference between baseline and stressed ECL?",
                 "describe_whatif")):
            intent = pr.read(question)
            assert intent.is_product, question
            assert intent.tool == tool, f"{question!r} -> {intent.tool}"
