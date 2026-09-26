"""Section 17.1's hand fixture, and the twelve numbers it must produce.

UNIT · INDEPENDENT ORACLE. No model, no provider call, no database.

The fixture is four artificial rows the specification gives by hand, and its
amounts are artificial currency units -- section 17.1 says so in as many
words, and they are not CreditProbe portfolio results and are not to be
copied anywhere they could be mistaken for one.

    ID   EAD        PD    LGD   ECL      note
    A    1,000,000   2%   40%   8,000    performing
    B      500,000   4%   50%  10,000    performing, different sector
    C       90,000   5%   40%   1,800    drawn 80,000, undrawn 20,000, CCF 50%
    Z      100,000   0%   40%       0    the zero-baseline boundary

Baseline total: 19,800.

**Every expected value here is computed from EAD, PD and LGD, or written as
a literal from the specification.** None of them calls `delta`, `units` or
`ledger` to find out what to expect. Section 17.1 is explicit about why:
*"A test that calls the same defective function to obtain both actual and
expected values is not evidence."* So `ecl(ead, pd, lgd)` below is three
multiplications written out here, and if it and the engine ever disagree,
one of them is wrong and the test says which numbers differ.

O12 is not here. It needs a population above the display cap and therefore a
real book, so it lives in `test_whatif_sql.py` where the database is.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import ledger as lg
from backend.cockpit_v4.scenario import preview as pv
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario import userdefined as ud

D = Decimal


# ---- the oracle's own arithmetic, owing nothing to the code under test ---

def ecl(ead: Decimal, pd: Decimal, lgd_fraction: Decimal) -> Decimal:
    """Expected credit loss, written out. Three multiplications, by hand."""
    return ead * pd * lgd_fraction


#: The fixture, in the storage conventions the Corporate field dictionary
#: declares: PD as a fraction, LGD as a percent, money as money. `stage = 1`
#: because all four are performing, which is what makes the 12-month PD the
#: one that enters ECL.
FIXTURE: dict[str, dict[str, Any]] = {
    "A": {"ead_sar_mn": D("1000000"), "pd_pit_12m": D("0.02"),
          "lgd_pct": D("40"), "ecl_sar_mn": D("8000"), "stage": D(1),
          "drawn_sar_mn": D("1000000"), "undrawn_sar_mn": D("0"),
          "write_off_sar_mn": D("0")},
    "B": {"ead_sar_mn": D("500000"), "pd_pit_12m": D("0.04"),
          "lgd_pct": D("50"), "ecl_sar_mn": D("10000"), "stage": D(1),
          "drawn_sar_mn": D("500000"), "undrawn_sar_mn": D("0"),
          "write_off_sar_mn": D("0")},
    "C": {"ead_sar_mn": D("90000"), "pd_pit_12m": D("0.05"),
          "lgd_pct": D("40"), "ecl_sar_mn": D("1800"), "stage": D(1),
          "drawn_sar_mn": D("80000"), "undrawn_sar_mn": D("20000"),
          "ccf": D("0.5"), "write_off_sar_mn": D("0")},
    "Z": {"ead_sar_mn": D("100000"), "pd_pit_12m": D("0"),
          "lgd_pct": D("40"), "ecl_sar_mn": D("0"), "stage": D(1),
          "drawn_sar_mn": D("100000"), "undrawn_sar_mn": D("0"),
          "write_off_sar_mn": D("0")},
}

BASELINE_TOTAL = D("19800")


def shock(field_id: str, value: str, operation: str = un.RELATIVE,
          **over) -> sp.Shock:
    return sp.Shock(field_id=field_id,
                    amount=un.parse(value, operation,
                                    raw=f"{field_id} {value}"),
                    origin=over.pop("origin", ""), **over)


def plan_for(*shocks: sp.Shock, submode: str = sp.PROPORTIONAL) -> dl.Plan:
    """A Delta plan over the Corporate field dictionary.

    The fixture is Corporate-shaped -- a facility with drawn, undrawn and a
    derived CCF -- so it reads its units and its eligibility rules from the
    Corporate book even though the amounts are invented.
    """
    spec = sp.ScenarioSpec(
        scenario_id="fixture", version=1,
        source=sp.SourceRef(domain_id=dom.CORPORATE, release_id="fixture",
                            release_fingerprint="0" * 16,
                            reporting_period="fixture"),
        cohort=sp.CohortRef(cohort_id="fx", membership_hash="0" * 64,
                            grain="facility", entity_count=len(FIXTURE),
                            baseline_ecl=str(BASELINE_TOTAL)),
        shocks=shocks, delta_submode=submode)
    return dl.plan(spec)


def run(plan: dl.Plan, ids=("A", "B", "C", "Z")) -> dict[str, dl.RowResult]:
    """Apply a plan to some of the fixture; the rest keep their baseline."""
    out: dict[str, dl.RowResult] = {}
    for key, row in FIXTURE.items():
        if key in ids:
            out[key] = dl.scale_row(plan, row)
        else:
            base = row["ecl_sar_mn"]
            out[key] = dl.RowResult(base, base, dl.UNAFFECTED,
                                    "outside the cohort")
    return out


def total(results: dict[str, dl.RowResult]) -> Decimal:
    return sum((r.scenario_ecl for r in results.values()), D(0))


# ---- the fixture is what the specification says it is -------------------

def test_the_fixture_reconciles_to_its_own_published_ecl() -> None:
    """If the four rows do not produce 19,800 by hand, nothing after this
    means anything."""
    for key, row in FIXTURE.items():
        computed = ecl(row["ead_sar_mn"], row["pd_pit_12m"],
                       row["lgd_pct"] / 100)
        assert computed == row["ecl_sar_mn"], key
    assert sum((r["ecl_sar_mn"] for r in FIXTURE.values()),
               D(0)) == BASELINE_TOTAL


def test_c_s_exposure_is_drawn_plus_converted_undrawn() -> None:
    row = FIXTURE["C"]
    assert (row["drawn_sar_mn"] + D("0.5") * row["undrawn_sar_mn"]
            == row["ead_sar_mn"])
    assert dl.baseline_ccf(row) == D("0.5")


# ---- O01 ---------------------------------------------------------------

def test_o01_a_full_book_proportional_pd_stress() -> None:
    """PD +20% relative for A/B/C, Z unchanged: total 23,760, up 3,960.

    Expected computed from the primitives: each row's own EAD x (PD x 1.2) x
    LGD, never from the engine's multiplier.
    """
    expected = sum(
        (ecl(r["ead_sar_mn"], r["pd_pit_12m"] * D("1.2"), r["lgd_pct"] / 100)
         for r in FIXTURE.values()), D(0))
    assert expected == D("23760")

    results = run(plan_for(shock("pd_pit_12m", "20")))
    assert total(results) == D("23760")
    assert total(results) - BASELINE_TOTAL == D("3960")


def test_o01_z_is_neutral_and_that_is_not_a_licence_to_divide() -> None:
    """Zero PD raised 20% relative is still zero, so Z contributes nothing
    and is not unsupported. Section 10.3's zero-to-POSITIVE case is O11, and
    the two must not be confused."""
    results = run(plan_for(shock("pd_pit_12m", "20")))
    assert results["Z"].scenario_ecl == D("0")
    assert results["Z"].disposition == dl.SCALED
    assert results["Z"].change == D("0")


# ---- O02 ---------------------------------------------------------------

def test_o02_a_cohort_of_one_leaves_the_rest_of_the_book_alone() -> None:
    """PD +20% for A only: A becomes 9,600 and the book totals 21,400."""
    assert ecl(D("1000000"), D("0.02") * D("1.2"), D("0.40")) == D("9600")

    results = run(plan_for(shock("pd_pit_12m", "20")), ids=("A",))
    assert results["A"].scenario_ecl == D("9600")
    assert total(results) == D("21400")
    for key in ("B", "C", "Z"):
        assert results[key].change == D("0"), key


# ---- O03 ---------------------------------------------------------------

def test_o03_two_parameters_compose_multiplicatively_not_additively() -> None:
    """A with PD +20% and LGD +10%: 10,560, not the first-order 10,400.

    The difference is the interaction term, 160, and a bridge that drops it
    reports a smaller loss than the scenario it was asked about.
    """
    expected = ecl(D("1000000"), D("0.02") * D("1.2"),
                   D("0.40") * D("1.1"))
    assert expected == D("10560")
    first_order = D("8000") + D("1600") + D("800")
    assert first_order == D("10400") and first_order != expected

    results = run(plan_for(shock("pd_pit_12m", "20"), shock("lgd_pct", "10")),
                  ids=("A",))
    assert results["A"].scenario_ecl == D("10560")
    assert results["A"].change == D("2560")
    assert total(results) == D("22360")


# ---- O04 ---------------------------------------------------------------

def test_o04_shapley_splits_the_interaction_evenly() -> None:
    """Standalone PD 1,600, standalone LGD 800, interaction 160. Shapley
    gives PD 1,680 and LGD 880, which sum to the whole 2,560."""
    baseline = D("8000")
    pd_only = ecl(D("1000000"), D("0.02") * D("1.2"), D("0.40"))
    lgd_only = ecl(D("1000000"), D("0.02"), D("0.40") * D("1.1"))
    both = ecl(D("1000000"), D("0.02") * D("1.2"), D("0.40") * D("1.1"))
    assert pd_only - baseline == D("1600")
    assert lgd_only - baseline == D("800")
    assert (both - baseline) - D("1600") - D("800") == D("160")

    bars = lg.shapley({frozenset(): baseline,
                       frozenset({"PD"}): pd_only,
                       frozenset({"LGD"}): lgd_only,
                       frozenset({"PD", "LGD"}): both}, baseline=baseline)
    got = {c.label: c.change for c in bars}
    assert got["PD"] == D("1680")
    assert got["LGD"] == D("880")
    assert got["PD"] + got["LGD"] == both - baseline


def test_o04_the_sequential_bridge_is_a_different_valid_view() -> None:
    """PD then LGD gives 1,600 and 960. Both views are legitimate when
    labelled; mixing them is what section 13.2 forbids."""
    baseline = D("8000")
    after_pd = ecl(D("1000000"), D("0.02") * D("1.2"), D("0.40"))
    after_both = ecl(D("1000000"), D("0.02") * D("1.2"), D("0.40") * D("1.1"))
    bars = lg.attribute([("PD", ("pd_pit_12m",), after_pd),
                         ("LGD", ("lgd_pct",), after_both)], baseline=baseline)
    assert [c.change for c in bars] == [D("1600"), D("960")]
    assert sum((c.change for c in bars), D(0)) == after_both - baseline


def test_o04_the_two_views_are_named_so_they_cannot_be_mixed() -> None:
    assert lg.SEQUENTIAL != lg.SHAPLEY


def test_o04_a_shapley_over_some_of_the_coalitions_is_refused() -> None:
    """An average over a subset is a different quantity with the same name,
    and publishing it as Shapley would be a wrong label on a real number."""
    with pytest.raises(Exception, match="coalitions"):
        lg.shapley({frozenset({"PD"}): D("9600"),
                    frozenset({"PD", "LGD"}): D("10560")},
                   baseline=D("8000"))


# ---- O05 ---------------------------------------------------------------

def test_o05_a_ccf_move_has_two_answers_and_they_differ() -> None:
    """Proportional gives 2,160; structural gives EAD 92,000 and ECL 1,840.

    Both are correct answers to different questions, which is exactly why
    the submode has to be stated rather than defaulted to silently.
    """
    proportional = D("1800") * (D("0.6") / D("0.5"))
    assert proportional == D("2160")

    structural_ead = D("80000") + D("0.6") * D("20000")
    assert structural_ead == D("92000")
    structural = ecl(structural_ead, D("0.05"), D("0.40"))
    assert structural == D("1840")

    got = dl.scale_row(plan_for(shock("ccf", "20")), FIXTURE["C"])
    assert got.scenario_ecl == D("2160")

    rebuilt = dl.structural_ead(FIXTURE["C"], domain_id=dom.CORPORATE,
                                moved={"ccf": D("0.6")})
    assert rebuilt == D("92000")
    assert ecl(rebuilt, D("0.05"), D("0.40")) == D("1840")


def test_o05_multiplying_by_both_the_ccf_and_the_ead_effect_is_caught(
) -> None:
    """2,208 is 1,800 x 1.2 x (92,000 / 90,000): the CCF counted twice,
    once as a ratio and once through the exposure it rebuilt."""
    double_counted = D("1800") * D("1.2") * (D("92000") / D("90000"))
    assert double_counted.quantize(D("0.01")) == D("2208.00")
    got = dl.scale_row(plan_for(shock("ccf", "20")), FIXTURE["C"])
    assert got.scenario_ecl != double_counted
    assert ecl(D("92000"), D("0.05"), D("0.40")) != double_counted


def test_o05_a_proportional_ccf_run_says_which_answer_it_gave() -> None:
    notes = " ".join(plan_for(shock("ccf", "20")).notes)
    assert "structural" in notes and "2,160" in notes and "1,840" in notes


# ---- O06 ---------------------------------------------------------------

def test_o06_twenty_basis_points_is_not_twenty_percent_is_not_set_to_twenty(
) -> None:
    """PD 2% is three different things away from three different answers,
    and the specification names all three so none can be defaulted to."""
    pd = D("0.02")
    assert un.apply(pd, un.parse("20", un.BASIS_POINTS),
                    storage=un.FRACTION) == D("0.022")
    assert un.apply(pd, un.parse("20", un.RELATIVE),
                    storage=un.FRACTION) == D("0.024")
    assert un.apply(pd, un.parse("20", un.SET_TO),
                    storage=un.FRACTION) == D("0.20")

    got = {un.apply(pd, un.parse("20", op), storage=un.FRACTION)
           for op in (un.BASIS_POINTS, un.RELATIVE, un.SET_TO)}
    assert len(got) == 3, "three readings, three answers"


def test_o06_the_wrong_readings_the_specification_names_are_not_produced(
) -> None:
    """*"becomes 2.2%, not 22% or 2.02%."*"""
    moved = un.apply(D("0.02"), un.parse("20", un.BASIS_POINTS),
                     storage=un.FRACTION)
    assert moved != D("0.22") and moved != D("0.0202")


# ---- O07 ---------------------------------------------------------------

def test_o07_the_unemployment_mapping_arithmetic() -> None:
    """Unemployment 6.0% down 10% relative is 5.4%; a slope of 0.20 PD
    points per unemployment point moves PD 3.00% to 2.88%; and a Delta whose
    only changed input is that PD moves ECL 10,000 to 9,600.

    The registry that would hold the slope does not exist in either book --
    the next test says so -- so this pins the arithmetic P5 will need,
    nothing more.
    """
    unemployment = un.apply(D("6.0"), un.parse("-10", un.RELATIVE),
                            storage=un.PERCENT)
    assert unemployment == D("5.40")

    move_pp = unemployment - D("6.0")
    assert move_pp == D("-0.60")
    pd = D("3.00") + D("0.20") * move_pp
    assert pd == D("2.8800")

    assert D("10000") * (pd / D("3.00")) == D("9600")


def test_o07_no_macro_factor_exists_to_attach_a_slope_to() -> None:
    """Section 7.1: *"Never present missing factors as zero."* A slope with
    no driver in the book is not a sensitivity, and asking for one is
    refused rather than answered with a default."""
    from backend.cockpit_v4.scenario import fields as fd
    from backend.cockpit_v4.scenario.errors import ScenarioError

    for domain_id in (dom.CORPORATE, dom.RETAIL):
        with pytest.raises(ScenarioError):
            fd.lookup(domain_id, "unemployment_rate")


# ---- O08 ---------------------------------------------------------------

def test_o08_a_held_overlay_is_added_back_not_scaled() -> None:
    """A declared variant of A: ECL 8,000 as modelled 7,600 plus overlay
    400. PD +20% gives 9,120 + 400 = 9,520, not 9,600.

    Declared as a variant, exactly as section 17.1 asks -- the base fixture
    is not changed behind the other eleven oracles' backs.
    """
    assert D("7600") * D("1.2") + D("400") == D("9520")

    variant = dict(FIXTURE["A"], overlay_sar_mn=D("400"))
    got = dl.scale_row(plan_for(shock("pd_pit_12m", "20")), variant)
    assert got.baseline_ecl == D("8000")
    assert got.scenario_ecl == D("9520")
    assert got.scenario_ecl != D("9600")


def test_o08_the_base_fixture_carries_no_overlay_and_is_unchanged() -> None:
    assert "overlay_sar_mn" not in FIXTURE["A"]
    got = dl.scale_row(plan_for(shock("pd_pit_12m", "20")), FIXTURE["A"])
    assert got.scenario_ecl == D("9600")


def test_o08_neither_published_book_splits_modelled_from_overlay() -> None:
    """Which is why the overlay defaults to zero: `ecl.py` refuses to invent
    the split, and so does this."""
    from backend.cockpit_v4.scenario import fields as fd

    for domain_id in (dom.CORPORATE, dom.RETAIL):
        names = {f.field_id for f in fd.BY_DOMAIN[domain_id]}
        assert not {"ecl_modelled_sar_mn", "ecl_overlay_sar_mn",
                    "overlay_sar_mn"} & names


# ---- O09 ---------------------------------------------------------------

def test_o09_ml_anchoring_is_additive_against_the_observed_baseline() -> None:
    """Raw baseline 7,800 and raw stress 9,500 against an observed 8,000
    gives 9,700, not 9,500: the model supplies the CHANGE and the book
    supplies the level."""
    raw_baseline, raw_stressed, observed = D("7800"), D("9500"), D("8000")
    anchored = observed + (raw_stressed - raw_baseline)
    assert anchored == D("9700")
    assert anchored - observed == D("1700")
    assert anchored != raw_stressed


def test_o09_a_zero_shock_anchors_back_to_the_observed_figure() -> None:
    observed = D("8000")
    assert observed + (D("7800") - D("7800")) == observed


def test_o09_method_two_reports_not_ready_rather_than_a_number() -> None:
    """Section 11.5: *"A failed model gate cannot be declared a completed ML
    capability."* It was never built here, which is the same answer."""
    spec = sp.ScenarioSpec(
        scenario_id="fx", version=1,
        source=sp.SourceRef(domain_id=dom.CORPORATE, release_id="fixture",
                            release_fingerprint="0" * 16,
                            reporting_period="fixture"),
        cohort=sp.CohortRef(cohort_id="fx", membership_hash="0" * 64,
                            grain="facility", entity_count=4),
        methods=(sp.DELTA, sp.ML))
    # "fixture" is not a release any emulator was fitted on, so the answer is
    # MODEL_NOT_READY and the reason says which of the several possible
    # reasons it is. Asserted as a prefix because the reason is the point:
    # this used to be a hardcoded constant, which was true while nothing was
    # trained and would have gone on saying so afterwards.
    told = pv.readiness(spec)[sp.ML]
    assert told.startswith("MODEL_NOT_READY")
    assert "fixture" in told or "no emulator is published" in told


