"""A Lens that remembers what it said. §18–§24.

The distinction everything here is built on
--------------------------------------------
Two timestamps, never conflated:

    refreshed_at      2026-09-09 08:30    when it was CALCULATED
    reporting_period  Q2 2026             which BUSINESS PERIOD it describes

Opening the same Lens twice on a Wednesday morning produces two refreshes with
one reporting period. A movement between them is a restatement of the same
quarter, or a definition change, or nothing at all — and it is emphatically not
the book moving. A movement between two different reporting periods is the book
moving. §22 asks for both histories and never for them mixed, and a schema with
one timestamp would have made mixing them the default.

Why a comparison is not "the previous row"
-------------------------------------------
§24. The refresh before this one may have run under a different filter, on a
different definition of one of its metrics, or over a period whose meaning has
changed. Comparing against it and calling the difference risk movement is the
most confidently wrong thing this feature could do, so `comparable()` looks for
the most recent refresh that matches on filter context and reporting-period
semantics, and reports what it had to relax when nothing matches exactly.

Why the classification is a SET
--------------------------------
§21 lists six states and a refresh is routinely several of them. The quarter
advanced AND a formula changed AND the filter is the same: reporting that as
one label forces a choice about which mattered, and the choice would be wrong
about as often as not. So a refresh carries every code that applies, and the
interpretation is told all of them.

What "source data changed" means, and why values cannot answer it
------------------------------------------------------------------
Two refreshes with identical values over changed source data is a different
fact from two refreshes with identical values over identical source data. The
first says a restatement did not move the number; the second says nothing
happened. No amount of comparing values distinguishes them, which is why
`data_versions` is recorded per dataset per refresh and why §21's first two
classifications are separate.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

REFRESH_VERSION = "3.0.0"

# ---------------------------------------------------------------------------
# §19: one pipeline, three doors
# ---------------------------------------------------------------------------

TRIGGER_OPENED = "lens_opened"
TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"
TRIGGERS = (TRIGGER_OPENED, TRIGGER_MANUAL, TRIGGER_SCHEDULED)

TRIGGER_LABELS = {
    TRIGGER_OPENED: "Lens opened",
    TRIGGER_MANUAL: "Refreshed by hand",
    TRIGGER_SCHEDULED: "Scheduled refresh",
}

# ---------------------------------------------------------------------------
# §21: what kind of refresh this was
# ---------------------------------------------------------------------------

NO_SOURCE_CHANGE = "no_source_change"
SOURCE_CHANGED_VALUE_UNCHANGED = "source_changed_value_unchanged"
SOURCE_AND_VALUE_CHANGED = "source_and_value_changed"
DEFINITION_CHANGED = "definition_changed"
FILTER_CHANGED = "filter_changed"
PERIOD_ADVANCED = "reporting_period_advanced"
BASELINE = "baseline"
STRUCTURE_CHANGED = "lens_structure_changed"

CLASSIFICATIONS = (BASELINE, NO_SOURCE_CHANGE, SOURCE_CHANGED_VALUE_UNCHANGED,
                   SOURCE_AND_VALUE_CHANGED, DEFINITION_CHANGED,
                   FILTER_CHANGED, PERIOD_ADVANCED, STRUCTURE_CHANGED)

CLASSIFICATION_LABELS = {
    BASELINE: "Baseline refresh",
    NO_SOURCE_CHANGE: "No source change, no value change",
    SOURCE_CHANGED_VALUE_UNCHANGED: "Source data changed, values unchanged",
    SOURCE_AND_VALUE_CHANGED: "Source data changed, values changed",
    DEFINITION_CHANGED: "A metric definition changed",
    FILTER_CHANGED: "Filter context changed",
    PERIOD_ADVANCED: "Reporting period advanced",
    STRUCTURE_CHANGED: "The Lens itself changed",
}

CLASSIFICATION_MEANING = {
    BASELINE: ("This is the first comparable refresh of this Lens, so there "
               "is nothing to compare it with yet."),
    NO_SOURCE_CHANGE: ("Neither the source data nor any value moved since the "
                       "previous comparable refresh."),
    SOURCE_CHANGED_VALUE_UNCHANGED: (
        "The underlying data was republished and the figures came out the "
        "same. That is a restatement that did not move the book, which is a "
        "different fact from nothing having happened."),
    SOURCE_AND_VALUE_CHANGED: (
        "The underlying data changed and figures moved with it."),
    DEFINITION_CHANGED: (
        "At least one metric is calculated differently from how it was at the "
        "previous refresh, so part of any movement is the definition rather "
        "than the book."),
    FILTER_CHANGED: (
        "This refresh covers a different population from the previous one. "
        "Headline figures are not comparable and are not presented as "
        "movement."),
    PERIOD_ADVANCED: (
        "This refresh reports a later business period than the previous one, "
        "so movement here is the book moving."),
    STRUCTURE_CHANGED: (
        "Metrics or charts were added to or removed from this Lens between "
        "the two refreshes."),
}

#: Below this, a change is noise. A relative threshold, because "0.01"
#: means something different on a ratio and on an exposure in billions.
MATERIAL_RELATIVE = 0.005
#: …and an absolute floor, so a metric that moved from 0.0001 to 0.0002 is not
#: reported as having doubled.
MATERIAL_ABSOLUTE = 1e-9

#: How many refreshes back a history strip goes. §45: bounded lookback.
HISTORY_LIMIT = 12


def _digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# What a refresh is, before it is stored
# ---------------------------------------------------------------------------


@dataclass
class PanelSnapshot:
    """One tile's figure at one refresh."""

    panel_key: str
    metric_id: str = ""
    kind: str = "metric"
    title: str = ""
    value: float | None = None
    comparison_value: float | None = None
    unit: str = "number"
    decimals: int = 2
    grain: str = ""
    reporting_period: str = ""
    metric_definition_version: str = ""
    definition_hash: str = ""
    coverage: dict[str, Any] = field(default_factory=dict)
    domains: list[str] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    query_version: str = ""
    data_version: str = ""
    status: str = "succeeded"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "panel_key": self.panel_key, "metric_id": self.metric_id,
            "kind": self.kind, "title": self.title, "value": self.value,
            "comparison_value": self.comparison_value, "unit": self.unit,
            "decimals": self.decimals, "grain": self.grain,
            "reporting_period": self.reporting_period,
            "metric_definition_version": self.metric_definition_version,
            "definition_hash": self.definition_hash,
            "coverage": dict(self.coverage), "domains": list(self.domains),
            "series": list(self.series), "query_version": self.query_version,
            "data_version": self.data_version, "status": self.status,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass
