"""Charts: a governed metric broken out across one dimension.

The tests that matter here are the reconciliation ones and the refusals.

Reconciliation, because a chart that computes its bars a different way from the
figure above it will eventually disagree with it, and the reader has no way to
tell which is right. An additive metric's bars must sum to its total, and a
ratio's bars must bracket its overall value — those two facts are what make the
chart evidence rather than decoration.

Refusals, because the whole claim of this feature is that it will not draw a
dishonest picture: no line between unordered categories, no matrix off one
dimension, no chart at all of a metric computed by a governed function, no
average of a ratio, and no grouping by a column the catalogue does not have.
Every one of them is asserted below with the reason the product gives.
"""

from __future__ import annotations

import pytest

from backend.metrics import execution, library
from backend.metrics import service as metrics
from backend.services import lenses as ln

#: An additive metric on the retail behavioural dataset, and a ratio on the
#: same one. Named rather than discovered so a failure says which metric.
TOTAL = "retail.balance"
RATIO = "retail.utilisation"
FUNCTION = "retail.scorecard.gini"

#: Categorical, with a handful of values. Ordered, and over time.
CATEGORY = "product"
ORDERED = "utilisation_pct_bin"
OVER_TIME = "observation_month"


def _metric(metric_id: str):
    return next(m for m in library.ALL if m.metric_id == metric_id)


# ---------------------------------------------------------------- the numbers


def test_the_bars_of_an_additive_metric_sum_to_its_total():
    """The reconciliation that makes a chart evidence.

    Not "close to": the same arithmetic over the same rows, so any difference
    beyond floating point is a defect in the grouping, not a rounding story.
    """
    metric = _metric(TOTAL)
    period = metrics.default_period(metric)
    whole = metrics.value(TOTAL, period=period)["value"]
    drawn = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                           limit=execution.MAX_GROUPS)

    parts = sum(p["value"] for p in drawn["points"] if p["value"] is not None)
    assert whole is not None
    assert not drawn["truncated"], (
        "every group has to be in the picture for this to be a reconciliation")
    assert parts == pytest.approx(whole, rel=1e-9)


def test_the_bars_of_a_ratio_bracket_its_overall_value():
    """A ratio is not the sum of its groups, and must not be drawn as one.

    The whole has to sit between the smallest and the largest group. A chart
    whose bars were all above the headline figure would mean the grouping had
    lost rows.
    """
    metric = _metric(RATIO)
    period = metrics.default_period(metric)
    whole = metrics.value(RATIO, period=period)["value"]
    drawn = metrics.series(RATIO, dimension=CATEGORY, period=period)

    values = [p["value"] for p in drawn["points"] if p["value"] is not None]
    assert len(values) > 1
    assert min(values) <= whole <= max(values)


def test_every_row_of_the_period_is_in_some_group():
    """No rows are lost between the metric and the chart."""
    metric = _metric(TOTAL)
    period = metrics.default_period(metric)
    counted = metrics.value(TOTAL, period=period)["calculation"]["rows_considered"]
    drawn = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                           limit=execution.MAX_GROUPS)
    assert sum(p["rows"] for p in drawn["points"]) == counted


def test_a_comparison_is_read_the_same_way_as_the_series_itself():
    metric = _metric(RATIO)
    period = metrics.default_period(metric)
    drawn = metrics.series(RATIO, dimension=CATEGORY, period=period,
                           compare="previous_period")
    comparison = drawn["comparison"]
    if comparison is None:
        # An honest outcome when the previous period is not in the book, and
        # the chart says so rather than drawing a zero.
        assert any("no data for" in note for note in drawn["notes"])
        return

    assert comparison["period"] != drawn["period"]
    against = metrics.series(RATIO, dimension=CATEGORY,
                             period=comparison["period"])
    theirs = {p["label"]: p["value"] for p in against["points"]}
    for point in comparison["points"]:
        assert point["value"] == theirs.get(point["label"])


def test_a_comparison_change_is_the_difference_between_the_two():
    period = metrics.default_period(_metric(RATIO))
    drawn = metrics.series(RATIO, dimension=CATEGORY, period=period,
                           compare="previous_period")
    if drawn["comparison"] is None:
        pytest.skip("the previous period is not in this deployment's data")
    now = {p["label"]: p["value"] for p in drawn["points"]}
    for point in drawn["comparison"]["points"]:
        if point["value"] is None or now[point["label"]] is None:
            assert point["change"] is None
        else:
            assert point["change"] == pytest.approx(
                now[point["label"]] - point["value"])


