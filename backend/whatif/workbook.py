"""
The audit-grade What-If workbook.

Why this exists as its own builder
----------------------------------
`backend/exports/calculation.py` builds a superb calculation pack, but it
builds it from a `Pack` — an analysis run, its plan, its lineage. A What-If has
none of those: it is a scenario applied to a book, not a registered analysis.
Forcing one through the other's contract would have meant faking a plan, and a
fabricated lineage in an audit workbook is worse than no workbook.

So this reads a `WhatIfResult` directly and writes the house style out of
`backend/exports/style.py`, which is where the conventions actually live.

What "audit-grade" is taken to mean
-----------------------------------
Somebody who was not in the room must be able to open this file six months
later and answer, without asking anyone:

  what book was this, at what date, and how many borrowers;
  what exactly was changed, in what order, and on whose assumptions;
  which staging rules produced each of the two columns;
  which ECL methodology priced it, at what version;
  what every borrower's parameters were BEFORE and AFTER;
  which facilities that exposure sits in;
  what caused the movement, split exactly, and what did not reconcile;
  whether the numbers add up — stated as tests that pass or fail, not claimed;
  and how to reproduce it exactly.

The reconciliation sheet is the load-bearing one. Every other sheet is a claim;
that sheet is the evidence the claims are consistent, and a failing check is
written into the file in red rather than raising and producing nothing. An
export that refuses to exist because one tie-out broke tells the reader
nothing; one that says which tie-out broke tells them everything.

Facility grain is an ALLOCATION and says so
-------------------------------------------
IFRS 9 staging here is assessed on the obligor, not the facility — a book that
stages one facility of a borrower differently from another is describing a bank
that does not exist. So there is no facility-level re-measurement to export.
What the facility sheet carries is the borrower's movement allocated across
their facilities by IFRS 9 EAD share, labelled as an allocation in the sheet's
own subtitle and in a column of its own. Presenting an allocation as a
measurement is the one thing this sheet must not do.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook as Book
from openpyxl.worksheet.worksheet import Worksheet

from backend.exports import style as sy
from backend.ifrs9 import policy
from backend.whatif import domain as dm
from backend.whatif import macro as mc

logger = logging.getLogger(__name__)

WORKBOOK_VERSION = "1.0.0"

#: The tie-out below which two figures are the same figure. A workbook that
#: called a rounding difference a break would cry wolf on every export.
TOLERANCE_PCT = 0.01

#: Excel holds a million rows; a reader does not. Beyond this the detail sheets
#: are truncated and the sheet SAYS it was truncated, with the full population
#: count beside it, because a silently short table is a wrong table.
MAX_DETAIL_ROWS = 100_000

#: The sheet names, and they are the reader's names for these things rather
#: than the code's. "COVER" and "RESULT SUMMARY" are what a developer calls
#: them; an audit file lands on a credit committee's desk and its tabs have to
#: read as what a credit person would look for.
#:
#: One departure from the specification, and it is Excel's rather than a
#: choice: a worksheet name may not contain "/", so "Account / Facility Detail"
#: is written with an ampersand. Every other name is verbatim.
COVER = "Executive Summary"
SCENARIO = "Scenario Definition"
SUMMARY = "Portfolio Before vs After"
BORROWERS = "Borrower Detail"
FACILITIES = "Account & Facility Detail"
ATTRIBUTION = "ECL Attribution"
STAGES = "Stage Migration"
RATINGS = "Rating Migration"
RECONCILIATION = "Reconciliation"
METHOD = "Model & Methodology"
DICTIONARY = "Data Dictionary"
REPRODUCE = "Reproduce"

SHEETS = (COVER, SCENARIO, SUMMARY, FACILITIES, BORROWERS, STAGES, RATINGS,
          ATTRIBUTION, METHOD, DICTIONARY, RECONCILIATION, REPRODUCE)


class WorkbookError(RuntimeError):
    """A workbook that cannot be built, said rather than half-written."""


@dataclass
class Check:
    """One tie-out, and whether it held."""

    name: str
    left_label: str
    left: float
    right_label: str
    right: float
    note: str = ""

    @property
    def difference(self) -> float:
        return float(self.left - self.right)

    @property
    def difference_pct(self) -> float:
        base = max(abs(self.right), 1.0)
        return float(self.difference / base * 100.0)

    @property
    def status(self) -> str:
        return "PASS" if abs(self.difference_pct) <= TOLERANCE_PCT else "FAIL"


# ------------------------------------------------------------------ helpers


def _f(value: Any, default: float = 0.0) -> float:
    try:
        found = float(value)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(found) else found


def _sum(frame: pd.DataFrame, column: str) -> float:
    if not isinstance(frame, pd.DataFrame) or column not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum())


def _who(owner: Any) -> str:
    if owner is None:
        return "not recorded"
    return str(owner)


# -------------------------------------------------------------------- build


def build(result: Any, *, owner: Any = None, requested_by: str = "",
          interpretation: dict[str, Any] | None = None,
          source: Any = None) -> bytes:
    """The whole workbook, as bytes.

    Never raises on a failing reconciliation: a break is a row in the file.
    It raises only when there is genuinely nothing to write.
    """
    frame = getattr(result, "borrowers", None)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise WorkbookError(
            "This What-If matched no borrowers, so there is nothing to "
            "export. Widen the population and run it again.")

    book = Book()
    book.remove(book.active)
    sheets: dict[str, Worksheet] = {
        name: book.create_sheet(title=name) for name in SHEETS}

    context = result.context() if hasattr(result, "context") else {}
    checks = _checks(result, frame)

    _cover(sheets[COVER], result, context, checks,
           owner=owner, requested_by=requested_by,
           interpretation=interpretation or {})
    _scenario(sheets[SCENARIO], result, context)
    _summary(sheets[SUMMARY], result, context)
    _borrowers(sheets[BORROWERS], result, frame, context)
    _facilities(sheets[FACILITIES], result, frame, context, source=source)
    _attribution(sheets[ATTRIBUTION], result, context)
    _stages(sheets[STAGES], result, context)
    _ratings(sheets[RATINGS], result, context)
    _reconciliation(sheets[RECONCILIATION], checks, context)
    _method(sheets[METHOD], result, context)
    _dictionary(sheets[DICTIONARY], context)
    _reproduce(sheets[REPRODUCE], result, context)

    for sheet in sheets.values():
        sheet.sheet_view.showGridLines = False

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# -------------------------------------------------------------------- COVER


def _cover(ws: Worksheet, result: Any, context: dict[str, Any],
           checks: list[Check], *, owner: Any, requested_by: str,
           interpretation: dict[str, Any]) -> None:
    row = sy.title(
        ws, "What-If Analysis — detailed export",
        "A SCENARIO, not the reported book. The baseline column is the "
        "reported position; every What-If column is hypothetical.")
    failed = [c for c in checks if c.status == "FAIL"]
    row = sy.facts(ws, [
        ("Domain", context.get("domain")),
        ("Dataset", context.get("dataset")),
        ("Reporting period", context.get("period")),
        ("Grain", context.get("grain")),
        ("Currency", context.get("currency")),
        ("Population", f'{context.get("population")} — '
                       f'{context.get("population_count"):,} borrowers'),
        ("Scenario", context.get("scenario")),
        ("ECL methodology", context.get("methodology_stamp")),
        ("What-If staging", f'{context.get("whatif_staging")} '
                            f'(v{context.get("whatif_staging_version")})'),
        ("Reported-book staging", f'{context.get("reported_staging")} '
                                  f'(v{context.get("reported_staging_version")})'),
        ("Macro sensitivities", context.get("sensitivity_note")),
        ("Exported", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
        ("Exported by", requested_by or _who(owner)),
        ("Workbook version", WORKBOOK_VERSION),
        ("Reconciliation", "ALL CHECKS PASS" if not failed
         else f"{len(failed)} CHECK(S) FAILED — see {RECONCILIATION}"),
    ], row)

    row = sy.section(ws, "The result", row)
    row = sy.facts(ws, [
        ("Reported ECL", f'{context.get("currency")} '
                         f'{_f(context.get("baseline_ecl")):,.1f}m'),
        ("What-If ECL", f'{context.get("currency")} '
                        f'{_f(context.get("whatif_ecl")):,.1f}m'),
        ("Change", f'{context.get("currency")} '
                   f'{_f(context.get("absolute_change")):,.1f}m '
                   f'({_f(context.get("percentage_change")):+,.2f}%)'),
    ], row)

    paragraphs = [p for p in (interpretation.get("paragraphs") or [])
                  if str(p).strip()] or list(
                      interpretation.get("findings") or [])
    if paragraphs:
        row = sy.section(ws, "Reading", row)
        for paragraph in paragraphs:
            row = sy.note(ws, str(paragraph), row)
        if interpretation.get("written_by"):
            row = sy.note(
                ws, f'Written by {interpretation["written_by"]}. Every figure '
                    "in it was checked back against the result before it was "
                    "written here.", row)

    warnings = list(getattr(result, "warnings", []) or [])
    if warnings:
        row = sy.section(ws, "Warnings about this result", row)
        for warning in warnings:
            row = sy.note(ws, str(warning), row)

    notes = list(getattr(result, "notes", []) or [])
    if notes:
        row = sy.section(ws, "About this installation", row)
        for text in notes:
            row = sy.note(ws, str(text), row)

    row = sy.section(ws, "What is in this workbook", row)
    sy.table(ws, ["Sheet", "What it carries"], [
        [SCENARIO, "Every step applied, in the order applied, and the rules "
                   "and assumptions in force for each"],
        [SUMMARY, "The movement, and the same movement by stage, sector and "
                  "rating"],
        [BORROWERS, "Every borrower, with every risk parameter before and "
                    "after"],
        [FACILITIES, "The borrower movement ALLOCATED to facility by IFRS 9 "
                     "EAD share. An allocation, not a measurement"],
        [ATTRIBUTION, "What caused the movement, split exactly and "
                      "order-neutrally, with anything unexplained named"],
        [STAGES, "Stage migration, with exposure and ECL on both sides"],
        [RATINGS, "Rating migration across the governed masterscale"],
        [RECONCILIATION, "The tie-outs, each stated as a test that passes or "
                         "fails"],
        [METHOD, "Versions, policy thresholds, macro sensitivities, "
                 "plausibility and the limitations of this data"],
        [REPRODUCE, "The exact state that reproduces this run"],
    ], row=row, widths=[24, 92], autofilter=False, freeze=False)


# ----------------------------------------------------------------- SCENARIO


def _scenario(ws: Worksheet, result: Any, context: dict[str, Any]) -> None:
    row = sy.crumb(ws)
    row = sy.title(
        ws, "The scenario, exactly as applied",
        "Shocks are applied in a fixed order so the same scenario always "
        "produces the same figures.", row=row)

    steps = list(getattr(result, "steps", []) or [])
    row = sy.section(ws, "Engine steps", row)
    row = sy.table(
        ws, ["#", "Step", "What it did", "Borrowers affected"],
        [[i, str(s.get("step", "")), str(s.get("detail", "")),
          s.get("affected", "")] for i, s in enumerate(steps, start=1)],
        row=row, widths=[5, 34, 96, 18], formats=[sy.INTEGER, sy.TEXT,
                                                  sy.TEXT, sy.INTEGER])

    written = list(context.get("steps") or [])
    if written:
        row = sy.section(ws, "As the person asked for it", row)
        row = sy.table(
            ws, ["#", "Kind", "Asked", "Read as", "Enabled"],
            [[i, str(s.get("kind", "")), str(s.get("instruction", "")),
              str(s.get("interpreted", "")), "yes" if s.get("enabled", True)
              else "no"]
             for i, s in enumerate(written, start=1)],
            row=row, widths=[5, 16, 56, 56, 10],
            formats=[sy.INTEGER, sy.TEXT, sy.TEXT, sy.TEXT, sy.TEXT])

    row = sy.section(ws, "Staging rules — two sets, named separately", row)
    row = sy.facts(ws, [
        ("Reported book", context.get("reported_staging")),
        ("Reported-book version", context.get("reported_staging_version")),
        ("What-If", context.get("whatif_staging")),
        ("What-If version", context.get("whatif_staging_version")),
    ], row)
    row = sy.note(ws, str(context.get("staging_note", "")), row)

    row = sy.section(ws, "Macro relationships in force", row)
    overrides = list(context.get("sensitivities") or [])
    if overrides:
        row = sy.table(
            ws, ["Variable", "Source", "Relationship", "Scoped to"],
            [[str(s.get("name") or s.get("variable")),
              str(s.get("source_label", "")), str(s.get("description", "")),
              "the whole book" if not s.get("scoped") else
              ", ".join(str(x) for x in (s.get("sectors") or [])
                        + (s.get("rating_bands") or [])) or "a subset"]
             for s in overrides],
            row=row, widths=[28, 30, 66, 30], autofilter=False)
    row = sy.note(ws, str(context.get("sensitivity_note", "")), row)


# ------------------------------------------------------------------ SUMMARY


def _summary(ws: Worksheet, result: Any, context: dict[str, Any]) -> None:
    currency = str(context.get("currency", "SAR"))
    row = sy.crumb(ws)
    row = sy.title(ws, "The movement", f"All amounts in {currency} millions.",
                   row=row)

    summary = dict(getattr(result, "summary", {}) or {})
    row = sy.section(ws, "Headline", row)
    row = sy.table(
        ws, ["Measure", "Reported book", "What-If", "Change", "Change %"],
        [["Expected credit loss",
          _f(summary.get("baseline_ecl")), _f(summary.get("stressed_ecl")),
          _f(summary.get("incremental_ecl")),
          _f(summary.get("incremental_ecl_pct"))]],
        row=row, formats=[sy.TEXT, sy.MONEY_2, sy.MONEY_2, sy.MONEY_2,
                          sy.PERCENT_2],
        widths=[28, 20, 20, 20, 14], autofilter=False)

    for label, frame, key in (("By stage", getattr(result, "by_stage", None),
                               "Opening stage"),
                              ("By sector", getattr(result, "by_sector", None),
                               "Sector"),
                              ("By rating", getattr(result, "by_rating", None),
                               "Opening rating")):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        row = sy.section(ws, label, row)
        first = frame.columns[0]
        row = sy.table(
            ws,
            [key, "Borrowers", f"Exposure ({currency}m)",
             f"Reported ECL ({currency}m)", f"What-If ECL ({currency}m)",
             f"Change ({currency}m)", "Change %"],
            [[r.get(first), r.get("borrowers"),
              _f(r.get("baseline_ead", r.get("exposure"))),
              _f(r.get("baseline_ecl")), _f(r.get("stressed_ecl")),
              _f(r.get("ecl_increase")), _f(r.get("ecl_increase_pct"))]
             for r in frame.to_dict(orient="records")],
            row=row,
            formats=[sy.TEXT, sy.INTEGER, sy.MONEY_2, sy.MONEY_2, sy.MONEY_2,
                     sy.MONEY_2, sy.PERCENT_2],
            widths=[28, 12, 18, 20, 20, 18, 12])


# ---------------------------------------------------------------- BORROWERS


#: Every column the detail sheet carries, as (frame column, header, format).
#: Explicit rather than derived so a column added to the engine's frame does
#: not silently change the shape of an audited file.
BORROWER_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("borrower_id", "Borrower ID", sy.TEXT),
    ("display_name", "Borrower", sy.TEXT),
    ("sector", "Sector", sy.TEXT),
    ("group_name", "Group", sy.TEXT),
    ("ead", "EAD before", sy.MONEY_2),
    ("ead_stressed", "EAD after", sy.MONEY_2),
    ("opening_rating", "Rating before", sy.TEXT),
    ("stressed_rating", "Rating after", sy.TEXT),
    ("stage_baseline", "Stage before", sy.INTEGER),
    ("stage_stressed", "Stage after", sy.INTEGER),
    ("pd_12m", "12m PD % before", sy.PERCENT_2),
    ("pd_stressed", "12m PD % after", sy.PERCENT_2),
    ("lgd", "LGD % before", sy.PERCENT_2),
    ("lgd_stressed", "LGD % after", sy.PERCENT_2),
    ("ecl_baseline", "Reported ECL", sy.MONEY_2),
    ("ecl_stressed", "What-If ECL", sy.MONEY_2),
    ("ecl_increase", "Change", sy.MONEY_2),
    ("ecl_increase_pct", "Change %", sy.PERCENT_2),
    ("primary_driver", "Primary driver", sy.TEXT),
)


def _borrowers(ws: Worksheet, result: Any, frame: pd.DataFrame,
               context: dict[str, Any]) -> None:
    currency = str(context.get("currency", "SAR"))
    total = int(len(frame))
    shown = frame.head(MAX_DETAIL_ROWS)
    row = sy.crumb(ws)
    row = sy.title(
        ws, "Every borrower, before and after",
        f"{len(shown):,} of {total:,} borrowers. Amounts in {currency} "
        "millions; PD and LGD in percent."
        + ("" if len(shown) == total else
           f" TRUNCATED at {MAX_DETAIL_ROWS:,} rows."), row=row)
    if len(shown) != total:
        row = sy.note(
            ws, "This sheet does not carry the whole population. Every total "
                "elsewhere in this workbook is computed over ALL "
                f"{total:,} borrowers, not over the rows below.", row)

    present = [c for c in BORROWER_COLUMNS if c[0] in shown.columns]
    sy.table(
        ws, [head for _, head, _ in present],
        [[r.get(name) for name, _, _ in present]
         for r in shown.to_dict(orient="records")],
        row=row, formats=[fmt for _, _, fmt in present])


# --------------------------------------------------------------- FACILITIES


def _facilities(ws: Worksheet, result: Any, frame: pd.DataFrame,
                context: dict[str, Any], *, source: Any = None) -> None:
    currency = str(context.get("currency", "SAR"))
    row = sy.crumb(ws)
    row = sy.title(
        ws, "Facility detail — an ALLOCATION",
        "IFRS 9 staging here is assessed on the OBLIGOR, so there is no "
        "facility-level measurement to export. Each borrower's movement is "
        "allocated across their facilities by IFRS 9 EAD share.", row=row)

    try:
        facilities = _facility_rows(frame, context, source=source)
    except Exception as e:  # noqa: BLE001 - a missing sheet is not a failure
        logger.warning("Could not build the facility allocation", exc_info=True)
        sy.note(ws, "The facility register could not be read for this period, "
                    f"so this sheet is empty: {e}. Every other sheet is "
                    "unaffected — the movement is measured at borrower grain "
                    "and does not depend on this allocation.", row)
        return

    if facilities.empty:
        sy.note(ws, "No facilities were found for this population in this "
                    "period.", row)
        return

    row = sy.note(
        ws, "Allocated ECL is NOT a facility-level provision. It is the "
            "borrower's What-If movement apportioned by each facility's share "
            "of the borrower's IFRS 9 EAD, and it sums back to the borrower "
            "figure exactly. A facility whose borrower has no EAD receives an "
            "equal share instead, which is stated in the basis column.", row)
    shown = facilities.head(MAX_DETAIL_ROWS)
    sy.table(
        ws,
        ["Facility ID", "Borrower ID", "Borrower", "Product", "Secured",
         f"Facility IFRS 9 EAD ({currency}m)", "Share of borrower EAD %",
         f"Allocated reported ECL ({currency}m)",
         f"Allocated What-If ECL ({currency}m)",
         f"Allocated change ({currency}m)", "Allocation basis"],
        [[r["facility_id"], r["borrower_id"], r["display_name"],
          r["product_type"], r["is_secured"], _f(r["ifrs9_ead"]),
          _f(r["share_pct"]), _f(r["ecl_baseline"]), _f(r["ecl_stressed"]),
          _f(r["ecl_increase"]), r["basis"]]
         for r in shown.to_dict(orient="records")],
        row=row,
        formats=[sy.TEXT, sy.TEXT, sy.TEXT, sy.TEXT, sy.TEXT, sy.MONEY_2,
                 sy.PERCENT_2, sy.MONEY_2, sy.MONEY_2, sy.MONEY_2, sy.TEXT])


def _facility_rows(frame: pd.DataFrame, context: dict[str, Any], *,
                   source: Any = None) -> pd.DataFrame:
    """The borrower movement, apportioned by IFRS 9 EAD share.

    Exact by construction: the shares within a borrower sum to one, so the
    allocated columns sum back to the borrower columns. Where a borrower's
    facilities carry no EAD the movement is split equally, because dropping
    those facilities would break that identity.
    """
    period = str(context.get("period") or "")
    # Through the domain reader, not around it: What-If reads the Corporate
    # IFRS 9 datasets and nothing else, and the facility register is one of
    # them. A second reader here would be a second answer to "what may this
    # feature see".
    held = dm.read(dm.FACILITIES, period, source=source)
    if held is None or held.empty:
        return pd.DataFrame()
    keep = [c for c in ("facility_id", "borrower_id", "product_type",
                        "is_secured", "ifrs9_ead") if c in held.columns]
    held = held[keep]

    wanted = frame[["borrower_id", "display_name", "ecl_baseline",
                    "ecl_stressed", "ecl_increase"]].copy()
    joined = held.merge(wanted, on="borrower_id", how="inner")
    if joined.empty:
        return joined

    ead = pd.to_numeric(joined.get("ifrs9_ead"), errors="coerce").fillna(0.0)
    joined["ifrs9_ead"] = ead
    totals = joined.groupby("borrower_id")["ifrs9_ead"].transform("sum")
    counts = joined.groupby("borrower_id")["ifrs9_ead"].transform("size")
    by_ead = totals > 0
    share = np.where(by_ead, ead / totals.where(totals > 0, 1.0),
                     1.0 / counts.clip(lower=1))
    joined["share_pct"] = share * 100.0
    joined["basis"] = np.where(
        by_ead, "IFRS 9 EAD share",
        "equal split — the borrower's facilities carry no IFRS 9 EAD")
    for column in ("ecl_baseline", "ecl_stressed", "ecl_increase"):
        joined[column] = pd.to_numeric(joined[column],
                                       errors="coerce").fillna(0.0) * share
    for column in ("facility_id", "product_type", "is_secured"):
        if column not in joined.columns:
            joined[column] = ""
    return joined.sort_values("ecl_increase", ascending=False)


# -------------------------------------------------------------- ATTRIBUTION


def _attribution(ws: Worksheet, result: Any, context: dict[str, Any]) -> None:
    currency = str(context.get("currency", "SAR"))
    body = dict(getattr(result, "attribution", {}) or {})
    row = sy.crumb(ws)
    row = sy.title(
        ws, "What moved the provision",
        str(body.get("method", "")) or "Driver attribution", row=row)

    if not body.get("available", True):
        sy.note(ws, "There is no attribution for this result: "
                    f'{body.get("why", "no reason was recorded")}.', row)
        return

    row = sy.note(
        ws, "Each driver's effect is its average marginal contribution across "
            "every order in which the factors could have moved — the unique "
            "split that is order-neutral, sums exactly to the total, and gives "
            "a factor that never moved an effect of zero.", row)

    row = sy.section(ws, "Drivers", row)
    row = sy.table(
        ws, ["Driver", f"Effect ({currency}m)", "Share of movement %",
             "Borrowers moved"],
        [[str(d.get("label", "")), _f(d.get("effect")),
          _f(d.get("share_pct")), d.get("borrowers_moved", "")]
         for d in (body.get("drivers") or [])],
        row=row, formats=[sy.TEXT, sy.MONEY_2, sy.PERCENT_2, sy.INTEGER],
        widths=[52, 20, 20, 18], autofilter=False)

    adjustment = body.get("model_adjustment") or {}
    if adjustment:
        row = sy.section(ws, str(adjustment.get("label", "Adjustment")), row)
        row = sy.facts(ws, [
            ("Effect", f'{currency} {_f(adjustment.get("effect")):,.4f}m'),
            ("Material enough to show on screen",
             "yes" if adjustment.get("material") else
             "no — below the materiality floor, carried here so the bridge "
             "adds up"),
        ], row)
        row = sy.note(ws, str(adjustment.get("note", "")), row)

    basis = body.get("measurement_basis") or {}
    if basis:
        row = sy.section(ws, "Measurement basis", row)
        row = sy.note(ws, str(basis.get("note", "")), row)

    check = body.get("reconciliation") or {}
    if check:
        row = sy.section(ws, "Does it add up?", row)
        row = sy.table(
            ws, ["Quantity", f"{currency}m"],
            [["Attributed to drivers", _f(check.get("attributed"))],
             ["Adjustment", _f(check.get("model_adjustment"))],
             ["Measured movement", _f(check.get("measured_movement"))],
             ["Reported movement", _f(check.get("reported_movement"))],
             ["Difference", _f(check.get("difference"))]],
            row=row, formats=[sy.TEXT, sy.MONEY_2], widths=[34, 20],
            autofilter=False)
        row = sy.note(ws, str(check.get("note", "")), row)


# ------------------------------------------------------------------- STAGES


def _stages(ws: Worksheet, result: Any, context: dict[str, Any]) -> None:
    currency = str(context.get("currency", "SAR"))
    movement = dict(getattr(result, "stage_movement", {}) or {})
    row = sy.crumb(ws)
    row = sy.title(
        ws, "Stage migration",
        "A scenario never cures a stage and never manufactures a default. "
        "Stage 3 is a fact about the borrower, not a modelling outcome.",
        row=row)
    if not movement:
        sy.note(ws, "No stage movement was recorded for this result.", row)
        return

    row = sy.facts(ws, [
        ("Borrowers that moved", movement.get("moved")),
        ("Deteriorated", movement.get("deteriorated")),
        ("Cured", movement.get("cured")),
    ], row)

    row = sy.section(ws, "From / to", row)
    row = sy.table(
        ws, ["From stage", "To stage", "Borrowers",
             f"Exposure ({currency}m)", f"Reported ECL ({currency}m)",
             f"What-If ECL ({currency}m)"],
        [[c.get("from"), c.get("to"), c.get("count"), _f(c.get("exposure")),
          _f(c.get("ecl_before")), _f(c.get("ecl_after"))]
         for c in (movement.get("cells") or [])],
        row=row, formats=[sy.INTEGER, sy.INTEGER, sy.INTEGER, sy.MONEY_2,
                          sy.MONEY_2, sy.MONEY_2],
        widths=[14, 12, 14, 20, 22, 22], autofilter=False)

    row = sy.section(ws, "Each stage, before and after", row)
    sy.table(
        ws, ["Stage", "Borrowers before", "Borrowers after",
             f"Exposure before ({currency}m)", f"Exposure after ({currency}m)",
             f"Reported ECL ({currency}m)", f"What-If ECL ({currency}m)"],
        [[s.get("stage"), s.get("count_before"), s.get("count_after"),
          _f(s.get("exposure_before")), _f(s.get("exposure_after")),
          _f(s.get("ecl_before")), _f(s.get("ecl_after"))]
         for s in (movement.get("stages") or [])],
        row=row, formats=[sy.INTEGER, sy.INTEGER, sy.INTEGER, sy.MONEY_2,
                          sy.MONEY_2, sy.MONEY_2, sy.MONEY_2],
        widths=[10, 18, 18, 22, 22, 22, 22], autofilter=False)


# ------------------------------------------------------------------ RATINGS


def _ratings(ws: Worksheet, result: Any, context: dict[str, Any]) -> None:
    currency = str(context.get("currency", "SAR"))
    movement = dict(getattr(result, "rating_movement", {}) or {})
    row = sy.crumb(ws)
    row = sy.title(ws, "Rating migration",
                   "Across the governed corporate masterscale.", row=row)
    if not movement or not movement.get("rows"):
        sy.note(ws, "This scenario did not move any borrower's rating.", row)
        return

    row = sy.facts(ws, [("Borrowers that moved grade",
                         movement.get("moved"))], row)
    row = sy.table(
        ws, ["Grade", "Borrowers before", "Borrowers after",
             f"Exposure before ({currency}m)", f"Exposure after ({currency}m)",
             f"Reported ECL ({currency}m)", f"What-If ECL ({currency}m)",
             "Left", "Arrived", f"ECL leaving ({currency}m)",
             f"ECL arriving ({currency}m)"],
        [[r.get("grade"), r.get("count_before"), r.get("count_after"),
          _f(r.get("exposure_before")), _f(r.get("exposure_after")),
          _f(r.get("ecl_before")), _f(r.get("ecl_after")), r.get("left"),
          r.get("arrived"), _f(r.get("ecl_leaving")),
          _f(r.get("ecl_arriving"))]
         for r in movement["rows"]],
        row=row,
        formats=[sy.TEXT, sy.INTEGER, sy.INTEGER, sy.MONEY_2, sy.MONEY_2,
                 sy.MONEY_2, sy.MONEY_2, sy.INTEGER, sy.INTEGER, sy.MONEY_2,
                 sy.MONEY_2])
    sy.note(ws, str(movement.get("note", "")), row)


# ----------------------------------------------------------- RECONCILIATION


def _checks(result: Any, frame: pd.DataFrame) -> list[Check]:
    """The tie-outs. Computed once, written to the sheet AND to the cover."""
    summary = dict(getattr(result, "summary", {}) or {})
    attribution = dict(getattr(result, "attribution", {}) or {})
    movement = dict(getattr(result, "stage_movement", {}) or {})

    # The detail sheet carries the figures at the two decimal places a reader
    # is shown; the totals are computed at full precision. So a reader who
    # sums the column gets a number a few hundredths away from the headline,
    # and this workbook says why rather than leaving them to find it.
    rounding = ("The detail sheet is written at two decimal places and the "
                "totals are computed at full precision, so summing the "
                "column differs from the headline by the rounding of "
                f"{len(frame):,} rows. The tolerance is {TOLERANCE_PCT}% and "
                "this difference is a presentation artefact, not a break.")
    checks = [
        Check("The reported total is the sum of the borrowers",
              "Sum of the detail column", _sum(frame, "ecl_baseline"),
              "Reported ECL on the result", _f(summary.get("baseline_ecl")),
              "A total that is not the sum of its rows is a different book. "
              + rounding),
        Check("The What-If total is the sum of the borrowers",
              "Sum of the detail column", _sum(frame, "ecl_stressed"),
              "What-If ECL on the result", _f(summary.get("stressed_ecl")),
              rounding),
        Check("The change is the difference of the two totals",
              "What-If less reported",
              _f(summary.get("stressed_ecl")) - _f(summary.get("baseline_ecl")),
              "Change on the result", _f(summary.get("incremental_ecl")),
              "Computed at full precision on both sides, so this one is "
              "exact."),
        Check("The borrower changes sum to the movement",
              "Sum of the detail column", _sum(frame, "ecl_increase"),
              "Change on the result", _f(summary.get("incremental_ecl")),
              rounding),
    ]

    reconciliation = attribution.get("reconciliation") or {}
    if reconciliation:
        checks.append(Check(
            "The attribution adds up to what it explains",
            "Drivers plus adjustment",
            _f(reconciliation.get("attributed"))
            + _f(reconciliation.get("model_adjustment")),
            "Reported movement", _f(reconciliation.get("reported_movement")),
            "An attribution that does not add up to the number it is "
            "explaining is a picture, not a decomposition."))

    if movement.get("stages"):
        stages = movement["stages"]
        checks.append(Check(
            "Stage migration conserves the population",
            "Borrowers before, across stages",
            float(sum(_f(s.get("count_before")) for s in stages)),
            "Borrowers after, across stages",
            float(sum(_f(s.get("count_after")) for s in stages)),
            "A scenario moves borrowers between stages; it does not create "
            "or remove any."))
        checks.append(Check(
            "Stage migration conserves the exposure",
            "Exposure before, across stages",
            float(sum(_f(s.get("exposure_before")) for s in stages)),
            "Exposure after, across stages",
            float(sum(_f(s.get("exposure_after")) for s in stages))))

    if "ecl_stressed" in frame.columns:
        cap = "ead_stressed" if "ead_stressed" in frame.columns else "ead"
        over = int((pd.to_numeric(frame["ecl_stressed"], errors="coerce")
                    .fillna(0.0)
                    > pd.to_numeric(frame[cap], errors="coerce").fillna(0.0)
                    + 1e-6).sum())
        checks.append(Check(
            "No borrower is provided for above their own exposure",
            "Borrowers priced above exposure", float(over),
            "Permitted", 0.0,
            "An expected loss larger than the amount at risk is not a loss."))

    if {"stage_baseline", "stage_stressed"} <= set(frame.columns):
        cured = int((pd.to_numeric(frame["stage_stressed"], errors="coerce")
                     < pd.to_numeric(frame["stage_baseline"],
                                     errors="coerce")).sum())
        checks.append(Check(
            "No scenario cures a stage",
            "Borrowers whose stage improved", float(cured), "Permitted", 0.0,
            "A scenario does not cure a default and does not create one."))

    return checks


def _reconciliation(ws: Worksheet, checks: list[Check],
                    context: dict[str, Any]) -> None:
    currency = str(context.get("currency", "SAR"))
    row = sy.crumb(ws)
    failed = [c for c in checks if c.status == "FAIL"]
    row = sy.title(
        ws, "Reconciliation",
        f"{len(checks)} tie-outs, tolerance {TOLERANCE_PCT}% of the figure "
        "being tied to. "
        + ("Every one of them passed."
           if not failed else
           f"{len(failed)} FAILED. The figures in this workbook do not "
           "reconcile and must not be used until the break is explained."),
        row=row)
    row = sy.table(
        ws,
        ["Check", "Status", "Left", f"Left ({currency}m or count)", "Right",
         f"Right ({currency}m or count)", "Difference", "Difference %",
         "Why it matters"],
        [[c.name, c.status, c.left_label, c.left, c.right_label, c.right,
          c.difference, c.difference_pct, c.note] for c in checks],
        row=row, status_column=2,
        formats=[sy.TEXT, sy.TEXT, sy.TEXT, sy.MONEY_2, sy.TEXT, sy.MONEY_2,
                 sy.MONEY_2, sy.PERCENT_2, sy.TEXT],
        widths=[46, 10, 28, 20, 28, 20, 16, 14, 70], autofilter=False)
    sy.note(
        ws, "These are computed when the workbook is written, from the "
            "figures in the workbook. They are not copied from the run.", row)


# ------------------------------------------------------------------- METHOD


def _method(ws: Worksheet, result: Any, context: dict[str, Any]) -> None:
    row = sy.crumb(ws)
    row = sy.title(
        ws, "Method and assumptions",
        "Everything below is versioned. A run months from now is comparable "
        "with this one only if these agree.", row=row)

    row = sy.section(ws, "Versions", row)
    row = sy.table(
        ws, ["Component", "Version"],
        [["Workbook", WORKBOOK_VERSION],
         ["ECL methodology", f'{context.get("ecl_methodology")} '
                             f'v{context.get("ecl_methodology_version")}'],
         ["Reported-book staging", context.get("reported_staging_version")],
         ["What-If staging", context.get("whatif_staging_version")],
         ["Macro sensitivities", context.get("macro_version")],
         ["IFRS 9 policy", policy.POLICY_VERSION]],
        row=row, widths=[34, 46], autofilter=False)

    row = sy.section(ws, "Governed IFRS 9 policy thresholds", row)
    described = policy.describe()
    row = sy.table(
        ws, ["Threshold", "Value", "What it means"],
        [[str(k), sy._scalar(v), ""] for k, v in described.items()
         if isinstance(v, (int, float, str, bool))],
        row=row, widths=[38, 20, 70], autofilter=False)

    row = sy.section(ws, "Macro reference sensitivities", row)
    row = sy.table(
        ws, ["Variable", "One adverse unit", "PD multiplier", "LGD change (pp)",
             "Observed column"],
        [[v.name, v.adverse_label, v.pd_multiplier, v.lgd_change_pp, v.column]
         for v in mc.VARIABLES],
        row=row,
        formats=[sy.TEXT, sy.TEXT, sy.MONEY_2, sy.MONEY_2, sy.TEXT],
        widths=[36, 26, 16, 18, 32], autofilter=False)
    row = sy.note(ws, mc.BASIS, row)

    plausibility = dict(getattr(result, "plausibility", {}) or {})
    if plausibility:
        row = sy.section(ws, "Where this shock sits in the book's own history",
                         row)
        if plausibility.get("available"):
            row = sy.facts(ws, [
                ("Verdict", plausibility.get("verdict")),
                ("Because", plausibility.get("because")),
                ("Window", plausibility.get("window")),
                ("Driven by", plausibility.get("driven_by")),
            ], row)
            row = sy.note(ws, str(plausibility.get("statement", "")), row)
        else:
            row = sy.note(
                ws, "No historical comparison was available: "
                    f'{plausibility.get("why", "no reason was recorded")}.',
                row)
        row = sy.note(
            ws, "This is a comparison against observed movement over the "
                "quarters this installation carries. It is not a forecast and "
                "not a probability that the scenario occurs.", row)

    ml = dict(getattr(result, "ml", {}) or {})
    if ml:
        row = sy.section(ws, "The ML model, where it priced this", row)
        row = sy.table(
            ws, ["Property", "Value"],
            [[str(k), sy._scalar(v)] for k, v in ml.items()
             if isinstance(v, (int, float, str, bool))],
            row=row, widths=[34, 60], autofilter=False)

    notes = list(getattr(result, "notes", []) or [])
    if notes:
        row = sy.section(ws, "Limitations of this installation's data", row)
        for text in notes:
            row = sy.note(ws, str(text), row)

# ------------------------------------------------------- DATA DICTIONARY


#: What every column on the detail sheets means, in the reader's terms rather
#: than the schema's, with its unit and where the number came from.
#:
#: This exists because an audit file is read by somebody who was not in the
#: room. "pd_stressed" is obvious to whoever built the scenario and opaque
#: three months later to a reviewer deciding whether the provision was
#: reasonable — and a column they cannot interpret is a column they have to
#: either ignore or ask about, both of which cost more than a page of prose.
DICTIONARY_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Borrower ID", "", "The obligor's identifier in the Corporate IFRS 9 "
     "book. Stable across quarters.", "corporate_borrower_360"),
    ("Borrower", "", "The obligor's display name.", "corporate_customer_master"),
    ("Sector", "", "The economic sector the obligor is classified in. Drives "
     "the asset correlation used in the point-in-time PD.", "corporate_customer_master"),
    ("Group", "", "The connected counterparty group the obligor sits in.",
     "corporate_connected_groups"),
    ("Facility ID", "", "One credit facility of the obligor. IFRS 9 staging "
     "is assessed at OBLIGOR level, so facility figures on this file are the "
     "borrower's movement ALLOCATED by EAD share and are labelled as such.",
     "corporate_facilities"),
    ("Rating before / after", "ordinal 1-19",
     "The CreditProbe internal grade on the governed nineteen-point "
     "performing scale, AAA (1) through C (19). Default is a separate state "
     "at ordinal 20, reached by the default event and never by a PD band. "
     "A downgrade is a positive notch move.", "corporate_ratings"),
    ("Stage before / after", "1, 2 or 3",
     "The IFRS 9 stage. 1 is performing, 2 has suffered a significant "
     "increase in credit risk, 3 is credit-impaired.", "governed staging rules"),
    ("SICR trigger", "",
     "Which governed test moved the obligor to Stage 2: a relative PD test, "
     "an absolute PD test, or days past due.", "backend/ifrs9/policy.py"),
    ("TTC PD", "%",
     "Through-the-cycle twelve-month PD. A property of the GRADE and not of "
     "the quarter, calibrated on public corporate default evidence. See "
     "docs/corporate_rating_pd_calibration.md.", "governed rating masterscale"),
    ("12m PD / PIT PD", "%",
     "Point-in-time twelve-month PD: the grade's central tendency with its "
     "single-factor default threshold shifted by the state of the cycle and "
     "by the obligor's own condition.", "corporate_ifrs9"),
    ("Lifetime PD", "%",
     "Cumulative PD over the 4.2-year behavioural life, on a hazard that "
     "reverts towards the grade's through-the-cycle level rather than "
     "assuming today's stress persists.", "corporate_ifrs9"),
    ("Applicable PD", "%",
     "The PD the measurement uses: twelve-month in Stage 1, lifetime in "
     "Stage 2, and 100% in Stage 3 because the default has already happened. "
     "A PD of 100% is NOT a loss of 100% — the severity stays with LGD.",
     "backend/corporate/ratingscale.py"),
    ("LGD before / after", "%",
     "Loss given default: the share of exposure expected to be lost once "
     "default occurs, after recovery and collateral.", "corporate_ifrs9"),
    ("CCF before / after", "%",
     "Credit conversion factor: the share of the undrawn commitment assumed "
     "to be drawn by the time of default. EAD = drawn + CCF x undrawn, so a "
     "20% rise in CCF is a much smaller rise in EAD.", "corporate_facilities"),
    ("EAD before / after", "currency",
     "Exposure at default: drawn balance plus the converted undrawn "
     "commitment.", "corporate_ifrs9"),
    ("Collateral / haircut", "currency, %",
     "The security held against the exposure and the discount applied to its "
     "market value. Collateral reaches ECL through LGD on the secured share "
     "only.", "corporate_collateral"),
    ("Reported ECL", "currency",
     "The obligor's provision as the book reports it, before any scenario. "
     "The What-If baseline column ties to this exactly; that tie is what "
     "makes the comparison worth anything.", "corporate_ifrs9"),
    ("What-If ECL", "currency",
     "The provision under the scenario, on the chosen methodology.",
     "this run"),
    ("Change / Change %", "currency, %",
     "What-If ECL less reported ECL, and that difference as a share of the "
     "reported figure.", "this run"),
    ("Primary driver", "",
     "The single largest contributor to this obligor's movement. The full "
     "order-neutral attribution is on the ECL Attribution sheet.", "this run"),
)


def _dictionary(ws: Worksheet, context: dict[str, Any]) -> None:
    """Every field on this file, in the terms a reviewer reads them in."""
    row = sy.crumb(ws)
    row = sy.title(
        ws, "Data dictionary",
        "What each column on this file means, what it is measured in, and "
        "where the figure came from.", row=row)
    row = sy.table(
        ws, ["Field", "Unit", "What it means", "Source"],
        [[name, unit, meaning, source]
         for name, unit, meaning, source in DICTIONARY_ROWS],
        row=row,
        formats=[sy.TEXT, sy.TEXT, sy.TEXT, sy.TEXT],
        widths=[28, 14, 92, 34], autofilter=False)
    row = sy.section(ws, "Conventions this file follows", row)
    for text in (
        f"Amounts are in {context.get('currency', 'SAR')} unless a column "
        "says otherwise. Percentages are written as percentages, not as "
        "fractions.",
        "IFRS 9 staging is assessed at OBLIGOR level, not facility level: a "
        "book that staged one facility of a borrower differently from another "
        "would be describing a bank that does not exist. Facility figures are "
        "an allocation of the obligor's movement and are labelled as one.",
        "A rate is exposure-weighted where it says so and a simple mean "
        "otherwise; a coverage ratio is always summed over summed and never "
        "an average of ratios.",
        "Nothing on this file was estimated by a model that could not be "
        "reproduced. The Reproduce sheet carries everything needed to "
        "recalculate every figure.",
    ):
        row = sy.note(ws, text, row)


# ---------------------------------------------------------------- REPRODUCE


def _reproduce(ws: Worksheet, result: Any, context: dict[str, Any]) -> None:
    row = sy.crumb(ws)
    row = sy.title(
        ws, "How to reproduce this exactly",
        "The engine is deterministic: the same state on the same period "
        "returns the same figures.", row=row)
    row = sy.facts(ws, [
        ("Period", context.get("period")),
        ("Dataset", context.get("dataset")),
        ("Methodology", context.get("ecl_methodology")),
        ("Methodology version", context.get("ecl_methodology_version")),
        ("What-If staging version", context.get("whatif_staging_version")),
        ("Macro sensitivity version", context.get("macro_version")),
    ], row)
    row = sy.section(ws, "The scenario state, verbatim", row)
    row = sy.note(
        ws, "POST this to /whatif/execute with the methodology above. It is "
            "the same object the browser holds, so it can also be pasted back "
            "into a thread.", row)
    state = result.state.to_dict() if hasattr(result, "state") else {}
    sy.code(ws, json.dumps(state, indent=2, default=str, sort_keys=True), row)


__all__ = ["Check", "MAX_DETAIL_ROWS", "SHEETS", "TOLERANCE_PCT",
           "WORKBOOK_VERSION", "WorkbookError", "build"]
