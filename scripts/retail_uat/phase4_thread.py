"""§8 in a browser: one thread, three doors, and the conversation survives.

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/phase4_thread.py
"""
import os
import sys
import time

sys.path.insert(0, "scripts")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import FRONTEND, Session, chromium_path  # noqa: E402

OUT = "docs/evidence/phase4"
os.makedirs(OUT, exist_ok=True)
THREAD = '[data-testid="ews-whatif-thread"]'
COMPOSER = '[data-testid="ews-whatif-input"]'
RESULT = '[data-testid="ews-whatif-result"]'

passed, failed = [], []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(viewport={"width": 1512, "height": 982})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        session = Session(page, context)
        assert session.sign_in(), "sign-in failed"

        def shot(name):
            page.screenshot(path=f"{OUT}/{name}.png", full_page=True)

        # --- 1. the landing page, with the raw catalogue gone --------------
        print("1. standalone landing")
        page.goto(FRONTEND + "/what-if", wait_until="commit")
        page.wait_for_selector('[data-testid="retail-whatif-journeys"]',
                               timeout=300_000)
        page.wait_for_timeout(4000)
        body = page.inner_text("body")
        check("no 'What this engine implements' block",
              "What this engine implements" not in body)
        raw = [n for n in ("pd_relative", "lgd_relative", "ccf_absolute",
                           "income_pct", "dpd_migration", "score_band_migration")
               if n in body]
        check("no raw parameter identifiers on the landing page", not raw,
              f"found {raw}" if raw else "")
        check("Delta model card present",
              page.locator('[data-testid="retail-whatif-open-delta"]').count() > 0)
        check("XGBoost model card present",
              page.locator('[data-testid="retail-whatif-open-xgboost"]').count() > 0)
        check("seven guided cards",
              page.locator('[data-testid^="retail-whatif-journey-"]').count() == 7,
              str(page.locator('[data-testid^="retail-whatif-journey-"]').count()))
        shot("01-landing")

        # --- 2. a guided card opens a real thread --------------------------
        print("2. a guided card opens a thread")
        page.click('[data-testid="retail-whatif-journey-dpd"]')
        page.wait_for_timeout(1200)
        page.click('[data-testid="retail-whatif-open-dpd"]')
        page.wait_for_url("**/what-if/threads/**", timeout=300_000)
        page.wait_for_selector(THREAD, timeout=300_000)
        page.wait_for_timeout(6000)
        url = page.url
        check("navigated to the canonical thread route",
              "/what-if/threads/" in url, url)
        check("the thread shows its cohort",
              page.locator('[data-testid="ews-whatif-source"]').count() > 0)
        check("the thread shows a baseline",
              page.locator('[data-testid="ews-whatif-baseline"]').count() > 0)
        check("the thread offers method cards",
              page.locator('[data-testid="ews-whatif-method-delta"]').count() > 0)
        shot("02-guided-thread")
        thread_url = url

        # --- 3. run the percentage-point shock -----------------------------
        print("3. the percentage-point shock the chips promise")
        before = page.locator(RESULT).count()
        page.fill(COMPOSER, "Increase LGD by 5 percentage points")
        page.click('[data-testid="ews-whatif-run"]')
        page.wait_for_function(
            "n => document.querySelectorAll('[data-testid=\\\"ews-whatif-result\\\"]')"
            ".length > n", arg=before, timeout=300_000)
        page.wait_for_timeout(4000)
        body = page.inner_text("body")
        check("LGD +5pp ran and produced a result",
              page.locator(RESULT).count() > before)
        check("the result does not show a raw identifier",
              "lgd_absolute_pp" not in body)
        shot("03-lgd-points")

        # --- 4. reopen it in a brand new browser context --------------------
        print("4. the conversation survives a new session")
        page2 = browser.new_context(viewport={"width": 1512, "height": 982}).new_page()
        fresh = Session(page2, page2.context)
        assert fresh.sign_in(), "second sign-in failed"
        page2.goto(thread_url, wait_until="commit")
        page2.wait_for_selector(THREAD, timeout=300_000)
        page2.wait_for_timeout(7000)
        check("the thread reopens with its turns in a new session",
              page2.locator(RESULT).count() > 0,
              f"{page2.locator(RESULT).count()} results")
        check("the question asked is still in the transcript",
              "percentage points" in page2.inner_text("body"))
        page2.screenshot(path=f"{OUT}/04-reopened.png", full_page=True)

        # --- 5. the Early Warning deep link still resolves -------------------
        print("5. the old Early Warning deep link")
        # `ews-headline` renders at the PORTFOLIO level only. Waiting for it
        # on a product-filtered URL waits for something that route never
        # draws, which reported the screen as broken when the selector was.
        page.goto(FRONTEND + "/early-warning?product=CREDIT_CARD",
                  wait_until="commit")
        page.wait_for_selector('[data-testid="ews-product-view"]',
                               timeout=300_000)
        page.wait_for_timeout(5000)
        exported = page.locator('[data-testid="ews-export-product"]')
        if exported.count():
            exported.first.click()
            page.wait_for_selector(THREAD, timeout=300_000)
            page.wait_for_timeout(6000)
            check("an Early Warning export opens the same thread component",
                  page.locator('[data-testid="ews-whatif-source"]').count() > 0,
                  page.url)
            shot("05-ews-export")
        else:
            check("an Early Warning export opens the same thread component",
                  False, "no export button on the product view")

        print("\npage errors:", errors[:4])
        browser.close()
    print(f"\n{len(passed)} of {len(passed) + len(failed)} checks passed")
    if failed:
        print("failed:", failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
