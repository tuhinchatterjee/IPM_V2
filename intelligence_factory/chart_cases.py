"""
The chart teaching case library. §89.

    "Add at least 150 visualization cases. … Include invalid examples."

Why the invalid examples are the library
-----------------------------------------
A hundred and fifty cases of "this shape maps to this chart" teaches a mapping
that §86 already states as data, and anything reading it would have got right
anyway. The seven invalid examples §89 names — a numeric measure on a category
axis, forty sectors in a vertical bar, a 3D chart with no third dimension, a
Sankey without flow semantics, a heatmap with one axis, a line over unordered
categories, a truncated zero baseline — are the cases where a plausible chart
is a false one, and they are the reason the library exists.

So each valid case is generated across the shapes and dimensions that vary
(category counts, label lengths, period counts, devices), and each invalid one
is written out by hand with the specific rejection reason it must produce.
Both kinds are checked against the real grammar and the real critic in the
tests, so a case cannot claim a preference the system does not make.

What a case is not
-------------------
Not a rendering. Nothing here draws anything, and nothing here contains client
data — the entities are the same governed synthetic names the rest of the
factory uses. A teaching case is a description of a SHAPE and the chart
judgement it warrants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.judgment import visual_grammar as vg

CHART_LIBRARY_VERSION = "1.0.0"

#: §89's floor. Not a target — the library is generated across the dimensions
#: that actually vary, and this is the number below which it stops covering
#: them.
MINIMUM_CASES = 150


@dataclass
class ChartCase:
    """§89's fields, for one visualization judgement."""

    case_id: str
    #: What the result IS, in §86's vocabulary.
    result_shape: str
    #: Role of the field in each of §85's slots.
    semantic_fields: dict[str, str] = field(default_factory=dict)
    preferred_chart: str = vg.TABLE
    acceptable_alternatives: list[str] = field(default_factory=list)
    rejected_charts: list[str] = field(default_factory=list)
    #: Why each rejected chart is wrong, keyed by chart. A rejection with no
    #: reason teaches that the chart is disliked, not what is wrong with it.
    rejection_reasons: dict[str, str] = field(default_factory=dict)
    #: What a reader who cannot use the chart gets instead.
    accessibility_fallback: str = "the result table, with the same figures"
    #: What clicking, hovering and selecting do. §90 depends on this being
    #: declared per chart rather than assumed.
    interaction_contract: str = ""
    #: The scoring inputs this case describes, so a test can run the real
    #: grammar over it rather than trusting the label.
    inputs: dict[str, Any] = field(default_factory=dict)
    #: True for §89's invalid examples: charts that must be refused.
    invalid: bool = False
    teaches: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "result_shape": self.result_shape,
            "semantic_fields": dict(self.semantic_fields),
            "preferred_chart": self.preferred_chart,
            "acceptable_alternatives": list(self.acceptable_alternatives),
            "rejected_charts": list(self.rejected_charts),
            "rejection_reasons": dict(self.rejection_reasons),
            "accessibility_fallback": self.accessibility_fallback,
            "interaction_contract": self.interaction_contract,
            "inputs": dict(self.inputs), "invalid": self.invalid,
            "teaches": self.teaches,
        }

    def scoring_inputs(self) -> vg.Inputs:
        return vg.Inputs(roles=dict(self.semantic_fields), **self.inputs)


# ---------------------------------------------------------------------------
# The interaction contract, per chart
# ---------------------------------------------------------------------------
#
# Declared once here rather than per case. §90's interactive selection depends
# on knowing what a click MEANS on each shape, and a contract invented per
# chart at render time is a contract nobody can test.

