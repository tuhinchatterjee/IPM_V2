"""
Taking an answer out of the Cockpit, with everything that makes it checkable.

What an export has to carry
---------------------------
A figure on its own is not evidence. Pasted into a memo it becomes a number
with no provenance, and the first question anyone asks of it -- which book,
which release, which month, how many rows -- is the one the export dropped.

So every document this module produces carries a LINEAGE block: the book, the
release id AND the fingerprint of the bytes it was computed from, the tenant,
the reporting period, the run, the artifacts, and the digest of the code that
produced each one. It is the same header the answer itself is pinned to, so
an export and the screen it came from cannot disagree.

Full rows, and saying which
---------------------------
A table on screen shows a preview. An export of that table shows the WHOLE
artifact, because a reader exporting a table is asking for the table. Where
that is not possible -- a clipped result whose full form was never
materialized -- the document says so in the lineage block rather than
presenting a subset as complete. `rows=displayed` is available and is
labelled as the subset it is.

What it never does
------------------
It does not recompute. Every value written here comes from the stored
artifact and the stored answer, formatted through the same display policy the
screen uses, so the number in the CSV is the number the reader saw.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from typing import Any

from backend.cockpit_v4 import display as disp

#: Rows shown on screen. An export defaults to everything, and says so.
ALL_ROWS = "all"
DISPLAYED_ROWS = "displayed"
ROW_MODES = (ALL_ROWS, DISPLAYED_ROWS)

FORMAT_CSV = "csv"
FORMAT_MARKDOWN = "md"
FORMAT_SVG = "svg"

MEDIA_TYPES = {
    FORMAT_CSV: "text/csv; charset=utf-8",
    FORMAT_MARKDOWN: "text/markdown; charset=utf-8",
    FORMAT_SVG: "image/svg+xml",
}


class ExportUnavailable(RuntimeError):
    """This cannot be exported. Said, never approximated."""


@dataclass(frozen=True)
class Lineage:
    """Where an exported figure came from. Carried by every document."""

    run_id: str
    question: str
    domain_id: str
    domain_label: str
    release_id: str
    release_fingerprint: str
    tenant_id: str
    reporting_currency: str
    amount_scale: str
    #: WHICH PERIODS the figures are from, and what a period IS in this book.
    #:
    #: The document said which book, which release and which day it was
    #: exported, and never which MONTH the numbers described. A reader who
    #: keeps the file -- which is the whole point of exporting it -- could
    #: not tell a year later what they were looking at, and neither could
    #: anyone they sent it to.
    reporting_periods: tuple[str, ...] = ()
    reporting_frequency: str = ""
    produced_at: str = ""
    artifact_ids: tuple[str, ...] = ()
    code_digests: tuple[str, ...] = ()
    row_scope: str = ALL_ROWS
    row_count: int = 0
    #: How many rows the stored result holds. Equal to `row_count` when the
    #: export is the whole thing, which is what `complete` then says.
    total_rows: int = 0
    complete: bool = True

    @property
    def period_line(self) -> str:
        """The period or periods these figures are for, in the book's own
        vocabulary. Never a quarter for a monthly book."""
        noun = ("month" if self.reporting_frequency == "monthly"
                else "quarter" if self.reporting_frequency == "quarterly"
                else "period")
        periods = [p for p in self.reporting_periods if p]
        if not periods:
            return "unstated"
        if len(periods) == 1:
            return f"{periods[0]} (one {noun})"
        return (f"{periods[0]} to {periods[-1]} "
                f"({len(periods)} {noun}s)")

    def lines(self) -> list[str]:
        body = [
            f"Question: {self.question}",
            f"Book: {self.domain_label or self.domain_id or 'unstated'}",
            f"Release: {self.release_id or 'unstated'}",
            f"Release fingerprint: {self.release_fingerprint or 'unstated'}",
            f"Tenant: {self.tenant_id}",
            f"Denomination: {self.reporting_currency} {self.amount_scale}",
            f"Reporting period: {self.period_line}",
            f"Run: {self.run_id}",
            f"Exported: {self.produced_at}",
        ]
        if self.artifact_ids:
            body.append(f"Artifacts: {', '.join(self.artifact_ids)}")
        if self.code_digests:
            body.append(f"Executed code digests: "
                        f"{', '.join(self.code_digests)}")
        total = self.total_rows or self.row_count
        if self.row_scope == ALL_ROWS:
            body.append(f"Rows: {self.row_count} (every row of the result)")
        elif self.complete:
            # The subset WAS everything. Saying "a subset" here would be a
            # false caveat, and a reader who learns the caveats are
            # unreliable stops reading them.
            body.append(f"Rows: {self.row_count} (the rows shown on screen, "
                        f"which is every row of the result)")
        else:
            body.append(f"Rows: {self.row_count} of {total} (the rows shown "
                        f"on screen)")
        if not self.complete:
            body.append(
                f"INCOMPLETE: this is {self.row_count} of {total} rows. "
                f"Export with rows=all for the whole result.")
        return body


_PERIOD_KEYS = ("reporting_months", "reporting_periods",
                "reporting_quarters")


def _periods_of(record: Any, artifact: dict[str, Any] | None,
                answer: dict[str, Any] | None,
                artifacts: dict[str, dict[str, Any]] | None = None
                ) -> tuple[str, ...]:
    """The periods this analysis was actually run over.

    Read from what the run PRODUCED -- the executed scope stored on each
    artifact, then the pinned scope of the published answer -- rather than
    from a guess. An export that names the wrong period is worse than one
    that says the period is unstated, so the release's latest month is used
    only when the run recorded nothing at all, and it is the last resort.
    """
    found: list[str] = []
    sources = [(a or {}).get("scope") or {}
               for a in (artifacts or {}).values()]
    sources.append((artifact or {}).get("scope") or {})
    sources.append(((answer or {}).get("pinned_scope") or {}))
    for source in sources:
        for key in _PERIOD_KEYS:
            for value in list(source.get(key) or []):
                text = str(value).strip()
                if text and text not in found:
                    found.append(text)
    if not found:
        latest = str((((answer or {}).get("release") or {})
                      .get("latest_populated_period")) or "").strip()
        if latest:
            found.append(latest)
    return tuple(sorted(found))


def _frequency_of(periods: tuple[str, ...]) -> str:
    """What a period IS here, read off its own spelling."""
    if not periods:
        return ""
    first = periods[0]
    if len(first) == 7 and first[4] == "-":
        return "monthly"
    if len(first) == 6 and first[4] in "Qq":
        return "quarterly"
    return ""


def lineage_for(*, record: Any, artifact: dict[str, Any] | None = None,
                header: Any = None, produced_at: str = "",
                row_scope: str = ALL_ROWS, row_count: int = 0,
                total_rows: int = 0, complete: bool = True,
                answer: dict[str, Any] | None = None,
                artifacts: dict[str, dict[str, Any]] | None = None
                ) -> Lineage:
    """Assemble the lineage from the run and the artifact it produced."""
    from backend.cockpit_v4 import domains as dom

    domain_id = str(getattr(record, "domain_id", "") or "")
    scope = (artifact or {}).get("scope") or {}
    domain_id = domain_id or str(scope.get("domain_id") or "")
    fingerprint = str(getattr(record, "release_fingerprint", "") or "")
    fingerprint = fingerprint or str(scope.get("release_fingerprint") or "")
    if header is not None:
        fingerprint = fingerprint or str(
            getattr(header, "release_fingerprint", "") or "")
    periods = _periods_of(record, artifact, answer, artifacts)
    return Lineage(
        reporting_periods=periods,
        reporting_frequency=str(getattr(header, "reporting_frequency", "")
                                or _frequency_of(periods)),
        run_id=str(getattr(record, "run_id", "")),
        question=str(getattr(record, "question", "")),
        domain_id=domain_id,
        domain_label=dom.LABELS.get(domain_id, ""),
        release_id=str((artifact or {}).get("release_id")
                       or getattr(record, "release_id", "") or ""),
        release_fingerprint=fingerprint,
        tenant_id=str(getattr(record, "tenant_id", "")),
        reporting_currency=str(getattr(header, "reporting_currency", "")
                               or "SAR"),
        amount_scale=str(getattr(header, "amount_scale", "") or "million"),
        produced_at=produced_at or _now(),
        artifact_ids=((str(artifact["artifact_id"]),) if artifact else ()),
        code_digests=((str(artifact.get("code_digest") or ""),)
                      if artifact and artifact.get("code_digest") else ()),
        row_scope=row_scope, row_count=row_count,
        total_rows=total_rows or int((artifact or {}).get("row_count") or 0)
        or row_count,
        complete=complete)


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- 1. one table ------------------------------------------------------

def table_csv(*, artifact: dict[str, Any], lineage: Lineage,
              columns: list[str] | None = None,
              units: dict[str, str] | None = None) -> str:
    """One result as CSV, with its lineage in a comment block above it.

    Two columns per measure: the canonical value a spreadsheet can compute
    with, and the published string the reader saw. Exporting only the string
    would hand over a column of text; exporting only the number would drop
    the currency and the scale.
    """
    rows = list(artifact.get("rows") or [])
    names = [str(c) for c in (columns or artifact.get("columns") or [])]
    if not names:
        raise ExportUnavailable("This result has no columns to export.")
    units = units or {}

    out = io.StringIO()
    for line in lineage.lines():
        out.write(f"# {line}\n")
    out.write("#\n# Every value below is the stored result, formatted by the "
              "same policy the screen uses. Nothing was recomputed.\n")
    writer = csv.writer(out, lineterminator="\n")
    header: list[str] = []
    for name in names:
        header.append(name)
        if units.get(name):
            header.append(f"{name} (as published)")
    writer.writerow(header)
    for row in rows:
        line: list[Any] = []
        for name in names:
            value = row.get(name)
            line.append("" if value is None else value)
            if units.get(name):
                line.append(_published(value, units[name]))
        writer.writerow(line)
    return out.getvalue()


def _published(value: Any, unit: str) -> str:
    """The reader's form of one cell, or empty when it is not a number."""
    from decimal import Decimal, InvalidOperation

    if value is None or isinstance(value, bool):
        return ""
    try:
        return disp.format_value(Decimal(str(value)), unit)
    except (InvalidOperation, ValueError, TypeError):
        return ""


