"""The workbook a What-If result becomes.

§12 of the demo completion contract, which is both a presentation standard and
a completeness gate. Twenty-two sheets, from an executive summary through every
step of the propagation to a trace, all built from the STORED result rather
than from a fresh run — a workbook that recalculated could disagree with the
page it came from, and then neither could be trusted.

What was wrong with the previous one
------------------------------------
Thirteen sheets, gridlines on every one of them, and number formats chosen by
sniffing the column's display label — so "Exposure (SAR)" got no format at all
while "LGD" happened to match a rule and got four decimal places:

    Exposure (SAR)   71118341.24
    PIT 12-month PD  0.034823
    LGD              0.8132

Every column now declares what it holds. Nothing is inferred from a string.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from backend.retail import workbook_style as ST
from backend.retail.workbook_sheet import Sheet

DISCLOSURE = (
    "Synthetic Saudi retail demonstration data and a synthetic demonstration "
    "engine. Not ANB customer data, not an ANB model, not an ANB policy, not "
    "a SAMA requirement, and not independently validated. No credit decision "
    "should rest on it.")

#: Sheet order, and what each one is for. The Contents page is built from this
#: list, so a sheet cannot be added without appearing in the index.
SHEETS: tuple[tuple[str, str], ...] = (
    ("Contents", "What is in this workbook, and how to read it"),
    ("Summary", "The scenario, the result, and how material it is"),
    ("Waterfall", "The ECL bridge, step by step, and how it reconciles"),
    ("Cohort", "Who is in the selected population, cut every way"),
    ("Impact by Level", "The same movement against each wider population"),
    ("Affected Customers", "Who moved, and by how much"),
    ("Customer Pre Post", "Customer-level values before and after"),
    ("Facility Pre Post", "Facility-level values before and after"),
    ("01 Raw Drivers", "The raw values the scenario moved"),
    ("02 Transformations", "Binning and transformation of each moved input"),
    ("03 Score Points", "Point contributions before and after"),
    ("04 Score Migration", "Behavioural band movement, count and exposure"),
    ("05 PD Mapping", "Score to PD, and the PD comparison basis"),
    ("06 Stage Decisions", "Staging before and after, and the policy"),
    ("07 LGD EAD Recovery", "Loss given default, exposure at default, recovery"),
    ("08 ECL Calculations", "Per scenario ECL, weights, overlay, final"),
    ("DPD Migration", "Delinquency bucket movement"),
    ("Behavioural Bands", "Score band distribution"),
    ("Stage Migration", "IFRS 9 stage movement"),
    ("Assumptions", "Method, staging policy, scenario weights, limits"),
    ("Data Dictionary", "Every column in this workbook, defined"),
    ("Trace & Checks", "Versions, hashes, reconciliation and what failed"),
)


def _say(value: Any) -> str:
    """Whatever this is, as a sentence fragment a person can read."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return ", ".join(f"{k} {v}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_say(one) for one in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _cohort_level(result: dict[str, Any]) -> dict[str, Any]:
    levels = result.get("levels") or []
    return next((one for one in levels if one.get("level") == "selection"),
                levels[0] if levels else {})


def _money(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def build(result: dict[str, Any], *, selection: dict[str, Any] | None = None,
          customers: list[dict[str, Any]] | None = None,
          facilities: list[dict[str, Any]] | None = None) -> tuple[bytes, str]:
    """The workbook for one What-If result. Returns the bytes and a filename."""
    import xlsxwriter

    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {"in_memory": True,
                                        "default_date_format": ST.F_DATE})
    styles = ST.styles(book)
    book.set_properties({
        "title": "Retail What-If Analysis",
        "subject": str(result.get("shocks_described") or "Scenario result"),
        "company": "Synthetic demonstration data — not ANB data or models",
        "comments": DISCLOSURE,
    })

    selection = selection or (result.get("selection") or {})
    customers = customers or []
    facilities = facilities or []
    built: list[tuple[str, str, int]] = []

    def note(name: str, rows: int) -> None:
        built.append((name, dict(SHEETS)[name], rows))

    contents = Sheet(book, styles, "Contents", "Retail What-If Analysis",
                     DISCLOSURE, landscape=False)

    note("Summary", _summary(book, styles, result, selection))
    note("Waterfall", _waterfall(book, styles, result))
    note("Cohort", _cohort(book, styles, result, selection))
    note("Impact by Level", _levels(book, styles, result))
    note("Affected Customers", _affected(book, styles, customers))
    note("Customer Pre Post", _prepost(book, styles, customers,
                                       "Customer Pre Post", "customer_id",
                                       "Customer"))
    note("Facility Pre Post", _prepost(book, styles, facilities,
                                       "Facility Pre Post", "facility_id",
                                       "Facility"))
    note("01 Raw Drivers", _raw_drivers(book, styles, result))
    note("02 Transformations", _transformations(book, styles, result))
    note("03 Score Points", _score_points(book, styles, result, customers))
    note("04 Score Migration", _score_migration(book, styles, result))
    note("05 PD Mapping", _pd_mapping(book, styles, result))
    note("06 Stage Decisions", _stage_decisions(book, styles, result))
    note("07 LGD EAD Recovery", _lgd_ead(book, styles, result))
    note("08 ECL Calculations", _ecl_calcs(book, styles, result))
    note("DPD Migration", _dpd(book, styles, result))
    note("Behavioural Bands", _bands(book, styles, result))
    note("Stage Migration", _stages(book, styles, result))
    note("Assumptions", _assumptions(book, styles, result))
    note("Data Dictionary", _dictionary(book, styles))
    note("Trace & Checks", _trace(book, styles, result, selection))

    _contents(contents, result, selection, built)

    book.close()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    label = str(selection.get("selection_id") or "retail").replace("/", "-")
    return buffer.getvalue(), f"WhatIf_{label}_{stamp}.xlsx"


# ============================================================= Contents

def _contents(sheet: Sheet, result: dict[str, Any],
              selection: dict[str, Any],
              built: list[tuple[str, str, int]]) -> None:
    """§12.1's Read Me: scope, period, method, versions and internal links."""
    method = result.get("methodology") or {}
    cohort = _cohort_level(result)
    delta = cohort.get("delta") or {}
    sheet.pairs([
        ("Scenario", result.get("shocks_described") or "—"),
        ("Selected cohort", selection.get("source_label") or "—"),
        ("Selection ID", selection.get("selection_id") or "—"),
        ("Reporting month", result.get("month") or "—"),
        ("Method", method.get("name") or "—"),
        ("Staging mode", (result.get("scenario") or {}).get("staging_mode")
                         or "—"),
        ("Model version", selection.get("source_model_version") or "—"),
        ("Rulebook version", selection.get("source_rulebook_version") or "—"),
        ("Taxonomy version", selection.get("taxonomy_version") or "—"),
        ("Facilities stressed", result.get("stressed_facilities")),
        ("ECL change (SAR)", _money(delta.get("ecl_weighted_sar"))),
        ("Built at (UTC)", datetime.now(UTC).isoformat(timespec="seconds")),
        ("Reconciliation", _reconciliation(result)),
    ])
    sheet.section("Sheets in this workbook")
    sheet.at += 1
    for name, purpose, rows in built:
        sheet.page.write_url(sheet.at, 0, f"internal:'{name[:31]}'!A1",
                             sheet.styles["link"], name)
        sheet.page.write(sheet.at, 1, purpose, sheet.styles["text"])
        sheet.page.write_number(sheet.at, 2, rows, sheet.styles["count"])
        sheet.at += 1
    sheet.page.set_column(0, 0, 26)
    sheet.page.set_column(1, 1, 58)
    sheet.page.set_column(2, 2, 12)
    sheet.at += 1
    sheet.line("Rows are the data rows on each sheet, excluding headings and "
               "totals. A sheet reporting zero rows is one this scenario had "
               "nothing to put on it — the reason is stated on the sheet "
               "itself rather than left as an empty page.")