# ---- O10 ---------------------------------------------------------------

def test_o10_an_extra_thousand_splits_444_44_and_555_56() -> None:
    """In proportion to baselines of 8,000 and 10,000, at two-decimal
    precision, summing to exactly 1,000."""
    got = ud.allocate(D("1000"), [D("8000"), D("10000")],
                      keys=["A", "B"])
    assert got == [D("444.44"), D("555.56")]
    assert sum(got, D(0)) == D("1000")


def test_o10_reordering_the_rows_does_not_move_the_allocation() -> None:
    forwards = ud.allocate(D("1000"), [D("8000"), D("10000")],
                           keys=["A", "B"])
    backwards = ud.allocate(D("1000"), [D("10000"), D("8000")],
                            keys=["B", "A"])
    assert (dict(zip(["A", "B"], forwards, strict=True))
            == dict(zip(["B", "A"], backwards, strict=True)))


def test_o10_an_exact_tie_is_broken_by_the_entity_id() -> None:
    """Three equal baselines and one leftover halala. It goes to the row
    with the smallest stable id, whatever order the rows arrived in."""
    by_id = {}
    for order in (["a", "b", "c"], ["c", "b", "a"], ["b", "a", "c"]):
        got = ud.allocate(D("1.00"), [D("1"), D("1"), D("1")], keys=order)
        by_id.update(dict(zip(order, got, strict=True)))
        assert dict(zip(order, got, strict=True))["a"] == D("0.34")
    assert by_id == {"a": D("0.34"), "b": D("0.33"), "c": D("0.33")}