# ---- 2. the whole analysis --------------------------------------------

def analysis_markdown(*, record: Any, answer: dict[str, Any],
                      artifacts: dict[str, dict[str, Any]],
                      lineage: Lineage) -> str:
    """Question, answer, claims, tables and lineage, as one document."""
    parts: list[str] = []
    parts.append(f"# {str(getattr(record, 'question', '')).strip()}\n")
    parts.append(f"*{lineage.domain_label or lineage.domain_id} · "
                 f"{lineage.release_id} · {lineage.period_line} · "
                 f"exported {lineage.produced_at}*\n")

    narrative = str(answer.get("narrative") or "").strip()
    if narrative:
        parts.append(narrative + "\n")

    claims = list(answer.get("numeric_claims") or [])
    if claims:
        parts.append("## Figures\n")
        parts.append("| Figure | Value | Evidence |")
        parts.append("| --- | --- | --- |")
        for claim in claims:
            shown = str(claim.get("display_value")
                        or claim.get("decimal_value") or "")
            evidence = claim.get("evidence") or {}
            reference = " ".join(str(evidence.get(k, "")) for k in
                                 ("artifact_id", "row_key", "column_id")
                                 if evidence.get(k))
            parts.append(f"| {claim.get('claim_id', '')} | {shown} | "
                         f"{reference} |")
        parts.append("")

    coverage = list(answer.get("coverage") or [])
    if coverage:
        parts.append("## What was answered\n")
        for entry in coverage:
            parts.append(f"- **{entry.get('subquestion', '')}** — "
                         f"{entry.get('status', '')}")
        parts.append("")

    for table in list(answer.get("tables") or []):
        artifact = artifacts.get(str(table.get("artifact_id") or ""))
        if artifact is None:
            continue
        parts.append(f"## {table.get('title') or 'Result'}\n")
        columns = [str(c) for c in (table.get("columns")
                                    or artifact.get("columns") or [])]
        units = dict(table.get("column_units") or {})
        parts.append("| " + " | ".join(columns) + " |")
        parts.append("| " + " | ".join("---" for _ in columns) + " |")
        for row in artifact.get("rows") or []:
            cells = []
            for column in columns:
                value = row.get(column)
                shown = _published(value, units.get(column, ""))
                cells.append(shown or ("" if value is None else str(value)))
            parts.append("| " + " | ".join(cells) + " |")
        parts.append("")
        parts.append(f"*{len(artifact.get('rows') or [])} rows · artifact "
                     f"{artifact.get('artifact_id')}*\n")

    limitations = list(answer.get("limitations") or [])
    if limitations:
        parts.append("## Limitations\n")
        for line in limitations:
            parts.append(f"- {line}")
        parts.append("")

    parts.append("## Lineage\n")
    for line in lineage.lines():
        parts.append(f"- {line}")
    parts.append("")
    parts.append("*Exported from CreditProbe Cockpit. Every figure above is "
                 "the stored result of an executed query; nothing was "
                 "recomputed for this document.*")
    return "\n".join(parts) + "\n"


