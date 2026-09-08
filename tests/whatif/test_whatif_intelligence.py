"""
The four intelligence layers that sit around the What-If engine.

Product knowledge, scenario plausibility, the macro lab and the written
interpretation are all places where the product SAYS something rather than
computes something, and every one of them is a place a plausible sentence can
be wrong without looking wrong. So the tests here are mostly about refusal:
what each layer declines to claim, and what it says instead.
"""

from __future__ import annotations

import pytest

from backend.whatif import comparison as cp
from backend.whatif import domain as dm
from backend.whatif import macro as mc
from backend.whatif import macrolab as ml
from backend.whatif import narrative as nr
from backend.whatif import plausibility as pl
from backend.whatif import product as pr
from backend.whatif import steps as sp

# ================================================= the written interpretation


class TestTheEvidenceCheck:
    """No number reaches a reader that was not in the evidence packet."""

    PACKET = {
        "RESULT": {"baseline_ecl": 1240.5, "whatif_ecl": 1631.2,
                   "absolute_change": 390.7, "percentage_change": 31.49,
                   "borrowers": 3244},
        "DRIVERS": [{"driver": "Probability of default", "share_pct": 60.4}],
    }

    def test_prose_drawn_from_the_packet_passes(self) -> None:
        good = ["Expected credit loss rises from SAR 1,240.5m to SAR 1,631.2m, "
                "an increase of SAR 390.7m or 31.49% across 3,244 borrowers."]
        assert nr.check(good, self.PACKET) == []

    def test_a_figure_the_packet_does_not_carry_is_caught(self) -> None:
        bad = ["Expected credit loss rises to SAR 1,631.2m, with 412 borrowers "
               "migrating and a peak exposure of SAR 9,999m."]
        found = nr.check(bad, self.PACKET)
        assert "412" in found
        assert "9999" in found
        assert "1631.2" not in found

    def test_a_rounded_form_of_a_known_figure_is_the_same_figure(self) -> None:
        """A writer may say 31.5% for 31.49%. That is prose, not invention."""
        rounded = ["Provisions rise 31.5%, or roughly SAR 391m."]
        assert nr.check(rounded, self.PACKET) == []

    def test_the_small_integers_of_ordinary_prose_are_not_figures(self) -> None:
        ordinary = ["Stage 2 exposure grew, IFRS 9 measurement moved to a "
                    "lifetime basis, and 3 of the drivers were material."]
        assert nr.check(ordinary, self.PACKET) == []

    def test_the_system_prompt_states_the_rule_in_those_words(self) -> None:
        assert "THE EVIDENCE PACKET BELOW IS THE ONLY THING YOU KNOW" in nr._SYSTEM
        assert "may NOT estimate, infer, extrapolate" in nr._SYSTEM

    def test_it_forbids_stating_a_probability_of_the_scenario(self) -> None:
        """Plausibility is a comparison against history, never a forecast."""
        assert "probability of the scenario occurring" in nr._SYSTEM


class TestTheDescription:
    def test_it_names_the_evidence_the_writer_is_given(self) -> None:
        body = nr.describe()
        assert "RESULT" in body["evidence_keys"]
        assert "PLAUSIBILITY" in body["evidence_keys"]
        assert "DATA_LIMITATIONS" in body["evidence_keys"]

    def test_it_states_that_the_engine_calculates_and_the_model_explains(
            self) -> None:
        assert "The engine calculates; the model explains." in nr.describe()[
            "statement"]


# ===================================================== scenario plausibility


