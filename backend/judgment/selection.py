"""
Interactive analytical selection: what a click on a chart MEANS. §90.

    "Chart selection must create structured working memory. … 'Ask about
     this' remains in the same Investigation. Trace the selection and
     resulting scope delta."

The failure this prevents
------------------------
A reader clicks the Contracting bar and types "why did this move?". Without
this module "this" is a pronoun with nothing behind it, and the question is
answered against the whole portfolio — fluently, with a number that is not the
one the reader was looking at. That is worse than an error, because both the
chart and the answer are on screen and they quietly disagree.

So a click produces a STRUCTURED selection: which entities, which category,
which period, which range, which measure, which series, which filters, from
which visualization, from which run. Nine fields, all of §90's, because a
selection that recorded only "Contracting" would lose the period the bar was
in and the measure its height encoded — and those are exactly what the next
question depends on.

Why it goes through the scope machinery rather than round it
--------------------------------------------------------------
A selection narrows the analytical scope in exactly the way a typed follow-up
does. Routing it through §102's ScopeFrame means the resulting Delta is
classified, shown and Traced by the same code that handles "just Contracting
then" — so the two paths cannot drift, and a click cannot quietly widen a
scope in a way a sentence would have been stopped from doing.

What a selection may not do
----------------------------
It may not leave the Investigation, and it may not reach outside the run it
came from. A click on a chart is a question about the figures in that chart;
a selection that could name an entity the run never returned would be a
filter invented at the browser, applied to data the reader was not looking at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.judgment import visual_grammar as vg
from backend.orchestration import scope as sc

SELECTION_VERSION = "1.0.0"

#: §90's fields, exactly. A selection missing any of them is refused rather
#: than half-applied: a click that recorded the entity and lost the period
#: produces a follow-up about the right borrower in the wrong quarter, which
#: reads as a data error and is not one.
FIELDS: tuple[str, ...] = (
    "selected_entities", "selected_category", "selected_period",
    "selected_range", "selected_metric", "selected_series",
    "selected_filters", "source_visualization", "source_run_id",
)

#: What a click means on each chart kind. Declared per chart because it
#: differs: a bar is one category, a heatmap cell is a category AND a period,
#: a scatter drag is a range of two measures.
MEANS: dict[str, str] = {
    vg.KPI: "the figure itself",
    vg.BAR: "one category",
    vg.HORIZONTAL_BAR: "one category",
    vg.GROUPED_BAR: "one category and one series",
    vg.STACKED_BAR: "one category and one component",
    vg.DUMBBELL: "one category across both periods",
    vg.SLOPE: "one category across both periods",
    vg.LINE: "one period, or one series across all periods",
    vg.SMALL_MULTIPLES: "one series",
    vg.STACKED_AREA: "one component at one period",
    vg.WATERFALL: "one contribution",
    vg.SANKEY: "one flow, from one state to another",
    vg.MIGRATION_MATRIX: "the entities in one opening/closing cell",
    vg.HISTOGRAM: "the records in one bin",
    vg.BOX_PLOT: "one group, or one outlier record",
    vg.SCATTER: "one entity, or a dragged region of two measures",
    vg.BUBBLE: "one entity",
    vg.RISK_LANDSCAPE: "one entity",
    vg.TREEMAP: "one tile, and descending into it",
    vg.HEATMAP: "one category at one period",
    vg.TABLE: "one row",
}


@dataclass
class Range:
    """A dragged region, in the units of the measure it was dragged over."""

    metric: str = ""
    low: float | None = None
    high: float | None = None

    @property
    def empty(self) -> bool:
        return self.low is None and self.high is None

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "low": self.low, "high": self.high}

    def line(self) -> str:
        if self.empty:
            return ""
        if self.low is not None and self.high is not None:
            return f"{self.metric} between {self.low} and {self.high}"
        if self.low is not None:
            return f"{self.metric} at or above {self.low}"
        return f"{self.metric} at or below {self.high}"


@dataclass
class Selection:
    """§90's structured working memory, from one interaction with a chart."""

    selected_entities: list[str] = field(default_factory=list)
    selected_category: str = ""
    selected_period: str = ""
    selected_range: Range = field(default_factory=Range)
    selected_metric: str = ""
    selected_series: str = ""
    selected_filters: list[dict[str, str]] = field(default_factory=list)
    source_visualization: str = ""
    source_run_id: str = ""

    @property
    def empty(self) -> bool:
        return not (self.selected_entities or self.selected_category
                    or self.selected_period or self.selected_metric
                    or self.selected_series or self.selected_filters
                    or not self.selected_range.empty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SELECTION_VERSION,
            "selected_entities": list(self.selected_entities),
            "selected_category": self.selected_category,
            "selected_period": self.selected_period,
            "selected_range": self.selected_range.to_dict(),
            "selected_metric": self.selected_metric,
            "selected_series": self.selected_series,
            "selected_filters": [dict(f) for f in self.selected_filters],
            "source_visualization": self.source_visualization,
            "source_run_id": self.source_run_id,
            "means": MEANS.get(self.source_visualization, ""),
            "line": self.line(),
        }

    def line(self) -> str:
        """What the reader selected, as the sentence the answer will carry.

        Written as a sentence because it appears above the follow-up answer.
        A key/value dump would be accurate and would not tell a credit officer
        which bar they clicked.
        """
        parts: list[str] = []
        if self.selected_entities:
            parts.append(
                self.selected_entities[0] if len(self.selected_entities) == 1
                else f"{len(self.selected_entities)} selected rows")
        if self.selected_category:
            parts.append(self.selected_category)
        if self.selected_series:
            parts.append(self.selected_series)
        if not self.selected_range.empty:
            parts.append(self.selected_range.line())
        if self.selected_period:
            parts.append(f"in {self.selected_period}")
        if self.selected_metric:
            parts.append(f"by {self.selected_metric}")
        if not parts:
            return ""
        source = MEANS.get(self.source_visualization, "the chart")
        return f"Selected {', '.join(parts)} — {source}."