def test_o10_the_allocation_reconciles_for_every_target_in_a_range() -> None:
    """A property, not an example. Largest-remainder makes the sum exact by
    construction, so any target over any baselines should hold."""
    baselines = [D("8000"), D("10000"), D("1800"), D("0")]
    for cents in range(-500, 500, 37):
        target = D(cents) / 100
        got = ud.allocate(target, baselines, keys=["A", "B", "C", "Z"])
        assert sum(got, D(0)) == target, target
        assert got[3] == D("0"), "a zero baseline receives nothing"


# ---- O11 ---------------------------------------------------------------

def test_o11_zero_to_positive_is_unsupported_not_divided() -> None:
    """Setting Z's PD from 0% to 1% has no ratio. Section 10.3: unsupported,
    with an alternative offered, never an epsilon denominator."""
    assert un.factor(D("0"), D("0.01")) is None

    got = dl.scale_row(plan_for(shock("pd_pit_12m", "1", un.SET_TO)),
                       FIXTURE["Z"])
    assert got.disposition == dl.UNSUPPORTED
    assert got.scenario_ecl == D("0"), "it keeps its baseline, not an invention"
    assert "zero" in got.reason


def test_o11_an_epsilon_denominator_would_have_produced_a_number() -> None:
    """What the refusal is worth: with an epsilon of 1e-9, Z's multiplier
    would be ten million, and it would have multiplied a real ECL."""
    epsilon = D("1e-9")
    assert (D("0.01") / epsilon) > D("1000000")
    got = dl.scale_row(plan_for(shock("pd_pit_12m", "1", un.SET_TO)),
                       FIXTURE["Z"])
    assert got.multiplier == D(1)


def test_o11_a_row_that_cannot_be_scaled_stays_in_the_total() -> None:
    """Section 9.1: never silently treat an ineligible record as zero."""
    results = run(plan_for(shock("pd_pit_12m", "1", un.SET_TO)))
    assert results["Z"].disposition == dl.UNSUPPORTED
    assert results["Z"].baseline_ecl == D("0")
    built = lg.build(domain_id=dom.CORPORATE, period="fixture",
                     membership_hash="0" * 64, results=results, labels=None,
                     tolerance=lg.EXACT)
    assert built.baseline == BASELINE_TOTAL
    assert any(c.disposition == dl.UNSUPPORTED for c in built.coverage())