class TestThePlausibilityVerdicts:
    """Six controlled labels, and not a seventh invented in a sentence."""

    def test_the_labels_are_a_closed_set(self) -> None:
        labels = {pl.CONSISTENT, pl.PLAUSIBLE, pl.POCKETS, pl.SEVERE_OBSERVED,
                  pl.SEVERE_RECENT, pl.OUTSIDE}
        assert len(labels) == 6

    @staticmethod
    def _evidence(**kwargs) -> pl.Evidence:
        body = pl.Evidence(measure="pd_12m", label="12-month PD",
                           proposed=20.0, unit="%")
        for name, value in kwargs.items():
            setattr(body, name, value)
        return body

    def test_a_common_movement_reads_as_consistent(self) -> None:
        found, _ = pl.verdict(self._evidence(
            observations=52880, qoq_share=0.438, yoy_share=0.55,
            quarters_seen=["Q1 2024"] * 9))
        assert found == pl.CONSISTENT

    def test_a_movement_seen_only_in_pockets_is_not_called_ordinary(
            self) -> None:
        found, _ = pl.verdict(self._evidence(
            observations=52880, qoq_share=0.0031, yoy_share=0.012,
            quarters_seen=["Q1 2024", "Q2 2024"]))
        assert found == pl.POCKETS

    def test_a_window_with_no_observation_cannot_place_the_shock(self) -> None:
        found, because = pl.verdict(self._evidence(observations=0))
        assert found == pl.OUTSIDE
        assert "cannot be placed" in because

    def test_it_never_states_a_probability(self) -> None:
        for body in (self._evidence(observations=52880, qoq_share=0.438,
                                    quarters_seen=["Q1 2024"] * 9),
                     self._evidence(observations=52880, qoq_share=0.0031,
                                    quarters_seen=["Q1 2024", "Q2 2024"]),
                     self._evidence(observations=0)):
            _, because = pl.verdict(body)
            said = because.lower()
            assert "probability" not in said
            assert "likely to happen" not in said
            assert "chance" not in said
            assert "will happen" not in said


@pytest.mark.usefixtures("data_loaded")
class TestPlausibilityAgainstTheBook:
    @staticmethod
    def _pd_shock(relative_pct: float) -> dict:
        from backend.whatif import scenarios as sc

        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, relative_pct, sc.RELATIVE),),
                    interpreted=f"PD +{relative_pct:g}%"))
        return pl.assess(state)

    def test_a_small_shock_and_a_large_one_are_not_read_the_same(self) -> None:
        """The whole point: +20% and +2000% must not present identically."""
        pl.reset_cache()
        small = self._pd_shock(20.0)
        large = self._pd_shock(2000.0)
        assert small.get("available"), small.get("why")
        assert large.get("available"), large.get("why")
        assert small["verdict"] != large["verdict"]

    def test_a_larger_shock_is_never_read_as_more_ordinary(self) -> None:
        """Monotonic by construction: severity cannot fall as the shock grows."""
        pl.reset_cache()
        order = [pl.CONSISTENT, pl.PLAUSIBLE, pl.POCKETS, pl.SEVERE_OBSERVED,
                 pl.SEVERE_RECENT, pl.OUTSIDE]
        seen = [order.index(self._pd_shock(size)["verdict"])
                for size in (20.0, 200.0, 2000.0)]
        assert seen == sorted(seen), seen

    def test_it_reports_the_window_it_compared_against(self) -> None:
        pl.reset_cache()
        body = self._pd_shock(20.0)
        assert body.get("available"), body.get("why")
        assert body.get("window")


# ================================================================ macro lab