# ---- 3. one chart ------------------------------------------------------

WIDTH = 720
HEIGHT = 360
PADDING = 48


def chart_svg(*, chart: dict[str, Any], lineage: Lineage) -> str:
    """A server-rendered SVG of a published chart.

    The server already owns every point, its label and its published string,
    because the analyst chose the series and the server supplied the values.
    Rendering here from the same body is what makes an exported chart the
    same chart: it cannot pick up a different scale, a different rounding or
    a different set of points on its way out.
    """
    kind = str(chart.get("kind") or chart.get("type") or "bar").lower()
    title = str(chart.get("title") or "")
    # A MATRIX AND A BOX PLOT ARE NOT POINT SERIES. Their bodies are built
    # by the server beside the points -- a grid of cells, or five numbers
    # per box -- and drawing them from `points[0]` would draw the flat rows
    # the grid exists to replace.
    if kind == "heatmap" and chart.get("matrix"):
        return _frame(title=title,
                      unit=str(chart["matrix"].get("unit") or ""),
                      body=_matrix_svg(chart["matrix"]), lineage=lineage)
    if kind == "box" and chart.get("boxes"):
        return _frame(title=title,
                      unit=str((chart["boxes"][0] or {}).get("unit") or ""),
                      body=_box_svg(chart["boxes"]), lineage=lineage)

    points = list(chart.get("points") or [])
    series = [str(c) for c in (chart.get("y_columns") or []) if c]
    if not points or not series:
        raise ExportUnavailable(
            "This chart has no plotted points, so there is nothing to "
            "export. The table behind it can be exported instead.")
    column = series[0]
    values: list[tuple[str, float, str]] = []
    for point in points:
        raw = (point.get("values") or {}).get(column)
        if raw is None:
            continue
        values.append((str(point.get("label") or ""), float(raw),
                       str((point.get("display") or {}).get(column) or "")))
    if not values:
        raise ExportUnavailable("Every point on this chart is empty.")

    unit = str((chart.get("series_units") or {}).get(column)
               or chart.get("unit") or "")

    # A FORM WITH SEVERAL MEASURES NEEDS THEM ALL. The single-series
    # `values` above is what a bar or a line is drawn from; a stack, a
    # group and a combo are drawn from every column the analyst named, so
    # they are dispatched before it and read the points themselves.
    if kind in _MULTI_SERIES:
        return _frame(title=title, unit=unit, lineage=lineage,
                      body=_MULTI_SERIES[kind](points, series))

    # EVERY FORM DRAWN AS ITSELF. `waterfall` and `scatter` have been legal
    # in the contract all along and fell through this dispatch to `_bar_svg`,
    # so an analyst that asked for a bridge got bars and was told nothing.
    body = {"line": _line_svg, "step_line": _step_line_svg,
            "area": _area_svg, "scatter": _scatter_svg,
            "waterfall": _waterfall_svg, "histogram": _histogram_svg,
            "pie": _pie_svg, "donut": _donut_svg,
            }.get(kind, _bar_svg)(values)
    return _frame(title=title, unit=unit, body=body, lineage=lineage)


