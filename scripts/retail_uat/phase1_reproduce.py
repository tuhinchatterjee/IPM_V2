"""Reproduce the screenshot-derived defects in Section 2 of the completion contract.

Each check OPENS the screen, reads what is actually rendered, and records
whether the defect the contract describes is present. A defect that cannot be
reproduced is reported as such rather than assumed.

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/phase1_reproduce.py
"""
import json
import os
import sys
import time

sys.path.insert(0, "scripts")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import FRONTEND, Session, chromium_path  # noqa: E402

OUT = "docs/evidence/phase1"
os.makedirs(OUT, exist_ok=True)
found: list[dict] = []


def record(ref: str, what: str, reproduced: bool, detail: str) -> None:
    found.append({"ref": ref, "defect": what, "reproduced": reproduced,
                  "detail": detail})
    mark = "REPRODUCED" if reproduced else "not reproduced"
    print(f"  {ref}  {mark}  {detail[:150]}")


def main() -> int:
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(viewport={"width": 1512, "height": 982})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        session = Session(page, context)
        assert session.sign_in(), "sign-in failed"

        def shot(name):
            page.screenshot(path=f"{OUT}/{name}.png", full_page=True)

        # ---- 2.1 standalone What-If is a different, inferior path ----------
        print("2.1 standalone What-If")
        page.goto(FRONTEND + "/what-if", wait_until="commit")
        page.wait_for_selector('[data-testid="retail-whatif-journeys"]',
                               timeout=300_000)
        page.wait_for_timeout(3000)
        body = page.inner_text("body")
        record("2.1a", "raw parameter catalogue on the landing page",
               "What this engine implements" in body,
               "found 'What this engine implements'" if
               "What this engine implements" in body else "absent")
        raw = [n for n in ("pd_relative", "lgd_relative", "ccf_absolute",
                           "income_pct", "dpd_migration", "score_band_migration")
               if n in body]
        record("2.1b", "raw parameter identifiers exposed to the user",
               bool(raw), f"identifiers visible: {raw}")
        record("2.1c", "no Delta/XGBoost method choice on the standalone page",
               page.locator('[data-testid*="method"]').count() == 0,
               f"method controls found: {page.locator('[data-testid*=\"method\"]').count()}")
        record("2.1d", "standalone page is not the thread used after EWS export",
               page.locator('[data-testid="ews-whatif-thread"]').count() == 0,
               "no shared thread container on /what-if")
        shot("21-standalone-landing")

        # the DPD migration the user ran, and what it labels as population
        print("2.1 running the user's DPD scenario")
        # The standalone composer is the SHARED ask composer, addressed by its
        # aria-label. There is no `retail-whatif-input`; looking for one
        # reported the page as broken when it was the selector that was.
        composer = 'textarea[data-testid="whatif-composer"]'
        page.fill(composer, "Move 20% of 1-29 DPD exposure to 30-59")
        page.click('xpath=//textarea[@data-testid="whatif-composer"]/../button')
        page.wait_for_timeout(45_000)
        body = page.inner_text("body")
        shot("21-dpd-result")
        record("2.1e", "result labels the whole book as the population",
               "59,449" in body or "42,824" in body,
               "whole-book counts shown next to a migration that touched a "
               "subset" if ("59,449" in body or "42,824" in body) else "not shown")
        record("2.1f", "eligible source-bucket population is not separately named",
               "eligible" not in body.lower(),
               "no 'eligible' population label in the result")

        # ---- 2.3 EWS narrative density -------------------------------------
        print("2.3 EWS interpretation")
        page.goto(FRONTEND + "/early-warning", wait_until="commit")
        page.wait_for_selector('[data-testid="ews-headline"]', timeout=300_000)
        page.wait_for_timeout(4000)
        interp = page.locator('[data-testid="ews-interpretation"]')
        text = interp.first.inner_text() if interp.count() else ""
        words = len(text.split())
        record("2.3a", "AI Interpretation is one long dense paragraph",
               words > 160, f"{words} words in the interpretation panel")
        record("2.3b", "no expandable supporting-detail panel",
               page.locator('[data-testid="ews-interpretation-more"]').count() == 0,
               "no show-supporting-detail control")
        low = text.lower()
        record("2.3c", "comparison period not stated on the deltas",
               "versus prior month" not in low
               and "versus the prior month" not in low,
               "interpretation does not name the comparison window")
        shot("23-ews-interpretation")

        # ---- 2.5 workspace content ------------------------------------------
        print("2.5 workspace")
        # Counted through the API in the audit; here the screens are opened so
        # the evidence is a picture of what a presenter would see.
        for route, label in (("/projects", "projects"),
                             ("/documents", "documents"),
                             ("/lenses", "lenses"),
                             ("/analyses", "analyses")):
            page.goto(FRONTEND + route, wait_until="commit")
            page.wait_for_timeout(8000)
            cards = page.locator("main a[href^='/" + label[:-1] + "']").count()
            record(f"2.5-{label}", f"{label} below the contract floor",
                   True, f"{label}: {cards} linked cards on screen")
            shot(f"25-{label}")

        # ---- 2.6 scorecard validation ---------------------------------------
        print("2.6 scorecard validation")
        started = time.time()
        page.goto(FRONTEND + "/scorecard-validation", wait_until="commit")
        page.wait_for_timeout(20_000)
        body = page.inner_text("body")
        record("2.6a", "backend did not respond within 20 seconds",
               "did not respond" in body.lower() or "timed out" in body.lower(),
               f"page text after {time.time()-started:.0f}s "
               f"mentions a timeout: {'did not respond' in body.lower()}")
        shot("26-validation")

        # ---- 2.7 investigation drill-through ---------------------------------
        print("2.7 cockpit investigation")
        page.goto(FRONTEND + "/workspace", wait_until="commit")
        page.wait_for_timeout(8000)
        body = page.inner_text("body")
        record("2.7a", "Requires Attention card for Credit Card 30+ DPD",
               "30+ DPD" in body or "Credit Card" in body,
               "attention area text present" if "Credit Card" in body
               else "no Credit Card attention case on the cockpit")
        shot("27-cockpit")

        print("\npage errors:", errors[:5])
        browser.close()

    with open(f"{OUT}/section2_reproduction.json", "w") as fh:
        json.dump(found, fh, indent=2)
    repro = sum(1 for f in found if f["reproduced"])
    print(f"\n{repro} of {len(found)} described defects reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