def _reconciliation(result: dict[str, Any]) -> str:
    steps = (result.get("waterfall") or {})
    if not steps:
        return "No decomposition was requested for this run."
    if steps.get("available") is False:
        return f"Not computed: {steps.get('because', '')}"
    rows = steps.get("steps") or []
    if not rows:
        return "Single-step scenario: the change IS the step."
    stepped = sum(float(one.get("change_sar") or 0.0) for one in rows)
    total = float(steps.get("total_change_sar") or 0.0)
    return (f"The {len(rows)} step(s) reconcile to the total within SAR "
            f"{abs(total - stepped):,.2f}.")


# ============================================================== Summary

def _summary(book: Any, styles: dict[str, Any], result: dict[str, Any],
             selection: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "Summary", "Retail What-If Analysis",
                  DISCLOSURE)
    cohort = _cohort_level(result)
    before, after = cohort.get("before") or {}, cohort.get("after") or {}
    delta = cohort.get("delta") or {}

    sheet.kpis([
        ("Baseline ECL (SAR)", _money(before.get("ecl_weighted_sar")), ""),
        ("Scenario ECL (SAR)", _money(after.get("ecl_weighted_sar")), ""),
        ("Change (SAR)", _money(delta.get("ecl_weighted_sar")), ""),
        ("Customers", before.get("customers"), ""),
        ("Facilities", before.get("accounts"), ""),
    ])
    sheet.section("What was asked")
    sheet.pairs([
        ("Scenario", result.get("shocks_described") or "—"),
        ("Cohort", selection.get("source_label") or "—"),
        ("Facilities actually stressed", result.get("stressed_facilities")),
        ("Narrowing applied", (result.get("narrowing") or {}).get("said")
                              or "No narrowing was applied"),
        ("Method", (result.get("methodology") or {}).get("name") or "—"),
    ])

    sheet.section("Baseline against scenario")
    columns = [
        ST.Col("measure", "Measure", ST.TEXT, width=34),
        ST.Col("before", "Baseline", ST.MONEY),
        ST.Col("after", "Scenario", ST.MONEY),
        ST.Col("change", "Change (SAR)", ST.MONEY, signed=True),
        ST.Col("change_pct", "Change", ST.RATE, signed=True),
    ]
    rows = []
    for key, label in (("ecl_weighted_sar", "Weighted ECL"),
                       ("ecl_base_sar", "Base-scenario ECL"),
                       ("exposure_sar", "Gross carrying amount"),
                       ("ead_sar", "Exposure at default")):
        one, two = _money(before.get(key)), _money(after.get(key))
        if one is None and two is None:
            continue
        change = None if (one is None or two is None) else two - one
        rows.append({"measure": label, "before": one, "after": two,
                     "change": change,
                     "change_pct": (change / one if change is not None
                                    and one else None)})
    head_at = sheet.at
    sheet.table(columns, rows, autofilter=False)
    # The change columns, rewritten as the subtraction and the division they
    # are. The values stay exactly as the engine reported them — they are
    # passed as the cached result — so nothing here can move a figure; what
    # changes is that a reader can see the arithmetic.
    for offset in range(len(rows)):
        at = head_at + 1 + offset
        row = rows[offset]
        if row["change"] is not None:
            sheet.page.write_formula(
                at, 3, f"=C{at + 1}-B{at + 1}",
                ST.cell_style(columns[3], row["change"], styles),
                float(row["change"]))
        if row["change_pct"] is not None:
            sheet.page.write_formula(
                at, 4, f"=IF(B{at + 1}=0,\"\",D{at + 1}/B{at + 1})",
                ST.cell_style(columns[4], row["change_pct"], styles),
                float(row["change_pct"]))

    steps = (result.get("waterfall") or {}).get("steps") or []
    if steps:
        first = sheet.at
        chart_rows = [{"step": one.get("label"),
                       "amount": _money(one.get("amount_sar"))}
                      for one in steps]
        sheet.section("What moved the allowance")
        sheet.table([ST.Col("step", "Step", ST.TEXT, width=38),
                     ST.Col("amount", "Contribution (SAR)", ST.MONEY,
                            signed=True)],
                    chart_rows, autofilter=False)
        sheet.chart(book, {
            "type": "column",
            "title": "Contribution to the ECL change, by step (SAR)",
            "series": [{
                "name": "SAR",
                "categories": [sheet.name, first + 1, 0,
                               first + len(chart_rows), 0],
                "values": [sheet.name, first + 1, 1,
                           first + len(chart_rows), 1],
                "fill": {"color": ST.NAVY_LIGHT},
            }],
            "y_axis": {"name": "SAR", "num_format": ST.F_MONEY0},
            "legend": "none",
        })

    sheet.section("Interpretation")
    # The engine returns this as prose on some paths and as a structured
    # object on others. Taking `.get` on it assumed one of those.
    reading = result.get("interpretation")
    if isinstance(reading, dict):
        lines = reading.get("points") or [reading.get("text") or ""]
    elif isinstance(reading, (list, tuple)):
        lines = list(reading)
    else:
        lines = [str(reading)] if reading else []
    for line in lines:
        if str(line).strip():
            sheet.line(str(line), "text")
    return len(rows)


# ============================================================ Waterfall