def _numbers(points: list[dict[str, Any]], series: list[str]
             ) -> list[tuple[str, list[float]]]:
    """Every named measure, per labelled point. Missing cells read zero.

    A stack with a hole in it is not a stack: the segments above would sit
    at the wrong height and the total would be wrong, which is worse than
    showing the contribution as nothing.
    """
    out: list[tuple[str, list[float]]] = []
    for point in points:
        raw = point.get("values") or {}
        row: list[float] = []
        for column in series:
            try:
                row.append(float(raw.get(column)))
            except (TypeError, ValueError):
                row.append(0.0)
        out.append((str(point.get("label") or ""), row))
    return out


def _frame(*, title: str, unit: str, body: str, lineage: Lineage) -> str:
    """The page every chart is drawn on: title, unit and provenance."""
    footnote = (f"{lineage.domain_label or lineage.domain_id} · "
                f"{lineage.release_id} · fingerprint "
                f"{lineage.release_fingerprint[:16]} · exported "
                f"{lineage.produced_at}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-label="{_escape(title)}">'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>'
        f'<text x="{PADDING}" y="28" font-family="system-ui, sans-serif" '
        f'font-size="16" font-weight="600" fill="#0f172a">'
        f'{_escape(title)}</text>'
        f'<text x="{PADDING}" y="46" font-family="system-ui, sans-serif" '
        f'font-size="11" fill="#64748b">{_escape(unit)}</text>'
        f'{body}'
        f'<text x="{PADDING}" y="{HEIGHT - 12}" '
        f'font-family="system-ui, sans-serif" font-size="10" '
        f'fill="#94a3b8">{_escape(footnote)}</text>'
        f'</svg>')


def _bar_svg(values: list[tuple[str, float, str]]) -> str:
    top = max(abs(v) for _l, v, _d in values) or 1.0
    left = PADDING + 170
    span = WIDTH - left - PADDING - 90
    height = 18
    gap = 8
    parts: list[str] = []
    for index, (label, value, shown) in enumerate(values[:12]):
        y = 70 + index * (height + gap)
        width = max(1.0, abs(value) / top * span)
        parts.append(
            f'<text x="{PADDING}" y="{y + 13}" '
            f'font-family="system-ui, sans-serif" font-size="12" '
            f'fill="#334155">{_escape(label[:26])}</text>'
            f'<rect x="{left}" y="{y}" width="{width:.2f}" '
            f'height="{height}" fill="#0f172a" rx="2"/>'
            f'<text x="{left + width + 8:.2f}" y="{y + 13}" '
            f'font-family="system-ui, sans-serif" font-size="11" '
            f'fill="#0f172a">{_escape(shown)}</text>')
    return "".join(parts)


def _line_svg(values: list[tuple[str, float, str]]) -> str:
    numbers = [v for _l, v, _d in values]
    top, bottom = max(numbers), min(numbers)
    span = (top - bottom) or 1.0
    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 70
    step = (right - left) / max(1, len(values) - 1)
    coordinates = []
    for index, (_label, value, _shown) in enumerate(values):
        x = left + index * step
        y = floor - (value - bottom) / span * (floor - ceiling)
        coordinates.append(f"{x:.2f},{y:.2f}")
    first, last = values[0], values[-1]
    return (
        f'<polyline fill="none" stroke="#0f172a" stroke-width="2" '
        f'points="{" ".join(coordinates)}"/>'
        f'<text x="{left}" y="{floor + 18}" '
        f'font-family="system-ui, sans-serif" font-size="11" '
        f'fill="#64748b">{_escape(first[0])}</text>'
        f'<text x="{right}" y="{floor + 18}" text-anchor="end" '
        f'font-family="system-ui, sans-serif" font-size="11" '
        f'fill="#64748b">{_escape(last[0])}</text>'
        f'<text x="{right}" y="{ceiling - 8}" text-anchor="end" '
        f'font-family="system-ui, sans-serif" font-size="11" '
        f'fill="#0f172a">{_escape(last[2])}</text>')


