"""§14: metrics built from other metrics, across periods and across domains.

The two cases that matter are the ones the term tree cannot express — a
quarter-on-quarter change and a ratio across two datasets — and the refusals
that keep a composite from becoming a way round the checks a formula gets.
"""

from __future__ import annotations

import pytest

from backend.metrics import composite as comp
from backend.metrics.formula import Condition, Formula, Side, Term

EXPOSURE = Formula(kind="sum", numerator=Side(terms=(
    Term(id="e", label="Exposure", dataset="portfolio_facility",
         aggregate="sum", field="exposure"),)))

WATCHLIST = Formula(kind="sum", numerator=Side(terms=(
    Term(id="w", label="Watchlist EAD", dataset="watchlist_register",
         aggregate="sum", field="total_ead"),)))


def growth() -> comp.Composite:
    return comp.Composite(
        operation="growth",
        numerator=comp.Leg(id="cur", label="Current Quarter Exposure",
                           formula=EXPOSURE, said="Current Quarter Exposure"),
        denominator=comp.Leg(id="prev", label="Previous Quarter Exposure",
                             formula=EXPOSURE, period_offset=1,
                             said="Previous Quarter Exposure"),
        scale=100.0)


# ------------------------------------------------------------ period shift


@pytest.mark.parametrize("period,back,expected", [
    ("Q2 2026", 1, "Q1 2026"),
    ("Q1 2026", 1, "Q4 2025"),
    ("Q2 2026", 4, "Q2 2025"),
    ("2026-Q2", 1, "2026-Q1"),
    ("2026-06", 1, "2026-03"),
])
def test_a_period_shifts_on_this_books_own_calendar(period, back, expected):
    assert comp.shift(period, back=back) == expected


def test_an_unshiftable_period_returns_empty_rather_than_guessing():
    """Empty is a REFUSAL. It was being read as "no period filter", which made
    a denominator the sum of every quarter the book has and turned a growth
    rate of -0.45% into -94%."""
    assert comp.shift("nonsense", back=1) == ""


def test_an_unshiftable_period_stops_the_leg_rather_than_widening_it():
    spec = comp.Composite(
        operation="growth",
        numerator=comp.Leg(id="a", formula=EXPOSURE),
        denominator=comp.Leg(id="b", formula=EXPOSURE, period_offset=1))
    calculation = comp.run(spec, period="not-a-period")
    assert calculation.denominator.value is None
    assert "could not work out the period" in calculation.denominator.unavailable


# ------------------------------------------------------------- validation


def test_a_growth_rate_needs_two_periods():
    spec = comp.Composite(
        operation="growth",
        numerator=comp.Leg(id="a", formula=EXPOSURE),
        denominator=comp.Leg(id="b", formula=EXPOSURE))
    assert any("compares two periods" in p for p in comp.problems(spec))


def test_a_leg_must_be_a_metric_or_a_formula_and_not_both():
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="a", formula=EXPOSURE,
                           metric_id="corporate.exposure"),
        denominator=comp.Leg(id="b", formula=EXPOSURE))
    assert any("must be either" in p for p in comp.problems(spec))


def test_a_ratio_needs_both_sides():
    spec = comp.Composite(operation="ratio",
                          numerator=comp.Leg(id="a", formula=EXPOSURE))
    assert any("needs both sides" in p for p in comp.problems(spec))


def test_a_leg_reading_outside_the_boundary_is_refused():
    outside = Formula(kind="average", numerator=Side(terms=(
        Term(id="g", label="Gini", dataset="pd_model_performance",
             aggregate="avg", field="gini"),)))
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="a", formula=outside),
        denominator=comp.Leg(id="b", formula=EXPOSURE))
    assert any("Scorecard" in p for p in comp.problems(spec))


def test_looking_into_the_future_is_refused():
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="a", formula=EXPOSURE, period_offset=-1),
        denominator=comp.Leg(id="b", formula=EXPOSURE))
    assert any("into the future" in p for p in comp.problems(spec))


def test_looking_too_far_back_is_refused():
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="a", formula=EXPOSURE),
        denominator=comp.Leg(id="b", formula=EXPOSURE, period_offset=99))
    assert any("as far as a comparison goes" in p for p in comp.problems(spec))


# ------------------------------------------------- the dependency graph


class _Metric:
    def __init__(self, metric_id, composite=None, formula=None):
        self.metric_id = metric_id
        self.composite = composite
        self.formula = formula or EXPOSURE
        self.unit = "currency"
        self.datasets = ("portfolio_facility",)


def test_a_cycle_is_refused_by_naming_the_loop():
    """"maximum recursion depth exceeded" is not actionable; "a depends on b,
    which depends on a" is."""
    a = comp.Composite(operation="ratio",
                       numerator=comp.Leg(id="n", metric_id="m.b"),
                       denominator=comp.Leg(id="d", formula=EXPOSURE))
    b = comp.Composite(operation="ratio",
                       numerator=comp.Leg(id="n", metric_id="m.a"),
                       denominator=comp.Leg(id="d", formula=EXPOSURE))
    store = {"m.a": _Metric("m.a", a), "m.b": _Metric("m.b", b)}
    with pytest.raises(comp.CircularDependency) as caught:
        comp.resolve(a, resolver=store.get, root="m.a")
    assert "m.a depends on m.b depends on m.a" in str(caught.value)