class Refresh:
    """One execution of a Lens, as it is held in memory."""

    id: int | None = None
    lens_id: int = 0
    refreshed_at: datetime | None = None
    reporting_period: str = ""
    filter_hash: str = ""
    lens_definition_version: int = 1
    data_versions: dict[str, str] = field(default_factory=dict)
    trigger: str = TRIGGER_OPENED
    status: str = "succeeded"
    classification: list[str] = field(default_factory=list)
    compared_with_id: int | None = None
    interpretation: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    budget: dict[str, Any] = field(default_factory=dict)
    triggered_by: int | None = None
    panels: list[PanelSnapshot] = field(default_factory=list)

    @property
    def baseline(self) -> bool:
        return self.compared_with_id is None

    def panel(self, panel_key: str) -> PanelSnapshot | None:
        for snapshot in self.panels:
            if snapshot.panel_key == panel_key:
                return snapshot
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "lens_id": self.lens_id,
            "refreshed_at": (self.refreshed_at.isoformat()
                             if self.refreshed_at else ""),
            "reporting_period": self.reporting_period,
            "filter_hash": self.filter_hash,
            "lens_definition_version": self.lens_definition_version,
            "data_versions": dict(self.data_versions),
            "trigger": self.trigger,
            "trigger_label": TRIGGER_LABELS.get(self.trigger, self.trigger),
            "status": self.status,
            "classification": list(self.classification),
            "classification_labels": [
                CLASSIFICATION_LABELS.get(c, c) for c in self.classification],
            "compared_with_id": self.compared_with_id,
            "baseline": self.baseline,
            "interpretation": dict(self.interpretation),
            "duration_ms": self.duration_ms,
            "budget": dict(self.budget),
            "panels": [p.to_dict() for p in self.panels],
        }