def _scatter_svg(values: list[tuple[str, float, str]]) -> str:
    """One mark per point, positioned rather than joined.

    A scatter drawn as a line asserts an ordering between neighbours that a
    scatter is specifically not claiming.
    """
    numbers = [v for _l, v, _d in values]
    top, bottom = max(numbers), min(numbers)
    span = (top - bottom) or 1.0
    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 70
    step = (right - left) / max(1, len(values) - 1)
    parts = []
    for index, (_label, value, _shown) in enumerate(values):
        x = left + index * step
        y = floor - (value - bottom) / span * (floor - ceiling)
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" '
                     f'fill="#0f172a" fill-opacity="0.75"/>')
    parts.append(
        f'<text x="{left}" y="{floor + 18}" '
        f'font-family="system-ui, sans-serif" font-size="11" '
        f'fill="#64748b">{_escape(values[0][0])}</text>'
        f'<text x="{right}" y="{floor + 18}" text-anchor="end" '
        f'font-family="system-ui, sans-serif" font-size="11" '
        f'fill="#64748b">{_escape(values[-1][0])}</text>')
    return "".join(parts)


def _waterfall_svg(values: list[tuple[str, float, str]]) -> str:
    """A bridge: each bar starts where the last one finished.

    Drawn as ordinary bars -- which is what happened -- a bridge loses the
    one thing it is for, which is showing how a total was arrived at.
    """
    running, stops = 0.0, [0.0]
    for _label, value, _shown in values:
        running += value
        stops.append(running)
    top, bottom = max(stops), min(stops)
    span = (top - bottom) or 1.0
    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 78
    width = (right - left) / max(1, len(values)) * 0.62
    step = (right - left) / max(1, len(values))

    def height_of(amount: float) -> float:
        return floor - (amount - bottom) / span * (floor - ceiling)

    parts = []
    for index, (label, value, shown) in enumerate(values):
        x = left + index * step + (step - width) / 2
        start, end = height_of(stops[index]), height_of(stops[index + 1])
        top_y, bar = min(start, end), max(2.0, abs(end - start))
        parts.append(
            f'<rect x="{x:.2f}" y="{top_y:.2f}" width="{width:.2f}" '
            f'height="{bar:.2f}" rx="2" '
            f'fill="{"#0f172a" if value >= 0 else "#b45309"}"/>'
            f'<text x="{x + width / 2:.2f}" y="{floor + 18}" '
            f'text-anchor="middle" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#64748b">{_escape(label[:12])}</text>'
            f'<text x="{x + width / 2:.2f}" y="{top_y - 5:.2f}" '
            f'text-anchor="middle" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#0f172a">{_escape(shown)}</text>')
        if index:
            previous = height_of(stops[index])
            joined = left + (index - 1) * step + (step + width) / 2
            parts.append(
                f'<line x1="{joined:.2f}" y1="{previous:.2f}" '
                f'x2="{x:.2f}" y2="{previous:.2f}" '
                f'stroke="#cbd5e1" stroke-width="1"/>')
    return "".join(parts)


#: A categorical ramp for stacked and grouped forms. Ordered so adjacent
#: segments stay distinguishable; the first is the same slate the
#: single-series forms use, so one chart does not look like another product.
_SERIES_COLOURS = ("#0f172a", "#0ea5e9", "#b45309", "#15803d", "#7c3aed",
                   "#be123c", "#0891b2", "#a16207")


def _colour(index: int) -> str:
    return _SERIES_COLOURS[index % len(_SERIES_COLOURS)]


def _legend(series: list[str], y: int = 60) -> str:
    """Which colour is which measure. A stack without one is a puzzle."""
    parts, x = [], PADDING
    for index, name in enumerate(series):
        parts.append(
            f'<rect x="{x}" y="{y - 8}" width="9" height="9" rx="2" '
            f'fill="{_colour(index)}"/>'
            f'<text x="{x + 13}" y="{y}" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#475569">{_escape(name[:18])}</text>')
        x += 22 + 6 * min(len(name), 18)
    return "".join(parts)


def _stacked_svg(points: list[dict[str, Any]], series: list[str], *,
                 normalise: bool = False) -> str:
    """Segments piled to a total, per category.

    `normalise` makes every column sum to 100%, which is how a delinquency
    BAND MIX is read: the question is what share sits in each bucket, not
    how big the book got.
    """
    rows = _numbers(points, series)
    if not rows:
        raise ExportUnavailable("This chart has no plotted points.")
    totals = [sum(abs(v) for v in values) or 1.0 for _l, values in rows]
    top = 1.0 if normalise else (max(totals) or 1.0)

    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 78
    step = (right - left) / max(1, len(rows))
    width = step * 0.68
    parts = [_legend(series)]
    for index, (label, values) in enumerate(rows):
        x = left + index * step + (step - width) / 2
        base = totals[index] if normalise else 1.0
        y = floor
        for order, value in enumerate(values):
            share = (abs(value) / base) if normalise else abs(value)
            height = share / top * (floor - ceiling)
            if height <= 0:
                continue
            y -= height
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" '
                f'height="{height:.2f}" fill="{_colour(order)}"/>')
        parts.append(
            f'<text x="{x + width / 2:.2f}" y="{floor + 18}" '
            f'text-anchor="middle" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#64748b">{_escape(label[:12])}</text>')
    return "".join(parts)


