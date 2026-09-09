"""What the thinking cost, by routing class. Part 14.

`routing.Decision` published a `cost_estimate`. Nothing ever set it, so every
turn reported that its AI cost was zero. A figure that is always zero is worse
than no figure: it looks like an answer, it reconciles with nothing, and the
first person to add it up gets a total that is wrong in a flattering direction.

Two things are being held here. That a cost, where one is reported, is derived
from tokens that were actually recorded and a price somebody actually entered.
And that where either is missing, the product says so rather than filling the
gap with a zero.
"""

from __future__ import annotations

import json

import pytest

from backend.llm import cost as ct
from backend.orchestration import routing as rt

TARIFF = {
    "small": {"input": 1.0, "output": 5.0,
              "cache_write": 1.25, "cache_read": 0.10},
    "big": {"input": 3.0, "output": 15.0,
            "cache_write": 3.75, "cache_read": 0.30},
}


class Recorded:
    """A telemetry Call, as far as the cost layer is concerned."""

    def __init__(self, role: str, model: str, *, inp: int = 0, out: int = 0,
                 cache_read: int = 0, cache_write: int = 0) -> None:
        self.role, self.model = role, model
        self.input_tokens, self.output_tokens = inp, out
        self.cache_read_tokens, self.cache_write_tokens = cache_read, cache_write


@pytest.fixture
def priced(monkeypatch):
    monkeypatch.setenv(ct.TARIFF_ENV, json.dumps(TARIFF))
    return TARIFF


@pytest.fixture
def unpriced(monkeypatch):
    monkeypatch.delenv(ct.TARIFF_ENV, raising=False)


# ==========================================================================
# A price nobody entered is not a price
# ==========================================================================


class TestNothingIsInvented:

    def test_an_unconfigured_deployment_prices_nothing(self, unpriced) -> None:
        assert not ct.configured()
        assert ct.price_of("small") is None

    def test_an_unpriced_call_costs_none_and_not_zero(self, unpriced) -> None:
        # Zero would let an unpriced deployment publish a total that reads as
        # free, which is the fabrication this whole layer exists to avoid.
        found = ct.of_call(Recorded("planner", "small", inp=1000, out=200))
        assert found is None

    def test_the_summary_says_why_there_is_no_cost(self, unpriced) -> None:
        found = ct.describe([Recorded("planner", "small", inp=10, out=2)])
        assert found["cost"] is None
        assert found["tariff_configured"] is False
        assert "No AI tariff is configured" in found["statement"]

    def test_tokens_are_still_published_without_a_tariff(self,
                                                         unpriced) -> None:
        # The tokens are measured. Only the money is unknown.
        found = ct.describe([Recorded("planner", "small", inp=1000, out=200)])
        assert found["tokens"] == 1200
        assert found["unpriced_calls"] == 1

    def test_a_malformed_tariff_prices_nothing_rather_than_guessing(
            self, monkeypatch) -> None:
        monkeypatch.setenv(ct.TARIFF_ENV, "{not json")
        assert ct.price_of("small") is None

    def test_a_tariff_that_is_not_an_object_is_refused(self,
                                                       monkeypatch) -> None:
        monkeypatch.setenv(ct.TARIFF_ENV, json.dumps(["small"]))
        assert not ct.configured()


# ==========================================================================
# The arithmetic
# ==========================================================================


class TestTheArithmetic:

    def test_it_is_tokens_times_price_per_million(self, priced) -> None:
        found = ct.of_call(Recorded("planner", "small", inp=1_000_000,
                                    out=1_000_000))
        assert found == pytest.approx(1.0 + 5.0)

    def test_output_is_priced_separately_from_input(self, priced) -> None:
        one = ct.of_call(Recorded("planner", "small", inp=1_000_000))
        other = ct.of_call(Recorded("planner", "small", out=1_000_000))
        assert other > one, "output tokens are dearer and must price dearer"

    def test_a_cache_read_is_cheaper_than_a_fresh_input_token(self,
                                                              priced) -> None:
        # The whole reason the telemetry splits cache reads from writes is
        # that they price differently. A cost layer that ignores the split
        # throws away the measurement.
        fresh = ct.of_call(Recorded("planner", "small", inp=1_000_000))
        cached = ct.of_call(Recorded("planner", "small",
                                     cache_read=1_000_000))
        assert cached < fresh

    def test_a_cache_write_is_dearer_than_a_fresh_input_token(self,
                                                              priced) -> None:
        fresh = ct.of_call(Recorded("planner", "small", inp=1_000_000))
        written = ct.of_call(Recorded("planner", "small",
                                      cache_write=1_000_000))
        assert written > fresh

    def test_a_missing_cache_price_falls_back_to_the_input_price(
            self, monkeypatch) -> None:
        # The conservative reading: a cache token priced as a plain input
        # token cannot understate the bill.
        monkeypatch.setenv(ct.TARIFF_ENV,
                           json.dumps({"plain": {"input": 2.0,
                                                 "output": 8.0}}))
        found = ct.of_call(Recorded("planner", "plain",
                                    cache_read=1_000_000))
        assert found == pytest.approx(2.0)

    def test_a_dearer_model_costs_more_for_the_same_work(self,
                                                         priced) -> None:
        cheap = ct.of_call(Recorded("planner", "small", inp=10_000, out=2_000))
        dear = ct.of_call(Recorded("complex_planner", "big",
                                   inp=10_000, out=2_000))
        assert dear > cheap