def test_a_filter_narrows_the_chart_and_is_named_back():
    period = metrics.default_period(_metric(TOTAL))
    everything = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                                limit=execution.MAX_GROUPS)
    one = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                         filters={"product": "CREDIT_CARD"})
    assert one["filters"] == {"product": "CREDIT_CARD"}
    assert [p["label"] for p in one["points"]] == ["CREDIT_CARD"]

    was = next(p["value"] for p in everything["points"]
               if p["label"] == "CREDIT_CARD")
    assert one["points"][0]["value"] == pytest.approx(was)


def test_sorting_orders_the_points_and_does_not_change_them():
    period = metrics.default_period(_metric(TOTAL))
    down = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                          sort="value", direction="desc",
                          limit=execution.MAX_GROUPS)
    up = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                        sort="value", direction="asc",
                        limit=execution.MAX_GROUPS)
    by_name = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                             sort="label", direction="asc",
                             limit=execution.MAX_GROUPS)

    values = [p["value"] for p in down["points"]]
    assert values == sorted(values, reverse=True)
    assert [p["value"] for p in up["points"]] == sorted(values)
    assert [p["label"] for p in by_name["points"]] == sorted(
        p["label"] for p in down["points"])
    assert {p["label"]: p["value"] for p in down["points"]} == \
           {p["label"]: p["value"] for p in by_name["points"]}


def test_a_limit_says_that_the_picture_is_not_the_whole_population():
    period = metrics.default_period(_metric(TOTAL))
    everything = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                                limit=execution.MAX_GROUPS)
    if everything["groups_found"] < 2:
        pytest.skip("this dimension has one group, so nothing can be cut")

    cut = metrics.series(TOTAL, dimension=CATEGORY, period=period, limit=1)
    assert cut["truncated"] is True
    assert len(cut["points"]) == 1
    assert any("not the whole population" in note for note in cut["notes"])


def test_a_chart_over_the_period_field_is_the_trend():
    period = metrics.default_period(_metric(TOTAL))
    drawn = metrics.series(TOTAL, dimension=OVER_TIME, period=period,
                           limit=execution.MAX_GROUPS)
    labels = [p["label"] for p in drawn["points"]]
    assert drawn["over_time"] is True
    assert len(labels) > 1, "a trend of one point is not a trend"
    assert labels == sorted(labels), "a trend has to be in date order"
    assert any("Every period the dataset holds" in n for n in drawn["notes"])


def test_counting_rows_is_offered_and_is_the_row_count():
    period = metrics.default_period(_metric(RATIO))
    counted = metrics.series(RATIO, dimension=CATEGORY, period=period,
                             aggregate="count", limit=execution.MAX_GROUPS)
    assert counted["series_label"] == "Number of rows"
    for point in counted["points"]:
        assert point["value"] == pytest.approx(point["rows"])


def test_an_overridden_aggregation_is_renamed_and_says_so():
    """A bar that is not the governed metric must not carry its name."""
    period = metrics.default_period(_metric(TOTAL))
    averaged = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                              aggregate="average")
    assert averaged["series_label"] != _metric(TOTAL).name
    assert averaged["higher_is_better"] is None
    assert any(_metric(TOTAL).name in note for note in averaged["notes"])

    total = metrics.series(TOTAL, dimension=CATEGORY, period=period,
                           limit=execution.MAX_GROUPS)
    by_label = {p["label"]: p for p in total["points"]}
    for point in averaged["points"]:
        other = by_label[point["label"]]
        assert point["value"] == pytest.approx(other["value"] / other["rows"])


# ------------------------------------------------------------- the refusals


def test_a_function_metric_has_no_chart_and_says_why():
    vocabulary = metrics.chart_vocabulary(FUNCTION)
    assert vocabulary["chart_types"] == []
    assert all("governed function" in r["because"]
               for r in vocabulary["chart_types_refused"])


def test_a_line_is_not_offered_between_unordered_categories():
    metric = metrics.resolve(TOTAL)
    chosen = next(d for d in metrics.dimension_fields(metric)
                  if d["name"] == CATEGORY)
    available, refused = metrics.chart_types_for(metric, chosen)
    assert "bar" in available
    assert "line" not in available
    assert any("suggest a progression that is not there" in r["because"]
               for r in refused if r["name"] == "line")


