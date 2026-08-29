"""
The Visualization Grammar: semantic roles, governed mapping, suitability.
§85, §86, §87.

    "Use semantic roles, not raw data types alone."

That instruction is the whole module in one line, and the failure behind it is
specific. A rating grade stored as an integer is not a measure. A stage number
is not a quantity. A customer id is not a value to plot. Every one of those
gets drawn as a bar by anything that reads dtypes, and each produces a chart
that is confidently, silently wrong — an axis of borrower ids ranked by
magnitude, a mean IFRS 9 stage of 1.7.

So a field's ROLE is what the chart is chosen from: fifteen roles that say
what a column means rather than what it is stored as, and a mapping from
result shapes to chart kinds that a person can read and disagree with.

Why the mapping is a table rather than a function
--------------------------------------------------
§86 gives fifteen shape → chart rules. Written as branching code they become
unreviewable within a month, and nobody can answer "what does CreditProbe draw
for a migration matrix?" without reading the whole function. Written as data
they can be listed, reviewed, disagreed with and tested one at a time — and
the Studio can show them.

Why suitability is scored rather than decided
----------------------------------------------
The default mapping is right most of the time and wrong in ways nothing about
the shape reveals: forty sectors is a valid category ranking and an unreadable
bar chart; a two-period comparison of two entities is a valid slope chart and
a pointless one. §87 scores each candidate against thirteen measures of
whether it will actually READ, rejects below a threshold, and — the part that
matters — persists the losing scores and the reasons. A picker that shows only
its winner cannot be argued with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GRAMMAR_VERSION = "1.0.0"

# ---------------------------------------------------------------- §85's roles
ENTITY = "ENTITY"
IDENTIFIER = "IDENTIFIER"
CATEGORY = "CATEGORY"
ORDINAL_CATEGORY = "ORDINAL_CATEGORY"
TIME = "TIME"
MEASURE = "MEASURE"
PERCENTAGE = "PERCENTAGE"
PERCENTAGE_POINT = "PERCENTAGE_POINT"
FLOW_SOURCE = "FLOW_SOURCE"
FLOW_DESTINATION = "FLOW_DESTINATION"
DISTRIBUTION_VALUE = "DISTRIBUTION_VALUE"
DECOMPOSITION_COMPONENT = "DECOMPOSITION_COMPONENT"
GEOGRAPHY = "GEOGRAPHY"
RISK_BAND = "RISK_BAND"
TECHNICAL_LINEAGE = "TECHNICAL_LINEAGE"

ROLES: tuple[str, ...] = (
    ENTITY, IDENTIFIER, CATEGORY, ORDINAL_CATEGORY, TIME, MEASURE, PERCENTAGE,
    PERCENTAGE_POINT, FLOW_SOURCE, FLOW_DESTINATION, DISTRIBUTION_VALUE,
    DECOMPOSITION_COMPONENT, GEOGRAPHY, RISK_BAND, TECHNICAL_LINEAGE,
)

#: What each role means, in the words somebody would use to argue that a
#: column was classified wrongly.
ROLE_MEANS: dict[str, str] = {
    ENTITY: "A named thing the reader recognises — a borrower, a sector, a "
            "branch. Labels an axis; never plotted as a value.",
    IDENTIFIER: "A key. Identifies a row and means nothing on an axis, even "
                "when it is stored as a number.",
    CATEGORY: "An unordered grouping. Bars may be sorted by their measure; a "
              "line between them would assert an order that does not exist.",
    ORDINAL_CATEGORY: "A grouping WITH an order — rating grades, stages, "
                      "ageing buckets. The order is the information and must "
                      "not be re-sorted by size.",
    TIME: "A period. The only role a line chart's x-axis may take.",
    MEASURE: "A quantity in units — an amount, a count, a days figure.",
    PERCENTAGE: "A rate. Two of these are not addable and a stacked chart of "
                "them is arithmetic nobody performed.",
    PERCENTAGE_POINT: "A difference between two percentages. Kept apart from "
                      "PERCENTAGE because conflating them is how 'coverage "
                      "rose 2%' comes to mean two things in one chart.",
    FLOW_SOURCE: "Where something came from. Half of a flow; meaningless "
                 "without its destination.",
    FLOW_DESTINATION: "Where something went.",
    DISTRIBUTION_VALUE: "A per-record value whose SPREAD is the point, not "
                        "its total.",
    DECOMPOSITION_COMPONENT: "A signed contribution that sums to a total. A "
                             "waterfall's steps; misread as a category it "
                             "becomes a bar chart of parts nobody can add.",
    GEOGRAPHY: "A place, which may be mapped.",
    RISK_BAND: "A governed band — stage, grade, watchlist tier. Ordinal, and "
               "its colour scale is governed rather than chosen.",
    TECHNICAL_LINEAGE: "Plumbing: as-of stamps, carried keys, denominators. "
                       "Never drawn.",
}

#: Roles that may sit on a value axis. Everything else on a value axis is the
#: §88 failure "numeric measures are not category labels" seen from the other
#: side: a category on the axis where the numbers go.
PLOTTABLE: frozenset[str] = frozenset({
    MEASURE, PERCENTAGE, PERCENTAGE_POINT, DISTRIBUTION_VALUE,
    DECOMPOSITION_COMPONENT})

#: Roles that may label a categorical axis.
LABELLING: frozenset[str] = frozenset({
    ENTITY, CATEGORY, ORDINAL_CATEGORY, RISK_BAND, GEOGRAPHY, FLOW_SOURCE,
    FLOW_DESTINATION})

#: Roles that carry an inherent order which must not be re-sorted by size.
#: Sorting rating grades by ECL puts CCC next to AA and calls it a ranking.
ORDERED: frozenset[str] = frozenset({ORDINAL_CATEGORY, RISK_BAND, TIME})

#: Never drawn, on any axis, in any chart.
NEVER_DRAWN: frozenset[str] = frozenset({IDENTIFIER, TECHNICAL_LINEAGE})


def plottable(role: str) -> bool:
    """Whether a value axis may carry this role.

    Unknown roles are refused rather than allowed. A column nobody classified
    is a column nobody checked, and the failure mode of the permissive answer
    is a chart with borrower ids up the y-axis.
    """
    return role in PLOTTABLE


def labelling(role: str) -> bool:
    return role in LABELLING


# ---------------------------------------------------------- §86's mapping
KPI = "kpi"
HORIZONTAL_BAR = "bar_horizontal"
BAR = "bar"
GROUPED_BAR = "bar_grouped"
DUMBBELL = "dumbbell"
SLOPE = "slope"
LINE = "line"
SMALL_MULTIPLES = "small_multiples"
STACKED_AREA = "stacked_area"
STACKED_BAR = "bar_stacked"
WATERFALL = "waterfall"
SANKEY = "sankey"
MIGRATION_MATRIX = "migration_matrix"
HISTOGRAM = "histogram"
BOX_PLOT = "box_plot"
SCATTER = "scatter"
BUBBLE = "bubble"
RISK_LANDSCAPE = "risk_landscape"
TREEMAP = "treemap"
HEATMAP = "heatmap"
TABLE = "table"

CHARTS: tuple[str, ...] = (
    KPI, HORIZONTAL_BAR, BAR, GROUPED_BAR, DUMBBELL, SLOPE, LINE,
    SMALL_MULTIPLES, STACKED_AREA, STACKED_BAR, WATERFALL, SANKEY,
    MIGRATION_MATRIX, HISTOGRAM, BOX_PLOT, SCATTER, BUBBLE, RISK_LANDSCAPE,
    TREEMAP, HEATMAP, TABLE,
)

#: What each is called on screen. A reader asked for "a graph"; telling them
#: they were given a `bar_horizontal` is the product speaking its enum aloud.
CHART_LABEL: dict[str, str] = {
    KPI: "a headline figure", HORIZONTAL_BAR: "a horizontal bar chart",
    BAR: "a bar chart", GROUPED_BAR: "a grouped bar chart",
    DUMBBELL: "a dumbbell chart", SLOPE: "a slope chart",
    LINE: "a line chart", SMALL_MULTIPLES: "small multiples",
    STACKED_AREA: "a stacked area chart", STACKED_BAR: "a stacked bar chart",
    WATERFALL: "a waterfall chart", SANKEY: "a Sankey diagram",
    MIGRATION_MATRIX: "a migration matrix", HISTOGRAM: "a histogram",
    BOX_PLOT: "a box plot", SCATTER: "a scatter plot", BUBBLE: "a bubble chart",
    RISK_LANDSCAPE: "a risk landscape", TREEMAP: "a treemap",
    HEATMAP: "a heatmap", TABLE: "a table",
}

# The fifteen result shapes §86 names, as data rather than as branches. Listed
# in §86's order so the mapping can be read against the brief line by line.
SINGLE_VALUE = "single_validated_value"
CATEGORY_RANKING = "category_ranking"
TWO_PERIOD_CATEGORY = "two_period_category_comparison"
TIME_SERIES = "time_series"
MANY_TIME_SERIES = "multiple_time_series"
COMPOSITION_OVER_TIME = "composition_over_time"
CHANGE_DECOMPOSITION = "change_decomposition"
MIGRATION_PATHS = "migration_paths"
MIGRATION_GRID = "opening_closing_grid"
DISTRIBUTION = "distribution"
TWO_MEASURE = "two_measure_relationship"
THREE_MEASURE = "three_independent_measures"
CONCENTRATION_HIERARCHY = "concentration_hierarchy"
CATEGORY_PERIOD_MEASURE = "category_period_measure"
RECORD_LEVEL = "record_level_heterogeneous"

SHAPES: tuple[str, ...] = (
    SINGLE_VALUE, CATEGORY_RANKING, TWO_PERIOD_CATEGORY, TIME_SERIES,
    MANY_TIME_SERIES, COMPOSITION_OVER_TIME, CHANGE_DECOMPOSITION,
    MIGRATION_PATHS, MIGRATION_GRID, DISTRIBUTION, TWO_MEASURE, THREE_MEASURE,
    CONCENTRATION_HIERARCHY, CATEGORY_PERIOD_MEASURE, RECORD_LEVEL,
)

#: §86's default mapping. First entry is the default; the rest are the
#: acceptable alternatives the picker offers and the suitability score may
#: promote when the default does not read.
MAPPING: dict[str, tuple[str, ...]] = {
    SINGLE_VALUE: (KPI,),
    CATEGORY_RANKING: (HORIZONTAL_BAR, BAR, TREEMAP),
    TWO_PERIOD_CATEGORY: (DUMBBELL, SLOPE, GROUPED_BAR),
    TIME_SERIES: (LINE, BAR),
    MANY_TIME_SERIES: (SMALL_MULTIPLES, LINE),
    COMPOSITION_OVER_TIME: (STACKED_AREA, STACKED_BAR),
    CHANGE_DECOMPOSITION: (WATERFALL, HORIZONTAL_BAR),
    MIGRATION_PATHS: (SANKEY, MIGRATION_MATRIX),
    MIGRATION_GRID: (MIGRATION_MATRIX, HEATMAP),
    DISTRIBUTION: (HISTOGRAM, BOX_PLOT),
    TWO_MEASURE: (SCATTER,),
    THREE_MEASURE: (BUBBLE, RISK_LANDSCAPE),
    CONCENTRATION_HIERARCHY: (TREEMAP, HORIZONTAL_BAR),
    CATEGORY_PERIOD_MEASURE: (HEATMAP, SMALL_MULTIPLES),
    RECORD_LEVEL: (TABLE,),
}

#: What each shape IS, so a reviewer can check the classification rather than
#: only the chart.
SHAPE_MEANS: dict[str, str] = {
    SINGLE_VALUE: "One validated figure and nothing to compare it against.",
    CATEGORY_RANKING: "One measure across unordered or ordinal groupings.",
    TWO_PERIOD_CATEGORY: "The same measure for the same groupings at two "
                         "dates.",
    TIME_SERIES: "One measure across three or more periods.",
    MANY_TIME_SERIES: "Several measures or several entities across periods.",
    COMPOSITION_OVER_TIME: "Parts of a whole across periods.",
    CHANGE_DECOMPOSITION: "Signed contributions that reconcile to a total "
                          "movement.",
    MIGRATION_PATHS: "Movements from one state to another, with volumes.",
    MIGRATION_GRID: "Opening state against closing state.",
    DISTRIBUTION: "Per-record values whose spread is the question.",
    TWO_MEASURE: "Two measures over the same entities.",
    THREE_MEASURE: "Three independent measures over the same entities.",
    CONCENTRATION_HIERARCHY: "Nested parts whose relative size is the point.",
    CATEGORY_PERIOD_MEASURE: "One measure over categories and periods both.",
    RECORD_LEVEL: "Heterogeneous records the reader needs the values of.",
}


def default_for(shape: str) -> str:
    """§86's default chart for a shape, or a table when the shape is unknown.

    Unknown shapes fall to a table rather than to a guess. A table of the
    right numbers is never wrong; a chart chosen for a shape nothing
    recognised very often is.
    """
    return MAPPING.get(shape, (TABLE,))[0]


def candidates_for(shape: str) -> tuple[str, ...]:
    """Every chart §86 permits for a shape, plus the table.

    The table is always a candidate. It is the fallback §88 falls to when
    every chart is rejected, and a candidate list that could come back empty
    would leave the critic with nothing to choose.
    """
    mapped = MAPPING.get(shape, ())
    return (*mapped, TABLE) if TABLE not in mapped else mapped


# ------------------------------------------------------- §87's suitability
#
# Thirteen measures, each in [0, 1], each a way a chart that is right for the
# shape still fails to read. Weighted because they are not equally fatal: an
# unreadable label is a nuisance, a misleading scale is a false statement.

FACTORS: tuple[str, ...] = (
    "semantic_role_compatibility", "category_count", "label_length",
    "period_count", "measure_count", "cardinality", "missingness", "overlap",
    "zero_baseline", "accessibility", "precision", "pattern_versus_records",
    "device",
)

WEIGHTS: dict[str, float] = {
    # A chart whose axes carry the wrong roles is not a bad chart, it is a
    # false one, so this dominates.
    "semantic_role_compatibility": 3.0,
    "zero_baseline": 2.0,
    "pattern_versus_records": 2.0,
    "category_count": 1.5,
    "cardinality": 1.5,
    "overlap": 1.2,
    "missingness": 1.2,
    "period_count": 1.0,
    "measure_count": 1.0,
    "label_length": 0.8,
    "accessibility": 0.8,
    "precision": 0.8,
    "device": 0.5,
}

#: Below this a candidate is rejected. Set where a chart failing role
#: compatibility outright cannot pass on the strength of everything else.
THRESHOLD = 0.55

#: A zero on either of these rejects the candidate whatever the weighted
#: average says — and does so through its own recorded reason rather than
#: through the average. §87 scores; it does not average away a chart that
#: asserts something untrue.
FATAL: frozenset[str] = frozenset({"semantic_role_compatibility",
                                    "zero_baseline"})

#: How far a single factor may fall before it becomes a stated reason to
#: reject rather than a mark against. Set so a chart carrying 12% more
#: categories than it comfortably holds still ships — 41 categories is not a
#: different kind of chart from 39 — while one carrying four times too many
#: does not.
SOFT_FLOOR = 0.75

#: Labels above this get rotated under a vertical axis, and rotated labels are
#: how charts become unreadable. Horizontal bars do not have the problem,
#: which is why a long-labelled ranking maps to one.
MAX_LABEL = 16

#: Charts whose category labels sit under a vertical axis.
VERTICAL_LABELS: frozenset[str] = frozenset({BAR, GROUPED_BAR, STACKED_BAR,
                                              LINE, STACKED_AREA})


#: The slots a chart binds fields to. Named semantically rather than as x and
#: y, because x is a category in a bar chart and a quantity in a scatter, and
#: a compatibility check that assumed either would be wrong half the time.
VALUE_SLOTS: tuple[str, ...] = ("value", "second_value", "size")
LABEL_SLOTS: tuple[str, ...] = ("category", "series", "source", "destination")
SLOTS: tuple[str, ...] = (*VALUE_SLOTS, *LABEL_SLOTS, "time")


@dataclass
class Inputs:
    """What §87 scores a candidate against.

    Every field is a property of the RESULT and the request, never of the
    values. Nothing here reads a number to decide what to draw.
    """

    #: Role of the field bound to each slot, keyed by slot name — `category`,
    #: `series`, `value`, `second_value`, `size`, `time`, `source`,
    #: `destination`.
    roles: dict[str, str] = field(default_factory=dict)
    categories: int = 0
    longest_label: int = 0
    periods: int = 0
    measures: int = 0
    #: Distinct values in the categorical field. Differs from `categories`
    #: when the result is already grouped.
    cardinality: int = 0
    missing_pct: float = 0.0
    #: How much the series would overlap when drawn — 0 is clean, 1 is a
    #: hairball.
    overlap: float = 0.0
    #: Whether the measure's axis must start at zero to be honest. True for
    #: anything whose LENGTH encodes the value.
    needs_zero_baseline: bool = False
    zero_baseline_available: bool = True
    #: Whether the reader asked to see a pattern or to read exact records.
    wants_records: bool = False
    #: Decimal places the answer needs to be read at.
    precision_required: int = 0
    accessible_alternative: bool = True
    narrow_device: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"roles": dict(self.roles), "categories": self.categories,
                "longest_label": self.longest_label, "periods": self.periods,
                "measures": self.measures, "cardinality": self.cardinality,
                "missing_pct": self.missing_pct, "overlap": self.overlap,
                "needs_zero_baseline": self.needs_zero_baseline,
                "zero_baseline_available": self.zero_baseline_available,
                "wants_records": self.wants_records,
                "precision_required": self.precision_required,
                "accessible_alternative": self.accessible_alternative,
                "narrow_device": self.narrow_device}


@dataclass
class Score:
    """One candidate's suitability, with every factor that produced it."""

    chart: str
    factors: dict[str, float] = field(default_factory=dict)
    total: float = 0.0
    accepted: bool = False
    #: Why it was rejected, in the words a reader would use. §87: persist
    #: rejection reasons. A picker that shows only its winner cannot be
    #: argued with.
    rejections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"chart": self.chart, "label": CHART_LABEL.get(self.chart,
                                                              self.chart),
                "factors": {k: round(v, 3) for k, v in self.factors.items()},
                "total": round(self.total, 4), "accepted": self.accepted,
                "rejections": list(self.rejections)}


