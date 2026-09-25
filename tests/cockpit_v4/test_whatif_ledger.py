"""The table and the headline are the same number, or nothing is published.

UNIT · NO MODEL. Decimal arithmetic over per-row results. No database, no
provider, not even a scripted one.

Section 13.1 asks for a ledger whose arithmetic is checkable rather than
asserted, and the three properties it turns into are the three things that go
wrong in practice:

* the lines do not sum to the total a reader was shown;
* a row nobody touched moved anyway, by a rounding residue;
* the cohort and the book disappear into two different denominators.

A ledger that fails any of them raises rather than publishing. That is worth
saying plainly, because the alternative -- publishing with a footnote about
small differences -- is exactly how a reader learns to distrust both numbers.

Attribution is here too. Section 13.2 wants a bridge whose bars sum to the
headline, and both the sequential and the Shapley views are tested against
section 17.1's O04 numbers.

Covers the reachable parts of section 16's R01, R04, R05 and D12.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import ledger as lg
from backend.cockpit_v4.scenario.errors import ScenarioError

D = Decimal


def result(baseline: str, scenario: str, disposition: str = dl.SCALED,
           reason: str = "") -> dl.RowResult:
    return dl.RowResult(D(baseline), D(scenario), disposition, reason)


def build(results, **over) -> lg.Ledger:
    body = {"domain_id": dom.CORPORATE, "period": "2026Q2",
            "membership_hash": "0" * 64, "results": results, "labels": None,
            "tolerance": lg.EXACT}
    body.update(over)
    return lg.build(**body)


SIMPLE = {
    "A": result("8000", "9600"),
    "B": result("10000", "10000", dl.UNAFFECTED, "PD does not enter this row"),
    "C": result("1800", "1800", dl.INELIGIBLE, "Stage 3 carries PD 1.0"),
    "Z": result("0", "0", dl.UNSUPPORTED, "the baseline value is zero"),
}


# ---- totals ------------------------------------------------------------

def test_the_lines_are_the_totals() -> None:
    made = build(SIMPLE)
    assert made.baseline == D("19800")
    assert made.scenario == D("21400")
    assert made.change == D("1600")


def test_the_relative_change_is_against_the_cohort_s_own_baseline() -> None:
    made = build(SIMPLE)
    assert made.relative_change() == D("1600") / D("19800") * 100


def test_a_zero_baseline_has_no_percentage_rather_than_a_zero_one() -> None:
    """There is no percentage of nothing, and a displayed 0% would read as
    "the scenario did nothing" rather than "this cannot be expressed as a
    rate"."""
    made = build({"Z": result("0", "0", dl.UNSUPPORTED, "zero baseline")})
    assert made.relative_change() is None
    assert made.totals_row()["relative_change_pct"] == ""


def test_the_book_outside_the_cohort_is_carried_explicitly() -> None:
    """A change of 1,600 on a cohort of 19,800 inside a book of 7,075,662 is
    three different numbers, and a reader shown only two cannot tell which
    denominator a percentage used."""
    made = build(SIMPLE, book_baseline=D("7075662"))
    assert made.outside_cohort == D("7055862")
    assert made.totals_row()["book_baseline_sar_mn"] == "7075662"


# ---- the three checks --------------------------------------------------

def test_an_untouched_row_that_moved_is_refused() -> None:
    with pytest.raises(ScenarioError, match="recorded as untouched"):
        build({"B": result("10000", "10000.01", dl.UNAFFECTED, "untouched")})


@pytest.mark.parametrize("disposition", lg.MUST_NOT_MOVE)
def test_every_disposition_that_must_not_move_is_checked(disposition) -> None:
    with pytest.raises(ScenarioError, match="recorded as untouched"):
        build({"X": result("100", "100.000001", disposition, "why")})


def test_a_scaled_row_is_allowed_to_move() -> None:
    """Which is what makes the check above mean something."""
    made = build({"A": result("8000", "9600")})
    assert made.change == D("1600")


def test_the_untouched_check_admits_no_tolerance_at_all() -> None:
    """A tolerance here would be admitting that the engine computed
    something for a row it was told not to touch. It carries its baseline
    through verbatim, so there is nothing for a floating-point argument to
    excuse."""
    with pytest.raises(ScenarioError):
        build({"B": result("10000", "10000.0000001", dl.UNAFFECTED, "no")},
              tolerance=lg.CURRENCY)


def test_a_bridge_that_does_not_sum_to_the_headline_is_refused() -> None:
    bars = (lg.Contribution(label="PD", fields=("pd_pit_12m",),
                            change=D("1000"), sequence=1),)
    with pytest.raises(ScenarioError, match="bridge sums to"):
        build(SIMPLE, contributions=bars)


def test_a_bridge_that_sums_to_the_headline_is_accepted() -> None:
    bars = (lg.Contribution(label="PD", fields=("pd_pit_12m",),
                            change=D("1600"), sequence=1),)
    made = build(SIMPLE, contributions=bars)
    assert made.contribution_rows()[0]["change_sar_mn"] == "1600"


def test_a_cohort_bigger_than_its_own_book_is_refused() -> None:
    """One of the two was measured on a different population or period, and
    publishing either would be publishing a number about neither."""
    with pytest.raises(ScenarioError, match="exceeds the book"):
        build(SIMPLE, book_baseline=D("100"))


def test_the_book_identity_holds_by_construction() -> None:
    made = build(SIMPLE, book_baseline=D("7075662"))
    assert made.baseline + made.outside_cohort == made.book_baseline
    assert made.reconciles()


def test_reconciles_reports_rather_than_raises() -> None:
    made = lg.Ledger(domain_id=dom.CORPORATE, period="p",
                     membership_hash="0" * 64,
                     lines=(lg.Line("B", D("100"), D("101"), dl.UNAFFECTED),))
    assert made.reconciles() is False