class TestTheMacroLab:
    def test_the_three_sources_are_labelled_wherever_they_appear(self) -> None:
        body = ml.describe()
        assert {s["source"] for s in body["sources"]} == {
            ml.REFERENCE, ml.EMPIRICAL, ml.USER}
        assert "never called required, regulatory, approved or empirical" in (
            body["statement"])

    def test_a_configured_sensitivity_reproduces_the_matrix(self) -> None:
        for variable in mc.VARIABLES:
            body = ml.configured(variable.key)
            assert body.source == ml.REFERENCE
            assert body.pd_response == pytest.approx(variable.pd_multiplier)

    def test_an_unknown_variable_names_the_ten(self) -> None:
        with pytest.raises(ml.MacroLabError) as raised:
            ml.estimate("the vibe of the market")
        assert "Unemployment Rate" in str(raised.value)

    def test_a_fit_it_cannot_make_is_never_recommended(self) -> None:
        body = ml.Fit(variable="gdp_growth", variable_name="GDP Growth Rate",
                      unit="percentage points", configured_pd_multiplier=1.10)
        body.strength = "insufficient"
        advice = ml.recommend(body)
        assert advice["recommends"] == ml.REFERENCE
        assert ml.EMPIRICAL not in advice["options"]

    def test_a_fit_running_the_wrong_way_is_explained_not_offered(
            self) -> None:
        body = ml.Fit(variable="equity_index", variable_name="Stock Market Index",
                      unit="percent", configured_pd_multiplier=1.05)
        body.strength = "weak in this window"
        body.points = 15
        body.implied_pd_multiplier = 0.617
        body.direction_agrees = False
        advice = ml.recommend(body)
        assert advice["recommends"] == ml.REFERENCE
        assert "OPPOSITE" in advice["because"]

    def test_the_small_sample_is_stated_rather_than_hidden(self) -> None:
        assert "sixteen quarterly observations" in ml.SMALL_SAMPLE


@pytest.mark.usefixtures("data_loaded")
class TestTheMacroLabAgainstTheBook:
    def test_every_governed_variable_can_be_estimated(self) -> None:
        """All ten carry an observed series, so all ten can be analysed."""
        for variable in mc.VARIABLES:
            body = ml.estimate(variable.key)
            assert body.points >= ml.MINIMUM_POINTS, variable.key
            assert body.series, variable.key

    def test_an_estimate_is_never_silently_substituted_for_the_configured_one(
            self) -> None:
        for variable in mc.VARIABLES:
            body = ml.estimate(variable.key)
            assert body.configured_pd_multiplier == pytest.approx(
                variable.pd_multiplier)
            assert ml.recommend(body)["recommends"] == ml.REFERENCE

    def test_the_policy_rate_estimate_is_on_a_credible_scale(self) -> None:
        """The unit mismatch this catches implied a PD multiplier of 46.

        The adverse unit is 200 basis points and the column is in percent, so
        differencing it raw shrank every observed move by a hundred and the
        fitted slope exploded.
        """
        body = ml.estimate("policy_rate")
        assert 0.2 < body.implied_pd_multiplier < 5.0

    def test_the_macro_cards_all_report_an_observed_series(self) -> None:
        body = mc.describe(dm.macro(), dm.latest_period())
        assert len(body["variables"]) == 10
        for card in body["variables"]:
            assert card["status"] == mc.OBSERVED, card["key"]
            assert card["observations"] == 16, card["key"]
            assert len(card["actions"]) == 3, card["key"]


# ========================================================= product knowledge


class TestProductKnowledge:
    def test_it_answers_from_the_live_configuration_not_a_written_page(
            self) -> None:
        body = pr.fields()
        assert {g["group"] for g in body["groups"]}
        assert body["field_count"] == sum(len(g["fields"])
                                          for g in body["groups"])
        # A field the engine cannot shock is never listed as shockable.
        assert 0 < body["shockable_count"] <= body["field_count"]

    def test_the_methodologies_it_describes_are_the_ones_that_run(self) -> None:
        from backend.whatif import methodology as me
        assert {m["value"] for m in pr.methodologies()["methods"]} == set(
            me.METHODS)

    def test_a_methodology_it_cannot_run_says_why_rather_than_vanishing(
            self) -> None:
        for method in pr.methodologies()["methods"]:
            if not method["available"]:
                assert method["unavailable_because"], method["value"]

    def test_the_system_prompt_forbids_inventing_a_capability(self) -> None:
        assert "invent" in pr._SYSTEM.lower()

    def test_every_intent_it_serves_has_composed_evidence(self) -> None:
        for intent in ("help", "data", "fields", "methodology"):
            body = pr.evidence(intent)
            assert body, intent
            written = pr._composed(intent, body)
            assert written, intent
            assert all(str(line).strip() for line in written), intent


# ========================================================= model comparison


