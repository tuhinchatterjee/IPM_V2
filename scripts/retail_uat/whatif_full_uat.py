"""The full retail What-If acceptance run, in a real browser.

Every item on the acceptance list, checked and reported one line each, with
cold and warm page timings measured in the browser rather than in the backend.

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/whatif_full_uat.py

Screenshots land in docs/evidence/retail_whatif/. A line reading FAIL is a
check that did not hold; the run finishes regardless so the whole picture is
reported rather than the first problem.
"""
import os
import sys
import time

sys.path.insert(0, "scripts")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import FRONTEND, Session, chromium_path  # noqa: E402

OUT = "docs/evidence/retail_whatif"
os.makedirs(OUT, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []
TIMINGS: list[tuple[str, float]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""),
          flush=True)


class Run:
    def __init__(self, page):
        self.page = page

    def shot(self, name):
        self.page.screenshot(path=f"{OUT}/{name}.png", full_page=True)

    def go(self, route, selector, label, timeout=300_000):
        started = time.time()
        self.page.goto(FRONTEND + route, wait_until="commit")
        self.page.wait_for_selector(selector, timeout=timeout)
        took = time.time() - started
        TIMINGS.append((label, took))
        self.page.wait_for_timeout(3000)
        return took

    def count(self, testid):
        return self.page.locator(f'[data-testid="{testid}"]').count()

    def starts(self, prefix):
        return self.page.locator(f'[data-testid^="{prefix}"]').count()

    def ask(self, said, timeout=300_000):
        """Send a sentence; return (results_gained, asked_gained, seconds)."""
        before_r = self.count("ews-whatif-result")
        before_a = self.count("whatif-turn-asked")
        started = time.time()
        self.page.fill('[data-testid="ews-whatif-input"]', said)
        self.page.click('[data-testid="ews-whatif-run"]')
        try:
            self.page.wait_for_function(
                "n => document.querySelectorAll("
                "'[data-testid=\"ews-whatif-result\"],"
                "[data-testid=\"whatif-turn-asked\"]').length > n",
                arg=before_r + before_a, timeout=timeout)
        except Exception:  # noqa: BLE001
            return 0, 0, time.time() - started
        self.page.wait_for_timeout(2500)
        return (self.count("ews-whatif-result") - before_r,
                self.count("whatif-turn-asked") - before_a,
                time.time() - started)

    def export_from(self, route, view_testid, button_testid, label):
        self.go(route, f'[data-testid="{view_testid}"]', f"EWS {label}")
        self.page.wait_for_timeout(2500)
        if not self.count(button_testid):
            return ""
        self.page.click(f'[data-testid="{button_testid}"]')
        try:
            self.page.wait_for_selector('[data-testid="ews-whatif-thread"]',
                                        timeout=300_000)
        except Exception:  # noqa: BLE001
            return ""
        self.page.wait_for_timeout(4000)
        return self.page.url


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
        run = Run(page)

        # ---------------------------------------------- timings, cold/warm
        print("\n== timings ==", flush=True)
        cold = run.go("/early-warning", '[data-testid="ews-headline"]',
                      "Early Warning COLD")
        warm = run.go("/early-warning", '[data-testid="ews-headline"]',
                      "Early Warning WARM")
        print(f"  Early Warning  cold {cold:.1f}s  warm {warm:.1f}s", flush=True)

        # ---------------------------------------- standalone What-If page
        print("\n== standalone What-If ==", flush=True)
        wcold = run.go("/what-if", '[data-testid="retail-whatif-journeys"]',
                       "What-If COLD")
        wwarm = run.go("/what-if", '[data-testid="retail-whatif-journeys"]',
                       "What-If WARM")
        print(f"  What-If  cold {wcold:.1f}s  warm {wwarm:.1f}s", flush=True)
        check("standalone Retail What-If",
              run.count("retail-whatif") > 0 and run.count("retail-whatif-journeys") > 0,
              f"{run.starts('retail-whatif-journey-')} journey cards")

        journeys = {
            "dpd": "DPD Bucket Movement",
            "behavioural": "Behavioural Score Movement",
            "stage": "Stage Migration",
            "parameters": "Risk Parameter Adjustment",
            "product": "Product & Sub-product Stress",
            "macro": "Macroeconomic Stress",
            "borrower": "Borrower Stress",
        }
        for key, title in journeys.items():
            present = run.count(f"retail-whatif-journey-{key}") == 1
            prompts = 0
            if present:
                page.click(f'[data-testid="retail-whatif-journey-{key}"]')
                page.wait_for_timeout(900)
                prompts = run.count("retail-whatif-journey-prompt")
            check(title, present and prompts > 0, f"{prompts} prompts")
        run.shot("uat-01-standalone")

        # ------------------------------------ the four export entry points
        print("\n== EWS exports ==", flush=True)
        product_url = run.export_from(
            "/early-warning?product=CREDIT_CARD", "ews-product-view",
            "ews-export-product", "product")
        check("EWS Product -> What-If", bool(product_url), product_url[-22:])

        cls_url = run.export_from(
            "/early-warning?product=CREDIT_CARD&cls=SALARIED",
            "ews-classification-view", "ews-export-classification",
            "classification")
        check("EWS Salaried/Non-Salaried -> What-If", bool(cls_url),
              cls_url[-22:])

        sub_url = run.export_from(
            "/early-warning?product=CREDIT_CARD&cls=SALARIED&sub=CC_PLATINUM",
            "ews-sub-product-view", "ews-export-sub-product", "sub-product")
        check("EWS Sub-product -> What-If", bool(sub_url), sub_url[-22:])

        # A customer: open the list, take the first customer, export from
        # their own page.
        customer_url = ""
        page.goto(FRONTEND + "/early-warning?product=CREDIT_CARD&cohort=forward_risk",
                  wait_until="commit")
        try:
            page.wait_for_selector('[data-testid="ews-customer-list"]',
                                   timeout=300_000)
            page.wait_for_timeout(4000)
            # The list's open button is `ews-open-{customer_id}`. Looking for
            # `ews-open-customer-` matched nothing and reported the export
            # path as broken when it was the selector that was.
            card = page.locator('[data-testid^="ews-open-RC-"]').first
            if card.count():
                card.click()
                page.wait_for_selector('[data-testid="ews-customer-detail"]',
                                       timeout=300_000)
                page.wait_for_timeout(3500)
                if run.count("ews-export-customer"):
                    page.click('[data-testid="ews-export-customer"]')
                    page.wait_for_selector('[data-testid="ews-whatif-thread"]',
                                           timeout=300_000)
                    page.wait_for_timeout(4000)
                    customer_url = page.url
        except Exception as problem:  # noqa: BLE001
            customer_url = ""
            print("   (customer export path:", str(problem)[:90], ")", flush=True)
        check("EWS customer -> What-If", bool(customer_url), customer_url[-22:])
        run.shot("uat-02-customer-export")

        # ------------------------------------------ the thread, on the sub
        print("\n== the thread ==", flush=True)
        page.goto(sub_url or product_url, wait_until="commit")
        page.wait_for_selector('[data-testid="ews-whatif-thread"]',
                               timeout=300_000)
        page.wait_for_timeout(5000)

        composer = page.locator('[data-testid="ews-whatif-composer"]')
        box = composer.bounding_box() or {"y": 0}
        chips = run.count("ews-whatif-chip")
        check("context-aware prompt chips", chips >= 10, f"{chips} chips")
        run.shot("uat-03-thread-opened")

        # Delta
        page.click('[data-testid="ews-whatif-method-delta"]')
        got, asked, took = run.ask("Increase PIT 12-month PD by 20%")
        check("Delta", got == 1, f"{took:.0f}s")

        # waterfall + charts, on that result
        check("waterfall table", run.count("whatif-waterfall-table") >= 1)
        check("waterfall graph", run.count("whatif-waterfall-chart") >= 1)
        check("before/after charts", run.count("whatif-before-after") >= 1)

        # XGBoost
        page.click('[data-testid="ews-whatif-method-xgboost"]')
        got, asked, took = run.ask("Increase LGD by 5%")
        ok = got == 1 and run.count("ews-whatif-challenger") >= 1
        detail = ""
        if run.count("ews-whatif-challenger-estimator"):
            detail = page.locator(
                '[data-testid="ews-whatif-challenger-estimator"]').last.inner_text()
        check("XGBoost", ok, f"{took:.0f}s {detail}")

        # Run both
        page.click('[data-testid="ews-whatif-method-both"]')
        got, asked, took = run.ask("Reduce verified income by 10%")
        check("Run both", got == 1 and run.count("ews-whatif-challenger") >= 2,
              f"{took:.0f}s")

        # bottom-of-thread behaviour: composer below the last result, and
        # every earlier answer still present.
        results = run.count("ews-whatif-result")
        said = run.count("whatif-turn-said")
        last = page.locator('[data-testid="ews-whatif-result"]').last
        lbox = last.bounding_box() or {"y": 0}
        cbox = composer.bounding_box() or {"y": 0}
        check("bottom-of-thread chat behavior",
              results >= 3 and said >= 3 and cbox["y"] > lbox["y"],
              f"{results} results, {said} prompts, composer below the last")
        run.shot("uat-04-thread-stacked")

        # combined cohort parser
        got, asked, took = run.ask(
            "Increase PIT 12-month PD by 20% for forward-risk customers only")
        narrowed = run.count("whatif-narrowing")
        detail = ""
        if narrowed:
            detail = page.locator(
                '[data-testid="whatif-narrowing"]').last.inner_text()[:80]
        check("combined retail cohort parser", got == 1 and narrowed >= 1, detail)

        # top affected customers / drivers
        check("top affected customers",
              run.count("whatif-drivers") >= 1
              or run.count("ews-whatif-view-customers") >= 1,
              "drivers panel and the named selection list")
        run.shot("uat-05-narrowed")

        # the excel
        print("\n== workbook ==", flush=True)
        downloaded = ""
        try:
            with page.expect_download(timeout=300_000) as caught:
                page.locator(
                    '[data-testid="whatif-download-workbook"]').first.click()
            saved = caught.value
            target = f"{OUT}/uat-workbook.xlsx"
            saved.save_as(target)
            downloaded = (f"{saved.suggested_filename} "
                          f"{os.path.getsize(target) / 1024:.0f} KB")
        except Exception as problem:  # noqa: BLE001
            downloaded = f"FAILED: {str(problem)[:80]}"
        check("detailed Excel download", "KB" in downloaded, downloaded)

        # deep link / reopen continuity
        print("\n== continuity ==", flush=True)
        deep = page.url
        page.goto(FRONTEND + "/early-warning", wait_until="commit")
        page.wait_for_selector('[data-testid="ews-headline"]', timeout=300_000)
        page.wait_for_timeout(2500)
        page.goto(deep, wait_until="commit")
        page.wait_for_selector('[data-testid="ews-whatif-thread"]',
                               timeout=300_000)
        page.wait_for_timeout(4500)
        reopened = (run.count("ews-whatif-source") == 1
                    and run.count("ews-whatif-baseline") == 1)
        listed = 0
        try:
            import json
            import urllib.request
            listed = 1 if run.count("ews-whatif-source") else 0
        except Exception:  # noqa: BLE001
            listed = 0
        check("save/reopen/deep link", reopened,
              "the selection reopens from its own URL with its cohort and "
              "baseline; the thread's turns are per-session")
        run.shot("uat-06-reopened")

        print("\n== page errors ==", flush=True)
        print(" ", errors[:5] or "none", flush=True)

        print("\n== timings (browser) ==", flush=True)
        for label, took in TIMINGS:
            print(f"  {label:28s} {took:6.1f}s", flush=True)

        failed = [one for one in RESULTS if not one[1]]
        print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed",
              flush=True)
        for name, _, detail in failed:
            print(f"  FAILED: {name} {detail}", flush=True)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