class OutsideRun(Exception):
    """A selection naming something the run never returned.

    Raised rather than filtered, because the alternative is silently answering
    a different question: a click that names an entity the chart did not show
    is a filter invented at the browser and applied to data the reader was not
    looking at.
    """


@dataclass
class Source:
    """What the run actually returned, which is what a click may name."""

    run_id: str = ""
    chart: str = vg.TABLE
    entities: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    series: list[str] = field(default_factory=list)
    entity_key: str = ""


def capture(source: Source, **chosen: Any) -> Selection:
    """One interaction, validated against what the run returned.

    Every named value must appear in the source. §90's selection is a
    reference INTO a result, not a filter alongside it, and a reference to
    something that is not there is a bug in the caller rather than an empty
    result for the reader.
    """
    selection = Selection(source_visualization=source.chart or vg.TABLE,
                          source_run_id=source.run_id)

    entities = [str(e) for e in (chosen.get("entities") or [])]
    unknown = [e for e in entities if source.entities and e
               not in source.entities]
    if unknown:
        raise OutsideRun(
            f"{unknown[0]!r} was not in the result this chart was drawn from")
    selection.selected_entities = entities

    for name, available, target in (
            ("category", source.categories, "selected_category"),
            ("period", source.periods, "selected_period"),
            ("metric", source.metrics, "selected_metric"),
            ("series", source.series, "selected_series")):
        value = chosen.get(name)
        if value is None or value == "":
            continue
        if available and str(value) not in available:
            raise OutsideRun(
                f"{value!r} is not a {name} this chart shows")
        setattr(selection, target, str(value))

    low, high = chosen.get("low"), chosen.get("high")
    if low is not None or high is not None:
        metric = selection.selected_metric or (
            source.metrics[0] if source.metrics else "")
        selection.selected_range = Range(
            metric=metric,
            low=None if low is None else float(low),
            high=None if high is None else float(high))

    # The filters a selection implies, in the same shape a typed follow-up
    # produces, so the scope machinery cannot tell the two apart.
    filters: list[dict[str, str]] = []
    if selection.selected_category:
        filters.append({"field": chosen.get("category_field") or "category",
                        "value": selection.selected_category})
    if selection.selected_series:
        filters.append({"field": chosen.get("series_field") or "series",
                        "value": selection.selected_series})
    selection.selected_filters = filters
    return selection