# ---------------------------------------------------------------------------
# Building a refresh out of a rendered Lens
# ---------------------------------------------------------------------------


def filter_hash(scope: dict[str, Any] | None,
                period: str | None = None) -> str:
    """A digest of the population this refresh covered.

    Deliberately NOT including the period: the period is stored beside this,
    and folding it in would make every quarter a different filter context and
    every comparison a baseline. What goes in is what narrows the book —
    portfolio, domains, and any filters the Lens carries.
    """
    scope = dict(scope or {})
    return _digest({
        "portfolio": scope.get("portfolio", ""),
        "domains": sorted(scope.get("domains") or []),
        "filters": scope.get("filters") or {},
        "visibility": scope.get("visibility", ""),
    })


def panel_key(index: int, panel: dict[str, Any]) -> str:
    """A stable identity for one tile across refreshes.

    Position AND what it draws. A Lens may show one metric twice — a figure
    and a chart of it — so the metric id alone is not an identity; and a tile
    that moved when somebody rearranged the Lens is the same tile, so position
    alone is not one either. Together they are stable through the ordinary
    edits and change when the tile genuinely becomes a different tile.
    """
    kind = str(panel.get("kind") or "metric")
    what = str(panel.get("metric_id") or panel.get("analysis_id") or "")
    dimension = str((panel.get("params") or {}).get("dimension") or "")
    return f"{index:02d}:{kind}:{what}" + (f":{dimension}" if dimension else "")


def _definition_hash(panel: dict[str, Any]) -> str:
    """A digest of HOW this tile is calculated, not of what it produced.

    §39's mechanism. A metric whose formula was edited without its version
    being bumped still changes this, so "the definition changed between these
    two refreshes" is answerable from the stored snapshots rather than only
    from a version somebody remembered to increment.
    """
    metric = panel.get("metric") or {}
    return _digest({
        "formula": metric.get("formula_tree"),
        "composite": metric.get("composite"),
        "scope": metric.get("filters"),
        "unit": metric.get("unit"),
        "params": panel.get("params") or {},
    })


def _series_of(panel: dict[str, Any]) -> list[dict[str, Any]]:
    points = panel.get("points") or []
    return [{"label": str(p.get("label", "")), "value": p.get("value")}
            for p in points if isinstance(p, dict)]


def _data_versions(datasets: list[str]) -> dict[str, str]:
    from backend.data_access.catalog import get_catalog

    out: dict[str, str] = {}
    for dataset in dict.fromkeys(datasets):
        if not dataset:
            continue
        try:
            spec = get_catalog().dataset(dataset)
            out[dataset] = str(spec.version)
        except Exception:  # noqa: BLE001 - unknown version is itself a fact
            out[dataset] = "unknown"
    return out


def _row_versions(datasets: list[str], period: str) -> dict[str, str]:
    """A digest of what each dataset actually CONTAINS for this period.

    The catalogue's version number changes when a steward republishes a
    definition. It does not change when the same dataset is reloaded with
    restated figures, which is exactly the case §21's first two
    classifications have to tell apart — so the row count and the period list
    are folded in. Cheap: both are metadata reads DuckDB answers from the
    Parquet footer, not scans.
    """
    from backend.data_access import get_data_source

    source = get_data_source()
    out: dict[str, str] = {}
    for dataset in dict.fromkeys(datasets):
        if not dataset:
            continue
        try:
            rows = source.row_count(dataset, period or None)
            periods = source.periods(dataset)
            out[dataset] = _digest({"rows": rows, "periods": periods})
        except Exception:  # noqa: BLE001 - reported as unknown, not fatal
            out[dataset] = "unknown"
    return out