def test_a_ledger_in_hand_has_already_been_checked() -> None:
    """There is no window in which an unchecked one could be read, which is
    why `build` checks rather than leaving it to the caller."""
    with pytest.raises(ScenarioError):
        build({"B": result("100", "101", dl.UNAFFECTED, "untouched")})


# ---- coverage ----------------------------------------------------------

def test_coverage_counts_every_disposition_with_its_reason() -> None:
    """Section 9.1: reason-coded ineligibility, published beside the number
    rather than folded into it."""
    coverage = {c.disposition: c for c in build(SIMPLE).coverage()}
    assert set(coverage) == set(dl.DISPOSITIONS)
    assert coverage[dl.INELIGIBLE].rows == 1
    assert "Stage 3" in coverage[dl.INELIGIBLE].reason
    assert coverage[dl.INELIGIBLE].baseline == D("1800")


def test_coverage_is_ordered_the_way_the_dispositions_are() -> None:
    order = [c.disposition for c in build(SIMPLE).coverage()]
    assert order == [d for d in dl.DISPOSITIONS if d in order]


def test_a_disposition_with_no_rows_is_absent_rather_than_a_zero() -> None:
    coverage = build({"A": result("8000", "9600")}).coverage()
    assert [c.disposition for c in coverage] == [dl.SCALED]


def test_the_rows_that_changed_are_counted_separately() -> None:
    made = build(SIMPLE)
    assert made.covered_rows() == 1
    assert made.totals_row()["rows"] == 4
    assert made.totals_row()["rows_changed"] == 1


def test_an_ineligible_row_stays_in_the_baseline_total() -> None:
    """It keeps its ECL rather than becoming zero, so the book does not
    quietly shrink by the rows a method could not handle."""
    made = build(SIMPLE)
    assert made.baseline == D("19800")
    assert any(ln.disposition == dl.INELIGIBLE and ln.baseline == D("1800")
               for ln in made.lines)


# ---- what gets published -----------------------------------------------

def test_every_published_number_leaves_as_a_string() -> None:
    """A float here would undo the Decimal arithmetic that got it this far."""
    made = build(SIMPLE, book_baseline=D("7075662"))
    for row in made.rows() + made.coverage_rows():
        for key, value in row.items():
            if key.endswith("_sar_mn"):
                assert isinstance(value, str), key
    for key, value in made.totals_row().items():
        if key.endswith("_sar_mn") or key.endswith("_pct"):
            assert isinstance(value, str), key


def test_a_published_row_says_why_it_did_or_did_not_move() -> None:
    """A change of zero could be untouched, ineligible or scaled by one, and
    a reader deciding whether to trust a total needs to know which."""
    by_key = {row["key"]: row for row in build(SIMPLE).rows()}
    assert by_key["B"]["disposition"] == dl.UNAFFECTED
    assert by_key["C"]["reason"]
    assert by_key["A"]["change_sar_mn"] == "1600"


def test_a_label_is_used_where_one_was_given() -> None:
    made = build(SIMPLE, labels={"A": "Al-Faisal Contracting"})
    by_key = {row["key"]: row for row in made.rows()}
    assert by_key["A"]["label"] == "Al-Faisal Contracting"
    assert by_key["B"]["label"] == "B", "the key, where there is no name"


# ---- attribution -------------------------------------------------------

def test_the_sequential_bridge_telescopes_to_the_headline() -> None:
    bars = lg.attribute([("PD", ("pd_pit_12m",), D("9600")),
                         ("LGD", ("lgd_pct",), D("10560"))],
                        baseline=D("8000"))
    assert [c.change for c in bars] == [D("1600"), D("960")]
    assert sum((c.change for c in bars), D(0)) == D("2560")


def test_a_bar_carries_its_position_in_the_canonical_order() -> None:
    """A sequential attribution is only reproducible if the order is
    published with it."""
    bars = lg.attribute([("PD", ("pd_pit_12m",), D("9600")),
                         ("LGD", ("lgd_pct",), D("10560"))],
                        baseline=D("8000"))
    assert [c.sequence for c in bars] == [1, 2]


def test_the_shapley_bridge_also_sums_to_the_headline() -> None:
    bars = lg.shapley({frozenset(): D("8000"),
                       frozenset({"PD"}): D("9600"),
                       frozenset({"LGD"}): D("8800"),
                       frozenset({"PD", "LGD"}): D("10560")},
                      baseline=D("8000"))
    assert sum((c.change for c in bars), D(0)) == D("2560")


def test_a_shapley_over_one_intervention_is_just_its_effect() -> None:
    bars = lg.shapley({frozenset(): D("8000"), frozenset({"PD"}): D("9600")},
                      baseline=D("8000"))
    assert [c.change for c in bars] == [D("1600")]


def test_a_shapley_over_three_interventions_still_adds_up() -> None:
    """Three factors need eight coalitions, and the weights are exact
    rationals rather than a Decimal division by six partway through."""
    base = D("1000")
    effects = {"P": D("1.2"), "L": D("1.1"), "E": D("1.05")}
    values = {}
    for mask in range(8):
        members = {name for i, name in enumerate(effects) if mask >> i & 1}
        value = base
        for name in members:
            value *= effects[name]
        values[frozenset(members)] = value
    bars = lg.shapley(values, baseline=base)
    whole = values[frozenset(effects)] - base
    assert abs(sum((c.change for c in bars), D(0)) - whole) < D("1e-30")


def test_an_empty_attribution_is_empty_rather_than_an_error() -> None:
    assert lg.attribute([], baseline=D("8000")) == ()
    assert lg.shapley({}, baseline=D("8000")) == ()
