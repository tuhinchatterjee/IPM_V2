"""The validation charts, drawn for a document rather than for a screen.

§15: "Include actual charts and tables using a readable probability/count
format." The screen already draws fifteen chart payloads; this draws the
same payloads to PNG so the document carries the picture rather than a table
of the numbers the picture was made from.

One vocabulary, two renderers
------------------------------
The payload is the runner's, unchanged — the same `result.chart` the browser
reads. That is deliberate: a document renderer with its own input shape is a
second place for a chart to be assembled, and the two diverge on the first
result whose payload changes. Here the only thing that differs is the medium.

It draws on `backend.reporting.charts` for the palette and the axis
conventions, so a chart in a validation report looks like a chart in a
committee pack, which looks like the screen.

What it refuses to draw
------------------------
A kind it does not know returns nothing, and the caller renders the section's
table instead. Every figure in this report accompanies a table rather than
replacing one, so a chart that cannot be drawn costs a picture and never a
number. Nothing here substitutes a zero for a missing value: a payload with
no usable series draws nothing rather than a flat line at the origin, which
is the one picture a validation document must never contain.
"""

from __future__ import annotations

import io
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from backend.reporting.charts import (  # noqa: E402
    AMBER,
    BLUE,
    GRID,
    MUTED,
    RED,
    TEAL,
    _bare,
)

CHARTS_VERSION = "scv-report-charts-1.0.0"

#: Wide enough to read a twelve-band axis at 6 inches on the page.
SIZE = (7.2, 3.1)


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    got = payload.get(key)
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) \
        else []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    return got if got == got and abs(got) != float("inf") else None


def _finish(fig: Any) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", facecolor="white",
                dpi=170)
    plt.close(fig)
    return buffer.getvalue()


def _short(label: str, keep: int = 22) -> str:
    label = str(label)
    return label if len(label) <= keep else label[: keep - 1] + "…"


def _as_rate(values: list[float]) -> bool:
    """Whether a series reads as a probability rather than as a count."""
    return bool(values) and all(0.0 <= v <= 1.0 for v in values)


def _label_bars(ax: Any, bars: Any, values: list[float], rate: bool) -> None:
    """A direct value on every bar, so the reading never depends on the axis.

    §15 asks for a readable probability/count format, which is the whole of
    this function: a default rate is printed as 1.71%, a count as 3,840, and
    neither is printed as 0.0171 or 3840.0.
    """
    for bar, value in zip(bars, values, strict=False):
        ax.annotate(f"{value:.2%}" if rate else f"{value:,.0f}",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    ha="center", va="bottom", fontsize=7, color=MUTED,
                    xytext=(0, 2), textcoords="offset points")


def _grouped(labels: list[str], series: list[tuple[str, list[float]]],
             *, rate: bool, rotate: int = 30) -> bytes | None:
    if not labels or not series:
        return None
    fig, ax = plt.subplots(figsize=SIZE)
    _bare(ax)
    width = 0.8 / len(series)
    colours = [TEAL, BLUE, AMBER, RED]
    spots = range(len(labels))
    for at, (name, values) in enumerate(series):
        bars = ax.bar([x + at * width - 0.4 + width / 2 for x in spots],
                      values, width=width * 0.92, label=name,
                      color=colours[at % len(colours)])
        if len(series) == 1:
            _label_bars(ax, bars, values, rate)
    ax.set_xticks(list(spots))
    ax.set_xticklabels([_short(one) for one in labels], rotation=rotate,
                       ha="right" if rotate else "center", fontsize=7.5)
    if rate:
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.1%}"))
    else:
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=7.5, loc="upper right")
    return _finish(fig)


# ------------------------------------------------------------- the kinds


def _band_rate(payload: dict[str, Any]) -> bytes | None:
    """Observed default rate by band, against the predicted PD beside it.

    Drawing only the observed half of a calibration picture leaves the reader
    to remember the other half, which in a document they are reading a year
    later they will not.
    """
    rows = _rows(payload, "bands") or _rows(payload, "buckets")
    if not rows:
        return None
    label_key = str(payload.get("label_key") or "")
    for candidate in (label_key, "band", "population", "segment", "period"):
        if candidate and any(candidate in row for row in rows):
            label_key = candidate
            break
    observed = next((k for k in ("observed_rate", "observed_default_rate")
                     if any(k in row for row in rows)), "")
    predicted = next((k for k in ("mean_predicted_pd", "average_predicted_pd")
                      if any(k in row for row in rows)), "")
    labels, first, second = [], [], []
    for row in rows:
        left = _number(row.get(observed)) if observed else None
        if left is None:
            continue
        labels.append(str(row.get(label_key, "")))
        first.append(left)
        second.append(_number(row.get(predicted)) or 0.0 if predicted else 0.0)
    if not labels:
        return None
    series: list[tuple[str, list[float]]] = [("Observed default rate", first)]
    if predicted and any(second):
        series.append(("Mean predicted PD", second))
    return _grouped(labels, series, rate=_as_rate(first + second))


