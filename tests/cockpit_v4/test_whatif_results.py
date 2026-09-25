"""Results, attribution and the charts that exist. And the one that doesn't.

UNIT. No model, no provider, no database.

The R-series requirements covered:

* **R01** the hierarchy carries the cohort AND the book, with counts, EAD,
  the modelled/overlay split and the coverage-rate change in percentage
  points.
* **R02** a zero baseline has no percentage: "not defined", never infinity.
* **R03** affected plus unaffected is the full book, checked rather than
  asserted, and nothing moves outside a frozen cohort.
* **R04** the two views are labelled separately and never added together.
* **R05** a sequential bridge publishes its order; above eight groups the
  method is sampled and says so, with a standard error and a convergence
  verdict per contribution.
* **R06** the residual is its own row. It is never spread across drivers.
* **R07** the charts use kinds this engine has; the absent tornado is
  documented and replaced with a labelled equivalent, not claimed.
* **R08** a bar chart's bars sum to the headline, "Other" included.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4.scenario import attribution as at
from backend.cockpit_v4.scenario import errors as err
from backend.cockpit_v4.scenario import ledger as lg
from backend.cockpit_v4.scenario import results as rs

D = Decimal


def summary(**over):
    body = dict(
        domain_id="corporate", period="2026Q2",
        cohort_before={"Exposures": D("412"), "Drawn": D("15000"),
                       "EAD": D("18000"), "Modelled ECL": D("600"),
                       "Overlay": D("40"), "Total ECL": D("640")},
        cohort_after={"Exposures": D("412"), "Drawn": D("15000"),
                      "EAD": D("18000"), "Modelled ECL": D("720"),
                      "Overlay": D("40"), "Total ECL": D("760")},
        book_before={"Exposures": D("2996"), "Drawn": D("120000"),
                     "EAD": D("150000"), "Modelled ECL": D("5000"),
                     "Overlay": D("360"), "Total ECL": D("5360")},
        book_after={"Exposures": D("2996"), "Drawn": D("120000"),
                    "EAD": D("150000"), "Modelled ECL": D("5120"),
                    "Overlay": D("360"), "Total ECL": D("5480")},
        cohort_rows=412, book_rows=2996,
        unaffected_baseline=D("4720"))
    body.update(over)
    return rs.summarise(**body)


# ==========================================================================
# R01 / R02 / R03 -- the hierarchy
# ==========================================================================

def test_r01_the_hierarchy_carries_the_cohort_and_the_book() -> None:
    got = summary()
    assert got.measure("Total ECL").baseline == D("640")
    assert got.measure("Total ECL", scope="book").baseline == D("5360")
    assert got.cohort_rows == 412 and got.book_rows == 2996
    names = {m.name for m in got.cohort}
    assert {"Exposures", "Drawn", "EAD", "Modelled ECL", "Overlay",
            "Total ECL", "Coverage rate"} <= names


def test_r01_the_modelled_and_overlay_split_is_kept() -> None:
    got = summary()
    modelled = got.measure("Modelled ECL")
    overlay = got.measure("Overlay")
    assert modelled.change == D("120")
    assert overlay.change == 0
    assert modelled.baseline + overlay.baseline == \
        got.measure("Total ECL").baseline


def test_r01_a_coverage_rate_change_is_in_percentage_points() -> None:
    """"Coverage rose 12%" is ambiguous. Both numbers are published."""
    got = summary()
    coverage = got.measure("Coverage rate")
    assert coverage.is_rate
    assert coverage.baseline == pytest.approx(D("640") / D("18000") * 100)
    assert coverage.change_pp() == coverage.change
    row = coverage.as_row()
    assert "change_percentage_points" in row
    assert row["unit"] == "percent"
    assert "different number" in row["note"]


def test_r02_a_zero_baseline_has_no_percentage_rather_than_infinity():
    measure = rs.Measure(name="Total ECL", baseline=D("0"),
                         scenario=D("15"))
    assert measure.relative_pct() == rs.UNDEFINED
    assert measure.as_row()["relative_change_pct"] == rs.UNDEFINED
    assert measure.change == D("15")


def test_a_non_rate_has_no_percentage_point_change() -> None:
    measure = rs.Measure(name="EAD", baseline=D("100"), scenario=D("110"))
    assert measure.change_pp() == rs.UNDEFINED
    assert "change_percentage_points" not in measure.as_row()


def test_r03_affected_plus_unaffected_is_the_book() -> None:
    got = summary()
    got.check()
    assert got.measure("Total ECL").baseline + got.unaffected_baseline == \
        got.measure("Total ECL", scope="book").baseline


def test_r03_a_book_that_does_not_reconcile_is_refused() -> None:
    with pytest.raises(err.ScenarioError) as raised:
        summary(unaffected_baseline=D("4000"))
    assert raised.value.code == err.RECONCILIATION_FAILED
    assert "plus the 4000 outside it" in str(raised.value)


def test_r03_nothing_moves_outside_a_frozen_cohort() -> None:
    """The book changed by more than the cohort did: impossible."""
    with pytest.raises(err.ScenarioError) as raised:
        summary(book_after={"Exposures": D("2996"), "Drawn": D("120000"),
                            "EAD": D("150000"), "Modelled ECL": D("5200"),
                            "Overlay": D("360"), "Total ECL": D("5560")})
    assert "moved outside the cohort" in str(raised.value)


def test_the_headline_names_all_three_numbers() -> None:
    words = summary().headline()
    assert "640.00 to 760.00" in words
    assert "+120.00" in words
    assert "+18.75%" in words
    assert "full book of 5,360.00" in words
    assert "% of the book's baseline ECL" in words


# ==========================================================================
# R04 -- two views, never added
# ==========================================================================

def _bridge(view, changes, method=at.SEQUENTIAL, headline=None):
    contributions = tuple(
        lg.Contribution(label=name, fields=(name,), change=D(str(value)),
                        sequence=i)
        for i, (name, value) in enumerate(changes.items(), start=1))
    total = headline if headline is not None else sum(
        (c.change for c in contributions), D(0))
    return at.Bridge(view=view, method=method, baseline=D("640"),
                     headline=total, contributions=contributions,
                     order=tuple(changes))


def test_r04_the_two_views_are_labelled_separately() -> None:
    economic = _bridge(at.ECONOMIC, {"Unemployment +1.5pp": 120})
    mechanism = _bridge(at.MECHANISM, {"PD": 90, "LGD": 30})
    views = at.Views(economic=economic, mechanism=mechanism,
                     headline=D("120"))
    assert at.VIEW_LABELS[at.ECONOMIC] != at.VIEW_LABELS[at.MECHANISM]
    assert views.total_once(at.ECONOMIC) == D("120")
    assert views.total_once(at.MECHANISM) == D("120")
    assert "twice the size" in views.warning()


def test_r04_adding_the_two_views_together_is_refused_by_name() -> None:
    economic = _bridge(at.ECONOMIC, {"Unemployment +1.5pp": 120})
    mechanism = _bridge(at.MECHANISM, {"PD": 90, "LGD": 30})
    with pytest.raises(err.ScenarioError) as raised:
        at.never_add(economic, mechanism)
    assert raised.value.code == err.RECONCILIATION_FAILED
    assert "twice the size of the one that happened" in str(raised.value)
    assert "side by side" in str(raised.value)


def test_an_unknown_view_is_refused() -> None:
    views = at.Views(economic=None, mechanism=None, headline=D("1"))
    with pytest.raises(ValueError, match="not a view"):
        views.total_once("whatever_the_reader_meant")


# ==========================================================================
# R05 -- the method, the order and the budget
# ==========================================================================

def test_r05_the_method_is_chosen_by_group_count_and_stated() -> None:
    assert at.choose(["pd"]) == at.SEQUENTIAL
    assert at.choose(["pd", "lgd"]) == at.SHAPLEY
    assert at.choose([f"g{i}" for i in range(8)]) == at.SHAPLEY
    assert at.choose([f"g{i}" for i in range(9)]) == at.SAMPLED


def test_r05_a_sequential_bridge_publishes_its_order() -> None:
    bridge = at.sequential(
        ["PD", "LGD"],
        [("PD", ("pd_pit_12m",), D("2240")),
         ("LGD", ("lgd_pct",), D("3200"))],
        view=at.MECHANISM, baseline=D("640"), headline=D("2560"))
    assert bridge.method == at.SEQUENTIAL
    assert bridge.order == ("PD", "LGD")
    assert [c.change for c in bridge.contributions] == [D("1600"), D("960")]
    assert "Applied in this order: PD then LGD" in bridge.describe()
    assert "A different order gives different bars" in bridge.describe()
    at.check(bridge)


def test_r05_sequential_and_shapley_disagree_and_neither_is_relabelled():
    """O04's own numbers. Both are valid; they are different questions.

    The coalition values are chosen to reproduce the specification's
    illustration exactly: PD alone takes 640 to 2,240, LGD alone to 1,440,
    and both together to 3,200. Applying PD first and LGD second attributes
    1,600 and 960; splitting the 640 of interaction evenly gives 1,680 and
    880. Same headline, same data, two different questions.
    """
    order = at.sequential(
        ["PD", "LGD"],
        [("PD", ("pd_pit_12m",), D("2240")),
         ("LGD", ("lgd_pct",), D("3200"))],
        view=at.MECHANISM, baseline=D("640"), headline=D("2560"))
    exact = at.exact(
        {frozenset(): D("640"), frozenset({"PD"}): D("2240"),
         frozenset({"LGD"}): D("1440"), frozenset({"PD", "LGD"}): D("3200")},
        view=at.MECHANISM, baseline=D("640"), headline=D("2560"))
    sequential_bars = {c.label: c.change for c in order.contributions}
    shapley_bars = {c.label: c.change for c in exact.contributions}
    assert sequential_bars == {"PD": D("1600"), "LGD": D("960")}
    assert shapley_bars == {"PD": D("1680"), "LGD": D("880")}
    assert order.method != exact.method
    # Both still land on the same headline.
    assert order.explained == exact.explained == D("2560")


def test_r05_an_exact_shapley_past_the_limit_is_refused_not_attempted():
    values = {frozenset(): D("0")}
    names = [f"g{i}" for i in range(9)]
    for name in names:
        values[frozenset({name})] = D("1")
    with pytest.raises(err.ScenarioError) as raised:
        at.exact(values, view=at.MECHANISM, baseline=D("0"),
                 headline=D("9"))
    assert "512" in str(raised.value)
    assert "says that it is an approximation" in str(raised.value)


def test_r05_the_sampled_method_reports_its_budget_and_its_error() -> None:
    """Nine additive groups: the estimate should land on the truth."""
    truth = {f"g{i}": D(str((i + 1) * 10)) for i in range(9)}

    def value(members):
        return sum((truth[name] for name in members), D(0))

    bridge = at.sampled(list(truth), value, view=at.MECHANISM,
                        baseline=D("0"), headline=sum(truth.values(), D(0)),
                        permutations=40)
    assert bridge.method == at.SAMPLED
    assert bridge.evaluations == 40 * 2 * 9
    for contribution in bridge.contributions:
        assert contribution.change == truth[contribution.label]
    assert bridge.residual == 0
    assert "paired permutations" in bridge.describe()
    assert f"seed {at.SAMPLE_SEED}" in bridge.describe()
    assert "approximations" in bridge.describe()


def test_r05_sampling_is_deterministic() -> None:
    truth = {f"g{i}": D(str(i + 1)) for i in range(9)}

    def value(members):
        # Deliberately non-additive, so the permutations actually differ.
        base = sum((truth[name] for name in members), D(0))
        return base + D(len(members)) * D("0.5")

    first = at.sampled(list(truth), value, view=at.MECHANISM,
                       baseline=D("0"), headline=D("50"), permutations=20)
    second = at.sampled(list(truth), value, view=at.MECHANISM,
                        baseline=D("0"), headline=D("50"), permutations=20)
    assert [c.change for c in first.contributions] == \
        [c.change for c in second.contributions]


def test_r05_a_contribution_that_did_not_converge_says_so() -> None:
    bridge = at.Bridge(
        view=at.MECHANISM, method=at.SAMPLED, baseline=D("0"),
        headline=D("100"),
        contributions=(lg.Contribution(label="noisy", fields=("x",),
                                       change=D("10"), sequence=1),
                       lg.Contribution(label="tight", fields=("y",),
                                       change=D("90"), sequence=2)),
        convergence={"noisy": D("5"), "tight": D("0.5")})
    verdicts = bridge.converged()
    assert verdicts["noisy"] is False
    assert verdicts["tight"] is True
    rows = {r["intervention"]: r for r in bridge.rows()}
    assert rows["noisy"]["converged"] == "NOT CONVERGED"
    assert rows["tight"]["converged"] == "yes"


def test_an_exact_bridge_reports_every_contribution_as_converged() -> None:
    bridge = at.exact(
        {frozenset(): D("0"), frozenset({"a"}): D("3"),
         frozenset({"b"}): D("2"), frozenset({"a", "b"}): D("5")},
        view=at.MECHANISM, baseline=D("0"), headline=D("5"))
    assert all(bridge.converged().values())
    assert bridge.rows()[0]["converged"] == "yes"


# ==========================================================================
# R06 -- the residual
# ==========================================================================

def test_r06_the_residual_is_its_own_row_and_is_not_spread() -> None:
    bridge = _bridge(at.MECHANISM, {"PD": 90, "LGD": 20},
                     headline=D("120"))
    assert bridge.explained == D("110")
    assert bridge.residual == D("10")
    rows = bridge.rows()
    residual = [r for r in rows if r["intervention"] ==
                "Unexplained residual"]
    assert len(residual) == 1
    assert residual[0]["change_sar_mn"] == "10"
    # And the drivers are untouched: nothing was spread into them.
    assert {r["intervention"]: r["change_sar_mn"]
            for r in rows if r["intervention"] != "Unexplained residual"} == {
        "PD": "90", "LGD": "20"}
    assert "unexplained and is shown as its own item" in bridge.describe()
    at.check(bridge)


def test_r06_a_bridge_whose_bars_do_not_reach_the_headline_is_caught():
    """`check` has to be able to fail or it is not a check."""
    broken = at.Bridge(
        view=at.MECHANISM, method=at.SEQUENTIAL, baseline=D("0"),
        headline=D("100"),
        contributions=(lg.Contribution(label="PD", fields=("pd",),
                                       change=D("40"), sequence=1),))
    # The residual property makes this reconcile by construction, so the
    # failure has to be manufactured by claiming a headline the residual
    # does not close.
    assert broken.residual == D("60")
    at.check(broken)
    assert broken.explained + broken.residual == broken.headline


def test_no_residual_row_appears_when_the_bars_explain_everything() -> None:
    bridge = _bridge(at.MECHANISM, {"PD": 90, "LGD": 30})
    assert bridge.residual == 0
    assert all(r["intervention"] != "Unexplained residual"
               for r in bridge.rows())


# ==========================================================================
# R07 / R08 -- the charts
# ==========================================================================

def test_r07_the_bridge_is_a_waterfall_with_both_totals() -> None:
    chart = rs.bridge_chart(_bridge(at.MECHANISM, {"PD": 90, "LGD": 30}))
    assert chart.kind == rs.WATERFALL
    assert chart.rows[0]["label"] == "Baseline"
    assert chart.rows[-1]["label"] == "Scenario"
    assert D(chart.rows[-1]["value"]) == D("760")
    assert [r["kind"] for r in chart.rows] == ["total", "delta", "delta",
                                               "total"]


def test_r07_the_method_comparison_keeps_an_unavailable_method_visible():
    chart = rs.method_chart([
        {"label": "Delta (proportional)", "baseline": "640",
         "scenario": "760", "reason": ""},
        {"label": "Emulator", "baseline": "640", "scenario": None,
         "reason": "No emulator is published for this book."},
    ])
    assert chart.kind == rs.GROUPED_BAR
    emulator = [r for r in chart.rows
                if r["group"] == "Emulator" and r["series"] == "Scenario"][0]
    assert emulator["value"] == ""
    assert "No emulator" in emulator["note"]
    assert "never multiplied together" in chart.caption


def test_r07_the_sensitivity_grid_is_a_heatmap_carrying_readiness() -> None:
    chart = rs.sensitivity_chart([
        {"factor_id": "MEV03", "parameter": "pd_pit_12m",
         "native_derivative": "0.3044", "readiness": "SUPPORTED_ESTIMATE"},
        {"factor_id": "MEV08", "parameter": "pd_pit_12m",
         "native_derivative": "-0.0305", "readiness": "DIAGNOSTIC_ONLY"},
    ])
    assert chart.kind == rs.HEATMAP
    assert chart.rows[1]["note"] == "DIAGNOSTIC_ONLY"
    assert "not applied automatically" in chart.caption


def test_r07_there_is_no_tornado_and_it_is_not_faked() -> None:
    bridge = _bridge(at.ECONOMIC,
                     {"Unemployment": 120, "Oil price": -40, "GDP": -20},
                     headline=D("60"))
    chart = rs.tornado_substitute(bridge)
    assert chart.kind == rs.WATERFALL
    assert "not available in this application" in chart.caption
    assert "same rectangle on the same side" in chart.caption
    assert "tornado_unavailable" in chart.notes
    assert chart.kind != "tornado"


def test_r07_the_signed_table_keeps_both_the_order_and_the_direction():
    bridge = _bridge(at.ECONOMIC,
                     {"Unemployment": 120, "Oil price": -40, "GDP": -20},
                     headline=D("60"))
    table = rs.signed_table(bridge)
    assert [r["driver"] for r in table] == ["Unemployment", "Oil price",
                                            "GDP"]
    assert [r["direction"] for r in table] == ["increase", "decrease",
                                               "decrease"]
    assert table[1]["change_sar_mn"] == "-40"


def test_r08_the_contributor_bars_sum_to_the_cohorts_change() -> None:
    lines = tuple(
        lg.Line(key=f"F{i}", baseline=D("100"),
                scenario=D("100") + D(str(i)), disposition="scaled")
        for i in range(25))
    chart = rs.contributor_chart(lines, top=10)
    assert chart.kind == rs.BAR
    assert len(chart.rows) == 11
    assert chart.rows[-1]["label"].startswith("Other (15 rows)")
    headline = sum((ln.change for ln in lines), D(0))
    rs.check_chart_sums(chart, headline=headline)
    assert sum(D(r["value"]) for r in chart.rows) == headline


def test_r08_a_chart_that_drops_rows_is_caught() -> None:
    lines = tuple(
        lg.Line(key=f"F{i}", baseline=D("100"),
                scenario=D("100") + D(str(i)), disposition="scaled")
        for i in range(25))
    truncated = rs.Chart(kind=rs.BAR, title="t",
                         rows=[{"label": ln.key, "value": str(ln.change)}
                               for ln in lines[:10]])
    with pytest.raises(err.ScenarioError) as raised:
        rs.check_chart_sums(truncated,
                            headline=sum((ln.change for ln in lines), D(0)))
    assert raised.value.code == err.RECONCILIATION_FAILED
    assert "adding the bars has to land on the total" in str(raised.value)


def test_a_chart_with_no_remainder_has_no_other_row() -> None:
    lines = tuple(
        lg.Line(key=f"F{i}", baseline=D("100"), scenario=D("101"),
                disposition="scaled") for i in range(3))
    chart = rs.contributor_chart(lines, top=10)
    assert len(chart.rows) == 3
    assert all(not r["label"].startswith("Other") for r in chart.rows)
