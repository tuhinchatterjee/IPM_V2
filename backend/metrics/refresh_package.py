"""What a model is shown when a Lens refreshes. §25 and §45.

One structured package, built deterministically, containing everything §25
lists and nothing else. The design constraint that shapes every decision here
is §45: not "send the data", but "send what is needed to REASON about the
change, bounded".

The size rule, stated in numbers
---------------------------------
A Lens of thirty tiles and eight charts, twelve refreshes deep, is:

    every value at every refresh          30 × 12   =    360 figures
    every chart point at every refresh     8 × 240  =  1,920 points
                                                     ------------
                                                        2,280 figures

which is a prompt nobody should pay for and no model reads carefully. What
goes instead:

    current values                                   30 figures
    previous comparable values                       30 figures
    the derived change between them                  30 figures
    bounded refresh history, material points only    ≤ 30 × 4
    chart deltas, material labels only               ≤ 8 × 6
    change features from Cockpit and EWS             ≤ 20

which is roughly a tenth of the first number and is strictly MORE useful,
because the change has already been computed and the model is not being asked
to subtract two columns of figures without arithmetic.

Every figure in the package is already true
--------------------------------------------
Nothing here computes a new number. Values come from stored snapshots and
changes from `refresh.compare`, which did the arithmetic in Python. That is
what makes §29 possible: every figure a written interpretation is allowed to
contain exists in this package before the model sees it, so a figure that is
NOT in it is a fabrication and can be found by looking.

What is deliberately excluded
------------------------------
Row-level data. Borrower names. Anything that is not a figure already on the
Lens or a fact about how it was computed. A model interpreting a dashboard has
no business seeing the book, and one that saw it might write about a borrower
the reader is not looking at.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.metrics import lens_domains as domains
from backend.metrics.refresh import (
    CLASSIFICATION_LABELS,
    CLASSIFICATION_MEANING,
    Delta,
    PanelChange,
    Refresh,
)

logger = logging.getLogger(__name__)

PACKAGE_VERSION = "3.0.0"

#: How many history points per metric. Four is enough to see a trend and to
#: say "third consecutive rise"; twelve is a table nobody reads.
HISTORY_POINTS = 4
#: In deep mode.
DEEP_HISTORY_POINTS = 8

#: How many chart labels travel per chart. The MOST MOVED ones, not the first
#: alphabetically — a chart of twenty sectors has three that matter.
CHART_LABELS = 6
DEEP_CHART_LABELS = 12

#: How many change features per domain.
FEATURES = 10

MODE_STANDARD = "standard"
MODE_DEEP = "deep"
MODES = (MODE_STANDARD, MODE_DEEP)


def _figure(value: float | None, unit: str, decimals: int = 2) -> str | None:
    """A figure as it appears on the Lens, character for character.

    The same formatting the tile uses, because §29 matches the model's prose
    against these strings: a package that said "9.4" where the screen says
    "9.40%" would make every correct sentence look fabricated.
    """
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if unit == "percent":
        return f"{value:,.{decimals}f}%"
    if unit == "currency":
        return f"{value:,.{decimals}f}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def _change_text(change: PanelChange) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if change.absolute is not None:
        out["absolute"] = _figure(change.absolute, change.unit,
                                  change.decimals)
    if change.relative is not None:
        out["relative"] = f"{change.relative * 100:,.2f}%"
    out["direction"] = change.direction
    out["material"] = change.material
    return out


# ---------------------------------------------------------------------------
# §25H and §25I: change features, per domain
# ---------------------------------------------------------------------------

#: Which movements belong to which domain's story, keyed on the words that
#: appear in a governed metric's name. Read as: when one of these moves, it is
#: a Cockpit fact or an EWS fact, and the two are reported separately so a
#: reader can see corroboration rather than being told about it.
COCKPIT_FEATURES: tuple[tuple[str, str], ...] = (
    ("exposure", "exposure movement"),
    ("ead", "exposure movement"),
    ("stage", "stage migration"),
    ("ecl", "impairment"),
    ("coverage", "impairment coverage"),
    ("provision", "impairment"),
    ("rating", "rating movement"),
    ("grade", "rating movement"),
    ("concentration", "concentration"),
    ("obligor", "concentration"),
    ("hhi", "concentration"),
    ("collateral", "collateral"),
    ("arrear", "arrears"),
    ("dpd", "arrears"),
    ("npl", "arrears"),
    ("delinquen", "arrears"),
    ("limit", "limits"),
    ("utilisation", "limits"),
)

EWS_FEATURES: tuple[tuple[str, str], ...] = (
    ("watchlist", "watchlist movement"),
    ("severity", "signal severity"),
    ("ews", "signal severity"),
    ("covenant", "covenants"),
    ("dscr", "debt service"),
    ("downgrade", "downgrade risk"),
    ("deteriorat", "credit trend"),
    ("trend", "credit trend"),
    ("risk score", "forward risk score"),
    ("signal", "signals"),
    ("sicr", "significant increase in credit risk"),
)


def _features(changes: list[PanelChange], domain: str) -> list[dict[str, Any]]:
    """§25H/§25I. The movements that belong to one domain's story.

    Classified by the metric's DOMAINS first — which is a fact recorded on the
    snapshot — and by its name only where the domains are ambiguous, which is
    the case for the facility position that both domains read. Naming it a
    "feature" rather than just listing every change is what lets the
    interpretation say "stage migration and watchlist movement are consistent"
    rather than "these seven numbers went up".
    """
    vocabulary = COCKPIT_FEATURES if domain == domains.COCKPIT else EWS_FEATURES
    out: list[dict[str, Any]] = []
    for change in changes:
        if not change.material:
            continue
        if change.domains and domain not in change.domains:
            continue
        name = (change.title or change.metric_id).lower()
        feature = next((label for word, label in vocabulary if word in name),
                       "")
        if not feature and change.domains == [domain]:
            feature = "other"
        if not feature:
            continue
        out.append({
            "feature": feature,
            "metric": change.title or change.metric_id,
            "previous": _figure(change.previous, change.unit, change.decimals),
            "current": _figure(change.current, change.unit, change.decimals),
            "direction": change.direction,
            **({"change": _figure(change.absolute, change.unit,
                                  change.decimals)}
               if change.absolute is not None else {}),
        })
        if len(out) >= FEATURES:
            break
    return out


# ---------------------------------------------------------------------------
# The package
# ---------------------------------------------------------------------------


def build(lens: dict[str, Any], rendered: dict[str, Any], current: Refresh,
          delta: Delta, history: list[Refresh], *, mode: str = MODE_STANDARD,
          budget: Any = None, permissions: dict[str, Any] | None = None
          ) -> dict[str, Any]:
    """§25's package: everything a model needs to interpret this refresh."""
    deep = (mode or MODE_STANDARD).lower() == MODE_DEEP
    points = DEEP_HISTORY_POINTS if deep else HISTORY_POINTS
    labels = DEEP_CHART_LABELS if deep else CHART_LABELS

    previous = delta.comparison.refresh
    by_key = {c.panel_key: c for c in delta.panels}

    # ---- §25B and §25C: current metrics and chart results ---------------
    metrics: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for snapshot in current.panels:
        change = by_key.get(snapshot.panel_key)
        if snapshot.status != "succeeded":
            unavailable.append(snapshot.title or snapshot.metric_id)
            continue
        if snapshot.kind == "chart":
            charts.append(_chart_entry(snapshot, change, labels=labels))
            continue
        entry: dict[str, Any] = {
            "id": snapshot.metric_id,
            "name": snapshot.title,
            "current": _figure(snapshot.value, snapshot.unit,
                               snapshot.decimals),
            "unit": snapshot.unit,
            "grain": snapshot.grain,
            "reporting_period": snapshot.reporting_period,
            "domains": [domains.LABELS.get(d, d) for d in snapshot.domains],
            "coverage": {
                "rows": snapshot.coverage.get("rows_considered", 0),
                "datasets": snapshot.coverage.get("datasets", []),
            },
        }
        if change is not None and change.previous is not None:
            entry["previous"] = _figure(change.previous, snapshot.unit,
                                        snapshot.decimals)
            entry["previous_reporting_period"] = change.previous_reporting_period
            entry["change"] = _change_text(change)
            if change.definition_changed:
                entry["definition_changed"] = True
                entry["definition_note"] = (
                    "This metric is calculated differently from how it was at "
                    "the previous refresh. Part of any movement is the "
                    "definition, not the book.")
        elif change is not None and change.note:
            entry["note"] = change.note
        series = _metric_history(snapshot.metric_id, history, points=points,
                                 unit=snapshot.unit, decimals=snapshot.decimals)
        if series["refresh_history"]:
            entry["refresh_history"] = series["refresh_history"]
        if series["reporting_period_history"]:
            entry["reporting_period_history"] = series["reporting_period_history"]
        metrics.append(entry)

    material = [c for c in delta.panels if c.material]

    package: dict[str, Any] = {
        # ---- §25A: what this Lens is ---------------------------------
        "lens": {
            "id": lens.get("id"),
            "name": lens.get("name", ""),
            "purpose": lens.get("description", ""),
            "audience": lens.get("audience", ""),
            "scope": rendered.get("scope") or {},
            "reporting_period": current.reporting_period,
            "sections": [s.get("title") for s in (rendered.get("sections") or [])
                         if isinstance(s, dict)],
            "design_rationale": (lens.get("definition") or {}).get(
                "design_rationale", ""),
        },
        "refresh": {
            "id": current.id,
            "refreshed_at": (current.refreshed_at.isoformat()
                             if current.refreshed_at else ""),
            "trigger": current.trigger,
            # §18. Said in the package as plainly as it is stored, because the
            # single most likely mistake a reading can make is treating a
            # same-quarter restatement as the book moving.
            "reporting_period": current.reporting_period,
            "note": ("`refreshed_at` is when this was CALCULATED. "
                     "`reporting_period` is which business period the figures "
                     "describe. They are different things."),
        },
        "metrics": metrics,
        "charts": charts,
        "unavailable": unavailable,

        # ---- §25D: what it is being compared with --------------------
        "previous_refresh": ({
            "id": previous.id,
            "refreshed_at": (previous.refreshed_at.isoformat()
                             if previous.refreshed_at else ""),
            "reporting_period": previous.reporting_period,
            "data_versions": previous.data_versions,
        } if previous is not None else None),
        "comparability": {
            "exact": delta.comparison.exact,
            "relaxed": delta.comparison.relaxed,
            "why_none": delta.comparison.why_none,
        },

        # ---- §25E: the change, already computed ----------------------
        "classification": [
            {"code": code, "label": CLASSIFICATION_LABELS.get(code, code),
             "means": CLASSIFICATION_MEANING.get(code, "")}
            for code in delta.classification],
        "material_changes": [
            {"metric": c.title or c.metric_id,
             "previous": _figure(c.previous, c.unit, c.decimals),
             "current": _figure(c.current, c.unit, c.decimals),
             **_change_text(c),
             "definition_changed": c.definition_changed,
             "domains": [domains.LABELS.get(d, d) for d in c.domains]}
            for c in material],
        "source_data_changed": delta.source_changed,

        # ---- §25G: what changed about the LENS, not the book ---------
        "lens_structural_change": {
            "metrics_added": delta.added,
            "metrics_removed": delta.removed,
            "definitions_changed": delta.definitions_changed,
            "filter_changed": any(
                c["code"] == "filter_changed"
                for c in [{"code": x} for x in delta.classification]),
        },

        # ---- §25H and §25I: change features, by domain ---------------
        "cockpit_changes": _features(material, domains.COCKPIT),
        "ews_changes": _features(material, domains.EWS),

        # ---- §25J: what may be spent and what may be reached ---------
        "permissions": dict(permissions or {}),
        "budget": (budget.to_dict() if hasattr(budget, "to_dict") else {}),
        "mode": MODE_DEEP if deep else MODE_STANDARD,
        "version": PACKAGE_VERSION,
    }
    return package


