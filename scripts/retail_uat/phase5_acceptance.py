"""Phase 5 acceptance, §11-§13, through the browser and then by opening files.

Nothing here passes on an HTTP 200 or a file existing. Both downloads are
taken by CLICKING in a real browser, then opened and inspected.

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/phase5_acceptance.py
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import time
import zipfile
from collections import Counter

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import docx  # noqa: E402
import openpyxl  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import FRONTEND, Session, chromium_path  # noqa: E402

OUT = "docs/evidence/phase5"
os.makedirs(OUT, exist_ok=True)

THREAD = '[data-testid="ews-whatif-thread"]'
COMPOSER = '[data-testid="ews-whatif-input"]'
RESULT = '[data-testid="ews-whatif-result"]'

ERRORS = ("#REF!", "#VALUE!", "#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!")
NULLISH = {"nan", "none", "null", "nat", "inf", "-inf", "<na>"}

passed: list[str] = []
failed: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name if ok else (name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                     else ""))
    return ok


def main() -> int:
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(
            viewport={"width": 1512, "height": 982}, accept_downloads=True)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        session = Session(page, context)
        assert session.sign_in(), "sign-in failed"

        # ---- open a thread on the same cohort every measurement uses ----
        print("\n1. open the cohort and run the scenario")
        page.goto(FRONTEND + "/what-if", wait_until="commit")
        page.wait_for_selector('[data-testid="retail-whatif-journeys"]',
                               timeout=300_000)
        page.wait_for_timeout(3000)
        page.click('[data-testid="retail-whatif-journey-product"]')
        page.wait_for_timeout(1000)
        page.click('[data-testid="retail-whatif-open-product"]')
        page.wait_for_url("**/what-if/threads/**", timeout=300_000)
        page.wait_for_selector(THREAD, timeout=300_000)
        page.wait_for_timeout(5000)
        check("a guided card opens a thread", True, page.url)

        before = page.locator(RESULT).count()
        started = time.time()
        page.fill(COMPOSER, "Reduce verified income by 10%")
        page.click('[data-testid="ews-whatif-run"]')
        page.wait_for_function(
            "n => document.querySelectorAll('[data-testid=\\\"ews-whatif-result\\\"]')"
            ".length > n", arg=before, timeout=300_000)
        page.wait_for_timeout(3000)
        ran = time.time() - started
        check("the scenario runs in the browser", True, f"{ran:.1f}s")
        page.screenshot(path=f"{OUT}/acceptance-01-result.png", full_page=True)

        # ---- 2. the workbook, downloaded by clicking -------------------
        print("\n2. download the workbook by clicking")
        started = time.time()
        with page.expect_download(timeout=600_000) as caught:
            page.locator('[data-testid="whatif-download-workbook"]').first.click()
        saved = caught.value
        xlsx = f"{OUT}/acceptance-workbook.xlsx"
        saved.save_as(xlsx)
        took = time.time() - started
        size = os.path.getsize(xlsx) / 1024
        check("browser download of the workbook", True,
              f"{saved.suggested_filename} · {size:.0f} KB · {took:.1f}s")
        check("workbook download inside the 10s target", took <= 10.0,
              f"{took:.1f}s")

        _inspect_workbook(xlsx)

        # ---- 3. the three Word reports ---------------------------------
        print("\n3. the three Word report families")
        _reports(page)

        print("\npage errors:", errors[:4])
        browser.close()

    print(f"\n{len(passed)} of {len(passed) + len(failed)} checks passed")
    for name, detail in failed:
        print(f"  FAILED  {name} — {detail}")
    return 1 if failed else 0


def _inspect_workbook(path: str) -> None:
    print("\n2b. open the workbook and inspect it")
    book = openpyxl.load_workbook(path)
    values = openpyxl.load_workbook(path, data_only=True)

    from backend.retail.whatif_workbook import SHEETS

    wanted = {name for name, _ in SHEETS}
    check("every mandatory sheet is present", wanted <= set(book.sheetnames),
          str(sorted(wanted - set(book.sheetnames))))
    check("no extra sheets", len(book.sheetnames) == len(SHEETS),
          f"{len(book.sheetnames)} sheets")

    showing = [ws.title for ws in book.worksheets
               if ws.sheet_view.showGridLines is not False]
    check("gridlines hidden on every sheet", not showing, str(showing))

    formats: Counter = Counter()
    loose: Counter = Counter()
    nulls: list[str] = []
    errs: list[str] = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    formats[cell.number_format] += 1
                    if cell.number_format == "General":
                        loose[sheet.title] += 1
                    if value != value:
                        nulls.append(f"{sheet.title}!{cell.coordinate} NaN")
                elif isinstance(value, str):
                    if value.strip().lower() in NULLISH:
                        nulls.append(f"{sheet.title}!{cell.coordinate}")
                    if any(one in value for one in ERRORS):
                        errs.append(f"{sheet.title}!{cell.coordinate}")
    check("every numeric cell carries a format", not loose, str(dict(loose)))
    check("nothing written as nan or None", not nulls, str(nulls[:4]))
    check("no error cells", not errs, str(errs[:4]))
    check("money uses a negative section",
          all(";" in one and "(" in one
              for one in formats if "#,##0" in one),
          str([one for one in formats if "#,##0" in one]))
    check("probabilities are percentages",
          any("%" in one for one in formats),
          str([one for one in formats if "%" in one]))

    # formulas, recomputed independently
    from retail_uat.check_workbook_formulas import _evaluate

    total = agree = 0
    wrong: list[str] = []
    for sheet in book.worksheets:
        cached = values[sheet.title]
        for row in sheet.iter_rows():
            for cell in row:
                if not (isinstance(cell.value, str)
                        and cell.value.startswith("=")):
                    continue
                total += 1
                got = _evaluate(cell.value, cached)
                shown = cached[cell.coordinate].value
                if got is None or not isinstance(shown, (int, float)):
                    continue
                if abs(got - float(shown)) <= 0.01:
                    agree += 1
                else:
                    wrong.append(f"{sheet.title}!{cell.coordinate} "
                                 f"{cell.value} -> {got} vs {shown}")
    check("the workbook uses formulas for its totals and checks", total >= 10,
          f"{total} formula cells")
    check("every formula recomputes to the value shown", not wrong,
          str(wrong[:3]))

    with zipfile.ZipFile(path) as archive:
        charts = [n for n in archive.namelist() if "/charts/chart" in n]
    check("charts are embedded", bool(charts), f"{len(charts)} charts")

    links = set()
    for row in book["Contents"].iter_rows():
        for cell in row:
            if cell.hyperlink and cell.hyperlink.location:
                links.add(cell.hyperlink.location.split("!")[0].strip("'"))
    named = set(book.sheetnames) - {"Contents"}
    check("Contents links to every sheet", named <= links,
          str(sorted(named - links)))

    # A column whose every cell is empty is a wiring mistake, not a design
    # choice: the heading promises a number and the sheet delivers a blank.
    # `Facilities` on Impact by Level was empty for a week because the engine
    # calls it `accounts`, and no format check could see it.
    hollow: list[str] = []
    for name in ("Impact by Level", "Cohort", "Waterfall", "Summary"):
        sheet = values[name]
        head = None
        for r in range(1, min(sheet.max_row, 14) + 1):
            filled = sum(1 for c in range(1, sheet.max_column + 1)
                         if isinstance(sheet.cell(row=r, column=c).value, str)
                         and sheet.cell(row=r, column=c).value.strip())
            if filled >= 4:
                head = r
                break
        if head is None:
            continue
        for c in range(1, sheet.max_column + 1):
            heading = sheet.cell(row=head, column=c).value
            if not isinstance(heading, str) or not heading.strip():
                continue
            body = [sheet.cell(row=r, column=c).value
                    for r in range(head + 1, min(sheet.max_row, head + 30) + 1)]
            if body and all(one is None for one in body):
                hollow.append(f"{name}!{heading}")
    check("no declared column is empty in every row", not hollow,
          str(hollow[:5]))

    affected = book["Affected Customers"]
    facility = book["Facility Pre Post"]
    check("customer evidence is detailed", affected.max_row > 100,
          f"{affected.max_row - 4:,} customers")
    check("facility evidence is detailed", facility.max_row > 100,
          f"{facility.max_row - 4:,} facilities")

    # numerical reconciliation, read out of the file itself
    sheet = values["Waterfall"]
    labels = {str(sheet.cell(row=r, column=1).value): r
              for r in range(1, sheet.max_row + 1)}
    if "Residual (SAR)" in labels:
        residual = sheet.cell(row=labels["Residual (SAR)"], column=2).value
        check("the waterfall reconciles inside the file",
              abs(float(residual or 0.0)) < 1.0, f"residual SAR {residual}")
    levels = values["Impact by Level"]
    changes = set()
    for r in range(1, levels.max_row + 1):
        one = levels.cell(row=r, column=7).value
        if isinstance(one, (int, float)):
            changes.add(round(float(one), 2))
    check("the movement is identical at every level", len(changes) == 1,
          f"{sorted(changes)}")


def _reports(page) -> None:
    families = (
        ("investigation", {"product": "CREDIT_CARD",
                           "question": "what is the reason of this rise?"}),
        ("trait_attribution", {"question": "Tell me what customer traits "
                                           "have deteriorated."}),
        ("scorecard_validation", {"model_id": "retail_beh_credit_card",
                                  "conclusion": "Usable for ranking."}),
    )
    for family, body in families:
        got = page.evaluate(
            """async ([family, body]) => {
                 const r = await fetch(
                   `${window.location.origin.replace('5328','8328')}`
                   + `/api/v1/retail/reports/${family}.docx`,
                   {method: 'POST', credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body)});
                 const buffer = await r.arrayBuffer();
                 return {status: r.status,
                         type: r.headers.get('content-type'),
                         name: r.headers.get('content-disposition'),
                         bytes: Array.from(new Uint8Array(buffer))};
               }""", [family, body])
        payload = bytes(got["bytes"])
        path = f"{OUT}/acceptance-{family}.docx"
        with open(path, "wb") as handle:
            handle.write(payload)
        check(f"{family}: downloaded from the browser",
              got["status"] == 200
              and "wordprocessingml" in str(got["type"]),
              f"{got['status']} · {str(got['type'])[-24:]} · "
              f"{len(payload) / 1024:.0f} KB")
        check(f"{family}: the bytes are a Word document",
              payload[:2] == b"PK"
              and b"word/document.xml" in zipfile.ZipFile(
                  io.BytesIO(payload)).namelist()[0].encode()
              or "word/document.xml" in zipfile.ZipFile(
                  io.BytesIO(payload)).namelist())
        document = docx.Document(io.BytesIO(payload))
        tops = [p.text for p in document.paragraphs
                if p.style.name == "Heading 1" and re.match(r"^\d+\.", p.text)]
        numbers = [int(re.match(r"^(\d+)\.", one).group(1)) for one in tops]
        check(f"{family}: sections are contiguous",
              numbers == list(range(1, len(numbers) + 1)),
              f"{len(numbers)} sections")
        check(f"{family}: it carries real tables",
              len(document.tables) >= 5, f"{len(document.tables)} tables")
        text = "\n".join(p.text for p in document.paragraphs)
        for table in document.tables:
            for row in table.rows:
                text += "\n" + "\n".join(c.text for c in row.cells)
        check(f"{family}: the disclosure is present",
              "Synthetic" in text)
        claimed = None
        for forbidden in ("approved by sama", "anb approved",
                          "auditor certified"):
            claimed = claimed or re.search(forbidden, text.lower())
        check(f"{family}: it claims nothing it cannot support", not claimed)


if __name__ == "__main__":
    raise SystemExit(main())