#: How many categories each chart can carry before it stops reading. A
#: horizontal bar scrolls and stays legible; a pie — which is not in the
#: mapping for exactly this reason — does not.
CATEGORY_CEILING: dict[str, int] = {
    BAR: 12, HORIZONTAL_BAR: 40, GROUPED_BAR: 10, STACKED_BAR: 8,
    STACKED_AREA: 8, SLOPE: 15, DUMBBELL: 25, TREEMAP: 60, HEATMAP: 40,
    SANKEY: 20, MIGRATION_MATRIX: 12, SMALL_MULTIPLES: 12, LINE: 8,
    WATERFALL: 15, SCATTER: 5000, BUBBLE: 500, RISK_LANDSCAPE: 500,
    HISTOGRAM: 60, BOX_PLOT: 20, KPI: 1, TABLE: 1_000_000,
}

#: Charts whose value is encoded as a LENGTH from an origin. Truncating their
#: axis makes a 2% difference look like a 200% one, which is the one charting
#: failure that has its own literature.
LENGTH_ENCODED: frozenset[str] = frozenset({
    BAR, HORIZONTAL_BAR, GROUPED_BAR, STACKED_BAR, STACKED_AREA, WATERFALL,
    TREEMAP, HISTOGRAM})

#: Charts that show a pattern and cannot show a value. Asking one of these for
#: exact records is asking the wrong object.
PATTERN_ONLY: frozenset[str] = frozenset({
    SCATTER, BUBBLE, RISK_LANDSCAPE, HEATMAP, TREEMAP, SANKEY, STACKED_AREA,
    BOX_PLOT})


