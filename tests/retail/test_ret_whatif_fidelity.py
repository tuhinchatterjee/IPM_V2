"""
What-If fidelity: every methodology the screen advertises is reachable in words,
and a conversation neither drops an instruction nor compounds a replaced one.

The screen lists twelve methodologies under "What this engine implements". That
list is generated from the engine's own contract, so it is always complete — but
it says nothing about whether a person can REACH each one by typing a sentence,
and that is the only way into this screen. Three of these gates exist because it
could not:

* `cutoff_replay` was advertised and unreachable. "Replay an application cutoff
  of 620 on personal finance" matched no shock pattern and was run as a scenario
  with no shocks — the published book, returned under the reader's question as
  though it were the answer.

* A narrowing follow-up dropped the shock it was narrowing. "Apply the same
  shock only to salary-transfer customers" kept the population and lost the 20%,
  so the answer was again the untouched book.

* The cutoff replay counted every product in its denominator regardless of which
  product the cutoff was asked about, turning "one in two personal-finance
  accounts" into "one in five accounts".

A screen that answers with the baseline is worse than one that refuses: a
refusal is visible and a baseline looks like a result.
"""

from __future__ import annotations

import pytest

from backend.retail import whatif as wif
from backend.retail import whatif_language as lang
from backend.retail.config import load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def snapshot(retail_book):
    return retail_book.latest()


MONTHS = ["2026-08"]

#: One sentence per advertised methodology, written the way a person would.
#: `staging_mode` and `cutoff_replay` are not shocks, so they are checked by the
#: field they set rather than by an entry in `shocks`.
REACHABLE: dict[str, tuple[str, str]] = {
    "pd_relative": ("Increase personal-finance PD by 20% relative", "shock"),
    "pd_absolute_pp": ("Increase PD by 2 percentage points for personal finance", "shock"),
    "lgd_relative": ("Increase LGD by 10% for personal finance", "shock"),
    "collateral_value_pct": ("Reduce mortgage collateral values by 10%", "shock"),
    "recovery_delay_months": ("Delay recovery by 6 months for mortgages", "shock"),
    "utilisation_pp": ("Increase card utilisation by 15 percentage points", "shock"),
    "ccf_absolute": ("Set the CCF to 60% for credit cards", "shock"),
    "income_pct": ("Reduce verified salary by 15% for salary-transfer customers", "shock"),
    "behavioural_score_points": (
        "Reduce the behavioural score by 30 points for personal finance", "shock"),
    "scenario_weights": (
        "Change scenario weights to base 50%, upturn 10%, downturn 40%", "weights"),
    "staging_mode": (
        "Increase personal-finance PD by 20% relative and re-evaluate staging", "staging"),
    "cutoff_replay": (
        "Replay an application cutoff of 620 on personal finance", "cutoff"),
}


class TestEveryAdvertisedMethodologyIsReachableInWords:
    def test_the_advertised_list_and_the_covered_list_are_the_same_set(self):
        """A methodology added to the engine must arrive with a way in."""
        assert set(REACHABLE) == set(wif.SUPPORTED_METHODOLOGIES)

    @pytest.mark.parametrize("name", sorted(REACHABLE))
    def test_a_typed_sentence_reaches_it(self, name):
        sentence, where = REACHABLE[name]
        ask = lang.read(sentence, MONTHS)
        assert not ask.needs_clarification, f"{name}: {ask.question}"
        assert not ask.unsupported, f"{name}: {ask.unsupported}"
        if where == "shock":
            assert name in ask.shocks, f"{name} not read from {sentence!r}"
        elif where == "weights":
            assert ask.scenario_weights is not None
        elif where == "staging":
            assert ask.staging_mode == wif.REEVALUATE_STAGE
        elif where == "cutoff":
            assert ask.cutoff, f"{name} not read from {sentence!r}"

    @pytest.mark.parametrize("name", sorted(REACHABLE))
    def test_it_is_never_read_as_an_unchanged_book(self, name):
        """The failure mode this whole class exists for."""
        ask = lang.read(REACHABLE[name][0], MONTHS)
        assert not ask.is_neutral, (
            f"{name!r} was read as a neutral scenario — the reader would be "
            "shown the published book under their own question.")


