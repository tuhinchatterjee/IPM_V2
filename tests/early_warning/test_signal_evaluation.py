"""Every governed signal, re-derived independently, over the real book. §41.

What makes this a validation rather than a repetition
-----------------------------------------------------
For each (signal, borrower) pair the suite reads the RAW row out of the
Borrower 360 snapshot, applies the signal's declared rule with arithmetic
written here and not imported from the engine, and compares the verdict with
what `signals.evaluate` produced. A test that called the engine to work out
what the engine should have said would pass whatever the engine did.

So the comparison is against a second implementation, and the two disagree
loudly when either is wrong. That is what caught the utilisation signals being
bound to large-exposure limit utilisation rather than facility drawdown: the
engine said nothing ever fired, and the re-derivation agreed, and the FIRING
RATE test below said a signal that never fires over three thousand borrowers
is not a signal.

Why the counts are properties, not values
------------------------------------------
The book is synthetic and regenerable. "1,084 borrowers breach a covenant" is
a fact about today's fixture and would have to be rewritten every time the
generator runs. "No signal fires for more than 60% of the book" is a fact
about whether the taxonomy carries information, and it survives regeneration —
which is the only kind of assertion worth having here.
"""

from __future__ import annotations

import pytest

from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

corporate = pytest.importorskip("backend.corporate.service")

#: Borrowers sampled for the pairwise re-derivation. Taken at a stride through
#: the ranked book rather than from the top, so the sample carries clean names
#: as well as distressed ones — a suite that only ever looks at the worst rows
#: never exercises the "did not fire" half of any rule.
SAMPLE = 16


