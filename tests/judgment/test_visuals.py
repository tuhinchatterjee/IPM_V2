"""
§85-§89 — the Visualization Grammar, the suitability score and the Visual
Critic.

The instruction the whole thing turns on
-----------------------------------------
    §85: "Use semantic roles, not raw data types alone."

The failure is specific and it is everywhere: a rating grade stored as an
integer is not a measure, a stage number is not a quantity, a borrower id is
not a value to plot. Anything reading dtypes draws all three as bars and
produces a chart that is confidently, silently wrong.

So most of these tests are about charts that are structurally valid and
semantically false — a Sankey between two unrelated categories, a bubble whose
size restates its y-value, a line across sectors — because those are the ones
a renderer will happily draw.
"""

from __future__ import annotations

from backend.judgment import visual_critic as vc
from backend.judgment import visual_grammar as vg


def _bar(**over) -> vc.Chart:
    base = dict(
        chart=vg.HORIZONTAL_BAR,
        bindings={"category": "sector", "value": "ecl"},
        roles={"category": vg.CATEGORY, "value": vg.MEASURE},
        labels=["Contracting", "Real Estate"],
        series={"ecl": [222.0, 140.0]}, units={"ecl": "SAR"},
        decimals=1, has_accessible_table=True)
    base.update(over)
    return vc.Chart(**base)


def _table(**over) -> vc.Table:
    base = dict(values={"ecl": [222.0, 140.0]},
                labels=["Contracting", "Real Estate"], units={"ecl": "SAR"})
    base.update(over)
    return vc.Table(**base)


# ======================================================== §85 semantic roles


def test_there_are_exactly_the_fifteen_roles_section_85_names():
    assert len(vg.ROLES) == 15
    for role in vg.ROLES:
        assert vg.ROLE_MEANS[role].strip()


def test_an_identifier_is_never_plotted_however_it_is_stored():
    """The failure this exists for: a borrower id is an integer, and anything
    reading dtypes puts it on a value axis."""
    assert vg.plottable(vg.IDENTIFIER) is False
    assert vg.labelling(vg.IDENTIFIER) is False
    assert vg.IDENTIFIER in vg.NEVER_DRAWN
    assert vg.TECHNICAL_LINEAGE in vg.NEVER_DRAWN


def test_a_role_nobody_classified_is_refused_rather_than_allowed():
    """A column nobody classified is a column nobody checked, and the
    permissive answer's failure mode is borrower ids up the y-axis."""
    assert vg.plottable("SOMETHING_NEW") is False
    assert vg.labelling("SOMETHING_NEW") is False


def test_ordinal_categories_and_risk_bands_carry_an_order():
    assert vg.ORDINAL_CATEGORY in vg.ORDERED
    assert vg.RISK_BAND in vg.ORDERED
    assert vg.CATEGORY not in vg.ORDERED


def test_percentage_and_percentage_point_are_separate_roles():
    """Conflating them is how "coverage rose 2%" comes to mean two different
    things in one chart."""
    assert vg.PERCENTAGE != vg.PERCENTAGE_POINT
    assert vg.plottable(vg.PERCENTAGE) and vg.plottable(vg.PERCENTAGE_POINT)


# ==================================================== §86 the governed mapping


def test_every_shape_section_86_names_has_a_mapping():
    assert len(vg.SHAPES) == 15
    for shape in vg.SHAPES:
        assert vg.MAPPING[shape], shape
        assert vg.SHAPE_MEANS[shape].strip(), shape
        assert vg.default_for(shape) in vg.CHARTS