def _waterfall(book: Any, styles: dict[str, Any],
               result: dict[str, Any]) -> int:
    steps = result.get("waterfall") or {}
    sheet = Sheet(book, styles, "Waterfall",
                  "The ECL bridge, step by step",
                  "Each step is a FULL recomputation of the IFRS 9 identity "
                  "with one more shock applied, not a share of the total "
                  "allocated backwards. The identity is not additive in its "
                  "inputs, so a split of a number that was never a sum would "
                  "report steps that do not exist.")
    if steps.get("available") is False:
        sheet.line(str(steps.get("because") or
                       "The decomposition was not computed for this run."),
                   "warn")
        return 0
    rows = steps.get("steps") or []
    if not rows:
        sheet.line("This scenario carries a single shock, so there is no "
                   "sequence to decompose. The Summary sheet's change IS the "
                   "step.", "note")
        return 0
    # The engine's own keys. Writing this sheet against invented names —
    # `amount_sar`, `running_ecl_sar` — produced a table of blanks that looked
    # like a formatting problem and was a wiring one.
    total_change = _money(steps.get("total_change_sar"))
    table = [{
        "order": index + 1,
        "label": one.get("label"),
        # A shock can arrive as a number, a dict or a sentence. The column is
        # prose, so it is made prose here rather than writing a bare number
        # into a text column and getting no format at all.
        "shock": _say(one.get("shock")),
        "from_sar": _money(one.get("from_sar")),
        "to_sar": _money(one.get("to_sar")),
        "change_sar": _money(one.get("change_sar")),
        "share": ((float(one.get("change_sar")) / total_change)
                  if (one.get("change_sar") is not None and total_change)
                  else None),
        "facilities_moved": one.get("facilities_moved"),
        "facilities_selected": one.get("facilities_selected"),
    } for index, one in enumerate(rows)]
    stepped = sum(float(one["change_sar"] or 0.0) for one in table)
    columns = [
        ST.Col("order", "#", ST.COUNT, width=5),
        ST.Col("label", "Step", ST.TEXT, width=32),
        ST.Col("shock", "Shock applied", ST.WRAP, width=28),
        ST.Col("from_sar", "ECL before this step (SAR)", ST.MONEY),
        ST.Col("to_sar", "ECL after this step (SAR)", ST.MONEY),
        ST.Col("change_sar", "This step moved (SAR)", ST.MONEY, signed=True),
        ST.Col("share", "Share of the total", ST.RATE),
        ST.Col("facilities_moved", "Facilities whose ECL moved", ST.COUNT),
    ]
    # Only a migration names its own population. Printing the column for a
    # parameter shock puts a heading promising a number over a column of
    # blanks, which reads as a broken export rather than as "not applicable".
    if any(one.get("facilities_selected") is not None for one in table):
        columns.append(ST.Col("facilities_selected",
                              "Facilities the shock selected", ST.COUNT))
    sheet.table(columns, table,
                total={"label": "Total", "change_sar": stepped},
                autofilter=False)
    if not any(one.get("facilities_selected") is not None for one in table):
        sheet.line("These shocks move a parameter on every eligible facility "
                   "rather than selecting a set, so there is no separate "
                   "selected population to report. A migration names the "
                   "facilities it moved and that column appears beside this "
                   "one.")

    # Where the step rows and their total landed, so the checks below can
    # point at them rather than restate their numbers.
    total_row = sheet.at - 2
    step_column = sheet.column_letter(5)

    sheet.section("Reconciliation")
    residual = (total_change - stepped) if total_change is not None else None
    baseline = _money(steps.get("baseline_sar"))
    final = _money(steps.get("final_sar"))
    where = sheet.pairs([
        ("Baseline ECL (SAR)", baseline),
        ("Scenario ECL (SAR)", final),
    ])
    # Written as the arithmetic rather than as the answer: a residual stated
    # as a number is a claim, and stated as the subtraction it came from is
    # something a reader can disagree with in the cell. Every reference comes
    # from `where`, so no cell address here is counted by hand.
    change_at = sheet.check(
        "Total change (SAR)",
        f"={where['Scenario ECL (SAR)']}-{where['Baseline ECL (SAR)']}",
        total_change or 0.0)
    stepped_at = sheet.check("Sum of the steps (SAR)",
                             f"={step_column}{total_row + 1}",
                             round(stepped, 2))
    sheet.check("Residual (SAR)", f"={change_at}-{stepped_at}",
                round(residual or 0.0, 2))
    sheet.at += 1
    sheet.pairs([
        ("Order applied", ", ".join(one.get("label", "") for one in rows)),
        ("Full published order", ", ".join(steps.get("order") or [])),
        ("Basis", steps.get("basis") or "sequential recomputation"),
    ])
    sheet.line("The residual is published rather than absorbed into the last "
               "step. A decomposition that always reconciles exactly because "
               "its final term is whatever is left over is not a "
               "decomposition.")
    return len(table)


# =============================================================== Cohort

_CUT_COLUMNS = [
    ST.Col("label", "Band", ST.TEXT, width=22),
    ST.Col("customers", "Customers", ST.COUNT),
    ST.Col("accounts", "Accounts", ST.COUNT),
    ST.Col("exposure_sar", "Exposure (SAR)", ST.MONEY),
    ST.Col("exposure_share", "Share of exposure", ST.RATE),
    ST.Col("pd_ttc", "TTC PD", ST.RATE),
    ST.Col("pd_pit_12m", "PIT 12-month PD", ST.RATE),
    ST.Col("pd_pit_lifetime", "PIT lifetime PD", ST.RATE),
    ST.Col("lgd", "LGD", ST.RATE),
    ST.Col("ccf", "CCF", ST.RATE),
    ST.Col("ead_sar", "EAD (SAR)", ST.MONEY),
    ST.Col("ecl_weighted_sar", "Weighted ECL (SAR)", ST.MONEY),
    ST.Col("coverage", "Coverage", ST.RATE),
]


def _cohort(book: Any, styles: dict[str, Any], result: dict[str, Any],
            selection: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "Cohort", "What is in the selected cohort",
                  "The cohort as it stood BEFORE the scenario ran, cut every "
                  "way the screen offers. Percentages of exposure are shares "
                  "of this cohort, not of the book.")
    sheet.pairs([
        ("Customers", selection.get("selected_customer_count")),
        ("Accounts", selection.get("selected_account_count")),
        ("Exposure (SAR)", selection.get("selected_exposure_sar")),
        ("Early Warning Score", selection.get("ews_score")),
        ("Severity", selection.get("ews_severity")),
        ("High or Critical", selection.get("high_or_critical")),
        ("Already bad", selection.get("current_bad")),
        ("Forward risk", selection.get("forward_risk")),
    ])
    total = 0
    for cut in (result.get("baseline") or {}).get("cuts") or []:
        if not cut.get("available"):
            continue
        rows = list(cut.get("rows") or [])
        if not rows:
            continue
        sheet.section(str(cut.get("label")))
        sheet.table(_CUT_COLUMNS, rows, autofilter=False)
        total += len(rows)
    if not total:
        sheet.line("The baseline carried no cuts for this cohort.", "warn")
    return total


# ======================================================= Impact by level

