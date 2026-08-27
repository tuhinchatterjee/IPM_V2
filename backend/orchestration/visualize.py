"""
Which picture makes this result easier to read, and when no picture does.

Two failures, opposite directions
---------------------------------
**A table where a chart belongs.** "For each rating grade, show average ECL
coverage, average leverage and average DSCR" is ten rows and three measures —
a shape whose whole point is the profile across grades, invisible in a grid of
thirty numbers and obvious in one small-multiple.

**A chart where a table belongs.** Forty columns of screening output drawn as
a bar chart is decoration. A credit officer reading a screen needs the values.

So the decision is made from the SHAPE of the result and from what the user
asked for, never from the values in it. Nothing here reads a number.

Always both
-----------
Every answer carries a table and, where one helps, a chart, with a toggle
between them. A chart that cannot be checked against its own figures is a chart
nobody in a bank is allowed to use.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

TABLE = "table"
KPI = "kpi"
BAR = "bar"
HORIZONTAL_BAR = "bar_horizontal"
GROUPED_BAR = "bar_grouped"
LINE = "line"
AREA = "area"
SLOPE = "slope"
WATERFALL = "waterfall"
HEATMAP = "heatmap"
HISTOGRAM = "histogram"
SCATTER = "scatter"
DOT = "dot"

#: What each shape is called on screen. A reader asked for "a graph"; telling
#: them they were given a `bar_horizontal` is the product speaking its own
#: enum out loud.
LABELS: dict[str, str] = {
    TABLE: "a table", KPI: "a headline figure", BAR: "a bar chart",
    HORIZONTAL_BAR: "a horizontal bar chart",
    GROUPED_BAR: "a grouped bar chart", LINE: "a line chart",
    AREA: "an area chart", SLOPE: "a slope chart",
    WATERFALL: "a waterfall chart", HEATMAP: "a heatmap",
    HISTOGRAM: "a histogram", SCATTER: "a scatter plot", DOT: "a dot plot",
}

#: Beyond this many categories a bar chart is a picket fence. The table is the
#: honest primary and the chart becomes the alternative.
MAX_CATEGORIES = 30

#: A ranking of named counterparties reads horizontally: "Al Rajhi Contracting
#: 4471" does not fit under a vertical bar and rotating it to 45 degrees is how
#: charts become unreadable.
HORIZONTAL_ABOVE = 6

#: More measures than this beside one dimension and small multiples stop being
#: small.
MAX_SERIES = 4


@dataclass
class Visual:
    """What to draw, why, and what else the reader may switch to."""

    chart: str = TABLE
    x: str = ""
    y: list[str] = field(default_factory=list)
    series: str = ""
    #: Why this shape, in one sentence a reader can disagree with.
    reason: str = ""
    #: True when the chart is the better primary and the table the alternative.
    chart_first: bool = False
    #: Other shapes that would also work here, offered in the picker.
    alternatives: list[str] = field(default_factory=list)
    #: Where the choice came from: "shape" or "asked".
    source: str = "shape"

    def label(self) -> str:
        """The chart kind in the words a person would use for it."""
        return LABELS.get(self.chart, self.chart.replace("_", " "))

    def to_dict(self) -> dict[str, Any]:
        return {"chart": self.chart, "label": self.label(),
                "x": self.x, "y": list(self.y),
                "series": self.series, "reason": self.reason,
                "chart_first": self.chart_first,
                "alternatives": list(self.alternatives),
                "source": self.source,
                # The toggle is not conditional. A chart without its figures is
                # not something a bank may act on.
                "toggle": [TABLE, self.chart] if self.chart != TABLE else [TABLE]}


# ---------------------------------------------------------------------------
# Reading the shape
# ---------------------------------------------------------------------------


@dataclass
class Shape:
    """What a result IS, in the terms the choice is made in."""

    rows: int = 0
    subject: str = ""            # the column each row is about
    subject_is_period: bool = False
    subject_is_entity: bool = False
    measures: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    opening: str = ""
    closing: str = ""
    columns: int = 0
    from_to: bool = False        # a transition matrix
    buckets: bool = False        # a distribution


def read_shape(columns: list[dict[str, Any]], rows: list[dict[str, Any]]) -> Shape:
    """The result's shape, from the presentation schema rather than the frame.

    The schema already knows what each column IS — a subject, a measure, a
    derived change, lineage — because the ontology told it. Re-deriving that
    from pandas dtypes is how a rating grade stored as an integer became a
    measure and got drawn as a bar.
    """
    from backend.orchestration import presentation as pr

    visible = [c for c in (columns or []) if not c.get("hidden")]
    shape = Shape(rows=len(rows or []), columns=len(visible))

    names = {str(c.get("name") or "").lower() for c in visible}
    shape.from_to = {"from_state", "to_state"} <= names
    shape.buckets = "bucket" in names

    for column in visible:
        name = str(column.get("name") or "")
        lowered = name.lower()
        semantic = str(column.get("semantic") or "")
        rank = int(column.get("rank") or pr.RANK_CONTEXT)

        if semantic == pr.PERIOD and not shape.subject:
            shape.subject, shape.subject_is_period = name, True
            continue
        if rank <= pr.RANK_SUBJECT and not shape.subject:
            shape.subject = name
            # An identity is a counterparty, not a category. A sector is a
            # dimension the plan grouped by and reads perfectly well on a
            # vertical axis; "Al Rajhi Contracting 4471" does not.
            shape.subject_is_entity = semantic == pr.IDENTITY
            continue
        if semantic in (pr.MONEY, pr.PERCENT, pr.RATIO, pr.COUNT, pr.DAYS):
            if rank == pr.RANK_DERIVED:
                shape.changes.append(name)
            else:
                shape.measures.append(name)
            if lowered.startswith("opening_"):
                shape.opening = name
            elif lowered.startswith("closing_"):
                shape.closing = name

    if not shape.subject:
        for column in visible:
            if str(column.get("semantic") or "") in ("identity", "text"):
                shape.subject = str(column.get("name") or "")
                shape.subject_is_entity = True
                break
    return shape


# ---------------------------------------------------------------------------
# Choosing
# ---------------------------------------------------------------------------


def choose(columns: list[dict[str, Any]], rows: list[dict[str, Any]], *,
           requested: str = "") -> Visual:
    """The shape to draw this in, or the table when nothing clarifies it.

    `requested` is what the user asked for — "show this as a graph", "use a
    table instead" — and it wins over the shape rule, because a person looking
    at their own result knows what they want to see. It cannot invent a chart
    the result has no axes for; asking for a line chart of a single scalar
    returns the KPI and says why.
    """
    try:
        return _choose(columns, rows, requested=requested)
    except Exception as e:  # noqa: BLE001 - a picture must never lose an answer
        logger.warning("Could not choose a visualisation: %s", e)
        return Visual(reason="the result is shown as a table")


def _choose(columns: list[dict[str, Any]], rows: list[dict[str, Any]], *,
            requested: str) -> Visual:
    shape = read_shape(columns, rows)

    if requested == TABLE:
        return Visual(chart=TABLE, source="asked",
                      reason="the table was asked for")

    chosen = _by_shape(shape)
    if requested == "chart":
        if chosen.chart == TABLE:
            # Asked for a chart on a shape that has none. Say so rather than
            # drawing something meaningless and calling it an answer.
            fallback = _forced(shape)
            if fallback is None:
                return Visual(
                    chart=TABLE, source="asked",
                    reason=("this result has no axis a chart could use — "
                            "it is shown as a table"))
            fallback.source = "asked"
            fallback.chart_first = True
            return fallback
        chosen.source = "asked"
        chosen.chart_first = True
    return chosen


def _by_shape(shape: Shape) -> Visual:
    if not shape.rows:
        return Visual(reason="there are no rows to draw")

    if shape.from_to:
        return Visual(chart=HEATMAP, x="to_state", y=["value"], series="from_state",
                      chart_first=True, alternatives=[TABLE],
                      reason="a from/to transition reads as a matrix")

    if shape.buckets:
        return Visual(chart=HISTOGRAM, x="bucket", y=["count"], chart_first=True,
                      alternatives=[TABLE],
                      reason="a distribution across ordered buckets")

    if shape.rows == 1 and shape.measures and not shape.subject_is_period:
        return Visual(chart=KPI, y=shape.measures[:MAX_SERIES], chart_first=True,
                      alternatives=[TABLE],
                      reason="one row of measures reads as figures, not bars")

    if not shape.subject or not (shape.measures or shape.changes):
        return Visual(reason="no dimension and measure to plot against each other")

    if shape.subject_is_period:
        return Visual(chart=LINE, x=shape.subject,
                      y=(shape.measures or shape.changes)[:MAX_SERIES],
                      chart_first=True, alternatives=[AREA, BAR, TABLE],
                      reason="a measure over an ordered period axis")

    if shape.opening and shape.closing:
        return Visual(chart=SLOPE, x=shape.subject,
                      y=[shape.opening, shape.closing], chart_first=True,
                      alternatives=[WATERFALL, GROUPED_BAR, TABLE],
                      reason="an opening and a closing position per row")

    if shape.rows > MAX_CATEGORIES:
        return Visual(
            chart=HORIZONTAL_BAR, x=shape.subject,
            y=(shape.measures or shape.changes)[:1],
            alternatives=[TABLE],
            reason=(f"{shape.rows} categories is past what a chart separates — "
                    "the table is the primary and the chart the overview"))

    measures = (shape.measures or shape.changes)[:MAX_SERIES]
    if len(measures) > 1:
        return Visual(chart=GROUPED_BAR, x=shape.subject, y=measures,
                      chart_first=True, alternatives=[DOT, TABLE],
                      reason=("several measures across one dimension — the "
                              "profile is the point"))

    horizontal = shape.subject_is_entity or shape.rows > HORIZONTAL_ABOVE
    return Visual(chart=HORIZONTAL_BAR if horizontal else BAR,
                  x=shape.subject, y=measures, chart_first=True,
                  alternatives=[TABLE],
                  reason=("a ranking of named rows reads horizontally"
                          if horizontal else
                          "one measure across a small number of categories"))


def _forced(shape: Shape) -> Visual | None:
    """A chart for a result whose shape did not ask for one.

    Only where there are real axes. "Show this as a graph" over a catalogue
    listing has no answer, and inventing one is how a product loses an argument
    with the person using it.
    """
    measures = shape.measures or shape.changes
    if shape.subject and measures:
        return Visual(chart=HORIZONTAL_BAR, x=shape.subject, y=measures[:1],
                      alternatives=[TABLE],
                      reason="drawn as asked, from the one dimension and "
                             "measure this result carries")
    if len(measures) >= 2:
        return Visual(chart=SCATTER, x=measures[0], y=[measures[1]],
                      alternatives=[TABLE],
                      reason="drawn as asked, as two measures against each other")
    return None


__all__ = ["AREA", "BAR", "DOT", "GROUPED_BAR", "HEATMAP", "HISTOGRAM",
           "HORIZONTAL_ABOVE", "HORIZONTAL_BAR", "KPI", "LINE", "MAX_CATEGORIES",
           "MAX_SERIES", "SCATTER", "SLOPE", "TABLE", "WATERFALL", "Shape",
           "Visual", "choose", "read_shape"]
