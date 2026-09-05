"""Thirty Analyses that are computed, and a threshold that honours nought.

Part 3 asked for thirty real Analyses. What the list actually held was 564
rows: four distinct analysis types between them, 443 of those one repeated
`portfolio_summary`, and 236 with an EMPTY result — saved Analyses that open
onto nothing. Seeding that list properly turned up a defect in one of the
functions being seeded, which is the argument for seeding through the real
engine rather than writing rows.

The defect
----------
`high_utilisation_watchlist` read its parameters as

    threshold = float(ctx.params.get("threshold_pct") or 90.0)

Nought is falsy. So a caller asking for a 0% threshold — "show me everything"
— was silently given 90%, and `top_n=0` became 20. A governed parameter the
caller set, replaced without the answer saying so, is precisely the silent
substitution the product contract forbids. The contract had already applied
its own defaults by the time that line ran, so the `or` bought nothing.

And a second thing the seeding showed: on the current book nothing is utilised
above the governed 90% threshold — the highest outside the watchlist is just
under it. The analysis is therefore legitimately empty, and an empty answer
that cannot explain itself is indistinguishable from one that failed.
"""

from __future__ import annotations

import pytest

from backend.engine.functions import stress as st
from backend.engine.registry import get_registry
from backend.engine.runner import run_analysis


class TestNoughtIsAValue:

    def test_nought_is_not_read_as_unset(self) -> None:
        assert st._number(0.0, 90.0) == 0.0
        assert st._number(0, 20) == 0.0

    def test_a_missing_value_falls_back(self) -> None:
        assert st._number(None, 90.0) == 90.0

    def test_something_that_is_not_a_number_falls_back(self) -> None:
        assert st._number("not a number", 90.0) == 90.0
        assert st._number([], 20.0) == 20.0

    def test_a_zero_threshold_is_not_rewritten_to_ninety(self) -> None:
        # The whole defect, end to end. A 0% threshold asks for everything;
        # it used to return exactly what a 90% threshold returns, which on
        # this book is nothing at all.
        everything = run_analysis("high_utilisation_watchlist",
                                  params={"threshold_pct": 0.0, "top_n": 10},
                                  period="latest")
        assert everything.status == "succeeded"
        assert everything.result is not None
        assert everything.result.to_dict()["values"]["threshold_pct"] == 0.0
        assert len(everything.result.to_dict()["rows"] or []) > 0, (
            "a 0% threshold excludes nothing, so it cannot come back empty")


class TestAnEmptyAnswerExplainsItself:

    def test_it_says_what_the_highest_utilisation_actually_is(self) -> None:
        found = run_analysis("high_utilisation_watchlist",
                             params={"threshold_pct": 90.0, "top_n": 10},
                             period="latest")
        assert found.status == "succeeded" and found.result is not None
        values = found.result.to_dict()["values"]
        if values["matched"]:
            pytest.skip("the book now has facilities above 90%, so the empty "
                        "case under test is not present")
        # Measured, not asserted: the figure comes from the same column the
        # filter read.
        assert values["highest_utilisation_pct"] is not None
        assert "No facility is utilised above 90%" in values["statement"]
        assert str(values["highest_utilisation_pct"]) in values["statement"]

    def test_a_matched_answer_does_not_carry_the_empty_statement(self) -> None:
        found = run_analysis("high_utilisation_watchlist",
                             params={"threshold_pct": 10.0, "top_n": 5},
                             period="latest")
        values = found.result.to_dict()["values"]
        assert values["matched"] > 0
        assert not values["statement"], (
            "a sentence explaining an empty answer must not appear beside "
            "rows that are not empty")


class TestTheSeedIsRealWork:

    def test_the_seed_plans_one_run_per_runnable_analysis(self) -> None:
        from scripts.seed_analyses import _plan

        runnable = {a.contract.id for a in get_registry().runnable()}
        planned = [one for one, _ in _plan()]
        assert set(planned) >= runnable, (
            "a seeded list that skips registered analyses is the thin list "
            "this replaced")
        assert len(planned) == len(runnable) + 1, (
            "one analysis is run twice, at a second window, so the set shows "
            "a parameterised run rather than one-shot fixtures")

    def test_the_second_window_names_a_parameter_the_contract_accepts(
            self) -> None:
        # The first attempt passed `periods`; the contract calls it
        # `n_periods`, and the seed failed on its thirtieth row.
        from scripts.seed_analyses import SECOND_WINDOW

        analysis_id, params = SECOND_WINDOW
        accepted = {p.name for p in get_registry().contract(analysis_id).parameters}
        assert set(params) <= accepted, (
            f"{sorted(set(params) - accepted)} is not accepted by "
            f"{analysis_id}; it accepts {sorted(accepted)}")