def _role_compatibility(chart: str, inputs: Inputs) -> tuple[float, list[str]]:
    """Whether the slots carry roles that mean what the chart asserts. §85.

    The one factor that can be zero on its own merits, because a chart whose
    category axis is a borrower id is not a chart that reads poorly — it is a
    picture of something that was never true.
    """
    # A table asserts nothing about roles; it prints the values, identifiers
    # and lineage stamps included. Running the chart checks over it rejected
    # the one candidate that exists to catch the others, and left `select`
    # falling back to a shape it had just refused.
    if chart == TABLE:
        return 1.0, []

    problems: list[str] = []
    roles = inputs.roles

    for slot in VALUE_SLOTS:
        role = roles.get(slot)
        if not role:
            continue
        if role in NEVER_DRAWN:
            problems.append(f"the {slot} slot carries {role}, which is never "
                            "drawn")
        elif not plottable(role):
            problems.append(f"the {slot} slot carries {role}, which is not a "
                            "quantity")
    for slot in LABEL_SLOTS:
        role = roles.get(slot)
        if not role:
            continue
        if role in NEVER_DRAWN:
            problems.append(f"the {slot} slot carries {role}, which is never "
                            "drawn")
        elif not labelling(role):
            problems.append(f"the {slot} slot carries {role}, which does not "
                            "label a category")
    if roles.get("time") and roles["time"] != TIME:
        problems.append(f"the time slot carries {roles['time']}, not a period")

    # A line asserts that the space between two points is traversable. Over
    # unordered categories that is a false statement, and it is one of the
    # invalid examples §89 names.
    # SLOPE is deliberately not in this list. Its two ends are the two
    # PERIODS and its lines are the categories travelling between them, so a
    # slope chart of unordered sectors asserts nothing false — it is §86's
    # named answer for exactly that shape. Reading it as a line over
    # categories rejected the chart the brief maps the shape to.
    if chart in (LINE, STACKED_AREA, SMALL_MULTIPLES):
        ordered_axis = (roles.get("time") == TIME
                        or roles.get("category") in (ORDINAL_CATEGORY,
                                                     RISK_BAND))
        if not ordered_axis:
            axis = roles.get("category") or roles.get("time") or "nothing"
            problems.append(
                f"a line over {axis} asserts an order between categories that "
                "have none")

    # A Sankey without flow semantics is a picture of arrows nobody computed.
    if chart == SANKEY and not (roles.get("source") == FLOW_SOURCE
                                and roles.get("destination")
                                == FLOW_DESTINATION):
        problems.append("a Sankey needs a flow source and a flow destination")

    # A heatmap with one categorical axis is a bar chart drawn in colour,
    # which is strictly harder to read.
    if chart in (HEATMAP, MIGRATION_MATRIX):
        labelled = [s for s in LABEL_SLOTS if roles.get(s)]
        if len(labelled) < 2 and roles.get("time") != TIME:
            problems.append(
                f"{CHART_LABEL.get(chart, chart)} needs two categorical axes")

    # The third dimension must be independent. A bubble whose size restates
    # its own y-value shows one number twice and looks like three.
    if chart in (BUBBLE, RISK_LANDSCAPE):
        bound = [roles.get(s) for s in ("value", "second_value", "size")]
        if not all(bound) or inputs.measures < 3:
            problems.append(
                "a third dimension must be an independent measure, not a "
                "restatement of one already on an axis")
    if chart == SCATTER and not (roles.get("value")
                                 and roles.get("second_value")):
        problems.append("a scatter plot needs two measures")

    # A waterfall's steps must reconcile to a total; category bars do not.
    if chart == WATERFALL and roles.get("value") != DECOMPOSITION_COMPONENT:
        problems.append(
            "a waterfall's steps must be decomposition components that "
            "reconcile to the total")
    if chart in (HISTOGRAM, BOX_PLOT) \
            and roles.get("value") not in (DISTRIBUTION_VALUE, MEASURE):
        problems.append(
            f"{CHART_LABEL.get(chart, chart)} needs per-record values, not an "
            "aggregate")

    return (0.0 if problems else 1.0), problems