def _chart_entry(snapshot: Any, change: PanelChange | None, *,
                 labels: int) -> dict[str, Any]:
    """§25C and §45. A chart as a deterministic summary and its moved labels.

    The whole series is stored; what travels is the total, the largest
    contributors and the labels that MOVED — because "Real Estate rose 2.1
    points while everything else held" is the sentence a reader wants and it
    needs three labels, not twenty.
    """
    points = [p for p in snapshot.series if p.get("value") is not None]
    values = [float(p["value"]) for p in points
              if isinstance(p.get("value"), (int, float))]
    entry: dict[str, Any] = {
        "name": snapshot.title,
        "metric_id": snapshot.metric_id,
        "unit": snapshot.unit,
        "reporting_period": snapshot.reporting_period,
        "domains": [domains.LABELS.get(d, d) for d in snapshot.domains],
        "groups": len(points),
        "summary": {
            "total": _figure(sum(values), snapshot.unit, snapshot.decimals)
            if values else None,
            "largest": _figure(max(values), snapshot.unit, snapshot.decimals)
            if values else None,
            "smallest": _figure(min(values), snapshot.unit, snapshot.decimals)
            if values else None,
        },
        "top": [
            {"label": p["label"],
             "value": _figure(p["value"], snapshot.unit, snapshot.decimals)}
            for p in sorted(points,
                            key=lambda x: -abs(float(x["value"] or 0)))[:labels]
        ],
        "result_reference": {
            "panel_key": snapshot.panel_key,
            "note": "The full series is stored on this refresh and can be "
                    "read back; only the largest and most-moved labels are "
                    "carried here.",
        },
    }
    if change is not None and change.series_change:
        moved = [s for s in change.series_change
                 if s.get("material") or s.get("note")]
        moved.sort(key=lambda s: -abs(float(s.get("absolute") or 0)))
        entry["moved"] = [
            {"label": s["label"],
             "previous": _figure(s.get("previous"), snapshot.unit,
                                 snapshot.decimals),
             "current": _figure(s.get("current"), snapshot.unit,
                                snapshot.decimals),
             **({"change": _figure(s["absolute"], snapshot.unit,
                                   snapshot.decimals)}
                if s.get("absolute") is not None else {}),
             **({"note": s["note"]} if s.get("note") else {})}
            for s in moved[:labels]
        ]
    return entry