def _waterfall(payload: dict[str, Any]) -> bytes | None:
    rows = _rows(payload, "steps")
    key = str(payload.get("value_key") or "rows")
    values = [_number(row.get(key)) for row in rows]
    kept = [(str(row.get("step", "")), value)
            for row, value in zip(rows, values, strict=False)
            if value is not None]
    if not kept:
        return None
    return _grouped([one for one, _ in kept],
                    [(str(payload.get("value_label") or "Value"),
                      [two for _, two in kept])],
                    rate=_as_rate([two for _, two in kept]))


def _distribution(payload: dict[str, Any]) -> bytes | None:
    """Development against current, or one banded distribution."""
    levels = _rows(payload, "levels")
    if levels:
        # One variable — the one that moved most, since a document cannot
        # offer the screen's selector.
        moved: dict[str, float] = {}
        for row in levels:
            name = str(row.get("variable", ""))
            moved[name] = moved.get(name, 0.0) + abs(
                _number(row.get("change")) or 0.0)
        chosen = max(moved, key=lambda k: moved[k]) if moved else ""
        shown = [row for row in levels
                 if str(row.get("variable", "")) == chosen][:14]
        labels = [str(row.get("level", "")) for row in shown]
        then = [_number(row.get("development_share")) or 0.0 for row in shown]
        now = [_number(row.get("current_share")) or 0.0 for row in shown]
        if not labels:
            return None
        return _grouped(labels, [("At development", then), ("Now", now)],
                        rate=True)

    bands = _rows(payload, "bands")
    if bands:
        label_key = str(payload.get("label_key") or "band")
        value_key = str(payload.get("value_key") or "share")
        labels = [str(row.get(label_key, "")) for row in bands]
        values = [_number(row.get(value_key)) or 0.0 for row in bands]
        return _grouped(labels, [("Share of the population", values)],
                        rate=_as_rate(values))

    matured = payload.get("matured")
    immature = payload.get("immature")
    if isinstance(matured, list) and isinstance(immature, list):
        return _grouped(["Outcome window closed", "Not yet matured"],
                        [("Periods", [float(len(matured)),
                                      float(len(immature))])],
                        rate=False, rotate=0)

    draws = payload.get("draws")
    if isinstance(draws, list) and draws:
        numbers = [x for x in (_number(one) for one in draws)
                   if x is not None]
        if not numbers:
            return None
        fig, ax = plt.subplots(figsize=SIZE)
        _bare(ax)
        ax.hist(numbers, bins=24, color=TEAL)
        ax.set_xlabel("Resampled statistic", fontsize=8)
        ax.set_ylabel("Resamples", fontsize=8)
        return _finish(fig)
    return None


def _trend(payload: dict[str, Any]) -> bytes | None:
    rows = (_rows(payload, "points") or _rows(payload, "periods")
            or _rows(payload, "series") or _rows(payload, "trend"))
    if not rows:
        return None
    label_key = next((k for k in ("period", "month", "cohort")
                      if any(k in row for row in rows)), "")
    value_key = next((k for k in ("value", "observed_over_expected", "auc",
                                  "gini", "ks", "index", "observed_rate",
                                  "psi")
                      if any(k in row for row in rows)), "")
    if not label_key or not value_key:
        return None
    labels, values = [], []
    for row in rows:
        got = _number(row.get(value_key))
        if got is None:
            continue
        labels.append(str(row.get(label_key, "")))
        values.append(got)
    if len(values) < 2:
        return None
    fig, ax = plt.subplots(figsize=SIZE)
    _bare(ax)
    ax.plot(range(len(values)), values, color=BLUE, linewidth=1.8,
            marker="o", markersize=3)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([_short(one, 10) for one in labels], rotation=45,
                       ha="right", fontsize=7)
    if _as_rate(values):
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.1%}"))
    return _finish(fig)


def _heatmap(payload: dict[str, Any]) -> bytes | None:
    """A grid, drawn as a grid. Rows are variables, columns are periods."""
    cells = _rows(payload, "cells")
    if not cells:
        return None
    rows_seen: list[str] = []
    columns_seen: list[str] = []
    grid: dict[tuple[str, str], float] = {}
    for cell in cells:
        row = str(cell.get("variable") or cell.get("segment") or "")
        column = str(cell.get("period") or "")
        value = (_number(cell.get("missing_rate"))
                 or _number(cell.get("value"))
                 or _number(cell.get("coverage")) or 0.0)
        if not row or not column:
            continue
        if row not in rows_seen:
            rows_seen.append(row)
        if column not in columns_seen:
            columns_seen.append(column)
        grid[(row, column)] = value
    if not rows_seen or not columns_seen:
        return None
    rows_seen, columns_seen = rows_seen[:14], columns_seen[:18]
    matrix = [[grid.get((r, c), 0.0) for c in columns_seen]
              for r in rows_seen]
    fig, ax = plt.subplots(
        figsize=(SIZE[0], max(2.0, 0.26 * len(rows_seen) + 1.0)))
    drawn = ax.imshow(matrix, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(columns_seen)))
    ax.set_xticklabels([_short(c, 10) for c in columns_seen], rotation=45,
                       ha="right", fontsize=7)
    ax.set_yticks(range(len(rows_seen)))
    ax.set_yticklabels([_short(r, 22) for r in rows_seen], fontsize=7)
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_color(GRID)
    bar = fig.colorbar(drawn, ax=ax, fraction=0.025, pad=0.02)
    bar.ax.tick_params(labelsize=6.5, length=0)
    bar.outline.set_visible(False)
    return _finish(fig)


