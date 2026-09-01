"""
§45 — the Early Warning book is fast enough to put on a screen.

Two seconds of arithmetic per page load is not a performance nicety, it is
whether the screen gets used. Standing three thousand borrowers up against
thirty-four conditions is genuinely that expensive; the fix is to do it once
per reporting period rather than once per request.

What these tests actually guard is the DANGEROUS half of that. A cache that
makes a screen fast and serves last quarter's book is worse than the slow
screen it replaced, so the assertions are mostly about invalidation and about
the cache never changing an answer.
"""

from __future__ import annotations

import time

import pytest

from backend.corporate import service as corporate
from backend.early_warning import cases as ec
from backend.early_warning import signals as sg

#: Generous by an order of magnitude. This is a regression guard against the
#: memo being removed or bypassed, not a benchmark - a shared CI box on a bad
#: day is still nowhere near this.
WARM_BUDGET_MS = 250


@pytest.fixture(autouse=True)
def _fresh():
    sg.reset()
    yield
    sg.reset()


class TestTheBookIsStoodUpOncePerPeriod:

    def test_a_second_request_for_the_same_period_is_fast(self):
        sg.portfolio(limit=5)
        started = time.perf_counter()
        sg.portfolio(limit=5)
        elapsed = (time.perf_counter() - started) * 1000
        assert elapsed < WARM_BUDGET_MS, (
            f"the second read took {elapsed:.0f}ms; the book is being stood "
            "up again on every request")

    def test_a_different_limit_reuses_the_same_evaluation(self):
        """Slicing is not re-evaluating.

        Twenty rows and five rows are the same ranking cut in two places, and
        paying for the whole book twice to show fifteen more names would be
        the slow path wearing a cache.
        """
        sg.portfolio(limit=5)
        started = time.perf_counter()
        wider = sg.portfolio(limit=25)
        elapsed = (time.perf_counter() - started) * 1000
        assert elapsed < WARM_BUDGET_MS
        assert wider["returned"] == 25

    def test_the_review_preview_is_stood_up_once_too(self):
        ec.standings_for()
        started = time.perf_counter()
        ec.standings_for()
        assert (time.perf_counter() - started) * 1000 < WARM_BUDGET_MS


class TestTheCacheNeverChangesAnAnswer:

    def test_a_warm_read_is_identical_to_a_cold_one(self):
        cold = sg.portfolio(limit=10)
        warm = sg.portfolio(limit=10)
        assert cold == warm

    def test_slicing_is_a_prefix_of_the_same_ranking(self):
        five = sg.portfolio(limit=5)
        twenty = sg.portfolio(limit=20)
        assert [b["borrower_id"] for b in twenty["borrowers"]][:5] == \
               [b["borrower_id"] for b in five["borrowers"]]
        assert five["evaluated"] == twenty["evaluated"]

    def test_the_private_ranking_never_reaches_a_caller(self):
        """The memo holds `Standing` objects; the response must not.

        A private key leaking into a JSON response is how an internal
        representation becomes an accidental API that somebody depends on.
        """
        body = sg.portfolio(limit=3)
        assert [k for k in body if k.startswith("_")] == []

    def test_two_periods_are_two_books(self):
        periods = corporate.periods()
        if len(periods) < 2:
            pytest.skip("this book carries one period")
        latest = sg.portfolio(periods[-1], limit=3)
        earlier = sg.portfolio(periods[-2], limit=3)
        assert latest["period"] != earlier["period"]
        assert latest["previous_period"] != earlier["previous_period"]

    def test_an_unknown_period_is_still_refused_when_warm(self):
        sg.portfolio(limit=1)
        body = sg.portfolio("Q9 1999", limit=1)
        assert body["borrowers"] == []
        assert "not a period this book holds" in body["note"]


class TestARebuiltLakeIsNotServedFromTheOldMemo:
    """The one direction a cache must never be wrong in.

    A deployment that regenerates its book and keeps answering from the
    previous one is worse than the slow screen it replaced: every figure is
    internally consistent and about last quarter.
    """

    def test_reset_clears_the_signal_book(self):
        sg.portfolio(limit=1)
        assert sg._book.cache_info().currsize == 1
        sg.reset()
        assert sg._book.cache_info().currsize == 0

    def test_reset_clears_the_review_standings_too(self):
        ec.standings_for()
        assert ec._standings.cache_info().currsize == 1
        sg.reset()
        assert ec._standings.cache_info().currsize == 0

    def test_reset_drops_the_snapshot_underneath_both(self):
        """Clearing the derived caches and leaving the source is half a fix.

        Both would then be rebuilt from the parquet frame the process read
        before the lake was regenerated.
        """
        sg.portfolio(limit=1)
        sg.reset()
        assert corporate._load.cache_info().currsize == 0

    def test_the_bootstrap_resets_them_when_it_rebuilds_the_lake(self):
        """Asserted at the seam, not assumed.

        `_refresh_data_access` runs after every universe build. If the
        early-warning reset ever falls out of it, a rebuilt deployment starts
        serving the previous book and nothing fails.
        """
        from backend.bootstrap import plan

        sg.portfolio(limit=1)
        ec.standings_for()
        plan._refresh_data_access()
        assert sg._book.cache_info().currsize == 0
        assert ec._standings.cache_info().currsize == 0