def test_a_self_reference_is_refused():
    a = comp.Composite(operation="ratio",
                       numerator=comp.Leg(id="n", metric_id="m.a"),
                       denominator=comp.Leg(id="d", formula=EXPOSURE))
    store = {"m.a": _Metric("m.a", a)}
    with pytest.raises(comp.CircularDependency):
        comp.resolve(a, resolver=store.get, root="m.a")


def test_a_duplicate_subexpression_is_recorded_as_shared():
    """§14: do not recompute each nested metric independently."""
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="n", metric_id="m.x"),
        denominator=comp.Leg(id="d", metric_id="m.x"))
    store = {"m.x": _Metric("m.x")}
    graph = comp.resolve(spec, resolver=store.get, root="root")
    assert graph.shared == ["m.x"]


def test_too_deep_a_graph_is_refused():
    chain = {}
    for level in range(comp.MAX_DEPTH + 3):
        nxt = f"m.{level + 1}"
        chain[f"m.{level}"] = _Metric(f"m.{level}", comp.Composite(
            operation="ratio",
            numerator=comp.Leg(id="n", metric_id=nxt),
            denominator=comp.Leg(id="d", formula=EXPOSURE)))
    chain[f"m.{comp.MAX_DEPTH + 3}"] = _Metric(f"m.{comp.MAX_DEPTH + 3}")
    with pytest.raises(comp.CompositeError) as caught:
        comp.resolve(chain["m.0"].composite, resolver=chain.get, root="m.0")
    assert "levels deep" in str(caught.value)


# ---------------------------------------------------------------- running


def test_a_growth_rate_reads_two_periods_and_shows_both():
    calculation = comp.run(growth(), period="Q2 2026")
    assert calculation.numerator.period == "Q2 2026"
    assert calculation.denominator.period == "Q1 2026"
    assert calculation.value is not None
    assert "− 1" in calculation.final_expression


def test_the_direction_the_person_wrote_is_the_direction_computed():
    """§5, end to end. Their inverted formula and the conventional one must
    produce different numbers, or preservation means nothing."""
    conventional = comp.run(growth(), period="Q2 2026").value
    inverted = comp.run(comp.Composite(
        operation="growth",
        numerator=comp.Leg(id="prev", label="Previous", formula=EXPOSURE,
                           period_offset=1),
        denominator=comp.Leg(id="cur", label="Current", formula=EXPOSURE),
        scale=100.0), period="Q2 2026").value
    assert conventional is not None and inverted is not None
    assert conventional != inverted
    # …and they point opposite ways.
    assert (conventional > 0) != (inverted > 0)


def test_a_cross_domain_ratio_reports_both_domains():
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="w", label="Watchlist", formula=WATCHLIST),
        denominator=comp.Leg(id="t", label="Total", formula=EXPOSURE),
        scale=100.0)
    calculation = comp.run(spec, period="Q2 2026")
    assert calculation.numerator.domains == ["ews"]
    assert calculation.denominator.domains == ["cockpit"]
    assert comp.domains_of(spec) == ("cockpit", "ews")


def test_an_ews_filter_over_a_cockpit_measure_reads_both_domains():
    critical = Formula(kind="sum", numerator=Side(terms=(
        Term(id="c", label="Critical EAD", dataset="portfolio_facility",
             aggregate="sum", field="exposure",
             where=(Condition(field="severity", op="=", value="Critical"),)),)))
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="c", label="Critical", formula=critical),
        denominator=comp.Leg(id="t", label="Total", formula=EXPOSURE),
        scale=100.0)
    calculation = comp.run(spec, period="Q2 2026")
    assert calculation.numerator.domains == ["cockpit", "ews"]


def test_a_zero_denominator_reports_rather_than_rendering_infinity():
    impossible = Formula(kind="sum", numerator=Side(terms=(
        Term(id="z", label="None of it", dataset="portfolio_facility",
             aggregate="sum", field="exposure",
             where=(Condition(field="sector", op="=",
                              value="A Sector That Does Not Exist"),)),)))
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="a", formula=EXPOSURE),
        denominator=comp.Leg(id="b", formula=impossible))
    calculation = comp.run(spec, period="Q2 2026")
    assert calculation.value is None
    assert "denominator is zero" in calculation.unavailable


def test_a_shared_leg_is_computed_once():
    cache: dict = {}
    spec = comp.Composite(
        operation="ratio",
        numerator=comp.Leg(id="a", formula=EXPOSURE),
        denominator=comp.Leg(id="b", formula=EXPOSURE))
    comp.run(spec, period="Q2 2026", cache=cache)
    assert len(cache) == 1
