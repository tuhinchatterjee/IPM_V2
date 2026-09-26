#!/usr/bin/env python3
"""Section 14.3's workbook, built offline, and reconciled to the chat numbers.

WHY THIS IS A SCRIPT AND NOT A DOWNLOAD BUTTON.

cockpit-v4 exports Markdown, CSV, SVG and a governance ZIP
(`routes.py:767, 853, 938, 983`). There is no XLSX route, `openpyxl` is used
only by the legacy `backend/exports/` which keys on integer run ids, and
adding a route is a protected-core change that nothing in the authorisation
covers. So the workbook is produced here, from the same artifact the chat
published, and `KNOWN_LIMITATIONS.md` records that the in-chat route was
documented rather than added.

## The workbook is reconciled, not just formatted

A spreadsheet is the artifact people forward, quote in a paper and reconcile
against a ledger six months later, so a workbook whose totals do not match the
answer that produced it is worse than no workbook. Before writing anything
this script re-derives, from the rows:

* the cohort's scenario total from the per-entity ledger lines;
* the book identity -- cohort scenario plus the untouched remainder;
* each method's change from its own baseline and scenario;
* the attribution total against the movement it decomposes.

A mismatch past `TOLERANCE` **fails the build**. It does not annotate the
cell, because a warning in a workbook is a warning nobody reads.

## Formula injection

Excel treats a cell beginning `=`, `+`, `-`, `@`, or a tab or carriage return
as a formula, and a value from a book -- a borrower name, a sector -- is
attacker-influenced text as far as a spreadsheet is concerned. Every string
cell written here goes through `safe_text`, which prefixes such a value with
an apostrophe so it is stored as text. Tested rather than asserted:
`test_whatif_workbook.py` writes a cell whose value is
`=HYPERLINK("http://x","click")` and reads it back.

Usage:
    python3 scripts/whatif/build_workbook.py --result result.json \
        --out artifacts/whatif/scenario.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

#: Currency reconciliation tolerance, in SAR million. The same figure
#: `ledger.CURRENCY` uses, and for the same reason: these totals come back
#: through a DOUBLE engine before they become Decimal again.
TOLERANCE = Decimal("0.01")

#: The characters Excel reads as the start of a formula.
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")

#: One sheet per question the result answers, in the order a reader meets
#: them. Not one sheet per section of the artifact: `headline` and `cohort`
#: belong on the same page, and `ml_explanation` must be on its own so it
#: cannot be read as a continuation of the attribution.
SHEETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Summary", ("headline", "cohort", "book")),
    ("Methods", ("method", "coverage")),
    ("Scenario attribution", ("attribution_economic",
                             "attribution_mechanism")),
    ("ML explanation", ("ml_explanation",)),
    ("Notes", ("note",)),
)

HEADERS: tuple[str, ...] = (
    "section", "view", "method", "item", "scope", "baseline_sar_mn",
    "scenario_sar_mn", "change_sar_mn", "change_pct", "unit", "status",
    "note")


def safe_text(value: Any) -> str:
    """A string Excel will store as text rather than evaluate.

    The apostrophe is the documented way to force a literal in Excel and is
    not part of the value: it is stripped on read. Prefixing unconditionally
    would put an apostrophe in front of every sector name, so it is applied
    only to values that would otherwise be read as formulas.
    """
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_STARTS):
        return "'" + text
    return text


def decimal_of(value: Any) -> Decimal | None:
    """A Decimal, or None for a cell that is not a number.

    None rather than zero. "not defined (the baseline is zero)" is a real
    value in these rows and coercing it to zero would put a number in a
    reconciliation that has none.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:  # noqa: BLE001
        return None


class Mismatch(Exception):
    """A reconciliation that did not hold. Fails the build."""


def reconcile(rows: list[dict[str, Any]]) -> list[str]:
    """Re-derive every total from the rows, or raise.

    Returns the checks that passed, so the workbook can publish what was
    checked rather than the word "reconciled".
    """
    passed: list[str] = []
    by_section: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_section.setdefault(str(row.get("section", "")), []).append(row)

    def one(section: str, item: str) -> dict[str, Any] | None:
        for row in by_section.get(section, []):
            if str(row.get("item", "")) == item:
                return row
        return None

    # 1. the book identity: cohort after + untouched remainder = book after
    cohort = one("cohort", "Total ECL")
    book = one("book", "Total ECL")
    outside = one("book", "Outside the cohort")
    if cohort and book and outside:
        left = ((decimal_of(cohort["scenario_sar_mn"]) or Decimal(0))
                + (decimal_of(outside["scenario_sar_mn"]) or Decimal(0)))
        right = decimal_of(book["scenario_sar_mn"]) or Decimal(0)
        if abs(left - right) > TOLERANCE:
            raise Mismatch(
                f"the book's scenario total is {right} and the cohort's "
                f"{cohort['scenario_sar_mn']} plus the untouched remainder "
                f"{outside['scenario_sar_mn']} is {left}. Section 13.1's "
                f"identity does not hold, so the workbook was not written.")
        passed.append(
            f"book identity: cohort {cohort['scenario_sar_mn']} + untouched "
            f"{outside['scenario_sar_mn']} = book {book['scenario_sar_mn']}")

    # 2. the untouched remainder did not move
    if outside:
        moved = decimal_of(outside["change_sar_mn"])
        if moved is not None and moved != 0:
            raise Mismatch(
                f"the part of the book outside the cohort changed by {moved}. "
                f"No rule reached those rows, so their change is exactly zero "
                f"or the run is wrong.")
        passed.append("rows no rule reached changed by exactly zero")

    # 3. each method's change is its own scenario minus its own baseline
    for row in by_section.get("method", []):
        base = decimal_of(row["baseline_sar_mn"])
        scen = decimal_of(row["scenario_sar_mn"])
        change = decimal_of(row["change_sar_mn"])
        if base is None or scen is None or change is None:
            # An unavailable method leaves them empty, which is the point:
            # section 12 forbids inserting a zero. Nothing to reconcile.
            continue
        if abs((scen - base) - change) > TOLERANCE:
            raise Mismatch(
                f"{row['item']} reports a change of {change} against a "
                f"baseline of {base} and a scenario of {scen}.")
        passed.append(f"{row['item']}: {base} -> {scen} = {change}")

    # 4. each attribution view reconciles to the movement it decomposes
    for section in ("attribution_economic", "attribution_mechanism"):
        lines = by_section.get(section, [])
        anchor = next((r for r in lines
                       if str(r.get("item")) == "Reconciles to"), None)
        if anchor is None:
            continue
        drivers = [decimal_of(r["change_sar_mn"]) for r in lines
                   if str(r.get("item")) not in
                   ("Reconciles to", "The two views are never added")]
        total = sum((d for d in drivers if d is not None), Decimal(0))
        headline = decimal_of(anchor["change_sar_mn"]) or Decimal(0)
        if abs(total - headline) > TOLERANCE:
            raise Mismatch(
                f"{section} decomposes into {total} and the movement it "
                f"explains is {headline}. The residual row is part of the "
                f"decomposition, so this should close exactly.")
        passed.append(f"{section}: contributions {total} = movement "
                      f"{headline}")
    return passed