class TestACutoffReplayIsNotAScenario:
    def test_it_is_read_as_a_cutoff_and_not_as_shocks(self):
        ask = lang.read("Replay an application cutoff of 620 on personal finance", MONTHS)
        assert ask.cutoff == {"PERSONAL_LOAN": 620.0}
        assert ask.shocks == {}

    def test_a_bare_cutoff_covers_the_whole_book(self):
        ask = lang.read("What if the approval threshold had been 700?", MONTHS)
        assert set(ask.cutoff) == {"PERSONAL_LOAN", "AUTO_LOAN", "HOME_LOAN", "CREDIT_CARD"}

    def test_a_number_that_cannot_be_a_score_is_refused_not_replayed(self):
        ask = lang.read("Replay a cutoff of 20", MONTHS)
        assert ask.cutoff is None
        assert any("300 to 900" in line for line in ask.unsupported)

    def test_only_the_products_asked_about_are_counted(self, snapshot):
        """The denominator defect: 4,053 of 7,761, not 4,053 of 19,745."""
        one = wif.cutoff_replay(snapshot, {"PERSONAL_LOAN": 620.0})
        book = wif.cutoff_replay(snapshot, {p: 620.0 for p in
                                            ("PERSONAL_LOAN", "AUTO_LOAN",
                                             "HOME_LOAN", "CREDIT_CARD")})
        assert one["products"] == ["PERSONAL_LOAN"]
        assert one["booked_facilities"] < book["booked_facilities"]
        assert one["booked_facilities"] == int(
            (snapshot.drop_duplicates("facility_id")["product_code"] == "PERSONAL_LOAN").sum())
        assert one["would_be_excluded_pct"] > book["would_be_excluded_pct"]

    def test_an_unknown_outcome_is_not_reported_as_zero_defaults(self, snapshot):
        """At the latest month no outcome window has closed. 0 would read as clean."""
        result = wif.cutoff_replay(snapshot, {"PERSONAL_LOAN": 620.0})
        if result["outcomes_available"]:
            pytest.skip("The shipped latest month now carries closed outcome windows.")
        assert "excluded_observed_defaults" not in result
        assert "retained_observed_defaults" not in result
        assert any("NOT KNOWN" in line for line in result["limitations"])

    def test_where_the_window_has_closed_the_outcomes_are_reported(self, retail_book):
        earlier = retail_book.month(
            "2025-08", columns=["facility_id", "product_code",
                                "application_score_at_origination",
                                "gross_carrying_amount_sar",
                                "observed_default_within_window"])
        result = wif.cutoff_replay(earlier, {"PERSONAL_LOAN": 620.0})
        assert result["outcomes_available"] is True
        assert result["excluded_with_known_outcome"] > 0
        assert result["retained_with_known_outcome"] > 0
        # The cutoff has to discriminate, or the replay is telling nobody
        # anything: the accounts it would have excluded defaulted more often.
        excluded_rate = (result["excluded_observed_defaults"]
                         / result["excluded_with_known_outcome"])
        retained_rate = (result["retained_observed_defaults"]
                         / result["retained_with_known_outcome"])
        assert excluded_rate > retained_rate

    def test_a_cutoff_below_the_policy_in_force_says_it_excludes_nobody(self, snapshot):
        result = wif.cutoff_replay(snapshot, {"PERSONAL_LOAN": 350.0})
        assert result["would_be_excluded"] == 0
        assert result["cutoffs_below_the_policy_in_force"] == ["PERSONAL_LOAN"]
        assert any("excludes nobody" in line for line in result["limitations"])
        assert result["lowest_booked_score"]["PERSONAL_LOAN"] > 350.0