INTERACTION: dict[str, str] = {
    vg.KPI: "The figure opens its own calculation; there is nothing to "
            "select.",
    vg.HORIZONTAL_BAR: "Click a bar to filter the investigation to that "
                       "category; hover shows the exact value and its share.",
    vg.BAR: "Click a bar to filter to that category; hover shows the exact "
            "value.",
    vg.GROUPED_BAR: "Click a bar to filter to that category and series; "
                    "click the legend to isolate one series.",
    vg.DUMBBELL: "Click a row to open the two-period comparison for that "
                 "category; hover shows both values and the change.",
    vg.SLOPE: "Click a line to follow one category across the two periods.",
    vg.LINE: "Hover reads every series at that period; click a point to open "
             "the period.",
    vg.SMALL_MULTIPLES: "Click a panel to open that series alone; the y-axis "
                        "is shared so panels stay comparable.",
    vg.STACKED_AREA: "Hover reads the band and the total; click a band to "
                     "isolate that component.",
    vg.STACKED_BAR: "Click a segment to filter to that component; hover "
                    "shows the segment and the total.",
    vg.WATERFALL: "Click a step to open the contribution behind it; the "
                  "running total is shown at every step.",
    vg.SANKEY: "Click a flow to list the entities that took it; hover shows "
               "the volume and the two states.",
    vg.MIGRATION_MATRIX: "Click a cell to list the entities that moved that "
                         "way; the diagonal is the unchanged population.",
    vg.HISTOGRAM: "Click a bin to list the records in it; hover shows the "
                  "bin's range and count.",
    vg.BOX_PLOT: "Hover reads the quartiles; click an outlier to open that "
                 "record.",
    vg.SCATTER: "Click a point to open that entity; drag to select a region "
                "and filter to it.",
    vg.BUBBLE: "Click a bubble to open that entity; the legend states what "
               "size encodes.",
    vg.RISK_LANDSCAPE: "Click a point to open that entity; the axes and the "
                       "size are named in the legend, and each is a "
                       "separately validated measure.",
    vg.TREEMAP: "Click a tile to descend one level; the path back is shown "
                "above.",
    vg.HEATMAP: "Click a cell to filter to that category and period; the "
                "colour scale is governed and stated.",
    vg.TABLE: "Sort by any column; click a row to open that record.",
}


# ---------------------------------------------------------------------------
# The valid cases, generated across what actually varies
# ---------------------------------------------------------------------------
#
# Written as data because the variation IS the coverage: the same shape at 6,
# 20 and 45 categories is three different judgements, and enumerating them by
# hand would produce a hundred and fifty near-copies with typos in them.

_SECTORS = "sector"
_BORROWER = "borrower"

#: (shape, roles, teaches) — the base of each family of cases.
_FAMILIES: tuple[tuple[str, dict[str, str], str], ...] = (
    (vg.SINGLE_VALUE, {"value": vg.MEASURE},
     "one validated figure is a headline, not a bar of length one"),
    (vg.CATEGORY_RANKING, {"category": vg.CATEGORY, "value": vg.MEASURE},
     "a ranking reads horizontally once the labels are names"),
    (vg.CATEGORY_RANKING, {"category": vg.ENTITY, "value": vg.MEASURE},
     "named counterparties do not fit under a vertical axis"),
    (vg.CATEGORY_RANKING, {"category": vg.RISK_BAND, "value": vg.PERCENTAGE},
     "a risk band keeps its own order and is never sorted by size"),
    (vg.TWO_PERIOD_CATEGORY, {"category": vg.CATEGORY, "value": vg.MEASURE},
     "two dates for the same categories is a comparison, not a time series"),
    (vg.TIME_SERIES, {"time": vg.TIME, "value": vg.MEASURE},
     "a measure across periods is a line"),
    (vg.TIME_SERIES, {"time": vg.TIME, "value": vg.PERCENTAGE},
     "a rate across periods is a line with a stated denominator"),
    (vg.MANY_TIME_SERIES, {"time": vg.TIME, "value": vg.MEASURE,
                           "series": vg.CATEGORY},
     "several series stop being one chart and become small multiples"),
    (vg.COMPOSITION_OVER_TIME, {"time": vg.TIME, "value": vg.MEASURE,
                                "series": vg.CATEGORY},
     "parts of a whole across periods stack; parts that are rates do not"),
    (vg.CHANGE_DECOMPOSITION, {"category": vg.ENTITY,
                               "value": vg.DECOMPOSITION_COMPONENT},
     "contributions that reconcile to a total are a waterfall"),
    (vg.CHANGE_DECOMPOSITION, {"category": vg.CATEGORY,
                               "value": vg.DECOMPOSITION_COMPONENT},
     "a decomposition shows the total it reconciles to at every step"),
    (vg.MIGRATION_PATHS, {"source": vg.FLOW_SOURCE,
                          "destination": vg.FLOW_DESTINATION,
                          "value": vg.MEASURE},
     "movements between states need both ends and a volume"),
    (vg.MIGRATION_GRID, {"category": vg.RISK_BAND, "series": vg.RISK_BAND,
                         "value": vg.MEASURE},
     "opening against closing is a matrix whose diagonal is the unchanged"),
    (vg.DISTRIBUTION, {"value": vg.DISTRIBUTION_VALUE},
     "a spread is the question, so the total is not the answer"),
    (vg.TWO_MEASURE, {"value": vg.MEASURE, "second_value": vg.MEASURE},
     "two measures over the same entities is an association, not a cause"),
    (vg.THREE_MEASURE, {"value": vg.MEASURE, "second_value": vg.MEASURE,
                        "size": vg.MEASURE},
     "a third dimension must be independent to be worth drawing"),
    (vg.CONCENTRATION_HIERARCHY, {"category": vg.CATEGORY,
                                  "value": vg.MEASURE},
     "relative size across nested groups is a treemap"),
    (vg.CATEGORY_PERIOD_MEASURE, {"category": vg.CATEGORY,
                                  "series": vg.TIME, "value": vg.MEASURE},
     "categories against periods is a heatmap with a governed scale"),
    (vg.RECORD_LEVEL, {"category": vg.ENTITY, "value": vg.MEASURE},
     "records the reader needs the values of are a table"),
)

