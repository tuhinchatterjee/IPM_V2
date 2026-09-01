"""
P0.11 — a chart has to say something true about the result.

The defect: a two-period sector-share result drawn as a heatmap whose axes were
the MEASURE VALUES. Every distinct share became its own category, so the matrix
was a sparse diagonal with floating-point headers — a picture of nothing, drawn
confidently, because selection had no validation step behind it.
"""

from __future__ import annotations

from backend.orchestration import visualize as vz
from backend.orchestration import viz_contract as vc


def _visual(chart: str, x: str = "", y: tuple[str, ...] = (),
            series: str = "", alternatives: tuple[str, ...] = ()) -> vz.Visual:
    return vz.Visual(chart=chart, x=x, y=list(y), series=series,
                     alternatives=list(alternatives))


# ---------------------------------------------------------------- axis roles


def test_a_measure_cannot_be_an_axis():
    """The exact defect. A share on an axis makes every value its own
    category, which is why the matrix came out diagonal."""
    columns = [
        {"name": "from_state", "semantic": "percent", "label": "Share Q1"},
        {"name": "to_state", "semantic": "percent", "label": "Share Q2"},
        {"name": "value", "semantic": "count", "label": "Sectors"},
    ]
    rows = [{"from_state": 2.62 + i, "to_state": 3.11 + i, "value": 1}
            for i in range(12)]
    verdict = vc.validate(
        _visual("heatmap", x="to_state", y=("value",), series="from_state"),
        columns, rows)
    assert verdict.ok is False
    assert any(p.check == "axis_roles" for p in verdict.problems)
    assert "measure" in verdict.why


def test_a_dimension_cannot_be_a_magnitude():
    columns = [
        {"name": "sector", "semantic": "category", "label": "Sector"},
        {"name": "region", "semantic": "category", "label": "Region"},
    ]
    rows = [{"sector": "Contracting", "region": "Riyadh"}]
    verdict = vc.validate(_visual("bar", x="sector", y=("region",)),
                          columns, rows)
    assert verdict.ok is False


def test_a_sector_by_period_heatmap_is_fine():
    """§G's own example of a VALID heatmap: both axes are dimensions and the
    cell is the measure. The validator must not reject the chart the brief
    asks for."""
    columns = [
        {"name": "sector", "semantic": "category", "label": "Sector"},
        {"name": "period", "semantic": "period", "label": "Period"},
        {"name": "share", "semantic": "percent", "unit": "%", "label": "Share"},
    ]
    rows = [{"sector": s, "period": p, "share": 4.2}
            for s in ("Contracting", "Retail", "Energy")
            for p in ("Q1 2026", "Q2 2026")]
    assert vc.validate(
        _visual("heatmap", x="period", y=("share",), series="sector"),
        columns, rows).ok is True


# --------------------------------------------------------------- readability


def test_an_axis_of_four_hundred_categories_is_refused():
    columns = [{"name": "customer", "semantic": "identity", "label": "Customer"},
               {"name": "ead", "semantic": "money", "label": "EAD"}]
    rows = [{"customer": f"CUST-{i:05d}", "ead": float(i)} for i in range(400)]
    verdict = vc.validate(_visual("bar", x="customer", y=("ead",)),
                          columns, rows)
    assert verdict.ok is False
    assert any(p.check == "cardinality" for p in verdict.problems)


def test_bare_numeric_labels_are_refused_even_when_the_semantic_lies():
    """The symptom, caught independently of the role check. A column whose
    metadata claims to be a category but whose values are floats produces
    exactly the unreadable headers that were observed."""
    columns = [{"name": "bucket", "semantic": "category", "label": "Bucket"},
               {"name": "n", "semantic": "count", "label": "Count"}]
    rows = [{"bucket": "2.6246841182876173", "n": 1},
            {"bucket": "3.1187224411", "n": 1}]
    verdict = vc.validate(_visual("bar", x="bucket", y=("n",)), columns, rows)
    assert verdict.ok is False
    assert any(p.check == "labels" for p in verdict.problems)


def test_money_and_percent_on_one_scale_is_refused():
    columns = [{"name": "sector", "semantic": "category"},
               {"name": "ecl", "semantic": "money", "unit": "USD mn"},
               {"name": "share", "semantic": "percent", "unit": "%"}]
    rows = [{"sector": "Contracting", "ecl": 1200.0, "share": 6.4}]
    verdict = vc.validate(_visual("bar", x="sector", y=("ecl", "share")),
                          columns, rows)
    assert verdict.ok is False
    assert any(p.check == "units" for p in verdict.problems)