def compatible(chart: str, roles: dict[str, str],
               measures: int = 0) -> tuple[bool, list[str]]:
    """Whether a chart's slots carry roles it can assert. §85.

    Public because the Visual Critic asks the same question after the chart is
    built, and it must get the same answer. Two implementations of "is this
    axis valid" drift, and the one that drifts is always the one that runs
    last.
    """
    score_value, problems = _role_compatibility(
        chart, Inputs(roles=dict(roles), measures=measures))
    return bool(score_value), problems


def _decay(value: float, ceiling: float) -> float:
    """1.0 up to the ceiling, then falling away rather than cliff-edging.

    A gradual decline because 41 categories in a chart rated for 40 is not a
    different kind of chart from 39.
    """
    if ceiling <= 0:
        return 0.0
    if value <= ceiling:
        return 1.0
    return max(0.0, ceiling / float(value))


def score(chart: str, inputs: Inputs) -> Score:
    """§87's suitability for one candidate, with every factor recorded."""
    result = Score(chart=chart)
    compatibility, problems = _role_compatibility(chart, inputs)
    result.factors["semantic_role_compatibility"] = compatibility
    result.rejections.extend(problems)

    ceiling = CATEGORY_CEILING.get(chart, 20)
    result.factors["category_count"] = _decay(inputs.categories, ceiling)
    if result.factors["category_count"] < SOFT_FLOOR:
        result.rejections.append(
            f"{inputs.categories} categories in {CHART_LABEL.get(chart, chart)}"
            f", which reads to about {ceiling}")

    # Long labels under a vertical bar get rotated, and rotated labels are how
    # charts become unreadable. Horizontal bars do not have the problem.
    result.factors["label_length"] = 1.0
    if chart in VERTICAL_LABELS and inputs.longest_label > MAX_LABEL:
        result.factors["label_length"] = _decay(inputs.longest_label,
                                                MAX_LABEL)
        if result.factors["label_length"] < SOFT_FLOOR:
            result.rejections.append(
                f"labels up to {inputs.longest_label} characters do not fit "
                "under a vertical axis")

    if chart in (LINE, SMALL_MULTIPLES, STACKED_AREA, SLOPE):
        # Two points are not a trend. A line between them says one anyway.
        need = 2 if chart == SLOPE else 3
        result.factors["period_count"] = (
            1.0 if inputs.periods >= need else 0.0)
        if inputs.periods < need:
            result.rejections.append(
                f"{inputs.periods} periods cannot support "
                f"{CHART_LABEL.get(chart, chart)}")
    else:
        result.factors["period_count"] = 1.0

    # A table separates as many measures as it has columns, which is why it
    # is the fallback. Giving it the default ceiling of three rejected the one
    # candidate that must never be rejected, and left `select` falling back to
    # a shape it had just refused.
    series_ceiling = {SMALL_MULTIPLES: 12, LINE: 5, GROUPED_BAR: 4,
                      STACKED_BAR: 8, STACKED_AREA: 8,
                      TABLE: 10_000}.get(chart, 3)
    result.factors["measure_count"] = _decay(inputs.measures, series_ceiling)
    if result.factors["measure_count"] < SOFT_FLOOR:
        result.rejections.append(
            f"{inputs.measures} measures is more than "
            f"{CHART_LABEL.get(chart, chart)} can separate")

    result.factors["cardinality"] = _decay(inputs.cardinality, ceiling * 4)
    # The reason names the table as the answer, so it cannot be a reason to
    # reject one: a sparse result is exactly the case a table exists for.
    result.factors["missingness"] = (
        1.0 if chart == TABLE else max(0.0, 1.0 - inputs.missing_pct))
    if inputs.missing_pct > 0.2 and chart != TABLE:
        result.rejections.append(
            f"{inputs.missing_pct:.0%} of values are missing, and a chart "
            "cannot show a gap the way a table can")
    result.factors["overlap"] = max(0.0, 1.0 - inputs.overlap)

    # The one charting failure with its own literature.
    if inputs.needs_zero_baseline and not inputs.zero_baseline_available:
        result.factors["zero_baseline"] = 0.0
        result.rejections.append(
            "the value is encoded as a length and the axis cannot start at "
            "zero, which would exaggerate the difference")
    elif chart in LENGTH_ENCODED and not inputs.zero_baseline_available:
        result.factors["zero_baseline"] = 0.0
        result.rejections.append(
            f"{CHART_LABEL.get(chart, chart)} encodes value as length and "
            "needs a zero baseline")
    else:
        result.factors["zero_baseline"] = 1.0

    result.factors["accessibility"] = (
        1.0 if inputs.accessible_alternative or chart == TABLE else 0.3)
    if not inputs.accessible_alternative and chart != TABLE:
        result.rejections.append(
            "no accessible table or summary accompanies the chart")

    # Two decimals is the display contract. A chart cannot show four.
    result.factors["precision"] = (
        1.0 if inputs.precision_required <= 2 or chart == TABLE else 0.2)
    if inputs.precision_required > 2 and chart != TABLE:
        result.rejections.append(
            f"the answer needs {inputs.precision_required} decimals, which "
            "only a table can show")

    if inputs.wants_records and chart in PATTERN_ONLY:
        result.factors["pattern_versus_records"] = 0.0
        result.rejections.append(
            "the reader asked for records and this shape shows a pattern")
    elif inputs.wants_records and chart != TABLE:
        result.factors["pattern_versus_records"] = 0.5
    else:
        result.factors["pattern_versus_records"] = 1.0

    result.factors["device"] = (
        0.4 if inputs.narrow_device and chart in (
            HEATMAP, MIGRATION_MATRIX, SANKEY, SMALL_MULTIPLES, BUBBLE,
            RISK_LANDSCAPE) else 1.0)

    weighted = sum(result.factors[f] * WEIGHTS[f] for f in FACTORS)
    result.total = weighted / sum(WEIGHTS.values())

    if result.total < THRESHOLD:
        result.rejections.append(
            f"suitability {result.total:.2f} is below the {THRESHOLD} "
            "threshold")
    # A recorded rejection reason rejects. Anything softer would make §87's
    # "persist rejection reasons" mean "persist misgivings", and a candidate
    # shipped with a reason it should not have been used is worse than one
    # shipped with none.
    result.accepted = not result.rejections
    return result