class TestAConversationNeitherDropsNorCompounds:
    CARRIED = {"filters": {"product_code": "PERSONAL_LOAN"},
               "shocks": {"pd_relative": 0.2}}

    def test_a_narrowing_follow_up_keeps_the_shock_it_narrows(self):
        ask = lang.read("Apply the same shock only to salary-transfer customers",
                        MONTHS, self.CARRIED)
        assert ask.shocks == {"pd_relative": 0.2}
        assert ask.filters == {"product_code": "PERSONAL_LOAN",
                               "salary_transfer_flag": True}
        assert not ask.is_neutral

    def test_the_carry_is_stated_rather_than_silent(self):
        ask = lang.read("Restrict it to secured facilities", MONTHS, self.CARRIED)
        assert any("carrying forward" in line for line in ask.read_as)

    def test_a_replacement_replaces_rather_than_stacking(self):
        """Both readings are PD. Two units of the same control never co-exist."""
        ask = lang.read("Instead increase PD by 2 percentage points",
                        MONTHS, self.CARRIED)
        assert ask.shocks == {"pd_absolute_pp": 2.0}
        assert "pd_relative" not in ask.shocks

    def test_a_replaced_shock_reaches_the_same_ecl_as_a_fresh_run(
            self, retail_book, snapshot, cfg):
        """Replacement is not almost-replacement: the numbers must be identical."""
        followed = lang.read("Instead increase PD by 2 percentage points",
                             MONTHS, {"filters": {"product_code": "PERSONAL_LOAN",
                                                  "salary_transfer_flag": True},
                                      "shocks": {"pd_relative": 0.2}})
        fresh = lang.read(
            "Increase PD by 2 percentage points for personal finance "
            "salary-transfer customers", MONTHS)
        assert followed.shocks == fresh.shocks
        assert followed.filters == fresh.filters

        def ecl(ask):
            scenario = wif.Scenario(
                name="t", dataset_version=retail_book.manifest["dataset_version"],
                snapshot_date=str(snapshot["snapshot_date"].iloc[0]),
                filters=ask.filters, shocks=ask.shocks,
                staging_mode=ask.staging_mode)
            return wif.run(snapshot, scenario, cfg)["scenario_result"]["ecl_final_sar"]

        assert ecl(followed) == pytest.approx(ecl(fresh), rel=1e-12)

    def test_a_new_sentence_with_no_back_reference_starts_fresh(self):
        """"Show me credit cards" is not a request to re-apply the last shock."""
        ask = lang.read("Show me credit cards", MONTHS, self.CARRIED)
        assert ask.shocks == {}
        assert ask.filters["product_code"] == "CREDIT_CARD"

    def test_a_cutoff_follow_up_does_not_inherit_shocks(self):
        ask = lang.read("Now replay the same cutoff of 620", MONTHS, self.CARRIED)
        assert ask.cutoff == {"PERSONAL_LOAN": 620.0}
        assert ask.shocks == {}

    def test_the_carried_shocks_are_validated_against_the_engine(self):
        """A carried key the engine does not implement is dropped, not smuggled."""
        ask = lang.read("Apply the same shock only to secured facilities", MONTHS,
                        {"shocks": {"rating_notches": 2, "pd_relative": 0.2}})
        assert ask.shocks == {"pd_relative": 0.2}


class TestAScenarioAssembledFromAClickDescribesItself:
    """The units question is answered by clicking, and the card must not then
    caption the run as something it is not."""

    def test_a_clicked_reading_is_described_in_the_same_words_as_a_typed_one(self):
        clicked = lang.Ask(filters={"product_code": "PERSONAL_LOAN"},
                           shocks={"pd_absolute_pp": 2.0})
        said = lang.describe_scenario(clicked)
        assert "PERSONAL_LOAN only" in said
        assert "PD +2 percentage points" in said

    def test_it_is_never_empty_for_a_scenario_that_changed_something(self):
        """An empty description makes the screen say 'an unchanged scenario
        over the whole retail book' above a shocked, filtered run."""
        for ask in (
            lang.Ask(shocks={"pd_relative": 0.2}),
            lang.Ask(shocks={"lgd_relative": 0.1}),
            lang.Ask(filters={"salary_transfer_flag": True}),
            lang.Ask(scenario_weights={"base": 0.5, "upturn": 0.1, "downturn": 0.4}),
            lang.Ask(staging_mode=wif.REEVALUATE_STAGE),
            lang.Ask(cutoff={"PERSONAL_LOAN": 620.0}),
        ):
            assert lang.describe_scenario(ask), ask

    @pytest.mark.parametrize("shock", sorted(
        set(wif.SUPPORTED_METHODOLOGIES) - {"staging_mode", "cutoff_replay",
                                            "scenario_weights"}))
    def test_every_shock_has_words_of_its_own(self, shock):
        said = lang.describe_scenario(lang.Ask(shocks={shock: 1.0}))
        assert said and said[0]

    def test_the_typed_and_clicked_descriptions_say_the_same_thing(self):
        """Not the same strings: a typed sentence echoes the reader's own words
        for the product ("personal finance only") while a clicked scenario has
        no sentence to echo and names the governed code. Both must name the
        same population and the same shock, in the same units."""
        typed = lang.read("Increase PD by 2 percentage points for personal finance",
                          MONTHS)
        clicked = lang.describe_scenario(
            lang.Ask(filters=dict(typed.filters), shocks=dict(typed.shocks)))
        assert "PD +2 percentage points" in typed.read_as
        assert "PD +2 percentage points" in clicked
        assert any("personal finance" in line for line in typed.read_as)
        assert any("PERSONAL_LOAN" in line for line in clicked)
        assert typed.filters["product_code"] == "PERSONAL_LOAN"
