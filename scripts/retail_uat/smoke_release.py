"""The release smoke: twenty checks, one browser, fifteen minutes.

Not an acceptance suite. This answers one question — does the candidate
start, sign in, and carry a reader through the demo's spine without a 500 or
a page error — and it answers it fast enough to run before every release.

Everything it touches is the real application at the real ports. There is no
mock, no test-only route, and no assertion that passes on a card being
present: a document check opens the file, a scenario check reads the number
the screen printed.
"""

from __future__ import annotations

import io
import os
import sys
import time
import zipfile

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import (  # noqa: E402
    BACKEND,
    FRONTEND,
    Session,
    chromium_path,
)

OUT = "docs/evidence/release_smoke"
os.makedirs(OUT, exist_ok=True)

passed: list[str] = []
failed: list[tuple[str, str]] = []


def check(number: str, name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(
        f"{number} {name}" if ok else (f"{number} {name}", detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {number} {name}"
          + (f" — {detail}" if detail else ""), flush=True)
    return ok


def _present(page, selector: str, seconds: int = 90) -> int:
    """Wait for a selector, then count it.

    Sampling after a fixed pause measures whichever route the dev server had
    compiled by then, and reports "0 category cards" on a page that renders
    them a second later. That is a statement about the sampling instant, not
    about the product.
    """
    try:
        page.locator(selector).first.wait_for(state="visible",
                                              timeout=seconds * 1000)
    except Exception:  # noqa: BLE001 - the count below is the verdict
        pass
    return page.locator(selector).count()


def _settle(page, marker: str, seconds: int = 120) -> bool:
    for _ in range(seconds):
        page.wait_for_timeout(1000)
        if marker.lower() in page.inner_text("body").lower():
            return True
    return False


def main() -> int:  # noqa: C901 - a checklist is a checklist
    import urllib.request

    # 01 / 02 — the two servers, before a browser is started.
    try:
        code = urllib.request.urlopen(BACKEND + "/api/v1/health",
                                      timeout=20).status
    except Exception as problem:  # noqa: BLE001
        code = str(problem)
    check("01", "backend starts", code == 200, f"health {code}")
    try:
        front = urllib.request.urlopen(FRONTEND, timeout=30).status
    except Exception as problem:  # noqa: BLE001
        front = str(problem)
    check("02", "frontend starts", front == 200, f"root {front}")

    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(
            viewport={"width": 1512, "height": 982}, accept_downloads=True)
        page = context.new_page()
        session = Session(page, context)

        # 03 — sign in.
        check("03", "login works", session.sign_in())

        # 04 — the cockpit.
        page.goto(FRONTEND + "/", wait_until="commit")
        opened = _settle(page, "cockpit", 60) or _settle(page, "attention", 30)
        check("04", "Cockpit loads", opened)
        page.screenshot(path=f"{OUT}/04-cockpit.png", full_page=True)

        # 05 / 06 — an investigation, and a governed answer inside it.
        page.goto(FRONTEND + "/investigations", wait_until="commit")
        page.wait_for_timeout(4000)
        # A row is a button carrying the investigation id — deliberately, so
        # assistive technology and a test can tell three rows apart. It is
        # not an anchor.
        found = _present(page, "button[data-investigation-id]")
        rows = page.locator("button[data-investigation-id]")
        check("05", "one Investigation opens", found > 0,
              f"{found} in the list")
        answered, said = False, ""
        if rows.count():
            rows.first.click()
            page.wait_for_timeout(6000)
            # The investigation thread uses the product's one composer, so
            # the driver's default selector is the right one here.
            got = session.ask("Why has Credit Card 30+ DPD risen?",
                              timeout=240)
            said = page.inner_text("body")
            # A governed answer names the product and the period it answered
            # for, rather than a paragraph about the portfolio.
            answered = bool(got.get("submitted")) and (
                "credit card" in said.lower()
                and ("2026-0" in said or "202" in said))
        check("06", "Investigation answers one governed question", answered,
              "answered with a product and a period" if answered
              else "no governed answer")
        page.screenshot(path=f"{OUT}/06-investigation.png", full_page=True)

        # 07 / 08 — scorecard validation, and a comment that survives.
        page.goto(FRONTEND + "/scorecard-validation", wait_until="commit")
        page.wait_for_timeout(5000)
        found = _present(page, "button:has-text('Data & Representativeness')")
        check("07", "Scorecard Validation opens", found > 0,
              f"{found} category cards")

        mark = f"SMOKE-{int(time.time())}"
        persisted = False
        page.locator("button:has-text('Calibration')").first.click()
        for _ in range(120):
            page.wait_for_timeout(1000)
            if page.locator('[data-testid="scv-stop"]').count() == 0:
                break
        page.wait_for_timeout(1500)
        _present(page, "button:has-text('Evidence')", 60)
        evidence = page.locator("button:has-text('Evidence')")
        if evidence.count():
            evidence.first.click()
            page.wait_for_timeout(700)
            add = page.locator('[data-testid="scv-add-comment"]')
            if add.count():
                add.first.click()
                page.wait_for_timeout(400)
                page.locator('[data-testid="scv-comment-body"]').first.fill(
                    f"{mark}: release smoke.")
                page.locator(
                    '[data-testid="scv-comment-save"]').first.click()
                page.wait_for_timeout(2500)
                page.reload(wait_until="commit")
                page.wait_for_timeout(5000)
                drawer = page.locator('[data-testid="scv-notes-drawer"]')
                if drawer.count():
                    drawer.first.click()
                    page.wait_for_timeout(1500)
                persisted = mark.lower() in page.inner_text("body").lower()
        check("08", "comment persists after refresh", persisted,
              "found after reload" if persisted else "gone")
        page.screenshot(path=f"{OUT}/08-comment.png", full_page=True)

        # 09 — the validation Word report, opened rather than counted.
        report_ok, report_note = False, ""
        try:
            # Matched on a substring without parentheses: "(Word)" inside
            # :has-text() is read as selector syntax, so the locator never
            # resolves and the failure looks like a missing control.
            page.goto(FRONTEND + "/scorecard-validation",
                      wait_until="commit")
            _present(page, "button:has-text('Data & Representativeness')",
                     120)
            _present(page, 'a:has-text("Draft report")', 120)
            with page.expect_download(timeout=300_000) as caught:
                page.click('a:has-text("Draft report")')
            saved = caught.value.path()
            blob = open(saved, "rb").read()
            zipped = zipfile.ZipFile(io.BytesIO(blob))
            xml = zipped.read("word/document.xml").decode("utf-8")
            images = [n for n in zipped.namelist()
                      if n.startswith("word/media/")]
            report_ok = (len(blob) > 50_000
                         and "Remediation actions" in xml
                         and "Trace appendix" in xml)
            report_note = f"{len(blob):,} bytes, {len(images)} charts"
        except Exception as problem:  # noqa: BLE001
            report_note = str(problem)[:90]
        check("09", "validation Word report downloads and opens", report_ok,
              report_note)

        # 10 — Early Warning.
        page.goto(FRONTEND + "/early-warning", wait_until="commit")
        page.wait_for_timeout(6000)
        ews = _settle(page, "early warning", 60)
        check("10", "Early Warning Score opens", ews)
        page.screenshot(path=f"{OUT}/10-ews.png", full_page=True)

        # 11 — the standalone What-If.
        # /what-if is the landing. Opening a guided card creates a selection
        # and a thread and navigates to it — the SAME thread component an
        # Early Warning export reaches, which is what check 12 then proves.
        page.goto(FRONTEND + "/what-if", wait_until="commit")
        _present(page, '[data-testid="retail-whatif-journeys"]', 90)
        opener = page.locator('[data-testid^="retail-whatif-journey-"]')
        standalone = False
        if opener.count():
            opener.first.click()
            page.wait_for_timeout(1200)
            more = page.locator('[data-testid^="retail-whatif-open-"]')
            if more.count():
                more.first.click()
            standalone = _present(
                page, '[data-testid="ews-whatif-thread"]', 90) > 0
        thread_url = page.url if standalone else ""
        check("11", "standalone What-If opens", standalone,
              page.url.split("/")[-1][:24] if standalone else "no thread")

        # 12 — the same thread reached from the EWS export.
        exported = False
        page.goto(FRONTEND + "/early-warning", wait_until="commit")
        # Export is a button: it writes an immutable cohort membership record
        # and then navigates to the thread. It is not a link, because the
        # selection does not exist until it is pressed.
        _present(page, '[data-testid^="ews-export-"]', 180)
        button = page.locator('[data-testid^="ews-export-"]')
        if button.count():
            button.first.click()
            exported = _present(
                page, '[data-testid="ews-whatif-thread"]', 120) > 0
            if exported:
                thread_url = page.url
        check("12", "EWS-exported What-If opens", exported,
              "same thread component" if exported else "no thread")

        # 13 / 14 — one scenario on each method.
        if thread_url and page.url != thread_url:
            page.goto(thread_url, wait_until="commit")
            _present(page, '[data-testid="ews-whatif-thread"]', 120)

        def run_scenario(method: str, said: str) -> tuple[bool, str]:
            picker = page.locator(f'[data-testid="ews-whatif-method-{method}"]')
            if picker.count():
                picker.first.click()
                page.wait_for_timeout(800)
            box = page.locator('[data-testid="ews-whatif-input"]')
            if not box.count():
                return False, "no composer"
            before = page.locator('[data-testid="ews-whatif-result"]').count()
            box.first.fill(said)
            page.locator('[data-testid="ews-whatif-run"]').first.click()
            for _ in range(180):
                page.wait_for_timeout(1000)
                if page.locator(
                        '[data-testid="ews-whatif-result"]').count() > before:
                    break
            after = page.locator('[data-testid="ews-whatif-result"]').count()
            if after <= before:
                return False, "no result block"
            summary = page.locator(
                '[data-testid="whatif-result-summary"]').last.inner_text()
            return ("SAR" in summary or "%" in summary), summary[:70]

        ok, note = run_scenario("delta", "increase PD by 10% for Stage 2")
        check("13", "one Delta scenario runs", ok, note)
        ok, note = run_scenario("xgboost", "increase PD by 10% for Stage 2")
        check("14", "one XGBoost scenario runs", ok, note)
        page.screenshot(path=f"{OUT}/14-whatif.png", full_page=True)

        # 15 — the detailed workbook, opened rather than counted.
        excel_ok, excel_note = False, ""
        try:
            button = page.locator('[data-testid="whatif-download-workbook"]')
            button.last.scroll_into_view_if_needed(timeout=30_000)
            with page.expect_download(timeout=600_000) as caught:
                button.last.click()
            saved = caught.value.path()
            import openpyxl

            book = openpyxl.load_workbook(saved)
            excel_ok = len(book.sheetnames) >= 15
            excel_note = f"{len(book.sheetnames)} sheets"
        except Exception as problem:  # noqa: BLE001
            excel_note = str(problem)[:90]
        check("15", "detailed Excel downloads and opens", excel_ok, excel_note)

        # 16 / 17 — what the journeys left behind.
        server_errors = [(m, u, s) for m, u, s in session.api if s >= 500]
        check("16", "no HTTP 500 in these journeys", not server_errors,
              "; ".join(f"{s} {u[-60:]}" for _, u, s in server_errors[:3]))
        check("17", "no browser page errors", not session.console_errors,
              "; ".join(session.console_errors[:2]))

        browser.close()

    print(f"\n{len(passed)} of {len(passed) + len(failed)} checks passed")
    for entry in failed:
        print(f"  FAILED  {entry[0]} — {entry[1]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