def test_a_line_is_offered_where_the_dimension_has_an_order():
    metric = metrics.resolve(TOTAL)
    for name in (ORDERED, OVER_TIME):
        chosen = next(d for d in metrics.dimension_fields(metric)
                      if d["name"] == name)
        available, _ = metrics.chart_types_for(metric, chosen)
        assert "line" in available, name


def test_a_matrix_is_never_offered_from_a_one_dimension_builder():
    metric = metrics.resolve(TOTAL)
    for chosen in metrics.dimension_fields(metric):
        available, refused = metrics.chart_types_for(metric, chosen)
        assert "matrix" not in available
        assert any("two dimensions" in r["because"]
                   for r in refused if r["name"] == "matrix")


def test_an_identifier_is_not_offered_as_a_dimension():
    metric = metrics.resolve(TOTAL)
    offered = {d["name"] for d in metrics.dimension_fields(metric)}
    assert "account_id" not in offered
    with pytest.raises(metrics.MetricRefused, match="not a dimension"):
        metrics.series(TOTAL, dimension="account_id")


def test_a_column_the_catalogue_does_not_have_is_refused():
    with pytest.raises(metrics.MetricRefused, match="not a dimension"):
        metrics.series(TOTAL, dimension="1=1; DROP TABLE users")
    with pytest.raises(metrics.MetricRefused, match="not a field"):
        metrics.series(TOTAL, dimension=CATEGORY,
                       filters={"no_such_column": 1})


def test_an_average_of_a_ratio_is_refused_with_the_reason():
    assert metrics.may_average(metrics.resolve(RATIO)) is False
    with pytest.raises(metrics.MetricRefused, match="not a single total"):
        metrics.series(RATIO, dimension=CATEGORY, aggregate="average")


def test_an_unknown_setting_is_refused_rather_than_defaulted():
    for kwargs in ({"aggregate": "median"}, {"sort": "magnitude"},
                   {"direction": "sideways"}, {"compare": "last_decade"}):
        with pytest.raises(metrics.MetricRefused):
            metrics.series(TOTAL, dimension=CATEGORY, **kwargs)


# --------------------------------------------------------- charts on a lens


def test_a_lens_accepts_a_chart_and_draws_it():
    panel = ln.Panel.chart(TOTAL, dimension=CATEGORY, visual="bar",
                           title="Balance by product")
    ln.validate([panel])

    drawn = ln._render_chart(panel, period=None, user_id=None)
    assert drawn["status"] == "succeeded"
    assert drawn["kind"] == ln.KIND_CHART
    assert len(drawn["points"]) > 1
    # The info control travels with the tile: what it means, and the query
    # that produced it.
    assert drawn["metric"]["name"]
    assert "SELECT" in drawn["lineage"]["sql"].upper()
    assert drawn["lineage"]["run_id"]


def test_a_lens_refuses_a_chart_it_cannot_honestly_draw():
    for panel, expected in (
        (ln.Panel.chart(TOTAL, dimension=CATEGORY, visual="line"),
         "progression that is not there"),
        (ln.Panel.chart(TOTAL, dimension=CATEGORY, visual="matrix"),
         "two dimensions"),
        (ln.Panel.chart(TOTAL, dimension="account_id", visual="bar"),
         "not a dimension"),
        (ln.Panel.chart(FUNCTION, dimension=CATEGORY, visual="bar"),
         "governed function"),
        (ln.Panel.chart(RATIO, dimension=CATEGORY, visual="bar",
                        aggregate="average"),
         "not a single total"),
        (ln.Panel.chart(TOTAL, dimension="", visual="bar"),
         "which dimension"),
    ):
        with pytest.raises(ln.InvalidLens, match=expected):
            ln.validate([panel])


def test_a_chart_survives_being_stored_and_read_back():
    panel = ln.Panel.chart(TOTAL, dimension=CATEGORY, visual="bar",
                           compare="previous_period", sort="label",
                           direction="asc", limit=5,
                           filters={"product": "CREDIT_CARD"})
    again = ln.Panel.from_dict(panel.to_dict())
    assert again.kind == ln.KIND_CHART
    assert again.params == panel.params
    assert again.filters == panel.filters
    ln.validate([again])