def capture(lens: dict[str, Any], rendered: dict[str, Any], *,
            trigger: str = TRIGGER_OPENED, user_id: int | None = None,
            duration_ms: int = 0) -> Refresh:
    """A rendered Lens, as a refresh ready to be stored.

    Pure: takes the render nothing else has touched and returns the snapshot
    it implies. Storing is `record`, comparing is `compare`, and keeping them
    apart is what lets every one of them be tested without a database.
    """
    scope = rendered.get("scope") or {}
    period = str(rendered.get("period") or scope.get("default_period") or "")

    panels: list[PanelSnapshot] = []
    datasets: list[str] = []
    for index, panel in enumerate(rendered.get("panels") or []):
        metric = panel.get("metric") or {}
        panel_datasets = list(metric.get("datasets") or [])
        datasets.extend(panel_datasets)
        status = str(panel.get("status") or "succeeded")
        snapshot = PanelSnapshot(
            panel_key=panel_key(index, panel),
            metric_id=str(panel.get("metric_id") or ""),
            kind=str(panel.get("kind") or "metric"),
            title=str(panel.get("title") or metric.get("name") or ""),
            value=_number(panel.get("value")),
            comparison_value=_number(panel.get("comparison_value")),
            unit=str(panel.get("unit") or metric.get("unit") or "number"),
            decimals=int(panel.get("decimals") or metric.get("decimals") or 2),
            grain=str(metric.get("grain") or ""),
            # `period_used` is the period the tile ACTUALLY read, resolved
            # by the engine. `period` is the one the tile PINS itself to, and
            # is empty on every tile that follows the Lens — reading it here
            # left every snapshot with no reporting period, which made every
            # refresh compare as "same period" whatever quarter the book had
            # moved to.
            reporting_period=str(panel.get("period_used")
                                 or panel.get("period") or period),
            metric_definition_version=str(metric.get("version") or ""),
            definition_hash=_definition_hash(panel),
            coverage={
                "rows_considered": ((panel.get("calculation") or {})
                                    .get("rows_considered") or 0),
                "datasets": panel_datasets,
                "available": bool(panel.get("value") is not None),
            },
            domains=list(metric.get("lens_domains") or []),
            series=_series_of(panel),
            query_version=str(metric.get("version") or ""),
            status=("succeeded" if status == "succeeded"
                    else ("unavailable" if status == "unavailable"
                          else "failed")),
            diagnostics={"error": str(panel.get("error") or ""),
                         "unavailable": str(panel.get("unavailable") or "")},
        )
        panels.append(snapshot)

    # §18B. A Lens that pins no period still REPORTS one: each tile resolved
    # its own, and the period this refresh describes is the one most of them
    # landed on. Leaving it empty was not neutral — it made every refresh
    # compare as "same reporting period" whatever quarter the book had moved
    # to, and printed "the reporting period is unchanged at ." on screen.
    if not period:
        period = _majority_period(panels)
    for snapshot in panels:
        if not snapshot.reporting_period:
            snapshot.reporting_period = period

    versions = _data_versions(datasets)
    rows = _row_versions(datasets, period)
    for dataset, digest in rows.items():
        versions[dataset] = f"{versions.get(dataset, 'unknown')}/{digest}"

    return Refresh(
        lens_id=int(lens.get("id") or 0),
        refreshed_at=datetime.now().astimezone(),
        reporting_period=period,
        filter_hash=filter_hash(scope),
        lens_definition_version=int(lens.get("version") or 1),
        data_versions=versions,
        trigger=trigger if trigger in TRIGGERS else TRIGGER_OPENED,
        status=("partial" if rendered.get("failed") else "succeeded"),
        triggered_by=user_id,
        duration_ms=duration_ms,
        panels=panels,
    )


def _majority_period(panels: list[PanelSnapshot]) -> str:
    """The period most of this Lens's tiles actually read.

    A Lens whose tiles read different periods — one pinned to a quarter, the
    rest following the latest — has no single reporting period, and the
    majority is the honest answer rather than the first tile's. Ties break on
    the latest, because a Lens straddling two quarters is reporting the newer
    one with some history beside it.
    """
    counts: dict[str, int] = {}
    for snapshot in panels:
        if snapshot.status != "succeeded" or not snapshot.reporting_period:
            continue
        counts[snapshot.reporting_period] = (
            counts.get(snapshot.reporting_period, 0) + 1)
    if not counts:
        return ""
    from backend.metrics.service import _period_order

    return max(counts, key=lambda p: (counts[p], _period_order(p)))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