# ==========================================================================
# The classes
# ==========================================================================


class TestTheRoutingClasses:

    def test_all_four_classes_are_published(self, priced) -> None:
        routes = [entry.route for entry in ct.by_class([])]
        assert routes == [rt.DETERMINISTIC, rt.ROUTINE, rt.COMPLEX, rt.CRITIC]

    def test_the_deterministic_class_is_present_with_zeros(self,
                                                           priced) -> None:
        # Class A is where no model was asked anything. A rollup that omits
        # it cannot show how much traffic was answered for nothing, which is
        # the whole argument for routing.
        first = ct.by_class([])[0]
        assert first.route == rt.DETERMINISTIC
        assert first.calls == 0 and first.tokens == 0

    def test_every_class_says_what_it_means(self, priced) -> None:
        for entry in ct.by_class([]):
            assert entry.label and entry.means
            assert entry.means.endswith(".")

    def test_a_role_lands_in_the_class_its_work_belongs_to(self) -> None:
        assert ct.class_of(Recorded("router", "small")) == rt.ROUTINE
        assert ct.class_of(Recorded("complex_planner", "big")) == rt.COMPLEX
        assert ct.class_of(Recorded("critic", "big")) == rt.CRITIC

    def test_every_configured_role_has_a_class(self) -> None:
        # A role with no class would be silently reclassified into the
        # cheapest bucket, which flatters the total.
        from backend.llm import roles

        for role in roles.all_roles(include_inactive=True):
            assert role.name in ct.ROLE_CLASS, (
                f"the {role.name} role has no routing class, so its cost "
                "would land wherever the default happens to be")

    def test_the_classes_add_up_to_the_total(self, priced) -> None:
        calls = [
            Recorded("router", "small", inp=1000, out=200),
            Recorded("complex_planner", "big", inp=9000, out=1500),
            Recorded("critic", "big", inp=3000, out=400),
        ]
        found = ct.describe(calls)
        parts = sum(entry["cost"] or 0.0 for entry in found["classes"])
        assert found["cost"] == pytest.approx(parts, abs=1e-6)
        assert found["calls"] == 3

    def test_a_partly_priced_window_says_it_is_partly_priced(self,
                                                             priced) -> None:
        calls = [
            Recorded("router", "small", inp=1000, out=200),
            Recorded("investigator", "not-in-the-tariff", inp=2000, out=300),
        ]
        found = ct.describe(calls)
        assert found["unpriced_calls"] == 1
        assert "part of the traffic rather than all of it" in found["statement"]
        assert found["tokens"] == 3500, "the unpriced call's tokens still count"


# ==========================================================================
# The field that used to always be zero
# ==========================================================================


class TestTheDecisionStopsReportingZero:

    def test_an_unmeasured_decision_reports_no_cost_rather_than_zero(
            self) -> None:
        found = rt.Decision().to_dict()
        assert found["cost_estimate"] is None
        assert found["cost_measured"] is False

    def test_a_recorded_call_makes_it_measured(self, priced) -> None:
        decision = rt.record_call(
            rt.Decision(), Recorded("planner", "small", inp=1000, out=200))
        assert decision.measured is True
        assert decision.input_tokens == 1000
        assert decision.output_tokens == 200
        assert decision.cost_estimate > 0
        assert decision.to_dict()["cost_estimate"] is not None

    def test_two_calls_accumulate(self, priced) -> None:
        decision = rt.Decision()
        rt.record_call(decision, Recorded("planner", "small", inp=1000))
        rt.record_call(decision, Recorded("critic", "big", inp=1000))
        assert decision.input_tokens == 2000

    def test_an_unpriced_call_is_measured_but_not_costed(self,
                                                         priced) -> None:
        # The call happened and its tokens are real. What is unknown is the
        # money, and `unpriced_calls` is what says so.
        decision = rt.record_call(
            rt.Decision(), Recorded("planner", "nowhere", inp=500, out=100))
        assert decision.measured is True
        assert decision.input_tokens == 500
        assert decision.cost_estimate == 0.0
        assert decision.unpriced_calls == 1

    def test_it_records_which_model_actually_served(self, priced) -> None:
        # §23: never a silent substitution. The served model is a fact about
        # what happened, and the cost is computed from it.
        decision = rt.record_call(
            rt.Decision(configured_model="small"),
            Recorded("planner", "big", inp=100))
        assert decision.served_model == "big"