def _levels(book: Any, styles: dict[str, Any], result: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "Impact by Level",
                  "The same movement, against each population it sits inside",
                  "The absolute movement is identical at every level: "
                  "stressing a cohort cannot change anything outside it. What "
                  "changes is how large that movement looks against a wider "
                  "denominator, which is what materiality means here.")
    rows = []
    for level in result.get("levels") or []:
        before = level.get("before") or {}
        after = level.get("after") or {}
        delta = level.get("delta") or {}
        change = _money(delta.get("ecl_weighted_sar"))
        base = _money(before.get("ecl_weighted_sar"))
        rows.append({
            "label": level.get("label"),
            "customers": before.get("customers"),
            # The engine calls this `accounts`. Reading `facilities` printed
            # a blank column under a heading that promised a number — visible
            # the moment the sheet was opened and read, and invisible to
            # every check that only asked whether cells were formatted.
            "facilities": before.get("accounts"),
            "exposure_sar": _money(before.get("exposure_sar")),
            "before": base, "after": _money(after.get("ecl_weighted_sar")),
            "change": change,
            "change_pct": (change / base) if (change is not None and base)
                          else None,
        })
    columns = [
        ST.Col("label", "Population", ST.TEXT, width=34),
        ST.Col("customers", "Customers", ST.COUNT),
        ST.Col("facilities", "Facilities", ST.COUNT),
        ST.Col("exposure_sar", "Exposure (SAR)", ST.MONEY),
        ST.Col("before", "Baseline ECL (SAR)", ST.MONEY),
        ST.Col("after", "Scenario ECL (SAR)", ST.MONEY),
        ST.Col("change", "Change (SAR)", ST.MONEY, signed=True),
        ST.Col("change_pct", "Change against that level", ST.RATE,
               signed=True),
    ]
    head_at = sheet.at
    sheet.table(columns, rows, autofilter=False)
    for offset, row in enumerate(rows):
        at = head_at + 1 + offset
        if row["change"] is not None:
            sheet.page.write_formula(
                at, 6, f"=F{at + 1}-E{at + 1}",
                ST.cell_style(columns[6], row["change"], styles),
                float(row["change"]))
        if row["change_pct"] is not None:
            sheet.page.write_formula(
                at, 7, f"=IF(E{at + 1}=0,\"\",G{at + 1}/E{at + 1})",
                ST.cell_style(columns[7], row["change_pct"], styles),
                float(row["change_pct"]))
    sheet.line("The change column is written as the subtraction it is, and "
               "the percentage as the division. Click either and the formula "
               "bar shows which two cells produced it.")
    return len(rows)


# ================================================== affected customers

#: The columns a reader actually reads on the affected-customer sheet.
#: Dumping all 498 book columns made a 4 MB sheet nobody could use; keeping
#: eighteen is not "discarding detailed calculations" — the per-step detail
#: lives on sheets 01 to 08, where it can be read.
AFFECTED: list[ST.Col] = [
    ST.Col("customer_id", "Customer", ST.TEXT, width=16),
    ST.Col("customer_name", "Name", ST.TEXT, width=26),
    ST.Col("product_code", "Product", ST.TEXT, width=16),
    ST.Col("sub_product_code", "Sub-product", ST.TEXT, width=18),
    ST.Col("classification", "Classification", ST.TEXT, width=16),
    ST.Col("facilities", "Facilities", ST.COUNT),
    ST.Col("exposure_sar", "Exposure (SAR)", ST.MONEY),
    ST.Col("dpd", "Days past due", ST.COUNT),
    ST.Col("dpd_bucket", "Bucket", ST.TEXT, width=12),
    ST.Col("ifrs9_stage", "Stage", ST.COUNT, width=7),
    ST.Col("behavioural_score", "Behavioural score", ST.POINTS),
    ST.Col("behavioural_score_band", "Band", ST.TEXT, width=8),
    ST.Col("pd_pit_12m_before", "PD before", ST.RATE),
    ST.Col("pd_pit_12m_after", "PD after", ST.RATE),
    ST.Col("lgd_before", "LGD before", ST.RATE),
    ST.Col("lgd_after", "LGD after", ST.RATE),
    ST.Col("ecl_before_sar", "ECL before (SAR)", ST.MONEY),
    ST.Col("ecl_after_sar", "ECL after (SAR)", ST.MONEY),
    ST.Col("ecl_change_sar", "ECL change (SAR)", ST.MONEY, signed=True),
    ST.Col("changed", "Changed", ST.TEXT, width=10),
    ST.Col("reason", "Why it was selected", ST.WRAP, width=34),
]


def _affected(book: Any, styles: dict[str, Any],
              rows: list[dict[str, Any]]) -> int:
    sheet = Sheet(book, styles, "Affected Customers",
                  "Who moved, and by how much",
                  "Every customer in the stressed population, whether or not "
                  "the scenario changed them. An unchanged row is evidence "
                  "too: it says the shock did not reach that customer, which "
                  "a filtered list would hide.")
    if not rows:
        sheet.line("No customer detail was attached to this result. The "
                   "cohort sheet reports the population; per-customer rows "
                   "are requested separately by the screen that downloads "
                   "this workbook.", "warn")
        return 0
    changed = sum(1 for one in rows if one.get("changed") in (True, "Yes"))
    sheet.pairs([
        ("Customers listed", len(rows)),
        ("Changed by the scenario", changed),
        ("Unchanged", len(rows) - changed),
    ])
    sheet.table(AFFECTED, rows, total={
        "facilities": sum(int(one.get("facilities") or 0) for one in rows),
        "exposure_sar": sum(float(one.get("exposure_sar") or 0.0)
                            for one in rows),
        "ecl_before_sar": sum(float(one.get("ecl_before_sar") or 0.0)
                              for one in rows),
        "ecl_after_sar": sum(float(one.get("ecl_after_sar") or 0.0)
                             for one in rows),
        "ecl_change_sar": sum(float(one.get("ecl_change_sar") or 0.0)
                              for one in rows),
    })
    sheet.line("The total row is SUBTOTAL(109, …), so filtering the table "
               "above narrows the totals with it — a filtered view whose "
               "total still described the whole population would be worse "
               "than no total at all.")
    return len(rows)


#: The facility comparison, declared rather than guessed.
#:
#: This function used to infer each column's kind from its key — and got it
#: wrong for every one of them, because `dpd_before` is not `dpd`,
#: `lgd_after` is not `lgd`, and `ecl_weighted_sar_before` does not end in
#: `_sar`. Forty thousand numeric cells came out as General: a PD written as
#: 0.1282480893365741 and money as 7745.726000000001, which is the §2.4
#: complaint reappearing in the sheet next door.
FACILITY_PREPOST: list[ST.Col] = [
    ST.Col("facility_id", "Facility", ST.TEXT, width=16),
    ST.Col("customer_id", "Customer", ST.TEXT, width=16),
    ST.Col("product_code", "Product", ST.TEXT, width=16),
    ST.Col("dpd_before", "Days past due, before", ST.COUNT),
    ST.Col("dpd_after", "Days past due, after", ST.COUNT),
    ST.Col("stage_before", "Stage before", ST.COUNT, width=10),
    ST.Col("stage_after", "Stage after", ST.COUNT, width=10),
    ST.Col("pd_pit_12m_before", "PIT 12-month PD, before", ST.RATE),
    ST.Col("pd_pit_12m_after", "PIT 12-month PD, after", ST.RATE),
    ST.Col("lgd_before", "LGD before", ST.RATE),
    ST.Col("lgd_after", "LGD after", ST.RATE),
    ST.Col("exposure_sar", "Exposure (SAR)", ST.MONEY),
    ST.Col("ecl_weighted_sar_before", "Weighted ECL before (SAR)", ST.MONEY),
    ST.Col("ecl_weighted_sar_after", "Weighted ECL after (SAR)", ST.MONEY),
    ST.Col("ecl_change_sar", "ECL change (SAR)", ST.MONEY, signed=True),
]