# ---------------------------------------------------------------------------
# §24: which earlier refresh this one may be compared with
# ---------------------------------------------------------------------------


@dataclass
class Comparison:
    """The earlier refresh chosen, and what had to be relaxed to choose it."""

    refresh: Refresh | None = None
    exact: bool = False
    relaxed: list[str] = field(default_factory=list)
    why_none: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "refresh": self.refresh.to_dict() if self.refresh else None,
            "exact": self.exact, "relaxed": list(self.relaxed),
            "why_none": self.why_none,
        }


def comparable(current: Refresh, history: list[Refresh]) -> Comparison:
    """The most recent refresh this one may honestly be compared with.

    Preference order, and each step down is RECORDED rather than silently
    taken:

    1. Same filter context, same reporting period, same Lens definition
       version. Two measurements of the same thing.
    2. Same filter context, same reporting period. The Lens changed shape;
       the population did not.
    3. Same filter context, earlier reporting period. The book moved, which
       is the comparison a quarterly Lens usually wants.

    A refresh under a DIFFERENT filter context is never chosen. §40: a Lens
    filtered to Construction is not the corporate book with a smaller number
    on it, and comparing the two would present a filter change as a collapse
    in exposure.
    """
    older = [r for r in history
             if r.id is not None and (current.id is None or r.id != current.id)]
    older.sort(key=lambda r: (r.refreshed_at or datetime.min, r.id or 0),
               reverse=True)

    same_filter = [r for r in older if r.filter_hash == current.filter_hash]
    if not same_filter:
        if older:
            return Comparison(
                why_none=(
                    "Every earlier refresh of this Lens ran under a different "
                    "filter context, so none of them measures the same "
                    "population as this one. Nothing is compared, because a "
                    "difference between two populations is not a movement."))
        return Comparison(
            why_none="This is the first recorded refresh of this Lens.")

    exact = [r for r in same_filter
             if r.reporting_period == current.reporting_period
             and r.lens_definition_version == current.lens_definition_version]
    if exact:
        return Comparison(refresh=exact[0], exact=True)

    same_period = [r for r in same_filter
                   if r.reporting_period == current.reporting_period]
    if same_period:
        return Comparison(
            refresh=same_period[0], exact=False,
            relaxed=["The Lens definition changed between the two refreshes."])

    earlier = [r for r in same_filter
               if r.reporting_period and r.reporting_period != current.reporting_period]
    if earlier:
        return Comparison(
            refresh=earlier[0], exact=False,
            relaxed=[f"The previous comparable refresh reports "
                     f"{earlier[0].reporting_period}, this one reports "
                     f"{current.reporting_period}."])
    return Comparison(refresh=same_filter[0], exact=False,
                      relaxed=["The previous refresh has no reporting period "
                               "recorded."])


# ---------------------------------------------------------------------------
# §21: what changed, deterministically
# ---------------------------------------------------------------------------


def material(current: float | None, previous: float | None) -> bool:
    """Whether a movement is worth reporting.

    Relative, with an absolute floor. A ratio that went from 9.1% to 9.4% has
    moved; an exposure that went from 41,800,000,001 to 41,800,000,002 has
    not, and a purely absolute threshold cannot tell them apart.
    """
    if current is None or previous is None:
        return current != previous
    delta = abs(current - previous)
    if delta <= MATERIAL_ABSOLUTE:
        return False
    scale = max(abs(current), abs(previous))
    if scale == 0:
        return delta > MATERIAL_ABSOLUTE
    return (delta / scale) >= MATERIAL_RELATIVE


