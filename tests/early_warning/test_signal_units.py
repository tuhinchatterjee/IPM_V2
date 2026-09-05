"""Every signal's value says what it is. R2 §3.

The acceptance run found the Early Warning borrower detail showing

    Value 75.4    Previously 71.2    Threshold 10

which is four numbers and no information. 75.4 what — millions of riyals, per
cent, days, a multiple? A credit officer cannot read that, and a screen that
makes them guess is a screen they stop trusting.

The unit is DERIVED from the field and the test rather than typed onto
forty-three signals by hand, because a hand-maintained table drifts away from
the fields it describes. This file is the explicit table that holds the
derivation honest: every signal, named, with the unit it must carry. A
derivation nobody has enumerated is a derivation nobody has checked.
"""

from __future__ import annotations

import pytest

from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

#: signal key -> the unit its value is denominated in.
EXPECTED: dict[str, str] = {
    # financial performance
    "revenue_fell": tx.PERCENT,
    "ebitda_margin_fell": tx.PERCENT,
    "cash_flow_negative": tx.MONEY,
    "free_cash_flow_negative": tx.MONEY,
    "receivable_days_stretched": tx.DAYS,
    "receivable_days_rose": tx.DAYS,
    "cash_cycle_stretched": tx.DAYS,
    "capex_starved": tx.PERCENT,
    # leverage and debt service
    "leverage_rose": tx.RATIO,
    "leverage_high": tx.RATIO,
    "interest_cover_weak": tx.RATIO,
    "interest_cover_fell": tx.RATIO,
    # liquidity
    "cash_thin": tx.PERCENT,
    "liquidity_buffer_thin": tx.PERCENT,
    "committed_headroom_thin": tx.PERCENT,
    "short_term_debt_heavy": tx.PERCENT,
    "maturity_wall": tx.PERCENT,
    "near_maturity_uncovered": tx.PERCENT,
    # facility behaviour
    "utilisation_high": tx.PERCENT,
    "utilisation_rose": tx.PERCENT,
    "undrawn_thin": tx.PERCENT,
    "large_exposure": tx.PERCENT,
    "in_arrears": tx.DAYS,
    "arrears_30": tx.DAYS,
    "repeated_delinquency": tx.DAYS,
    "restructured": tx.FLAG,
    # covenants
    "covenant_breached": tx.FLAG,
    "covenant_headroom_tight": tx.PERCENT,
    "covenant_headroom_fell": tx.PERCENT,
    "statements_stale": tx.DAYS,
    # collateral
    "collateral_thin": tx.PERCENT,
    "collateral_fell": tx.PERCENT,
    "collateral_shortfall": tx.PERCENT,
    "valuation_stale": tx.DAYS,
    # ratings and watchlist
    "rating_downgraded": tx.NOTCHES,
    "rating_multi_notch": tx.NOTCHES,
    "rating_stale": tx.FLAG,
    "on_watchlist": tx.FLAG,
    # IFRS 9
    "stage_2": tx.STAGE,
    "stage_3": tx.STAGE,
    "pd_rose": tx.PERCENT,
    "ecl_rose": tx.PERCENT,
    "sicr_flagged": tx.FLAG,
    # external and macro (layer 4)
    #
    # These are the units the layer-4 signals forced into existence. Five of
    # the six fell through to COUNT when they were first configured, and
    # `debtrank_impact` came out as MONEY because "debt" is a substring of
    # "debtrank" — which would have put SAR in front of 0.0003 on a screen.
    "outlook_negative": tx.CATEGORY,
    "external_rating_lost": tx.CATEGORY,
    "sector_concentrated": tx.RATIO,
    # group and network
    "network_risk_high": tx.SCORE,
    "group_large": tx.ENTITIES,
    "contagion_material": tx.SHARE,
}

UNITS = frozenset({tx.MONEY, tx.PERCENT, tx.RATIO, tx.DAYS, tx.NOTCHES,
                   tx.STAGE, tx.FLAG, tx.COUNT, tx.SCORE, tx.SHARE,
                   tx.ENTITIES, tx.CATEGORY})


class TestTheTable:
    def test_every_signal_is_named_here(self):
        """A new signal has to be given a unit deliberately."""
        assert {s.key for s in tx.SIGNALS} == set(EXPECTED)

    @pytest.mark.parametrize("key,unit", sorted(EXPECTED.items()))
    def test_each_signal_carries_the_unit_it_should(self, key, unit):
        found = {s.key: s for s in tx.SIGNALS}[key]
        assert found.unit == unit, (found.field, found.test)

    def test_nothing_falls_through_to_a_bare_number(self):
        """`count` is the fallback. Nothing in this taxonomy should need it —
        a value with no unit is exactly the defect §3 is about."""
        assert all(s.unit != tx.COUNT for s in tx.SIGNALS)


