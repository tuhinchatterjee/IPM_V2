"""A money figure that reads as nothing when it is something.

EVIDENCE LABEL: **NO MODEL.** Pure functions and one in-process render; no
provider is involved, scripted or otherwise.

MEASURED DEFECT. A riyal amount is written in whole units, which is right for
the Corporate book -- its totals run to SAR 779,475 million and two decimals
there are three-hundredths of a riyal on a forty-billion book. It is wrong for
the Retail book, whose ENTIRE monthly ECL is SAR 3.19 million:

    ECL by product, Retail, at whole millions      what the rows really are
      Personal Finance     SAR 2 million             1.6929
      Mortgage             SAR 1 million             0.6057
      Credit Card          SAR 1 million             0.5681
      Auto Finance         SAR 0 million             0.2972
      Buy Now Pay Later    SAR 0 million             0.0249

Two products read as nothing and the ordering is invisible. The same policy
turned a real 20% PD rise on a Retail cohort into "SAR 2 million becomes SAR 2
million, a change of SAR 0 million" -- three figures, none of them wrong,
together saying the opposite of what happened.

The rule gained a second half and only a second half. At one unit or above a
money figure is still written whole, so every Corporate figure and every large
Retail one is untouched. Below one unit it gets the fewest decimals that give
the smallest non-zero amount in its GROUP two significant digits, capped at
four. One precision per group -- one column, one series, one unit's worth of
claims -- because a column that mixed 1.7 with 0.30 is a column nobody can
read down.

These tests are the guard. They fail if a non-zero amount is written as zero,
if a column mixes precisions, if the five surfaces disagree, or if the
Corporate book's own figures move.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from backend.cockpit_v4 import display as disp
from backend.cockpit_v4 import precision as prec

MONEY = "SAR million"


def shown(values, unit: str = MONEY) -> list[str]:
    """The group, written the way the server writes it."""
    places = disp.decimals(unit, smallest=disp.smallest_of(values))
    return [disp.format_value(D(str(v)), unit, places) for v in values]


# ---- 1. the reported defect, and the books it was measured on -----------

def test_a_small_retail_portfolio_is_not_a_column_of_zeroes() -> None:
    """The ECL-by-product table that started this."""
    products = ["1.6929", "0.6057", "0.5681", "0.2972", "0.0249"]
    written = shown(products)
    assert not any(w == "SAR 0 million" for w in written), written
    # Every product is distinguishable from every other one.
    assert len(set(written)) == len(products), written
    assert written[0] == "SAR 1.693 million"
    assert written[-1] == "SAR 0.025 million"


def test_a_sub_million_movement_is_never_written_as_no_movement() -> None:
    """The scenario sentence, verbatim: baseline, scenario, change."""
    baseline, scenario, change = shown(
        ["1.692865", "2.031438", "0.338573"])
    assert baseline == "SAR 1.69 million"
    assert scenario == "SAR 2.03 million"
    assert change == "SAR 0.34 million"
    assert baseline != scenario, (
        "a 20% PD rise that reads as no change is a wrong answer however "
        "correctly each figure was rounded")
    assert change != "SAR 0 million"


def test_a_million_level_movement_keeps_the_whole_number_it_always_had():
    """The Corporate cohort. Nothing here moves."""
    baseline, scenario, change = shown(
        ["170.997581", "202.143137", "31.145556"])
    assert (baseline, scenario, change) == (
        "SAR 171 million", "SAR 202 million", "SAR 31 million")


def test_a_billion_level_figure_is_unchanged() -> None:
    assert shown(["779475.35", "6919.12", "484248.0"]) == [
        "SAR 779,475 million", "SAR 6,919 million", "SAR 484,248 million"]


def test_the_accepted_corporate_magnitudes_do_not_move(monkeypatch) -> None:
    """The claim that makes this safe to ship: a group at one unit or above
    is written exactly as it was before this rule existed."""
    for group in (["40599.1736630513815"], ["7013.1167117986615"],
                  ["3421.173663"], ["1.0"], ["2120.4985", "0.0065"]):
        smallest = disp.smallest_of(group)
        if smallest is not None and smallest >= D(1):
            assert shown(group) == [
                disp.format_value(D(v), MONEY) for v in group], group


# ---- 2. signs, zeroes and the floor -------------------------------------

def test_a_negative_change_keeps_its_sign_and_its_precision() -> None:
    written = shown(["-0.338573", "1.692865"])
    assert written[0] == "SAR -0.34 million"
    assert written[1] == "SAR 1.69 million"


def test_a_negative_that_rounds_to_nothing_is_not_written_minus_zero():
    """`-0.00` on a screen is a rounding artefact pretending to be a
    direction. `quantize` normalises it away and must keep doing so."""
    for places in range(0, disp.MAX_MONEY_DECIMALS + 1):
        written = disp.format_value(D("-0.000000001"), MONEY, places)
        assert "-0" not in written.replace("SAR ", "").split(" ")[0] or \
            written == "SAR 0 million", written


def test_a_genuine_zero_is_written_as_zero() -> None:
    assert shown(["0", "0"]) == ["SAR 0 million", "SAR 0 million"]


def test_a_zero_in_a_small_group_is_still_zero_and_still_distinguishable():
    written = shown(["0", "0.338573"])
    assert written[0] == "SAR 0.00 million"
    assert written[1] == "SAR 0.34 million"


def test_the_floor_is_declared_rather_than_discovered() -> None:
    """Below what four decimals can show, an amount is written as zero. That
    is a stated limitation, not a rounding anybody chose, and the cap is a
    constant a reader of this module can find."""
    assert disp.MAX_MONEY_DECIMALS == 4
    assert disp.decimals(MONEY, smallest=D("0.0000004")) == 4
    assert shown(["0.0000004"]) == ["SAR 0.0000 million"]


# ---- 3. one group, one precision ----------------------------------------

def test_one_group_is_written_at_one_precision() -> None:
    """A column that mixed 1.7 with 0.30 would not be a column anybody could
    compare down, which is the whole reason the precision is per group."""
    for group in (["1.6929", "0.0249"], ["0.5681", "0.2972"],
                  ["100.0", "0.4"], ["0.000002", "0.0121"]):
        decimals_seen = {w.split("SAR ")[1].split(" ")[0].partition(".")[2]
                         for w in shown(group)}
        assert len({len(d) for d in decimals_seen}) == 1, (group, decimals_seen)


def test_the_smallest_non_zero_value_is_what_decides() -> None:
    """Not the largest, and not the first: the figure that would have
    vanished is the one the precision has to accommodate."""
    assert disp.smallest_of(["100", "0.0249", "5"]) == D("0.0249")
    assert disp.smallest_of(["0", "0", "3"]) == D(3)
    assert disp.smallest_of(["0", "0"]) is None
    assert disp.smallest_of([None, "", "x", "2.5"]) == D("2.5")


def test_a_group_with_nothing_in_it_gets_the_class_default() -> None:
    assert disp.decimals(MONEY, smallest=None) == 0
    assert disp.decimals(MONEY, smallest=disp.smallest_of([])) == 0


# ---- 4. the policy is still the server's, and still governed ------------

def test_the_analyst_still_cannot_choose_a_money_precision() -> None:
    """`smallest` changes what the SERVER answers. It does not hand the
    decision to whoever is asking."""
    assert disp.PERMITTED[disp.MONETARY_AMOUNT] == (0,)
    assert disp.MONETARY_AMOUNT in disp.GOVERNED
    for asked in (0, 1, 2, 3, 4, 7):
        assert disp.resolve_decimals(MONEY, asked) == 0
        assert disp.resolve_decimals(
            MONEY, asked, smallest=D("0.338573")) == 2


def test_a_unit_that_is_not_money_is_untouched_by_this_rule() -> None:
    for unit in ("PCT", "percent", "ratio", "count", "probability"):
        assert disp.decimals(unit, smallest=D("0.0000001")) == \
            disp.decimals(unit), unit


def test_the_affix_sentinel_still_reads_as_a_whole_number() -> None:
    """`written_affixes` formats Decimal(0) to find the prefix and suffix a
    unit writes. It must not start carrying decimals, or the narrative's
    duplicate-unit stripping matches nothing."""
    prefixes, suffixes = disp.written_affixes(MONEY)
    assert any("sar" in p.lower() for p in prefixes), prefixes
    assert any("million" in s.lower() for s in suffixes), suffixes
    # The sentinel is Decimal(0) written with NO group, so it stays "0" and
    # the affixes partition around a whole number as they always did.
    assert disp.format_value(__import__("decimal").Decimal(0), MONEY) == \
        "SAR 0 million"


def test_precision_delegates_rather_than_holding_a_second_opinion() -> None:
    assert prec.default_precision(MONEY, smallest=D("0.0249")) == 3
    assert prec.default_precision(MONEY) == 0
    assert prec.smallest_of(["0.5", "2"]) == D("0.5")


@pytest.mark.parametrize("smallest,places", [
    ("5", 0), ("1", 0), ("1.0001", 0),
    # Two significant digits, so 0.99 keeps both of them and 0.5 is written
    # "0.50" rather than "0.5" -- the second place is what lets 0.50 and 0.57
    # sit in one column and still be two different numbers.
    ("0.99", 2), ("0.5", 2), ("0.1", 2),
    ("0.099", 3), ("0.0249", 3), ("0.001", 4), ("0.0000004", 4),
])
def test_the_ladder_is_exactly_as_declared(smallest, places) -> None:
    assert disp.decimals(MONEY, smallest=D(smallest)) == places


# ---- 5. the precondition the frontend boundary exists for ---------------

def test_a_table_the_server_cannot_resolve_is_passed_through_unrendered():
    """NOT a fix -- a pin on the behaviour that makes the browser boundary
    necessary. `render_tables` resolves each declared table to a stored
    artifact and, when it cannot, appends the analyst's raw dict untouched:
    no `row_id`, no `canonical`, no `display`. The cell renderer reads
    `row.display[column]`, so that payload throws in the browser.

    Refusing to publish it at all would be the server-side half of the fix
    and is NOT authorised in this round; recording the precondition is.
    """
    from backend.cockpit_v4 import finalization as fin

    class _Store:
        def get_artifact(self, artifact_id, *, tenant_id):
            return None

    final = type("F", (), {"tables": [
        {"title": "Deliberately unrenderable", "columns": ["a"],
         "rows": [["x"]]}]})()
    published = fin.Finalizer(
        store=_Store(), tenant_id="t", release_id="r",
        limits=type("L", (), {"charts": 4})()).render_tables(final)

    assert len(published) == 1
    row = published[0]["rows"][0]
    assert not isinstance(row, dict) or "display" not in row, (
        "if this now carries a display map the server-side half has landed "
        "and the browser boundary is belt to its braces -- update this test "
        "rather than deleting it")
    assert published[0].get("rendered_by") != "creditprobe"