@dataclass
class PanelChange:
    """One tile, then and now, with the arithmetic between them done here."""

    panel_key: str
    metric_id: str = ""
    title: str = ""
    unit: str = "number"
    decimals: int = 2
    current: float | None = None
    previous: float | None = None
    absolute: float | None = None
    relative: float | None = None
    direction: str = "unchanged"
    material: bool = False
    definition_changed: bool = False
    status: str = "succeeded"
    previous_status: str = ""
    domains: list[str] = field(default_factory=list)
    reporting_period: str = ""
    previous_reporting_period: str = ""
    series_change: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "panel_key": self.panel_key, "metric_id": self.metric_id,
            "title": self.title, "unit": self.unit, "decimals": self.decimals,
            "current": self.current, "previous": self.previous,
            "absolute": self.absolute, "relative": self.relative,
            "direction": self.direction, "material": self.material,
            "definition_changed": self.definition_changed,
            "status": self.status, "previous_status": self.previous_status,
            "domains": list(self.domains),
            "reporting_period": self.reporting_period,
            "previous_reporting_period": self.previous_reporting_period,
            "series_change": list(self.series_change),
            "note": self.note,
        }


@dataclass
class Delta:
    """Everything that changed between two refreshes, worked out arithmetically."""

    classification: list[str] = field(default_factory=list)
    panels: list[PanelChange] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    definitions_changed: list[str] = field(default_factory=list)
    source_changed: list[str] = field(default_factory=list)
    comparison: Comparison = field(default_factory=Comparison)

    @property
    def material_changes(self) -> list[PanelChange]:
        return [p for p in self.panels if p.material]

    @property
    def anything_material(self) -> bool:
        return bool(self.material_changes or self.added or self.removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": list(self.classification),
            "classification_labels": [CLASSIFICATION_LABELS.get(c, c)
                                      for c in self.classification],
            "classification_meaning": [CLASSIFICATION_MEANING.get(c, "")
                                       for c in self.classification],
            "panels": [p.to_dict() for p in self.panels],
            "material": [p.to_dict() for p in self.material_changes],
            "added": list(self.added), "removed": list(self.removed),
            "definitions_changed": list(self.definitions_changed),
            "source_changed": list(self.source_changed),
            "comparison": self.comparison.to_dict(),
            "anything_material": self.anything_material,
        }


def compare(current: Refresh, comparison: Comparison) -> Delta:
    """§21 and §25E. The deterministic account of what changed.

    Everything a written interpretation is allowed to say about movement is
    computed here first, in Python, from two stored snapshots. That ordering
    is what makes §29's claim validation possible: the figures exist before
    anybody writes about them.
    """
    delta = Delta(comparison=comparison)
    previous = comparison.refresh
    if previous is None:
        delta.classification = [BASELINE]
        for snapshot in current.panels:
            delta.panels.append(PanelChange(
                panel_key=snapshot.panel_key, metric_id=snapshot.metric_id,
                title=snapshot.title, unit=snapshot.unit,
                decimals=snapshot.decimals, current=snapshot.value,
                status=snapshot.status, domains=list(snapshot.domains),
                reporting_period=snapshot.reporting_period))
        return delta

    before = {s.panel_key: s for s in previous.panels}
    now = {s.panel_key: s for s in current.panels}
    delta.added = [now[k].title or k for k in now if k not in before]
    delta.removed = [before[k].title or k for k in before if k not in now]

    for key, snapshot in now.items():
        earlier = before.get(key)
        change = PanelChange(
            panel_key=key, metric_id=snapshot.metric_id,
            title=snapshot.title, unit=snapshot.unit,
            decimals=snapshot.decimals, current=snapshot.value,
            status=snapshot.status, domains=list(snapshot.domains),
            reporting_period=snapshot.reporting_period)
        if earlier is None:
            change.note = "Added to this Lens since the previous refresh."
            delta.panels.append(change)
            continue

        change.previous = earlier.value
        change.previous_status = earlier.status
        change.previous_reporting_period = earlier.reporting_period
        change.definition_changed = (
            earlier.definition_hash != snapshot.definition_hash)
        if change.definition_changed:
            delta.definitions_changed.append(snapshot.title or key)

        if snapshot.value is not None and earlier.value is not None:
            change.absolute = snapshot.value - earlier.value
            if earlier.value:
                change.relative = change.absolute / abs(earlier.value)
            change.direction = ("up" if change.absolute > 0
                                else "down" if change.absolute < 0
                                else "unchanged")
        elif snapshot.value is None and earlier.value is not None:
            change.note = ("This produced a figure at the previous refresh "
                           "and does not now.")
        elif snapshot.value is not None and earlier.value is None:
            change.note = ("This produced no figure at the previous refresh "
                           "and does now.")

        change.material = material(snapshot.value, earlier.value)
        if change.material and change.definition_changed:
            change.note = (
                "This moved AND its definition changed between the two "
                "refreshes, so the movement is not purely the book.")
        change.series_change = _series_delta(earlier.series, snapshot.series)
        delta.panels.append(change)

    delta.source_changed = sorted(
        dataset for dataset, version in current.data_versions.items()
        if previous.data_versions.get(dataset) != version)

    delta.classification = _classify(current, previous, delta)
    return delta