CUSTOMER_PREPOST: list[ST.Col] = [
    ST.Col("customer_id", "Customer", ST.TEXT, width=16),
    ST.Col("customer_name", "Name", ST.TEXT, width=26),
    ST.Col("facilities", "Facilities", ST.COUNT),
    ST.Col("exposure_sar", "Exposure (SAR)", ST.MONEY),
    ST.Col("pd_pit_12m_before", "PIT 12-month PD, before", ST.RATE),
    ST.Col("pd_pit_12m_after", "PIT 12-month PD, after", ST.RATE),
    ST.Col("lgd_before", "LGD before", ST.RATE),
    ST.Col("lgd_after", "LGD after", ST.RATE),
    ST.Col("ecl_before_sar", "Weighted ECL before (SAR)", ST.MONEY),
    ST.Col("ecl_after_sar", "Weighted ECL after (SAR)", ST.MONEY),
    ST.Col("ecl_change_sar", "ECL change (SAR)", ST.MONEY, signed=True),
    ST.Col("changed", "Changed", ST.TEXT, width=10),
]


def _prepost(book: Any, styles: dict[str, Any], rows: list[dict[str, Any]],
             name: str, key: str, label: str) -> int:
    sheet = Sheet(book, styles, name,
                  f"{label}-level values, before and after",
                  "The full numeric comparison rather than a list of "
                  "identifiers. Where a channel is genuinely untouched by "
                  "this scenario the before and after are equal, which is the "
                  "honest way to say so.")
    if not rows:
        sheet.line(f"No {label.lower()}-level rows were attached to this "
                   f"result.", "warn")
        return 0
    declared = (FACILITY_PREPOST if key == "facility_id"
                else CUSTOMER_PREPOST)
    held = set(rows[0])
    columns = [one for one in declared if one.key in held]
    totals: dict[str, Any] = {}
    for column in columns:
        if column.kind in (ST.MONEY, ST.MONEY0, ST.COUNT):
            totals[column.key] = sum(float(one.get(column.key) or 0.0)
                                     for one in rows)
    sheet.table(columns, rows, total=totals or None)
    # Descriptive fields — product, sub-product, band, bucket — live on the
    # Affected Customers sheet. This one is the numeric comparison, and
    # appending undeclared columns to it wrote numbers with no format at all,
    # which is the defect this file exists to stop.
    undeclared = sorted(held - {one.key for one in declared})
    if undeclared:
        sheet.line("Also held for each row and shown on the Affected "
                   "Customers sheet, where they are formatted: "
                   + ", ".join(undeclared) + ".")
    return len(rows)


# ================================================ 01-08 the propagation

def _step_sheet(book: Any, styles: dict[str, Any], name: str, title: str,
                note: str) -> Sheet:
    return Sheet(book, styles, name, title, note)


def _not_applicable(sheet: Sheet, why: str) -> int:
    """§12.2: an inapplicable step explains itself rather than inventing rows."""
    sheet.line(why, "warn")
    sheet.line("This sheet is present and empty on purpose. A propagation "
               "step that this scenario does not touch is reported as not "
               "applicable; it is never filled with figures that were not "
               "calculated.")
    return 0


def _shock_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    from backend.retail import whatif as W
    from backend.retail import whatif_cohort as C

    out = []
    for name, value in (result.get("shocks") or {}).items():
        out.append({
            "shock": C._SAYS[name](value) if name in C._SAYS else name,
            "parameter": name,
            "value": value if isinstance(value, (int, float)) else str(value),
            "what": W.SUPPORTED_METHODOLOGIES.get(name, ""),
        })
    return out


def _raw_drivers(book: Any, styles: dict[str, Any],
                 result: dict[str, Any]) -> int:
    sheet = _step_sheet(book, styles, "01 Raw Drivers",
                        "The raw values this scenario moved",
                        "Step one of the propagation: what the scenario "
                        "changed at source, before anything downstream reads "
                        "it.")
    rows = _shock_rows(result)
    if not rows:
        return _not_applicable(sheet, "This run carried no shocks — it is a "
                                      "neutral baseline.")
    sheet.table([
        ST.Col("shock", "What was asked", ST.WRAP, width=44),
        ST.Col("parameter", "Engine parameter", ST.TEXT, width=24),
        ST.Col("value", "Value", ST.POINTS),
        ST.Col("what", "What the engine does with it", ST.WRAP, width=62),
    ], rows, autofilter=False)
    eligible = result.get("eligibility") or {}
    if eligible:
        sheet.section("Eligibility")
        sheet.pairs(list(eligible.items()))
    return len(rows)


def _transformations(book: Any, styles: dict[str, Any],
                     result: dict[str, Any]) -> int:
    sheet = _step_sheet(book, styles, "02 Transformations",
                        "How each moved input is binned and transformed",
                        "Step two: the scorecard's own binning and weight of "
                        "evidence for every input this scenario reaches. The "
                        "bins and their values are the model's, read from the "
                        "registry rather than restated here.")
    rows = (result.get("transformations") or [])
    if not rows:
        return _not_applicable(
            sheet, "This scenario moves parameters of the IFRS 9 identity "
                   "directly — PD, LGD, EAD or staging — and does not pass "
                   "through a scorecard input, so there is no transformation "
                   "to show.")
    sheet.table([
        ST.Col("model_id", "Model", ST.TEXT, width=26),
        ST.Col("feature", "Input", ST.TEXT, width=24),
        ST.Col("business_name", "What it measures", ST.WRAP, width=36),
        ST.Col("raw_before", "Raw before", ST.POINTS),
        ST.Col("raw_after", "Raw after", ST.POINTS),
        ST.Col("bin_before", "Bin before", ST.TEXT, width=16),
        ST.Col("bin_after", "Bin after", ST.TEXT, width=16),
        ST.Col("woe_before", "WoE before", ST.POINTS),
        ST.Col("woe_after", "WoE after", ST.POINTS),
        ST.Col("facilities", "Facilities", ST.COUNT),
    ], rows)
    return len(rows)


def _score_points(book: Any, styles: dict[str, Any], result: dict[str, Any],
                  customers: list[dict[str, Any]]) -> int:
    sheet = _step_sheet(book, styles, "03 Score Points",
                        "Point contributions, before and after",
                        "Step three: each input's contribution to the score "
                        "in points, so the score change is the sum of "
                        "movements a reader can check rather than a number "
                        "that appears.")
    rows = (result.get("score_contributions") or [])
    if not rows:
        return _not_applicable(
            sheet, "No scorecard input moved in this scenario, so no point "
                   "contribution changed. A scenario that shocks PD or LGD "
                   "directly reaches ECL without passing through the score.")
    sheet.table([
        ST.Col("model_id", "Model", ST.TEXT, width=26),
        ST.Col("feature", "Input", ST.TEXT, width=24),
        ST.Col("points_before", "Points before", ST.POINTS),
        ST.Col("points_after", "Points after", ST.POINTS),
        ST.Col("points_change", "Change", ST.POINTS, signed=True),
        ST.Col("facilities", "Facilities", ST.COUNT),
    ], rows)
    return len(rows)


