"""§14 in a browser: the race, the progress, the stop, the category names.

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/phase6_validation.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import FRONTEND, Session, chromium_path  # noqa: E402

OUT = "docs/evidence/phase6"
os.makedirs(OUT, exist_ok=True)

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
        context = browser.new_context(viewport={"width": 1512, "height": 982})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        session = Session(page, context)
        assert session.sign_in(), "sign-in failed"

        print("\n1. the page opens without running anything")
        started = time.time()
        page.goto(FRONTEND + "/scorecard-validation", wait_until="commit")
        page.wait_for_selector("text=Scorecard Validation", timeout=300_000)
        page.wait_for_timeout(4000)
        check("the validation page opens", True, f"{time.time()-started:.1f}s")
        page.screenshot(path=f"{OUT}/01-opened.png", full_page=True)

        cards = page.locator("button:has-text('Data & Representativeness')")
        # Waited for rather than sampled. A fixed pause samples whatever the
        # dev server happened to have compiled by then and reports "0
        # matching" on a page that renders the cards a second later, which
        # is a statement about the sampling instant.
        try:
            cards.first.wait_for(state="visible", timeout=60_000)
        except Exception:  # noqa: BLE001 - the count below is the verdict
            pass
        check("the category cards are present", cards.count() > 0,
              f"{cards.count()} matching")

        print("\n2. a category runs as a job, with progress")
        began = time.time()
        cards.first.click()
        page.wait_for_selector('[data-testid="scv-progress"]', timeout=120_000)
        showed = time.time() - began
        check("progress appears promptly", showed < 10.0, f"{showed:.1f}s")
        check("a Stop control is offered while it runs",
              page.locator('[data-testid="scv-stop"]').count() > 0)
        seen = set()
        for _ in range(40):
            page.wait_for_timeout(1000)
            node = page.locator('[data-testid="scv-progress-count"]')
            if node.count():
                seen.add(node.first.inner_text())
            if page.locator('[data-testid="scv-stop"]').count() == 0:
                break
        check("progress advanced through several counts", len(seen) >= 3,
              f"{len(seen)} distinct readings")
        page.screenshot(path=f"{OUT}/02-progress.png", full_page=True)

        print("\n3. the race: slow category, then fast one")
        # Data & Representativeness is the slowest; Champion vs Challenger is
        # the fastest. Clicking the first then the second used to paint the
        # challenger results and then overwrite them with the data results,
        # under the heading the reader chose last.
        page.reload(wait_until="commit")
        page.wait_for_selector("text=Scorecard Validation", timeout=300_000)
        page.wait_for_timeout(3000)
        page.locator("button:has-text('Data & Representativeness')").first.click()
        page.wait_for_timeout(700)
        challenger = page.locator("button:has-text('Champion vs Challenger')")
        if not challenger.count():
            check("the challenger card is present", False, "not found")
        else:
            challenger.first.click()
            page.wait_for_timeout(1500)
            # Let the SLOW one finish; if the guard works it can never write.
            for _ in range(45):
                page.wait_for_timeout(1000)
                if page.locator('[data-testid="scv-stop"]').count() == 0:
                    break
            page.wait_for_timeout(2500)
            node = page.locator('[data-testid="scv-progress"]')
            heading = node.first.inner_text() if node.count() else ""
            check("the finished run is the one clicked LAST",
                  "champion" in heading.lower(),
                  heading.split("\n")[0][:70])
            body = page.inner_text("body")
            check("no data-quality test id is on screen under the "
                  "challenger heading",
                  "DATA-ROWS" not in body and "DATA-MISSING" not in body,
                  "found a DATA- test" if "DATA-ROWS" in body else "")
        page.screenshot(path=f"{OUT}/03-race.png", full_page=True)

        print("\n4. stopping a run")
        page.reload(wait_until="commit")
        page.wait_for_selector("text=Scorecard Validation", timeout=300_000)
        page.wait_for_timeout(3000)
        page.click("button:has-text('Run full validation')")
        page.wait_for_selector('[data-testid="scv-stop"]', timeout=120_000)
        page.wait_for_timeout(6000)
        page.click('[data-testid="scv-stop"]')
        for _ in range(30):
            page.wait_for_timeout(1000)
            if page.locator('[data-testid="scv-stop"]').count() == 0:
                break
        body = page.inner_text("body")
        check("a stopped run says so and keeps what it measured",
              "Stopped after" in body, body[body.find("Stopped after"):][:80]
              if "Stopped after" in body else "no stop message")
        page.screenshot(path=f"{OUT}/04-stopped.png", full_page=True)

        print("\n5. §15: commenting on a result, and what survives")
        page.reload(wait_until="commit")
        page.wait_for_selector("text=Scorecard Validation", timeout=300_000)
        page.wait_for_timeout(3000)
        page.locator("button:has-text('Calibration')").first.click()
        # Wait for the run to finish so there are results to comment on.
        for _ in range(90):
            page.wait_for_timeout(1000)
            if page.locator('[data-testid="scv-stop"]').count() == 0:
                break
        page.wait_for_timeout(1500)
        cards = page.locator("button:has-text('Evidence')")
        check("the results workspace offers evidence to comment on",
              cards.count() > 0, f"{cards.count()} cards")
        if cards.count():
            cards.first.click()
            page.wait_for_timeout(700)
            add = page.locator('[data-testid="scv-add-comment"]')
            check("every piece of evidence offers Add Comment",
                  add.count() > 0, f"{add.count()} controls")
            add.first.click()
            page.wait_for_timeout(400)
            said = f"UAT-{int(time.time())}"
            page.locator('[data-testid="scv-comment-body"]').first.fill(
                f"{said}: the level gap predates this book; recalibration "
                "should be dated rather than treated as drift.")
            page.locator(
                '[data-testid="scv-comment-assessment"]').first.select_option(
                    "DISAGREED")
            # A severity of the author's own, which §15 requires to be
            # rendered as theirs rather than as the engine's verdict.
            page.locator("select").nth(2).select_option("CRITICAL")
            page.locator('[data-testid="scv-comment-save"]').first.click()
            page.wait_for_timeout(2500)
            # Lowercased before matching: the assessment chip is uppercased
            # by CSS, and `inner_text` returns what is RENDERED, so a
            # case-sensitive check compares the DOM's "Disagreed" against
            # the screen's "DISAGREED" and reports a defect that is not one.
            body = page.inner_text("body").lower()
            check("the comment is on screen with its assessment",
                  said.lower() in body and "disagreed" in body,
                  "saved" if said.lower() in body else "not shown")
            check("the author's severity is labelled as theirs, not the "
                  "engine's",
                  "author\u2019s severity critical" in body
                  or "author's severity critical" in body,
                  "labelled" if "severity critical" in body else "unlabelled")

            # §15: survives a refresh.
            page.reload(wait_until="commit")
            page.wait_for_selector("text=Scorecard Validation",
                                   timeout=300_000)
            page.wait_for_timeout(4000)
            drawer = page.locator('[data-testid="scv-notes-drawer"]')
            check("the findings and notes drawer is present",
                  drawer.count() > 0)
            if drawer.count():
                drawer.first.click()
                page.wait_for_timeout(1200)
            after = page.inner_text("body")
            check("the comment survives a refresh", said in after,
                  "still there" if said in after else "gone after reload")
            check("an overall validation conclusion is offered",
                  page.locator('[data-testid="scv-conclusion"]').count() > 0)
        page.screenshot(path=f"{OUT}/05-comments.png", full_page=True)

        print("\npage errors:", errors[:4])
        browser.close()

    print(f"\n{len(passed)} of {len(passed) + len(failed)} checks passed")
    for name, detail in failed:
        print(f"  FAILED  {name} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