def test_the_mapping_matches_section_86_line_by_line():
    """Written as data rather than as branches precisely so this test can be a
    list. Branching code that implemented the same rules could not be checked
    against the brief without reading the whole function."""
    assert vg.default_for(vg.SINGLE_VALUE) == vg.KPI
    assert vg.default_for(vg.CATEGORY_RANKING) == vg.HORIZONTAL_BAR
    assert vg.default_for(vg.TWO_PERIOD_CATEGORY) == vg.DUMBBELL
    assert vg.default_for(vg.TIME_SERIES) == vg.LINE
    assert vg.default_for(vg.MANY_TIME_SERIES) == vg.SMALL_MULTIPLES
    assert vg.default_for(vg.COMPOSITION_OVER_TIME) == vg.STACKED_AREA
    assert vg.default_for(vg.CHANGE_DECOMPOSITION) == vg.WATERFALL
    assert vg.default_for(vg.MIGRATION_PATHS) == vg.SANKEY
    assert vg.default_for(vg.MIGRATION_GRID) == vg.MIGRATION_MATRIX
    assert vg.default_for(vg.DISTRIBUTION) == vg.HISTOGRAM
    assert vg.default_for(vg.TWO_MEASURE) == vg.SCATTER
    assert vg.default_for(vg.THREE_MEASURE) == vg.BUBBLE
    assert vg.default_for(vg.CONCENTRATION_HIERARCHY) == vg.TREEMAP
    assert vg.default_for(vg.CATEGORY_PERIOD_MEASURE) == vg.HEATMAP
    assert vg.default_for(vg.RECORD_LEVEL) == vg.TABLE


def test_an_unknown_shape_falls_to_a_table_rather_than_to_a_guess():
    """A table of the right numbers is never wrong; a chart chosen for a shape
    nothing recognised very often is."""
    assert vg.default_for("something_nobody_classified") == vg.TABLE


def test_the_table_is_always_a_candidate():
    """It is what §88 falls to when every chart is rejected, and a candidate
    list that could come back empty would leave the critic with nothing."""
    for shape in vg.SHAPES:
        assert vg.TABLE in vg.candidates_for(shape), shape


# ============================================== §87 the suitability score


def test_the_thirteen_factors_section_87_names_are_all_scored():
    assert len(vg.FACTORS) == 13
    scored = vg.score(vg.HORIZONTAL_BAR, vg.Inputs(
        roles={"category": vg.CATEGORY, "value": vg.MEASURE}, categories=6))
    assert set(scored.factors) == set(vg.FACTORS)
    assert set(vg.WEIGHTS) == set(vg.FACTORS)


def test_role_incompatibility_rejects_whatever_else_scores_well():
    """A chart whose value axis is a borrower id is not a chart that reads
    poorly; it is a picture of something that was never true, and no amount
    of readability elsewhere makes up for it."""
    scored = vg.score(vg.BAR, vg.Inputs(
        roles={"category": vg.ENTITY, "value": vg.IDENTIFIER},
        categories=5, longest_label=8, measures=1))

    assert scored.factors["semantic_role_compatibility"] == 0.0
    assert scored.accepted is False
    assert "never drawn" in scored.rejections[0]


def test_a_line_over_unordered_categories_is_refused():
    """§89's invalid example. A line asserts that the space between two points
    is traversable, and between Contracting and Real Estate it is not."""
    scored = vg.score(vg.LINE, vg.Inputs(
        roles={"category": vg.CATEGORY, "value": vg.MEASURE}, periods=5))

    assert scored.accepted is False
    assert "asserts an order" in scored.rejections[0]


def test_a_line_over_an_ordinal_axis_is_fine():
    scored = vg.score(vg.LINE, vg.Inputs(
        roles={"category": vg.RISK_BAND, "value": vg.MEASURE}, periods=5,
        categories=7, measures=1))

    assert scored.factors["semantic_role_compatibility"] == 1.0


def test_a_slope_chart_of_unordered_categories_is_not_a_line_over_them():
    """Its two ends are the two PERIODS and its lines are the categories
    travelling between them, which is §86's named answer for that shape.
    Reading it as a line over categories rejected the chart the brief maps
    the shape to."""
    scored = vg.score(vg.SLOPE, vg.Inputs(
        roles={"category": vg.CATEGORY, "value": vg.MEASURE}, periods=2,
        categories=9, measures=1))

    assert scored.accepted is True


def test_a_sankey_without_flow_semantics_is_refused():
    scored = vg.score(vg.SANKEY, vg.Inputs(
        roles={"source": vg.CATEGORY, "destination": vg.CATEGORY,
               "value": vg.MEASURE}, categories=8, measures=1))

    assert scored.accepted is False
    assert "flow source and a flow destination" in scored.rejections[0]