#: The dimensions each family is generated across. Chosen because each one
#: changes the answer: 6 sectors and 45 sectors are different charts, and a
#: narrow device is a different chart again.
_SPREADS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("small", {"categories": 6, "longest_label": 11, "periods": 4,
               "measures": 1, "cardinality": 6}),
    ("mid", {"categories": 18, "longest_label": 14, "periods": 8,
             "measures": 1, "cardinality": 18}),
    ("wide", {"categories": 42, "longest_label": 12, "periods": 12,
              "measures": 1, "cardinality": 42}),
    ("long-labels", {"categories": 9, "longest_label": 34, "periods": 4,
                     "measures": 1, "cardinality": 9}),
    ("narrow-device", {"categories": 9, "longest_label": 12, "periods": 6,
                       "measures": 1, "cardinality": 9,
                       "narrow_device": True}),
    ("sparse", {"categories": 12, "longest_label": 12, "periods": 6,
                "measures": 1, "cardinality": 12, "missing_pct": 0.28}),
    ("exact-records", {"categories": 12, "longest_label": 12, "periods": 4,
                       "measures": 1, "cardinality": 12,
                       "wants_records": True}),
    ("high-precision", {"categories": 8, "longest_label": 12, "periods": 4,
                        "measures": 1, "cardinality": 8,
                        "precision_required": 4}),
)


def _tune(shape: str, roles: dict[str, str],
          spread: dict[str, Any]) -> dict[str, Any]:
    """The spread, adjusted for what the shape structurally requires.

    A three-measure shape with `measures: 1` is not a hard case, it is an
    impossible one, and generating it would fill the library with cases that
    fail for a reason the case was not about.
    """
    tuned = dict(spread)
    if shape == vg.THREE_MEASURE:
        tuned["measures"] = 3
    elif shape in (vg.MANY_TIME_SERIES, vg.COMPOSITION_OVER_TIME):
        tuned["measures"] = 4
    elif shape == vg.TWO_MEASURE:
        tuned["measures"] = 2
    elif shape == vg.RECORD_LEVEL:
        tuned["measures"] = 8
    if shape == vg.SINGLE_VALUE:
        tuned["categories"] = 1
        tuned["cardinality"] = 1
    if shape in (vg.TIME_SERIES, vg.MANY_TIME_SERIES,
                 vg.COMPOSITION_OVER_TIME):
        tuned["periods"] = max(3, int(tuned.get("periods", 4)))
    if shape == vg.TWO_PERIOD_CATEGORY:
        tuned["periods"] = 2
    # A length-encoded chart of a rate needs its zero baseline; the spread
    # does not decide that, the roles do.
    if vg.PERCENTAGE in roles.values():
        tuned["needs_zero_baseline"] = True
    return tuned