def _matrix_rows(source: Any) -> list[dict[str, Any]]:
    return list(source or [])


def _score_migration(book: Any, styles: dict[str, Any],
                     result: dict[str, Any]) -> int:
    sheet = _step_sheet(book, styles, "04 Score Migration",
                        "Behavioural band movement, by count and by exposure",
                        "Step four. Unchanged and improving populations are "
                        "in the matrix, not filtered out of it: a table "
                        "showing only the downgrades reads as though the "
                        "whole book moved one way.")
    rows = _matrix_rows((result.get("score_migration") or {}).get("matrix"))
    if not rows:
        return _not_applicable(
            sheet, "No behavioural score band changed under this scenario.")
    sheet.table([
        ST.Col("from", "From band", ST.TEXT, width=12),
        ST.Col("to", "To band", ST.TEXT, width=12),
        ST.Col("facilities", "Facilities", ST.COUNT),
        ST.Col("customers", "Customers", ST.COUNT),
        ST.Col("exposure_sar", "Exposure (SAR)", ST.MONEY),
        ST.Col("count_share_pct", "Share of the row, by count", ST.PERCENT),
        ST.Col("exposure_share_pct", "Share of the row, by exposure",
               ST.PERCENT),
        ST.Col("direction", "Direction", ST.TEXT, width=12),
    ], rows)
    return len(rows)


def _pd_mapping(book: Any, styles: dict[str, Any],
                result: dict[str, Any]) -> int:
    sheet = _step_sheet(book, styles, "05 PD Mapping",
                        "Score to PD, and on what basis they compare",
                        "Step five. A twelve-month PD may be compared only "
                        "with a twelve-month observed default rate on the "
                        "same eligible population; it is not comparable with "
                        "a delinquency rate measured at a date.")
    cohort = _cohort_level(result)
    before, after = cohort.get("before") or {}, cohort.get("after") or {}
    rows = []
    for key, label in (("pd_ttc", "Through-the-cycle PD"),
                       ("pd_pit_12m", "Point-in-time 12-month PD"),
                       ("pd_pit_lifetime", "Point-in-time lifetime PD")):
        one, two = before.get(key), after.get(key)
        if one is None and two is None:
            continue
        rows.append({"measure": label, "before": one, "after": two,
                     "change": (None if one is None or two is None
                                else float(two) - float(one))})
    if not rows:
        return _not_applicable(
            sheet, "This result does not carry cohort-level PD averages.")
    sheet.table([
        ST.Col("measure", "Measure", ST.TEXT, width=34),
        ST.Col("before", "Baseline", ST.RATE4),
        ST.Col("after", "Scenario", ST.RATE4),
        ST.Col("change", "Change", ST.RATE4, signed=True),
    ], rows, autofilter=False)
    sheet.section("Comparison basis")
    sheet.pairs([
        ("Event", "First new default — 90+ DPD or recorded unlikeliness to "
                  "pay"),
        ("Horizon", "12 months from the observation month"),
        ("Eligible population", "Facilities not already in default at "
                                "observation"),
        ("Weighting", "Unweighted by account, unless a sheet says otherwise"),
        ("Comparable with", "ret.odr.12m — the observed 12-month default rate"),
        ("NOT comparable with", "any 30+ DPD rate, which is a stock at a date "
                                "rather than an event over a window"),
    ])
    return len(rows)


def _stage_decisions(book: Any, styles: dict[str, Any],
                     result: dict[str, Any]) -> int:
    sheet = _step_sheet(book, styles, "06 Stage Decisions",
                        "Staging before and after, and the policy applied",
                        "Step six. A stage change alters the loss HORIZON — "
                        "twelve months against lifetime — so its effect "
                        "appears once, here and in the waterfall's staging "
                        "step, and never again under PD.")
    scenario = result.get("scenario") or {}
    mode = str(scenario.get("staging_mode") or "")
    sheet.pairs([
        ("Staging mode", mode or "—"),
        ("What that means",
         "Each facility keeps the stage the book published; the scenario "
         "does not re-stage it." if "frozen" in mode else
         "The governed staging policy is re-run on the shocked values, so a "
         "facility may move stage as a consequence of the shock."),
        ("Policy version", scenario.get("staging_policy_version") or "—"),
    ])
    rows = _matrix_rows((result.get("stage_movement") or {}).get("matrix"))
    if not rows:
        return _not_applicable(
            sheet, "No facility changed IFRS 9 stage under this scenario"
                   + (" — staging is frozen for this run." if "frozen" in mode
                      else "."))
    sheet.table([
        ST.Col("from", "From stage", ST.COUNT, width=12),
        ST.Col("to", "To stage", ST.COUNT, width=12),
        ST.Col("facilities", "Facilities", ST.COUNT),
        ST.Col("exposure_sar", "Exposure (SAR)", ST.MONEY),
        ST.Col("direction", "Direction", ST.TEXT, width=12),
    ], rows, autofilter=False)
    return len(rows)


def _lgd_ead(book: Any, styles: dict[str, Any],
             result: dict[str, Any]) -> int:
    sheet = _step_sheet(book, styles, "07 LGD EAD Recovery",
                        "Loss given default, exposure at default, recovery",
                        "Step seven. Where a channel is untouched the before "
                        "and after are equal and the sheet says so — an "
                        "invented LGD movement on a scenario that moved "
                        "income would be a fabrication.")
    cohort = _cohort_level(result)
    before, after = cohort.get("before") or {}, cohort.get("after") or {}
    rows = []
    for key, label, kind in (("lgd", "Loss given default", ST.RATE4),
                             ("ccf", "Credit conversion factor", ST.RATE4),
                             ("ead_sar", "Exposure at default (SAR)",
                              ST.MONEY),
                             ("recovery_rate", "Recovery rate", ST.RATE4),
                             ("recovery_delay_months", "Recovery delay "
                                                       "(months)", ST.POINTS)):
        one, two = before.get(key), after.get(key)
        if one is None and two is None:
            continue
        change = (None if one is None or two is None
                  else float(two) - float(one))
        rows.append({"measure": label, "before": one, "after": two,
                     "change": change, "kind": kind,
                     "status": ("Unchanged by this scenario" if change == 0
                                else "Moved by this scenario")})
    if not rows:
        return _not_applicable(
            sheet, "This result does not carry cohort-level LGD, EAD or "
                   "recovery averages.")
    sheet.table([
        ST.Col("measure", "Measure", ST.TEXT, width=34),
        ST.Col("before", "Baseline", ST.POINTS),
        ST.Col("after", "Scenario", ST.POINTS),
        ST.Col("change", "Change", ST.POINTS, signed=True),
        ST.Col("status", "Status", ST.TEXT, width=30),
    ], rows, autofilter=False)
    bounded = result.get("bounded") or {}
    if bounded:
        sheet.section("Bounds reached")
        sheet.pairs([(k, v) for k, v in bounded.items()])
        sheet.line("A facility whose shocked value passed a policy bound was "
                   "clipped to it. The count is reported because the move "
                   "applied to those facilities is smaller than the one "
                   "requested.")
    return len(rows)