@pytest.fixture(scope="module")
def book():
    """The latest two reporting periods, loaded once."""
    try:
        snapshot = corporate._load(corporate.SNAPSHOT)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no corporate book here: {e}")
    periods = sorted((str(p) for p in snapshot["period"].unique()),
                     key=sg._period_key)
    if len(periods) < 2:
        pytest.skip("the book carries fewer than two periods")
    now, before = periods[-1], periods[-2]
    current = snapshot[snapshot["period"] == now]
    prior = snapshot[snapshot["period"] == before].set_index("borrower_id")
    rows = current.to_dict("records")
    stride = max(1, len(rows) // SAMPLE)
    sampled = rows[::stride][:SAMPLE]
    return {"period": now, "previous_period": before, "rows": rows,
            "sampled": sampled, "prior": prior}


@pytest.fixture(scope="module")
def evaluated(book):
    """Every sampled borrower's observations, keyed by (borrower, signal)."""
    out = {}
    for row in book["sampled"]:
        borrower = str(row.get("borrower_id"))
        before = (book["prior"].loc[borrower].to_dict()
                  if borrower in book["prior"].index else {})
        for observation in sg.evaluate(row, before, period=book["period"],
                                       previous_period=book["previous_period"]):
            out[(borrower, observation.signal)] = (observation, row, before)
    return out


# --------------------------------------------------- the second implementation


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        found = float(value)
    except (TypeError, ValueError):
        return None
    return None if found != found else found


def _expected(signal: tx.Signal, row: dict, before: dict):
    """The signal's rule, written out again. Returns None for "untested"."""
    if signal.field not in row:
        return None

    if signal.test == tx.TRUE:
        return str(row.get(signal.field)).strip().lower() in {"true", "1",
                                                              "yes", "y"}

    if signal.test in (tx.RATIO_ABOVE, tx.RATIO_ROSE_BY):
        top, bottom = _num(row.get(signal.field)), _num(row.get(signal.against))
        if top is None or bottom is None or bottom == 0:
            return None
        now = 100.0 * top / bottom
        if signal.test == tx.RATIO_ABOVE:
            limit = float(signal.threshold)
            return now <= -limit if limit < 0 else now >= limit
        was_top = _num(before.get(signal.field))
        was_bottom = _num(before.get(signal.against))
        if was_top is None or was_bottom is None or was_bottom == 0:
            return None
        return (now - 100.0 * was_top / was_bottom) >= float(signal.threshold)

    now = _num(row.get(signal.field))
    if now is None:
        return None
    if signal.test == tx.ABOVE:
        return now >= float(signal.threshold)
    if signal.test == tx.BELOW:
        return now < float(signal.threshold)
    was = _num(before.get(signal.field))
    if was is None:
        return None
    if signal.test == tx.ROSE_BY:
        return (now - was) >= float(signal.threshold)
    if signal.test == tx.FELL_BY:
        return (was - now) >= float(signal.threshold)
    if signal.test == tx.CHANGED:
        return row.get(signal.field) != before.get(signal.field)
    raise AssertionError(f"{signal.test} has no independent implementation")


def _pairs():
    """(signal, index) for every signal against every sampled position."""
    return [(signal, index) for signal in tx.SIGNALS
            for index in range(SAMPLE)]


# ------------------------------------------------------ the 500+ validations


@pytest.mark.parametrize(
    "signal,index", _pairs(),
    ids=lambda v: v.key if isinstance(v, tx.Signal) else f"b{v}")
def test_the_engine_agrees_with_the_rule_as_written(signal, index, book,
                                                    evaluated):
    """One signal, one borrower, two independent implementations. §41."""
    if index >= len(book["sampled"]):
        pytest.skip("the book is smaller than the sample")
    row = book["sampled"][index]
    borrower = str(row.get("borrower_id"))
    observation, _row, before = evaluated[(borrower, signal.key)]

    expected = _expected(signal, row, before)
    if expected is None:
        assert not observation.available, (
            f"{signal.key} on {borrower}: the rule cannot be evaluated here, "
            f"and the engine reported {observation.fired}")
        return
    assert observation.available, (
        f"{signal.key} on {borrower}: the rule evaluates, and the engine said "
        f"it could not — {observation.unavailable}")
    assert observation.fired is expected, (
        f"{signal.key} on {borrower}: rule says {expected}, engine said "
        f"{observation.fired}; value={observation.value!r} "
        f"threshold={signal.threshold!r} test={signal.test}")


# -------------------------------------------------- the taxonomy carries data


@pytest.mark.parametrize("signal", tx.SIGNALS, ids=lambda s: s.key)
def test_no_signal_fires_for_nearly_the_whole_book(signal, book):
    """A condition that holds for everybody is a constant, not a signal.

    This is the test that found `statements_stale` at 180 days firing for
    100% of the book — the threshold was below the minimum the data carries,
    so the signal said "every borrower has stale statements", which is true
    and useless.
    """
    prior = book["prior"]
    fired = 0
    for row in book["rows"]:
        borrower = str(row.get("borrower_id"))
        before = (prior.loc[borrower].to_dict()
                  if borrower in prior.index else {})
        if _expected(signal, row, before):
            fired += 1
    share = fired / max(1, len(book["rows"]))
    assert share <= 0.60, (
        f"{signal.key} fires for {share:.0%} of the book. A condition that "
        "holds for nearly everybody carries no information; the threshold "
        "needs to be where the data actually is.")


@pytest.mark.parametrize("family", sorted(tx.FAMILIES), ids=lambda f: f)
def test_every_family_finds_somebody(family, book):
    """A family that never fires is a family the book cannot support, and it
    belongs in `unavailable()` rather than in the taxonomy."""
    prior = book["prior"]
    for signal in tx.in_family(family):
        for row in book["rows"][:600]:
            borrower = str(row.get("borrower_id"))
            before = (prior.loc[borrower].to_dict()
                      if borrower in prior.index else {})
            if _expected(signal, row, before):
                return
    pytest.skip(
        f"no signal in the {family} family fires anywhere in this book — "
        "which is a statement about the fixture, not a defect")


# ------------------------------------------------------- portfolio properties


@pytest.fixture(scope="module")
def portfolio():
    return sg.portfolio(limit=50)


class TestThePortfolioView:

    def test_it_reads_the_latest_period_and_the_one_before(self, portfolio,
                                                           book):
        assert portfolio["period"] == book["period"]
        assert portfolio["previous_period"] == book["previous_period"]

    def test_it_evaluates_every_borrower_and_returns_a_page(self, portfolio,
                                                            book):
        """Bounded by rows RETURNED, never by rows evaluated: a screen showing
        the fifty worst names must have looked at all of them."""
        assert portfolio["evaluated"] == len(book["rows"])
        assert len(portfolio["borrowers"]) <= 50
        assert portfolio["with_signals"] >= len(portfolio["borrowers"])

    def test_the_ranking_is_by_breadth_then_severity(self, portfolio):
        keys = [(-b["breadth"], -tx.SEVERITY_RANK[b["severity"]],
                 -b["persistence"], -b["worsening"], b["borrower_id"])
                for b in portfolio["borrowers"]]
        assert keys == sorted(keys)

    def test_the_same_call_twice_returns_the_same_page(self):
        """§11. A ranking screen that shows a different tenth name on a
        second visit is not a ranking."""
        first = sg.portfolio(limit=20)
        second = sg.portfolio(limit=20)
        assert ([b["borrower_id"] for b in first["borrowers"]]
                == [b["borrower_id"] for b in second["borrowers"]])

    def test_no_borrower_row_carries_a_score(self, portfolio):
        """§19, §25. The assertion this module exists to make possible."""
        for borrower in portfolio["borrowers"]:
            for key in borrower:
                assert "score" not in key.lower(), (
                    f"{borrower['borrower_id']} carries {key!r}")

    def test_every_returned_borrower_has_at_least_one_signal(self, portfolio):
        for borrower in portfolio["borrowers"]:
            assert borrower["fired"], borrower["borrower_id"]
            assert borrower["breadth"] >= 1

    def test_the_headline_counts_situations_not_raw_signals(self, portfolio):
        """"New signals: 4,812" tells nobody anything."""
        headline = portfolio["headline"]
        assert headline["borrowers"] == portfolio["evaluated"]
        for key in ("with_a_new_signal", "worsening", "persisting", "severe",
                    "multi_family", "booked_stage_2_or_worse"):
            assert 0 <= headline[key] <= headline["borrowers"], key

    def test_the_headline_separates_booked_from_predicted(self, portfolio):
        """§20: never describe an early-warning prediction as an accounting
        stage classification."""
        means = portfolio["headline"]["means"]
        assert "BOOKED" in means["booked_stage_2_or_worse"]
        assert "not a prediction" in means["booked_stage_2_or_worse"]

    def test_it_says_what_it_cannot_watch_for(self, portfolio):
        assert portfolio["unavailable"]

    def test_an_unknown_period_is_refused_rather_than_defaulted(self):
        found = sg.portfolio("Q9 1999")
        assert found["borrowers"] == []
        assert "not a period" in found["note"]

    def test_an_earlier_period_can_still_be_read(self, book):
        found = sg.portfolio(book["previous_period"], limit=5)
        assert found["period"] == book["previous_period"]
        assert found["evaluated"] > 0


class TestLifecycleOverRealData:

    def test_every_lifecycle_state_is_reachable(self, portfolio):
        """If a state never occurs over three thousand borrowers, either the
        rule is wrong or the state is decoration."""
        seen = {o["lifecycle"] for b in portfolio["borrowers"]
                for o in b["fired"]}
        assert sg.NEW in seen
        assert sg.PERSISTING in seen
        assert sg.WORSENING in seen

    def test_a_cured_signal_is_not_also_a_fired_one(self, portfolio):
        for borrower in portfolio["borrowers"]:
            fired = {o["signal"] for o in borrower["fired"]}
            cured = {o["signal"] for o in borrower["cured"]}
            assert not (fired & cured), borrower["borrower_id"]

    def test_conflict_is_reported_where_it_exists(self, portfolio):
        """§26 asks for contradictory evidence by name. Over fifty of the
        worst borrowers, some of them must have something improving."""
        assert any(b["conflict"] or b["improving"]
                   for b in portfolio["borrowers"])