class TestTheComparisonDoesNotRecommend:
    """Neither figure is the right one, and the product must not pick."""

    def test_it_says_what_neither_figure_is(self) -> None:
        body = cp.describe()
        said = body["statement"] + " " + body["both_directions"]
        assert "SAME shocked book" in said
        assert "one question away" in said

    def test_the_system_prompt_forbids_a_recommendation(self) -> None:
        assert "Do NOT recommend one methodology" in cp._SYSTEM
        assert "governance decision" in cp._SYSTEM

    def test_it_forbids_calling_either_one_more_accurate(self) -> None:
        assert "more accurate, more correct or better" in cp._SYSTEM

    def test_the_evidence_is_the_only_thing_the_writer_knows(self) -> None:
        assert "THE EVIDENCE PACKET BELOW IS THE ONLY THING YOU KNOW" in (
            cp._SYSTEM)

    def test_agreement_is_stated_rather_than_dressed_as_a_difference(
            self) -> None:
        assert "If the two agree, say so plainly" in cp._SYSTEM


@pytest.mark.usefixtures("data_loaded")
class TestTheComparisonAgainstTheBook:
    @staticmethod
    def _state():
        from backend.whatif import scenarios as sc

        return sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    interpreted="PD +20%"))

    def test_it_prices_the_scenario_both_ways(self) -> None:
        from backend.whatif import methodology as me

        body = cp.compare(self._state())
        if not body.get("available"):
            pytest.skip(body.get("why", "one methodology is unavailable"))
        assert {r["method"] for r in body["rows"] if r["available"]} == set(
            me.METHODS)

    def test_the_figures_do_not_depend_on_the_direction_asked_from(
            self) -> None:
        """Only the phrasing follows the reader. The numbers do not."""
        from backend.whatif import methodology as me

        state = self._state()
        left = cp.compare(state, ran=me.DELTA)
        right = cp.compare(state, ran=me.ML)
        if not (left.get("available") and right.get("available")):
            pytest.skip("one methodology is unavailable")
        assert left["spread"] == pytest.approx(right["spread"])
        assert left["direction"] != right["direction"]
        assert left["ran"] != right["ran"]

    def test_it_locates_the_difference_rather_than_only_measuring_it(
            self) -> None:
        """A spread is where the useful part starts, not where it ends."""
        body = cp.compare(self._state())
        if not body.get("available") or body.get("agree"):
            pytest.skip("the two methodologies agreed here")
        assert body["by_sector"], "no sector split"
        assert body["borrowers"], "no borrowers named"

    def test_the_borrower_counts_account_for_the_matched_population(
            self) -> None:
        body = cp.compare(self._state())
        if not body.get("available"):
            pytest.skip("one methodology is unavailable")
        total = (body["borrowers_priced_higher_by_ml"]
                 + body["borrowers_priced_lower_by_ml"]
                 + body["borrowers_priced_the_same"])
        assert total == body["matched_borrowers"]

    def test_the_written_reading_states_no_figure_it_was_not_given(
            self) -> None:
        from backend.whatif import narrative as nr

        body = cp.compare(self._state())
        if not body.get("available"):
            pytest.skip("one methodology is unavailable")
        reading = cp.explain(body)
        assert nr.check([*reading["paragraphs"], reading["headline"]],
                        cp.packet(body)) == []

    def test_it_never_recommends_a_methodology_in_the_prose(self) -> None:
        body = cp.compare(self._state())
        if not body.get("available"):
            pytest.skip("one methodology is unavailable")
        said = " ".join(cp.explain(body)["paragraphs"]).lower()
        for word in ("recommend", "you should use", "more accurate",
                     "the better model", "the correct model"):
            assert word not in said, word

    def test_a_model_limit_reaches_the_reader(self) -> None:
        """A borrower outside what the model saw is a limit on the figure,
        not a footnote."""
        body = cp.compare(self._state())
        if not body.get("available"):
            pytest.skip("one methodology is unavailable")
        assert "out_of_distribution" in body
        if body["out_of_distribution"]:
            said = " ".join(cp.compose(body)["paragraphs"])
            assert "outside the range" in said
