"""Drive the Early Warning -> What-If thread in a real browser.

The journey the demo guide walks, executed and photographed: a cohort exported
from an Early Warning card, its baseline drawn, three scenarios run in one
thread, a narrowing, a refusal, and the workbook.

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/whatif_thread_journey.py

Screenshots land in docs/evidence/retail_whatif/. Anything printed as a count
of zero is a page that did not render what it is supposed to.
"""
import os
import sys
import time

sys.path.insert(0, "scripts")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import FRONTEND, Session, chromium_path  # noqa: E402

OUT = "docs/evidence/retail_whatif"
os.makedirs(OUT, exist_ok=True)


def main() -> int:
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(viewport={"width": 1512, "height": 982})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        session = Session(page, context)
        assert session.sign_in(), "sign-in failed"

        def shot(name: str) -> None:
            page.screenshot(path=f"{OUT}/{name}.png", full_page=True)
            print("   shot", name)

        def ask(said: str, label: str, wait: int = 240_000) -> None:
            before = page.locator('[data-testid="ews-whatif-result"]').count()
            started = time.time()
            page.fill('[data-testid="ews-whatif-input"]', said)
            page.click('[data-testid="ews-whatif-run"]')
            try:
                page.wait_for_function(
                    "n => document.querySelectorAll("
                    "'[data-testid=\\"ews-whatif-result\\"],"
                    "[data-testid=\\"whatif-turn-asked\\"]').length > n",
                    arg=before, timeout=wait)
            except Exception as problem:  # noqa: BLE001
                print(f"   {label}: TIMED OUT — {problem}")
                return
            page.wait_for_timeout(3500)
            print(f"   {label}  {time.time() - started:.1f}s"
                  f"  results now {page.locator('[data-testid=\"ews-whatif-result\"]').count()}")

        # --- 1. the cohort, exported -----------------------------------
        print("1. Early Warning -> sub-product -> export")
        page.goto(FRONTEND + "/early-warning?product=CREDIT_CARD"
                  "&cls=SALARIED&sub=CC_PLATINUM", wait_until="commit")
        page.wait_for_selector('[data-testid="ews-sub-product-view"]',
                               timeout=300_000)
        page.wait_for_timeout(5000)
        page.click('[data-testid="ews-export-sub-product"]')
        page.wait_for_selector('[data-testid="ews-whatif-thread"]',
                               timeout=300_000)
        page.wait_for_timeout(7000)
        print("   url:", page.url)
        for name in ("ews-whatif-source", "ews-whatif-baseline",
                     "ews-whatif-cohort-charts", "ews-whatif-composer",
                     "ews-whatif-chips"):
            print(f"   {name}: {page.locator(f'[data-testid=\"{name}\"]').count()}")
        print("   baseline charts:",
              page.locator('[data-testid^="ews-whatif-chart-"]').count())
        print("   chips:", page.locator('[data-testid="ews-whatif-chip"]').count())
        shot("01-thread-opened")

        # --- 2. three scenarios, stacking ------------------------------
        print("2. three scenarios in one thread")
        page.click('[data-testid="ews-whatif-method-both"]')
        ask("Reduce verified income by 10%", "income -10%")
        shot("02-income")
        print("   waterfall:",
              page.locator('[data-testid="whatif-waterfall"]').count(),
              "chart:",
              page.locator('[data-testid="whatif-waterfall-chart"]').count(),
              "table:",
              page.locator('[data-testid="whatif-waterfall-table"]').count())
        print("   levels rows:",
              page.locator('[data-testid^="ews-whatif-level-"]').count())
        print("   challenger:",
              page.locator('[data-testid="ews-whatif-challenger"]').count())
        print("   interpretation:",
              page.locator('[data-testid="ews-whatif-interpretation"]').count())

        ask("Move 15% of Stage 1 exposure to Stage 2", "stage migration")
        ask("Move 20% of 30-59 DPD exposure to 90+", "dpd migration")
        print("   results stacked:",
              page.locator('[data-testid="ews-whatif-result"]').count(),
              "| questions asked:",
              page.locator('[data-testid="whatif-turn-said"]').count())
        shot("03-thread-stacked")

        # --- 3. narrowing, and a refusal -------------------------------
        print("3. narrowing and refusal")
        ask("Increase PIT 12-month PD by 20% for forward-risk customers only",
            "narrowed")
        print("   narrowing badge:",
              page.locator('[data-testid="whatif-narrowing"]').count())
        if page.locator('[data-testid="whatif-narrowing"]').count():
            print("   said:", page.locator('[data-testid="whatif-narrowing"]')
                  .last.inner_text()[:120])
        shot("04-narrowed")

        ask("make it worse somehow", "unreadable")
        asked = page.locator('[data-testid="whatif-turn-asked"]')
        print("   asked back:", asked.count())
        if asked.count():
            print("   question:", asked.last.inner_text()[:140]
                  .replace("\n", " "))
        shot("05-refusal")

        # --- 4. the workbook -------------------------------------------
        print("4. the workbook")
        with page.expect_download(timeout=300_000) as caught:
            page.locator('[data-testid="whatif-download-workbook"]').first.click()
        saved = caught.value
        target = f"{OUT}/downloaded.xlsx"
        saved.save_as(target)
        print("   downloaded:", saved.suggested_filename,
              f"{os.path.getsize(target) / 1024:.0f} KB")

        # --- 5. the standalone page ------------------------------------
        print("5. standalone What-If, guided journeys")
        page.goto(FRONTEND + "/what-if", wait_until="commit")
        page.wait_for_selector('[data-testid="retail-whatif-journeys"]',
                               timeout=300_000)
        page.wait_for_timeout(4000)
        print("   journeys:",
              page.locator('[data-testid^="retail-whatif-journey-"]').count())
        page.click('[data-testid="retail-whatif-journey-dpd"]')
        page.wait_for_timeout(1200)
        print("   prompts:",
              page.locator('[data-testid="retail-whatif-journey-prompt"]')
              .count())
        shot("06-standalone-journeys")

        print("\npage errors:", errors[:5])
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