def _valid_cases() -> list[ChartCase]:
    cases: list[ChartCase] = []
    for index, (shape, roles, teaches) in enumerate(_FAMILIES):
        for name, spread in _SPREADS:
            inputs = _tune(shape, roles, spread)
            selection = vg.select(shape, vg.Inputs(roles=dict(roles),
                                                   **inputs))
            rejected = [s.chart for s in selection.rejected]
            cases.append(ChartCase(
                case_id=f"cc-{index + 1:02d}-{name}",
                result_shape=shape,
                semantic_fields=dict(roles),
                preferred_chart=selection.chosen,
                acceptable_alternatives=[s.chart for s in selection.accepted
                                         if s.chart != selection.chosen],
                rejected_charts=rejected,
                rejection_reasons={
                    s.chart: s.rejections[0] for s in selection.rejected
                    if s.rejections},
                interaction_contract=INTERACTION.get(selection.chosen, ""),
                inputs=inputs, teaches=teaches))
    return cases


# ---------------------------------------------------------------------------
# §89's invalid examples
# ---------------------------------------------------------------------------
#
# Seven, named in the brief, written by hand because each one is a specific
# false chart rather than a shape at an awkward size. The `must_reject`
# fragment is asserted against the real grammar in the tests: a case that
# claimed a rejection the system does not make would teach a rule that does
# not exist.

@dataclass
class InvalidCase(ChartCase):
    """A chart that must be refused, and the words the refusal must contain."""

    attempted_chart: str = ""
    must_reject: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(),
                "attempted_chart": self.attempted_chart,
                "must_reject": self.must_reject}


INVALID: tuple[InvalidCase, ...] = (
    InvalidCase(
        case_id="cc-bad-measure-as-category",
        result_shape=vg.CATEGORY_RANKING,
        semantic_fields={"category": vg.MEASURE, "value": vg.MEASURE},
        attempted_chart=vg.BAR,
        must_reject="does not label a category",
        preferred_chart=vg.HISTOGRAM,
        rejected_charts=[vg.BAR],
        rejection_reasons={
            vg.BAR: "a quantity on the category axis produces one bar per "
                    "distinct value, ordered by magnitude, which looks like a "
                    "ranking of things and is a ranking of numbers"},
        teaches="a numeric measure is not a category axis, whatever its dtype",
        invalid=True,
        inputs={"categories": 40, "measures": 1, "cardinality": 40}),

    InvalidCase(
        case_id="cc-bad-too-many-vertical-bars",
        result_shape=vg.CATEGORY_RANKING,
        semantic_fields={"category": vg.CATEGORY, "value": vg.MEASURE},
        attempted_chart=vg.BAR,
        must_reject="categories in a bar chart",
        preferred_chart=vg.TREEMAP,
        acceptable_alternatives=[vg.TABLE],
        rejected_charts=[vg.BAR],
        rejection_reasons={
            vg.BAR: "forty-four sectors in a vertical bar chart is a picket "
                    "fence; no label is readable and no two bars can be "
                    "compared"},
        teaches="too many categories in a vertical bar chart",
        invalid=True,
        inputs={"categories": 44, "longest_label": 12, "measures": 1,
                "cardinality": 44}),

    InvalidCase(
        case_id="cc-bad-third-dimension-restated",
        result_shape=vg.THREE_MEASURE,
        semantic_fields={"value": vg.MEASURE, "second_value": vg.MEASURE,
                         "size": vg.MEASURE},
        attempted_chart=vg.BUBBLE,
        must_reject="independent measure",
        preferred_chart=vg.SCATTER,
        rejected_charts=[vg.BUBBLE, vg.RISK_LANDSCAPE],
        rejection_reasons={
            vg.BUBBLE: "the bubble size restates the y-value, so the chart "
                       "shows two numbers and appears to show three"},
        teaches="a 3D chart with no independent third dimension",
        invalid=True,
        inputs={"measures": 2, "categories": 60, "cardinality": 60}),

    InvalidCase(
        case_id="cc-bad-sankey-without-flow",
        result_shape=vg.MIGRATION_PATHS,
        semantic_fields={"source": vg.CATEGORY, "destination": vg.CATEGORY,
                         "value": vg.MEASURE},
        attempted_chart=vg.SANKEY,
        must_reject="flow source and a flow destination",
        preferred_chart=vg.MIGRATION_MATRIX,
        rejected_charts=[vg.SANKEY],
        rejection_reasons={
            vg.SANKEY: "two unrelated categories drawn as a Sankey assert "
                       "that volume moved from one to the other, which "
                       "nothing computed"},
        teaches="a Sankey without flow semantics",
        invalid=True,
        inputs={"categories": 8, "measures": 1, "cardinality": 8}),

    InvalidCase(
        case_id="cc-bad-heatmap-one-axis",
        result_shape=vg.CATEGORY_PERIOD_MEASURE,
        semantic_fields={"category": vg.CATEGORY, "value": vg.MEASURE},
        attempted_chart=vg.HEATMAP,
        must_reject="two categorical axes",
        preferred_chart=vg.HORIZONTAL_BAR,
        rejected_charts=[vg.HEATMAP],
        rejection_reasons={
            vg.HEATMAP: "one categorical axis makes a heatmap a bar chart "
                        "drawn in colour, which encodes the same information "
                        "less precisely"},
        teaches="a heatmap with one categorical axis only",
        invalid=True,
        inputs={"categories": 12, "measures": 1, "cardinality": 12}),

    InvalidCase(
        case_id="cc-bad-line-over-categories",
        result_shape=vg.CATEGORY_RANKING,
        semantic_fields={"category": vg.CATEGORY, "value": vg.MEASURE},
        attempted_chart=vg.LINE,
        must_reject="asserts an order between categories that have none",
        preferred_chart=vg.HORIZONTAL_BAR,
        rejected_charts=[vg.LINE],
        rejection_reasons={
            vg.LINE: "a line between sectors says the space between "
                     "Contracting and Real Estate is traversable, and that "
                     "the slope between them means something"},
        teaches="a line chart for unordered categories",
        invalid=True,
        inputs={"categories": 8, "periods": 1, "measures": 1,
                "cardinality": 8}),

    InvalidCase(
        case_id="cc-bad-truncated-baseline",
        result_shape=vg.CATEGORY_RANKING,
        semantic_fields={"category": vg.CATEGORY, "value": vg.PERCENTAGE},
        attempted_chart=vg.BAR,
        must_reject="cannot start at zero",
        preferred_chart=vg.TABLE,
        rejected_charts=[vg.BAR, vg.HORIZONTAL_BAR, vg.TREEMAP],
        rejection_reasons={
            vg.BAR: "coverage ratios of 3.1% and 3.3% drawn from a baseline "
                    "of 3% look like a doubling, and the reader has no way to "
                    "see that the axis was cut"},
        teaches="a truncated zero baseline where the value is a length",
        invalid=True,
        inputs={"categories": 8, "measures": 1, "cardinality": 8,
                "needs_zero_baseline": True,
                "zero_baseline_available": False}),
)


