"""The nine conditions the screen used to say it could not watch for. §1.

The signals screen carried a box headed "What this deployment cannot watch
for", and every entry in it was liquidity or external context: receivable
days, free cash flow, the maturity schedule, cash and committed headroom as a
buffer. Those were true statements and the wrong answer, because liquidity is
where a corporate credit actually fails — a borrower does not default because
its leverage ratio drifted, it defaults because a payment fell due and the
cash was not there.

So the data was built and these nine conditions were written against it.
These tests hold three things: the signals exist and read fields the
catalogue actually carries, they FIRE on the real book at rates a credit
officer would recognise, and the limitation list shrank because the data
arrived rather than because the box was deleted.
"""

from __future__ import annotations

import pytest

from backend.early_warning import signals as ews
from backend.early_warning import taxonomy as tx

#: The nine, and the band each should fire in. A signal that never fires is
#: decoration; one that fires on most of the book is not a warning, it is a
#: description of the book. Both ends are asserted.
NEW_SIGNALS: tuple[tuple[str, float, float], ...] = (
    ("receivable_days_stretched", 1.0, 25.0),
    ("receivable_days_rose", 2.0, 30.0),
    ("cash_cycle_stretched", 0.3, 20.0),
    ("capex_starved", 1.0, 25.0),
    ("liquidity_buffer_thin", 1.0, 30.0),
    ("committed_headroom_thin", 2.0, 35.0),
    ("short_term_debt_heavy", 1.0, 30.0),
    ("maturity_wall", 2.0, 40.0),
    ("near_maturity_uncovered", 1.0, 30.0),
)


@pytest.fixture(scope="module")
def book():
    ews.reset()
    found = ews.portfolio(limit=4000)
    if not found.get("borrowers"):
        pytest.skip("the corporate book is not built in this environment")
    return found


@pytest.fixture(scope="module")
def rates(book) -> dict[str, float]:
    tally: dict[str, int] = {}
    for row in book["borrowers"]:
        for fired in row["fired"]:
            tally[fired["signal"]] = tally.get(fired["signal"], 0) + 1
    evaluated = max(int(book["evaluated"]), 1)
    return {key: 100.0 * count / evaluated for key, count in tally.items()}


class TestTheSignalsExist:
    @pytest.mark.parametrize("key", [k for k, _, _ in NEW_SIGNALS])
    def test_it_is_in_the_taxonomy(self, key: str):
        assert key in tx.BY_KEY

    @pytest.mark.parametrize("key", [k for k, _, _ in NEW_SIGNALS])
    def test_it_reads_a_field_the_catalogue_carries(self, key: str):
        from backend import metadata as md

        signal = tx.BY_KEY[key]
        dataset = md.dataset(signal.dataset)
        assert dataset is not None, f"{signal.dataset} is not governed"
        assert dataset.field(signal.field) is not None, (
            f"{signal.dataset} does not carry {signal.field}")
        if signal.against:
            assert dataset.field(signal.against) is not None, (
                f"{signal.dataset} does not carry {signal.against}")

    def test_they_are_spread_across_the_families_that_needed_them(self):
        families = {tx.BY_KEY[k].family for k, _, _ in NEW_SIGNALS}
        assert tx.LIQUIDITY in families
        assert tx.FINANCIAL in families


@pytest.mark.parametrize(("key", "floor", "ceiling"), NEW_SIGNALS,
                         ids=[k for k, _, _ in NEW_SIGNALS])
def test_each_signal_fires_at_a_rate_a_credit_officer_would_recognise(
        rates: dict[str, float], key: str, floor: float, ceiling: float):
    """A signal that never fires is decoration. One that fires on most of the
    book is not a warning, it is a description of the book.

    Both ends were hit while writing these. "Capital expenditure cut sharply"
    was written as `FELL_BY 0.0`, which is ANY decrease, and fired on 67% of
    borrowers every quarter; it now tests capex against revenue. And the
    generator committed 72% of a sanctioned limit, which made "little
    committed headroom" arithmetically true for half the book — a structural
    artefact rather than a signal.
    """
    rate = rates.get(key, 0.0)
    assert rate >= floor, (
        f"{key} fired on {rate:.1f}% of the book, below the {floor}% floor — "
        f"a signal nothing trips is decoration")
    assert rate <= ceiling, (
        f"{key} fired on {rate:.1f}% of the book, above the {ceiling}% "
        f"ceiling — that is a description of the book, not a warning")


class TestTheLimitationListShrankBecauseTheDataArrived:
    def test_liquidity_is_no_longer_listed_as_unwatchable(self):
        families = {entry["family"] for entry in tx.unavailable()}
        assert tx.LIQUIDITY not in families
        assert tx.FINANCIAL not in families
        assert tx.LEVERAGE not in families
        assert tx.BEHAVIOURAL not in families
        assert tx.COLLATERAL not in families
        assert tx.RATING not in families

    def test_what_remains_is_stated_rather_than_emptied(self):
        """The mechanism stays. An empty list would be a claim that nothing
        is ever missing, which is a different and worse thing to say."""
        assert tx.UNAVAILABLE, (
            "the list was emptied rather than reduced to what is still true")
        for family, why in tx.UNAVAILABLE:
            assert family in tx.FAMILIES
            assert len(why) > 30, "a limitation has to say what is missing"

    def test_the_screen_shows_the_box_only_when_there_is_something_in_it(self):
        """`unavailable()` drives the box; a family with nothing missing
        returns nothing, and the card renders null on an empty list."""
        assert tx.unavailable(tx.LIQUIDITY) == []
        assert tx.unavailable(tx.COVENANT)


def test_the_published_signal_count_matches_the_taxonomy(book):
    """A caption reading "34 governed conditions" over a taxonomy carrying
    forty-three is a small lie that nobody notices until somebody counts."""
    assert book["signal_count"] == len(tx.SIGNALS)
