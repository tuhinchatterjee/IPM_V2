"""
A What-If result, as a workbook somebody can open in Excel and work in.

Why a workbook at all
---------------------
The screen answers the question that was asked. The workbook answers the ones
that come after it — which customers, which facilities, what were their
parameters before and after, what exactly did the engine do — and it answers
them in the tool the reader already uses for that. A screen that tried to hold
all of it would be unreadable, and a CSV of one table would lose the rest.

What is in it
-------------
Twelve sheets, in the order a reader works through them: what was run, how the
number moved, who is in the cohort, who is affected, what changed on each
customer and each facility, what the parameters did, and what the method
assumed. Sheets that do not apply to a scenario say so on their own face rather
than being dropped, so the workbook has the same shape every time and a reader
who knows where something lives keeps knowing.

What it will not do
-------------------
Recompute. Every figure here comes from the result that was already computed,
served and shown on the screen. A workbook that recalculated could disagree
with the page it was downloaded from, and then neither could be trusted.

Everything is SYNTHETIC demonstration data from a synthetic demonstration
engine. Not an ANB model, not an ANB policy, not a SAMA requirement, not
independently validated.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from backend.retail import ews_model as M

#: Column widths that fit the content rather than the header.
_WIDTH_MIN, _WIDTH_MAX = 10, 52

#: How a number is written, by what it is.
MONEY = '#,##0.00'
MONEY0 = '#,##0'
PERCENT = '0.00%'
RATIO = '0.0000'
COUNT = '#,##0'


def _styles(workbook: Any) -> dict[str, Any]:
    """One set of formats, made once and reused on every sheet."""
    return {
        "title": workbook.add_format({
            "bold": True, "font_size": 14, "font_color": "#1F3864"}),
        "note": workbook.add_format({
            "italic": True, "font_size": 9, "font_color": "#595959",
            "text_wrap": True, "valign": "top"}),
        "head": workbook.add_format({
            "bold": True, "bg_color": "#1F3864", "font_color": "#FFFFFF",
            "border": 1, "text_wrap": True, "valign": "vcenter"}),
        "text": workbook.add_format({"border": 1, "valign": "top"}),
        "wrap": workbook.add_format({
            "border": 1, "text_wrap": True, "valign": "top"}),
        "money": workbook.add_format({"border": 1, "num_format": MONEY}),
        "money0": workbook.add_format({"border": 1, "num_format": MONEY0}),
        "pct": workbook.add_format({"border": 1, "num_format": PERCENT}),
        "ratio": workbook.add_format({"border": 1, "num_format": RATIO}),
        "count": workbook.add_format({"border": 1, "num_format": COUNT}),
        "up": workbook.add_format({
            "border": 1, "num_format": MONEY, "font_color": "#9C0006",
            "bg_color": "#FFC7CE"}),
        "down": workbook.add_format({
            "border": 1, "num_format": MONEY, "font_color": "#006100",
            "bg_color": "#C6EFCE"}),
        "total": workbook.add_format({
            "bold": True, "top": 2, "num_format": MONEY}),
        "total_text": workbook.add_format({"bold": True, "top": 2}),
    }


def _format_for(column: str, styles: dict[str, Any]) -> Any:
    """The format a column takes, from what its name says it holds."""
    name = str(column).lower()
    if name.endswith("_pct") or name.endswith("_share") or "percent" in name:
        return styles["pct"]
    if name.endswith("_sar") or name.startswith("sar"):
        return styles["money"]
    if name.startswith("pd_") or name in ("lgd", "ccf", "coverage"):
        return styles["ratio"]
    if (name.endswith("_count") or name in ("customers", "accounts",
                                            "facilities", "rows")):
        return styles["count"]
    return styles["text"]


def _sheet(workbook: Any, styles: dict[str, Any], name: str, title: str,
           note: str = "") -> Any:
    """A sheet with its title and, where one helps, a sentence under it."""
    page = workbook.add_worksheet(name[:31])
    page.write(0, 0, title, styles["title"])
    if note:
        page.merge_range(1, 0, 1, 9, note, styles["note"])
        page.set_row(1, 28)
    return page


def _table(page: Any, styles: dict[str, Any], rows: list[dict[str, Any]],
           columns: list[str] | None, at: int, *,
           labels: dict[str, str] | None = None,
           empty: str = "Nothing to show for this scenario.") -> int:
    """One table, headed, bordered, frozen and sized to what it holds."""
    if not rows:
        page.write(at, 0, empty, styles["note"])
        return at + 2
    columns = columns or list(rows[0])
    labels = labels or {}
    widths = [len(str(labels.get(one, one))) for one in columns]

    for index, column in enumerate(columns):
        page.write(at, index, str(labels.get(column, column)), styles["head"])
    page.set_row(at, 30)

    for offset, row in enumerate(rows, start=1):
        for index, column in enumerate(columns):
            value = row.get(column)
            style = _format_for(column, styles)
            if value is None or value == "":
                page.write_blank(at + offset, index, None, styles["text"])
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                page.write_number(at + offset, index, float(value), style)
                widths[index] = max(widths[index], len(f"{value:,.2f}"))
            else:
                text = str(value)
                page.write_string(at + offset, index, text,
                                  styles["wrap"] if len(text) > 60
                                  else styles["text"])
                widths[index] = max(widths[index], min(len(text), _WIDTH_MAX))

    for index, width in enumerate(widths):
        page.set_column(index, index,
                        max(_WIDTH_MIN, min(width + 3, _WIDTH_MAX)))
    page.freeze_panes(at + 1, 0)
    page.autofilter(at, 0, at + len(rows), len(columns) - 1)
    return at + len(rows) + 3


def _pairs(page: Any, styles: dict[str, Any],
           rows: list[tuple[str, Any]], at: int) -> int:
    """A two-column block: what it is, and what it says."""
    for offset, (label, value) in enumerate(rows):
        page.write(at + offset, 0, str(label), styles["head"])
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            page.write_number(at + offset, 1, float(value),
                              _format_for(str(label), styles))
        else:
            page.write(at + offset, 1, "" if value is None else str(value),
                       styles["wrap"])
    page.set_column(0, 0, 34)
    page.set_column(1, 5, 46)
    return at + len(rows) + 2


# ------------------------------------------------------------------ the book

def build(result: dict[str, Any], *, selection: dict[str, Any] | None = None,
          customers: list[dict[str, Any]] | None = None,
          facilities: list[dict[str, Any]] | None = None) -> tuple[bytes, str]:
    """The workbook for one What-If result. Returns the bytes and a filename.

    Nothing here is recomputed: every figure is read out of `result`, which is
    the answer the screen showed. A workbook that recalculated could disagree
    with the page it came from, and then neither could be trusted.
    """
    import xlsxwriter

    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {
        "in_memory": True, "default_date_format": "yyyy-mm-dd"})
    styles = _styles(workbook)
    workbook.set_properties({
        "title": "Retail What-If Analysis",
        "subject": str(result.get("shocks_described") or "Scenario result"),
        "company": "Synthetic demonstration data — not ANB data or models",
    })

    selection = selection or (result.get("selection") or {})
    _summary(workbook, styles, result, selection)
    _waterfall(workbook, styles, result)
    _cohort(workbook, styles, result, selection)
    _levels(workbook, styles, result)
    _affected(workbook, styles, customers or [])
    _customer_prepost(workbook, styles, customers or [])
    _facility_prepost(workbook, styles, facilities or [])
    _drivers(workbook, styles, result)
    _parameters(workbook, styles, result)
    _stage_migration(workbook, styles, result)
    _dpd_analysis(workbook, styles, result)
    _band_analysis(workbook, styles, result)
    _method(workbook, styles, result)

    workbook.close()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    label = str(selection.get("selection_id") or "retail").replace("/", "-")
    return buffer.getvalue(), f"WhatIf_{label}_{stamp}.xlsx"


def _summary(workbook: Any, styles: dict[str, Any], result: dict[str, Any],
             selection: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "1 Summary", "Retail What-If Analysis",
                  "Synthetic Saudi retail demonstration data and a synthetic "
                  "demonstration engine. Not an ANB model, not an ANB policy, "
                  "not a SAMA requirement, not independently validated. No "
                  "credit decision should rest on it.")
    method = result.get("methodology") or {}
    levels = result.get("levels") or []
    cohort = next((one for one in levels if one.get("level") == "selection"),
                  levels[0] if levels else {})
    before, after = cohort.get("before") or {}, cohort.get("after") or {}
    delta = cohort.get("delta") or {}

    at = _pairs(page, styles, [
        ("Scenario", result.get("shocks_described") or "—"),
        ("Selected cohort", cohort.get("label") or "—"),
        ("Reporting month", result.get("month") or "—"),
        ("Methodology", method.get("name") or "—"),
        ("Methodology version", method.get("version") or "—"),
        ("Calculation of record", method.get("authority") or "—"),
        ("Selection id", selection.get("selection_id") or "—"),
        ("Exported at", datetime.now(UTC).isoformat(timespec="seconds")),
    ], 3)

    page.write(at, 0, "What the scenario did to the selected cohort",
               styles["title"])
    at = _table(page, styles, [
        {"Measure": "Customers", "Before": before.get("customers"),
         "After": after.get("customers")},
        {"Measure": "Accounts", "Before": before.get("accounts"),
         "After": after.get("accounts")},
        {"Measure": "Exposure (SAR)", "Before": before.get("exposure_sar"),
         "After": after.get("exposure_sar")},
        {"Measure": "PIT 12-month PD", "Before": before.get("pd_pit_12m"),
         "After": after.get("pd_pit_12m")},
        {"Measure": "Lifetime PD", "Before": before.get("pd_pit_lifetime"),
         "After": after.get("pd_pit_lifetime")},
        {"Measure": "LGD", "Before": before.get("lgd"),
         "After": after.get("lgd")},
        {"Measure": "EAD (SAR)", "Before": before.get("ead_sar"),
         "After": after.get("ead_sar")},
        {"Measure": "Weighted ECL (SAR)",
         "Before": before.get("ecl_weighted_sar"),
         "After": after.get("ecl_weighted_sar")},
        {"Measure": "Coverage (%)", "Before": before.get("ecl_coverage_pct"),
         "After": after.get("ecl_coverage_pct")},
    ], ["Measure", "Before", "After"], at + 1)

    page.write(at, 0, "Movement", styles["title"])
    _pairs(page, styles, [
        ("Weighted ECL change (SAR)", delta.get("ecl_weighted_sar")),
        ("Weighted ECL change (%)", delta.get("ecl_weighted_sar_pct")),
        ("Interpretation", result.get("interpretation") or "—"),
    ], at + 1)


def _waterfall(workbook: Any, styles: dict[str, Any],
               result: dict[str, Any]) -> None:
    steps = result.get("waterfall") or {}
    page = _sheet(workbook, styles, "2 Waterfall",
                  "How the number moved, step by step",
                  str(steps.get("basis") or
                      "Each step is the scenario re-run with one more shock "
                      "applied, and reported as the difference it made."))
    if not steps.get("available"):
        _pairs(page, styles, [
            ("Not decomposed", steps.get("because")
             or "This scenario applied no shock to decompose."),
        ], 3)
        return
    rows = [{
        "Step": one.get("label"),
        "ECL before (SAR)": one.get("from_sar"),
        "ECL after (SAR)": one.get("to_sar"),
        "Change (SAR)": one.get("change_sar"),
        "Change (%)": one.get("change_pct"),
        "Facilities moved": one.get("facilities_moved"),
    } for one in steps.get("steps") or []]
    at = _table(page, styles, rows, list(rows[0]) if rows else None, 3)
    _pairs(page, styles, [
        ("Baseline (SAR)", steps.get("baseline_sar")),
        ("Final (SAR)", steps.get("final_sar")),
        ("Total change (SAR)", steps.get("total_change_sar")),
        ("Total change (%)", steps.get("total_change_pct")),
    ], at)


def _cohort(workbook: Any, styles: dict[str, Any], result: dict[str, Any],
            selection: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "3 Cohort", "What is in the selected cohort",
                  "Every cut of the cohort as it stood before the scenario ran.")
    at = _pairs(page, styles, [
        ("Customers", selection.get("selected_customer_count")),
        ("Accounts", selection.get("selected_account_count")),
        ("Exposure (SAR)", selection.get("selected_exposure_sar")),
        ("Early Warning Score", selection.get("ews_score")),
        ("Severity", selection.get("ews_severity")),
        ("High or Critical", selection.get("high_or_critical")),
        ("Already bad", selection.get("current_bad")),
        ("Forward risk", selection.get("forward_risk")),
    ], 3)
    for cut in (result.get("baseline") or {}).get("cuts") or []:
        if not cut.get("available"):
            continue
        page.write(at, 0, str(cut.get("label")), styles["title"])
        rows = [{
            "Band": one.get("label"),
            "Customers": one.get("customers"),
            "Accounts": one.get("accounts"),
            "Exposure (SAR)": one.get("exposure_sar"),
            "PIT 12-month PD": one.get("pd_pit_12m"),
            "LGD": one.get("lgd"),
            "EAD (SAR)": one.get("ead_sar"),
            "Weighted ECL (SAR)": one.get("ecl_weighted_sar"),
        } for one in cut.get("rows") or []]
        at = _table(page, styles, rows, list(rows[0]) if rows else None, at + 1)


def _levels(workbook: Any, styles: dict[str, Any],
            result: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "4 Impact by level",
                  "The same scenario, read at every level it sits inside",
                  "The absolute movement is identical at every level, because "
                  "stressing a cohort cannot change anything outside it. What "
                  "changes is how large that movement looks against a wider "
                  "book.")
    rows = []
    for one in result.get("levels") or []:
        before, after = one.get("before") or {}, one.get("after") or {}
        delta = one.get("delta") or {}
        rows.append({
            "Level": one.get("level"),
            "Population": one.get("label"),
            "Customers": before.get("customers"),
            "Accounts": before.get("accounts"),
            "Exposure (SAR)": before.get("exposure_sar"),
            "ECL before (SAR)": before.get("ecl_weighted_sar"),
            "ECL after (SAR)": after.get("ecl_weighted_sar"),
            "Change (SAR)": delta.get("ecl_weighted_sar"),
            "Change (%)": delta.get("ecl_weighted_sar_pct"),
        })
    _table(page, styles, rows, list(rows[0]) if rows else None, 3)


def _affected(workbook: Any, styles: dict[str, Any],
              customers: list[dict[str, Any]]) -> None:
    page = _sheet(workbook, styles, "5 Affected customers",
                  "Every customer in the stressed cohort",
                  "The exact population the scenario ran on, named. This is "
                  "the list the selection carried out of Early Warning, not a "
                  "re-derivation of it.")
    _table(page, styles, customers, None, 3,
           empty="No customer list was carried with this result.")


def _customer_prepost(workbook: Any, styles: dict[str, Any],
                      customers: list[dict[str, Any]]) -> None:
    page = _sheet(workbook, styles, "6 Customer pre-post",
                  "Customer by customer, before and after")
    keep = [one for one in customers if any(
        str(k).endswith("_after") for k in one)]
    _table(page, styles, keep, None, 3,
           empty="This result reports at cohort level; no per-customer "
                 "before-and-after was produced.")


def _facility_prepost(workbook: Any, styles: dict[str, Any],
                      facilities: list[dict[str, Any]]) -> None:
    page = _sheet(workbook, styles, "7 Facility pre-post",
                  "Facility by facility, before and after",
                  "Every facility the scenario touched, with the parameters "
                  "it was scored on and the ones it ended with.")
    _table(page, styles, facilities, None, 3,
           empty="No facility-level detail was carried with this result.")


def _drivers(workbook: Any, styles: dict[str, Any],
             result: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "8 Drivers",
                  "What moved, by product",
                  "Where the movement landed. A cohort drawn from one product "
                  "will show one row; a wider selection shows where the "
                  "concentration is.")
    engine = (next((one for one in result.get("levels") or []
                    if one.get("level") == "selection"), {}) or {}).get("engine")
    rows = [{
        "Product": one.get("product_code"),
        "Baseline ECL (SAR)": one.get("baseline"),
        "Scenario ECL (SAR)": one.get("scenario"),
        "Change (SAR)": one.get("delta_sar"),
    } for one in ((engine or {}).get("drivers") or [])]
    _table(page, styles, rows, list(rows[0]) if rows else None, 3)


def _parameters(workbook: Any, styles: dict[str, Any],
                result: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "9 PD LGD EAD ECL",
                  "The risk parameters, before and after",
                  "Exposure-weighted at each level, as the screen reports "
                  "them.")
    rows = []
    for one in result.get("levels") or []:
        before, after = one.get("before") or {}, one.get("after") or {}
        for measure, key in (("TTC PD", "pd_ttc_12m"),
                             ("PIT 12-month PD", "pd_pit_12m"),
                             ("Lifetime PD", "pd_pit_lifetime"),
                             ("LGD", "lgd"), ("CCF", "ccf"),
                             ("EAD (SAR)", "ead_sar"),
                             ("Base ECL (SAR)", "ecl_base_sar"),
                             ("Weighted ECL (SAR)", "ecl_weighted_sar")):
            one_before, one_after = before.get(key), after.get(key)
            if one_before is None and one_after is None:
                continue
            rows.append({
                "Level": one.get("level"), "Population": one.get("label"),
                "Measure": measure, "Before": one_before, "After": one_after,
                "Change": (None if one_before is None or one_after is None
                           else round(float(one_after) - float(one_before), 6)),
            })
    _table(page, styles, rows, list(rows[0]) if rows else None, 3)


def _stage_migration(workbook: Any, styles: dict[str, Any],
                     result: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "10 Stage migration",
                  "Where the IFRS 9 stages ended up")
    rows = []
    for one in result.get("levels") or []:
        before = (one.get("before") or {}).get("stage_mix") or {}
        after = (one.get("after") or {}).get("stage_mix") or {}
        for stage in sorted(set(before) | set(after), key=str):
            rows.append({
                "Level": one.get("level"), "Population": one.get("label"),
                "Stage": stage,
                "Accounts before": before.get(stage, 0),
                "Accounts after": after.get(stage, 0),
                "Change": int(after.get(stage, 0)) - int(before.get(stage, 0)),
            })
    _table(page, styles, rows, list(rows[0]) if rows else None, 3,
           empty="This scenario did not report a stage mix.")


def _dpd_analysis(workbook: Any, styles: dict[str, Any],
                  result: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "11 Days past due",
                  "The delinquency profile the scenario started from")
    cut = next((one for one in (result.get("baseline") or {}).get("cuts") or []
                if one.get("key") == "dpd_bucket"), None)
    rows = [{
        "Bucket": one.get("label"), "Customers": one.get("customers"),
        "Accounts": one.get("accounts"),
        "Exposure (SAR)": one.get("exposure_sar"),
        "PIT 12-month PD": one.get("pd_pit_12m"), "LGD": one.get("lgd"),
        "Weighted ECL (SAR)": one.get("ecl_weighted_sar"),
    } for one in ((cut or {}).get("rows") or [])]
    _table(page, styles, rows, list(rows[0]) if rows else None, 3,
           empty="No delinquency cut was carried with this result.")


def _band_analysis(workbook: Any, styles: dict[str, Any],
                   result: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "12 Score bands",
                  "Behavioural and application score bands")
    at = 3
    for key, title in (("behavioural_score_band", "Behavioural score band"),
                       ("application_score_band", "Application score band")):
        cut = next((one for one in
                    (result.get("baseline") or {}).get("cuts") or []
                    if one.get("key") == key), None)
        page.write(at, 0, title, styles["title"])
        rows = [{
            "Band": one.get("label"), "Customers": one.get("customers"),
            "Accounts": one.get("accounts"),
            "Exposure (SAR)": one.get("exposure_sar"),
            "PIT 12-month PD": one.get("pd_pit_12m"),
            "Weighted ECL (SAR)": one.get("ecl_weighted_sar"),
        } for one in ((cut or {}).get("rows") or [])]
        at = _table(page, styles, rows, list(rows[0]) if rows else None, at + 1,
                    empty=f"No {title.lower()} cut was carried.")


def _method(workbook: Any, styles: dict[str, Any],
            result: dict[str, Any]) -> None:
    page = _sheet(workbook, styles, "13 Method", "Assumptions and method",
                  "What the engine did, what it assumed, and what it does not "
                  "claim.")
    method = result.get("methodology") or {}
    at = _pairs(page, styles, [
        ("Methodology", method.get("name")),
        ("Version", method.get("version")),
        ("What it does", method.get("what")),
        ("Authority", method.get("authority")),
        ("Shocks applied", result.get("shocks_described")),
        ("Disclaimer", result.get("disclaimer") or M.DISCLAIMER),
    ], 3)

    engine = (next((one for one in result.get("levels") or []
                    if one.get("level") == "selection"), {}) or {}).get("engine")
    for title, key in (("Assumptions", "assumptions"),
                       ("Limitations", "limitations")):
        entries = (result.get(key) or (engine or {}).get(key) or [])
        page.write(at, 0, title, styles["title"])
        rows = [{"#": index, title[:-1]: str(one)}
                for index, one in enumerate(entries, start=1)]
        at = _table(page, styles, rows, list(rows[0]) if rows else None, at + 1,
                    empty=f"No {title.lower()} were recorded.")

    challenger = result.get("challenger") or {}
    page.write(at, 0, "Challenger comparison", styles["title"])
    _pairs(page, styles, [
        ("Challenger", challenger.get("name")),
        ("Estimator", challenger.get("estimator")),
        ("Fitted on (rows)", challenger.get("fitted_on")),
        ("Challenger change (SAR)", challenger.get("estimated_delta_sar")),
        ("Delta method change (SAR)",
         challenger.get("delta_method_delta_sar")),
        ("Agreement", challenger.get("agreement")),
        ("Note", challenger.get("note")),
    ] if challenger.get("available") else [
        ("Challenger", "Not run for this scenario."),
    ], at + 1)