def test_a_heatmap_with_one_categorical_axis_is_refused():
    scored = vg.score(vg.HEATMAP, vg.Inputs(
        roles={"category": vg.CATEGORY, "value": vg.MEASURE}, categories=12,
        measures=1))

    assert scored.accepted is False
    assert "two categorical axes" in scored.rejections[0]


def test_a_third_dimension_must_be_independent():
    """A bubble whose size restates its own y-value shows two numbers and
    appears to show three."""
    restated = vg.score(vg.BUBBLE, vg.Inputs(
        roles={"value": vg.MEASURE, "second_value": vg.MEASURE,
               "size": vg.MEASURE}, measures=2, categories=60))
    assert restated.accepted is False
    assert "independent measure" in restated.rejections[0]

    real = vg.score(vg.BUBBLE, vg.Inputs(
        roles={"value": vg.MEASURE, "second_value": vg.MEASURE,
               "size": vg.MEASURE}, measures=3, categories=60,
        cardinality=60))
    assert real.accepted is True


def test_a_truncated_baseline_rejects_a_length_encoded_chart():
    """The one charting failure with its own literature: a 2% difference from
    a cut axis looks like a 200% one."""
    scored = vg.score(vg.BAR, vg.Inputs(
        roles={"category": vg.CATEGORY, "value": vg.PERCENTAGE},
        categories=8, measures=1, needs_zero_baseline=True,
        zero_baseline_available=False))

    assert scored.factors["zero_baseline"] == 0.0
    assert scored.accepted is False
    assert "zero" in scored.rejections[0]


def test_too_many_categories_rejects_a_vertical_bar_and_not_a_treemap():
    """§89's invalid example. Forty-four sectors is a picket fence in a bar
    chart and a legible treemap."""
    inputs = vg.Inputs(roles={"category": vg.CATEGORY, "value": vg.MEASURE},
                       categories=44, longest_label=12, measures=1,
                       cardinality=44)

    assert vg.score(vg.BAR, inputs).accepted is False
    assert vg.score(vg.TREEMAP, inputs).accepted is True


def test_a_chart_slightly_over_its_ceiling_still_ships():
    """41 categories is not a different kind of chart from 39, and a cliff
    edge at the ceiling would make the ceiling the decision."""
    inputs = vg.Inputs(roles={"category": vg.CATEGORY, "value": vg.MEASURE},
                       categories=44, longest_label=10, measures=1,
                       cardinality=44)

    assert vg.score(vg.HORIZONTAL_BAR, inputs).accepted is True


def test_two_periods_cannot_support_a_line():
    """Two points are not a trend. A line between them says one anyway."""
    scored = vg.score(vg.LINE, vg.Inputs(
        roles={"time": vg.TIME, "value": vg.MEASURE}, periods=2, measures=1,
        categories=2))

    assert scored.accepted is False


def test_a_reader_who_asked_for_records_does_not_get_a_pattern():
    inputs = vg.Inputs(roles={"category": vg.ENTITY, "value": vg.MEASURE},
                       categories=200, measures=2, cardinality=200,
                       wants_records=True)

    assert vg.score(vg.SCATTER, inputs).accepted is False
    assert vg.score(vg.TABLE, inputs).accepted is True


def test_four_decimals_can_only_be_shown_in_a_table():
    inputs = vg.Inputs(roles={"category": vg.CATEGORY, "value": vg.MEASURE},
                       categories=8, measures=1, precision_required=4)

    assert vg.score(vg.BAR, inputs).accepted is False
    assert vg.score(vg.TABLE, inputs).accepted is True


def test_a_recorded_rejection_reason_actually_rejects():
    """§87 says persist rejection reasons. A reason that did not reject would
    make that "persist misgivings", and a candidate shipped with a stated
    reason it should not have been used is worse than one shipped with
    none."""
    for chart in vg.CHARTS:
        scored = vg.score(chart, vg.Inputs(
            roles={"category": vg.CATEGORY, "value": vg.MEASURE},
            categories=44, longest_label=30, measures=6, periods=1,
            cardinality=44, missing_pct=0.4))
        assert scored.accepted == (not scored.rejections), chart