def _ecl_calcs(book: Any, styles: dict[str, Any],
               result: dict[str, Any]) -> int:
    sheet = _step_sheet(book, styles, "08 ECL Calculations",
                        "Per-scenario ECL, weights, overlay and the final "
                        "allowance",
                        "Step eight, the identity itself. The weighted "
                        "allowance is the exact weighted combination of the "
                        "three published scenario values; it is not rounded a "
                        "second time, which is what keeps a neutral run "
                        "reproducing the published figure exactly.")
    cohort = _cohort_level(result)
    before, after = cohort.get("before") or {}, cohort.get("after") or {}
    weights = (result.get("scenario") or {}).get("scenario_weights") or {}
    rows = []
    for key, label in (("ecl_base_sar", "Base scenario"),
                       ("ecl_upturn_sar", "Upturn scenario"),
                       ("ecl_downturn_sar", "Downturn scenario"),
                       ("ecl_weighted_sar", "Probability-weighted"),
                       ("management_overlay_sar", "Management overlay"),
                       ("ecl_final_sar", "Final allowance")):
        one, two = _money(before.get(key)), _money(after.get(key))
        if one is None and two is None:
            continue
        name = key.replace("ecl_", "").replace("_sar", "")
        rows.append({
            "scenario": label,
            "weight": weights.get(name),
            "before": one, "after": two,
            "change": None if (one is None or two is None) else two - one,
        })
    if not rows:
        return _not_applicable(
            sheet, "This result does not carry per-scenario ECL values.")
    sheet.table([
        ST.Col("scenario", "Component", ST.TEXT, width=30),
        ST.Col("weight", "Weight", ST.RATE),
        ST.Col("before", "Baseline (SAR)", ST.MONEY),
        ST.Col("after", "Scenario (SAR)", ST.MONEY),
        ST.Col("change", "Change (SAR)", ST.MONEY, signed=True),
    ], rows, autofilter=False)
    return len(rows)


# ========================================== the aggregate migration views

def _cut_named(result: dict[str, Any], *needles: str) -> dict[str, Any] | None:
    for cut in (result.get("baseline") or {}).get("cuts") or []:
        label = str(cut.get("label") or "").lower()
        if any(one in label for one in needles):
            return cut
    return None


def _dpd(book: Any, styles: dict[str, Any], result: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "DPD Migration",
                  "Delinquency buckets, and what the scenario did to them",
                  "The bucket profile the scenario started from, and the "
                  "movement it applied. Facilities that move are the worst in "
                  "the bucket they leave and land on what THIS book shows for "
                  "the bucket they enter — read from the data, never assumed.")
    cut = _cut_named(result, "days past due", "dpd", "delinquen")
    rows = list((cut or {}).get("rows") or [])
    if not rows:
        return _not_applicable(sheet, "The baseline carried no delinquency "
                                      "cut for this cohort.")
    first = sheet.at
    sheet.table(_CUT_COLUMNS, rows, autofilter=False)
    sheet.chart(book, {
        "type": "column",
        "title": "Exposure by delinquency bucket (SAR)",
        "series": [{
            "name": "Exposure",
            "categories": [sheet.name, first + 1, 0, first + len(rows), 0],
            "values": [sheet.name, first + 1, 3, first + len(rows), 3],
            "fill": {"color": ST.TEAL},
        }],
        "y_axis": {"name": "SAR", "num_format": ST.F_MONEY0},
        "legend": "none",
    })
    moved = (result.get("migration") or {}).get("dpd")
    if moved:
        sheet.section("What the scenario moved")
        sheet.pairs(list(moved.items()))
    return len(rows)


def _bands(book: Any, styles: dict[str, Any], result: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "Behavioural Bands",
                  "Behavioural score bands in this cohort",
                  "E is the worst band and A+ the best: the retail "
                  "scorecards run higher-is-safer, which is the opposite "
                  "direction from the Early Warning Score.")
    cut = _cut_named(result, "behavioural", "score band")
    rows = list((cut or {}).get("rows") or [])
    if not rows:
        return _not_applicable(sheet, "The baseline carried no behavioural "
                                      "band cut for this cohort.")
    first = sheet.at
    sheet.table(_CUT_COLUMNS, rows, autofilter=False)
    sheet.chart(book, {
        "type": "column",
        "title": "Exposure by behavioural score band (SAR)",
        "series": [{
            "name": "Exposure",
            "categories": [sheet.name, first + 1, 0, first + len(rows), 0],
            "values": [sheet.name, first + 1, 3, first + len(rows), 3],
            "fill": {"color": ST.NAVY_LIGHT},
        }],
        "y_axis": {"name": "SAR", "num_format": ST.F_MONEY0},
        "legend": "none",
    })
    return len(rows)


def _stages(book: Any, styles: dict[str, Any], result: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "Stage Migration",
                  "IFRS 9 stages in this cohort",
                  "Stage decides the loss horizon: twelve months in Stage 1, "
                  "lifetime in Stages 2 and 3.")
    cut = _cut_named(result, "stage")
    rows = list((cut or {}).get("rows") or [])
    if not rows:
        return _not_applicable(sheet, "The baseline carried no stage cut for "
                                      "this cohort.")
    sheet.table(_CUT_COLUMNS, rows, autofilter=False)
    return len(rows)


# ============================================ assumptions, dictionary, trace

def _assumptions(book: Any, styles: dict[str, Any],
                 result: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "Assumptions",
                  "Method, policy, weights and what this cannot tell you")
    method = result.get("methodology") or {}
    scenario = result.get("scenario") or {}
    sheet.pairs([
        ("Method", method.get("name") or "—"),
        ("What it does", method.get("what") or "—"),
        ("Authority", method.get("authority") or "—"),
        ("Staging mode", scenario.get("staging_mode") or "—"),
        ("Methodology version", scenario.get("methodology_version") or "—"),
        ("Snapshot date", scenario.get("snapshot_date") or "—"),
        ("Dataset version", scenario.get("dataset_version") or "—"),
    ])
    weights = scenario.get("scenario_weights") or {}
    if weights:
        sheet.section("Macroeconomic scenario weights")
        sheet.table([ST.Col("scenario", "Scenario", ST.TEXT, width=20),
                     ST.Col("weight", "Weight", ST.RATE)],
                    [{"scenario": k.title(), "weight": v}
                     for k, v in weights.items()], autofilter=False)
    rows = list(result.get("assumptions") or [])
    if rows:
        sheet.section("Assumptions")
        for one in rows:
            sheet.line(str(one), "text")
    limits = list(result.get("limitations") or [])
    if limits:
        sheet.section("Limitations")
        for one in limits:
            sheet.line(str(one), "warn")
    sheet.section("Disclosure")
    sheet.line(DISCLOSURE, "warn")
    return len(rows) + len(limits)