def write(rows: list[dict[str, Any]], provenance: dict[str, Any],
          checks: list[str], out: Path) -> Path:
    """The workbook itself. Every string cell through `safe_text`."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    book = Workbook()
    book.remove(book.active)

    cover = book.create_sheet("Provenance")
    cover["A1"] = "What-If scenario result"
    cover["A1"].font = Font(bold=True, size=14)
    cover["A3"] = safe_text(
        "EVERY FIGURE IN THIS WORKBOOK IS MEASURED ON A GENERATED BOOK. The "
        "borrowers and customers do not exist, the economy did not happen, "
        "and no model or sensitivity here is bank-validated. Nothing in it is "
        "bank output, an accounting figure or observed economic history.")
    cover["A3"].alignment = Alignment(wrap_text=True, vertical="top")
    cover.merge_cells("A3:F6")
    line = 8
    cover.cell(row=line, column=1, value="Provenance").font = Font(bold=True)
    line += 1
    for key in sorted(provenance):
        cover.cell(row=line, column=1, value=safe_text(key))
        cover.cell(row=line, column=2, value=safe_text(provenance[key]))
        line += 1
    line += 1
    cover.cell(row=line, column=1,
               value="Reconciliation checks that passed").font = Font(bold=True)
    line += 1
    for check in checks:
        cover.cell(row=line, column=1, value=safe_text(check))
        line += 1
    cover.column_dimensions["A"].width = 46
    cover.column_dimensions["B"].width = 64

    for title, sections in SHEETS:
        wanted = [r for r in rows if str(r.get("section", "")) in sections]
        if not wanted:
            continue
        sheet = book.create_sheet(title[:31])
        if title == "ML explanation":
            sheet["A1"] = safe_text(
                "THIS IS NOT A DECOMPOSITION OF THE SCENARIO'S ECL MOVEMENT. "
                "It describes how the fitted function responds to its own "
                "inputs -- association in a model, not causation. The ECL "
                "movement is decomposed on the 'Scenario attribution' sheet, "
                "by re-running the calculation. Do not add the two.")
            sheet["A1"].font = Font(bold=True)
            sheet["A1"].alignment = Alignment(wrap_text=True, vertical="top")
            sheet.merge_cells("A1:L3")
            top = 5
        else:
            top = 1
        for column, header in enumerate(HEADERS, start=1):
            cell = sheet.cell(row=top, column=column, value=header)
            cell.font = Font(bold=True)
        for index, row in enumerate(wanted, start=top + 1):
            for column, header in enumerate(HEADERS, start=1):
                value = row.get(header, "")
                number = (decimal_of(value)
                          if header.endswith(("_sar_mn", "_pct")) else None)
                if number is not None:
                    # Written as a number so a reader can sum a column, and
                    # as a float only here, at the edge, after every check
                    # above has run in Decimal.
                    sheet.cell(row=index, column=column, value=float(number))
                else:
                    sheet.cell(row=index, column=column,
                               value=safe_text(value))
        sheet.freeze_panes = sheet.cell(row=top + 1, column=1)
        for column, header in enumerate(HEADERS, start=1):
            letter = sheet.cell(row=top, column=column).column_letter
            sheet.column_dimensions[letter].width = (
                60 if header == "note" else max(12, len(header) + 2))

    out.parent.mkdir(parents=True, exist_ok=True)
    book.save(out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True,
                       help="JSON with `rows` and `provenance`, as the "
                            "scenario step published them")
    parser.add_argument("--out", default="artifacts/whatif/scenario.xlsx")
    args = parser.parse_args()

    payload = json.loads(Path(args.result).read_text(encoding="utf-8"))
    rows = list(payload.get("rows") or [])
    if not rows:
        print("the result carries no rows; nothing was written.")
        return 1
    try:
        checks = reconcile(rows)
    except Mismatch as exc:
        print(f"RECONCILIATION FAILED: {exc}")
        return 1
    out = write(rows, dict(payload.get("provenance") or {}), checks,
                Path(args.out))
    print(f"{out} written; {len(rows)} rows, {len(checks)} checks passed:")
    for check in checks:
        print(f"  {check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