class TestTheDerivation:
    def test_a_share_is_not_a_percentage(self):
        """`debtrank_impact` is a fraction of one, around 0.00002 on this
        book. Rendering it as a percentage understates it by a hundred; the
        two units exist so nothing has to guess which scale it is on."""
        assert tx.unit_for("debtrank_impact", tx.ABOVE) == tx.SHARE
        assert tx.SHARE != tx.PERCENT

    def test_a_money_word_inside_another_word_is_not_money(self):
        """"debt" is a substring of "debtrank_impact". Matching on substrings
        put a currency in front of a modelled transmission share."""
        assert tx.unit_for("debtrank_impact", tx.ABOVE) != tx.MONEY
        assert tx.unit_for("total_debt", tx.ABOVE) == tx.MONEY

    def test_a_rating_label_is_not_a_number(self):
        assert tx.unit_for("rating_outlook", tx.EQUALS) == tx.CATEGORY
        assert tx.unit_for("external_rating", tx.CHANGED) == tx.CATEGORY

    def test_a_score_says_it_is_a_score(self):
        assert tx.unit_for("network_risk_score", tx.ABOVE) == tx.SCORE


    def test_a_ratio_test_is_a_percentage_whatever_it_divides(self):
        """`cash / drawn_exposure` is money over money and the answer is a
        percentage. The unit belongs to the TEST, not to the column."""
        assert tx.unit_for("cash", tx.RATIO_ABOVE) == tx.PERCENT
        assert tx.unit_for("maturing_0_3m", tx.RATIO_ROSE_BY) == tx.PERCENT

    def test_the_same_field_read_directly_keeps_its_own_unit(self):
        assert tx.unit_for("cash", tx.BELOW) == tx.MONEY

    def test_a_boolean_is_a_flag_not_a_number(self):
        assert tx.unit_for("watchlist_flag", tx.TRUE) == tx.FLAG

    def test_a_multiple_is_not_a_percentage(self):
        """A covenant written as "minimum DSCR 1.25x" is not "minimum DSCR
        125%", and showing one as the other misstates the test."""
        for name in ("dscr", "interest_coverage", "net_leverage",
                     "debt_to_equity", "current_ratio"):
            assert tx.unit_for(name, tx.BELOW) == tx.RATIO, name

    def test_a_percentage_is_recognised_by_suffix_or_by_name(self):
        assert tx.unit_for("collateral_coverage_pct", tx.BELOW) == tx.PERCENT
        assert tx.unit_for("ebitda_margin", tx.FELL_BY) == tx.PERCENT

    def test_days_are_recognised_by_suffix_and_by_dpd(self):
        assert tx.unit_for("valuation_age_days", tx.ABOVE) == tx.DAYS
        assert tx.unit_for("current_dpd", tx.ABOVE) == tx.DAYS
        assert tx.unit_for("max_dpd_12m", tx.ABOVE) == tx.DAYS

    def test_an_unrecognised_field_is_a_count_not_money(self):
        """Guessing "money" would put a currency on something that is not
        one, which is a worse answer than no unit at all."""
        assert tx.unit_for("board_meetings_held", tx.ABOVE) == tx.COUNT

    def test_every_unit_is_one_the_screen_knows(self):
        assert {s.unit for s in tx.SIGNALS} <= UNITS


class TestTheObservationCarriesIt:
    ROW = {"borrower_id": "CORP-1", "cash": 10.0, "drawn_exposure": 400.0,
           "current_dpd": 45, "debt_to_equity": 4.2, "stage": 2,
           "free_cash_flow": -75.4, "watchlist_flag": True}

    def observations(self):
        return {o.signal: o for o in
                sg.evaluate(self.ROW, {}, period="Q2 2026")}

    def test_the_unit_reaches_the_screen(self):
        found = self.observations()
        for key, unit in EXPECTED.items():
            assert found[key].to_dict()["unit"] == unit, key

    def test_the_currency_is_the_riyal_and_is_stated_once(self):
        assert tx.CURRENCY == "SAR"
        payload = self.observations()["free_cash_flow_negative"].to_dict()
        assert payload["currency"] == "SAR"

    def test_an_untested_signal_still_says_what_it_would_have_been(self):
        """A reader looking at what could NOT be checked still needs to know
        what kind of number was missing."""
        sparse = {"borrower_id": "CORP-2", "stage": 1}
        found = {o.signal: o for o in sg.evaluate(sparse, {})}
        assert found["collateral_thin"].unavailable
        assert found["collateral_thin"].to_dict()["unit"] == tx.PERCENT

    def test_the_taxonomy_publishes_the_unit_too(self):
        """Data Builder and the analyst's tools read `describe()`, not the
        observation, and they need the same answer."""
        flat = {s["key"]: s for s in tx.describe()["signals"]}
        for key, unit in EXPECTED.items():
            assert flat[key]["unit"] == unit, key
            assert flat[key]["currency"] == "SAR"