def _stacked_100_svg(points: list[dict[str, Any]], series: list[str]) -> str:
    return _stacked_svg(points, series, normalise=True)


def _grouped_svg(points: list[dict[str, Any]], series: list[str]) -> str:
    """Bars side by side, per category. The comparison is WITHIN a group."""
    rows = _numbers(points, series)
    if not rows:
        raise ExportUnavailable("This chart has no plotted points.")
    top = max((abs(v) for _l, values in rows for v in values), default=0) or 1.0

    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 78
    step = (right - left) / max(1, len(rows))
    band = step * 0.72
    width = band / max(1, len(series))
    parts = [_legend(series)]
    for index, (label, values) in enumerate(rows):
        start = left + index * step + (step - band) / 2
        for order, value in enumerate(values):
            height = abs(value) / top * (floor - ceiling)
            x = start + order * width
            parts.append(
                f'<rect x="{x:.2f}" y="{floor - height:.2f}" '
                f'width="{max(1.0, width - 1):.2f}" height="{height:.2f}" '
                f'fill="{_colour(order)}"/>')
        parts.append(
            f'<text x="{start + band / 2:.2f}" y="{floor + 18}" '
            f'text-anchor="middle" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#64748b">{_escape(label[:12])}</text>')
    return "".join(parts)


def _combo_svg(points: list[dict[str, Any]], series: list[str]) -> str:
    """Volumes as bars, a RATE as a line on its own scale.

    The one form a credit pack cannot do without: exposure in SAR millions
    and a delinquency rate in percent do not share an axis, and plotting
    them on one makes the rate a flat line along the floor.
    """
    rows = _numbers(points, series)
    if not rows or len(series) < 2:
        raise ExportUnavailable(
            "A combo chart needs two measures: bars first, then the line.")
    bar_top = max((abs(v[0]) for _l, v in rows), default=0) or 1.0
    line_values = [v[1] for _l, v in rows]
    line_top, line_bottom = max(line_values), min(line_values)
    line_span = (line_top - line_bottom) or 1.0

    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 78
    step = (right - left) / max(1, len(rows))
    width = step * 0.56
    parts = [_legend(series)]
    coordinates = []
    for index, (label, values) in enumerate(rows):
        centre = left + index * step + step / 2
        height = abs(values[0]) / bar_top * (floor - ceiling)
        parts.append(
            f'<rect x="{centre - width / 2:.2f}" y="{floor - height:.2f}" '
            f'width="{width:.2f}" height="{height:.2f}" rx="2" '
            f'fill="{_colour(0)}" fill-opacity="0.85"/>'
            f'<text x="{centre:.2f}" y="{floor + 18}" text-anchor="middle" '
            f'font-family="system-ui, sans-serif" font-size="10" '
            f'fill="#64748b">{_escape(label[:12])}</text>')
        y = floor - (values[1] - line_bottom) / line_span * (floor - ceiling)
        coordinates.append(f"{centre:.2f},{y:.2f}")
    parts.append(
        f'<polyline fill="none" stroke="{_colour(1)}" stroke-width="2" '
        f'points="{" ".join(coordinates)}"/>')
    return "".join(parts)


#: Forms drawn from EVERY named measure rather than the first one.
_MULTI_SERIES = {"stacked_bar": _stacked_svg,
                 "stacked_bar_100": _stacked_100_svg,
                 "grouped_bar": _grouped_svg,
                 "combo": _combo_svg,
                 "bubble": None}      # replaced below, after _bubble_svg


def _bubble_svg(points: list[dict[str, Any]], series: list[str]) -> str:
    """Two measures against each other, a third as the area."""
    rows = _numbers(points, series)
    if not rows or len(series) < 2:
        raise ExportUnavailable(
            "A bubble chart needs two measures: the axis, then the size.")
    xs = [v[0] for _l, v in rows]
    sizes = [abs(v[1]) for _l, v in rows]
    x_top, x_bottom = max(xs), min(xs)
    x_span = (x_top - x_bottom) or 1.0
    size_top = max(sizes) or 1.0

    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 78
    step = (right - left) / max(1, len(rows))
    parts = [_legend(series)]
    for index, (label, values) in enumerate(rows):
        cx = left + index * step + step / 2
        cy = floor - (values[0] - x_bottom) / x_span * (floor - ceiling)
        # AREA, not radius: a radius proportional to the value exaggerates
        # a big bubble by its square.
        radius = 4 + 18 * ((abs(values[1]) / size_top) ** 0.5)
        parts.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{radius:.2f}" '
            f'fill="{_colour(0)}" fill-opacity="0.45" stroke="{_colour(0)}"/>'
            f'<text x="{cx:.2f}" y="{floor + 18}" text-anchor="middle" '
            f'font-family="system-ui, sans-serif" font-size="10" '
            f'fill="#64748b">{_escape(label[:10])}</text>')
    return "".join(parts)