@dataclass
class Selection:
    """The chosen chart, and every candidate that lost.

    §87: persist candidate scores AND rejection reasons. The losing scores
    are the part that makes this reviewable — anybody can ask why a
    horizontal bar was not used and get a number and a sentence.
    """

    shape: str = ""
    chosen: str = TABLE
    scores: list[Score] = field(default_factory=list)
    fell_back: bool = False

    @property
    def accepted(self) -> list[Score]:
        return [s for s in self.scores if s.accepted]

    @property
    def rejected(self) -> list[Score]:
        return [s for s in self.scores if not s.accepted]

    def reason(self) -> str:
        winner = next((s for s in self.scores if s.chart == self.chosen), None)
        label = CHART_LABEL.get(self.chosen, self.chosen)
        if self.fell_back:
            refused = "; ".join(
                f"{CHART_LABEL.get(s.chart, s.chart)} — {s.rejections[0]}"
                for s in self.rejected if s.rejections)
            return (f"Shown as {label}: no chart passed. {refused}."
                    if refused else f"Shown as {label}.")
        if winner is None:
            return f"Shown as {label}."
        return (f"Shown as {label} ({SHAPE_MEANS.get(self.shape, self.shape)} "
                f"maps to it, suitability {winner.total:.2f}).")

    def to_dict(self) -> dict[str, Any]:
        return {"version": GRAMMAR_VERSION, "shape": self.shape,
                "shape_means": SHAPE_MEANS.get(self.shape, ""),
                "chosen": self.chosen,
                "chosen_label": CHART_LABEL.get(self.chosen, self.chosen),
                "fell_back": self.fell_back,
                "scores": [s.to_dict() for s in self.scores],
                "accepted": [s.chart for s in self.accepted],
                "rejected": [s.chart for s in self.rejected],
                "reason": self.reason()}


