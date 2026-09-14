"""The filtered book, as a workbook somebody can actually work in.

What "an Excel file" has to mean
--------------------------------
A `.csv` renamed, or an HTML table with an `.xls` extension, opens with a
warning and arrives as text: every exposure a string, every score a string,
no sorting, no sum, no pivot. The thing a credit officer asked for is a
workbook whose numbers are numbers.

So this writes a real XLSX through openpyxl, with numeric cells carrying
numeric values and a format, dates as dates, and a frozen, filtered header
row -- because the first thing anyone does with a downloaded book is sort it.

Two sheets, and why the second one
-----------------------------------
`Early Warning` is the complete filtered result -- every matching obligor, not
the page that happened to be on screen.

`View` is what was on the screen when the button was pressed: the as-of month,
every active filter, the sort, how many obligors matched out of how many
published, when it was exported and by whom. A spreadsheet that leaves the
building without its scope is a spreadsheet that will be read next quarter as
if it were the whole book. This sheet is the difference between a file and a
figure somebody can defend in a committee.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd

MIME = ("application/vnd.openxmlformats-officedocument"
        ".spreadsheetml.sheet")

#: Column headings a reader recognises, and how each is formatted. A column
#: missing from here is still exported -- with its stored name -- rather than
#: dropped, because a silently missing column is worse than an ugly heading.
HEADINGS: dict[str, tuple[str, str]] = {
    "customer_id": ("Customer ID", "@"),
    "customer_name": ("Customer", "@"),
    "segment": ("Segment", "@"),
    "exposure": ("Exposure (SAR m)", "#,##0.00"),
    "dpd": ("Days past due", "#,##0"),
    "ifrs9_stage": ("IFRS 9 stage", "#,##0"),
    "internal_rating": ("Internal rating", "@"),
    "ews_score": ("Early Warning score", "#,##0.0"),
    "ews_band": ("Early Warning band", "@"),
    "ta_score": ("Trigger & Accelerator score", "#,##0.0"),
    "ta_band": ("Trigger & Accelerator band", "@"),
    "classifier_score": ("Classifier score", "#,##0.0"),
    "classifier_band": ("Classifier band", "@"),
    "dominant_driver": ("Dominant driver", "@"),
    "signal_count_fired": ("Signals fired", "#,##0"),
    "overrides_applied": ("Overrides applied", "@"),
}


def _heading(column: str) -> str:
    return HEADINGS.get(column, (column.replace("_", " ").capitalize(), "@"))[0]


def _format(column: str) -> str:
    return HEADINGS.get(column, ("", "@"))[1]


def filename(meta: dict[str, Any]) -> str:
    """A name that says what the file is without being opened.

    `early-warning_2026-06_high-very-high_52-obligors.xlsx` tells a reader
    which month, which cut and how big it is from the download shelf. A
    timestamped `export(3).xlsx` tells them nothing, and three of them in a
    folder are indistinguishable.
    """
    parts = ["early-warning", str(meta.get("period") or "")]
    for chip in meta.get("chips") or []:
        value = re.sub(r"[^a-z0-9]+", "-",
                       str(chip.get("value", "")).lower()).strip("-")
        if value:
            parts.append(value[:40])
    count = meta.get("matched")
    if isinstance(count, int):
        parts.append(f"{count}-obligors")
    name = "_".join(p for p in parts if p)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-_")
    return f"{(name or 'early-warning')[:120]}.xlsx"


def workbook(frame: pd.DataFrame, meta: dict[str, Any], *,
             exported_by: str = "") -> bytes:
    """The two-sheet workbook, as bytes ready to be returned."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    sheet.title = "Early Warning"

    columns = list(frame.columns)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F3864")

    for index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=index, value=_heading(column))
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    for offset, (_, record) in enumerate(frame.iterrows(), start=2):
        for index, column in enumerate(columns, start=1):
            value = record[column]
            cell = sheet.cell(row=offset, column=index,
                              value=_cell_value(value))
            number_format = _format(column)
            if number_format and number_format != "@":
                cell.number_format = number_format

    sheet.freeze_panes = "A2"
    if len(frame):
        sheet.auto_filter.ref = (
            f"A1:{get_column_letter(len(columns))}{len(frame) + 1}")
    for index, column in enumerate(columns, start=1):
        width = max(len(_heading(column)) + 2, 12)
        sheet.column_dimensions[get_column_letter(index)].width = min(width, 34)

    _view_sheet(book.create_sheet("View"), meta, frame,
                exported_by=exported_by)

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _cell_value(value: Any) -> Any:
    """A real value, so a number arrives in Excel as a number.

    pandas types do not survive the trip: a numpy int64 raises on write, and
    a NaN becomes the string "nan" in a cell somebody will later sum.
    """
    if value is None:
        return None
    if isinstance(value, (bool,)):
        return bool(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and pd.isna(value):
            return None
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            pass
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _view_sheet(sheet: Any, meta: dict[str, Any], frame: pd.DataFrame, *,
                exported_by: str) -> None:
    from openpyxl.styles import Font

    bold = Font(bold=True)
    rows: list[tuple[str, Any]] = [
        ("As-of month", meta.get("period", "")),
        ("Obligors in this file", int(len(frame))),
        ("Obligors matching the filter", meta.get("matched", len(frame))),
        ("Obligors published in the month", meta.get("population", "")),
        ("Scope", meta.get("scope", "the whole book")),
        ("Sorted by", meta.get("sort_by", "")),
        ("Sort direction", "descending" if meta.get("descending", True)
         else "ascending"),
        ("Exported at (UTC)",
         datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
    ]
    if exported_by:
        rows.append(("Exported by", exported_by))

    basis = meta.get("trend_basis")
    if basis:
        rows.append(("Trend basis", basis))
    note = meta.get("trend_note")
    if note:
        rows.append(("Trend note", note))

    sheet.cell(row=1, column=1, value="What this file is").font = bold
    line = 2
    for label, value in rows:
        sheet.cell(row=line, column=1, value=label).font = bold
        sheet.cell(row=line, column=2, value=_cell_value(value))
        line += 1

    chips = meta.get("chips") or []
    line += 1
    sheet.cell(row=line, column=1, value="Filters applied").font = bold
    line += 1
    if not chips:
        sheet.cell(row=line, column=1, value="None — the whole book.")
    else:
        for chip in chips:
            sheet.cell(row=line, column=1, value=str(chip.get("label", "")))
            sheet.cell(row=line, column=2, value=str(chip.get("value", "")))
            line += 1

    line += 1
    sheet.cell(row=line, column=1, value="Basis").font = bold
    line += 1
    sheet.cell(row=line, column=1, value=(
        "Early Warning scores are produced by the CreditProbe Early Warning "
        "Framework Version 2 from the published monthly snapshots. They are "
        "descriptive of the evidence available at the as-of month, not a "
        "prediction, and are never an approval or decline rule."))

    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 72


__all__ = ["HEADINGS", "MIME", "filename", "workbook"]