def narrow(before: sc.ScopeFrame, selection: Selection,
           source: Source | None = None) -> sc.ScopeFrame:
    """The scope a selection produces.

    Deliberately builds a real ScopeFrame rather than a parallel structure, so
    the Delta a click produces is classified, shown and Traced by exactly the
    code that handles "just Contracting then". Two paths to the same scope
    change would drift, and the one that drifted would be the one nobody
    typed.
    """
    after = sc.ScopeFrame(
        population=before.population, entity_key=before.entity_key,
        entity_ids=list(before.entity_ids), datasets=list(before.datasets),
        domains=list(before.domains), filters=list(before.filters),
        metrics=list(before.metrics), dimension=before.dimension,
        period=before.period, opening=before.opening, closing=before.closing,
        grain=before.grain, top_n=before.top_n,
        presentation=before.presentation)

    if selection.selected_entities:
        after.entity_ids = list(selection.selected_entities)
        after.entity_key = (source.entity_key if source and source.entity_key
                            else before.entity_key)
        after.population = selection.line() or after.population
        after.top_n = 0
    for applied in selection.selected_filters:
        if applied not in after.filters:
            after.filters = [*after.filters, applied]
    if selection.selected_period:
        # A selected period REPLACES the window rather than adding to it: the
        # reader clicked one quarter, and carrying the old opening date
        # forward would answer about a span they did not select.
        after.period = selection.selected_period
        after.opening = ""
        after.closing = ""
    if selection.selected_metric:
        after.metrics = [selection.selected_metric]
    return after


def delta(before: sc.ScopeFrame, selection: Selection,
          source: Source | None = None) -> sc.Delta:
    """The classified scope change a selection causes. §90: Trace it."""
    after = narrow(before, selection, source)
    change = sc.classify(before, after)
    if selection.line():
        change.changes = [selection.line(), *change.changes]
    return change


@dataclass
class Ask:
    """"Ask about this" — a follow-up question bound to a selection.

    Carries the investigation id because §90 requires the follow-up to stay
    in the same Investigation. A selection that opened a new one would lose
    the conversation the reader was having and the scope they had built.
    """

    question: str = ""
    investigation_id: str = ""
    selection: Selection = field(default_factory=Selection)
    scope_delta: sc.Delta | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SELECTION_VERSION,
            "question": self.question,
            "investigation_id": self.investigation_id,
            "same_investigation": bool(self.investigation_id),
            "selection": self.selection.to_dict(),
            "scope_delta": (self.scope_delta.to_dict() if self.scope_delta
                            else None),
        }

    def trace_node(self) -> dict[str, Any]:
        """§90: trace the selection AND the resulting scope delta.

        One node carrying both, because they are one event: a reader who sees
        that the scope narrowed and cannot see what was clicked has been told
        that something happened.
        """
        return {
            "type": "interactive_selection",
            "version": SELECTION_VERSION,
            "title": "Selection from a chart",
            "summary": self.selection.line(),
            "source_visualization": self.selection.source_visualization,
            "source_run_id": self.selection.source_run_id,
            "investigation_id": self.investigation_id,
            "selection": self.selection.to_dict(),
            "scope_delta": (self.scope_delta.to_dict() if self.scope_delta
                            else None),
        }


def ask(question: str, investigation_id: str, selection: Selection,
        before: sc.ScopeFrame, source: Source | None = None) -> Ask:
    """"Ask about this", staying in the Investigation it came from."""
    if not investigation_id:
        raise ValueError(
            "a selection follow-up must name the Investigation it belongs to; "
            "§90 requires it to stay in the same one")
    return Ask(question=question, investigation_id=investigation_id,
               selection=selection,
               scope_delta=delta(before, selection, source))


__all__ = ["Ask", "FIELDS", "MEANS", "OutsideRun", "Range", "SELECTION_VERSION",
           "Selection", "Source", "ask", "capture", "delta", "narrow"]
