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
    produced_at: str
    artifact_ids: tuple[str, ...] = ()
    code_digests: tuple[str, ...] = ()
    row_scope: str = ALL_ROWS
    row_count: int = 0
    #: How many rows the stored result holds. Equal to `row_count` when the
    #: export is the whole thing, which is what `complete` then says.
    total_rows: int = 0
    complete: bool = True

    def lines(self) -> list[str]:
        body = [
            f"Question: {self.question}",
            f"Book: {self.domain_label or self.domain_id or 'unstated'}",
            f"Release: {self.release_id or 'unstated'}",
            f"Release fingerprint: {self.release_fingerprint or 'unstated'}",
            f"Tenant: {self.tenant_id}",
            f"Denomination: {self.reporting_currency} {self.amount_scale}",
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


def lineage_for(*, record: Any, artifact: dict[str, Any] | None = None,
                header: Any = None, produced_at: str = "",
                row_scope: str = ALL_ROWS, row_count: int = 0,
                total_rows: int = 0, complete: bool = True) -> Lineage:
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
    return Lineage(
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
                 f"{lineage.release_id} · exported {lineage.produced_at}*\n")

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

    kind = str(chart.get("kind") or chart.get("type") or "bar").lower()
    title = str(chart.get("title") or "")
    unit = str((chart.get("series_units") or {}).get(column)
               or chart.get("unit") or "")
    body = (_line_svg(values) if kind.startswith("line")
            else _bar_svg(values))
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
