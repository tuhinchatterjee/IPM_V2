"""The What-If methodology routes, opened. §10.2 and the retail-only boundary.

What this is checking, and why it needed its own suite
-------------------------------------------------------
`/what-if/models/delta` and `/what-if/models/ml` are CORPORATE routes. They
read the corporate registry and they are retired in a retail installation.
One of them was briefly repointed at the retail challenger — which turned a
corporate route into a retail one, broke the boundary that
`TestTheCorporateWhatIfRoutesDoNotServeTheirScreen` holds, and left the
retail challenger reachable only by violating it.

The retail methodologies now live at `/what-if/methods/[method]`, beside
`/what-if/threads/[threadId]`, under the word the retail engine uses. So
there are two things to keep true at once, and a source-level test can check
the first but not the second: the corporate routes stay guarded, AND the
retail pages actually open and carry their content.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright  # noqa: E402

from retail_uat.driver import FRONTEND, Session, chromium_path  # noqa: E402

OUT = "docs/evidence/phase9_method_routes"
os.makedirs(OUT, exist_ok=True)

results: list[tuple[str, str, bool, str]] = []


def check(number: str, name: str, ok: bool, detail: str = "") -> bool:
    results.append((number, name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {number} {name}"
          + (f" — {detail}" if detail else ""), flush=True)
    return ok


def _visible(page, selector: str, seconds: int = 240) -> bool:
    """Wait for the ELEMENT the check is about to read.

    Waiting for a word fails here: "what-if", "corporate" and "retired" are
    all in the navigation chrome, which renders long before the route does.
    The first run of this suite reported six failures that were all the
    harness reading the app shell.
    """
    try:
        page.locator(selector).first.wait_for(state="visible",
                                              timeout=seconds * 1000)
        return True
    except Exception:  # noqa: BLE001
        return False


def _settle(page, marker: str, seconds: int = 180) -> bool:
    for _ in range(seconds):
        page.wait_for_timeout(1000)
        if marker.lower() in page.inner_text("body").lower():
            return True
    return False


def main() -> int:  # noqa: C901
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chromium_path())
        context = browser.new_context(viewport={"width": 1512, "height": 982})
        page = context.new_page()
        session = Session(page, context)
        if not session.sign_in():
            print("could not sign in")
            return 1

        # A — the retail What-If offers the XGBoost card, and it opens the
        # retail page rather than a retired corporate one.
        page.goto(FRONTEND + "/what-if", wait_until="commit")
        _visible(page, '[data-testid="retail-whatif-open-xgboost"]', 240)
        card = page.locator('[data-testid="retail-whatif-open-xgboost"]')
        check("A-01", "the retail What-If offers an XGBoost card",
              card.count() > 0, f"{card.count()} card(s)")
        href = card.first.get_attribute("href") if card.count() else ""
        check("A-02", "the card points at the retail route, not the corporate "
                      "one",
              href == "/what-if/methods/xgboost",
              f"href {href!r}")
        if card.count():
            card.first.click()
            page.wait_for_timeout(4000)
        opened = _visible(page, '[data-testid="challenger-page"]', 240)
        check("A-03", "clicking it opens the retail challenger page",
              opened and "/what-if/methods/xgboost" in page.url, page.url)
        artifact = page.locator('[data-testid="challenger-page"]').count()
        check("A-04", "the challenger page carries its content, not a stub",
              artifact > 0
              and "not part of this" not in page.inner_text("body").lower(),
              f"challenger body present: {artifact > 0}")
        page.screenshot(path=f"{OUT}/A-retail-xgboost.png", full_page=True)

        # Back returns to the What-If screen it came from.
        page.go_back()
        back = _visible(page, '[data-testid="retail-whatif-open-xgboost"]', 240)
        check("A-05", "browser Back returns to the retail What-If screen",
              back and page.url.rstrip("/").endswith("/what-if"), page.url)

        # B — the corporate route stays guarded.
        page.goto(FRONTEND + "/what-if/models/ml", wait_until="commit")
        guarded = _visible(page, '[data-testid="retired-screen"]', 240)
        body = page.inner_text("body").lower()
        check("B-01", "the corporate /what-if/models/ml stays guarded in a "
                      "retail installation",
              guarded and "model card" not in body,
              "retired screen rendered" if guarded
              else "no retired screen: " + body[:80])
        # And it points somewhere useful rather than at a dead end.
        instead = page.locator('a[href="/what-if/methods/xgboost"]')
        check("B-02", "the guarded screen sends the reader to the retail page",
              instead.count() > 0,
              f"{instead.count()} link(s) to the retail route")
        page.screenshot(path=f"{OUT}/B-corporate-guarded.png", full_page=True)

        page.goto(FRONTEND + "/what-if/models/delta", wait_until="commit")
        check("B-03", "the corporate /what-if/models/delta stays guarded too",
              _visible(page, '[data-testid="retired-screen"]', 240),
              "retired screen rendered")

        # C — the Delta methodology page opens on the retail route.
        page.goto(FRONTEND + "/what-if/methods/delta", wait_until="commit")
        opened = _visible(page, '[data-testid="retail-method-other"]', 240)
        check("C-01", "the retail Delta method page opens",
              opened and "calculation of record"
              in page.inner_text("body").lower(),
              page.url)
        page.screenshot(path=f"{OUT}/C-retail-delta.png", full_page=True)

        other = page.locator('[data-testid="retail-method-other"]')
        check("C-02", "each methodology links to the other",
              other.count() > 0,
              f"{other.count()} cross-link(s)")

        bad = [one for one in session.api if one[2] >= 500]
        check("Z-01", "no HTTP 500 across the method routes", not bad,
              "; ".join(f"{m} {p} {s}" for m, p, s in bad[:3]))
        check("Z-02", "no page errors", not session.console_errors,
              "; ".join(session.console_errors[:2]))
        browser.close()

    passed = [one for one in results if one[2]]
    print(f"\n{len(passed)} of {len(results)} checks passed")
    for number, name, ok, detail in results:
        if not ok:
            print(f"  FAILED  {number} {name} — {detail}")
    with open(f"{OUT}/result.json", "w") as handle:
        json.dump({"passed": [f"{n} {t}" for n, t, ok, _ in results if ok],
                   "failed": [{"check": f"{n} {t}", "detail": d}
                              for n, t, ok, d in results if not ok]},
                  handle, indent=2)
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