CASES: tuple[ChartCase, ...] = (*_valid_cases(), *INVALID)
BY_ID: dict[str, ChartCase] = {c.case_id: c for c in CASES}


def valid() -> list[ChartCase]:
    return [c for c in CASES if not c.invalid]


def invalid() -> list[InvalidCase]:
    return list(INVALID)


def by_shape(shape: str) -> list[ChartCase]:
    return [c for c in CASES if c.result_shape == shape]


def coverage() -> dict[str, int]:
    """Cases per §86 shape. A zero is a gap, and visible."""
    return {shape: len(by_shape(shape)) for shape in vg.SHAPES}


def gaps() -> list[str]:
    return [shape for shape, count in coverage().items() if count == 0]


def charts_taught() -> dict[str, int]:
    """How often each chart kind is the preferred answer.

    Reported because a library that never prefers a waterfall is a library
    that cannot teach one, however many cases it has.
    """
    counts = {chart: 0 for chart in vg.CHARTS}
    for case in valid():
        counts[case.preferred_chart] = counts.get(case.preferred_chart, 0) + 1
    return counts


def report() -> dict[str, Any]:
    return {
        "version": CHART_LIBRARY_VERSION,
        "total": len(CASES),
        "valid": len(valid()),
        "invalid": len(INVALID),
        "minimum": MINIMUM_CASES,
        "meets_minimum": len(CASES) >= MINIMUM_CASES,
        "coverage": coverage(),
        "gaps": gaps(),
        "charts_taught": {k: v for k, v in charts_taught().items() if v},
        "never_preferred": [k for k, v in charts_taught().items() if not v],
    }


__all__ = ["BY_ID", "CASES", "CHART_LIBRARY_VERSION", "ChartCase",
           "INTERACTION", "INVALID", "InvalidCase", "MINIMUM_CASES",
           "by_shape", "charts_taught", "coverage", "gaps", "invalid",
           "report", "valid"]