def _metric_history(metric_id: str, history: list[Refresh], *, points: int,
                    unit: str, decimals: int) -> dict[str, Any]:
    """§25F. Bounded history for one metric, in both of §22's senses."""
    by_refresh: list[dict[str, Any]] = []
    by_period: dict[str, dict[str, Any]] = {}
    for refresh in sorted(history,
                          key=lambda r: (r.refreshed_at or 0, r.id or 0)):
        for snapshot in refresh.panels:
            if snapshot.metric_id != metric_id or snapshot.value is None:
                continue
            figure = _figure(snapshot.value, unit, decimals)
            by_refresh.append({
                "refreshed_at": (refresh.refreshed_at.date().isoformat()
                                 if refresh.refreshed_at else ""),
                "value": figure})
            if snapshot.reporting_period:
                by_period[snapshot.reporting_period] = {
                    "reporting_period": snapshot.reporting_period,
                    "value": figure}
            break
    return {
        "refresh_history": by_refresh[-points:],
        "reporting_period_history": list(by_period.values())[-points:],
    }


# ---------------------------------------------------------------------------
# §29: what a written reading is allowed to say
# ---------------------------------------------------------------------------


def figures(package: dict[str, Any]) -> set[str]:
    """Every figure in the package, as the strings the Lens shows.

    This is the set §29 checks a written interpretation against. Built by
    walking the package rather than by re-listing what went into it, so a
    field added to the package cannot fall out of the check by being
    forgotten.
    """
    import re

    number = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            found.update(number.findall(node))
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            found.add(f"{node:,.2f}")
            found.add(str(node))

    walk(package)
    return found


__all__ = ["CHART_LABELS", "COCKPIT_FEATURES", "DEEP_CHART_LABELS",
           "DEEP_HISTORY_POINTS", "EWS_FEATURES", "FEATURES",
           "HISTORY_POINTS", "MODES", "MODE_DEEP", "MODE_STANDARD",
           "PACKAGE_VERSION", "build", "figures"]