def select(shape: str, inputs: Inputs) -> Selection:
    """§86's mapping, scored by §87, with the losers kept.

    The default is tried first and wins ties, so the mapping stays the
    explanation for most answers and the score only overrides it when the
    default genuinely does not read. A scoring function free to pick anything
    would make §86 decorative.
    """
    selection = Selection(shape=shape)
    ordered = candidates_for(shape)
    selection.scores = [score(chart, inputs) for chart in ordered]

    for candidate in selection.scores:
        if candidate.accepted:
            selection.chosen = candidate.chart
            break
    else:
        # §88's rule, applied one step early: when nothing passes, the table.
        selection.chosen = TABLE

    # "Fell back" means §86 mapped this shape to a chart and none of them
    # could be used — not merely that a table was shown, which is the right
    # answer for record-level output and no kind of failure there.
    selection.fell_back = (selection.chosen == TABLE
                           and default_for(shape) != TABLE)
    return selection


__all__ = ["BAR", "BOX_PLOT", "BUBBLE", "CATEGORY", "CATEGORY_CEILING",
           "CATEGORY_PERIOD_MEASURE", "CATEGORY_RANKING", "CHARTS",
           "CHART_LABEL", "CHANGE_DECOMPOSITION", "COMPOSITION_OVER_TIME",
           "CONCENTRATION_HIERARCHY", "DECOMPOSITION_COMPONENT",
           "DISTRIBUTION", "DISTRIBUTION_VALUE", "DUMBBELL", "ENTITY",
           "FACTORS", "FATAL", "FLOW_DESTINATION", "FLOW_SOURCE",
           "GEOGRAPHY", "GRAMMAR_VERSION", "GROUPED_BAR", "HEATMAP",
           "HISTOGRAM", "HORIZONTAL_BAR", "IDENTIFIER", "Inputs", "KPI",
           "LABELLING", "LENGTH_ENCODED", "LINE", "MANY_TIME_SERIES",
           "MAPPING", "MEASURE", "MIGRATION_GRID", "MIGRATION_MATRIX",
           "MIGRATION_PATHS", "NEVER_DRAWN", "ORDERED", "ORDINAL_CATEGORY",
           "PATTERN_ONLY", "PERCENTAGE", "PERCENTAGE_POINT", "PLOTTABLE",
           "RECORD_LEVEL", "RISK_BAND", "RISK_LANDSCAPE", "ROLES",
           "ROLE_MEANS", "SANKEY", "SCATTER", "SHAPES", "SHAPE_MEANS",
           "SINGLE_VALUE", "SLOPE", "SMALL_MULTIPLES", "STACKED_AREA",
           "STACKED_BAR", "TABLE", "THREE_MEASURE", "THRESHOLD", "TIME",
           "TIME_SERIES", "TECHNICAL_LINEAGE", "TREEMAP", "TWO_MEASURE",
           "TWO_PERIOD_CATEGORY", "LABEL_SLOTS", "MAX_LABEL", "SLOTS",
           "SOFT_FLOOR", "VALUE_SLOTS", "VERTICAL_LABELS", "WATERFALL",
           "WEIGHTS", "Score",
           "Selection", "candidates_for", "compatible", "default_for",
           "labelling",
           "plottable", "score", "select"]