def test_the_losing_candidates_are_kept_with_their_reasons():
    """A picker that shows only its winner cannot be argued with."""
    selection = vg.select(vg.CATEGORY_RANKING, vg.Inputs(
        roles={"category": vg.CATEGORY, "value": vg.MEASURE},
        categories=60, longest_label=10, measures=1, cardinality=60))

    assert selection.chosen == vg.TREEMAP
    assert vg.BAR in [s.chart for s in selection.rejected]
    losing = next(s for s in selection.scores if s.chart == vg.BAR)
    assert losing.rejections
    assert 0.0 <= losing.total <= 1.0
    assert selection.to_dict()["rejected"]


def test_the_default_wins_when_it_passes_so_the_mapping_stays_the_reason():
    """A scoring function free to pick anything would make §86 decorative."""
    selection = vg.select(vg.CHANGE_DECOMPOSITION, vg.Inputs(
        roles={"category": vg.ENTITY, "value": vg.DECOMPOSITION_COMPONENT},
        categories=9, measures=1, cardinality=9))

    assert selection.chosen == vg.WATERFALL
    assert "maps to it" in selection.reason()


def test_a_table_is_never_rejected():
    """It is the fallback everything falls to. Rejecting it would leave
    `select` falling back to a shape it had just refused."""
    hostile = vg.Inputs(roles={"category": vg.IDENTIFIER,
                               "value": vg.TECHNICAL_LINEAGE},
                        categories=9000, longest_label=200, measures=40,
                        cardinality=9000, missing_pct=0.9,
                        wants_records=True, precision_required=6,
                        narrow_device=True, zero_baseline_available=False)

    assert vg.score(vg.TABLE, hostile).accepted is True


def test_falling_back_means_no_chart_passed_not_merely_that_a_table_showed():
    """A table for record-level output is the right answer and no kind of
    failure."""
    records = vg.select(vg.RECORD_LEVEL, vg.Inputs(
        roles={"category": vg.ENTITY, "value": vg.MEASURE},
        categories=400, measures=8, wants_records=True))
    assert records.chosen == vg.TABLE
    assert records.fell_back is False

    broken = vg.select(vg.TIME_SERIES, vg.Inputs(
        roles={"time": vg.TIME, "value": vg.IDENTIFIER}, periods=8,
        measures=1))
    assert broken.chosen == vg.TABLE
    assert broken.fell_back is True
    assert "no chart passed" in broken.reason()


# ================================================== §88 the Visual Critic


def test_the_twelve_checks_section_88_names_all_run():
    assert len(vc.CHECKS) == 12
    verdict = vc.review(_bar(), _table())
    assert [f.check for f in verdict.findings] == list(vc.CHECKS)
    for check in vc.CHECKS:
        assert vc.ASKS[check].endswith("?")


def test_a_sound_chart_is_approved():
    verdict = vc.review(_bar(), _table())

    assert verdict.approved is True
    assert verdict.failures == []
    assert "passed all" in verdict.why()


def test_a_chart_that_does_not_reconcile_to_its_table_is_refused():
    """The single worst thing this system could put in front of a credit
    committee: both numbers on screen and only one of them right."""
    verdict = vc.review(_bar(series={"ecl": [222.0, 141.0]}), _table())

    assert verdict.approved is False
    assert verdict.get(vc.RECONCILES).outcome == vc.FAIL
    assert verdict.get(vc.RECONCILES).fatal is True
    assert "drawn as 141.0 and tabled as 140.0" in verdict.why()


def test_reconciliation_has_no_tolerance_for_a_visible_difference():
    within = vc.review(_bar(series={"ecl": [222.0 + 1e-9, 140.0]}), _table())
    assert within.approved is True

    visible = vc.review(_bar(series={"ecl": [222.01, 140.0]}), _table())
    assert visible.approved is False


def test_a_missing_table_leaves_reconciliation_unchecked_and_that_is_not_a_pass():
    """A skipped check is not a passed one. The reconciliation check in
    particular passes far too easily when the table it compares against was
    never handed over."""
    verdict = vc.review(_bar(), None)

    assert verdict.get(vc.RECONCILES).outcome == vc.UNCHECKED
    assert verdict.approved is False
    assert vc.RECONCILES in [f.check for f in verdict.unchecked]