_MULTI_SERIES["bubble"] = _bubble_svg


def _area_svg(values: list[tuple[str, float, str]]) -> str:
    """A line with the ground filled in: a level over time, not a rate."""
    line = _line_svg(values)
    numbers = [v for _l, v, _d in values]
    top, bottom = max(numbers), min(numbers)
    span = (top - bottom) or 1.0
    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 70
    step = (right - left) / max(1, len(values) - 1)
    points = [f"{left:.2f},{floor:.2f}"]
    for index, (_label, value, _shown) in enumerate(values):
        x = left + index * step
        y = floor - (value - bottom) / span * (floor - ceiling)
        points.append(f"{x:.2f},{y:.2f}")
    points.append(f"{left + (len(values) - 1) * step:.2f},{floor:.2f}")
    return (f'<polygon fill="#0f172a" fill-opacity="0.12" '
            f'points="{" ".join(points)}"/>' + line)


def _step_line_svg(values: list[tuple[str, float, str]]) -> str:
    """A level that holds until it changes -- a limit, a cut-off, a rate."""
    numbers = [v for _l, v, _d in values]
    top, bottom = max(numbers), min(numbers)
    span = (top - bottom) or 1.0
    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 70
    step = (right - left) / max(1, len(values) - 1)
    points = []
    previous_y = None
    for index, (_label, value, _shown) in enumerate(values):
        x = left + index * step
        y = floor - (value - bottom) / span * (floor - ceiling)
        if previous_y is not None:
            points.append(f"{x:.2f},{previous_y:.2f}")
        points.append(f"{x:.2f},{y:.2f}")
        previous_y = y
    return (f'<polyline fill="none" stroke="#0f172a" stroke-width="2" '
            f'points="{" ".join(points)}"/>')


def _histogram_svg(values: list[tuple[str, float, str]]) -> str:
    """Counts per band, drawn touching, because the axis is continuous.

    The gap between bars is what says "these categories are separate". A
    DPD distribution has no gaps -- 10-19 abuts 20-29 -- and drawing one
    invites a reader to see groups that are not there.
    """
    top = max((abs(v) for _l, v, _d in values), default=0) or 1.0
    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 78
    width = (right - left) / max(1, len(values))
    parts = []
    for index, (label, value, shown) in enumerate(values):
        height = abs(value) / top * (floor - ceiling)
        x = left + index * width
        parts.append(
            f'<rect x="{x:.2f}" y="{floor - height:.2f}" '
            f'width="{max(1.0, width - 0.5):.2f}" height="{height:.2f}" '
            f'fill="#0f172a" fill-opacity="0.82"/>'
            f'<text x="{x + width / 2:.2f}" y="{floor + 18}" '
            f'text-anchor="middle" font-family="system-ui, sans-serif" '
            f'font-size="9" fill="#64748b">{_escape(label[:9])}</text>')
    return "".join(parts)


def _slice_svg(values: list[tuple[str, float, str]], *, hole: float) -> str:
    """Shares of one whole. `hole` makes it a donut."""
    total = sum(abs(v) for _l, v, _d in values)
    if total <= 0:
        raise ExportUnavailable("A share chart needs a non-zero total.")
    cx, cy = WIDTH / 2, (HEIGHT + 20) / 2
    radius = min(HEIGHT - 150, 120)
    angle = -90.0
    parts = []
    for index, (label, value, shown) in enumerate(values):
        sweep = abs(value) / total * 360.0
        end = angle + sweep
        large = 1 if sweep > 180 else 0
        x1 = cx + radius * math.cos(math.radians(angle))
        y1 = cy + radius * math.sin(math.radians(angle))
        x2 = cx + radius * math.cos(math.radians(end))
        y2 = cy + radius * math.sin(math.radians(end))
        parts.append(
            f'<path d="M {cx:.2f} {cy:.2f} L {x1:.2f} {y1:.2f} '
            f'A {radius:.2f} {radius:.2f} 0 {large} 1 {x2:.2f} {y2:.2f} Z" '
            f'fill="{_colour(index)}"/>')
        middle = math.radians(angle + sweep / 2)
        label_r = radius * (0.66 if hole <= 0 else (1 + hole) / 2)
        parts.append(
            f'<text x="{cx + label_r * math.cos(middle):.2f}" '
            f'y="{cy + label_r * math.sin(middle):.2f}" '
            f'text-anchor="middle" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#ffffff">{_escape(label[:10])}</text>')
        angle = end
    if hole > 0:
        parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" '
                     f'r="{radius * hole:.2f}" fill="#ffffff"/>')
    return "".join(parts)


def _pie_svg(values: list[tuple[str, float, str]]) -> str:
    return _slice_svg(values, hole=0.0)


def _donut_svg(values: list[tuple[str, float, str]]) -> str:
    return _slice_svg(values, hole=0.55)


