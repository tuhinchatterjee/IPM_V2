

# ---------------------------------------------------------------------------
# The signal vocabulary. §1, §15.
# ---------------------------------------------------------------------------


class TestWhatCountsAsABorrowerSignal:
    """A review that only ever notices two things reads as unreviewed.

    The screen used to look at stage, rating and days past due, so every case
    on a correctly bootstrapped demonstration was "stage moved" or "rating
    moved" and the committee categories a credit officer actually works
    through - ECL movement, liquidity pressure, watchlist entry,
    non-performing classification - were invisible even where the published
    data showed them. §1 allows a category to be empty when the book has
    nothing in it; it does not allow the screen to be unable to see it.

    Every signal below is a comparison of two published figures at the
    customer grain. None of them adds a query.
    """

    @staticmethod
    def _signals(now, before):
        from backend.agentic import screening

        base = {"stage": "1", "rating": "BBB", "dpd": 0, "ecl": 1_000_000.0,
                "utilisation": 40.0, "watchlist": False, "npl": False}
        return screening._signals({**base, **now}, {**base, **before})

    def test_a_material_ecl_rise_is_a_signal(self):
        found = self._signals({"ecl": 2_000_000.0}, {})
        assert any("credit loss" in s.lower() for s in found), found

    def test_a_rise_on_a_trivial_ecl_is_not(self):
        """25% of nothing is nothing, and reporting it teaches a reader to
        ignore the ECL signal entirely."""
        found = self._signals({"ecl": 900.0}, {"ecl": 100.0})
        assert not any("credit loss" in s.lower() for s in found), found

    def test_a_drawdown_is_a_signal(self):
        found = self._signals({"utilisation": 72.0}, {"utilisation": 55.0})
        assert any("utilisation" in s.lower() for s in found), found

    def test_no_headroom_is_a_signal_even_where_it_did_not_move(self):
        found = self._signals({"utilisation": 98.0}, {"utilisation": 98.0})
        assert any("headroom" in s.lower() for s in found), found

    def test_entering_the_watchlist_is_a_signal_and_leaving_it_is_not(self):
        entered = self._signals({"watchlist": True}, {"watchlist": False})
        assert any("watchlist" in s.lower() for s in entered), entered
        left = self._signals({"watchlist": False}, {"watchlist": True})
        assert not any("watchlist" in s.lower() for s in left), left

    def test_becoming_non_performing_is_a_signal(self):
        found = self._signals({"npl": True}, {"npl": False})
        assert any("non-performing" in s.lower() for s in found), found

    def test_a_quiet_borrower_produces_no_signal_at_all(self):
        """So the broadened vocabulary cannot pass by flagging everybody.

        A screen that reports something about every borrower has not become
        more observant; it has stopped discriminating, and the Cockpit fills
        with cases nobody can act on.
        """
        assert self._signals({}, {}) == []