def test_a_chart_plotting_a_series_the_table_does_not_have_is_refused():
    verdict = vc.review(_bar(series={"ecl": [222.0, 140.0],
                                     "invented": [1.0, 2.0]}), _table())

    assert verdict.approved is False
    assert "invented is plotted and is not in the table" in \
        verdict.get(vc.RECONCILES).detail


def test_a_quantity_on_the_category_axis_is_refused():
    """§89's first invalid example, checked after the chart is built."""
    verdict = vc.review(_bar(roles={"category": vg.MEASURE,
                                    "value": vg.MEASURE}), _table())

    assert verdict.get(vc.MEASURE_AS_LABEL).outcome == vc.FAIL
    assert verdict.get(vc.MEASURE_AS_LABEL).fatal is True
    assert "is a quantity and not a category name" in verdict.why()


def test_a_truncated_length_encoded_axis_is_refused():
    verdict = vc.review(_bar(axis_starts_at_zero=False), _table())

    assert verdict.get(vc.SCALE).outcome == vc.FAIL
    assert verdict.approved is False


def test_a_scatter_has_no_baseline_to_truncate():
    """NOT_APPLICABLE rather than PASS, because §88's checks are only evidence
    of anything if a reader can tell which ones ran."""
    scatter = vc.Chart(
        chart=vg.SCATTER, roles={"value": vg.MEASURE,
                                 "second_value": vg.MEASURE},
        series={"leverage": [1.0, 2.0]}, units={"leverage": "x"},
        axis_starts_at_zero=False, has_accessible_table=True)
    verdict = vc.review(scatter, vc.Table(values={"leverage": [1.0, 2.0]},
                                          units={"leverage": "x"}))

    assert verdict.get(vc.SCALE).outcome == vc.NOT_APPLICABLE
    assert verdict.approved is True


def test_an_ordinal_axis_sorted_by_value_is_refused():
    """Sorting rating grades by their ECL puts CCC beside AA and calls it a
    ranking."""
    graded = _bar(roles={"category": vg.RISK_BAND, "value": vg.MEASURE},
                  labels=["CCC", "AA"], ordering="by_value")
    verdict = vc.review(graded, _table(labels=["CCC", "AA"]))

    assert verdict.get(vc.ORDERING).outcome == vc.FAIL
    assert "destroys the order" in verdict.get(vc.ORDERING).detail


def test_two_units_on_one_axis_are_refused():
    """Two series in different units on one axis is a chart of two unrelated
    things drawn as though they were comparable."""
    mixed = _bar(series={"ecl": [222.0, 140.0], "coverage": [4.1, 3.2]},
                 units={"ecl": "SAR", "coverage": "%"})
    verdict = vc.review(mixed, _table(
        values={"ecl": [222.0, 140.0], "coverage": [4.1, 3.2]},
        units={"ecl": "SAR", "coverage": "%"}))

    assert verdict.get(vc.UNITS).outcome == vc.FAIL
    assert "not comparable" in verdict.get(vc.UNITS).detail


def test_a_unit_that_disagrees_with_the_computed_one_is_refused():
    verdict = vc.review(_bar(units={"ecl": "%"}), _table())

    assert verdict.get(vc.UNITS).outcome == vc.FAIL
    assert "drawn as % and computed as SAR" in verdict.get(vc.UNITS).detail


def test_more_than_two_decimals_is_refused():
    verdict = vc.review(_bar(decimals=4), _table())

    assert verdict.get(vc.PRECISION).outcome == vc.FAIL
    assert verdict.approved is False


def test_a_chart_with_no_accessible_table_is_refused():
    verdict = vc.review(_bar(has_accessible_table=False), _table())

    assert verdict.get(vc.ACCESSIBLE).outcome == vc.FAIL
    assert verdict.approved is False