def test_a_chart_that_is_mostly_gaps_is_refused():
    columns = [{"name": "sector", "semantic": "category"},
               {"name": "dscr", "semantic": "ratio", "unit": "x"}]
    rows = ([{"sector": f"S{i}", "dscr": None} for i in range(8)]
            + [{"sector": "S9", "dscr": 1.2}])
    verdict = vc.validate(_visual("bar", x="sector", y=("dscr",)),
                          columns, rows)
    assert verdict.ok is False
    assert any(p.check == "missing_values" for p in verdict.problems)


def test_a_scatter_of_five_thousand_marks_is_refused():
    columns = [{"name": "ead", "semantic": "money"},
               {"name": "ecl", "semantic": "money"}]
    rows = [{"ead": float(i), "ecl": float(i)} for i in range(5000)]
    verdict = vc.validate(_visual("scatter", x="ead", y=("ecl",)),
                          columns, rows)
    assert any(p.check in ("overplotting", "axis_roles")
               for p in verdict.problems)


def test_a_period_axis_out_of_order_is_flagged_but_not_fatal():
    """Order is fixable by sorting; it does not make the chart a lie."""
    columns = [{"name": "period", "semantic": "period"},
               {"name": "ecl", "semantic": "money", "unit": "USD mn"}]
    rows = [{"period": "Q2 2026", "ecl": 1.0}, {"period": "Q1 2026", "ecl": 2.0}]
    verdict = vc.validate(_visual("line", x="period", y=("ecl",)),
                          columns, rows)
    assert any(p.check == "period_semantics" for p in verdict.problems)
    assert verdict.ok is True


# ------------------------------------------------------------- what it allows


def test_a_table_is_never_rejected():
    """A table cannot misrepresent its own numbers, so there is nothing here
    that could make one invalid."""
    assert vc.validate(_visual("table"), [], []).ok is True
    assert vc.validate(_visual("kpi", y=("ecl",)), [], []).ok is True


def test_an_ordinary_ranking_survives():
    columns = [{"name": "customer", "semantic": "identity", "label": "Customer"},
               {"name": "ead", "semantic": "money", "unit": "USD mn"}]
    rows = [{"customer": f"Borrower {i}", "ead": float(100 - i)}
            for i in range(10)]
    assert vc.validate(_visual("bar_horizontal", x="customer", y=("ead",)),
                       columns, rows).ok is True


# ------------------------------------------------------------ the integration


def test_choose_replaces_an_invalid_chart_with_a_table_and_says_why():
    """P0.11: 'if invalid, choose a better chart or table.' Replaced, not
    annotated — a misleading picture is worse than the numbers."""
    columns = [
        {"name": "from_state", "semantic": "percent", "label": "Share Q1"},
        {"name": "to_state", "semantic": "percent", "label": "Share Q2"},
        {"name": "value", "semantic": "count", "label": "Sectors"},
    ]
    rows = [{"from_state": 2.62 + i * 0.37, "to_state": 3.11 + i * 0.41,
             "value": 1} for i in range(15)]
    chosen = vz.choose(columns, rows)
    assert chosen.chart == vz.TABLE
    assert "would not say something true" in chosen.reason
    assert "measure" in chosen.reason


def test_choose_leaves_a_valid_chart_alone():
    columns = [
        {"name": "sector", "semantic": "category", "label": "Sector", "rank": 0},
        {"name": "ecl", "semantic": "money", "unit": "USD mn", "label": "ECL"},
    ]
    rows = [{"sector": s, "ecl": 100.0} for s in
            ("Contracting", "Retail", "Energy", "Transport")]
    chosen = vz.choose(columns, rows)
    assert chosen.chart != vz.TABLE
    assert "would not say something true" not in chosen.reason


def test_a_subject_ranked_zero_is_still_the_subject():
    """RANK_SUBJECT is 0, and 0 is falsy. Reading the rank with `or` demoted
    every correctly ranked subject to context, so a grouped result had no axis
    and was quietly drawn as a table."""
    from backend.orchestration import presentation as pr

    shape = vz.read_shape(
        [{"name": "sector", "semantic": "category", "rank": pr.RANK_SUBJECT},
         {"name": "ecl", "semantic": "money", "rank": pr.RANK_PRIMARY}],
        [{"sector": "Contracting", "ecl": 100.0}])
    assert shape.subject == "sector"
    assert shape.measures == ["ecl"]