#: Every column this workbook can write, and what it means. §12.2 asks for a
#: data dictionary; a reader who meets "CCF" on sheet 07 should not have to
#: guess.
DICTIONARY: tuple[tuple[str, str, str], ...] = (
    ("Customers", "Count", "Distinct customer identifiers. A customer with "
                           "several facilities is counted once."),
    ("Accounts / Facilities", "Count", "Distinct facility identifiers."),
    ("Exposure (SAR)", "Money", "Gross carrying amount at the month-end."),
    ("EAD (SAR)", "Money", "Exposure at default: drawn balance plus the "
                           "credit conversion factor applied to any undrawn "
                           "commitment."),
    ("TTC PD", "Rate", "Through-the-cycle probability of default, a long-run "
                       "average that does not move with the cycle."),
    ("PIT 12-month PD", "Rate", "Point-in-time probability of default over "
                                "the next twelve months, on the current "
                                "conditions."),
    ("PIT lifetime PD", "Rate", "Point-in-time probability of default over "
                                "the remaining life of the facility."),
    ("LGD", "Rate", "Loss given default: the share of exposure expected to be "
                    "lost once a facility defaults, after recoveries and "
                    "their delay are discounted."),
    ("CCF", "Rate", "Credit conversion factor: the share of an undrawn "
                    "commitment expected to be drawn before default."),
    ("Weighted ECL (SAR)", "Money", "Probability-weighted expected credit "
                                    "loss across the three macroeconomic "
                                    "scenarios."),
    ("Final allowance (SAR)", "Money", "Weighted ECL after any management "
                                       "overlay. This is the published "
                                       "figure."),
    ("Coverage", "Rate", "Weighted ECL divided by gross carrying amount."),
    ("Days past due", "Count", "Days since the oldest unpaid contractual "
                               "instalment."),
    ("Bucket", "Text", "Governed delinquency band: CURRENT, 1-29, 30-59, "
                       "60-89, 90-179, 180+."),
    ("Stage", "Count", "IFRS 9 stage. 1 is twelve-month loss, 2 and 3 are "
                       "lifetime."),
    ("Behavioural score", "Points", "Current-behaviour scorecard output. "
                                    "Higher is safer."),
    ("Band", "Text", "Score band, E (worst) through A+ (best)."),
    ("Share of exposure", "Rate", "This row's exposure divided by the "
                                  "cohort's, not the book's."),
    ("Change (SAR)", "Money", "Scenario minus baseline. Negative values are "
                              "shown in parentheses and coloured green, "
                              "because a fall in expected loss is an "
                              "improvement."),
)


def _dictionary(book: Any, styles: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "Data Dictionary",
                  "Every column in this workbook, defined")
    sheet.table([
        ST.Col("term", "Column", ST.TEXT, width=26),
        ST.Col("kind", "Kind", ST.TEXT, width=12),
        ST.Col("definition", "What it means", ST.WRAP, width=86),
    ], [{"term": a, "kind": b, "definition": c} for a, b, c in DICTIONARY],
        autofilter=False)
    sheet.section("How numbers are written")
    sheet.pairs([
        ("Counts", "#,##0"),
        ("Money", "#,##0.00, with SAR named in the column heading"),
        ("Probabilities and rates", "0.00% — a PD of 0.0348 reads as 3.48%"),
        ("Negative values", "In parentheses"),
        ("Missing values", "Blank. A zero is a measurement; a blank is the "
                           "absence of one, and this workbook does not write "
                           "the first for the second."),
    ])
    return len(DICTIONARY)


def _trace(book: Any, styles: dict[str, Any], result: dict[str, Any],
           selection: dict[str, Any]) -> int:
    sheet = Sheet(book, styles, "Trace & Checks",
                  "What produced these figures, and what was checked",
                  "Enough to reproduce this workbook from the same book on "
                  "another machine, and to tell whether the figures still "
                  "describe the data underneath.")
    sheet.pairs([
        ("Selection ID", selection.get("selection_id")),
        ("Source module", selection.get("source_module")),
        ("Source route", selection.get("source_route")),
        ("Source level", selection.get("source_level")),
        ("Reporting month", result.get("month")),
        ("Model version", selection.get("source_model_version")),
        ("Rulebook version", selection.get("source_rulebook_version")),
        ("Panel version", selection.get("source_panel_version")),
        ("Taxonomy version", selection.get("taxonomy_version")),
        ("Dataset version", (result.get("scenario") or {})
                            .get("dataset_version")),
        ("Selection created", selection.get("created_at")),
        ("Workbook built (UTC)",
         datetime.now(UTC).isoformat(timespec="seconds")),
    ])
    sheet.section("Population")
    sheet.pairs([
        ("Selected facilities", selection.get("selected_account_count")),
        ("Selected customers", selection.get("selected_customer_count")),
        ("Facilities actually stressed", result.get("stressed_facilities")),
        ("Narrowing", (result.get("narrowing") or {}).get("said")
                      or "No narrowing was applied"),
    ])

    sheet.section("Checks")
    checks = []
    steps = result.get("waterfall") or {}
    if steps.get("steps"):
        residual = abs(float(steps.get("residual_sar") or 0.0))
        checks.append({
            "check": "The waterfall's steps sum to the total change",
            "result": "Pass" if residual < 1.0 else "Review",
            "detail": f"residual SAR {residual:,.2f}"})
    parity = result.get("parity")
    if parity:
        checks.append({
            "check": "A neutral scenario reproduces the published allowance",
            "result": "Pass" if parity.get("within_tolerance") else "Review",
            "detail": str(parity.get("note") or "")})
    levels = result.get("levels") or []
    if len(levels) > 1:
        moves = {round(float((one.get("delta") or {})
                             .get("ecl_weighted_sar") or 0.0), 2)
                 for one in levels}
        checks.append({
            "check": "The absolute movement is the same at every level",
            "result": "Pass" if len(moves) == 1 else "Review",
            "detail": f"{len(moves)} distinct movement(s) across "
                      f"{len(levels)} levels"})
    bounded = result.get("bounded") or {}
    for name, count in bounded.items():
        checks.append({
            "check": f"Facilities clipped at a policy bound under {name}",
            "result": "Noted",
            "detail": f"{int(count):,} facilities"})
    if not checks:
        checks.append({"check": "No automated check applies to this run",
                       "result": "Not run",
                       "detail": "A neutral or single-step scenario carries "
                                 "no decomposition to reconcile."})
    sheet.table([
        ST.Col("check", "Check", ST.WRAP, width=52),
        ST.Col("result", "Result", ST.TEXT, width=12),
        ST.Col("detail", "Detail", ST.WRAP, width=44),
    ], checks, autofilter=False)
    return len(checks)