def test_a_gap_drawn_as_a_zero_is_refused():
    """It states that something was measured and was nothing, which is a
    different claim entirely."""
    gapped = _bar(series={"ecl": [222.0, None]},
                  missing_shown_as="zero")
    verdict = vc.review(gapped, _table(values={"ecl": [222.0, None]}))

    assert verdict.get(vc.MISSING).outcome == vc.FAIL

    honest = _bar(series={"ecl": [222.0, None]}, missing_shown_as="gap")
    assert vc.review(honest, _table(
        values={"ecl": [222.0, None]})).get(vc.MISSING).outcome == vc.PASS


def test_long_labels_under_a_vertical_axis_are_refused():
    verdict = vc.review(_bar(chart=vg.BAR,
                             labels=["Al Rajhi Contracting Company Limited",
                                     "Real Estate"]),
                        _table(labels=["Al Rajhi Contracting Company Limited",
                                       "Real Estate"]))

    assert verdict.get(vc.LABELS).outcome == vc.FAIL


def test_a_bubble_whose_size_is_already_on_an_axis_is_refused():
    bubble = vc.Chart(
        chart=vg.BUBBLE,
        bindings={"value": "leverage", "second_value": "dscr",
                  "size": "leverage"},
        roles={"value": vg.MEASURE, "second_value": vg.MEASURE,
               "size": vg.MEASURE},
        series={"leverage": [1.0], "dscr": [2.0], "ead": [3.0]},
        units={"leverage": "x", "dscr": "x", "ead": "x"},
        third_dimension_field="leverage", has_accessible_table=True)
    verdict = vc.review(bubble, vc.Table(
        values={"leverage": [1.0], "dscr": [2.0], "ead": [3.0]},
        units={"leverage": "x", "dscr": "x", "ead": "x"}))

    assert verdict.get(vc.THIRD_DIMENSION).outcome == vc.FAIL
    assert "restates a number the reader can see" in \
        verdict.get(vc.THIRD_DIMENSION).detail


def test_the_critic_and_the_grammar_agree_about_axes():
    """Two implementations of "is this axis valid" drift, and the one that
    drifts is always the one that runs last."""
    roles = {"category": vg.IDENTIFIER, "value": vg.MEASURE}
    ok, _ = vg.compatible(vg.BAR, roles)
    verdict = vc.review(_bar(chart=vg.BAR, roles=roles), _table())

    assert ok is False
    assert verdict.get(vc.AXES).outcome == vc.FAIL


def test_a_table_is_approved_without_the_chart_checks_applying():
    verdict = vc.review(vc.Chart(chart=vg.TABLE), _table())

    assert verdict.approved is True
    assert verdict.get(vc.SCALE).outcome == vc.NOT_APPLICABLE
    assert verdict.get(vc.ACCESSIBLE).outcome == vc.PASS


def test_a_rejected_chart_falls_to_the_next_candidate():
    bad = _bar(series={"ecl": [222.0, 999.0]})
    good = _bar()

    rendered = vc.render([bad, good], _table())

    assert rendered.chart == vg.HORIZONTAL_BAR
    assert len(rendered.refused) == 1
    assert rendered.fell_back_to_table is False


def test_when_nothing_passes_the_table_renders():
    """A product that renders a doubtful chart because the alternative feels
    like a climbdown has chosen its own dignity over the reader's."""
    rendered = vc.render([_bar(series={"ecl": [1.0, 2.0]})], _table())

    assert rendered.chart == vg.TABLE
    assert rendered.fell_back_to_table is True
    assert rendered.verdict.approved is True
    assert len(rendered.refused) == 1


def test_every_refusal_is_kept_where_somebody_can_read_it():
    """An invisible control is one nobody maintains."""
    rendered = vc.render([_bar(decimals=6), _bar(has_accessible_table=False)],
                         _table())

    payload = rendered.to_dict()
    assert len(payload["refused"]) == 2
    assert payload["refused"][0]["failed"] == [vc.PRECISION]
    assert payload["refused"][1]["failed"] == [vc.ACCESSIBLE]


def test_a_fatal_check_cannot_be_outweighed_by_the_others_passing():
    verdict = vc.review(_bar(series={"ecl": [0.0, 0.0]}), _table())

    passed = [f for f in verdict.findings if f.outcome == vc.PASS]
    assert len(passed) >= 6
    assert verdict.approved is False