def _matrix_svg(matrix: dict[str, Any]) -> str:
    """The grid, with every cell shaded by its share of the largest.

    A migration matrix read as forty-nine rows is read by scrolling. Read
    as a grid it is one picture: the diagonal is everything that stayed
    put, and the mass either side of it is the movement.
    """
    rows = [str(r) for r in (matrix.get("rows") or [])]
    columns = [str(c) for c in (matrix.get("columns") or [])]
    cells = matrix.get("cells") or {}
    if not rows or not columns:
        raise ExportUnavailable("This matrix has no axes to draw.")

    numbers = [abs(float(v)) for v in cells.values()
               if isinstance(v, (int, float))]
    top = max(numbers) if numbers else 1.0
    left, head = PADDING + 92, 78
    span = WIDTH - left - PADDING
    depth = HEIGHT - head - 52
    box_w, box_h = span / len(columns), depth / len(rows)
    square = bool(matrix.get("square"))

    parts = []
    for c, column in enumerate(columns):
        parts.append(
            f'<text x="{left + c * box_w + box_w / 2:.2f}" y="{head - 6}" '
            f'text-anchor="middle" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#64748b">{_escape(column[:8])}</text>')
    for r, row in enumerate(rows):
        y = head + r * box_h
        parts.append(
            f'<text x="{left - 8}" y="{y + box_h / 2 + 4:.2f}" '
            f'text-anchor="end" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#64748b">{_escape(row[:12])}</text>')
        for c, column in enumerate(columns):
            raw = cells.get(f"{row}|{column}")
            x = left + c * box_w
            if isinstance(raw, (int, float)):
                # A single hue by intensity. Sequential, because these are
                # magnitudes with no natural midpoint to diverge around.
                weight = min(1.0, abs(float(raw)) / top) if top else 0.0
                fill, opacity = "#0f172a", 0.08 + 0.84 * weight
            else:
                # ABSENT IS NOT ZERO. No row for this pair means the query
                # never reported that move; a shaded zero would assert it.
                fill, opacity = "#f8fafc", 1.0
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{box_w - 1:.2f}" '
                f'height="{box_h - 1:.2f}" fill="{fill}" '
                f'fill-opacity="{opacity:.3f}"/>')
            if square and rows[r] == columns[c]:
                parts.append(
                    f'<rect x="{x:.2f}" y="{y:.2f}" width="{box_w - 1:.2f}" '
                    f'height="{box_h - 1:.2f}" fill="none" '
                    f'stroke="#0ea5e9" stroke-width="1.5"/>')
    return "".join(parts)


def _box_svg(boxes: list[dict[str, Any]]) -> str:
    """Min, Q1, median, Q3, max -- the five numbers, already computed.

    Nothing is derived here. The quartiles were computed server-side beside
    the points, for the same reason every other published figure is: a
    number a reader acts on is not calculated in a renderer.
    """
    def number(box: dict[str, Any], name: str) -> float:
        try:
            return float(box.get(name))
        except (TypeError, ValueError):
            return 0.0

    spread = [number(b, n) for b in boxes
              for n in ("minimum", "maximum")]
    if not spread:
        raise ExportUnavailable("This box plot has nothing to summarise.")
    top, bottom = max(spread), min(spread)
    scale = (top - bottom) or 1.0
    left, right = PADDING + 10, WIDTH - PADDING
    floor, ceiling = HEIGHT - 60, 78
    step = (right - left) / max(1, len(boxes))
    width = step * 0.46

    def height_of(amount: float) -> float:
        return floor - (amount - bottom) / scale * (floor - ceiling)

    parts = []
    for index, box in enumerate(boxes):
        centre = left + index * step + step / 2
        x = centre - width / 2
        low, q1 = height_of(number(box, "minimum")), height_of(
            number(box, "q1"))
        med, q3 = height_of(number(box, "median")), height_of(
            number(box, "q3"))
        high = height_of(number(box, "maximum"))
        parts.append(
            f'<line x1="{centre:.2f}" y1="{high:.2f}" x2="{centre:.2f}" '
            f'y2="{low:.2f}" stroke="#94a3b8" stroke-width="1"/>'
            f'<rect x="{x:.2f}" y="{min(q1, q3):.2f}" width="{width:.2f}" '
            f'height="{max(2.0, abs(q1 - q3)):.2f}" rx="2" '
            f'fill="#0f172a" fill-opacity="0.16" stroke="#0f172a"/>'
            f'<line x1="{x:.2f}" y1="{med:.2f}" x2="{x + width:.2f}" '
            f'y2="{med:.2f}" stroke="#0f172a" stroke-width="2"/>'
            f'<text x="{centre:.2f}" y="{floor + 18}" text-anchor="middle" '
            f'font-family="system-ui, sans-serif" font-size="10" '
            f'fill="#64748b">'
            f'{_escape(str(box.get("label") or "")[:14])}</text>')
    return "".join(parts)


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def filename(*, kind: str, run_id: str, suffix: str) -> str:
    """A name that says what the file is without opening it."""
    return f"creditprobe-{kind}-{run_id[:12]}.{suffix}"


__all__ = ["ALL_ROWS", "DISPLAYED_ROWS", "ExportUnavailable", "FORMAT_CSV",
           "FORMAT_MARKDOWN", "FORMAT_SVG", "Lineage", "MEDIA_TYPES",
           "ROW_MODES", "analysis_markdown", "chart_svg", "filename",
           "lineage_for", "table_csv"]