def _series_delta(before: list[dict[str, Any]],
                  after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A chart's movement, per label, for labels present in both.

    §45: what a model is shown about a chart is this, not 240 points. A label
    that appeared or disappeared is reported as such rather than as a movement
    from nothing.
    """
    was = {str(p.get("label")): p.get("value") for p in before or []}
    now = {str(p.get("label")): p.get("value") for p in after or []}
    out: list[dict[str, Any]] = []
    for label in now:
        current, earlier = _number(now[label]), _number(was.get(label))
        entry: dict[str, Any] = {"label": label, "current": current,
                                 "previous": earlier}
        if label not in was:
            entry["note"] = "new"
        elif current is not None and earlier is not None:
            entry["absolute"] = current - earlier
            entry["material"] = material(current, earlier)
        out.append(entry)
    for label in was:
        if label not in now:
            out.append({"label": label, "current": None,
                        "previous": _number(was[label]), "note": "gone"})
    return out


def _classify(current: Refresh, previous: Refresh, delta: Delta) -> list[str]:
    """§21. Every code that applies, in a stable order."""
    codes: list[str] = []
    if current.filter_hash != previous.filter_hash:
        codes.append(FILTER_CHANGED)
    if (current.reporting_period and previous.reporting_period
            and current.reporting_period != previous.reporting_period):
        codes.append(PERIOD_ADVANCED)
    if delta.definitions_changed:
        codes.append(DEFINITION_CHANGED)
    if delta.added or delta.removed:
        codes.append(STRUCTURE_CHANGED)

    source_changed = bool(delta.source_changed)
    values_changed = any(p.material for p in delta.panels)
    if source_changed and values_changed:
        codes.append(SOURCE_AND_VALUE_CHANGED)
    elif source_changed:
        codes.append(SOURCE_CHANGED_VALUE_UNCHANGED)
    elif not values_changed:
        codes.append(NO_SOURCE_CHANGE)
    else:
        # Values moved with no source version change. Real, and worth its own
        # sentence: it means the definition or the period did the moving, and
        # both of those are already in `codes` above when they happened.
        codes.append(SOURCE_AND_VALUE_CHANGED)
    return [c for c in CLASSIFICATIONS if c in codes]


__all__ = [
    "BASELINE", "CLASSIFICATIONS", "CLASSIFICATION_LABELS",
    "CLASSIFICATION_MEANING", "DEFINITION_CHANGED", "FILTER_CHANGED",
    "HISTORY_LIMIT", "MATERIAL_ABSOLUTE", "MATERIAL_RELATIVE",
    "NO_SOURCE_CHANGE", "PERIOD_ADVANCED", "REFRESH_VERSION",
    "SOURCE_AND_VALUE_CHANGED", "SOURCE_CHANGED_VALUE_UNCHANGED",
    "STRUCTURE_CHANGED", "TRIGGERS", "TRIGGER_LABELS", "TRIGGER_MANUAL",
    "TRIGGER_OPENED", "TRIGGER_SCHEDULED",
    "Comparison", "Delta", "PanelChange", "PanelSnapshot", "Refresh",
    "capture", "comparable", "compare", "filter_hash", "material",
    "panel_key",
]