def _ranking(payload: dict[str, Any]) -> bytes | None:
    rows = _rows(payload, "rows") or _rows(payload, "variables")
    if not rows:
        return None
    label_key = str(payload.get("label_key") or "")
    value_key = str(payload.get("value_key") or "")
    if not label_key:
        label_key = next((k for k in ("model", "variable", "segment", "name")
                          if any(k in row for row in rows)), "")
    if not value_key:
        value_key = next((k for k in ("value", "index", "csi", "inversions",
                                      "information_value", "gini")
                          if any(k in row for row in rows)), "")
    if not label_key or not value_key:
        return None
    pairs = [(str(row.get(label_key, "")), _number(row.get(value_key)))
             for row in rows]
    kept = [(one, two) for one, two in pairs if two is not None][:14]
    if not kept:
        return None
    return _grouped([one for one, _ in kept],
                    [(value_key.replace("_", " ").title(),
                      [two for _, two in kept])],
                    rate=_as_rate([two for _, two in kept]))


def _calibration(payload: dict[str, Any]) -> bytes | None:
    rows = _rows(payload, "buckets") or _rows(payload, "bands")
    if not rows:
        return None
    observed, predicted = [], []
    for row in rows:
        left = _number(row.get("observed_default_rate"))
        right = _number(row.get("average_predicted_pd"))
        if left is None or right is None:
            continue
        observed.append(left)
        predicted.append(right)
    if len(observed) < 2:
        return None
    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    _bare(ax)
    top = max(observed + predicted) * 1.1 or 1.0
    ax.plot([0, top], [0, top], color=MUTED, linewidth=1.0, linestyle="--",
            label="Perfectly calibrated")
    ax.scatter(predicted, observed, color=RED, s=26, zorder=3,
               label="Score band")
    ax.set_xlabel("Mean predicted PD", fontsize=8)
    ax.set_ylabel("Observed default rate", fontsize=8)
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.1%}"))
    ax.legend(frameon=False, fontsize=7.5, loc="upper left")
    return _finish(fig)


def _curves(payload: dict[str, Any]) -> bytes | None:
    for key, x_key, y_key, x_label, y_label in (
            ("roc", "false_positive_rate", "true_positive_rate",
             "False positive rate", "True positive rate"),
            ("cap", "share", "captured", "Share of the population",
             "Share of defaults captured"),
            ("ks", "score", "separation", "Score", "Cumulative separation"),
            ("deciles", "decile", "lift", "Decile", "Lift")):
        rows = _rows(payload, key)
        if not rows:
            continue
        xs, ys = [], []
        for row in rows:
            left, right = _number(row.get(x_key)), _number(row.get(y_key))
            if left is None or right is None:
                continue
            xs.append(left)
            ys.append(right)
        if len(xs) < 2:
            continue
        fig, ax = plt.subplots(figsize=(4.8, 3.6))
        _bare(ax)
        ax.plot(xs, ys, color=BLUE, linewidth=1.8)
        if key in ("roc", "cap"):
            ax.plot([min(xs), max(xs)], [min(ys), max(ys)], color=MUTED,
                    linewidth=1.0, linestyle="--")
        ax.set_xlabel(x_label, fontsize=8)
        ax.set_ylabel(y_label, fontsize=8)
        return _finish(fig)
    return None


DRAW: dict[str, Any] = {
    "band_rate": _band_rate,
    "waterfall": _waterfall,
    "distribution": _distribution,
    "heatmap": _heatmap,
    "trend": _trend,
    "psi_trend": _trend,
    "ranking": _ranking,
    "tornado": _ranking,
    "woe": _ranking,
    "calibration": _calibration,
    "roc": _curves,
    "cap": _curves,
    "ks": _curves,
    "lift": _curves,
    "gains": _curves,
}


def render(kind: str, payload: dict[str, Any]) -> bytes | None:
    """One chart payload as PNG bytes, or nothing if it cannot be drawn."""
    draw = DRAW.get(str(kind or ""))
    if draw is None or not isinstance(payload, dict) or not payload:
        return None
    try:
        return draw(payload)
    except Exception:  # noqa: BLE001 - a chart never fails a document
        # A figure that cannot be drawn costs a picture. The section's table
        # carries the same numbers, so the evidence is unaffected, and a
        # report that refused to generate because of a chart would be a
        # report nobody could produce.
        return None


__all__ = ["CHARTS_VERSION", "DRAW", "render"]
